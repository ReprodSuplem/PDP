# pdp_mip.py

from pdp_ins_gen import PDP_reform
from pdp_utils import PDP_utils 
import os
import time
import gurobipy as gp
from gurobipy import GRB

class PDP_MIP(PDP_reform):
    def __init__(self, pdpName, num_reqs, num_vehs, capacity, knn, increment=None, bc_strategy='hybrid'):
        super().__init__(pdpName, num_reqs, num_vehs, capacity, knn, increment)
        self.knn = int(knn)
        
        # Valid strategies: 'hybrid' (MTZ + Lazy Capacity) or 'full' (Pure Lazy Constraints)
        self.bc_strategy = bc_strategy.lower()
        
        self.env = gp.Env(empty=True)
        self.env.setParam("OutputFlag", 1)
        self.env.start()
        
        # Semantic model naming for academic rigorousness
        self.model_name = f"pdp_{pdpName}_r{num_reqs}v{num_vehs}k{knn}_{self.bc_strategy}_bc"
        self.m = gp.Model(self.model_name, env=self.env)
        self.insName = self.model_name
        
        # Enable Lazy Constraints (Required for both strategies)
        self.m.Params.LazyConstraints = 1

        self.x = {}
        self.y = {}
        self.u = {} 
        self.DEPOT = self.lenOfLocation

    def genGurobiModel(self):
        self.genXVarList()
        self.genYVarList()
        
        if self.bc_strategy == 'hybrid':
            self.genUVarList()

        num_nodes = 1 + self.lenOfLocation
        num_reqs = self.lenOfRequest
        num_vehs = self.lenOfVehicle
        n = self.lenOfLocation

        # ==================== Variable Declaration ====================
        for t in range(num_vehs):
            for r in range(num_reqs):
                var_id = self.yVarList[r][t]
                self.y[r, t] = self.m.addVar(vtype=GRB.BINARY, name=f"y{var_id}")
            
            for i in range(num_nodes):
                if self.bc_strategy == 'hybrid' and i < self.lenOfLocation:
                    u_id = self.uVarList[t][i]
                    # Continuous relaxation for MTZ yields identical integer bounds but solves much faster
                    self.u[t, i] = self.m.addVar(lb=0, ub=n-1, vtype=GRB.CONTINUOUS, name=f"u{u_id}")
                
                for j in range(num_nodes):
                    if i != j and self.adjMatrx[i][j] != 0:
                        var_id = self.xVarList[t][i][j]
                        self.x[t, i, j] = self.m.addVar(vtype=GRB.BINARY, name=f"x{var_id}")

        # ==================== Objective Function ====================
        
        # Eq.1: Minimize Total Routing Cost
        obj_expr = gp.LinExpr()
        for t, i, j in self.x.keys():
            cost = self.my_round_int(self.vehicleList[t][1] * self.locaList[i][j])
            obj_expr += cost * self.x[t, i, j]
                
        self.m.setObjective(obj_expr, GRB.MINIMIZE)

        # ==================== Base Constraints ====================
        
        # Eq.2: Mandatory Request Assignment (Exactly-One)
        for r in range(num_reqs):
            self.m.addConstr(gp.quicksum(self.y[r, t] for t in range(num_vehs)) == 1)

        # Eq.3 & Eq.4: Node Visitation Linkage
        for r in range(num_reqs):
            pickup = self.requestList[r][1]
            dropoff = self.requestList[r][2]
            for t in range(num_vehs):
                self.m.addConstr(gp.quicksum(self.x[t, k, pickup] for k in range(num_nodes) if (t, k, pickup) in self.x) >= self.y[r, t])
                self.m.addConstr(gp.quicksum(self.x[t, k, dropoff] for k in range(num_nodes) if (t, k, dropoff) in self.x) >= self.y[r, t])

        # Eq.5 & Eq.6: Flow Balance and Degree Constraints
        for t in range(num_vehs):
            for j in range(num_nodes):
                in_edges = [self.x[t, i, j] for i in range(num_nodes) if (t, i, j) in self.x]
                out_edges = [self.x[t, j, k] for k in range(num_nodes) if (t, j, k) in self.x]
                self.m.addConstr(gp.quicksum(in_edges) == gp.quicksum(out_edges))
                self.m.addConstr(gp.quicksum(out_edges) <= 1)

        # ==================== Strategy-Specific Topologies ====================
        if self.bc_strategy == 'hybrid':
            # Eq.7: MTZ Subtour Elimination 
            for t in range(num_vehs):
                for j in range(self.lenOfLocation):
                    for k in range(self.lenOfLocation):
                        if j != k and (t, j, k) in self.x:
                            self.m.addConstr(self.u[t, j] - self.u[t, k] + n * self.x[t, j, k] <= n - 1)

            # Eq.8: Physical Precedence Constraints
            for r in range(num_reqs):
                pickup = self.requestList[r][1]
                dropoff = self.requestList[r][2]
                if pickup != dropoff:
                    for t in range(num_vehs):
                        self.m.addConstr(self.u[t, pickup] - self.u[t, dropoff] + n * self.y[r, t] <= n - 1)

        # ==================== Model Enhancements (Valid Inequalities) ====================
        
        # Symmetry Breaking for Homogeneous Fleet
        for t in range(1, num_vehs):
            for r in range(num_reqs):
                self.m.addConstr(self.y[r, t] <= gp.quicksum(self.y[prev_r, t-1] for prev_r in range(r)))

        # Active Vehicle Pruning (EVP)
        for t in range(num_vehs):
            vehicle_is_active = gp.quicksum(self.y[r, t] for r in range(num_reqs))
            for i in range(num_nodes):
                for j in range(num_nodes):
                    if (t, i, j) in self.x:
                        self.m.addConstr(self.x[t, i, j] <= vehicle_is_active)

        # ==================== Metadata for Callbacks ====================
        self.m._x = self.x
        self.m._y = self.y
        self.m._DEPOT = self.DEPOT
        self.m._num_vehs = num_vehs
        self.m._num_reqs = num_reqs
        self.m._cap = int(self.vehicleList[0][0])
        self.m._demand = {r: self.requestList[r][0] for r in range(num_reqs)}
        self.m._pickup = {r: self.requestList[r][1] for r in range(num_reqs)}
        self.m._dropoff = {r: self.requestList[r][2] for r in range(num_reqs)}


    # ==========================================
    # Callback Route 1: Hybrid Strategy (Eq.9: Capacity Lazy Evaluation Only)
    # ==========================================
    @staticmethod
    def hybrid_benders_callback(model, where):
        if where == GRB.Callback.MIPSOL:
            x_vals = model.cbGetSolution(model._x)
            y_vals = model.cbGetSolution(model._y)

            for t in range(model._num_vehs):
                edges = [(i, j) for (veh, i, j), val in x_vals.items() if veh == t and val > 0.5]
                if not edges: continue

                adj = {u: v for u, v in edges}
                if model._DEPOT not in adj: continue
                
                route_edges = []
                curr = model._DEPOT
                while curr in adj:
                    nxt = adj[curr]
                    route_edges.append((curr, nxt))
                    curr = nxt
                    if curr == model._DEPOT: break

                assigned_reqs = [r for r in range(model._num_reqs) if y_vals[r, t] > 0.5]
                load = 0
                onboard = set()
                
                for k, (u, v) in enumerate(route_edges):
                    for r in assigned_reqs:
                        pk = model._pickup[r]
                        dp = model._dropoff[r]
                        if pk == dp and v == dp:
                            pass
                        elif v == pk:
                            load += model._demand[r]
                            onboard.add(r)
                        elif v == dp and r in onboard:
                            load -= model._demand[r]
                            onboard.remove(r)

                    if load > model._cap:
                        # Greedy reduction for Minimal Conflict Set (MCS)
                        onboard_list = list(onboard)
                        onboard_list.sort(key=lambda r: model._demand[r], reverse=True)

                        conflict_core = []
                        core_load = 0
                        for r in onboard_list:
                            core_load += model._demand[r]
                            conflict_core.append(r)
                            if core_load > model._cap: break

                        prefix_edges = route_edges[:k+1]
                        rhs_bound = len(prefix_edges) + len(conflict_core) - 1

                        # Broadcast Combinatorial Cut
                        for veh_id in range(model._num_vehs):
                            cut_expr = gp.quicksum(model._x[veh_id, src, tgt] for src, tgt in prefix_edges if (veh_id, src, tgt) in model._x)
                            cut_expr += gp.quicksum(model._y[r, veh_id] for r in conflict_core)
                            model.cbLazy(cut_expr <= rhs_bound)
                            
                        break

    # ==========================================
    # Callback Route 2: Full Strategy (Eq.7 & Eq.8 & Eq.9 Lazy Evaluation)
    # ==========================================
    @staticmethod
    def full_benders_callback(model, where):
        if where == GRB.Callback.MIPSOL:
            x_vals = model.cbGetSolution(model._x)
            y_vals = model.cbGetSolution(model._y)

            for t in range(model._num_vehs):
                edges = [(i, j) for (veh, i, j), val in x_vals.items() if veh == t and val > 0.5]
                if not edges: continue

                adj = {u: v for u, v in edges}

                # Stage 1: DFJ Subtour Elimination (Mapping to Eq.7)
                visited = set()
                has_subtour = False
                for u, v in edges:
                    if u not in visited:
                        curr = u
                        cycle = []
                        while True:
                            visited.add(curr)
                            cycle.append(curr)
                            if curr not in adj: break
                            nxt = adj[curr]
                            
                            if nxt == u:
                                if model._DEPOT not in cycle:
                                    S = cycle
                                    for veh_id in range(model._num_vehs):
                                        cut_expr = gp.quicksum(model._x[veh_id, src, tgt] for src in S for tgt in S if (veh_id, src, tgt) in model._x)
                                        model.cbLazy(cut_expr <= len(S) - 1)
                                    has_subtour = True
                                break
                            
                            if nxt in visited: break
                            curr = nxt
                
                if has_subtour: continue 

                # Stage 2: Infeasible Path Cuts (Mapping to Eq.8)
                if model._DEPOT not in adj: continue
                
                route_edges = []
                curr = model._DEPOT
                while curr in adj:
                    nxt = adj[curr]
                    route_edges.append((curr, nxt))
                    curr = nxt
                    if curr == model._DEPOT: break

                assigned_reqs = [r for r in range(model._num_reqs) if y_vals[r, t] > 0.5]
                
                seen_nodes = set([model._DEPOT])
                has_precedence_violation = False
                
                for k, (u, v) in enumerate(route_edges):
                    seen_nodes.add(v)
                    for r in assigned_reqs:
                        pk = model._pickup[r]
                        dp = model._dropoff[r]
                        if pk != dp and v == dp and pk not in seen_nodes:
                            prefix_edges = route_edges[:k+1]
                            rhs_bound = len(prefix_edges)
                            for veh_id in range(model._num_vehs):
                                cut_expr = gp.quicksum(model._x[veh_id, src, tgt] for src, tgt in prefix_edges if (veh_id, src, tgt) in model._x)
                                cut_expr += model._y[r, veh_id]
                                model.cbLazy(cut_expr <= rhs_bound)
                            has_precedence_violation = True
                            break
                    if has_precedence_violation: break
                
                if has_precedence_violation: continue

                # Stage 3: Combinatorial Benders Cuts (Mapping to Eq.9)
                load = 0
                onboard = set()
                for k, (u, v) in enumerate(route_edges):
                    for r in assigned_reqs:
                        pk = model._pickup[r]
                        dp = model._dropoff[r]
                        if pk == dp and v == dp: pass
                        elif v == pk:
                            load += model._demand[r]
                            onboard.add(r)
                        elif v == dp and r in onboard:
                            load -= model._demand[r]
                            onboard.remove(r)

                    if load > model._cap:
                        onboard_list = list(onboard)
                        onboard_list.sort(key=lambda r: model._demand[r], reverse=True)
                        conflict_core = []
                        core_load = 0
                        for r in onboard_list:
                            core_load += model._demand[r]
                            conflict_core.append(r)
                            if core_load > model._cap: break

                        prefix_edges = route_edges[:k+1]
                        rhs_bound = len(prefix_edges) + len(conflict_core) - 1

                        for veh_id in range(model._num_vehs):
                            cut_expr = gp.quicksum(model._x[veh_id, src, tgt] for src, tgt in prefix_edges if (veh_id, src, tgt) in model._x)
                            cut_expr += gp.quicksum(model._y[r, veh_id] for r in conflict_core)
                            model.cbLazy(cut_expr <= rhs_bound)
                        break

    def solve(self, time_limit=3600, assumption_file=None):
        self.genGurobiModel()
        
        if time_limit is not None:
            print(f"[Gurobi {self.bc_strategy}_bc] Setting time limit to {time_limit} seconds")
            self.m.setParam('TimeLimit', time_limit)
            
        self.m.setParam('Threads', 1) 

        log_file = f"{self.insName}.out"
        with open(log_file, "w") as f:
            def log(msg):
                print(msg)
                f.write(msg + "\n")
                f.flush()
                
            start_time = time.time()
            
            self.best_incumbent_obj = float('inf')

            def combined_callback(model, where):
                if where == gp.GRB.Callback.MIPSOL:
                    obj = model.cbGet(gp.GRB.Callback.MIPSOL_OBJ)
                    bnd = model.cbGet(gp.GRB.Callback.MIPSOL_OBJBND)
                    runtime = model.cbGet(gp.GRB.Callback.RUNTIME)
                
                if obj < self.best_incumbent_obj:
                    self.best_incumbent_obj = obj
                    
                    gap_str = "N/A"
                    if abs(obj) > 1e-5: 
                        gap = abs(obj - bnd) / abs(obj) * 100.0
                        gap_str = f"{gap:.2f}%"
                        
                    with open(log_file, "a") as cb_f:
                        cb_f.write(f"[Incumbent] Time: {runtime:.2f}s | Obj: {obj:.1f} | Bound: {bnd:.1f} | Gap: {gap_str}\n")
                            
                # Route execution based on the chosen Benders strategy
                if self.bc_strategy == 'hybrid':
                    self.hybrid_benders_callback(model, where)
                elif self.bc_strategy == 'full':
                    self.full_benders_callback(model, where)

            # Callback Routing based on strategy using the combined callback
            self.m.optimize(combined_callback)
            
            elapsed = time.time() - start_time

            if self.m.Status == gp.GRB.OPTIMAL or self.m.Status == gp.GRB.TIME_LIMIT:
                if self.m.SolCount > 0:
                    raw_model = [v.VarName for v in self.m.getVars() if v.X > 0.5 and (v.VarName.startswith('x') or v.VarName.startswith('y'))]
                    filtered_model = PDP_utils.convert_model(raw_model)

                    log(f"[Gurobi {self.bc_strategy}] Status: {self.m.Status}")
                    log(f"[Gurobi {self.bc_strategy}] BEST OBJ: {self.m.ObjVal}")
                    log(f"[Gurobi {self.bc_strategy}] BEST BOUND: {self.m.ObjBound}")
                    log(f"[Gurobi {self.bc_strategy}] Runtime: {elapsed:.3f} sec")
                    
                    PDP_utils.printVehRoutes(self, filtered_model, log_file)
                    PDP_utils.evaluateSolution(self, filtered_model, log_file)
                    return filtered_model
                else:
                    log(f"[Gurobi {self.bc_strategy}] Reached Time Limit, NO feasible solution.")
                    try:
                        best_bound = self.m.ObjBound
                        log(f"Best objective -, best bound {best_bound}")
                    except:
                        pass
            else:
                log(f"[Gurobi {self.bc_strategy}] Failed to find solution. Status: {self.m.Status}")
            return None
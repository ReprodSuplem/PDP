# ppdsp_mip.py

import os
import time
import gurobipy as gp
from gurobipy import GRB
from ppdsp_ins_gen import PPDSP_reform
from ppdsp_utils import PPDSP_utils

class PPDSP_MIP(PPDSP_reform):
    def __init__(self, pdpName, num_reqs, num_vehs, capacity, knn, increment=None, bc_strategy='hybrid'):
        super().__init__(pdpName, num_reqs, num_vehs, capacity, knn, increment)
        self.bc_strategy = bc_strategy.lower()
        
        self.env = gp.Env(empty=True)
        self.env.setParam("OutputFlag", 1)
        self.env.start()
        self.model = gp.Model(f"PPDSP_{pdpName}", env=self.env)
        
        self.insName = f"ppdsp_{pdpName}_r{num_reqs}v{num_vehs}k{knn}_{self.bc_strategy}_bc"
        
        self.y = {} 
        self.x = {} 
        self.u = {} 
        
    def genMipModel(self):
        self.genXVarList()
        self.genYVarList()

        num_nodes = 1 + self.lenOfLocation
        DEPOT = self.lenOfLocation
        num_reqs = self.lenOfRequest
        num_vehs = self.lenOfVehicle

        # ==================== Variable Declaration ====================
        for t in range(num_vehs):
            for r in range(num_reqs):
                self.y[r, t] = self.model.addVar(vtype=GRB.BINARY, name=f"y_r{r}_t{t}")
                
            for i in range(num_nodes):
                if self.bc_strategy == 'hybrid':
                    self.u[t, i] = self.model.addVar(lb=0, ub=num_nodes, vtype=GRB.CONTINUOUS, name=f"u_t{t}_i{i}")
                    
                for j in range(num_nodes):
                    if i == j:
                        self.x[t, i, i] = self.model.addVar(vtype=GRB.BINARY, name=f"x_t{t}_i{i}_j{i}")
                    elif self.adjMatrx[i][j] != 0:
                        self.x[t, i, j] = self.model.addVar(vtype=GRB.BINARY, name=f"x_t{t}_i{i}_j{j}")
                    else:
                        self.x[t, i, j] = None

        self.model.update()

        # ==================== PPDSP Objective Function ====================
        obj_expr = gp.LinExpr()
        
        # 1. Collected Profit
        for r in range(num_reqs):
            profit = self.requestList[r][0]
            for t in range(num_vehs):
                obj_expr.addTerms(profit, self.y[r, t])
                
        # 2. Routing Cost
        for t in range(num_vehs):
            veh_cost = self.vehicleList[t][1]
            for i in range(num_nodes):
                for j in range(num_nodes):
                    if i != j and self.x[t, i, j] is not None:
                        cost = self.my_round_int(veh_cost * self.locaList[i][j])
                        obj_expr.addTerms(-cost, self.x[t, i, j])

        self.model.setObjective(obj_expr, GRB.MAXIMIZE)

        # ==================== Base Constraints ====================
        
        # PPDSP Eq.2: Optional Request Assignment (At-Most-One for Selection)
        for r in range(num_reqs):
            self.model.addConstr(gp.quicksum(self.y[r, t] for t in range(num_vehs)) <= 1, name=f"c2_r{r}")

        # Node Activation & Flow Constraints
        for t in range(num_vehs):
            is_used = self.model.addVar(vtype=GRB.BINARY, name=f"is_used_t{t}")
            for r in range(num_reqs):
                self.model.addConstr(is_used >= self.y[r, t])
            self.model.addConstr(self.x[t, DEPOT, DEPOT] == 1 - is_used)

            for i in range(num_nodes):
                if i != DEPOT:
                    reqs_pickup = [r for r in range(num_reqs) if self.requestList[r][2] == i]
                    reqs_delivery = [r for r in range(num_reqs) if self.requestList[r][3] == i]
                    
                    is_active_i = gp.quicksum(self.y[r, t] for r in reqs_pickup) + gp.quicksum(self.y[r, t] for r in reqs_delivery)
                    
                    in_flow = gp.quicksum(self.x[t, j, i] for j in range(num_nodes) if i != j and self.x[t, j, i] is not None)
                    out_flow = gp.quicksum(self.x[t, i, j] for j in range(num_nodes) if i != j and self.x[t, i, j] is not None)
                    
                    self.model.addConstr(in_flow == is_active_i, name=f"c3_in_t{t}_i{i}")
                    self.model.addConstr(out_flow == is_active_i, name=f"c4_out_t{t}_i{i}")
                    self.model.addConstr(self.x[t, i, i] == 1 - is_active_i, name=f"c5_self_t{t}_i{i}")

            depot_in = gp.quicksum(self.x[t, j, DEPOT] for j in range(num_nodes) if DEPOT != j and self.x[t, j, DEPOT] is not None)
            depot_out = gp.quicksum(self.x[t, DEPOT, j] for j in range(num_nodes) if DEPOT != j and self.x[t, DEPOT, j] is not None)
            
            self.model.addConstr(depot_out == is_used, name=f"c6_depot_out_t{t}")
            self.model.addConstr(depot_in == is_used, name=f"c7_depot_in_t{t}")

        # MTZ Valid Inequalities (Hybrid mode only)
        if self.bc_strategy == 'hybrid':
            for t in range(num_vehs):
                self.model.addConstr(self.u[t, DEPOT] == 0)
                for i in range(num_nodes):
                    for j in range(num_nodes):
                        if i != j and j != DEPOT and self.x[t, i, j] is not None:
                            self.model.addConstr(
                                self.u[t, i] - self.u[t, j] + 1 <= num_nodes * (1 - self.x[t, i, j]),
                                name=f"mtz_t{t}_i{i}_j{j}"
                            )
                
                # Physical Precedence Constraint
                for r in range(num_reqs):
                    p_node = self.requestList[r][2]
                    d_node = self.requestList[r][3]
                    if p_node != d_node:
                        self.model.addConstr(
                            self.u[t, p_node] <= self.u[t, d_node] - 1 + num_nodes * (1 - self.y[r, t]),
                            name=f"prec_t{t}_r{r}"
                        )

        # Symmetry Breaking
        for t in range(1, num_vehs):
            for r in range(num_reqs):
                self.model.addConstr(
                    self.y[r, t] <= gp.quicksum(self.y[prev_r, t-1] for prev_r in range(r)),
                    name=f"sym_r{r}_t{t}"
                )

    # ==================== Benders Cut Lazy Callback ====================
    @staticmethod
    def benders_callback(model, where):
        if where != GRB.Callback.MIPSOL:
            return

        num_nodes = 1 + model._inst.lenOfLocation
        DEPOT = model._inst.lenOfLocation
        num_reqs = model._inst.lenOfRequest
        num_vehs = model._inst.lenOfVehicle

        for v in range(num_vehs):
            edges = []
            for i in range(num_nodes):
                for j in range(num_nodes):
                    if i != j and model._vars['x'][v, i, j] is not None:
                        val = model.cbGetSolution(model._vars['x'][v, i, j])
                        if val > 0.5:
                            edges.append((i, j))
            
            if not edges:
                continue

            # 1. Subtour & Precedence Verification
            next_node = {i: j for i, j in edges}
            route = []
            current = DEPOT
            
            if current in next_node:
                while current in next_node:
                    nxt = next_node[current]
                    route.append((current, nxt))
                    current = nxt
                    if current == DEPOT:
                        break

            if len(route) < len(edges) or (route and route[-1][1] != DEPOT):
                visited = set([i for i, j in route])
                unvisited_edges = [(i, j) for i, j in edges if i not in visited]
                
                if unvisited_edges:
                    subtour_nodes = set()
                    curr_edge = unvisited_edges[0]
                    subtour_edges = []
                    
                    temp_next = {i: j for i, j in unvisited_edges}
                    curr = curr_edge[0]
                    
                    while curr in temp_next and curr not in subtour_nodes:
                        subtour_nodes.add(curr)
                        nxt = temp_next[curr]
                        subtour_edges.append((curr, nxt))
                        curr = nxt
                        
                    if subtour_edges:
                        S = list(subtour_nodes)
                        cut_expr = gp.quicksum(model._vars['x'][v, i, j] 
                                               for i in S for j in S 
                                               if i != j and model._vars['x'][v, i, j] is not None)
                        model.cbLazy(cut_expr <= len(S) - 1)
                        continue 

            # Full mode specific: Precedence check
            if model._bc_strategy == 'full':
                pos_map = {}
                for idx, (orig, dest) in enumerate(route):
                    pos_map[dest] = idx
                    
                assigned_reqs = [r for r in range(num_reqs) if model.cbGetSolution(model._vars['y'][r, v]) > 0.5]
                prec_violated = False
                
                for r in assigned_reqs:
                    p_node = model._inst.requestList[r][2]
                    d_node = model._inst.requestList[r][3]
                    
                    if p_node in pos_map and d_node in pos_map:
                        if pos_map[p_node] >= pos_map[d_node]:
                            p_idx = pos_map[p_node]
                            d_idx = pos_map[d_node]
                            
                            cycle_nodes = [route[i][0] for i in range(d_idx+1, p_idx+1)]
                            cycle_nodes.append(p_node)
                            
                            cut_expr = gp.quicksum(model._vars['x'][v, i, j] 
                                                   for i in cycle_nodes for j in cycle_nodes 
                                                   if i != j and model._vars['x'][v, i, j] is not None)
                            model.cbLazy(cut_expr <= len(cycle_nodes) - 1)
                            prec_violated = True
                            break
                            
                if prec_violated:
                    continue

            # 2. Capacity Check
            assigned_reqs = [r for r in range(num_reqs) if model.cbGetSolution(model._vars['y'][r, v]) > 0.5]
            if route and assigned_reqs:
                cap = model._inst.vehicleList[v][0]
                load = 0
                onboard = set()
                violated = False
                
                for k, (orig, dest) in enumerate(route):
                    for r in assigned_reqs:
                        if dest == model._inst.requestList[r][2] and dest == model._inst.requestList[r][3]:
                            continue
                        elif dest == model._inst.requestList[r][2]:
                            load += model._inst.requestList[r][1]
                            onboard.add(r)
                        elif dest == model._inst.requestList[r][3] and r in onboard:
                            load -= model._inst.requestList[r][1]
                            onboard.remove(r)
                            
                    if load > cap:
                        violated = True
                        onboard_reqs = list(onboard)
                        onboard_reqs.sort(key=lambda req: model._inst.requestList[req][1], reverse=True)
                        
                        minimal_conflict = []
                        current_subset_load = 0
                        for req in onboard_reqs:
                            current_subset_load += model._inst.requestList[req][1]
                            minimal_conflict.append(req)
                            if current_subset_load > cap:
                                break
                                
                        y_lits = [model._vars['y'][req, v] for req in minimal_conflict]
                        prefix_origins = [route[i][0] for i in range(k + 1)]
                        
                        x_lits = []
                        for req in minimal_conflict:
                            dp = model._inst.requestList[req][3]
                            for p in prefix_origins:
                                if model._vars['x'][v, p, dp] is not None:
                                    x_lits.append(model._vars['x'][v, p, dp])
                                    
                        model.cbLazy(gp.quicksum(y_lits) + gp.quicksum(x_lits) <= len(y_lits) - 1)
                        break

    def solve(self, time_limit=3600):
        self.genMipModel()
        
        if time_limit is not None:
            self.model.Params.TimeLimit = time_limit
        self.model.Params.Threads = 1
        self.model.Params.LazyConstraints = 1
        
        # Pass necessary instances to the callback
        self.model._inst = self
        self.model._vars = {'x': self.x, 'y': self.y}
        self.model._bc_strategy = self.bc_strategy
        
        print(f"[MIP] Starting Gurobi optimization for {self.insName} (Strategy: {self.bc_strategy.upper()})")
        
        # Initialize the log file BEFORE optimization so the callback can append to it
        log_file = f"{self.insName}.out"
        with open(log_file, "w") as f:
            f.write(f"--- Starting MIP for {self.insName} ---\n")
            
        def log(msg):
            print(msg)
            with open(log_file, "a") as f:
                f.write(msg + "\n")
                
        start_time = time.time()

        # Initialize history tracker to negative infinity
        self.best_incumbent_obj = float('-inf')
        
        # Combined callback: logs incumbent updates AND executes your lazy constraints
        def combined_callback(model, where):
            # 1. Capture genuine, valid Incumbent updates
            if where == gp.GRB.Callback.MIP:
                # Use MIP_OBJBST to get the best objective AFTER lazy constraints validation
                obj_bst = model.cbGet(gp.GRB.Callback.MIP_OBJBST)
                bnd = model.cbGet(gp.GRB.Callback.MIP_OBJBND)
                runtime = model.cbGet(gp.GRB.Callback.RUNTIME)

                # Ensure a valid solution is found (Gurobi initializes with -1e100)
                # Only log if it strictly improves upon our recorded best
                if obj_bst > self.best_incumbent_obj and obj_bst > -1e99:
                    self.best_incumbent_obj = obj_bst
                    
                    # Calculate relative gap for maximization problem
                    gap_str = "N/A"
                    if abs(obj_bst) > 1e-5: 
                        gap = abs(bnd - obj_bst) / abs(obj_bst) * 100.0
                        gap_str = f"{gap:.2f}%"
                        
                    # Log with [Incumbent] to match the parser regex
                    with open(log_file, "a") as cb_f:
                        cb_f.write(f"[Incumbent] Time: {runtime:.2f}s | Obj: {obj_bst:.1f} | Bound: {bnd:.1f} | Gap: {gap_str}\n")
            
            # 2. Route execution to the Benders decomposition callback
            # This must be OUTSIDE the `if where == MIP` block so Lazy Constraints trigger correctly
            self.benders_callback(model, where)

        self.model.optimize(combined_callback)
        
        elapsed = time.time() - start_time
        
        if self.model.Status == gp.GRB.OPTIMAL or self.model.SolCount > 0:
            raw_model = []
            
            for t in range(self.lenOfVehicle):
                for i in range(1 + self.lenOfLocation):
                    for j in range(1 + self.lenOfLocation):
                        if i != j and self.x[t, i, j] is not None:
                            if self.x[t, i, j].X > 0.5:
                                var_id = self.xVarList[t][i][j]
                                raw_model.append(f"x{var_id}")
                                
            for r in range(self.lenOfRequest):
                for t in range(self.lenOfVehicle):
                    if self.y[r, t].X > 0.5:
                        var_id = self.yVarList[r][t]
                        raw_model.append(f"y{var_id}")
                        
            filtered_model = PPDSP_utils.convert_model(raw_model)
            
            log(f"[Gurobi] Status: {self.model.Status}")
            log(f"[Gurobi] BEST OBJ: {self.model.ObjVal}")
            log(f"[Gurobi] BEST BOUND: {self.model.ObjBound}")
            log(f"[Gurobi] Runtime: {elapsed:.3f} sec")
            try:
                log(f"[Gurobi] Gap: {self.model.MIPGap * 100:.2f}%")
            except AttributeError:
                pass
            
            PPDSP_utils.printVehRoutes(self, filtered_model, log_file)
            PPDSP_utils.evaluateSolution(self, filtered_model, log_file)
            
            log("===== RAW XY MODEL =====")
            log(" ".join(str(v) for v in filtered_model))
            
            return filtered_model
        else:
            log(f"[Gurobi] Status: {self.model.Status}")
            log("[Gurobi] No feasible solution found.")
            log(f"[Gurobi] Runtime: {elapsed:.3f} sec")
            try:
                best_bound = self.model.ObjBound
                log(f"[Gurobi] BEST OBJ: -, BEST BOUND: {best_bound}")
            except AttributeError:
                pass
            return None
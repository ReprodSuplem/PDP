# ppdsp_cpsat.py

from ppdsp_ins_gen import PPDSP_reform
from ppdsp_utils import PPDSP_utils
import time
import math
from ortools.sat.python import cp_model

class SolutionLogger(cp_model.CpSolverSolutionCallback):
    """
    Custom Solution Logger to capture incumbent solutions and optimality gaps
    during the CP-SAT search process.
    """
    def __init__(self, log_func):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self.log_func = log_func
        self.solution_count = 0

    def OnSolutionCallback(self):
        self.solution_count += 1
        obj = self.ObjectiveValue()
        bound = self.BestObjectiveBound()
        time_elapsed = self.WallTime()

        if obj == 0:
            gap = float('inf') if bound != 0 else 0.0
        else:
            gap = abs(bound - obj) / abs(obj) * 100.0

        msg = f"[Incumbent {self.solution_count:02d}] Time: {time_elapsed:6.2f}s | Obj: {obj:6.0f} | Bound: {bound:6.0f} | Gap: {gap:6.2f}%"
        self.log_func(msg)

class PPDSP_CPSAT(PPDSP_reform):
    def __init__(self, pdpName, num_reqs, num_vehs, capacity, knn, increment=None):
        super().__init__(pdpName, num_reqs, num_vehs, capacity, knn, increment)
        self.knn = int(knn)
        self.model = cp_model.CpModel()
        self.insName = f"ppdsp_{pdpName}_r{num_reqs}v{num_vehs}k{knn}_cpsat"
        
        # Variable dictionaries mapped to CP-SAT variables
        self.y = {}      
        self.x = {}      
        self.active = {} 
        self.pos = {}    
        self.load = {}   
        self.delta = {}  

    def genCpModel(self):
        # Generate essential variables only. U and H are omitted as they are redundant in CP-SAT.
        self.genXVarList()
        self.genYVarList()

        num_nodes = 1 + self.lenOfLocation
        DEPOT = self.lenOfLocation
        num_reqs = self.lenOfRequest
        num_vehs = self.lenOfVehicle

        # ==================== Variable Declaration ====================
        for t in range(num_vehs):
            cap = int(self.vehicleList[t][0])
            for r in range(num_reqs):
                self.y[r, t] = self.model.NewBoolVar(f'y_r{r}_t{t}')

            for i in range(num_nodes):
                self.active[t, i] = self.model.NewBoolVar(f'act_t{t}_i{i}')
                self.pos[t, i] = self.model.NewIntVar(0, num_nodes, f'pos_t{t}_i{i}')
                self.load[t, i] = self.model.NewIntVar(0, cap, f'load_t{t}_i{i}')
                self.delta[t, i] = self.model.NewIntVar(-cap, cap, f'delta_t{t}_i{i}')

                for j in range(num_nodes):
                    if i == j: 
                        self.x[t, i, i] = self.model.NewBoolVar(f'x_t{t}_i{i}_j{i}')
                    elif self.adjMatrix[i][j] != 0:
                        self.x[t, i, j] = self.model.NewBoolVar(f'x_t{t}_i{i}_j{j}')

        # ==================== Base Constraints ====================
        
        # PPDSP Eq.2: Optional Request Assignment (At-Most-One for Selection)
        for r in range(num_reqs):
            self.model.AddAtMostOne([self.y[r, t] for t in range(num_vehs)])

        # PPDSP Eq.3 & Eq.4 mapping: Node Activation and Net Demand (Delta) Logic
        for t in range(num_vehs):
            self.model.Add(self.load[t, DEPOT] == 0)  
            self.model.Add(self.delta[t, DEPOT] == 0)
            self.model.Add(self.pos[t, DEPOT] == 0)   

            is_used = self.model.NewBoolVar(f'is_used_t{t}')
            self.model.AddMaxEquality(is_used, [self.y[r, t] for r in range(num_reqs)])
            self.model.Add(self.x[t, DEPOT, DEPOT] == is_used.Not()) 

            for i in range(num_nodes):
                if i != DEPOT:
                    self.model.Add(self.x[t, i, i] == self.active[t, i].Not())
                    
                    # PPDSP Request extraction: [profit, size, pk, dp]
                    reqs_pickup = [r for r in range(num_reqs) if self.requestList[r][2] == i]
                    reqs_delivery = [r for r in range(num_reqs) if self.requestList[r][3] == i]
                    all_reqs = reqs_pickup + reqs_delivery

                    for r in all_reqs:
                        self.model.AddImplication(self.y[r, t], self.active[t, i])
                        
                    self.model.AddImplication(is_used.Not(), self.active[t, i].Not())

                    pickup_sum = sum(self.requestList[r][1] * self.y[r, t] for r in reqs_pickup)
                    delivery_sum = sum(self.requestList[r][1] * self.y[r, t] for r in reqs_delivery)
                    self.model.Add(self.delta[t, i] == pickup_sum - delivery_sum)

        # Eq.5 & Eq.6 & Eq.7 & Eq.9 mappings: Global Circuit Constraint (Flow, Subtour & Capacity)
        for t in range(num_vehs):
            arcs = []
            for i in range(num_nodes):
                if (t, i, i) in self.x:
                    arcs.append((i, i, self.x[t, i, i]))
                for j in range(num_nodes):
                    if i != j and (t, i, j) in self.x:
                        arcs.append((i, j, self.x[t, i, j]))
                        
                        if j != DEPOT:
                            self.model.Add(self.pos[t, j] == self.pos[t, i] + 1).OnlyEnforceIf(self.x[t, i, j])
                            self.model.Add(self.load[t, j] == self.load[t, i] + self.delta[t, j]).OnlyEnforceIf(self.x[t, i, j])

            self.model.AddCircuit(arcs)

            # Eq.8 mapping: Physical Precedence Constraint
            for r in range(num_reqs):
                p_node = self.requestList[r][2]
                d_node = self.requestList[r][3]
                if p_node != d_node:
                    self.model.Add(self.pos[t, p_node] < self.pos[t, d_node]).OnlyEnforceIf(self.y[r, t])

        # ==================== Model Enhancements (Valid Inequalities) ====================
        
        # Symmetry Breaking for Homogeneous Fleet
        for t in range(1, num_vehs):
            for r in range(num_reqs):
                self.model.Add(self.y[r, t] <= sum(self.y[prev_r, t-1] for prev_r in range(r)))

        # Active Vehicle Pruning (EVP)
        for t in range(num_vehs):
            is_used = self.model.NewBoolVar(f'evp_is_used_t{t}')
            self.model.AddMaxEquality(is_used, [self.y[r, t] for r in range(num_reqs)])
            for i in range(num_nodes):
                for j in range(num_nodes):
                    if i != j and (t, i, j) in self.x:
                        self.model.AddImplication(is_used.Not(), self.x[t, i, j].Not())

        # ==================== PPDSP Objective Function ====================
        
        # PPDSP Eq.1: Maximize (Collected Profit - Routing Cost)
        obj_terms = []
        
        # 1. Add Collected Profit
        for r in range(num_reqs):
            profit = self.requestList[r][0]
            for t in range(num_vehs):
                obj_terms.append(profit * self.y[r, t])
                
        # 2. Subtract Routing Cost
        for t in range(num_vehs):
            veh_cost = self.vehicleList[t][1]
            for i in range(num_nodes):
                for j in range(num_nodes):
                    if i != j and (t, i, j) in self.x:
                        dist = math.dist(self.locaList[i], self.locaList[j])
                        cost = self.my_round_int(veh_cost * dist)
                        obj_terms.append(-cost * self.x[t, i, j])

        self.model.Maximize(sum(obj_terms))

    def solve(self, time_limit=3600, assumption_file=None):
        self.genCpModel()
        solver = cp_model.CpSolver()
        
        if time_limit is not None:
            solver.parameters.max_time_in_seconds = time_limit
        
        solver.parameters.num_search_workers = 1
        solver.parameters.log_search_progress = True 
        
        print(f"[CP-SAT] Setting time limit to {time_limit} seconds with {solver.parameters.num_search_workers} workers.")
        
        log_file = f"{self.insName}.out"
        def log(msg):
            print(msg)
            with open(log_file, "a") as f:
                f.write(msg + "\n")
                
        with open(log_file, "w") as f:
            f.write(f"--- Starting CP-SAT for {self.insName} ---\n")

        solution_logger = SolutionLogger(log)

        start_time = time.time()
        status = solver.Solve(self.model, solution_logger)
        elapsed = time.time() - start_time

        status_name = solver.StatusName(status)
        log(f"[CP-SAT] Status: {status_name}")
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            raw_model = []
            
            for t in range(self.lenOfVehicle):
                for i in range(1 + self.lenOfLocation):
                    for j in range(1 + self.lenOfLocation):
                        if i != j and (t, i, j) in self.x:
                            if solver.Value(self.x[t, i, j]):
                                var_id = self.xVarList[t][i][j]
                                raw_model.append(f"x{var_id}")
                                
            for r in range(self.lenOfRequest):
                for t in range(self.lenOfVehicle):
                    if (r, t) in self.y:
                        if solver.Value(self.y[r, t]):
                            var_id = self.yVarList[r][t]
                            raw_model.append(f"y{var_id}")

            filtered_model = PPDSP_utils.convert_model(raw_model)

            log(f"[CP-SAT] FINAL OBJ: {solver.ObjectiveValue()}")
            log(f"[CP-SAT] Total Runtime: {elapsed:.3f} sec")
            
            PPDSP_utils.printVehRoutes(self, filtered_model, log_file)
            PPDSP_utils.evaluateSolution(self, filtered_model, log_file)
            
            log("===== RAW XY MODEL =====")
            log(" ".join(str(v) for v in filtered_model))
            
            return filtered_model
        else:
            log("[CP-SAT] No feasible solution found.")
            log(f"[CP-SAT] Total Runtime: {elapsed:.3f} sec")
            return None
# pdp_maxsat.py

import os
from pdp_ins_gen import PDP_reform
from pdp_utils import PDP_utils
from pysat.pb import *
from pysat.formula import *

class PDP_MaxSAT(PDP_reform):
    def __init__(self, pdpName, num_reqs, num_vehs, capacity, knn, increment=None):
        super().__init__(pdpName, num_reqs, num_vehs, capacity, knn, increment)
        self.knn = int(knn)
        self.wcnf = WCNF()
        self.cnf = CNF()
        self.vpool = None
        
        # Enforce lowercase naming convention
        self.insName = f"pdp_{pdpName}_r{num_reqs}v{num_vehs}k{knn}_maxsat"

    def atLeastOne(self, varList):
        self.wcnf.append(varList)

    def atMostOne(self, varList):
        for i in range(len(varList)):
            for j in range(1+i, len(varList)):
                self.wcnf.append([(-1 * varList[i]), (-1 * varList[j])])

    def exactlyOne(self, varList):
        self.atMostOne(varList)
        self.atLeastOne(varList)

    def twoSumsEqvt(self, litList1, litList2):
        return (
            [[-x] + litList2 for x in litList1] +
            [[-y] + litList1 for y in litList2]
        )

    # Eq.1: Minimize Total Routing Cost (Implemented via Soft Clauses)
    def genSoftClause(self):
        for i in range(self.lenOfVehicle):
            for j in range(1+self.lenOfLocation):
                for k in range(1+self.lenOfLocation):
                    if k != j:
                        if self.adjMatrx[j][k] == 0: continue
                        cost = self.my_round_int(self.vehicleList[i][1] * self.locaList[j][k])
                        self.wcnf.append([-self.xVarList[i][j][k]], weight=cost)

    # Eq.2: Mandatory Request Assignment (Exactly-One)
    def genHardClauseForEq2(self):
        for i in range(self.lenOfRequest):
            varList = []
            for j in range(self.lenOfVehicle):
                varList.append(self.yVarList[i][j])
            self.exactlyOne(varList)

    # Eq.3: Node Visitation Linkage (Pickup)
    def genHardClauseForEq3(self):
        for i in range(self.lenOfRequest):
            pickup = self.requestList[i][1]
            dropoff = self.requestList[i][2]
            for j in range(self.lenOfVehicle):
                varList = [-self.yVarList[i][j]]
                for k in range(1+self.lenOfLocation):
                    if k != pickup and k != dropoff:
                        if self.adjMatrx[k][pickup] != 0:
                            varList.append(self.xVarList[j][k][pickup])
                self.wcnf.append(varList)

    # Eq.4: Node Visitation Linkage (Dropoff)
    def genHardClauseForEq4(self):
        for i in range(self.lenOfRequest):
            dropoff = self.requestList[i][2]
            for j in range(self.lenOfVehicle):
                varList = [-self.yVarList[i][j]]
                for k in range(self.lenOfLocation):
                    if k != dropoff:
                        if self.adjMatrx[k][dropoff] != 0:
                            varList.append(self.xVarList[j][k][dropoff])
                self.wcnf.append(varList)

    # Eq.5: Flow Balance Constraint
    def genHardClauseForEq5(self):
        for i in range(self.lenOfVehicle):
            for j in range(1+self.lenOfLocation):
                litList1 = []
                litList2 = []
                for k in range(1+self.lenOfLocation):
                    if k != j and self.adjMatrx[j][k] != 0:
                        litList1.append(self.xVarList[i][j][k])
                    if k != j and self.adjMatrx[k][j] != 0:
                        litList2.append(self.xVarList[i][k][j])
                cnf_obj = self.twoSumsEqvt(litList1, litList2)
                for clause in cnf_obj:
                    self.wcnf.append(clause)

    # Eq.6: Degree Constraint (Out-degree <= 1)
    def genHardClauseForEq6(self):
        for i in range(self.lenOfVehicle):
            for j in range(1+self.lenOfLocation):
                varList = []
                for k in range(1+self.lenOfLocation):
                    if k != j:
                        varList.append(self.xVarList[i][j][k])
                self.atMostOne(varList)

    # Order Encoding Base: Domain Transitivity
    def genHardClauseForDomainTransitive(self):
        num_bits = self.lenOfLocation - 1 
        for t in range(self.lenOfVehicle):
            for i in range(self.lenOfLocation):
                for p in range(num_bits - 1):
                    self.wcnf.append([-self.nuVarList[t][i][p], self.nuVarList[t][i][p+1]])

    # Eq.7: Subtour Elimination (via Order Encoding)
    def genHardClauseForEq7(self): 
        num_bits = self.lenOfLocation - 1 
        last_bit_idx = num_bits - 1 
        for t in range(self.lenOfVehicle):
            for j in range(self.lenOfLocation):
                for k in range(self.lenOfLocation):
                    if j == k: continue
                    if self.adjMatrx[j][k] == 0: continue 
                    for p in range(num_bits):
                        clause = [-self.xVarList[t][j][k], -self.nuVarList[t][k][p]]
                        if p > 0:
                            clause.append(self.nuVarList[t][j][p-1])
                        self.wcnf.append(clause)
                    
                    clause_boundary = [-self.xVarList[t][j][k], self.nuVarList[t][j][last_bit_idx]]
                    self.wcnf.append(clause_boundary)

    # Eq.8: Physical Precedence Constraint (via Order Encoding)
    def genHardClauseForEq8(self): 
        num_bits = self.lenOfLocation - 1 
        last_bit_idx = num_bits - 1 
        for i in range(self.lenOfRequest):
            pickup = self.requestList[i][1]
            dropoff = self.requestList[i][2]
            
            if pickup == dropoff:
                continue
                
            for t in range(self.lenOfVehicle):
                for p in range(num_bits):
                    clause = [-self.yVarList[i][t], -self.nuVarList[t][dropoff][p]]
                    if p > 0:
                        clause.append(self.nuVarList[t][pickup][p-1])
                    self.wcnf.append(clause)
                
                clause_boundary = [-self.yVarList[i][t], self.nuVarList[t][pickup][last_bit_idx]]
                self.wcnf.append(clause_boundary)

    # Valid Inequality: k-NN Sparsification
    def genHardClauseForKnn(self): 
        for t in range(self.lenOfVehicle):
            for i in range(len(self.adjMatrx)):
                for j in range(len(self.adjMatrx[i])):
                    if self.adjMatrx[i][j] == 0:
                        x_var = self.xVarList[t][i][j]
                        self.wcnf.append([-x_var])

    # Valid Inequality: Redundancy Elimination Constraint (REC)
    def genHardClauseFoRec(self):
        node_requests = [[] for _ in range(self.lenOfLocation)]
        for r in range(self.lenOfRequest):
            pickup = self.requestList[r][1]
            dropoff = self.requestList[r][2]
            node_requests[pickup].append(r)
            if dropoff != pickup:
                node_requests[dropoff].append(r)
            
        for k in range(self.lenOfVehicle):
            for i in range(self.lenOfLocation):
                service_lits = [self.yVarList[r][k] for r in node_requests[i]]
                for j in range(self.lenOfLocation + 1): 
                    if j == i: continue
                    x_var = self.xVarList[k][j][i]
                    self.wcnf.append([-x_var] + service_lits)

    # Valid Inequality: Symmetry Breaking Constraint (SBC)
    def genHardClauseForSbc(self):
        groups = PDP_utils.get_sbc_groups(self.vehicleList)
        for key, veh_ids in groups.items():
            for i in range(len(veh_ids) - 1):
                leader = veh_ids[i]
                follower = veh_ids[i+1]
                for r in range(self.lenOfRequest):
                    clause = [-self.yVarList[r][follower]]
                    for prev_r in range(r):
                        clause.append(self.yVarList[prev_r][leader])
                    self.wcnf.append(clause)

    # Valid Inequality: Active Vehicle Pruning (EVP)
    def genHardClauseForEVP(self):
        for t in range(self.lenOfVehicle):
            any_req_lits = [self.yVarList[r][t] for r in range(self.lenOfRequest)]
            for i in range(1+self.lenOfLocation):
                for j in range(1+self.lenOfLocation):
                    if i != j and self.adjMatrx[i][j] != 0:
                        x_var = self.xVarList[t][i][j]
                        self.wcnf.append([-x_var] + any_req_lits)

    def genMaxsatFormular(self):
        self.genXVarList()
        self.genYVarList()
        self.genNuVarList()

        self.genSoftClause()
        self.genHardClauseForEq2()
        self.genHardClauseForEq3()
        self.genHardClauseForEq4()
        self.genHardClauseForEq5()
        self.genHardClauseForEq6()
        
        self.genHardClauseForDomainTransitive()
        self.genHardClauseForEq7()
        self.genHardClauseForEq8()
        
        self.genHardClauseFoRec() if self.knn == 0 else self.genHardClauseForKnn()
        self.genHardClauseForSbc()
        self.genHardClauseForEVP()

        print(f"[MaxSAT] Generating instance: {self.insName}.wcnf ...")
        self.wcnf.extend(self.cnf)
        self.wcnf.to_file(self.insName + ".wcnf")
        PDP_utils.export_meta(self, self.insName + ".meta")

    def solve(self, verbose=1, time_limit=3600, assumption_file=None):
        wcnf_file = self.insName + ".wcnf"
        lastY = self.getLastYVarID()
        meta_file = self.insName + ".meta"
        log_file  = wcnf_file + ".out"

        cmd = f"stdbuf -oL uwrmaxsat -no-bin -no-sat -no-par -no-scip -ppdsp-time={time_limit} -ppdsp-lastY={lastY} -ppdsp={meta_file}"
        if assumption_file is not None and os.path.exists(assumption_file):
            cmd += f" -ppdsp-assume={assumption_file}"
            print(f"  [Info] Injected assumption file: {assumption_file}")
            
        cmd += f" {wcnf_file} | tee {log_file}"
        print(f"[UWrMaxSAT] Executing solver command:\n  {cmd}")
        os.system(cmd)

        model = []
        with open(log_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("v "):
                    for lit in line.split()[1:]: 
                        if lit != "0":
                            model.append(int(lit))

        if not model:
            with open(log_file, "a") as f:
                f.write("\n[UWrMaxSAT] No feasible solution found.\n")
            print("[UWrMaxSAT] No feasible solution found.")
            return None

        filtered_model = PDP_utils.extractXYModel(self, model)

        PDP_utils.printVehRoutes(self, filtered_model)
        obj_val = PDP_utils.evaluateSolution(self, filtered_model)

        with open(log_file, "a") as f:
            f.write(f"[UWrMaxSAT] OBJ: {obj_val}")

        return filtered_model
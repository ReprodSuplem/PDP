# ppdsp_utils.py

import os

class GlobalVariableRegistry:

    # ==========================================
    # Global variable registry for incremental model
    # ==========================================
    def __init__(self):
        self.varCounter = 0
        self.varDict = {}

    def get_id(self, var_type, *args):
        """
        Generate or retrieve a fixed global ID based on variable type and indices.
        var_type: 'x', 'y', 'u', 'nu', 'h'
        args: corresponding index combinations, e.g., (t, o, d)
        """
        key = (var_type,) + args
        if key not in self.varDict:
            self.varCounter += 1
            self.varDict[key] = self.varCounter
        return self.varDict[key]

    def get_max_core_id(self):
        """
        Return the maximum ID assigned so far, used as a safe starting point for ID pools.
        """
        return self.varCounter


class PPDSP_utils:

    # ----------------------------
    # Parse log file to generate Assumption
    # ----------------------------
    @staticmethod
    def parse_and_save_assumption(log_file, assumption_file, lastY, mode):
        if not os.path.exists(log_file):
            print(f"  [Warning] Log file {log_file} not found.")
            return False

        core_lits = []
        
        if mode == "maxsat":
            with open(log_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("v "):
                        lits = line.split()[1:]
                        for lit_str in lits:
                            try:
                                lit = int(lit_str)
                                if abs(lit) <= lastY:
                                    core_lits.append(lit)
                            except ValueError:
                                pass
        elif mode == "mip":
            positive_vars = set()
            raw_model_found = False
            with open(log_file, "r") as f:
                lines = f.readlines()
                for i, line in enumerate(lines):
                    if line.startswith("===== RAW XY MODEL ====="):
                        raw_model_found = True
                        if i + 1 < len(lines):
                            val_str = lines[i+1].strip()
                            if val_str:
                                positive_vars = set(int(v) for v in val_str.split())
                        break
            
            if raw_model_found:
                for vid in range(1, lastY + 1):
                    if vid in positive_vars:
                        core_lits.append(vid)
                    else:
                        core_lits.append(-vid)
        
        if core_lits:
            with open(assumption_file, "w") as f:
                f.write(" ".join(map(str, core_lits)) + "\n")
            print(f"  [Info] Saved {len(core_lits)} core assumption literals to {assumption_file}")
            return True
        else:
            print("  [Warning] No valid literals found in log. Assumption creation failed.")
            return False

    # ----------------------------
    # Convert string varNames to integer literal IDs
    # ----------------------------
    @staticmethod
    def convert_model(raw_model):
        filtered = []
        for name in raw_model:
            if len(name) > 1 and (name[0] == 'x' or name[0] == 'y'):
                try:
                    filtered.append(int(name[1:]))
                except Exception:
                    pass
        return filtered

    # ----------------------------
    # Build reverse mapping: varID -> (type, ...)
    # ----------------------------
    @staticmethod
    def buildVarIndexMap(self):
        self.id2Var = {}
        for t in range(self.lenOfVehicle):
            for o in range(len(self.xVarList[t])):
                for d in range(len(self.xVarList[t][o])):
                    vid = self.xVarList[t][o][d]
                    self.id2Var[vid] = ('x', t, o, d)
        
        for r in range(self.lenOfRequest):
            for t in range(self.lenOfVehicle):
                vid = self.yVarList[r][t]
                self.id2Var[vid] = ('y', r, t)

    # ----------------------------
    # Extract structural model (xy domain)
    # ----------------------------
    @staticmethod
    def extractXYModel(self, model):
        return [i for i in model if 0 < i <= self.getLastYVarID()]

    # ----------------------------
    # Decode paths and assignments from variable model
    # ----------------------------
    @staticmethod
    def decodeModel(self, filtered_model):
        if self.id2Var is None:
            PPDSP_utils.buildVarIndexMap(self)

        veh_routes = {v: {'route': [], 'requests': []} for v in range(self.lenOfVehicle)}

        for vid in filtered_model:
            varInfo = self.id2Var.get(vid)
            if varInfo is None:
                continue
            if varInfo[0] == 'x':
                _, t, o, d = varInfo
                if o != d:
                    veh_routes[t]['route'].append((o, d))
            elif varInfo[0] == 'y':
                _, r, t = varInfo
                veh_routes[t]['requests'].append(r)

        for v in range(self.lenOfVehicle):
            edges = veh_routes[v]['route']
            if not edges:
                continue
            next_map = {o: d for (o, d) in edges}
            route = []
            cur = self.lenOfLocation
            while cur in next_map:
                nxt = next_map[cur]
                route.append((cur, nxt))
                cur = nxt
                if cur == self.lenOfLocation:
                    break
            veh_routes[v]['route'] = route
            
        return veh_routes

    # ----------------------------
    # Homogeneous fleet grouping
    # ----------------------------
    @staticmethod
    def get_sbc_groups(vehicleList):
        groups = {}
        for t, veh in enumerate(vehicleList):
            cap = int(veh[0])
            cost = float(f"{veh[1]:.4f}")
            key = (cap, cost)
            
            if key not in groups:
                groups[key] = []
            groups[key].append(t)
            
        return {k: v for k, v in groups.items() if len(v) >= 2}

    # ----------------------------
    # Check overload and return learnt clause
    # ----------------------------
    @staticmethod
    def checkOverload(self, vehID, route, assigned_reqs):
        if not route:
            return False, []

        capacity = self.vehicleList[vehID][0]
        load = 0
        onboard = set()

        # Shifted indices specifically for PPDSP requestList format [profit, size, pk, dp]
        req_size    = {r: self.requestList[r][1] for r in range(self.lenOfRequest)}
        pickup_node = {r: self.requestList[r][2] for r in range(self.lenOfRequest)}
        drop_node   = {r: self.requestList[r][3] for r in range(self.lenOfRequest)}

        violated = False
        learnt_clause = []

        for k, (o, d) in enumerate(route):
            for r in assigned_reqs:
                if d == pickup_node[r] and d == drop_node[r]:
                    continue
                elif d == pickup_node[r]:
                    load += req_size[r]
                    onboard.add(r)
                elif d == drop_node[r] and r in onboard:
                    load -= req_size[r]
                    onboard.remove(r)

            if load > capacity:
                violated = True
                onboard_reqs = list(onboard)
                onboard_reqs.sort(key=lambda r: req_size[r], reverse=True)

                minimal_conflict = []
                current_subset_load = 0
                for r in onboard_reqs:
                    current_subset_load += req_size[r]
                    minimal_conflict.append(r)
                    if current_subset_load > capacity:
                        break 

                yLits = [-self.yVarList[r][vehID] for r in minimal_conflict]
                prefix_origins = [route[i][0] for i in range(k + 1)]

                xLits = []
                for r in minimal_conflict:
                    dp = drop_node[r]
                    for p in prefix_origins:
                        xLits.append(self.xVarList[vehID][p][dp])

                learnt_clause = yLits + xLits
                break

        return violated, learnt_clause

    # ----------------------------
    # Output visual representation of vehicle routes
    # ----------------------------
    @staticmethod
    def printVehRoutes(self, filtered_model, log_file=None):
        vehRoutes = PPDSP_utils.decodeModel(self, filtered_model)
        depot = self.lenOfLocation
        output_lines = []
        for vehID, info in vehRoutes.items():
            route = info['route']
            reqs  = info['requests']
            if not route:
                output_lines.append(f"Vehicle {vehID}: Depot, (requests = {reqs})")
                continue
            node_seq = [route[0][0]] + [d for (_, d) in route]
            node_seq_str = ["Depot" if n == depot else str(n) for n in node_seq]
            pretty_route = " → ".join(node_seq_str)
            output_lines.append(f"Vehicle {vehID}: {pretty_route}, (requests = {reqs})")

        output_str = "\n".join(output_lines)
        print(output_str)

        if log_file and os.path.exists(log_file):
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("\n" + output_str + "\n")

    # ----------------------------
    # Evaluate PPDSP Objective Function
    # ----------------------------
    @staticmethod
    def evaluateSolution(self, filtered_model, log_file=None):
        import math
        if self.id2Var is None:
            PPDSP_utils.buildVarIndexMap(self)

        cost = 0
        profit = 0

        for vid in filtered_model:
            varInfo = self.id2Var.get(vid)
            if varInfo is None:
                continue

            if varInfo[0] == 'x':
                _, t, o, d = varInfo
                if o != d:
                    cost += self.my_round_int(self.vehicleList[t][1] * self.locaList[o][d])
            elif varInfo[0] == 'y':
                _, r, t = varInfo
                profit += self.requestList[r][0]

        obj = profit - cost
        
        eval_lines = [
            "======== PPDSP SOLUTION EVALUATION ========",
            f"Total Collected Profit = {profit}",
            f"Total Routing Cost     = {cost}",
            f"Objective Value        = {obj}",
            "==========================================="
        ]
        eval_str = "\n".join(eval_lines)
        print(eval_str)
        
        if log_file and os.path.exists(log_file):
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(eval_str + "\n")

        return obj

    # ----------------------------
    # Compile metadata for UWrMaxSAT parser
    # ----------------------------
    @staticmethod
    def export_meta(self, filename):
        with open(filename, "w") as f:
            f.write(f"{self.lenOfVehicle} {self.lenOfRequest} {self.lenOfLocation}\n")

            f.write("# xVarList\n")
            for t in range(self.lenOfVehicle):
                for o in range(len(self.xVarList[t])):
                    for d in range(len(self.xVarList[t][o])):
                        vid = self.xVarList[t][o][d]
                        f.write(f"{t} {o} {d} {vid}\n")

            f.write("# yVarList\n")
            for r in range(self.lenOfRequest):
                for t in range(self.lenOfVehicle):
                    vid = self.yVarList[r][t]
                    f.write(f"{r} {t} {vid}\n")

            f.write("# requestList\n")
            for r in range(self.lenOfRequest):
                # PPDSP Export: Passing the real profit value to the C++ parser
                profit, q, pk, dp = self.requestList[r]
                f.write(f"{r} {profit} {q} {pk} {dp}\n")

            f.write("# vehicleList\n")
            for t in range(self.lenOfVehicle):
                cap, cost = self.vehicleList[t]
                f.write(f"{t} {cap} {cost}\n")

            f.write("# vehicleGroups\n")
            groups = PPDSP_utils.get_sbc_groups(self.vehicleList)
            gid = 0
            for key, vehs in groups.items():
                line = f"{gid} {len(vehs)} " + " ".join(map(str, vehs))
                f.write(line + "\n")
                gid += 1
            
            print(f"[UWrMaxSAT] PPDSP Metadata successfully exported to {filename}.")

    # ----------------------------
    # Read core assumption literals for warm-start operations
    # ----------------------------
    @staticmethod
    def read_assumption_literals(filename):
        lits = set()
        try:
            with open(filename, 'r') as f:
                content = f.read()
                tokens = content.replace('\n', ' ').split()
                for t in tokens:
                    try:
                        lit = int(t)
                        if lit != 0: lits.add(lit) 
                    except ValueError:
                        pass 
        except FileNotFoundError:
            print(f"[Utils] Assumption file not found: {filename}")
        return lits
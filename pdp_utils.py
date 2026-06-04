# pdp_utils.py

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


class PDP_utils:

    # ----------------------------
    # Parse log file to generate Assumption
    # ----------------------------
    @staticmethod
    def parse_and_save_assumption(log_file, assumption_file, lastY, mode):
        """
        Extract xVars and yVars from the log file to generate a standard assumption file.
        Maintains compatibility with both MaxSAT (.wcnf.out) and MIP (.out) log structures.
        """
        import os
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
        """
        Converts identifier strings (e.g., ['x303', 'y17']) into integer literals ([303, 17]).
        """
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
        # Mapping for x variables
        for t in range(self.lenOfVehicle):
            for o in range(len(self.xVarList[t])):
                for d in range(len(self.xVarList[t][o])):
                    vid = self.xVarList[t][o][d]
                    self.id2Var[vid] = ('x', t, o, d)
        
        # Mapping for y variables
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
            PDP_utils.buildVarIndexMap(self)

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

        # Reconstruct ordered Hamiltonian cycles for active vehicles
        for v in range(self.lenOfVehicle):
            edges = veh_routes[v]['route']
            if not edges:
                continue
            next_map = {o: d for (o, d) in edges}
            route = []
            cur = self.lenOfLocation # Start from depot
            while cur in next_map:
                nxt = next_map[cur]
                route.append((cur, nxt))
                cur = nxt
                if cur == self.lenOfLocation: # Tour completed
                    break
            veh_routes[v]['route'] = route
            
        return veh_routes

    # ----------------------------
    # Homogeneous fleet grouping
    # ----------------------------
    @staticmethod
    def get_sbc_groups(vehicleList):
        """
        Group vehicles by Capacity and Routing Cost Factor to enforce Symmetry Breaking Constraints (SBC).
        Returns a dictionary formatted as {(capacity, cost): [v1, v2, v3...]}
        """
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
    # Output visual representation of vehicle routes
    # ----------------------------
    @staticmethod
    def printVehRoutes(self, filtered_model, log_file=None):
        vehRoutes = PDP_utils.decodeModel(self, filtered_model)
        depot = self.lenOfLocation
        output_lines = []
        for vehID, info in vehRoutes.items():
            route = info['route']
            reqs  = info['requests']
            if not route:
                print(f"Vehicle {vehID}: Depot, (requests = {reqs})")
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
    # Evaluate Total Objective Cost
    # ----------------------------
    @staticmethod
    def evaluateSolution(self, filtered_model, log_file=None):
        if self.id2Var is None:
            PDP_utils.buildVarIndexMap(self)

        cost = 0

        for vid in filtered_model:
            varInfo = self.id2Var.get(vid)
            if varInfo is None:
                continue

            if varInfo[0] == 'x':
                _, t, o, d = varInfo
                cost += self.my_round_int(self.vehicleList[t][1] * self.locaList[o][d])

        eval_lines = [
            "======== PDP SOLUTION EVALUATION ========",
            f"Total Routing Cost     = {cost}",
            f"Objective Value        = {cost}",
            "========================================="
        ]
        eval_str = "\n".join(eval_lines)
        print(eval_str)
        
        if log_file and os.path.exists(log_file):
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(eval_str + "\n")

        return cost

    # ----------------------------
    # Compile metadata for UWrMaxSAT parser
    # ----------------------------
    @staticmethod
    def export_meta(self, filename):
        """
        Export essential dimensional and assignment metadata for the C++ MaxSAT engine.
        """
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
                q, pk, dp = self.requestList[r]
                # Inject a dummy profit of 0 to maintain structural backward compatibility with the C++ parser
                f.write(f"{r} 0 {q} {pk} {dp}\n")

            f.write("# vehicleList\n")
            for t in range(self.lenOfVehicle):
                cap, cost = self.vehicleList[t]
                f.write(f"{t} {cap} {cost}\n")

            f.write("# vehicleGroups\n")
            groups = PDP_utils.get_sbc_groups(self.vehicleList)
            gid = 0
            for key, vehs in groups.items():
                line = f"{gid} {len(vehs)} " + " ".join(map(str, vehs))
                f.write(line + "\n")
                gid += 1
            
            print(f"[UWrMaxSAT] Metadata successfully exported to {filename}.")

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
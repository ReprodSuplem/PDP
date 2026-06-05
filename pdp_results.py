import os
import re
import pandas as pd
import numpy as np

def parse_log_file(filepath):
    filename = os.path.basename(filepath)
    match = re.match(r"pdp_(.*)_r(\d+)v(\d+)k(\d+)_(.*)\.out", filename)
    if not match:
        return None

    instance = match.group(1)
    reqs = int(match.group(2))
    k_val = int(match.group(4))
    method = match.group(5).replace('.wcnf', '') 

    obj = np.nan
    bound = np.nan
    incumbent_time = None
    total_time = None
    is_timeout = False

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

        # Check for explicit timeout indicators in the log
        if re.search(r"Time limit reached", content) or re.search(r"\[UWrMaxSAT\] Timeout", content) or re.search(r"NO feasible solution", content):
            is_timeout = True

        # Extract Objective and Bound based on the solver
        if method == "maxsat":
            obj_match = re.search(r"\[UWrMaxSAT\] OBJ:\s*([\d\.]+)", content)
            if obj_match:
                obj = float(obj_match.group(1))

        elif method == "cpsat":
            obj_match = re.search(r"FINAL OBJ:\s*([\d\.]+)", content)
            if not obj_match:
                obj_match = re.search(r"objective:\s*([\d\.]+)", content)
            bound_match = re.search(r"best_bound:\s*([\d\.]+)", content)
            
            if obj_match: obj = float(obj_match.group(1))
            if bound_match: bound = float(bound_match.group(1))

        elif method in ["hybrid_bc", "full_bc"]:
            obj_bound_match = re.search(r"BEST OBJ:\s*([-\d\.]+).*?BEST BOUND:\s*([-\d\.]+)", content, re.DOTALL)
            opt_match = re.search(r"Optimal objective\s+([\d\.\-]+)", content)
            
            if obj_bound_match:
                o_val = obj_bound_match.group(1)
                b_val = obj_bound_match.group(2)
                if o_val != '-': obj = float(o_val)
                if b_val != '-': bound = float(b_val)
            elif opt_match:
                obj = float(opt_match.group(1))
                bound = obj

        # Extract the time of the best incumbent
        if pd.notna(obj):
            if method == "maxsat":
                matches = re.findall(r"c \[Elapsed time\]\s*([\d\.]+)\s*s\s*c Found solution:\s*([\d\.]+)", content)
                for t_str, o_str in matches:
                    if abs(float(o_str) - obj) < 1e-5:
                        incumbent_time = float(t_str)
                        break
            elif method == "cpsat":
                matches = re.findall(r"\[Incumbent\s*\d+\] Time:\s*([\d\.]+)s\s*\|\s*Obj:\s*([\d\.]+)", content)
                for t_str, o_str in matches:
                    if abs(float(o_str) - obj) < 1e-5:
                        incumbent_time = float(t_str)
                        break
            elif method in ["hybrid_bc", "full_bc"]:
                matches = re.findall(r"\[MIP Incumbent\] Time:\s*([\d\.]+)s\s*\|\s*Obj:\s*([\d\.]+)", content)
                for t_str, o_str in matches:
                    if abs(float(o_str) - obj) < 1e-5:
                        incumbent_time = float(t_str)
                        break

        # Extract the total solver runtime to accurately determine timeout
        if method == "maxsat":
            time_match = re.search(r"CPU time\s*:\s*([\d\.]+)\s*s", content)
            if time_match: total_time = float(time_match.group(1))
        elif method == "cpsat":
            time_match = re.search(r"\[CP-SAT\] Total Runtime:\s*([\d\.]+)\s*sec", content)
            if time_match: total_time = float(time_match.group(1))
        elif method in ["hybrid_bc", "full_bc"]:
            time_match = re.search(r"Runtime:\s*([\d\.]+)\s*sec", content)
            if time_match: total_time = float(time_match.group(1))

        # Finalize timeout logic
        if total_time is not None and total_time >= 3590.0:
            is_timeout = True
            
        # Determine the reporting time
        if incumbent_time is not None:
            time_val = incumbent_time
        elif total_time is not None:
            time_val = total_time
        else:
            time_val = 3600.0 if is_timeout else np.nan

        # Assign bound if optimality was proven
        if not is_timeout and pd.notna(obj) and pd.isna(bound):
            bound = obj

        has_feasible = pd.notna(obj)

    return {
        "Instance": instance,
        "Requests": reqs,
        "K": k_val,
        "Method": method,
        "HasFeasible": has_feasible,
        "Timeout": is_timeout,
        "Objective": obj,
        "BestBound": bound,
        "Time(s)": time_val
    }

def main():
    log_dir = "."
    results = []

    for filename in os.listdir(log_dir):
        if filename.endswith(".out") and filename.startswith("pdp_"):
            filepath = os.path.join(log_dir, filename)
            res = parse_log_file(filepath)
            if res:
                results.append(res)

    df = pd.DataFrame(results)
    if df.empty:
        print("No valid log files found.")
        return

    df = df.sort_values(by=["Instance", "Requests", "K", "Method"])
    df['BKB'] = np.nan
    df['Gap(%)'] = np.nan

    # Dynamic BKB Calculation for Minimization
    for (inst, req, k_val), group in df.groupby(['Instance', 'Requests', 'K']):
        optimal_runs = group[(group['Timeout'] == False) & (group['Objective'].notna())]
        
        if not optimal_runs.empty:
            bkb = optimal_runs['Objective'].min()
        else:
            valid_bounds = group['BestBound'].dropna()
            if not valid_bounds.empty:
                bkb = valid_bounds.max() 
            else:
                bkb = np.nan
                
        df.loc[group.index, 'BKB'] = bkb
        
        for idx in group.index:
            obj = df.loc[idx, 'Objective']
            if pd.notna(obj) and pd.notna(bkb) and obj > 0:
                gap = ((obj - bkb) / obj) * 100.0
                df.loc[idx, 'Gap(%)'] = max(0.0, round(gap, 2))

    cols = ['Instance', 'Requests', 'K', 'Method', 'HasFeasible', 'Timeout', 'Objective', 'BestBound', 'BKB', 'Gap(%)', 'Time(s)']
    df = df[cols]
    
    output_file = "pdp_results.csv"
    df.to_csv(output_file, index=False)

if __name__ == "__main__":
    main()
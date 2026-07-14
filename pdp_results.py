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

        # Check for explicit timeout indicators
        if re.search(r"Time limit reached", content, re.IGNORECASE) or re.search(r"\[UWrMaxSAT\] Timeout", content) or re.search(r"NO feasible solution", content, re.IGNORECASE):
            is_timeout = True

        # Extract Objective and Bound
        if method == "maxsat":
            obj_match = re.search(r"\[UWrMaxSAT\] OBJ:\s*([-\d\.]+)", content)
            if obj_match:
                obj = float(obj_match.group(1))

        elif method == "cpsat":
            obj_match = re.search(r"(?:FINAL OBJ:|objective:)\s*([-\d\.]+)", content, re.IGNORECASE)
            if obj_match: 
                obj = float(obj_match.group(1))
                
            bound_match = re.search(r"(?:best_bound:|best bound)\s*([-\d\.]+)", content, re.IGNORECASE)
            if bound_match: 
                bound = float(bound_match.group(1))
            else:
                inc_bounds = re.findall(r"Bound:\s*([-\d\.]+)", content, re.IGNORECASE)
                if inc_bounds:
                    bound = float(inc_bounds[-1])

        elif method in ["static", "hybrid_bc", "full_bc"]:
            obj_bound_match = re.search(r"(?:BEST OBJ:|Best objective)\s*([-\d\.]+).*?(?:BEST BOUND:|best bound)\s*([-\d\.]+)", content, re.IGNORECASE | re.DOTALL)
            opt_match = re.search(r"Optimal objective\s+([-\d\.]+)", content, re.IGNORECASE)
            
            if obj_bound_match:
                o_val = obj_bound_match.group(1)
                b_val = obj_bound_match.group(2)
                if o_val != '-': obj = float(o_val)
                if b_val != '-': bound = float(b_val)
            elif opt_match:
                obj = float(opt_match.group(1))
                bound = obj

        # Extract Total Time & Incumbent Time
        if method == "maxsat":
            time_match = re.search(r"CPU time\s*:\s*([\d\.]+)\s*s", content)
            if time_match: total_time = float(time_match.group(1))
        elif method == "cpsat":
            time_match = re.search(r"\[CP-SAT\] Total Runtime:\s*([\d\.]+)\s*sec", content, re.IGNORECASE)
            if time_match: total_time = float(time_match.group(1))
        elif method in ["static", "hybrid_bc", "full_bc"]:
            time_match = re.search(r"Runtime:\s*([\d\.]+)\s*sec", content, re.IGNORECASE)
            if time_match: total_time = float(time_match.group(1))

        # Adjust timeout flag based on total time (3600s boundary)
        if total_time is not None and total_time >= 3590.0:
            is_timeout = True
            
        if total_time is None and is_timeout:
            total_time = 3600.0

        # Extract Time to Best Incumbent
        if pd.notna(obj):
            if method == "maxsat":
                matches = re.findall(r"c \[Elapsed time\]\s*([\d\.]+)\s*s\s*c Found solution:\s*([-\d\.]+)", content)
                if matches:
                    incumbent_time = float(matches[-1][0])
                elif re.search(r"c Found solution:", content):
                    incumbent_time = 0.01 
            elif method == "cpsat":
                matches = re.findall(r"\[Incumbent\s*\d+\] Time:\s*([\d\.]+)s", content, re.IGNORECASE)
                if matches:
                    incumbent_time = float(matches[-1])
            elif method in ["static", "hybrid_bc", "full_bc"]:
                matches = re.findall(r"\[(?:MIP )?Incumbent\] Time:\s*([\d\.]+)s", content, re.IGNORECASE)
                if matches:
                    incumbent_time = float(matches[-1])
                        
            if incumbent_time is None and total_time is not None:
                incumbent_time = total_time

        # If it finished optimally, the bound MUST be equal to the objective
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
        "Time_to_Best(s)": incumbent_time,
        "Total_Time(s)": total_time
    }

def main():
    log_dir = "."
    if not os.path.exists(log_dir):
        print(f"Directory '{log_dir}' not found.")
        return

    results = []
    for filename in os.listdir(log_dir):
        if filename.endswith(".out"):
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

    cols = ['Instance', 'Requests', 'K', 'Method', 'HasFeasible', 'Timeout', 
            'Objective', 'BestBound', 'BKB', 'Gap(%)', 'Time_to_Best(s)', 'Total_Time(s)']
    df = df[cols]

    output_csv = "pdp_results.csv"
    df.to_csv(output_csv, index=False)
    print(f"Results successfully saved to {output_csv}")

if __name__ == "__main__":
    main()
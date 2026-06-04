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
    method = match.group(5).replace('.wcnf', '') 

    obj = np.nan
    bound = np.nan
    time_val = np.nan

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

        if method == "maxsat":
            obj_match = re.search(r"\[UWrMaxSAT\] OBJ:\s*([\d\.]+)", content)
            if obj_match:
                obj = float(obj_match.group(1))
            time_match = re.search(r"CPU time\s*:\s*([\d\.]+)\s*s", content)
            if time_match:
                time_val = float(time_match.group(1))

        elif method == "cpsat":
            obj_match = re.search(r"objective:\s*([\d\.]+)", content)
            bound_match = re.search(r"best_bound:\s*([\d\.]+)", content)
            time_match = re.search(r"walltime:\s*([\d\.]+)", content)
            
            if obj_match: obj = float(obj_match.group(1))
            if bound_match: bound = float(bound_match.group(1))
            if time_match: time_val = float(time_match.group(1))

        elif method in ["hybrid_bc", "full_bc"]:
            obj_bound_match = re.search(r"Best objective ([\d\.]+), best bound ([\d\.]+)", content)
            opt_match = re.search(r"Optimal objective\s+([\d\.\-]+)", content)
            
            if obj_bound_match:
                obj = float(obj_bound_match.group(1))
                bound = float(obj_bound_match.group(2))
            elif opt_match:
                obj = float(opt_match.group(1))
                bound = obj
                
            time_match = re.search(r"Explored \d+ nodes .*? in ([\d\.]+) seconds", content)
            if time_match:
                time_val = float(time_match.group(1))

        # Handle timeouts
        if pd.isna(time_val):
            if re.search(r"Time limit reached", content) or re.search(r"\[UWrMaxSAT\] Timeout", content):
                time_val = 3600.0
            else:
                time_val = 3600.0 
                
        # If solved optimally within time limit, bound equals obj
        if time_val < 3590 and pd.notna(obj):
            bound = obj

    return {
        "Instance": instance,
        "Requests": reqs,
        "Method": method,
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

    # Sort and prepare dynamic columns
    df = df.sort_values(by=["Instance", "Requests", "Method"])
    df['BKB'] = np.nan
    df['Gap(%)'] = np.nan

    # Dynamic BKB Calculation for Minimization (Pure PDP)
    for (inst, req), group in df.groupby(['Instance', 'Requests']):
        optimal_runs = group[(group['Time(s)'] < 3590) & (group['Objective'].notna())]
        
        if not optimal_runs.empty:
            bkb = optimal_runs['Objective'].min()
        else:
            valid_bounds = group['BestBound'].dropna()
            if not valid_bounds.empty:
                bkb = valid_bounds.max() # Max Lower Bound
            else:
                bkb = np.nan
                
        df.loc[group.index, 'BKB'] = bkb
        
        for idx in group.index:
            obj = df.loc[idx, 'Objective']
            if pd.notna(obj) and pd.notna(bkb) and obj > 0:
                gap = ((obj - bkb) / obj) * 100.0
                df.loc[idx, 'Gap(%)'] = max(0.0, round(gap, 2))

    # Reorder columns for clean CSV
    cols = ['Instance', 'Requests', 'Method', 'Objective', 'BestBound', 'BKB', 'Gap(%)', 'Time(s)']
    df = df[cols]
    
    output_file = "pdp_results.csv"
    df.to_csv(output_file, index=False)
    print(f"Results successfully parsed and saved to {output_file}")

if __name__ == "__main__":
    main()
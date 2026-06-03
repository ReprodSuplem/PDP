# pdp_results.py

import os
import re
import pandas as pd

def parse_experiments(directory="."):
    """
    Scans the specified directory for solver log files and extracts
    the best objective value and total runtime for each experiment.
    """
    results = []
    
    # Regex to match filenames, e.g.: pdp_lc101_r10v25k3_cpsat.out or pdp_lc101_r10v25k3_maxsat.wcnf.out
    file_pattern = re.compile(
        r"pdp_(?P<inst>[^_]+)_r(?P<req>\d+)v(?P<veh>\d+)k(?P<knn>\d+)_(?P<method>cpsat|full_bc|hybrid_bc|maxsat\.wcnf)\.out"
    )

    if not os.path.exists(directory):
        print(f"[Error] Directory '{directory}' not found.")
        return pd.DataFrame()

    for filename in os.listdir(directory):
        match = file_pattern.match(filename)
        if not match:
            continue
            
        inst = match.group("inst")
        req = int(match.group("req"))
        veh = int(match.group("veh"))
        method = match.group("method").replace(".wcnf", "")
        
        filepath = os.path.join(directory, filename)
        
        obj = None
        time = None
        
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
            if method == "cpsat":
                m_obj = re.search(r"\[CP-SAT\] FINAL OBJ:\s*([\d\.]+)", content)
                m_time = re.search(r"\[CP-SAT\] Total Runtime:\s*([\d\.]+)", content)
                if m_obj: obj = float(m_obj.group(1))
                if m_time: time = float(m_time.group(1))
                    
            elif method in ["full_bc", "hybrid_bc"]:
                # Use re.IGNORECASE to support different naming conventions
                m_obj = re.search(r"\[Gurobi.*?\] BEST OBJ:\s*([0-9\.]+)", content, re.IGNORECASE)
                m_time = re.search(r"\[Gurobi.*?\] Runtime:\s*([\d\.]+)", content, re.IGNORECASE)
                if m_obj: obj = float(m_obj.group(1))
                if m_time: time = float(m_time.group(1))
                    
            elif method == "maxsat":
                m_obj = re.search(r"\[UWrMaxSAT\] OBJ:\s*([\d\.]+)", content)
                m_time = re.search(r"c CPU time\s*:\s*([\d\.]+)\s*s", content)
                if m_obj: obj = float(m_obj.group(1))
                if m_time: time = float(m_time.group(1))
        
        results.append({
            "Instance": inst,
            "Requests": req,
            "Vehicles": veh,
            "Method": method,
            "Objective": obj,
            "Time(s)": time
        })

    return pd.DataFrame(results)

if __name__ == "__main__":
    print("[Parse] Starting log parsing in the current directory...")
    df = parse_experiments(directory=".")
    
    if df.empty:
        print("[Parse] No valid log files found in the current directory.")
        exit(1)

    # Save the flat base data directly to pdp_results.csv
    output_csv = "pdp_results.csv"
    df.sort_values(by=["Instance", "Requests", "Vehicles", "Method"], inplace=True)
    df.to_csv(output_csv, index=False)
    
    print(f"[Parse] Data parsing completed successfully. Results saved to {output_csv}")
import os
import re
import pandas as pd
import numpy as np

def analyze_cvrp_instances(directory="."):
    """
    Scan CVRP instances to extract capacity metrics and analyze the statistical 
    distribution of customer demands.
    """
    results = []
    
    for filename in os.listdir(directory):
        if not filename.endswith(".vrp"):
            continue

        filepath = os.path.join(directory, filename)

        k_match = re.search(r'-k(\d+)', filename, re.IGNORECASE)
        k_veh = int(k_match.group(1)) if k_match else None

        capacity = 0
        demands = []
        reading_demand = False

        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                
                if line.startswith("COMMENT") and k_veh is None:
                    m = re.search(r'trucks:\s*(\d+)', line, re.IGNORECASE)
                    if m:
                        k_veh = int(m.group(1))
                        
                elif line.startswith("CAPACITY"):
                    capacity = int(line.split(":")[1].strip())
                    
                elif line.startswith("DEMAND_SECTION"):
                    reading_demand = True
                    continue
                elif line.startswith("DEPOT_SECTION") or line.startswith("EOF"):
                    reading_demand = False

                if reading_demand:
                    parts = line.split()
                    if len(parts) >= 2:
                        demand_val = int(parts[1])
                        # Exclude depot demand which is strictly 0
                        if demand_val > 0:
                            demands.append(demand_val)

        if k_veh is None:
            print(f"[Error] Vehicle count missing for {filename}. Skipping.")
            continue
            
        if not demands:
            print(f"[Error] No valid demand data found in {filename}. Skipping.")
            continue

        total_capacity = k_veh * capacity
        total_demand = sum(demands)
        target_demand = int(total_capacity * 1.5)
        shortfall = target_demand - total_demand

        # Statistical distribution analysis of the demand values
        demand_series = pd.Series(demands)
        
        results.append({
            "Instance": filename,
            "Vehicles(K)": k_veh,
            "Unit_Cap": capacity,
            "Total_Cap": total_capacity,
            "Orig_Demand": total_demand,
            "Target_Demand(1.5x)": target_demand,
            "Missing_Demand": shortfall,
            "Demand_Mean": round(demand_series.mean(), 2),
            "Demand_Std": round(demand_series.std(), 2),
            "Demand_Min": demand_series.min(),
            "Demand_25%": demand_series.quantile(0.25),
            "Demand_Median": demand_series.median(),
            "Demand_75%": demand_series.quantile(0.75),
            "Demand_Max": demand_series.max()
        })

    df = pd.DataFrame(results)
    if not df.empty:
        df.sort_values(by="Instance", inplace=True)
        print(df.to_string(index=False))
        df.to_csv("cvrp_capacity_analysis.csv", index=False)
        print(f"\n[Success] Analysis saved to cvrp_capacity_analysis.csv. Processed {len(df)} files.")
    else:
        print("[Error] No valid .vrp files found.")

if __name__ == "__main__":
    analyze_cvrp_instances(".")
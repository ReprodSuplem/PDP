# ppdsp_run_exp.py

import os
import glob
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 1. Configuration
# ==========================================
# All 30 instances from the CVRP capacity analysis
INSTANCES = [
    'A-n33-k5', 'A-n33-k6', 'A-n34-k5', 'A-n37-k5', 'A-n38-k5', 
    'A-n39-k6', 'A-n45-k6', 'A-n55-k9', 'A-n61-k9', 'A-n65-k9', 'A-n69-k9', 
    'B-n39-k5', 'B-n41-k6', 'B-n45-k5', 'B-n50-k7', 'B-n51-k7', 'B-n52-k7', 
    'B-n56-k7', 'B-n63-k10', 'B-n64-k9', 'B-n67-k10', 
    'P-n22-k8', 'P-n40-k5', 'P-n45-k5', 'P-n50-k8', 'P-n51-k10', 'P-n55-k15', 
    'P-n60-k15', 'P-n65-k10', 'P-n70-k10'
]

TIME_LIMIT = 3600
MAX_WORKERS = 8 
METHODS = ["cpsat", "maxsat", "hybrid_bc", "full_bc"]

# Global Seed for reproducible empirical generation in PPDSP
GLOBAL_SEED = 42

def generate_data(inst):
    """
    Generate CSVs for the instance using ppdsp_ins_arg.py
    """
    vrp_file = f"{inst}.vrp"
    if not os.path.exists(vrp_file):
        print(f"[Warning] Original benchmark file {vrp_file} not found. Assuming CSVs exist.")
        return

    print(f"--- Generating Data for {inst} (Seed: {GLOBAL_SEED}) ---")
    cmd = f"python ppdsp_ins_arg.py {vrp_file} . {GLOBAL_SEED}"
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_task(cmd):
    print(f"Started: {cmd}")
    start_time = time.time()
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        status = "Success"
    except subprocess.CalledProcessError:
        status = "Failed"
    elapsed = time.time() - start_time
    print(f"Finished: {cmd} | Status: {status} | Time: {elapsed:.2f}s")

def main():
    inst_to_req = {}
    
    # Step 1: Pre-generate all data files and dynamically discover the exact request counts
    print("========== STEP 1: DATA GENERATION & DISCOVERY ==========")
    for inst in INSTANCES:
        generate_data(inst)
        
        # Dynamically find the generated requestInfo file to parse the true request count
        pattern = f"requestInfo*_{inst}.csv"
        matching_files = glob.glob(pattern)
        if matching_files:
            filename = os.path.basename(matching_files[0])
            try:
                # Extract the number from 'requestInfoX_...'
                req_num = int(filename.replace("requestInfo", "").split("_")[0])
                inst_to_req[inst] = req_num
                print(f"  [Discovered] {inst} -> Generated exact selection pool size: {req_num}")
            except ValueError:
                print(f"  [Error] Could not parse request count from {filename}")
        else:
            print(f"  [Warning] No requestInfo file found for {inst} after generation.")

    # Step 2: Queue tasks using the discovered true pool sizes
    print("\n========== STEP 2: SOLVER TASK QUEUING ==========")
    tasks = []
    for inst, req in inst_to_req.items():
        for method in METHODS:
            if method == "maxsat":
                cmd = f"python ppdsp_main.py sat {inst} {req} --time {TIME_LIMIT}"
            elif method == "cpsat":
                cmd = f"python ppdsp_main.py cpsat {inst} {req} --time {TIME_LIMIT}"
            elif method == "hybrid_bc":
                cmd = f"python ppdsp_main.py mip {inst} {req} --mip_strategy hybrid --time {TIME_LIMIT}"
            elif method == "full_bc":
                cmd = f"python ppdsp_main.py mip {inst} {req} --mip_strategy full --time {TIME_LIMIT}"
            else:
                continue
            tasks.append(cmd)

    print(f"\nTotal tasks queued: {len(tasks)} ({len(inst_to_req)} instances x {len(METHODS)} solvers)")
    print(f"Starting parallel execution with {MAX_WORKERS} workers...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(run_task, tasks)

    print("\nAll PPDSP experiments completed successfully.")
    print("Triggering results compilation...")
    subprocess.run("python ppdsp_results.py", shell=True)

if __name__ == "__main__":
    main()
# ppdsp_run_exp.py

import os
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

# Extract request sizes dynamically based on the instance name (n - 1)
def get_req_sizes(inst):
    # Example: 'P-n40-k5' -> 39 requests total. We test 25%, 50%, 75%, 100% sizes.
    try:
        n_val = int(inst.split('-')[1][1:])
        max_req = n_val - 1
        return [int(max_req * 0.25), int(max_req * 0.5), int(max_req * 0.75), max_req]
    except Exception:
        return [10, 20, 30] # Fallback if parsing fails

TIME_LIMIT = 3600
MAX_WORKERS = 12
METHODS = ["cpsat", "maxsat", "hybrid_bc", "full_bc"]

# Global Seed for reproducible empirical generation in PPDSP
GLOBAL_SEED = 42

def generate_data(inst, req_sizes):
    """
    Generate CSVs for the instance using ppdsp_ins_arg.py
    Since generation takes the original .vrp file, we append it here.
    """
    vrp_file = f"{inst}.vrp"
    if not os.path.exists(vrp_file):
        print(f"[Warning] Original benchmark file {vrp_file} not found. Assuming CSVs exist.")
        return

    print(f"--- Generating Data for {inst} (Seed: {GLOBAL_SEED}) ---")
    # Using the updated signature of ppdsp_ins_arg.py which accepts seed
    cmd = f"python ppdsp_ins_arg.py {vrp_file} . {GLOBAL_SEED}"
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL)

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
    tasks = []
    for inst in INSTANCES:
        req_sizes = get_req_sizes(inst)
        
        # Step 1: Pre-generate all CSV combinations for this instance
        generate_data(inst, req_sizes)
        
        # Step 2: Queue the exact solver commands
        for req in req_sizes:
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

    print(f"\nTotal tasks queued: {len(tasks)}")
    print(f"Starting execution with {MAX_WORKERS} workers...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(run_task, tasks)

    print("\nAll experiments completed.")
    print("Triggering results compilation...")
    subprocess.run("python ppdsp_results.py", shell=True)

if __name__ == "__main__":
    main()
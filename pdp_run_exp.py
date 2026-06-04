# pdp_run_exp.py

import os
import sys
import subprocess
import concurrent.futures
import threading

# ==========================================
# Global Experiment Configuration
# ==========================================
INSTANCES = ["lc101", "lr101", "lrc101"]
TIME_LIMIT = 3600
MAX_WORKERS = 12
K_VALUES = [3, 4, 5]

progress_lock = threading.Lock()
completed_tasks = 0
total_tasks = 0

# ==========================================
# Phase 1: Data Preparation
# ==========================================
def prepare_data_and_get_tasks():
    tasks = []
    print("\n[Phase 1: Data Prep] Generating data from benchmark files...")
    
    for ins in INSTANCES:
        txt_file = f"{ins}.txt"
        if not os.path.exists(txt_file):
            print(f"  [Error] Benchmark file not found: {txt_file}")
            sys.exit(1)
            
        for k in K_VALUES:
            print(f"  -> Slicing and processing {txt_file} for K={k}...")
            try:
                subprocess.run(
                    f"python pdp_ins_arg.py {txt_file} . {k}", 
                    shell=True, 
                    check=True,
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
            except subprocess.CalledProcessError:
                print(f"  [Error] Failed to generate data for {txt_file} at K={k}")
                sys.exit(1)
            
        req_sizes = set()
        for filename in os.listdir("."):
            if filename.startswith("requestInfo") and filename.endswith(f"_{ins}.csv"):
                size_str = filename.replace("requestInfo", "").replace(f"_{ins}.csv", "")
                try:
                    req_sizes.add(int(size_str))
                except ValueError:
                    continue
                    
        for req in sorted(list(req_sizes)):
            for k in K_VALUES:
                tasks.append((ins, req, k))
            
    print(f"[Phase 1 Complete] Found {len(tasks)} instance-size-k combinations.\n")
    return tasks

# ==========================================
# Phase 2: Task Building
# ==========================================
def build_commands(task_list):
    cmds = []
    for ins, req, k in task_list:
        cmds.append(f"python pdp_main.py mip {ins} {req} --knn {k} --mip_strategy hybrid --time {TIME_LIMIT}")
        cmds.append(f"python pdp_main.py mip {ins} {req} --knn {k} --mip_strategy full --time {TIME_LIMIT}")
        cmds.append(f"python pdp_main.py cpsat {ins} {req} --knn {k} --time {TIME_LIMIT}")
        cmds.append(f"python pdp_main.py sat {ins} {req} --knn {k} --time {TIME_LIMIT}")
    return cmds

def worker(cmd):
    global completed_tasks
    try:
        subprocess.run(
            cmd, 
            shell=True, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        with progress_lock:
            print(f"[Error] Task execution failed: {cmd}\nReason: {e}")
    finally:
        with progress_lock:
            completed_tasks += 1
            print(f"[{completed_tasks:03d}/{total_tasks:03d}] Finished: {cmd}")

# ==========================================
# Phase 3: Results Parsing
# ==========================================
def parse_and_export_results():
    print("\n[Phase 3: Results Parsing] Collecting data from log files...")
    try:
        subprocess.run(
            f"python pdp_results.py", 
            shell=True, 
            check=True
        )
        print("[Phase 3 Complete] Results successfully exported to pdp_results.csv")
    except Exception as e:
        print(f"[Warning] Failed to run pdp_results.py automatically. Error: {e}")

# ==========================================
# Main Orchestrator
# ==========================================
if __name__ == "__main__":
    print("==================================================")
    print("  PDP Full Ablation Experiment Pipeline")
    print("==================================================")
    
    task_combinations = prepare_data_and_get_tasks()
    commands = build_commands(task_combinations)
    total_tasks = len(commands)
    
    print("==================================================")
    print(f"  Total Tasks : {total_tasks}")
    print(f"  Time Limit  : {TIME_LIMIT}s per task")
    print(f"  Concurrency : {MAX_WORKERS} cores")
    print("==================================================\n")
    
    print("[Phase 2: Execution] Starting process pool...\n")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(worker, cmd) for cmd in commands]
        concurrent.futures.wait(futures)
        
    print("\n[Phase 2 Complete] All solver tasks finished.")
    parse_and_export_results()
    
    print("\n==================================================")
    print("  All pipeline stages have been successfully completed.")
    print("==================================================")
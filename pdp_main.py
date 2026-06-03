# pdp_main.py

import sys
import os
import glob
import argparse

from pdp_mip import PDP_MIP
from pdp_maxsat import PDP_MaxSAT
from pdp_cpsat import PDP_CPSAT

def main():
    parser = argparse.ArgumentParser(description="Exact Solvers Testbed for Pure PDP")
    parser.add_argument("solver", choices=["mip", "sat", "cpsat"], help="Choose the exact solver")
    parser.add_argument("--mip_strategy", type=str, choices=['hybrid', 'full'], default='hybrid', 
                    help="Choose Benders Cut strategy for MIP: 'hybrid' (MTZ+Cap) or 'full' (Pure Lazy)")
    parser.add_argument("instance", type=str, help="Benchmark name without extension (e.g., lc101)")
    parser.add_argument("reqs", type=int, help="Number of truncated requests to test (e.g., 20, 35)")
    parser.add_argument("--vehs", type=int, default=None, help="Override benchmark global fleet size (optional)")
    parser.add_argument("--cap", type=int, default=None, help="Override benchmark global capacity (optional)")
    parser.add_argument("--knn", type=int, default=3, help="k-NN sparsification factor (default: 3)")
    parser.add_argument("--time", type=int, default=3600, help="Time limit in seconds (default: 3600)")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    pdp_name = args.instance.replace('.txt', '')
    
    # Automatically detect vehicle count from generated CSVs if not provided
    num_vehs = args.vehs
    if num_vehs is None:
        pattern = f"vehicleInfo*_{pdp_name}.csv"
        matching_files = glob.glob(pattern)
        if matching_files:
            try:
                # Extract the integer between 'vehicleInfo' and '_'
                filename = os.path.basename(matching_files[0])
                num_vehs_str = filename.replace("vehicleInfo", "").split("_")[0]
                num_vehs = int(num_vehs_str)
            except ValueError:
                pass

    if num_vehs is None:
        print(f"[Error] Could not automatically detect vehicle count for {pdp_name}. Please specify --vehs.")
        sys.exit(1)
        
    # Note: capacity is left as None or user-provided. 
    # pdp_ins_gen.py will load the true capacity directly from the vehicleInfo CSV.
    capacity = args.cap if args.cap is not None else -1 

    print("\n==================================================")
    print(f"  PDP Exact Solver: {args.solver.upper()}")
    print(f"  Instance: {pdp_name} | Requests: {args.reqs}")
    print(f"  Fleet: {num_vehs} Vehicles | Fallback Cap: {'CSV Data' if capacity == -1 else capacity}")
    print(f"  Graph: {args.knn}-NN | Time Limit: {args.time}s")
    if args.solver == "mip":
        print(f"  MIP Strategy: {args.mip_strategy.upper()}")
    print("==================================================\n")

    if args.solver == "mip":
        solver = PDP_MIP(
            pdpName=pdp_name, 
            num_reqs=args.reqs, 
            num_vehs=num_vehs, 
            capacity=capacity, 
            knn=args.knn,
            bc_strategy=args.mip_strategy
        )
        solver.solve(time_limit=args.time)

    elif args.solver == "sat":
        solver = PDP_MaxSAT(
            pdpName=pdp_name, 
            num_reqs=args.reqs, 
            num_vehs=num_vehs, 
            capacity=capacity, 
            knn=args.knn
        )
        solver.genMaxsatFormular()
        solver.solve(time_limit=args.time)

    elif args.solver == "cpsat":
        solver = PDP_CPSAT(
            pdpName=pdp_name, 
            num_reqs=args.reqs, 
            num_vehs=num_vehs, 
            capacity=capacity, 
            knn=args.knn
        )
        solver.solve(time_limit=args.time)

if __name__ == "__main__":
    main()
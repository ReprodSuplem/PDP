# ppdsp_ins_arg.py

import sys
import os
import math
import re
import pandas as pd
import networkx as nx
import random
from typing import List, Tuple

def my_round_int(x: float) -> int:
    return int((x * 2 + 1) // 2)

def extract_cvrp_meta(filepath: str) -> Tuple[int, int, List[int]]:
    """
    Parse a CVRP file to extract vehicle count, unit capacity, and all non-zero demands.
    """
    k_veh = 0
    capacity = 0
    demands = []
    
    k_match = re.search(r'-k(\d+)', filepath, re.IGNORECASE)
    if k_match:
        k_veh = int(k_match.group(1))

    reading_demands = False
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
                
            if line.startswith("COMMENT") and k_veh == 0:
                m = re.search(r'trucks:\s*(\d+)', line, re.IGNORECASE)
                if m: k_veh = int(m.group(1))
            elif line.startswith("CAPACITY"):
                capacity = int(line.split(":")[1].strip())
            elif line.startswith("DEMAND_SECTION"):
                reading_demands = True
                continue
            elif line.startswith("DEPOT_SECTION") or line.startswith("EOF"):
                reading_demands = False
                continue
                
            if reading_demands:
                parts = line.split()
                if len(parts) >= 2:
                    val = int(parts[1])
                    if val > 0:
                        demands.append(val)
                        
    return k_veh, capacity, demands

def read_cvrp_coords(filepath: str) -> Tuple[List[Tuple[float, float]], str]:
    """
    Read CVRPLib (.vrp) file and return standardized coordinates list.
    Ensures Depot is explicitly moved to the END of the list.
    Coordinates are scaled to TARGET_MAX = 2000.0 for solver efficiency.
    """
    raw_coords = []
    node_map = {}
    
    with open(filepath, 'r') as f:
        lines = f.read().splitlines()
        
    reading_coord = False
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line.startswith("NODE_COORD_SECTION"):
            reading_coord = True
            continue
        elif line.startswith("DEMAND_SECTION") or line.startswith("DEPOT_SECTION") or line.startswith("EOF"):
            reading_coord = False
            continue
        
        if reading_coord:
            parts = line.split()
            if len(parts) >= 3:
                nid = int(parts[0])
                x = float(parts[1])
                y = float(parts[2])
                node_map[nid] = [x, y]
    
    sorted_ids = sorted(node_map.keys())
    if 1 in sorted_ids:
        for nid in sorted_ids:
            if nid != 1: raw_coords.append(node_map[nid])
        raw_coords.append(node_map[1])
    else:
        for nid in sorted_ids: raw_coords.append(node_map[nid])

    TARGET_MAX = 2000.0
    max_val = 0.0
    for coord in raw_coords:
        max_val = max(max_val, abs(coord[0]), abs(coord[1]))
    
    scale_factor = 1.0
    if max_val > 0:
        scale_factor = TARGET_MAX / max_val
        
    coords = []
    for coord in raw_coords:
        scaled_x = coord[0] * scale_factor
        scaled_y = coord[1] * scale_factor
        coords.append([scaled_x, scaled_y])

    instance_name = os.path.basename(filepath).replace('.vrp', '')
    return coords, instance_name

def gen_request_list(coords: List[Tuple[float, float]], demands_pool: List[int], target_total_demand: int, seed: int = None) -> List[List[int]]:
    """
    Generate PPDSP requests using Empirical Sampling from the CVRP demand pool.
    Guarantees every original demand (and thus corresponding node) appears at least once.
    Implements profit mapping.
    """
    if seed is not None:
        random.seed(seed)

    current_total = 0
    final_demands = []
    
    # Guarantee phase: pre-load all original demands to ensure coverage
    for d in demands_pool:
        final_demands.append(d)
        current_total += d

    # Sampling phase: fill the remaining capacity up to the target
    while current_total < target_total_demand:
        sampled_demand = random.choice(demands_pool)
        if current_total + sampled_demand > target_total_demand * 1.05 and len(final_demands) > len(demands_pool):
            continue
        final_demands.append(sampled_demand)
        current_total += sampled_demand

    avg_demand = sum(final_demands) / len(final_demands)
    lenOfCoord = len(coords)
    
    sumOfDistance = 0
    for i in range(lenOfCoord):
        for j in range(i+1, lenOfCoord):
            sumOfDistance += my_round_int(math.dist(coords[i], coords[j]))
    avgDistance = my_round_int(sumOfDistance / (lenOfCoord * (lenOfCoord-1) / 2))

    requestList = []
    customer_indices = list(range(lenOfCoord - 1)) # Explicitly excludes the depot (last index)

    for demand in final_demands:
        pickup, dropoff = random.sample(customer_indices, 2)
        
        pd_dist = math.dist(coords[pickup], coords[dropoff])
        base_reward = avgDistance * 2.0
        volume_factor = 1.0 + (demand / avg_demand)
        raw_profit = (pd_dist + base_reward) * volume_factor
        rand_factor = random.uniform(0.9, 1.1)
        
        profit = my_round_int(raw_profit * rand_factor)
        
        requestList.append([profit, demand, pickup, dropoff])
        
    return requestList

def write_nodes_csv(coords: List[Tuple[float, float]], instance_name: str, outDir: str = "."):
    df = pd.DataFrame(coords)
    df.to_csv(f'{outDir}/2DNode_{instance_name}.csv', header=False, index=False)

def write_request_csvs(requestList: List[List[int]], instance_name: str, outDir: str = "."):
    """
    Export the generated request list to CSV.
    """
    total_reqs = len(requestList)
    df = pd.DataFrame(requestList)
    df.to_csv(f'{outDir}/requestInfo{total_reqs}_{instance_name}.csv', header=False, index=False)
    return total_reqs

def gen_adj_matrs(coords: List[Tuple[float, float]], start_k: int, sizeOfGList: int, skip: int, instance_name: str, outDir: str = "."):
    lenOfCoord = len(coords)
    depot_idx = lenOfCoord - 1
    
    G_complete = nx.Graph()
    all_dists = [[0]*lenOfCoord for _ in range(lenOfCoord)]
    
    for i in range(lenOfCoord):
        all_dists[i][i] = (0, i)
        for j in range(i + 1, lenOfCoord):
            dist = my_round_int(math.dist(coords[i], coords[j]))
            G_complete.add_edge(i, j, weight=dist)
            all_dists[i][j] = (dist, j)
            all_dists[j][i] = (dist, i)

    mst_edges = set(nx.minimum_spanning_edges(G_complete, algorithm="kruskal", data=False))

    for iter_idx in range(sizeOfGList):
        current_k = int(start_k + iter_idx * skip)
        adjMatrix = [[0]*lenOfCoord for _ in range(lenOfCoord)]
            
        for i in range(lenOfCoord):
            neighbors = sorted(all_dists[i], key=lambda x: x[0])
            limit = min(lenOfCoord, current_k + 1)
            for rank in range(1, limit):
                target_node = neighbors[rank][1]
                adjMatrix[i][target_node] = 1
                adjMatrix[target_node][i] = 1

        for u, v in mst_edges:
            adjMatrix[u][v] = 1
            adjMatrix[v][u] = 1

        for i in range(lenOfCoord):
            adjMatrix[depot_idx][i] = 1
            adjMatrix[i][depot_idx] = 1
            adjMatrix[i][i] = 0

        df = pd.DataFrame(adjMatrix)
        df.to_csv(f'{outDir}/adjMatrx{current_k}_{instance_name}.csv', header=False, index=False)

def gen_vehic_caps(k_veh: int, capacity: int, instance_name: str, outDir: str = "."):
    """
    Generate vehicleInfo CSV strictly respecting the original CVRP fleet size and capacity.
    Cost factor is kept at 1.0 for homogeneous settings.
    """
    vehicleList = []
    for i in range(k_veh):
        vehicleList.append([i, capacity, 1.0])
        
    csv_filename = f'{outDir}/vehicleInfo{k_veh}_{instance_name}.csv'
    df = pd.DataFrame(vehicleList, columns=['VehicleID', 'Capacity', 'CostFactor'])
    df.to_csv(csv_filename, index=False)

def gen_all_ins_arg(filepath: str, outDir: str = ".", seed: int = 42, k_nn: int = 3):
    """
    Master Pipeline: Generates PPDSP benchmark files strictly derived from CVRP instances.
    """
    print(f"[Info] Processing CVRP into PPDSP: {filepath}")
    
    k_veh, capacity, demands_pool = extract_cvrp_meta(filepath)
    if k_veh == 0 or not demands_pool:
        print(f"[Error] Failed to extract valid metadata from {filepath}.")
        sys.exit(1)
        
    target_demand = int(k_veh * capacity * 1.5)
    
    coords, instance_name = read_cvrp_coords(filepath)
    
    write_nodes_csv(coords, instance_name, outDir=outDir)
    gen_adj_matrs(coords, start_k=k_nn, sizeOfGList=1, skip=1, instance_name=instance_name, outDir=outDir)
    gen_vehic_caps(k_veh, capacity, instance_name, outDir=outDir)
    
    requestList = gen_request_list(coords, demands_pool, target_demand, seed=seed)
    total_reqs = write_request_csvs(requestList, instance_name, outDir=outDir)
    
    print(f"  -> Generated {total_reqs} requests.")
    print(f"  -> Fleet: {k_veh} vehicles, Unit Capacity: {capacity}")
    print(f"  -> Total Capacity: {k_veh * capacity}, Target Demand: {target_demand}")
    print(f"[Success] All files generated successfully for {instance_name}.\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ppdsp_ins_arg.py <file.vrp> [outDir] [seed] [k_nn]")
        sys.exit(1)
    
    vrp_file = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
        
    seed_val = 42
    if len(sys.argv) > 3:
        try:
            seed_val = int(sys.argv[3])
        except ValueError:
            pass
            
    k_val = 3
    if len(sys.argv) > 4:
        try:
            k_val = int(sys.argv[4])
        except ValueError:
            print(f"[Warning] Invalid k_nn argument '{sys.argv[4]}', defaulting to 3")

    random.seed(seed_val)
    print(f"[Init] Global Random Seed set to {seed_val} | K-NN set to {k_val}")

    gen_all_ins_arg(vrp_file, outDir=out_dir, seed=seed_val, k_nn=k_val)
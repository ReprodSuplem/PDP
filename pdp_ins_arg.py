# pdp_ins_arg.py

import sys
import math
import pandas as pd
import networkx as nx
from typing import List

def my_round_int(x: float) -> int:
    """
    Round a float to the nearest integer (half-up).
    """
    return int((x * 2 + 1) // 2)

def process_pdp_benchmark(filepath: str, k_nn: int = 3, outDir: str = "."):
    """
    Parses a standard Li & Lim PDP benchmark file (.txt). 
    Features:
    1. Extracts homogeneous vehicle fleet constraints directly from the benchmark.
    2. Generates vehicle configurations for solver consumption.
    3. Performs location-based compression to deduplicate spatial coordinates.
    4. Extracts delivery requests (Demand, Pickup, Delivery).
    5. Generates k-NN + MST sparsified adjacency matrices.
    6. Generates tiered sub-instances (e.g., 10, 20, 30...) WITHOUT altering the fleet size.
    """
    print(f"[Info] Processing Pure PDP Benchmark: {filepath}")
    
    try:
        with open(filepath, 'r') as f:
            lines = [list(map(float, line.strip().split())) for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        print(f"[Error] File not found: {filepath}")
        sys.exit(1)

    # 1. Read fleet information from the first line
    # The solver will use these exact values globally.
    total_vehs = int(lines[0][0])
    cap = int(lines[0][1]) 
    print(f"  -> Benchmark Global Fleet: {total_vehs} vehicles, Capacity: {cap}")

    pdpName = filepath.split('/')[-1].replace('.txt', '')

    # 2. Generate vehicleInfo CSV
    vehicle_data = []
    for v in range(total_vehs):
        vehicle_data.append([v, cap, 1.0])
        
    df_veh = pd.DataFrame(vehicle_data, columns=['VehicleID', 'Capacity', 'CostFactor'])
    vehicle_file_path = f"{outDir}/vehicleInfo{total_vehs}_{pdpName}.csv"
    df_veh.to_csv(vehicle_file_path, index=False)
    print(f"  -> Generated Vehicle Info: {vehicle_file_path}")

    orig_to_new = {}
    coord_to_new = {}
    customer_coords = []
    
    depot_x, depot_y = lines[1][1], lines[1][2]
    
    # 3. Coordinate deduplication (Location-based Compression)
    for line in lines[2:]:
        orig_id = int(line[0])
        x, y = line[1], line[2]
        if (x, y) not in coord_to_new:
            new_id = len(customer_coords)
            customer_coords.append([x, y])
            coord_to_new[(x, y)] = new_id
        orig_to_new[orig_id] = coord_to_new[(x, y)]

    # 4. Append the Depot to the end of the coordinate list
    depot_new_id = len(customer_coords)
    coords = customer_coords + [[depot_x, depot_y]]
    coord_to_new[(depot_x, depot_y)] = depot_new_id
    orig_to_new[0] = depot_new_id

    lenOfCoord = len(coords)

    # 5. Extract delivery requests
    all_requests = []
    for line in lines[2:]:
        delivery_id = int(line[8])
        if delivery_id != 0: # Indicates a Pickup node line
            orig_id = int(line[0])
            demand = int(line[3])
            pickup_new = orig_to_new[orig_id]
            delivery_new = orig_to_new[delivery_id]
            
            # Pure PDP format: [Demand, Pickup Node, Delivery Node]
            all_requests.append([demand, pickup_new, delivery_new])

    # A. Export Node Coordinates to CSV
    df_nodes = pd.DataFrame(coords)
    df_nodes.to_csv(f'{outDir}/2DNode_{pdpName}.csv', header=False, index=False)

    # B. Generate k-NN + MST Sparsified Adjacency Matrix
    print(f"  -> Generating {k_nn}-NN Sparsified Adjacency Matrix...")
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
    
    adjMatrix = [[0]*lenOfCoord for _ in range(lenOfCoord)]
    
    for i in range(lenOfCoord):
        neighbors = sorted(all_dists[i], key=lambda x: x[0])
        limit = min(lenOfCoord, k_nn + 1)
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

    df_adj = pd.DataFrame(adjMatrix)
    df_adj.to_csv(f'{outDir}/adjMatrx{k_nn}_{pdpName}.csv', header=False, index=False)

    # C. Dynamically generate tiered sub-instances for scalability testing
    total_reqs = len(all_requests)
    cutLens = []
    
    for step in range(10, total_reqs, 10):
        if total_reqs - step <= 5:
            break
        cutLens.append(step)

    if total_reqs not in cutLens or not cutLens:
        cutLens.append(total_reqs)

    for length in cutLens:
        current_requests = all_requests[:length]
        
        # Export truncated Request CSV
        df_req = pd.DataFrame(current_requests)
        df_req.to_csv(f'{outDir}/requestInfo{length}_{pdpName}.csv', header=False, index=False)
        
        print(f"  -> Generated Sub-instance Tier: {length} Requests. (Note: Solver must use global T={total_vehs}, Q={cap})")

    print(f"[Success] {pdpName}: Compressed to {lenOfCoord} unique locations. (K={k_nn})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdp_ins_arg.py <benchmark.txt> [outDir] [k_nn]")
        sys.exit(1)
        
    file_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    
    k_val = 3
    if len(sys.argv) > 3:
        try:
            k_val = int(sys.argv[3])
        except ValueError:
            print(f"[Warning] Invalid k_nn argument '{sys.argv[3]}', defaulting to 3")

    process_pdp_benchmark(file_path, k_nn=k_val, outDir=out_dir)
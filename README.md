# Exact Solvers for Pickup and Delivery Problems

This repository contains the source code, data generation scripts, and exact solver implementations for two variations of routing problems:
1. **PDP**: The standard Pickup and Delivery Problem (minimizing total routing cost while satisfying all requests).
2. **PPDSP**: The Profit-Maximizing Pickup and Delivery Selection Problem (maximizing the difference between collected profit and routing cost under capacity constraints).

The codebase provides a unified framework to evaluate three state-of-the-art exact solving paradigms: Mixed Integer Programming (MIP), Constraint Programming (CP-SAT), and Maximum Satisfiability (MaxSAT). It is designed to facilitate academic research and ensure strict reproducibility of the experimental results presented in our paper.

## Dependencies

To run the scripts and solvers, ensure you have the following dependencies installed in your Python environment (Python 3.8+ recommended):

- `gurobipy` (Requires a valid Gurobi license)
- `ortools` (Google OR-Tools for CP-SAT)
- `python-sat` (PySAT toolkit)
- `networkx`
- `pandas`
- `tsplib95`

**External Solver Requirement:**
The MaxSAT models rely on `uwrmaxsat`. You must compile `uwrmaxsat` and ensure its executable is available in your system's `PATH`.

## Repository Structure

The repository is strictly divided into two parallel suites ensuring structural symmetry. 

### Pure PDP Suite
- `pdp_ins_arg.py`: Parses TSPLIB/CVRPLib instances, applies k-NN sparsification, and generates standardized CSV files.
- `pdp_ins_gen.py`: Base class that reads CSV data and builds global variable ID pools for solvers.
- `pdp_utils.py`: Helper functions for solution decoding, route validation, and metadata exporting.
- `pdp_mip.py`: Gurobi MIP solver featuring Benders Decomposition (supports both 'hybrid' MTZ+Lazy and 'full' Lazy strategies).
- `pdp_cpsat.py`: Google OR-Tools CP-SAT solver implementation.
- `pdp_maxsat.py`: MaxSAT solver utilizing Order Encoding and valid inequalities.
- `pdp_main.py`: Command-line interface for testing individual instances.
- `pdp_run_exp.py`: Multiprocessing orchestrator for executing large-scale batch experiments.
- `pdp_results.py`: Log parser that extracts objective values and runtimes into aggregated CSV reports.

### PPDSP Suite
- `ppdsp_ins_arg.py`: Extended data generator featuring empirical demand sampling and profit mapping mechanisms.
- `ppdsp_ins_gen.py`: Base class adapted for the 4D request structure of PPDSP.
- `ppdsp_utils.py`: Adapted helper functions for profit-cost evaluation and PPDSP metadata mapping.
- `ppdsp_mip.py`: Adapted Gurobi solver maximizing net profit with relaxed assignment constraints.
- `ppdsp_cpsat.py`: Adapted CP-SAT solver for profit maximization.
- `ppdsp_maxsat.py`: Adapted MaxSAT solver utilizing weighted soft clauses for profit and routing costs.
- `ppdsp_main.py`: Command-line interface for testing individual instances.
- `ppdsp_run_exp.py`: Multiprocessing orchestrator for executing large-scale batch experiments.
- `ppdsp_results.py`: Log parser that extracts objective values and runtimes into aggregated CSV reports.

## Usage Guide

The workflow is identical for both PDP and PPDSP suites. The instructions below use the PPDSP suite as the primary example. To evaluate the Pure PDP models, simply replace the `ppdsp_` prefix with `pdp_`.

### 1. Data Generation

Before running any solver, the raw benchmark instances must be converted into solver-ready CSV matrices.

```bash
# Usage: python ppdsp_ins_arg.py <benchmark_file> [output_directory] [seed]
python ppdsp_ins_arg.py P-n22-k8.vrp . 42
```
This script will automatically detect the fleet size, apply a 1.5x capacity target (for PPDSP), and generate files such as `2DNode_...csv`, `adjMatrx3_...csv`, `requestInfo...csv`, and `vehicleInfo...csv`.

### 2. Single Instance Evaluation

Use the main interface to test specific instances and solver configurations. The script automatically detects the generated CSV files in the directory.

```bash
# Test CP-SAT solver
python ppdsp_main.py cpsat P-n22-k8 35 --time 3600

# Test MaxSAT solver
python ppdsp_main.py sat P-n22-k8 35 --time 3600

# Test MIP solver (using hybrid Benders strategy)
python ppdsp_main.py mip P-n22-k8 35 --mip_strategy hybrid --time 3600
```

**Positional Arguments:**
- `solver`: Choice of exact engine (`mip`, `sat`, `cpsat`).
- `instance`: Name of the benchmark instance without extension (e.g., `P-n22-k8`).
- `reqs`: Number of requests to evaluate (matches the generated CSV request count).

**Optional Arguments:**
- `--time`: Time limit in seconds (default: 3600).
- `--knn`: k-NN sparsification factor used during generation (default: 3).
- `--mip_strategy`: Benders cut strategy for Gurobi (`hybrid` or `full`).

### 3. Reproducing Paper Experiments

To reproduce the comprehensive computational results presented in our paper, utilize the automated experiment pipeline.

1. Configure the `INSTANCES`, `TIME_LIMIT`, and `MAX_WORKERS` variables at the top of `ppdsp_run_exp.py`.
2. Execute the script:
```bash
python ppdsp_run_exp.py
```
3. The script executes the following automated pipeline:
   - Identifies all target benchmarks.
   - Invokes `ppdsp_ins_arg.py` to generate the structural CSVs.
   - Constructs execution commands for all solvers (`mip`, `sat`, `cpsat`) across all generated request sizes.
   - Dispatches tasks utilizing a thread pool for parallel execution.
   - Routes solver outputs to designated `.out` log files.
   - Automatically triggers `ppdsp_results.py` upon completion.
4. Review the final `ppdsp_results.csv` (or `pdp_results.csv`) for the compiled benchmark report, which includes instance details, solver types, final objective values, and CPU runtimes.
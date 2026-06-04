#!/bin/bash

# master_run.sh
# Master script to run PDP and PPDSP experiments sequentially.

echo "=================================================="
echo "  Master Experiment Pipeline Started"
echo "  Time: $(date)"
echo "=================================================="

# ------------------------------------------------
# Step 1: Run Pure PDP Experiments
# ------------------------------------------------
echo ""
echo ">>> [Step 1] Transitioning to PDP directory..."
cd ~/exp/PDP || { echo "Failed to enter PDP directory"; exit 1; }

echo ">>> Starting pdp_run_exp.py..."
# Run the script. If it fails, the master script stops to prevent cascading errors.
python pdp_run_exp.py
if [ $? -ne 0 ]; then
    echo "[Error] pdp_run_exp.py encountered a fatal error. Aborting pipeline."
    exit 1
fi
echo ">>> PDP Experiments Completed Successfully at $(date)."

# ------------------------------------------------
# Step 2: Run PPDSP Experiments
# ------------------------------------------------
echo ""
echo ">>> [Step 2] Transitioning to PPDSP directory..."
cd ~/exp/PDP/PPDSP || { echo "Failed to enter PPDSP directory"; exit 1; }

echo ">>> Starting ppdsp_run_exp.py..."
python ppdsp_run_exp.py
if [ $? -ne 0 ]; then
    echo "[Error] ppdsp_run_exp.py encountered a fatal error. Aborting pipeline."
    exit 1
fi
echo ">>> PPDSP Experiments Completed Successfully at $(date)."

# ------------------------------------------------
# Done
# ------------------------------------------------
echo ""
echo "=================================================="
echo "  ALL EXPERIMENTS COMPLETED SUCCESSFULLY!"
echo "  Time: $(date)"
echo "=================================================="
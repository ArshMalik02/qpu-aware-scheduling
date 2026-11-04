#!/bin/bash
#SBATCH --job-name=aer_bell
#SBATCH --gres=qpu:1
#SBATCH -c1
#SBATCH --mem=500M
#SBATCH --time=00:05:00
#SBATCH -o /data/jobs/out/aer_bell_%j.out
# --mem is required: with DefMemPerNode=UNLIMITED one job would take a whole node.
# The qpu GRES is a Slurm counter only; the circuit runs on Aer (CPU). SIMULATED.
set -euo pipefail
echo "host=$(hostname) arch=$(uname -m) job=${SLURM_JOB_ID}"
# Record the live allocation (per-node GRES=qpu:1) while the job is RUNNING;
# after completion scontrol no longer shows it.
scontrol show job -d "$SLURM_JOB_ID" > "/data/jobs/out/aer_bell_${SLURM_JOB_ID}.alloc.txt"
python3 /data/jobs/aer_bell.py

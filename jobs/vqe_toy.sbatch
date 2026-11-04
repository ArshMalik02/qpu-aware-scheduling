#!/bin/bash
#SBATCH --job-name=vqe_toy
#SBATCH --gres=qpu:1
#SBATCH -c1
#SBATCH --mem=500M
#SBATCH --time=00:05:00
#SBATCH -o /data/jobs/out/vqe_toy_%j.out
# Toy VQE timing on Aer (CPU). SIMULATED: the qpu GRES is a Slurm counter only.
set -euo pipefail
echo "host=$(hostname) arch=$(uname -m) job=${SLURM_JOB_ID}"
# Record the live allocation (per-node GRES=qpu:1) while the job is RUNNING;
# after completion scontrol no longer shows it.
scontrol show job -d "$SLURM_JOB_ID" > "/data/jobs/out/vqe_toy_${SLURM_JOB_ID}.alloc.txt"
python3 /data/jobs/vqe_toy.py

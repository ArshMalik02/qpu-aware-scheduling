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
python3 /data/jobs/vqe_toy.py

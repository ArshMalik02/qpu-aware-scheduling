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
python3 /data/jobs/aer_bell.py

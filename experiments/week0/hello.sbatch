#!/bin/bash
#SBATCH --job-name=hello
#SBATCH --output=/data/hello_%j.out
#SBATCH --time=00:02:00
echo "batch script running on: $(hostname)"
sleep 20
srun hostname

#!/bin/bash
#SBATCH -c1
#SBATCH --mem=500M
#SBATCH --time=00:10:00
#SBATCH --output=/data/burn_%A_%a.out
head -c 12G /dev/zero | sha256sum > /dev/null

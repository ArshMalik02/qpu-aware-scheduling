#!/bin/bash
# Overcommit test: submit arrays of 1, 4, 8 burn jobs and report average ElapsedRaw.
# Run inside the slurmctld container from /data (burn.sbatch must be in /data).
cd /data || exit 1

waitjob() { while squeue -h -j "$1" | grep -q .; do sleep 5; done; echo "done"; }
avg()     { sacct -X -n -j "$1" --format=ElapsedRaw | awk '{s+=$1;n++} END{printf "jobs=%d avg=%.1fs\n", n, s/n}'; }

for n in 1 4 8; do J=$(sbatch --parsable --array=1-$n burn.sbatch); waitjob $J; echo -n "n=$n "; avg $J; done

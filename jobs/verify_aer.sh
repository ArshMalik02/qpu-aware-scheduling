#!/usr/bin/env bash
# Submit the Aer Bell job and the toy VQE job through Slurm (--gres=qpu:1 each),
# wait for both, check their outputs, and (only on PASS) copy the results back to the repo.
# Everything is SIMULATED: the qpu GRES is a Slurm counter, circuits run on Aer (CPU).
#
# Usage (from the repo root, with the cluster up):  jobs/verify_aer.sh
# VERIFY_TIMEOUT_S (default 300) sets how long to wait before cancelling the jobs.
set -euo pipefail

ctl() { docker exec slurmctld "$@"; }

cd "$(dirname "$0")/.."
fail=0
timeout_s=${VERIFY_TIMEOUT_S:-300}

echo "==> Staging jobs/ into slurmctld:/data/jobs"
ctl mkdir -p /data/jobs/out
docker cp jobs/. slurmctld:/data/jobs/
ctl rm -rf /data/jobs/results

echo "==> Submitting"
bell=$(ctl sbatch --parsable /data/jobs/aer_bell.sbatch)
vqe=$(ctl sbatch --parsable /data/jobs/vqe_toy.sbatch)
echo "    aer_bell=$bell vqe_toy=$vqe"

echo "==> squeue right after submit"
ctl squeue -o "%.8i %.9j %.9T %.12R %.10b %N"   # %b = GRES requested (qpu:1)

echo "==> Waiting for both to leave the queue (timeout ${timeout_s} s)"
for _ in $(seq 1 $(( (timeout_s + 1) / 2 ))); do
    if [ -z "$(ctl squeue -h -j "$bell,$vqe" 2>/dev/null)" ]; then break; fi
    sleep 2
done
if [ -n "$(ctl squeue -h -j "$bell,$vqe" 2>/dev/null)" ]; then
    echo "FAIL: jobs still queued/running after ${timeout_s} s; cancelling $bell $vqe" >&2
    ctl squeue -j "$bell,$vqe" -o "%.8i %.9j %.9T %.12R %.10b %N" || true
    ctl scancel "$bell" "$vqe" || true
    exit 1
fi
sleep 2  # let accounting catch up

state() { ctl sacct -j "$1" -X -n -o State | tr -d ' '; }
for id in "$bell" "$vqe"; do
    s=$(state "$id")
    echo "    job $id: $s"
    [ "$s" = "COMPLETED" ] || fail=1
done

echo "==> Checking outputs"
checks_out=$(ctl python3 /data/jobs/check_outputs.py "$bell" "$vqe") || fail=1
echo "$checks_out" | grep -v "^CHECKS_RAN$" || true
# Guard against the checks silently not running.
grep -q "^CHECKS_RAN$" <<<"$checks_out" || { echo "FAIL: output checks did not run" >&2; fail=1; }

echo "==> sacct (queue wait = Start - Submit, wall time = Elapsed; times are the container clock, $(ctl date +%Z))"
sacct_txt=$(ctl sacct -j "$bell,$vqe" -X -o JobID,JobName,State,Submit,Start,End,Elapsed,NodeList,AllocTRES%40)
echo "$sacct_txt"

# Each job saves `scontrol show job -d` while RUNNING (see the .sbatch files): after
# completion scontrol no longer shows the per-node GRES, and sacct AllocTRES omits
# gres/qpu because it isn't in AccountingStorageTRES.
echo "==> GRES allocation (scontrol show job -d, captured inside each running job)"
alloc_txt=""
for f in "aer_bell_$bell.alloc.txt" "vqe_toy_$vqe.alloc.txt"; do
    a=$(ctl cat "/data/jobs/out/$f" 2>/dev/null || true)
    alloc_txt+="$a"$'\n\n'
    line=$(grep -E "^ *Nodes=.*GRES=" <<<"$a" | sed 's/^ *//' || true)
    echo "    $f: ${line:-<missing>}"
    grep -q "GRES=qpu" <<<"$line" || { echo "FAIL: no qpu GRES in allocation for $f" >&2; fail=1; }
done

if [ "$fail" -ne 0 ]; then
    echo "FAIL (results not copied)" >&2
    exit 1
fi

arch=$(ctl uname -m)
dest="jobs/results/$arch"
echo "==> Copying results to $dest/"
mkdir -p "$dest"
for f in "aer_bell_$bell.json" "aer_bell_$bell.out" "aer_bell_$bell.alloc.txt" \
         "vqe_toy_$vqe.json" "vqe_toy_$vqe.csv" "vqe_toy_$vqe.out" "vqe_toy_$vqe.alloc.txt"; do
    docker cp "slurmctld:/data/jobs/out/$f" "$dest/$f"
done
echo "$sacct_txt" > "$dest/sacct_${bell}_${vqe}.txt"
echo "PASS"

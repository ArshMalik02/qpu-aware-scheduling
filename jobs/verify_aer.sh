#!/usr/bin/env bash
# Submit the Aer Bell job and the toy VQE job through Slurm (--gres=qpu:1 each),
# wait for both, check their outputs, and copy the results back to the repo.
# Everything is SIMULATED: the qpu GRES is a Slurm counter, circuits run on Aer (CPU).
#
# Usage (from the repo root, with the cluster up):  jobs/verify_aer.sh
set -euo pipefail

ctl() { docker exec slurmctld "$@"; }

cd "$(dirname "$0")/.."
fail=0

echo "==> Staging jobs/ into slurmctld:/data/jobs"
ctl mkdir -p /data/jobs/out
docker cp jobs/. slurmctld:/data/jobs/
ctl rm -rf /data/jobs/results

echo "==> Submitting"
bell=$(ctl sbatch --parsable /data/jobs/aer_bell.sbatch)
vqe=$(ctl sbatch --parsable /data/jobs/vqe_toy.sbatch)
echo "    aer_bell=$bell vqe_toy=$vqe"

echo "==> squeue right after submit"
ctl squeue -o "%.8i %.9j %.9T %.12R %N"

echo "==> Waiting for both to leave the queue (timeout 300 s)"
for _ in $(seq 1 150); do
    if [ -z "$(ctl squeue -h -j "$bell,$vqe" 2>/dev/null)" ]; then break; fi
    sleep 2
done
if [ -n "$(ctl squeue -h -j "$bell,$vqe" 2>/dev/null)" ]; then
    echo "FAIL: jobs still queued/running after 300 s" >&2
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

echo "==> sacct (queue wait = Start - Submit, wall time = Elapsed)"
sacct_txt=$(ctl sacct -j "$bell,$vqe" -X -o JobID,JobName,State,Submit,Start,End,Elapsed,NodeList)
echo "$sacct_txt"

arch=$(ctl uname -m)
dest="jobs/results/$arch"
echo "==> Copying results to $dest/"
mkdir -p "$dest"
for f in "aer_bell_$bell.json" "aer_bell_$bell.out" "vqe_toy_$vqe.json" "vqe_toy_$vqe.csv" "vqe_toy_$vqe.out"; do
    docker cp "slurmctld:/data/jobs/out/$f" "$dest/$f"
done
echo "$sacct_txt" > "$dest/sacct_${bell}_${vqe}.txt"

if [ "$fail" -eq 0 ]; then
    echo "PASS"
else
    echo "FAIL" >&2
    exit 1
fi

#!/usr/bin/env bash
# Check that the cluster advertises a simulated `qpu` GRES on c1 and c2, then
# rerun the Week 0 contention test: 3 jobs, each wanting 1 QPU, on 2 QPUs.
# Expected: 2 RUNNING, 1 PENDING (Resources).
#
# Usage (from cluster/, with the cluster up):  ./verify_qpu.sh
set -euo pipefail

ctl() { docker exec slurmctld "$@"; }

echo "==> Waiting for c1 and c2 to register with qpu:1 ..."
for _ in $(seq 1 60); do
    if [ "$(ctl sinfo -h -N -o '%N %G' | grep -cE '^c[12] .*qpu:1')" -ge 2 ]; then
        break
    fi
    sleep 2
done

echo "==> sinfo -N -o \"%N %G %t\""
ctl sinfo -N -o "%N %G %t"

if [ "$(ctl sinfo -h -N -o '%N %G' | grep -cE '^c[12] .*qpu:1')" -lt 2 ]; then
    cat >&2 <<'EOF'
FAIL: nodes do not show qpu:1. If they show qpu:0 the controller kept a stale
node record. Fix:
    docker exec slurmctld scontrol delete nodename=c1,c2
    docker compose restart cpu-worker
EOF
    exit 1
fi

echo "==> Submitting 3 jobs, each --gres=qpu:1 --mem=500M -c1"
for n in q1 q2 q3; do
    ctl sbatch -J "$n" --gres=qpu:1 --mem=500M -c1 -o /dev/null --wrap "sleep 120" >/dev/null
done
sleep 8

echo "==> squeue"
ctl squeue -o "%.8i %.4j %.9T %.12R %N"

running=$(ctl squeue -h -t RUNNING -o %i | wc -l | tr -d " ")   # macOS wc pads with spaces
pending=$(ctl squeue -h -t PENDING -o %r | grep -c Resources || true)
echo "==> RUNNING=$running PENDING(Resources)=$pending"

ctl scancel -u root >/dev/null 2>&1 || true

if [ "$running" -eq 2 ] && [ "$pending" -eq 1 ]; then
    echo "PASS"
else
    echo "FAIL: expected 2 RUNNING and 1 PENDING (Resources)" >&2
    exit 1
fi

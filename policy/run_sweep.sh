#!/usr/bin/env bash
# Sweep: every policy x seed, then aggregate + chart. SIMULATED.
# Usage: make sweep SEEDS="1 2 3 4 5" POLICIES="static reactive predictive"
#
# For seed N every policy gets the same workload seed (N) and the same feed seed (100+N),
# so recal timing varies between seeds but not between policies. Runs are sequential
# on one machine (they share the cluster).
#
# Env: SEEDS (default "1"), POLICIES (default "static reactive predictive"),
#      RUN_MIN (default 30), FEED_SPEED (36), RATE_PER_MIN (1.5), DRAIN_MIN (15)
set -uo pipefail

SEEDS=${SEEDS:-1}
POLICIES=${POLICIES:-static reactive predictive}
export RUN_MIN=${RUN_MIN:-30}
export FEED_SPEED=${FEED_SPEED:-36}
export RATE_PER_MIN=${RATE_PER_MIN:-1.5}
export DRAIN_MIN=${DRAIN_MIN:-15}
cd "$(dirname "$0")/.."

n_seeds=$(wc -w <<<"$SEEDS"); n_pol=$(wc -w <<<"$POLICIES"); n=$((n_seeds * n_pol))
# Per run: arrival window + ~4 min for the last jobs to drain + ~1.5 min setup/teardown.
per=$((RUN_MIN + 6))
echo "==> Sweep: $n runs (seeds: $SEEDS; policies: $POLICIES), RUN_MIN=$RUN_MIN"
echo "    estimated wall time: ~$((n * per)) min (~$((n * per / 60)) h $((n * per % 60)) min); up to $((n * (RUN_MIN + DRAIN_MIN + 2))) min if queues drain slowly"

failed=()
for seed in $SEEDS; do
    for policy in $POLICIES; do
        echo "==> $(date -u +%H:%M:%SZ) run: policy=$policy seed=$seed feed_seed=$((100 + seed))"
        if ! POLICY=$policy SEED=$seed FEED_SEED=$((100 + seed)) policy/run_baseline.sh; then
            failed+=("$policy/seed$seed")
        fi
    done
done

echo "==> Aggregating"
python3 policy/aggregate.py --results results
if python3 -c "import matplotlib" 2>/dev/null; then
    python3 policy/plot_sweep.py --results results
else
    echo "    matplotlib not installed; run: python3 -m pip install -r feed/requirements-dev.txt && python3 policy/plot_sweep.py"
fi

if [ ${#failed[@]} -gt 0 ]; then
    echo "FAIL: ${#failed[@]} run(s) did not pass their checks: ${failed[*]}" >&2
    exit 1
fi
echo "PASS: all $n runs passed their checks"

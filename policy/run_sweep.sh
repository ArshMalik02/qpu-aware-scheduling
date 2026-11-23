#!/usr/bin/env bash
# Sweep: every policy x seed, then aggregate + chart. SIMULATED.
# Usage: make sweep SEEDS="1 2 3 4 5" POLICIES="static reactive predictive"
#
# For seed N every policy gets the same workload seed (N) and the same feed seed (100+N),
# so recal timing varies between seeds but not between policies. Runs are sequential
# on one machine (they share the cluster).
#
# Resumable: a policy/seed is skipped (FORCE=1 re-runs it) if its
# results/<policy>/seed<N>/summary.json has every check passing and its run_config.json
# has this sweep's feed seed (100+N), RUN_MIN and FEED_SPEED. A failed run is retried
# once. So after an interruption, re-run the same command and it picks up where it stopped.
#
# Unattended (e.g. overnight), from the repo root:
#   setsid nohup make sweep SEEDS="1 2 3 4 5" > results/sweep.log 2>&1 < /dev/null &
#   tail -f results/sweep.log           # progress; ends with PASS or FAIL
#
# Env: SEEDS (default "1"), POLICIES (default "static reactive predictive"), FORCE (0),
#      RUN_MIN (default 30), FEED_SPEED (36), RATE_PER_MIN (1.5), DRAIN_MIN (15)
set -uo pipefail

SEEDS=${SEEDS:-1}
POLICIES=${POLICIES:-static reactive predictive}
FORCE=${FORCE:-0}
export RUN_MIN=${RUN_MIN:-30}
export FEED_SPEED=${FEED_SPEED:-36}
export RATE_PER_MIN=${RATE_PER_MIN:-1.5}
export DRAIN_MIN=${DRAIN_MIN:-15}
cd "$(dirname "$0")/.."

# passed <policy> <seed>: summary.json exists with every check true, AND run_config.json
# matches this sweep (feed_seed == 100+seed, run_min == RUN_MIN, feed_speed == FEED_SPEED),
# so a run made with other settings is re-run rather than mixed in.
passed() {
    python3 - "results/$1/seed$2" "$2" "$RUN_MIN" "$FEED_SPEED" <<'PY' 2>/dev/null
import json, sys
d, seed, run_min, speed = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
c = json.load(open(f"{d}/summary.json")).get("checks") or {}
cfg = json.load(open(f"{d}/run_config.json"))
ok = (bool(c) and all(c.values()) and int(cfg["feed_seed"]) == 100 + seed
      and float(cfg["run_min"]) == run_min and float(cfg["feed_speed"]) == speed)
sys.exit(0 if ok else 1)
PY
}

todo=()
for seed in $SEEDS; do
    for policy in $POLICIES; do
        if [ "$FORCE" != 1 ] && passed "$policy" "$seed"; then
            echo "==> skip $policy/seed$seed: already passed with these settings (FORCE=1 to re-run)"
        else
            todo+=("$policy:$seed")
        fi
    done
done

n=${#todo[@]}
# Per run: arrival window + ~4 min for the last jobs to drain + ~1.5 min setup/teardown.
per=$((RUN_MIN + 6))
echo "==> Sweep: $n run(s) to do (seeds: $SEEDS; policies: $POLICIES), RUN_MIN=$RUN_MIN"
echo "    estimated wall time: ~$((n * per)) min (~$((n * per / 60)) h $((n * per % 60)) min); up to $((n * (RUN_MIN + DRAIN_MIN + 2))) min if queues drain slowly (plus any retries)"

failed=()
for item in "${todo[@]}"; do
    policy=${item%%:*}; seed=${item##*:}
    ok=0
    for attempt in 1 2; do
        echo "==> $(date -u +%H:%M:%SZ) run: policy=$policy seed=$seed feed_seed=$((100 + seed)) (attempt $attempt/2)"
        if POLICY=$policy SEED=$seed FEED_SEED=$((100 + seed)) policy/run_baseline.sh; then
            ok=1; break
        fi
        echo "==> $(date -u +%H:%M:%SZ) $policy/seed$seed failed (attempt $attempt/2)"
    done
    [ "$ok" = 1 ] || failed+=("$policy/seed$seed")
done

echo "==> Aggregating"
python3 policy/aggregate.py --results results
if python3 -c "import matplotlib" 2>/dev/null; then
    python3 policy/plot_sweep.py --results results
else
    echo "    matplotlib not installed; run: python3 -m pip install -r feed/requirements-dev.txt && python3 policy/plot_sweep.py"
fi

if [ ${#failed[@]} -gt 0 ]; then
    echo "FAIL: ${#failed[@]} run(s) did not pass their checks after a retry: ${failed[*]}" >&2
    exit 1
fi
echo "PASS: all requested runs passed their checks ($n run now, the rest already passed)"

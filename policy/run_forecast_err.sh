#!/usr/bin/env bash
# Forecast-error runs: predictive policy with the feed's FORECAST_ERR_MIN. SIMULATED.
#
# Each item is N:seed. For seed s: workload seed s, feed seed 100+s, RUN_MIN 30, 36x;
# output in results/forecast_err/N<N>/seed<s>/. Every finished run is checked against
# that seed's sweep manifest (results/static/seed<s>/manifest.json, byte-identical),
# then committed (that directory only) and pushed.
#
# Resumable: a run whose summary.json has every check passing and whose run_config.json
# has this N and feed seed is skipped. A failed run is retried once.
#
# Unattended, from the repo root:
#   setsid nohup policy/run_forecast_err.sh > results/forecast_err/runs.log 2>&1 < /dev/null &
# Env: RUNS (default "0:1 120:1 120:2 120:3 120:4 120:5")
set -uo pipefail
cd "$(dirname "$0")/.."
RUNS=${RUNS:-0:1 120:1 120:2 120:3 120:4 120:5}

passed() {  # passed <dir> <N> <seed>
    python3 - "$1" "$2" "$3" <<'PY' 2>/dev/null
import json, sys
d, n, seed = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
s = json.load(open(f"{d}/summary.json")); c = json.load(open(f"{d}/run_config.json"))
ok = (all(s["checks"].values()) and float(c.get("forecast_err_min", 0)) == n
      and int(c["feed_seed"]) == 100 + seed and float(c["run_min"]) == 30)
sys.exit(0 if ok else 1)
PY
}

git_retry() {  # git_retry <git args...>: retry while another git process holds the index
    for i in 1 2 3 4 5; do git "$@" && return 0; sleep $((i * 3)); done
    return 1
}

commit_push() {  # commit_push <dir> <N> <seed>
    git_retry add "$1" || return 1
    git_retry commit -q -m "Forecast-error run N=$2, seed $3 (simulated): predictive

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- "$1" || return 1
    for i in 1 2 3 4; do git push -q && return 0; sleep $((2 ** i)); done
    echo "==> push failed for $1 (committed locally)"
}

failed=()
for item in $RUNS; do
    N=${item%%:*}; seed=${item##*:}
    D=results/forecast_err/N$N/seed$seed
    if passed "$D" "$N" "$seed"; then echo "==> skip N=$N seed=$seed: already passed"; continue; fi
    ok=0
    for attempt in 1 2; do
        echo "==> $(date -u +%H:%M:%SZ) run N=$N seed=$seed (attempt $attempt/2)"
        if POLICY=predictive SEED=$seed FEED_SEED=$((100 + seed)) FEED_SPEED=36 RUN_MIN=30 \
             RATE_PER_MIN=1.5 DRAIN_MIN=15 FORECAST_ERR_MIN=$N DEST=$D policy/run_baseline.sh; then
            ok=1; break
        fi
        echo "==> $(date -u +%H:%M:%SZ) N=$N seed=$seed failed (attempt $attempt/2)"
    done
    if [ "$ok" != 1 ]; then failed+=("N$N/seed$seed"); continue; fi
    if ! cmp -s "$D/manifest.json" "results/static/seed$seed/manifest.json"; then
        echo "==> MANIFEST MISMATCH N=$N seed=$seed vs results/static/seed$seed (not committed)"
        failed+=("N$N/seed$seed:manifest"); continue
    fi
    echo "==> manifest identical to results/static/seed$seed (md5 $(md5sum < "$D/manifest.json" | cut -c1-12))"
    commit_push "$D" "$N" "$seed" && echo "==> committed and pushed $D"
done
if [ ${#failed[@]} -gt 0 ]; then echo "==> ALL DONE with failures: ${failed[*]}"; exit 1; fi
echo "==> ALL DONE $(date -u +%H:%M:%SZ)"

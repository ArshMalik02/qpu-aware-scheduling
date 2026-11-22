#!/usr/bin/env bash
# Reactive baseline (policy 2): feed sidecar + HRES-like up/down loop + seeded workload.
# Everything is SIMULATED. Run from the repo root (or via `make baseline-reactive SEED=1`).
#
# Env:
#   SEED          workload seed (default 1)
#   FEED_SEED     feed seed (default 42)
#   FEED_SPEED    feed simulated-seconds per wall-second (default 36: ~18 h of feed time in 30 min)
#   RUN_MIN       workload arrival window in minutes (default 20)
#   RATE_PER_MIN  mean job arrivals per minute (default 1.5)
#   DRAIN_MIN     max minutes to wait for the queue to empty afterwards (default 15)
set -euo pipefail

SEED=${SEED:-1}
export FEED_SEED=${FEED_SEED:-42}
export FEED_SPEED=${FEED_SPEED:-36}
RUN_MIN=${RUN_MIN:-20}
RATE_PER_MIN=${RATE_PER_MIN:-1.5}
DRAIN_MIN=${DRAIN_MIN:-15}
RUN=/data/results/reactive
DEST="results/reactive/seed${SEED}"

ctl() { docker exec slurmctld "$@"; }
cd "$(dirname "$0")/.."

stop_loop() { ctl pkill -TERM -f /data/policy/reactive.py >/dev/null 2>&1 || true; }

echo "==> Cluster + feed sidecar (seed $FEED_SEED, speed ${FEED_SPEED}x; simulated)"
( cd cluster && docker compose --profile reactive up -d >/dev/null && \
  docker compose --profile reactive up -d --force-recreate feed >/dev/null )
for _ in $(seq 1 30); do
    ctl python3 -c "import urllib.request; urllib.request.urlopen('http://feed:8787/healthz')" 2>/dev/null && break
    sleep 2
done

echo "==> Preflight: c1 and c2 must be up"
# After a Docker restart slurmctld marks the nodes DOWN ("Node unexpectedly rebooted")
# and every job would sit in ReqNodeNotAvail. Resume once, then require idle/mixed/alloc.
down=$(ctl sinfo -h -N -n c1,c2 -t down,drain,fail,unknown -o "%N" | sort -u | tr '\n' ' ')
if [ -n "$down" ]; then
    echo "    nodes not up: $down; trying State=RESUME"
    for n in $down; do ctl scontrol update NodeName="$n" State=RESUME || true; done
    sleep 5
fi
bad=$(ctl sinfo -h -N -n c1,c2 -t down,drain,fail,unknown -o "%N %T %E" | sort -u)
if [ -n "$bad" ]; then
    echo "FAIL: nodes still not up, not starting the run:" >&2
    echo "$bad" >&2
    exit 1
fi
ctl sinfo -N -n c1,c2 -o "    %N %G %t"

echo "==> Staging jobs/, policy/, workload/ into slurmctld:/data"
stop_loop
ctl rm -rf "$RUN" && ctl mkdir -p "$RUN" /data/jobs
docker cp --quiet jobs/. slurmctld:/data/jobs/
docker cp --quiet policy slurmctld:/data/
docker cp --quiet workload slurmctld:/data/
ctl rm -rf /data/jobs/results
start_utc=$(ctl date -u +%Y-%m-%dT%H:%M:%S)
INTERVAL_S=10

# Run config: summarize.py reads feed_speed from here to convert wall seconds to feed minutes.
printf '{"seed": %s, "feed_seed": %s, "feed_speed": %s, "run_min": %s, "rate_per_min": %s, "poll_interval_s": %s, "map": "qpu0=c1,qpu1=c2", "start_utc": "%s", "simulated": true}\n' \
    "$SEED" "$FEED_SEED" "$FEED_SPEED" "$RUN_MIN" "$RATE_PER_MIN" "$INTERVAL_S" "$start_utc" \
    | docker exec -i slurmctld tee "$RUN/run_config.json" >/dev/null

echo "==> Starting the reactive loop (poll ${INTERVAL_S} s, qpu0->c1, qpu1->c2)"
ctl bash -c "nohup python3 /data/policy/reactive.py --interval $INTERVAL_S --out-dir $RUN > $RUN/loop.out 2>&1 &"
trap 'stop_loop' EXIT

echo "==> Submitting the seeded workload (seed $SEED, ${RUN_MIN} min, ${RATE_PER_MIN}/min)"
ctl python3 /data/workload/gen.py --seed "$SEED" --duration-min "$RUN_MIN" \
    --rate-per-min "$RATE_PER_MIN" --manifest "$RUN/manifest.json" --submit \
    --out-dir "$RUN/jobs" --submit-log "$RUN/submitted.log"

echo "==> Waiting for the queue to drain (max ${DRAIN_MIN} min)"
for _ in $(seq 1 $((DRAIN_MIN * 6))); do
    [ -z "$(ctl squeue -h)" ] && break
    sleep 10
done
if [ -n "$(ctl squeue -h)" ]; then
    echo "    queue not empty after ${DRAIN_MIN} min; cancelling the rest"
    ctl scancel -u root || true
fi

echo "==> Stopping the loop (restores every QPU)"
stop_loop
for _ in $(seq 1 20); do ctl pgrep -f /data/policy/reactive.py >/dev/null || break; sleep 1; done
trap - EXIT
ctl sinfo -N -o "%N %G %t"

sleep 3  # accounting
ctl bash -c "sacct -X -P -S $start_utc -o JobID,JobName,State,Submit,Start,End,Elapsed,NodeList,ReqTRES%60 > $RUN/sacct.txt"

echo "==> Summary (times UTC; simulated)"
status=0
ctl python3 /data/policy/summarize.py --run-dir "$RUN" || status=$?

echo "==> Copying results to $DEST/"
rm -rf "$DEST" && mkdir -p "$DEST"
for f in run_config.json manifest.json submitted.log transitions.log queue.log loop.out sacct.txt jobs.csv summary.json; do
    docker cp --quiet "slurmctld:$RUN/$f" "$DEST/$f"
done
echo "    copied to $DEST/"
exit $status

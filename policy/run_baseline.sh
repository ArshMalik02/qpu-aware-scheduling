#!/usr/bin/env bash
# One baseline run: feed sidecar + a QPU policy + the seeded workload. SIMULATED.
# Run from the repo root, or via `make baseline-reactive SEED=1` / `make sweep`.
#
# Env:
#   POLICY        static | reactive | predictive (default reactive)
#                   static     = reactive.py --observe-only (logs recal windows, never touches nodes)
#                   reactive   = reactive.py (QPU out during recal; HRES-like)
#                   predictive = predictive.py (reactive + start a QPU job only if it ends before
#                                the next recal); QPU jobs are submitted held (gen.py --hold-qpu)
#   SEED          workload seed (default 1)
#   FEED_SEED     feed seed (default 42; the sweep uses 100 + SEED)
#   FEED_SPEED    feed simulated-seconds per wall-second (default 36)
#   RUN_MIN       workload arrival window in minutes (default 20; the sweep uses 30)
#   RATE_PER_MIN  mean job arrivals per minute (default 1.5)
#   DRAIN_MIN     max minutes to wait for the queue to empty afterwards (default 15)
#
# Unattended-safe: a non-empty queue before the run is cancelled (and waited out) instead
# of failing; on any early exit the trap cancels this run's jobs, waits for the queue to
# empty and stops the loop (which restores every QPU), so the next run starts clean.
set -euo pipefail

POLICY=${POLICY:-reactive}
SEED=${SEED:-1}
export FEED_SEED=${FEED_SEED:-42}
export FEED_SPEED=${FEED_SPEED:-36}
RUN_MIN=${RUN_MIN:-20}
RATE_PER_MIN=${RATE_PER_MIN:-1.5}
DRAIN_MIN=${DRAIN_MIN:-15}
INTERVAL_S=10
RUN=/data/results/run
DEST="results/${POLICY}/seed${SEED}"

case "$POLICY" in
    static)     LOOP="python3 /data/policy/reactive.py --observe-only --interval $INTERVAL_S"; HOLD="" ;;
    reactive)   LOOP="python3 /data/policy/reactive.py --interval $INTERVAL_S"; HOLD="" ;;
    predictive) LOOP="python3 /data/policy/predictive.py --interval $INTERVAL_S --feed-speed $FEED_SPEED"
                HOLD="--hold-qpu" ;;
    *) echo "unknown POLICY=$POLICY (static|reactive|predictive)" >&2; exit 2 ;;
esac

ctl() { docker exec slurmctld "$@"; }
cd "$(dirname "$0")/.."

stop_loop() { ctl pkill -TERM -f "/data/policy/(reactive|predictive).py" >/dev/null 2>&1 || true; }
queue_empty() { [ -z "$(ctl squeue -h 2>/dev/null)" ]; }
# cancel_and_wait <why>: scancel everything, then wait (up to 2 min) until squeue is empty.
cancel_and_wait() {
    echo "    $1: cancelling $(ctl squeue -h 2>/dev/null | wc -l) job(s) and waiting for an empty queue"
    ctl scancel -u root >/dev/null 2>&1 || true
    for _ in $(seq 1 60); do queue_empty && return 0; sleep 2; done
    echo "    queue still not empty after 2 min:" >&2
    ctl squeue -h -o "    %i %j %T %r" >&2 || true
    return 1
}
finished=0
on_exit() {
    local rc=$?
    [ "$finished" = 1 ] && return
    echo "==> Early exit (rc=$rc): cleaning up so the next run starts clean" >&2
    ctl pkill -TERM -f "/data/workload/gen.py" >/dev/null 2>&1 || true  # stop submitting first
    cancel_and_wait "early exit" || true
    stop_loop
}
trap on_exit EXIT
trap 'exit 130' INT TERM HUP  # so a killed run still goes through on_exit

echo "==> [$POLICY seed $SEED] cluster + feed sidecar (feed seed $FEED_SEED, speed ${FEED_SPEED}x; simulated)"
( cd cluster && docker compose --profile reactive up -d >/dev/null && \
  docker compose --profile reactive up -d --force-recreate feed >/dev/null )
for _ in $(seq 1 30); do
    ctl python3 -c "import urllib.request; urllib.request.urlopen('http://feed:8787/healthz')" 2>/dev/null && break
    sleep 2
done

echo "==> Preflight: c1 and c2 must be up, queue empty"
# After a Docker restart slurmctld marks the nodes DOWN ("Node unexpectedly rebooted")
# and every job would sit in ReqNodeNotAvail. Resume once, then require idle/mixed/alloc.
stop_loop
down=$(ctl sinfo -h -N -n c1,c2 -t down,drain,fail,unknown -o "%N" | sort -u | tr '\n' ' ')
if [ -n "$down" ]; then
    echo "    nodes not up: $down; trying State=RESUME"
    for n in $down; do ctl scontrol update NodeName="$n" State=RESUME || true; done
    sleep 5
fi
for n in c1 c2; do ctl scontrol update NodeName="$n" Gres=qpu:1 >/dev/null 2>&1 || true; done
bad=$(ctl sinfo -h -N -n c1,c2 -t down,drain,fail,unknown -o "%N %T %E" | sort -u)
if [ -n "$bad" ]; then
    echo "FAIL: nodes still not up, not starting the run:" >&2
    echo "$bad" >&2
    exit 1
fi
if ! queue_empty; then
    cancel_and_wait "queue not empty before the run" || { echo "FAIL: could not empty the queue" >&2; exit 1; }
fi
ctl sinfo -N -n c1,c2 -o "    %N %G %t"

echo "==> Staging jobs/, policy/, workload/ into slurmctld:/data"
ctl rm -rf "$RUN" && ctl mkdir -p "$RUN" /data/jobs
docker cp --quiet jobs/. slurmctld:/data/jobs/
docker cp --quiet policy slurmctld:/data/
docker cp --quiet workload slurmctld:/data/
ctl rm -rf /data/jobs/results
start_utc=$(ctl date -u +%Y-%m-%dT%H:%M:%S)

# Run config: summarize.py reads policy and feed_speed from here.
printf '{"policy": "%s", "seed": %s, "feed_seed": %s, "feed_speed": %s, "run_min": %s, "rate_per_min": %s, "poll_interval_s": %s, "map": "qpu0=c1,qpu1=c2", "start_utc": "%s", "simulated": true}\n' \
    "$POLICY" "$SEED" "$FEED_SEED" "$FEED_SPEED" "$RUN_MIN" "$RATE_PER_MIN" "$INTERVAL_S" "$start_utc" \
    | docker exec -i slurmctld tee "$RUN/run_config.json" >/dev/null

echo "==> Starting the $POLICY loop (poll ${INTERVAL_S} s, qpu0->c1, qpu1->c2)"
ctl bash -c "cd /data/policy && nohup $LOOP --out-dir $RUN > $RUN/loop.out 2>&1 &"

echo "==> Submitting the seeded workload (seed $SEED, ${RUN_MIN} min, ${RATE_PER_MIN}/min)"
# In the background + wait, so a signal reaches the trap now, not after the arrival window.
ctl python3 /data/workload/gen.py --seed "$SEED" --duration-min "$RUN_MIN" \
    --rate-per-min "$RATE_PER_MIN" --manifest "$RUN/manifest.json" --submit $HOLD \
    --out-dir "$RUN/jobs" --submit-log "$RUN/submitted.log" &
wait $!

echo "==> Waiting for the queue to drain (max ${DRAIN_MIN} min)"
for _ in $(seq 1 $((DRAIN_MIN * 6))); do
    [ -z "$(ctl squeue -h)" ] && break
    sleep 10
done
if [ -n "$(ctl squeue -h)" ]; then
    echo "    queue not empty after ${DRAIN_MIN} min; cancelling the rest"
    ctl squeue -h -o "    %i %j %T %r"
    cancel_and_wait "drain timeout" || true
fi

echo "==> Stopping the loop (restores every QPU)"
stop_loop
for _ in $(seq 1 20); do ctl pgrep -f "/data/policy/(reactive|predictive).py" >/dev/null || break; sleep 1; done
ctl sinfo -N -o "%N %G %t"

sleep 3  # accounting
ctl bash -c "sacct -X -P -S $start_utc -o JobID,JobName,State,Submit,Start,End,Elapsed,NodeList,ReqTRES%60,Flags > $RUN/sacct.txt"

echo "==> Summary (times UTC; simulated)"
status=0
ctl python3 /data/policy/summarize.py --run-dir "$RUN" || status=$?

echo "==> Copying results to $DEST/"
rm -rf "$DEST" && mkdir -p "$DEST"
for f in run_config.json manifest.json submitted.log transitions.log queue.log loop.out sacct.txt jobs.csv summary.json; do
    docker cp --quiet "slurmctld:$RUN/$f" "$DEST/$f"
done
echo "    copied to $DEST/"
finished=1
exit $status

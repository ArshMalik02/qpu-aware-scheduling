#!/usr/bin/env bash
# Repro: the predictive gate re-holds a released QPU job that stops fitting, and releases
# it again once a QPU fits. SIMULATED (stub feed, GRES-counter QPUs).
#
# Drives the real policy/predictive.py against a stub feed (inside slurmctld) whose
# per-QPU status and minutes-to-next-recal this script sets.
#
# Steps:
#   1. stub: both QPUs online, next recal in 600 feed min; blockers take both QPUs
#   2. victim QPU job submitted held (2 min limit = 72 feed min at 36x)
#        -> gate releases it (both fit); it pends on Resources behind the blockers
#   3. stub: both recals in 30 feed min -> nothing fits -> gate re-holds the victim
#        (scontrol uhold -> JobHeldUser)
#   4. stub: qpu1's recal back to 600 min -> gate releases it with ExcNodeList=c1;
#        cancel the c2 blocker -> victim runs on c2
#   5. PASS if the victim COMPLETED on c2 and transitions.log has gate_release,
#      gate_rehold, gate_release for it, in that order
#
# Usage (repo root, cluster up, idle):  policy/repro_rehold.sh
set -euo pipefail

ctl() { docker exec slurmctld "$@"; }
cd "$(dirname "$0")/.."
D=/data/results/repro_rehold
STUB_PORT=8798
INTERVAL=2
SPEED=36

say() { echo "[$(date -u +%H:%M:%SZ)] $*"; }
reason() { ctl squeue -h -j "$1" -o "%T %r" 2>/dev/null || true; }
wait_for() {  # wait_for <seconds> <description> <command...>
    local t=$1 desc=$2; shift 2
    for _ in $(seq 1 "$t"); do "$@" && return 0; sleep 1; done
    say "TIMEOUT waiting for: $desc"; return 1
}
# set_feed <qpu0 status> <qpu0 min-to-recal> <qpu1 status> <qpu1 min-to-recal>
set_feed() { ctl bash -c "printf '{\"qpu0\": [\"$1\", $2], \"qpu1\": [\"$3\", $4]}' > $D/stub_state.json"; }

cleanup() {
    ctl pkill -TERM -f "predictive.py --feed http://localhost:$STUB_PORT" >/dev/null 2>&1 || true
    sleep 1
    ctl pkill -f "stub_feed_recal.py" >/dev/null 2>&1 || true
    for j in ${b1:-} ${b2:-} ${victim:-}; do ctl scancel "$j" >/dev/null 2>&1 || true; done
    ctl scontrol update NodeName=c1 Gres=qpu:1 >/dev/null 2>&1 || true
    ctl scontrol update NodeName=c2 Gres=qpu:1 >/dev/null 2>&1 || true
}
trap cleanup EXIT

say "preflight: nodes up, queue empty"
for n in $(ctl sinfo -h -N -n c1,c2 -t down,drain,fail -o "%N"); do ctl scontrol update NodeName="$n" State=RESUME; done
[ -z "$(ctl squeue -h)" ] || { say "FAIL: queue not empty; run this on an idle cluster"; exit 1; }

ctl rm -rf "$D" && ctl mkdir -p "$D"
docker cp --quiet policy slurmctld:/data/
# Stub feed: /qpus/<id>/state with status and next_recal.start = now + N feed min, where
# "now" (updated_at) is the wall clock (simulated). -i so the heredoc reaches cat.
docker exec -i slurmctld bash -c "cat > $D/stub_feed_recal.py" <<'PY'
import json, sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
STATE = sys.argv[1]
def iso(t): return t.isoformat(timespec="seconds").replace("+00:00", "Z")
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        qpu = self.path.strip("/").split("/")[1]
        st, mins = json.load(open(STATE))[qpu]
        now = datetime.now(timezone.utc)
        body = json.dumps({"id": qpu, "status": st, "healthy": True,
                           "status_reason": f"stub: {st} (simulated)",
                           "next_recal": {"start": iso(now + timedelta(minutes=mins)), "kind": "quick",
                                          "duration_min": 40},
                           "updated_at": iso(now), "simulated": True}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(body)
HTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()
PY

set_feed online 600 online 600
ctl bash -c "nohup python3 $D/stub_feed_recal.py $D/stub_state.json $STUB_PORT > $D/stub.out 2>&1 &"
sleep 1
ctl bash -c "cd /data/policy && nohup python3 predictive.py --feed http://localhost:$STUB_PORT --interval $INTERVAL --feed-speed $SPEED --out-dir $D > $D/loop.out 2>&1 &"
sleep 3

say "step 1: blockers take both QPUs"
b1=$(ctl sbatch --parsable -J blocker1 --gres=qpu:1 -w c1 --time=10:00 --mem=100M -c1 -o /dev/null --wrap "sleep 600")
b2=$(ctl sbatch --parsable -J blocker2 --gres=qpu:1 -w c2 --time=10:00 --mem=100M -c1 -o /dev/null --wrap "sleep 600")
wait_for 30 "blockers running" bash -c "[ \"\$(docker exec slurmctld squeue -h -j $b1,$b2 -t R -o %i | wc -l)\" = 2 ]"

say "step 2: victim submitted held -> gate releases it, it pends on Resources"
victim=$(ctl sbatch --parsable --hold -J victim --gres=qpu:1 --time=02:00 --mem=100M -c1 -o /dev/null --wrap "sleep 5")
wait_for 20 "victim released (Resources)" bash -c "docker exec slurmctld squeue -h -j $victim -o %r | grep -q Resources"
say "    victim $victim: $(reason "$victim")"

say "step 3: both recals in 30 feed min -> nothing fits -> gate re-holds it"
set_feed online 30 online 30
wait_for 20 "victim re-held" bash -c "docker exec slurmctld squeue -h -j $victim -o %r | grep -q JobHeld"
held_reason=$(ctl squeue -h -j "$victim" -o %r)
say "    victim $victim: $(reason "$victim")"

say "step 4: qpu1's recal back to 600 feed min -> released with ExcNodeList=c1; free c2"
set_feed online 30 online 600
wait_for 20 "victim released again" bash -c "! docker exec slurmctld squeue -h -j $victim -o %r | grep -q JobHeld"
exc=$(ctl scontrol show job "$victim" | grep -o 'ExcNodeList=[^ ]*')
say "    victim $victim: $(reason "$victim"), $exc"
ctl scancel "$b2"
wait_for 60 "victim done" bash -c "[ -z \"\$(docker exec slurmctld squeue -h -j $victim)\" ]"
sleep 2
read -r state node < <(ctl sacct -j "$victim" -X -n -P -o State,NodeList | tr '|' ' ')
say "    victim $victim: $state on $node"

echo "--- loop.out (gate lines)"
ctl grep " gate " "$D/loop.out" | sed 's/^/    /' || true
seq=$(ctl grep "\"job\": \"$victim\"" "$D/transitions.log" | python3 -c "import json,sys; print(' '.join(json.loads(l)['event'] for l in sys.stdin))")
echo "--- gate events for the victim: $seq"

if [ "$state" = COMPLETED ] && [ "$node" = c2 ] && [ "$held_reason" = JobHeldUser ] \
        && grep -q "gate_release gate_rehold gate_release" <<<"$seq"; then
    say "PASS: victim released, re-held (JobHeldUser), released onto c2 and COMPLETED (simulated)"
else
    say "FAIL: state=$state node=$node held_reason=$held_reason events=[$seq]"
    exit 1
fi

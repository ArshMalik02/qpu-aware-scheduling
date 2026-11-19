#!/usr/bin/env bash
# Repro: a QPU job pending when EVERY QPU goes out gets stuck in BadConstraints on
# Slurm 26.05.2, and the reactive loop's hold+release recheck recovers it. SIMULATED.
#
# Drives the real policy/reactive.py against a stub feed (inside slurmctld) whose
# per-QPU status this script sets, so the recheck path tested is the loop's own code.
#
# Steps:
#   1. stub: qpu0 paused, qpu1 online       -> loop sets c1 qpu:0
#   2. blocker job takes c2's QPU; victim QPU job pends (Resources)
#   3. stub: qpu1 paused too                 -> loop sets c2 qpu:0; victim -> BadConstraints
#   4. stub: both online                     -> loop restores both and rechecks the victim
#   5. PASS if the victim COMPLETED and transitions.log has a recheck event for it
#
# Usage (repo root, cluster up):  policy/repro_badconstraints.sh
set -euo pipefail

ctl() { docker exec slurmctld "$@"; }
cd "$(dirname "$0")/.."
D=/data/results/repro_badconstraints
STUB_PORT=8799
INTERVAL=2

say() { echo "[$(date -u +%H:%M:%SZ)] $*"; }
reason() { ctl squeue -h -j "$1" -o "%T %r" 2>/dev/null || true; }
wait_for() {  # wait_for <seconds> <description> <command...>
    local t=$1 desc=$2; shift 2
    for _ in $(seq 1 "$t"); do "$@" && return 0; sleep 1; done
    say "TIMEOUT waiting for: $desc"; return 1
}
set_feed() { ctl bash -c "printf '{\"qpu0\": \"$1\", \"qpu1\": \"$2\"}' > $D/stub_state.json"; }

cleanup() {
    ctl pkill -TERM -f "reactive.py --feed http://localhost:$STUB_PORT" >/dev/null 2>&1 || true
    sleep 1
    ctl pkill -f "stub_feed.py" >/dev/null 2>&1 || true
    [ -n "${blocker:-}" ] && ctl scancel "$blocker" >/dev/null 2>&1 || true
    [ -n "${victim:-}" ] && ctl scancel "$victim" >/dev/null 2>&1 || true
    ctl scontrol update NodeName=c1 Gres=qpu:1 >/dev/null 2>&1 || true
    ctl scontrol update NodeName=c2 Gres=qpu:1 >/dev/null 2>&1 || true
}
trap cleanup EXIT

say "preflight: nodes up, queue empty"
for n in $(ctl sinfo -h -N -n c1,c2 -t down,drain,fail -o "%N"); do ctl scontrol update NodeName="$n" State=RESUME; done
[ -z "$(ctl squeue -h)" ] || { say "FAIL: queue not empty; run this on an idle cluster"; exit 1; }

ctl rm -rf "$D" && ctl mkdir -p "$D"
docker cp --quiet policy slurmctld:/data/
# Stub feed: serves /qpus/<id>/state with the status from stub_state.json (simulated).
# -i so the heredoc reaches cat on stdin (without it the file is silently empty).
docker exec -i slurmctld bash -c "cat > $D/stub_feed.py" <<'PY'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
STATE = sys.argv[1]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        qpu = self.path.strip("/").split("/")[1]
        st = json.load(open(STATE))[qpu]
        body = json.dumps({"id": qpu, "status": st, "healthy": True,
                           "status_reason": f"stub: {st} (simulated)",
                           "updated_at": "stub", "simulated": True}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(body)
HTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()
PY

set_feed paused online
ctl bash -c "nohup python3 $D/stub_feed.py $D/stub_state.json $STUB_PORT > $D/stub.out 2>&1 &"
sleep 1
ctl bash -c "nohup python3 /data/policy/reactive.py --feed http://localhost:$STUB_PORT --interval $INTERVAL --out-dir $D > $D/loop.out 2>&1 &"

say "step 1: qpu0 paused -> loop takes c1's QPU out"
wait_for 20 "c1 qpu:0" bash -c "docker exec slurmctld sinfo -h -N -n c1 -o %G | grep -q 'qpu:0'"
ctl sinfo -N -o "    %N %G %t"

say "step 2: blocker holds c2's QPU; submit the victim QPU job"
blocker=$(ctl sbatch --parsable -J blocker --gres=qpu:1 -w c2 --mem=100M -c1 -o /dev/null --wrap "sleep 300")
wait_for 20 "blocker running" bash -c "[ \"\$(docker exec slurmctld squeue -h -j $blocker -o %T)\" = RUNNING ]"
victim=$(ctl sbatch --parsable -J victim --gres=qpu:1 --mem=100M -c1 -o /dev/null --wrap "true")
wait_for 30 "victim pending (Resources)" bash -c "docker exec slurmctld squeue -h -j $victim -o %r | grep -q Resources"
say "    victim $victim: $(reason "$victim")"

say "step 3: qpu1 paused too -> every QPU out"
set_feed paused paused
wait_for 20 "c2 qpu:0" bash -c "docker exec slurmctld sinfo -h -N -n c2 -o %G | grep -q 'qpu:0'"
ctl sinfo -N -o "    %N %G %t"
wait_for 60 "victim BadConstraints" bash -c "docker exec slurmctld squeue -h -j $victim -o %r | grep -q BadConstraints"
say "    victim $victim: $(reason "$victim")"

say "step 4: both online -> loop restores both QPUs and rechecks stuck jobs"
set_feed online online
wait_for 60 "victim done" bash -c "[ -z \"\$(docker exec slurmctld squeue -h -j $victim)\" ]"
sleep 2
state=$(ctl sacct -j "$victim" -X -n -o State | tr -d ' ')
say "    victim $victim: $state"

echo "--- loop.out"
ctl sed 's/^/    /' "$D/loop.out"
echo "--- recheck events in transitions.log"
rechecks=$(ctl grep '"event": "recheck"' "$D/transitions.log" || true)
echo "${rechecks:-    (none)}" | sed 's/^/    /'

if [ "$state" = COMPLETED ] && grep -q "\"job\": \"$victim\"" <<<"$rechecks"; then
    say "PASS: victim went Resources -> BadConstraints, was rechecked by the loop, and COMPLETED (simulated)"
else
    say "FAIL: victim state=$state; recheck logged for victim: $(grep -c "\"job\": \"$victim\"" <<<"$rechecks" || true)"
    exit 1
fi

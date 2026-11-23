#!/usr/bin/env python3
"""Predictive (recal-timing) QPU policy on Slurm 26.05.2. SIMULATED.

Does everything reactive.py does (QPU out while the feed says it isn't online, back in
after, BadConstraints recheck) plus one admission rule for QPU jobs:

    a job may start on a QPU only if, in feed time,
        now + job time limit + one poll interval <= that QPU's next_recal.start
    and the QPU is online right now.

The limit is the one Slurm enforces (squeue %l, whole minutes), converted to feed time
with --feed-speed. The poll interval is added because the feed is only read every
--interval seconds.

Mechanism on 26.05.2 (no HRES):
  - QPU jobs are submitted held (workload/gen.py --hold-qpu).
  - About every second, for each pending QPU job, the gate computes which QPUs fit:
      held  + some fit  -> scontrol update ExcNodeList=<nodes that don't fit>, release
      held  + none fit  -> stay held (logged once as gate_hold)
      released, pending + none fit any more -> scontrol uhold (gate_rehold)
      released, pending + fitting set changed -> update ExcNodeList (gate_exclude)
    That table is decide(), a pure function. "Held" is reason JobHeldUser or JobHeldAdmin:
    the gate runs as root, and as root `scontrol hold` is an admin hold (JobHeldAdmin),
    so re-holds use `scontrol uhold` (JobHeldUser) and both reasons count as held.
  - Between feed polls, feed time is extrapolated from the last poll at --feed-speed.

Difference from an HRES prerun gate: HRES evaluates a job at its prerun, just before
it starts, with job.end_time = start + time limit, and can return "not now" for that one
scheduling attempt. Here the decision is made from outside the scheduler, ahead of time,
by holding/releasing and per-job ExcNodeList, so there's up to ~1 s of gate lag and the
decision can be stale by the time Slurm picks the job. The rule itself is the same
comparison and would map onto hres_controller_job_prerun.

Every hold/release/exclude is logged to transitions.log (no "action" key, so the
recal-overlap metric is unaffected) with the job, its limit, and per QPU the time to the
next recal. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta

from reactive import DEFAULT_MAP, Loop, run, wall


def parse_feed_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_slurm_limit(s: str) -> float | None:
    """squeue %l ('4:00', '1:02:00', '1-00:00:00', 'UNLIMITED') -> seconds, or None."""
    s = s.strip()
    if not s or s in ("UNLIMITED", "INVALID", "NOT_SET"):
        return None
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = [int(p) for p in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts
    return days * 86400 + h * 3600 + m * 60 + sec


HELD_REASONS = ("JobHeldUser", "JobHeldAdmin")


def fits(status: str | None, now_feed: datetime, limit_feed_s: float, poll_feed_s: float,
         next_recal_start: datetime | None, healthy: bool | None = True) -> bool:
    """The admission rule (pure): QPU online and healthy, and the job ends before the next recal.

    healthy=False doesn't fit, matching reactive.py's layer-disable rule
    (status != "online" or healthy == false). A next_recal.start already in the past
    never fits.
    """
    if status != "online" or healthy is False:
        return False
    if next_recal_start is None:
        return True
    return now_feed + timedelta(seconds=limit_feed_s + poll_feed_s) <= next_recal_start


def fitting_nodes(states: dict[str, dict], mapping: dict[str, str], now_feed: dict[str, datetime],
                  limit_wall_s: float, speed: float, interval_s: float) -> list[str]:
    """Nodes whose QPU fits a job with this wall-clock limit (pure)."""
    out = []
    for qpu, node in mapping.items():
        st = states.get(qpu)
        if st is None or qpu not in now_feed:
            continue
        nr = (st.get("next_recal") or {}).get("start")
        if fits(st.get("status"), now_feed[qpu], limit_wall_s * speed, interval_s * speed,
                parse_feed_time(nr), st.get("healthy")):
            out.append(node)
    return sorted(out)


def decide(held: bool, fitting: list[str], all_nodes: list[str],
           current_exc: tuple[str, ...] | None) -> tuple[str, tuple[str, ...] | None]:
    """The gate's per-job decision (pure) -> (action, ExcNodeList to set).

    action is one of:
      release  held, some QPU fits: set ExcNodeList to the non-fitting nodes, release
      stay     held, no QPU fits: keep it held
      rehold   released (still pending), no QPU fits any more: hold it again
      exclude  released, fitting set changed: update ExcNodeList
      nothing  released, same fitting set
    """
    exc = tuple(n for n in all_nodes if n not in fitting)
    if held:
        return ("release", exc) if fitting else ("stay", current_exc)
    if not fitting:
        return "rehold", current_exc
    if exc != current_exc:
        return "exclude", exc
    return "nothing", current_exc


class PredictiveLoop(Loop):
    def __init__(self, a: argparse.Namespace):
        super().__init__(a)
        self.speed = a.feed_speed
        self.gate_every = a.gate_interval
        self._last_gate = 0.0
        self.jobs: dict[str, dict] = {}  # job id -> {"held": bool, "exc": tuple, "gated": bool}

    def now_feed(self) -> dict[str, datetime]:
        out, mono = {}, time.monotonic()
        for qpu, (st, at) in self.last_state.items():
            t = parse_feed_time(st.get("updated_at"))
            if t is not None:
                out[qpu] = t + timedelta(seconds=(mono - at) * self.speed)
        return out

    def log_gate(self, event: str, jid: str, limit_s: float, nodes: list[str], now: dict) -> None:
        per_qpu = {}
        for qpu, node in self.mapping.items():
            st = self.last_state.get(qpu, ({}, 0))[0]
            nr = parse_feed_time((st.get("next_recal") or {}).get("start"))
            ttr = round((nr - now[qpu]).total_seconds() / 60, 1) if nr and qpu in now else None
            per_qpu[qpu] = {"node": node, "status": st.get("status"), "to_next_recal_feed_min": ttr}
        feed_t = min(now.values()).isoformat().replace("+00:00", "Z") if now else None
        rec = {"wall": wall(), "feed_time": feed_t, "event": event, "job": jid, "limit_wall_s": limit_s,
               "limit_feed_min": round(limit_s * self.speed / 60, 1),
               "fitting_nodes": nodes, "qpus": per_qpu, "simulated": True}
        self.tlog.write(json.dumps(rec) + "\n")
        print(f"[{rec['wall']}] gate {event:12s} job {jid} limit {rec['limit_feed_min']} feed-min "
              f"fits={nodes or '-'} " + " ".join(f"{q}:{v['to_next_recal_feed_min']}" for q, v in per_qpu.items()),
              flush=True)

    def gate(self) -> None:
        if len(self.last_state) < len(self.mapping):
            return  # no feed state yet
        now = self.now_feed()
        states = {q: s for q, (s, _) in self.last_state.items()}
        out = run("squeue", "-h", "-t", "PD", "-o", "%i|%r|%b|%l")
        seen = set()
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) != 4 or "qpu" not in parts[2]:
                continue
            jid, reason, _, lim = parts
            seen.add(jid)
            limit_s = parse_slurm_limit(lim)
            if limit_s is None:
                continue
            ok = fitting_nodes(states, self.mapping, now, limit_s, self.speed, self.interval)
            held = reason in HELD_REASONS
            j = self.jobs.setdefault(jid, {"exc": None, "gated": False})
            action, exc = decide(held, ok, list(self.mapping.values()), j["exc"])
            if action == "release":
                run("scontrol", "update", f"JobId={jid}", f"ExcNodeList={','.join(exc)}")
                run("scontrol", "release", jid)
                j["exc"] = exc
                self.log_gate("gate_release", jid, limit_s, ok, now)
            elif action == "stay" and not j["gated"]:
                j["gated"] = True
                self.log_gate("gate_hold", jid, limit_s, ok, now)
            elif action == "rehold":
                run("scontrol", "uhold", jid)
                j["gated"] = True
                self.log_gate("gate_rehold", jid, limit_s, ok, now)
            elif action == "exclude":
                run("scontrol", "update", f"JobId={jid}", f"ExcNodeList={','.join(exc)}")
                j["exc"] = exc
                self.log_gate("gate_exclude", jid, limit_s, ok, now)
        for jid in list(self.jobs):
            if jid not in seen:
                del self.jobs[jid]

    def tick(self) -> None:
        super().tick()
        self.gate()

    def idle(self) -> None:
        if time.monotonic() - self._last_gate >= self.gate_every:
            self._last_gate = time.monotonic()
            self.gate()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Predictive (recal-timing) QPU policy (simulated).")
    p.add_argument("--feed", default="http://feed:8787")
    p.add_argument("--map", default=DEFAULT_MAP)
    p.add_argument("--interval", type=float, default=10.0, help="feed poll seconds (HRES example: 10)")
    p.add_argument("--gate-interval", type=float, default=1.0, help="gate check seconds")
    p.add_argument("--feed-speed", type=float, required=True, help="feed seconds per wall second")
    p.add_argument("--duration-s", type=float, default=0)
    p.add_argument("--out-dir", default="/data/results/predictive")
    a = p.parse_args(argv)
    a.observe_only = False
    PredictiveLoop(a).run()


if __name__ == "__main__":
    sys.exit(main())

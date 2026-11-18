#!/usr/bin/env python3
"""Reactive QPU up/down loop, emulating Slurm 26.11 HRES on Slurm 26.05.2. SIMULATED.

Every --interval seconds (default 10, the HRES example maintenance_cycle) it reads
each QPU's state from the simulated feed and sets the mapped node's GRES count:
    feed status == "online" and healthy != false  ->  scontrol update NodeName=<n> Gres=qpu:1
    otherwise                                      ->  scontrol update NodeName=<n> Gres=qpu:0
That mirrors the HRES layer-disable rule (status ~= "online" or healthy == false).
Removing the GRES count leaves the node up, so CPU-only jobs keep running.

Logs (append-only, one line per event):
    transitions.log  every QPU out/in change, with wall time and feed (simulated) time
    queue.log        one line per poll: each node's qpu count + pending/running jobs

On exit (SIGTERM, SIGINT or --duration-s), every node is restored to qpu:1: the
controller keeps qpu:0 across slurmd restarts (DEVLOG 2026-11-18), so the loop is
the only thing that brings a QPU back.

Runs inside slurmctld. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MAP = "qpu0=c1,qpu1=c2"


def wall() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def node_qpus(node: str) -> int:
    """Current qpu count on the node, as the controller sees it."""
    for tok in run("scontrol", "show", "node", node).split():
        if tok.startswith("Gres="):
            for g in tok[len("Gres="):].split(","):
                if g.startswith("qpu:"):
                    return int(g.split(":")[-1].split("(")[0])
            return 0
    return 0


def set_qpus(node: str, n: int) -> None:
    run("scontrol", "update", f"NodeName={node}", f"Gres=qpu:{n}")


def feed_state(feed: str, qpu: str) -> dict:
    with urllib.request.urlopen(f"{feed}/qpus/{qpu}/state", timeout=5) as r:
        return json.load(r)


def queue_snapshot() -> list[str]:
    # id, name, state, reason, requested gres, node
    out = run("squeue", "-h", "-o", "%i|%j|%T|%r|%b|%N")
    return [line for line in out.splitlines() if line.strip()]


class Loop:
    def __init__(self, a: argparse.Namespace):
        self.feed = a.feed.rstrip("/")
        self.mapping = dict(p.split("=") for p in a.map.split(","))
        self.interval = a.interval
        self.deadline = time.monotonic() + a.duration_s if a.duration_s else None
        out = Path(a.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.tlog = open(out / "transitions.log", "a", buffering=1)
        self.qlog = open(out / "queue.log", "a", buffering=1)
        self.stop = False

    def log_transition(self, node: str, qpu: str, old: int, new: int, st: dict | None, why: str) -> None:
        rec = {
            "wall": wall(), "feed_time": st.get("updated_at") if st else None,
            "node": node, "qpu": qpu, "qpu_count": f"{old}->{new}",
            "action": "QPU_OUT" if new == 0 else "QPU_IN",
            "feed_status": st.get("status") if st else None,
            "reason": why, "simulated": True,
        }
        self.tlog.write(json.dumps(rec) + "\n")
        print(f"[{rec['wall']}] feed={rec['feed_time']} {node}/{qpu} {rec['action']} "
              f"qpu:{old}->{new} ({why})", flush=True)

    def tick(self) -> None:
        counts, feed_time = {}, None
        for qpu, node in self.mapping.items():
            try:
                st = feed_state(self.feed, qpu)
            except Exception as e:  # keep the last state; HRES would hold jobs on a stale cache
                self.tlog.write(json.dumps({"wall": wall(), "node": node, "qpu": qpu,
                                            "error": f"feed unreachable: {e}"}) + "\n")
                counts[node] = node_qpus(node)
                continue
            feed_time = st.get("updated_at")
            want = 1 if (st.get("status") == "online" and st.get("healthy") is not False) else 0
            have = node_qpus(node)
            if want != have:
                set_qpus(node, want)
                self.log_transition(node, qpu, have, want, st,
                                    f"{st.get('status')}: {st.get('status_reason')}")
            counts[node] = want
        self.qlog.write(json.dumps({"wall": wall(), "feed_time": feed_time, "qpus": counts,
                                    "queue": queue_snapshot()}) + "\n")

    def restore_all(self) -> None:
        for qpu, node in self.mapping.items():
            have = node_qpus(node)
            if have != 1:
                set_qpus(node, 1)
                self.log_transition(node, qpu, have, 1, None, "loop exit: restore")

    def run(self) -> None:
        def _stop(*_):
            self.stop = True
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        print(f"[{wall()}] reactive loop: feed={self.feed} map={self.mapping} "
              f"interval={self.interval}s (simulated)", flush=True)
        try:
            while not self.stop and (self.deadline is None or time.monotonic() < self.deadline):
                self.tick()
                end = time.monotonic() + self.interval
                while not self.stop and time.monotonic() < end:
                    time.sleep(0.2)
        finally:
            self.restore_all()
            print(f"[{wall()}] reactive loop stopped; all QPUs restored", flush=True)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Reactive QPU up/down loop (HRES-like, simulated).")
    p.add_argument("--feed", default="http://feed:8787")
    p.add_argument("--map", default=DEFAULT_MAP, help=f"qpu=node pairs (default {DEFAULT_MAP})")
    p.add_argument("--interval", type=float, default=10.0, help="poll seconds (HRES example: 10)")
    p.add_argument("--duration-s", type=float, default=0, help="stop after N seconds (0 = until signalled)")
    p.add_argument("--out-dir", default="/data/results/reactive")
    a = p.parse_args(argv)
    Loop(a).run()


if __name__ == "__main__":
    sys.exit(main())

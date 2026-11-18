#!/usr/bin/env python3
"""Summarize a reactive-baseline run and check the done-when. SIMULATED results.

Reads, from --run-dir: sacct.txt (sacct -X -P), submitted.log, transitions.log, queue.log.
Writes: jobs.csv (submit, start, end, QPU-wait per job) and summary.json.
Prints three checks and PASS/FAIL:
  1. the loop took a QPU out and restored it (QPU_OUT and QPU_IN transitions)
  2. a QPU job was PENDING at a poll where some node's QPU was out
  3. a classical job was RUNNING on a node whose QPU was out at that poll
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path


def ts(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args(argv)
    d = Path(a.run_dir)

    submitted = {r["job_id"]: r for r in load_jsonl(d / "submitted.log")}
    rows = list(csv.DictReader((d / "sacct.txt").read_text().splitlines(), delimiter="|"))
    jobs = []
    for r in rows:
        if r["JobID"] not in submitted:
            continue
        sub, start, end = ts(r["Submit"]), ts(r["Start"]), ts(r["End"])
        rec = submitted[r["JobID"]]
        kind = rec["type"]
        wait = (start - sub).total_seconds() if sub and start else None
        delay = rec.get("submit_delay_s", 0.0)
        # QPU wait = time sbatch kept rejecting it (no QPU configured anywhere) + queue wait.
        qwait = round(delay + wait, 2) if wait is not None else None
        jobs.append({"job_id": r["JobID"], "name": r["JobName"], "type": kind,
                     "state": r["State"], "node": r["NodeList"], "submit": r["Submit"],
                     "start": r["Start"], "end": r["End"],
                     "submit_delay_s": delay, "queue_wait_s": wait,
                     "qpu_wait_s": qwait if kind != "classical" else ""})
    with open(d / "jobs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(jobs[0]) if jobs else ["job_id"])
        w.writeheader()
        w.writerows(jobs)

    trans = [t for t in load_jsonl(d / "transitions.log") if "action" in t]
    polls = load_jsonl(d / "queue.log")

    pending_examples, running_examples = [], []
    for p in polls:
        out_nodes = {n for n, c in p["qpus"].items() if c == 0}
        if not out_nodes:
            continue
        for line in p["queue"]:
            jid, name, state, reason, gres, node = (line.split("|") + [""] * 6)[:6]
            if state == "PENDING" and "qpu" in gres:
                pending_examples.append({"wall": p["wall"], "feed_time": p["feed_time"],
                                         "qpus_out_on": sorted(out_nodes), "job": jid,
                                         "name": name, "reason": reason})
            if state == "RUNNING" and name.startswith("classical") and node in out_nodes:
                running_examples.append({"wall": p["wall"], "feed_time": p["feed_time"],
                                         "node": node, "job": jid, "name": name})

    def stats(xs):
        xs = [x for x in xs if isinstance(x, (int, float))]
        if not xs:
            return None
        xs.sort()
        return {"n": len(xs), "mean_s": round(statistics.mean(xs), 1),
                "median_s": round(statistics.median(xs), 1),
                "p95_s": round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 1), "max_s": round(xs[-1], 1)}

    summary = {
        "simulated": True,
        "jobs_by_type": {k: sum(j["type"] == k for j in jobs) for k in ("qpu", "hybrid", "classical")},
        "states": {s: sum(j["state"] == s for j in jobs) for s in sorted({j["state"] for j in jobs})},
        "qpu_wait": {k: stats([j["qpu_wait_s"] for j in jobs if j["type"] == k]) for k in ("qpu", "hybrid")},
        "rejected_at_submit_all_qpus_out": [
            {"job_id": j["job_id"], "name": j["name"], "submit_delay_s": j["submit_delay_s"]}
            for j in jobs if j["submit_delay_s"] and j["submit_delay_s"] > 1],
        "classical_queue_wait": stats([j["queue_wait_s"] for j in jobs if j["type"] == "classical"]),
        "transitions": {"QPU_OUT": sum(t["action"] == "QPU_OUT" for t in trans),
                        "QPU_IN": sum(t["action"] == "QPU_IN" for t in trans)},
        "polls": len(polls),
        "polls_with_qpu_out": sum(any(c == 0 for c in p["qpus"].values()) for p in polls),
        "qpu_job_pending_while_qpu_out": {"count": len(pending_examples), "first": pending_examples[:3]},
        "classical_running_on_qpu_out_node": {"count": len(running_examples), "first": running_examples[:3]},
    }
    checks = {
        "1_qpu_taken_out_and_restored": summary["transitions"]["QPU_OUT"] > 0 and summary["transitions"]["QPU_IN"] > 0,
        "2_qpu_job_pending_while_qpu_out": len(pending_examples) > 0,
        "3_classical_running_on_qpu_out_node": len(running_examples) > 0,
    }
    summary["checks"] = checks
    (d / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps({k: summary[k] for k in ("jobs_by_type", "states", "transitions", "qpu_wait",
                                              "classical_queue_wait", "rejected_at_submit_all_qpus_out")},
                     indent=2))
    for k, v in checks.items():
        print(f"    {k}: {'ok' if v else 'NO'}")
    ok = all(checks.values())
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

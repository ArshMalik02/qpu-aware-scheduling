#!/usr/bin/env python3
"""Summarize a baseline run and check the done-when. SIMULATED results.

Reads, from --run-dir:
  run_config.json   feed_speed etc. (written by the run script)
  sacct.txt         sacct -X -P
  submitted.log     one line per submitted job (gen.py)
  transitions.log   QPU_OUT / QPU_IN events per node (reactive.py, or reactive.py --observe-only)
  queue.log         one squeue snapshot per poll
Writes jobs.csv and summary.json, prints the key numbers and four checks:
  0. every submitted job COMPLETED (so a run where nothing executed can't pass)
  1. the loop took a QPU out and restored it (QPU_OUT and QPU_IN transitions)
  2. a QPU job was PENDING (reason Resources) at a poll where some node's QPU was out
  3. a classical job was RUNNING on a node whose QPU was out at that poll

Units: hold times and waits are wall seconds; the feed runs at feed_speed simulated
seconds per wall second, so every wait/overlap is also given in feed minutes
(wall_s * feed_speed / 60). feed_speed is read from run_config.json, never assumed.

The recal-overlap metric (recal_overlap()) is the one the three policies are compared on,
so it depends only on jobs.csv and the QPU_OUT/QPU_IN events, measured the same way for
every policy.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path


def ts(s: str | None) -> datetime | None:
    """Parse sacct (naive, UTC in the containers) and loop ('...Z') timestamps as naive UTC."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=None)
    except ValueError:
        return None


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def feed_min(wall_s: float, speed: float) -> float:
    return round(wall_s * speed / 60, 1)


def stats(xs: list, speed: float) -> dict | None:
    """Wait statistics in wall seconds and in feed minutes."""
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return None
    w = {"mean": statistics.mean(xs), "median": statistics.median(xs),
         "p95": xs[min(len(xs) - 1, int(0.95 * len(xs)))], "max": xs[-1]}
    return {"n": len(xs),
            "wall_s": {k: round(v, 1) for k, v in w.items()},
            "feed_min": {k: feed_min(v, speed) for k, v in w.items()}}


def recal_windows(transitions: list[dict], run_end: datetime) -> dict[str, list[tuple[datetime, datetime]]]:
    """Per node, the [QPU_OUT, next QPU_IN) windows from transitions.log (no QPU_IN -> run end)."""
    by_node: dict[str, list[tuple[datetime, str]]] = {}
    for t in transitions:
        if "action" in t and ts(t.get("wall")):
            by_node.setdefault(t["node"], []).append((ts(t["wall"]), t["action"]))
    windows: dict[str, list[tuple[datetime, datetime]]] = {}
    for node, evs in by_node.items():
        evs.sort()
        for i, (t_out, action) in enumerate(evs):
            if action != "QPU_OUT":
                continue
            t_in = next((t for t, a in evs[i + 1:] if a == "QPU_IN"), run_end)
            windows.setdefault(node, []).append((t_out, t_in))
    return windows


def recal_overlap(jobs: list[dict], transitions: list[dict], speed: float, run_end: datetime) -> dict:
    """QPU/hybrid jobs whose run overlapped a recal window on their node.

    A window is [QPU_OUT, next QPU_IN) on node N (no QPU_IN -> run end). A QPU or hybrid job
    on N overlaps by |[start, end) ∩ window|, summed over every window: how long it used a
    QPU that the feed said was recalibrating. This counts jobs already running at QPU_OUT
    and jobs that start during the window (which only a policy that doesn't take QPUs out,
    e.g. static, lets happen). Event times are the poll times in transitions.log, so the
    up-to-one-poll lag is the same for every policy that logs them the same way.
    """
    windows = recal_windows(transitions, run_end)
    hits = []
    for j in jobs:
        if j["type"] == "classical":
            continue
        start, end = ts(j["start"]), ts(j["end"])
        if not (start and end):
            continue
        parts = []
        for w_out, w_in in windows.get(j["node"], []):
            ov = (min(end, w_in) - max(start, w_out)).total_seconds()
            if ov > 0:
                parts.append((w_out, ov))
        if parts:
            ov = sum(o for _, o in parts)
            hits.append({"job_id": j["job_id"], "name": j["name"], "type": j["type"], "node": j["node"],
                         "qpu_out_at": [w.isoformat() + "Z" for w, _ in parts],
                         "overlap_parts_wall_s": [round(o, 1) for _, o in parts],
                         "started_inside_window": any(w_out <= start < w_in for w_out, w_in in windows.get(j["node"], [])),
                         "overlap_wall_s": round(ov, 1), "overlap_feed_min": feed_min(ov, speed)})
    total = sum(h["overlap_wall_s"] for h in hits)
    return {"count": len(hits), "jobs": hits,
            "total_overlap_wall_s": round(total, 1), "total_overlap_feed_min": feed_min(total, speed)}


def forecast_split(overlap: dict, transitions: list[dict], forecast: list[dict],
                   mapping: dict[str, str], speed: float, feed_end: datetime | None) -> dict:
    """Split recal overlap by the direction of each recal's forecast error (simulated).

    forecast.log has one line per recal: true_start, published_start, offset_s
    (= published - true). offset > 0: the recal came EARLIER than published, so a job
    the gate let start can run into it. offset < 0: it came LATER than published, which
    can only make the gate hold jobs longer. Each overlapping window (a logged QPU_OUT on
    a node) is matched to the recal on that node's QPU whose true [start, end) contains
    the QPU_OUT's feed time.
    """
    node_qpu = {n: q for q, n in mapping.items()}
    out_feed = {(t["node"], t["wall"]): ts(t.get("feed_time")) for t in transitions if t.get("action") == "QPU_OUT"}

    def recal_for(node: str, wall: str) -> dict | None:
        ft = out_feed.get((node, wall))
        for r in forecast:
            if r["qpu"] == node_qpu.get(node) and ft and ts(r["true_start"]) <= ft < ts(r["true_end"]):
                return r
        return None

    def direction(r: dict | None) -> str:
        if r is None:
            return "unmatched"
        return "exact" if r["offset_s"] == 0 else ("earlier_than_published" if r["offset_s"] > 0 else "later_than_published")

    keys = ("earlier_than_published", "later_than_published", "exact", "unmatched")
    by_dir = {k: {"jobs": set(), "wall_s": 0.0} for k in keys}
    per_recal: dict[tuple, dict] = {}
    for h in overlap["jobs"]:
        for wall, part in zip(h["qpu_out_at"], h.get("overlap_parts_wall_s", [h["overlap_wall_s"]])):
            r = recal_for(h["node"], wall)
            k = direction(r)
            by_dir[k]["jobs"].add(h["job_id"])
            by_dir[k]["wall_s"] += part
            if r is not None:
                pr = per_recal.setdefault((r["qpu"], r["true_start"]), {"jobs": set(), "wall_s": 0.0})
                pr["jobs"].add(h["job_id"]); pr["wall_s"] += part
    in_run = [r for r in forecast if feed_end is None or ts(r["true_start"]) <= feed_end]
    recals = []
    for r in in_run:
        pr = per_recal.get((r["qpu"], r["true_start"]), {"jobs": set(), "wall_s": 0.0})
        recals.append({"qpu": r["qpu"], "node": mapping.get(r["qpu"]), "kind": r["kind"],
                       "true_start": r["true_start"], "published_start": r["published_start"],
                       "offset_min": r["offset_min"], "direction": direction(r),
                       "overlap_jobs": len(pr["jobs"]), "overlap_wall_s": round(pr["wall_s"], 1),
                       "overlap_feed_min": feed_min(pr["wall_s"], speed)})
    return {"recals_in_run": recals,
            "overlap_by_direction": {k: {"jobs": len(v["jobs"]), "wall_s": round(v["wall_s"], 1),
                                         "feed_min": feed_min(v["wall_s"], speed)} for k, v in by_dir.items()},
            "recals_by_direction": {k: sum(r["direction"] == k for r in recals) for k in keys[:3]}}


def _makespan(jobs: list[dict], speed: float) -> dict | None:
    subs = [ts(j["submit"]) for j in jobs if ts(j["submit"])]
    ends = [ts(j["end"]) for j in jobs if ts(j["end"])]
    if not subs or not ends:
        return None
    w = (max(ends) - min(subs)).total_seconds()
    return {"wall_s": round(w, 1), "feed_min": feed_min(w, speed)}


def _gate_counts(events: list[dict]) -> dict:
    """Predictive gate events (empty counts for other policies).

    Every QPU job is submitted held, so "held" alone means nothing. jobs_kept_held counts the
    jobs the gate kept held at least once: it found no fitting QPU at its first look
    (gate_hold), or it re-held them after release (gate_rehold).
    """
    g = [e for e in events if str(e.get("event", "")).startswith("gate_")]
    held = {e["job"] for e in g if e["event"] in ("gate_hold", "gate_rehold")}
    return {"jobs_kept_held": len(held),
            "releases": sum(e["event"] == "gate_release" for e in g),
            "reholds": sum(e["event"] == "gate_rehold" for e in g),
            "excludes_updated": sum(e["event"] == "gate_exclude" for e in g)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args(argv)
    d = Path(a.run_dir)

    cfg = json.loads((d / "run_config.json").read_text())
    speed = float(cfg["feed_speed"])

    submitted = {r["job_id"]: r for r in load_jsonl(d / "submitted.log")}
    rows = list(csv.DictReader((d / "sacct.txt").read_text().splitlines(), delimiter="|"))
    jobs = []
    for r in rows:
        if r["JobID"] not in submitted:
            continue
        sub, start = ts(r["Submit"]), ts(r["Start"])
        rec = submitted[r["JobID"]]
        kind = rec["type"]
        wait = (start - sub).total_seconds() if sub and start else None
        delay = rec.get("submit_delay_s", 0.0)
        # QPU wait = time sbatch kept rejecting it (no QPU configured anywhere) + queue wait.
        qwait = round(delay + wait, 2) if wait is not None else None
        end = ts(r["End"])
        # Completion = end - intended arrival (submit time minus any submit-rejection delay).
        comp = round((end - sub).total_seconds() + delay, 2) if end and sub and r["State"] == "COMPLETED" else None
        jobs.append({"job_id": r["JobID"], "name": r["JobName"], "type": kind,
                     "state": r["State"], "node": r["NodeList"], "submit": r["Submit"],
                     "start": r["Start"], "end": r["End"], "completion_s": comp,
                     "submit_delay_s": delay, "queue_wait_s": wait,
                     "qpu_wait_s": qwait if kind != "classical" else "",
                     "qpu_wait_feed_min": feed_min(qwait, speed) if kind != "classical" and qwait is not None else ""})
    with open(d / "jobs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(jobs[0]) if jobs else ["job_id"])
        w.writeheader()
        w.writerows(jobs)

    trans = [t for t in load_jsonl(d / "transitions.log") if "action" in t]
    polls = load_jsonl(d / "queue.log")
    ends = [ts(j["end"]) for j in jobs if ts(j["end"])] + [ts(t["wall"]) for t in trans]
    run_end = max(ends) if ends else datetime.max

    pending_examples, running_examples = [], []
    for p in polls:
        out_nodes = {n for n, c in p["qpus"].items() if c == 0}
        if not out_nodes:
            continue
        for line in p["queue"]:
            jid, name, state, reason, gres, node = (line.split("|") + [""] * 6)[:6]
            # Only "Resources": that's what a missing qpu GRES produces. Other reasons
            # (e.g. ReqNodeNotAvail when nodes are down) aren't caused by the loop.
            if state == "PENDING" and "qpu" in gres and reason == "Resources":
                pending_examples.append({"wall": p["wall"], "feed_time": p["feed_time"],
                                         "qpus_out_on": sorted(out_nodes), "job": jid,
                                         "name": name, "reason": reason})
            if state == "RUNNING" and name.startswith("classical") and node in out_nodes:
                running_examples.append({"wall": p["wall"], "feed_time": p["feed_time"],
                                         "node": node, "job": jid, "name": name})

    summary = {
        "simulated": True,
        "run_config": cfg,
        "units": "wall_s = wall-clock seconds; feed_min = wall_s * feed_speed / 60 (simulated feed minutes)",
        "jobs_by_type": {k: sum(j["type"] == k for j in jobs) for k in ("qpu", "hybrid", "classical")},
        "states": {s: sum(j["state"] == s for j in jobs) for s in sorted({j["state"] for j in jobs})},
        "qpu_wait": {k: stats([j["qpu_wait_s"] for j in jobs if j["type"] == k], speed) for k in ("qpu", "hybrid")},
        "classical_queue_wait": stats([j["queue_wait_s"] for j in jobs if j["type"] == "classical"], speed),
        "completion": {k: stats([j["completion_s"] for j in jobs if j["type"] == k], speed)
                       for k in ("qpu", "hybrid", "classical")},
        "completion_all": stats([j["completion_s"] for j in jobs], speed),
        "makespan": _makespan(jobs, speed),
        "jobs_total": len(jobs),
        "jobs_completed": sum(j["state"] == "COMPLETED" for j in jobs),
        "submit_rejections": sum(1 for j in jobs if j["submit_delay_s"] and j["submit_delay_s"] > 1),
        "gate": _gate_counts(load_jsonl(d / "transitions.log")),
        "rejected_at_submit_all_qpus_out": [
            {"job_id": j["job_id"], "name": j["name"], "submit_delay_s": j["submit_delay_s"],
             "submit_delay_feed_min": feed_min(j["submit_delay_s"], speed)}
            for j in jobs if j["submit_delay_s"] and j["submit_delay_s"] > 1],
        "recal_overlap": recal_overlap(jobs, trans, speed, run_end),
        "rechecks_badconstraints": [t["job"] for t in load_jsonl(d / "transitions.log")
                                    if t.get("event") == "recheck"],
        "transitions": {"QPU_OUT": sum(t["action"] == "QPU_OUT" for t in trans),
                        "QPU_IN": sum(t["action"] == "QPU_IN" for t in trans)},
        "polls": len(polls),
        "polls_with_qpu_out": sum(any(c == 0 for c in p["qpus"].values()) for p in polls),
        "qpu_job_pending_while_qpu_out": {"count": len(pending_examples), "first": pending_examples[:3]},
        "classical_running_on_qpu_out_node": {"count": len(running_examples), "first": running_examples[:3]},
    }
    policy = cfg.get("policy", "reactive")
    checks = {
        "0_all_jobs_completed": bool(jobs) and all(j["state"] == "COMPLETED" for j in jobs),
        # static only observes the recal windows (reactive.py --observe-only), so check 1
        # means "windows were observed" there, and 2-3 (QPU actually taken out) don't apply.
        "1_qpu_taken_out_and_restored": summary["transitions"]["QPU_OUT"] > 0 and summary["transitions"]["QPU_IN"] > 0,
    }
    if policy != "static":
        checks["2_qpu_job_pending_while_qpu_out"] = len(pending_examples) > 0
        checks["3_classical_running_on_qpu_out_node"] = len(running_examples) > 0
    summary["checks"] = checks
    # Forecast error (feed --forecast-err-min): split overlap by early/late recals.
    summary["forecast_err_min"] = cfg.get("forecast_err_min", 0)
    if (d / "forecast.log").exists():
        mapping = dict(kv.split("=") for kv in cfg.get("map", "qpu0=c1,qpu1=c2").split(","))
        feed_times = [ts(q.get("feed_time")) for q in load_jsonl(d / "queue.log") if q.get("feed_time")]
        summary["forecast"] = forecast_split(summary["recal_overlap"], trans, load_jsonl(d / "forecast.log"),
                                             mapping, speed, max(feed_times) if feed_times else None)
    (d / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(json.dumps({k: summary[k] for k in ("jobs_by_type", "states", "transitions", "qpu_wait",
                                              "classical_queue_wait", "completion_all", "makespan",
                                              "rejected_at_submit_all_qpus_out", "recal_overlap",
                                              "rechecks_badconstraints", "gate")}, indent=2))
    print(f"    policy: {policy}")
    for k, v in checks.items():
        print(f"    {k}: {'ok' if v else 'NO'}")
    ok = all(checks.values())
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Aggregate sweep runs into results/sweep_summary.csv and results/sweep_table.md. SIMULATED.

Reads results/<policy>/seed<N>/summary.json for every policy and seed present.
  sweep_summary.csv  one row per policy x seed (wall s and feed min)
  sweep_table.md     per policy: median across seeds, with [min-max] across seeds
Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path

POLICIES = ("static", "reactive", "predictive")


def g(d, *path):
    for k in path:
        if d is None:
            return None
        d = d.get(k) if isinstance(d, dict) else None
    return d


def row_for(policy: str, seed: int, s: dict) -> dict:
    cfg = s.get("run_config", {})
    ov = s.get("recal_overlap", {})
    r = {"policy": policy, "seed": seed, "feed_seed": cfg.get("feed_seed"),
         "feed_speed": cfg.get("feed_speed"), "run_min": cfg.get("run_min"),
         "jobs_total": s.get("jobs_total"), "jobs_completed": s.get("jobs_completed"),
         "recal_overlap_jobs": ov.get("count"),
         "recal_overlap_wall_s": ov.get("total_overlap_wall_s"),
         "recal_overlap_feed_min": ov.get("total_overlap_feed_min")}
    for label, key in (("qpu", ("qpu_wait", "qpu")), ("hybrid", ("qpu_wait", "hybrid")),
                       ("classical", ("classical_queue_wait",))):
        for q in ("median", "p95"):
            r[f"{label}_wait_{q}_wall_s"] = g(s, *key, "wall_s", q)
            r[f"{label}_wait_{q}_feed_min"] = g(s, *key, "feed_min", q)
    for q in ("median", "p95"):
        r[f"completion_{q}_wall_s"] = g(s, "completion_all", "wall_s", q)
        r[f"completion_{q}_feed_min"] = g(s, "completion_all", "feed_min", q)
    r["makespan_wall_s"] = g(s, "makespan", "wall_s")
    r["makespan_feed_min"] = g(s, "makespan", "feed_min")
    r["submit_rejections"] = s.get("submit_rejections")
    r["gate_jobs_kept_held"] = g(s, "gate", "jobs_kept_held")
    r["gate_reholds"] = g(s, "gate", "reholds")
    r["badconstraints_rechecks"] = len(s.get("rechecks_badconstraints", []))
    r["checks_pass"] = all(s.get("checks", {}).values()) if s.get("checks") else None
    r["simulated"] = True
    return r


def collect(results: Path) -> list[dict]:
    rows = []
    for policy in POLICIES:
        for d in sorted((results / policy).glob("seed*")):
            m = re.fullmatch(r"seed(\d+)", d.name)
            if not m or not (d / "summary.json").exists():
                continue  # e.g. seed1-aarch64 or an incomplete run
            rows.append(row_for(policy, int(m.group(1)), json.loads((d / "summary.json").read_text())))
    return rows


TABLE = [  # (label, column, unit)
    ("Recal-overlap jobs", "recal_overlap_jobs", ""),
    ("Recal overlap (feed min)", "recal_overlap_feed_min", ""),
    ("QPU-only wait median (feed min)", "qpu_wait_median_feed_min", ""),
    ("QPU-only wait p95 (feed min)", "qpu_wait_p95_feed_min", ""),
    ("Hybrid wait p95 (feed min)", "hybrid_wait_p95_feed_min", ""),
    ("Classical wait p95 (feed min)", "classical_wait_p95_feed_min", ""),
    ("Completion median (feed min)", "completion_median_feed_min", ""),
    ("Completion p95 (feed min)", "completion_p95_feed_min", ""),
    ("Jobs completed", "jobs_completed", ""),
    ("Submit rejections", "submit_rejections", ""),
    ("Gate: jobs kept held at least once", "gate_jobs_kept_held", ""),
    ("Gate: re-holds", "gate_reholds", ""),
]


def fmt(x) -> str:
    if x is None:
        return "–"
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def table_md(rows: list[dict]) -> str:
    policies = [p for p in POLICIES if any(r["policy"] == p for r in rows)]
    seeds = {p: sorted(r["seed"] for r in rows if r["policy"] == p) for p in policies}
    out = ["# Sweep results (simulated)", "",
           "Median across seeds, with [min–max] across seeds. Drift, recal schedule and job times are "
           "assumed; all numbers are from the Docker cluster with a simulated feed, not hardware.", "",
           "p95 is the value at index int(0.95·n) of the sorted waits, so for n ≤ 20 it is the "
           "maximum: one job. Every QPU job is submitted held under "
           "predictive; the gate rows count jobs it kept held (no QPU fitted) at least once.", "",
           "| Metric | " + " | ".join(f"{p} (seeds {','.join(map(str, seeds[p]))})" for p in policies) + " |",
           "|---|" + "---|" * len(policies)]
    for label, col, _ in TABLE:
        cells = []
        for p in policies:
            xs = [r[col] for r in rows if r["policy"] == p and isinstance(r[col], (int, float))]
            if not xs:
                cells.append("–")
            elif len(xs) == 1:
                cells.append(fmt(xs[0]))
            else:
                cells.append(f"{fmt(round(statistics.median(xs), 2))} [{fmt(min(xs))}–{fmt(max(xs))}]")
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    a = ap.parse_args(argv)
    res = Path(a.results)
    rows = collect(res)
    if not rows:
        print("no results/<policy>/seed<N>/summary.json found", file=sys.stderr)
        return 1
    with open(res / "sweep_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (res / "sweep_table.md").write_text(table_md(rows))
    print(f"wrote {res / 'sweep_summary.csv'} ({len(rows)} rows) and {res / 'sweep_table.md'} (simulated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

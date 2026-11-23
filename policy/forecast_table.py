#!/usr/bin/env python3
"""Forecast-error table: results/forecast_err/table.md. SIMULATED, one seed.

Columns: static and reactive seed 1 (results/<policy>/seed1, the committed sweep runs),
predictive at N = 0 (results/predictive/seed1, exact forecast) and at each N in
results/forecast_err/N<k>/seed1 (feed --forecast-err-min N). Checks that every run's
manifest.json is byte-identical to static seed 1's. Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def g(d, *path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def fmt(x) -> str:
    if x is None:
        return "–"
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    res = Path(a.results)
    s = a.seed
    runs = [("static", res / "static" / f"seed{s}"), ("reactive", res / "reactive" / f"seed{s}"),
            ("predictive N=0", res / "predictive" / f"seed{s}")]
    ns = sorted(int(m.group(1)) for p in (res / "forecast_err").glob("N*")
                if (m := re.fullmatch(r"N(\d+)", p.name)) and (p / f"seed{s}" / "summary.json").exists())
    runs += [(f"predictive N={n}", res / "forecast_err" / f"N{n}" / f"seed{s}") for n in ns]
    S = {name: json.loads((d / "summary.json").read_text()) for name, d in runs}
    md5 = {name: hashlib.md5((d / "manifest.json").read_bytes()).hexdigest() for name, d in runs}
    ref = md5["static"]
    same = all(v == ref for v in md5.values())

    def cushion(name, d):
        """Smallest (Slurm limit - actual run time) over QPU/hybrid jobs + one poll, feed min.

        The gate starts a job only if start + limit + poll <= published start, so an early
        recal (offset > 0) can reach the job only if offset > limit - run + poll.
        """
        if "predictive" not in name:
            return None
        cfg = json.loads((d / "run_config.json").read_text())
        speed, poll = float(cfg["feed_speed"]), float(cfg.get("poll_interval_s", 10))
        man = {f"{j['type']}-{j['idx']:03d}": j for j in json.loads((d / "manifest.json").read_text())["jobs"]}
        best = None
        for j in csv.DictReader((d / "jobs.csv").read_text().splitlines()):
            if j["type"] == "classical" or not (j["start"] and j["end"]):
                continue
            run = (datetime.fromisoformat(j["end"]) - datetime.fromisoformat(j["start"])).total_seconds()
            c = (man[j["name"]]["slurm_limit_s"] - run + poll) * speed / 60
            best = c if best is None else min(best, c)
        return round(best, 1) if best is not None else None

    def max_early(name):
        rec = g(S[name], "forecast", "recals_in_run")
        if rec is None:
            return None if name in ("static", "reactive") else 0
        return max([r["offset_min"] for r in rec if r["offset_min"] > 0], default=0)

    def ovd(name, k, field):
        f = S[name].get("forecast")
        if f is None:
            return None if name in ("static", "reactive") else 0  # N=0: no forecast error, nothing to split
        return g(f, "overlap_by_direction", k, field)

    rows = [
        ("Forecast error N (feed min)", lambda n: None if n in ("static", "reactive") else S[n].get("forecast_err_min", 0)),
        ("Largest early offset in the run (feed min)", max_early),
        ("Smallest gate cushion: limit − actual run + poll (feed min)", lambda n: cushion(n, dict(runs)[n])),
        ("Recal-overlap jobs", lambda n: g(S[n], "recal_overlap", "count")),
        ("Recal overlap (feed min)", lambda n: g(S[n], "recal_overlap", "total_overlap_feed_min")),
        ("… from recals earlier than published: jobs", lambda n: ovd(n, "earlier_than_published", "jobs")),
        ("… from recals earlier than published: feed min", lambda n: ovd(n, "earlier_than_published", "feed_min")),
        ("… from recals later than published: jobs", lambda n: ovd(n, "later_than_published", "jobs")),
        ("… from recals later than published: feed min", lambda n: ovd(n, "later_than_published", "feed_min")),
        ("QPU-only wait p95 (feed min)", lambda n: g(S[n], "qpu_wait", "qpu", "feed_min", "p95")),
        ("Hybrid wait p95 (feed min)", lambda n: g(S[n], "qpu_wait", "hybrid", "feed_min", "p95")),
        ("Classical wait p95 (feed min)", lambda n: g(S[n], "classical_queue_wait", "feed_min", "p95")),
        ("Completion p95 (feed min)", lambda n: g(S[n], "completion_all", "feed_min", "p95")),
        ("Jobs completed / total", lambda n: f"{S[n].get('jobs_completed')}/{S[n].get('jobs_total')}"),
        ("Gate: jobs kept held at least once", lambda n: g(S[n], "gate", "jobs_kept_held") if "predictive" in n else None),
        ("Gate: releases", lambda n: g(S[n], "gate", "releases") if "predictive" in n else None),
        ("Gate: re-holds", lambda n: g(S[n], "gate", "reholds") if "predictive" in n else None),
        ("Gate: ExcNodeList updates", lambda n: g(S[n], "gate", "excludes_updated") if "predictive" in n else None),
    ]
    names = [n for n, _ in runs]
    out = [f"# Forecast error, seed {s} (simulated, one seed)", "",
           f"Predictive policy with the feed's published `next_recal.start` = true start + u·N feed min, "
           f"u ~ U(−1, 1) seeded per recal (feed `--forecast-err-min N`); the recal itself happens at the "
           f"true start. Workload seed {s}, feed seed {100 + s}, RUN_MIN 30, 36× (1 wall s = 0.6 feed min). "
           "Static and reactive don't read `next_recal`, so they're the committed sweep runs, unaffected by N. "
           "Drift, the recal schedule and job times are assumed. One seed: observations, not results.", "",
           f"Job manifest byte-identical to static seed {s} in every column: **{'yes' if same else 'NO'}** "
           f"(md5 {ref[:12]}…).", "",
           "p95 is the value at index int(0.95·n), so for n ≤ 20 it is the maximum (one job).", "",
           "Gate cushion: the gate starts a QPU job only if start + Slurm limit + one poll ≤ published start, "
           "so a recal that comes early by `offset` can only reach a job if offset > (limit − actual run time) "
           "+ poll. The row gives the smallest such cushion over the run's QPU/hybrid jobs.", "",
           "| Metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for label, fn in rows:
        out.append(f"| {label} | " + " | ".join(fmt(fn(n)) for n in names) + " |")

    out += ["", "**Recals in each run** (offset = published − true start, feed min; > 0 means the recal "
            "came earlier than published):", "",
            "| Run | QPU | Kind | True start | Published start | Offset | Overlap jobs | Overlap (feed min) |",
            "|---|---|---|---|---|---|---|---|"]
    for n in names:
        for r in g(S[n], "forecast", "recals_in_run") or []:
            out.append(f"| {n} | {r['qpu']} | {r['kind']} | {r['true_start'][11:19]} | {r['published_start'][11:19]} | "
                       f"{r['offset_min']:+g} | {r['overlap_jobs']} | {fmt(r['overlap_feed_min'])} |")
    (res / "forecast_err").mkdir(parents=True, exist_ok=True)
    (res / "forecast_err" / "table.md").write_text("\n".join(out) + "\n")
    print(f"wrote {res / 'forecast_err' / 'table.md'} ({len(names)} columns; manifests identical: {same}; simulated)")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())

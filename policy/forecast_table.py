#!/usr/bin/env python3
"""Forecast-error table: results/forecast_err/table.md. SIMULATED.

Section 1 (seed 1): static and reactive seed 1 (the committed sweep runs), predictive at
N = 0 from the sweep (results/predictive/seed1, exact forecast), and every
results/forecast_err/N<k>/seed1 run (feed --forecast-err-min k; N0 there is a fresh
exact-forecast control).
Section 2 (each N with more than one seed, e.g. N=120): one column per seed, next to
that seed's reactive and predictive (N = 0) sweep runs.
Every run's manifest.json must be byte-identical to static seed<N>'s. Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "feed"))
from trade_table import trade  # noqa: E402


def g(d, *path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def fmt(x) -> str:
    if x is None:
        return "–"
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def ts(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class Run:
    def __init__(self, label: str, d: Path):
        self.label, self.d = label, d
        self.s = json.loads((d / "summary.json").read_text())
        self.cfg = json.loads((d / "run_config.json").read_text())
        self.policy = self.cfg.get("policy")
        self.n = self.cfg.get("forecast_err_min", 0) if self.policy == "predictive" else None

    @property
    def predictive(self) -> bool:
        return self.policy == "predictive"

    def recals(self) -> list[dict]:
        """Every recal's true and published start: forecast.log, or the feed's own function
        for runs made before forecast.log existed (those are exact-forecast runs)."""
        if (self.d / "forecast.log").exists():
            return [json.loads(l) for l in (self.d / "forecast.log").read_text().splitlines() if l.strip()]
        import calibration_feed as f
        q = [json.loads(l) for l in (self.d / "queue.log").read_text().splitlines() if l.strip()]
        end = max(ts(x["feed_time"]) for x in q if x.get("feed_time")) + timedelta(hours=4)
        cfg = f.FeedConfig(seed=int(self.cfg["feed_seed"]), speed=float(self.cfg["feed_speed"]))
        return f.forecast_log(cfg, cfg.epoch, end)

    def to_feed(self):
        """wall -> feed time, anchored on the first queue.log poll (feed clock = epoch + speed·elapsed)."""
        q0 = json.loads((self.d / "queue.log").read_text().splitlines()[0])
        aw, af, sp = ts(q0["wall"]), ts(q0["feed_time"]), float(self.cfg["feed_speed"])
        return lambda w: af + (w - aw) * sp

    def qpu_jobs(self):
        for j in csv.DictReader((self.d / "jobs.csv").read_text().splitlines()):
            if j["type"] != "classical" and j["start"] and j["end"]:
                yield j

    def cushion(self):
        """Smallest (Slurm limit - actual run time) + one poll over QPU/hybrid jobs, feed min.
        Worst-case bound: an early recal can reach a job only if offset > this."""
        if not self.predictive:
            return None
        sp, poll = float(self.cfg["feed_speed"]), float(self.cfg.get("poll_interval_s", 10))
        man = {f"{j['type']}-{j['idx']:03d}": j for j in json.loads((self.d / "manifest.json").read_text())["jobs"]}
        c = [(man[j["name"]]["slurm_limit_s"] - (ts(j["end"]) - ts(j["start"])).total_seconds() + poll) * sp / 60
             for j in self.qpu_jobs()]
        return round(min(c), 1) if c else None

    def actual_margin(self):
        """Smallest (true start of the next recal on the job's node, at or after the job's
        start) - job end, over QPU/hybrid jobs, feed min. Negative would mean overlap."""
        if not self.predictive:
            return None
        node_qpu = {n: q for q, n in (kv.split("=") for kv in self.cfg.get("map", "qpu0=c1,qpu1=c2").split(","))}
        feed, rec = self.to_feed(), self.recals()
        best = None
        for j in self.qpu_jobs():
            st, en = feed(ts(j["start"])), feed(ts(j["end"]))
            nxt = sorted(ts(r["true_start"]) for r in rec if r["qpu"] == node_qpu[j["node"]] and ts(r["true_start"]) >= st)
            if nxt:
                m = (nxt[0] - en).total_seconds() / 60
                best = m if best is None else min(best, m)
        return round(best, 1) if best is not None else None

    def max_early(self):
        if not self.predictive:
            return None
        rec = g(self.s, "forecast", "recals_in_run")
        if rec is None:
            return 0
        return max([r["offset_min"] for r in rec if r["offset_min"] > 0], default=0)

    def split(self, k: str, field: str):
        if not self.predictive:
            return None
        f = self.s.get("forecast")
        return 0 if f is None else g(f, "overlap_by_direction", k, field)


def metric_rows(base_dirs: dict[str, Path]):
    """(label, fn(run)) rows; base_dirs maps 'reactive'/'static' to that seed's run dir."""
    def tr(b, k):
        return lambda r: trade(r.d, base_dirs[b])[k] if r.predictive else None
    return [
        ("Forecast error N (feed min)", lambda r: r.n),
        ("Largest early offset in the run (feed min)", Run.max_early),
        ("Smallest actual margin: true next-recal start on the job's node − job end (feed min)", Run.actual_margin),
        ("Worst-case bound (cushion): Slurm limit − actual run + poll (feed min)", Run.cushion),
        ("Recal-overlap jobs", lambda r: g(r.s, "recal_overlap", "count")),
        ("Recal overlap (feed min)", lambda r: g(r.s, "recal_overlap", "total_overlap_feed_min")),
        ("… from recals earlier than published: jobs / feed min",
         lambda r: None if not r.predictive else f"{fmt(r.split('earlier_than_published', 'jobs'))} / {fmt(r.split('earlier_than_published', 'feed_min'))}"),
        ("… from recals later than published: jobs / feed min",
         lambda r: None if not r.predictive else f"{fmt(r.split('later_than_published', 'jobs'))} / {fmt(r.split('later_than_published', 'feed_min'))}"),
        ("QPU-only wait p95 (feed min)", lambda r: g(r.s, "qpu_wait", "qpu", "feed_min", "p95")),
        ("Hybrid wait p95 (feed min)", lambda r: g(r.s, "qpu_wait", "hybrid", "feed_min", "p95")),
        ("Classical wait p95 (feed min)", lambda r: g(r.s, "classical_queue_wait", "feed_min", "p95")),
        ("Completion p95 (feed min)", lambda r: g(r.s, "completion_all", "feed_min", "p95")),
        ("Jobs completed / total", lambda r: f"{r.s.get('jobs_completed')}/{r.s.get('jobs_total')}"),
        ("Gate: jobs kept held at least once", lambda r: g(r.s, "gate", "jobs_kept_held") if r.predictive else None),
        ("Gate: releases / re-holds", lambda r: f"{g(r.s, 'gate', 'releases')} / {g(r.s, 'gate', 'reholds')}" if r.predictive else None),
        ("Trade vs reactive: overlap saved (feed min)", tr("reactive", "saved")),
        ("Trade vs reactive: extra QPU+hybrid wait (feed min)", tr("reactive", "extra")),
        ("Trade vs reactive: ratio extra/saved", tr("reactive", "ratio")),
        ("Trade vs static: overlap saved (feed min)", tr("static", "saved")),
        ("Trade vs static: extra QPU+hybrid wait (feed min)", tr("static", "extra")),
        ("Trade vs static: ratio extra/saved", tr("static", "ratio")),
    ]


def table(runs: list[Run], rows) -> list[str]:
    out = ["| Metric | " + " | ".join(r.label for r in runs) + " |", "|---|" + "---|" * len(runs)]
    for label, fn in rows:
        out.append(f"| {label} | " + " | ".join(fmt(fn(r)) for r in runs) + " |")
    return out


NOTES = [
    "p95 is the value at index int(0.95·n), so for n ≤ 20 it is the maximum (one job).",
    "**Margins.** The gate starts a QPU job only if start + Slurm limit + one poll ≤ *published* start. "
    "So a recal that comes early by `offset` can reach a job only if offset > (limit − actual run) + poll: "
    "the cushion row is a worst-case bound (necessary for overlap, not sufficient). The actual-margin row "
    "is how far each job's end really was from the true start of the next recal on its node (job times "
    "converted to feed time via the run's queue.log; sacct has 1 s = 0.6 feed min resolution).",
    "**Trade rows** compare QPU-recal minutes (overlap saved) with queue-wait minutes (extra QPU+hybrid "
    "wait, summed over jobs matched by name); see results/trade_table.md. The ratio isn't a cost model.",
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    a = ap.parse_args(argv)
    res = Path(a.results)
    fe = res / "forecast_err"
    by_n: dict[int, list[int]] = {}
    for p in fe.glob("N*/seed*/summary.json"):
        m1, m2 = re.fullmatch(r"N(\d+)", p.parent.parent.name), re.fullmatch(r"seed(\d+)", p.parent.name)
        if m1 and m2:
            by_n.setdefault(int(m1.group(1)), []).append(int(m2.group(1)))

    def base(seed):
        return {"reactive": res / "reactive" / f"seed{seed}", "static": res / "static" / f"seed{seed}"}

    all_runs: list[Run] = []
    # Section 1: seed 1
    s1 = [Run("static", res / "static/seed1"), Run("reactive", res / "reactive/seed1"),
          Run("predictive N=0 (sweep)", res / "predictive/seed1")]
    s1 += [Run(f"predictive N={n}" + (" (control)" if n == 0 else ""), fe / f"N{n}" / "seed1")
           for n in sorted(by_n) if 1 in by_n[n]]
    all_runs += s1
    out = ["# Forecast error (simulated)", "",
           "Predictive policy with the feed's published `next_recal.start` = true start + u·N feed min, "
           "u ~ U(−1, 1) seeded per recal (feed `--forecast-err-min N`); the recal itself happens at the true "
           "start. Workload seed s, feed seed 100+s, RUN_MIN 30, 36× (1 wall s = 0.6 feed min). Static and "
           "reactive don't read `next_recal`, so they're the committed sweep runs, unaffected by N. Drift, the "
           "recal schedule and job times are assumed. Few seeds: observations, not results.", ""]
    out += [f"- {n}" for n in NOTES] + [""]
    out += ["## Seed 1", ""] + table(s1, metric_rows(base(1))) + [""]

    # Section 2: each N run on several seeds
    for n in sorted(k for k, v in by_n.items() if len(v) > 1):
        out += [f"## N = {n}, per seed", "",
                f"Each seed's predictive N = {n} run, with that seed's reactive and predictive (N = 0) sweep runs "
                "for reference.", ""]
        for seed in sorted(by_n[n]):
            runs = [Run("reactive", res / "reactive" / f"seed{seed}"),
                    Run("predictive N=0 (sweep)", res / "predictive" / f"seed{seed}"),
                    Run(f"predictive N={n}", fe / f"N{n}" / f"seed{seed}")]
            all_runs += runs
            out += [f"### Seed {seed}", ""] + table(runs, metric_rows(base(seed))) + [""]

    # Per-recal offsets for every forecast-error run
    out += ["## Recals in each forecast-error run", "",
            "Offset = published − true start (feed min); > 0 means the recal came earlier than published.", "",
            "| Run | QPU | Kind | True start | Published start | Offset | Overlap jobs | Overlap (feed min) |",
            "|---|---|---|---|---|---|---|---|"]
    for n in sorted(by_n):
        for seed in sorted(by_n[n]):
            r = Run("", fe / f"N{n}" / f"seed{seed}")
            for x in g(r.s, "forecast", "recals_in_run") or []:
                out.append(f"| N={n} seed {seed} | {x['qpu']} | {x['kind']} | {x['true_start'][11:19]} | "
                           f"{x['published_start'][11:19]} | {x['offset_min']:+g} | {x['overlap_jobs']} | "
                           f"{fmt(x['overlap_feed_min'])} |")

    # Manifest check
    bad = []
    for r in all_runs:
        seed = int(r.cfg["seed"])
        ref = (res / "static" / f"seed{seed}" / "manifest.json").read_bytes()
        if (r.d / "manifest.json").read_bytes() != ref:
            bad.append(str(r.d))
    out += ["", f"Job manifests byte-identical to static seed<s> for every run above: "
            f"**{'yes' if not bad else 'NO: ' + ', '.join(bad)}**."]
    fe.mkdir(parents=True, exist_ok=True)
    (fe / "table.md").write_text("\n".join(out) + "\n")
    print(f"wrote {fe / 'table.md'} (N: {sorted(by_n)}; manifests identical: {not bad}; simulated)")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())

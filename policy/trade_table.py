#!/usr/bin/env python3
"""Trade table: recal overlap saved vs extra QPU/hybrid queue wait. SIMULATED.

For each seed, compares predictive with a baseline (reactive, and static):
  saved  = recal overlap (feed min) of the baseline - that of predictive
  extra  = sum over QPU and hybrid jobs, matched by job name (same manifest), of
           (predictive qpu_wait_s - baseline qpu_wait_s) * feed_speed / 60
  ratio  = extra / saved
The two sides are different quantities: minutes a job used a QPU the feed said was
recalibrating, vs minutes jobs spent waiting in the queue. The ratio is only a way to
put them side by side.

trade(pred_dir, base_dir) is also used by forecast_table.py. Stdlib only.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

NOTE = ("Compares two different quantities: QPU-recal minutes (time QPU/hybrid jobs ran on a QPU "
        "the feed said was recalibrating) and queue-wait minutes (time QPU/hybrid jobs waited "
        "before starting). The ratio only puts them side by side; it isn't a cost model.")


def _jobs(d: Path) -> dict[str, dict]:
    return {j["name"]: j for j in csv.DictReader((d / "jobs.csv").read_text().splitlines())}


def trade(pred: Path, base: Path) -> dict:
    """saved / extra / ratio (feed min) for predictive run `pred` vs baseline run `base`."""
    sp, sb = (json.loads((d / "summary.json").read_text()) for d in (pred, base))
    speed = float(json.loads((pred / "run_config.json").read_text())["feed_speed"])
    if (pred / "manifest.json").read_bytes() != (base / "manifest.json").read_bytes():
        raise SystemExit(f"manifest differs: {pred} vs {base}")
    jp, jb = _jobs(pred), _jobs(base)
    extra_s = 0.0
    for name, j in jp.items():
        if j["type"] == "classical":
            continue
        extra_s += float(j["qpu_wait_s"]) - float(jb[name]["qpu_wait_s"])
    saved = sb["recal_overlap"]["total_overlap_feed_min"] - sp["recal_overlap"]["total_overlap_feed_min"]
    extra = extra_s * speed / 60
    return {"saved": round(saved, 1), "extra": round(extra, 1),
            "ratio": round(extra / saved, 1) if saved > 0 else None}


def fmt(x) -> str:
    return "–" if x is None else f"{x:g}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--seeds", default="1 2 3 4 5")
    a = ap.parse_args(argv)
    res = Path(a.results)
    seeds = [int(s) for s in a.seeds.split()]
    rows = {(b, s): trade(res / "predictive" / f"seed{s}", res / b / f"seed{s}")
            for b in ("reactive", "static") for s in seeds}
    out = ["# Trade: recal overlap saved vs extra queue wait (simulated)", "",
           "Predictive vs a baseline, per seed (workload seed N, feed seed 100+N, same job manifest). "
           "All values in feed minutes (36×: 1 wall s = 0.6 feed min). Drift, the recal schedule and job "
           "times are assumed.", "",
           "- **Overlap saved** = baseline recal overlap − predictive recal overlap.",
           "- **Extra QPU+hybrid wait** = sum over QPU and hybrid jobs, matched by job name, of "
           "(predictive − baseline) QPU wait.",
           "- **Ratio** = extra / saved.", "", NOTE, ""]
    for b in ("reactive", "static"):
        r = [rows[b, s]["ratio"] for s in seeds if rows[b, s]["ratio"] is not None]
        out += [f"## Baseline: {b}", "",
                "| Seed | Overlap saved | Extra QPU+hybrid wait | Ratio extra/saved |", "|---|---|---|---|"]
        out += [f"| {s} | {fmt(rows[b, s]['saved'])} | {fmt(rows[b, s]['extra'])} | {fmt(rows[b, s]['ratio'])} |"
                for s in seeds]
        out += ["", f"Ratio range across seeds: {min(r):g}–{max(r):g}." if r else "", ""]
    (res / "trade_table.md").write_text("\n".join(out))
    print(f"wrote {res / 'trade_table.md'} (seeds {seeds}; simulated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

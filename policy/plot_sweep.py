#!/usr/bin/env python3
"""Chart the sweep: results/sweep_summary.csv -> results/sweep.png. SIMULATED.

Two panels, one dot per seed per policy: recal overlap (feed min) and QPU-only wait
p95 (feed min). matplotlib is dev-only (feed/requirements-dev.txt).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

POLICIES = ("static", "reactive", "predictive")
FOOTER = "simulated; drift, recal schedule and job times are assumed"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    a = ap.parse_args(argv)
    res = Path(a.results)
    rows = list(csv.DictReader(open(res / "sweep_summary.csv")))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    policies = [p for p in POLICIES if any(r["policy"] == p for r in rows)]
    panels = [("recal_overlap_feed_min", "recal overlap (feed min)"),
              ("qpu_wait_p95_feed_min", "QPU-only wait p95 (feed min)")]
    fig, axes = plt.subplots(1, len(panels), figsize=(10, 4.2))
    for ax, (col, label) in zip(axes, panels):
        for i, p in enumerate(policies):
            pts = [(int(r["seed"]), float(r[col])) for r in rows if r["policy"] == p and r[col] not in ("", None)]
            n = len(pts)
            for k, (seed, y) in enumerate(sorted(pts)):
                x = i + (k - (n - 1) / 2) * 0.08 if n > 1 else i
                ax.plot(x, y, "o", color=f"C{i}", ms=7, alpha=0.85)
                ax.annotate(str(seed), (x, y), textcoords="offset points", xytext=(5, 2), fontsize=7, color="0.4")
        ax.set_xticks(range(len(policies)), policies)
        ax.set_xlim(-0.6, len(policies) - 0.4)
        ax.set_ylabel(label)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=0.3)
    seeds = sorted({r["seed"] for r in rows}, key=int)
    fig.suptitle(f"Static vs reactive vs predictive, seeds {', '.join(seeds)} (one dot per seed; simulated)")
    fig.text(0.5, 0.01, FOOTER, ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(res / "sweep.png", dpi=120)
    print(f"wrote {res / 'sweep.png'} (simulated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

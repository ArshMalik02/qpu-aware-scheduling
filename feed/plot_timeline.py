#!/usr/bin/env python3
"""Plot a 24 h timeline of the simulated calibration feed. SIMULATED data only.

Calls qpu_state() directly (no server): seed 42, 1-minute steps from the epoch,
qpu0 and qpu1. Writes feed/results/timeline_seed42.csv and .png.

matplotlib is a dev-only dependency (feed/requirements-dev.txt); the feed itself
stays stdlib-only.

Usage: python3 feed/plot_timeline.py [--seed 42] [--hours 24] [--out-dir feed/results]
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibration_feed as feed  # noqa: E402

STATUS_COLORS = {"online": "#2e7d32", "paused": "#f9a825", "offline": "#c62828"}
CAPTION = "simulated; within-day drift rates assumed"


def collect(seed: int, hours: int) -> list[dict]:
    cfg = feed.FeedConfig(seed=seed)
    rows = []
    for m in range(hours * 60 + 1):
        t = cfg.epoch + timedelta(minutes=m)
        for q in feed.qpu_ids(cfg):
            s = feed.qpu_state(cfg, q, t)
            rows.append({
                "time": s["updated_at"], "minute": m, "qpu": q, "status": s["status"],
                "healthy": s["healthy"], "available": s["available"],
                "readout_err": s["metrics"]["readout_err"],
                "gate_err_1q": s["metrics"]["gate_err_1q"], "t1_us": s["metrics"]["t1_us"],
                "drift_score": s["drift_score"],
            })
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def plot(rows: list[dict], path: Path, seed: int, hours: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    qpus = sorted({r["qpu"] for r in rows})
    fig, axes = plt.subplots(3, 1, figsize=(11, 7), sharex=True,
                             gridspec_kw={"height_ratios": [1, 2, 2]})
    ax_status, ax_ro, ax_drift = axes

    for i, q in enumerate(qpus):
        rs = [r for r in rows if r["qpu"] == q]
        x = [r["minute"] / 60 for r in rs]
        # Status bands: one horizontal bar per QPU, coloured per minute segment.
        start = 0
        for j in range(1, len(rs) + 1):
            if j == len(rs) or rs[j]["status"] != rs[start]["status"]:
                ax_status.broken_barh([(x[start], x[j - 1] - x[start] + 1 / 60)], (i - 0.4, 0.8),
                                      color=STATUS_COLORS[rs[start]["status"]])
                start = j
        ax_ro.plot(x, [r["readout_err"] * 100 for r in rs], lw=1, label=q)
        ax_drift.plot(x, [r["drift_score"] for r in rs], lw=1, label=q)

    ax_status.set_yticks(range(len(qpus)), qpus)
    ax_status.set_ylim(-0.6, len(qpus) - 0.4)
    ax_status.set_title("status", loc="left")
    ax_status.legend(handles=[Patch(color=c, label=s) for s, c in STATUS_COLORS.items()],
                     loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=3, fontsize=8, frameon=False)
    ax_ro.set_ylabel("readout error (%)")
    ax_ro.legend(loc="upper left", fontsize=8)
    ax_drift.set_ylabel("drift_score (assumed)")
    ax_drift.set_xlabel("hours since feed epoch (2026-11-01T00:00Z)")
    ax_drift.legend(loc="upper left", fontsize=8)
    ax_drift.set_xlim(0, hours)

    fig.suptitle(f"Simulated QPU calibration feed, seed {seed}, {hours} h ({CAPTION})")
    fig.text(0.5, 0.005, f"SIMULATED data from feed/calibration_feed.py; {CAPTION}. "
             "Recal durations from Mansfield et al.; day-to-day drift from Deng et al.",
             ha="center", fontsize=7)
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    fig.savefig(path, dpi=120)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--out-dir", default=str(Path(__file__).resolve().parent / "results"))
    a = p.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = collect(a.seed, a.hours)
    stem = f"timeline_seed{a.seed}"
    write_csv(rows, out / f"{stem}.csv")
    plot(rows, out / f"{stem}.png", a.seed, a.hours)
    shown = os.path.relpath(out / stem)  # relative, so no host path is printed
    print(f"wrote {shown}.csv and .png ({len(rows)} rows, simulated)")


if __name__ == "__main__":
    main()

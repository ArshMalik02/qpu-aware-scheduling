#!/usr/bin/env python3
"""Seeded mixed workload for the simulated cluster. SIMULATED jobs only.

Poisson arrivals of three job types:
  qpu       QPU-only: Aer Bell circuit (jobs/aer_bell.py), --gres=qpu:1 -c1
  hybrid    toy VQE loop (jobs/vqe_toy.py) holding 2 CPUs and the QPU, --gres=qpu:1 -c2
  classical CPU-only filler, -c1, no GRES
Each job then holds its resources for a seeded "hold" time (sleep), standing in for
device/compute time. Hold times and the mix are ASSUMED parameters, not measured.

Time limits: each job gets limit_s = ceil(hold_s * 1.5) + 30, passed as --time=MM:SS.
Slurm rounds a time limit up to whole minutes (--time=01:45 becomes 00:02:00 on
26.05.2), so the manifest also records slurm_limit_s, the limit Slurm enforces.
hold_s < limit_s <= slurm_limit_s always holds (tested).

--hold-qpu submits QPU and hybrid jobs held (sbatch --hold), for the predictive policy,
which releases each job only once it fits before the next recal. A held submit is
accepted even while every QPU is out, where a plain one is rejected (see submit()).

  gen.py --seed N --manifest m.json            write the manifest only
  gen.py --seed N --manifest m.json --submit   write it, then sbatch each job at its arrival time

The same seed (and parameters) gives a byte-identical manifest. Runs inside slurmctld
for --submit. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import time
from pathlib import Path

MIX = {"qpu": 0.4, "hybrid": 0.2, "classical": 0.4}           # assumed
MEAN_HOLD_S = {"qpu": 45.0, "hybrid": 90.0, "classical": 60.0}  # assumed, wall seconds
CPUS = {"qpu": 1, "hybrid": 2, "classical": 1}
MAX_HOLD_S = 240.0


def limit_for(hold_s: float) -> tuple[int, int]:
    """(limit_s, slurm_limit_s): the requested limit and Slurm's whole-minute round-up."""
    limit_s = math.ceil(hold_s * 1.5) + 30
    return limit_s, math.ceil(limit_s / 60) * 60


def time_arg(limit_s: int) -> str:
    return f"--time={limit_s // 60:02d}:{limit_s % 60:02d}"


def make_manifest(seed: int, duration_min: float, rate_per_min: float) -> dict:
    r = random.Random(seed)
    jobs, t, horizon = [], 0.0, duration_min * 60
    while True:
        t += r.expovariate(rate_per_min / 60.0)
        if t >= horizon:
            break
        kind = r.choices(list(MIX), weights=list(MIX.values()))[0]
        hold = min(MAX_HOLD_S, r.expovariate(1.0 / MEAN_HOLD_S[kind]))
        hold = round(hold, 1)
        limit_s, slurm_limit_s = limit_for(hold)
        jobs.append({"idx": len(jobs), "type": kind, "arrival_s": round(t, 2),
                     "hold_s": hold, "limit_s": limit_s, "slurm_limit_s": slurm_limit_s,
                     "cpus": CPUS[kind], "qpu": kind != "classical"})
    return {"seed": seed, "duration_min": duration_min, "rate_per_min": rate_per_min,
            "mix": MIX, "mean_hold_s": MEAN_HOLD_S, "max_hold_s": MAX_HOLD_S,
            "limit_rule": "limit_s = ceil(hold_s * 1.5) + 30; Slurm rounds up to whole minutes",
            "assumed": True, "simulated": True, "jobs": jobs}


def sbatch_args(job: dict, out_dir: str, hold_qpu: bool = False) -> list[str]:
    name = f"{job['type']}-{job['idx']:03d}"
    args = ["sbatch", "--parsable", "-J", name, f"-c{job['cpus']}", "--mem=500M",
            time_arg(job["limit_s"]), "-o", f"{out_dir}/{name}_%j.out",
            f"--export=ALL,JOBS_OUT_DIR={out_dir}"]
    if job["qpu"]:
        args.append("--gres=qpu:1")
        if hold_qpu:
            args.append("--hold")
    body = {"qpu": "python3 /data/jobs/aer_bell.py >/dev/null",
            "hybrid": "python3 /data/jobs/vqe_toy.py >/dev/null",
            "classical": "true"}[job["type"]]
    args += ["--wrap", f"{body} && sleep {job['hold_s']}"]
    return args


NO_QPU_CONFIGURED = "Requested node configuration is not available"
RETRY_S = 5.0


def submit(manifest: dict, out_dir: str, log_path: Path, hold_qpu: bool = False) -> None:
    """sbatch each job at its arrival time.

    On 26.05.2, while every node's QPU is out (Gres=qpu:0 everywhere), sbatch rejects a
    --gres=qpu job outright with NO_QPU_CONFIGURED instead of queueing it (HRES would
    queue it with reason HRESDisabled). Those jobs are deferred and retried every RETRY_S
    seconds, without delaying other jobs; the delay is logged as submit_delay_s.
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    pending = list(manifest["jobs"])   # not yet due or not yet accepted, in arrival order
    attempts: dict[int, int] = {}
    with open(log_path, "a", buffering=1) as log:
        while pending:
            now = time.monotonic() - t0
            due = [j for j in pending if j["arrival_s"] <= now]
            for job in due:
                res = subprocess.run(sbatch_args(job, out_dir, hold_qpu), capture_output=True, text=True)
                attempts[job["idx"]] = attempts.get(job["idx"], 0) + 1
                if res.returncode == 0:
                    jid = res.stdout.strip()
                    after = round(time.monotonic() - t0, 2)
                    rec = {"idx": job["idx"], "type": job["type"], "job_id": jid,
                           "arrival_s": job["arrival_s"], "submitted_after_s": after,
                           "submit_delay_s": round(after - job["arrival_s"], 2),
                           "rejected_attempts": attempts[job["idx"]] - 1}
                    log.write(json.dumps(rec) + "\n")
                    extra = f" (after {rec['rejected_attempts']} rejections)" if rec["rejected_attempts"] else ""
                    print(f"submitted {job['type']:9s} idx={job['idx']:3d} job={jid}{extra}", flush=True)
                    pending.remove(job)
                elif NO_QPU_CONFIGURED in res.stderr and job["qpu"]:
                    if attempts[job["idx"]] == 1:
                        print(f"deferred  {job['type']:9s} idx={job['idx']:3d}: no node has a QPU "
                              f"configured right now (all out); retrying every {RETRY_S:.0f} s", flush=True)
                else:
                    raise RuntimeError(f"sbatch failed for idx {job['idx']}: {res.stderr.strip()}")
            if not pending:
                break
            waiting = [j for j in pending if j["arrival_s"] <= time.monotonic() - t0]
            next_arrival = min(j["arrival_s"] for j in pending) - (time.monotonic() - t0)
            time.sleep(RETRY_S if waiting else max(0.0, min(next_arrival, RETRY_S)))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Seeded mixed workload (simulated).")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--duration-min", type=float, default=20.0, help="arrival window (minutes)")
    p.add_argument("--rate-per-min", type=float, default=1.5, help="mean arrivals per minute")
    p.add_argument("--manifest", required=True, help="path to write the manifest JSON")
    p.add_argument("--submit", action="store_true", help="sbatch each job at its arrival time")
    p.add_argument("--out-dir", default="/data/results/reactive/jobs")
    p.add_argument("--submit-log", default="/data/results/reactive/submitted.log")
    p.add_argument("--hold-qpu", action="store_true",
                   help="submit QPU/hybrid jobs held (predictive policy releases them)")
    a = p.parse_args(argv)
    m = make_manifest(a.seed, a.duration_min, a.rate_per_min)
    Path(a.manifest).parent.mkdir(parents=True, exist_ok=True)
    Path(a.manifest).write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    counts = {k: sum(j["type"] == k for j in m["jobs"]) for k in MIX}
    print(f"manifest: {len(m['jobs'])} jobs {counts} (seed {a.seed}, simulated)", flush=True)
    if a.submit:
        submit(m, a.out_dir, Path(a.submit_log), a.hold_qpu)


if __name__ == "__main__":
    sys.exit(main())

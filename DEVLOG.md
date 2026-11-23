## 2026-11-22: Predictive (recal-timing) policy + 3-policy sweep runner

Everything here is **simulated**: the QPUs are Slurm GRES counters, the jobs run on Aer (CPU), and recal windows come from the simulated feed. The claim being tested is narrow: what does seeing a recal *before* it starts buy you? Slurm 26.11 HRES and the reactive loop from 2026-11-18 only act once a recal has started.

**Per-job time limits.** Every job used to get `--time=00:10:00`, far longer than any hold (max 240 s), and a rule based on time limits would have blocked almost everything. `gen.py` now sets `limit_s = ceil(hold_s × 1.5) + 30` as `--time=MM:SS`. **Slurm rounds limits up to whole minutes:** `--time=01:45` became `TimeLimit=00:02:00` on 26.05.2. So the manifest also records `slurm_limit_s`, and the predictive rule uses the limit Slurm enforces (read from `squeue %l`), not the requested one. A test checks that `hold_s < limit_s ≤ slurm_limit_s`. The same manifest is used for all three policies.

**The rule** (`policy/predictive.py`, pure function `fits()`): a QPU job may start on a QPU only if that QPU is online (with `healthy` not false) and, in feed time, `now + limit + one poll interval ≤ next_recal.start`. Wall time is converted to feed time with `feed_speed` from `run_config.json`, so at 36× a 2-minute limit is 72 feed minutes and the 10 s poll adds 6. Unit tests cover: fits, doesn't fit, the exact boundary, a recal already running, two QPUs with one fitting, and none or both fitting.

**Mechanism on 26.05.2** (no HRES):
- QPU jobs are submitted held (`gen.py --hold-qpu`).
- About every second, the gate computes which QPUs fit each pending QPU job. If some fit, it sets `scontrol update ExcNodeList=<nodes that don't fit>` and releases the job. If none fit, the job stays held. A released job that stops fitting is held again with `scontrol uhold`, and a changed fitting set updates `ExcNodeList`. This per-job table (held/released × fits/none/changed) is the pure function `decide()`, with unit tests.
- **Hold reasons:** the gate runs as root, and as root `scontrol hold` is an *admin* hold. Checked live on 26.05.2: `scontrol hold` → `JobHeldAdmin`, `scontrol uhold` → `JobHeldUser`, `sbatch --hold` → `JobHeldUser`. The first version re-held with `scontrol hold` but only treated `JobHeldUser` as held. So a re-held job would have looked "released" forever and never been released (from reading the code; it never happened, because no re-hold fired in the smoke run). Now re-holds use `uhold`, and both reasons count as held.
- **`fits()` edge cases (unit tests):** a `next_recal.start` already in the past doesn't fit; `status: online` with `healthy: false` doesn't fit, matching `reactive.py`'s rule; a QPU with no state yet doesn't fit.
- The feed is still polled every 10 s. Between polls, feed time is extrapolated from the last poll at `feed_speed`, so held jobs aren't kept waiting for the next poll.
- Every hold, release and exclude is logged to `transitions.log` with the job, its limit, and the time to each QPU's next recal (feed min).
- Checked live against a stub feed. A job that fit only on c1 got `ExcNodeList=c2` and ran on c1. With both QPUs near a recal, a job stayed held until qpu1's recal moved out, then ran on c2.
- **Re-hold, live** (`policy/repro_rehold.sh`, stub feed, 2026-11-23):
  - Blockers held both QPUs, and job 355 (2-min limit = 72 feed min) was released and pended on `Resources`.
  - The stub then moved both recals to 30 feed min out. The gate logged `gate_rehold`, and the job went to `JobHeldUser` within ~1 s.
  - With qpu1's recal moved back to 600 min, it was released with `ExcNodeList=c1` and COMPLETED on c2.
  - Gate events for the job: `gate_release gate_rehold gate_release`. PASS.

**How this differs from an HRES prerun gate:** HRES evaluates a job in `hres_controller_job_prerun`, just before it would start, with `job.end_time = start + time limit`, and can say "not now" for that one scheduling attempt. Here the decision is made from outside the scheduler, ahead of time: there's up to ~1 s of gate lag, and a decision can be stale by the time Slurm picks the job. The comparison itself is the same, so it maps onto an HRES prerun gate later.

**A held submit is accepted while every QPU is out.** `sbatch --hold --gres=qpu:1` succeeded with `qpu:0` on both nodes, where the same submit without `--hold` is rejected ("Requested node configuration is not available", 2026-11-18). Released after the QPUs returned, the job ran normally. So predictive never sees submit rejections, while static and reactive can. The `submit_rejections` column isn't comparable across policies, and a rejected job's delay is still counted as QPU wait.

**Policies in the sweep:** static = `reactive.py --observe-only` (logs the recal windows, never touches nodes, so its overlap is measured the same way); reactive = `reactive.py`; predictive = `predictive.py`. `make sweep SEEDS="…"` runs every policy for each seed with workload seed N and feed seed 100+N, so recal timing varies between seeds but not between policies. Output goes to `results/<policy>/seed<N>/`; `policy/aggregate.py` writes `results/sweep_summary.csv` and `sweep_table.md`, and `policy/plot_sweep.py` writes `results/sweep.png`. PR #4's seed-1 results used the old 10-minute limits and are archived under `results/archive/pr4-week4-reactive/`, not compared.

**Smoke run (seed 1, feed seed 101, RUN_MIN=30, 36×; simulated, x86_64 Docker cluster).** All three runs PASS their checks. The manifest is byte-identical across policies (55 jobs: 19 QPU, 13 hybrid, 23 classical), and all 55 complete in each run. Waits and overlaps are in feed minutes (1 wall s = 0.6 feed min); `results/sweep_table.md` has the full table.

| Metric | static | reactive | predictive |
|---|---|---|---|
| Recal-overlap jobs | 6 | 2 | 0 |
| Recal overlap (feed min) | 116.4 | 69 | 0 |
| QPU-only wait median / p95 | 0 / 16.2 | 0 / 81 | 2.4 / 121.8 |
| Hybrid wait p95 | 1.2 | 6 | 156 |
| Classical wait p95 | 1.2 | 1.2 | 13.2 |
| Completion median / p95 | 22.2 / 79.2 | 22.2 / 111.6 | 32.4 / 172.8 |
| Submit rejections | 0 | 0 | 0 |
| Gate: jobs kept held at least once / releases / re-holds | – | – | 7 / 32 / 0 |

**Recal overlap is the intersection of each QPU/hybrid job's [start, end) with every [QPU_OUT, QPU_IN) window on its node** (QPU_IN missing → run end). The first version counted only jobs already running at the QPU_OUT instant, which misses jobs that *start* during a recal. That happens mainly under static, which never takes a QPU out. Under reactive it can happen only within the ≤10 s poll lag, and it didn't in this run. Re-summarized from the committed seed-1 run directories (no re-run):
- static: 6 jobs, 194 wall s = 116.4 feed min. `qpu-033` and `hybrid-012` were running at QPU_OUT; `qpu-014`, `hybrid-018`, `hybrid-020` and `qpu-037` started inside a window.
- reactive: 2 jobs / 69 feed min.
- predictive: 0.

"Gate: jobs kept held at least once" counts jobs the gate found no fitting QPU for at least once. Every QPU job is submitted held under predictive, so "held" alone means nothing.

What one seed shows:
- Static: 6 jobs overlapped a recal (116.4 feed min).
- Reactive: 2 (69 feed min). It stopped the four jobs that static let start inside a recal, but `qpu-033` (42 feed min) and `hybrid-012` (27 feed min) were already running when their recal began, and reactive only blocks new starts.
- Predictive: 0. It didn't start those two, because they wouldn't have finished before the recal.
- It pays for this in wait: QPU-only p95 went from 81 to 121.8 feed min and hybrid p95 from 6 to 156, because a job is held until it fits before the next recal.
- **p95 here is one job.** `stats()` takes the value at index int(0.95·n), so for n ≤ 20 the p95 *is* the max: QPU-only n = 19, hybrid n = 13. Reactive's 81 is `qpu-014` alone (next: 16.2). Classical (n = 23) p95 is the second-largest wait.
- **Classical p95 rose to 13.2 feed min (22 wall s) under predictive.** `queue.log` shows the slow classical jobs (`classical-019`, `-024`, `-036`, `-039`: 11–24 wall s) PENDING with reason `Priority`, behind released QPU/hybrid jobs pending on `Resources`.
  - `sacct -o Flags` shows all four were started by the backfill scheduler (`SchedBackfill`), not the main one. Under predictive, 7 of 23 classical jobs were started by backfill, against 1 under static and 0 under reactive.
  - So the delay is backfill timing: the main scheduler won't start a lower-priority job behind a blocked one in the same partition, and backfill runs every `bf_interval`. That's 30 s by default, and this cluster sets no `SchedulerParameters`.
  - The flags are verified. That the default is 30 s and that the main scheduler stops at the blocked job come from Slurm's documented behaviour; I didn't check them against slurmctld's logs.
- Makespan is identical (1816 wall s) in all three, because the last job to finish is a late classical arrival.
- The re-hold path (`gate_rehold`) wasn't triggered in this run; it was exercised separately against a stub feed (above).
- This is one seed, so these are observations, not a result.

**Full sweep estimate:** `make sweep SEEDS="1 2 3 4 5"` is 15 runs at about 36 min each (30 min of arrivals, drain, setup), so about 540 min (9 h). The worst case, if every queue uses its full 15-min drain, is 15 × 47 = 705 min. The seed-1 smoke run took 92 min for three runs (23:20–00:52 UTC), about 31 min per run.

**Unattended sweep:**
- **Resume:** `run_sweep.sh` skips any policy/seed whose `summary.json` has every check passing (`FORCE=1` re-runs it), and retries a failed run once. So after an interruption, re-running the same command resumes. With seed 1 already committed, the 5-seed sweep runs the other 12 (about 432 min, 7.2 h).
- **Cleanup on failure:** `run_baseline.sh` cancels a leftover queue and waits for it to empty instead of failing, and waits again after the drain-timeout `scancel`. On any early exit, including a signal, an EXIT trap stops `gen.py`, cancels the run's jobs, waits for an empty queue and stops the loop, which restores both QPUs.
- **Tested:** SIGTERM mid-submit exits in ~1 s with an empty queue and both QPUs at `qpu:1`. A leftover job before a run is cancelled by the preflight.

## 2026-11-18: Reactive up/down loop (HRES-like) on 26.05.2

Everything here is **simulated**: the QPUs are Slurm GRES counters, the jobs run on Aer (CPU), and QPU state comes from the simulated feed.

**Step 3: can a node's QPU be taken out without draining the node?** Tested on the `cluster/` setup (Slurm 26.05.2, dynamic nodes registered with `--conf "Gres=qpu:1"`, no `gres.conf`). **Yes: `scontrol update NodeName=c1 Gres=qpu:0` works, and so does restoring with `Gres=qpu:1`.**

| Check | Result |
|---|---|
| `scontrol update NodeName=c1 Gres=qpu:0` | rc 0; `sinfo` shows `c1 qpu:0`, node state unchanged (`IDLE+DYNAMIC_NORM`) |
| QPU job submitted while c1 = `qpu:0` and c2's QPU busy | PENDING, reason `Resources` |
| CPU-only job on c1 at the same time | RUNNING: removing the QPU doesn't block CPU work |
| `scontrol update NodeName=c1 Gres=qpu:1` | rc 0; the pending QPU job started on c1 within one scheduling pass |
| `qpu:0` while a QPU job is *running* on c1 | Accepted. The running job isn't touched and completed normally (`COMPLETED 0:0`); c1 stays `qpu:0` |
| slurmd restart on c1 while at `qpu:0` | c1 **stays** `qpu:0`: the controller keeps its stored value over the node's `--conf` (same behavior as the 2026-10-26 stale-record bug) |

So the DRAIN/RESUME fallback isn't needed, and CPU-only jobs keep running while a QPU is out, which is what HRES does too. Two differences from HRES: the pending reason is `Resources`, not `HRESDisabled`; and because the controller keeps `qpu:0` across slurmd restarts, the loop is the only thing that restores a QPU, so it has to restore every node when it exits.

**The loop and the workload.** `make baseline-reactive SEED=1` does the following:
- starts the feed as a sidecar (`docker compose --profile reactive`, seed 42, 36× speed, so ~30 min of wall time ≈ 18 h of feed time);
- runs `policy/reactive.py` in slurmctld: it polls every 10 s and sets `Gres=qpu:0/1` per node, with qpu0→c1 and qpu1→c2;
- submits `workload/gen.py --seed 1`: 35 jobs over 20 min, 12 QPU-only Bell, 8 hybrid toy-VQE (`-c2`) and 15 classical, each holding its resources for a seeded, *assumed* time;
- drains the queue, restores the QPUs, and writes everything to `results/reactive/seed<N>/`. That run's results are in `results/archive/pr4-week4-reactive/seed1-x86_64/`.

**What broke:**
1. *All QPUs out → sbatch rejects QPU jobs.* The first full run died when `sbatch --gres=qpu:1` failed with `Requested node configuration is not available`. That happens while the two daily full recals overlap (feed ≈ 03:55–04:13), because with `qpu:0` on every node, no node is configured for the job at all. HRES would accept the job and hold it with `HRESDisabled`. Fix: `gen.py` retries those jobs every 5 s without delaying other arrivals, logs `submit_delay_s`, and `summarize.py` counts that delay as QPU wait. In the passing run, `hybrid-012` was rejected once and accepted 5 s later.

**Results** (seed 1, x86_64, simulated; times UTC). Feed speed 36× (from `run_config.json`), so 1 wall second = 0.6 feed minutes. Every wait is given as wall s / feed min. The workload manifest is byte-identical to the first run's.

| | Value |
|---|---|
| Jobs | 35, all COMPLETED |
| Loop transitions | 5 × QPU_OUT, 5 × QPU_IN, matching the feed's recal windows as seen by the loop, up to one poll late (qpu0 quick 00:00–00:24, full 02:31–04:13, quick 10:14–10:56; qpu1 full 03:55–05:37, quick 11:38–12:20, feed time) |
| Polls with a QPU out | 49 of 127 |
| **Recal overlap** (QPU/hybrid jobs RUNNING on a node when its QPU went out) | **1 job**: `hybrid-032` on c2, **55 s / 33.0 feed min** |
| QPU wait, QPU-only jobs | mean 21.2 s / 12.7 min, median 0 / 0, p95 = max 86 s / 51.6 min |
| QPU wait, hybrid jobs | mean 1.3 s / 0.8 min, max 5 s / 3.0 min (the one submit rejection) |
| Classical queue wait | mean 1.7 s / 1.0 min, max 11 s / 6.6 min |
| Submit rejections (all QPUs out) | 1 (`hybrid-012`, 5 s / 3.0 min) |
| BadConstraints rechecks | 0 in this run (see below) |
| Checks | all jobs COMPLETED ✔; QPU taken out and restored ✔; QPU job PENDING (`Resources`) while a QPU was out ✔ (21 polls); classical job RUNNING on a node whose QPU was out ✔ (3 polls) → **PASS** |

Recal overlap is the number a predictive policy should bring down: a reactive loop only acts after a recal has started, so a job already holding the QPU keeps it. `summarize.py` measures it from `jobs.csv` and `transitions.log` alone. A non-reactive policy can produce the same `transitions.log` with `reactive.py --observe-only`, so all three policies are measured the same way.

Excerpt: c1's QPU went out at feed 02:30 for the full recal, and `qpu-006` then pended while c2's QPU was busy:

```
[22:44:43Z] feed=2026-11-01T02:30:50Z c1/qpu0 QPU_OUT qpu:1->0 (paused: full recalibration in progress (simulated))
queue.log 22:45:03Z feed 02:42:52  qpus {c1: 0, c2: 1}
  144|qpu-006|PENDING|Resources|gres/qpu:1|
  143|qpu-005|RUNNING|None|gres/qpu:1|c2
jobs.csv: qpu-006 submit 22:44:55, start 22:45:34 on c2 → QPU wait 39 s / 23.4 feed min
```

**aarch64 (M1) run.** `make baseline-reactive SEED=1` also passed on the M1 Mac (Docker Desktop), in `results/archive/pr4-week4-reactive/seed1-aarch64/`. Same config (feed seed 42, 36×, 20 min at 1.5/min), and the manifest is byte-identical to the x86_64 run. Before it, the M1 cluster needed `scontrol delete nodename=c1,c2` plus a worker restart: both nodes were DOWN and c1's stored record showed GRES `(null)`, another stale controller record.

| Simulated, wall s / feed min | aarch64 (M1) | x86_64 (Linux) |
|---|---|---|
| Jobs | 35, all COMPLETED | 35, all COMPLETED |
| Loop transitions | 5 × QPU_OUT, 5 × QPU_IN | 5 × QPU_OUT, 5 × QPU_IN |
| Polls with a QPU out | 46 of 125 | 49 of 127 |
| **Recal overlap** | **1 job, `hybrid-032` on c2: 49 s / 29.4 min** | **1 job, `hybrid-032` on c2: 55 s / 33.0 min** |
| QPU wait, QPU-only (mean; p95 = max) | 21.2 s / 12.7 min; 82 s / 49.2 min | 21.2 s / 12.7 min; 86 s / 51.6 min |
| QPU wait, hybrid (max) | 2 s / 1.2 min | 5 s / 3.0 min |
| Classical queue wait (mean; max) | 2.8 s / 1.7 min; 22 s / 13.2 min | 1.7 s / 1.0 min; 11 s / 6.6 min |
| Rejected at submit (all QPUs out) | 0 | 1 (`hybrid-012`, 5 s) |
| BadConstraints rechecks | 0 | 0 |
| Checks | PASS | PASS |

The same job overlaps a recal on both architectures, for a similar length, so the overlap metric gives the same answer across machines. The submit rejection only happened on x86_64: `hybrid-012` arrives within a few seconds of the brief window when both QPUs are out, so whether it hits that window depends on run timing.

**Two more things broke while rerunning:**
2. *Nodes DOWN after a Docker restart.* After the Docker daemon restarted, slurmctld marked c1 and c2 `DOWN` ("Node unexpectedly rebooted"). One run had every job stuck in `ReqNodeNotAvail` until the drain timeout cancelled all 35. The old checks didn't catch it: jobs pending behind down nodes were counted as "pending while QPU out". Fixes:
   - the run script now resumes down nodes and stops before submitting if they stay down;
   - new check 0 requires every job to have COMPLETED;
   - check 2 now counts only reason `Resources`.
3. *QPU jobs stuck in `BadConstraints`.* In another run, `qpu-011` was pending (`Resources`) when the second QPU also went out (both out ≈ feed 03:58–04:10). Slurm re-evaluated it against a cluster with no `qpu` configured, set it to `BadConstraints`, and never re-checked it after the QPUs returned. I reproduced this on its own; `scontrol hold` + `release` makes the job re-validate and run. The loop now does that on every poll where a QPU is in, and logs a `recheck` event. It wasn't triggered in the committed run, because no QPU job happened to be pending at the moment both QPUs went out.

**BadConstraints repro (`policy/repro_badconstraints.sh`).** The recheck path wasn't triggered in the committed seed-1 run, so a script triggers it on purpose. It runs the real `reactive.py` (2 s polling) against a stub feed whose per-QPU status the script sets:
1. qpu0 paused, so c1 goes to `qpu:0`.
2. A blocker job holds c2's QPU, and the victim QPU job pends.
3. qpu1 is paused too, so every QPU is out.
4. Both come back online.

PASS on x86_64 (output below) and on the M1 (aarch64) (simulated):

```
[02:52:23Z] step 1: qpu0 paused -> loop takes c1's QPU out
[02:52:29Z]     victim 175: PENDING Resources
[02:52:29Z] step 3: qpu1 paused too -> every QPU out      (c1 qpu:0, c2 qpu:0)
[02:52:33Z]     victim 175: PENDING BadConstraints
[02:52:33Z] step 4: both online -> loop restores both QPUs and rechecks stuck jobs
[2026-11-19T02:52:33Z] feed=stub job 175: BadConstraints after all QPUs were out; hold+release to re-validate
[02:52:37Z]     victim 175: COMPLETED
[02:52:38Z] PASS: victim went Resources -> BadConstraints, was rechecked by the loop, and COMPLETED (simulated)
```

The repro also passed on the M1 (aarch64), as reported by the person who ran it (that output isn't committed). Without the recheck the job stays `BadConstraints` after the QPUs return (reproduced by hand earlier the same day: still stuck 35 s after both QPUs and the blocker were cleared).

**Not like HRES:** the pending reason is `Resources`, not `HRESDisabled`; when every QPU is out, new jobs are rejected at submit and already-pending ones go to `BadConstraints` (both above) instead of being held; there's no admission check on slots, `busy` or status age; there's up to one poll (10 s ≈ 6 min of feed time) of lag each way; and nothing restores a QPU except the loop.

**Takeaway:** taking the QPU out by GRES count gives the HRES effect on 26.05.2 (QPU jobs wait, CPU work continues) for 49 of 127 polls in this run. The wait lands on QPU-only jobs (p95 86 s / 51.6 feed min, simulated). One hybrid job (`hybrid-032`) was already running when its node's QPU went out and kept it for another 55 s / 33.0 feed min: that's the recal overlap a reactive loop can't avoid and a predictive policy should reduce. The case HRES handles better is when every QPU is out at once (submit rejections, `BadConstraints`).

**Next:** policy 1 (static) and policy 3 (simple predictive) on the same seeded workload, then the comparison table (3 seeds).

## 2026-11-03: Aer job through --gres=qpu:1 + toy VQE timing

**Setup:** the Docker cluster from `cluster/` (Slurm 26.05.2, nodes c1 and c2, each with `qpu:1`), run on **x86_64** Linux. Qiskit 2.6.1, qiskit-aer 0.18.2, numpy 2.5.4 and scipy 1.18.1 are baked into the image from wheels: `cluster/requirements-jobs.txt`, plus `cluster/constraints-jobs.txt` (the `pip freeze`) passed with `-c` so transitive dependencies are pinned too. Two batch jobs (`jobs/`), each with `--gres=qpu:1 -c1 --mem=500M`, were submitted together by `jobs/verify_aer.sh`. Everything is **simulated**: Aer on CPU, and the `qpu` GRES is a counter.

**What broke:**
1. *Docker Hub rate limit.* The first from-scratch rebuild got `429 Too Many Requests` resolving `golang:1.26-bookworm` and was still failing after about 7.5 min of backoff, so I first tested the pip layer on top of the existing image. A later retry went through: the full `docker compose build` from scratch with the final layer (`-r` + `-c`) passes, `pip freeze` on c1 matches `constraints-jobs.txt` exactly, and `verify_qpu.sh` still passes.
2. *verify_aer.sh false PASS.* The output checks were a Python heredoc piped into `docker exec` without `-i`, so Python read empty stdin, exited 0, and checked nothing. Fixed: the checks now live in `jobs/check_outputs.py`, and the script fails unless the checker prints a sentinel. Negative test: corrupted Bell counts (3500/596) give `BAD` and exit 1.
3. *GRES allocation not visible after the fact.* Once a job completes, `scontrol show job -d` shows `GRES=` empty, and sacct `AllocTRES` has no `gres/qpu` because it isn't in `AccountingStorageTRES`. Fix: each job runs `scontrol show job -d` on itself while RUNNING (saved as `*.alloc.txt`), and `verify_aer.sh` requires `GRES=qpu` there. On timeout, `verify_aer.sh` now cancels both jobs and copies nothing; I tested this with `VERIFY_TIMEOUT_S=1` (both CANCELLED, exit 1, results unchanged).

**Results** (jobs 6 and 7 of a fresh cluster; outputs in `jobs/results/x86_64/`):

Bell, 4096 shots, `seed_simulator=1234`, on c1: `{"00": 2074, "11": 2022}`. Allocation captured in each job: `Nodes=c1 CPU_IDs=0 Mem=500 GRES=qpu(CNT:1)`.

| Toy VQE (COBYLA, maxiter 30), on c1 | |
|---|---|
| Iterations | 30 |
| Σ quantum_s (Aer estimator calls) | 0.1283 s |
| Σ classical_s (optimizer + overhead + binding) | 0.0547 s |
| Quantum fraction | 0.701 |
| setup_s (imports, build, transpile) | 0.963 s |
| Total wall (script) | 1.146 s |

| sacct (times UTC) | Submit | Start | Queue wait | Elapsed | Node |
|---|---|---|---|---|---|
| aer_bell (6) | 19:32:31 | 19:32:31 | 0 s | 00:00:01 | c1 |
| vqe_toy (7) | 19:32:32 | 19:32:34 | 2 s | 00:00:01 | c1 |

There were two free qpu GRES slots, yet vqe_toy sat PENDING (`None`) for about 2 s until the next scheduling pass and then ran on c1 after aer_bell had finished. In an earlier run both started in the same second, on different nodes. sacct has 1 s resolution. Across three x86_64 runs the quantum fraction was 0.64–0.70 and setup 0.96–2.0 s, so treat these as rough. Here setup is about 5× the whole optimization loop. These numbers reflect this Docker setup on x86_64, not hardware.

**aarch64 (M1) run.** The same commands passed on the M1 Mac (Docker Desktop, `uname -m` = `aarch64`): `cd cluster && docker compose up -d --build && ./verify_qpu.sh && cd .. && jobs/verify_aer.sh`. `verify_qpu.sh` gave 2 RUNNING, 1 PENDING (Resources), and `verify_aer.sh` passed with `GRES=qpu(CNT:1)` captured on c1 and c2. Run 2 (jobs 6 and 7), after `docker cp --quiet` was added, passed the same way. Outputs for both runs are in `jobs/results/aarch64/`.

| Simulated, Docker cluster | aarch64 run 1 (jobs 4, 5) | aarch64 run 2 (jobs 6, 7) | x86_64 (Linux) |
|---|---|---|---|
| Bell counts (4096 shots, seed 1234) | `{"00": 2074, "11": 2022}` | `{"00": 2074, "11": 2022}` | `{"00": 2074, "11": 2022}` |
| VQE iterations | 30 | 30 | 30 |
| Σ quantum_s | 0.1371 s | 0.0989 s | 0.1283 s |
| Σ classical_s | 0.0826 s | 0.0528 s | 0.0547 s |
| Quantum fraction | 0.624 | 0.652 | 0.701 |
| setup_s | 3.681 s | 2.261 s | 0.963 s |
| Total wall (script) | 3.902 s | 2.413 s | 1.146 s |
| Queue wait (sacct, UTC) | aer_bell 0 s, vqe_toy 1 s | 0 s, 0 s | aer_bell 0 s, vqe_toy 2 s |
| sacct Elapsed | 4 s, 4 s | 2 s, 3 s | 1 s, 1 s |

- The Bell counts are identical across architectures with the same seed.
- The VQE final energy is bit-identical between the two aarch64 runs (−1.3567740895783653), but differs slightly on x86_64 (−1.3487) with identical seeds and pins. So the optimizer's path reproduces exactly on the same architecture but not across architectures. That's a reproducibility note about this setup, not a physics result.
- Setup varies a lot from run to run on the same M1 (3.7 s vs 2.3 s), and it's slower than on x86_64. These are different machines and different Docker VMs, so this isn't a chip comparison. The quantum fraction lands in the same 0.62–0.70 range everywhere.
- On macOS, `wc -l` pads its count with spaces (`RUNNING=       2`). `verify_qpu.sh` now strips the padding (cosmetic; the numeric check already worked).

**Where QRMI acquire/release would sit in this job** (if it ran under the QRMI SPANK plugin, spank-plugins@3455388):
- *Acquire:* in `slurm_spank_init_post_opt` in slurmstepd, after nodes are allocated. It calls `is_accessible` and `acquire`; on failure the error is deferred to `task_init`, which cancels the job ([docs/landscape.md](docs/landscape.md)). So acquire runs after allocation and before `python3 aer_bell.py` starts, and the scheduler never looked at QPU state when it placed the job.
- *Release:* in `slurm_spank_exit`, "called once just before slurmstepd exits in remote context" ([`spank_qrmi.c` L722](https://github.com/qiskit-community/spank-plugins/blob/3455388/plugins/spank_qrmi/spank_qrmi.c#L722)). It walks the acquired resources and calls `_release_qpu` ([L740](https://github.com/qiskit-community/spank-plugins/blob/3455388/plugins/spank_qrmi/spank_qrmi.c#L740)), which calls `qrmi_resource_release` ([L898](https://github.com/qiskit-community/spank-plugins/blob/3455388/plugins/spank_qrmi/spank_qrmi.c#L898)). So the QPU is held from just after allocation until the step exits, including the classical parts of the loop.

**Takeaway:** in this toy loop the simulated quantum calls are about two-thirds of the iteration time, but the job holds its `qpu:1` (and, under QRMI, the acquired QPU) for the whole run, setup included. Nothing in this path asks whether the QPU is calibrated.

**Next:** Week 3: feed QPU state into the scheduler.

## 2026-11-02: Week 1 landscape: where QPU state is static

In every Slurm integration I read (the QRMI SPANK plugin, the QRMI license-poller example, QDMI/MQT Core, Pasqal via QRMI, LRZ/MQSS), the most live QPU state that reaches the scheduler is an up/busy flag at admission. The SPANK plugin checks only `is_accessible` inside slurmstepd *after* allocation and cancels the job on failure.
Nothing I found passes calibration drift, recal windows or a prediction into placement or backfill. The closest measured work (Rocco et al., arXiv:2508.04217) releases classical nodes per job phase, not by QPU state.
Signals to target: day-to-day drift (lag-1 ACF 0.10–0.20, Deng et al. Table I), 40/100-min recal windows (Mansfield et al.), and hybrid-job idle under IBM's architecture 2.
Every row was re-checked against source at a pinned commit, or against the paper's full text. qBraid OS and Qblox/NVQLink are still unverified. Full table and sources: [docs/landscape.md](docs/landscape.md).

## 2026-11-02: Cluster moved into the repo + calibration feed skeleton

Week 2, part 1. Everything is **simulated**.

**Cluster (`cluster/`).** Copied in slurm-docker-cluster tag 3.0.2 (`9001503`, Slurm 26.05.5 default; now pinned to 26.05.2) and applied `experiments/week0/gres-qpu.patch`. Bring it up with `docker compose up -d --build`, then check it with `./verify_qpu.sh`. I tested from a clean `down -v` on an x86_64 Linux Docker host, not the M1. The image build there needed the sandbox's proxy CA injected into a scratch copy of the Dockerfile; the committed Dockerfile doesn't include that.

```
NODELIST GRES STATE
c1 qpu:1 idle
c2 qpu:1 idle
   JOBID NAME     STATE NODELIST(REASON) NODELIST
       3   q3   PENDING  (Resources)
       2   q2   RUNNING           c1 c1
       1   q1   RUNNING           c2 c2
```

Same result as Week 0: 2 RUNNING, 1 PENDING (Resources).

**What broke:**
1. *Stale config, root cause.* `/etc/slurm` is a named volume, and Docker seeds a named volume from the image only when it creates it. After a rebuild the volume keeps the old slurm.conf, which is the likely source of the Oct 26 `qpu:0` record. Fix: the image keeps `/etc/slurm.baked/slurm.conf`, and the slurmctld entrypoint copies it over on start, before any worker registers. Test: I set the volume's file back to `GresTypes=gpu` and ran `down` then `up` without `-v`. It came back as `gpu,qpu`, both nodes showed `qpu:1`, and the test passed.
2. *Worker crashed on startup (upstream race).* `qpu-cpu-worker-2` exited 1 because it started 0.2 s before worker-1. `detect_replica_number` stopped at the first DNS name that didn't resolve yet and returned 1, and `set -e` then killed the entrypoint. Fix: scan every index and retry for up to 15 s.
3. *Node naming.* Without a `.env`, the compose project name didn't match the `slurm-` prefix the entrypoint resolves, so nodes would have fallen back to container IDs. Fix: `name: ${COMPOSE_PROJECT_NAME:-qpu}` in compose, plus a matching worker default. This also keeps the volumes separate from the old Week 0 checkout.

**spank-plugins demo (15-min look).** `demo/qrmi/slurm-docker-cluster/INSTALL.md` pins slurm-docker-cluster **0.9.0** (Slurm 25.05.3, static nodes, a login node). Its `file.patch` rewrites that layout (slurm.conf, plugstack.conf, qrmi_config.json, compose), so it won't apply to 3.0.2. Using it for Week 3 means either running the demo as a separate cluster or porting plugstack.conf, qrmi_config.json and the QRMI build onto `cluster/`. Plan unchanged.

*Update (same day): simulated_quantum_resource, **verified**.* The `qiskit-community/...` URL doesn't exist; the repo is [`qrmi-community/simulated_quantum_resource`](https://github.com/qrmi-community/simulated_quantum_resource) (QRMI's `.github/workflows/e2e.yml` L137 checks it out from there). At `5f7b75d`, `get_backend_details()` in `qsa_sim/qsa_service.py` returns `"status": "online"` and `"locked": False` as literals (L309-310; L304-305 before commit `becd5e0`, Oct 31). No other code path sets a backend status, so a QRMI `status()` against this simulator always reads online. For Week 3 that means the simulator can't produce paused/offline on its own, so recal windows have to come from our feed (or a patch to the simulator).

**Calibration feed (`feed/`).** A stdlib HTTP service with `GET /qpus` and `GET /qpus/<id>/state`; `?at=` pins the time. State is a pure function of seed, QPU id and simulated time, with `--speed` to speed up the clock. Model: a full recal every day (100 min), a quick recal about every 6 h (40 min), with `paused` while a recal runs; daily quality follows an AR(1) with φ = 0.15, so a score from yesterday's calibration says little about today's (lag-1 ACF 0.10–0.20); drift since the last recal; 5 %/day maintenance outages (an assumed default, not from a source). There are 11 unit tests, including a sample ACF of 0.15 ± 0.06 over 3000 days. Sample (`--seed 42`, `GET /qpus/qpu1/state?at=2026-11-03T03:00:00Z`):

```json
{"id": "qpu1", "status": "online", "status_reason": "calibrated (simulated)",
 "next_recal": {"start": "2026-11-03T03:53:43Z", "kind": "full", "duration_min": 100},
 "metrics": {"t1_us": 223.5, "readout_err": 0.01438, "gate_err_1q": 0.0003404},
 "updated_at": "2026-11-03T03:00:00Z", "simulated": true}
```

**Takeaway:** Slurm still sees only `qpu:1`. The feed now knows qpu1 goes into a 100-minute full recal at 03:53, but nothing connects the two yet.

**Next:** rerun `./verify_qpu.sh` on the M1 (aarch64) to confirm. Week 3: have a Slurm hook (job_submit.lua or a SPANK plugin) read `/qpus/<id>/state`, and put the feed in compose.

## 2026-10-26 — Fake QPU resource (GRES) + contention test

**Setup:** same cluster. Added a count-only `qpu` GRES. Both CPU workers come from one compose service, so each got one QPU (2 total).

**Changes** (in slurm-docker-cluster; saved as `experiments/week0/gres-qpu.patch`):
- `config/26.05/slurm.conf`: `GresTypes=gpu` → `GresTypes=gpu,qpu`
- `docker-entrypoint.sh`: dynamic slurmd registration `--conf "Feature=cpu"` → `--conf "Feature=cpu Gres=qpu:1"`

Nodes register dynamically (`slurmd -Z`), so there are no `NodeName=` lines. A node advertises its GRES at startup. No `gres.conf` needed for a count-only resource.

**Bug: the controller trusted its stale record over the node.** The workers restarted before the new slurm.conf was pushed, so slurmctld logged `Invalid GRES configured on node c1: qpu:1` and stored both nodes with 0 QPUs. After a full restart it logged `Ignoring excess count on node c1 (1 > 0)`: the node reported 1, the controller kept its stored 0. Fix: `scontrol delete nodename=c1,c2` and restart the workers. Both then showed `qpu:1`.

**Contention test:** 3 jobs, each `--gres=qpu:1 --mem=500M -c1`, on 2 QPUs.

| Job | State | Node |
|---|---|---|
| q1 | RUNNING | c2 |
| q2 | RUNNING | c1 |
| q3 | PENDING (Resources) | — |

Both nodes showed CPUs `1/3/0/4` (3 idle each). The only thing blocking q3 was the QPU. c2 showed `mixed-`: the backfill scheduler had already planned it for q3.

**Takeaway:** Slurm sees a QPU as a counter, 1 or 0. It doesn't know whether the QPU just recalibrated or is drifting.

**Next:** quantum execution stack: run circuits on Aer and a fake IBM backend, time a toy VQE loop (classical vs quantum), find where QRMI acquire/release sits in a Slurm job. Week 2 packaging note: bake or push slurm.conf before workers start, to avoid the stale-record bug.

## 2026-10-14 — Slurm from the inside + overcommit test

**Setup:** slurm-docker-cluster (Slurm 26.05.2, EL9 aarch64) on an M1 MacBook Air via Docker Desktop. Two worker nodes (c1, c2). Each reports 4 CPUs and 7851 MB (the Docker VM's full budget), so Slurm sees 8 CPUs; the VM has 4.

**Overcommit test:** `burn.sbatch` hashes 12 GB of zeros (`head -c 12G /dev/zero | sha256sum`), 1 CPU and 500 MB per job. Arrays of 1, 4, 8 jobs, average ElapsedRaw from sacct, 2 runs.

| Concurrent jobs | Run 1 | Run 2 | Avg | vs baseline |
|---|---|---|---|---|
| 1 | 42.0s | 43.0s | 42.5s | 1.0× |
| 4 | 45.0s | 45.2s | 45.1s | 1.06× |
| 8 | 91.1s | 92.8s | 92.0s | 2.16× |

All 8 ran simultaneously (4 per node). The ~6% at n=4 is background containers sharing the CPUs. Takeaway: the scheduler only knows what nodes report.

**Other findings:**

1. Slurm runs a copy of the submitted script (/var/spool/slurm/jobNNNNN/slurm_script), so editing the file after sbatch changes nothing.
2. A job's final state comes from the last command's exit code (job 1 did its work but ended FAILED from a stray line).
3. With CR_CORE_MEMORY and DefMemPerNode=UNLIMITED, a 1-CPU job with no --mem took all 7851M of a node, so arrays ran 1 per node. --mem=500M fixed it (8 at once).
4. Backfill: a small job first showed PENDING (Priority), then the backfill pass started it ~30 s later. The big job's start estimate = the running job's start + its declared time limit.

**Caveat:** numbers on this setup reflect scheduling behavior, not real hardware speed.

**Next:** fake `qpu` GRES (nodes register dynamically, so config may live in slurmd startup rather than slurm.conf).

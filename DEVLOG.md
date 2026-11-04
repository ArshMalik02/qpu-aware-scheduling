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

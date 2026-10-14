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

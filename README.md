# qpu-aware-scheduling

**Scheduling hybrid quantum-classical jobs on HPC clusters using live QPU state.**

> A scheduler only knows what it's told.

Today Slurm sees a QPU as a counter: 1 or 0. It doesn't know whether the device is mid-recalibration, drifting, or about to go down, so a hybrid job can be handed CPU/GPU nodes for a QPU it can't use yet. This project is an experiment, built in public, in telling the scheduler more, and measuring whether it helps.

Everything here runs on a laptop against a **simulated QPU**. All results are labeled simulated.

## The gap (Week 1 reading)

From the QRMI SPANK plugin source and the docs I read (full sources and commits: [docs/landscape.md](docs/landscape.md)):

| System | How Slurm sees the QPU | Live QPU state that reaches the scheduler |
|---|---|---|
| [QRMI / spank-plugins](https://github.com/qiskit-community/spank-plugins) | `--qpu=` SPANK option mapped to `qrmi_config.json` | Plugin: none. The QPU is checked inside the job *after* nodes are allocated; on failure the job is cancelled |
| [QRMI license poller (reference example)](https://github.com/qrmi-community/slurm_poller_daemon_example) | Slurm dynamic license per backend (`--licenses=`) | Ready/busy only, polled every `poll_interval` s; jobs pend while busy, offline or paused |
| [QDMI (MQT Core docs)](https://mqt.readthedocs.io/projects/core/en/latest/qdmi/slurm.html) | One Slurm license per device | Up/down only, at admission (a documented license monitor) |
| [LRZ / MQSS](https://arxiv.org/abs/2608.14827) | GRES `qpu` + prolog | None in the public code; recal handled by the vendor stack |

I haven't found published work where calibration or recalibration state reaches Slurm placement or backfill as anything more than an up/busy flag (no drift, no recal windows, no prediction). Closest measured work: [Rocco et al., QCE25](https://arxiv.org/abs/2508.04217) cuts classical node-seconds vs static allocation on Slurm by releasing nodes per job phase, not QPU state. If you know of more, please open an issue.

## What works today

- **Week 0:** Local Slurm cluster ([slurm-docker-cluster](https://github.com/giovtorres/slurm-docker-cluster), Slurm 26.05.2) on an M1 Mac. Slurm sees 8 CPUs on a 4-CPU VM, so 8 concurrent jobs ran **2.16x** slower than one. The scheduler trusts what nodes report.
- **Fake `qpu` GRES + contention test:** 3 jobs requesting `--gres=qpu:1` on 2 QPUs. Two run, and the third pends on `Resources` while both nodes have 3 idle CPUs. The QPU is the only thing blocking it.

Details, numbers and bugs hit along the way: [DEVLOG.md](DEVLOG.md).

## Roadmap

- [x] Week 0: Slurm internals, overcommit test, fake `qpu` GRES
- [x] Week 1: Landscape: where QPU state does and doesn't enter scheduling
- [x] Week 2: Cluster in this repo (`docker compose up`) + a Qiskit Aer job through `--gres=qpu:1`
- [ ] Week 3: QRMI against a simulator + a simulated calibration/recal feed
- [ ] Week 4: Static-allocation baseline: classical node-seconds idle, queue wait, QPU utilization (3 seeded runs)
- [ ] Week 5: State-aware policy (`job_submit` Lua, external scheduler as fallback)
- [ ] Week 6: One chart, one table, limits written down; open an upstream discussion

## Repo layout

- `experiments/week0/`: overcommit test, GRES patch, sbatch scripts
- `DEVLOG.md`: what I ran, what I saw, what broke

## Reproduce Week 0

See [experiments/week0/README.md](experiments/week0/README.md). You need Docker and a clone of slurm-docker-cluster; apply `gres-qpu.patch` for the `qpu` GRES.

## Follow along

Weekly build logs on X: [@arshmalik02](https://x.com/arshmalik02). Issues and corrections welcome.

## License

See [LICENSE](LICENSE).

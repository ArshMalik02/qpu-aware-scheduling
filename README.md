Scheduling hybrid quantum-classical jobs on HPC clusters using live QPU state

Everything here is **simulated**: the QPUs are Slurm counters and the calibration data is synthetic.

| Path | What |
|---|---|
| [`cluster/`](cluster/) | Docker Slurm cluster (slurm-docker-cluster 3.0.2) with a `qpu` GRES on c1, c2. `cd cluster && docker compose up -d --build && ./verify_qpu.sh` |
| [`feed/`](feed/) | Seeded, simulated calibration feed over HTTP: `python3 feed/calibration_feed.py --seed 42` |
| [`experiments/`](experiments/) | Week-by-week experiments |
| [`DEVLOG.md`](DEVLOG.md) | Running log |

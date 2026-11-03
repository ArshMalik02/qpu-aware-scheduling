# jobs/: simulated quantum jobs through `--gres=qpu:1`

Two Slurm batch jobs that each request the cluster's `qpu` GRES and run on Qiskit Aer on the CPU.
**Everything here is simulated.** The `qpu` GRES is a Slurm counter (see [`../cluster/`](../cluster/)),
and no quantum hardware is involved. The timings show how this Docker setup behaves, not any hardware.

## Run

With the cluster up (`cd cluster && docker compose up -d --build && ./verify_qpu.sh`), from the repo root:

```bash
jobs/verify_aer.sh
```

It copies `jobs/` into `slurmctld:/data/jobs/`, submits both jobs, waits for them (5 min timeout),
checks the outputs, prints `sacct` (queue wait = Start − Submit, wall time = Elapsed), copies the results
to `jobs/results/<arch>/`, and prints `PASS` or `FAIL` (exit 1).

Qiskit, Aer, numpy and scipy are baked into the cluster image at exact pins
([`../cluster/requirements-jobs.txt`](../cluster/requirements-jobs.txt)), so there's no setup on the nodes.

## Files

| File | What it does |
|---|---|
| `aer_bell.sbatch` | `--gres=qpu:1 -c1 --mem=500M --time=00:05:00`; runs `aer_bell.py` |
| `aer_bell.py` | 2-qubit Bell circuit (H, CX, measure), 4096 shots on `AerSimulator`, `seed_simulator=1234`. Writes `out/aer_bell_<jobid>.json`: counts, shots, versions, hostname, arch, `SLURM_JOB_ID`, any GRES/GPU env vars, `"simulated": true` |
| `vqe_toy.sbatch` | Same resources; runs `vqe_toy.py` |
| `vqe_toy.py` | Toy VQE: toy Hamiltonian `ZZ + 0.5·XI + 0.5·IX` (not a molecule), a 4-parameter RY/CX ansatz transpiled once, Aer `EstimatorV2` with fixed seeds, COBYLA with `maxiter=30` and fixed initial parameters. Writes `out/vqe_toy_<jobid>.csv` (`iter,energy,quantum_s,classical_s`) and a `.json` summary |
| `check_outputs.py` | Checks run by `verify_aer.sh` inside slurmctld: Bell shots == 4096, only `00`/`11`, each 40–60 %; VQE ≥ 5 rows, all timings > 0, energies finite |
| `verify_aer.sh` | The end-to-end check above |
| `results/<arch>/` | Committed outputs from a run: JSON, CSV, `.out` and `sacct` text |

`--mem=500M` is required. With `DefMemPerNode=UNLIMITED`, a job without it takes a whole node
([DEVLOG 2026-10-14](../DEVLOG.md)).

## Timing definitions (`vqe_toy.py`)

All timings use `time.perf_counter()`.

- `quantum_s`: the Aer estimator `run(...).result()` call only (simulated "quantum" time).
- `classical_s`: from the end of the previous estimator call to the start of this one, which covers COBYLA,
  Python overhead and parameter binding. For the first iteration it starts just before `minimize`.
- `setup_s`: imports, circuit build and transpile. `total_wall_s`: script start to finish.
- `quantum_frac = Σquantum_s / (Σquantum_s + Σclassical_s)`.

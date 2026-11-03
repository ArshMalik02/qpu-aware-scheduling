#!/usr/bin/env python3
"""Toy VQE loop with per-iteration timing. SIMULATED: Aer EstimatorV2 on CPU.

Systems timing only. The Hamiltonian is a hard-coded 2-qubit toy Hamiltonian
(ZZ + 0.5*XI + 0.5*IX), not a molecule, and the energies say nothing physical.

Timing per objective call (time.perf_counter):
  quantum_s   = the Aer estimator run(...).result() call only
  classical_s = time from the end of the previous estimator call to the start of
                this one: optimizer work, Python overhead and parameter binding
Also: setup_s (imports, circuit build, transpile) and total wall time.

Writes /data/jobs/out/vqe_toy_<jobid>.csv and vqe_toy_<jobid>.json.
"""

import time

t_wall0 = time.perf_counter()

import csv
import json
import math
import os
import platform
import socket
from pathlib import Path

import numpy as np
import qiskit
import qiskit_aer
import scipy
from qiskit import QuantumCircuit
from qiskit.circuit import ParameterVector
from qiskit.quantum_info import SparsePauliOp
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_aer.primitives import EstimatorV2
from scipy.optimize import minimize

SEED = 1234
MAXITER = 30
OUT_DIR = Path(os.environ.get("JOBS_OUT_DIR", "/data/jobs/out"))
job_id = os.environ.get("SLURM_JOB_ID", "local")

# Toy Hamiltonian (not a molecule).
hamiltonian = SparsePauliOp.from_list([("ZZ", 1.0), ("XI", 0.5), ("IX", 0.5)])

# Small hand-built ansatz: RY layer, CX, RY layer (4 parameters).
theta = ParameterVector("θ", 4)
ansatz = QuantumCircuit(2)
ansatz.ry(theta[0], 0)
ansatz.ry(theta[1], 1)
ansatz.cx(0, 1)
ansatz.ry(theta[2], 0)
ansatz.ry(theta[3], 1)

# Transpile once, before the loop.
backend = AerSimulator(seed_simulator=SEED)
pm = generate_preset_pass_manager(optimization_level=1, backend=backend, seed_transpiler=SEED)
isa_ansatz = pm.run(ansatz)
isa_obs = hamiltonian.apply_layout(isa_ansatz.layout)

estimator = EstimatorV2(options={"backend_options": {"seed_simulator": SEED},
                                 "run_options": {"seed": SEED}})

setup_s = time.perf_counter() - t_wall0

rows = []
_prev_end = None  # end of previous estimator call


def objective(x):
    global _prev_end
    t0 = time.perf_counter()
    params = np.asarray(x, dtype=float)  # parameter binding happens in the pub
    pub = (isa_ansatz, isa_obs, params)
    t1 = time.perf_counter()
    energy = float(estimator.run([pub]).result()[0].data.evs)
    t2 = time.perf_counter()
    classical = (t0 - _prev_end) + (t1 - t0)
    rows.append({"iter": len(rows) + 1, "energy": energy,
                 "quantum_s": t2 - t1, "classical_s": classical})
    _prev_end = t2
    return energy


x0 = np.array([0.1, 0.2, 0.3, 0.4])
_prev_end = time.perf_counter()
res = minimize(objective, x0, method="COBYLA", options={"maxiter": MAXITER})
total_wall_s = time.perf_counter() - t_wall0

sum_q = sum(r["quantum_s"] for r in rows)
sum_c = sum(r["classical_s"] for r in rows)
summary = {
    "iterations": len(rows),
    "final_energy": rows[-1]["energy"],
    "energy_finite": all(math.isfinite(r["energy"]) for r in rows),
    "sum_quantum_s": round(sum_q, 6),
    "sum_classical_s": round(sum_c, 6),
    "quantum_frac": round(sum_q / (sum_q + sum_c), 4),
    "setup_s": round(setup_s, 4),
    "total_wall_s": round(total_wall_s, 4),
    "optimizer": "COBYLA maxiter=30",
    "hamiltonian": "toy: ZZ + 0.5*XI + 0.5*IX",
    "qiskit": qiskit.__version__,
    "qiskit_aer": qiskit_aer.__version__,
    "numpy": np.__version__,
    "scipy": scipy.__version__,
    "hostname": socket.gethostname(),
    "arch": platform.machine(),
    "SLURM_JOB_ID": job_id,
    "backend": "AerSimulator (CPU)",
    "simulated": True,
}

OUT_DIR.mkdir(parents=True, exist_ok=True)
with open(OUT_DIR / f"vqe_toy_{job_id}.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["iter", "energy", "quantum_s", "classical_s"])
    w.writeheader()
    for r in rows:
        w.writerow({"iter": r["iter"], "energy": f"{r['energy']:.8f}",
                    "quantum_s": f"{r['quantum_s']:.6f}", "classical_s": f"{r['classical_s']:.6f}"})
(OUT_DIR / f"vqe_toy_{job_id}.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))

#!/usr/bin/env python3
"""2-qubit Bell circuit on Qiskit Aer (CPU simulator). SIMULATED: no quantum hardware.

Writes /data/jobs/out/aer_bell_<jobid>.json with counts and run metadata.
"""

import json
import os
import platform
import socket
import time
from pathlib import Path

t_start = time.perf_counter()

import qiskit
import qiskit_aer
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

SHOTS = 4096
SEED = 1234
OUT_DIR = Path(os.environ.get("JOBS_OUT_DIR", "/data/jobs/out"))

qc = QuantumCircuit(2, 2)
qc.h(0)
qc.cx(0, 1)
qc.measure([0, 1], [0, 1])

sim = AerSimulator()
counts = sim.run(transpile(qc, sim), shots=SHOTS, seed_simulator=SEED).result().get_counts()

job_id = os.environ.get("SLURM_JOB_ID", "local")
gres_env = {k: v for k, v in os.environ.items() if "GRES" in k or "GPUS" in k}

result = {
    "counts": dict(sorted(counts.items())),
    "shots": SHOTS,
    "seed_simulator": SEED,
    "qiskit": qiskit.__version__,
    "qiskit_aer": qiskit_aer.__version__,
    "hostname": socket.gethostname(),
    "arch": platform.machine(),
    "SLURM_JOB_ID": job_id,
    "slurm_gres_env": gres_env,
    "wall_s": round(time.perf_counter() - t_start, 4),
    "backend": "AerSimulator (CPU)",
    "simulated": True,
}

OUT_DIR.mkdir(parents=True, exist_ok=True)
out = OUT_DIR / f"aer_bell_{job_id}.json"
out.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))

#!/usr/bin/env python3
"""Check the Bell and toy-VQE outputs for jobs/verify_aer.sh. Usage: check_outputs.py <bell_id> <vqe_id>"""
import csv, json, math, sys
bell, vqe = sys.argv[1], sys.argv[2]
b = json.load(open(f"/data/jobs/out/aer_bell_{bell}.json"))
c = b["counts"]
frac = {k: v / b["shots"] for k, v in c.items()}
bell_ok = b["shots"] == 4096 and set(c) <= {"00", "11"} and all(0.4 <= f <= 0.6 for f in frac.values()) and len(c) == 2
print(f"    Bell     counts={c} shots={b['shots']} host={b['hostname']} arch={b['arch']} -> {'ok' if bell_ok else 'BAD'}")
rows = list(csv.DictReader(open(f"/data/jobs/out/vqe_toy_{vqe}.csv")))
vqe_ok = (len(rows) >= 5
          and all(float(r["quantum_s"]) > 0 and float(r["classical_s"]) > 0 for r in rows)
          and all(math.isfinite(float(r["energy"])) for r in rows))
s = json.load(open(f"/data/jobs/out/vqe_toy_{vqe}.json"))
print(f"    VQE      iters={s['iterations']} sum_quantum_s={s['sum_quantum_s']} sum_classical_s={s['sum_classical_s']} "
      f"quantum_frac={s['quantum_frac']} setup_s={s['setup_s']} total_wall_s={s['total_wall_s']} -> {'ok' if vqe_ok else 'BAD'}")
print("CHECKS_RAN")
sys.exit(0 if (bell_ok and vqe_ok) else 1)

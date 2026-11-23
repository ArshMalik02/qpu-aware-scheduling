"""Tests for the workload generator. Run: python3 -m unittest -v (from workload/)."""

import json
import tempfile
import unittest
from pathlib import Path

import gen


class GenTests(unittest.TestCase):
    def manifest_bytes(self, seed):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.json"
            gen.main(["--seed", str(seed), "--manifest", str(p)])
            return p.read_bytes()

    def test_same_seed_same_manifest(self):
        self.assertEqual(self.manifest_bytes(1), self.manifest_bytes(1))

    def test_different_seed_different_manifest(self):
        self.assertNotEqual(self.manifest_bytes(1), self.manifest_bytes(2))

    def test_job_shapes(self):
        m = json.loads(self.manifest_bytes(1))
        self.assertTrue(m["simulated"] and m["assumed"])
        self.assertEqual({j["type"] for j in m["jobs"]}, {"qpu", "hybrid", "classical"})
        arrivals = [j["arrival_s"] for j in m["jobs"]]
        self.assertEqual(arrivals, sorted(arrivals))
        self.assertTrue(all(0 < a < m["duration_min"] * 60 for a in arrivals))
        for j in m["jobs"]:
            args = gen.sbatch_args(j, "/tmp/out")
            self.assertIn("--mem=500M", args)
            self.assertEqual("--gres=qpu:1" in args, j["type"] != "classical")

    def test_time_limits(self):
        for seed in range(1, 6):
            m = json.loads(self.manifest_bytes(seed))
            for j in m["jobs"]:
                self.assertLess(j["hold_s"], j["limit_s"])
                self.assertLessEqual(j["limit_s"], j["slurm_limit_s"])
                self.assertEqual(j["slurm_limit_s"] % 60, 0)
                self.assertEqual((j["limit_s"], j["slurm_limit_s"]), gen.limit_for(j["hold_s"]))
                args = gen.sbatch_args(j, "/tmp/out")
                t = [x for x in args if x.startswith("--time=")]
                self.assertEqual(t, [gen.time_arg(j["limit_s"])])
                mm, ss = t[0][len("--time="):].split(":")
                self.assertEqual(int(mm) * 60 + int(ss), j["limit_s"])

    def test_limit_examples(self):
        self.assertEqual(gen.limit_for(10.0), (45, 60))     # ceil(15)+30
        self.assertEqual(gen.limit_for(240.0), (390, 420))  # max hold -> 6:30, Slurm 7:00
        self.assertEqual(gen.time_arg(390), "--time=06:30")

    def test_hold_qpu_only_holds_qpu_jobs(self):
        m = json.loads(self.manifest_bytes(1))
        for j in m["jobs"]:
            self.assertEqual("--hold" in gen.sbatch_args(j, "/tmp/o", hold_qpu=True), j["qpu"])
            self.assertNotIn("--hold", gen.sbatch_args(j, "/tmp/o"))


if __name__ == "__main__":
    unittest.main()

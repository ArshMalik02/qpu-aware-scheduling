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


if __name__ == "__main__":
    unittest.main()

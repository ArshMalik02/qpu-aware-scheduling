"""Tests for the policy-agnostic recal-overlap metric. Run: python3 -m unittest -v (from policy/)."""

import unittest
from datetime import datetime

import summarize as s


def job(jid, kind, node, start, end):
    return {"job_id": jid, "name": f"{kind}-{jid}", "type": kind, "node": node,
            "start": start, "end": end}


T = [  # c1 out 10:00:00 -> in 10:01:00; c2 out 10:05:00 -> never back (run end)
    {"wall": "2026-11-18T10:00:00Z", "node": "c1", "action": "QPU_OUT"},
    {"wall": "2026-11-18T10:01:00Z", "node": "c1", "action": "QPU_IN"},
    {"wall": "2026-11-18T10:05:00Z", "node": "c2", "action": "QPU_OUT"},
]
END = datetime(2026, 11, 18, 10, 10)


class RecalOverlapTests(unittest.TestCase):
    def test_intersection_with_each_window(self):
        jobs = [
            job("1", "qpu", "c1", "2026-11-18T09:59:30", "2026-11-18T10:00:30"),       # running at out: 30 s
            job("2", "hybrid", "c1", "2026-11-18T09:59:00", "2026-11-18T10:03:00"),    # capped at QPU_IN: 60 s
            job("3", "classical", "c1", "2026-11-18T09:59:00", "2026-11-18T10:03:00"), # classical: ignored
            job("4", "qpu", "c2", "2026-11-18T10:00:00", "2026-11-18T10:02:00"),       # ended before c2 out
            job("5", "qpu", "c1", "2026-11-18T10:00:00", "2026-11-18T10:00:10"),       # started exactly at out
            job("6", "qpu", "c1", "2026-11-18T10:00:30", "2026-11-18T10:00:40"),       # started inside the window
            job("8", "qpu", "c1", "2026-11-18T10:01:00", "2026-11-18T10:02:00"),       # started at QPU_IN: 0
            job("9", "qpu", "c1", "2026-11-18T09:58:00", "2026-11-18T10:00:00"),       # ended at QPU_OUT: 0
        ]
        r = s.recal_overlap(jobs, T, speed=36, run_end=END)
        got = {h["job_id"]: h["overlap_wall_s"] for h in r["jobs"]}
        self.assertEqual(got, {"1": 30.0, "2": 60.0, "5": 10.0, "6": 10.0})
        self.assertEqual(r["count"], 4)
        self.assertEqual(r["total_overlap_wall_s"], 110.0)
        self.assertEqual(r["total_overlap_feed_min"], 66.0)  # 110 s * 36 / 60

    def test_job_starting_inside_window_is_counted(self):
        # The static case: the QPU is never taken out, so a job can start mid-recal.
        jobs = [job("10", "hybrid", "c1", "2026-11-18T10:00:20", "2026-11-18T10:05:00")]
        r = s.recal_overlap(jobs, T, speed=36, run_end=END)
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["jobs"][0]["overlap_wall_s"], 40.0)  # 10:00:20 -> QPU_IN 10:01:00
        self.assertTrue(r["jobs"][0]["started_inside_window"])

    def test_job_spanning_two_windows_sums_both(self):
        t2 = T[:2] + [{"wall": "2026-11-18T10:02:00Z", "node": "c1", "action": "QPU_OUT"},
                      {"wall": "2026-11-18T10:02:30Z", "node": "c1", "action": "QPU_IN"}]
        jobs = [job("11", "qpu", "c1", "2026-11-18T10:00:45", "2026-11-18T10:03:00")]
        r = s.recal_overlap(jobs, t2, speed=36, run_end=END)
        self.assertEqual(r["jobs"][0]["overlap_wall_s"], 45.0)  # 15 s + 30 s
        self.assertEqual(len(r["jobs"][0]["qpu_out_at"]), 2)

    def test_open_window_runs_to_job_end(self):
        jobs = [job("7", "qpu", "c2", "2026-11-18T10:04:00", "2026-11-18T10:06:00")]
        r = s.recal_overlap(jobs, T, speed=36, run_end=END)
        self.assertEqual(r["jobs"][0]["overlap_wall_s"], 60.0)
        self.assertEqual(r["jobs"][0]["overlap_feed_min"], 36.0)

    def test_feed_min_uses_given_speed(self):
        self.assertEqual(s.feed_min(60, 36), 36.0)
        self.assertEqual(s.feed_min(60, 72), 72.0)


if __name__ == "__main__":
    unittest.main()

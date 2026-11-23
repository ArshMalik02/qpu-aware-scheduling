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

    def test_forecast_split_by_direction(self):
        # c1's recal came 5 min EARLIER than published (offset +300 s); c2's came LATER (-120 s).
        trans = [
            {"wall": "2026-11-18T10:00:00Z", "feed_time": "2026-11-01T04:00:10Z", "node": "c1", "action": "QPU_OUT"},
            {"wall": "2026-11-18T10:01:00Z", "feed_time": "2026-11-01T04:36:10Z", "node": "c1", "action": "QPU_IN"},
            {"wall": "2026-11-18T10:05:00Z", "feed_time": "2026-11-01T07:00:05Z", "node": "c2", "action": "QPU_OUT"},
        ]
        fc = [
            {"qpu": "qpu0", "kind": "quick", "true_start": "2026-11-01T04:00:00Z", "true_end": "2026-11-01T04:40:00Z",
             "published_start": "2026-11-01T04:05:00Z", "offset_s": 300, "offset_min": 5.0},
            {"qpu": "qpu1", "kind": "quick", "true_start": "2026-11-01T07:00:00Z", "true_end": "2026-11-01T07:40:00Z",
             "published_start": "2026-11-01T06:58:00Z", "offset_s": -120, "offset_min": -2.0},
            {"qpu": "qpu0", "kind": "full", "true_start": "2026-11-02T04:00:00Z", "true_end": "2026-11-02T05:40:00Z",
             "published_start": "2026-11-02T04:00:00Z", "offset_s": 0, "offset_min": 0.0},  # after the run
        ]
        jobs = [job("1", "qpu", "c1", "2026-11-18T09:59:30", "2026-11-18T10:00:30"),   # 30 s, early recal
                job("2", "hybrid", "c2", "2026-11-18T10:04:00", "2026-11-18T10:06:00")]  # 60 s, late recal
        ov = s.recal_overlap(jobs, trans, speed=36, run_end=END)
        r = s.forecast_split(ov, trans, fc, {"qpu0": "c1", "qpu1": "c2"}, 36,
                             feed_end=datetime(2026, 11, 1, 18, 0))
        d = r["overlap_by_direction"]
        self.assertEqual((d["earlier_than_published"]["jobs"], d["earlier_than_published"]["wall_s"]), (1, 30.0))
        self.assertEqual((d["later_than_published"]["jobs"], d["later_than_published"]["wall_s"]), (1, 60.0))
        self.assertEqual(d["unmatched"]["jobs"], 0)
        self.assertEqual(len(r["recals_in_run"]), 2)  # the day-2 recal is after feed_end
        self.assertEqual(r["recals_by_direction"], {"earlier_than_published": 1, "later_than_published": 1, "exact": 0})

    def test_feed_min_uses_given_speed(self):
        self.assertEqual(s.feed_min(60, 36), 36.0)
        self.assertEqual(s.feed_min(60, 72), 72.0)


if __name__ == "__main__":
    unittest.main()

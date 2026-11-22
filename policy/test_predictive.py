"""Tests for the predictive admission rule (pure functions). Run: python3 -m unittest -v (from policy/)."""

import unittest
from datetime import datetime, timedelta, timezone

import predictive as p

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
MAP = {"qpu0": "c1", "qpu1": "c2"}


def state(status, minutes_to_recal):
    nr = (T0 + timedelta(minutes=minutes_to_recal)).isoformat().replace("+00:00", "Z")
    return {"status": status, "next_recal": {"start": nr}}


class FitsTests(unittest.TestCase):
    def test_fits(self):
        # 2 min wall limit at 36x = 72 feed min; poll 10 s = 6 feed min; recal in 90 min.
        self.assertTrue(p.fits("online", T0, 120 * 36, 10 * 36, T0 + timedelta(minutes=90)))

    def test_does_not_fit(self):
        # 72 + 6 = 78 feed min needed, recal in 75 min.
        self.assertFalse(p.fits("online", T0, 120 * 36, 10 * 36, T0 + timedelta(minutes=75)))

    def test_exact_boundary_fits(self):
        self.assertTrue(p.fits("online", T0, 120 * 36, 10 * 36, T0 + timedelta(minutes=78)))

    def test_recal_already_running(self):
        # paused (recal in progress): never fits, however far the next recal is.
        self.assertFalse(p.fits("paused", T0, 60, 10, T0 + timedelta(hours=6)))
        self.assertFalse(p.fits("offline", T0, 60, 10, T0 + timedelta(hours=6)))

    def test_no_next_recal_fits_if_online(self):
        self.assertTrue(p.fits("online", T0, 60, 10, None))

    def test_two_qpus_one_fits(self):
        states = {"qpu0": state("online", 30), "qpu1": state("online", 300)}
        now = {"qpu0": T0, "qpu1": T0}
        self.assertEqual(p.fitting_nodes(states, MAP, now, 120, 36, 10), ["c2"])

    def test_two_qpus_none_and_both(self):
        now = {"qpu0": T0, "qpu1": T0}
        none = {"qpu0": state("paused", 300), "qpu1": state("online", 10)}
        both = {"qpu0": state("online", 300), "qpu1": state("online", 300)}
        self.assertEqual(p.fitting_nodes(none, MAP, now, 120, 36, 10), [])
        self.assertEqual(p.fitting_nodes(both, MAP, now, 120, 36, 10), ["c1", "c2"])


class ParseTests(unittest.TestCase):
    def test_slurm_limit(self):
        self.assertEqual(p.parse_slurm_limit("2:00"), 120)
        self.assertEqual(p.parse_slurm_limit("1:02:00"), 3720)
        self.assertEqual(p.parse_slurm_limit("1-00:00:00"), 86400)
        self.assertIsNone(p.parse_slurm_limit("UNLIMITED"))


if __name__ == "__main__":
    unittest.main()

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

    def test_next_recal_in_the_past_does_not_fit(self):
        self.assertFalse(p.fits("online", T0, 60, 10, T0 - timedelta(minutes=1)))
        self.assertFalse(p.fits("online", T0, 0, 0, T0 - timedelta(seconds=1)))

    def test_online_but_unhealthy_does_not_fit(self):
        # Matches reactive.py: the QPU is out when status != online or healthy == false.
        self.assertFalse(p.fits("online", T0, 60, 10, T0 + timedelta(hours=6), healthy=False))
        self.assertTrue(p.fits("online", T0, 60, 10, T0 + timedelta(hours=6), healthy=None))
        unhealthy = {"qpu0": dict(state("online", 300), healthy=False), "qpu1": state("online", 300)}
        self.assertEqual(p.fitting_nodes(unhealthy, MAP, {"qpu0": T0, "qpu1": T0}, 120, 36, 10), ["c2"])

    def test_missing_qpu_state_does_not_fit(self):
        self.assertFalse(p.fits(None, T0, 60, 10, None))
        only_qpu1 = {"qpu1": state("online", 300)}
        self.assertEqual(p.fitting_nodes(only_qpu1, MAP, {"qpu0": T0, "qpu1": T0}, 120, 36, 10), ["c2"])
        # state present but no feed time for it (never polled): also skipped
        both = {"qpu0": state("online", 300), "qpu1": state("online", 300)}
        self.assertEqual(p.fitting_nodes(both, MAP, {"qpu1": T0}, 120, 36, 10), ["c2"])


NODES = ["c1", "c2"]


class DecideTests(unittest.TestCase):
    def test_held_some_fit_releases_with_exclude(self):
        self.assertEqual(p.decide(True, ["c1"], NODES, None), ("release", ("c2",)))

    def test_held_all_fit_releases_with_empty_exclude(self):
        self.assertEqual(p.decide(True, ["c1", "c2"], NODES, None), ("release", ()))

    def test_held_none_fit_stays(self):
        self.assertEqual(p.decide(True, [], NODES, None), ("stay", None))
        self.assertEqual(p.decide(True, [], NODES, ("c2",)), ("stay", ("c2",)))

    def test_released_none_fit_reholds(self):
        self.assertEqual(p.decide(False, [], NODES, ("c2",)), ("rehold", ("c2",)))

    def test_released_fitting_set_changed_excludes(self):
        self.assertEqual(p.decide(False, ["c2"], NODES, ("c2",)), ("exclude", ("c1",)))
        self.assertEqual(p.decide(False, ["c1", "c2"], NODES, ("c2",)), ("exclude", ()))

    def test_released_same_set_does_nothing(self):
        self.assertEqual(p.decide(False, ["c1"], NODES, ("c2",)), ("nothing", ("c2",)))

    def test_released_seen_first_time_sets_exclude(self):
        # e.g. the loop restarted: no recorded ExcNodeList yet
        self.assertEqual(p.decide(False, ["c1"], NODES, None), ("exclude", ("c2",)))

    def test_both_hold_reasons_count_as_held(self):
        self.assertEqual(set(p.HELD_REASONS), {"JobHeldUser", "JobHeldAdmin"})


class ParseTests(unittest.TestCase):
    def test_slurm_limit(self):
        self.assertEqual(p.parse_slurm_limit("2:00"), 120)
        self.assertEqual(p.parse_slurm_limit("1:02:00"), 3720)
        self.assertEqual(p.parse_slurm_limit("1-00:00:00"), 86400)
        self.assertIsNone(p.parse_slurm_limit("UNLIMITED"))


if __name__ == "__main__":
    unittest.main()

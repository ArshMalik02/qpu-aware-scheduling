"""Tests for the simulated calibration feed. Run: python3 -m unittest -v (from feed/)."""

import json
import threading
import unittest
import urllib.request
from datetime import timedelta
from http.server import ThreadingHTTPServer

import calibration_feed as f


class ModelTests(unittest.TestCase):
    cfg = f.FeedConfig(seed=7)
    t0 = f.FeedConfig.epoch + timedelta(hours=12)

    def test_same_seed_same_output(self):
        a = f.qpu_state(f.FeedConfig(seed=7), "qpu0", self.t0)
        b = f.qpu_state(f.FeedConfig(seed=7), "qpu0", self.t0)
        self.assertEqual(a, b)

    def test_different_seed_different_output(self):
        a = f.qpu_state(f.FeedConfig(seed=7), "qpu0", self.t0)
        b = f.qpu_state(f.FeedConfig(seed=8), "qpu0", self.t0)
        self.assertNotEqual(a["metrics"], b["metrics"])

    def test_changes_over_time(self):
        a = f.qpu_state(self.cfg, "qpu0", self.t0)
        b = f.qpu_state(self.cfg, "qpu0", self.t0 + timedelta(minutes=5))
        self.assertNotEqual(a["metrics"], b["metrics"])

    def test_schema(self):
        s = f.qpu_state(self.cfg, "qpu1", self.t0)
        self.assertIn(s["status"], {"online", "paused", "offline"})
        self.assertIn(s["next_recal"]["kind"], {"quick", "full"})
        self.assertEqual(set(s["metrics"]), {"t1_us", "readout_err", "gate_err_1q"})
        self.assertIs(s["simulated"], True)

    def test_recal_durations_and_paused_status(self):
        seen = {}
        for day in range(5):
            for w in f._day_windows(self.cfg, "qpu0", day):
                if w.kind != "maintenance":
                    seen[w.kind] = w.duration_min
                    mid = w.start + (w.end - w.start) / 2
                    self.assertEqual(f.qpu_state(self.cfg, "qpu0", mid)["status"], "paused")
        self.assertEqual(seen, {"full": 100, "quick": 40})

    def test_next_recal_is_in_the_future(self):
        for h in range(0, 48, 3):
            t = self.t0 + timedelta(hours=h)
            s = f.qpu_state(self.cfg, "qpu0", t)
            self.assertGreater(f.parse_time(s["next_recal"]["start"]), t)

    def test_day_to_day_correlation_is_weak(self):
        # Sample lag-1 ACF of the daily quality series should sit near phi=0.15.
        z = [f._day_quality(f.FeedConfig(seed=1), "qpu0", d) for d in range(3000)]
        m = sum(z) / len(z)
        num = sum((z[i] - m) * (z[i + 1] - m) for i in range(len(z) - 1))
        den = sum((x - m) ** 2 for x in z)
        self.assertAlmostEqual(num / den, 0.15, delta=0.06)

    def test_unknown_qpu(self):
        with self.assertRaises(KeyError):
            f.qpu_state(self.cfg, "qpu99", self.t0)



class HresShapeTests(unittest.TestCase):
    """QRMI ResourceStatus / HRES-plugin fields added in Week 3."""

    cfg = f.FeedConfig(seed=7)

    def sweep(self, cfg, days=3, step_min=5):
        t = f.FeedConfig.epoch
        for i in range(days * 24 * 60 // step_min):
            for q in f.qpu_ids(cfg):
                yield q, f.qpu_state(cfg, q, t + timedelta(minutes=i * step_min))

    def test_new_fields_present_and_typed(self):
        s = f.qpu_state(self.cfg, "qpu0", ModelTests.t0)
        self.assertIsInstance(s["healthy"], bool)
        self.assertIs(s["busy"], False)
        self.assertEqual(set(s["capacity"]), {"available_slots", "max_slots"})
        self.assertIsNone(s["pending_job_count"])
        for k in ("available", "max", "reason", "drift_score"):
            self.assertIn(k, s)
        self.assertEqual(s["reason"], s["status_reason"])
        self.assertEqual(s["available"], s["capacity"]["available_slots"])
        self.assertEqual(s["max"], s["capacity"]["max_slots"])

    def test_available_zero_unless_online(self):
        seen = set()
        for _, s in self.sweep(self.cfg):
            seen.add(s["status"])
            if s["status"] == "online":
                self.assertEqual(s["available"], s["max"])
            else:
                self.assertEqual(s["available"], 0)
        self.assertIn("paused", seen)

    def test_healthy_false_only_when_offline(self):
        # Seed-independent: find an offline window by scanning maintenance windows.
        cfg = f.FeedConfig(seed=7, p_offline_per_day=1.0)
        offline = 0
        for _, s in self.sweep(cfg, days=2):
            self.assertEqual(s["healthy"], s["status"] != "offline")
            offline += s["status"] == "offline"
        self.assertGreater(offline, 0)

    def test_slots_flag(self):
        cfg = f.FeedConfig(seed=7, slots=4)
        states = [s for _, s in self.sweep(cfg, days=1, step_min=30)]
        self.assertTrue(all(s["max"] == 4 for s in states))
        self.assertTrue(any(s["available"] == 4 for s in states))

    def test_drift_score_resets_after_each_recal(self):
        for day in range(3):
            for w in f._day_windows(self.cfg, "qpu1", day):
                if w.kind == "maintenance":
                    continue
                at_end = f.qpu_state(self.cfg, "qpu1", w.end)["drift_score"]
                before_end = f.qpu_state(self.cfg, "qpu1", w.end - timedelta(minutes=1))["drift_score"]
                later = f.qpu_state(self.cfg, "qpu1", w.end + timedelta(hours=2))["drift_score"]
                self.assertEqual(at_end, 0.0)
                self.assertLess(at_end, later)
                if day > 0 or w.kind == "quick":  # a previous recal exists to drift from
                    self.assertGreater(before_end, 0.0)

    def test_same_seed_identical_json(self):
        a = [json.dumps(s, sort_keys=True) for _, s in self.sweep(f.FeedConfig(seed=11), days=1, step_min=17)]
        b = [json.dumps(s, sort_keys=True) for _, s in self.sweep(f.FeedConfig(seed=11), days=1, step_min=17)]
        self.assertEqual(a, b)

class ForecastErrorTests(unittest.TestCase):
    """--forecast-err-min N: published next_recal.start = true start + U(-N, +N) min."""

    def states(self, cfg, hours=48, step_min=7):
        t = cfg.epoch
        out = []
        while t < cfg.epoch + timedelta(hours=hours):
            out.append({q: f.qpu_state(cfg, q, t) for q in f.qpu_ids(cfg)})
            t += timedelta(minutes=step_min)
        return out

    def test_n0_matches_default_exactly(self):
        # Byte-identical JSON to a config that never heard of forecast error.
        for seed in (42, 101, 105):
            a = json.dumps(self.states(f.FeedConfig(seed=seed)), sort_keys=True)
            b = json.dumps(self.states(f.FeedConfig(seed=seed, forecast_err_min=0)), sort_keys=True)
            self.assertEqual(a, b)
        log = f.forecast_log(f.FeedConfig(seed=101), f.FeedConfig.epoch, f.FeedConfig.epoch + timedelta(days=2))
        self.assertTrue(log)
        self.assertTrue(all(r["offset_s"] == 0 and r["published_start"] == r["true_start"] for r in log))

    def test_offsets_stay_in_range(self):
        for n in (15, 30, 60):
            cfg = f.FeedConfig(seed=101, forecast_err_min=n)
            log = f.forecast_log(cfg, cfg.epoch, cfg.epoch + timedelta(days=30))
            self.assertGreater(len(log), 100)
            offs = [r["offset_s"] for r in log]
            self.assertTrue(all(-n * 60 <= o <= n * 60 for o in offs), (n, min(offs), max(offs)))
            self.assertLess(min(offs), 0)   # both directions occur
            self.assertGreater(max(offs), 0)

    def test_same_seed_same_offsets(self):
        mk = lambda: f.forecast_log(f.FeedConfig(seed=101, forecast_err_min=30),
                                    f.FeedConfig.epoch, f.FeedConfig.epoch + timedelta(days=3))
        self.assertEqual(mk(), mk())
        other = f.forecast_log(f.FeedConfig(seed=102, forecast_err_min=30),
                               f.FeedConfig.epoch, f.FeedConfig.epoch + timedelta(days=3))
        self.assertNotEqual([r["offset_s"] for r in mk()], [r["offset_s"] for r in other])

    def test_only_published_start_changes(self):
        # The real recal (status, durations, everything else) stays at the true start.
        exact = self.states(f.FeedConfig(seed=101))
        err = self.states(f.FeedConfig(seed=101, forecast_err_min=60))
        changed = 0
        for a, b in zip(exact, err):
            for q in a:
                sa, sb = dict(a[q]), dict(b[q])
                if sa["next_recal"]["start"] != sb["next_recal"]["start"]:
                    changed += 1
                sa["next_recal"] = {k: v for k, v in sa["next_recal"].items() if k != "start"}
                sb["next_recal"] = {k: v for k, v in sb["next_recal"].items() if k != "start"}
                self.assertEqual(sa, sb)
        self.assertGreater(changed, 0)

    def test_served_start_matches_log(self):
        cfg = f.FeedConfig(seed=101, forecast_err_min=30)
        log = f.forecast_log(cfg, cfg.epoch, cfg.epoch + timedelta(days=1))
        for r in log[:6]:
            just_before = f.parse_time(r["true_start"]) - timedelta(seconds=1)
            st = f.qpu_state(cfg, r["qpu"], just_before)
            self.assertEqual(st["next_recal"]["start"], r["published_start"])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = f.FeedConfig(seed=3)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), f.make_handler(cfg, f.SimClock(cfg)))
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return json.load(r)

    def test_list(self):
        body = self.get("/qpus")
        self.assertEqual([q["id"] for q in body["qpus"]], ["qpu0", "qpu1"])

    def test_state_at_is_reproducible(self):
        p = "/qpus/qpu0/state?at=2026-11-03T10:00:00Z"
        self.assertEqual(self.get(p), self.get(p))
        self.assertEqual(self.get(p)["updated_at"], "2026-11-03T10:00:00Z")

    def test_404(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/qpus/nope/state")
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()

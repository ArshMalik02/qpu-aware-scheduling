#!/usr/bin/env python3
"""Simulated QPU calibration feed.

Everything this service returns is SIMULATED. No real hardware is involved.

Serves JSON over HTTP so that Slurm hooks and workflow managers can read
per-QPU state:

    GET /qpus                 -> list of QPU ids plus a state snapshot for each
    GET /qpus/<id>/state      -> state for one QPU
    GET /healthz              -> {"ok": true}

Both /qpus endpoints accept ?at=<ISO-8601 UTC time> to read state at a fixed
moment instead of "now", which makes queries reproducible.

State is a pure function of (seed, qpu id, simulated time). Two feeds started
with the same --seed and --epoch return identical JSON for the same `at`.

Model (see feed/README.md for the sources behind the defaults):
  * Every QPU runs a full recalibration once per simulated day (default 100 min)
    and quick recalibrations every few hours (default 40 min). While a recal
    runs, status is "paused".
  * Rare maintenance windows make a QPU "offline".
  * Each day's post-calibration quality is an AR(1) draw with phi ~0.15, so a
    score from yesterday's calibration says little about today's (lag-1 ACF
    0.10-0.20).
  * Between recals, errors grow and T1 decays with time since the last recal.

Stdlib only. Python 3.9+.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DAY = timedelta(days=1)


@dataclass(frozen=True)
class FeedConfig:
    seed: int = 0
    n_qpus: int = 2
    epoch: datetime = datetime(2026, 11, 1, tzinfo=timezone.utc)
    # Simulated seconds per wall-clock second. 1 = real time.
    speed: float = 1.0
    quick_recal_min: int = 40
    full_recal_min: int = 100
    # A quick recal starts this many hours after the previous recal ends.
    quick_every_h: float = 6.0
    # AR(1) coefficient for day-to-day calibration quality.
    day_phi: float = 0.15
    # Per-day probability of a maintenance window (status "offline").
    p_offline_per_day: float = 0.05
    # Baseline medians across qubits (illustrative, not tied to any device).
    t1_us: float = 250.0
    readout_err: float = 0.012
    gate_err_1q: float = 2.5e-4


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    kind: str  # "quick" | "full" | "maintenance"

    @property
    def duration_min(self) -> int:
        return round((self.end - self.start).total_seconds() / 60)


def _rng(cfg: FeedConfig, *key: object) -> random.Random:
    """Deterministic RNG for a (seed, key...) tuple, stable across runs and platforms."""
    raw = "|".join([str(cfg.seed), *map(str, key)]).encode()
    return random.Random(int.from_bytes(hashlib.sha256(raw).digest()[:8], "big"))


def qpu_ids(cfg: FeedConfig) -> list[str]:
    return [f"qpu{i}" for i in range(cfg.n_qpus)]


def _day_index(cfg: FeedConfig, t: datetime) -> int:
    return math.floor((t - cfg.epoch) / DAY)


def _day_start(cfg: FeedConfig, day: int) -> datetime:
    return cfg.epoch + day * DAY


@lru_cache(maxsize=4096)
def _day_windows(cfg: FeedConfig, qpu: str, day: int) -> tuple[Window, ...]:
    """Recal and maintenance windows that start on a given simulated day."""
    r = _rng(cfg, qpu, "schedule", day)
    d0 = _day_start(cfg, day)
    windows: list[Window] = []

    # Full recal once a day at a per-QPU hour (stable across days), +-15 min jitter.
    full_hour = _rng(cfg, qpu, "full_hour").uniform(1.0, 5.0)
    full_start = d0 + timedelta(hours=full_hour, minutes=r.uniform(-15, 15))
    full_end = full_start + timedelta(minutes=cfg.full_recal_min)
    windows.append(Window(full_start, full_end, "full"))

    # Quick recals every `quick_every_h` after the full one, until the day ends.
    t = full_end
    while True:
        start = t + timedelta(hours=cfg.quick_every_h, minutes=r.uniform(-20, 20))
        if start >= d0 + DAY:
            break
        end = start + timedelta(minutes=cfg.quick_recal_min)
        windows.append(Window(start, end, "quick"))
        t = end

    # Occasional maintenance outage (1-3 h), placed after the full recal.
    if r.random() < cfg.p_offline_per_day:
        start = full_end + timedelta(hours=r.uniform(1, 18))
        windows.append(Window(start, start + timedelta(hours=r.uniform(1, 3)), "maintenance"))

    return tuple(sorted(windows, key=lambda w: w.start))


def _windows_around(cfg: FeedConfig, qpu: str, t: datetime) -> list[Window]:
    day = _day_index(cfg, t)
    out: list[Window] = []
    for d in (day - 1, day, day + 1):
        out.extend(_day_windows(cfg, qpu, d))
    return sorted(out, key=lambda w: w.start)


_BURN_IN_DAYS = 20
_quality_memo: dict[tuple, dict[int, float]] = {}


def _day_quality(cfg: FeedConfig, qpu: str, day: int) -> float:
    """AR(1) z-score of calibration quality on `day` (0 = typical, >0 = worse).

    The series starts from a burn-in before day 0 and is extended forward, so it
    is stationary and any day can be asked for. Values are memoized per series.
    """
    phi = cfg.day_phi
    innov = math.sqrt(1 - phi * phi)
    first = -_BURN_IN_DAYS
    if day < first:  # far past: start a fresh burn-in just for that day
        first = day - _BURN_IN_DAYS
    memo = _quality_memo.setdefault((cfg, qpu, first), {})
    if not memo:
        memo[first] = _rng(cfg, qpu, "q", first).gauss(0, 1)
    d = max(memo)
    while d < day:
        d += 1
        memo[d] = phi * memo[d - 1] + innov * _rng(cfg, qpu, "q", d).gauss(0, 1)
    return memo[day]


def _last_recal_end(windows: list[Window], t: datetime) -> datetime | None:
    """End time of the most recent finished recal (quick or full)."""
    ended = [w for w in windows if w.kind != "maintenance" and w.end <= t]
    return ended[-1].end if ended else None


def qpu_state(cfg: FeedConfig, qpu: str, t: datetime) -> dict:
    if qpu not in qpu_ids(cfg):
        raise KeyError(qpu)
    windows = _windows_around(cfg, qpu, t)

    status, reason = "online", "calibrated (simulated)"
    for w in windows:
        if w.start <= t < w.end:
            if w.kind == "maintenance":
                status, reason = "offline", "maintenance window (simulated)"
            else:
                status, reason = "paused", f"{w.kind} recalibration in progress (simulated)"
            break

    upcoming = next(w for w in windows if w.kind != "maintenance" and w.start > t)

    # Quality: today's AR(1) draw, set by the most recent full recal.
    fulls = [w for w in windows if w.kind == "full" and w.end <= t]
    cal_day = _day_index(cfg, fulls[-1].start) if fulls else _day_index(cfg, t) - 1
    z = _day_quality(cfg, qpu, cal_day)

    # Drift: hours since the most recent finished recal (quick or full).
    last_end = _last_recal_end(windows, t)
    age_h = max(0.0, (t - last_end).total_seconds() / 3600) if last_end else 0.0

    # Small per-tick noise so the numbers move between reads. Tick = 1 sim minute.
    tick = math.floor((t - cfg.epoch).total_seconds() / 60)
    n = _rng(cfg, qpu, "noise", tick)

    quality = math.exp(0.15 * z)  # >1 means worse than baseline
    t1 = cfg.t1_us / quality * math.exp(-0.02 * age_h) * (1 + n.gauss(0, 0.01))
    readout = cfg.readout_err * quality * (1 + 0.03 * age_h) * (1 + n.gauss(0, 0.02))
    gate = cfg.gate_err_1q * quality * (1 + 0.05 * age_h) * (1 + n.gauss(0, 0.02))

    return {
        "id": qpu,
        "status": status,
        "status_reason": reason,
        "next_recal": {
            "start": _iso(upcoming.start),
            "kind": upcoming.kind,
            "duration_min": upcoming.duration_min,
        },
        "metrics": {
            "t1_us": round(t1, 1),
            "readout_err": round(readout, 5),
            "gate_err_1q": round(gate, 7),
        },
        "updated_at": _iso(t),
        "simulated": True,
    }


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


class SimClock:
    """Maps wall-clock time to simulated time: epoch + speed * elapsed."""

    def __init__(self, cfg: FeedConfig):
        self.cfg = cfg
        self.wall_start = datetime.now(timezone.utc)

    def now(self) -> datetime:
        elapsed = datetime.now(timezone.utc) - self.wall_start
        return self.cfg.epoch + elapsed * self.cfg.speed


_STATE_PATH = re.compile(r"^/qpus/([^/]+)/state/?$")


def make_handler(cfg: FeedConfig, clock: SimClock):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SimCalibrationFeed/0.1"

        def log_message(self, fmt, *args):  # quieter default logging
            sys.stderr.write("feed: " + fmt % args + "\n")

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body, indent=2).encode() + b"\n"
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            try:
                t = parse_time(q["at"][0]) if "at" in q else clock.now()
            except ValueError:
                return self._send(400, {"error": "bad 'at' timestamp, use ISO-8601"})

            if url.path in ("/healthz", "/healthz/"):
                return self._send(200, {"ok": True, "simulated": True})
            if url.path in ("/qpus", "/qpus/"):
                return self._send(200, {
                    "qpus": [qpu_state(cfg, i, t) for i in qpu_ids(cfg)],
                    "seed": cfg.seed,
                    "simulated": True,
                })
            m = _STATE_PATH.match(url.path)
            if m:
                try:
                    return self._send(200, qpu_state(cfg, m.group(1), t))
                except KeyError:
                    return self._send(404, {"error": f"unknown qpu {m.group(1)!r}"})
            return self._send(404, {"error": "not found"})

    return Handler


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Simulated QPU calibration feed (all data is fake).")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--qpus", type=int, default=2, help="number of QPUs (default 2, one per Slurm node)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--epoch", default=_iso(FeedConfig.epoch),
                   help="simulated time at startup (ISO-8601, default %(default)s)")
    p.add_argument("--speed", type=float, default=1.0,
                   help="simulated seconds per real second (e.g. 60 = 1 sim hour per minute)")
    p.add_argument("--quick-recal-min", type=int, default=FeedConfig.quick_recal_min)
    p.add_argument("--full-recal-min", type=int, default=FeedConfig.full_recal_min)
    p.add_argument("--day-phi", type=float, default=FeedConfig.day_phi,
                   help="AR(1) coefficient for day-to-day calibration quality")
    a = p.parse_args(argv)

    cfg = FeedConfig(
        seed=a.seed, n_qpus=a.qpus, epoch=parse_time(a.epoch), speed=a.speed,
        quick_recal_min=a.quick_recal_min, full_recal_min=a.full_recal_min, day_phi=a.day_phi,
    )
    server = ThreadingHTTPServer((a.host, a.port), make_handler(cfg, SimClock(cfg)))
    print(f"SIMULATED calibration feed on http://{a.host}:{a.port} "
          f"(seed={cfg.seed}, qpus={cfg.n_qpus}, speed={cfg.speed}x)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

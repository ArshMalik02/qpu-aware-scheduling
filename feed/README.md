# feed/: simulated QPU calibration feed

A small HTTP service that reports per-QPU state (status, the next recalibration, error metrics) so
Slurm hooks and workflow managers can read live QPU state. **All data is simulated.** Every
response carries `"simulated": true`.

Stdlib only (Python 3.9+), no install step.

```bash
python3 feed/calibration_feed.py --seed 42                 # http://127.0.0.1:8787, real time
python3 feed/calibration_feed.py --seed 42 --speed 60      # 1 simulated hour per real minute
curl -s localhost:8787/qpus/qpu0/state
```

## API

| Endpoint | Returns |
|---|---|
| `GET /qpus` | `{"qpus": [<state>, ...], "seed": N, "simulated": true}` |
| `GET /qpus/<id>/state` | one `<state>` (ids are `qpu0`, `qpu1`, ...; 404 otherwise) |
| `GET /healthz` | `{"ok": true}` |

Both `/qpus` endpoints take `?at=2026-11-03T10:00:00Z` to read state at a fixed simulated time.
The example below is `--seed 42`, `GET /qpus/qpu0/state?at=2026-11-03T10:00:00Z`:

```json
{
  "id": "qpu0",
  "status": "online",
  "status_reason": "calibrated (simulated)",
  "next_recal": {
    "start": "2026-11-03T10:36:36Z",
    "kind": "quick",
    "duration_min": 40
  },
  "metrics": {
    "t1_us": 181.2,
    "readout_err": 0.01647,
    "gate_err_1q": 0.0003861
  },
  "updated_at": "2026-11-03T10:00:00Z",
  "simulated": true
}
```

`status` is `online`, `paused` (a recalibration is running) or `offline` (a maintenance window).
Metrics are QPU-level medians across qubits.

## Reproducibility

State is a pure function of `(seed, qpu id, simulated time)`. Simulated time is
`--epoch + speed × (wall time since start)`, with the default epoch `2026-11-01T00:00:00Z`. Two feeds
with the same `--seed` return identical JSON for the same `?at=`. A different seed gives a different
schedule and different metrics.

## Model and defaults

- **Recalibration windows.** Each QPU runs a full recal once a simulated day, at a per-QPU hour
  between 01:00 and 05:00 (±15 min), and quick recals about every 6 h after that. Defaults:
  **quick 40 min, full 100 min** (Mansfield et al., arXiv:2509.12949). Override with
  `--quick-recal-min` and `--full-recal-min`.
- **Day-to-day drift.** Each day's post-calibration quality is an AR(1) z-score with φ = 0.15
  (`--day-phi`): a score from yesterday's calibration says little about today's (lag-1 ACF 0.10–0.20)
  (Deng et al., arXiv:2508.21231). The quality multiplies T1 down and error rates up by `exp(0.15·z)`.
- **Within-day drift.** Since the last finished recal, T1 decays by about 2 %/h, readout error grows
  by about 3 %/h and 1q gate error by about 5 %/h. Each recal resets the drift.
- **Outages.** Each day has a 5 % chance of a 1–3 h maintenance window (`offline`).
- **Noise.** About 1–2 % multiplicative noise per simulated minute, so values move between reads.

Baselines (T1 250 µs, readout 1.2 %, 1q gate 2.5e-4) are illustrative and don't describe any real device.

## References

- Mansfield et al., arXiv:2509.12949: source for the quick (40 min) and full (100 min) recalibration durations.
- Deng et al., arXiv:2508.21231: source for the weak day-to-day correlation of calibration quality (lag-1 ACF 0.10–0.20).

## Tests

```bash
cd feed && python3 -m unittest -v
```

The tests cover seed reproducibility, change over time, the response schema, recal durations and
`paused` status, `next_recal` always in the future, a sample lag-1 ACF of 0.15 ± 0.06 over 3000
simulated days, and the HTTP endpoints.

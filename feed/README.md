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
  "drift_score": 0.1884,
  "healthy": true,
  "busy": false,
  "capacity": {
    "available_slots": 1,
    "max_slots": 1
  },
  "pending_job_count": null,
  "available": 1,
  "max": 1,
  "reason": "calibrated (simulated)",
  "updated_at": "2026-11-03T10:00:00Z",
  "simulated": true
}
```

`status` is `online`, `paused` (a recalibration is running) or `offline` (a maintenance window).
Metrics are QPU-level medians across qubits.

### QRMI / Slurm HRES fields

The feed also returns QRMI's `ResourceStatus` shape, which the Slurm 26.11 HRES plugin reads through
QRMI `status()`. That way a thin QRMI shim can hand the feed's state straight to the plugin later.

| Field | Value in the feed | Source of the name |
|---|---|---|
| `status`, `status_reason` | as above (`online` / `paused` / `offline`) | QRMI `ResourceStatus` |
| `healthy` | `false` only while `offline`; `true` while `paused` (healthy but recalibrating) | QRMI `ResourceStatus` |
| `busy` | always `false`: the feed doesn't track jobs | QRMI `ResourceStatus` |
| `capacity.available_slots` / `capacity.max_slots` | `max_slots` = `--slots` (default 1); `available_slots` = `max_slots` while `online`, else 0 | QRMI `ResourceCapacity` |
| `pending_job_count` | always `null`: the feed doesn't track queues | QRMI `ResourceStatus` |
| `available`, `max`, `reason` | flat copies of `capacity.available_slots`, `capacity.max_slots`, `status_reason` | HRES plugin status-cache keys |
| `drift_score` | see below (*assumed*) | this feed |

Sources:
- QRMI `src/models/resource_status.rs` L26–31 and L72–89 at
  [`qiskit-community/qrmi@8713bd0`](https://github.com/qiskit-community/qrmi/blob/8713bd0/src/models/resource_status.rs#L72-L89)
- `containers/qrmi_hres.lua` at
  [`qrmi-community/slurm-hres-plugins@b24bc7a`](https://github.com/qrmi-community/slurm-hres-plugins/blob/b24bc7a/containers/qrmi_hres.lua)

Mapping notes (from the plugin source; not run against Slurm here):
- `write_status` (L611–620) reads `st.healthy`, `st.busy`, `st.capacity.available_slots` and
  `st.capacity.max_slots`. It writes them to a cache file as `healthy`, `busy`, `available`, `max` and
  `reason`, plus its own `time`. The cached `reason` is built from `status` + `status_reason` (L862),
  so the flat fields here are copies for convenience; the plugin itself needs the nested QRMI shape.
- The admission check (L899–931) holds a job unless `status == "online"`, `healthy ~= false`,
  `busy ~= true`, and the requested slots fit in `available`. It disables the layer (pending reason
  `HRESDisabled`) only while `status ~= "online"` or `healthy == false` (L55–56, L871). So a feed
  `paused` window disables the QPU, and `offline` does too.
- `time` is the plugin's own cache timestamp (`os.time()`). It's checked against `status_max_age`, so
  the feed has no equivalent. The feed's `updated_at` is simulated time, not wall time.

### `drift_score` (*assumed*)

The mean fractional degradation of the three metrics versus their noise-free post-recal values:
`(T1 loss + readout-error growth + 1q-gate-error growth) / 3`, with the *assumed* within-day rates
below. It's 0 when a recalibration ends and rises with time since then. It keeps rising during a
recal window, until the recal finishes. It's a convenience summary for plots and policies, not a
quantity from any paper or device.

## Reproducibility

State is a pure function of `(seed, qpu id, simulated time)`. Simulated time is
`--epoch + speed × (wall time since start)`, with the default epoch `2026-11-01T00:00:00Z`. Two feeds
with the same `--seed` return identical JSON for the same `?at=`. A different seed gives a different
schedule and different metrics.

## Model and defaults

Only the recal durations and the day-to-day correlation come from a source. Everything marked
*assumed* is a placeholder I picked for the simulation; it isn't taken from any paper or device.

- **Recalibration windows.** Defaults: **quick 40 min, full 100 min** (Mansfield et al.,
  arXiv:2509.12949). Override with `--quick-recal-min` and `--full-recal-min`. *Assumed:* one full
  recal per simulated day at a per-QPU hour between 01:00 and 05:00 (±15 min), and a quick recal
  about every 6 h after that.
- **Day-to-day drift.** Each day's post-calibration quality is an AR(1) z-score with φ = 0.15
  (`--day-phi`). A score from yesterday's calibration says little about today's (lag-1 ACF
  0.10–0.20: T1 0.10, readout 0.16, 1q gate 0.20, over 250 days of daily calibration on LRZ's
  20-qubit IQM) (Deng, Schulz & Schulz, arXiv:2508.21231). *Assumed:* quality scales T1 down and
  error rates up by `exp(0.15·z)`.
- **Within-day drift.** *Assumed:* since the last finished recal, T1 decays by about 2 %/h, readout
  error grows by about 3 %/h and 1q gate error by about 5 %/h. Each recal resets the drift.
- **Outages.** *Assumed default, not from a source:* each day has a 5 % chance of a 1–3 h
  maintenance window (`offline`).
- **Noise.** *Assumed:* about 1–2 % multiplicative noise per simulated minute, so values move between reads.
- **Baselines.** *Assumed:* T1 250 µs, readout 1.2 %, 1q gate 2.5e-4. These are illustrative and
  don't describe any real device.

## References

- Mansfield et al., [arXiv:2509.12949](https://arxiv.org/abs/2509.12949): quick (40 min) and full (100 min) recalibration durations.
- Deng, Schulz & Schulz, [arXiv:2508.21231](https://arxiv.org/abs/2508.21231): day-to-day lag-1 autocorrelation of calibration metrics (0.10–0.20).

## 24 h timeline plot

```bash
python3 -m pip install -r feed/requirements-dev.txt   # matplotlib, dev-only
python3 feed/plot_timeline.py                          # seed 42, 24 h, 1-min steps
```

Calls `qpu_state()` directly (no server) for qpu0 and qpu1 and writes
[`results/timeline_seed42.csv`](results/timeline_seed42.csv) and
[`results/timeline_seed42.png`](results/timeline_seed42.png): status bands, readout error and
`drift_score`. **Simulated; within-day drift rates assumed.** With seed 42 the first 24 h have no
`offline` window (outages are a 5 %/day assumption). Re-running gives a byte-identical CSV.

## Tests

```bash
cd feed && python3 -m unittest -v
```

The tests cover the QRMI/HRES fields (`available == 0` unless online, `healthy` false only when
offline, `--slots`, `drift_score` resets at each recal end, identical JSON for the same seed), seed reproducibility, change over time, the response schema, recal durations and
`paused` status, `next_recal` always in the future, a sample lag-1 ACF of 0.15 ± 0.06 over 3000
simulated days, and the HTTP endpoints.

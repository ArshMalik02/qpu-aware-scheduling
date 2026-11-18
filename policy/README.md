# policy/: reactive QPU up/down loop (HRES-like) + baseline runner

Policy 2 of the three-policy baseline: emulate Slurm 26.11 HRES's reactive layer up/down on our
pinned Slurm 26.05.2 cluster. **Everything here is simulated.** QPU state comes from the simulated
feed ([`../feed/`](../feed/)), the QPUs are Slurm GRES counters, and jobs run on Aer (CPU).

## Run

```bash
make baseline-reactive SEED=1        # from the repo root; about 30 min
```

This runs [`run_baseline_reactive.sh`](run_baseline_reactive.sh), which does the following:
1. Starts the cluster and the **feed sidecar** (`docker compose --profile reactive`, service `feed`,
   `http://feed:8787` inside the cluster). It recreates the feed, so its simulated clock starts at the
   epoch.
2. Copies `jobs/`, `policy/` and `workload/` into `slurmctld:/data`.
3. Starts [`reactive.py`](reactive.py) in slurmctld.
4. Runs [`../workload/gen.py`](../workload/gen.py) `--seed $SEED --submit`, which submits jobs at their
   Poisson arrival times.
5. Waits for the queue to drain, then stops the loop. Stopping the loop restores every QPU.
6. Dumps `sacct`, runs [`summarize.py`](summarize.py), and copies everything to
   `results/reactive/seed$SEED/`.

| Env var | Default | Meaning |
|---|---|---|
| `SEED` | 1 | workload seed |
| `FEED_SEED` | 42 | feed seed (recal schedule and metrics) |
| `FEED_SPEED` | 36 | feed seconds per wall second: 30 min ≈ 18 h of feed time, so a quick recal (40 min) lasts ≈ 67 s and a full one (100 min) ≈ 2.8 min |
| `RUN_MIN` | 20 | arrival window, minutes |
| `RATE_PER_MIN` | 1.5 | mean arrivals per minute |
| `DRAIN_MIN` | 15 | max wait for the queue to empty; anything left is cancelled |

## How the loop takes a QPU out

Every 10 s (the `maintenance_cycle` in the HRES plugin example), for each `qpu → node`
(`qpu0 → c1`, `qpu1 → c2`):
- feed `status == "online"` and `healthy != false`: `scontrol update NodeName=<node> Gres=qpu:1`
- otherwise: `scontrol update NodeName=<node> Gres=qpu:0`

That's the HRES layer-disable rule (`status ~= "online" or healthy == false`). Setting the GRES
count to 0 leaves the node up, so CPU-only jobs keep running. On 26.05.2 this works without a
`gres.conf` on our dynamic nodes; see DEVLOG 2026-11-18 for the test. On exit the loop restores every
node to `qpu:1`, because the controller keeps `qpu:0` across slurmd restarts.

## Outputs (`results/reactive/seed<N>/`)

| File | Contents |
|---|---|
| `manifest.json` | the seeded workload (same seed → byte-identical) |
| `submitted.log` | job id per manifest entry, with submit offset |
| `transitions.log` | one JSON line per QPU_OUT / QPU_IN: wall time (UTC), feed time (simulated), node, reason |
| `loop.out` | the same transitions, human-readable |
| `queue.log` | one JSON line per poll: each node's qpu count + the `squeue` snapshot |
| `sacct.txt` | `sacct -X -P` for the run |
| `jobs.csv` | per job: submit, start, end (UTC), queue wait; QPU wait for QPU/hybrid jobs |
| `run_config.json` | seed, feed seed, **feed speed**, run length, arrival rate, poll interval, start time |
| `summary.json` | counts, waits (wall s and feed min), recal overlap, and the three checks below |

## Units

Hold times and waits are **wall-clock seconds**. The feed runs at `FEED_SPEED` simulated seconds per
wall second, so `summarize.py` reports every wait and overlap twice: `wall_s` and
`feed_min = wall_s × feed_speed / 60`. It reads `feed_speed` from `run_config.json`, so a run at a
different speed is converted correctly. The workload's hold times (`MEAN_HOLD_S` in
`../workload/gen.py`: QPU 45 s, hybrid 90 s, classical 60 s, capped at 240 s) are **assumed** and
given in wall seconds. At the default 36× speed a 45 s hold is 27 feed minutes, so changing
`FEED_SPEED` changes how long jobs are relative to the recal windows.

## Recal overlap (the cross-policy metric)

`recal_overlap()` in `summarize.py` counts the QPU and hybrid jobs that were **RUNNING on a node at the
moment its QPU went out** (a `QPU_OUT` in `transitions.log`). For each one it measures the overlap,
`min(job end, next QPU_IN on that node) − QPU_OUT time`, in wall seconds and feed minutes. That's how
long the job kept using a QPU the feed said was recalibrating. A reactive policy can't avoid this,
since it only reacts once the recal has started. It's the number a predictive policy should bring
down.

The metric needs only `jobs.csv` and `transitions.log`, so it's computed the same way for every
policy. For a policy that doesn't take QPUs out (e.g. static), run the loop with
`reactive.py --observe-only`. It polls the feed on the same 10 s cycle and writes the same
`QPU_OUT`/`QPU_IN` events, without calling `scontrol`, so the event times carry the same poll lag.
Overlap times have 1 s resolution (sacct).

## Checks

`summarize.py` prints PASS only if all three hold:
1. the loop took a QPU out and restored it
2. a QPU job was PENDING at a poll where some node's QPU was out
3. a classical job was RUNNING on a node whose QPU was out

## Differences from HRES

- **Pending reason is `Resources`, not `HRESDisabled`.** 26.05.2 has no HRES, so the job just sees no
  free `qpu` GRES.
- **When every QPU is out, new QPU jobs are rejected at submit, not queued.** With `Gres=qpu:0` on
  every node, `sbatch --gres=qpu:1` fails with `Requested node configuration is not available`.
  HRES would accept the job and hold it with `HRESDisabled`. `gen.py` treats that error as a deferral:
  it retries every 5 s without delaying other jobs, logs `submit_delay_s` and `rejected_attempts` in
  `submitted.log`, and `summarize.py` adds the delay to the job's QPU wait. With feed seed 42 this
  happens while the two daily full recals overlap (about 03:50–04:10 feed time).
- **A QPU job already pending when every QPU goes out gets stuck in `BadConstraints`.** Slurm
  re-evaluates it against a cluster with no `qpu` configured, marks it `BadConstraints`, and never
  re-checks it after the QPUs come back: it stays pending until cancelled. HRES has no such state. The
  loop works around it on every poll where at least one QPU is in: it runs `scontrol hold` +
  `scontrol release` on such jobs, which makes them re-validate, and logs a `recheck` event in
  `transitions.log`. `summary.json` lists those jobs as `rechecks_badconstraints`.
- **No admission check on slots, `busy` or cache age.** HRES checks `available_slots` and holds jobs
  when its cached status is older than `status_max_age`. Here, if the feed is unreachable the loop logs
  the error and keeps the node's last state.
- **Up to one poll (10 s) of lag** in each direction, as with HRES's `maintenance_cycle`. At
  `FEED_SPEED=36` that's up to 6 min of feed time.
- **Running jobs aren't touched** when a QPU is taken out; they finish normally. HRES also only
  disables the layer for new allocations.
- **The loop is the only thing that restores a QPU.** If it's killed with SIGKILL, run
  `docker exec slurmctld scontrol update NodeName=c1 Gres=qpu:1` (and the same for c2).

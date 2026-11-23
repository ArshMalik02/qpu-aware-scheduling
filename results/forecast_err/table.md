# Forecast error (simulated)

Predictive policy with the feed's published `next_recal.start` = true start + u·N feed min, u ~ U(−1, 1) seeded per recal (feed `--forecast-err-min N`); the recal itself happens at the true start. Workload seed s, feed seed 100+s, RUN_MIN 30, 36× (1 wall s = 0.6 feed min). Static and reactive don't read `next_recal`, so they're the committed sweep runs, unaffected by N. Drift, the recal schedule and job times are assumed. Few seeds: observations, not results.

- p95 is the value at index int(0.95·n), so for n ≤ 20 it is the maximum (one job).
- **Margins.** The gate starts a QPU job only if start + Slurm limit + one poll ≤ *published* start. So a recal that comes early by `offset` can reach a job only if offset > (limit − actual run) + poll: the cushion row is a worst-case bound (necessary for overlap, not sufficient). The actual-margin row is how far each job's end really was from the true start of the next recal on its node (job times converted to feed time via the run's queue.log; sacct has 1 s = 0.6 feed min resolution).
- **Trade rows** compare QPU-recal minutes (overlap saved) with queue-wait minutes (extra QPU+hybrid wait, summed over jobs matched by name); see results/trade_table.md. The ratio isn't a cost model.

## Seed 1

| Metric | static | reactive | predictive N=0 (sweep) | predictive N=15 | predictive N=30 | predictive N=60 |
|---|---|---|---|---|---|---|
| Forecast error N (feed min) | – | – | 0 | 15 | 30 | 60 |
| Largest early offset in the run (feed min) | – | – | 0 | 4.6 | 9.2 | 18.42 |
| Smallest actual margin: true next-recal start on the job's node − job end (feed min) | – | – | 66.8 | 50.2 | 67.8 | 67.8 |
| Worst-case bound (cushion): Slurm limit − actual run + poll (feed min) | – | – | 30 | 29.4 | 29.4 | 29.4 |
| Recal-overlap jobs | 6 | 2 | 0 | 0 | 0 | 0 |
| Recal overlap (feed min) | 116.4 | 69 | 0 | 0 | 0 | 0 |
| … from recals earlier than published: jobs / feed min | – | – | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| … from recals later than published: jobs / feed min | – | – | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| QPU-only wait p95 (feed min) | 16.2 | 81 | 121.8 | 120.6 | 124.2 | 123.6 |
| Hybrid wait p95 (feed min) | 1.2 | 6 | 156 | 150.6 | 156.6 | 156.6 |
| Classical wait p95 (feed min) | 1.2 | 1.2 | 13.2 | 21 | 21.6 | 22.2 |
| Completion p95 (feed min) | 79.2 | 111.6 | 172.8 | 175.8 | 175.2 | 175.8 |
| Jobs completed / total | 55/55 | 55/55 | 55/55 | 55/55 | 55/55 | 55/55 |
| Gate: jobs kept held at least once | – | – | 7 | 7 | 7 | 7 |
| Gate: releases / re-holds | – | – | 32 / 0 | 32 / 0 | 32 / 0 | 32 / 0 |
| Trade vs reactive: overlap saved (feed min) | – | – | 69 | 69 | 69 | 69 |
| Trade vs reactive: extra QPU+hybrid wait (feed min) | – | – | 922.1 | 906 | 931.8 | 933 |
| Trade vs reactive: ratio extra/saved | – | – | 13.4 | 13.1 | 13.5 | 13.5 |
| Trade vs static: overlap saved (feed min) | – | – | 116.4 | 116.4 | 116.4 | 116.4 |
| Trade vs static: extra QPU+hybrid wait (feed min) | – | – | 1016.4 | 1000.2 | 1026 | 1027.2 |
| Trade vs static: ratio extra/saved | – | – | 8.7 | 8.6 | 8.8 | 8.8 |

## Recals in each forecast-error run

Offset = published − true start (feed min); > 0 means the recal came earlier than published.

| Run | QPU | Kind | True start | Published start | Offset | Overlap jobs | Overlap (feed min) |
|---|---|---|---|---|---|---|---|
| N=15 seed 1 | qpu0 | full | 04:00:19 | 04:01:09 | +0.83 | 0 | 0 |
| N=15 seed 1 | qpu1 | full | 04:40:17 | 04:39:52 | -0.42 | 0 | 0 |
| N=15 seed 1 | qpu0 | quick | 11:50:22 | 11:47:29 | -2.88 | 0 | 0 |
| N=15 seed 1 | qpu1 | quick | 12:39:22 | 12:43:58 | +4.6 | 0 | 0 |
| N=30 seed 1 | qpu0 | full | 04:00:19 | 04:01:59 | +1.67 | 0 | 0 |
| N=30 seed 1 | qpu1 | full | 04:40:17 | 04:39:26 | -0.85 | 0 | 0 |
| N=30 seed 1 | qpu0 | quick | 11:50:22 | 11:44:36 | -5.77 | 0 | 0 |
| N=30 seed 1 | qpu1 | quick | 12:39:22 | 12:48:34 | +9.2 | 0 | 0 |
| N=60 seed 1 | qpu0 | full | 04:00:19 | 04:03:39 | +3.33 | 0 | 0 |
| N=60 seed 1 | qpu1 | full | 04:40:17 | 04:38:35 | -1.7 | 0 | 0 |
| N=60 seed 1 | qpu0 | quick | 11:50:22 | 11:38:50 | -11.53 | 0 | 0 |
| N=60 seed 1 | qpu1 | quick | 12:39:22 | 12:57:47 | +18.42 | 0 | 0 |

Job manifests byte-identical to static seed<s> for every run above: **yes**.

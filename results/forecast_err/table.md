# Forecast error (simulated)

Predictive policy with the feed's published `next_recal.start` = true start + u·N feed min, u ~ U(−1, 1) seeded per recal (feed `--forecast-err-min N`); the recal itself happens at the true start. Workload seed s, feed seed 100+s, RUN_MIN 30, 36× (1 wall s = 0.6 feed min). Static and reactive don't read `next_recal`, so they're the committed sweep runs, unaffected by N. Drift, the recal schedule and job times are assumed. Few seeds: observations, not results.

- p95 is the value at index int(0.95·n), so for n ≤ 20 it is the maximum (one job).
- **Margins.** The gate starts a QPU job only if start + Slurm limit + one poll ≤ *published* start. So a recal that comes early by `offset` can reach a job only if offset > (limit − actual run) + poll: the cushion row is a worst-case bound (necessary for overlap, not sufficient). The actual-margin row is how far each job's end really was from the true start of the next recal on its node (job times converted to feed time via the run's queue.log; sacct has 1 s = 0.6 feed min resolution).
- **Trade rows** compare QPU-recal minutes (overlap saved) with queue-wait minutes (extra QPU+hybrid wait, summed over jobs matched by name); see results/trade_table.md. The ratio isn't a cost model.

## Seed 1

| Metric | static | reactive | predictive N=0 (sweep) | predictive N=0 (control) | predictive N=15 | predictive N=30 | predictive N=60 | predictive N=120 |
|---|---|---|---|---|---|---|---|---|
| Forecast error N (feed min) | – | – | 0 | 0 | 15 | 30 | 60 | 120 |
| Largest early offset in the run (feed min) | – | – | 0 | 0 | 4.6 | 9.2 | 18.42 | 36.83 |
| Smallest actual margin: true next-recal start on the job's node − job end (feed min) | – | – | 66.8 | 64.3 | 50.2 | 67.8 | 67.8 | 9.3 |
| Worst-case bound (cushion): Slurm limit − actual run + poll (feed min) | – | – | 30 | 30 | 29.4 | 29.4 | 29.4 | 29.4 |
| Recal-overlap jobs | 6 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| Recal overlap (feed min) | 116.4 | 69 | 0 | 0 | 0 | 0 | 0 | 0 |
| … from recals earlier than published: jobs / feed min | – | – | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| … from recals later than published: jobs / feed min | – | – | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| QPU-only wait p95 (feed min) | 16.2 | 81 | 121.8 | 121.2 | 120.6 | 124.2 | 123.6 | 123.6 |
| Hybrid wait p95 (feed min) | 1.2 | 6 | 156 | 150.6 | 150.6 | 156.6 | 156.6 | 156.6 |
| Classical wait p95 (feed min) | 1.2 | 1.2 | 13.2 | 20.4 | 21 | 21.6 | 22.2 | 14.4 |
| Completion p95 (feed min) | 79.2 | 111.6 | 172.8 | 174.6 | 175.8 | 175.2 | 175.8 | 162 |
| Jobs completed / total | 55/55 | 55/55 | 55/55 | 55/55 | 55/55 | 55/55 | 55/55 | 55/55 |
| Gate: jobs kept held at least once | – | – | 7 | 7 | 7 | 7 | 7 | 6 |
| Gate: releases / re-holds | – | – | 32 / 0 | 32 / 0 | 32 / 0 | 32 / 0 | 32 / 0 | 32 / 0 |
| Trade vs reactive: overlap saved (feed min) | – | – | 69 | 69 | 69 | 69 | 69 | 69 |
| Trade vs reactive: extra QPU+hybrid wait (feed min) | – | – | 922.1 | 896.4 | 906 | 931.8 | 933 | 822.6 |
| Trade vs reactive: ratio extra/saved | – | – | 13.4 | 13 | 13.1 | 13.5 | 13.5 | 11.9 |
| Trade vs static: overlap saved (feed min) | – | – | 116.4 | 116.4 | 116.4 | 116.4 | 116.4 | 116.4 |
| Trade vs static: extra QPU+hybrid wait (feed min) | – | – | 1016.4 | 990.6 | 1000.2 | 1026 | 1027.2 | 916.8 |
| Trade vs static: ratio extra/saved | – | – | 8.7 | 8.5 | 8.6 | 8.8 | 8.8 | 7.9 |

## N = 120, per seed

Each seed's predictive N = 120 run, with that seed's reactive and predictive (N = 0) sweep runs for reference.

### Seed 1

| Metric | reactive | predictive N=0 (sweep) | predictive N=120 |
|---|---|---|---|
| Forecast error N (feed min) | – | 0 | 120 |
| Largest early offset in the run (feed min) | – | 0 | 36.83 |
| Smallest actual margin: true next-recal start on the job's node − job end (feed min) | – | 66.8 | 9.3 |
| Worst-case bound (cushion): Slurm limit − actual run + poll (feed min) | – | 30 | 29.4 |
| Recal-overlap jobs | 2 | 0 | 0 |
| Recal overlap (feed min) | 69 | 0 | 0 |
| … from recals earlier than published: jobs / feed min | – | 0 / 0 | 0 / 0 |
| … from recals later than published: jobs / feed min | – | 0 / 0 | 0 / 0 |
| QPU-only wait p95 (feed min) | 81 | 121.8 | 123.6 |
| Hybrid wait p95 (feed min) | 6 | 156 | 156.6 |
| Classical wait p95 (feed min) | 1.2 | 13.2 | 14.4 |
| Completion p95 (feed min) | 111.6 | 172.8 | 162 |
| Jobs completed / total | 55/55 | 55/55 | 55/55 |
| Gate: jobs kept held at least once | – | 7 | 6 |
| Gate: releases / re-holds | – | 32 / 0 | 32 / 0 |
| Trade vs reactive: overlap saved (feed min) | – | 69 | 69 |
| Trade vs reactive: extra QPU+hybrid wait (feed min) | – | 922.1 | 822.6 |
| Trade vs reactive: ratio extra/saved | – | 13.4 | 11.9 |
| Trade vs static: overlap saved (feed min) | – | 116.4 | 116.4 |
| Trade vs static: extra QPU+hybrid wait (feed min) | – | 1016.4 | 916.8 |
| Trade vs static: ratio extra/saved | – | 8.7 | 7.9 |

### Seed 2

| Metric | reactive | predictive N=0 (sweep) | predictive N=120 |
|---|---|---|---|
| Forecast error N (feed min) | – | 0 | 120 |
| Largest early offset in the run (feed min) | – | 0 | 94.33 |
| Smallest actual margin: true next-recal start on the job's node − job end (feed min) | – | 60.3 | 3.6 |
| Worst-case bound (cushion): Slurm limit − actual run + poll (feed min) | – | 31.8 | 31.8 |
| Recal-overlap jobs | 3 | 0 | 0 |
| Recal overlap (feed min) | 67.2 | 0 | 0 |
| … from recals earlier than published: jobs / feed min | – | 0 / 0 | 0 / 0 |
| … from recals later than published: jobs / feed min | – | 0 / 0 | 0 / 0 |
| QPU-only wait p95 (feed min) | 31.2 | 77.4 | 156 |
| Hybrid wait p95 (feed min) | 41.4 | 67.2 | 159 |
| Classical wait p95 (feed min) | 14.4 | 10.8 | 12 |
| Completion p95 (feed min) | 118.8 | 118.2 | 191.4 |
| Jobs completed / total | 38/38 | 38/38 | 38/38 |
| Gate: jobs kept held at least once | – | 2 | 4 |
| Gate: releases / re-holds | – | 20 / 1 | 20 / 1 |
| Trade vs reactive: overlap saved (feed min) | – | 67.2 | 67.2 |
| Trade vs reactive: extra QPU+hybrid wait (feed min) | – | 259.8 | 801 |
| Trade vs reactive: ratio extra/saved | – | 3.9 | 11.9 |
| Trade vs static: overlap saved (feed min) | – | 91.8 | 91.8 |
| Trade vs static: extra QPU+hybrid wait (feed min) | – | 259.2 | 800.4 |
| Trade vs static: ratio extra/saved | – | 2.8 | 8.7 |

### Seed 3

| Metric | reactive | predictive N=0 (sweep) | predictive N=120 |
|---|---|---|---|
| Forecast error N (feed min) | – | 0 | 120 |
| Largest early offset in the run (feed min) | – | 0 | 118.63 |
| Smallest actual margin: true next-recal start on the job's node − job end (feed min) | – | 55.1 | -36 |
| Worst-case bound (cushion): Slurm limit − actual run + poll (feed min) | – | 31.8 | 32.4 |
| Recal-overlap jobs | 2 | 0 | 2 |
| Recal overlap (feed min) | 65.4 | 0 | 37.8 |
| … from recals earlier than published: jobs / feed min | – | 0 / 0 | 2 / 37.8 |
| … from recals later than published: jobs / feed min | – | 0 / 0 | 0 / 0 |
| QPU-only wait p95 (feed min) | 44.4 | 141.6 | 133.2 |
| Hybrid wait p95 (feed min) | 46.2 | 161.4 | 117 |
| Classical wait p95 (feed min) | 12 | 10.8 | 16.2 |
| Completion p95 (feed min) | 144.6 | 223.8 | 178.2 |
| Jobs completed / total | 43/43 | 43/43 | 43/43 |
| Gate: jobs kept held at least once | – | 6 | 3 |
| Gate: releases / re-holds | – | 25 / 1 | 24 / 0 |
| Trade vs reactive: overlap saved (feed min) | – | 65.4 | 27.6 |
| Trade vs reactive: extra QPU+hybrid wait (feed min) | – | 672.6 | 772.8 |
| Trade vs reactive: ratio extra/saved | – | 10.3 | 28 |
| Trade vs static: overlap saved (feed min) | – | 185.4 | 147.6 |
| Trade vs static: extra QPU+hybrid wait (feed min) | – | 816 | 916.2 |
| Trade vs static: ratio extra/saved | – | 4.4 | 6.2 |

### Seed 4

| Metric | reactive | predictive N=0 (sweep) | predictive N=120 |
|---|---|---|---|
| Forecast error N (feed min) | – | 0 | 120 |
| Largest early offset in the run (feed min) | – | 0 | 111.37 |
| Smallest actual margin: true next-recal start on the job's node − job end (feed min) | – | 50.1 | 5.8 |
| Worst-case bound (cushion): Slurm limit − actual run + poll (feed min) | – | 30 | 30.6 |
| Recal-overlap jobs | 2 | 0 | 0 |
| Recal overlap (feed min) | 21 | 0 | 0 |
| … from recals earlier than published: jobs / feed min | – | 0 / 0 | 0 / 0 |
| … from recals later than published: jobs / feed min | – | 0 / 0 | 0 / 0 |
| QPU-only wait p95 (feed min) | 3 | 33 | 15.6 |
| Hybrid wait p95 (feed min) | 17.4 | 23.4 | 23.4 |
| Classical wait p95 (feed min) | 1.8 | 1.8 | 1.8 |
| Completion p95 (feed min) | 117 | 118.8 | 118.8 |
| Jobs completed / total | 39/39 | 39/39 | 39/39 |
| Gate: jobs kept held at least once | – | 2 | 2 |
| Gate: releases / re-holds | – | 27 / 0 | 27 / 0 |
| Trade vs reactive: overlap saved (feed min) | – | 21 | 21 |
| Trade vs reactive: extra QPU+hybrid wait (feed min) | – | 128.4 | 91.2 |
| Trade vs reactive: ratio extra/saved | – | 6.1 | 4.3 |
| Trade vs static: overlap saved (feed min) | – | 75 | 75 |
| Trade vs static: extra QPU+hybrid wait (feed min) | – | 147 | 109.8 |
| Trade vs static: ratio extra/saved | – | 2 | 1.5 |

### Seed 5

| Metric | reactive | predictive N=0 (sweep) | predictive N=120 |
|---|---|---|---|
| Forecast error N (feed min) | – | 0 | 120 |
| Largest early offset in the run (feed min) | – | 0 | 75.3 |
| Smallest actual margin: true next-recal start on the job's node − job end (feed min) | – | 45.6 | 13.2 |
| Worst-case bound (cushion): Slurm limit − actual run + poll (feed min) | – | 31.2 | 31.2 |
| Recal-overlap jobs | 1 | 0 | 0 |
| Recal overlap (feed min) | 96.6 | 0 | 0 |
| … from recals earlier than published: jobs / feed min | – | 0 / 0 | 0 / 0 |
| … from recals later than published: jobs / feed min | – | 0 / 0 | 0 / 0 |
| QPU-only wait p95 (feed min) | 30 | 175.8 | 70.2 |
| Hybrid wait p95 (feed min) | 1.2 | 130.8 | 130.2 |
| Classical wait p95 (feed min) | 0.6 | 1.8 | 5.4 |
| Completion p95 (feed min) | 82.2 | 178.8 | 81.6 |
| Jobs completed / total | 42/42 | 42/42 | 42/42 |
| Gate: jobs kept held at least once | – | 6 | 2 |
| Gate: releases / re-holds | – | 21 / 0 | 21 / 0 |
| Trade vs reactive: overlap saved (feed min) | – | 96.6 | 96.6 |
| Trade vs reactive: extra QPU+hybrid wait (feed min) | – | 775.8 | 246.6 |
| Trade vs reactive: ratio extra/saved | – | 8 | 2.6 |
| Trade vs static: overlap saved (feed min) | – | 127.8 | 127.8 |
| Trade vs static: extra QPU+hybrid wait (feed min) | – | 804.6 | 275.4 |
| Trade vs static: ratio extra/saved | – | 6.3 | 2.2 |

## Recals in each forecast-error run

Offset = published − true start (feed min); > 0 means the recal came earlier than published.

| Run | QPU | Kind | True start | Published start | Offset | Overlap jobs | Overlap (feed min) |
|---|---|---|---|---|---|---|---|
| N=0 seed 1 | qpu0 | full | 04:00:19 | 04:00:19 | +0 | 0 | 0 |
| N=0 seed 1 | qpu1 | full | 04:40:17 | 04:40:17 | +0 | 0 | 0 |
| N=0 seed 1 | qpu0 | quick | 11:50:22 | 11:50:22 | +0 | 0 | 0 |
| N=0 seed 1 | qpu1 | quick | 12:39:22 | 12:39:22 | +0 | 0 | 0 |
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
| N=120 seed 1 | qpu0 | full | 04:00:19 | 04:07:00 | +6.68 | 0 | 0 |
| N=120 seed 1 | qpu1 | full | 04:40:17 | 04:36:53 | -3.4 | 0 | 0 |
| N=120 seed 1 | qpu0 | quick | 11:50:22 | 11:27:18 | -23.07 | 0 | 0 |
| N=120 seed 1 | qpu1 | quick | 12:39:22 | 13:16:12 | +36.83 | 0 | 0 |
| N=120 seed 2 | qpu1 | full | 02:38:06 | 01:47:53 | -50.22 | 0 | 0 |
| N=120 seed 2 | qpu0 | full | 04:25:47 | 02:40:43 | -105.07 | 0 | 0 |
| N=120 seed 2 | qpu1 | quick | 10:02:02 | 11:36:22 | +94.33 | 0 | 0 |
| N=120 seed 2 | qpu0 | quick | 12:12:58 | 13:16:42 | +63.73 | 0 | 0 |
| N=120 seed 2 | qpu1 | quick | 16:33:57 | 16:45:36 | +11.65 | 0 | 0 |
| N=120 seed 2 | qpu0 | quick | 18:39:37 | 19:26:42 | +47.08 | 0 | 0 |
| N=120 seed 3 | qpu0 | full | 03:01:21 | 03:06:52 | +5.52 | 0 | 0 |
| N=120 seed 3 | qpu1 | full | 04:45:37 | 06:27:51 | +102.23 | 1 | 7.2 |
| N=120 seed 3 | qpu0 | quick | 10:51:45 | 09:32:37 | -79.13 | 0 | 0 |
| N=120 seed 3 | qpu1 | quick | 12:14:08 | 12:41:39 | +27.52 | 0 | 0 |
| N=120 seed 3 | qpu0 | quick | 17:14:56 | 16:46:17 | -28.65 | 0 | 0 |
| N=120 seed 3 | qpu1 | quick | 19:06:38 | 21:05:16 | +118.63 | 1 | 30.6 |
| N=120 seed 4 | qpu0 | full | 01:24:33 | 23:41:04 | -103.48 | 0 | 0 |
| N=120 seed 4 | qpu1 | full | 02:47:16 | 02:42:06 | -5.17 | 0 | 0 |
| N=120 seed 4 | qpu0 | quick | 09:05:19 | 09:05:37 | +0.3 | 0 | 0 |
| N=120 seed 4 | qpu1 | quick | 10:43:15 | 12:33:02 | +109.78 | 0 | 0 |
| N=120 seed 4 | qpu0 | quick | 15:44:50 | 17:36:12 | +111.37 | 0 | 0 |
| N=120 seed 4 | qpu1 | quick | 17:33:48 | 17:21:27 | -12.35 | 0 | 0 |
| N=120 seed 5 | qpu1 | full | 02:02:06 | 01:18:36 | -43.5 | 0 | 0 |
| N=120 seed 5 | qpu0 | full | 03:28:54 | 04:12:07 | +43.22 | 0 | 0 |
| N=120 seed 5 | qpu1 | quick | 10:00:59 | 08:47:28 | -73.52 | 0 | 0 |
| N=120 seed 5 | qpu0 | quick | 11:12:50 | 11:38:35 | +25.75 | 0 | 0 |
| N=120 seed 5 | qpu1 | quick | 16:57:39 | 18:12:57 | +75.3 | 0 | 0 |
| N=120 seed 5 | qpu0 | quick | 17:57:01 | 18:37:51 | +40.83 | 0 | 0 |

Job manifests byte-identical to static seed<s> for every run above: **yes**.

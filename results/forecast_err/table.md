# Forecast error, seed 1 (simulated, one seed)

Predictive policy with the feed's published `next_recal.start` = true start + u·N feed min, u ~ U(−1, 1) seeded per recal (feed `--forecast-err-min N`); the recal itself happens at the true start. Workload seed 1, feed seed 101, RUN_MIN 30, 36× (1 wall s = 0.6 feed min). Static and reactive don't read `next_recal`, so they're the committed sweep runs, unaffected by N. Drift, the recal schedule and job times are assumed. One seed: observations, not results.

Job manifest byte-identical to static seed 1 in every column: **yes** (md5 bcdc250d4797…).

p95 is the value at index int(0.95·n), so for n ≤ 20 it is the maximum (one job).

Gate cushion: the gate starts a QPU job only if start + Slurm limit + one poll ≤ published start, so a recal that comes early by `offset` can only reach a job if offset > (limit − actual run time) + poll. The row gives the smallest such cushion over the run's QPU/hybrid jobs.

| Metric | static | reactive | predictive N=0 | predictive N=15 | predictive N=30 | predictive N=60 |
|---|---|---|---|---|---|---|
| Forecast error N (feed min) | – | – | 0 | 15 | 30 | 60 |
| Largest early offset in the run (feed min) | – | – | 0 | 4.6 | 9.2 | 18.42 |
| Smallest gate cushion: limit − actual run + poll (feed min) | – | – | 30 | 29.4 | 29.4 | 29.4 |
| Recal-overlap jobs | 6 | 2 | 0 | 0 | 0 | 0 |
| Recal overlap (feed min) | 116.4 | 69 | 0 | 0 | 0 | 0 |
| … from recals earlier than published: jobs | – | – | 0 | 0 | 0 | 0 |
| … from recals earlier than published: feed min | – | – | 0 | 0 | 0 | 0 |
| … from recals later than published: jobs | – | – | 0 | 0 | 0 | 0 |
| … from recals later than published: feed min | – | – | 0 | 0 | 0 | 0 |
| QPU-only wait p95 (feed min) | 16.2 | 81 | 121.8 | 120.6 | 124.2 | 123.6 |
| Hybrid wait p95 (feed min) | 1.2 | 6 | 156 | 150.6 | 156.6 | 156.6 |
| Classical wait p95 (feed min) | 1.2 | 1.2 | 13.2 | 21 | 21.6 | 22.2 |
| Completion p95 (feed min) | 79.2 | 111.6 | 172.8 | 175.8 | 175.2 | 175.8 |
| Jobs completed / total | 55/55 | 55/55 | 55/55 | 55/55 | 55/55 | 55/55 |
| Gate: jobs kept held at least once | – | – | 7 | 7 | 7 | 7 |
| Gate: releases | – | – | 32 | 32 | 32 | 32 |
| Gate: re-holds | – | – | 0 | 0 | 0 | 0 |
| Gate: ExcNodeList updates | – | – | 7 | 6 | 7 | 7 |

**Recals in each run** (offset = published − true start, feed min; > 0 means the recal came earlier than published):

| Run | QPU | Kind | True start | Published start | Offset | Overlap jobs | Overlap (feed min) |
|---|---|---|---|---|---|---|---|
| predictive N=15 | qpu0 | full | 04:00:19 | 04:01:09 | +0.83 | 0 | 0 |
| predictive N=15 | qpu1 | full | 04:40:17 | 04:39:52 | -0.42 | 0 | 0 |
| predictive N=15 | qpu0 | quick | 11:50:22 | 11:47:29 | -2.88 | 0 | 0 |
| predictive N=15 | qpu1 | quick | 12:39:22 | 12:43:58 | +4.6 | 0 | 0 |
| predictive N=30 | qpu0 | full | 04:00:19 | 04:01:59 | +1.67 | 0 | 0 |
| predictive N=30 | qpu1 | full | 04:40:17 | 04:39:26 | -0.85 | 0 | 0 |
| predictive N=30 | qpu0 | quick | 11:50:22 | 11:44:36 | -5.77 | 0 | 0 |
| predictive N=30 | qpu1 | quick | 12:39:22 | 12:48:34 | +9.2 | 0 | 0 |
| predictive N=60 | qpu0 | full | 04:00:19 | 04:03:39 | +3.33 | 0 | 0 |
| predictive N=60 | qpu1 | full | 04:40:17 | 04:38:35 | -1.7 | 0 | 0 |
| predictive N=60 | qpu0 | quick | 11:50:22 | 11:38:50 | -11.53 | 0 | 0 |
| predictive N=60 | qpu1 | quick | 12:39:22 | 12:57:47 | +18.42 | 0 | 0 |

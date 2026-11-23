# Trade: recal overlap saved vs extra queue wait (simulated)

Predictive vs a baseline, per seed (workload seed N, feed seed 100+N, same job manifest). All values in feed minutes (36×: 1 wall s = 0.6 feed min). Drift, the recal schedule and job times are assumed.

- **Overlap saved** = baseline recal overlap − predictive recal overlap.
- **Extra QPU+hybrid wait** = sum over QPU and hybrid jobs, matched by job name, of (predictive − baseline) QPU wait.
- **Ratio** = extra / saved.

Compares two different quantities: QPU-recal minutes (time QPU/hybrid jobs ran on a QPU the feed said was recalibrating) and queue-wait minutes (time QPU/hybrid jobs waited before starting). The ratio only puts them side by side; it isn't a cost model.

## Baseline: reactive

| Seed | Overlap saved | Extra QPU+hybrid wait | Ratio extra/saved |
|---|---|---|---|
| 1 | 69 | 922.1 | 13.4 |
| 2 | 67.2 | 259.8 | 3.9 |
| 3 | 65.4 | 672.6 | 10.3 |
| 4 | 21 | 128.4 | 6.1 |
| 5 | 96.6 | 775.8 | 8 |

Ratio range across seeds: 3.9–13.4.

## Baseline: static

| Seed | Overlap saved | Extra QPU+hybrid wait | Ratio extra/saved |
|---|---|---|---|
| 1 | 116.4 | 1016.4 | 8.7 |
| 2 | 91.8 | 259.2 | 2.8 |
| 3 | 185.4 | 816 | 4.4 |
| 4 | 75 | 147 | 2 |
| 5 | 127.8 | 804.6 | 6.3 |

Ratio range across seeds: 2–8.7.

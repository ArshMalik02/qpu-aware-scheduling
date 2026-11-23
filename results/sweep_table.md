# Sweep results (simulated)

Median across seeds, with [min–max] across seeds. Drift, recal schedule and job times are assumed; all numbers are from the Docker cluster with a simulated feed, not hardware.

| Metric | static (seeds 1) | reactive (seeds 1) | predictive (seeds 1) |
|---|---|---|---|
| Recal-overlap jobs | 2 | 2 | 0 |
| Recal overlap (feed min) | 69 | 69 | 0 |
| QPU-only wait median (feed min) | 0 | 0 | 2.4 |
| QPU-only wait p95 (feed min) | 16.2 | 81 | 121.8 |
| Hybrid wait p95 (feed min) | 1.2 | 6 | 156 |
| Classical wait p95 (feed min) | 1.2 | 1.2 | 13.2 |
| Completion median (feed min) | 22.2 | 22.2 | 32.4 |
| Completion p95 (feed min) | 79.2 | 111.6 | 172.8 |
| Jobs completed | 55 | 55 | 55 |
| Submit rejections | 0 | 0 | 0 |
| Gate: jobs held | 0 | 0 | 7 |

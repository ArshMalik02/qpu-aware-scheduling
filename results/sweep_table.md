# Sweep results (simulated)

Median across seeds, with [min–max] across seeds. Drift, recal schedule and job times are assumed; all numbers are from the Docker cluster with a simulated feed, not hardware.

p95 is the value at index int(0.95·n) of the sorted waits, so for n ≤ 20 it is the maximum: one job. Every QPU job is submitted held under predictive; the gate rows count jobs it kept held (no QPU fitted) at least once.

| Metric | static (seeds 1,2,3,4,5) | reactive (seeds 1,2,3,4,5) | predictive (seeds 1,2,3,4,5) |
|---|---|---|---|
| Recal-overlap jobs | 6 [3–8] | 2 [1–3] | 0 [0–0] |
| Recal overlap (feed min) | 116.4 [75–185.4] | 67.2 [21–96.6] | 0 [0–0] |
| QPU-only wait median (feed min) | 0 [0–0.3] | 0 [0–10.2] | 2.4 [1.5–30.6] |
| QPU-only wait p95 (feed min) | 24.6 [1.8–32.4] | 31.2 [3–81] | 121.8 [33–175.8] |
| Hybrid wait p95 (feed min) | 9 [1.2–46.2] | 17.4 [1.2–46.2] | 130.8 [23.4–161.4] |
| Classical wait p95 (feed min) | 1.8 [0.6–12] | 1.8 [0.6–14.4] | 10.8 [1.8–13.2] |
| Completion median (feed min) | 23.1 [15–39.6] | 24 [16.2–44.4] | 32.4 [20.4–48.6] |
| Completion p95 (feed min) | 117 [79.2–144.6] | 117 [82.2–144.6] | 172.8 [118.2–223.8] |
| Jobs completed | 42 [38–55] | 42 [38–55] | 42 [38–55] |
| Submit rejections | 0 [0–0] | 0 [0–1] | 0 [0–0] |
| Gate: jobs kept held at least once | 0 [0–0] | 0 [0–0] | 6 [2–7] |
| Gate: re-holds | 0 [0–0] | 0 [0–0] | 0 [0–1] |

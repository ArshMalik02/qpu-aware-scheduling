# Archived: PR #4 reactive seed-1 runs (simulated)

These runs used the old fixed `--time=00:10:00` for every job, before per-job time limits
(`limit_s = ceil(hold_s * 1.5) + 30`). Kept for the DEVLOG 2026-11-18 entry; don't compare
them with the three-policy sweep in `results/<policy>/seed<N>/`, which reruns static and
reactive with the new limits.

# Week 0: Slurm overcommit test

Run on a local slurm-docker-cluster. Results are in [DEVLOG.md](../../DEVLOG.md).

## Files

- `burn.sbatch`: CPU burn job. Hashes 12 GB of zeros with sha256sum; requests 1 CPU and 500 MB.
- `hello.sbatch`: Smoke test. Prints the batch host, sleeps 20 s, then runs `srun hostname`.
- `run_overcommit.sh`: Submits arrays of 1, 4 and 8 `burn.sbatch` jobs, waits for each, and prints the job count and average ElapsedRaw from sacct.

## Running the test

From this directory, with the cluster up:

```bash
docker cp burn.sbatch slurmctld:/data/
docker cp run_overcommit.sh slurmctld:/data/
docker exec -it slurmctld bash
```

Then inside the container:

```bash
cd /data
bash run_overcommit.sh
```

# cluster/: local Slurm cluster with a simulated `qpu` GRES

A pinned copy of [giovtorres/slurm-docker-cluster](https://github.com/giovtorres/slurm-docker-cluster)
with a count-only `qpu` generic resource on every CPU worker. **The QPU is simulated:** it's just a counter
in Slurm and has no quantum hardware or simulator behind it.

| | |
|---|---|
| Upstream | `giovtorres/slurm-docker-cluster` tag **3.0.2**, commit `9001503b42e7277c7ff45c08aeecdb6427474d68` (2026-10-18) |
| Slurm | **26.05.2** by default, pinned to match Week 0 (upstream 3.0.2 defaults to 26.05.5). Override with `SLURM_VERSION` in `.env`. |
| Nodes | `c1`, `c2` (dynamic registration, `slurmd -Z`), each `Gres=qpu:1` → 2 QPUs total |
| Upstream docs | [README.upstream.md](README.upstream.md), license in [LICENSE](LICENSE) (MIT) |

## One command

```bash
cd cluster
docker compose up -d --build     # first build compiles Slurm, ~10-20 min
./verify_qpu.sh                  # sinfo shows qpu:1 on c1,c2; 3-job contention test
```

`make up` / `make down` / `make clean` from upstream also work.

## Changes from upstream

Applied from [`experiments/week0/gres-qpu.patch`](../experiments/week0/gres-qpu.patch), plus packaging fixes:

1. `config/26.05/slurm.conf` (and `25.11`): `GresTypes=gpu` → `GresTypes=gpu,qpu`.
2. `docker-entrypoint.sh`: CPU workers register with `--conf "Feature=cpu Gres=qpu:1"`.
   No `NodeName=` lines and no `gres.conf` are needed for a count-only GRES.
3. **Stale-record fix** (DEVLOG 2026-10-26). `/etc/slurm` is a named volume, and Docker only seeds a
   named volume from the image when it first creates it, so after a rebuild the old slurm.conf
   wins. The Dockerfile now also keeps the baked config in `/etc/slurm.baked/`, and the slurmctld
   entrypoint copies it into `/etc/slurm` at startup. Workers wait for a healthy slurmctld, so they
   always register against the current `GresTypes`.
4. `docker-compose.yml`: fixed project name `qpu` (`name: ${COMPOSE_PROJECT_NAME:-qpu}`), and the
   workers' `COMPOSE_PROJECT_NAME` defaults to `qpu` too. The entrypoint names nodes `c<N>` by
   resolving `${COMPOSE_PROJECT_NAME}-cpu-worker-N`. Without a matching name it falls back to the
   container ID. The new name also keeps these volumes separate from an older checkout's `slurm_*` volumes.

If nodes still show `qpu:0`:

```bash
docker exec slurmctld scontrol delete nodename=c1,c2
docker compose restart cpu-worker
```

## spank-plugins demo (Step 1-alt, not adopted)

`qiskit-community/spank-plugins` `demo/qrmi/slurm-docker-cluster/` targets slurm-docker-cluster
**0.9.0** (Slurm 25.05.3, static `NodeName` lines, six containers including a login node). Its
`file.patch` rewrites that older layout, so it won't apply to this 3.0.2 copy. See DEVLOG 2026-11-02.

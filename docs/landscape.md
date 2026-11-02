# Landscape: where is QPU state static?

*Week 1 reading, Oct 29 – Nov 2, 2026. Systems claims only. Every row cites the file and commit, or the
document, it comes from. "Re-checked" means the source was opened again on 2026-11-02 at the commit or
URL shown and says what the row says.*

## 1. Today's model

Slurm schedules a QPU like any other countable resource: a GRES, a license, or a SPANK option. A GRES
is configured per node by count (plus optional device files and cores), and jobs only get it if they
ask for it at submit time with `--gres` ([Slurm GRES docs](https://slurm.schedmd.com/gres.html)). The page
lists count, device files and cores as GRES attributes, and nothing about device health. In this repo's Week 0 test, three
`--gres=qpu:1` jobs on two simulated QPUs gave 2 RUNNING and 1 PENDING (Resources), with 3 idle CPUs on
each node. The counter was the only thing blocking the third job ([DEVLOG 2026-10-26](../DEVLOG.md),
simulated). Nothing in that counter says whether the device is calibrated, drifting or about to pause.

## 2. Where QPU state enters scheduling

| System | How Slurm sees the QPU | Live state that reaches the scheduler | Source | Status |
|---|---|---|---|---|
| **QRMI SPANK plugin** | `--qpu=names` SPANK option ([L139](https://github.com/qiskit-community/spank-plugins/blob/3455388/plugins/spank_qrmi/spank_qrmi.c#L139)), resolved through `qrmi_config.json` ([L337](https://github.com/qiskit-community/spank-plugins/blob/3455388/plugins/spank_qrmi/spank_qrmi.c#L337)) | **None.** Runs in `slurm_spank_init_post_opt` on the remote side, i.e. slurmstepd after nodes are allocated ([L236-247](https://github.com/qiskit-community/spank-plugins/blob/3455388/plugins/spank_qrmi/spank_qrmi.c#L236-L247)). It calls only `is_accessible` and `acquire` ([L841-874](https://github.com/qiskit-community/spank-plugins/blob/3455388/plugins/spank_qrmi/spank_qrmi.c#L841-L874)); on failure the error is deferred to `task_init`, which cancels the job ([L57-62](https://github.com/qiskit-community/spank-plugins/blob/3455388/plugins/spank_qrmi/spank_qrmi.c#L57-L62)). It never calls `status()` or `target()`. | spank-plugins@3455388 `plugins/spank_qrmi/spank_qrmi.c` | Re-checked |
| **QRMI license poller** (example repo, not part of the plugin) | Slurm dynamic license per backend | **Ready/busy flag, admission only.** Idle only if QRMI `status()` is `online` and not `busy` or unhealthy; offline and paused count as busy, so jobs pend ([main.py L294-327](https://github.com/qrmi-community/slurm_poller_daemon_example/blob/31803a4/poller/slurm_license_poller/main.py#L294-L327)). QRMI defines paused as "online but not accepting jobs due to a maintenance-type event (e.g. calibration)" ([qrmi `resource_status.rs` L47-48](https://github.com/qiskit-community/qrmi/blob/15a9b21/src/models/resource_status.rs#L47-L48)). Polls every `poll_interval` s, a required key with no default ([L140](https://github.com/qrmi-community/slurm_poller_daemon_example/blob/31803a4/poller/slurm_license_poller/main.py#L140)). | slurm_poller_daemon_example@31803a4 | Re-checked |
| **QDMI via MQT Core** | One Slurm license per QDMI device ID | **Up/down, admission only.** "An availability monitor keeps new jobs pending while a device is unavailable." The monitor maintains a `qdmi-unavailable-ID` reservation. | [MQT Core QDMI Slurm docs](https://mqt.readthedocs.io/projects/core/en/latest/qdmi/slurm.html) | Docs re-checked; **not run** |
| **Pasqal (CUDA-Q + QRMI)** | Same `--qpu` path as the plugin | **None.** Cloud `is_accessible` only checks that the device isn't retired (`availability == "ACTIVE"`), because "jobs can still be submitted and queued" while it's down. | [qrmi@8284bb2 `src/pasqal/cloud.rs` L255-267](https://github.com/qiskit-community/qrmi/blob/8284bb2/src/pasqal/cloud.rs#L255-L267) | Re-checked |
| **LRZ / MQSS** | GRES `qpu` (`Name=qpu Type=general Count=1`) + prolog/epilog and SPANK modules | **None in the public code.** No file in the repo mentions calibration. The paper describes two-level scheduling: Slurm allocates the GRES, and MQSS's QRM&CI does JIT compilation and dispatch ([arXiv:2608.14827](https://arxiv.org/abs/2608.14827)). Recalibration is automated, and the HPC center controls when it runs ([Mansfield et al., arXiv:2509.12949](https://arxiv.org/abs/2509.12949), §3). | [MQSS-SLURM-Plugins-Suite@eade4c7](https://github.com/Munich-Quantum-Software-Stack/MQSS-SLURM-Plugins-Suite/blob/eade4c7/deployment/on_beast_wolpy_testbed/slurm_conf_files/gres.conf) | Re-checked; the paper's "quantum availability" metric is **unverified** in code |
| **qBraid OS, Qblox / NVQLink** | — | — | No public Slurm docs found | **Unverified** |

Simulator note: `qrmi-community/simulated_quantum_resource`, which QRMI's e2e CI uses
([qrmi `.github/workflows/e2e.yml` L137](https://github.com/qiskit-community/qrmi/blob/15a9b21/.github/workflows/e2e.yml#L137)),
returns `"status": "online"` and `"locked": False` as literals
([`qsa_sim/qsa_service.py` L309-310 @5f7b75d](https://github.com/qrmi-community/simulated_quantum_resource/blob/5f7b75d/qsa_sim/qsa_service.py#L309-L310)).
Against the stock simulator, `status()` is always online.

## 3. The gap

I haven't found published work where calibration or recalibration state reaches Slurm placement or backfill as anything more than an up/busy flag (no drift, no recal windows, no prediction).

Closest measured work: Rocco et al., QCE25 ([https://arxiv.org/abs/2508.04217](https://arxiv.org/abs/2508.04217)) — real Slurm, emulated 2-min QPU jobs, up to ~54% fewer classical node-seconds vs static allocation with malleability; releases nodes per job phase, not QPU state.
(Re-checked in the PDF: SLURM 23.02.7, a two-minute artificial delay that emulates the QPU, and "≈ 54% reduction in node-seconds compared to the baseline".)

## 4. The three signals this project targets

- **Calibration drift.** A score from yesterday's calibration says little about today's (lag-1 ACF 0.10–0.20: T1 0.10, readout 0.16, 1q gate 0.20, over 250 days of daily calibration on LRZ's 20-qubit IQM). Source: Deng, Schulz & Schulz, [arXiv:2508.21231](https://arxiv.org/abs/2508.21231), Table I. The values are means across qubits with wide spreads (±0.10, ±0.23, ±0.25), and the readout and 1q values are *fidelities*. The text also notes that daily-mean T1 shows "moderate multi-day persistence" (Fig. 6a), so per-qubit and device-mean memory differ.
- **Availability and recalibration windows.** Quick recal takes about 40 min and full recal about 100 min, and the HPC center controls when they run. Source: Mansfield et al., [arXiv:2509.12949](https://arxiv.org/abs/2509.12949), §3.
- **Hybrid-job idle.** IBM chose architecture 2 (the hybrid model), in which a running quantum-classical job "blocks off all resources required for the job's entire duration". IBM presents this as a benefit; the cost is classical nodes held while the QPU part runs or waits. Source: [IBM Quantum blog, QCSC software](https://www.ibm.com/quantum/blog/qcsc-software).

The simulated feed in [`feed/`](../feed/) models the first two (simulated data).

## 5. Open questions

- Is a recal window a Slurm reservation, or is it handled outside the scheduler? (QDMI's monitor uses a `qdmi-unavailable-ID` reservation for "unavailable", but nothing I read covers *planned* recal windows.)
- Does in-loop calibration state (MQSS QRM&CI, vendor stacks) ever get reported up to Slurm?
- Which signal would a facility want measured first?

## Sources

| Source | Version read |
|---|---|
| [qiskit-community/spank-plugins](https://github.com/qiskit-community/spank-plugins) | `3455388` |
| [qiskit-community/qrmi](https://github.com/qiskit-community/qrmi) | `15a9b21` (models, CI); `8284bb2` (Pasqal) |
| [qrmi-community/slurm_poller_daemon_example](https://github.com/qrmi-community/slurm_poller_daemon_example) | `31803a4` |
| [qrmi-community/simulated_quantum_resource](https://github.com/qrmi-community/simulated_quantum_resource) | `5f7b75d` |
| [Munich-Quantum-Software-Stack/MQSS-SLURM-Plugins-Suite](https://github.com/Munich-Quantum-Software-Stack/MQSS-SLURM-Plugins-Suite) | `eade4c7` |
| [MQT Core QDMI Slurm docs](https://mqt.readthedocs.io/projects/core/en/latest/qdmi/slurm.html) | `latest`, read 2026-11-02 |
| Farooqi et al., *Enabling Hybrid HPCQC Workflows with a Heterogeneous Software Stack*, [arXiv:2608.14827](https://arxiv.org/abs/2608.14827) | v1, abstract |
| Bacher et al., *Quantum resources in resource management systems*, [arXiv:2506.10052](https://arxiv.org/abs/2506.10052) | v2, abstract |
| Rocco et al., *Dynamic Solutions for Hybrid Quantum-HPC Resource Allocation*, [arXiv:2508.04217](https://arxiv.org/abs/2508.04217) | v1, full text |
| Deng, Schulz & Schulz, *Qubit Health Analytics and Clustering for HPC-Integrated Quantum Processors*, [arXiv:2508.21231](https://arxiv.org/abs/2508.21231) | v1, full text |
| Mansfield et al., *First Practical Experiences Integrating Quantum Computers with HPC Resources*, [arXiv:2509.12949](https://arxiv.org/abs/2509.12949) | v1, full text |
| [IBM Quantum blog: QCSC software](https://www.ibm.com/quantum/blog/qcsc-software) | read 2026-11-02 |
| [Slurm GRES docs](https://slurm.schedmd.com/gres.html) | read 2026-11-02 |

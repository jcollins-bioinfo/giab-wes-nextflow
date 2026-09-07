# M3 readiness dossier

Observed 2026-09-07. Author: John Patrick Collins.

The expected M2.1 baseline was verified at
`d9a9d700ab5603b693468d22b4fd66ed96348881`, including merged PR #18 and
[successful required CI](https://github.com/jcollins-bioinfo/giab-wes-nextflow/actions/runs/34091284958).
The audit subsequently reproduced package/path, cache-recovery, publication and
launcher provenance defects beyond that CI coverage. M3 continuation therefore
requires the M2.1.1 recovery checks and green required CI, not just the older run.

| Boundary | Observed status | Continuation requirement |
|---|---|---|
| M2 package | Sole implementation remains `src/giab_wes_nextflow`; wrappers delegate | Recovery unit/negative and clean-wheel tests pass |
| Python 3.12/3.13 | Baseline CI passed; recovery tests recorded separately | Repair required CI green |
| Nextflow/nf-test/Docker | Baseline synthetic foundation CI passed | Repair runtime-version contract and existing tests green |
| Launcher | Exact origin, clean SHA, isolated interpreter and installed-file identity checks implemented | Local/CI negative tests; owner-run evidence remains separate |
| Source mirror | Historical record plus 10 current size/name entries observed | Rehash bytes via explicit legacy-cache hydration |
| Reference preparation | No immutable preparation record established | Owner runtime must execute/validate preparation separately |
| Capture Gate B | Unresolved exact assay target identity | Block canonical domains, target-aware acceptance and publication |
| M3 synthetic development | Permitted after M2 recovery continuation gate | Never call intermediate/synthetic BAM canonical HG001 output |
| BQSR | Accepted ADR 0003 requires OQ retention and caller-specific effective qualities; known-sites absent from M2 manifest | Pin and validate distinct known-sites before BQSR, or seek a new material scientific decision |
| DeepVariant/ARM64 | Not executed; local macOS has no verified supporting container runtime | M4 requires an actually supporting x86_64 smoke/integration environment |

Current machine state and exact next action are authoritative in
[project-state.json](orchestration/project-state.json). The historical decision
`M3_IMPLEMENTATION_READY_WITH_EXPLICIT_GATES` was valid only with its stated
no-package-defect condition; reproduced defects require repair before reuse.

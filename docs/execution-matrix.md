# Tested versus configured execution matrix

| Environment/capability | Recorded evidence | Scope and limitation |
|---|---|---|
| Linux CI Python 3.12/3.13 | M2.1.1 required CI 34094504379 at 22d01b202e15bb098e9d42d0ad4a98606e78c2c2 | 104-test recovery suites; no real genomic execution |
| Linux CI Nextflow 26.04.6/nf-test/Docker | Same recovery run | Synthetic foundation; no alignment/caller result implied |
| macOS ARM64 Python 3.12/3.13 | Local recovery suites and clean-wheel suite | 104 tests per run; Python 3.12 interpreter BLAKE2 warnings recorded |
| macOS ARM64 Java/Nextflow/nf-test | [version commands](orchestration/evidence/local-framework-versions.json) | Framework version commands executed; biological containers not tested |
| M3 tool containers, Linux/x86_64 Docker 28.0.4 | [Verified CI 34103737524](orchestration/evidence/m3-verified.json), head c3426d3 and identical tested merge tree | Real invented-input preprocessing: 22 completed then 22 cached tasks; independent BAM/index/OQ/ownership checks; no HG001 or callers |
| Historical source mirror | [control/metadata audit](orchestration/evidence/source-cache-metadata.json) | x86_64 producer field is not independent Colab or container qualification |
| macOS ARM64 M4 Python and framework | [Local verification](orchestration/evidence/m4-local-verification.json) | 227 Python tests on3.12 and isolated3.13 wheel;14 nf-tests; selection/resume stubs only |
| DeepVariant CPU Linux/amd64 | [Pinned M4 image/model declarations](orchestration/evidence/m4-container-declaration.json) | Actual pinned WES inference/native calls, independent/both equivalence and resume passed main CI34237377774; synthetic SNVs only |
| DeepVariant GPU, native Apple Silicon, emulation | No immutable execution record | Not executed or qualified |
| Colab capability | Owner-supplied 2026-09-08 report, 43-file code inventory consistency checked | Linux/x86_64, 8 CPUs, 50.99 GiB, no Docker; not remote attestation or canonical runtime qualification |
| Colab real pipeline, Apptainer, SLURM, AWS, Seqera/Wave | None | Configured/planned only; paid infrastructure requires owner authorization |
| M5 BCFtools 1.24 / RTG 3.13, Linux/x86_64 Docker | [Retained CI34270789172](orchestration/evidence/m5-verified-34270789172.json), identical-tree main CI34272289311 | Frozen SNP/indel representations, exact counts, isolation, independent/both/resume and typed raw-trace parsing; no HG001 or canonical cost |
| Explorer/site deployment | Existing website baseline build metadata only | No GIAB Explorer or project result page deployed |

A supporting platform declared by an image manifest does not establish execution.
Canonical HG001, target-aware coverage and accuracy/cost claims require their own
immutable run evidence and scientific gates. Local syntax/stub tests cannot be
relabeled Docker or x86_64 execution.

## Canonical continuation environments

| Environment | Implemented interface | Observed status |
|---|---|---|
| Local metadata/unit tooling, Python3.12/3.13 | Canonical assets, runtime guards, checkpoints, collector and model tests | Invented inputs and negative tests; no Mac genomic execution |
| Nextflow26.04.6 | Five-stage canonical composition and zero-task closed gate | Local stubs and configuration parsing; no canonical result |
| Colab High-RAM Linux/x86_64 | Exact-SHA notebook, full reference/classic BWA, independent BQSR, runtime qualification and analysis | Configured; actual representative callers/index/reference/HG001 acceptance pending |
| Apptainer/Singularity | Existing OCI pins through sole task mounts | Configured until representative callers execute |
| Docker | Dedicated canonical runtime backend | Configured for canonical work; historical M3–M5 synthetic Docker evidence remains separate |
| udocker/PRoot | Pinned no-daemon fallback with reduced isolation | Configured until actual Colab execution; technical P1/P2 qualification fallback only |
| SLURM / AWS Batch / Seqera-Wave | Parsed profiles and unschedulable placeholders/cost guards | Configured only; no cloud job or spend |
| Dash canonical view | Trusted manifest, model validation, safe JSON/TSV, unavailable state | Consumer/callback tests; canonical data and public deployment pending |
| Website showcase | Separate branch, pipeline-SHA/evidence binding | Canonical results unavailable until accepted bundle import |

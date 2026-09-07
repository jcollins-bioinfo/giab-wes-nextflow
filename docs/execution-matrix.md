# Tested versus configured execution matrix

| Environment/capability | Recorded evidence | Scope and limitation |
|---|---|---|
| Linux CI Python 3.12/3.13 | M2.1.1 required CI 34094504379 at 22d01b202e15bb098e9d42d0ad4a98606e78c2c2 | 104-test recovery suites; no real genomic execution |
| Linux CI Nextflow 26.04.6/nf-test/Docker | Same recovery run | Synthetic foundation; no alignment/caller result implied |
| macOS ARM64 Python 3.12/3.13 | Local recovery suites and clean-wheel suite | 104 tests per run; Python3.12 interpreter BLAKE2 warnings recorded |
| macOS ARM64 Java/Nextflow/nf-test | [version commands](orchestration/evidence/local-framework-versions.json) | Framework version commands executed; biological containers not tested |
| M3 tool containers | [immutable declarations](../config/m3-tools.json) | Registry digests/platform metadata verified; actual synthetic execution evidence pending |
| Historical source mirror | [control/metadata audit](orchestration/evidence/source-cache-metadata.json) | x86_64 producer field is not independent Colab or container qualification |
| DeepVariant CPU/GPU | Existing immutable M4 contracts | Not executed; no Apple Silicon/native/emulation claim |
| Colab real pipeline, Apptainer, SLURM, AWS, Seqera/Wave | None | Configured/planned only; paid infrastructure requires owner authorization |
| Explorer/site deployment | Existing website baseline build metadata only | No GIAB Explorer or project result page deployed |

A supporting platform declared by an image manifest does not establish execution.
Canonical HG001, target-aware coverage and accuracy/cost claims require their own
immutable run evidence and scientific gates. Local syntax/stub tests cannot be
relabeled Docker or x86_64 execution.

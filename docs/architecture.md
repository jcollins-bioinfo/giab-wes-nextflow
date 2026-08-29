# Architecture

M1 uses strict-compatible DSL2 without the legacy DSL flag, preview typing, DSL1, or parser v1. `main.nf` performs help/parameter validation, samplesheet conversion, one `GIAB_WES` call, and completion logging. Orchestration is in `workflows/`; reusable validation in `subworkflows/local/`; project processes in `modules/local/`; future nf-core modules will be locally vendored and recorded in `modules.json`, never remote.

Stable workflow outputs with `copy` semantics are the sole future publication mechanism; process `publishDir` is forbidden. Topic channels will collect future software versions. Dependency is canonical Nextflow run → immutable machine-readable evidence → strict tested Python model → Dash. Dash may only filter/render precomputed values.

The shared physical BAM/BAI identity feeds both callers. GATK sees recalibrated QUAL; DeepVariant uses OQ (`use_original_quality_scores=true`): caller-appropriate views, not identical effective evidence. Truth cannot enter caller inputs/environments. ARM64 orchestration is configured-compatible; DeepVariant images are linux/amd64 and CPU requires AVX, so Apple Silicon/ARM execution is not tested.

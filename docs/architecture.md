# Architecture

M1 uses strict-compatible DSL2 without the legacy DSL flag, preview typing, DSL1, or parser v1. `main.nf` performs help/parameter validation, samplesheet conversion, one `GIAB_WES` call, and completion logging. Orchestration is in `workflows/`; reusable validation in `subworkflows/local/`; project processes in `modules/local/`; future nf-core modules will be locally vendored and recorded in `modules.json`, never remote.

Stable workflow outputs with `copy` semantics publish workflow files; process `publishDir` is forbidden. Topic channels will collect future software versions. Dependency is canonical Nextflow run → immutable machine-readable evidence → strict tested Python model → Dash. Dash may only filter/render precomputed values.

The shared physical BAM/BAI identity feeds both callers. GATK sees recalibrated QUAL; DeepVariant uses OQ (`use_original_quality_scores=true`): caller-appropriate views, not identical effective evidence. Truth cannot enter caller inputs/environments. ARM64 orchestration is configured-compatible; DeepVariant images are linux/amd64 and CPU requires AVX, so Apple Silicon/ARM execution is not tested.


M3 adds an explicit synthetic shared-preprocessing subworkflow and retains the
foundation mode. Source preflight cryptographically binds invented inputs before
biological tasks. Each lane is validated/aligned/sorted separately; both lanes
merge once by sample/library before retained duplicate marking and BQSR. One
BAM/BAI channel is emitted for future caller abstraction. Neither truth, capture
intervals nor benchmark parameters enter the M3 tool contract.

The package owns fixture construction, streaming FASTQ validation, SAM/quality
acceptance, metric parsing, result schemas and evidence publication. The final
collector validates all mandatory transformations and tool versions and writes
six immutable JSON artifacts. Raw Nextflow trace/report/timeline/DAG and tool
reports remain execution evidence, with explicit missingness where the JSON
collector has no observed cost measurement. The integration driver owns exact
checkout/runtime qualification and real/resume acceptance. A separate guarded
publisher revalidates small synthetic evidence and writes completion markers
last; it does not publish work directories or confer canonical readiness.

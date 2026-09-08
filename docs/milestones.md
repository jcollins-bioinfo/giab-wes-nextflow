# Milestones

1. **M1 — foundation and architecture.**
2. **M2 — data and provenance.**
3. **M3 — FASTQ QC, alignment, preprocessing, and alignment/coverage QC.**
4. **M4 — independently selectable GATK HaplotypeCaller and DeepVariant WES callers.**
5. **M5 — common GIAB benchmarking and explicit caller accuracy-versus-resource comparison.**
6. **M6 — operational hardening, Seqera observability, and cloud/HPC profiles.**
7. **M7 — comprehensive QA, canonical execution, reproducibility audit, and v1.0 release.**
8. **M8 — Plotly Dash Pipeline Evidence Explorer and deployment.**
9. **M9 — website research showcase and final claim/reproducibility audit.**

The dependency is `Nextflow canonical run → immutable machine-readable results → tested Python analysis/result model → Dash`. Scientific calculations never exist only in Dash callbacks. ONT and somatic workflows are outside v1.

Current boundary (2026-09-08): M3 and M4 are synthetically verified on recorded
Linux/x86_64 Docker CI. M5 common normalization, authoritative benchmarking and
resource infrastructure are implemented with local checks; actual engine and
Nextflow resume qualification remain distinct. The approved early Explorer is a
synthetic prototype and does not advance canonical M7/M8 completion.

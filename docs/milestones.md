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

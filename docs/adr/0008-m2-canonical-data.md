# ADR 0008: M2 canonical data, target gate, and domains

**Status:** accepted for Gate A (2026-09-03); Gate B blocked

## Decision

Canonical input is only the original GIAB-hosted HG001 `NIST7035_TAAGGCGA_L001` pair. The reference is GIAB `GCA_000001405.15_GRCh38_no_alt_analysis_set`; truth is HG001 GRCh38 v4.2.1. Expected source identities live in the strict M2 manifest and acquisition observations live only in immutable private run evidence.

Capture design is **unresolved**: NCBI establishes Nextera/WXS/hybrid-selection lineage, but not the exact Expanded Exome revision or target-file bytes. No coverage- or truth-derived inference is permitted. Gate B and canonical domain publication remain blocked until primary evidence establishes the exact design.

When unblocked, legacy BED coordinates are converted explicitly from 0-based half-open BED to 1-based closed Picard interval-list coordinates, lifted with Picard 3.1.1 `LiftOverIntervalList` and `MIN_LIFTOVER_PCT=0.95` using the classic checksummed UCSC hg19-to-hg38 chain, audited, validated against the destination dictionary, then sorted and merged. `T_design` is unpadded; `R_call` is its 100 bp padded, bounds-clipped primary-contig form; `R_eval_full` is GIAB HC intersect design; `R_eval_holdout` is full intersect chr20-22. Evaluation never depends on coverage or calls.

Private active downloads and computation use ephemeral storage. Only rehashed, allowlisted immutable artifacts may be copied into the existing Drive workspace through `_incomplete`; the append-only registry precedes `COMPLETED.json`, which is written last.

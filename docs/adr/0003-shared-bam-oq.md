# ADR 0003: shared bam oq

**Status:** accepted for v1 foundation (2026-08-29)

## Decision

One BWA-MEM2→sort→markdup-retained→BQSR→ApplyBQSR BAM retains OQ. Both callers get identical BAM/BAI hashes; GATK uses recalibrated QUAL and DeepVariant OQ. These are caller-appropriate, not identical effective quality evidence.

## Reversal conditions
Failed OQ completeness or failed DeepVariant equivalence testing blocks comparison and requires a preregistered new preprocessing ADR.

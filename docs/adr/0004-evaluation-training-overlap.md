# ADR 0004: evaluation training overlap

**Status:** accepted for v1 foundation (2026-08-29)

## Decision

Keep design/calling/full/chr20–22 domains distinct and depth-independent. Full is descriptive/in-sample; chr20–22 is limited same-individual locus-held-out sensitivity.

## Reversal conditions
Training provenance changes or target audit fails; freeze a replacement domain before examining truth metrics.

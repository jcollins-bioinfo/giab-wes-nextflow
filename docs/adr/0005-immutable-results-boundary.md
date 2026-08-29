# ADR 0005: immutable results boundary

**Status:** accepted for v1 foundation (2026-08-29)

## Decision

Dependency is Nextflow canonical run → immutable evidence bundle → strict tested Python result model → Dash. Dash renders only; it never parses scientific files or derives metrics/resources/lineage.

## Reversal conditions
A schema migration requires versioned readers and immutable originals. A failed deployment experiment may select a reverse-proxy fallback, documented in a new ADR; deployment is not M1-tested.

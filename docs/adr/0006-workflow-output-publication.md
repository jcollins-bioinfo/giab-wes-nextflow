# ADR 0006: workflow output publication

**Status:** accepted for v1 foundation (2026-08-29)

## Decision

Stable workflow outputs with explicit copy semantics are the sole publication mechanism; no process publishDir duplicates.

## Reversal conditions
Demonstrated workflow-output incompatibility requires one atomic publication change across code, schemas, tests, and docs—never parallel publication paths.

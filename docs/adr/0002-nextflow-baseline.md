# ADR 0002: nextflow baseline

**Status:** accepted for v1 foundation (2026-08-29)

## Decision

Use strict-compatible DSL2, stable 26.04.6 and floor 25.10.4 with parser v2 at the floor, Java 17+, no preview typing/DSL1. nf-schema is parameter source of truth; modules are vendored.

## Reversal conditions
Change pins only for an authoritative security/compatibility release with both matrix paths rerun. Failure of DeepVariant on qualified x86/AVX blocks biological milestones, not silent architecture substitution.

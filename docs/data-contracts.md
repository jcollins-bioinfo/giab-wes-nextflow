# Data and evidence contracts

The lane-aware samplesheet and checks are described in README. Normalized items are `[meta, [R1,R2]]`, with stable metadata keys. Draft 2020-12 schemas reject unknown fields where practical, negative values, malformed hashes and paths; semantic validation rejects inconsistent formulas and cyclic lineage. Every missing resource measurement is `{missing_reason}`, never zero by implication. Comparisons require shared BAM, truth, evaluation-domain, and configuration identities.

The evidence manifest declares relative path, SHA-256, bytes, media type, schema ID/version, and semantic role. Schemas distinguish truth-side TP/query-side TP, FP/FN/UNK, metrics/evaluated bases; resource wall/observed and allocated CPU/RSS/I/O/disk/task/retry/cache scope/aggregation; distinct domains, lineage, and error overlap policy. All M1 evidence fixtures say `synthetic: true`; no biological metric is computed.

## M3 executable and distribution identities

The M3 tool-lock contract and provenance schema use version 2.0.0. Each tool
retains its distribution `version` (provenance `declared_version`), an explicit
`expected_reported_version`, actual `observed_version_text`, immutable image
digest, and explanatory source evidence. Fresh collection and restored bundles
must agree with the installed package's complete tool inventory. Recomputing
payload/file hashes cannot authorize a different version or image.

This distinction is required by an observed upstream mismatch: the pinned
BWA-MEM2 2.3 distribution executes a binary reporting `2.2.1`. The exact 2.3
release archive defines the same fallback. The report expectation is exactly
`2.2.1` for this pin; `2.3`, extra standalone version reports, missing fields and
different images are rejected. A distribution label cannot substitute for an
executable observation. Evidence is retained in
[CI attempt 4](orchestration/evidence/m3-ci-attempt-4.json).

The new provenance fields are required, so the incompatible schema has a new
major version. Historical 1.0.0 provenance is preserved as historical bytes and
rejected by current acceptance; there is no implicit migration. Other M3 evidence
schemas remain at 1.0.0 and retain their own validation and hash rules. Neither
schema version establishes successful synthetic or canonical execution by itself.

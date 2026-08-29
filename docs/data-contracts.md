# Data and evidence contracts

The lane-aware samplesheet and checks are described in README. Normalized items are `[meta, [R1,R2]]`, with stable metadata keys. Draft 2020-12 schemas reject unknown fields where practical, negative values, malformed hashes and paths; semantic validation rejects inconsistent formulas and cyclic lineage. Every missing resource measurement is `{missing_reason}`, never zero by implication. Comparisons require shared BAM, truth, evaluation-domain, and configuration identities.

The evidence manifest declares relative path, SHA-256, bytes, media type, schema ID/version, and semantic role. Schemas distinguish truth-side TP/query-side TP, FP/FN/UNK, metrics/evaluated bases; resource wall/observed and allocated CPU/RSS/I/O/disk/task/retry/cache scope/aggregation; distinct domains, lineage, and error overlap policy. All M1 evidence fixtures say `synthetic: true`; no biological metric is computed.

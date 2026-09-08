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

## M4 input, native-caller and bundle contracts

`m4-inputs`, `m4-caller`, `m4-bundle` and `m4-publication` schemas use version
1.0.0. Their package validators enforce closed inventories and scientific
relationships in addition to JSON structure. All current M4 records explicitly
say synthetic, noncanonical, and pre-normalization. The selected fixture identity
is exact and independently bound to its authored manifest; the original M3
recipe remains unchanged.

The input envelope binds the accepted M3 manifest, BAM/BAI, FASTA/FAI/dictionary,
and a complete invented-reference calling region by hash and size. The copied
input directory contains only these six data files and aggregate metadata.
Reference/calling-region bytes are identical between callers. Recalibrated QUAL
for GATK and OQ for DeepVariant are separately declared quality policies.

Each native-caller envelope binds run/repository/package identity, sample,
input payload and physical file identities, the exact installed image/version
and parameters, observed command, resources and native output hashes. GATK
uses direct VCF with null gVCF/model fields. DeepVariant requires WES model
inventory and nonzero candidate/inference evidence. Native representation is
retained; M5 will own common normalization and accuracy/cost results. Null
logical task IDs in host-collected JSON are not actual task IDs: preserved
Nextflow trace rows bind actual process/task/cache identities independently.

The bundle selects GATK, DeepVariant or both in canonical order and revalidates
every selected record and shared input lineage. Publication accepts only the
selected three or four JSON files, hashes destination bytes, writes an immutable
registry and exposes the completion marker last. Recovery revalidates those
records; it does not recover Nextflow work or qualify a new caller execution.

## M5 common contracts

`m5-normalization`, `m5-benchmark` and `m5-resources` are versioned package-owned
schemas, mirrored byte-for-byte in the root schema directory. ADR 0014 defines
symmetric fully-called diploid nonreference inclusion, native FILTER retention,
strict REF validation, decomposition and RTG representation matching. Raw
queries remain unchanged; normalization and engine outputs retain SHA-256 lineage.
Truth-side and query-side TP counts are distinct. Precision uses query TP; recall
uses truth TP; undefined denominators remain null with reasons. The fixed BED
intersection supplies evaluated bases independently of query/depth/callability.
Resource observations retain attempts, cached versus executed costs and units;
summed task durations and maxima of individual task memory peaks are not whole-run
wall time or concurrent run peak memory. See [resource semantics](m5-resources.md).

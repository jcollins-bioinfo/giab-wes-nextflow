# M2.1.1 recovery and gated M3–M9 execution

Author: John Patrick Collins. Observed baseline: 2026-09-07.

## Baseline and dependency

Pipeline main is `d9a9d700ab5603b693468d22b4fd66ed96348881`, version
`0.2.0-dev.3`, including merged PR #18. CI run 34091284958 and its required
job passed. Website main is `d933578401d305bc8504e584f2aaa5f484085e18`;
the current Cloudflare build check passed, with no Actions workflows or runs.
Neither repository had open PRs at inspection. No applicable AGENTS.md was found.

The baseline audit reproduced defects beyond the old suite: macOS `/tmp`
resolution rejected valid manifests; mirror run IDs allowed path traversal;
repeat mirrors conflicted on newly generated timestamps; mirror validation
trusted incomplete acquisition observations; and the readiness launcher could
install a different checkout from its recorded requested ref. Publication also
requires independent Gate B and destination-integrity checks. M3 depends on
repairing these contracts and observing green required CI for the repair.

## Current implementation

1. Repair acquisition path containment and validated cache recovery. Reuse bytes
   only after source-manifest binding and destination checksums pass; retain
   historical evidence identity when package-only manifest metadata changes.
2. Make mirrors immutable and restart safe. Validate run IDs, paths, inventories,
   source checksums, record schema and recovered acquisition lineage. Commit
   atomic records only after byte verification. Test with nonhuman synthetic bytes.
3. Make the canonical publisher enforce the capture-design gate, source and
   transformation lineage, domain schemas, destination hashes, append-only registry
   and last-written completion marker. Reject stale/corrupt completed runs.
4. Pin the launcher to an exact allowed origin and clean checked-out SHA before
   installation. Keep both notebooks as thin package launch surfaces and expose
   explicit hydration/acquisition/mirror choices.
5. Add validated orchestration state, M3–M9 checkpoints, a claim ledger, current
   source/evidence ledger, version consistency checks and negative tests.
6. Run Python 3.12/3.13, clean-wheel/outside-checkout, schema, notebook, hygiene,
   formatting and remote CI checks. Preserve exact logs and hashes.

## Branch strategy and continuation

Recovery branch: `codex/m2.1.1-provenance-recovery`, based on the verified main
commit. Maintain a draft PR; never merge or enable auto-merge. Once required
repair CI is green and no M2 package/contract defect remains, start a distinct
M3 branch. If the recovery PR remains unmerged, the M3 branch/PR is stacked on it.
Record each parent branch explicitly. M4 through M9 remain `not_started` until
their prerequisites are met; preparation of state files does not implement them.

M3 implements synthetic FASTQ validation, raw QC and the shared alignment/BAM
contract, module/subworkflow tests, immutable tool identities, lineage/QC schemas,
and reproducible Docker tests. BQSR requires pinned known-sites and an accepted
quality-evidence contract. Target-aware acceptance remains blocked by Gate B.
M4 additionally requires actual dual-caller integration in a supporting environment.
M5 canonical benchmarking requires owner-approved domain identity and real HG001
outputs from both callers. M6–M9 retain all specified execution, cost, release,
canonical-result, deployment and scientific claim gates.

## Observed external evidence and limits

The latest private source-cache control record reports ten objects totaling
4,900,011,445 bytes from pre-recovery commit
`568ad18bf6745c80d9aac346e9be151d7a850877`. Names and sizes match Drive metadata;
this audit did not retrieve/re-hash the genomic objects. Reference preparation,
canonical domains and completion are not established. Rehydration must rehash
actual bytes before they can be used. Do not repeat large downloads for activity.

No canonical HG001 computation, caller comparison, public deployment, release,
paid compute, DNS change or clinical/generalization claim is authorized by code
readiness. The current local machine is macOS ARM64; no Docker or usable Java
runtime was found during baseline inspection. Git SSH read access works; GitHub
CLI credentials failed validation, and the connected GitHub API remains available.


## M3 implementation plan, begun after recovery verification

Recovery required CI run 34094504379 succeeded at
`22d01b202e15bb098e9d42d0ad4a98606e78c2c2`. Draft PR #19 remains unmerged.
Branch `codex/m3-shared-preprocessing` is explicitly stacked on
`codex/m2.1.1-provenance-recovery`; its PR base must be that branch while PR #19
is unmerged. The recovery evidence record is `evidence/m2.1.1-verified.json`.

1. Preserve explicit foundation mode; add synthetic shared-preprocessing mode
   and an actionable fail-closed canonical mode. Bind invented fixtures by hash.
2. Implement typed package input/QC/alignment/coverage/resource/provenance models,
   schemas and negative tests with deterministic paired reads/reference/known sites.
3. Run raw FastQC, BWA-MEM2, sample-level merge, retained duplicate marking,
   BaseRecalibrator/ApplyBQSR with original qualities, BAM acceptance/summaries,
   target-independent mosdepth and explicit MultiQC inputs in DSL2 modules.
4. Pin verified tool-container manifest identities and capture executable versions,
   actual commands, task resources, trace/report/timeline/DAG and shared BAM lineage.
5. Test malformed reads/metadata/reference, module/subworkflow stubs, actual tiny
   Docker integration, sort/index/RG/duplicate/OQ invariants and resume behavior.
6. Maintain current README/methods/runbook and gate-aware checkpoints. Execution
   uses the clean-clone Docker CI driver; a thin M3 Colab launcher is required if
   Colab becomes an execution target. Run local and remote tests before any M4
   continuation decision.

Canonical known-sites resources are absent and require separate pinned identity
and reference-compatibility verification. The existing ADR 0003 quality contract
is preserved. Synthetic BQSR tests qualify plumbing, not calibration adequacy or
HG001 performance. No assay targets, truth VCF/BED or benchmark inputs enter M3
processing tasks. Canonical capture-dependent acceptance remains Gate B blocked.

Observed CI attempts are retained in `evidence/m3-ci-attempt-1.json` through
`evidence/m3-ci-attempt-4.json`. The fourth attempt passed Python and Nextflow
framework jobs and all 21 upstream processing/QC tasks, then the real collector
rejected a tool-version mismatch. The exact BWA-MEM2 2.3 distribution reports
executable version 2.2.1, matching its inspected release-source fallback. The
contract must preserve both identities and require the exact expected report
against the unchanged image digest. Complete collection, independent
BAM/ownership checks and resume must still pass in actual Docker execution before
M3 is verified.

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

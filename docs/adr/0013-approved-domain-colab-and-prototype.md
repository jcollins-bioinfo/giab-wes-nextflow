# ADR 0013: owner-approved coding domain, Colab compute and early prototype

Date: 2026-09-08. Status: owner decisions accepted; execution incomplete.

The owner explicitly approved the fixed GENCODE v50 coding-domain alternative
after reviewing the proposal. The exact approval and proposal digests are in
[the immutable approval record](../../explorer/src/pipeline_evidence_explorer/data/domain-approval.json).
This replaces physical capture-design adoption as the selected primary estimand;
it does not establish the uncertain NIST7035 kit identity.

The proposal selects protein-coding CDS plus stop codons from GENCODE v50 Basic,
uses 0-based half-open merged coordinates and no observed-coverage selection.
Calling uses chr1–22 and chrX with 100-base padding. Evaluation intersects the
unpadded autosomal coding domain with GIAB confidence. The proposed identities are:

| Domain | Bases | SHA-256 |
|---|---:|---|
| Calling | 77,896,078 | `521a5c1140953bb516f36d28486767f49284a071a851331ce8d14f320d7ff728` |
| Full evaluation | 33,567,783 | `9c270a2c46c2e83ae0d35e5ceaa75e4b77918924bf7443d4fffe467cd9b950d4` |
| Chr20–22 sensitivity | 1,905,809 | `7730c4303e03fef74d2c22193102845e369e04ac81fabb7f41fae1374be65d00` |

Eligible truth at uncaptured or uncovered coding loci remains in recall; its
false negatives reflect end-to-end capture/coverage/calling performance. Full
HG001 DeepVariant WES results are descriptive/in-sample because training included
HG001. Chr20–22 is a same-individual sensitivity analysis, not population
generalization. Approved domain construction still needs a package-owned,
validated implementation before canonical execution.

The owner also approved an early Dash prototype from verified synthetic evidence,
changing the original ordering for this prototype only. It may display recorded
synthetic observations and missing canonical fields. It cannot assert canonical
accuracy, a caller winner, M8 completion or deployment.

The owner selected Colab Pro for capability inspection and required index
construction to use Colab compute and memory. All durable large storage belongs
in the permitted private Google Drive project hierarchy. See
[the compute/storage handoff](../canonical-colab.md). No index construction on
the owner's Mac is authorized by this plan.

M4 synthetic SNV execution is now verified on main by
[CI34237377774 and its hash-verified artifact](../orchestration/evidence/m4-verified-main-34237377774.json).
Recipe 1.1.0 repairs allele/fragment-position coupling while preserving the frozen
loci, allele balances, native genotypes and strict acceptance requirements.
Independent callers, both-mode, positive DeepVariant inference and full resume
passed. Canonical HG001 and indel qualification remain unestablished.

Historical CI34202569517 completed DeepVariant inference and prediction inspection,
then failed frozen native genotype/filter acceptance on recipe 1.0.0. Its failed
record remains unchanged. The early Explorer now renders the current synthetic
pass and retains that historical diagnostic in its hash-locked evidence bundle.

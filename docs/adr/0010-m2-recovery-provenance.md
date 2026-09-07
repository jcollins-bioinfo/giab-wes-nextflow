# ADR 0010: recover source bytes without upgrading historical evidence

Author: John Patrick Collins. Status: accepted implementation repair, 2026-09-07.

## Context

The M2.1 baseline CI was green, but a macOS path-containment defect and missing
mirror/publication identity checks were reproduced in a new audit. A historical
private source cache exists. Its manifest differs from the current baseline only
in project-version metadata, and its source object declarations are unchanged.
Re-downloading those objects would not repair the provenance defects.

## Decision

Canonicalize an allowed root before testing containment, reject traversal and
symlink destinations, and validate both input observations and output records.
Use deliberate run IDs, stable content identity on retry, atomic staging and
rehashing before promotion. Existing completion markers are claims to verify,
not permission to skip verification. Require the actual approved capture-design
decision and complete domain lineage before canonical publication.

A source mirror remains a reusable cache. Recovery from a historical mirror must
bind the exact historical manifest, compare its resource contracts with the
current manifest, and rehash the actual local source bytes with both recorded
SHA-256 and upstream MD5. Fresh acquisition observations may be produced only
after this check; separate recovery provenance retains original run/repository
and manifest identities. No historical record is rewritten as current evidence.

The launcher verifies the complete origin, clean checkout and exact resolved SHA
before installing source with the chosen Python interpreter. Notebooks call the
installed package through that shared launcher and contain no scientific logic.

Orchestration records cite an observed prior commit because a committed file
cannot contain its own future Git SHA. CI links and test evidence explicitly name
the commit they verified. Checkpoints never promote later milestones on intent.

## Scientific and operational consequences

These changes repair identity, integrity and restart behavior; they do not change
the estimand, capture-design decision, reference build, truth release or callers.
Gate B stays blocked. The local macOS audit does not establish Colab, Docker,
DeepVariant, canonical HG001, cloud or public-deployment execution. A mirror
architecture field is not an independently measured container capability record.

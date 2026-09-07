# M3 readiness dossier

Evidence date: 2026-09-07. Scope is code readiness for the GIAB HG001 Illumina WES workflow, not canonical biological execution readiness.

| Area | Evidence/status | Decision or owner/action |
|---|---|---|
| Repository/package integrity | M2 behavior resides in `src/giab_wes_nextflow`; five thin wrappers and wheel/resource/console tests cover the installed boundary. | Ready; maintainers keep wrappers algorithm-free. |
| Python 3.12 and 3.13 | CI matrix configured for complete offline suite and installed-wheel checks. | Requires green feature-branch Actions evidence before merge. |
| Nextflow/nf-test/nf-core synthetic | One pinned Nextflow job retains lint, schema, nf-test, and `test,docker`. | Requires green feature-branch Actions evidence; no real data. |
| Colab launcher static status | JSON, shell syntax, ordering, identity, SHA, staging, and Gate B safety are statically tested. | Ready as configured code. |
| Real Colab execution | Not executed. | Owner: maintainer; execute and retain runtime evidence separately. |
| Verified-source acquisition/mirror | Synthetic tests cover destination rehash, hydration corruption, immutability, and absence of completion markers. | Code ready; no Drive/source operation performed. |
| GRCh38 preparation | Implementation retained, but no public reference was downloaded or prepared here. | Operational execution remains untested. |
| Capture-design Gate B | Exact capture-design bytes remain unresolved. | Block canonical domains and publication; data owner must confirm artifact/checksums. |
| M3 work independent of Gate B | Alignment/QC module design, interfaces, synthetic fixtures, and fail-closed contracts may proceed. | May implement without claiming canonical execution. |
| M3 work dependent on Gate B | Target-aware QC acceptance, canonical target metrics, real HG001 execution, and publication remain provisional/blocked. | Wait for confirmed canonical target domains. |
| Remaining defects | Remote CI/Colab evidence and canonical capture artifact are absent. | Maintainer: run CI/Colab; data owner: resolve Gate B. |

M3_IMPLEMENTATION_READY_WITH_EXPLICIT_GATES

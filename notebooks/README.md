# Notebook launch center

All notebooks are thin launch/inspection surfaces. They clone the named GitHub
repository, require a reviewed 40-character SHA, verify origin and a clean
checkout, install with `sys.executable -m pip`, import `giab_wes_nextflow` and
invoke repository-owned interfaces. No QC/alignment/domain science lives here.
Notebook files have no saved outputs and have not been executed in Colab as part
of the M2.1.1 recovery audit.

| Notebook | Purpose | Inputs | Outputs | Compute/storage | Gate status |
|---|---|---|---|---|---|
| [M2 recovery](m2_colab.ipynb) | Code verification, source-cache hydration, explicit acquisition/mirroring | Reviewed SHA; run ID; existing permitted project folder; historical manifest for legacy recovery | Local verified sources and immutable acquisition/hydration records; optional verified source mirror | About 4.9 GB sources plus one local copy, rehash I/O and headroom; no Nextflow work/ on Drive | Code/cache operations only; Gate B closed |
| [M2 acquisition compatibility](m2_colab_acquisition.ipynb) | Same canonical launcher retained for old links | Same inputs | Same outputs | Same expectations | Same Gate B boundary; no independent preparation/publication path |

[![Open M2 recovery in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jcollins-bioinfo/giab-wes-nextflow/blob/main/notebooks/m2_colab.ipynb)
[![Open M2 compatibility notebook in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jcollins-bioinfo/giab-wes-nextflow/blob/main/notebooks/m2_colab_acquisition.ipynb)

While a change is in draft, use the notebook at the exact draft commit supplied
in the handoff rather than assuming `main` contains it. `REPOSITORY_REF` is empty
by default and must be filled deliberately. Code checks run before mounting or
writing private data. Review zero-download preflight before selecting a data mode.

The established mount is `/content/drive/MyDrive/giab-wes-nextflow-private`.
Active M2 I/O belongs in `/content/m2-stage`; future milestones use their own
local staging directories. Never access a folder whose name contains
`DO NOT ACCESS WITH CHATGPT`. Never use Drive as Nextflow `work/`.

For an interrupted operation, preserve the deliberate source and recovery run
IDs. Hydration rehashes MD5/SHA-256 and sizes before local promotion. For old
mirrors, supply the exact historical source manifest and a new recovery ID as
explained in [M2 recovery](../docs/m2-recovery.md). After hydration, use the new
recovery ID for acquisition verification or a new mirror operation. Do not
redownload large files merely to create new evidence when validated reuse works.

The latest observed mirror reports 10 objects and 4,900,011,445 bytes; this audit
inspected control records and metadata only. No prepared reference or canonical
completion marker was observed. Gate A source readiness requires fresh verified
bytes. Under ADR 0013, Gate B requires validated materialization of the owner-approved fixed coding domain instead of unresolved physical capture-kit adoption. A mirror never completes Gate B.

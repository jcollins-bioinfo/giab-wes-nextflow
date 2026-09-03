# Notebook launch center

Notebooks are thin, restart-safe launchers around the installed `giab-wes-nextflow` package and Nextflow code. No scientific logic should live only in notebook cells.

[![Open M2 in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jcollins-bioinfo/giab-wes-nextflow/blob/main/notebooks/m2_colab.ipynb)

> The badge launches the current `main`. The notebook resolves and records the exact Git SHA actually executed; edit `REPOSITORY_REF` to select a reviewed branch, tag, or commit.

| Notebook | Purpose | Inputs | Durable outputs | Disk | Scientific gate | Status |
|---|---|---|---|---|---|---|
| `m2_colab.ipynb` | Bootstrap, acquire, validate, mirror | Canonical ten-resource manifest; public HG001 sources | Checksummed source cache and mirror evidence in the established Drive workspace | Multi-gigabyte local `/content`; equivalent Drive capacity | Gate A configured; source mirror supported; canonical Gate B blocked | Bootstrap statically tested; Colab/Drive configured, not executed in CI |

## Clean-runtime launch

1. Open the badge in a clean Colab runtime and optionally pin `REPOSITORY_REF`.
2. Run cells in order. Review the resolved SHA and installed package path.
3. Mount the existing workspace at `/content/drive/MyDrive/giab-wes-nextflow-private` (folder ID `13R7K0NtUA-GOoyj2gi2hBWUaGITu98u5`).
4. Keep downloads and compute-heavy I/O in `/content/m2-stage`; never use Drive as the Nextflow work directory.
5. Choose a unique `RUN_ID`, run zero-download preflight, acquisition, validation, then verified mirroring.

If the runtime is interrupted, bootstrap again, mount Drive, restore the prior run ID, and run the documented hydration command. Hydration re-hashes every cached object before atomic local promotion.

**Gate status:** Gate A establishes contracts and synthetic tests. The durable verified-source mirror is a cache, not canonical completion, and never creates `COMPLETED.json`. Canonical Gate B remains fail-closed because public metadata has not bound the library to an exact capture-target BED. Only reviewed primary evidence and approved hashes in `config/m2-target-design.json` can enable liftover and canonical domains.

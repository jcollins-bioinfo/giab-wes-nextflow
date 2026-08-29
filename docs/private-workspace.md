# Private workspace

The existing unshared Drive folder `giab-wes-nextflow-private` (ID `13R7K0NtUA-GOoyj2gi2hBWUaGITu98u5`) may be mounted in Colab at `/content/drive/MyDrive/giab-wes-nextflow-private`; this documentation path is never pipeline logic. Existing top-level layout is config, inputs, references, cache, registry/runs, runs, reports, exports, logs, `WORKSPACE_README.md`, and `workspace_manifest.json`.

The publisher accepts root only via `--root` or `GIAB_WES_PRIVATE_ROOT`, writes M1 milestone paths, validates manifest size/hash/path/schema metadata, uses `_incomplete`, renames, updates registry, and writes `COMPLETED.json` last. Identical runs no-op; conflicts fail. Drive must never contain transient Nextflow work. Human sequence/BAM/VCF and secrets are denied in M1.

After mounting: `python scripts/publish_private_workspace.py --root /content/drive/MyDrive/giab-wes-nextflow-private --bundle artifacts/private-workspace/m1_foundation --run-id m1-foundation-0.1.0-dev.1`.

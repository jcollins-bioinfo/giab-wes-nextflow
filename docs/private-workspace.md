# Private workspace

The existing unshared Drive folder `giab-wes-nextflow-private` (ID `13R7K0NtUA-GOoyj2gi2hBWUaGITu98u5`) may be mounted in Colab at `/content/drive/MyDrive/giab-wes-nextflow-private`; this documentation path is never pipeline logic. Existing top-level layout is config, inputs, references, cache, registry/runs, runs, reports, exports, logs, `WORKSPACE_README.md`, and `workspace_manifest.json`.

The publisher accepts root only via `--root` or `GIAB_WES_PRIVATE_ROOT`, writes M1 milestone paths, validates manifest size/hash/path/schema metadata, uses `_incomplete`, renames, updates registry, and writes `COMPLETED.json` last. Identical runs no-op; conflicts fail. Drive must never contain transient Nextflow work. Human sequence/BAM/VCF and secrets are denied in M1.

After mounting: `python scripts/publish_private_workspace.py --root /content/drive/MyDrive/giab-wes-nextflow-private --bundle artifacts/private-workspace/m1_foundation --run-id m1-foundation-0.1.0-dev.1`.

## M2 private layout

The M2 driver writes canonical bytes directly beneath `inputs/HG001` and `references`, and immutable JSON records beneath `registry`. A `.part` file is the only resumable transient and is atomically renamed only after MD5 verification. Re-running verifies and reuses matching bytes; mismatch is deleted and reacquired. The workspace remains private, is never a Nextflow work directory, and acquisition does not publish human data back into Git.

For M2, active acquisition occurs in ephemeral `m2-stage`, not directly on Drive. `publish_m2_workspace.py` requires materialized canonical domains, copies only manifest-declared verified sources plus run evidence, rehashes every destination, uses `m2_data_provenance/runs/_incomplete/<run-id>`, promotes atomically, writes an append-only registry record, and creates `COMPLETED.json` last. Publication refuses the `DO NOT ACCESS WITH CHATGPT` marker. See `docs/m2-data-provenance.md`.

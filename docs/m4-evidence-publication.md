# M4 synthetic evidence publication and recovery

The package publisher validates the common M4 result bundle before copying any
evidence. It accepts only `m4-inputs.json`, the selected `m4-gatk.json` and/or
`m4-deepvariant.json`, and `m4-manifest.json`. Each file is capped at 2 MiB.
Raw/native VCFs, BAM/BAI, model weights, reference, reads, logs and Nextflow work
directories are excluded. This JSON recovery interface cannot restore an active
Nextflow task cache or qualify a canonical HG001 run.

Use an installed, reviewed package and an actual completed synthetic M4 contract
directory. The project root must be named `giab-wes-nextflow-private`; symlinks,
unsafe ancestry, prohibited-folder markers and nested staging roots are rejected.

```bash
python -m giab_wes_nextflow.m4_publication inventory --bundle /local/m4/both/contracts
python -m giab_wes_nextflow.m4_publication publish --bundle /local/m4/both/contracts \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private --dry-run
python -m giab_wes_nextflow.m4_publication publish --bundle /local/m4/both/contracts \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private
python -m giab_wes_nextflow.m4_publication validate \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private \
  --run-id YOUR_RECORDED_RUN_ID --selection both
python -m giab_wes_nextflow.m4_publication hydrate \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private \
  --run-id YOUR_RECORDED_RUN_ID --selection both --staging /content/m4-recovered
```

Replace the example local bundle path and run ID with the identities produced
by the integration driver. `--selection` accepts `gatk`, `deepvariant` or `both`;
independent modes may share the run ID while retaining separate immutable
registries. The caller selection is validated against the manifest and exact
file allowlist. Commands above are an interface example, not evidence of a
Drive publication performed in this task.

The stable namespaces are:

- `incomplete/m4-synthetic/<manifest-sha256>/` for interrupted copies;
- `evidence/synthetic/m4/bundles/<manifest-sha256>/` for promoted JSON bundles;
- `registry/milestones/M4/synthetic/<run-id>/<selection>.json` for immutable
  registry records;
- `COMPLETED.json` inside a promoted bundle, written last after destination
  rehash, schema/semantic validation and successful registry writing.

Copies are atomic per file and promoted on the same filesystem. Identical
validated retries preserve the original registry metadata; conflicting run or
artifact identities fail without overwriting evidence. The publisher holds an
exclusive lock. A lock left by process death fails closed and requires an
explicit operator audit before removal; no automatic lock stealing occurs.

Recovery revalidates the registry, completion marker, destination bytes and
package-owned caller lineage before it writes `M4_EVIDENCE_RECOVERED.json`.
Inventory and dry-run modes are read-only and report logical identities and
byte estimates. No canonical namespace or genomic source cache is created.

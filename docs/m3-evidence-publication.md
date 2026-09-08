# M3 synthetic evidence publication and recovery

The installed package publishes only six validated JSON files, each at most
2 MiB: `m3-manifest.json`, `m3-alignment.json`, `m3-qc.json`,
`m3-coverage.json`, `m3-resources.json`, and `m3-provenance.json`.
This interface accepts synthetic M3 evidence only. It does not publish a canonical
run, cache a BAM/reference, or copy Nextflow work. Public reports should use
logical artifact identifiers; private roots never belong in website data.

The existing private root must be named `giab-wes-nextflow-private`; its permitted
Google Drive folder ID is `13R7K0NtUA-GOoyj2gi2hBWUaGITu98u5`. Name/ancestor
guards reject prohibited folders, safety markers, symlinks and root escapes.
Synthetic evidence and canonical results occupy separate namespaces:

```text
giab-wes-nextflow-private/
  cache/verified-sources/                     # existing M2 reusable cache
  registry/runs/<source-run-id>/              # existing M2 acquisition/mirror lineage
  incomplete/m3-synthetic/<manifest-sha256>/   # unaccepted interrupted publication
  evidence/synthetic/m3/bundles/<manifest-sha256>/
    m3-*.json                                # exactly six accepted JSON artifacts
    COMPLETED.json                           # last-written acceptance marker
  registry/milestones/M3/synthetic/<run-id>.json
```

The six source artifacts first pass schemas, payload/file hashes and cross-file
scientific lineage checks. Publication rehashes each staged destination, validates
the complete bundle again, promotes the directory within the same filesystem,
writes the append-only run registry, and writes `COMPLETED.json` last. A bundle
without the marker is incomplete even if its files or registry already exist.
Consumers validate the marker against the registry and freshly rehash the bundle.

An identical retry reuses the original record, including its producer/publisher
version, timestamp and architecture. Changed bytes under an existing run identity
fail closed. Content addressing avoids repeated copies of an identical bundle.
Interrupted staging copies may be replaced; completed mismatching files are
preserved for inspection. Exclusive locks prevent competing writers. After a
runtime dies, first establish that no writer remains before moving a stale lock
to an audit location; the tool never guesses that another writer has died.

## Commands

Use the package from the exact reviewed commit. These examples assume an owner
has mounted the established Drive folder and that the six files have already
been generated and validated by an actual synthetic run. No Colab execution is
asserted by these instructions.

```bash
python -I -m giab_wes_nextflow.m3_publication inventory \
  --bundle /content/m3-stage/results/m3/contracts
python -I -m giab_wes_nextflow.m3_publication publish \
  --bundle /content/m3-stage/results/m3/contracts \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private --dry-run
python -I -m giab_wes_nextflow.m3_publication publish \
  --bundle /content/m3-stage/results/m3/contracts \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private
python -I -m giab_wes_nextflow.m3_publication validate \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private \
  --run-id m3-synthetic
```

Inventory/dry-run are read-only and report bytes without exposing private paths.
Allow temporary plus final bundle space during first publication (up to 24 MiB
plus small control records by the JSON size cap). This is separate from image,
generated fixture and workflow storage. Colab runtime/storage qualification and
canonical execution remain future gates.

After runtime loss, hydrate only completed evidence into local staging:

```bash
python -I -m giab_wes_nextflow.m3_publication hydrate \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private \
  --run-id m3-synthetic --staging /content/m3-stage/recovered-evidence --dry-run
python -I -m giab_wes_nextflow.m3_publication hydrate \
  --drive-root /content/drive/MyDrive/giab-wes-nextflow-private \
  --run-id m3-synthetic --staging /content/m3-stage/recovered-evidence
```

Recovery writes `M3_EVIDENCE_RECOVERED.json` only after local rehash and bundle
validation. Recovered summaries are inspectable evidence, not a Nextflow cache;
they do not make `-resume` possible after work storage is lost. M2 source-cache
hydration remains a separate interface and provenance chain.

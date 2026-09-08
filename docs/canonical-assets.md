# Canonical asset interface

These installed package APIs implement asset preparation; they do not establish
that a canonical run has happened. The new canonical launcher supplies the
qualified runtime and keeps all active directories under `/content` outside
`/content/drive`. Only `/content/drive/MyDrive/giab-wes-nextflow-private` is accepted
for durable canonical source and asset operations. Every ancestor is checked for
the prohibited folder name or safety marker before access.

```python
from giab_wes_nextflow import canonical_assets as assets

reference = assets.prepare_reference(source_gz, authenticated_source_fai, reference_dir)
index = assets.build_index(reference_dir, index_dir, runner)
sources = assets.acquire_known_sites(source_scratch, drive_root, allow_large_downloads=True)
known_sites = assets.prepare_known_sites(sources, reference_dir, known_sites_dir, runner)
index_cache = assets.publish_assets(
    index_dir, drive_root, run_id, repository_sha, kind="canonical_bwa_index_asset"
)
```

`runner(tool: str, args: list[str], cwd: Path) -> str` executes the exact pinned
tool through the qualified runtime. Arguments exclude the executable. All file
arguments are relative to `cwd`; the sole task mount contains the reference,
index, and private probe input. For `runner("bwa", [], cwd)`, the adapter must
allow BWA's usage exit code 1 and return stdout plus stderr so the exact version
can be checked. All other commands require exit 0. SAM probe output and genomic
known-sites bytes must remain private. Runtime receipts, image identities and
stderr belong in the enclosing execution evidence; they are not a substitute
for the asset manifest's complete byte checks.

Reference output is exactly `reference.fa`, `reference.fa.fai`, `reference.dict`
and `reference-manifest.json`. The index stage contains the same four files,
`reference.fa.{amb,ann,bwt,pac,sa}`, and `index-manifest.json`; private runtime logs
and `_probe_work/` are not published. The known-sites stage contains three
`bqsr_*.no-alt.vcf.gz` derivatives, their `.tbi` indexes, and
`known-sites-manifest.json`. Original six-object identities stay in source cache
and acquisition registry; derivative source-to-output counts stay in the manifest.

The CLI exposes reference preparation and read-only asset validation:

```bash
python -I -m giab_wes_nextflow.canonical_assets reference \
  --source-gz /content/m2-stage/references/GRCh38/source.fasta.gz \
  --source-fai /content/m2-stage/references/GRCh38/source/source.fasta.gz.fai \
  --output /content/canonical-assets/reference
python -I -m giab_wes_nextflow.canonical_assets validate \
  --directory /content/canonical-assets/index --kind canonical_bwa_index_asset
```

`hydrate_assets(drive_root, reference_id, asset_id, output, kind=...)` requires an
existing completed content-addressed asset and returns its validated manifest.
`validate_asset(directory, kind)` rehashes all expected payloads and checks the
current installed source/tool contracts. `publish_assets` returns the durable
asset directory; its registry records contain `kind`, `reference_id`, `asset_id`,
repository SHA, run ID, the exact payload inventory, and `asset_contract_sha256`.
The discovery hash binds current reference, method and tool/source contracts;
records from a different contract are not selected. Current matching records
that fail hydration remain explicit failures. A subsequent launcher
can discover only these small registry records before selecting a matching
asset. Retry with the same inputs preserves immutable content identity. A stale
lock after abrupt runtime loss is an actionable stop: verify that no writer is
active, inspect the affected operation, then remove only that abandoned lock.
There is no automatic stale-lock stealing or silent corrupt-cache replacement.

Source downloads reuse declared MD5s and pinned GCS generations through the
existing resumable acquisition implementation. Verified Drive sources are
rehydrated before network acquisition and rehashed afterward. Missing source
bytes require `allow_large_downloads=True`; inadequate scratch or reported Drive
filesystem space still fails. Filesystem free space does not prove Drive account
quota. BQSR object bytes total 1,648,657,444; preparing derivatives additionally
requires at least 20 GiB free scratch at derivative admission for
decompression/compression/index headroom. These floors are admission policies,
not measured peak-use guarantees. Full classic indexing requires
at least 35 GiB free scratch and measured 16 GiB effective RAM at admission.
Actual duration and peak memory remain unmeasured until execution.

`extract_archive` is a separate exact-inventory utility for already authenticated
archives. It rejects traversal, links, sparse entries, duplicate/unexpected files,
wrong sizes and hashes. Successful extraction alone cannot qualify a prebuilt
Hartwig index; that route remains unqualified under ADR 0015.

Unit tests use only invented sequence and a test-local source contract. They
cover complete MD5/FAI behavior, corruption, no-alt BQSR transformation, index
record-count plumbing, resumability, marker ordering, durable rehash, source
lineage, memory admission and archive safety. They do not claim full GRCh38
construction or actual classic BWA execution. Those require the reviewed Colab
notebook and returned execution evidence.

The launcher reuses the original M2 `cache/verified-sources/<destination>` paths
by authenticating bytes directly against current source pins. It does not relabel
an old acquisition manifest or invoke the obsolete capture-target gate. Cache-only
mode validates existing local bytes before acquisition, so a corrupt file cannot
trigger an unauthorized download. Atomic source and domain copies retain partial
bytes separately and commit their completion records last.

# Canonical public result bundle contract (consumer interface 1.0.0)

The producer writes a fresh public directory containing `manifest.json`,
`result.json`, and only the small JSON/TSV metadata members listed in the manifest.
No VCF, sequence, BAM, reference, index, private path, credential, or signed URL
belongs in this bundle. Native/normalized genomic output identities are hashes
inside the result, not public genomic files. The trusted manifest SHA-256 is
provided separately to the consumer; a self-hashed replacement is not trusted.

`manifest.json`: `{"schema_version":"1.0.0","kind":"canonical_public_manifest",
"files":{"result.json":{"bytes":123,"sha256":"64 hex"},"runtime.json":
{"bytes":123,"sha256":"64 hex"},"...":{"bytes":123,"sha256":"64 hex"}}}`.
Byte counts/hashes are computed from actual final files; the example numbers
above are schema illustrations only. Inventory is exact, regular files only.

`result.json` has these required keys (all objects are closed):

- `schema_version`: `1.0.0`; `kind`: `canonical_results`; `status`: `complete`;
  `synthetic`: false; `canonical`: true.
- `run_id`: safe identifier; `repository_sha`: full40; `package_version`: string.
- `scope`: `hg001_chr20_22_coding` or `hg001_full_coding`; `sample`: `HG001`.
- `domain`: `{id,sha256,bases,interval_count,contigs}`. Holdout id
  `R_eval_holdout`, SHA `7730c4303e03fef74d2c22193102845e369e04ac81fabb7f41fae1374be65d00`,
  bases1905809, intervals11715, contigs `["chr20","chr21","chr22"]`.
  Full id `R_eval_full`, SHA `9c270a2c46c2e83ae0d35e5ceaa75e4b77918924bf7443d4fffe467cd9b950d4`,
  bases33567783, intervals203986, contigs chr1 through chr22 in dictionary order.
- `shared_inputs`: `{bam_sha256,bai_sha256,reference_sha256,calling_regions_sha256}`.
- `alignment`: `{aligner,version,runtime_identity}`; aligner `bwa-mem2` or `bwa`;
  runtime_identity is an immutable image/source identity string.
- `callers`: exact `gatk` and `deepvariant` objects, each containing
  `{quality_source,shared_inputs,raw_vcf_sha256,normalized_vcf_sha256,metrics}`.
  Shared inputs must equal the top-level object; quality_source is respectively
  `QUAL` and `OQ`. Metrics exactly SNP/INDEL/OTHER, each carrying
  `{tp_query,tp_truth,fp,fn,precision,recall,f1,missing_reasons}` as in M5.
- `resources`: `{gatk,deepvariant,shared_preprocessing,common_downstream,total}`.
  Each has `{wall_seconds,cpu_seconds,peak_rss_bytes,missing_reasons}`. Values are
  nonnegative numbers (RSS integer) or null; every null needs a corresponding
  reason. These are observations, not additive peak memory or summed wall time.
- `coverage`: null or `{evaluated_bases,covered_bases,definition,artifact}`;
  `coverage_missing_reason`: nonempty string when null, otherwise null.
- `qualification`: exact roles `sources`, `reference`, `index`, `domain`,
  `runtime`, `preprocessing`, `gatk`, `deepvariant`, `benchmark`, `resume`.
  Each maps to `{artifact,sha256}` identifying a retained small JSON receipt.
  Receipts must be public-safe objects with `status:"passed"`, `kind` equal to
  their qualification role, and `run_id` equal to this run. They may contain
  additional actual evidence fields; never generate a passed receipt merely
  to satisfy this consumer. Reusable source/index/runtime evidence can be
  incorporated into run-specific receipts that preserve original provenance.
- `environments`: array of `{name,status,evidence}`; status `executed` or
  `configured_only`; executed requires nonempty evidence filename in manifest.
- `limitations`: nonempty strings including exact mandatory texts exported by
  `canonical_results.REQUIRED_LIMITATIONS`; `uncertainty`: nonempty string.

The producer must establish all gates before writing a complete result. The
consumer rederives arithmetic, validates known domain identities and comparison
symmetry, checks every receipt/hash, and exposes safe JSON/TSV. It does not turn
valid JSON into an independent attestation that execution happened. Publishing
requires an externally reviewed manifest SHA. Without it the Explorer displays
canonical results as unavailable and keeps synthetic evidence separately labelled.

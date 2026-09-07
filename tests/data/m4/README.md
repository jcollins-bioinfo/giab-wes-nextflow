# M4 invented SNV-positive fixture

Generate the separately registered `m4-snv-positive` recipe after installing the package:

```bash
python -m giab_wes_nextflow.m4_fixture --output tests/data/m4-generated
```

The generator retains the complete M3 reference, independent known sites, samplesheet metadata, and original 24 read pairs. It appends 240 unique fragment pairs across the same two lanes and read groups. The result contains 264 pairs of 150-base reads: 528 primary records, 524 mapped records, four unmapped records, and the original exactly four marked duplicate reads. Original qualities vary deterministically from Q27 to Q40 in the added reads. The reference has two invented contigs of 12,000 and 8,000 bases. No downloaded sequence, human sequence, external target file, or benchmark truth contributes bytes.

The frozen caller qualification cases are:

| Contig | Position (1-based) | Reference | Alternate | Expected genotype | Reference fragments | Alternate fragments |
|---|---:|---|---|---|---:|---:|
| chrSYN1 | 3151 | T | A | 0/1 | 40 | 40 |
| chrSYN2 | 7101 | T | A | 1/1 | 0 | 80 |
| chrSYN1 | 5401 | G | — | 0/0 | 80 | 0 |

Each locus receives 80 distinct fragments with 40 forward-mate and 40 reverse-mate observations. Every added fragment has a distinct mapped start/end pair. The cases use isolated SNVs so the independent BAM acceptance oracle can require the original exact `150M` placements. An indel would need its own versioned fixture and alignment representation contract. These cases qualify native calling and actual neural inference; they do not estimate biological accuracy or clinical performance.

The fixture must pass the complete shared M3 BWA, sorting, duplicate retention, BaseRecalibrator, ApplyBQSR, and original-quality-to-OQ acceptance path. M4 additionally requires a real recalibration table containing positive observations. Both callers receive the same accepted physical BAM. GATK uses recalibrated QUAL; DeepVariant uses OQ. Calling spans both complete invented contigs and has no truth-derived interval restriction.

The package admits only explicit registered recipe identities. The default M3 fixture and its public hashes remain unchanged. `expected-hashes.json` pins the new source bytes and full expectation manifest independently of the output directory. Generated FASTA, FASTQ, VCF, samplesheet, and per-read expectation files are ignored and excluded from distributions. Only the deterministic recipe, this description, and the small identity inventory belong in Git.

The full per-read and per-site oracle stays outside the isolated caller task. The caller input directory contains only the shared BAM/BAI, reference FASTA/FAI/dictionary, full-contig regions, and aggregate input provenance. Unit metadata stand-ins exercise validation code only; actual acceptance requires the separate Docker integration driver to observe both callers, indexed native outputs, nonzero DeepVariant candidate and inference records, fixed model inventory, and cache reuse.

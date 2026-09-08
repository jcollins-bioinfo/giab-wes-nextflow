# ADR 0015: canonical full-reference assets and classic BWA fallback

Status: accepted implementation choice; canonical execution remains unqualified.

The authorized canonical subset still aligns against the complete GRCh38 no-alt
reference. Calling and benchmarking may use the approved chr20–22 domain; the
alignment reference is never truncated to those chromosomes.

The preferred Hartwig BWA-MEM2 archive remains unqualified. Retained primary
metadata identifies an 8,797,807,834-byte archive labelled 2.2.1, a matching
195-contig FAI, and a complete sequence dictionary with MD5 values. Its multipart
ETag is not a whole-file MD5. No authenticated archive checksum, complete archive
inventory, producer execution evidence, or demonstrated compatibility with the
project's pinned MEM2 executable has been established. FAI equality alone cannot
close those gaps. We do not spend the canonical execution budget treating that
metadata as completed qualification.

Use classic BWA 0.7.17, `bwa index -a bwtsw`, as the authorized fallback. The
[upstream BWA manual](https://bio-bwa.sourceforge.net/bwa.shtml) specifies bwtsw
for whole-human-genome indexing; its IS algorithm is unsuitable above 2 GB.
The implementation requires measured effective RAM of at least 16 GiB and
35 GiB free scratch before this build. These are conservative admission floors,
not measured resource results or a guarantee of completion. The observed Colab
allocation of approximately 50.99 GiB exceeds the RAM floor. No BWA-MEM2 full
index construction is permitted by this route.

The OCI manifest bytes for `quay.io/biocontainers/bwa:0.7.17--hed695b0_7` were
verified against SHA-256
`c3a708bea7947a44288e675fd9791c7aaf0c97dba0710addba336ed193821f8a`.
Its config bytes were verified against
`821f214d9847ceccf88d41b64bd445d9d72bdbc3df9e1992fd95f54ef98ce548` and declare
Linux/amd64. Canonical execution requires the exact `0.7.17-r1188` binary
self-report through the qualified runtime, actual full-reference construction,
and successful deterministic probes. A manifest pin is not an execution claim.
BWA is distributed under GPLv3; retain its license and citation. Historical M3
BWA-MEM2 synthetic qualification remains unchanged and does not qualify classic
BWA automatically. Both canonical callers consume the same resulting physical
BQSR BAM, preserving comparison symmetry.

`prepare_reference` verifies the pinned NCBI/GIAB compressed source and source
FAI MD5s. It streams all reference bases and compares all 195 contig MD5s to the
pinned provider dictionary, then independently constructs physical uncompressed
FAI offsets and a SAM dictionary. Compressed-source FAI offsets are not copied
onto the uncompressed reference. Source identities, full per-contig identity,
derivative hashes, and sampled alignment evidence remain separate fields.

The index reader probes six chromosomes (1, 2, 20, 21, 22, X), both orientations,
and three predeclared contexts: ordinary sequence, high GC, and a homopolymer
with diverse flanking sequence. Exact generated loci must be observed, including
secondary alignments if repeats produce additional hits. The 36 probes are
sampled compatibility evidence; complete base identity comes from streaming all
contig MD5s. Probe FASTQ/SAM bytes stay in private active scratch. Only coordinates,
context, strand, and hashes enter the index manifest. A probe failure requires
investigation and never licenses changing the acceptance rule to obtain a pass.

Independent BQSR inputs are the Broad GRCh38 dbSNP138, known-indels, and
Mills/1000G gold-standard indel VCFs and original TBI files. The installed contract
pins all six GCS generations, byte counts, and provider MD5s. The
[official GATK resource bundle](https://gatk.broadinstitute.org/hc/en-us/articles/360035890811-Resource-bundle)
is the source authority; GIAB truth is excluded. Source variants on contigs absent
from the no-alt reference are explicitly counted and removed, with no contig
renaming or caller-dependent filtering. Every retained REF allele and record
order is checked against the authenticated FASTA. Newly compressed derivatives
receive new TBI indexes and matching index record counts. No compatibility claim
is made until this has actually executed on the complete sources.

Durable publication uses
`cache/reference-assets/sha256/<reference-id>/<asset-id>/`. Only the fixed
validated payload inventory is copied. Every destination is rehashed, an
immutable run registry record is written, and `COMPLETED.json` is written last.
Hydration requires the complete marker, current tool/source contracts, exact
inventory, and fresh hashes; reference reuse also repeats complete base checks.
Partial assets cannot qualify a run. Active compute and extraction stay under
`/content`, outside Drive; the only durable root is the authorized project folder.

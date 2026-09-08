# Capture-design investigation, 2026-09-07

Current decision: ADR 0013 records owner approval of the fixed GENCODE v50 coding-domain alternative. Physical kit assignment remains unresolved; the historical capture investigation below does not override that approval. Canonical domain implementation/validation remains a separate gate.

The exact deposited Expanded Exome target file and its association with the
Garvan dataset are now established. The remaining uncertainty is narrower:
the inspected primary sources do not uniquely assign library NIST7035 to the
37 Mb Exome design or the 62 Mb Expanded Exome design. Canonical domain
construction remains fail-closed. This research does not select an estimand.

The [GIAB dataset README](https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data/NA12878/Garvan_NA12878_HG001_HiSeq_Exome/Garvan_NA12878_HG001_HiSeq_Exome.README)
names NIST7035 and NIST7086, describes Exome/Expanded Exome kits together, and
explicitly identifies the deposited Expanded Exome BED as the target file.
This is stronger evidence than a nearby filename. An [official GIAB repository
contributor's response](https://github.com/genome-in-a-bottle/giab_data_indexes/issues/2#issuecomment-324378470)
also directs users of the Garvan trimmed FASTQ index to that exact file.
Both the current index and its [2015 historical version](https://github.com/genome-in-a-bottle/giab_data_indexes/blob/a9b86cee05e63591924991d349609cc838b2636c/NA12878/sequence.index.NA12878_Illumina_HiSeq_Exome_Garvan_trimmed_fastq_09252015)
contain both libraries and both lanes. The response therefore supports the
dataset-level target recommendation without resolving the separate library
assignments.

| Observed artifact | Exact identity |
|---|---|
| Deposited `nexterarapidcapture_expandedexome_targetedregions.bed.gz` | 2,878,665 compressed bytes; SHA-256 `7ce7a9f769e51ecb8ab5588c6bc7c24d19e25b2bd6c1b958415b7b16987f01b8` |
| Fully expanded stream | 10,907,040 bytes; SHA-256 `13130066e4c50adcd2a8d1c14514aee3a80f8167881b9e64dab4e524c225f0c0` |
| BED structure | 201,071 valid four-column rows across 24 primary chromosomes; no assembly/header line |
| Union before liftover | 62,085,286 bases; 201,032 intervals after merging overlap and touching boundaries |

The compressed stream was read to EOF with gzip integrity checks. These are
locally observed SHA-256 identities; no independent published provider checksum
was found in the bounded investigation. That absence does not by itself demand
a laboratory lot number or a new vendor checksum as an additional gate.
The vendor file remains outside Git; only source identities and aggregate audit
findings are retained in [machine-readable evidence](orchestration/evidence/capture-design-investigation.json).

The [Illumina May 2015 datasheet](https://www.illumina.com/documents/products/datasheets/datasheet_nextera_rapid_capture_exome.pdf)
identifies NCBI37/hg19 and distinguishes the 37 Mb and 62 Mb products. Its
201,121 target-exon count and the BED's 201,071 rows are different, unreconciled
units; neither equality nor corruption is inferred from those counts. The
source coordinate system is supported by product documentation, rather than
inferred from coordinate bounds alone. A pinned source reference dictionary,
bounds validation and actual audited hg19-to-GRCh38 liftover remain necessary.

The [ENA experiment record](https://www.ebi.ac.uk/ena/browser/api/xml/SRX1608029)
has empty library-name and design-description fields. The [run record](https://www.ebi.ac.uk/ena/browser/api/xml/SRR3197785)
binds NIST7035, its barcode and lane 1 to the selected experiment, but supplies
no unique kit assignment. Its submitted-alignment assembly field is not a
capture-target dictionary. The [NIST-hosted original paper](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=917741)
describes Garvan Nextera rapid capture exome data without uniquely identifying
NIST7035 as Expanded Exome. No contributor was contacted, and no broader claim
that missing evidence cannot exist is made.

Before canonical benchmarking, the owner must review a concrete domain decision
if stronger per-library evidence remains unavailable. Adopting the deposited
62 Mb design would require explicitly retaining its assay-assignment uncertainty;
it must not be described as a newly confirmed physical assay. A fixed public
coding-exome domain is a different possible estimand and likewise requires the
specified owner approval and an ADR. Coverage-conditioned regions remain
secondary only. Neither option has been made canonical by this investigation.

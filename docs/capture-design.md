# Capture-design evidence and classification

**Classification: `unresolved`.** NCBI identifies SRX1608029 as “Nextera Garvan Institute Exome,” WXS, hybrid selection, paired HiSeq 2500, and binds SRR3197785 to NIST7035 lane 1. The GIAB index independently binds the original `NIST7035_TAAGGCGA_L001` FASTQ names and MD5 values. Neither primary record identifies an exact Nextera Rapid Capture Expanded Exome revision or target-file byte identity. The Illumina legacy download page is relevant vendor evidence, but it does not establish that missing sample-to-file link.

M2 therefore does not guess a target BED or substitute generic/modern exons. `config/m2-target-design.json` is the machine-readable gate and has `canonical_domains_allowed: false`. Canonical liftover, domain materialization, and Gate B publication are blocked until reviewed primary evidence justifies changing the classification to `confirmed` and locks a target checksum.

The implemented post-gate method converts 0-based half-open BED intervals with stable IDs to 1-based closed Picard interval lists, uses Picard 3.1.1 `LiftOverIntervalList` with `MIN_LIFTOVER_PCT=0.95` and the classic checksummed UCSC chain, retains rejects, validates destination coordinates, and only then sorts/merges. Synthetic tests cover the coordinate boundary. No truth, read depth, coverage, calls, or genotypes influence capture selection.

Evidence accessed 2026-09-03:

* [NCBI SRA SRX1608029](https://www.ncbi.nlm.nih.gov/sra/SRX1608029)
* [GIAB Garvan FASTQ index](https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_indexes/NA12878/sequence.index.NA12878_Illumina_HiSeq_Exome_Garvan_fastq_09252015)
* [Illumina Nextera Rapid Capture Exome downloads](https://support.illumina.com/sequencing/sequencing_kits/nextera-rapid-capture-exome-kit/downloads.html)

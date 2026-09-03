# Capture-design evidence and classification

**Classification: `unresolved`.** NCBI identifies SRX1608029 as “Nextera Garvan Institute Exome,” WXS, hybrid selection, paired HiSeq 2500, and binds SRR3197785 to NIST7035 lane 1. The GIAB index independently binds the original `NIST7035_TAAGGCGA_L001` FASTQ names and MD5 values. Neither primary record identifies an exact Nextera Rapid Capture Expanded Exome revision or target-file byte identity. The Illumina legacy download page is relevant vendor evidence, but it does not establish that missing sample-to-file link.

M2 therefore does not guess a target BED or substitute generic/modern exons. `config/m2-target-design.json` is the machine-readable gate and has `canonical_domains_allowed: false`. Canonical liftover, domain materialization, and Gate B publication are blocked until reviewed primary evidence justifies changing the classification to `confirmed` and populating `approved_artifacts` with the SHA-256 identities of both the target BED and its source sequence dictionary. The gate also binds the canonical Picard `MIN_LIFTOVER_PCT` value; command-line overrides cannot weaken it.

The implemented post-gate method converts 0-based half-open BED intervals with stable IDs to 1-based closed Picard interval lists, uses Picard 3.1.1 `LiftOverIntervalList` with `MIN_LIFTOVER_PCT=0.95` and the classic checksummed UCSC chain, retains rejects, validates destination coordinates, and only then sorts/merges. Synthetic tests cover the coordinate boundary. No truth, read depth, coverage, calls, or genotypes influence capture selection.

Evidence accessed 2026-09-03:

* [NCBI SRA SRX1608029](https://www.ncbi.nlm.nih.gov/sra/SRX1608029)
* [GIAB Garvan FASTQ index](https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_indexes/NA12878/sequence.index.NA12878_Illumina_HiSeq_Exome_Garvan_fastq_09252015)
* [Illumina Nextera Rapid Capture Exome downloads](https://support.illumina.com/sequencing/sequencing_kits/nextera-rapid-capture-exome-kit/downloads.html)
# Capture-design evidence and fail-closed decision

The NCBI SRA record for SRX1608029 identifies the experiment as **Nextera Garvan Institute Exome**, WXS, hybrid selection, paired Illumina HiSeq 2500; SRR3197785 is the NIST7035 lane-1 aligned submission. The GIAB sequence index independently binds the original `NIST7035_TAAGGCGA_L001` FASTQ pair and MD5 values. These records establish sample/lane lineage, but neither names a Nextera kit revision nor provides a vendor target-file byte identity.

Consequently M2 does **not** guess a vendor BED or silently substitute generic exons. Canonical execution is fail-closed until the owner supplies the archived, independently verified hg19 BED and chain as explicit `--target-hg19` and `--chain` inputs. `prepare_m2.py` records both SHA-256 identities, retains every unmapped interval, lifts intervals individually, filters to chr1–22/X, validates coordinates, then merges. This is the reproducible implementation of the locked target policy; the resulting hashes freeze `T_design`, `R_call`, `R_eval_full`, and `R_eval_holdout`. A target with undocumented product/revision is not canonical.

Evidence accessed 2026-09-03:

* [NCBI SRA SRX1608029 record](https://www.ncbi.nlm.nih.gov/sra/SRX1608029)
* [GIAB authoritative Garvan FASTQ index](https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_indexes/NA12878/sequence.index.NA12878_Illumina_HiSeq_Exome_Garvan_fastq_09252015)

No truth, genotypes, read depth, callable loci, or query calls participate in capture selection. If exact capture evidence cannot be obtained, acquisition may complete but domain construction and every downstream canonical analysis remain blocked.

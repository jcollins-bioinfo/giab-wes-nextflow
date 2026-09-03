# Capture-design evidence and fail-closed decision

The NCBI SRA record for SRX1608029 identifies the experiment as **Nextera Garvan Institute Exome**, WXS, hybrid selection, paired Illumina HiSeq 2500; SRR3197785 is the NIST7035 lane-1 aligned submission. The GIAB sequence index independently binds the original `NIST7035_TAAGGCGA_L001` FASTQ pair and MD5 values. These records establish sample/lane lineage, but neither names a Nextera kit revision nor provides a vendor target-file byte identity.

Consequently M2 does **not** guess a vendor BED or silently substitute generic exons. Canonical execution is fail-closed until the owner supplies the archived, independently verified hg19 BED and chain as explicit `--target-hg19` and `--chain` inputs. `prepare_m2.py` records both SHA-256 identities, retains every unmapped interval, lifts intervals individually, filters to chr1–22/X, validates coordinates, then merges. This is the reproducible implementation of the locked target policy; the resulting hashes freeze `T_design`, `R_call`, `R_eval_full`, and `R_eval_holdout`. A target with undocumented product/revision is not canonical.

Evidence accessed 2026-09-03:

* [NCBI SRA SRX1608029 record](https://www.ncbi.nlm.nih.gov/sra/SRX1608029)
* [GIAB authoritative Garvan FASTQ index](https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_indexes/NA12878/sequence.index.NA12878_Illumina_HiSeq_Exome_Garvan_fastq_09252015)

No truth, genotypes, read depth, callable loci, or query calls participate in capture selection. If exact capture evidence cannot be obtained, acquisition may complete but domain construction and every downstream canonical analysis remain blocked.

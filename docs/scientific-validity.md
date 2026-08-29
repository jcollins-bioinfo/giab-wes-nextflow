# Scientific validity boundaries

Canonical data/reference/domains and interpretation are stated in README. Physical preprocessing is planned as BWA-MEM2 → coordinate sort → mark duplicates without removal → BQSR → ApplyBQSR retaining OQ. Both callers receive identical BAM/BAI SHA identities.

Planned GATK: scattered HaplotypeCaller GVCFs, gather, GenotypeGVCFs, then frozen exome hard filters. Starting SNP thresholds: QD<2, QUAL<30, SOR>3, FS>60, MQ<40, MQRankSum<-12.5, ReadPosRankSum<-8. INDEL: QD<2, QUAL<30, FS>200, ReadPosRankSum<-20. M4 must verify against the pinned release, freeze before truth metrics, and define missing-annotation behavior in separate expressions. Planned DeepVariant 1.10.0 uses `run_deepvariant`, `model_type=WES`, native filters. Both retain native VCF/gVCF and provenance; one shared normalizer creates benchmark derivatives.

DeepVariant 1.10 WES training included 57 HG001 replicates. Full chr1–22 is descriptive/in-sample; chr20–22 was excluded from documented training but remains same-individual locus-held-out sensitivity. No scalar winner, superiority, generalization, or clinical claim. Denominators cannot be conditioned on depth/callability/query/genotype.

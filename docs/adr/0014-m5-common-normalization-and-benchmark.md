# ADR 0014: common normalization and diploid haplotype benchmarking

Date: 2026-09-08. Status: preregistered; implementation and synthetic execution
qualification are distinct. No canonical HG001 metrics have been inspected.

Use BCFtools 1.24 BioContainers digest
`a3e0d3007ffe325c409b398f660840a3e7574d076219c6e82fc994ced87d47c3`
and official RTG Tools 3.13 digest
`b53115f1646258c5bd7af1e884fd06f1eab70ebb4ebc1161fff1e5529e200790`.
Use direct `rtg vcfeval` diploid haplotype matching, split outputs, all records,
no ROC and two threads. No custom allele matcher or implicit alternate engine.
These are manifest-verified Linux/amd64 declarations, not execution results.
The current executable envelope admits synthetic references up to 64 MiB; this
bounded in-memory reference validator does not admit canonical GRCh38 execution.

Both query branches use `bcftools norm -f reference.fa -c e -m -any
--multi-overlaps 0 --old-rec-tag M5_ORIG`, followed by sorting and tabix indexing.
No atomization, REF repair, duplicate removal, contig rename, quality cutoff,
caller-specific FILTER policy or genotype substitution is permitted. Preserve
native VCF/index bytes. Validate exact reference bases, FAI offsets/order/length,
dictionary and optional MD5, VCF contig dictionary/order, single sample, genotype
allele indexes, duplicate alleles and full index-query agreement. Split records
retain native FILTER and source-record annotations. Include fully called diploid
nonreference genotypes symmetrically; count excluded reference/missing/non-diploid
records explicitly. Reject symbolic/ambiguous alleles. FORMAT annotations are
retained by BCFtools but are not treated as unchanged likelihood evidence.

Normalization tasks receive only query, reference and optional caller provenance.
Truth and domain data enter downstream benchmarking only. Benchmarking separately
normalizes a preserved truth copy under the same transformation and validates all
identities. The evaluation domain is the exact deterministic intersection of
predeclared 0-based half-open BED and confidence BED, with ordered, disjoint
intervals. Whole-reference VCF context remains available to RTG. Use
`--evaluation-regions` rather than input clipping; RTG includes boundary matches
while restricting assessed calls according to its documented evaluation-region
semantics. The separate `--ref-overlap` allele-overlap relaxation is not enabled. No domain depends on query records, depth, genotype or callability.

Count records directly in RTG's `tp`, `tp-baseline`, `fp`, and `fn` VCF partitions,
retaining query-side and truth-side TP separately. Classify biallelic length-one
substitutions as SNP and length-changing variants as INDEL; retain equal-length
complex substitutions as OTHER with a warning, never silently as indels. This is
representation-based stratification, not hap.py/GA4GH atomized event counting.
Precision is TP_query/(TP_query+FP); recall TP_truth/(TP_truth+FN); F1 is 2PR/(P+R).
Zero denominators produce null with reasons; defined P=R=0 gives F1=0. A zero-base
domain is not evaluated, with all metrics null. Out-of-domain records are excluded
from assessed counts by RTG and are not false positives. No overall winner or
clinical inference is permitted. Full HG001 remains descriptive/in-sample;
chr20–22 is same-individual locus-held-out sensitivity only.

Resource observations separate shared preprocessing, incremental callers, common
normalization/benchmarking and end-to-end run boundaries. Cached tasks cannot
substitute for executed cost. Synthetic timing qualifies instrumentation only;
canonical cost and accuracy remain null. Missing measurements remain explicit.

The M5 fixture is independently invented and versioned. Its preregistered counts
are SNP TP_query=TP_truth=4, FP=2, FN=2; INDEL TP_query=TP_truth=1, FP=FN=0.
Cases include isolated TP/FP/FN, homozygous alternate, genotype disagreement,
multiallelic versus split alleles, a shifted homopolymer insertion, and a SNP
outside a confidence boundary. Existing M3/M4 fixtures and strict oracles remain
unchanged. Actual M4 output integration qualifies only its SNV interface.

Primary method and immutable-manifest observations are in
[the focused source record](../m5-primary-sources.json). No image layers or genomic
artifacts were retrieved during method selection. Actual execution belongs to CI.

## Representation-overlap repair, 2026-09-08

CI34266895406 executed both tools successfully but rejected SNP counts3/3/3
against the unchanged4 TP,2 FP,2 FN oracle. The failed artifact preserved
summary hashes but omitted the actual partitions; locus attribution is therefore
a documentation-supported diagnosis pending direct partition confirmation.
BCFtools decomposition creates two heterozygous records at the same position.
RTG's default treats each reference allele as a no-change assertion, preventing
both split records from being selected together. Its documented `--ref-overlap`
mode admits reference-overlapping split representations while retaining diploid
matching. Use it symmetrically for query and truth. Keep the original fixture,
counts, genotype-mismatch FP/FN, confidence boundary, and indel oracle unchanged.
Do not use `--squash-ploidy`. Retain complete bounded synthetic partitions even
on failure so the next run can confirm this diagnosis.

Source: [RTG3.13 vcfeval overlap semantics](https://realtimegenomics.github.io/rtg-tools/rtg_command_reference.html#vcfeval),
accessed2026-09-08. This repair is not an observed engine pass.

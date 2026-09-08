# ADR 0012: single-sample caller execution and positive qualification

**Status:** accepted for M4 implementation, execution qualification pending (2026-09-07).

M3 required CI34103737524 qualified the actual invented-input preprocessing
workflow. Its accepted BAM/BAI and reference boundary is the sole upstream input
to M4. This decision does not approve a canonical HG001 domain.

## Caller and quality contracts

Use pinned GATK 4.7.0.0 HaplotypeCaller in direct VCF mode (`-ERC NONE`) for this
single-sample germline project. The native output contains raw calls. A gVCF
intermediate and cohort genotyping add no required cohort capability to v1;
raw VCFs from both callers will enter the same M5 normalization interface.
This is an implementation choice, not a claim of equivalence between direct
calling and every gVCF/genotyping configuration. Retain GATK's own native
annotations and filters; M5 must preregister any symmetric downstream policy.

The bounded M4 test uses one HaplotypeCaller task over the complete invented
reference, two native PairHMM threads, and an explicit calling-confidence
threshold of 30. No scatter is needed for 20 kb: additional partitions introduce
boundary and gathering obligations without useful parallel work. Canonical
scatter is deferred until the approved domain and measured execution plan can
justify it. No scatter/gather execution claim follows from this test.

Use the DeepVariant 1.10.0 CPU image and its bundled WES model at
`/opt/models/wes`. The image digest fixes the distributed model; additionally
record the actual model file inventory and SHA-256 identities inside that image.
Compare the bundled `model.example_info.json` with the independently retrieved
250-byte public metadata (SHA-256
`10a47721a3ea86f6c25bcabda3af5c31a936a3183847ac8a25857a709359187a`).
Do not invent unobserved weight checksums or claim native model redistribution
rights from the code license alone. Keep the image and weights outside Git.

The tiny test fixes one DeepVariant example shard, two declared CPUs, CPU
inference, and `postprocess_cpus=0`. Record all actual commands, stage outcomes,
runtime versions, model identities and observed resources. These settings are
identical in independent and `both` mode. Preserve the native VCF and auxiliary
gVCF with separate hashes; the common caller interface owns the native VCF.

ADR0003 remains authoritative. Both callers receive identical accepted physical
BAM/BAI/reference/calling-region identities. GATK consumes recalibrated QUAL;
DeepVariant explicitly receives `use_original_quality_scores=true` through
`make_examples_extra_args`. All original qualities, including unmapped reads,
must survive in OQ. The two callers therefore use different effective quality
views of the same file; this difference must accompany any later comparison.

## Fixture and isolation

Preserve the original M3 generator and expected hashes. Add a separately
registered, versioned CC0 invented fixture with the same 20 kb reference and
independent known sites. Its frozen expectation contains two strong SNV sites
(heterozygous and homozygous alternate), a reference control and the original
duplicate/unmapped/overlap cases. The package admits only exact registered
manifests and exact full read expectations. Sharing a reference hash does not
permit a different read recipe or an arbitrary self-hashed input.

The calling region is the complete two-contig reference, constructed from its
dictionary without using variants, coverage or expectations. It is an
integration-test scope, not a human WES evaluation denominator. Use actual
shared BWA-MEM2, duplicate marking, BaseRecalibrator and ApplyBQSR processing;
hand-assembled or separately spiked caller BAMs cannot satisfy this gate.

Materialize dedicated regular caller-input files after M3 acceptance. Caller
tasks copy those files into their task directory and run without network access.
Inspect actual Docker mounts: omitting an oracle from an input tuple is
insufficient if its parent directory remains mounted. Neither caller may access
fixture expectations, a benchmark/truth file, or a broad repository/fixture
directory. A separate post-call host oracle audits expected alleles and BAM
support. It never supplies requested alleles to a caller.

## Execution gate and limits

Detect actual Linux/x86_64, Docker, RAM, free disk, SSE4 and AVX support before
calling. Public image metadata supports only Linux/amd64. Apple Silicon native
execution, emulation, GPU and Colab container execution remain unqualified.
Fail early and route actual testing to the observed compatible Linux runner;
do not provision paid resources or call configuration an execution result.

Run independent GATK, independent DeepVariant, `both`, and resumed `both` with
one unchanged cache, source and parameter identity. Require upstream reuse,
identical caller parameters, byte identities and native call semantics. Require
actual nonzero DeepVariant candidate examples **and** inference records with
valid probabilities, plus the frozen native SNV/genotype expectations and
reference control. Empty-candidate success, version/help commands or stubs
cannot qualify neural inference. Preserve raw trace, cache state and independent
assertions. These integration runs do not estimate comparative caller cost.

M4 may be verified only after both branches actually pass these tests in a
supporting environment and required CI is green. This initial fixture qualifies
SNV integration; it does not establish end-to-end indel accuracy, HG001 accuracy,
generalization, empirical BQSR adequacy or canonical execution. DeepVariant's
documented 57 HG001 WES training replicates and chr20–22 exclusions preserve
ADR0004's descriptive/in-sample and same-individual locus-holdout limitations.

## Evidence

- [Pinned HaplotypeCaller source](https://github.com/broadinstitute/gatk/blob/0cde69eed30339f5978cbb1ac6e5cf3662f9e1f8/src/main/java/org/broadinstitute/hellbender/tools/walkers/haplotypecaller/HaplotypeCaller.java)
- [Pinned DeepVariant runner](https://github.com/google/deepvariant/blob/d6b15e21323d9d15b347083f1d256ad62998c4cf/scripts/run_deepvariant.py)
- [Pinned training data](https://github.com/google/deepvariant/blob/d6b15e21323d9d15b347083f1d256ad62998c4cf/docs/deepvariant-details-training-data.md)
- [Source inventory](../orchestration/evidence/m4-primary-sources.json),
  [container declaration](../orchestration/evidence/m4-container-declaration.json),
  [public WES metadata](../orchestration/evidence/m4-wes-model-metadata.json)
- [Authoritative caller lock](../../config/m4-tools.json)

# ADR 0011: Qualify shared preprocessing with invented data and explicit real-data gates

Status: accepted for synthetic implementation; canonical execution remains blocked.

Author: John Patrick Collins. Date: 2026-09-07.

## Context

M2.1.1 required CI passed at `22d01b202e15bb098e9d42d0ad4a98606e78c2c2`.
The retained source mirror does not prove current byte verification or reference
preparation. The exact capture design is unresolved, and the canonical M2 source
manifest contains no independently sourced BQSR known-sites set. GIAB benchmark
truth is forbidden as a BQSR input. These limitations permit synthetic M3
qualification but prevent canonical HG001 preprocessing acceptance.

## Decision

Keep foundation contract execution as a separate default mode. Add a synthetic
mode that accepts only the installed package's byte-bound invented recipe and a
canonical mode that fails before biological tasks while required resources and
domain decisions remain unresolved. The test recipe uses a SHA-256 counter to
invent two contigs, paired reads across two lanes sharing one library/sample,
known duplicate fragments, overlapping mates, unmapped reads, and independent
invented known sites. It contains no copied human or other external sequence.
Generated files stay outside Git; the recipe dedicates its generated data to CC0.

The shared transformation is BWA-MEM2 per lane, coordinate sort per lane, sample
merge, GATK's Picard MarkDuplicates with duplicate reads retained, BaseRecalibrator,
ApplyBQSR with original qualities emitted as OQ, and final indexing/acceptance.
The pipeline emits one final BAM/BAI channel. M3 includes no caller or benchmark
tasks. The single-sample fixture tests cross-lane library/duplicate behavior;
it does not qualify cohorts or large-reference capacity.

Preserve ADR 0003: GATK will consume recalibrated QUAL and DeepVariant will consume
original OQ through an explicitly checked M4 flag. The BAM bytes are shared, but
the effective quality evidence differs. Comparing these documented caller paths
does not isolate an algorithm effect with identical quality inputs. The tiny
fixture validates recalibration plumbing and OQ preservation; it cannot establish
the empirical quality or benefit of real-data recalibration.

Run raw FastQC without trimming the adapter-free fixture. Trimming remains
disabled; this is not an empirical judgment about HG001 reads. Collect samtools
alignment/index/count summaries and Picard duplicate metrics. Picard duplicate
metrics add library-level evidence; a second duplicate algorithm is unnecessary.
Use mosdepth's normal overlap/CIGAR handling on fixed reference windows. Those
windows are target-independent QC summaries and cannot become calling/evaluation
intervals. CollectHsMetrics and target-aware acceptance remain blocked by the
missing authoritative bait/target design. MultiQC aggregates explicit inputs;
it does not own scientific calculations.

Six versioned JSON result artifacts carry input/output hashes, observed tool
versions, immutable image declarations, resource declarations, missingness,
reference/BAM lineage, and explicit synthetic status. Measured Nextflow traces
are retained separately by the integration driver. Requested resources are never
substituted for observed CPU time or memory. M5 will own normalized caller cost
measurements and their comparison boundary.

## Qualification and implications

A clean-clone Linux/x86_64 Docker run and a subsequent `-resume` run must validate
the actual BAM invariants, installed package identity, complete task reuse, and
output identity. Python tests exercise parsers, paths, schema/semantic failures,
corruption and interrupted evidence publication. nf-test/stub execution checks
workflow wiring, never biological correctness. A framework command on macOS
ARM64 is not a biological-tool or DeepVariant architecture qualification.

Tool identities are owned by `config/m3-tools.json` and its identical packaged
copy. Registry manifest/platform observations are distinct from executed tool
versions. CI success must be recorded before M3 becomes `verified`; only actual
HG001 evidence can support `canonically_executed`.

## Sources

- [GATK BaseRecalibrator at the selected release commit](https://github.com/broadinstitute/gatk/blob/0cde69eed30339f5978cbb1ac6e5cf3662f9e1f8/src/main/java/org/broadinstitute/hellbender/tools/walkers/bqsr/BaseRecalibrator.java)
- [GATK ApplyBQSR at the same commit](https://github.com/broadinstitute/gatk/blob/0cde69eed30339f5978cbb1ac6e5cf3662f9e1f8/src/main/java/org/broadinstitute/hellbender/tools/walkers/bqsr/ApplyBQSR.java)
- [BWA-MEM2 v2.3 source](https://github.com/bwa-mem2/bwa-mem2/blob/7aa5ff6c3330490e5629ab9b7327683d2dce02d6/README.md)
- [mosdepth v0.3.14 source](https://github.com/brentp/mosdepth/blob/821fddb12860d024fef4cf0bfe86918f2413d4e4/README.md)
- [Picard metrics documentation](https://broadinstitute.github.io/picard/command-line-overview.html)

Accessed 2026-09-07. Further registry/release identities appear in the source
ledger and `docs/orchestration/evidence/m3-container-declarations.json`.

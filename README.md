[![CI](https://github.com/jcollins-bioinfo/giab-wes-nextflow/actions/workflows/ci.yml/badge.svg)](https://github.com/jcollins-bioinfo/giab-wes-nextflow/actions/workflows/ci.yml)
# GIAB¹ HG001 WES: Dual-caller Benchmark and Evidence Explorer

Canonical continuation now has an exact-SHA Colab Run-all launcher, full-reference
classic BWA0.7.17 fallback, independent Broad BQSR assets, gated GATK/DeepVariant
execution, common benchmarking, fixed-domain coverage, durable restart, and a
validated canonical Explorer interface. **Real HG001 chr20–22 results remain
pending actual Colab qualification and execution.** M5 is synthetically verified.
See [canonical execution](docs/canonical-analysis.md), [notebooks](notebooks/README.md)
and [release readiness](docs/release-candidate-readiness.md). No release or new
public deployment is claimed.


> **Synthetic Dash prototype available; real HG001 results pending.** The owner approved the fixed GENCODE v50 coding-domain alternative and early synthetic prototype (ADR 0013). M3 synthetic preprocessing and M5 common benchmarking are synthetically verified; M5 retained CI34270789172 and post-merge CI34272289311 passed. M4 is synthetically verified on merged main `f29ed262b886ba4afe18cf9cc6455edcf13df808`: CI 34237377774 passed actual GATK/DeepVariant execution, independent/both equivalence and resume. The prior RefCall failure is historical. [Run the explorer](explorer/README.md) and [prepare the Colab capability observation](docs/canonical-colab.md). Index construction will use Colab CPU/RAM with durable large storage in the permitted private Drive hierarchy. No canonical run or public deployment is claimed.
>
> ¹ <sub>See: **NIST GIAB ([*Genome in a Bottle*](https://www.nist.gov/programs-projects/genome-bottle))</sub>**

## AWS cloud implementation

A separate direct-container cloud DAG, quota-aware preflight, identity-bound
HealthOmics packaging, bounded Terraform infrastructure and Explorer image are
implemented. Cloud execution and canonical public-bundle qualification remain
pending. HealthOmics currently documents Nextflow26.04.0, below this repository's
26.04.6 minimum. Seven project service IAM roles were bootstrapped separately;
compute, storage and serving infrastructure were not deployed. See the
[AWS execution guide](docs/aws-cloud.md) for exact gates, authentication,
Terraform imports, quota handling and the deployment sequence.

## Motivation and architecture

The project preregisters a reproducible comparison of GATK HaplotypeCaller and DeepVariant WES from one analysis-ready BAM while keeping truth out of caller environments.

```text
lane-aware FASTQs → shared BWA-MEM2/sort/markdup/BQSR BAM (+ OQ)
                    ├─ GATK ───────┐
                    └─ DeepVariant ├→ shared normalization → GIAB benchmarking
Nextflow canonical run → immutable evidence → tested Python model → Dash renderer
```

Synthetic shared preprocessing and its typed Python evidence boundary passed local tests and actual Linux/x86_64 Docker CI. Caller branches passed actual Linux/x86_64 Docker synthetic qualification in M4; canonical benchmarking and completion of M8 require later gates; the owner-approved synthetic Dash prototype is available now. ONT and somatic workflows are outside v1.

## Foundation quick start (synthetic, nonhuman fixture only)

```bash
python tests/data/generate_fixture.py
python scripts/validate_contracts.py
nextflow run . -profile test,docker
python -m unittest discover -s tests/unit -v
```

The samplesheet is lane-aware (`sample,library,lane,read_group_id,platform_unit,fastq_1,fastq_2`, optional `sequencing_center`); identifiers are URL-safe, IDs unique, mates distinct/readable gzip FASTQs, and platform is fixed to `ILLUMINA`. `--callers` accepts `gatk`, `deepvariant`, or `both` (default), but foundation and M3 preprocessing invoke neither.

## M3 shared-preprocessing qualification

The synthetic mode validates the exact invented paired-read/reference/known-sites
recipe, raw FastQC, lane-aware BWA-MEM2 alignment, coordinate sorting, sample
merge, retained duplicate marking, BQSR with original OQ, final BAM/BAI acceptance,
samtools/Picard summaries, fixed-window mosdepth coverage and explicit MultiQC
aggregation. It produces one shared BAM at `<outdir>/m3/SYNTHETIC01.analysis-ready.bam`
and six typed JSON evidence artifacts under `<outdir>/m3/contracts/`.
The tiny BQSR fixture tests wiring and quality preservation, not empirical
calibration performance. See [the M3 decision](docs/adr/0011-m3-synthetic-shared-preprocessing.md).

Tool provenance separates the distribution release from the executable's actual
version report. The pinned BWA-MEM2 2.3 distribution reports `2.2.1`, matching its
release-source fallback; the collector requires that exact report and the
unchanged image digest. Both identities and their evidence are retained in
provenance schema 2.0.0. Older provenance is rejected rather than upgraded.
See [data contracts](docs/data-contracts.md) and the
[observed version discrepancy](docs/orchestration/evidence/m3-ci-attempt-4.json).

From a clean reviewed checkout on Linux/x86_64 with working Docker, Python and
Nextflow 26.04.6/Java 17:

```bash
python scripts/run_m3_synthetic.py --mode preflight \
  --output-root /tmp/giab-m3-check --expected-sha "$(git rev-parse HEAD)"
python scripts/run_m3_synthetic.py --mode docker \
  --output-root /tmp/giab-m3-integration --expected-sha "$(git rev-parse HEAD)"
```

The driver makes a fresh clone, binds the installed package to the requested
commit, generates invented inputs, runs real tools, validates actual BAM/index
invariants, and requires a subsequent `-resume` run to reuse upstream tasks and
preserve results. Its uploadable `evidence/` directory contains small reports;
local generated genomic files and `work/` remain separate. `--mode stub` tests
workflow wiring without establishing biological execution. See
[testing](docs/testing.md), [execution matrix](docs/execution-matrix.md), and
[publication/recovery](docs/m3-evidence-publication.md).

The synthetic fixture is 24 pairs across two lanes and two invented contigs
(20,000 bases). Tool images dominate storage, including about 2.49 GB compressed
GATK layers; allow at least 10 GiB free for image/runtime/test headroom. This
estimate is for the tiny integration test, not full-reference HG001 alignment.

`--workflow_mode m3_canonical` fails closed. No exact real known-sites manifest,
prepared reference or validated canonical domain implementation is established. The fixed coding-domain alternative is owner-approved under ADR 0013. Synthetic
reference windows are QC intervals and cannot serve as the primary evaluation
domain. Neither caller executes in M3. Future GATK consumes recalibrated QUAL;
future DeepVariant consumes OQ, so identical BAM bytes do not imply identical
effective quality evidence.

## M4 dual-caller qualification

The `m4_synthetic` workflow accepts `--callers gatk`, `--callers deepvariant`,
or `--callers both`. It uses the same accepted BAM/BAI, reference and fixed
full-contig calling region in all modes. GATK HaplotypeCaller 4.7.0.0 emits a
direct native VCF using recalibrated QUAL. DeepVariant 1.10.0 uses its CPU WES
model and explicitly consumes OQ. Their effective quality evidence differs,
as recorded in [ADR 0003](docs/adr/0003-shared-bam-oq.md) and
[the M4 execution decision](docs/adr/0012-m4-caller-execution-and-qualification.md).

The separate [M4 fixture](tests/data/m4/README.md) has 264 invented read pairs,
two expected SNVs and a reference control. The original M3 fixture is unchanged.
Caller tasks contain seven explicit regular files, mount only their task
directory and run without network access. The independent qualification driver
checks the actual mounted copies and requires positive candidate and inference
records tied to the pinned WES model, indexed native outputs, matching independent
and both-mode results, and complete resume reuse.

From a clean committed checkout on Linux/x86_64 with Docker, SSE4.1/SSE4.2/AVX,
Python and Nextflow 26.04.6/Java 17:

```bash
python scripts/run_m4_synthetic.py --mode preflight \
  --output-root /tmp/giab-m4-check --expected-sha "$(git rev-parse HEAD)"
python scripts/run_m4_synthetic.py --mode docker \
  --output-root /tmp/giab-m4-integration --expected-sha "$(git rev-parse HEAD)"
```

The synthetic driver requires at least two Docker CPUs, 12 GiB engine memory
and 30 GiB free before preparing images. These are tiny-test prerequisites,
not a canonical HG001 resource estimate. Local macOS/ARM tests qualify Python
and framework behavior; real DeepVariant execution there remains unsupported
by this project. M4 passed required Linux Docker CI 34237377774 on merged main.

Historical failed attempts, including the original DeepVariant RefCall, remain
preserved under `docs/orchestration/evidence/m4-ci-attempt-*.json`. Merged repairs
staggered invented heterozygous support without changing expected alleles or
genotypes, and fixed process-name parsing around Nextflow display tags. Existing
main CI 34237377774 passed the strict native-call, inference, isolation,
independent/both equivalence and resume acceptance. This reconciliation does not
constitute new biological execution. See [the verified M4 checkpoint](docs/orchestration/checkpoints/M4.json).

Each selected caller emits a versioned pre-normalization JSON contract, with
input/output hashes, image/version/model identity, exact parameters and task
resources. Only validated small JSON contracts enter the guarded
[M4 evidence publisher](docs/m4-evidence-publication.md). See
[actual integration acceptance](tests/integration/M4.md) for the complete gate.
This fixture establishes no indel accuracy, canonical domain, HG001 benchmark
or compute-cost comparison; those belong to M5 and later execution.

## Scientific plan and claim boundary

The canonical input is original paired Garvan HiSeq 2500 `NIST7035_TAAGGCGA_L001` FASTQ fetched directly from GIAB; SRR3197785/SRX1608029/SRP012400/PRJNA162355 are lineage only, not an SRA substitute. The reference is `GCA_000001405.15_GRCh38_no_alt_analysis_set` and truth is GIAB v4.2.1.

Under owner-approved ADR 0013, `T_design` is the fixed GENCODE v50 Basic protein-coding CDS plus stop-codon union; `R_call = merge(pad(T_design,100)) ∩ chr1-22,X`; `R_eval_full = HC ∩ T_design ∩ chr1-22`; `R_eval_holdout = R_eval_full ∩ chr20-22`. Denominators never depend on depth, callable/query calls, or genotypes. Full results are descriptive/in-sample because DeepVariant 1.10 WES training included HG001 replicates. Chr20–22 is only a same-individual locus-held-out sensitivity—not generalization. No winner, superiority, clinical, or scalar-ranking claim is allowed.

## Baseline and current execution limits

| Item | Evidence/status |
|---|---|
| M2.1.1 recovery Python 3.12/3.13, wheel and synthetic foundation CI | [Required CI passed](https://github.com/jcollins-bioinfo/giab-wes-nextflow/actions/runs/34094504379) at `22d01b202e15bb098e9d42d0ad4a98606e78c2c2`; 104 Python tests per environment |
| Nextflow 26.04.6 minimum, Java ≥17 | CI contract; local status reported honestly |
| nf-core/tools 4.1.0, nf-schema 2.8.0, nf-test 0.9.5 | Pinned CI/tooling contracts |
| M3 BWA-MEM2, GATK preprocessing and QC | [Verified synthetic Docker execution and resume](docs/orchestration/evidence/m3-verified.json); no canonical HG001 result |
| GATK HaplotypeCaller and DeepVariant WES | M4 synthetic SNV qualification passed required CI 34237377774 |
| DeepVariant linux/amd64 CPU (AVX) and GPU images | CPU image synthetically verified; GPU image configured only |
| ARM64/Apple Silicon | Python tests and framework version commands executed; M3 biological containers and DeepVariant unqualified |
| Source-cache control record | Ten objects reported, 4,900,011,445 bytes; metadata observed, fresh byte rehash pending |
| Reference preparation / real HG001 workflow / callers | No immutable canonical execution evidence established |
| Colab | Owner-supplied capability report consistency-checked; 50.99 GiB, no Docker; canonical runtime unqualified |
| SLURM, Seqera/Wave | Not executed |
| Dash | Local synthetic prototype; not deployed |

## Data and private-workspace policy

Only the deterministic, explicitly synthetic nonhuman FASTQ fixture recipe is public; the gzip files are materialized locally so repository reviews remain text-only. Human FASTQ/BAM/VCF/reference/truth/vendor data are forbidden in Git. The guarded [M3 evidence publisher](docs/m3-evidence-publication.md) copies only six validated small JSON files to a content-addressed synthetic namespace. M2 reusable source caches and future canonical results have separate paths and acceptance rules. Drive is never a Nextflow work directory. See [private workspace](docs/private-workspace.md).

## Roadmap and limitations

M1 foundation and architecture; M2 data and provenance; M3 FASTQ QC, alignment, preprocessing, and alignment/coverage QC; M4 independently selectable GATK HaplotypeCaller and DeepVariant WES callers; M5 common GIAB benchmarking and explicit caller accuracy-versus-resource comparison; M6 operational hardening, Seqera observability, and cloud/HPC profiles; M7 comprehensive QA, canonical execution, reproducibility audit, and v1.0 release; M8 Plotly Dash Pipeline Evidence Explorer and deployment; M9 website research showcase and final claim/reproducibility audit. See [milestones](docs/milestones.md), [architecture](docs/architecture.md), [contracts](docs/data-contracts.md), and [scientific validity](docs/scientific-validity.md). This is an external, unbranded nf-core-inspired structure—not an official nf-core pipeline or Sarek replacement.

Authoritative sources and access dates are recorded in [`docs/source-ledger.yaml`](docs/source-ledger.yaml).

## M2 canonical data driver

`config/m2-resources.json` locks the one HG001 lane, exact GRCh38 source and GIAB v4.2.1 truth resources. Install the repository as a Python package before using console commands:

```bash
python -m pip install .
giab-wes-acquire-m2 --preflight-only --workspace /path/to/m2-stage
# Only if verified cache recovery is unavailable, choose a deliberate run ID:
giab-wes-acquire-m2 --workspace /path/to/m2-stage --run-id m2-YYYYMMDDTHHMMSSZ
```

Partial downloads resume; completed bytes are verified before reuse. Use the [Colab launch center](notebooks/README.md) and [recovery runbook](docs/m2-recovery.md) to reuse the observed source cache. The primary source inventory is about 4.9 GB. No large acquisition was performed during the recovery audit. Human and large reference bytes remain private and outside Git.

M2 distinguishes implementation readiness from canonical data readiness. **Gate A** provides strict source contracts, synthetic downloader/domain tests, and private-workspace tooling. **Gate B has not run:** the owner approved the fixed GENCODE v50 coding-domain alternative in ADR 0013. Its deterministic canonical implementation and reference/BQSR validation remain pending. The unresolved physical capture-kit assignment is retained as historical uncertainty and does not revoke the approved alternative. See [M2 operations](docs/m2-data-provenance.md), the machine-readable [target decision](config/m2-target-design.json), and [ADR 0008](docs/adr/0008-m2-canonical-data.md). The [source-cache metadata audit](docs/orchestration/evidence/source-cache-metadata.json) documents the observed older mirror. It does not establish preparation, a qualified Colab/container environment or canonical domains.

## Colab launch

Use the [notebook launch center](notebooks/README.md) or open M2 directly:
[![Open M2 in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jcollins-bioinfo/giab-wes-nextflow/blob/main/notebooks/m2_colab.ipynb). The launcher records the resolved commit and keeps canonical Gate B fail-closed.

## M2.1 package and readiness boundary

Version `0.2.0-dev.3` established `src/giab_wes_nextflow/` the sole M2 implementation; the retained `scripts/*_m2.py` files only preserve historical command paths. Development dependencies are declared in `requirements-dev.in`, with the reviewed pinned direct set mirrored in `requirements-dev.txt`; CI installs that file before building both distributions and tests the wheel outside the checkout.

Version `0.2.0-dev.4` repairs observed path, identity and restart defects. From a clean reviewed checkout, run `scripts/run_m2_readiness.sh identity` for zero-install identity verification, then `scripts/run_m2_readiness.sh verify` for package installation and local code verification. Data modes (`preflight`, `acquire`, `hydrate`, and `mirror`) are explicit and require a reusable `RUN_ID`. Mirroring is only a durable, rehashed source cache: it cannot create `COMPLETED.json`, satisfy capture-design Gate B, or authorize canonical publication. The exact deposited target bytes are now recorded; their unique per-library assay assignment remains unresolved; canonical analysis instead uses the approved coding-domain alternative once its implementation is validated. Historical Drive mirror metadata is observed; fresh hydration verification and all canonical biological execution remain separate evidence gates. M3 is synthetically verified after the recovery gate. M4 is synthetically verified on merged main; M5 is synthetically verified from retained CI; canonical execution retains its own gates.

## M5 synthetically verified

Version `0.5.0-dev.1` adds common BCFtools normalization, direct RTG vcfeval
benchmarking, schema-validated Python count/metric artifacts and typed resource
attribution. [ADR 0014](docs/adr/0014-m5-common-normalization-and-benchmark.md)
preregisters the policy and immutable tools. `m5.nf -profile m5_test` is a
synthetic-only downstream workflow; truth stays outside normalization. Actual
engine qualification uses the bounded driver in the existing M4 CI job.
Retained [CI34270789172 evidence](docs/orchestration/evidence/m5-verified-34270789172.json)
qualifies actual BCFtools 1.24/RTG 3.13 execution, split representations, isolation,
independent/both equivalence and full resume. Post-merge main CI34272289311 passed
on the identical tested source tree. M5 is synthetically verified. Canonical HG001 accuracy, cost and clinical/generalization
claims remain unavailable. Approved coding-domain construction is locally reproduced as described below;
reusable-index qualification remains deferred and Colab is still unqualified.

### M5 continuation

CI34266895406 passed M4 caller execution but rejected M5 SNP counts. The repair
adds RTG reference-overlap handling for decomposed records while preserving the
4TP/2FP/2FN oracle and diploid genotype mismatch tests. Duplicate JSON keys now
fail before task launch. The actual Nextflow independent/both/resume qualification
helper passed in CI34270789172: independent GATK and DeepVariant modes each
executed two tasks; both-mode and resume each reused four. Both queries match
the frozen SNP4TP/2FP/2FN and indel1TP/0FP/0FN expectations. Retained traces
qualify resource parsing and cache attribution, not canonical caller cost.

The package-owned `python -m giab_wes_nextflow.coding_domain` constructor reproduced
all three ADR0013 domain hashes from the exact pinned inputs in memory. Its
optional output writes verified BEDs and a completion record last. It does not
qualify reference bases, a Colab runtime or canonical execution. The restart-safe
reusable-index notebook remains deferred.

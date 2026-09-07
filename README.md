# GIAB HG001 WES: dual-caller benchmark and evidence explorer

> **M3 shared preprocessing — version 0.3.0-dev.1, implemented; required synthetic Docker CI pending.** M2.1.1 recovery passed required CI at `22d01b202e15bb098e9d42d0ad4a98606e78c2c2` and remains draft PR #19. This dependent branch adds synthetic shared-BAM qualification. Real HG001, independent known-sites compatibility and capture-dependent execution remain gated. See the [observed state](docs/orchestration/project-state.json), [implementation plan](docs/orchestration/implementation-plan.md), and [claim ledger](docs/claim-ledger.yaml).

## Motivation and architecture

The project preregisters a reproducible comparison of GATK HaplotypeCaller and DeepVariant WES from one analysis-ready BAM while keeping truth out of caller environments.

```text
lane-aware FASTQs → shared BWA-MEM2/sort/markdup/BQSR BAM (+ OQ)
                    ├─ GATK ───────┐
                    └─ DeepVariant ├→ shared normalization → GIAB benchmarking
Nextflow canonical run → immutable evidence → tested Python model → Dash renderer
```

Synthetic shared preprocessing and its typed Python evidence boundary are implemented and locally tested. Caller branches, benchmarking and Dash remain later milestones. ONT and somatic workflows are outside v1.

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
prepared reference or approved capture-dependent domain is established. Synthetic
reference windows are QC intervals and cannot serve as the primary evaluation
domain. Neither caller executes in M3. Future GATK consumes recalibrated QUAL;
future DeepVariant consumes OQ, so identical BAM bytes do not imply identical
effective quality evidence.

## Scientific plan and claim boundary

The canonical input is original paired Garvan HiSeq 2500 `NIST7035_TAAGGCGA_L001` FASTQ fetched directly from GIAB; SRR3197785/SRX1608029/SRP012400/PRJNA162355 are lineage only, not an SRA substitute. The reference is `GCA_000001405.15_GRCh38_no_alt_analysis_set` and truth is GIAB v4.2.1.

`T_design` is individually lifted/audited/merged/unpadded; `R_call = merge(pad(T_design,100)) ∩ chr1-22,X`; `R_eval_full = HC ∩ T_design ∩ chr1-22`; `R_eval_holdout = R_eval_full ∩ chr20-22`. Denominators never depend on depth, callable/query calls, or genotypes. Full results are descriptive/in-sample because DeepVariant 1.10 WES training included HG001 replicates. Chr20–22 is only a same-individual locus-held-out sensitivity—not generalization. No winner, superiority, clinical, or scalar-ranking claim is allowed.

## Baseline and current execution limits

| Item | Evidence/status |
|---|---|
| M2.1.1 recovery Python 3.12/3.13, wheel and synthetic foundation CI | [Required CI passed](https://github.com/jcollins-bioinfo/giab-wes-nextflow/actions/runs/34094504379) at `22d01b202e15bb098e9d42d0ad4a98606e78c2c2`; 104 Python tests per environment |
| Nextflow 26.04.6 minimum, Java ≥17 | CI contract; local status reported honestly |
| nf-core/tools 4.1.0, nf-schema 2.8.0, nf-test 0.9.5 | Pinned CI/tooling contracts |
| M3 BWA-MEM2, GATK preprocessing and QC | Implemented on this branch; synthetic Docker qualification pending |
| GATK HaplotypeCaller and DeepVariant WES | M4 caller branches not implemented or executed |
| DeepVariant linux/amd64 CPU (AVX) and GPU images | Configured immutable contracts; not tested |
| ARM64/Apple Silicon | Python tests and framework version commands executed; M3 biological containers and DeepVariant unqualified |
| Source-cache control record | Ten objects reported, 4,900,011,445 bytes; metadata observed, fresh byte rehash pending |
| Reference preparation / real HG001 workflow / callers | No immutable canonical execution evidence established |
| Cloud, SLURM, Seqera/Wave, Dash | Not executed |

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

M2 distinguishes implementation readiness from canonical data readiness. **Gate A** provides strict source contracts, synthetic downloader/domain tests, and private-workspace tooling. **Gate B has not run and is blocked:** the public metadata does not bind this library to an exact capture-design target file. See [M2 operations](docs/m2-data-provenance.md), the machine-readable [target decision](config/m2-target-design.json), and [ADR 0008](docs/adr/0008-m2-canonical-data.md). The [source-cache metadata audit](docs/orchestration/evidence/source-cache-metadata.json) documents the observed older mirror. It does not establish preparation, a qualified Colab/container environment or canonical domains.

## Colab launch

Use the [notebook launch center](notebooks/README.md) or open M2 directly:
[![Open M2 in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jcollins-bioinfo/giab-wes-nextflow/blob/main/notebooks/m2_colab.ipynb). The launcher records the resolved commit and keeps canonical Gate B fail-closed.

## M2.1 package and readiness boundary

Version `0.2.0-dev.3` established `src/giab_wes_nextflow/` the sole M2 implementation; the retained `scripts/*_m2.py` files only preserve historical command paths. Development dependencies are declared in `requirements-dev.in`, with the reviewed pinned direct set mirrored in `requirements-dev.txt`; CI installs that file before building both distributions and tests the wheel outside the checkout.

Version `0.2.0-dev.4` repairs observed path, identity and restart defects. From a clean reviewed checkout, run `scripts/run_m2_readiness.sh identity` for zero-install identity verification, then `scripts/run_m2_readiness.sh verify` for package installation and local code verification. Data modes (`preflight`, `acquire`, `hydrate`, and `mirror`) are explicit and require a reusable `RUN_ID`. Mirroring is only a durable, rehashed source cache: it cannot create `COMPLETED.json`, satisfy capture-design Gate B, or authorize canonical publication. The exact capture-design bytes remain unresolved. Historical Drive mirror metadata is observed; fresh hydration verification and all canonical biological execution remain separate evidence gates. M3 is locally implemented after the verified recovery gate; M4–M9 checkpoints remain not started until their prerequisites pass.

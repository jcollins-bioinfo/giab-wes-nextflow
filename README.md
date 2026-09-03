[![CI](https://github.com/jcollins-bioinfo/giab-wes-nextflow/actions/workflows/ci.yml/badge.svg)](https://github.com/jcollins-bioinfo/giab-wes-nextflow/actions/workflows/ci.yml)

# GIAB HG001 WES: dual-caller benchmark and evidence explorer

> **Milestone 2 — data and provenance.** This repository now provides checksum-gated canonical acquisition, reference preparation, target liftover, and frozen domain construction. It performs no read processing, variant calling, or benchmarking.

## Motivation and architecture

The project preregisters a reproducible comparison of GATK HaplotypeCaller and DeepVariant WES from one analysis-ready BAM while keeping truth out of caller environments.

```text
lane-aware FASTQs → shared BWA-MEM2/sort/markdup/BQSR BAM (+ OQ)
                    ├─ GATK ───────┐
                    └─ DeepVariant ├→ shared normalization → GIAB benchmarking
Nextflow canonical run → immutable evidence → tested Python model → Dash renderer
```

The biological processes and Python/Dash layers are planned, not implemented. ONT and somatic workflows are outside v1.

## Foundation quick start (synthetic, nonhuman fixture only)

```bash
python tests/data/generate_fixture.py
python scripts/validate_contracts.py
nextflow run . -profile test,docker
python -m unittest discover -s tests/unit -v
```

The samplesheet is lane-aware (`sample,library,lane,read_group_id,platform_unit,fastq_1,fastq_2`, optional `sequencing_center`); identifiers are URL-safe, IDs unique, mates distinct/readable gzip FASTQs, and platform is fixed to `ILLUMINA`. `--callers` accepts `gatk`, `deepvariant`, or `both` (default), but M1 invokes neither.

## Scientific plan and claim boundary

The canonical input is original paired Garvan HiSeq 2500 `NIST7035_TAAGGCGA_L001` FASTQ fetched directly from GIAB; SRR3197785/SRX1608029/SRP012400/PRJNA162355 are lineage only, not an SRA substitute. The reference is `GCA_000001405.15_GRCh38_no_alt_analysis_set` and truth is GIAB v4.2.1.

`T_design` is individually lifted/audited/merged/unpadded; `R_call = merge(pad(T_design,100)) ∩ chr1-22,X`; `R_eval_full = HC ∩ T_design ∩ chr1-22`; `R_eval_holdout = R_eval_full ∩ chr20-22`. Denominators never depend on depth, callable/query calls, or genotypes. Full results are descriptive/in-sample because DeepVariant 1.10 WES training included HG001 replicates. Chr20–22 is only a same-individual locus-held-out sensitivity—not generalization. No winner, superiority, clinical, or scalar-ranking claim is allowed.

## Baseline: tested versus planned

| Item | M1 status |
|---|---|
| Python schema/publisher tests | Tested where reported in the PR |
| Nextflow 26.04.6 minimum, Java ≥17 | CI contract; local status reported honestly |
| nf-core/tools 4.1.0, nf-schema 2.8.0, nf-test 0.9.5 | Pinned CI/tooling contracts |
| GATK and DeepVariant 1.10.0 WES | Planned only; never invoked in M1 |
| DeepVariant linux/amd64 CPU (AVX) and GPU images | Configured immutable contracts; not tested |
| ARM64/Apple Silicon | Architecture-compatible orchestration only; DeepVariant execution untested/unsupported until qualified |
| HG001, GIAB, Colab/Drive, cloud, SLURM, Seqera/Wave, Dash | Not tested in M1 |

## Data and private-workspace policy

Only the deterministic, explicitly synthetic nonhuman FASTQ fixture recipe is public; the gzip files are materialized locally so repository reviews remain text-only. Human FASTQ/BAM/VCF/reference/truth/vendor data are forbidden in Git. A guarded publisher can stage non-sensitive evidence in `artifacts/private-workspace/m1_foundation`; Drive publication is opt-in and never a Nextflow work directory. See [private workspace](docs/private-workspace.md).

## Roadmap and limitations

M1 foundation and architecture; M2 data and provenance; M3 FASTQ QC, alignment, preprocessing, and alignment/coverage QC; M4 independently selectable GATK HaplotypeCaller and DeepVariant WES callers; M5 common GIAB benchmarking and explicit caller accuracy-versus-resource comparison; M6 operational hardening, Seqera observability, and cloud/HPC profiles; M7 comprehensive QA, canonical execution, reproducibility audit, and v1.0 release; M8 Plotly Dash Pipeline Evidence Explorer and deployment; M9 website research showcase and final claim/reproducibility audit. See [milestones](docs/milestones.md), [architecture](docs/architecture.md), [contracts](docs/data-contracts.md), and [scientific validity](docs/scientific-validity.md). This is an external, unbranded nf-core-inspired structure—not an official nf-core pipeline or Sarek replacement.

Authoritative sources and access dates are recorded in [`docs/source-ledger.yaml`](docs/source-ledger.yaml).

## M2 canonical data driver

`config/m2-resources.json` locks the one HG001 lane, exact GRCh38 source, and GIAB v4.2.1 truth resources. Run `python scripts/acquire_m2.py --preflight-only --workspace /path/to/m2-stage
# Then choose a unique ID:
python scripts/acquire_m2.py --workspace /path/to/m2-stage --run-id m2-YYYYMMDDTHHMMSSZ`; partial downloads resume and completed bytes are re-verified before reuse. Then use `prepare_m2.py` with the verified hg19 capture BED and chain. See [capture evidence](docs/capture-design.md) and the ordered [Colab notebook](notebooks/m2_colab.ipynb). Human and large reference bytes remain private and ignored by Git.

M2 distinguishes implementation readiness from canonical data readiness. **Gate A** provides strict source contracts, synthetic downloader/domain tests, and private-workspace tooling. **Gate B has not run and is blocked:** the public metadata does not bind this library to an exact capture-design target file. See [M2 operations](docs/m2-data-provenance.md), the machine-readable [target decision](config/m2-target-design.json), and [ADR 0008](docs/adr/0008-m2-canonical-data.md). No download, Drive publication, Colab architecture, or canonical domain is claimed without immutable execution evidence.

## Colab launch

Use the [notebook launch center](notebooks/README.md) or open M2 directly:
[![Open M2 in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jcollins-bioinfo/giab-wes-nextflow/blob/main/notebooks/m2_colab.ipynb). The launcher records the resolved commit and keeps canonical Gate B fail-closed.

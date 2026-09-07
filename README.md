# GIAB HG001 WES: dual-caller benchmark and evidence explorer

> **M4 dual callers — version 0.4.0-dev.1, implemented; local tests passed, actual caller qualification pending.** M3 synthetic shared preprocessing passed required CI 34103737524 at `c3426d3d4578ec6e66a6494c09fde983a7e4f3cd`; its evidence checkpoint is draft PR #20, stacked on M2.1.1 recovery draft PR #19. This M4 branch adds isolated caller contracts and a separately versioned positive fixture. Real HG001, independent known-sites compatibility and capture-dependent execution remain gated. See the [observed state](docs/orchestration/project-state.json), [implementation plan](docs/orchestration/implementation-plan.md), and [claim ledger](docs/claim-ledger.yaml).

## Motivation and architecture

The project preregisters a reproducible comparison of GATK HaplotypeCaller and DeepVariant WES from one analysis-ready BAM while keeping truth out of caller environments.

```text
lane-aware FASTQs → shared BWA-MEM2/sort/markdup/BQSR BAM (+ OQ)
                    ├─ GATK ───────┐
                    └─ DeepVariant ├→ shared normalization → GIAB benchmarking
Nextflow canonical run → immutable evidence → tested Python model → Dash renderer
```

Synthetic shared preprocessing and its typed Python evidence boundary passed local tests and actual Linux/x86_64 Docker CI. Caller branches are implemented and locally tested in M4; benchmarking and Dash require later gates. ONT and somatic workflows are outside v1.

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
prepared reference or approved capture-dependent domain is established. Synthetic
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
by this project. M4 is not verified until required Linux Docker CI passes.

Each selected caller emits a versioned pre-normalization JSON contract, with
input/output hashes, image/version/model identity, exact parameters and task
resources. Only validated small JSON contracts enter the guarded
[M4 evidence publisher](docs/m4-evidence-publication.md). See
[actual integration acceptance](tests/integration/M4.md) for the complete gate.
This fixture establishes no indel accuracy, canonical domain, HG001 benchmark
or compute-cost comparison; those belong to M5 and later execution.

## Scientific plan and claim boundary

The canonical input is original paired Garvan HiSeq 2500 `NIST7035_TAAGGCGA_L001` FASTQ fetched directly from GIAB; SRR3197785/SRX1608029/SRP012400/PRJNA162355 are lineage only, not an SRA substitute. The reference is `GCA_000001405.15_GRCh38_no_alt_analysis_set` and truth is GIAB v4.2.1.

`T_design` is individually lifted/audited/merged/unpadded; `R_call = merge(pad(T_design,100)) ∩ chr1-22,X`; `R_eval_full = HC ∩ T_design ∩ chr1-22`; `R_eval_holdout = R_eval_full ∩ chr20-22`. Denominators never depend on depth, callable/query calls, or genotypes. Full results are descriptive/in-sample because DeepVariant 1.10 WES training included HG001 replicates. Chr20–22 is only a same-individual locus-held-out sensitivity—not generalization. No winner, superiority, clinical, or scalar-ranking claim is allowed.

## Baseline and current execution limits

| Item | Evidence/status |
|---|---|
| M2.1.1 recovery Python 3.12/3.13, wheel and synthetic foundation CI | [Required CI passed](https://github.com/jcollins-bioinfo/giab-wes-nextflow/actions/runs/34094504379) at `22d01b202e15bb098e9d42d0ad4a98606e78c2c2`; 104 Python tests per environment |
| Nextflow 26.04.6 minimum, Java ≥17 | CI contract; local status reported honestly |
| nf-core/tools 4.1.0, nf-schema 2.8.0, nf-test 0.9.5 | Pinned CI/tooling contracts |
| M3 BWA-MEM2, GATK preprocessing and QC | [Verified synthetic Docker execution and resume](docs/orchestration/evidence/m3-verified.json); no canonical HG001 result |
| GATK HaplotypeCaller and DeepVariant WES | M4 implemented; local tests passed, actual caller qualification pending |
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

M2 distinguishes implementation readiness from canonical data readiness. **Gate A** provides strict source contracts, synthetic downloader/domain tests, and private-workspace tooling. **Gate B has not run and is blocked:** new primary-source research establishes the exact deposited Expanded Exome target and dataset association, but does not uniquely assign NIST7035 to the 37 Mb or 62 Mb assay. Canonical domain adoption, reference-dictionary validation and audited liftover remain pending. See [M2 operations](docs/m2-data-provenance.md), the machine-readable [target decision](config/m2-target-design.json), and [ADR 0008](docs/adr/0008-m2-canonical-data.md). The [source-cache metadata audit](docs/orchestration/evidence/source-cache-metadata.json) documents the observed older mirror. It does not establish preparation, a qualified Colab/container environment or canonical domains.

## Colab launch

Use the [notebook launch center](notebooks/README.md) or open M2 directly:
[![Open M2 in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jcollins-bioinfo/giab-wes-nextflow/blob/main/notebooks/m2_colab.ipynb). The launcher records the resolved commit and keeps canonical Gate B fail-closed.

## M2.1 package and readiness boundary

Version `0.2.0-dev.3` established `src/giab_wes_nextflow/` the sole M2 implementation; the retained `scripts/*_m2.py` files only preserve historical command paths. Development dependencies are declared in `requirements-dev.in`, with the reviewed pinned direct set mirrored in `requirements-dev.txt`; CI installs that file before building both distributions and tests the wheel outside the checkout.

Version `0.2.0-dev.4` repairs observed path, identity and restart defects. From a clean reviewed checkout, run `scripts/run_m2_readiness.sh identity` for zero-install identity verification, then `scripts/run_m2_readiness.sh verify` for package installation and local code verification. Data modes (`preflight`, `acquire`, `hydrate`, and `mirror`) are explicit and require a reusable `RUN_ID`. Mirroring is only a durable, rehashed source cache: it cannot create `COMPLETED.json`, satisfy capture-design Gate B, or authorize canonical publication. The exact deposited target bytes are now recorded; their unique per-library assay assignment and canonical adoption remain unresolved. Historical Drive mirror metadata is observed; fresh hydration verification and all canonical biological execution remain separate evidence gates. M3 is synthetically verified after the recovery gate. M4 is implemented and locally tested; actual caller execution and M5–M9 retain their own gates.

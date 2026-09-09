# Canonical HG001 Colab execution

The new `canonical_hg001_analysis_colab.ipynb` launcher runs the installed package
`giab_wes_nextflow.canonical_run`, which owns all preflight, acquisition,
qualification, Nextflow execution, restart validation and publication. Its
implementation SHA is pinned separately from the notebook commit. The current
implementation is testable code; no real HG001 execution is claimed until its
returned evidence bundle passes external review.

The preregistered first result is **HG001 chr20–22 coding-domain benchmark**:
original Garvan NIST7035 L001 paired FASTQs, full authenticated GRCh38 no-alt
alignment, one duplicate-marked and BQSR BAM, GATK recalibrated QUAL and
DeepVariant retained OQ, the same padded calling domain, common BCFtools1.24
normalization and RTG3.13 genotype-aware vcfeval. Evaluation uses fixed GENCODEv50
CDS/stop-codon union intersected with GIABv4.2.1 confidence: 1,905,809 bases in
11,715 intervals. No metric chooses the domain, filtering, resources or stopping
point. Uncovered and uncaptured coding loci remain in recall. Full approved
33,567,783-base coding-domain execution is an incomplete extension.

## Execution and storage

Only `/content/drive/MyDrive/giab-wes-nextflow-private` is admitted as the durable
root. Public large downloads default to authorized. Every source is authenticated
against its declared checksum; existing source-cache bytes are preferred and
rehash-verified before copying. Known-sites use six generation-pinned Broad
objects, independent of GIAB truth. Reference qualification streams all195
contigs and checks their exact ordered length/MD5 identities. Neither a matching
FAI alone nor a downloaded archive alone qualifies an index.

Classic BWA0.7.17 `bwtsw` builds the complete reference index in `/content` after
measured memory/storage checks. Its immutable OCI identity and36 deterministic
forward/reverse functional probes are distinct from complete base-identity
verification. Historical M3 BWA-MEM2 evidence is preserved. The Hartwig prebuilt
candidate is not qualified because retained metadata lacks archive and producer
identity sufficient for reuse; its multipart ETag is not a whole-file checksum.

Runtime priority is existing Apptainer/Singularity, a functioning rootless OCI
route, then explicitly manifested native execution. Pinned udocker/PRoot provides
the automatic no-daemon route. PRoot has reduced isolation, documented in ADR0016.
Each command sees only its staged task root; caller task roots exclude truth,
confidence, expected results and other caller outputs. Version probes remain
configured evidence. Representative positive native GATK and DeepVariant
execution is mandatory before canonical tasks can run.

Initial capacity allowance is100GiB active scratch and60GiB durable storage;
actual allocations and incremental copy requirements are checked before use.
Restart requires at least16GiB free reserve. Filesystem free space is recorded
separately from Drive account quota. Several hours is a planning allowance, not
an observed performance result. Runtime host, CPU affinity, RAM ceilings,
architecture, tool identity, measured CPU/wall time and sampled RSS limitations
are retained. GPU memory does not substitute for system RAM, and no accelerator
is used by this CPU configuration.

## Restart behavior

Use Run all again with the same pinned code. Partial downloads remain partial;
only authenticated complete bytes are promoted. Completed assets have exact
content-addressed manifests and rehashed Drive destinations. Completion markers
are last. Completed scientific stages are separately checkpointed under
`runs/<run-id>/completed-stages/`; they contain selected complete outputs, never
Nextflow work. A runtime reset reconstructs scratch and validates each durable
stage before reuse. A changed input, backend or code identity invalidates the
stage key. Conflicting or corrupt completed bytes fail rather than being reused.

Same-runtime Nextflow resume requires five cached tasks, identical task hashes,
and unchanged scientific output inventory. Stored resource receipts retain their
original uncached measurements; total elapsed time is unavailable when cache or
durable recovery would combine different executions. CPU sums do not imply a
concurrent peak RSS. Sampled process-tree RSS is not reported as exact peak RSS.

The small `canonical-hg001-evidence.zip` contains only validated metadata and
hashes. The separately returned `canonical-complete.json` gives its manifest pin.
The Explorer and website consume only a bundle verified against that external
pin. Native and normalized VCFs, RTG partitions, BAMs, sources and large assets
remain private. No canonical result, release, public deployment or cloud executor
is marked completed merely because code/configuration exists.

## Incident triage

For an error, preserve the private cache and return `canonical-failure.json`.
Read the failing stage's private audit record before retrying. Scientific
acceptance errors, checksum changes, missing OQ, REF mismatches and malformed
VCFs terminate. Technical PRoot startup failures allow one bounded P1-to-P2
qualification attempt; biological failures do not. Temporary transfer errors
use bounded backoff. Nextflow retries only an explicit temporary-failure exit75,
with two retries and unchanged scientific parameters. No OOM-driven parameter
search is performed.

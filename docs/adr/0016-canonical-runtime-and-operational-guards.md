# ADR 0016: qualified Colab execution and bounded operational profiles

Status: implemented runtime machinery; representative Colab execution remains
unverified until the returned qualification receipt passes. Historical M3–M5
Docker execution evidence and image identities remain unchanged.

The owner authorized public tool downloads on Colab and required progress on the
observed Linux/amd64 allocation with about 50.99 GiB RAM and no Docker daemon.
Runtime discovery first tries existing Apptainer/Singularity, then functional
Podman, then the pinned user-space udocker route. Docker remains an explicit
profile for environments that actually provide it. Discovery runs a real
samtools container probe, not just an executable-presence check. Apptainer's
user-namespace/FUSE requirements can be unavailable inside a hosted runtime;
its installation or presence alone is not qualification.
[Apptainer installation requirements](https://apptainer.org/docs/admin/main/installation.html)

The no-Docker installation route is udocker 1.3.17 with the upstream-declared
engine bundle 1.2.11. Source is pinned by SHA-256 and size. The engine is pinned
by its immutable upstream repository commit, Git blob identity and size; its
SHA-256 is computed after authenticated Colab download. No publisher SHA-256 is
invented. The 46 MB engine and genomic tool images were not downloaded or
executed on the owner's Mac. Root/package copies of `canonical-runtime.json`
contain the exact identities and source URLs. Download completion is checked
before promotion; archive paths, special nodes and escaping links are rejected.
An installation marker is written after source/engine inventories are recorded,
and inventories are rechecked before reuse.
[Official udocker release](https://github.com/indigo-dc/udocker/releases/tag/1.3.17)

udocker runs OCI images through PRoot without a Docker daemon. P1 is attempted
first; P2 can be attempted once with fresh smoke-test staging following a
technical execution failure. A biological acceptance failure never changes the
runtime automatically or relaxes the acceptance gate. Image environment is
retained; explicit entrypoints avoid duplicating commands such as `rtg`.
The reviewed 1.3.17 source accepts `image@sha256:...` in `_check_imagespec` and
passes the digest as the registry manifest identifier.

PRoot is filesystem translation, not an adversarial sandbox. Only each task
root is explicitly mapped to `/work`; the host home, Drive, `/content`, truth,
and frozen answers are not mounted. Required system pseudo-filesystems may
remain visible. Tools are the trusted, digest-pinned implementations already
accepted in M3–M5. This reduced isolation is recorded in runtime evidence; it is
not equivalent to a hardened security boundary. A native fallback can be used
only with an explicit reviewed native manifest, exact version, full installation
inventory and an ADR identifying reduced isolation. No unpinned pip/conda
scientific-tool installation is silently substituted.

The actual representative qualification preserves the existing invented M4
positive fixture recipe, prepares a classic-BWA BAM with retained original
qualities, and executes both GATK HaplotypeCaller and DeepVariant WES. Fixture
expectations remain outside all scientific mounts. Each caller receives a
separate copy of the same reference/BAM/regions. Both preregistered SNV genotype
gates must pass; no M4 or canonical accuracy claim follows from this new smoke
route. Executable versions for samtools, GATK, DeepVariant, bcftools and RTG are
checked before acceptance; BWA identity is additionally handled by the asset
qualification contract. A version/help command cannot qualify a runtime.

Runtime state becomes `qualified_representative_callers` only after unchanged
execution receipts and output-validator acceptance. Separate Nextflow processes
revalidate the saved executable identity, image pins, receipts and log hashes.
Canonical preprocessing/caller/downstream stages refuse to run on configured-only
state. Actual output identities and the reviewed package identity remain separate
gates in the canonical launcher.

M6 resource limits are explicit and conservative: at most eight logical CPUs,
at most 44 GiB, and at least 10% RAM headroom against the effective host ceiling.
The launcher can choose lower values from actual observations. Only one canonical
task is scheduled at once. Runtime CPU affinity and a sampled descendant RSS guard
limit no-daemon execution; RSS sums can count shared pages more than once, so they
are not reported as an exact run peak. Exact aggregate peak RSS remains null.
Waited-child CPU usage is reported only for serial no-daemon execution; Docker/
Podman daemon-mediated CPU accounting is unavailable. Wall time is measured
independently. `RTG_MEM=8G`, bounded OpenMP/TensorFlow threading and explicit GATK
heap options prevent automatic host-wide thread/memory assumptions.

Transport retries are bounded to three attempts and retain resumable partial
bytes. Scientific commands run once. Nextflow retries only explicit temporary
exit status 75, at most twice; OOM and scientific failures terminate. Completed
validated stages and Nextflow `-resume` provide restart semantics without changing
scientific parameters or silently accepting partial results.

Local, Colab, explicit Docker and Apptainer configurations are provided. SLURM,
AWS Batch, Seqera and Wave are **configured_only**. AWS uses an intentionally
unconfigured queue; Wave and Fusion remain disabled. No cloud credentials,
spending, worker deployment or successful remote execution is implied. The
canonical notebook launches the local Colab profile only.

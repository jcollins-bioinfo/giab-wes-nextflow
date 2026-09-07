# Testing

CI runs pinned formatting, Draft 2020-12 schema/semantic checks, publisher unit tests, Nextflow lint, nf-core schema/pipeline lint, nf-test, and `nextflow run . -profile test,docker` on the supported Nextflow 26.04.6 baseline. Negative samplesheets cover malformed CSV, missing/identical mates, duplicate RG/PU, and incoherent platform. Unknown params and caller enums are errors. Snapshot summaries exclude absolute paths/timestamps. Fixture-size and forbidden-content scans are blocking. `test_full` is non-CI and empty until authorized private inputs exist.


## M2.1.1 recovery checks

The Python 3.12/3.13 CI matrix validates the orchestration schema and semantic
state transitions with `python scripts/validate_orchestration.py`. Version checks
cover the Python package, Hatch source, Nextflow manifest and root/packaged
current resource manifests/schemas; historical evidence keeps its producer version.

Negative tests execute launcher origin/SHA/dirty-checkout gates in disposable
Git repositories and use synthetic bytes for acquisition, mirror, hydration and
canonical-publication checks. Coverage includes path aliases, traversal/symlinks,
manifest/size/hash mismatches, incomplete or duplicate inventories, same-run retry,
legacy recovery lineage, corrupt destination objects, Gate B rejection, and
completion/registry integrity. No real genomic bytes are used in CI.

Local macOS results and Linux CI results remain separate. A stock system Java
launcher without a JRE and the absence of Docker do not count as workflow tests.
The recovery audit's initial Python 3.13 baseline suite ran 37 tests with 15 errors
from the path portability defect; exact final results are recorded in the
orchestration evidence after the repaired suite runs. The local Python 3.12.2
interpreter emits BLAKE2 availability warnings; these are environment evidence,
not grounds to weaken checks or claim a healthy canonical runtime.


## M3 synthetic qualification

The required `m3-docker` job runs the same repository-owned
`scripts/run_m3_synthetic.py` driver available locally, from a fresh clone on
Ubuntu 24.04 Linux/x86_64. It requires a functional Docker daemon and the exact
checked-out SHA, installs the package in a clone-specific environment, generates
the byte-bound invented fixture, executes the locked tool images, independently
inspects the final BAM/index, validates the Python result bundle, and reruns with
`-resume`. The resume check binds unchanged input/parameter identity, task cache
status and output hashes; cached work is not a new cost observation. Separate
trace/report/timeline/DAG files preserve both attempts. Only the driver's small
`evidence/` directory is uploaded; generated reference/FASTQ/BAM/VCF and work
files are excluded.

The existing `nextflow` job covers foundation execution, M3 nf-test wiring/stubs,
Nextflow lint, and nf-core schema/pipeline lint. The two Python jobs retain all
M2 tests and add FASTQ pairing/format/integrity, RG/reference/contig, deterministic
fixture, SAM alignment/duplicate/OQ, parser/lineage/hash, driver identity/privacy,
and publication/recovery failures. Valid bundle unit helpers use explicitly
invented binary identity stand-ins; only actual Docker execution can qualify
binary BAM/index behavior.

All packaged JSON resources must match their root authoritative files byte for
byte. Installed-wheel smoke tests include both M3 interfaces outside the checkout.
No notebook contains a separate scientific implementation. M3 does not use Colab
for this qualification, and no M3 Colab execution is claimed.

A green Python or stub suite is insufficient for M3 verification. The required
aggregate includes `python`, `nextflow`, and `m3-docker`; only green CI on the
observed code plus local synthetic tests can mark M3 verified. Current exact
results are recorded in the orchestration checkpoint after observation.

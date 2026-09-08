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

The first M3 CI attempt passed both Python jobs but exposed a legitimate Docker
format string that the nf-core template linter rejected, plus a MultiQC image
user/work-directory ownership mismatch. The format builder retains only five
non-sensitive engine fields; the lint check remains enabled. MultiQC alone maps
Docker execution to the host UID/GID. The integration oracle checks ownership of
the original task report and hashes it against the published copy, so a host-owned
Nextflow copy cannot conceal a mismatched container-created artifact. The first
attempt remains recorded as failed and cannot qualify M3.


## M4 local and actual-caller qualification

Generate all three fixture families after installing the package and before
`nf-test test --ci`: `python tests/data/generate_fixture.py`,
`python tests/data/generate_m3_fixture.py --output tests/data/m3-generated`,
and `python -m giab_wes_nextflow.m4_fixture --output tests/data/m4-generated`.
The CI job uses this exact order; no ignored files from an earlier local test
may substitute for generation in a fresh checkout.

M4 adds package contracts, a separately versioned positive SNV fixture, guarded
JSON publication, and 14 total nf-tests covering foundation, M3 and M4 wiring,
selection and early failure gates. Unit tests exercise malformed native records,
changed BAM/reference/model identities, unknown caller parameters, unsafe paths,
interrupted publication, candidate-to-inference mismatch and cache regressions.
Stand-ins in unit tests are explicitly synthetic and cannot establish native
BAM/VCF/index behavior.

The required aggregate now also includes `m4-docker`. Its clean-clone driver
executes the same scientific parameters in independent and both modes, validates
actual copied caller inputs and network-disabled mounts, observes positive WES
model inference, checks expected native SNVs/genotypes and actual random-access
indexes, and requires complete shared-task reuse. Expected completed/cached
counts are 26/0, 3/23, 1/27 and 0/28. Cached executions are reuse evidence, not
new compute measurements. See [M4 integration](../tests/integration/M4.md).

A local Python, wheel or stub pass does not qualify dual-caller execution. Only
an observed successful required CI run and reviewed actual inference/output
artifacts can advance M4 to verified. Canonical HG001, indel accuracy, common
normalization and benchmarking remain separate later gates.

## M5 qualification boundary

Generate `python tests/data/generate_m5_stub.py` before the three additional M5
nf-tests. These test both caller selections through identical modules and explicit
noncanonical stub outputs; they do not exercise normalization or matching engines.
The independently versioned `m5_fixture` supplies real representation-sensitive
query/truth cases to `scripts/run_m5_synthetic.py`. The existing `m4-docker` job
runs that bounded driver after successful M4 execution, consuming its actual
outputs without another preprocessing/caller run. Its separate evidence artifact
retains M5 outputs and engine proof. An observed engine pass is required before
claiming M5 synthetic execution verification. Local unit/negative, arithmetic,
resource, schema and wiring tests alone establish implementation checks.
M4's accepted fixture remains unchanged and qualifies SNVs only.

The initial M5 real-tool driver verifies independent caller interfaces and repeated
normalization bytes. It records `nextflow_resume_qualified: false`: repeated tool
execution is not cache reuse. Actual M5 independent-versus-both execution and
resume acceptance remain an explicit follow-up, although all three selections
are wired and stub-tested. The M5 JSON launcher also relies on Nextflow's
JsonSlurper manifest parsing; duplicate manifest-key rejection is an open
hardening item, distinct from strict duplicate rejection in package evidence JSON.

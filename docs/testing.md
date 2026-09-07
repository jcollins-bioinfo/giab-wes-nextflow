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

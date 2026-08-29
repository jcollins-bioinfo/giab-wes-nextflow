# Testing

CI runs pinned formatting, Draft 2020-12 schema/semantic checks, publisher unit tests, Nextflow lint, nf-core schema/pipeline lint, nf-test, and `nextflow run . -profile test,docker` on the supported Nextflow 26.04.6 baseline. Negative samplesheets cover malformed CSV, missing/identical mates, duplicate RG/PU, and incoherent platform. Unknown params and caller enums are errors. Snapshot summaries exclude absolute paths/timestamps. Fixture-size and forbidden-content scans are blocking. `test_full` is non-CI and empty until authorized private inputs exist.

# M3 synthetic integration qualification

The canonical driver is `scripts/run_m3_synthetic.py`. It installs the pinned direct development dependencies and package from a fresh clone of the exact clean source commit into an isolated virtual environment, materializes the deterministic invented fixture, and records qualification evidence independently of Nextflow work files. The proof retains observed installed dependency versions, including resolved transitive dependencies.

```bash
python scripts/run_m3_synthetic.py \
  --output-root "$RUNNER_TEMP/m3-integration" \
  --expected-sha "$(git rev-parse HEAD)" \
  --mode docker
```

Docker mode requires an observed Linux/x86_64 Docker engine with at least one CPU and 4 GiB of assigned memory, Nextflow 26.04.6, and at least 10 GiB of free output filesystem space. It checks these capabilities before cloning or downloading dependencies. These minimums cover the tiny invented fixture and tool images; they do not qualify resources for a canonical human reference or WES run. It runs the `m3_test,docker` profile, verifies the real BAM and its index using the pinned samtools container, checks package-owned schemas and lineage, and repeats with the same parameters/work directory using `-resume`. Every repeated task must be cached, and published hashes and contract semantics must remain identical. First and repeated trace, report, timeline, DAG, and log files use different explicit names.

`--mode preflight` only inspects clean source identity, executable availability, and free space on the intended output filesystem; it performs no clone, install, Docker run, or filesystem output. It reports low disk space without claiming execution readiness. `--mode stub` uses an independent fresh clone with `m3_test -stub-run`, requires a `stub_only`/`not_validated` manifest, and cannot mark biological processing validated. Stub execution does not substitute for the Docker qualification.

Upload **only `OUTPUT_ROOT/evidence/`** from CI. It contains the integration proof, six small result JSONs, text command diagnostics, and execution reports. Personal root paths and query-bearing URL credentials are redacted in uploadable diagnostics; exact raw reports originate separately under `raw-execution/` with their hashes recorded. All upload candidates are quarantined before validation and promoted only after every candidate passes. A privacy validation failure leaves only a safe failed proof in the upload directory. `quarantined-evidence-*`, `inspection/`, `diagnostics/`, `raw-execution/`, `checkout/`, `published/`, `package-venv/`, and `nextflow-work/` are local qualification data and must not be uploaded by the CI evidence step. Failures after the qualification directory is created retain diagnostics and a failed proof; they never become execution evidence.

The focused negative/oracle suite is `tests/unit/test_m3_integration_driver.py` and runs without Docker. It tests altered alignments/read groups/reference/OQ, missing reads, absent duplicate flags, stale or incomplete resume traces, divergent task hashes, source/origin identity failures, and missing-Docker preflight behavior. All fixture bytes are invented and deterministic; no human reads, reference genome, truth variants, or vendor targets enter these tests.

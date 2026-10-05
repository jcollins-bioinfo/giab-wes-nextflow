# Bounded managed cache preparation

This is an **offline preparation and receipt-validation tool**. It does not call
AWS, register workflows, reserve money, start a run, or claim managed cache
qualification. The separate accepted full nonhuman DAG need not be rerun.

The suite contains eight sequential, one-task cases: first execution, unchanged
reuse, then independent parameter, input content, reference, domain, container
and command changes. Each task requests one CPU, 2 GiB, a five-minute task limit
and zero retries. Server run limits, total spending and independent supervision
are separate admission requirements. Task limits do not bound queue or staging
time and do not make a laptop controller durable.

Prepare from the exact reviewed source and production package, using two
different immutable platform manifests whose images provide `cat` and `printf`:

```bash
PYTHONPATH=src python -m giab_wes_nextflow.cloud_cache prepare \
  --repo . --output "$PRIVATE_PROBE_DIRECTORY" \
  --image "$VERIFIED_IMAGE_A" --alternate-image "$VERIFIED_IMAGE_B" \
  --source-sha "$REVIEWED_SOURCE_SHA" \
  --production-package-sha256 "$REVIEWED_PRODUCTION_PACKAGE_SHA256" \
  --qualification-receipt-sha256 "$ACCEPTED_FULL_DAG_RECEIPT_SHA256"
```

The output contains two deterministic ZIPs, two 11-byte nonhuman input fixtures,
and `plan.json`. The ZIPs differ only in the probe command and its manifest.
The production configuration and historical engine requirements are unchanged.
Pin the generated plan and ZIPs before registration. Local contract tests do
not establish parser compatibility or native managed behavior.

After budget and supervisor admission, actual registration and staging are
still required through the existing authorized operator path. Prepare a private
bindings JSON with `cache_id`, `run_group_id`, `role_arn`, `output_uri`,
`workflows.baseline` and `workflows.command` (each with the provider's `id` and
`digest`), and `inputs.input-A.txt` / `inputs.input-B.txt` (each with `uri`,
`version_id`, `sha256`, `bytes`). These are real provider values, never examples
to submit unchanged. Both inputs must use **the same S3 key and URI**, distinct
retained non-null VersionIds and equal byte lengths. Before each case, restore
its declared nonhuman bytes as the current version at that key and verify the
current version and whole bytes. Preserve every old version. A changed input
URI cannot establish content-only invalidation.

```bash
PYTHONPATH=src python -m giab_wes_nextflow.cloud_cache requests \
  --plan "$PRIVATE_PROBE_DIRECTORY/plan.json" \
  --bindings "$PRIVATE_BINDINGS_JSON" --output "$PRIVATE_REQUESTS_JSON"
```

Requests use one run cache, explicit Nextflow 26.04.0/parser v2 and
`CACHE_ALWAYS`. A completed first run must export its cache before the unchanged
case starts. The existing canonical helper defaults to `CACHE_ON_FAILURE`, which
does not establish reuse of a successful baseline. AWS documents the explicit
cache setting and provider `cacheHit` observation in
[Using the run cache](https://docs.aws.amazon.com/omics/latest/dev/workflow-cache-startrun.html).

The generated file has `submitted:false` and `budget_reserved:false`. Do not
submit it outside the existing independently bounded watchdog/admission path.
Before every case, refresh identity, all matching request/run state, actual
run-group bounds, ACTIVE cache/workflow identities and input versions. Never
rerun a consumed request or adopt an existing run without matching its identity.

For evidence replay, collect one private JSON mapping all eight case names to:

- `request`: the exact submitted request; `run`: actual GetRun response.
- `task_request`: the exact GetRunTask request (`id` and `taskId`), and `task`:
  its unmodified response with explicit `cacheHit` and image details.
- `trace`: the one actual CACHE_PROBE trace row (`name`, `container`, `status`,
  `hash`). Preserve its original trace file in the pinned private capture.
- `input`: actual `uri`, non-null `version_id`, `sha256`, `bytes`, and
  `whole_object_sha256_verified:true` only after direct byte verification.
- `output_text`: the complete returned nonhuman receipt bytes decoded as UTF-8.

An absent `cacheHit` is unknown, never silently a miss. Independently review and
pin the capture; this offline validator checks joins, not remote authenticity.

```bash
PYTHONPATH=src python -m giab_wes_nextflow.cloud_cache validate \
  --plan "$PRIVATE_PROBE_DIRECTORY/plan.json" \
  --observations "$PRIVATE_OBSERVATIONS_JSON" \
  --observations-sha256 "$INDEPENDENTLY_REVIEWED_CAPTURE_SHA256" \
  --output "$PRIVATE_PROBE_VALIDATION_JSON"
```

The result remains separate from `cloud_resume_receipt`. A Nextflow trace hash
is not asserted to be a HealthOmics provider cache-entry key. Actual cache-entry
keys and their source receipts must still be mapped into the strict existing
resume contract, and the accepted full-DAG qualification plus this probe must be
reviewed against the exact production package before that gate passes. No
human result, production engine qualification or public bundle is fabricated.

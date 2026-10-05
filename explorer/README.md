# Pipeline Evidence Explorer

Version `0.1.0.dev1`. The owner approved this early prototype on 2026-09-08.
It is a separate Python distribution. Install the pipeline package alongside it
to enable the canonical result consumer. The app now also renders accepted managed
nonhuman qualification and source-bound infrastructure declarations. Canonical HG001
execution and public deployment remain unavailable in its bundled evidence; this
does not establish M8 completion.

The overview renders the verified M3 synthetic 48-read preprocessing run,
22 completed tasks and 22 cached tasks on resume. The execution view filters
the original trace, retaining milliseconds, CPU percentage and RSS bytes.
The provenance view lists immutable source hashes and downloads a fixed,
validated JSON snapshot. A package-owned loader validates the six-file inventory
before rendering; callbacks only select views or validated observations.

Caller qualification now records the passed synthetic M4 run on main
[`f29ed262`](https://github.com/jcollins-bioinfo/giab-wes-nextflow/actions/runs/34237377774).
The package bundles the concise [verified record](../docs/orchestration/evidence/m4-verified-main-34237377774.json),
bound to its downloaded artifact, all 93 verified evidence members, source tree,
fixture and tool identities. Recipe 1.1.0 passed both native SNV genotypes and its
reference control, two DeepVariant candidate/inference records, independent
caller modes, both-mode and full resume. This qualifies synthetic SNV integration.

The original `m4-attempt.json` remains unchanged as historical recipe 1.0.0 failure
evidence: its expected heterozygote returned `0/0`/`RefCall`. The current passed
record does not archive individual native VCF rows, so the UI does not infer
per-site FILTER, AD or GQ from the successful acceptance assertions. HG001 accuracy
and comparative costs remain null, with explicit missing reasons. Synthetic
timings do not estimate WES cost; indel and canonical HG001 qualification remain
unavailable.

The synthetic M5 panel records retained CI `34270789172`: pinned BCFtools 1.24
and RTG Tools 3.13, strict invented SNP/indel representations, accepted M4
SNV interfaces, independent/both execution and actual cached resume. Its
metrics qualify that fixture only; they are not HG001 accuracy measurements.

## Accepted managed execution and infrastructure

The execution view includes the accepted managed nonhuman fixture observed on
2026-09-15: 28 provider tasks across 21 processes, 23 native identity joins and
22 retained native command timings. The collector cannot include its own final
observation in the JSON it writes, so its command timing stays unavailable in
this projection. Five fixture tasks have no accepted native attempt identity;
the app does not invent an attempt number. Observed CPU seconds and peak RSS
remain null for all tasks. Requested vCPUs and memory are reservations.

The interactive timeline preserves concurrent provider intervals, separates
creation-to-start (queue/staging combined) from start-to-stop, and shows native
command elapsed independently. It never turns sums of task durations into run
wall time. The task selector and clickable bars expose image digests, command
hashes and artifact byte identities. A native dropdown offers the same details
without using the chart. Managed cache/retry-history qualification remains
unavailable; historical local M3 resume reuse does not qualify managed reuse.

`managed/evidence.json` is a fixed allowlisted export. Its external source-code
pin is checked before rendering; `managed/readyz` is separate from synthetic and
canonical readiness. The exporter verifies the already accepted validation
receipt, then its exact provider and collector hashes. It publishes no provider
run/task/account identifiers, storage locations, raw commands or genomic payloads.
To reproduce from the accepted private receipt chain:

```bash
python explorer/export_managed.py --validation "$VALIDATION_RECEIPT" \
  --provider "$PROVIDER_RECEIPT" --collector "$COLLECTOR_EVIDENCE" \
  --output "$PUBLIC_EXECUTION_JSON"
```

The Infrastructure tab uses a separately pinned sanitized JSON snapshot of
repository declarations, with exact source SHA and file hashes. It explains
Terraform provisioning, Nextflow scheduling, IAM responsibilities, durable and
working storage, image registry, logs and the separate Lightsail module. Every
component is **declared**; no plan, apply receipt, live inventory, DNS state or
public-hosting claim is inferred. The fixed `infrastructure/evidence.json` download
contains the same public declaration snapshot. No Terraform state is loaded.


## Run locally

From the repository root in a Python 3.12 or 3.13 virtual environment:

```bash
python -m pip install . ./explorer
gunicorn pipeline_evidence_explorer.wsgi:server --bind 127.0.0.1:8050 --workers 1 --no-control-socket
```

Open `http://127.0.0.1:8050/giab-wes-nextflow/`.
Direct dependencies are pinned to Dash 4.4.1, Plotly 7.0.0 and Gunicorn 26.2.0;
the container installs the pinned transitive `requirements.lock`. A public image,
reverse proxy, hosting qualification and deployment approval remain future work.

The application factory supports a validated route prefix. Under that prefix,
`healthz` checks process liveness; `readyz` checks the synthetic bundle and always
reports `canonical: false`; `evidence.json` accepts no user-selected file path.
Invalid evidence returns readiness/download 503. Responses include same-origin
CSP, no-store, nosniff, no-referrer and same-origin framing headers.

## Canonical consumer and exports

The default Canonical tab reports unavailable. To load a reviewed, public-safe
bundle, configure both `EXPLORER_CANONICAL_BUNDLE` (local directory) and
`EXPLORER_CANONICAL_MANIFEST_SHA256` (externally reviewed manifest digest).
The pipeline-owned `load_canonical_bundle` validates the closed schema, exact
inventory, hashes, domain, shared caller inputs, metric arithmetic, qualification
receipts and missingness before the UI can render results. See
[the result contract](../docs/canonical-results-contract.md). An internal
self-consistent manifest is insufficient without the external trust pin.

Under the configured route prefix, `canonical/readyz` returns 503 when absent
or invalid. Valid bundles expose fixed `canonical/evidence.json`,
`canonical/metrics.tsv` and `canonical/resources.tsv` downloads. The synthetic
`evidence.json` and readiness remain distinct. Canonical views show caller
metrics, resource groups, coverage availability, environment qualification,
artifact lineage and mandatory scientific limitations. Plotting performs no
scientific calculation in callbacks.

## Verification

```bash
python -I -m unittest discover -s explorer/tests -v
```

Source tests cover bundled observations, source corruption, symlinks,
HTTP/callback behavior, fixed downloads, readiness, prefix rejection and
canonical unavailable/valid exports. Five pipeline model tests additionally
cover schema, inventory, unsafe content, metric arithmetic and missingness.
Current source tests passed locally with both package dependencies available.
Earlier prototype browser checks covered its original three views at desktop
and 390-pixel widths. The canonical, managed execution and infrastructure views have HTTP/callback coverage;
current visual, responsive and accessibility browser qualification is pending;
these earlier checks do not qualify the new view. Public hosting and an actual
canonical bundle are still required for operational M8 completion.

## Container and AWS serving path

Build from the repository root: `docker build --platform linux/amd64 -f explorer/Dockerfile .`.
The image pins its official Python amd64 base and runtime dependency versions,
runs non-root and exposes port8050. A read-only filesystem needs writable `/tmp`.
`python explorer/container_smoke.py` checks a running default image at localhost8050.
The new CI builds and checks both project images; a local source HTTP check is
not a Docker image qualification. See [AWS deployment](../docs/aws-cloud.md) and
[Terraform](../infra/aws/README.md). Deployment remains explicitly disabled.

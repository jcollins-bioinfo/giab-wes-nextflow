# Pipeline Evidence Explorer — synthetic prototype

Version `0.1.0.dev1`. The owner approved this early prototype on 2026-09-08.
It is a separate Python distribution; pipeline version remains `0.4.0-dev.1`.
This is not canonical M8 completion or a deployed service.

The overview renders the verified M3 synthetic 48-read preprocessing run,
22 completed tasks and 22 cached tasks on resume. The execution view filters
the original trace, retaining milliseconds, CPU percentage and RSS bytes.
The provenance view lists immutable source hashes and downloads a fixed,
validated JSON snapshot. A package-owned loader validates the four-file inventory
before rendering; callbacks only select views or validated observations.

Caller qualification uses the separate M4 fixture and records its actual failure:
DeepVariant returned `0/0`/`RefCall` at the expected heterozygote, with AD `[40,40]`.
Its other expected site returned `1/1`/`PASS`. No cause is inferred. Both-mode and
final resume acceptance remain unverified. HG001 accuracy and comparative costs
are null, with explicit missing reasons. Synthetic timings do not estimate WES cost.

## Run locally

From the repository root in a Python 3.12 or 3.13 virtual environment:

```bash
python -m pip install ./explorer
gunicorn pipeline_evidence_explorer.wsgi:server --bind 127.0.0.1:8050 --workers 1 --no-control-socket
```

Open `http://127.0.0.1:8050/research/giab-wes-nextflow/explorer/`.
Direct dependencies are pinned to Dash 4.4.1, Plotly 7.0.0 and Gunicorn 26.2.0;
transitive dependencies are not a reproducible deployment lock. A public image,
reverse proxy, hosting qualification and deployment approval remain future work.

The application factory supports a validated route prefix. Under that prefix,
`healthz` checks process liveness; `readyz` checks the synthetic bundle and always
reports `canonical: false`; `evidence.json` accepts no user-selected file path.
Invalid evidence returns readiness/download 503. Responses include same-origin
CSP, no-store, nosniff, no-referrer and same-origin framing headers.

## Verification

```bash
python -I -m unittest discover -s explorer/tests -v
```

Five tests cover known observations, missing metrics, source corruption and
symlinks, actual HTTP/callback behavior, fixed downloads, invalid readiness and
prefix rejection. The installed wheel passed locally on Python 3.13. Browser
checks covered all three views, a real process-filter interaction, provenance,
desktop and 390-pixel layouts, and no console errors/warnings. Native radio
navigation exposes named controls and visible focus; this is not an accessibility
certification. CI additionally exercises Python 3.12 and 3.13.

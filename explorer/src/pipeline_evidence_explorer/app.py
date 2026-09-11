"""Render validated synthetic evidence with an explicit missing-results boundary."""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from dash import Dash, Input, Output, dcc, html
from flask import Response, redirect, request
import plotly.graph_objects as go

from . import __version__
from .model import MANIFEST_SHA256, REPO, Snapshot, load_snapshot, select_tasks

DEFAULT_PREFIX = "/giab-wes-nextflow/"
LEGACY_PREFIX = "/research/giab-wes-nextflow/explorer/"


def card(label: str, value: str, detail: str) -> Any:
    """Render one observation with its scope and unit alongside the value."""
    return html.Div([html.P(label, className="eyebrow"), html.H2(value), html.P(detail)], className="card")


def task_table(snapshot: Snapshot, selection: str) -> Any:
    """Render selected raw trace fields without estimating missing resource metrics."""
    tasks = select_tasks(snapshot, selection)
    return html.Table([html.Thead(html.Tr([html.Th(x, scope="col") for x in
                       ("Process", "State", "Execution (ms)", "CPU (%)", "Peak RSS (bytes)", "Task hash")])),
                       html.Tbody([html.Tr([html.Td(value) for value in
                                  (task.name.split(":")[-1], task.status, task.elapsed, task.cpu,
                                   task.peak_rss, task.task_hash)]) for task in tasks])])


def canonical_view(data: Any, missing_reason: str, prefix: str) -> Any:
    """Render only validated package observations and precomputed exports."""
    if data is None:
        return html.Section([html.H2("Canonical results unavailable"), html.P(missing_reason),
            html.P("No HG001 accuracy, resource result, or canonical completion is inferred from the synthetic qualification panels."),
            html.P("The canonical notebook must return a complete, validated public bundle and its independently reviewed manifest SHA-256.")], className="panel")
    record = data.record
    label = "HG001 chr20–22 coding-domain benchmark" if record["scope"] == "hg001_chr20_22_coding" else "HG001 full coding-domain benchmark"
    columns = ("Caller", "Variant", "TP query", "TP truth", "FP", "FN", "Precision", "Recall", "F1")
    rows = []
    for caller, value in record["callers"].items():
        for kind, metrics in value["metrics"].items():
            row = [caller, kind] + [metrics[k] if metrics[k] is not None else "Unavailable" for k in ("tp_query", "tp_truth", "fp", "fn", "precision", "recall", "f1")]
            rows.append(html.Tr([html.Td(x) for x in row]))
    chart = go.Figure()
    for caller in ("gatk", "deepvariant"):
        resource = record["resources"][caller]; accuracy = record["callers"][caller]["metrics"]["SNP"]["f1"]
        if resource["wall_seconds"] is not None and accuracy is not None:
            chart.add_trace(go.Scatter(x=[resource["wall_seconds"]], y=[accuracy], mode="markers+text", name=caller,
                text=[caller], textposition="top center", hovertemplate="%{text}: %{x} seconds, SNP F1 %{y}<extra></extra>"))
    chart.update_layout(template="plotly_white", xaxis_title="Observed caller wall time (seconds)", yaxis_title="SNP F1", height=320)
    resource_rows = [html.Tr([html.Td(group)] + [html.Td(value[k] if value[k] is not None else "Unavailable") for k in ("wall_seconds", "cpu_seconds", "peak_rss_bytes")]) for group,value in record["resources"].items()]
    coverage = record["coverage"]
    return html.Section([html.Div("VALIDATED CANONICAL EVIDENCE", className="scope"), html.H2(label),
        html.P(f"Run {record['run_id']} · sample {record['sample']} · pipeline {record['package_version']}"),
        html.P(f"Evaluation: {record['domain']['bases']:,} bases in {record['domain']['interval_count']:,} fixed intervals."),
        html.P("Coverage unavailable: " + record["coverage_missing_reason"] if coverage is None else f"Coverage: {coverage['covered_bases']:,} evaluated bases covered; {coverage['definition']}"),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(x, scope="col") for x in columns])),html.Tbody(rows)]),className="table-wrap"),
        html.H3("Accuracy and observed resources"), dcc.Graph(figure=chart, config={"displayModeBar":False}, responsive=True) if chart.data else html.P("No complete wall-time/SNP-F1 pair is available for plotting."),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(x,scope="col") for x in ("Attribution", "Wall seconds", "CPU seconds", "Peak RSS bytes")])),html.Tbody(resource_rows)]),className="table-wrap"),
        html.P(record["uncertainty"]),html.Ul([html.Li(x) for x in record["limitations"]]),
        html.H3("Tested versus configured environments"),html.Ul([html.Li(f"{x['name']}: {x['status']}") for x in record["environments"]]),
        html.H3("Provenance and artifact lineage"),html.P(["Pipeline SHA: ",html.Code(record["repository_sha"])]),
        html.P(["Reviewed public manifest: ",html.Code(data.manifest_sha256)]),
        html.Ul([html.Li([name, " · ",html.Code(sha)]) for name,sha in data.artifact_inventory]),
        html.Div([html.A(label,href=prefix+"canonical/"+name,className="button") for name,label in (("evidence.json","Validated JSON"),("metrics.tsv","Metric TSV"),("resources.tsv","Resource TSV"))])],className="panel")


def create_app(*, bundle_dir: Path | None = None, prefix: str = DEFAULT_PREFIX,
               canonical_dir: Path | None = None, canonical_manifest_sha256: str | None = None) -> Dash:
    """Create an isolated Flask/Dash app, failing readiness on invalid evidence."""
    if not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*", prefix):
        raise ValueError("invalid application prefix")
    snapshot: Snapshot | None = None
    try:
        snapshot = load_snapshot(bundle_dir)
    except (ValueError, OSError, KeyError, TypeError):
        pass
    canonical_data = None
    canonical_error = "No reviewed canonical evidence bundle has been supplied."
    configured_dir = canonical_dir or (Path(os.environ["EXPLORER_CANONICAL_BUNDLE"]) if os.environ.get("EXPLORER_CANONICAL_BUNDLE") else None)
    configured_pin = canonical_manifest_sha256 or os.environ.get("EXPLORER_CANONICAL_MANIFEST_SHA256")
    if configured_dir or configured_pin:
        try:
            from giab_wes_nextflow.canonical_results import load_canonical_bundle
            if configured_dir is None or configured_pin is None:
                raise ValueError("canonical directory and trusted manifest pin are both required")
            canonical_data = load_canonical_bundle(configured_dir, configured_pin)
        except (ValueError, OSError, KeyError, TypeError, ImportError):
            canonical_error = "Canonical evidence failed validation or its installed result model is unavailable."
    app = Dash(__name__, requests_pathname_prefix=prefix, routes_pathname_prefix=prefix,
               title="Pipeline Evidence Explorer", update_title=None,
               assets_folder=str(Path(__file__).parent / "assets"))
    app.server.config.update(MAX_CONTENT_LENGTH=1_000_000)

    if prefix != "/":
        @app.server.get("/")
        def directory():
            return Response('<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Applications | John Patrick Collins</title><main><h1>Applications</h1><p><a href="' + prefix + '">GIAB WES Pipeline Evidence Explorer</a></p><p>Research software demonstrations. Evidence status is shown inside each application.</p></main></html>', mimetype="text/html")

    if prefix != LEGACY_PREFIX:
        @app.server.route(LEGACY_PREFIX, defaults={"path": ""}, methods=["GET", "POST"])
        @app.server.route(LEGACY_PREFIX + "<path:path>", methods=["GET", "POST"])
        def legacy_redirect(path):
            # 308 retains callback POST method/body for existing bookmarked pages.
            suffix = ("?" + request.query_string.decode("ascii")) if request.query_string else ""
            return redirect(prefix + path + suffix, code=308)

    @app.server.get(prefix + "healthz")
    def health() -> tuple[dict[str, str], int]:
        """Report process liveness separately from evidence readiness."""
        return {"status": "ok", "version": __version__}, 200

    @app.server.get(prefix + "readyz")
    def readiness() -> tuple[dict[str, Any], int]:
        """Report valid prototype data without suggesting canonical readiness."""
        return {"status": "synthetic_prototype_ready" if snapshot else "invalid_evidence",
                "canonical": False, "manifest_sha256": MANIFEST_SHA256}, 200 if snapshot else 503

    @app.server.get(prefix + "evidence.json")
    def evidence() -> Response:
        """Serve only the prevalidated fixed public snapshot; accept no file path."""
        return Response(snapshot.public_json if snapshot else '{"error":"invalid_evidence"}',
                        status=200 if snapshot else 503, mimetype="application/json",
                        headers={"Content-Disposition": 'attachment; filename="synthetic-evidence.json"'})

    @app.server.get(prefix + "canonical/readyz")
    def canonical_readiness() -> tuple[dict[str, Any], int]:
        """Keep canonical readiness distinct from the synthetic prototype."""
        return {"status": "canonical_ready" if canonical_data else "canonical_unavailable",
                "canonical": bool(canonical_data), "scope": canonical_data.record["scope"] if canonical_data else None,
                "manifest_sha256": canonical_data.manifest_sha256 if canonical_data else None}, 200 if canonical_data else 503

    @app.server.get(prefix + "canonical/<download>")
    def canonical_download(download: str) -> Response:
        """Serve fixed prevalidated exports; no client-selected filesystem path."""
        if canonical_data is None:
            return Response('{"error":"canonical_unavailable"}', status=503, mimetype="application/json")
        exports = {"evidence.json": (canonical_data.public_json, "application/json"),
                   "metrics.tsv": (canonical_data.metrics_tsv, "text/tab-separated-values"),
                   "resources.tsv": (canonical_data.resources_tsv, "text/tab-separated-values")}
        if download not in exports:
            return Response('{"error":"unknown_export"}', status=404, mimetype="application/json")
        body, mime = exports[download]
        return Response(body, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="canonical-{download}"'})

    @app.server.after_request
    def secure_response(response: Response) -> Response:
        """Add same-origin, privacy and embedding protections to every response."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'self' " + " ".join(app.csp_hashes())
            + "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")
        return response

    if snapshot is None:
        app.layout = html.Main([html.H1("Evidence unavailable"), html.P(
            "The configured evidence failed validation. Restore the pinned bundle before serving results.")])
        return app
    data = snapshot
    reads = go.Figure(go.Bar(x=["Mapped", "Unmapped"], y=[data.mapped_reads, data.unmapped_reads],
                            marker_color=["#087f8c", "#d69b39"], text=[data.mapped_reads, data.unmapped_reads],
                            textposition="outside", hovertemplate="%{x}: %{y} reads<extra></extra>"))
    reads.update_layout(template="plotly_white", height=285, margin=dict(l=45, r=20, t=25, b=35),
                        yaxis_title="Primary reads", font=dict(family="Arial", color="#23354a"),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    overview = html.Div([
        html.Div([card("Primary reads", str(data.primary_reads), "M3 invented preprocessing fixture"),
                  card("First execution", str(data.completed_tasks), "Completed Nextflow tasks"),
                  card("Resume reuse", str(data.cached_tasks), "Cached tasks; accepted bytes unchanged")], className="cards"),
        html.Div([html.Section([html.H2("One shared alignment"), html.P(
            "Coordinate sorting, indexed queries, reference identity and original base-quality preservation passed."),
            dcc.Graph(figure=reads, config={"displayModeBar": False}, responsive=True),
            html.P(f"{data.duplicate_reads} marked duplicate reads are retained within the read totals; {data.read_groups} read groups.", className="note")], className="panel"),
            html.Section([html.H2("Caller qualification"), html.Div([html.Strong("GATK HaplotypeCaller"),
                html.Span("Accepted in synthetic test", className="badge success")], className="caller"),
                html.Div([html.Strong("DeepVariant WES"), html.Span("Accepted in synthetic test", className="badge success")], className="caller"),
                html.P(data.caller_observation),
                html.P("Independent callers, both-mode and final resume passed on main. This qualifies invented SNV integration; indel and canonical HG001 qualification remain unavailable."),
                html.P("M4 recipe 1.1.0 has 528 primary reads. Its caller observations are separate from the 48-read M3 run plotted here. Earlier recipe 1.0.0 failures remain in the evidence download as historical attempts.", className="note"),
                html.A("Inspect the recorded caller run ↗", href=f"{REPO}/actions/runs/{data.m4_run_id}")], className="panel")], className="columns"),
        html.Section([html.H2("Synthetic M5 benchmark qualification"), html.P(data.m5_observation),
            html.A("Inspect retained M5 CI evidence ↗", href=f"{REPO}/actions/runs/{data.m5_run_id}")], className="panel"),
        html.Section([html.H2("Primary HG001 results"), html.P("Awaiting real execution and common benchmarking."),
            html.Div([card("SNP precision / recall / F1", "Unavailable", "No canonical SNP counts"),
                      card("Indel precision / recall / F1", "Unavailable", "No canonical indel counts"),
                      card("Accuracy versus cost", "Unavailable", "No fair caller-cost experiment")], className="cards"),
            html.P("The fixed GENCODE v50 coding-domain alternative is owner-approved. Full HG001 results will be descriptive/in-sample: the DeepVariant WES training data include HG001. Chr20–22 is a same-individual sensitivity analysis.")], className="panel")])
    execution = html.Div([html.H2("Recorded task execution"), html.P(
        "M3 first execution, Linux/x86_64 Docker. Original Nextflow trace units are retained. CPU is reported utilization; these observations are not a dual-caller cost comparison."),
        html.Label("Process", htmlFor="process"), dcc.Dropdown(id="process", value="all", clearable=False,
            options=[{"label": "All processes", "value": "all"}] + [{"label": t.name.split(":")[-1], "value": t.name} for t in data.tasks]),
        html.Div(task_table(data, "all"), id="task-table", className="table-wrap", **{"aria-live": "polite"})], className="panel")
    provenance = html.Div([html.H2("Trace every observation"), html.P("This app loads immutable source files and verifies their hashes before rendering."),
        html.Dl([html.Dt("Actual M3 tested pipeline SHA"), html.Dd(html.Code(data.pipeline_sha)),
                 html.Dt("Actual M4 passed main SHA"), html.Dd(html.Code(data.m4_sha)),
                 html.Dt("Shared M3 BAM SHA-256"), html.Dd(html.Code(data.bam_sha256)),
                 html.Dt("Shared M3 BAI SHA-256"), html.Dd(html.Code(data.bai_sha256)),
                 html.Dt("Explorer evidence manifest SHA-256"), html.Dd(html.Code(MANIFEST_SHA256))]),
        html.H3("Verified source inventory"), html.Ul([html.Li([html.Strong(name), html.Br(), html.Code(sha)]) for name, sha in data.sources]),
        html.A("Download validated evidence JSON", href=prefix + "evidence.json", className="button"),
        html.H3("Field ownership"), html.P("Read/QC cards: m3-proof.json → bam_assertions. Execution cards: resume_assertions. Task table: m3-first.trace.tsv. Current caller status: m4-verified-main-34237377774.json → execution_scope. Historical failure: m4-attempt.json. Domain decision: domain-approval.json. Benchmark metrics are null, with an explicit missing reason.")], className="panel")
    canonical_panel = canonical_view(canonical_data, canonical_error, prefix)
    app.layout = html.Div([html.Header([html.A("JPC / RESEARCH", href=REPO, className="brand"),
        html.Span(f"EXPLORER {__version__}", className="version")]), html.Main([
        html.Div("SYNTHETIC EVIDENCE PROTOTYPE", className="scope"), html.H1("Pipeline Evidence Explorer"),
        html.P("From raw reads to inspectable evidence.", className="subtitle"),
        html.P("GIAB HG001 WES project · John Patrick Collins · Public engineering work, 2026", className="byline"),
        html.Div("This preview contains invented test data and recorded qualification outcomes. It does not report HG001 accuracy or a caller winner.", className="notice", role="note"),
        html.Fieldset([html.Legend("Choose evidence view", className="sr-only"),
            dcc.RadioItems(id="view", options=[{"label": x.title(), "value": x} for x in ("overview", "execution", "provenance", "canonical")],
                           value="overview", inline=True, className="section-nav")]),
        html.Div(overview, id="overview-panel"), html.Div(execution, id="execution-panel", style={"display": "none"}),
        html.Div(provenance, id="provenance-panel", style={"display": "none"}),
        html.Div(canonical_panel, id="canonical-panel", style={"display": "none"})]),
        html.Footer(["Source-owned measurements. Explicit limitations. ", html.A("View repository ↗", href=REPO)])])

    @app.callback(Output("overview-panel", "style"), Output("execution-panel", "style"),
                  Output("provenance-panel", "style"), Output("canonical-panel", "style"), Input("view", "value"))
    def choose_view(selection: str) -> tuple[dict[str, str], ...]:
        """Switch panels with keyboard-accessible native radio controls."""
        return tuple({"display": "block" if selection == name else "none"}
                     for name in ("overview", "execution", "provenance", "canonical"))

    @app.callback(Output("task-table", "children"), Input("process", "value"))
    def filter_tasks(selection: str) -> Any:
        """Filter validated observations only; invalid selections expose no data path."""
        try:
            return task_table(data, selection)
        except ValueError:
            return html.P("Choose a process from the list.")

    app.server.config["EXPLORER_SNAPSHOT"] = data
    app.server.config["CANONICAL_RESULTS"] = canonical_data
    return app


def main() -> None:
    """Serve a local preview; public deployment requires separate authorization."""
    create_app().run(host="127.0.0.1", port=int(os.environ.get("PORT", "8050")), debug=False)

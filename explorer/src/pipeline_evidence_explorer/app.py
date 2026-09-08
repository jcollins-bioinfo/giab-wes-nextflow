"""Render validated synthetic evidence with an explicit missing-results boundary."""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from dash import Dash, Input, Output, dcc, html
from flask import Response
import plotly.graph_objects as go

from . import __version__
from .model import MANIFEST_SHA256, REPO, Snapshot, load_snapshot, select_tasks

DEFAULT_PREFIX = "/research/giab-wes-nextflow/explorer/"


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


def create_app(*, bundle_dir: Path | None = None, prefix: str = DEFAULT_PREFIX) -> Dash:
    """Create an isolated Flask/Dash app, failing readiness on invalid evidence."""
    if not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*", prefix):
        raise ValueError("invalid application prefix")
    snapshot: Snapshot | None = None
    try:
        snapshot = load_snapshot(bundle_dir)
    except (ValueError, OSError, KeyError, TypeError):
        pass
    app = Dash(__name__, requests_pathname_prefix=prefix, routes_pathname_prefix=prefix,
               title="Pipeline Evidence Explorer", update_title=None,
               assets_folder=str(Path(__file__).parent / "assets"))
    app.server.config.update(MAX_CONTENT_LENGTH=1_000_000)

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
                html.Div([html.Strong("DeepVariant WES"), html.Span("Native-call gate failed", className="badge pending")], className="caller"),
                html.P(data.caller_observation),
                html.P("DeepVariant and its prediction inspector completed. Both-mode and final resume qualification remain open."),
                html.P("The M4 fixture has 528 primary reads. Its caller observations are separate from the 48-read M3 run plotted here.", className="note"),
                html.A("Inspect the recorded caller run ↗", href=f"{REPO}/actions/runs/{data.m4_run_id}")], className="panel")], className="columns"),
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
                 html.Dt("M4 diagnostic source SHA"), html.Dd(html.Code(data.m4_sha)),
                 html.Dt("Shared M3 BAM SHA-256"), html.Dd(html.Code(data.bam_sha256)),
                 html.Dt("Shared M3 BAI SHA-256"), html.Dd(html.Code(data.bai_sha256)),
                 html.Dt("Explorer evidence manifest SHA-256"), html.Dd(html.Code(MANIFEST_SHA256))]),
        html.H3("Verified source inventory"), html.Ul([html.Li([html.Strong(name), html.Br(), html.Code(sha)]) for name, sha in data.sources]),
        html.A("Download validated evidence JSON", href=prefix + "evidence.json", className="button"),
        html.H3("Field ownership"), html.P("Read/QC cards: m3-proof.json → bam_assertions. Execution cards: resume_assertions. Task table: m3-first.trace.tsv. Caller status: m4-attempt.json → execution_scope. Domain decision: domain-approval.json. Benchmark metrics are null, with an explicit missing reason.")], className="panel")
    app.layout = html.Div([html.Header([html.A("JPC / RESEARCH", href=REPO, className="brand"),
        html.Span(f"EXPLORER {__version__}", className="version")]), html.Main([
        html.Div("SYNTHETIC EVIDENCE PROTOTYPE", className="scope"), html.H1("Pipeline Evidence Explorer"),
        html.P("From raw reads to inspectable evidence.", className="subtitle"),
        html.P("GIAB HG001 WES project · John Patrick Collins · Public engineering work, 2026", className="byline"),
        html.Div("This preview contains invented test data and recorded qualification outcomes. It does not report HG001 accuracy or a caller winner.", className="notice", role="note"),
        html.Fieldset([html.Legend("Choose evidence view", className="sr-only"),
            dcc.RadioItems(id="view", options=[{"label": x.title(), "value": x} for x in ("overview", "execution", "provenance")],
                           value="overview", inline=True, className="section-nav")]),
        html.Div(overview, id="overview-panel"), html.Div(execution, id="execution-panel", style={"display": "none"}),
        html.Div(provenance, id="provenance-panel", style={"display": "none"})]),
        html.Footer(["Source-owned measurements. Explicit limitations. ", html.A("View repository ↗", href=REPO)])])

    @app.callback(Output("overview-panel", "style"), Output("execution-panel", "style"),
                  Output("provenance-panel", "style"), Input("view", "value"))
    def choose_view(selection: str) -> tuple[dict[str, str], ...]:
        """Switch panels with keyboard-accessible native radio controls."""
        return tuple({"display": "block" if selection == name else "none"}
                     for name in ("overview", "execution", "provenance"))

    @app.callback(Output("task-table", "children"), Input("process", "value"))
    def filter_tasks(selection: str) -> Any:
        """Filter validated observations only; invalid selections expose no data path."""
        try:
            return task_table(data, selection)
        except ValueError:
            return html.P("Choose a process from the list.")

    app.server.config["EXPLORER_SNAPSHOT"] = data
    return app


def main() -> None:
    """Serve a local preview; public deployment requires separate authorization."""
    create_app().run(host="127.0.0.1", port=int(os.environ.get("PORT", "8050")), debug=False)

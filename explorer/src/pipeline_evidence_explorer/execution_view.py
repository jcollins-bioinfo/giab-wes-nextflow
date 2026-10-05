"""Render accepted managed task metadata without querying any cloud service."""
from __future__ import annotations

from typing import Any
from dash import dcc, html
import plotly.graph_objects as go

from .execution import ExecutionSnapshot, MANAGED_SHA256
from .model import require


def timeline_figure(data: ExecutionSnapshot, selection: str = "all") -> go.Figure:
    """Display precomputed provider intervals; do not sum them into wall time."""
    require(isinstance(selection, str), "invalid managed task selection")
    require(selection == "all" or selection in {row.key for row in data.timeline}, "unknown managed task")
    rows = [row for row in data.timeline if selection == "all" or row.key == selection]
    chart = go.Figure()
    for label, color, starts, lengths in (
        ("Creation to start (queue / staging combined)", "#d69b39", [row.created for row in rows], [row.staging_seconds for row in rows]),
        ("Provider start to stop", "#087f8c", [row.start for row in rows], [row.provider_seconds for row in rows]),
    ):
        chart.add_trace(go.Bar(name=label, y=[row.label for row in rows], x=lengths, base=starts,
            orientation="h", marker_color=color, customdata=[row.key for row in rows],
            hovertemplate="%{y}<br>%{x:.3f} seconds<extra>%{fullData.name}</extra>"))
    chart.update_layout(template="plotly_white", barmode="overlay", height=max(330, len(rows) * 27 + 125),
        margin=dict(l=10, r=20, t=65, b=40), xaxis_title="Seconds after provider run start",
        yaxis=dict(autorange="reversed", automargin=True), legend=dict(orientation="h", y=1.08),
        font=dict(size=11), clickmode="event+select")
    return chart


def task_detail(data: ExecutionSnapshot, selection: str) -> Any:
    """Expose task identity, resource missingness and safe artifact hashes."""
    if selection == "all":
        return html.P("Choose a task from the keyboard-accessible list or click a timeline bar to inspect its attempt, requested resources and artifact identities.")
    task = next((item for item in data.record["tasks"] if item["key"] == selection), None)
    require(task is not None, "unknown managed task")
    row = next(item for item in data.timeline if item.key == selection)
    fields = [
        ("Process", task["process"]), ("Input group", task["label"]),
        ("Process-local index", task["index"]), ("Attempt", task["attempt"]),
        ("Provider status", task["status"]),
        ("Cache / retries", "No managed cache qualification; a complete retry history is not supplied."),
        ("Creation to start, seconds", round(row.staging_seconds, 6)),
        ("Provider start to stop, seconds", round(row.provider_seconds, 6)),
        ("Native command elapsed, seconds", task["native_seconds"]),
        ("Requested vCPUs", task["requested_cpus"]),
        ("Requested memory, bytes", task["requested_memory_bytes"]),
        ("Observed task CPU seconds", task["cpu_seconds"]),
        ("Observed task peak RSS, bytes", task["peak_rss_bytes"]),
        ("Image platform-manifest digest", task["image_digest"]),
        ("Native command SHA-256", task["command_sha256"]),
    ]
    artifacts = []
    for direction in ("inputs", "outputs"):
        artifacts.append(html.H4(direction.title() + " (byte identities only)"))
        artifacts.append(html.Ul([html.Li([html.Code(item["sha256"]), f" · {item['bytes']:,} bytes"]) for item in task[direction]]) if task[direction] else html.P("Unavailable in this public projection."))
    return html.Div([html.H3(row.label), html.Dl([part for name, value in fields for part in
        (html.Dt(name), html.Dd(html.Code(str(value)) if value is not None else "Unavailable: not observed in the retained source."))]),
        html.P("Requested resources are reservations, not observed usage. Provider intervals include container overhead; creation-to-start does not separate queue and staging. Native command timing has whole-second resolution. No launcher CPU or task-time sum substitutes for measured task CPU or run elapsed time.", className="note"),
        html.Details([html.Summary("Inspect artifact lineage"), *artifacts])])


def managed_overview(data: ExecutionSnapshot | None, prefix: str) -> Any:
    if data is None:
        return html.Section([html.H2("Managed evidence unavailable"), html.P("The managed nonhuman snapshot failed its immutable identity or evidence checks.")], className="panel")
    record = data.record
    return html.Section([html.Div("ACCEPTED MANAGED NONHUMAN EVIDENCE", className="scope"),
        html.H2("A complete managed workflow, with HG001 still unavailable"),
        html.P(f"Observed {record['observed_date']}: 28 completed tasks across 21 processes on Nextflow {record['engine']} / {record['parser']}. The independently accepted invented fixture has 23 native observation joins, 528 verified original-quality records and 198 returned objects rehashed."),
        html.P(f"Provider run elapsed: {record['elapsed_seconds']:.3f} seconds. Managed cache invalidation and real HG001 acceptance remain unqualified in this snapshot."),
        html.P(["Exact tested workflow source: ", html.Code(record["repository_sha"])]),
        html.A("Download sanitized managed execution metadata", href=prefix + "managed/evidence.json", className="button")], className="panel")


def managed_execution(data: ExecutionSnapshot | None) -> Any:
    if data is None:
        return html.Section([html.H2("Managed execution unavailable"), html.P("Restore the pinned managed snapshot.")], className="panel")
    return html.Section([html.H2("Managed nonhuman execution timeline"),
        html.P("Accepted invented fixture observed 2026-09-15. The chart preserves overlap between tasks. These timings do not estimate HG001 runtime or caller cost."),
        html.Label("Managed task", htmlFor="managed-task"),
        dcc.Dropdown(id="managed-task", value="all", clearable=False,
            options=[{"label": "All 28 tasks", "value": "all"}] + [{"label": row.label, "value": row.key} for row in data.timeline]),
        dcc.Graph(id="managed-timeline", figure=timeline_figure(data), responsive=True, config={"displayModeBar": False}),
        html.Div(task_detail(data, "all"), id="managed-task-detail", **{"aria-live": "polite"}),
        html.P(["Sanitized execution SHA-256: ", html.Code(MANAGED_SHA256)], className="note")], className="panel")

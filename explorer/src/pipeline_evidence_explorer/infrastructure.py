"""Read a source-bound, sanitized declaration snapshot, never Terraform state."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from dash import html
from .model import REPO, require

INFRASTRUCTURE_SHA256 = "2f38a966accb3ae94f4acd29e9c98077b2dab3e824d6d3aa88d44a3a243ba635"


def validate_infrastructure(record: dict[str, Any]) -> None:
    require(set(record) == {"schema_version", "observed_date", "repository_sha", "evidence_state", "source_files", "components", "relationships"}, "unexpected infrastructure fields")
    require(record["schema_version"] == "1.0.0" and record["evidence_state"] == "declared", "infrastructure snapshot is declarations only")
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["observed_date"]) is not None, "invalid observation date")
    require(re.fullmatch(r"[a-f0-9]{40}", record["repository_sha"]) is not None, "invalid infrastructure source identity")
    for source in record["source_files"]:
        require(set(source) == {"path", "sha256"} and re.fullmatch(r"(?:infra/[a-z0-9_./-]+|cloud.nf)", source["path"]) is not None and ".." not in source["path"], "unsafe source location")
        require(re.fullmatch(r"[a-f0-9]{64}", source["sha256"]) is not None, "invalid declaration identity")
    ids = {node["id"] for node in record["components"]}
    require(len(ids) == len(record["components"]), "duplicate infrastructure component")
    for node in record["components"]:
        require(set(node) == {"id", "name", "owner", "state", "purpose", "source"} and node["state"] == "declared", "unsupported infrastructure observation")
        require(node["source"] in {source["path"] for source in record["source_files"]}, "unknown declaration source")
    for edge in record["relationships"]:
        require(set(edge) == {"from", "to", "relationship"} and edge["from"] in ids and edge["to"] in ids, "unknown infrastructure relationship")
    text = json.dumps(record)
    require(not any(marker in text for marker in ("arn:", "s3://", "amazonaws.com", "/Users/", "account_id", "tfstate")), "private infrastructure content")


def load_infrastructure(path: Path | None = None) -> dict[str, Any]:
    path = path or Path(__file__).parent / "data/infrastructure-declared.json"
    require(not any(item.is_symlink() for item in (path, *path.parents)), "linked infrastructure snapshot")
    require(path.is_file() and path.stat().st_size < 100_000, "missing infrastructure snapshot")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == INFRASTRUCTURE_SHA256, "infrastructure snapshot identity mismatch")
    record = json.loads(raw); validate_infrastructure(record)
    return record


def infrastructure_view(record: dict[str, Any] | None, prefix: str) -> Any:
    if record is None:
        return html.Section([html.H2("Infrastructure declarations unavailable"), html.P("The sanitized source snapshot failed validation.")], className="panel")
    names = {node["id"]: node["name"] for node in record["components"]}
    return html.Section([html.H2("Infrastructure ownership and relationships"),
        html.Div("DECLARED CONFIGURATION · NO LIVE RESOURCE CLAIM", className="scope"),
        html.P(f"Source snapshot observed {record['observed_date']}. This view describes reviewed repository declarations. It contains no plan, apply receipt or current provider inventory."),
        html.H3("Provisioning and scheduling have different owners"),
        html.P("Terraform declares storage, identity permissions, registry, logs and optional compute or hosting resources. Nextflow schedules scientific processes, stages their declared inputs, tracks dependencies and records task/cache behavior. A Terraform declaration does not establish that a workflow ran or that a service is deployed."),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(x, scope="col") for x in ("Component", "Owner", "Evidence state", "Responsibility")])),
            html.Tbody([html.Tr([html.Td(node['name']), html.Td(node['owner']), html.Td(node['state']), html.Td(node['purpose'], className="wrap-cell")]) for node in record['components']])]), className="table-wrap"),
        html.H3("Declared relationships"),
        html.Ul([html.Li([html.Strong(names[edge['from']]), ' → ', html.Strong(names[edge['to']]), ': '+edge['relationship']]) for edge in record['relationships']]),
        html.H3("What each state establishes"),
        html.Ul([html.Li("Declared: the versioned source describes the resource or workflow."),
                 html.Li("Planned: a reviewed Terraform plan would describe proposed changes; no plan is included here."),
                 html.Li("Applied: an apply receipt would establish provisioning at its observation time; none is included here."),
                 html.Li("Live verified: a dated provider observation would establish current service state; none is included here.")]),
        html.P("The separate execution view establishes a historical managed nonhuman run on its own accepted receipts. It does not upgrade these infrastructure declarations to a current live inventory. Public hosting and DNS status remain unavailable in this snapshot.", className="note"),
        html.Details([html.Summary("Inspect declaration source identities"), html.Ul([html.Li([html.A(source['path'], href=REPO+'/blob/'+record['repository_sha']+'/'+source['path']), html.Br(), html.Code(source['sha256'])]) for source in record['source_files']])]),
        html.A("Download sanitized infrastructure declarations", href=prefix+'infrastructure/evidence.json', className="button")], className="panel")

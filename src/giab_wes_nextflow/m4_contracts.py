"""Validate isolated shared-BAM inputs and native synthetic dual-caller evidence."""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import tempfile
from typing import Any

from jsonschema import Draft202012Validator

from . import __version__
from .acquisition import checksum, destination, safe_root
from .m3 import canonical_hash, checked_file, validate_reference
from .m3_collect import validate_result_bundle
from .resources import config_path, schema_path
from .synthetic_fixtures import fixture_contract

CALLERS = ("gatk", "deepvariant")
INPUT_FILES = ("shared.bam", "shared.bam.bai", "reference.fa", "reference.fa.fai", "reference.dict", "regions.bed")
MODEL_FILES = {"fingerprint.pb", "saved_model.pb", "model.example_info.json",
               "variables/variables.data-00000-of-00001", "variables/variables.index"}


def load_json(path: str | Path) -> dict[str, Any]:
    """Reject ambiguous duplicate JSON keys at every nested contract boundary."""
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Construct one object only when each source key occurs exactly once."""
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key in M4 evidence")
            result[key] = value
        return result

    result = json.loads(checked_file(path).read_text(), object_pairs_hook=unique_object)
    if not isinstance(result, dict):
        raise ValueError("M4 JSON boundary requires an object")
    return result


def _envelope(kind: str, run_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Create a current synthetic-only contract with a canonical payload hash."""
    result = {"schema_version": "1.0.0", "artifact_type": kind, "run_id": run_id,
              "producer": {"package": "giab-wes-nextflow", "version": __version__, "module": "giab_wes_nextflow.m4_contracts"},
              "synthetic": True, "canonical": False, "data": data}
    result["payload_sha256"] = canonical_hash(result)
    validate_envelope(result)
    return result


def validate_envelope(record: dict[str, Any]) -> None:
    """Require the exact M4 schema and self-independent payload identity."""
    kind = record.get("artifact_type")
    if kind not in {"inputs", "caller", "bundle"}:
        raise ValueError("unknown M4 evidence kind")
    Draft202012Validator(load_json(schema_path(f"m4-{kind}.schema.json"))).validate(record)
    if canonical_hash({key: value for key, value in record.items() if key != "payload_sha256"}) != record["payload_sha256"]:
        raise ValueError("M4 payload hash mismatch")


def _write(path: Path, content: bytes) -> None:
    """Write one immutable guarded file, preserving every conflicting artifact."""
    root = safe_root(path.parent, allow_test_root=True)
    target = destination(root, path.name)
    root.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and target.read_bytes() != content):
        raise FileExistsError(f"conflicting immutable M4 artifact: {path.name}")
    if not target.exists():
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.is_symlink() or target.read_bytes() != content:
                    raise FileExistsError(f"conflicting immutable M4 artifact: {path.name}") from None
        finally:
            temporary.unlink(missing_ok=True)


def write_record(path: str | Path, record: dict[str, Any]) -> None:
    """Validate and persist JSON without silently changing an earlier result."""
    validate_envelope(record)
    _write(Path(path), (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def _file(path: str | Path) -> dict[str, Any]:
    """Identify bytes by a logical filename with no local absolute path."""
    source = checked_file(path)
    return {"filename": Path(path).name, "bytes": source.stat().st_size, "sha256": checksum(source)}


def _input_semantics(record: dict[str, Any]) -> None:
    """Bind declared reference and calling regions to the registered positive fixture."""
    validate_envelope(record)
    if record["artifact_type"] != "inputs":
        raise ValueError("expected M4 caller input contract")
    data = record["data"]
    contract = fixture_contract("m4-snv-positive")
    expected = contract.expectations
    files = {item["filename"]: item for item in data["files"]}
    regions = [{"contig": name, "start": 0, "end": length} for name, length in expected["contigs"].items()]
    region_bytes = "".join(f"{item['contig']}\t0\t{item['end']}\n" for item in regions).encode()
    if (len(files) != len(INPUT_FILES) or set(files) != set(INPUT_FILES)
            or data["fixture_id"] != contract.fixture_id or data["fixture_manifest_sha256"] != contract.manifest_sha256
            or data["sample"] != expected["sample"] or data["calling_regions"] != regions
            or files["reference.fa"]["sha256"] != expected["files"]["reference.fa"]["sha256"]
            or data["known_sites_sha256"] != expected["files"]["known-sites.vcf"]["sha256"]
            or files["reference.fa"]["bytes"] != expected["files"]["reference.fa"]["bytes"]
            or files["regions.bed"]["sha256"] != hashlib.sha256(region_bytes).hexdigest()
            or files["regions.bed"]["bytes"] != len(region_bytes)):
        raise ValueError("M4 caller inputs differ from the fixed synthetic source/domain")


def prepare_inputs(bundle: str | Path, bam: str | Path, bai: str | Path,
                   reference_bundle: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Copy only accepted BAM/reference bytes into an isolated regular-file directory."""
    source_manifest = Path(bundle) / "m3-manifest.json" if Path(bundle).is_dir() else Path(bundle)
    manifest_sha256 = checksum(checked_file(source_manifest))
    records = validate_result_bundle(bundle)
    if checksum(checked_file(source_manifest)) != manifest_sha256:
        raise ValueError("preprocessing manifest changed during M4 preparation")
    provenance = records["provenance"]["data"]
    contract = fixture_contract("m4-snv-positive")
    if provenance["fixture_expectations_sha256"] != contract.manifest_sha256:
        raise ValueError("M4 requires the registered variant-positive preprocessing fixture")
    reference = Path(reference_bundle)
    validate_reference(reference / "reference.fa", contract.expectations,
                       reference / "reference.fa.fai", reference / "reference.dict")
    for path, key in ((bam, "bam"), (bai, "bai")):
        expected = records["alignment"]["data"][key]
        actual = _file(path)
        if actual["sha256"] != expected["sha256"] or actual["bytes"] != expected["bytes"]:
            raise ValueError("M4 shared BAM/BAI differs from accepted preprocessing")
    root = safe_root(output_dir, allow_test_root=True)
    if root.exists() and not {item.name for item in root.iterdir()} <= set(INPUT_FILES) | {"m4-inputs.json"}:
        raise ValueError("caller input destination contains unexpected files")
    sources = {"shared.bam": bam, "shared.bam.bai": bai, "reference.fa": reference / "reference.fa",
               "reference.fa.fai": reference / "reference.fa.fai", "reference.dict": reference / "reference.dict"}
    before = {name: _file(source) for name, source in sources.items()}
    for name, key in (("shared.bam", "bam"), ("shared.bam.bai", "bai")):
        if any(before[name][field] != records["alignment"]["data"][key][field] for field in ("sha256", "bytes")):
            raise ValueError("shared BAM/BAI changed before copy")
    for name, source in sources.items():
        _write(root / name, checked_file(source).read_bytes())
        if any(_file(root / name)[field] != before[name][field] for field in ("sha256", "bytes")):
            raise ValueError("M4 source changed during isolated copy")
    validate_reference(root / "reference.fa", contract.expectations,
                       root / "reference.fa.fai", root / "reference.dict")
    regions = [{"contig": name, "start": 0, "end": length} for name, length in contract.expectations["contigs"].items()]
    _write(root / "regions.bed", "".join(f"{item['contig']}\t0\t{item['end']}\n" for item in regions).encode())
    data = {"repository_sha": provenance["repository_sha"], "sample": provenance["sample"],
            "fixture_id": contract.fixture_id, "fixture_manifest_sha256": contract.manifest_sha256,
            "preprocessing_manifest_sha256": manifest_sha256,
            "preprocessing_payload_sha256": records["bundle"]["payload_sha256"],
            "known_sites_sha256": provenance["known_sites_sha256"], "calling_regions": regions,
            "quality_policy": {"gatk": "QUAL", "deepvariant": "OQ"},
            "bqsr_policy": "shared_accepted_BaseRecalibrator_ApplyBQSR_emit_OQ",
            "files": [_file(root / name) for name in INPUT_FILES]}
    result = _envelope("inputs", records["bundle"]["run_id"], data)
    _input_semantics(result)
    if {item.name for item in root.iterdir()} - {"m4-inputs.json"} != set(INPUT_FILES):
        raise ValueError("caller input inventory changed before acceptance marker")
    write_record(root / "m4-inputs.json", result)
    validate_caller_inputs(root)
    return result


def validate_caller_inputs(path: str | Path) -> dict[str, Any]:
    """Rehash the closed input inventory and reject links or unexpected files."""
    root = Path(path)
    record = load_json(root / "m4-inputs.json")
    _input_semantics(record)
    if {item.name for item in root.iterdir()} != set(INPUT_FILES) | {"m4-inputs.json"}:
        raise ValueError("caller input directory contains unexpected files")
    for item in record["data"]["files"]:
        source = root / item["filename"]
        if source.is_symlink() or _file(source) != item:
            raise ValueError("M4 caller input must be a hash-matched regular file")
    return record


def _native_records(path: str | Path) -> tuple[str, dict[str, int], list[dict[str, Any]]]:
    """Parse one-sample native VCF without normalizing its original representation."""
    source = checked_file(path)
    opener = gzip.open if source.suffix == ".gz" else open
    contigs: dict[str, int] = {}
    sample = ""
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    with opener(source, "rt") as stream:
        for line in stream:
            if line.startswith("##contig="):
                match = re.search(r"ID=([^,>]+),length=([0-9]+)", line)
                if match is None or match[1] in contigs:
                    raise ValueError("invalid or duplicate native VCF contig")
                contigs[match[1]] = int(match[2])
            elif line.startswith("#CHROM"):
                fields = line.rstrip().split("\t")
                if len(fields) != 10 or sample:
                    raise ValueError("native VCF must have exactly one sample header")
                sample = fields[9]
            elif not line.startswith("#"):
                fields = line.rstrip().split("\t")
                if len(fields) != 10 or not sample:
                    raise ValueError("invalid native VCF record")
                name, pos, _identifier, ref, alt, qual, filter_value, info, fmt, value = fields
                position = int(pos)
                key = (name, position, ref, alt)
                if key in seen or name not in contigs or not 1 <= position <= contigs[name] or not re.fullmatch("[ACGTN]+", ref):
                    raise ValueError("native VCF coordinate/reference identity invalid")
                seen.add(key)
                format_keys = fmt.split(":")
                values = value.split(":")
                if len(format_keys) != len(set(format_keys)) or len(values) > len(format_keys):
                    raise ValueError("ambiguous native VCF FORMAT fields")
                if qual != "." and (not math.isfinite(float(qual)) or float(qual) < 0):
                    raise ValueError("native VCF QUAL must be finite and nonnegative")
                call_fields = dict(zip(format_keys, values))
                genotype = call_fields.get("GT")
                if genotype is None or not re.fullmatch(r"(?:[0-9]+|\.)[/|](?:[0-9]+|\.)", genotype):
                    raise ValueError("native VCF requires a diploid genotype")
                end_match = re.search(r"(?:^|;)END=([0-9]+)(?:;|$)", info)
                end = int(end_match[1]) if end_match else position + len(ref) - 1
                if not position <= end <= contigs[name]:
                    raise ValueError("native VCF end coordinate is out of bounds")
                records.append({"contig": name, "position": position, "end": end, "ref": ref,
                                "alt": alt.split(","), "genotype": genotype.replace("|", "/"), "filter": filter_value,
                                "diagnostic_format": {key: call_fields.get(key) for key in ("GQ", "DP", "AD", "PL")}})
    if not sample:
        raise ValueError("missing native VCF header")
    return sample, contigs, records


def _native_site_diagnostic(path: str | Path) -> dict[str, Any]:
    """Describe frozen synthetic loci with bounded values, never arbitrary VCF text.

    This failure-only evidence is not acceptance. Require the registered sample
    and dictionary; expose only SNV/known symbolic alleles, short numeric GTs and
    known filters. Hash other strings, omit paths, and cap rows and ALT entries.
    """
    expected = fixture_contract("m4-snv-positive").expectations
    sample, contigs, records = _native_records(path)
    if sample != expected["sample"] or list(contigs.items()) != list(expected["contigs"].items()):
        raise ValueError("native diagnostics require the registered synthetic sample/reference")

    def bounded(value: str, kind: str) -> str | dict[str, Any]:
        """Keep only closed safe vocabularies and hash every other source string."""
        allowed = ((kind == "allele" and (re.fullmatch("[ACGTN]", value) is not None
                    or value in {".", "*", "<NON_REF>", "<*>"}))
                   or (kind == "genotype" and len(value) <= 16
                       and re.fullmatch(r"(?:[0-9]+|\.)/(?:[0-9]+|\.)", value) is not None)
                   or (kind == "filter" and value in {"PASS", ".", "RefCall", "LowQual"}))
        return value if allowed else {"length": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()}

    def numeric(value: str | None, *, array: bool) -> Any:
        """Expose short nonnegative numeric fields or null; hash other FORMAT text."""
        if value is None or value == ".":
            return None
        parts = value.split(",") if array else [value]
        if len(parts) <= 8 and all(len(part) <= 16 and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", part) for part in parts):
            numbers = [float(part) if "." in part else int(part) for part in parts]
            return numbers if array else numbers[0]
        return {"length": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()}

    sites = []
    for site in expected["variant_sites"]:
        rows = [item for item in records if item["contig"] == site["contig"]
                and item["position"] <= site["position_1based"] <= item["end"]]
        sites.append({"contig": site["contig"], "position_1based": site["position_1based"],
                      "expected": {key: site[key] for key in ("ref", "alt", "genotype")},
                      "overlapping_record_count": len(rows), "rows_truncated": len(rows) > 4,
                      "rows": [{"position_1based": item["position"], "end_1based": item["end"],
                                "ref": bounded(item["ref"], "allele"),
                                "alt": [bounded(value, "allele") for value in item["alt"][:4]],
                                "alt_count": len(item["alt"]), "alts_truncated": len(item["alt"]) > 4,
                                "genotype": bounded(item["genotype"], "genotype"),
                                "filter": bounded(item["filter"], "filter"),
                                "format": {key: numeric(item["diagnostic_format"][key], array=key in {"AD", "PL"})
                                           for key in ("GQ", "DP", "AD", "PL")}} for item in rows[:4]]})
    source = checked_file(path)
    return {"schema_version": "1.0.0", "fixture_id": "m4-snv-positive", "acceptance": False,
            "file_bytes": source.stat().st_size, "file_sha256": checksum(source),
            "record_count": len(records), "sites": sites}


def validate_native_calls(vcf_path: str | Path, *, caller: str,
                          fixture_id: str = "m4-snv-positive") -> dict[str, Any]:
    """Require the two frozen easy SNVs and no nonreference call at the control."""
    if caller not in CALLERS or fixture_id != "m4-snv-positive":
        raise ValueError("unregistered caller or fixture")
    expected = fixture_contract(fixture_id).expectations
    reference: dict[str, str] = {}
    name = ""
    for line in fixture_contract(fixture_id).payloads["reference.fa"].decode().splitlines():
        if line.startswith(">"):
            name = line[1:]
            reference[name] = ""
        else:
            reference[name] += line
    sample, contigs, records = _native_records(vcf_path)
    if sample != expected["sample"] or contigs != expected["contigs"] or list(contigs) != list(expected["contigs"]):
        raise ValueError("native VCF sample/reference dictionary mismatch")
    previous = (-1, -1)
    for item in records:
        offset = item["position"] - 1
        key = (list(contigs).index(item["contig"]), item["position"])
        if reference[item["contig"]][offset:offset + len(item["ref"])] != item["ref"] or key < previous:
            raise ValueError("native VCF REF or coordinate order differs from reference")
        previous = key
        alleles = [item["ref"]] + item["alt"]
        if any(value != "." and int(value) >= len(alleles) for value in item["genotype"].split("/")):
            raise ValueError("native VCF genotype allele index is invalid")
    accepted = []
    for site in expected["variant_sites"]:
        rows = [item for item in records if item["contig"] == site["contig"] and item["position"] == site["position_1based"]]
        wanted = sorted([site["ref"], site["alt"]] if site["genotype"] == "0/1" else [site["alt"], site["alt"]])
        valid = []
        for item in rows:
            alleles = [item["ref"]] + item["alt"]
            gt = item["genotype"].split("/")
            if all(value.isdigit() and int(value) < len(alleles) for value in gt):
                if sorted(alleles[int(value)] for value in gt) == wanted and item["filter"] in {"PASS", "."}:
                    valid.append(item)
        if len(valid) != 1:
            try:
                diagnostic = _native_site_diagnostic(vcf_path)
            except (ValueError, OSError, UnicodeError, EOFError):
                diagnostic = {"acceptance": False, "status": "unavailable_or_invalid_synthetic_vcf"}
            raise ValueError("native caller failed a frozen positive SNV genotype; synthetic_native_diagnostic="
                             + json.dumps(diagnostic, sort_keys=True, separators=(",", ":")))
        accepted.append({"contig": site["contig"], "position_1based": site["position_1based"], "ref": site["ref"],
                         "alt": site["alt"], "genotype": site["genotype"]})
    for control in expected["reference_controls"]:
        for item in records:
            if item["contig"] == control["contig"] and item["position"] <= control["position_1based"] <= item["end"]:
                if any(value not in {"0", "."} for value in item["genotype"].split("/")):
                    raise ValueError("nonreference call at frozen reference control")
    return {"record_count": len(records), "expected_positive_sites": accepted,
            "reference_control_nonreference_calls": 0, "acceptance": "invented_integration_only"}


def _shell_command_lines(command: str) -> list[list[str]]:
    """Tokenize wrapper lines across quoted newlines without executing shell syntax.

    These recorded wrappers contain one command per logical line. Preserve quoted
    literal newlines, remove shell line continuations only outside single quotes,
    and ignore quote characters in comments. This is an evidence reader, not a
    general shell interpreter or a replacement for the actual task/mount audit.
    """
    lines: list[str] = []
    current: list[str] = []
    quote: str | None = None
    comment = False
    index = 0
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'" and not comment and index + 1 < len(command):
            following = command[index + 1]
            if following != "\n":
                current.extend((character, following))
            index += 2
            continue
        if character == "\n" and quote is None:
            lines.append("".join(current))
            current = []
            comment = False
        else:
            current.append(character)
            if not comment:
                if character == "#" and quote is None:
                    comment = True
                elif character in {"'", '"'}:
                    if quote is None:
                        quote = character
                    elif quote == character:
                        quote = None
        index += 1
    if quote is not None:
        raise ValueError("caller command script contains an unclosed shell quote")
    if current:
        lines.append("".join(current))
    return [shlex.split(line, comments=True) for line in lines]


def _parameters(caller: str, command: str) -> dict[str, Any]:
    """Read explicit scientific flags from the actual copied command script."""
    candidates = [tokens for tokens in _shell_command_lines(command) if tokens and
                  ((tokens[0] == "gatk" and "HaplotypeCaller" in tokens) if caller == "gatk" else
                   (tokens[0] == "/opt/deepvariant/bin/run_deepvariant" and
                    any(token.startswith("--model_type") for token in tokens)))]
    if len(candidates) != 1:
        raise ValueError("caller command must contain exactly one scientific invocation")
    tokens = candidates[0]
    allowed = ({"--java-options", "--reference", "--input", "--intervals", "--interval-padding",
                "--native-pair-hmm-threads", "--standard-min-confidence-threshold-for-calling",
                "--emit-ref-confidence", "--create-output-variant-index", "--output"} if caller == "gatk" else
               {"--model_type", "--ref", "--reads", "--regions", "--sample_name", "--num_shards",
                "--postprocess_cpus", "--make_examples_extra_args", "--output_vcf", "--output_gvcf",
                "--intermediate_results_dir", "--logging_dir"})
    if any(token.startswith("--") and token.split("=", 1)[0] not in allowed for token in tokens):
        raise ValueError("unapproved caller command parameter")
    if any(token.startswith("-") and not token.startswith("--")
           and not (caller == "gatk" and re.fullmatch(r"-Xmx[0-9]+[mMgG]", token)) for token in tokens):
        raise ValueError("unapproved caller short option")

    def flag(name: str) -> str:
        """Require exactly one explicit long-option value in the command."""
        values = [token.split("=", 1)[1] for token in tokens if token.startswith(name + "=")]
        values += [tokens[index + 1] for index, token in enumerate(tokens[:-1]) if token == name]
        if len(values) != 1:
            raise ValueError(f"missing or repeated explicit caller parameter: {name}")
        return values[0]

    if caller == "gatk":
        expected = {"--reference": "caller-inputs/reference.fa", "--input": "caller-inputs/shared.bam",
                    "--intervals": "caller-inputs/regions.bed", "--interval-padding": "0",
                    "--create-output-variant-index": "true", "--output": "SYNTHETIC01.gatk.native.vcf.gz"}
        if tokens[0] != "gatk" or any(flag(name) != value for name, value in expected.items()):
            raise ValueError("GATK must use the isolated physical BAM/reference/regions and native indexed output")
        return {"native_pair_hmm_threads": int(flag("--native-pair-hmm-threads")),
                "standard_min_confidence_threshold_for_calling": float(flag("--standard-min-confidence-threshold-for-calling")),
                "emit_ref_confidence": flag("--emit-ref-confidence")}
    expected = {"--ref": "caller-inputs/reference.fa", "--reads": "caller-inputs/shared.bam",
                "--regions": "caller-inputs/regions.bed", "--sample_name": "SYNTHETIC01",
                "--output_vcf": "SYNTHETIC01.deepvariant.native.vcf.gz",
                "--output_gvcf": "SYNTHETIC01.deepvariant.native.g.vcf.gz",
                "--intermediate_results_dir": "deepvariant.intermediate", "--logging_dir": "deepvariant.logs"}
    if tokens[0] != "/opt/deepvariant/bin/run_deepvariant" or any(flag(name) != value for name, value in expected.items()):
        raise ValueError("DeepVariant must use the isolated physical BAM/reference/regions and native outputs")
    if flag("--make_examples_extra_args") != "use_original_quality_scores=true":
        raise ValueError("DeepVariant must use original OQ without extra hidden parameters")
    return {"model_type": flag("--model_type"), "num_shards": int(flag("--num_shards")),
            "postprocess_cpus": int(flag("--postprocess_cpus")), "use_original_quality_scores": True}


def _model_inventory(record: dict[str, Any], tool: dict[str, Any]) -> list[dict[str, Any]]:
    """Bind the five runtime model identities to the pinned metadata file."""
    files = record["model_files"]
    names = [item["filename"] for item in files]
    if record.get("model_type") != "WES" or len(names) != 5 or set(names) != MODEL_FILES:
        raise ValueError("incomplete WES model inventory")
    for item in files:
        if set(item) != {"filename", "bytes", "sha256"} or type(item["bytes"]) is not int or item["bytes"] <= 0 or not re.fullmatch("[0-9a-f]{64}", item["sha256"]):
            raise ValueError("invalid model file identity")
    metadata = next(item for item in files if item["filename"] == "model.example_info.json")
    if metadata["sha256"] != tool["model"]["example_info_sha256"] or metadata["bytes"] != tool["model"]["example_info_bytes"]:
        raise ValueError("WES model metadata differs from pinned primary source")
    return sorted(files, key=lambda item: item["filename"])


def _caller_semantics(record: dict[str, Any], inputs: dict[str, Any]) -> None:
    """Rebind persisted caller identity and scientific settings to the installed lock."""
    validate_envelope(record)
    if record["artifact_type"] != "caller":
        raise ValueError("expected native caller record")
    data = record["data"]
    tool = load_json(config_path("m4-tools.json"))["tools"][data["caller"]]
    if (canonical_hash(data["tool_contract"]) != canonical_hash(tool)
            or canonical_hash(data["observed_parameters"]) != canonical_hash(tool["parameters"])
            or data["inputs_payload_sha256"] != inputs["payload_sha256"]
            or record["run_id"] != inputs["run_id"] or data["repository_sha"] != inputs["data"]["repository_sha"]
            or data["sample"] != inputs["data"]["sample"]):
        raise ValueError("M4 caller identity/parameters/input lineage differs from immutable contract")
    if re.search(r"(?<![0-9.])" + re.escape(tool["expected_reported_version"]) + r"(?![0-9.])", data["observed_version_text"]) is None:
        raise ValueError("observed caller executable version differs from lock")
    if data["resources"]["container"] != tool["image"]:
        raise ValueError("caller resource image differs from immutable lock")
    expected_sites = [{key: site[key] for key in ("contig", "position_1based", "ref", "alt", "genotype")}
                      for site in fixture_contract("m4-snv-positive").expectations["variant_sites"]]
    if data["native_acceptance"]["expected_positive_sites"] != expected_sites or data["native_acceptance"]["record_count"] < 2:
        raise ValueError("native acceptance differs from frozen positive SNV oracle")
    if data["resources"]["logical_artifact_id"] != f"m4_{data['caller']}" or data["resources"]["requested_cpus"] != 2:
        raise ValueError("caller declared resources do not match its execution contract")
    process = "M4_HAPLOTYPECALLER" if data["caller"] == "gatk" else "M4_DEEPVARIANT"
    if data["resources"]["process"] != process:
        raise ValueError("caller resource process identity differs")
    prefix = f"{data['sample']}.{data['caller']}.native"
    filenames = {"vcf": f"{prefix}.vcf.gz", "vcf_index": f"{prefix}.vcf.gz.tbi"}
    if data["caller"] == "deepvariant":
        filenames.update(gvcf=f"{prefix}.g.vcf.gz", gvcf_index=f"{prefix}.g.vcf.gz.tbi")
    if any(data["outputs"][key] is None or data["outputs"][key]["filename"] != value for key, value in filenames.items()):
        raise ValueError("native output filenames do not match the executed caller contract")
    if data["caller"] == "gatk" and any(data["outputs"][key] is not None for key in ("gvcf", "gvcf_index")):
        raise ValueError("GATK direct VCF mode cannot claim a gVCF")
    if data["caller"] == "deepvariant":
        if data["resources"]["architecture"] != "x86_64" or any(data["outputs"][key] is None for key in ("gvcf", "gvcf_index")):
            raise ValueError("DeepVariant requires x86_64 CPU and native gVCF identities")
        inference = data["inference"]
        before, after = _model_inventory(data["model_before"], tool), _model_inventory(inference, tool)
        if before != after or not inference["all_probabilities_valid"] or inference["probability_tolerance"] != 1e-5:
            raise ValueError("DeepVariant model/probability validation failed")
        if inference["example_record_count"] <= 0 or inference["call_variants_record_count"] <= 0:
            raise ValueError("DeepVariant requires nonzero candidate and actual inference records")
        if not set(inference["variant_contigs"]) <= set(fixture_contract("m4-snv-positive").expectations["contigs"]):
            raise ValueError("DeepVariant inference contains an unexpected contig")
        for key in ("example_files", "call_variants_files"):
            names = [item["filename"] for item in inference[key]]
            if len(names) != len(set(names)):
                raise ValueError("DeepVariant inference contains duplicate file identities")


def collect_caller(caller: str, inputs: str | Path, vcf: str | Path, vcf_index: str | Path,
                   version_file: str | Path, command_file: str | Path, resources: str | Path,
                   output: str | Path, *, gvcf: str | Path | None = None, gvcf_index: str | Path | None = None,
                   inference: str | Path | None = None, model_before: str | Path | None = None) -> dict[str, Any]:
    """Collect actual native artifacts and bounded synthetic acceptance outside callers."""
    if caller not in CALLERS:
        raise ValueError("unknown M4 caller")
    source = validate_caller_inputs(inputs)
    tool = load_json(config_path("m4-tools.json"))["tools"][caller]
    try:
        summary = validate_native_calls(vcf, caller=caller)
    except ValueError as error:
        if caller != "deepvariant" or gvcf is None or not str(error).startswith("native caller failed a frozen positive SNV genotype;"):
            raise
        try:
            diagnostic = _native_site_diagnostic(gvcf)
        except (ValueError, OSError, UnicodeError, EOFError):
            diagnostic = {"acceptance": False, "status": "unavailable_or_invalid_synthetic_gvcf"}
        raise ValueError(str(error) + "; synthetic_gvcf_diagnostic="
                         + json.dumps(diagnostic, sort_keys=True, separators=(",", ":"))) from None
    outputs = {"vcf": _file(vcf), "vcf_index": _file(vcf_index), "gvcf": None, "gvcf_index": None}
    if outputs["vcf_index"]["bytes"] <= 0:
        raise ValueError("native VCF index is empty")
    if caller == "deepvariant":
        if any(value is None for value in (gvcf, gvcf_index, inference, model_before)):
            raise ValueError("DeepVariant requires native gVCF and positive inference/model evidence")
        validate_native_calls(gvcf, caller=caller)
        outputs.update(gvcf=_file(gvcf), gvcf_index=_file(gvcf_index))
        if outputs["gvcf_index"]["bytes"] <= 0:
            raise ValueError("native gVCF index is empty")
    elif any(value is not None for value in (gvcf, gvcf_index, inference, model_before)):
        raise ValueError("direct GATK VCF mode cannot claim gVCF or neural inference")
    data = {"caller": caller, "repository_sha": source["data"]["repository_sha"], "sample": source["data"]["sample"],
            "inputs_payload_sha256": source["payload_sha256"], "tool_contract": tool,
            "observed_parameters": _parameters(caller, checked_file(command_file).read_text()),
            "observed_version_text": checked_file(version_file).read_text().strip(),
            "version_evidence": _file(version_file), "command_evidence": _file(command_file),
            "resources": load_json(resources), "resource_evidence": _file(resources),
            "outputs": outputs, "native_acceptance": summary,
            "inference": load_json(inference) if inference else None,
            "model_before": load_json(model_before) if model_before else None,
            "inference_evidence": _file(inference) if inference else None,
            "model_before_evidence": _file(model_before) if model_before else None}
    result = _envelope("caller", source["run_id"], data)
    _caller_semantics(result, source)
    write_record(output, result)
    return result


def bundle_results(inputs: str | Path, caller_results: list[str | Path], output_dir: str | Path) -> dict[str, Any]:
    """Write a mode-specific immutable JSON-only bundle with a closed inventory."""
    source = validate_caller_inputs(inputs)
    root = safe_root(output_dir, allow_test_root=True)
    records = {"inputs": source}
    for path in caller_results:
        record = load_json(path)
        _caller_semantics(record, source)
        caller = record["data"]["caller"]
        if caller in records:
            raise ValueError("duplicate caller result")
        records[caller] = record
    selected = [caller for caller in CALLERS if caller in records]
    if not selected or not set(selected) <= set(CALLERS):
        raise ValueError("empty or unknown caller selection")
    records = {name: records[name] for name in ["inputs", *selected]}
    for name, record in records.items():
        write_record(root / f"m4-{name}.json", record)
    data = {"repository_sha": source["data"]["repository_sha"], "sample": source["data"]["sample"],
            "selected_callers": selected, "inputs_payload_sha256": source["payload_sha256"],
            "artifacts": [{**_file(root / f"m4-{name}.json"), "artifact_id": name,
                           "payload_sha256": record["payload_sha256"]} for name, record in records.items()]}
    manifest = _envelope("bundle", source["run_id"], data)
    write_record(root / "m4-manifest.json", manifest)
    validate_m4_result_bundle(root)
    return manifest


def validate_m4_result_bundle(path: str | Path) -> dict[str, dict[str, Any]]:
    """Validate JSON-only bundle hashes, frozen source identity and caller semantics."""
    root = Path(path)
    manifest_path = root / "m4-manifest.json" if root.is_dir() else root
    manifest = load_json(manifest_path)
    validate_envelope(manifest)
    if manifest["artifact_type"] != "bundle":
        raise ValueError("expected M4 result bundle")
    selected = manifest["data"]["selected_callers"]
    artifacts = manifest["data"]["artifacts"]
    expected = {"inputs"} | set(selected)
    if (not selected or selected != [caller for caller in CALLERS if caller in selected]
            or len(artifacts) != len(expected) or [item["artifact_id"] for item in artifacts] != ["inputs", *selected]):
        raise ValueError("invalid M4 result inventory")
    result = {"bundle": manifest}
    for item in artifacts:
        name = item["artifact_id"]
        if name not in expected or name in result or item["filename"] != f"m4-{name}.json":
            raise ValueError("unsafe or duplicate M4 artifact identity")
        file = manifest_path.parent / item["filename"]
        if _file(file) != {key: item[key] for key in ("filename", "bytes", "sha256")}:
            raise ValueError("M4 bundle file hash mismatch")
        record = load_json(file)
        validate_envelope(record)
        if record["payload_sha256"] != item["payload_sha256"] or record["run_id"] != manifest["run_id"] or record["producer"] != manifest["producer"]:
            raise ValueError("M4 artifact payload/run/producer lineage mismatch")
        result[name] = record
    if set(result) != expected | {"bundle"}:
        raise ValueError("incomplete M4 bundle")
    source = result["inputs"]
    _input_semantics(source)
    if any(record["data"]["repository_sha"] != source["data"]["repository_sha"] or record["data"]["sample"] != source["data"]["sample"] for record in result.values()):
        raise ValueError("M4 repository/sample identity diverges across outputs")
    if manifest["data"]["inputs_payload_sha256"] != source["payload_sha256"]:
        raise ValueError("M4 bundle input payload identity mismatch")
    for caller in selected:
        _caller_semantics(result[caller], source)
    return result

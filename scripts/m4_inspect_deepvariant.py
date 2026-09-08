#!/usr/bin/env python3
"""Inspect actual pinned DeepVariant model bytes and nonempty inference records.

This helper is copied alone into the isolated caller task. It contains no fixture
allele oracle and accepts only reference lengths as its coordinate boundary.
TensorFlow and the protobufs come from the executing immutable image, never from
a host installation or downloaded package.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Iterator, Mapping, Sequence
import zipfile

MODEL_FILES = (
    "fingerprint.pb", "saved_model.pb", "model.example_info.json",
    "variables/variables.data-00000-of-00001", "variables/variables.index",
)
PROBABILITY_TOLERANCE = 1e-5
FORBIDDEN_FOLDER = "DO NOT ACCESS WITH CHATGPT"


def require(condition: bool, message: str) -> None:
    """Retain every acceptance check when Python optimization is enabled."""
    if not condition:
        raise ValueError(message)


def guarded_path(path: Path) -> Path:
    """Reject prohibited names, markers and symlinks before reading or writing."""
    raw = path.absolute()
    require(not any(FORBIDDEN_FOLDER in part for part in raw.parts), "prohibited inspection path")
    for candidate in (raw, *raw.parents):
        require(not candidate.is_symlink(), "linked inspection input is forbidden")
        require(not (candidate / FORBIDDEN_FOLDER).exists(), "workspace safety marker present")
    return raw


def regular_file(path: Path) -> Path:
    """Require an existing regular input after applying the path boundary."""
    raw = guarded_path(path)
    require(raw.is_file(), "inspection input is not a regular file")
    return raw


def file_identity(path: Path, filename: str) -> dict[str, str | int]:
    """Hash immutable inspected bytes using a logical filename without host paths."""
    source = regular_file(path)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    require(source.stat().st_size > 0, "empty inspection input")
    return {"filename": filename, "bytes": source.stat().st_size, "sha256": digest.hexdigest()}


def model_inventory(root: Path, metadata_sha256: str) -> dict[str, Any]:
    """Bind the five WES model files to the independently pinned metadata hash."""
    require(re.fullmatch(r"[0-9a-f]{64}", metadata_sha256) is not None, "invalid expected WES metadata hash")
    files = [file_identity(root / name, name) for name in MODEL_FILES]
    metadata = next(item for item in files if item["filename"] == "model.example_info.json")
    require(metadata["sha256"] == metadata_sha256, "WES model metadata differs from pinned identity")
    return {"schema_version": "1.0.0", "kind": "m4_deepvariant_model_inventory", "model_type": "WES", "model_files": files}


def reference_lengths(path: Path) -> dict[str, int]:
    """Read only an independently supplied FASTA index to bound record coordinates."""
    result: dict[str, int] = {}
    for line in regular_file(path).read_text().splitlines():
        fields = line.split("\t")
        require(len(fields) >= 5, "malformed reference index")
        name, length = fields[0], int(fields[1])
        require(bool(name) and name not in result and length > 0, "duplicate or invalid reference contig")
        result[name] = length
    require(bool(result), "empty reference dictionary")
    return result


def validate_variant(name: str, start: int, end: int, reference: str,
                     alternatives: Sequence[str], lengths: Mapping[str, int]) -> str:
    """Require a real candidate allele at valid coordinates without an allele oracle."""
    require(name in lengths and 0 <= start < end <= lengths[name], "candidate lies outside reference dictionary")
    require(len(reference) == end - start and bool(alternatives), "candidate allele span is invalid")
    require(all(bool(allele) and allele != reference for allele in alternatives), "candidate lacks an alternate allele")
    return name


def validate_probabilities(values: Iterable[float], tolerance: float = PROBABILITY_TOLERANCE) -> None:
    """Reject absent, nonfinite, out-of-range or unnormalized diploid probabilities."""
    probabilities = list(values)
    require(len(probabilities) == 3, "CVO must have three genotype probabilities")
    require(all(math.isfinite(value) and 0 <= value <= 1 for value in probabilities), "invalid genotype probability")
    require(abs(sum(probabilities) - 1.0) <= tolerance, "genotype probabilities do not sum to one")


def candidate_identity(name: str, start: int, end: int, reference: str,
                       alternatives: Sequence[str], indices: Sequence[int],
                       lengths: Mapping[str, int]) -> tuple[Any, ...]:
    """Identify the exact candidate and selected alternate alleles presented to inference."""
    validate_variant(name, start, end, reference, alternatives, lengths)
    require(bool(indices) and len(set(indices)) == len(indices) and
            all(0 <= index < len(alternatives) for index in indices), "candidate alternate allele indices are invalid")
    return (name, start, end, reference, tuple(alternatives), tuple(indices))


def require_candidate_lineage(candidate: tuple[Any, ...], examples: set[tuple[Any, ...]]) -> None:
    """Reject predictions for variants or alternate indices absent from generated examples."""
    require(candidate in examples, "inference output does not correspond to a generated candidate")


def image_protobufs(archive: Path = Path("/opt/deepvariant/bin/call_variants.zip")) -> tuple[Any, Any]:
    """Load generated protobuf modules from the executing image's Python binary ZIP."""
    source = regular_file(archive)
    suffix = "deepvariant/protos/deepvariant_pb2.py"
    with zipfile.ZipFile(source) as bundle:
        matches = [name for name in bundle.namelist() if name.endswith(suffix)]
    require(len(matches) == 1, "pinned image protobuf package cannot be identified uniquely")
    prefix = matches[0][:-len(suffix)]
    require(not prefix.startswith("/") and ".." not in Path(prefix).parts, "unsafe image package path")
    sys.path.insert(0, str(source) + "/" + prefix.rstrip("/"))
    return (importlib.import_module("deepvariant.protos.deepvariant_pb2"),
            importlib.import_module("third_party.nucleus.protos.variants_pb2"))


def tfrecords(paths: Sequence[Path], tensorflow: Any) -> Iterator[bytes]:
    """Read every record with TensorFlow's checksum-aware TFRecord implementation."""
    for path in paths:
        source = regular_file(path)
        compression = "GZIP" if source.name.endswith(".gz") else ""
        dataset = tensorflow.data.TFRecordDataset([str(source)], compression_type=compression, num_parallel_reads=1)
        for record in dataset.as_numpy_iterator():
            require(bool(record), "empty serialized TFRecord")
            yield bytes(record)


def unique_files(paths: Sequence[Path]) -> list[dict[str, str | int]]:
    """Reject duplicate inputs or ambiguous logical names before counting records."""
    require(bool(paths), "missing inference files")
    sources = [regular_file(path) for path in paths]
    require(len(set(sources)) == len(sources), "duplicate inference file")
    require(len({path.name for path in sources}) == len(sources), "ambiguous inference filename")
    return [file_identity(path, path.name) for path in sources]


def inspect_inference(examples: Sequence[Path], calls: Sequence[Path], fai: Path,
                      model_root: Path, metadata_sha256: str) -> dict[str, Any]:
    """Verify positive actual examples and model predictions, retaining immutable hashes."""
    model = model_inventory(model_root, metadata_sha256)
    example_files, call_files = unique_files(examples), unique_files(calls)
    lengths = reference_lengths(fai)
    tensorflow = importlib.import_module("tensorflow")
    tensorflow.config.threading.set_intra_op_parallelism_threads(1)
    tensorflow.config.threading.set_inter_op_parallelism_threads(1)
    deepvariant, variants = image_protobufs()
    count_examples = count_calls = 0
    contigs: set[str] = set()
    candidates: set[tuple[Any, ...]] = set()
    for serialized in tfrecords(examples, tensorflow):
        example = tensorflow.train.Example.FromString(serialized)
        features = example.features.feature
        for key in ("variant/encoded", "image/encoded", "alt_allele_indices/encoded"):
            require(key in features and len(features[key].bytes_list.value) == 1 and bool(features[key].bytes_list.value[0]),
                    "TFExample lacks a required candidate or image feature")
        variant = variants.Variant.FromString(features["variant/encoded"].bytes_list.value[0])
        indices = deepvariant.CallVariantsOutput.AltAlleleIndices.FromString(features["alt_allele_indices/encoded"].bytes_list.value[0]).indices
        candidates.add(candidate_identity(variant.reference_name, variant.start, variant.end,
                                          variant.reference_bases, variant.alternate_bases, indices, lengths))
        contigs.add(variant.reference_name)
        count_examples += 1
    for serialized in tfrecords(calls, tensorflow):
        record = deepvariant.CallVariantsOutput.FromString(serialized)
        variant = record.variant
        candidate = candidate_identity(variant.reference_name, variant.start, variant.end,
                                       variant.reference_bases, variant.alternate_bases, record.alt_allele_indices.indices, lengths)
        require_candidate_lineage(candidate, candidates)
        contigs.add(variant.reference_name)
        validate_probabilities(record.genotype_probabilities)
        count_calls += 1
    require(count_examples > 0 and count_calls > 0, "DeepVariant requires nonzero examples and inference outputs")
    require(example_files == unique_files(examples) and call_files == unique_files(calls), "inference input bytes changed during inspection")
    require(model["model_files"] == model_inventory(model_root, metadata_sha256)["model_files"], "model bytes changed during inspection")
    return {"schema_version": "1.0.0", "kind": "m4_deepvariant_inference", "model_type": "WES",
            "example_record_count": count_examples, "call_variants_record_count": count_calls,
            "all_probabilities_valid": True, "probability_tolerance": PROBABILITY_TOLERANCE,
            "variant_contigs": sorted(contigs), "example_files": example_files,
            "call_variants_files": call_files, "model_files": model["model_files"]}


def main(argv: Sequence[str] | None = None) -> int:
    """Write one model freeze or completed inference inspection, never a stub result."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, default=Path("/opt/models/wes"))
    parser.add_argument("--expected-model-metadata-sha256", required=True)
    parser.add_argument("--model-only", action="store_true")
    parser.add_argument("--examples", type=Path, action="append", default=[])
    parser.add_argument("--call-variants", type=Path, action="append", default=[])
    parser.add_argument("--reference-fai", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.model_only:
        require(not args.examples and not args.call_variants and args.reference_fai is None, "model freeze does not accept inference inputs")
        result = model_inventory(args.model_root, args.expected_model_metadata_sha256)
    else:
        require(args.reference_fai is not None, "inference inspection requires a reference index")
        result = inspect_inference(args.examples, args.call_variants, args.reference_fai,
                                   args.model_root, args.expected_model_metadata_sha256)
    output = guarded_path(args.output)
    require(not output.exists(), "inspection output already exists")
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

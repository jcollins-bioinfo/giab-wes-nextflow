"""Negative scientific and provenance boundaries for invented M4 evidence."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
from typing import Any, Callable
import unittest
from unittest.mock import patch

from jsonschema.exceptions import ValidationError

from giab_wes_nextflow.acquisition import checksum
from giab_wes_nextflow.m3 import canonical_hash
from giab_wes_nextflow import m4_contracts as contracts
from giab_wes_nextflow.m4_cli import main
from test_m4_support import make_unit_bundle


def rehash_bundle(bundle: Path, name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    """Model an adversary recomputing all JSON hashes after changing semantics."""
    path = bundle / f"m4-{name}.json"
    record = json.loads(path.read_text())
    mutate(record)
    record["payload_sha256"] = canonical_hash({key: value for key, value in record.items() if key != "payload_sha256"})
    path.write_text(json.dumps(record))
    manifest_path = bundle / "m4-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    item = next(item for item in manifest["data"]["artifacts"] if item["artifact_id"] == name)
    item.update(bytes=path.stat().st_size, sha256=checksum(path), payload_sha256=record["payload_sha256"])
    manifest["payload_sha256"] = canonical_hash({key: value for key, value in manifest.items() if key != "payload_sha256"})
    manifest_path.write_text(json.dumps(manifest))


class ContractTest(unittest.TestCase):
    """Exercise source identity, actual native alleles and restored evidence gates."""

    def setUp(self) -> None:
        """Prepare complete production-validated metadata from explicit unit inputs."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = make_unit_bundle(self.root / "source")

    def test_three_caller_modes_and_cli_validate(self) -> None:
        """Each mode has canonical order and an independently valid closed manifest."""
        for callers in (("gatk",), ("deepvariant",), ("gatk", "deepvariant")):
            with self.subTest(callers=callers):
                bundle = make_unit_bundle(self.root / "-".join(callers), callers=callers)
                records = contracts.validate_m4_result_bundle(bundle)
                self.assertEqual(records["bundle"]["data"]["selected_callers"], list(callers))
                self.assertEqual(main(["validate-bundle", "--bundle", str(bundle)]), 0)

    def test_input_copy_has_no_oracle_or_links_and_repeats(self) -> None:
        """Only the accepted physical inputs and aggregate contract enter callers."""
        root = self.root / "source"
        inputs = root / "caller-inputs"
        before = {path.name: path.read_bytes() for path in inputs.iterdir()}
        upstream = root / "preprocessing"
        contracts.prepare_inputs(upstream / "contracts", upstream / "analysis_ready.unit-identity",
            upstream / "analysis_ready.unit-index", upstream / "fixture", inputs)
        self.assertEqual(before, {path.name: path.read_bytes() for path in inputs.iterdir()})
        self.assertEqual(set(before), set(contracts.INPUT_FILES) | {"m4-inputs.json"})
        self.assertFalse(any(path.is_symlink() for path in inputs.iterdir()))
        self.assertNotIn("variant_sites", (inputs / "m4-inputs.json").read_text())
        (inputs / "oracle.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            contracts.validate_caller_inputs(inputs)

    def test_source_change_during_copy_cannot_create_acceptance_marker(self) -> None:
        """A source race fails against accepted bytes before any ready marker."""
        upstream = self.root / "source/preprocessing"
        output = self.root / "raced-inputs"
        original = contracts._write

        def changed_copy(path: Path, content: bytes) -> None:
            """Inject a changed copy while preserving every other write operation."""
            original(path, content + b"changed" if path.name == "shared.bam" else content)

        with patch.object(contracts, "_write", side_effect=changed_copy):
            with self.assertRaisesRegex(ValueError, "changed during"):
                contracts.prepare_inputs(upstream / "contracts", upstream / "analysis_ready.unit-identity",
                    upstream / "analysis_ready.unit-index", upstream / "fixture", output)
        self.assertFalse((output / "m4-inputs.json").exists())
        output = self.root / "unexpected-inputs"
        output.mkdir()
        (output / "oracle.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            contracts.prepare_inputs(upstream / "contracts", upstream / "analysis_ready.unit-identity",
                upstream / "analysis_ready.unit-index", upstream / "fixture", output)
        self.assertFalse((output / "m4-inputs.json").exists())

    def test_modified_shared_bam_and_link_are_rejected(self) -> None:
        """A stale input descriptor cannot accept altered or linked physical bytes."""
        inputs = self.root / "source/caller-inputs"
        bam = inputs / "shared.bam"
        original = bam.read_bytes()
        bam.write_bytes(original + b"altered")
        with self.assertRaises(ValueError):
            contracts.validate_caller_inputs(inputs)
        bam.unlink()
        source = self.root / "original.unit"
        source.write_bytes(original)
        bam.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "regular"):
            contracts.validate_caller_inputs(inputs)

    def test_native_reference_genotype_and_control_invariants(self) -> None:
        """Correct REF, diploid alleles and reference-control behavior are mandatory."""
        source = self.root / "source/gatk/SYNTHETIC01.gatk.native.vcf.gz"
        text = gzip.decompress(source.read_bytes()).decode()
        variants = {
            "wrong_ref": text.replace("3151\t.\tT", "3151\t.\tC"),
            "wrong_gt": text.replace("GT\t0/1", "GT\t1/1"),
            "missing": "\n".join(line for line in text.splitlines() if "3151" not in line) + "\n",
            "bad_index": text.replace("GT\t0/1", "GT\t0/2"),
            "wrong_contig": text.replace("chrSYN1,length=12000", "chrSYN1,length=12001"),
            "control": text.replace("chrSYN2\t7101", "chrSYN1\t5401\t.\tG\tA\t99\tPASS\t.\tGT\t0/1\nchrSYN2\t7101"),
        }
        for name, changed in variants.items():
            with self.subTest(name=name):
                path = self.root / f"{name}.vcf"
                path.write_text(changed)
                with self.assertRaises(ValueError):
                    contracts.validate_native_calls(path, caller="gatk")

    def test_rehashed_tool_parameter_oracle_and_lineage_forgery(self) -> None:
        """Self-consistent JSON hashes do not bypass frozen scientific identities."""
        mutations = [
            lambda record: record["data"]["tool_contract"].update(image="invented@sha256:" + "0" * 64),
            lambda record: record["data"]["observed_parameters"].update(model_type="WGS"),
            lambda record: record["data"]["observed_parameters"].update(num_shards=True),
            lambda record: record["data"]["tool_contract"]["parameters"].update(num_shards=True),
            lambda record: record["data"].update(repository_sha="f" * 40),
            lambda record: record["data"].update(inputs_payload_sha256="f" * 64),
            lambda record: record["data"]["native_acceptance"]["expected_positive_sites"][0].update(genotype="1/1"),
            lambda record: record["data"]["inference"].update(example_record_count=0),
            lambda record: record["data"]["inference"].update(call_variants_record_count=0),
            lambda record: record["data"]["inference"].update(all_probabilities_valid=False),
            lambda record: record["data"]["model_before"]["model_files"][0].update(sha256="f" * 64),
            lambda record: record["data"]["resources"].update(architecture="arm64"),
        ]
        originals = {path.name: path.read_bytes() for path in self.bundle.iterdir()}
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                for name, content in originals.items():
                    (self.bundle / name).write_bytes(content)
                rehash_bundle(self.bundle, "deepvariant", mutate)
                with self.assertRaises((ValueError, ValidationError)):
                    contracts.validate_m4_result_bundle(self.bundle)

    def test_duplicate_json_keys_are_rejected_at_nested_boundaries(self) -> None:
        """Equivalent last-key parsing cannot hide ambiguous source evidence."""
        path = self.root / "ambiguous.json"
        for text in ('{"x":1,"x":1}', '{"a":{"x":1,"x":1}}'):
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                contracts.load_json(path)
        marked = self.root / "marked"
        marked.mkdir()
        (marked / "DO NOT ACCESS WITH CHATGPT").touch()
        link = marked / "metadata.json"
        path.write_text("{}")
        link.symlink_to(path)
        with self.assertRaises(PermissionError):
            contracts.load_json(link)

    def test_actual_command_binds_inputs_and_rejects_hidden_parameters(self) -> None:
        """Alternative inputs, qualities or extra model settings cannot be omitted from provenance."""
        for caller in contracts.CALLERS:
            text = (self.root / f"source/{caller}/command.sh").read_text()
            contracts._parameters(caller, text)
            for changed in (text.replace("caller-inputs/shared.bam", "other.bam"),
                            text.rstrip() + " --unapproved-scientific-option=true\n",
                            text.rstrip() + " -I other.bam\n", text + text):
                with self.subTest(caller=caller, changed=changed):
                    with self.assertRaises(ValueError):
                        contracts._parameters(caller, changed)

    def test_persisted_caller_order_and_producer_identity_are_exact(self) -> None:
        """Manifest order is canonical and no caller can claim a different producer."""
        rehash_bundle(self.bundle, "gatk", lambda record: record["producer"].update(version="9.0.0"))
        with self.assertRaisesRegex(ValueError, "producer"):
            contracts.validate_m4_result_bundle(self.bundle)
        manifest_path = self.bundle / "m4-manifest.json"
        record = json.loads(manifest_path.read_text())
        record["data"]["selected_callers"].reverse()
        record["payload_sha256"] = canonical_hash({key: value for key, value in record.items() if key != "payload_sha256"})
        manifest_path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "inventory"):
            contracts.validate_m4_result_bundle(self.bundle)

    def test_unknown_reference_and_unsafe_output_fail_before_marker(self) -> None:
        """Forbidden output ancestors and changed source references are fail-closed."""
        upstream = self.root / "source/preprocessing"
        target = self.root / "DO NOT ACCESS WITH CHATGPT" / "inputs"
        with self.assertRaises(PermissionError):
            contracts.prepare_inputs(upstream / "contracts", upstream / "analysis_ready.unit-identity",
                upstream / "analysis_ready.unit-index", upstream / "fixture", target)
        self.assertFalse(target.parent.exists())
        reference = upstream / "fixture/reference.fa"
        reference.write_bytes(reference.read_bytes() + b"A\n")
        target = self.root / "changed-reference"
        with self.assertRaises(ValueError):
            contracts.prepare_inputs(upstream / "contracts", upstream / "analysis_ready.unit-identity",
                upstream / "analysis_ready.unit-index", upstream / "fixture", target)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()

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

    def test_native_failures_report_both_frozen_sites_without_acceptance(self) -> None:
        """Wrong GT, filtering and absent loci remain failures with distinct evidence."""
        source = self.root / "source/gatk/SYNTHETIC01.gatk.native.vcf.gz"
        text = gzip.decompress(source.read_bytes()).decode()
        cases = {"wrong_gt": text.replace("GT\t0/1", "GT\t1/1"),
                 "low_qual": text.replace("\tPASS\t", "\tLowQual\t", 1),
                 "missing": "\n".join(line for line in text.splitlines() if "3151" not in line) + "\n"}
        for caller in contracts.CALLERS:
            for kind, changed in cases.items():
                with self.subTest(caller=caller, kind=kind):
                    path = self.root / "native-failure.vcf"
                    path.write_text(changed)
                    with self.assertRaisesRegex(ValueError, "native caller failed a frozen positive SNV genotype") as caught:
                        contracts.validate_native_calls(path, caller=caller)
                    evidence = json.loads(str(caught.exception).split("synthetic_native_diagnostic=", 1)[1])
                    self.assertFalse(evidence["acceptance"])
                    self.assertEqual(evidence["file_sha256"], checksum(path))
                    self.assertEqual([site["position_1based"] for site in evidence["sites"]], [3151, 7101])
                    rows = evidence["sites"][0]["rows"]
                    if kind == "wrong_gt":
                        self.assertEqual(rows[0]["genotype"], "1/1")
                    elif kind == "low_qual":
                        self.assertEqual(rows[0]["filter"], "LowQual")
                    else:
                        self.assertEqual(rows, [])
                    self.assertNotIn(str(self.root), str(caught.exception))

    def test_native_diagnostics_bound_and_redact_untrusted_fields(self) -> None:
        """Only safe alleles/GT/filters and capped rows enter synthetic diagnostics."""
        source = self.root / "source/gatk/SYNTHETIC01.gatk.native.vcf.gz"
        header = "\n".join(line for line in gzip.decompress(source.read_bytes()).decode().splitlines()
                           if line.startswith("#")) + "\n"
        secret = "sensitive-source-field-" * 100
        rows = [f"chrSYN1\t3151\t.\t{'T' * 1000}\t{secret}{index},A,<NON_REF>,*,N\t1\t{secret}\t.\tGT:GQ:DP:AD:PL\t0/1:{secret}:80:40,40:0,1,2,3,4,5,6,7,8\n"
                for index in range(12)]
        path = self.root / "private-source-name.vcf"
        path.write_text(header + "".join(rows))
        evidence = contracts._native_site_diagnostic(path)
        site = evidence["sites"][0]
        self.assertEqual(site["overlapping_record_count"], 12)
        self.assertEqual(len(site["rows"]), 4)
        self.assertTrue(site["rows_truncated"])
        self.assertEqual(site["rows"][0]["alt_count"], 5)
        self.assertTrue(site["rows"][0]["alts_truncated"])
        self.assertEqual(site["rows"][0]["ref"]["length"], 1000)
        self.assertEqual(site["rows"][0]["format"]["DP"], 80)
        self.assertEqual(site["rows"][0]["format"]["AD"], [40, 40])
        self.assertEqual(site["rows"][0]["format"]["GQ"]["length"], len(secret))
        self.assertIn("sha256", site["rows"][0]["format"]["PL"])
        serialized = json.dumps(evidence)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(path.name, serialized)
        self.assertNotIn("T" * 1000, serialized)
        self.assertLess(len(serialized), 6000)
        path.write_text((header + "".join(rows)).replace("SYNTHETIC01", "UNREGISTERED"))
        with self.assertRaisesRegex(ValueError, "registered synthetic"):
            contracts._native_site_diagnostic(path)

    def test_failed_collector_adds_gvcf_context_only_after_synthetic_input_gate(self) -> None:
        """Rejected native sites include bounded reference blocks without a marker."""
        directory = self.root / "source/deepvariant"
        vcf = directory / "SYNTHETIC01.deepvariant.native.vcf.gz"
        gvcf = directory / "SYNTHETIC01.deepvariant.native.g.vcf.gz"
        text = gzip.decompress(vcf.read_bytes()).decode()
        vcf.write_bytes(gzip.compress("\n".join(line for line in text.splitlines() if "3151" not in line).encode() + b"\n"))
        gvcf.write_bytes(gzip.compress(text.replace("3151\t.\tT\tA\t99\tPASS\t.\tGT\t0/1",
            "3151\t.\tT\t<NON_REF>\t0\t.\tEND=3250\tGT:GQ:DP:AD:PL\t0/0:12:80:40,40:0,12,100").encode()))
        output = self.root / "failed-caller.json"
        args = ("deepvariant", self.root / "source/caller-inputs", vcf, Path(str(vcf) + ".tbi"),
                directory / "version.txt", directory / "command.sh", directory / "resources.json", output)
        with self.assertRaisesRegex(ValueError, "native caller failed") as caught:
            contracts.collect_caller(*args, gvcf=gvcf)
        evidence = json.loads(str(caught.exception).split("synthetic_gvcf_diagnostic=", 1)[1])
        row = evidence["sites"][0]["rows"][0]
        self.assertEqual((row["genotype"], row["end_1based"], row["alt"]), ("0/0", 3250, ["<NON_REF>"]))
        self.assertEqual(row["format"], {"GQ": 12, "DP": 80, "AD": [40, 40], "PL": [0, 12, 100]})
        self.assertEqual(evidence["sites"][1]["rows"][0]["format"], {"GQ": None, "DP": None, "AD": None, "PL": None})
        self.assertFalse(output.exists())
        gvcf.write_bytes(gzip.compress(text.replace("SYNTHETIC01", "UNREGISTERED").encode()))
        with self.assertRaises(ValueError) as caught:
            contracts.collect_caller(*args, gvcf=gvcf)
        self.assertIn("unavailable_or_invalid_synthetic_gvcf", str(caught.exception))
        self.assertNotIn("UNREGISTERED", str(caught.exception))
        inputs = self.root / "source/caller-inputs"
        (inputs / "shared.bam").write_bytes(b"unaccepted source")
        with patch.object(contracts, "_native_site_diagnostic") as diagnostic:
            with self.assertRaises(ValueError):
                contracts.collect_caller(*args, gvcf=gvcf)
            diagnostic.assert_not_called()
            with self.assertRaisesRegex(ValueError, "unregistered"):
                contracts.validate_native_calls(vcf, caller="deepvariant", fixture_id="unregistered")
            diagnostic.assert_not_called()
        self.assertFalse(output.exists())

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

    def test_multiline_quoted_wrapper_preserves_both_caller_parameters(self) -> None:
        """Parse actual-style printf literal newlines before continued caller commands."""
        prefix = "#!/bin/bash -euo pipefail\n# An unmatched ' in a comment is inert.\n"
        prefix += "printf '{\"task_id\":null,\"architecture\":\"%s\"}\n' \"$(uname -m)\" > resources.json\n"
        for caller in contracts.CALLERS:
            text = (self.root / f"source/{caller}/command.sh").read_text()
            continued = text.replace(" --", " \\\n    --")
            with self.subTest(caller=caller):
                self.assertEqual(contracts._parameters(caller, prefix + continued),
                                 contracts._parameters(caller, text))

    def test_quoted_caller_text_is_not_a_scientific_invocation(self) -> None:
        """Do not mistake a command printed inside a quoted argument for execution."""
        for caller in contracts.CALLERS:
            text = (self.root / f"source/{caller}/command.sh").read_text().strip()
            quoted = "printf '%s\\n' '\n" + text + "\n'\n"
            with self.subTest(caller=caller), self.assertRaisesRegex(ValueError, "exactly one"):
                contracts._parameters(caller, quoted)

    def test_multiline_wrapper_keeps_malformed_duplicate_and_option_gates(self) -> None:
        """Literal-newline support must not ignore broken syntax or hidden parameters."""
        prefix = "printf 'unit metadata\n' > resources.json\n"
        for caller in contracts.CALLERS:
            text = (self.root / f"source/{caller}/command.sh").read_text()
            cases = (prefix + text + "printf 'unclosed\n", prefix + text + text,
                     prefix + text.rstrip() + " --unapproved-scientific-option=true\n")
            for changed in cases:
                with self.subTest(caller=caller, command=changed), self.assertRaises(ValueError):
                    contracts._parameters(caller, changed)

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

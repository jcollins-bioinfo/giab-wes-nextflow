"""Scientific contract and negative tests for deterministic invented M3 inputs."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
from typing import Any, Callable
import unittest

from giab_wes_nextflow.m3 import (canonical_hash, checked_file, identity, load_json, preflight, read_pairs,
                                 reference_lengths, require_fixture, validate_envelope, validate_fastq, write_envelope)
from giab_wes_nextflow.m3_cli import main
from giab_wes_nextflow.m3_collect import _resource_records, _sam, parse_coverage, validate_result_bundle
from giab_wes_nextflow.m3_fixture import fixture_payloads, generate_fixture
from test_m3_support import make_unit_bundle


class FixtureContractTest(unittest.TestCase):
    """Reject arbitrary bytes before synthetic workflow admission."""

    def setUp(self) -> None:
        """Generate a fresh deterministic fixture without any external download."""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fixture = self.root / "fixture"
        self.expected = generate_fixture(self.fixture)
        self.addCleanup(self.temporary.cleanup)

    def test_fixture_bytes_repeat_across_paths(self) -> None:
        """All compressed bytes, sample metadata and identities are path independent."""
        other = self.root / "other"
        generate_fixture(other)
        self.assertEqual({p.name: p.read_bytes() for p in self.fixture.iterdir()}, {p.name: p.read_bytes() for p in other.iterdir()})
        self.assertEqual(sum(self.expected["contigs"].values()), 20000)
        self.assertEqual(self.expected["pair_count"], 24)
        self.assertEqual(len(self.expected["read_expectations"]), 48)

    def test_fixture_conflict_is_preserved(self) -> None:
        """The generator does not overwrite unexplained pre-existing artifacts."""
        path = self.fixture / "reference.fa"
        path.write_text("retain this conflict")
        with self.assertRaises(FileExistsError):
            generate_fixture(self.fixture)
        self.assertEqual(path.read_text(), "retain this conflict")

    def test_preflight_requires_no_indexes_and_binds_all_inputs(self) -> None:
        """Source hashes gate execution before any indexing process is invoked."""
        result = preflight(self.fixture / "samplesheet.csv", self.fixture / "reference.fa", self.fixture / "known-sites.vcf",
                           self.fixture / "fixture-expectations.json", "a" * 40, "m3-test")
        self.assertTrue(result["data"]["source_bytes_verified"])
        self.assertEqual(len(result["input_artifacts"]), 8)
        self.assertIsNone(result["data"]["reference"]["fai"])
        self.assertFalse(result["canonical"])

    def test_forged_synthetic_manifest_fails(self) -> None:
        """A self-consistent synthetic label cannot admit unrelated sequences."""
        path = self.fixture / "fixture-expectations.json"
        record = json.loads(path.read_text())
        record["files"]["reference.fa"]["sha256"] = "0" * 64
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "deterministic fixture recipe"):
            require_fixture(path)

    def test_changed_reference_rejected_before_tools(self) -> None:
        """Actual source bytes, not merely the manifest label, control admission."""
        (self.fixture / "reference.fa").write_text(">chrSYN1\nACGT\n")
        with self.assertRaisesRegex(ValueError, "source identity"):
            preflight(self.fixture / "samplesheet.csv", self.fixture / "reference.fa", self.fixture / "known-sites.vcf",
                      self.fixture / "fixture-expectations.json", "a" * 40, "m3-test")

    def test_generator_rejects_symlink_output_ancestor(self) -> None:
        """Synthetic fixture materialization cannot follow an unexpected write link."""
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        link = self.root / "linked-output"
        link.symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            generate_fixture(link / "fixture")
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_marker_blocks_input_and_output_without_opening_data(self) -> None:
        """Existing ancestor markers guard reads as well as generated writes."""
        record = preflight(self.fixture / "samplesheet.csv", self.fixture / "reference.fa", self.fixture / "known-sites.vcf",
                           self.fixture / "fixture-expectations.json", "a" * 40, "m3-test")
        (self.root / "DO NOT ACCESS WITH CHATGPT").touch()
        for action in (lambda: checked_file(self.fixture / "reference.fa"),
                       lambda: write_envelope(self.root / "results/report.json", record),
                       lambda: generate_fixture(self.root / "new-fixture")):
            with self.assertRaises(PermissionError):
                action()
        self.assertFalse((self.root / "results").exists())
        self.assertFalse((self.root / "new-fixture").exists())

    def test_normal_nextflow_staging_symlinks_are_readable(self) -> None:
        """Normal explicit task staging links retain compatibility with guarded reads."""
        link = self.root / "reference-link.fa"
        link.symlink_to(self.fixture / "reference.fa")
        self.assertEqual(checked_file(link), (self.fixture / "reference.fa").resolve())

    def test_read_group_mismatch_fails(self) -> None:
        """Read-group metadata must correspond to the exact lane source pair."""
        row = self.expected["lanes"][0]
        with self.assertRaisesRegex(ValueError, "read-group metadata"):
            validate_fastq(self.fixture / row["fastq_1"], self.fixture / row["fastq_2"], row["sample"], "WRONG_LIB", row["lane"],
                           row["read_group_id"], row["platform_unit"], row["platform"], self.fixture / "reference.fa",
                           self.fixture / "fixture-expectations.json")

    def test_reference_parser_rejects_duplicate_and_invalid_contigs(self) -> None:
        """Malformed reference inputs fail independently of a fixture hash check."""
        path = self.root / "bad.fa"
        for content in (">x\nACGT\n>x\nACGT\n", ">x\nACZ\n", "ACGT\n", ">x\n"):
            path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                reference_lengths(path)

    def test_paired_fastq_negative_structure_cases(self) -> None:
        """Truncation, mismatches, invalid qualities and duplicate IDs are rejected."""
        first, second = self.root / "bad1.fq.gz", self.root / "bad2.fq.gz"
        valid1, valid2 = "@read/1\nACGT\n+\nABCD\n", "@read/2\nACGT\n+\nABCD\n"
        cases = [
            ("@read/1\nACGT\n+\n", valid2),
            (valid1, valid2.replace("read/2", "other/2")),
            (valid1.replace("ABCD", "ABC"), valid2),
            (valid1.replace("ABCD", "AB C"), valid2),
            (valid1.replace("/1", "/2"), valid2),
            (valid1 + valid1, valid2 + valid2),
            (valid1, ""),
        ]
        for left, right in cases:
            first.write_bytes(gzip.compress(left.encode(), mtime=0))
            second.write_bytes(gzip.compress(right.encode(), mtime=0))
            with self.subTest(left=left, right=right), self.assertRaises(ValueError):
                list(read_pairs(first, second))

    def test_gzip_crc_truncation_is_detected(self) -> None:
        """Compressed transport corruption is not accepted as valid FASTQ."""
        first = self.root / "truncated.gz"
        first.write_bytes((self.fixture / "reads_1.fastq.gz").read_bytes()[:-6])
        with self.assertRaises((EOFError, OSError)):
            list(read_pairs(first, self.fixture / "reads_2.fastq.gz"))


class BundleContractTest(unittest.TestCase):
    """Check cross-artifact identity and actual SAM quality/coordinate invariants."""

    def setUp(self) -> None:
        """Build a fully validated six-file nonhuman unit contract bundle."""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = make_unit_bundle(self.root)
        self.expected = fixture_payloads()[1]
        self.addCleanup(self.temporary.cleanup)

    def rewrite_result(self, kind: str, mutate: Callable[[dict[str, Any]], None]) -> None:
        """Rehash forged envelopes to test semantic checks beyond ordinary integrity."""
        path = self.bundle / f"m3-{kind}.json"
        record = load_json(path)
        mutate(record)
        record["payload_sha256"] = canonical_hash({key: value for key, value in record.items() if key != "payload_sha256"})
        path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
        manifest_path = self.bundle / "m3-manifest.json"
        manifest = load_json(manifest_path)
        item = next(item for item in manifest["data"]["artifacts"] if item["artifact_type"] == kind)
        item.update(sha256=identity(path, kind, "immutable_m3_result")["sha256"], bytes=path.stat().st_size, payload_sha256=record["payload_sha256"])
        manifest["payload_sha256"] = canonical_hash({key: value for key, value in manifest.items() if key != "payload_sha256"})
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")

    def test_complete_bundle_and_cli_validate(self) -> None:
        """Every value has a schema, payload identity and manifest-bound file hash."""
        result = validate_result_bundle(self.bundle)
        self.assertEqual(set(result), {"bundle", "alignment", "qc", "coverage", "resources", "provenance"})
        self.assertEqual(result["alignment"]["data"]["duplicate_reads"], 4)
        self.assertEqual(result["alignment"]["data"]["primary_reads"], 48)
        self.assertTrue(result["alignment"]["data"]["oq_complete"])
        self.assertEqual(main(["validate-bundle", "--bundle", str(self.bundle)]), 0)

    def test_resources_do_not_invent_cost(self) -> None:
        """Requested resources are explicit; unobserved cost measurements stay null."""
        result = validate_result_bundle(self.bundle)["resources"]
        self.assertFalse(result["data"]["comparison_cost_available"])
        for item in result["data"]["tasks"]:
            self.assertIsNone(item["cpu_seconds"])
            self.assertIsNone(item["peak_rss_bytes"])
        self.assertIn("observed_task_resources", result["missingness"])

    def test_missing_task_id_is_explicit_not_fabricated(self) -> None:
        """Unavailable task IDs require an honest logical-artifact relationship."""
        path = self.root / "declaration.json"
        path.write_text(json.dumps({"task_id": None, "logical_artifact_id": "sample.bam", "process": "M3_ALIGN",
                        "requested_cpus": 2, "requested_memory_bytes": 1000, "requested_time_seconds": 60,
                        "container": None, "architecture": "unit-fixture"}))
        rows, missing = _resource_records([str(path)])
        self.assertIsNone(rows[0]["task_id"])
        self.assertIn("task_identity", missing)

    def test_changed_output_bytes_fail(self) -> None:
        """Artifact byte identity is verified on every bundle load."""
        path = self.bundle / "m3-qc.json"
        path.write_text(path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "byte hash"):
            validate_result_bundle(self.bundle)

    def test_rehashed_wrong_repository_still_fails(self) -> None:
        """A locally rehashed record cannot contradict the bundle's repository SHA."""
        self.rewrite_result("provenance", lambda record: record["data"].update(repository_sha="b" * 40))
        with self.assertRaisesRegex(ValueError, "repository identity"):
            validate_result_bundle(self.bundle)

    def test_rehashed_wrong_producer_version_fails(self) -> None:
        """Every result must share one observed producer identity."""
        self.rewrite_result("qc", lambda record: record["producer"].update(version="99.0.0"))
        with self.assertRaisesRegex(ValueError, "producer identity"):
            validate_result_bundle(self.bundle)

    def test_rehashed_wrong_common_bam_identity_fails(self) -> None:
        """The shared BAM identity is one cross-linked input, never copied by hand."""
        self.rewrite_result("qc", lambda record: next(item for item in record["input_artifacts"] if item["artifact_id"] == "shared_analysis_ready_bam").update(sha256="f" * 64))
        with self.assertRaisesRegex(ValueError, "input lineage"):
            validate_result_bundle(self.bundle)

    def test_oq_original_quality_invariant(self) -> None:
        """A missing or changed OQ tag blocks even synthetic final-BAM acceptance."""
        path = self.root / "final.sam"
        original = path.read_text()
        path.write_text(original.replace("OQ:Z:", "XX:Z:", 1))
        with self.assertRaisesRegex(ValueError, "OQ"):
            _sam(path, self.expected, True)

    def test_wrong_known_coordinate_fails(self) -> None:
        """Expected fixture alignments are checked against actual positions."""
        path = self.root / "final.sam"
        lines = path.read_text().splitlines()
        index = next(number for number, line in enumerate(lines) if not line.startswith("@"))
        fields = lines[index].split("\t")
        fields[3] = str(int(fields[3]) + 1)
        lines[index] = "\t".join(fields)
        path.write_text("\n".join(lines) + "\n")
        with self.assertRaisesRegex(ValueError, "coordinate"):
            _sam(path, self.expected, True)

    def test_all_three_copies_marked_duplicate_fails(self) -> None:
        """The known duplicate group must preserve one original fragment pair."""
        path = self.root / "final.sam"
        lines = []
        for line in path.read_text().splitlines():
            if line.startswith("SYN_L001_0001\t"):
                fields = line.split("\t")
                fields[1] = str(int(fields[1]) | 1024)
                line = "\t".join(fields)
            lines.append(line)
        path.write_text("\n".join(lines) + "\n")
        with self.assertRaisesRegex(ValueError, "two duplicate pairs"):
            _sam(path, self.expected, True)

    def test_split_duplicate_flags_fail_despite_correct_total(self) -> None:
        """Four flagged reads must form two complete duplicate pairs."""
        path = self.root / "final.sam"
        lines = path.read_text().splitlines()
        toggled: set[bool] = set()
        for index, line in enumerate(lines):
            if line.startswith("@"):
                continue
            fields = line.split("\t")
            flag = int(fields[1])
            key = fields[0] + ("/1" if flag & 64 else "/2")
            duplicate = bool(flag & 1024)
            if flag & 64 and self.expected["read_expectations"][key]["duplicate_group"] and duplicate not in toggled:
                fields[1] = str(flag ^ 1024)
                lines[index] = "\t".join(fields)
                toggled.add(duplicate)
        self.assertEqual(toggled, {False, True})
        path.write_text("\n".join(lines) + "\n")
        with self.assertRaisesRegex(ValueError, "fragment pair"):
            _sam(path, self.expected, True)

    def test_whole_reference_coverage_is_not_benchmark_domain(self) -> None:
        """Coverage retains the independent 20kb denominator and Gate B missingness."""
        data = validate_result_bundle(self.bundle)["coverage"]["data"]
        self.assertEqual(data["reference_bases"], 20000)
        self.assertEqual(data["mean_depth"], 0.3)
        self.assertIsNone(data["primary_evaluation_bases"])
        self.assertFalse(data["benchmark_domain"])
        path = self.root / "wrong-mosdepth.txt"
        path.write_text("chrom\tlength\tbases\tmean\tmin\tmax\ntotal\t20000\t6000\t1.5\t0\t2\n")
        with self.assertRaisesRegex(ValueError, "mean disagrees"):
            parse_coverage(path, 20000)


if __name__ == "__main__":
    unittest.main()

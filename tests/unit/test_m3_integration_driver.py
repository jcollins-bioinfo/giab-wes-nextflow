"""Independent synthetic oracles for the M3 clean-clone integration driver."""
from __future__ import annotations

import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any
from contextlib import redirect_stdout
from unittest.mock import patch

from giab_wes_nextflow.m3_fixture import fixture_payloads, reverse_complement

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("m3_integration_driver", ROOT / "scripts/run_m3_synthetic.py")
DRIVER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DRIVER
SPEC.loader.exec_module(DRIVER)


def expected_sam() -> tuple[str, dict[str, Any]]:
    """Build an oracle SAM from the invented recipe, with four known duplicates."""
    payloads, fixture = fixture_payloads()
    sequences = {}
    for name, content in payloads.items():
        if name.endswith(".fastq.gz"):
            lines = gzip.decompress(content).decode().splitlines()
            for index in range(0, len(lines), 4):
                sequences[lines[index][1:]] = lines[index + 1]
    headers = ["@HD\tVN:1.6\tSO:coordinate"]
    headers += [f"@SQ\tSN:{name}\tLN:{length}" for name, length in fixture["contigs"].items()]
    headers += [f"@RG\tID:{lane['read_group_id']}\tSM:{fixture['sample']}\tLB:{fixture['library']}\tPL:ILLUMINA" for lane in fixture["lanes"]]
    records = []
    order = {name: index for index, name in enumerate(fixture["contigs"])}
    for key, expected in fixture["read_expectations"].items():
        flag = 1 | (64 if expected["mate"] == 1 else 128)
        if expected["contig"] is None:
            flag |= 4 | 8
        else:
            flag |= 2
            if expected["reverse"]:
                flag |= 16
        if expected["duplicate_group"] and expected["qname"] != "SYN_L001_0001":
            flag |= 1024
        sequence = reverse_complement(sequences[key]) if flag & 16 else sequences[key]
        original = expected["original_qualities"][::-1] if flag & 16 else expected["original_qualities"]
        row = [expected["qname"], str(flag), expected["contig"] or "*", str(expected["position_1based"] or 0),
               "60" if expected["contig"] else "0", "150M" if expected["contig"] else "*", "*", "0", "0",
               sequence, "5" * fixture["read_length"], "RG:Z:" + expected["read_group"], "OQ:Z:" + original]
        records.append(((order.get(expected["contig"], 99), expected["position_1based"] or 0), "\t".join(row)))
    return "\n".join(headers + [row for _, row in sorted(records, key=lambda item: item[0])]) + "\n", fixture


class BamOracleTest(unittest.TestCase):
    def test_complete_expected_bam_shape_passes(self) -> None:
        """Accept the complete 48-read recipe with retained duplicates and original qualities."""
        sam, fixture = expected_sam()
        observed = DRIVER.validate_sam(sam, fixture)
        self.assertEqual(observed["primary_reads"], 48)
        self.assertEqual(observed["mapped_reads"], 44)
        self.assertEqual(observed["duplicate_reads"], 4)
        self.assertTrue(observed["oq_on_all_primary_reads"])

    def test_missing_oq_wrong_reference_and_missing_read_fail(self) -> None:
        """Reject each independent break in quality, reference, or read-inventory provenance."""
        sam, fixture = expected_sam()
        cases = [sam.replace("\tOQ:Z:", "\tXX:Z:", 1), sam.replace("SN:chrSYN1\tLN:12000", "SN:chrSYN1\tLN:11999"),
                 "\n".join(sam.splitlines()[:-1]) + "\n"]
        for invalid in cases:
            with self.subTest(prefix=invalid[:30]), self.assertRaises(ValueError):
                DRIVER.validate_sam(invalid, fixture)

    def test_changed_read_sequence_position_or_group_fails(self) -> None:
        """A valid record count cannot conceal altered sequence, placement, or read group."""
        sam, fixture = expected_sam()
        lines = sam.splitlines()
        first = next(index for index, line in enumerate(lines) if not line.startswith("@"))
        original = lines[first].split("\t")
        for column, value in [(3, "5010"), (9, "A" * 150), (11, "RG:Z:UNKNOWN")]:
            modified = original.copy()
            modified[column] = value
            altered = lines.copy()
            altered[first] = "\t".join(modified)
            with self.assertRaises(ValueError):
                DRIVER.validate_sam("\n".join(altered) + "\n", fixture)

    def test_reverse_read_oq_must_match_sam_orientation(self) -> None:
        """Reverse-strand OQ must be reversed from FASTQ order exactly once."""
        sam, fixture = expected_sam()
        lines = sam.splitlines()
        index = next(i for i, line in enumerate(lines) if not line.startswith("@") and int(line.split("\t")[1]) & 16)
        fields = lines[index].split("\t")
        fields[-1] = "OQ:Z:" + fields[-1][5:][::-1]
        lines[index] = "\t".join(fields)
        with self.assertRaisesRegex(ValueError, "original quality"):
            DRIVER.validate_sam("\n".join(lines), fixture)

    def test_no_duplicate_marking_and_unsorted_records_fail(self) -> None:
        """Require retained duplicate flags and observed coordinate ordering together."""
        sam, fixture = expected_sam()
        lines = sam.splitlines()
        without_duplicates = []
        for line in lines:
            if line.startswith("@"):
                without_duplicates.append(line)
            else:
                fields = line.split("\t")
                fields[1] = str(int(fields[1]) & ~1024)
                without_duplicates.append("\t".join(fields))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            DRIVER.validate_sam("\n".join(without_duplicates), fixture)
        first = next(i for i, line in enumerate(lines) if not line.startswith("@"))
        lines[first], lines[-1] = lines[-1], lines[first]
        with self.assertRaises(ValueError):
            DRIVER.validate_sam("\n".join(lines), fixture)

    def test_preserving_duplicate_count_cannot_split_duplicate_pairs(self) -> None:
        """Keeping the duplicate total fixed cannot hide inconsistent flags within a pair."""
        sam, fixture = expected_sam()
        lines = sam.splitlines()
        original = next(i for i, line in enumerate(lines) if line.startswith("SYN_L001_0001\t") and int(line.split("\t")[1]) & 64)
        duplicate = next(i for i, line in enumerate(lines) if not line.startswith("@") and int(line.split("\t")[1]) & 1024 and int(line.split("\t")[1]) & 64)
        for index in (original, duplicate):
            fields = lines[index].split("\t")
            fields[1] = str(int(fields[1]) ^ 1024)
            lines[index] = "\t".join(fields)
        with self.assertRaisesRegex(ValueError, "split a read pair"):
            DRIVER.validate_sam("\n".join(lines), fixture)


class ResumeOracleTest(unittest.TestCase):
    def setUp(self) -> None:
        """Prepare completed tasks and matching cached records with stable identity fields."""
        self.first = [{"task_id": "1", "hash": "aa/111", "name": "W:M3_ALIGN (lane1)", "status": "COMPLETED", "exit": "0", "container": "image@sha256:" + "a" * 64},
                      {"task_id": "2", "hash": "bb/222", "name": "W:M3_SORT (lane1)", "status": "COMPLETED", "exit": "0", "container": "image@sha256:" + "a" * 64}]
        self.repeat = [dict(row, status="CACHED") for row in self.first]
        self.processes = {"M3_ALIGN", "M3_SORT"}

    def test_same_tasks_and_hashes_must_all_be_cached(self) -> None:
        """Reject reruns, changed hashes, missing tasks, and substituted processes on resume."""
        result = DRIVER.validate_resume(self.first, self.repeat, self.processes)
        self.assertEqual(result["resumed_cached_tasks"], 2)
        for mutate in [lambda rows: rows[0].update(status="COMPLETED"), lambda rows: rows[0].update(hash="cc/different"),
                       lambda rows: rows.pop(), lambda rows: rows[0].update(name="W:M4_DEEPVARIANT (lane1)")]:
            altered = copy.deepcopy(self.repeat)
            mutate(altered)
            with self.assertRaises(ValueError):
                DRIVER.validate_resume(self.first, altered, self.processes)

    def test_first_run_cannot_have_a_preexisting_cache_hit(self) -> None:
        """Qualification must start with actual execution before any cache claim is accepted."""
        self.first[0]["status"] = "CACHED"
        with self.assertRaisesRegex(ValueError, "first run"):
            DRIVER.validate_resume(self.first, self.repeat, self.processes)

    def test_trace_must_contain_required_columns_and_tasks(self) -> None:
        """Incomplete headers and empty traces cannot establish execution or resume evidence."""
        with self.assertRaisesRegex(ValueError, "required"):
            DRIVER.parse_trace("name\tstatus\nM3_ALIGN\tCOMPLETED\n")
        with self.assertRaisesRegex(ValueError, "empty"):
            DRIVER.parse_trace("task_id\thash\tname\tstatus\texit\tcontainer\n")

    def test_command_keeps_params_and_work_identical_with_separate_raw_reports(self) -> None:
        """Keep cached inputs stable while preserving distinct first-run and resume reports."""
        root = Path("/tmp/m3-driver-test")
        args = ["nextflow", root / "checkout", root / "work", root / "out", root / "evidence", "a" * 40, "synthetic-run", "docker"]
        first = DRIVER.nextflow_command(*args, "first")
        repeat = DRIVER.nextflow_command(*args, "resume")
        for key in ("--m3_repository_sha", "--m3_run_id", "--outdir", "-work-dir", "-profile"):
            self.assertEqual(first[first.index(key) + 1], repeat[repeat.index(key) + 1])
        for key in ("-log", "-with-trace", "-with-report", "-with-timeline", "-with-dag"):
            self.assertNotEqual(first[first.index(key) + 1], repeat[repeat.index(key) + 1])
        self.assertNotIn("-resume", first)
        self.assertIn("-resume", repeat)
        self.assertFalse(any("truth" in value for value in first))
        stub = DRIVER.nextflow_command(*args[:-1], "stub", "stub")
        self.assertIn("-stub-run", stub)
        self.assertEqual(stub[stub.index("-profile") + 1], "m3_test")


class EvidenceBindingTest(unittest.TestCase):
    def test_reported_tool_version_is_distinct_from_distribution_release(self) -> None:
        """Executable identity must use its required report contract, not release metadata."""
        declaration = {"version": "9.0", "expected_reported_version": "1.24"}
        DRIVER.validate_samtools_version("samtools 1.24", declaration)
        for observed in ("samtools 9.0", "samtools 1.240", "samtools 1.24.1"):
            with self.assertRaisesRegex(ValueError, "observed samtools version"):
                DRIVER.validate_samtools_version(observed, declaration)
        with self.assertRaisesRegex(ValueError, "expectation is missing"):
            DRIVER.validate_samtools_version("samtools 1.24", {"version": "1.24"})

    def setUp(self) -> None:
        """Prepare mutually consistent synthetic contracts for isolated identity mutations."""
        self.fixture = fixture_payloads()[1]
        self.version = "0.3.0-dev.1"
        base = {"run_id": "run", "producer": {"version": self.version}, "synthetic": True,
                "canonical": False, "validation_status": "validated_synthetic", "data": {}}
        self.contracts = {f"m3-{name}.json": copy.deepcopy(base) for name in
                          ("manifest", "alignment", "qc", "coverage", "resources", "provenance")}
        reference = self.fixture["files"]["reference.fa"]["sha256"]
        self.contracts["m3-manifest.json"]["data"] = {"repository_sha": "a" * 40, "reference_sha256": reference, "shared_bam_sha256": "b" * 64}
        self.contracts["m3-alignment.json"]["data"] = {"bam": {"sha256": "b" * 64}, "bai": {"sha256": "c" * 64}, "sample": self.fixture["sample"], "duplicates_retained": True, "bqsr_applied": True}
        self.contracts["m3-provenance.json"]["data"] = {"repository_sha": "a" * 40, "shared_bam_sha256": "b" * 64,
            "known_sites_sha256": self.fixture["files"]["known-sites.vcf"]["sha256"], "sample": self.fixture["sample"],
            "callers_executed": [], "canonical_hg001_executed": False, "capture_design_gate": "blocked"}

    def check(self) -> None:
        """Bind every contract to the same run, code, reference, BAM, and synthetic scope."""
        DRIVER.validate_contract_identity(self.contracts, self.fixture, "a" * 40, "run", self.version, "b" * 64, "c" * 64)

    def test_contracts_bind_exact_execution_bam_reference_and_scope(self) -> None:
        """Mutating one contract must break acceptance even when the remaining bundle agrees."""
        self.check()
        for filename, field, value in [("m3-manifest.json", "repository_sha", "d" * 40),
                                        ("m3-manifest.json", "reference_sha256", "d" * 64),
                                        ("m3-provenance.json", "shared_bam_sha256", "d" * 64),
                                        ("m3-provenance.json", "canonical_hg001_executed", True),
                                        ("m3-provenance.json", "callers_executed", ["gatk"])]:
            prior = self.contracts[filename]["data"][field]
            self.contracts[filename]["data"][field] = value
            with self.assertRaises(ValueError):
                self.check()
            self.contracts[filename]["data"][field] = prior

    def test_declared_container_tag_cannot_replace_verified_digest(self) -> None:
        """Only the configured immutable image identity may satisfy a task container record."""
        image = "quay.io/example/tool@sha256:" + "a" * 64
        row = {"name": "W:M3_ALIGN (lane1)", "container": image}
        DRIVER.validate_trace_containers([row], {"tools": {"bwa-mem2": {"image": image}}})
        row["container"] = "quay.io/example/tool:latest"
        with self.assertRaisesRegex(ValueError, "container"):
            DRIVER.validate_trace_containers([row], {"tools": {"bwa-mem2": {"image": image}}})

    def test_uploadable_evidence_redacts_paths_and_url_credentials(self) -> None:
        """Remove private roots and URL credentials while preserving safe logical locations."""
        root = Path.home() / "private-integration"
        text = f"{root}/task https://user:password@example.invalid/file?token=secret#fragment"
        result = DRIVER.redact_text(text, root)
        self.assertNotIn(str(Path.home()), result)
        self.assertNotIn("password", result)
        self.assertNotIn("token=", result)
        self.assertIn("$INTEGRATION_ROOT/task", result)

    def test_exact_raw_reports_are_preserved_before_public_redaction(self) -> None:
        """Retain original report bytes and bind them to separately hashed redacted copies."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            evidence = root / "evidence"
            evidence.mkdir()
            report = evidence / "first.report.html"
            raw = f"<html>execution path {root}/nextflow-work</html>"
            report.write_text(raw)
            info = DRIVER.finish_evidence(root)
            self.assertEqual((root / "raw-execution/first.report.html").read_text(), raw)
            self.assertTrue(info[report.name]["redacted_copy"])
            self.assertNotEqual(info[report.name]["raw_sha256"], info[report.name]["uploaded_sha256"])
            self.assertNotIn(str(root), report.read_text())


    def test_invalid_report_quarantines_all_candidates_before_any_promotion(self) -> None:
        """One unsafe report prevents promotion of every candidate, including safe diagnostics."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "a.nextflow.log").write_text("invented /Users/another-person/private/path")
            (evidence / "z.report.html").write_text("invented /content/drive/private/report")
            (evidence / "safe.stdout.txt").write_text("safe diagnostic")
            with self.assertRaisesRegex(ValueError, "private path"):
                DRIVER.finish_evidence(root)
            self.assertEqual(list(evidence.iterdir()), [])
            self.assertTrue(list(root.glob("quarantined-evidence-*")))

    def test_evidence_or_proof_privacy_failure_leaves_only_a_safe_failed_proof(self) -> None:
        """Any privacy failure clears success claims and leaves only a sanitized failure record."""
        cases = [("diagnostic.stdout.txt", "invented /Users/another-person/private/path", {}),
                 ("contracts/m3-provenance.json", '{"filename":"/content/drive/private/file"}', {}),
                 ("safe.txt", "safe diagnostic", {"failure": {"message": "invented /home/another-person/path"}})]
        for filename, contents, extra in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                evidence = root / "evidence"
                target = evidence / filename
                target.parent.mkdir(parents=True)
                target.write_text(contents)
                proof = {"status": "passed", "biological_processing_validated": True, **extra}
                with self.assertRaises(ValueError):
                    DRIVER.finalize_proof(root, proof)
                self.assertEqual([path.name for path in evidence.iterdir()], ["integration-proof.json"])
                failed = json.loads((evidence / "integration-proof.json").read_text())
                self.assertEqual(failed["status"], "failed")
                self.assertFalse(failed["biological_processing_validated"])
                self.assertNotIn("another-person", json.dumps(failed))
                self.assertNotIn("/content/drive", json.dumps(failed))

    def test_runner_validates_both_diagnostic_streams_before_upload(self) -> None:
        """Unsafe stderr blocks publication even when command exit and stdout appear valid."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = DRIVER.Runner(root, {}, [])
            result = subprocess.CompletedProcess(["invented"], 0, "safe stdout", "invented /Users/another-person/path")
            with patch("m3_integration_driver.subprocess.run", return_value=result), self.assertRaises(ValueError):
                runner.run("synthetic-diagnostic", ["invented"], root)
            self.assertEqual(list((root / "evidence").iterdir()), [])
            self.assertEqual((root / "diagnostics/synthetic-diagnostic.stderr.txt").read_text(), result.stderr)


class PreflightSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        """Create an isolated empty Git commit with the exact expected repository origin."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repository = self.root / "checkout"
        self.repository.mkdir()
        for command in [["git", "init", "-b", "main"], ["git", "remote", "add", "origin", "https://github.com/jcollins-bioinfo/giab-wes-nextflow.git"],
                        ["git", "-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid", "commit", "--allow-empty", "-m", "Synthetic identity fixture"]]:
            subprocess.run(command, cwd=self.repository, check=True, capture_output=True)
        self.sha = DRIVER.git_output(self.repository, "rev-parse", "HEAD")

    def test_preflight_observes_missing_docker_without_creating_output(self) -> None:
        """Read-only preflight may report missing tools without claiming execution or creating output."""
        output = self.root / "qualification"
        stream = io.StringIO()
        with patch("m3_integration_driver.shutil.which", return_value=None), redirect_stdout(stream):
            self.assertEqual(DRIVER.main(["--repository", str(self.repository), "--output-root", str(output), "--expected-sha", self.sha, "--mode", "preflight"]), 0)
        result = json.loads(stream.getvalue())
        self.assertFalse(result["execution_verified"])
        self.assertGreater(result["storage"]["free_bytes"], 0)
        self.assertEqual(result["storage"]["minimum_free_bytes"], 10 * 1024 ** 3)
        self.assertFalse(output.exists())

    def test_low_disk_fails_before_cloning_installing_or_creating_output(self) -> None:
        """Insufficient storage must fail before any command or qualification directory is created."""
        output = self.root / "qualification"
        observation = {"free_bytes": 1, "total_bytes": 20 * 1024 ** 3,
                       "minimum_free_bytes": 10 * 1024 ** 3, "meets_synthetic_minimum": False}
        with patch("m3_integration_driver.shutil.which", return_value="/fake/executable"), \
                patch("m3_integration_driver.storage_observation", return_value=observation), \
                patch.object(DRIVER.Runner, "run") as execute:
            with self.assertRaisesRegex(ValueError, "10 GiB"):
                DRIVER.main(["--repository", str(self.repository), "--output-root", str(output), "--expected-sha", self.sha, "--mode", "docker"])
            execute.assert_not_called()
        self.assertFalse(output.exists())

    def test_docker_capability_checks_memory_cpu_and_architecture(self) -> None:
        """Require usable Linux amd64 capacity and exclude unrelated daemon metadata."""
        valid = {"OSType": "linux", "Architecture": "x86_64", "NCPU": 2,
                 "MemTotal": 4 * 1024 ** 3, "ServerVersion": "observed", "unrelated": "excluded"}
        self.assertNotIn("unrelated", DRIVER.validate_docker_capability(valid))
        for change in [{"MemTotal": 4 * 1024 ** 3 - 1}, {"MemTotal": "unavailable"},
                       {"NCPU": 0}, {"NCPU": True}, {"Architecture": "arm64"}, {"OSType": "darwin"}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                DRIVER.validate_docker_capability(dict(valid, **change))

    def test_docker_format_requests_only_runtime_capacity_and_identity(self) -> None:
        """Request each of the five allowed daemon fields exactly once and preserve valid JSON."""
        template = DRIVER.docker_info_format()
        fields = ("OSType", "Architecture", "ServerVersion", "NCPU", "MemTotal")
        rendered = template
        for field in fields:
            token = "{" * 2 + "json ." + field + "}" * 2
            self.assertEqual(template.count(token), 1)
            rendered = rendered.replace(token, "null")
        self.assertEqual(json.loads(rendered), dict.fromkeys(fields))

    def test_multiqc_ownership_binds_original_task_to_published_report(self) -> None:
        """Verify task-report UID, GID, and bytes independently of the published copy."""
        work = self.root / "nextflow-work"
        report = work / "aa" / ("b" * 30) / "multiqc_report.html"
        report.parent.mkdir(parents=True)
        report.write_text("<html>invented report</html>")
        published = self.root / "multiqc_report.html"
        published.write_bytes(report.read_bytes())
        rows = [{"name": "W:M3_MULTIQC (stage)", "hash": "aa/" + "b" * 6}]
        result = DRIVER.validate_multiqc_ownership(rows, work, published)
        self.assertTrue(result["task_report_owned_by_host_user_and_group"])
        self.assertEqual(result["report_sha256"], DRIVER.digest(published))
        with patch("m3_integration_driver.os.getuid", return_value=report.stat().st_uid + 1):
            with self.assertRaisesRegex(ValueError, "ownership"):
                DRIVER.validate_multiqc_ownership(rows, work, published)
        with patch("m3_integration_driver.os.getgid", return_value=report.stat().st_gid + 1):
            with self.assertRaisesRegex(ValueError, "ownership"):
                DRIVER.validate_multiqc_ownership(rows, work, published)
        published.write_text("altered report")
        with self.assertRaisesRegex(ValueError, "differs"):
            DRIVER.validate_multiqc_ownership(rows, work, published)

    def test_multiqc_ownership_rejects_ambiguous_or_unsafe_trace_location(self) -> None:
        """Resolve one safe task directory from the trace before inspecting report ownership."""
        work = self.root / "nextflow-work"
        for suffix in ("c", "d"):
            (work / "aa" / ("b" * 6 + suffix * 24)).mkdir(parents=True)
        rows = [{"name": "W:M3_MULTIQC (stage)", "hash": "aa/" + "b" * 6}]
        with self.assertRaisesRegex(ValueError, "exactly one task directory"):
            DRIVER.validate_multiqc_ownership(rows, work, self.root / "report.html")
        rows[0]["hash"] = "../outside"
        with self.assertRaisesRegex(ValueError, "invalid MultiQC trace hash"):
            DRIVER.validate_multiqc_ownership(rows, work, self.root / "report.html")

    def test_preflight_reports_low_disk_without_running_an_engine(self) -> None:
        """Observe capacity through an existing ancestor without creating paths or invoking an engine."""
        output = self.root / "missing-parent" / "qualification"
        fake_usage = type("Usage", (), {"free": 1, "total": 2})()
        with patch("m3_integration_driver.shutil.disk_usage", return_value=fake_usage), \
                patch.object(DRIVER.Runner, "run") as execute:
            result = DRIVER.preflight(self.repository, self.sha, "nextflow", "docker", output)
            execute.assert_not_called()
        self.assertFalse(result["storage"]["meets_synthetic_minimum"])
        self.assertFalse(output.parent.exists())

    def test_missing_docker_cannot_be_reported_as_execution_success(self) -> None:
        """Missing Docker must stop execution mode before a qualification directory exists."""
        with patch("m3_integration_driver.shutil.which", side_effect=lambda value: "/fake/nextflow" if value == "nextflow" else None):
            with self.assertRaisesRegex(ValueError, "Docker is unavailable"):
                DRIVER.main(["--repository", str(self.repository), "--output-root", str(self.root / "qualification"), "--expected-sha", self.sha, "--mode", "docker"])
        self.assertFalse((self.root / "qualification").exists())

    def test_wrong_sha_dirty_source_and_substring_origin_are_rejected(self) -> None:
        """Require the exact clean commit and origin rather than a matching repository substring."""
        with self.assertRaisesRegex(ValueError, "commit"):
            DRIVER.repository_identity(self.repository, "0" * 40)
        (self.repository / "untracked.txt").write_text("synthetic")
        with self.assertRaisesRegex(ValueError, "clean"):
            DRIVER.repository_identity(self.repository, self.sha)
        (self.repository / "untracked.txt").unlink()
        subprocess.run(["git", "remote", "set-url", "origin", "https://example.invalid/jcollins-bioinfo/giab-wes-nextflow.git"], cwd=self.repository, check=True)
        with self.assertRaisesRegex(ValueError, "origin"):
            DRIVER.repository_identity(self.repository, self.sha)

    def test_forbidden_output_name_rejected_before_access(self) -> None:
        """Reject a prohibited path component before reading or creating its descendants."""
        with self.assertRaisesRegex(ValueError, "prohibited"):
            DRIVER.guarded_path(self.root / "DO NOT ACCESS WITH CHATGPT area" / "integration")


if __name__ == "__main__":
    unittest.main()

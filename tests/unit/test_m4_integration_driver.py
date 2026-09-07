"""Independent negative gates for real M4 execution, isolation and mode equivalence."""
from __future__ import annotations

import copy
import gzip
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    SPEC = importlib.util.spec_from_file_location("m4_integration_driver", ROOT / "scripts/run_m4_synthetic.py")
    DRIVER = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(DRIVER)
finally:
    sys.path.pop(0)


def mode_traces() -> tuple[dict[str, list[dict[str, str]]], dict[str, Any], dict[str, Any]]:
    """Construct task-state observations without executing or claiming any caller."""
    m3 = json.loads((ROOT / "config/m3-tools.json").read_text())
    m4 = json.loads((ROOT / "config/m4-tools.json").read_text())
    assignments = {"M3_REFERENCE_FAIDX": "samtools", "M3_SORT": "samtools", "M3_MERGE": "samtools",
                   "M3_PRE_BQSR": "samtools", "M3_BAM_SUMMARY": "samtools", "M3_BWA_INDEX": "bwa-mem2",
                   "M3_ALIGN": "bwa-mem2", "M3_FASTQC": "fastqc", "M3_REFERENCE_METADATA": "gatk",
                   "M3_MARKDUP": "gatk", "M3_RECALIBRATE": "gatk", "M3_APPLY_BQSR": "gatk",
                   "M3_PICARD_QC": "gatk", "M3_MOSDEPTH": "mosdepth", "M3_MULTIQC": "multiqc"}
    base = []
    for name in sorted(DRIVER.shared.EXPECTED_PROCESSES):
        for lane in range(2 if name in {"M3_FASTQ_VALIDATE", "M3_FASTQC", "M3_ALIGN", "M3_SORT"} else 1):
            base.append({"name": f"W:{name} ({lane})", "hash": f"aa/{len(base):06x}", "exit": "0",
                         "status": "COMPLETED", "container": m3["tools"][assignments[name]]["image"] if name in assignments else "-"})
    traces = {}
    previous: set[str] = set()
    for phase in ("gatk", "deepvariant", "both", "resume"):
        mode = "both" if phase == "resume" else phase
        rows = copy.deepcopy(base)
        selected = ("gatk", "deepvariant") if mode == "both" else (mode,)
        rows.append({"name": "W:M4_PREPARE_INPUTS (common)", "hash": "bb/000001", "container": "-", "exit": "0"})
        rows.append({"name": "W:M4_BUNDLE", "hash": {"gatk": "bb/000002", "deepvariant": "bb/000003", "both": "bb/000004"}[mode], "container": "-", "exit": "0"})
        for index, caller in enumerate(selected):
            rows.append({"name": f"W:{DRIVER.CALLER_PROCESSES[caller]} (sample)", "hash": "cc/000001" if caller == "gatk" else "cc/000002", "container": m4["tools"][caller]["image"], "exit": "0"})
            rows.append({"name": f"W:M4_COLLECT_{caller.upper()} (sample)", "hash": "dd/000001" if caller == "gatk" else "dd/000002", "container": "-", "exit": "0"})
        for row in rows:
            row["status"] = "CACHED" if row["name"] in previous else "COMPLETED"
            if row["name"] == "W:M4_BUNDLE" and phase != "resume":
                row["status"] = "COMPLETED"
        previous.update(row["name"] for row in rows)
        traces[phase] = rows
    return traces, m3, m4


class ModeReuseTest(unittest.TestCase):
    """Independent modes must execute once and share accepted preprocessing thereafter."""

    def test_real_modes_and_identical_cached_repeat_are_required(self) -> None:
        """Initial execution and later complete reuse are both necessary observations."""
        traces, m3, m4 = mode_traces()
        result = DRIVER.validate_mode_traces(traces, m3, m4)
        self.assertTrue(result["both_callers_executed"])
        self.assertEqual(result["modes"], {"gatk": {"COMPLETED": 26}, "deepvariant": {"CACHED": 23, "COMPLETED": 3},
                                        "both": {"CACHED": 27, "COMPLETED": 1}, "resume": {"CACHED": 28}})
        for phase, field, value in (("gatk", "status", "CACHED"), ("deepvariant", "status", "COMPLETED"),
                                    ("both", "hash", "ef/123456"), ("resume", "status", "COMPLETED")):
            modified = copy.deepcopy(traces)
            modified[phase][0][field] = value
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                DRIVER.validate_mode_traces(modified, m3, m4)

    def test_selection_cannot_omit_collector_or_add_caller(self) -> None:
        """Unexpected or omitted tasks cannot be concealed by a successful native file."""
        traces, m3, m4 = mode_traces()
        traces["gatk"] = [row for row in traces["gatk"] if "M4_COLLECT" not in row["name"]]
        with self.assertRaisesRegex(ValueError, "task inventory"):
            DRIVER.validate_mode_traces(traces, m3, m4)

    def test_commands_keep_sources_params_and_work_identical(self) -> None:
        """Only caller selection and report filenames vary across the four invocations."""
        arguments = ("nextflow", Path("checkout"), Path("work"), Path("output"), Path("reports"), "a" * 40, "run")
        gatk = DRIVER.nextflow_command(*arguments, "gatk", "gatk")
        both = DRIVER.nextflow_command(*arguments, "both", "both")
        repeat = DRIVER.nextflow_command(*arguments, "both", "resume")
        self.assertNotIn("-resume", gatk)
        self.assertIn("-resume", both)
        for field in ("--m3_repository_sha", "--m3_run_id", "--outdir", "-work-dir"):
            self.assertEqual(gatk[gatk.index(field) + 1], both[both.index(field) + 1])
        self.assertNotEqual(both[both.index("-with-trace") + 1], repeat[repeat.index("-with-trace") + 1])
        self.assertNotIn("-stub-run", gatk + both + repeat)


class IndexReaderVersionTest(unittest.TestCase):
    """A Conda prefix declaration cannot replace exact image-bound version evidence."""

    def test_observation_preserves_selector_and_exact_runtime_versions(self) -> None:
        """Accept the observed versions only for the immutable image in the tool lock."""
        lock = json.loads((ROOT / "config/m4-tools.json").read_text())
        text = "bcftools 1.15.1\nUsing htslib 1.21\nLicense information\n"
        result = DRIVER.validate_index_reader_version(text, lock["tools"]["deepvariant"]["image"])
        self.assertEqual(result["declared_conda_selector"], "bioconda::bcftools=1.15")
        self.assertEqual(result["observed_version"], "1.15.1")
        self.assertEqual(result["observed_htslib_version"], "1.21")
        self.assertEqual(result["observed_text"], text)
        self.assertEqual(result["observed_text_sha256"], DRIVER.hashlib.sha256(text.encode()).hexdigest())

    def test_selector_patch_drift_missing_library_and_ambiguous_reports_fail(self) -> None:
        """Reject fuzzy matches, absent HTSlib identity and conflicting version lines."""
        text = "bcftools 1.15.1\nUsing htslib 1.21\n"
        for bad in (text.replace("1.15.1", "1.15"), text.replace("1.15.1", "1.15.10"),
                    text.replace("1.21", "1.21.1"), "bcftools 1.15.1\n", "warning\n" + text,
                    text + "bcftools 1.15\n", text + "Using htslib 1.15\n"):
            with self.subTest(text=bad), self.assertRaises(ValueError):
                DRIVER.validate_index_reader_version(bad, DRIVER.INDEX_READER_IMAGE)

    def test_matching_versions_do_not_qualify_a_different_image(self) -> None:
        """Identical version text cannot transfer qualification to another image digest."""
        image = DRIVER.INDEX_READER_IMAGE.rsplit("@", 1)[0] + "@sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "image lacks"):
            DRIVER.validate_index_reader_version("bcftools 1.15.1\nUsing htslib 1.21\n", image)


class IsolationAndCapabilityTest(unittest.TestCase):
    """A caller must never see fixture ancestors or launch on an unsupported CPU."""

    def test_task_mounts_require_network_none_and_exclude_ancestors(self) -> None:
        """Actual Docker volume sources must be confined to the copied task directory."""
        with tempfile.TemporaryDirectory() as temporary:
            task = Path(temporary).resolve() / "task"
            task.mkdir()
            command = f'docker run --network none -v {task}:{task} -w "$NXF_TASK_WORKDIR" image bash'
            self.assertTrue(DRIVER.validate_caller_mounts(command, task)["mounts_within_task_only"])
            for bad in (command.replace("--network none", "--network host"),
                        command.replace(f"-v {task}:", f"-v {task.parent}:"),
                        command + f" -v {task.parent}/oracle:/oracle:ro", command + " --privileged"):
                with self.subTest(command=bad), self.assertRaises(ValueError):
                    DRIVER.validate_caller_mounts(bad, task)

    def test_missing_avx_and_low_memory_fail(self) -> None:
        """Declared x86 metadata cannot substitute for measured required instructions."""
        engine = {"OSType": "linux", "Architecture": "x86_64", "NCPU": 4, "MemTotal": 16 * 1024 ** 3}
        flags = ["sse4_1", "sse4_2", "avx"]
        cpu = {"system": "Linux", "architecture": "x86_64", "flags": flags}
        DRIVER.validate_capability(engine, cpu, flags)
        for bad in ({**cpu, "flags": ["sse4_1", "sse4_2"]}, {**cpu, "architecture": "aarch64"}):
            with self.assertRaises(ValueError):
                DRIVER.validate_capability(engine, bad, flags)
        with self.assertRaises(ValueError):
            DRIVER.validate_capability({**engine, "MemTotal": 8 * 1024 ** 3}, cpu, flags)

    def test_actual_caller_input_bytes_bind_to_accepted_contract(self) -> None:
        """Swapped BAM/reference bytes or additional files cannot pass regular-file checks alone."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            inputs = root / "caller-inputs"
            inputs.mkdir()
            names = ("shared.bam", "shared.bam.bai", "reference.fa", "reference.fa.fai", "reference.dict", "regions.bed")
            identities = []
            for name in names:
                path = inputs / name
                path.write_bytes(name.encode())
                identities.append({"filename": name, "bytes": path.stat().st_size, "sha256": DRIVER.shared.digest(path)})
            metadata = root / "accepted.json"
            metadata.write_text(json.dumps({"data": {"files": identities}}))
            (inputs / "m4-inputs.json").write_bytes(metadata.read_bytes())
            self.assertTrue(DRIVER.validate_staged_inputs(inputs, metadata)["actual_bytes_match_accepted_contract"])
            for name in ("shared.bam", "reference.fa"):
                path = inputs / name
                before = path.read_bytes()
                path.write_bytes(b"swapped")
                with self.assertRaisesRegex(ValueError, "input bytes differ"):
                    DRIVER.validate_staged_inputs(inputs, metadata)
                path.write_bytes(before)
            (inputs / "oracle.json").write_text("invented")
            with self.assertRaisesRegex(ValueError, "unexpected"):
                DRIVER.validate_staged_inputs(inputs, metadata)
            (inputs / "oracle.json").unlink()
            (inputs / "m4-inputs.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "metadata differs"):
                DRIVER.validate_staged_inputs(inputs, metadata)

    def test_arm_rejected_before_any_command_or_output_creation(self) -> None:
        """An unsupported host cannot reach Nextflow, Docker, cloning or caller launch."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "new"
            info = {"nextflow_executable": "nextflow", "docker_executable": "docker"}
            with patch.object(DRIVER.shared, "preflight", return_value=info), patch.object(DRIVER, "storage_observation", return_value={"meets_synthetic_minimum": True}), \
                 patch.object(DRIVER.platform, "system", return_value="Linux"), patch.object(DRIVER.platform, "machine", return_value="aarch64"), \
                 patch.object(DRIVER.shared.Runner, "run") as run:
                with self.assertRaisesRegex(ValueError, "Linux x86_64"):
                    DRIVER.main(["--output-root", str(output), "--expected-sha", "a" * 40])
                run.assert_not_called()
            self.assertFalse(output.exists())

    def test_privacy_failure_leaves_only_safe_m4_proof(self) -> None:
        """Unsafe text is quarantined before any M4 artifact is eligible for upload."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "evidence").mkdir()
            (root / "evidence/report.txt").write_text("/Users/invented_private_owner/secret")
            with self.assertRaises(ValueError):
                DRIVER.finalize_proof(root, {"kind": "m4-synthetic-integration-proof", "status": "passed"})
            files = list((root / "evidence").iterdir())
            self.assertEqual([path.name for path in files], ["integration-proof.json"])
            proof = json.loads(files[0].read_text())
            self.assertEqual(proof["kind"], "m4-synthetic-integration-proof")
            self.assertEqual(proof["status"], "failed")
            self.assertNotIn("/Users/", files[0].read_text())

    def test_failure_diagnostics_validate_both_streams_before_printing(self) -> None:
        """CI logs expose safe errors while withholding either stream on privacy failure."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            runner = DRIVER.Runner(root, {}, [])
            for stdout, stderr, allowed in (("safe stdout", "actual task error", True),
                                            ("safe stdout", "/Users/invented_owner/private", False)):
                stream = io.StringIO()
                with patch.object(DRIVER.shared.subprocess, "run", return_value=SimpleNamespace(stdout=stdout, stderr=stderr, returncode=1)), redirect_stderr(stream):
                    with self.assertRaises(ValueError):
                        runner.run("failure", ["invented-command"], root)
                self.assertEqual(bool(stream.getvalue()), allowed)
                self.assertNotIn("/Users/", stream.getvalue())


class InferenceIdentityTest(unittest.TestCase):
    """Only positive inference using the pre-frozen WES model can satisfy M4."""

    def setUp(self) -> None:
        """Create metadata-only invented observations without loading a model."""
        names = ["fingerprint.pb", "saved_model.pb", "model.example_info.json",
                 "variables/variables.data-00000-of-00001", "variables/variables.index"]
        files = [{"filename": name, "bytes": 20, "sha256": "a" * 64} for name in names]
        self.before = {"kind": "m4_deepvariant_model_inventory", "schema_version": "1.0.0", "model_type": "WES", "model_files": files}
        self.after = {**copy.deepcopy(self.before), "kind": "m4_deepvariant_inference", "example_record_count": 3,
                      "call_variants_record_count": 3, "all_probabilities_valid": True, "probability_tolerance": 1e-5,
                      "variant_contigs": ["chrSYN1"], "example_files": [{"filename": "examples.gz", "bytes": 10, "sha256": "b" * 64}],
                      "call_variants_files": [{"filename": "calls.gz", "bytes": 10, "sha256": "c" * 64}]}

    def test_zero_candidates_invalid_predictions_or_model_drift_fail(self) -> None:
        """Nonempty calls alone cannot hide missing candidates or altered model files."""
        self.assertTrue(DRIVER.validate_inference(self.before, self.after, "a" * 64, {"chrSYN1"})["pre_inference_model_hashes_identical"])
        for key, value in (("example_record_count", 0), ("call_variants_record_count", 0),
                           ("all_probabilities_valid", False), ("probability_tolerance", 0.1),
                           ("variant_contigs", ["human"]), ("example_files", [])):
            bad = {**self.after, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                DRIVER.validate_inference(self.before, bad, "a" * 64, {"chrSYN1"})
        bad = copy.deepcopy(self.after)
        bad["model_files"][0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "model bytes changed"):
            DRIVER.validate_inference(self.before, bad, "a" * 64, {"chrSYN1"})

    def test_index_semantics_preserve_loci_genotypes_and_gvcf_spans(self) -> None:
        """Indexed comparisons bind record positions, alleles, genotypes and block ends."""
        first = "chrSYN1\t1\t.\tA\t<*>\t.\t.\tEND=100\tGT\t0/0\n"
        self.assertNotEqual(DRIVER.vcf_query_semantics(first), DRIVER.vcf_query_semantics(first.replace("END=100", "END=99")))
        with self.assertRaises(ValueError):
            DRIVER.vcf_query_semantics("")


class ExecutionIdentityTest(unittest.TestCase):
    """Package-validated metadata still must identify this independently inspected run."""

    def test_contracts_bind_actual_run_package_fixture_and_shared_bam(self) -> None:
        """A valid bundle from another run or BAM cannot satisfy the integration proof."""
        from giab_wes_nextflow import __version__
        from test_m4_support import make_unit_bundle
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            contracts = make_unit_bundle(root)
            fixture_path = root / "preprocessing/fixture/fixture-expectations.json"
            fixture = json.loads(fixture_path.read_text())
            args = [contracts, "a" * 40, "m4-unit-contract", __version__, fixture, DRIVER.shared.digest(fixture_path),
                    DRIVER.shared.digest(root / "caller-inputs/shared.bam"), DRIVER.shared.digest(root / "caller-inputs/shared.bam.bai"),
                    root / "preprocessing/contracts/m3-manifest.json"]
            DRIVER.validate_execution_identity(*args)
            for index, value in ((1, "b" * 40), (2, "other-run"), (3, "0.0.0"), (5, "f" * 64), (6, "e" * 64), (7, "d" * 64)):
                changed = list(args)
                changed[index] = value
                with self.subTest(index=index), self.assertRaises(ValueError):
                    DRIVER.validate_execution_identity(*changed)


class AlleleOracleTest(unittest.TestCase):
    """A fixed allele oracle must reject empty, moved or genotype-discordant calls."""

    def test_fragment_counts_and_cigar_are_exact(self) -> None:
        """Observed allele support cannot be manufactured by caller outputs or clipping."""
        rows = []
        for site in DRIVER.ORACLE:
            bases = [site["ref"]] * site["ref_fragments"] + [site["alt"]] * site["alt_fragments"]
            for index, base in enumerate(bases):
                sequence = "A" * 50 + base + "A" * 99
                rows.append(f"read_{site['contig']}_{site['position_1based']}_{index}\t0\t{site['contig']}\t{site['position_1based'] - 50}\t60\t150M\t*\t0\t0\t{sequence}\t{'I' * 150}")
        sam = "\n".join(rows)
        self.assertTrue(DRIVER.validate_alleles(sam)["all_mapped_cigars_150M"])
        for bad in ("\n".join(rows[1:]), sam.replace("150M", "149M1S", 1)):
            with self.assertRaises(ValueError):
                DRIVER.validate_alleles(bad)

    def test_native_genotypes_and_reference_control(self) -> None:
        """Only both predeclared native SNVs and a nonvariant control satisfy acceptance."""
        header = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSYNTHETIC01\n"
        body = "chrSYN1\t3151\t.\tT\tA\t60\tPASS\t.\tGT\t0/1\nchrSYN2\t7101\t.\tT\tA\t60\tPASS\t.\tGT\t1/1\n"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "native.vcf.gz"
            with gzip.open(path, "wt") as stream:
                stream.write(header + body)
            self.assertTrue(DRIVER.validate_native_vcf(path, "SYNTHETIC01")["expected_native_snvs_valid"])
            for text in (header, header + body.replace("0/1", "0/0"),
                         header + body + "chrSYN1\t5401\t.\tG\tA\t60\tPASS\t.\tGT\t0/1\n"):
                with gzip.open(path, "wt") as stream:
                    stream.write(text)
                with self.assertRaises(ValueError):
                    DRIVER.validate_native_vcf(path, "SYNTHETIC01")


if __name__ == "__main__":
    unittest.main()

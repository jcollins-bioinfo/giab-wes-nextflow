"""Synthetic publication contract tests; no genomic fixture bytes are used."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
from typing import Any, Callable
import unittest
from unittest.mock import patch

from giab_wes_nextflow.acquisition import checksum, now, observation
from giab_wes_nextflow.preparation import build_domains
from giab_wes_nextflow.publication import publish
from giab_wes_nextflow.resources import config_path


class PublishM2Test(unittest.TestCase):
    """Exercise real validation with a fully declared nonhuman fixture bundle."""

    def setUp(self) -> None:
        """Create all canonical resource roles using deterministic synthetic bytes."""
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.drive = self.base / "giab-wes-nextflow-private"
        self.stage = self.base / "m2-stage"
        self.drive.mkdir()
        self.stage.mkdir()
        self.run = "test-run"
        self.evidence = self.stage / "registry/runs" / self.run
        self.evidence.mkdir(parents=True)
        self.manifest = self.base / "manifest.json"
        self.decision = self.base / "target-decision.json"
        self.spec = json.loads(config_path("m2-resources.json").read_text())
        fasta = b">chr20\n" + b"ACGT" * 100 + b"\n"
        observations = []
        for item in self.spec["resources"]:
            path = self.stage / item["destination"]
            path.parent.mkdir(parents=True, exist_ok=True)
            content = (b"synthetic-nonhuman-" + item["id"].encode() + b"\n")
            if item["id"] == "grch38_no_alt_fasta_gz":
                content = gzip.compress(fasta, mtime=0)
            elif item["id"] == "hg001_v421_high_confidence_bed":
                content = b"chr20\t15\t35\n"
            path.write_bytes(content)
            item["bytes"] = len(content)
            item["checksum"]["expected"] = checksum(path, "md5")
            observations.append(observation(item, path, "verified", 0, {}, item["url"]))
        self.write_json(self.manifest, self.spec)
        self.write_json(self.evidence / "acquisition.json", {
            "schema_version": "1.0.0", "run_id": self.run, "created_utc": now(),
            "source_manifest_sha256": checksum(self.manifest), "observations": observations,
        })
        reference = []
        reference_bytes = {
            "grch38_fasta": ("references/ref.fa", fasta),
            "grch38_fai": ("references/ref.fa.fai", b"chr20\t400\t7\t400\t401\n"),
            "grch38_dict": ("references/ref.dict", b"@HD\tVN:1.6\n@SQ\tSN:chr20\tLN:400\n"),
        }
        for identity, (relative, content) in reference_bytes.items():
            path = self.stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            reference.append({"id": identity, "path": relative, "sha256": checksum(path)})
        cache = self.stage / "cache" / self.run
        cache.mkdir(parents=True)
        self.lifted = cache / "targets.GRCh38.bed"
        self.lifted.write_bytes(b"chr20\t10\t30\tsynthetic-target\n")
        rejected = cache / "targets.rejected.interval_list"
        rejected.write_bytes(b"@HD\tVN:1.6\n")
        source_bed = self.base / "synthetic-source-target.bed"
        source_bed.write_bytes(self.lifted.read_bytes())
        source_dict = self.base / "synthetic-source.dict"
        source_dict.write_bytes((self.stage / "references/ref.dict").read_bytes())
        self.write_json(self.decision, {
            "schema_version": "1.0.0", "classification": "confirmed", "canonical_domains_allowed": True,
            "approved_artifacts": {"target_bed_sha256": checksum(source_bed), "source_dict_sha256": checksum(source_dict)},
            "candidate": "Deterministic nonhuman unit-test fixture", "min_liftover_pct": 0.95,
            "primary_evidence": [{"finding": "All fixture bytes are generated in this test; no assay inference.",
                                  "url": "https://example.invalid/synthetic-fixture"}],
            "block_reason": None,
        })
        chain = next(item for item in self.spec["resources"] if item["id"] == "ucsc_hg19_to_hg38_chain")
        truth = next(item for item in self.spec["resources"] if item["id"] == "hg001_v421_high_confidence_bed")
        domains = build_domains(self.lifted, self.stage / truth["destination"], self.stage / "references/ref.dict",
                                self.stage / "references/domains", self.run)
        self.write_json(self.evidence / "transformation.json", {
            "schema_version": "1.0.0", "run_id": self.run, "status": "domains_materialized",
            "capture_design_classification": "confirmed", "reference": reference, "domains": domains,
            "liftover": {"tool": "Picard LiftOverIntervalList", "required_version": "3.1.1", "observed_version": "3.1.1",
                         "min_liftover_pct": 0.95, "source_sha256": checksum(source_bed),
                         "source_dict_sha256": checksum(source_dict), "chain_sha256": checksum(self.stage / chain["destination"]),
                         "lifted_bed_path": str(self.lifted.relative_to(self.stage)), "lifted_bed_sha256": checksum(self.lifted),
                         "rejected_sha256": checksum(rejected), "input_intervals": 1, "input_bases": 20,
                         "lifted_intervals": 1, "lifted_bases": 20, "rejected_intervals": 0,
                         "split_intervals": 0, "merged_intervals": 1, "altered_length_intervals": 0},
        })

    def tearDown(self) -> None:
        """Remove only the owned temporary synthetic workspace."""
        self.tmp.cleanup()

    @staticmethod
    def write_json(path: Path, record: dict[str, Any]) -> None:
        """Persist a deterministic fixture control record."""
        path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")

    def publish_fixture(self) -> tuple[Path, bool]:
        """Use the complete explicit synthetic decision, never a gate bypass."""
        return publish(self.drive, self.stage, self.run, self.manifest, self.decision)

    def mutate(self, name: str, mutate: Callable[[dict[str, Any]], Any]) -> None:
        """Alter a fixture evidence object for a negative test."""
        path = self.evidence / name
        record = json.loads(path.read_text())
        mutate(record)
        self.write_json(path, record)

    def test_completed_last_and_idempotent(self) -> None:
        """All durable bytes and immutable control records survive no-op retry."""
        path, changed = self.publish_fixture()
        self.assertTrue(changed)
        self.assertTrue((path / "COMPLETED.json").is_file())
        registry = self.drive / "m2_data_provenance/registry/runs/test-run.json"
        self.assertTrue(registry.is_file())
        before = {file.relative_to(path): file.read_bytes() for file in path.rglob("*") if file.is_file()}
        self.assertFalse(self.publish_fixture()[1])
        self.assertEqual(before, {file.relative_to(path): file.read_bytes() for file in path.rglob("*") if file.is_file()})

    def test_default_unresolved_gate_rejects_forged_status(self) -> None:
        """A complete forged status cannot override the packaged scientific gate."""
        with self.assertRaisesRegex(ValueError, "Gate B blocked"):
            publish(self.drive, self.stage, self.run, self.manifest)
        self.assertFalse((self.drive / "m2_data_provenance").exists())

    def test_incomplete_never_completed_and_gate_required(self) -> None:
        """Missing transformation evidence fails before durable publication."""
        (self.evidence / "transformation.json").unlink()
        with self.assertRaises(ValueError):
            self.publish_fixture()
        self.assertFalse((self.drive / "m2_data_provenance").exists())

    def test_rejects_partial_or_wrong_manifest_acquisition(self) -> None:
        """Publication requires each declared resource exactly once."""
        self.mutate("acquisition.json", lambda record: record.update(observations=[]))
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.publish_fixture()

    def test_rejects_dot_path_run_ids(self) -> None:
        """Run identities cannot be path traversal or special directories."""
        for run_id in (".", "..", "a/b", "../x"):
            with self.subTest(run_id=run_id), self.assertRaisesRegex(ValueError, "invalid run id"):
                publish(self.drive, self.stage, run_id, self.manifest, self.decision)

    def test_rejects_missing_prepared_artifact(self) -> None:
        """A recorded digest cannot stand in for missing prepared bytes."""
        (self.stage / "references/domains/T_design.bed").unlink()
        with self.assertRaisesRegex(ValueError, "prepared artifact"):
            self.publish_fixture()

    def test_safety_marker(self) -> None:
        """The explicit owner safety marker prevents any Drive publication."""
        (self.drive / "DO NOT ACCESS WITH CHATGPT").touch()
        with self.assertRaises(PermissionError):
            self.publish_fixture()

    def test_rejects_wrong_gate_source_identity(self) -> None:
        """Liftover must use the exact target bytes approved by the decision."""
        self.mutate("transformation.json", lambda record: record["liftover"].update(source_sha256="a" * 64))
        with self.assertRaisesRegex(ValueError, "approved source identity"):
            self.publish_fixture()

    def test_rejects_invalid_acquisition_schema(self) -> None:
        """A source record missing required provenance is not publishable."""
        self.mutate("acquisition.json", lambda record: record["observations"][0].pop("tool"))
        with self.assertRaisesRegex(ValueError, "schema.*validation failed"):
            self.publish_fixture()

    def test_rejects_cross_run_transformation(self) -> None:
        """Preparation from a different run cannot satisfy the requested run."""
        self.mutate("transformation.json", lambda record: record.update(run_id="other-run"))
        with self.assertRaisesRegex(ValueError, "run identity"):
            self.publish_fixture()

    def test_rejects_wrong_domain_parent(self) -> None:
        """Canonical domain parents must match the fixed scientific definition."""
        self.mutate("transformation.json", lambda record: record["domains"][0].update(parents=["query-calls"]))
        with self.assertRaisesRegex(ValueError, "domain lineage"):
            self.publish_fixture()

    def test_rejects_invented_domain_summary(self) -> None:
        """Recorded evaluated bases are checked against actual interval bytes."""
        self.mutate("transformation.json", lambda record: record["domains"][0].update(bases=999))
        with self.assertRaisesRegex(ValueError, "domain lineage"):
            self.publish_fixture()

    def test_rejects_changed_domain_even_with_new_hash(self) -> None:
        """A self-consistent hash cannot redefine the approved evaluation domain."""
        path = self.stage / "references/domains/R_eval_full.bed"
        path.write_bytes(b"chr20\t10\t35\n")
        self.mutate("transformation.json", lambda record: next(item for item in record["domains"]
                    if item["artifact_id"] == "R_eval_full").update(sha256=checksum(path)))
        with self.assertRaisesRegex(ValueError, "domain lineage"):
            self.publish_fixture()

    def test_rejects_reference_substitution(self) -> None:
        """Prepared FASTA must be exactly derived from the acquired compression."""
        path = self.stage / "references/ref.fa"
        path.write_bytes(b">chr20\n" + b"N" * 400 + b"\n")
        self.mutate("transformation.json", lambda record: record["reference"][0].update(sha256=checksum(path)))
        with self.assertRaisesRegex(ValueError, "not derived"):
            self.publish_fixture()

    def test_rejects_symlink_source(self) -> None:
        """Even links to identical bytes cannot cross the publication boundary."""
        path = self.stage / "references/domains/T_design.bed"
        target = self.base / "outside.bed"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.publish_fixture()

    def test_rejects_symlink_destination_parent(self) -> None:
        """Pre-existing destination links cannot redirect durable publication."""
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        (self.drive / "m2_data_provenance").symlink_to(elsewhere)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.publish_fixture()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_retry_rejects_corrupt_durable_bytes(self) -> None:
        """Marker existence cannot conceal corruption on a completed retry."""
        path, _ = self.publish_fixture()
        (path / "prepared/references/domains/T_design.bed").write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "rehash failed"):
            self.publish_fixture()

    def test_retry_rejects_marker_lineage_change(self) -> None:
        """Completion marker must bind the exact manifest and registry hashes."""
        path, _ = self.publish_fixture()
        marker = json.loads((path / "COMPLETED.json").read_text())
        marker["manifest_sha256"] = "a" * 64
        self.write_json(path / "COMPLETED.json", marker)
        with self.assertRaisesRegex(ValueError, "marker lineage"):
            self.publish_fixture()

    def test_retry_rejects_registry_conflict(self) -> None:
        """Completed retry cannot silently accept an altered append-only registry."""
        self.publish_fixture()
        registry = self.drive / "m2_data_provenance/registry/runs/test-run.json"
        content = registry.read_bytes()
        self.write_json(registry, {"run_id": "other"})
        with self.assertRaisesRegex(ValueError, "registry conflict"):
            self.publish_fixture()
        self.assertNotEqual(content, registry.read_bytes())

    def test_rejects_existing_registry_before_promotion(self) -> None:
        """Registry collisions fail before any completed-directory mutation."""
        registry = self.drive / "m2_data_provenance/registry/runs/test-run.json"
        registry.parent.mkdir(parents=True)
        registry.write_text("immutable prior record\n")
        with self.assertRaisesRegex(FileExistsError, "registry conflict"):
            self.publish_fixture()
        self.assertEqual(registry.read_text(), "immutable prior record\n")
        self.assertFalse((self.drive / "m2_data_provenance/runs/completed/test-run").exists())

    def test_completion_marker_is_last_and_interrupted_retry_recovers(self) -> None:
        """An interrupted final-marker write leaves no success claim and resumes."""
        from giab_wes_nextflow import publication
        original = publication._write_exclusive
        writes: list[str] = []

        def interrupted(path: Path, record: dict[str, Any]) -> None:
            """Observe control-file ordering and simulate a pre-marker failure."""
            writes.append(path.name)
            if path.name == "COMPLETED.json":
                self.assertTrue((self.drive / "m2_data_provenance/registry/runs/test-run.json").is_file())
                raise OSError("simulated interruption")
            original(path, record)

        with patch.object(publication, "_write_exclusive", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "simulated interruption"):
                self.publish_fixture()
        completed = self.drive / "m2_data_provenance/runs/completed/test-run"
        self.assertFalse((completed / "COMPLETED.json").exists())
        self.assertEqual(writes[-1], "COMPLETED.json")
        self.assertTrue(self.publish_fixture()[1])
        self.assertFalse(self.publish_fixture()[1])

    def test_rejects_false_fai_offset_with_matching_lengths(self) -> None:
        """FAI coordinates must describe actual FASTA bytes, not just lengths."""
        index = self.stage / "references/ref.fa.fai"
        index.write_bytes(b"chr20\t400\t999\t400\t401\n")
        self.mutate("transformation.json", lambda record: next(item for item in record["reference"]
                    if item["id"] == "grch38_fai").update(sha256=checksum(index)))
        with self.assertRaisesRegex(ValueError, "index coordinates"):
            self.publish_fixture()

    def test_rejects_unrecognized_transformation_field(self) -> None:
        """Unexpected transformation fields cannot smuggle unreviewed lineage."""
        self.mutate("transformation.json", lambda record: record.update(query_derived_domain=True))
        with self.assertRaisesRegex(ValueError, "transformation validation failed"):
            self.publish_fixture()

    def test_rejects_domain_path_traversal(self) -> None:
        """Domain paths are canonical artifact names, never arbitrary paths."""
        self.mutate("transformation.json", lambda record: record["domains"][0].update(path="../T_design.bed"))
        with self.assertRaisesRegex(ValueError, "domain path"):
            self.publish_fixture()

    def test_rejects_inferred_target_with_true_permission(self) -> None:
        """A boolean permission cannot override an unresolved identity decision."""
        decision = json.loads(self.decision.read_text())
        decision["classification"] = "inferred"
        self.write_json(self.decision, decision)
        with self.assertRaisesRegex(ValueError, "Gate B blocked"):
            self.publish_fixture()

    def test_unexpected_incomplete_bytes_are_preserved(self) -> None:
        """Recovery never deletes unexplained pre-existing staging data."""
        incomplete = self.drive / "m2_data_provenance/runs/_incomplete/test-run"
        incomplete.mkdir(parents=True)
        (incomplete / "unknown.txt").write_text("retain for audit")
        with self.assertRaisesRegex(ValueError, "unexpected incomplete"):
            self.publish_fixture()
        self.assertEqual((incomplete / "unknown.txt").read_text(), "retain for audit")

    def test_retry_rejects_added_durable_artifact(self) -> None:
        """Completion inventories are exhaustive, not lists of optional files."""
        completed, _ = self.publish_fixture()
        (completed / "untracked.txt").write_text("extra")
        with self.assertRaisesRegex(ValueError, "unexpected or missing"):
            self.publish_fixture()

    def test_retry_rejects_durable_symlink(self) -> None:
        """A completed marker cannot legitimize a subsequently replaced link."""
        completed, _ = self.publish_fixture()
        path = completed / "prepared/references/domains/T_design.bed"
        path.unlink()
        path.symlink_to(self.stage / "references/domains/T_design.bed")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.publish_fixture()


if __name__ == "__main__":
    unittest.main()

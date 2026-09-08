"""Verify immutable evidence, missingness and the public prototype HTTP boundary."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pipeline_evidence_explorer import model
from pipeline_evidence_explorer.app import DEFAULT_PREFIX, create_app


class ExplorerTests(unittest.TestCase):
    """Exercise actual loaders, Flask endpoints and the registered Dash callback."""

    def test_observations_and_missing_metrics(self) -> None:
        data = model.load_snapshot()
        self.assertEqual((data.primary_reads, data.mapped_reads, data.unmapped_reads), (48, 44, 4))
        self.assertEqual((data.completed_tasks, data.cached_tasks), (22, 22))
        public = json.loads(data.public_json)
        self.assertIsNone(public["benchmark_metrics"])
        self.assertIsNone(public["comparative_cost"])
        self.assertFalse(public["canonical"])
        self.assertEqual(public["m4"]["status"], "passed")
        self.assertEqual(public["m4"]["run_id"], 34237377774)
        self.assertTrue(public["m4"]["execution_scope"]["both_and_resume_accepted"])
        self.assertEqual(public["m4"]["deepvariant_inference"]["call_variants_record_count"], 2)
        self.assertEqual(public["m4_historical_attempt"]["status"], "failed")
        self.assertEqual(public["m4_historical_attempt"]["run_id"], 34202569517)
        self.assertIsNone(public["m4"]["evidence_limits"]["raw_native_call_rows"])
        self.assertEqual(len(model.select_tasks(data, "all")), 22)
        self.assertEqual(len(model.select_tasks(data, data.tasks[0].name)), 1)
        with self.assertRaises(ValueError):
            model.select_tasks(data, "../../secret")

    def test_corruption_and_links_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "data"
            shutil.copytree(Path(model.__file__).parent / "data", root)
            file = root / "m3-proof.json"
            original = file.read_bytes()
            file.write_bytes(original + b" ")
            with self.assertRaisesRegex(ValueError, "hash"):
                model.load_snapshot(root)
            file.unlink()
            real = Path(tmp).resolve() / "original.json"
            real.write_bytes(original)
            file.symlink_to(real)
            with self.assertRaisesRegex(ValueError, "linked"):
                model.load_snapshot(root)

    def test_http_layout_callback_and_fixed_download(self) -> None:
        app = create_app()
        client = app.server.test_client()
        for route in ("", "healthz", "readyz", "_dash-layout", "_dash-dependencies", "evidence.json"):
            response = client.get(DEFAULT_PREFIX + route)
            self.assertEqual(response.status_code, 200, route)
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertFalse(client.get(DEFAULT_PREFIX + "readyz").json["canonical"])
        layout = client.get(DEFAULT_PREFIX + "_dash-layout").get_data(as_text=True)
        self.assertIn("Independent callers, both-mode and final resume passed on main", layout)
        self.assertNotIn("Native-call gate failed", layout)
        payload = client.get(DEFAULT_PREFIX + "evidence.json").json
        self.assertEqual(payload["scope"], "synthetic_prototype")
        data = model.load_snapshot()
        response = client.post(DEFAULT_PREFIX + "_dash-update-component", json={
            "output": "task-table.children", "outputs": {"id": "task-table", "property": "children"},
            "inputs": [{"id": "process", "property": "value", "value": data.tasks[0].name}],
            "state": [], "changedPropIds": ["process.value"]})
        self.assertEqual(response.status_code, 200)
        self.assertIn(data.tasks[0].task_hash, json.dumps(response.json))

    def test_invalid_bundle_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(bundle_dir=Path(tmp))
            client = app.server.test_client()
            self.assertEqual(client.get(DEFAULT_PREFIX + "healthz").status_code, 200)
            self.assertEqual(client.get(DEFAULT_PREFIX + "readyz").status_code, 503)
            self.assertEqual(client.get(DEFAULT_PREFIX + "evidence.json").status_code, 503)
            self.assertNotIn(tmp, client.get(DEFAULT_PREFIX + "_dash-layout").get_data(as_text=True))

    def test_prefix_validation(self) -> None:
        for value in ("//evil.test/", "/../", "/bad?name/"):
            with self.assertRaises(ValueError):
                create_app(prefix=value)


if __name__ == "__main__":
    unittest.main()

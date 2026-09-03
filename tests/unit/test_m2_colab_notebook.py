import ast
import json
import unittest
from pathlib import Path


class M2ColabNotebookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        cls.notebook = json.loads((root / "notebooks/m2_colab_acquisition.ipynb").read_text())
        cls.code = "\n".join(
            "".join(cell.get("source", []))
            for cell in cls.notebook["cells"]
            if cell["cell_type"] == "code"
        )

    def test_notebook_has_no_stored_outputs(self):
        self.assertTrue(all(not cell.get("outputs") for cell in self.notebook["cells"]))

    def test_every_subprocess_run_is_fail_closed(self):
        tree = ast.parse(self.code)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "run"
        ]
        self.assertGreater(len(calls), 0)
        for call in calls:
            check = next((kw.value for kw in call.keywords if kw.arg == "check"), None)
            self.assertIsInstance(check, ast.Constant)
            self.assertIs(check.value, True)

    def test_gate_controls_domain_preparation_and_publication(self):
        self.assertIn("gate['classification']=='confirmed'", self.code)
        self.assertIn("--target-bed", self.code)
        self.assertIn("publish_m2_workspace.py", self.code)
        self.assertIn("Gate B BLOCKED", self.code)


if __name__ == "__main__":
    unittest.main()

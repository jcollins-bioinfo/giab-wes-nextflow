"""Validate the exact-SHA thin launcher without authenticating Colab or Drive."""
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


class CanonicalNotebookTests(unittest.TestCase):
    def test_reviewed_launcher_cells_compile_and_have_no_saved_execution(self):
        source = Path(__file__).resolve().parents[2] / 'scripts/build_canonical_notebook.py'
        spec = importlib.util.spec_from_file_location('canonical_notebook', source)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'launcher.ipynb'
            module.build('a' * 40, output)
            notebook = json.loads(output.read_text()); code = []
            for cell in notebook['cells']:
                if cell['cell_type'] == 'code':
                    text = ''.join(cell['source']); ast.parse(text); code.append(text)
                    self.assertIsNone(cell['execution_count']); self.assertEqual(cell['outputs'], [])
            joined = '\n'.join(code)
            self.assertIn('ALLOW_LARGE_DOWNLOADS = True', joined)
            self.assertIn('giab_wes_nextflow.canonical_run', joined)
            self.assertIn('NEW_CHECKOUT', joined)
            self.assertNotIn('bwa mem', joined)
            with self.assertRaisesRegex(ValueError, 'SHA'):
                module.build('main', output)


if __name__ == '__main__':
    unittest.main()

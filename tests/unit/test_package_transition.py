"""Protect package ownership, current version consistency and launch ordering."""
import ast
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

from giab_wes_nextflow import __version__

ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = {
    "acquire_m2.py": "giab_wes_nextflow.acquisition",
    "prepare_m2.py": "giab_wes_nextflow.preparation",
    "validate_m2.py": "giab_wes_nextflow.validation",
    "publish_m2_workspace.py": "giab_wes_nextflow.publication",
    "mirror_m2.py": "giab_wes_nextflow.mirror",
}

class PackageTransitionTest(unittest.TestCase):
    def test_wrappers_are_thin_and_delegate_to_package_main(self) -> None:
        """Require algorithm-free compatibility wrappers to delegate to the installed package."""
        for filename, module in WRAPPERS.items():
            path=ROOT/'scripts'/filename; tree=ast.parse(path.read_text())
            functions=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
            self.assertEqual(functions,[],filename)
            spec=importlib.util.spec_from_file_location('wrapper_'+filename[:-3],path)
            wrapper=importlib.util.module_from_spec(spec);spec.loader.exec_module(wrapper)
            self.assertIs(wrapper.main,__import__(module,fromlist=['main']).main)
    def test_version_is_consistent(self) -> None:
        """Bind active package, Nextflow and manifest versions to this milestone."""
        self.assertEqual(__version__,'0.4.0-dev.1')
        self.assertIn("version = '0.4.0-dev.1'",(ROOT/'nextflow.config').read_text())
        self.assertEqual(json.loads((ROOT/'config/m2-resources.json').read_text())['project_version'],__version__)
    def test_launcher_orders_fixture_before_samplesheet_validation(self) -> None:
        """Generate synthetic files before validating the samplesheet and retain exact code identity."""
        text=(ROOT/'scripts/run_m2_readiness.sh').read_text()
        self.assertLess(text.index('tests/data/generate_fixture.py'),text.index('scripts/check_samplesheets.py'))
        self.assertNotIn('publish-m2',text);self.assertNotIn('work/drive',text.lower())
        self.assertIn('/content/m2-stage',text);self.assertIn('--repository-sha "$RESOLVED_SHA"',text)
    def test_import_from_outside_checkout(self) -> None:
        """Verify the installed package remains importable outside repository working paths."""
        result=subprocess.run([sys.executable,'-c','import giab_wes_nextflow; print(giab_wes_nextflow.__version__)'],cwd='/tmp',text=True,capture_output=True,check=True)
        self.assertEqual(result.stdout.strip(),__version__)

if __name__ == '__main__': unittest.main()

"""Exercise canonical UI readiness, export and view callbacks using test metadata."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from pipeline_evidence_explorer.app import DEFAULT_PREFIX, create_app
from giab_wes_nextflow.canonical_results import write_public_bundle

SPEC = importlib.util.spec_from_file_location('canonical_model_test_fixture', Path(__file__).resolve().parents[2]/'tests/unit/test_canonical_results.py')
assert SPEC is not None and SPEC.loader is not None
FIXTURE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(FIXTURE)


class CanonicalViewTests(unittest.TestCase):
    """Verify no unavailable result can silently become canonical UI evidence."""
    def test_unavailable_is_explicit(self) -> None:
        client=create_app().server.test_client()
        self.assertEqual(client.get(DEFAULT_PREFIX+'canonical/readyz').status_code,503)
        self.assertIn('Canonical results unavailable',client.get(DEFAULT_PREFIX+'_dash-layout').get_data(as_text=True))
        self.assertEqual(client.get(DEFAULT_PREFIX+'canonical/metrics.tsv').status_code,503)
        public=client.get(DEFAULT_PREFIX+'evidence.json').json
        self.assertEqual(public['m5_synthetic']['status'],'synthetically_verified')
        self.assertIsNone(public['benchmark_metrics'])

    def test_validated_result_downloads_and_callback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp).resolve()/'bundle';record,receipts=FIXTURE.example_result()
            pin=write_public_bundle(directory,record,receipts)
            app=create_app(canonical_dir=directory,canonical_manifest_sha256=pin);client=app.server.test_client()
            self.assertTrue(client.get(DEFAULT_PREFIX+'canonical/readyz').json['canonical'])
            self.assertEqual(client.get(DEFAULT_PREFIX+'canonical/evidence.json').json['scope'],'hg001_chr20_22_coding')
            self.assertIn('tp_query\ttp_truth',client.get(DEFAULT_PREFIX+'canonical/metrics.tsv').get_data(as_text=True))
            self.assertEqual(client.get(DEFAULT_PREFIX+'canonical/unknown.json').status_code,404)
            layout=client.get(DEFAULT_PREFIX+'_dash-layout').get_data(as_text=True)
            self.assertIn('HG001 chr20',layout);self.assertIn('1905809',json.dumps(record))
            key=next(k for k in app.callback_map if 'canonical-panel.style' in k)
            response=client.post(DEFAULT_PREFIX+'_dash-update-component',json={
                'output':key,'outputs':[{'id':name+'-panel','property':'style'} for name in ('overview','execution','provenance','canonical')],
                'inputs':[{'id':'view','property':'value','value':'canonical'}],'state':[],'changedPropIds':['view.value']})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['response']['canonical-panel']['style'],{'display':'block'})
            self.assertEqual(client.get(DEFAULT_PREFIX+'canonical/evidence.json').headers['Cache-Control'],'no-store')

    def test_replaced_pin_fails_without_leaking_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp).resolve()/'bundle';record,receipts=FIXTURE.example_result()
            write_public_bundle(directory,record,receipts)
            client=create_app(canonical_dir=directory,canonical_manifest_sha256='0'*64).server.test_client()
            self.assertEqual(client.get(DEFAULT_PREFIX+'canonical/readyz').status_code,503)
            self.assertNotIn(temp,client.get(DEFAULT_PREFIX+'_dash-layout').get_data(as_text=True))


if __name__=='__main__':unittest.main()

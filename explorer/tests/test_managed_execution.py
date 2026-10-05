"""Validate real sanitized metadata, temporal semantics and public UI boundaries."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline_evidence_explorer import execution
from pipeline_evidence_explorer.app import DEFAULT_PREFIX, create_app


class ManagedExecutionTests(unittest.TestCase):
    def test_accepted_metadata_and_missingness(self):
        data = execution.load_managed()
        self.assertEqual((len(data.timeline), data.record['native_observation_count']), (28, 23))
        self.assertEqual(data.record['elapsed_seconds'], 1346.630810)
        self.assertFalse(data.record['canonical'])
        self.assertFalse(data.record['managed_cache_qualified'])
        self.assertTrue(all(task['cpu_seconds'] is None and task['peak_rss_bytes'] is None for task in data.record['tasks']))
        self.assertEqual(sum(task['native_seconds'] is not None for task in data.record['tasks']), 22)
        self.assertEqual(sum(task['attempt'] is None for task in data.record['tasks']), 5)
        self.assertNotIn('arn:', data.public_json)
        self.assertNotIn('s3://', data.public_json)
        self.assertNotIn('amazonaws.com', data.public_json)
        self.assertNotIn('provider_task_id', data.public_json)
        self.assertNotIn('run_id', data.public_json)
        self.assertNotIn('command.sh', data.public_json)

    def test_timeline_preserves_overlap_and_distinct_intervals(self):
        data = execution.load_managed()
        row = next(row for row in data.timeline if row.key == 'CLOUD_DEEPVARIANT_CALL:1:1')
        task = next(task for task in data.record['tasks'] if task['key'] == row.key)
        self.assertAlmostEqual(row.provider_seconds, task['stop_seconds'] - task['start_seconds'])
        self.assertAlmostEqual(row.staging_seconds, task['start_seconds'] - task['created_seconds'])
        self.assertNotEqual(sum(row.provider_seconds for row in data.timeline), data.record['elapsed_seconds'])
        self.assertTrue(any(a.start < b.start < a.start + a.provider_seconds for a in data.timeline for b in data.timeline))

    def test_private_fields_and_unsupported_claims_rejected(self):
        original = execution.load_managed().record
        changes = [lambda x: x.update(canonical=True), lambda x: x.update(managed_cache_qualified=True),
                   lambda x: x.update(account_id='private'),
                   lambda x: x.update(engine='25.04.8'), lambda x: x.update(parser='v1'),
                   lambda x: x.update(observed_date='2026-02-30'),
                   lambda x: x.update(elapsed_seconds=float('inf')),
                   lambda x: x.update(submission_to_start_seconds=True),
                   lambda x: x['tasks'][0].update(cpu_seconds=float('inf')),
                   lambda x: x['tasks'][0].update(peak_rss_bytes=float('nan')),
                   lambda x: x['tasks'][0].update(start_seconds=True),
                   lambda x: x['tasks'][0].update(provider_task_id='private'),
                   lambda x: x['tasks'][0].update(start_seconds=-1),
                   lambda x: x['tasks'][0].update(image_digest='untrusted:latest'),
                   lambda x: x['tasks'][0].update(key='arbitrary'),
                   lambda x: x['tasks'][0]['outputs'].append({'sha256': 'a'*64, 'bytes': 1, 'path': 'private'})]
        for mutate in changes:
            record = deepcopy(original); mutate(record)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                execution.validate_managed(record)

    def test_hash_corruption_and_symlinks_fail_closed(self):
        raw = (Path(execution.__file__).parent/'data/managed-execution.json').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp).resolve()/'execution.json'; file.write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError, 'identity'):
                execution.load_managed(file)
            file.write_bytes(raw)
            link = file.parent/'link.json'; link.symlink_to(file)
            with self.assertRaisesRegex(ValueError, 'linked'):
                execution.load_managed(link)

    def test_projection_refuses_an_unaccepted_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve()/'receipt.json'; path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'identity'):
                execution.project_managed_receipts(path, path, path)

    def test_download_and_task_selection_callback(self):
        app = create_app(); client = app.server.test_client()
        status = client.get(DEFAULT_PREFIX+'managed/readyz')
        self.assertEqual(status.status_code, 200); self.assertFalse(status.json['canonical'])
        exported = client.get(DEFAULT_PREFIX+'managed/evidence.json')
        self.assertEqual(hashlib.sha256(exported.data).hexdigest(), execution.MANAGED_SHA256)
        self.assertEqual(client.get(DEFAULT_PREFIX+'canonical/readyz').status_code, 503)
        output = next(key for key in app.callback_map if 'managed-task-detail.children' in key)
        payload = {'output': output, 'outputs': [{'id': 'managed-timeline', 'property': 'figure'}, {'id': 'managed-task-detail', 'property': 'children'}],
                   'inputs': [{'id': 'managed-task', 'property': 'value', 'value': 'CLOUD_DEEPVARIANT_CALL:1:1'}], 'state': [], 'changedPropIds': ['managed-task.value']}
        response = client.post(DEFAULT_PREFIX+'_dash-update-component', json=payload)
        self.assertEqual(response.status_code, 200)
        text = json.dumps(response.json)
        self.assertIn('Requested vCPUs', text); self.assertIn('Unavailable: not observed', text)
        self.assertIn('sha256:962e5a83', text)
        figure = response.json['response']['managed-timeline']['figure']
        self.assertEqual(len(figure['data'][0]['y']), 1)
        for invalid in ('../../private', [], {}, None):
            payload['inputs'][0]['value'] = invalid
            response = client.post(DEFAULT_PREFIX+'_dash-update-component', json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertIn('Choose a managed task', json.dumps(response.json))

    def test_invalid_managed_bundle_preserves_human_missingness(self):
        with patch('pipeline_evidence_explorer.app.load_managed', side_effect=ValueError('private path')):
            client = create_app().server.test_client()
        self.assertEqual(client.get(DEFAULT_PREFIX+'managed/readyz').status_code, 503)
        self.assertEqual(client.get(DEFAULT_PREFIX+'managed/evidence.json').status_code, 503)
        self.assertEqual(client.get(DEFAULT_PREFIX+'canonical/readyz').status_code, 503)
        self.assertNotIn('private path', client.get(DEFAULT_PREFIX+'_dash-layout').get_data(as_text=True))

class InfrastructureSnapshotTests(unittest.TestCase):
    def test_source_bound_declarations_do_not_claim_apply(self):
        from pipeline_evidence_explorer.infrastructure import load_infrastructure
        record = load_infrastructure()
        self.assertEqual(record['evidence_state'], 'declared')
        self.assertTrue(all(node['state'] == 'declared' for node in record['components']))
        root = Path(__file__).resolve().parents[2]
        for source in record['source_files']:
            self.assertEqual(hashlib.sha256((root/source['path']).read_bytes()).hexdigest(), source['sha256'])
        client = create_app().server.test_client()
        exported = client.get(DEFAULT_PREFIX+'infrastructure/evidence.json')
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json, record)
        layout = client.get(DEFAULT_PREFIX+'_dash-layout').get_data(as_text=True)
        self.assertIn('NO LIVE RESOURCE CLAIM', layout)
        self.assertIn('Nextflow schedules scientific processes', layout)

    def test_live_state_or_private_fields_are_rejected(self):
        from pipeline_evidence_explorer.infrastructure import load_infrastructure, validate_infrastructure
        for change in (lambda x: x.update(evidence_state='live-verified'),
                       lambda x: x['components'][0].update(state='applied'),
                       lambda x: x.update(account_id='private'),
                       lambda x: x['relationships'][0].update(to='unknown'),
                       lambda x: x['components'][0].update(purpose='s3://private-data')):
            record=deepcopy(load_infrastructure()); change(record)
            with self.assertRaises(ValueError): validate_infrastructure(record)


if __name__ == '__main__':
    unittest.main()

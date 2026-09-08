"""Resource arithmetic, attribution and missingness gates without caller-cost claims."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, ValidationError

from giab_wes_nextflow.m5_resources import TRACE_UNITS, build_report, main, parse_trace, validate_report

ROOT = Path(__file__).resolve().parents[2]
HEADERS = ['task_id', 'hash', 'name', 'status', 'exit', 'attempt', 'duration', 'realtime', '%cpu', 'peak_rss', 'peak_vmem', 'cpus', 'memory']


def row(task_id: int = 1, process: str = 'M4_HAPLOTYPECALLER', **changes: str) -> dict[str, str]:
    """Provide deterministic artificial trace numbers for arithmetic tests only."""
    result = dict(zip(HEADERS, [str(task_id), f'aa/{task_id:06d}', f'W:{process} (gatk:SYNTHETIC01)', 'COMPLETED', '0', '1', '4000000', '3600000', '200', '1024', '4096', '4', '8192']))
    result.update(changes)
    return result


def trace(*rows: dict[str, str]) -> str:
    """Serialize known fields as a raw tab-delimited Nextflow trace."""
    return '\t'.join(HEADERS) + '\n' + ''.join('\t'.join(item[field] for field in HEADERS) + '\n' for item in rows)


def runtime() -> dict:
    """Keep metadata explicitly unknown where no host observation was taken."""
    return {key: {'value': None, 'reason': 'not observed in this synthetic test'}
            for key in ('architecture', 'accelerator', 'input_bytes', 'evaluated_bases')}


class ResourceEvidenceTests(unittest.TestCase):
    """Exercise complete and partial evidence independently of workflow execution."""

    def report(self, *rows: dict[str, str], **kwargs: object) -> dict:
        """Build and validate one temporary resource report."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.tsv'
            path.write_text(trace(*rows))
            return build_report(path, runtime=runtime(), trace_units=TRACE_UNITS, **kwargs)

    def test_cpu_estimate_and_memory_maximum_are_correct(self) -> None:
        """Utilization already includes CPUs; task memory maxima must not be added."""
        report = self.report(row(), row(2, peak_rss='2048'), observed_wall_seconds=4000)
        summary = report['end_to_end']['executed_attempts']
        self.assertEqual(summary['summed_cpu_hours_estimated']['value'], 4)
        self.assertIsNone(summary['summed_cpu_hours_measured']['value'])
        self.assertEqual(summary['summed_task_duration_seconds']['value'], 8000)
        self.assertEqual(report['elapsed_wall_seconds']['value'], 4000)
        self.assertEqual(summary['max_task_peak_rss_bytes']['value'], 2048)
        self.assertEqual(summary['max_task_peak_vmem_bytes']['value'], 4096)

    def test_groups_and_tags_are_unambiguous(self) -> None:
        """Caller-tag colons cannot override the settled process-name identity."""
        report = self.report(row(1, 'M3_ALIGN'), row(2), row(3, 'M4_DEEPVARIANT'), row(4, 'M5_NORMALIZE'), row(5, 'M5_BENCHMARK'), row(6, 'M4_BUNDLE'), row(7, 'M4_COLLECT_GATK'), row(8, 'M4_COLLECT_DEEPVARIANT'), row(9, 'M4_PREPARE_INPUTS'))
        self.assertEqual([group['task_attempt_count'] for group in report['groups'].values()], [2, 2, 2, 3])
        self.assertEqual(report['tasks'][6]['process'], 'M4_COLLECT_GATK')

    def test_cached_and_executed_work_never_share_a_total(self) -> None:
        """A missing cached observation cannot become zero work in the current run."""
        report = self.report(row(), row(2, status='CACHED', realtime='-', peak_rss='-'))
        summary = report['end_to_end']
        self.assertEqual(summary['executed_attempts']['summed_cpu_hours_estimated']['value'], 2)
        self.assertIsNone(summary['cached_prior_attempts']['summed_cpu_hours_estimated']['value'])
        self.assertIsNotNone(summary['cached_prior_attempts']['summed_cpu_hours_estimated']['reason'])
        cached = self.report(row(status='CACHED'))
        self.assertIsNone(cached['end_to_end']['executed_attempts']['summed_cpu_hours_estimated']['value'])
        self.assertEqual(cached['end_to_end']['cached_prior_attempts']['summed_cpu_hours_estimated']['value'], 2)

    def test_failed_retry_attempts_count_as_work(self) -> None:
        """A successful retry cannot erase an earlier failed attempt's consumption."""
        report = self.report(row(status='FAILED', exit='1'), row(attempt='2'))
        self.assertEqual(report['end_to_end']['status_counts']['FAILED'], 1)
        self.assertEqual(report['end_to_end']['executed_attempts']['summed_cpu_hours_estimated']['value'], 4)

    def test_missing_and_zero_resolution_remain_explicit(self) -> None:
        """Unavailable and zero-resolution runtime cannot produce a free-work claim."""
        report = self.report(row(realtime='0', memory='-', attempt='-'))
        self.assertIsNone(report['tasks'][0]['metrics']['cpu_hours_estimated']['value'])
        self.assertIsNone(report['tasks'][0]['metrics']['requested_memory_bytes']['value'])
        self.assertIsNone(report['tasks'][0]['attempt']['value'])
        self.assertIsNone(report['elapsed_wall_seconds']['value'])

    def test_malformed_negative_and_human_units_fail_closed(self) -> None:
        """Reject mixed units, malformed values, infinities and invalid task states."""
        for field, value in [('duration', '-1'), ('realtime', '2s'), ('memory', '1 GB'), ('peak_rss', '1.5'), ('cpus', '0'), ('cpus', '1.5'), ('%cpu', 'NaN'), ('%cpu', 'inf'), ('%cpu', '1e2'), ('attempt', '0'), ('attempt', '1.5'), ('status', 'RUNNING'), ('status', 'unknown'), ('task_id', '-1'), ('exit', '1')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.report(row(**{field: value}))
        with self.assertRaises(ValueError):
            parse_trace(trace(row()), trace_units='human')

    def test_unknown_and_ambiguous_process_names_rejected(self) -> None:
        """Unknown tasks require an explicit attribution policy before accounting."""
        for name in ['W:OTHER (gatk:SYNTHETIC01)', 'W:M4_HAPLOTYPECALLER (broken', 'W:M4_HAPLOTYPECALLER trailing']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.report(row(name=name))

    def test_duplicate_attempt_and_malformed_table_rejected(self) -> None:
        """Do not double count duplicates or accept truncated/extra-field rows."""
        for text in [trace(row(), row()), trace(row(attempt='-'), row(attempt='2')), trace(row()).replace('hash\t', 'task_id\t', 1), trace(row()) + '1\textra\n', trace(row()).rstrip('\n') + '\textra\n', '\t'.join(HEADERS) + '\n']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_trace(text, trace_units=TRACE_UNITS)

    def test_wall_clock_requires_consistent_external_evidence(self) -> None:
        """Timezone-aware invocation boundaries are separate from task durations."""
        report = self.report(row(), started_at='2026-09-08T10:00:00+00:00', ended_at='2026-09-08T10:01:00+00:00')
        self.assertEqual(report['elapsed_wall_seconds']['value'], 60)
        for kwargs in [{'observed_wall_seconds': -1}, {'observed_wall_seconds': float('nan')}, {'started_at': '2026-09-08T10:00:00'}, {'started_at': '2026-09-08T10:00:00', 'ended_at': '2026-09-08T10:01:00'}, {'started_at': '2026-09-08T10:01:00+00:00', 'ended_at': '2026-09-08T10:00:00+00:00'}, {'observed_wall_seconds': 0, 'started_at': '2026-09-08T10:01:00+00:00'}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.report(row(), **kwargs)

    def test_schemas_synchronized_and_schema_rejects_missing_runtime(self) -> None:
        """Installed and checkout schemas agree and enforce unknownable metadata."""
        primary = ROOT / 'schemas/m5-resources.schema.json'
        packaged = ROOT / 'src/giab_wes_nextflow/data/schemas/m5-resources.schema.json'
        self.assertEqual(primary.read_bytes(), packaged.read_bytes())
        Draft202012Validator.check_schema(json.loads(primary.read_text()))
        report = self.report(row())
        del report['runtime']['architecture']
        with self.assertRaises(ValidationError):
            validate_report(report)
        report = self.report(row())
        report['runtime']['architecture']['reason'] = None
        with self.assertRaises(ValidationError):
            validate_report(report)

    def test_report_arithmetic_and_attribution_tampering_rejected(self) -> None:
        """Schema-valid arithmetic edits must not bypass the tested Python model."""
        original = self.report(row())
        for mutate in [lambda data: data['end_to_end']['executed_attempts']['summed_cpu_hours_estimated'].update(value=9), lambda data: data['tasks'][0].update(group='shared_preprocessing'), lambda data: data['tasks'][0]['metrics']['cpu_hours_estimated'].update(value=8), lambda data: data['tasks'][0].update(cached=True)]:
            data = copy.deepcopy(original)
            mutate(data)
            with self.assertRaises(ValueError):
                validate_report(data)

    def test_real_existing_m3_traces_parse_without_invented_attempts(self) -> None:
        """Historical recorded M3 raw traces establish parser compatibility only."""
        for phase, status in [('first', 'COMPLETED'), ('resume', 'CACHED')]:
            report = build_report(ROOT / f'docs/orchestration/evidence/m3-synthetic-ci-34103737524/{phase}.trace.tsv', runtime=runtime(), trace_units=TRACE_UNITS)
            self.assertEqual(len(report['tasks']), 22)
            self.assertEqual(report['end_to_end']['status_counts'][status], 22)
            self.assertTrue(all(task['attempt']['value'] is None for task in report['tasks']))

    def test_output_order_is_deterministic_and_cli_is_package_owned(self) -> None:
        """The package CLI writes the same validated bytes on repeated collection."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'trace.tsv').write_text(trace(row(2), row(1)))
            (root / 'runtime.json').write_text(json.dumps(runtime()))
            args = ['--trace', str(root / 'trace.tsv'), '--trace-units', TRACE_UNITS, '--runtime-json', str(root / 'runtime.json'), '--output', str(root / 'report.json')]
            self.assertEqual(main(args), 0)
            first = (root / 'report.json').read_bytes()
            self.assertEqual(main(args), 0)
            self.assertEqual(first, (root / 'report.json').read_bytes())
            self.assertEqual([task['task_id'] for task in json.loads(first)['tasks']], [1, 2])


if __name__ == '__main__':
    unittest.main()

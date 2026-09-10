"""A startup transport failure is retryable; evidence assertions are not."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'container_smoke', Path(__file__).resolve().parents[1] / 'container_smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class ContainerSmokeTests(unittest.TestCase):
    def test_startup_connection_reset_retries(self):
        with patch.object(smoke, 'check', side_effect=[ConnectionResetError(), None]) as check, \
                patch.object(smoke.time, 'sleep') as sleep, patch('sys.argv', ['smoke']):
            smoke.main()
        self.assertEqual(check.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_transport_retries_are_bounded(self):
        with patch.object(smoke, 'check', side_effect=ConnectionResetError()) as check, \
                patch.object(smoke.time, 'sleep'), patch('sys.argv', ['smoke']):
            with self.assertRaises(ConnectionResetError):
                smoke.main()
        self.assertEqual(check.call_count, 30)

    def test_invalid_evidence_fails_immediately(self):
        with patch.object(smoke, 'check', side_effect=AssertionError('bad evidence')) as check, \
                patch.object(smoke.time, 'sleep') as sleep, patch('sys.argv', ['smoke']):
            with self.assertRaises(AssertionError):
                smoke.main()
        check.assert_called_once()
        sleep.assert_not_called()

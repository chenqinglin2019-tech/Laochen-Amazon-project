"""Interpreter identity and pre-source guard failures, never live receipts."""
import subprocess
import sys
import unittest
from unittest.mock import patch

from run_browser_plan import run_process


class BrowserRuntimeBridgeTests(unittest.TestCase):
    def test_bridge_uses_current_interpreter(self):
        response = subprocess.CompletedProcess(['node'], 0, '{"status":"success"}', '')
        with patch('run_browser_plan.subprocess.run', return_value=response) as run:
            self.assertEqual(run_process(['node'])['status'], 'success')
        self.assertEqual(run.call_args.kwargs['env']['LC_IPR_PYTHON'], sys.executable)

    def test_authorization_failures_are_not_submitted(self):
        for code in ('SCENARIO_DISPATCH_INPUT_INVALID', 'SCENARIO_DISPATCH_TIMEOUT',
                     'SCENARIO_ACTION_STALE', 'DECISION_WORKFLOW_REVISION_UNSUPPORTED'):
            response = subprocess.CompletedProcess(['node'], 1, '', code + ': current action blocked')
            with self.subTest(code=code), patch('run_browser_plan.subprocess.run', return_value=response):
                result = run_process(['node'])
                self.assertEqual(result['error_code'], code)
                self.assertEqual(result['phase'], 'validate_plan')
                self.assertEqual(result['submission_state'], 'not_submitted')

    def test_unknown_generic_failure_is_not_reclassified(self):
        response = subprocess.CompletedProcess(['node'], 1, '', 'connection closed')
        with patch('run_browser_plan.subprocess.run', return_value=response):
            result = run_process(['node'])
        self.assertNotEqual(result.get('submission_state'), 'not_submitted')


if __name__ == '__main__':
    unittest.main()

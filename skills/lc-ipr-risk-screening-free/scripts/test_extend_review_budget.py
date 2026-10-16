"""The owner-only review allowance extension never resets a counter and refuses non-interactive use."""
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json
import execution_budget as budget
import extend_review_budget as tool


class ExtendReviewBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # A v1 task whose review allowance is spent, exactly like the run that stopped at 900.0 s.
        self.task = {'task_id': 'OFFLINE-EXTEND', 'execution_budget_revision': budget.REVISION,
                     'execution_budget': dict(budget.DEFAULTS)}
        atomic_write_json(self.root / 'task.json', self.task)
        atomic_write_json(self.root / 'evidence.json', {'task_id': self.task['task_id'], 'progress_events': []})
        limits = budget.policy(self.task)
        data = budget._read(self.root, self.task, limits)
        data.update(used_seconds=976.674, review_used_seconds=900.0, invocations=7, active=None)
        atomic_write_json(self.root / budget.JOURNAL, data)
        self.before = load_json(self.root / budget.JOURNAL)

    def run_cli(self, *, interactive, typed='', seconds=600, reason='five of six modules complete; one pass left'):
        errors = StringIO()
        with patch('sys.stderr', errors), patch('sys.stdout', new=StringIO()):
            code = tool.main(['--task-dir', str(self.root), '--add-seconds', str(seconds), '--reason', reason],
                             interactive=interactive, ask=lambda prompt: typed)
        return code, errors.getvalue()

    def test_non_interactive_use_is_refused_and_prints_the_owner_command(self):
        code, errors = self.run_cli(interactive=False)
        self.assertEqual(code, 2)
        self.assertIn('interactive terminal', errors)
        self.assertIn('--add-seconds 600', errors)
        self.assertEqual(load_json(self.root / budget.JOURNAL), self.before)

    def test_wrong_confirmation_changes_nothing(self):
        code, errors = self.run_cli(interactive=True, typed='yes')
        self.assertEqual(code, 1)
        self.assertEqual(load_json(self.root / budget.JOURNAL), self.before)

    def test_confirmed_extension_adds_allowance_and_keeps_every_counter(self):
        self.assertEqual(budget.snapshot(self.root)['review_remaining_seconds'], 0)
        code, _ = self.run_cli(interactive=True, typed='EXTEND OFFLINE-EXTEND 600')
        self.assertEqual(code, 0)
        data = load_json(self.root / budget.JOURNAL)
        for key in ('used_seconds', 'review_used_seconds', 'invocations', 'policy_sha256', 'revision', 'task_id'):
            self.assertEqual(data[key], self.before[key], key)
        row = data['review_extensions'][0]
        self.assertEqual((row['seconds'], row['actor']), (600, 'owner-terminal'))
        self.assertEqual(row['review_used_seconds_before'], 900.0)
        self.assertTrue(row['journal_sha256_before'])
        snapshot = budget.snapshot(self.root)
        self.assertEqual(snapshot['review_remaining_seconds'], 600)
        self.assertEqual(snapshot['review_extension_seconds'], 600)
        with budget.execution_budget(self.root, 'review') as deadline:
            self.assertIsNotNone(deadline)

    def test_limits_reason_and_active_lease_are_enforced(self):
        for seconds, code in ((30, 'SECONDS_OUT_OF_RANGE'), (1900, 'SECONDS_OUT_OF_RANGE')):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, code):
                tool.extend(self.root, seconds, 'a sufficiently long reason')
        with self.assertRaisesRegex(ValueError, 'REASON_REQUIRED'):
            tool.extend(self.root, 600, 'short')
        tool.extend(self.root, 1200, 'first bounded pass for the retained run')
        with self.assertRaisesRegex(ValueError, 'TOTAL_LIMIT_REACHED'):
            tool.extend(self.root, 700, 'second bounded pass for the retained run')
        for _ in range(2):
            tool.extend(self.root, 60, 'a further short bounded pass of one minute')
        with self.assertRaisesRegex(ValueError, 'RECORD_LIMIT_REACHED'):
            tool.extend(self.root, 60, 'a fourth record is never accepted')
        data = load_json(self.root / budget.JOURNAL)
        data['active'] = {'lease': 'x', 'started': 1.0, 'deadline': 2.0, 'phase': 'review', 'admitted_ids': []}
        data['review_extensions'] = []
        atomic_write_json(self.root / budget.JOURNAL, data)
        with self.assertRaisesRegex(ValueError, 'LEASE_ACTIVE'):
            tool.extend(self.root, 600, 'cannot extend while a lease is active')

    def test_task_without_budget_is_refused(self):
        atomic_write_json(self.root / 'task.json', {'task_id': 'LEGACY'})
        with self.assertRaisesRegex(ValueError, 'TASK_HAS_NO_BUDGET'):
            tool.extend(self.root, 600, 'a legacy task has no review allowance')


if __name__ == '__main__':
    unittest.main()

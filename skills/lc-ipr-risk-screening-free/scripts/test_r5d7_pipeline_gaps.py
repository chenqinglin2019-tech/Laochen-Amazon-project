"""r5d7: the readiness catch-up repeats while it changes something, a stale result review is redone without a new
dispatch, and a rewrite cancelled before submission no longer holds its parent open (B0GLNPC6K8 real run)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import sha256_json
import auto_refine
import run_pipeline as rp


def pipeline(root):
    return rp.Pipeline(rp.parser().parse_args(['--task-dir', str(root)]))


class ReadinessCatchUpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'run'
        self.root.mkdir()

    def run_readiness(self, changes):
        """``changes``: how many catch-up rounds change the progress signature before nothing changes."""
        subject = pipeline(self.root)
        rounds, signature = [], [0]

        def core_round(stage, robust, ran, number):
            rounds.append(number)
            if len(rounds) <= changes:
                signature[0] += 1
        gates = iter([{'ready': False}, {'ready': True}])
        with mock.patch.object(subject, 'robust', return_value=True), \
                mock.patch.object(subject, 'ready', side_effect=lambda: next(gates)), \
                mock.patch.object(subject, 'core_round', side_effect=core_round), \
                mock.patch.object(subject, 'progress_signature', side_effect=lambda: [signature[0]]), \
                mock.patch.object(subject, 'flush_sources', return_value=[]) as flush:
            result = subject.s_readiness()
        return result, rounds, flush

    def test_a_round_that_plans_new_work_is_followed_by_another(self):
        result, rounds, flush = self.run_readiness(changes=1)
        self.assertEqual(result, {'ready': True, 'catch_up': True})
        self.assertEqual(rounds, [1, 2])
        flush.assert_called_once()

    def test_the_catch_up_is_bounded(self):
        _, rounds, _ = self.run_readiness(changes=10)
        self.assertEqual(rounds, [1, 2, 3])

    def test_a_round_without_change_runs_once(self):
        _, rounds, _ = self.run_readiness(changes=0)
        self.assertEqual(rounds, [1])


class StaleResultReviewTests(unittest.TestCase):
    def test_result_review_runs_even_when_nothing_is_dispatched(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        subject = pipeline(Path(temp.name))
        commands = []

        def call(stage, command, **kwargs):
            commands.append([str(part) for part in command])
            return 0, '', ''
        with mock.patch.object(subject, 'call', side_effect=call), \
                mock.patch.object(subject, 'ready_sources', return_value=0), \
                mock.patch.object(subject, 'run_parallel', return_value=[(0, '', ''), (0, '', '')]), \
                mock.patch.object(subject, 'refine'), \
                mock.patch.object(subject, 'host_flags', return_value=[]):
            subject.core_round('readiness', True, [], 1)
        stages = [command[command.index('--stages') + 1] for command in commands
                  if any(part.endswith('discovery_review_host.py') for part in command)]
        self.assertEqual(stages, ['direction,before', 'after'])
        self.assertFalse(any(part.endswith('advance_work.py') for command in commands for part in command))


class CancelledChildTests(unittest.TestCase):
    def setUp(self):
        self.parent = {'query_id': 'QRY-P', 'q': 'cat toy'}
        self.child = {'query_id': 'QRY-C', 'q': 'butterfly attachment', 'parent_query_id': 'QRY-P',
                      'discovery_role': 'refinement'}
        self.plan = {'queries': {'epo_ops': [self.parent, self.child]}, 'execution_dispositions': [
            {'query_id': 'QRY-C', 'plan_entry_sha256': sha256_json(self.child), 'status': 'cancelled',
             'reason': 'API_DISCOVERY_TRIAGE_CHANGED'}]}

    def test_a_child_cancelled_before_submission_does_not_carry_the_parent(self):
        self.assertFalse(auto_refine.has_child(self.plan, self.parent, {'source_runs': []}))

    def test_a_cancelled_child_that_ran_still_counts(self):
        evidence = {'source_runs': [{'query_id': 'QRY-C', 'submission_state': 'submitted', 'status': 'success'}]}
        self.assertTrue(auto_refine.has_child(self.plan, self.parent, evidence))

    def test_live_children_and_callers_without_evidence_are_unchanged(self):
        self.assertTrue(auto_refine.has_child(self.plan, self.parent))
        live = {**self.plan, 'execution_dispositions': []}
        self.assertTrue(auto_refine.has_child(live, self.parent, {'source_runs': []}))


if __name__ == '__main__':
    unittest.main()

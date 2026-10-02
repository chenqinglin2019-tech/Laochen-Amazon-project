"""Offline adversarial execution bounds; no product, credential or model calls."""
from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_file
import execution_budget as budget
from continuous_progress_stage_d import status
import test_continuous_progress_stage_d as progress_fixtures


class MeaningfulProgressTests(progress_fixtures.ProgressStageDTests):
    def setUp(self):
        super().setUp()
        self.task.update(execution_budget_revision=budget.REVISION, execution_budget=deepcopy(budget.DEFAULTS))
        atomic_write_json(self.path / 'task.json', self.task)

    def valid_run(self, run_id='R1'):
        raw = self.path / 'original.json'
        atomic_write_json(raw, {'status': 'no_result', 'records': []})
        return {'run_id': run_id, 'query_id': 'Q1', 'status': 'no_result',
                'raw_paths': [str(raw)], 'payload_digest': sha256_file(raw)}

    def test_bound_fact_is_progress_and_resets_only_own_streak(self):
        self.round()
        self.assertTrue(self.round(update=lambda: self.evidence['source_runs'].append(self.valid_run()))['effective_progress'])
        self.assertEqual(status(self.evidence, 'ACTION-1')['consecutive_no_progress'], 0)

    def test_repeated_failures_and_prose_do_not_reset_stall(self):
        for number in range(2):
            def update():
                self.evidence['source_runs'].append({'run_id': 'R' + str(number), 'query_id': 'Q1',
                    'status': 'failed', 'error_code': 'TIMEOUT', 'finished_at': str(number)})
            self.assertFalse(self.round(update=update)['effective_progress'])
        self.assertEqual(status(self.evidence, 'ACTION-1')['consecutive_no_progress'], 2)
        with self.assertRaisesRegex(ValueError, 'DIAGNOSIS_AND_REPAIR'):
            self.event('begin', work_id='W1')

    def test_collection_content_counts_but_duplicate_ids_do_not(self):
        def update():
            raw = self.path / 'candidate.json'
            atomic_write_json(raw, {'serial_number': '12345678'})
            self.evidence['collections'] = {'discovery': [{'evidence_id': 'E1', 'query_id': 'Q1',
                'path': str(raw), 'sha256': sha256_file(raw),
                'payload': {'candidates': [{'serial_number': '12345678'}]}}]}
        self.assertTrue(self.round(update=update)['effective_progress'])
        def duplicate():
            row = deepcopy(self.evidence['collections']['discovery'][0])
            row.update(evidence_id='E2', recorded_at='different', reasoning='rewritten prose')
            self.evidence['collections']['discovery'].append(row)
        self.assertFalse(self.round(update=duplicate)['effective_progress'])

    def test_duplicate_success_response_does_not_reset_stall(self):
        def first():
            self.evidence['source_runs'].append(self.valid_run())
        self.assertTrue(self.round(update=first)['effective_progress'])
        def duplicate():
            self.evidence['source_runs'].append({**self.valid_run('R2'), 'finished_at': 'new-time'})
        self.assertFalse(self.round(update=duplicate)['effective_progress'])

    def test_invalid_success_and_error_original_cannot_clear_stall(self):
        def missing():
            self.evidence['source_runs'].append({'run_id': 'bad', 'query_id': 'Q1',
                'status': 'success', 'payload_digest': 'not-an-original', 'raw_paths': ['missing.json']})
        self.assertFalse(self.round(update=missing)['effective_progress'])
        def error_original():
            run = self.valid_run('error')
            atomic_write_json(self.path / 'original.json', {'status': 'failed', 'error_code': 'TIMEOUT'})
            run['payload_digest'] = sha256_file(self.path / 'original.json')
            self.evidence['source_runs'].append(run)
        self.assertFalse(self.round(update=error_original)['effective_progress'])
        with self.assertRaisesRegex(ValueError, 'DIAGNOSIS_AND_REPAIR'):
            self.event('begin', work_id='W1')

    def test_diagnostic_metadata_and_recapture_time_do_not_count(self):
        self.assertTrue(self.round(update=lambda: self.evidence['source_runs'].append(self.valid_run()))['effective_progress'])
        def recapture():
            raw = self.path / 'recapture.json'
            atomic_write_json(raw, {'status': 'no_result', 'records': [], 'captured_at': 'another time'})
            self.evidence['source_runs'].append({'run_id': 'R2', 'query_id': 'Q1', 'status': 'no_result',
                'raw_paths': [str(raw)], 'payload_digest': sha256_file(raw), 'metadata': {'receipt': 'new diagnostics'}})
        self.assertFalse(self.round(update=recapture)['effective_progress'])

    def test_disappearing_evidence_is_not_new_progress(self):
        self.assertTrue(self.round(update=lambda: self.evidence['source_runs'].append(self.valid_run()))['effective_progress'])
        self.assertFalse(self.round(update=lambda: self.evidence['source_runs'].clear())['effective_progress'])

    def test_cross_action_budget_survives_route_change_and_reopen(self):
        self.task['execution_budget']['max_no_progress_rounds'] = 2
        atomic_write_json(self.path / 'task.json', self.task)
        self.round('W1'); self.round('W2')
        from continuous_progress_stage_d import dispatch_block, project
        self.assertEqual(dispatch_block(self.task, self.evidence, 'other-provider', {'query_id': 'renamed'}),
            'EXECUTION_NO_PROGRESS_BUDGET_EXHAUSTED')
        self.assertTrue(all(row['state'] == 'blocked' for row in project(self.task, self.view(), self.evidence)['entries']))
        with self.assertRaisesRegex(ValueError, 'NO_PROGRESS_BUDGET_EXHAUSTED'):
            self.event('begin', work_id='W2')

    def test_review_queue_is_not_mistaken_for_closed_obligation(self):
        begin = self.event('begin', work_id='W1')
        self.rows[0]['kind'] = 'scope_review'
        view = {'entries': [self.rows[1]], 'review_work': {'entries': [self.rows[0]]}}
        with patch('workflow_v24.work_view_from_dir', return_value=view):
            from continuous_progress_stage_d import record_event
            result = record_event(self.path, {'kind': 'finish', 'begin_id': begin['event_id'],
                'actor': 'agent', 'reasoning': 'still requires review', 'action_taken': 'read original'})
        self.assertFalse(result['effective_progress'])


class ExecutionBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {'task_id': 'OFFLINE-BUDGET', 'execution_budget_revision': budget.REVISION,
            'execution_budget': {**budget.DEFAULTS, 'active_seconds': 100, 'review_seconds': 30,
                                 'review_reserve_seconds': 10}}
        atomic_write_json(self.root / 'task.json', self.task)
        atomic_write_json(self.root / 'evidence.json', {'task_id': self.task['task_id'], 'progress_events': []})

    def test_same_task_time_does_not_reset_between_calls_and_reserves_review(self):
        clock = {'now': 1000}
        with patch('execution_budget.time.time', side_effect=lambda: clock['now']):
            with budget.execution_budget(self.root, 'sources') as deadline:
                self.assertEqual(deadline, 1090)
                clock['now'] = 1085
            with budget.execution_budget(self.root, 'sources') as deadline:
                self.assertEqual(deadline, 1090)
                clock['now'] = 1090
        self.assertEqual(budget.snapshot(self.root)['stop_reason'], 'EXECUTION_SOURCE_TIME_BUDGET_EXHAUSTED')
        with self.assertRaisesRegex(ValueError, 'TIME_BUDGET_EXHAUSTED'):
            with budget.execution_budget(self.root, 'sources'):
                self.fail('must not execute')
        with patch('execution_budget.time.time', return_value=2000):
            with budget.execution_budget(self.root, 'review') as deadline:
                self.assertEqual(deadline, 2010)

    def test_review_budget_is_cumulative_across_host_calls(self):
        clock = {'now': 1000}
        with patch('execution_budget.time.time', side_effect=lambda: clock['now']):
            with budget.execution_budget(self.root, 'review') as deadline:
                self.assertEqual(deadline, 1030)
                clock['now'] += 20
            with budget.execution_budget(self.root, 'review') as deadline:
                self.assertEqual(deadline, 1030)
                clock['now'] += 10
            with self.assertRaisesRegex(ValueError, 'TIME_BUDGET_EXHAUSTED'):
                with budget.execution_budget(self.root, 'review'):
                    self.fail('must not renew review allowance')

    def test_interrupted_reservation_is_not_refunded(self):
        limits = budget.policy(self.task)
        data = budget._read(self.root, self.task, limits)
        data['active'] = {'lease': 'lost-process', 'started': 1000, 'deadline': 1090, 'phase': 'sources'}
        atomic_write_json(self.root / budget.JOURNAL, data)
        with self.assertRaisesRegex(ValueError, 'TIME_BUDGET_EXHAUSTED'):
            with budget.execution_budget(self.root, 'sources'):
                self.fail('interruption cannot buy another source budget')
        self.assertEqual(load_json(self.root / budget.JOURNAL)['used_seconds'], 90)
        with budget.execution_budget(self.root, 'review'):
            pass

    def test_elapsed_time_is_charged_once_for_inherited_child(self):
        with patch('execution_budget.time.time', side_effect=[1000, 1001, 1002]):
            with budget.execution_budget(self.root, 'sources') as deadline:
                env = budget.child_environment(self.root, deadline)
                with patch.dict(os.environ, env):
                    with budget.execution_budget(self.root, 'sources', inherit=True) as child:
                        self.assertEqual(child, deadline)
        data = load_json(self.root / budget.JOURNAL)
        self.assertEqual((data['invocations'], data['used_seconds']), (1, 2))

    def test_wrong_lease_and_policy_changes_are_rejected(self):
        with budget.execution_budget(self.root, 'sources') as deadline:
            env = budget.child_environment(self.root, deadline); env[budget.ENV_LEASE] = 'forged'
            with patch.dict(os.environ, env), self.assertRaisesRegex(ValueError, 'LEASE_INVALID'):
                with budget.execution_budget(self.root, 'sources', inherit=True):
                    pass
        self.task['execution_budget']['active_seconds'] += 1
        atomic_write_json(self.root / 'task.json', self.task)
        with self.assertRaisesRegex(ValueError, 'BINDING_CHANGED'):
            budget.snapshot(self.root)

    def test_global_no_progress_stops_sources_but_allows_final_review(self):
        evidence = {'progress_events': [{'kind': 'finish', 'effective_progress': False}] * 12}
        atomic_write_json(self.root / 'evidence.json', evidence)
        with self.assertRaisesRegex(ValueError, 'NO_PROGRESS_BUDGET_EXHAUSTED'):
            with budget.execution_budget(self.root, 'sources'):
                pass
        with budget.execution_budget(self.root, 'review'):
            pass

    def test_legacy_task_has_no_budget_journal(self):
        atomic_write_json(self.root / 'task.json', {'task_id': 'LEGACY'})
        with budget.execution_budget(self.root, 'sources') as deadline:
            self.assertIsNone(deadline)
        self.assertIsNone(budget.snapshot(self.root))
        self.assertFalse((self.root / budget.JOURNAL).exists())

    def test_invalid_or_expired_deadline_never_launches(self):
        for deadline in (float('nan'), time.time() - 1):
            with patch('execution_budget.subprocess.Popen', side_effect=AssertionError('must not launch')):
                with self.assertRaisesRegex(ValueError, 'DEADLINE_INVALID|TIME_BUDGET_EXHAUSTED'):
                    budget.run_bounded(['unused'], deadline=deadline, timeout=10)

    def test_real_timeout_retains_partial_output_and_kills_process_group(self):
        command = [sys.executable, '-c', 'import time; print("partial evidence", flush=True); time.sleep(20)']
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            budget.run_bounded(command, deadline=time.time() + .15, timeout=10, text=True)
        self.assertIn('partial evidence', caught.exception.output)
        self.assertLess(time.monotonic() - started, 2)

    def test_queued_modules_and_later_summary_share_one_deadline(self):
        import module_review
        jobs = [{'command': [str(i)], 'prompt': '', 'workspace': self.root,
            'trace_path': self.root / str(i), 'stderr_path': self.root / ('e' + str(i))} for i in range(2)]
        timeouts = []
        clock = {'now': 1000}
        def run(*args):
            timeouts.append(args[-1]); clock['now'] += 30; return 'synthetic result'
        with patch('report_review_host.run_native_logged', side_effect=run), \
                patch('execution_budget.time.time', side_effect=lambda: clock['now']):
            module_review.run_jobs(jobs, 180, 1, deadline=1080)
            module_review.run_jobs(jobs[:1], 180, 1, deadline=1080)
            with self.assertRaisesRegex(ValueError, 'TIME_BUDGET_EXHAUSTED'):
                module_review.run_jobs(jobs[:1], 180, 1, deadline=1080)
        self.assertGreater(timeouts[0], timeouts[1]); self.assertGreater(timeouts[1], timeouts[2])


if __name__ == '__main__':
    unittest.main()

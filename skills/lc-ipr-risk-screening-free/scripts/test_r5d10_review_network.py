"""r5d10: a review session cut off by the network is run again in the same pass (B0GLNPC6K8 new task, final review).

Three of six module sessions ended with "stream disconnected before completion: Transport error: network error:
error decoding response body" and the review stopped after one pass, leaving 526 s of its 1200 s allowance.
"""
import json
import tempfile
import unittest
from pathlib import Path

import execution_budget
import module_review
from review_judgment import ModelJudgmentError

CUT = 'stream disconnected before completion: Transport error: network error: error decoding response body'
ROBUST = {'pipeline_robust_revision': __import__('pipeline_robust').REVISION}


class NetworkRetryTests(unittest.TestCase):
    def job(self, events):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        path = root / 'events.jsonl'
        path.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
        return {'trace_path': path}

    def test_a_network_cut_is_retried_on_a_robust_task(self):
        job = self.job([{'type': 'turn.started'}, {'type': 'error', 'message': CUT},
                        {'type': 'turn.failed', 'error': {'message': CUT}}])
        exc = ValueError('REPORT_REVIEW_HOST_EXECUTION_FAILED')
        self.assertTrue(module_review.network_interrupted(job))
        self.assertTrue(module_review.retryable(exc, job, 'fresh', ROBUST))
        self.assertFalse(module_review.retryable(exc, job, 'fresh', {}))           # older tasks unchanged
        self.assertFalse(module_review.retryable(exc, job, 'retained', ROBUST))

    def test_other_execution_failures_are_not_retried(self):
        exc = ValueError('REPORT_REVIEW_HOST_EXECUTION_FAILED')
        timeout = self.job([{'type': 'turn.started'}])                              # killed at its time limit
        refused = self.job([{'type': 'turn.failed', 'error': {'message': 'Your input exceeds the context window'}}])
        for job in (timeout, refused):
            self.assertFalse(module_review.retryable(exc, job, 'fresh', ROBUST))
        self.assertFalse(module_review.network_interrupted({'trace_path': Path('/nonexistent/events.jsonl')}))

    def test_a_refused_answer_is_still_retried(self):
        self.assertTrue(module_review.retryable(ModelJudgmentError('ASSESSMENT_SCENARIO_BINDING_INVALID'),
                                                self.job([]), 'fresh', {}))

    def test_robust_tasks_get_room_for_one_retry_pass(self):
        plain, robust = execution_budget.v2_limits(1), execution_budget.v2_limits(1, robust=True)
        self.assertEqual((plain['review_seconds'], plain['active_seconds']), (1200, 2400))
        self.assertEqual((robust['review_seconds'], robust['review_reserve_seconds'], robust['active_seconds']),
                         (1800, 1800, 3000))
        self.assertEqual(execution_budget.v2_limits(2, robust=True)['review_seconds'], 2400)
        execution_budget.policy({'execution_budget_revision': execution_budget.REVISION_V2, 'execution_budget': robust})


class AllowanceShortTests(unittest.TestCase):
    """Second resume: the estimate said 190 s for a module cut at 655 s, a 526 s pass started and timed out at 507 s."""

    def test_unfinished_turns_of_the_same_prompt_raise_the_estimate(self):
        from common import atomic_write_json
        from review_preflight import _measured_seconds
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        slot = root / '1' / 'technical'
        for folder, status, seconds, prompt in ((slot, 'timed_out', 507.0, 'P'),
                                                (slot.with_name('technical.attempt-1'), 'process_failed', 655.6, 'P'),
                                                (slot.with_name('technical.attempt-2'), 'process_failed', 900.0, 'OTHER')):
            folder.mkdir(parents=True)
            atomic_write_json(folder / 'events.execution.json',
                              {'status': status, 'elapsed_seconds': seconds, 'prompt_sha256': prompt})
        self.assertAlmostEqual(_measured_seconds(slot, 'P'), 775.6)
        atomic_write_json(slot / 'events.execution.json',
                          {'status': 'process_exited', 'elapsed_seconds': 820.0, 'prompt_sha256': 'P'})
        self.assertEqual(_measured_seconds(slot, 'P'), 820.0)
        self.assertIsNone(_measured_seconds(slot, 'NONE'))

    def test_the_pipeline_prints_the_owner_command_whole(self):
        import run_pipeline
        from unittest import mock
        from common import atomic_write_json
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        atomic_write_json(root / 'task.json', {'task_id': 'IPRF-x'})
        pipeline = run_pipeline.Pipeline(mock.Mock(task_dir=str(root), guard_session_id='s', chief=None))
        hint = pipeline.review_budget_hint({'code': 'EXECUTION_REVIEW_BUDGET_INSUFFICIENT', 'needed_seconds': 916,
                                            'review_remaining_seconds': 0})
        self.assertIn('extend_review_budget.py', hint)
        self.assertIn('--add-seconds 1800', hint)
        self.assertIn('EXTEND IPRF-x 1800', hint)
        self.assertIn('Agent 不得代为执行', hint)
        self.assertEqual(pipeline.review_budget_hint({'code': 'OTHER'}), '')


class NetworkRetryPassTests(unittest.TestCase):
    """The real module review loop with the offline host fixture: one module's stream is cut once."""

    def fixture(self, robust):
        import time
        from types import SimpleNamespace
        from common import atomic_write_json, load_json
        from review_readiness import prepare_review_context, freeze_input
        from test_review_identity_recovery import recovery_fixture
        manager = recovery_fixture(kind='seven-country-large')
        f = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        if robust:
            f.task.update(ROBUST, execution_budget_revision=execution_budget.REVISION_V2,
                          execution_budget=execution_budget.v2_limits(7, robust=True))
            atomic_write_json(f.source / 'task.json', f.task)
            f.context = prepare_review_context(f.source)
            (f.output / 'frozen.json').unlink()
            f.meta = freeze_input(f.source, f.output / 'frozen.json', prepared_context=f.context)
            f.frozen = load_json(f.output / 'frozen.json')
        native, cut = f.native, []

        def flaky(command, prompt, workspace, trace_path, stderr_path, timeout):
            if (trace_path.parent.parent.name, trace_path.parent.name) == ('2', 'technical') and not cut:
                cut.append(True)
                f.calls.append(('2', 'technical'))
                text = '\n'.join(json.dumps(e) for e in ({'type': 'thread.started', 'thread_id': 'cut'},
                    {'type': 'turn.started'}, {'type': 'error', 'message': CUT},
                    {'type': 'turn.failed', 'error': {'message': CUT}})) + '\n'
                trace_path.write_text(text, encoding='utf-8')
                stderr_path.write_text('', encoding='utf-8')
                return SimpleNamespace(returncode=1, pid=1), text, ''
            return native(command, prompt, workspace, trace_path, stderr_path, timeout)
        f.native = flaky
        return f, time.time() + 3600

    def run_pair(self, f, deadline):
        from unittest.mock import patch
        from module_review import run_module_pair
        with patch('report_review_host.run_native_logged', side_effect=f.native), \
                patch('native_review_jobs._probe', return_value=[]), \
                patch('report_review_host._probe', return_value=[]), \
                patch('macos_review_host.require_chatgpt_auth'):
            return run_module_pair(f.source, f.output, f.binary, f.frozen, f.meta, f.context, timeout=10,
                                   max_parallel=2, isolation='macos-sandbox', deadline=deadline)

    def test_the_cut_module_runs_again_in_the_same_pass(self):
        f, deadline = self.fixture(robust=True)
        paths = self.run_pair(f, deadline)
        self.assertEqual(len(paths), 2)
        self.assertEqual(f.calls.count(('2', 'technical')), 2)
        self.assertTrue((f.output / '2' / 'technical.attempt-1').is_dir())

    def test_an_older_task_still_stops_for_a_resume(self):
        f, deadline = self.fixture(robust=False)
        with self.assertRaisesRegex(ValueError, 'REPORT_REVIEW_HOST_EXECUTION_FAILED'):
            self.run_pair(f, deadline)
        self.assertEqual(f.calls.count(('2', 'technical')), 1)


if __name__ == '__main__':
    unittest.main()

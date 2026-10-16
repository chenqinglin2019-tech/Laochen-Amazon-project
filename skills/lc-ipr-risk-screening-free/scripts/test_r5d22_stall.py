"""r5d22: silent sessions are stopped once their finished peers prove them overdue and run again; a re-drafted scope
stops at checkpoint 1 again."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import module_review
import review_preflight
import run_pipeline as rp
import stall_guard
from report_review_host import run_native_logged

H1, H2, H3 = 'a' * 64, 'b' * 64, 'c' * 64
SILENT = 'import sys,time,json\nsys.stdin.read()\nprint(json.dumps({"type":"turn.started"}),flush=True)\ntime.sleep(30)\n'
TALKING = ('import sys,time,json\nsys.stdin.read()\nprint(json.dumps({"type":"item.started","item":{"type":"reasoning"}}),'
           'flush=True)\ntime.sleep(30)\n')


def finished(directory, seconds, status='process_exited', exit_code=0, **extra):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'events.execution.json').write_text(json.dumps(
        {'status': status, 'exit_code': exit_code, 'elapsed_seconds': seconds, 'turn_completed_seconds': seconds,
         'first_agent_message_seconds': None, 'first_reasoning_seconds': None, 'prompt_sha256': 'p', **extra}))


class Temp(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='stall-'))
        self.addCleanup(shutil.rmtree, self.root, True)
        patcher = mock.patch.dict(os.environ, {'LC_IPR_MODEL_SLOT_DIR': str(self.root / 'slots'),
                                               'LC_IPR_RATE_LIMIT_BACKOFF': '0.05'})
        patcher.start()
        self.addCleanup(patcher.stop)


class LimitTests(Temp):
    def test_batch_sessions_wait_for_two_finished_peers(self):
        batch = self.root / 'discovery-review' / 'after'
        finished(batch / H2, 14)
        self.assertIsNone(stall_guard.limit(batch / H1 / 'events.jsonl'))
        finished(batch / (H1 + '.attempt-1'), 5)                        # its own earlier attempt is no peer
        self.assertIsNone(stall_guard.limit(batch / H1 / 'events.jsonl'))
        finished(batch / H3, 65)
        self.assertEqual(stall_guard.limit(batch / H1 / 'events.jsonl'), 195)
        finished(batch / ('d' * 64), 20, status='timed_out', exit_code=-9)  # unfinished peers do not count
        self.assertEqual(stall_guard.limit(batch / H1 / 'events.jsonl'), 195)

    def test_a_short_peer_never_cuts_below_the_minimum(self):
        batch = self.root / 'recall-screen-text' / 'batch'
        finished(batch / H2, 10)
        finished(batch / H3, 12)
        self.assertEqual(stall_guard.limit(batch / H1 / 'events.jsonl'), stall_guard.MIN_SECONDS)

    def test_final_review_slots_follow_the_other_chain(self):
        review = self.root / 'final-review'
        self.assertIsNone(stall_guard.limit(review / '2' / 'appearance' / 'events.jsonl'))
        finished(review / '1' / 'appearance', 392)
        self.assertAlmostEqual(stall_guard.limit(review / '2' / 'appearance' / 'events.jsonl'), 1.6 * 392)
        finished(review / '1' / 'technical', 80)
        self.assertEqual(stall_guard.limit(review / '2' / 'technical' / 'events.jsonl'), 80 + stall_guard.TWIN_MARGIN)
        self.assertIsNone(stall_guard.limit(review / '2' / 'expression' / 'events.jsonl'))
        self.assertIsNone(stall_guard.limit(self.root / 'product-understanding' / 'session' / 'x' / 'events.jsonl'))


class RunnerTests(Temp):
    def run_session(self, directory, program, timeout=20):
        directory.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, 'REPORT_REVIEW_HOST_TIMEOUT_NO_AUTOMATIC_RETRY'):
            run_native_logged([sys.executable, '-u', '-c', program], 'prompt', directory,
                              directory / 'events.jsonl', directory / 'stderr.log', timeout)
        return time.monotonic() - started, json.loads((directory / 'events.execution.json').read_text())

    @mock.patch.multiple(stall_guard, MIN_SECONDS=0.5, PEER_FACTOR=1.0, CHECK_SECONDS=0.1)
    def test_a_silent_session_is_stopped_once_its_peers_prove_it_overdue(self):
        batch = self.root / 'discovery-review' / 'direction'
        finished(batch / H2, 0.2)
        finished(batch / H3, 0.3)
        seconds, record = self.run_session(batch / H1, SILENT)
        self.assertLess(seconds, 10)
        self.assertEqual((record['status'], record['failure_code']), ('stalled', 'REPORT_REVIEW_HOST_STALLED'))
        self.assertEqual(record['stall_limit_seconds'], 0.5)
        self.assertTrue(stall_guard.stalled(batch / H1))

    @mock.patch.multiple(stall_guard, MIN_SECONDS=0.5, PEER_FACTOR=1.0, CHECK_SECONDS=0.1)
    def test_a_session_that_has_started_answering_is_left_to_its_timeout(self):
        batch = self.root / 'discovery-review' / 'direction'
        finished(batch / H2, 0.2)
        finished(batch / H3, 0.3)
        seconds, record = self.run_session(batch / H1, TALKING, timeout=3)
        self.assertGreaterEqual(seconds, 2.9)
        self.assertEqual(record['status'], 'timed_out')
        self.assertNotIn('stall_limit_seconds', record)

    @mock.patch.multiple(stall_guard, MIN_SECONDS=0.5, PEER_FACTOR=1.0, CHECK_SECONDS=0.1)
    def test_without_finished_peers_nothing_changes(self):
        seconds, record = self.run_session(self.root / 'discovery-review' / 'direction' / H1, SILENT, timeout=2)
        self.assertGreaterEqual(seconds, 1.9)
        self.assertEqual(record['status'], 'timed_out')


class FinalReviewTests(Temp):
    @mock.patch.multiple(stall_guard, MIN_SECONDS=0.5, TWIN_MARGIN=0, CHECK_SECONDS=0.1)
    def test_a_stalled_module_is_a_failed_turn_that_the_pass_runs_again(self):
        review = self.root / 'final-review'
        finished(review / '1' / 'appearance', 0.2)
        slot = review / '2' / 'appearance'
        slot.mkdir(parents=True)
        job = {'command': [sys.executable, '-u', '-c', SILENT], 'prompt': 'p', 'workspace': slot,
               'trace_path': slot / 'events.jsonl', 'stderr_path': slot / 'stderr.log'}
        started = time.monotonic()
        (proc, trace, _), = module_review.run_jobs([job], 20, 1)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(proc.returncode, -9)
        self.assertIn('turn.started', trace)
        robust = {'pipeline_robust_revision': 'robust-v1'}
        failed = ValueError('REPORT_REVIEW_HOST_EXECUTION_FAILED')
        self.assertTrue(module_review.retryable(failed, job, 'fresh', robust))
        self.assertFalse(module_review.retryable(failed, job, 'fresh', {}))
        # the retry allowance is sized by the other chain, not by the stall
        self.assertEqual(module_review._session_seconds(slot, 99), 0.2)

    def test_a_plain_timeout_still_fails_the_pass(self):
        slot = self.root / 'final-review' / '2' / 'appearance'
        slot.mkdir(parents=True)
        job = {'command': [sys.executable, '-u', '-c', SILENT], 'prompt': 'p', 'workspace': slot,
               'trace_path': slot / 'events.jsonl', 'stderr_path': slot / 'stderr.log'}
        with self.assertRaisesRegex(ValueError, 'TIMEOUT_NO_AUTOMATIC_RETRY'):
            module_review.run_jobs([job], 1, 1)


class StallPassTests(unittest.TestCase):
    """The real module review loop with the offline host fixture: chain 2's technical module stalls once."""

    def fixture(self, robust):
        from types import SimpleNamespace  # noqa: F401
        import execution_budget
        from common import atomic_write_json, load_json
        from review_readiness import prepare_review_context, freeze_input
        from test_review_identity_recovery import recovery_fixture
        manager = recovery_fixture(kind='seven-country-large')
        f = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        if robust:
            f.task.update({'pipeline_robust_revision': 'robust-v1'},
                          execution_budget_revision=execution_budget.REVISION_V2,
                          execution_budget=execution_budget.v2_limits(7, robust=True))
            atomic_write_json(f.source / 'task.json', f.task)
            f.context = prepare_review_context(f.source)
            (f.output / 'frozen.json').unlink()
            f.meta = freeze_input(f.source, f.output / 'frozen.json', prepared_context=f.context)
            f.frozen = load_json(f.output / 'frozen.json')
        native, stalls = f.native, []

        def stalling(command, prompt, workspace, trace_path, stderr_path, timeout):
            if (trace_path.parent.parent.name, trace_path.parent.name) == ('2', 'technical') and not stalls:
                stalls.append(True)
                f.calls.append(('2', 'technical'))
                trace_path.write_text(json.dumps({'type': 'turn.started'}) + '\n', encoding='utf-8')
                stderr_path.write_text('', encoding='utf-8')
                trace_path.with_suffix('.execution.json').write_text(json.dumps(
                    {'status': 'stalled', 'failure_code': 'REPORT_REVIEW_HOST_STALLED', 'elapsed_seconds': 5,
                     'stall_limit_seconds': 5, 'prompt_sha256': 'x'}), encoding='utf-8')
                raise ValueError('REPORT_REVIEW_HOST_TIMEOUT_NO_AUTOMATIC_RETRY')
            return native(command, prompt, workspace, trace_path, stderr_path, timeout)
        f.native = stalling
        return f, time.time() + 3600

    def run_pair(self, f, deadline):
        from module_review import run_module_pair
        with mock.patch('report_review_host.run_native_logged', side_effect=f.native), \
                mock.patch('native_review_jobs._probe', return_value=[]), \
                mock.patch('report_review_host._probe', return_value=[]), \
                mock.patch('macos_review_host.require_chatgpt_auth'):
            return run_module_pair(f.source, f.output, f.binary, f.frozen, f.meta, f.context, timeout=10,
                                   max_parallel=2, isolation='macos-sandbox', deadline=deadline)

    def test_the_stalled_module_runs_again_in_the_same_pass(self):
        f, deadline = self.fixture(robust=True)
        self.assertEqual(len(self.run_pair(f, deadline)), 2)
        self.assertEqual(f.calls.count(('2', 'technical')), 2)
        self.assertTrue(stall_guard.stalled(f.output / '2' / 'technical.attempt-1'))

    def test_an_older_task_still_stops_for_a_resume(self):
        f, deadline = self.fixture(robust=False)
        with self.assertRaisesRegex(ValueError, 'REPORT_REVIEW_HOST_EXECUTION_FAILED'):
            self.run_pair(f, deadline)
        self.assertEqual(f.calls.count(('2', 'technical')), 1)


class PreflightTests(Temp):
    def test_a_silent_cut_off_turn_is_measured_by_the_other_chain(self):
        review = self.root / 'final-review'
        finished(review / '1' / 'appearance', 392)
        finished(review / '2' / 'appearance', 900, status='timed_out', exit_code=-9)
        self.assertEqual(review_preflight._measured_seconds(review / '2' / 'appearance', 'p'), 392)
        finished(review / '2' / 'appearance', 900, status='timed_out', exit_code=-9, first_reasoning_seconds=30)
        self.assertEqual(review_preflight._measured_seconds(review / '2' / 'appearance', 'p'),
                         900 + review_preflight.UNFINISHED_MARGIN_SECONDS)       # it was working: keep the margin
        shutil.rmtree(review / '1')
        finished(review / '2' / 'appearance', 900, status='timed_out', exit_code=-9)
        self.assertEqual(review_preflight._measured_seconds(review / '2' / 'appearance', 'p'),
                         900 + review_preflight.UNFINISHED_MARGIN_SECONDS)


class CheckpointOneTests(Temp):
    def pipeline(self, *flags):
        run = self.root / 'RUN'
        (run / 'checkpoints').mkdir(parents=True, exist_ok=True)
        (run / 'task.json').write_text('{"task_id": "T"}', encoding='utf-8')
        pipeline = rp.Pipeline(rp.parser().parse_args(['--task-dir', str(run), *flags]))
        scope = run / 'checkpoints' / '1-scope.json'

        def call(stage, command, **kw):
            scope.write_text('{}', encoding='utf-8')
            return 0, '{"driver": "native"}', ''
        pipeline.call = call
        return pipeline, scope

    def test_a_re_draft_under_resume_is_shown_again(self):
        pipeline, scope = self.pipeline('--resume')
        pipeline.state['checkpoints']['1'] = 'waiting'          # the owner deleted 1-*.json and resumed
        with self.assertRaises(rp.Checkpoint):
            pipeline.s_understanding()
        self.assertTrue(scope.is_file())
        self.assertEqual(pipeline.s_understanding(), {'scope_draft': str(scope)})   # the next resume goes on
        self.assertEqual(pipeline.state['checkpoints']['1'], 'released')

    def test_a_first_run_still_stops(self):
        pipeline, _ = self.pipeline()
        with self.assertRaises(rp.Checkpoint):
            pipeline.s_understanding()


if __name__ == '__main__':
    unittest.main()

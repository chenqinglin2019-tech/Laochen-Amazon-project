"""r5d23 (run B0GLNPC6K8, r5d21): an unresolved web card no longer holds back every search, an identical dead-end
packet is not sent again, a session whose answer arrived but whose turn never closed is stopped early, and a time-box
task does not fail at the core exit."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pipeline_robust
import review_preflight
import run_pipeline as rp
import stall_guard
import test_text_triage_host as text_fixture
from report_review_host import run_native_logged

H1 = 'a' * 64
ANSWERED = ('import sys,time,json\nsys.stdin.read()\n'
            'print(json.dumps({"type":"thread.started","thread_id":"T"}),flush=True)\n'
            'print(json.dumps({"type":"turn.started"}),flush=True)\n'
            'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"{}"}}),flush=True)\n'
            'time.sleep(30)\n')
CLOSED = ANSWERED.replace('time.sleep(30)\n', 'time.sleep(0.5)\nprint(json.dumps({"type":"turn.completed"}),flush=True)\n')
STREAMING = ('import sys,time,json\nsys.stdin.read()\nprint(json.dumps({"type":"turn.started"}),flush=True)\n'
             'print(json.dumps({"type":"item.started","item":{"type":"agent_message","text":""}}),flush=True)\n'
             'time.sleep(30)\n')


class Temp(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='r5d23-'))
        self.addCleanup(shutil.rmtree, self.root, True)
        patcher = mock.patch.dict(os.environ, {'LC_IPR_MODEL_SLOT_DIR': str(self.root / 'slots'),
                                               'LC_IPR_RATE_LIMIT_BACKOFF': '0.05'})
        patcher.start()
        self.addCleanup(patcher.stop)


@mock.patch.multiple(stall_guard, ANSWERED_GRACE=1, CHECK_SECONDS=0.1)
class AnsweredStallTests(Temp):
    def session(self, program, timeout):
        directory = self.root / 'discovery-review' / 'direction' / H1
        directory.mkdir(parents=True)
        started = time.monotonic()
        result = run_native_logged([sys.executable, '-u', '-c', program], 'prompt', directory,
                                   directory / 'events.jsonl', directory / 'stderr.log', timeout)
        return result, time.monotonic() - started, json.loads((directory / 'events.execution.json').read_text())

    def test_an_answer_whose_turn_never_closes_is_stopped_after_the_grace(self):
        with self.assertRaisesRegex(ValueError, 'REPORT_REVIEW_HOST_TIMEOUT_NO_AUTOMATIC_RETRY'):
            self.session(ANSWERED, 20)
        record = json.loads((self.root / 'discovery-review' / 'direction' / H1 / 'events.execution.json').read_text())
        self.assertEqual((record['status'], record['stall_kind']), ('stalled', 'answered_turn_not_closed'))
        self.assertLess(record['elapsed_seconds'], 10)
        self.assertTrue(stall_guard.stalled(self.root / 'discovery-review' / 'direction' / H1))

    def test_a_turn_that_closes_is_untouched(self):
        (proc, _, _), _, record = self.session(CLOSED, 20)
        self.assertEqual((proc.returncode, record['status']), (0, 'process_exited'))
        self.assertNotIn('stall_kind', record)

    def test_an_answer_still_being_written_is_left_to_its_timeout(self):
        with self.assertRaisesRegex(ValueError, 'TIMEOUT'):
            self.session(STREAMING, 3)
        record = json.loads((self.root / 'discovery-review' / 'direction' / H1 / 'events.execution.json').read_text())
        self.assertEqual(record['status'], 'timed_out')
        self.assertGreaterEqual(record['elapsed_seconds'], 2.9)

    def test_rule(self):
        self.assertTrue(stall_guard.answered_stalled(72, None, 72, 73))
        self.assertFalse(stall_guard.answered_stalled(72, None, 72, 72.5))
        self.assertFalse(stall_guard.answered_stalled(72, 72.2, 72.2, 200))
        self.assertFalse(stall_guard.answered_stalled(None, None, 5, 200))


class PreflightTests(Temp):
    def test_an_answered_stall_is_measured_by_its_answer(self):
        slot = self.root / 'final-review' / '2' / 'appearance'
        slot.mkdir(parents=True)
        (slot / 'events.execution.json').write_text(json.dumps(
            {'status': 'stalled', 'stall_kind': 'answered_turn_not_closed', 'elapsed_seconds': 422,
             'first_agent_message_seconds': 392, 'prompt_sha256': 'p'}))
        self.assertEqual(review_preflight._measured_seconds(slot, 'p'), 392)


class LightTriageTests(Temp):
    def view(self, *candidates):
        return {'entries': [{'kind': 'triage', 'state': 'awaiting_review', 'reason': 'CANDIDATE_TRIAGE_REQUIRED',
                             'candidate_id': cid, 'work_id': 'WORK-' + cid} for cid in candidates]}

    def test_a_card_the_text_host_left_unresolved_no_longer_holds_dispatch(self):
        self.assertTrue(pipeline_robust.light_triage_pending(self.view('CAND-web'), self.root))
        (self.root / 'text-triage').mkdir()
        (self.root / 'text-triage' / 'last-run.json').write_text(json.dumps({'unresolved': [
            {'candidate_id': 'CAND-web', 'reason': 'execution_or_registration:TEXT_NEEDS_INFO_ACTIONS_REQUIRED'}]}))
        self.assertFalse(pipeline_robust.light_triage_pending(self.view('CAND-web'), self.root))
        # a card nobody has judged yet still goes first
        self.assertTrue(pipeline_robust.light_triage_pending(self.view('CAND-web', 'CAND-new'), self.root))


class DeadEndTests(text_fixture.TextHostFixture):
    def raw(self, packet, **special):
        dead = {'decision': 'needs_info', 'missing_information': ['The complaint text naming the accused product'],
                'missing_fact_effect': 'The card names the parties only', 'existing_material_review': 'Card read',
                'completion_condition': 'Read the complaint', 'next_actions': []}
        return super().raw(packet, P2=dead, **special)

    def test_an_identical_dead_end_packet_is_not_sent_again(self):
        import text_triage_host
        first = self.run_host()
        self.assertEqual([row['candidate_id'] for row in first['unresolved']], ['P2'])
        calls = len(self.calls)
        second = self.run_host()
        self.assertEqual(len(self.calls), calls + 1)                 # one more try, then the packet is a known dead end
        self.assertTrue(second['unresolved'][0]['reason'].startswith('repeat:TEXT_NEEDS_INFO_ACTIONS_REQUIRED'))
        third = self.run_host()
        self.assertEqual(len(self.calls), calls + 1)                 # no session at all
        self.assertEqual([row['candidate_id'] for row in third['unresolved']], ['P2'])
        dead = json.loads((self.root / 'text-triage' / text_triage_host.DEAD_END_FILE).read_text())
        self.assertTrue(all(row['reason'] == 'TEXT_NEEDS_INFO_ACTIONS_REQUIRED' for row in dead.values()))


class CoreExitTests(Temp):
    def pipeline(self, box):
        run = self.root / 'RUN'
        run.mkdir()
        (run / 'task.json').write_text('{"task_id": "T"}', encoding='utf-8')
        pipeline = rp.Pipeline(rp.parser().parse_args(['--task-dir', str(run)]))
        pipeline.call = lambda *a, **k: (0, '{}', '')
        pipeline.robust = lambda: True
        pipeline.speed = lambda: True
        pipeline.precise = lambda: True
        pipeline.box = lambda: box
        pipeline.boxed = lambda name: False
        pipeline.core_round = lambda *a, **k: None
        pipeline.progress_signature = lambda: 1
        pipeline.flush_sources = lambda stage, rounds=2: ['QRY-a', 'QRY-b']
        return pipeline

    def test_a_time_box_task_goes_on_to_the_readiness_check(self):
        pipeline = self.pipeline(box=True)
        pipeline.s_core()
        self.assertEqual(pipeline.state['undispatched_at_core_exit'], ['QRY-a', 'QRY-b'])

    def test_other_tasks_still_stop_with_the_diagnosis(self):
        with self.assertRaises(rp.StageFailed):
            self.pipeline(box=False).s_core()


if __name__ == '__main__':
    unittest.main()

"""r5d21 scheduling: machine-wide model slots, rate-limit retries, derivation caches (every task)."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import model_slots
from report_review_host import run_native_logged

RATE = [{'type': 'thread.started', 'thread_id': 'T'}, {'type': 'turn.started'},
        {'type': 'error', 'message': 'exceeded retry limit, last status: 429 Too Many Requests, request id: x'},
        {'type': 'turn.failed', 'error': {'message': 'exceeded retry limit, last status: 429 Too Many Requests'}}]
GOOD = [{'type': 'thread.started', 'thread_id': 'T'}, {'type': 'turn.started'},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"decisions":[]}'}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 5, 'output_tokens': 1}}]


def trace(events):
    return '\n'.join(json.dumps(event) for event in events)


class SlotEnvironment(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        patcher = mock.patch.dict(os.environ, {'LC_IPR_MODEL_SLOT_DIR': str(self.root / 'slots'),
                                               'LC_IPR_RATE_LIMIT_BACKOFF': '0.05', 'LC_IPR_MODEL_SLOTS': '2'})
        patcher.start()
        self.addCleanup(patcher.stop)


class DetectionTests(unittest.TestCase):
    def test_rate_limit_before_output_is_transient(self):
        self.assertTrue(model_slots.rate_limited(trace(RATE)))
        self.assertFalse(model_slots.rate_limited(trace(GOOD)))
        self.assertFalse(model_slots.rate_limited(trace(RATE[:2] + GOOD[2:3] + RATE[2:])))   # output arrived first
        network = [{'type': 'error', 'message': 'stream disconnected before completion'}]
        self.assertFalse(model_slots.rate_limited(trace(network)))

    def test_spent_quota_is_not_retried(self):
        quota = [{'type': 'error', 'message': "429 Too Many Requests: You've hit your usage limit, try again later"}]
        self.assertFalse(model_slots.rate_limited(trace(quota)))
        self.assertTrue(model_slots.quota_exhausted(trace(quota)))


class SlotTests(SlotEnvironment):
    def test_third_session_waits_for_a_free_slot(self):
        release, held = threading.Event(), []

        def hold():
            with model_slots.slot(poll=0.02) as record:
                held.append(record['slot'])
                release.wait(5)
        threads = [threading.Thread(target=hold) for _ in range(2)]
        for thread in threads:
            thread.start()
        while len(held) < 2:
            time.sleep(0.01)
        with self.assertRaises(ValueError) as caught:
            with model_slots.slot(poll=0.02, max_wait=0.2):
                pass
        self.assertEqual(str(caught.exception), 'MODEL_SLOT_WAIT_TIMEOUT')
        release.set()
        for thread in threads:
            thread.join()
        with model_slots.slot(poll=0.02, max_wait=1) as record:
            self.assertIn(record['slot'], (0, 1))
        self.assertEqual(sorted(held), [0, 1])

    def test_a_slot_held_by_another_process_is_respected_and_freed_on_exit(self):
        env = {**os.environ, 'LC_IPR_MODEL_SLOTS': '1', 'PYTHONPATH': str(Path(model_slots.__file__).parent)}
        code = ('import model_slots,time,sys\nwith model_slots.slot():\n print("held",flush=True)\n'
                ' time.sleep(1.0)\n')
        child = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True, env=env)
        self.assertEqual(child.stdout.readline().strip(), 'held')
        with mock.patch.dict(os.environ, {'LC_IPR_MODEL_SLOTS': '1'}):
            with self.assertRaises(ValueError):
                with model_slots.slot(poll=0.05, max_wait=0.2):
                    pass
            child.wait(5)
            child.stdout.close()
            with model_slots.slot(poll=0.05, max_wait=2) as record:
                self.assertEqual(record['slot'], 0)

    def test_cool_down_is_shared_and_waited_for(self):
        waited = model_slots.note_rate_limit(0)
        self.assertGreater(model_slots.cooldown_remaining(), 0)
        sleeps = []
        model_slots.wait_cooldown(sleep=lambda seconds: (sleeps.append(seconds), time.sleep(seconds)))
        self.assertTrue(sleeps)
        self.assertLessEqual(waited, 0.05)


class RunnerRetryTests(SlotEnvironment):
    def program(self, outcomes):
        """A fake native CLI: the n-th run prints outcomes[n] ('rate' or 'good' or 'network') and exits accordingly."""
        counter = self.root / 'runs.txt'
        return ('import json,sys,pathlib\nsys.stdin.read()\n'
                'p=pathlib.Path(%r)\nn=int(p.read_text()) if p.exists() else 0\np.write_text(str(n+1))\n'
                'outcomes=%r\nkind=outcomes[min(n,len(outcomes)-1)]\n'
                'events={"rate":%r,"good":%r,"network":[{"type":"error","message":"stream disconnected"}]}[kind]\n'
                'for e in events: print(json.dumps(e),flush=True)\n'
                'sys.exit(0 if kind=="good" else 1)\n') % (str(counter), outcomes, RATE, GOOD)

    def run_fake(self, outcomes):
        work = self.root / 'job'
        work.mkdir(exist_ok=True)
        trace_path, errors = work / 'events.jsonl', work / 'stderr.log'
        result = run_native_logged([sys.executable, '-u', '-c', self.program(outcomes)], 'prompt', work, trace_path,
                                   errors, 10)
        return result, work

    def test_a_rate_limited_session_is_run_again_in_the_same_step(self):
        (proc, stdout, _), work = self.run_fake(['rate', 'rate', 'good'])
        self.assertEqual(proc.returncode, 0)
        self.assertIn('agent_message', stdout)
        sidecar = json.loads((work / 'events.ratelimit.json').read_text())
        self.assertEqual([row['attempt'] for row in sidecar['attempts']], [1, 2])
        self.assertFalse(sidecar['final_rate_limited'])
        self.assertTrue((work / 'events.ratelimit-1.jsonl').is_file())
        self.assertTrue((work / 'events.ratelimit-2.jsonl').is_file())
        self.assertEqual(json.loads((work / 'events.execution.json').read_text())['status'], 'process_exited')

    def test_other_failures_are_returned_at_once(self):
        (proc, _, _), work = self.run_fake(['network', 'good'])
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((work / 'events.ratelimit.json').exists())
        self.assertEqual((self.root / 'runs.txt').read_text(), '1')

    def test_retries_stop_at_the_limit(self):
        (proc, _, _), work = self.run_fake(['rate'])
        self.assertEqual(proc.returncode, 1)
        sidecar = json.loads((work / 'events.ratelimit.json').read_text())
        self.assertEqual(len(sidecar['attempts']), model_slots.MAX_RATE_LIMIT_RETRIES)
        self.assertTrue(sidecar['final_rate_limited'])
        self.assertEqual((self.root / 'runs.txt').read_text(), str(model_slots.MAX_RATE_LIMIT_RETRIES + 1))


import test_text_triage_host as text_fixture


class SchedulerTests(text_fixture.TextHostFixture):
    def test_a_rate_limited_batch_is_retried_whole_not_halved(self):
        from types import SimpleNamespace
        calls = []
        original = self.native

        def native(command, prompt, workspace, trace_path, stderr_path, timeout):
            packet = json.loads((trace_path.parent / 'packet.json').read_text())
            calls.append(len(packet['units']))
            if len(calls) == 1:
                trace_path.write_text(trace(RATE))
                stderr_path.write_text('')
                return SimpleNamespace(returncode=1, pid=1), trace(RATE), ''
            return original(command, prompt, workspace, trace_path, stderr_path, timeout)
        self.native = native
        summary = self.run_host()
        self.assertEqual(calls, [3, 3])
        self.assertEqual(summary['unresolved'], [])


class AllowanceUnionTests(unittest.TestCase):
    def test_hosts_running_side_by_side_are_charged_once(self):
        import host_triage
        task = {'task_id': 'T'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            host_triage._charge(root, task, 1000.0, 1360.0, 360.0)      # comparison, 6 minutes
            host_triage._charge(root, task, 1000.0, 1300.0, 300.0)      # screen beside it
            host_triage._charge(root, task, 1200.0, 1500.0, 300.0)      # half overlapping
            data = json.loads((root / host_triage.JOURNAL).read_text())
        self.assertEqual(data['used_seconds'], 500.0)
        self.assertEqual(data['invocations'], 3)
        self.assertEqual(host_triage._overlap(0, 10, [(2, 4), (3, 6), (8, 20)]), 6)


class DerivationCacheTests(unittest.TestCase):
    def test_caches_exist_only_inside_a_derivation(self):
        import derivation_memo
        self.assertIsNone(derivation_memo.cache('x'))
        with derivation_memo.active():
            table = derivation_memo.cache('x')
            table['k'] = 1
            with derivation_memo.active():
                self.assertEqual(derivation_memo.cache('x')['k'], 1)
            self.assertEqual(derivation_memo.cache('x')['k'], 1)
        self.assertIsNone(derivation_memo.cache('x'))
        with mock.patch.dict(os.environ, {'LC_IPR_DERIVATION_MEMO': '0'}), derivation_memo.active():
            self.assertIsNone(derivation_memo.cache('x'))

    def test_a_changed_file_is_hashed_again_inside_a_derivation(self):
        import derivation_memo
        from assessment_estimate import _verify_file
        from common import sha256_bytes
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.bin'
            path.write_bytes(b'first')
            digest = sha256_bytes(b'first')
            with derivation_memo.active():
                _verify_file(path, digest, 5)
                _verify_file(path, digest, 5)
                time.sleep(0.01)
                path.write_bytes(b'other')
                with self.assertRaises(ValueError):
                    _verify_file(path, digest, 5)

    def test_event_chain_tampering_outside_a_derivation_is_still_detected(self):
        import derivation_memo
        import specialty_analysis as sa
        task = {'task_id': 'T', sa.EVENTS: []}
        row = {'kind': sorted(sa.KINDS)[0], 'previous_event_id': ''}
        from common import sha256_json, stable_id
        row['event_id'] = stable_id('SPECIALTY', 'T', sha256_json(row))
        task[sa.EVENTS].append(row)
        with derivation_memo.active():
            self.assertEqual(sa.events(task), [row])
            self.assertEqual(sa.events(task), [row])
        row['kind'] = 'changed'
        with self.assertRaises(ValueError):
            sa.events(task)


if __name__ == '__main__':
    unittest.main()

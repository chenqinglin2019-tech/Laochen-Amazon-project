"""r5d9: time the computer slept is not model analysis (B0GLNPC6K8 new task, resume after r5d8).

The first run slept 34 minutes inside three host calls; the wall-clock charge left the resume 72 seconds of its
3600-second analysis allowance, so the design comparison session was cut off at 72 seconds and checkpoint 2 listed
the two designs as 'inventory pending'. The same run's timings give back 2064 seconds (checked on the run copy).
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import atomic_write_json, load_json
import host_triage


def task():
    return {'task_id': 'T', 'host_triage_revision': host_triage.REVISION, 'host_triage': dict(host_triage.DEFAULTS)}


def timing(stage, start, wall, process):
    return {'stage': stage, 'elapsed_ms': process * 1000, 'started_at': '2026-10-13T03:%02d:00+00:00' % start,
            'finished_at': '2026-10-13T03:%02d:%02d+00:00' % (start + int(wall) // 60, int(wall) % 60)}


class SleepBudgetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, self.root, True)

    def write_timings(self, rows):
        (self.root / 'runtime-timings.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')

    def test_a_call_is_charged_its_awake_time(self):
        clocks = {'wall': 1000.0, 'awake': 50.0}
        with mock.patch.object(host_triage.time, 'time', side_effect=lambda: clocks['wall']), \
                mock.patch.object(host_triage.time, 'perf_counter', side_effect=lambda: clocks['awake']):
            with host_triage.analysis_budget(self.root, task()):
                clocks['wall'] += 1700     # 28 minutes asleep ...
                clocks['awake'] += 70      # ... and 70 seconds of work
        journal = load_json(self.root / host_triage.JOURNAL)
        self.assertEqual((journal['used_seconds'], journal['invocations']), (70.0, 1))
        self.assertIn('awake_since', journal)

    def test_sleep_an_earlier_version_charged_is_credited_back(self):
        self.write_timings([
            timing('provenance_host', 3, 1645, 68),       # slept 1577 s
            timing('discovery_review', 30, 400, 10),      # two parallel slots of one call: one sleep, counted once
            timing('discovery_review', 30, 395, 12),
            timing('text_triage', 50, 90, 60),            # 30 s apart: not sleep
            timing('candidate_merge', 52, 300, 1),        # not a host step: never charged to this allowance
        ])
        atomic_write_json(self.root / host_triage.JOURNAL, {'revision': host_triage.REVISION, 'task_id': 'T',
                                                             'used_seconds': 3600.0, 'invocations': 59})
        self.assertEqual(host_triage.remaining_seconds(self.root, task()), 1577 + 390)
        # a call under this version keeps the credit and charges only its own awake time
        with host_triage.analysis_budget(self.root, task()):
            pass
        journal = load_json(self.root / host_triage.JOURNAL)
        self.assertEqual(journal['sleep_credit_seconds'], 1577 + 390)
        self.assertAlmostEqual(host_triage.remaining_seconds(self.root, task()), 1967, delta=1)

    def test_steps_after_the_first_awake_charge_are_never_credited(self):
        self.write_timings([timing('comparison_host', 40, 900, 60)])
        atomic_write_json(self.root / host_triage.JOURNAL, {
            'revision': host_triage.REVISION, 'task_id': 'T', 'used_seconds': 3600.0, 'invocations': 3,
            'awake_since': '2026-10-13T03:10:00+00:00'})
        self.assertEqual(host_triage.remaining_seconds(self.root, task()), 0)
        with self.assertRaisesRegex(ValueError, 'ANALYSIS_BUDGET_EXHAUSTED'):
            with host_triage.analysis_budget(self.root, task()):
                pass

    def test_checkpoint_two_names_an_exhausted_allowance(self):
        import run_pipeline
        atomic_write_json(self.root / 'task.json', task())
        pipeline = run_pipeline.Pipeline(mock.Mock(task_dir=str(self.root), guard_session_id='s', chief=None))
        self.assertEqual(pipeline.analysis_budget_notice(), {})
        atomic_write_json(self.root / host_triage.JOURNAL, {'revision': host_triage.REVISION, 'task_id': 'T',
                                                             'used_seconds': 3528.0, 'invocations': 58})
        notice = pipeline.analysis_budget_notice()['analysis_budget']
        self.assertEqual((notice['remaining_seconds'], notice['limit_seconds']), (72, 3600))
        self.assertIn('不含电脑睡眠时间', notice['message'])


if __name__ == '__main__':
    unittest.main()

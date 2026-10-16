"""r5d21 time box: open work becomes a disclosed limitation instead of a checkpoint-2 stop (time-box-v1 tasks)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_pipeline as rp
import time_box

TASK = {'task_id': 'T', 'time_box_revision': time_box.REVISION}
ENTRIES = [{'work_id': 'WORK-A', 'kind': 'agent_investigation', 'state': 'awaiting_review', 'reason': 'SPECIALTY_FACT_REQUIRED',
            'scenario_id': 'S', 'jurisdiction': 'US', 'right_type': 'design', 'candidate_id': 'C1'},
           {'work_id': 'WORK-B', 'kind': 'source_lookup', 'state': 'submission_unknown', 'reason': 'VERIFY_PRIOR_SUBMISSION'},
           {'work_id': 'WORK-C', 'kind': 'user_information', 'state': 'awaiting_user', 'reason': 'OWN_BRAND'},
           {'work_id': 'WORK-D', 'kind': 'source_lookup', 'state': 'blocked', 'reason': 'SOURCE_RETRY_DEPENDENCY_REQUIRED'},
           {'work_id': 'WORK-E', 'kind': 'source_lookup', 'state': 'blocked', 'reason': 'BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED'}]


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='box-'))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_listed_open_work_becomes_a_bound_limitation(self):
        data = time_box.close(self.root, TASK, ENTRIES, active_seconds=1400, why='time_box', unestablished=['WORK-D'])
        self.assertEqual(data['work_ids'], ['WORK-A', 'WORK-B', 'WORK-D'])     # never a user wait or an established limit
        limit = time_box.limitation(TASK, ENTRIES[0], self.root)
        self.assertEqual((limit['state'], limit['reason'], limit['limitation_kind']), ('blocked', 'TIME_BOX_REACHED', 'time_box'))
        self.assertEqual(limit['budget_proof']['work_id'], 'WORK-A')
        self.assertIn('不代表', limit['reasoning'])
        self.assertIsNone(time_box.limitation(TASK, ENTRIES[2], self.root))
        self.assertIsNone(time_box.limitation(TASK, ENTRIES[4], self.root))
        self.assertIsNone(time_box.limitation(TASK, {**ENTRIES[0], 'work_id': 'WORK-NEW'}, self.root))
        self.assertIsNone(time_box.limitation({'task_id': 'T'}, ENTRIES[0], self.root))      # older tasks
        self.assertIsNone(time_box.limitation({**TASK, 'task_id': 'OTHER'}, ENTRIES[0], self.root))

    def test_the_budget_hook_projects_the_closure(self):
        import execution_budget
        time_box.close(self.root, TASK, ENTRIES, active_seconds=1400, why='time_box')
        view = execution_budget.project(TASK, {}, {'queries': {}}, {'entries': [dict(row) for row in ENTRIES]}, self.root)
        states = {row['work_id']: (row['state'], row['reason']) for row in view['entries']}
        self.assertEqual(states['WORK-A'], ('blocked', 'TIME_BOX_REACHED'))
        self.assertEqual(states['WORK-B'], ('blocked', 'TIME_BOX_REACHED'))
        self.assertEqual(states['WORK-C'], ('awaiting_user', 'OWN_BRAND'))
        projected = next(row for row in view['entries'] if row['work_id'] == 'WORK-A')
        self.assertEqual(projected['underlying_state'], 'awaiting_review')
        # the publication gate reads the same limit through execution_budget.delivery_limit
        self.assertEqual(execution_budget.delivery_limit(TASK, {}, {'queries': {}}, projected, self.root)['reason'],
                         'TIME_BOX_REACHED')
        untouched = execution_budget.project({'task_id': 'T'}, {}, {'queries': {}}, {'entries': [dict(ENTRIES[0])]}, self.root)
        self.assertEqual(untouched['entries'][0]['state'], 'awaiting_review')


class PipelineBoxTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='box-pipeline-'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.run_dir = self.base / 'RUN'
        self.run_dir.mkdir()
        (self.run_dir / 'task.json').write_text(json.dumps({**TASK, 'pipeline_robust_revision': 'robust-v1',
                                                            'candidate_precision_revision': 'precision-v1'}),
                                                encoding='utf-8')
        self.pipeline = rp.Pipeline(rp.parser().parse_args(['--task-dir', str(self.run_dir)]))
        self.calls = []
        self.pipeline.call = lambda stage, command, **kw: (self.calls.append((stage, Path(command[3]).name)) or (0, '{}', ''))

    def test_readiness_closes_the_box_and_goes_on_to_the_final_review(self):
        self.pipeline.state['active_seconds'] = 1500                  # past the 22-minute core limit
        ready = lambda: {'ready': (self.run_dir / time_box.RECORD).is_file(), 'blockers': [{'reason': 'X'}],
                         'publication_preparation': {'errors': ['EVIDENCE_LIMITATION_NOT_ESTABLISHED: WORK-D']}}
        with mock.patch.object(self.pipeline, 'ready', ready), \
                mock.patch('workflow_v24.work_view_from_dir', return_value={'entries': [dict(row) for row in ENTRIES]}):
            result = self.pipeline.s_readiness()
        self.assertTrue(result['ready'])
        self.assertEqual(result['time_box']['closed_work'], 3)
        self.assertEqual(result['time_box']['why'], 'time_box')
        record = json.loads((self.run_dir / time_box.RECORD).read_text(encoding='utf-8'))
        self.assertEqual(record['work_ids'], ['WORK-A', 'WORK-B', 'WORK-D'])
        self.assertNotIn(('readiness', 'comparison_host.py'), self.calls)   # no catch-up round after the limit

    def test_a_task_without_a_time_box_still_stops_at_checkpoint_2(self):
        (self.run_dir / 'task.json').write_text(json.dumps({'task_id': 'T'}), encoding='utf-8')
        with mock.patch.object(self.pipeline, 'ready', lambda: {'ready': False, 'blockers': [{'reason': 'X'}]}):
            with self.assertRaises(rp.Checkpoint):
                self.pipeline.s_readiness()
        self.assertFalse((self.run_dir / time_box.RECORD).exists())

    def test_sources_stop_starting_rounds_after_their_limit(self):
        counter = iter(range(1000))
        rounds = []
        with mock.patch.object(self.pipeline, 'source_round', lambda stage, robust: rounds.append(stage) or False), \
                mock.patch.object(self.pipeline, 'progress_signature', lambda: [next(counter)]), \
                mock.patch.object(self.pipeline, 'discovery_signature', lambda: [next(counter)]), \
                mock.patch.object(self.pipeline, 'ready', lambda: {'ready': False}), \
                mock.patch.object(self.pipeline, 'external_runs', lambda: ['ATT-1']), \
                mock.patch.object(self.pipeline, 'require_discovery_sources', lambda stage: None), \
                mock.patch.object(self.pipeline, 'flush_sources', lambda *a, **k: self.fail('no flush after the limit')):
            self.pipeline.state['active_seconds'] = 800                # past the 12-minute sources limit
            self.pipeline.s_sources()
        self.assertEqual(len(rounds), 1)
        self.assertEqual(self.pipeline.state['rounds'][-1].get('time_box'), 'sources_seconds')

    def test_precise_tasks_run_at_most_two_source_rounds(self):
        counter = iter(range(1000))
        rounds = []
        with mock.patch.object(self.pipeline, 'source_round', lambda stage, robust: rounds.append(stage) or False), \
                mock.patch.object(self.pipeline, 'progress_signature', lambda: [next(counter)]), \
                mock.patch.object(self.pipeline, 'discovery_signature', lambda: [next(counter)]), \
                mock.patch.object(self.pipeline, 'ready', lambda: {'ready': False}), \
                mock.patch.object(self.pipeline, 'external_runs', lambda: ['ATT-1']), \
                mock.patch.object(self.pipeline, 'require_discovery_sources', lambda stage: None), \
                mock.patch.object(self.pipeline, 'flush_sources', lambda *a, **k: []):
            self.pipeline.s_sources()
        self.assertEqual(len(rounds), rp.PRECISE_SOURCE_ROUNDS)


if __name__ == '__main__':
    unittest.main()

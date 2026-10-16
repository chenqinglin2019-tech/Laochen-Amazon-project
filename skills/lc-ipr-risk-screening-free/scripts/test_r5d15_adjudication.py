"""r5d15: pending-only rows that one review adds are settled by the program; an untouched draft is refreshed.

B0GLNPC6K8 r5d12 task, first finished final review: the second review added the optional own-brand word and logo
rows as pending (no brand name or logo supplied), the first left them out, and checkpoint 3 stopped on these two
rows. On a copy of the run the current rules settle them (0 open decisions) and the report publishes
(limited_round_closed).
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pipeline_robust
import prepare_adjudication as pa

ROBUST = {'pipeline_robust_revision': pipeline_robust.REVISION}


def row(right, *, risk=None, status='pending', candidate=None, reason='尚未提供拟用自有品牌名称。'):
    out = {'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': right, 'candidate_id': candidate,
           'assessment_object': 'own_brand', 'risk': risk, 'assessment_status': status}
    if status == 'pending':
        out['pending_reasoning'] = reason
    return out


class AutoCompleteTests(unittest.TestCase):
    def settle(self, task, reviewed):
        key = tuple(reviewed.get(k) for k in pa.UNIT_KEYS)
        decision = dict(reviewed, adjudication_reasoning='')
        with mock.patch('assessment_estimate.best_estimate_v2', return_value=False):
            agreed, _ = pa._auto_complete(task, {}, [decision], {}, {key: reviewed}, {}, [])
        return agreed, decision

    def test_a_pending_row_only_one_review_lists_is_carried_as_pending(self):
        agreed, decision = self.settle(ROBUST, row('trademark_word'))
        self.assertEqual(agreed, 1)
        self.assertIsNone(decision['risk'])
        self.assertIn('尚未提供拟用自有品牌名称', decision['adjudication_reasoning'])
        self.assertIn('不赋予风险等级', decision['adjudication_reasoning'])

    def test_graded_rows_candidates_and_older_tasks_stay_with_the_chief(self):
        for task, reviewed in ((ROBUST, row('trademark_word', risk='中', status='assessed')),
                               (ROBUST, row('patent', candidate='CAND-1')),
                               (ROBUST, row('trademark_word', reason='')),
                               ({}, row('trademark_word'))):
            agreed, decision = self.settle(task, reviewed)
            self.assertEqual((agreed, decision['adjudication_reasoning']), (0, ''))


class RefreshTests(unittest.TestCase):
    def pipeline(self, current, fresh):
        import run_pipeline
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, root, True)
        args = mock.Mock(task_dir=str(root), guard_session_id='s', chief='主审')
        pipeline = run_pipeline.Pipeline(args)
        path, sheet = root / 'adjudication.json', root / 'adjudication-worksheet.json'
        path.write_text(json.dumps(current, ensure_ascii=False), encoding='utf-8')
        sheet.write_text('{"old": true}', encoding='utf-8')

        def call(stage, command, **kwargs):
            out = Path(command[command.index('--output') + 1])
            out.write_text(json.dumps(fresh, ensure_ascii=False), encoding='utf-8')
            Path(command[command.index('--worksheet') + 1]).write_text('{"new": true}', encoding='utf-8')
            return 0, '', ''
        pipeline.call = call
        return pipeline, path, sheet

    @staticmethod
    def draft(*decisions):
        return {'reviewer': '主审', 'review_context': {'session_id': 's'}, 'decisions': list(decisions)}

    def test_an_untouched_draft_is_rebuilt(self):
        settled = dict(row('copyright', risk='低', status='assessed'), adjudication_reasoning='两审等级一致')
        current = self.draft(settled, dict(row('trademark_word'), adjudication_reasoning=''))
        fresh = self.draft(settled, dict(row('trademark_word'), adjudication_reasoning='照录为待判断'))
        pipeline, path, sheet = self.pipeline(current, fresh)
        self.assertTrue(pipeline.refresh_adjudication(path, sheet))
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), fresh)
        self.assertEqual(json.loads(sheet.read_text(encoding='utf-8')), {'new': True})
        self.assertEqual(sorted(p.name for p in path.parent.iterdir() if 'refresh' in p.name), [])

    def test_a_row_a_person_wrote_keeps_the_file(self):
        mine = dict(row('trademark_figurative'), adjudication_reasoning='主审：待用户提供 Logo 后再判断')
        current = self.draft(mine, dict(row('trademark_word'), adjudication_reasoning=''))
        fresh = self.draft(dict(mine, adjudication_reasoning='照录为待判断'),
                           dict(row('trademark_word'), adjudication_reasoning='照录为待判断'))
        pipeline, path, sheet = self.pipeline(current, fresh)
        self.assertFalse(pipeline.refresh_adjudication(path, sheet))
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), current)
        self.assertEqual(json.loads(sheet.read_text(encoding='utf-8')), {'old': True})


if __name__ == '__main__':
    unittest.main()

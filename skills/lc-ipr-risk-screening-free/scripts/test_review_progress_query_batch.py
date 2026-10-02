"""09A query-only atomic batching keeps exact single-completion gates and history."""
from copy import deepcopy
from unittest.mock import patch
import unittest
from common import atomic_write_json,load_json,sha256_json
from review_progress_stage_a import record_event,record_query_completions,ledger,_completion
import test_review_progress_stage_a as fixtures

class ReviewProgressBatchTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReviewProgressStageATest();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.plan['queries']['registry'].append({**self.f.row,'query_id':'Q2'})
        one=self.f.item(1,kind='query');two=self.f.item(2,kind='query');two['query_id']='Q2'
        self.f.event('initialize',items=[one,two])
        self.f.evidence['source_runs']=[{'run_id':'RUN-'+str(n),'provider':'registry','query_id':row['query_id'],
            'plan_entry_sha256':sha256_json(row),'submission_state':'submitted','status':'success'}
            for n,row in enumerate(self.f.plan['queries']['registry'],1)]
        self.f.evidence['collections']={'patents':[{'evidence_id':'EV-'+str(n),'source_run_id':'RUN-'+str(n)} for n in (1,2)]}
        self.f.save()
        self.requests=[{'kind':'complete','actor':'reader','reasoning':'Read exact retained response and candidate scope',
            'item_id':'ITEM-'+str(n),'source_run_id':'RUN-'+str(n),'evidence_refs':['RUN-'+str(n),'EV-'+str(n)]} for n in (1,2)]
        self.view={'status':'incomplete','entries':[{'kind':'agent_investigation','state':'awaiting_review','query_id':'Q1'}],
            'continuous_work':{'issues':self.f.open_issues}}
    def batch(self,requests=None):
        with patch('workflow_v24.work_view_from_dir',return_value=self.view) as view,patch('review_progress_stage_a._completion',wraps=_completion) as check:
            result=record_query_completions(self.f.path,self.requests if requests is None else requests)
            self.assertEqual(view.call_count,1);self.assertEqual(check.call_count,len(self.requests if requests is None else requests))
            self.assertTrue(all(call.args[5] is self.view for call in check.call_args_list))
        return result
    def test_two_exact_completions_use_one_real_view_and_keep_each_count_event(self):
        before=load_json(self.f.path/'evidence.json');events=self.batch();after=load_json(self.f.path/'evidence.json')
        self.assertEqual(len(events),2);self.assertEqual([e['version'] for e in events],[2,3])
        self.assertEqual([e['before']['completed'] for e in events],[0,1]);self.assertEqual([e['after']['completed'] for e in events],[1,2])
        result=ledger(self.f.task,after);self.assertEqual((result['completed'],result['planned'],result['percentage']),(2,2,100))
        self.assertEqual(after['source_runs'],before['source_runs']);self.assertEqual(after['collections'],before['collections'])
        self.assertEqual(after['review_progress_events'][0],before['review_progress_events'][0])
    def test_second_bad_ref_is_atomic_and_does_not_append_first(self):
        before=(self.f.path/'evidence.json').read_bytes();self.requests[1]['evidence_refs'].append('EV-MISSING')
        with patch('workflow_v24.work_view_from_dir',return_value=self.view):
            with self.assertRaisesRegex(ValueError,'VERIFIED_EVIDENCE_REFS_REQUIRED'):record_query_completions(self.f.path,self.requests)
        self.assertEqual((self.f.path/'evidence.json').read_bytes(),before)
    def test_wrong_plan_run_and_original_source_work_still_block(self):
        for mutation,error in [('plan','QUERY_PLAN_CHANGED'),('run','SUCCESSFUL_BOUND_RUN_REQUIRED'),('work','QUERY_WORK_REMAINS')]:
            with self.subTest(mutation=mutation):
                self.f.save();requests=deepcopy(self.requests);view=deepcopy(self.view)
                if mutation=='plan':
                    changed=deepcopy(self.f.plan);changed['queries']['registry'][1]['q']='different';atomic_write_json(self.f.path/'search-plan.json',changed)
                if mutation=='run':requests[1]['source_run_id']='RUN-1'
                if mutation=='work':view['entries'].append({'kind':'source_lookup','state':'ready','query_id':'Q2'})
                before=(self.f.path/'evidence.json').read_bytes()
                with patch('workflow_v24.work_view_from_dir',return_value=view):
                    with self.assertRaisesRegex(ValueError,error):record_query_completions(self.f.path,requests)
                self.assertEqual((self.f.path/'evidence.json').read_bytes(),before)
    def test_duplicate_and_issue_requests_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):record_query_completions(self.f.path,[self.requests[0],self.requests[0]])
        self.f.event('add',items=[self.f.item(3)],upstream_ref='RUN-1')
        request={**self.requests[0],'item_id':'ITEM-3'}
        with self.assertRaisesRegex(ValueError,'QUERY_ONLY'):record_query_completions(self.f.path,[request])
    def test_input_change_during_view_rejected_without_completion_write(self):
        before=(self.f.path/'evidence.json').read_bytes()
        def mutate(*args):
            changed=deepcopy(self.f.plan);changed['queries']['registry'][0]['q']='changed concurrently';atomic_write_json(self.f.path/'search-plan.json',changed)
            return self.view
        with patch('workflow_v24.work_view_from_dir',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'BATCH_INPUTS_CHANGED'):record_query_completions(self.f.path,self.requests)
        self.assertEqual((self.f.path/'evidence.json').read_bytes(),before)
    def test_retained_raw_change_during_view_rejected(self):
        raw=self.f.path/'source.json';raw.write_text('actual original fixture')
        self.f.evidence['source_runs'][0].update(raw_paths=[str(raw)],payload_digest='declared hash for byte binding');self.f.save()
        before=(self.f.path/'evidence.json').read_bytes()
        def mutate(*args):raw.write_text('changed original');return self.view
        with patch('workflow_v24.work_view_from_dir',side_effect=mutate):
            with self.assertRaisesRegex(ValueError,'BATCH_INPUTS_CHANGED'):record_query_completions(self.f.path,self.requests)
        self.assertEqual((self.f.path/'evidence.json').read_bytes(),before)
    def test_queries_in_separate_calls_do_not_share_work_view(self):
        with patch('workflow_v24.work_view_from_dir',return_value=self.view) as view:
            record_query_completions(self.f.path,[self.requests[0]])
            record_query_completions(self.f.path,[self.requests[1]])
        self.assertEqual(view.call_count,2)
        with patch('workflow_v24.work_view_from_dir',return_value=self.view):
            with self.assertRaisesRegex(ValueError,'COMPLETION_STATE_INVALID'):record_query_completions(self.f.path,[self.requests[0]])
    def test_empty_or_non_complete_batch_rejected(self):
        for requests in ([],{},[{**self.requests[0],'kind':'remove'}]):
            with self.assertRaisesRegex(ValueError,'QUERY_COMPLETE_BATCH_REQUIRED'):record_query_completions(self.f.path,requests)

if __name__=='__main__':unittest.main()

"""Physical API budgets retain debits and immutable logical reuse provenance."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from common import load_json, sha256_json
from candidate_api_actions import _budget_issue, _physical_planned, append
import test_lens_physical_reuse as lens_fixtures

class PhysicalBudgetTests(unittest.TestCase):
    def setUp(self):
        self.f=lens_fixtures.LensReuseTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.task=self.f.task
        self.task['serpapi_free_enhancement']['max_queries_per_task']=10
    def evidence(self):return load_json(self.f.root/'evidence.json')
    def physical(self,queries,evidence=None,plan=None):
        return _physical_planned(self.task,evidence or self.evidence(),queries,
            {'serpapi_google_lens','serpapi_google_patents'},plan=plan,task_dir=self.f.root)
    def test_exact_retained_response_and_bound_reuse_consume_one_actual_slot(self):
        self.f.reuse(); e=self.evidence()
        old={**self.f.row,'query_id':'old'}
        queries={'serpapi_google_lens':[old,self.f.row,{**self.f.row,'query_id':'pending'}]}
        self.assertEqual(self.physical(queries,e),[old])
        from serpapi_patents_client import consumed_queries
        self.assertEqual(consumed_queries(e),1)
        # Tampered retained bytes cannot release a pending slot or certify reuse.
        self.f.raw.write_text('{}')
        self.assertEqual(len(self.physical(queries,e)),3)
    def test_other_country_parameter_stale_failed_unknown_response_not_reused(self):
        self.assertEqual(self.physical({'serpapi_google_lens':[self.f.row]}),[])
        for change in ({'jurisdiction':'GB'},{'hl':'ja'},{'type':'visual_matches'}):
            row={**self.f.row,**change}
            self.assertEqual(self.physical({'serpapi_google_lens':[row]}),[row])
        for change in ({'status':'failed'},{'submission_state':'unknown'},
                {'finished_at':(datetime.now(timezone.utc)-timedelta(hours=49)).isoformat()}):
            e=self.evidence();e['source_runs'][0].update(change)
            self.assertEqual(self.physical({'serpapi_google_lens':[self.f.row]},e),[self.f.row])
    def test_only_valid_no_run_lens_wire_groups_and_unknown_submission_reserves(self):
        rows=[self.f.row,{**self.f.row,'query_id':'second','right_type':'design'}]
        e={'source_runs':[],'collections':{}}
        self.assertEqual(len(self.physical({'serpapi_google_lens':rows},e)),1)
        e['source_runs']=[{'provider':'serpapi_google_lens','query_id':'second','submission_state':'unknown','quota':{'network_request_attempted':False}}]
        self.assertEqual(len(self.physical({'serpapi_google_lens':rows},e)),2)
        self.assertEqual(len(self.physical({'serpapi_google_lens':[{'query_id':'A'},{'query_id':'B'}]},e)),2)
    def test_hashbound_cancellation_without_attempt_releases_only_reserved_slot(self):
        row={'query_id':'Q'};plan={'recall_integrity_revision':'recall-integrity-v1','queries':{'serpapi_google_patents':[row]}}
        # Use the production validator with the exact revision accepted by fixtures.
        import workflow_v24
        from common import RECALL_INTEGRITY_REVISION
        self.task['screening_revision']=plan['screening_revision']=RECALL_INTEGRITY_REVISION
        plan['schema_version']='2.4-free'
        plan['execution_dispositions']=[{'query_id':'Q','plan_entry_sha256':sha256_json(row),'status':'cancelled','reason':'withdrawn before submission'}]
        self.assertTrue(workflow_v24.validated_query_cancellation(self.task,plan,row))
        self.assertEqual(self.physical(plan['queries'],{'source_runs':[]},plan),[])
        for state in ['submitted','unknown','not_submitted']:
            e={'source_runs':[{'provider':'serpapi_google_patents','query_id':'Q','submission_state':state,'quota':{'network_request_attempted':state=='submitted'}}]}
            self.assertEqual(self.physical(plan['queries'],e,plan),[row])
        plan['execution_dispositions'][0]['plan_entry_sha256']='bad'
        self.assertEqual(self.physical(plan['queries'],{'source_runs':[]},plan),[row])
    def test_nine_actual_attempts_allow_last_slot_ten_still_hard_stop(self):
        e=self.evidence();e['source_runs'] += [{'provider':'serpapi_google_patents','query_id':'P'+str(i),'operation':'candidate_detail','quota':{'network_request_attempted':True}} for i in range(8)]
        queries={'serpapi_google_patents':[{'query_id':'P'+str(i)} for i in range(8)],'serpapi_google_lens':[self.f.row]}
        self.assertEqual(_budget_issue(self.task,e,queries,'serpapi_google_patents',task_dir=self.f.root),'')
        queries['serpapi_google_patents'].append({'query_id':'last'})
        self.assertEqual(_budget_issue(self.task,e,queries,'serpapi_google_patents',task_dir=self.f.root),'FREE_TASK_RESERVED_REQUEST_LIMIT_REACHED')
        e['source_runs'].append({'provider':'serpapi_google_patents','operation':'candidate_detail','quota':{'network_request_attempted':True}})
        self.assertEqual(_budget_issue(self.task,e,{},'serpapi_google_patents',task_dir=self.f.root),'FREE_TASK_REQUEST_LIMIT_REACHED')

class CandidateBudgetDriftTests(unittest.TestCase):
    def test_already_attempted_operation_precedes_budget_and_preserves_old_gap_signature(self):
        task={'retrieval_workflow_revision':'api-first-v3'}
        candidate={'candidate_id':'C','publication_number':'US1A1'}
        decision={**candidate,'scenario_id':'product_entry','jurisdiction':'US','right_type':'patent'}
        row={**decision,'query_id':'Q','operation':'candidate_detail','api_gap_revision':'api-first-v3'}
        queries={'serpapi_google_patents':[row]};evidence={'source_runs':[{'query_id':'Q'}]}
        with patch('trusted_api.accepted_verification',return_value={'complete':False,'missing':['rights_holder'],'evidence_refs':['E']}),patch('candidate_api_actions._origins',return_value=set()),patch('candidate_api_actions._budget_issue',side_effect=AssertionError('Already attempted must not inspect global budget')):
            gap=append(task,evidence,queries,candidate,decision,[],capabilities={'serpapi_google_patents':{'executable':True}})[0]
            gap['api_budget_limits']={'serpapi_google_patents':'FREE_TASK_PLAN_LIMIT_REACHED'}
            plan={'queries':queries,'candidate_action_gaps':[deepcopy(gap)]};original=deepcopy(plan)
            self.assertEqual(append(task,evidence,queries,candidate,decision,[],capabilities={'serpapi_google_patents':{'executable':True}},plan=plan),[gap])
            self.assertEqual(plan,original)
            # Actual facts/evidence changes cannot retain the old gap.
            plan['candidate_action_gaps'][0]['evidence_refs']=['changed']
            self.assertNotEqual(append(task,evidence,queries,candidate,decision,[],capabilities={'serpapi_google_patents':{'executable':True}},plan=plan),[gap])

class CandidatePlanPersistenceTests(unittest.TestCase):
    def test_v3_expand_returns_and_retains_candidate_action_writes(self):
        import test_scenario_planning as fixtures
        import workflow_v24
        from common import atomic_write_json, serper_free_enhancement, serpapi_free_enhancement
        f=fixtures.ScenarioPlanningTests();f.setUp();self.addCleanup(f.tearDown)
        f.task.update(retrieval_workflow_revision='api-first-v3',retrieval_policy={'enabled':True},
            serper_free_enhancement=serper_free_enhancement(False,'api-first-v3'),
            serpapi_free_enhancement=serpapi_free_enhancement(False,'api-first-v3'))
        atomic_write_json(f.path/'task.json',f.task)
        # Historical fixture; isolate persistence from already covered v3 contracts.
        def record(path,task,candidates,**kwargs):
            self.assertNotIn('gaps_only',kwargs)
            plan=load_json(path/'search-plan.json')
            plan['queries'].setdefault('serpapi_google_patents',[]).append({'query_id':'new-exact-api'})
            atomic_write_json(path/'search-plan.json',plan)
        with patch('workflow_v24.append_scenario_candidate_actions',side_effect=record), \
                patch('common.assert_active_free_policy'),patch('workflow_v24.assert_recall_planning_contract'):
            result=workflow_v24.generate_plan(f.path,expand=True)
        self.assertEqual(result,load_json(f.path/'search-plan.json'))
        self.assertIn('new-exact-api',[r['query_id'] for r in result['queries']['serpapi_google_patents']])

if __name__=='__main__':unittest.main()

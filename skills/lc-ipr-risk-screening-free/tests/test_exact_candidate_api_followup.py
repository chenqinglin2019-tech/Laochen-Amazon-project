"""Exact 05B selectors must retain identity and cannot expand discovery."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from candidate_followup import request_class


class ExactCandidateApiTests(unittest.TestCase):
    def test_serpapi_exact_wire_selector(self):
        params = {"q": "US20260048338A1", "publication_number": "US20260048338A1",
                  "candidate_id": "C1", "patent_id": "patent/US20260048338A1/en"}
        self.assertEqual(request_class("serpapi_google_patents", "candidate_detail", params), "targeted")
        for key, value in (("patent_id", "patent/US20260041061A1/en"),
                           ("include_related", True), ("foo", "extra")):
            self.assertNotEqual(request_class("serpapi_google_patents", "candidate_detail", {**params, key: value}), "targeted")
        self.assertNotEqual(request_class("other_api", "candidate_detail", params), "targeted")
        self.assertNotEqual(request_class("serpapi_google_patents", "search", params), "targeted")

    def test_ops_exact_restricted_section(self):
        params = {"q": "USD1127315S", "publication_number": "USD1127315S",
                  "document": "USD1127315S", "candidate_id": "C1", "detail_operation": "images",
                  "right_type": "design"}
        for section in ("images", "fulltext", "biblio", "legal"):
            self.assertEqual(request_class("epo_ops", "candidate_detail", {**params, "detail_operation": section}), "targeted")
        for key, value in (("document", "USD1127315S1"), ("detail_operation", "family"),
                           ("detail_operation", "other"), ("right_type", "enforcement")):
            self.assertNotEqual(request_class("epo_ops", "candidate_detail", {**params, key: value}), "targeted")

    def test_legacy_classification_unchanged(self):
        self.assertEqual(request_class("uspto_patent_browser", "candidate_verification",
                         {"q": "US11111111B2", "record_number": "US11111111B2"}), "targeted")
        self.assertEqual(request_class("epo_ops", "search", {"q": "toy ball"}), "discovery")

    def test_runner_can_compile_existing_content_sections(self):
        from run_api_plan import command_for
        for section in ("fulltext", "images"):
            item = {"q": "USD1127315S", "candidate_id": "C1", "query_id": "Q1",
                    "operation": "candidate_detail", "detail_operation": section,
                    "jurisdiction": "US", "right_type": "design"}
            command = command_for(Path('/scripts'), Path('/task'), 'epo_ops', item)
            self.assertEqual(command[command.index('--operation')+1], section)
        from serpapi_patent_details_client import _request_params
        self.assertEqual(_request_params({'patent_id':'patent/US123B1/en', 'candidate_id':'C1',
            'right_type':'patent', 'publication_number':'US123B1'})['publication_number'], 'US123B1')

    def test_v3_gap_route_is_planned_without_changing_canonical(self):
        import workflow_v24 as planner
        import decision_workflow
        from copy import deepcopy
        for provider, params in (
            ('epo_ops', {'q':'US123B1','document':'US123B1','detail_operation':'fulltext','candidate_id':'C1'}),
            ('serpapi_google_patents', {'q':'US123B1','publication_number':'US123B1','patent_id':'patent/US123B1/en','candidate_id':'C1'})):
            task={'retrieval_workflow_revision':'api-first-v3','coverage_requirements':[
                {'requirement_id':'COV-US-PATENT-VERIFY','jurisdiction':'US','right_type':'patent',
                 'phase':'candidate_verification','routes':[],
                 'gap_only_routes':[{'provider':'epo_ops','operation':'candidate_detail'}]}]}
            original=deepcopy(task['coverage_requirements'])
            candidate={'candidate_id':'C1','jurisdiction':'US','right_type':'patent'}
            action={'action_id':'A1','kind':'source_lookup','provider':provider,'operation':'candidate_detail',
                    'params':params,'purpose':'read missing claims','max_attempts':1,
                    'required_facts':['protection_content'],'reading_scope':{'level':'protection_content'}}
            record={'candidate_id':'C1','scenario_id':'product_entry','jurisdiction':'US','right_type':'patent',
                    'current':True,'decision':'needs_info','next_actions':[action]}
            with tempfile.TemporaryDirectory() as temp:
                folder=Path(temp)
                (folder/'search-plan.json').write_text(json.dumps({'queries':{}}))
                with patch.object(planner,'assert_recall_planning_contract'), \
                     patch.object(planner,'_scenario_context',return_value=({}, {}, {})), \
                     patch.object(planner,'scenario_supplement',return_value=None), \
                     patch.object(planner,'correction_enabled',return_value=True), \
                     patch.object(planner,'reconcile_scenario_actions'), \
                     patch.object(planner,'bind_scenario_action',side_effect=lambda task,provider,row,**kwargs:row), \
                     patch.object(decision_workflow,'triage_summary',return_value={'records':[record]}), \
                     patch.object(decision_workflow,'scenario_index',return_value={'product_entry':{}}), \
                     patch.object(decision_workflow,'necessary_scenario_right_types',return_value={'patent'}), \
                     patch.object(decision_workflow,'triage_scope_enabled',return_value=False), \
                     patch('common.provider_execution_error',return_value=''):
                    planner.append_scenario_candidate_actions(folder,task,{'patents':[candidate]})
                plan=json.loads((folder/'search-plan.json').read_text())
                self.assertEqual(len(plan['queries'][provider]),1)
                self.assertFalse(plan['candidate_action_gaps'])
                self.assertEqual(task['coverage_requirements'],original)

    def test_runtime_details_does_not_enter_discovery_followup(self):
        import test_workflow_v24
        import runtime_v24
        import subprocess
        from common import atomic_write_json
        from workflow_v24 import generate_plan
        fixture=test_workflow_v24.WorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        plan=generate_plan(fixture.path)
        row={**plan['queries']['serpapi_google_patents'][0], 'operation':'candidate_detail',
             'q':'US123B1','candidate_id':'C1','patent_id':'patent/US123B1/en','required':False}
        row.pop('fallback_query_id',None)
        plan['queries']={'serpapi_google_patents':[row]}
        atomic_write_json(fixture.path/'search-plan.json',plan)
        with patch('runtime_v24.capabilities',return_value=[{'provider':'serpapi_google_patents','executable':True}]), \
             patch('workflow_v24.validated_discovery_followup',side_effect=AssertionError('Details must not discover')) as followup, \
             patch('run_api_plan.command_for',return_value=['offline-details']), \
             patch('runtime_v24.subprocess.run',return_value=subprocess.CompletedProcess([],2,
                   '{"status":"access_limited","error_code":"OFFLINE_ONLY"}','')) as network:
            runtime_v24.execute_api_plan(fixture.path)
        followup.assert_not_called()
        network.assert_called_once()

    def test_exact_gap_error_receipt_is_saved_and_mismatches_rejected(self):
        import test_workflow_v24
        from common import (atomic_write_json, load_json, load_skill_config,
                            serper_free_enhancement, serpapi_free_enhancement, signa_free_enhancement)
        from coverage_v3 import build_requirements
        from workflow_v24 import build_coverage_requirements_v24
        from provider_utils import record_error, ProviderError, coverage_route_policy, require_provider_operation
        fixture=test_workflow_v24.WorkflowTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        task=fixture.task
        task.update(retrieval_workflow_revision='api-first-v3',
            decision_workflow_revision='scenario-triage-v1',workflow_correction_revision='workflow-correction-v1',
            retrieval_policy=load_skill_config()['api_first'],
            serper_free_enhancement=serper_free_enhancement(),
            serpapi_free_enhancement=serpapi_free_enhancement(),
            signa_free_enhancement=signa_free_enhancement())
        task['coverage_requirements']=build_requirements(task,build_coverage_requirements_v24(task['target_jurisdictions']))
        row={'query_id':'EXACT-GAP','operation':'candidate_detail','jurisdiction':'US','right_type':'design',
             'q':'USD123S','document':'USD123S','detail_operation':'images','candidate_id':'C1',
             'required':False,'execute_by_default':True,'execution_phase':'needs_info',
             'action_purpose':'needs_info:read exact missing figure','triage_action_id':'A1','triage_candidate_id':'C1',
             'requirement_ids':['COV-US-DESIGN-RECALL']}
        atomic_write_json(fixture.path/'task.json',task)
        atomic_write_json(fixture.path/'search-plan.json',{**task,'queries':{'epo_ops':[row]}})
        params={key:row[key] for key in ('q','document','detail_operation','candidate_id','right_type')}
        self.assertFalse(coverage_route_policy(task,'epo_ops','candidate_detail',jurisdiction='US',right_type='design')[0])
        # Current 05B authorization is independently covered by the workflow
        # suite. Here the real recorder, exact wire binding and saved receipt
        # are exercised without introducing synthetic business decisions.
        with patch('provider_utils.authorize_current_scenario_action') as current:
            run=record_error(fixture.path,provider='epo_ops',operation='candidate_detail',query=row['q'],
                jurisdiction='US',evidence_type='patent',error_value=ProviderError('OFFLINE_GAP','access_limited','No image returned'),
                request_params=params,query_id=row['query_id'],submission_state='not_submitted')
            self.assertGreaterEqual(current.call_count,1)
            before=(fixture.path/'evidence.json').read_bytes()
            with self.assertRaisesRegex(ProviderError,'differs from the selected plan entry'):
                record_error(fixture.path,provider='epo_ops',operation='candidate_detail',query=row['q'],
                    jurisdiction='US',evidence_type='patent',error_value=ProviderError('OFFLINE_GAP','access_limited','Mismatch'),
                    request_params={**params,'candidate_id':'other'},query_id=row['query_id'],submission_state='not_submitted')
            self.assertEqual((fixture.path/'evidence.json').read_bytes(),before)
        self.assertEqual(run['status'],'access_limited')
        self.assertEqual(run['submission_state'],'not_submitted')
        self.assertEqual(load_json(fixture.path/'evidence.json')['source_runs'][-1]['run_id'],run['run_id'])
        with self.assertRaisesRegex(ProviderError,'not configured'):
            require_provider_operation(task,'epo_ops','candidate_detail',jurisdiction='US',right_type='design')
        with self.assertRaises(ProviderError):
            require_provider_operation({**task,'retrieval_workflow_revision':'api-first-v2'},'epo_ops','candidate_detail',
                jurisdiction='US',right_type='design',task_dir=fixture.path,query_id=row['query_id'],query=row['q'],request_params=params)


if __name__ == "__main__":
    unittest.main()

"""V3 plan quotas release only slots proven bound to an existing request."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import test_lens_physical_reuse as fixture
from common import (atomic_write_json, load_json, sha256_json, serpapi_plan_physical_slots,
                    authorize_serpapi_free_plan_entry, default_discovery_plan_error)
from runtime_v24 import _reuse_physical_response
from trusted_api import annotate_entry


class PhysicalPlanLimitTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.LensReuseTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root, self.task = self.f.root, self.f.task
        self.task['task_id'] = 'TEST-PHYSICAL'
        original_row = {**self.f.row, 'query_id':'old', 'right_type':'design'}
        self.f.original['plan_entry_sha256'] = sha256_json(original_row)
        self.f.entry['plan_entry_sha256'] = sha256_json(original_row)
        annotate_entry(self.task, self.f.entry, self.f.original)
        self.f.save()
        self.patents = [{'query_id':'P'+str(i), 'operation':'candidate_detail', 'required':False,
            'candidate_id':'C'+str(i), 'q':'US123'+str(i)+'B1', 'patent_id':'patent/US123'+str(i)+'B1/en'}
            for i in range(7)]
        reused_rows = [{**self.f.row, 'query_id':'reuse-'+str(i), 'right_type':right}
                       for i, right in enumerate(('copyright','trade_dress','design'))]
        self.plan = {**deepcopy(self.task), 'queries':{
            'serpapi_google_patents':self.patents, 'serpapi_google_lens':[original_row]+reused_rows}}
        atomic_write_json(self.root/'search-plan.json', self.plan)
        for row in reused_rows:
            params = {key:value for key,value in self.f.params.items()}
            params['right_type'] = row['right_type']
            reused = _reuse_physical_response(self.root, 'serpapi_google_lens', row, 48,
                authorized_task=self.task, authorized_params=params)
            self.assertIsNotNone(reused)
        evidence = load_json(self.root/'evidence.json')
        evidence.update(task_id=self.task['task_id'], schema_version=self.task['schema_version'])
        atomic_write_json(self.root/'evidence.json', evidence)

    def slots(self, plan=None, task=None):
        return serpapi_plan_physical_slots(task or self.task, plan or self.plan, task_dir=self.root)

    def authorize(self, *, plan=None, task=None, context=True):
        with patch('common.provider_execution_error', return_value=''), \
             patch('common.plan_free_policy_matches_task', return_value=True):
            return authorize_serpapi_free_plan_entry(task or self.task, plan or self.plan,
                'candidate_detail', 'P0', **({'task_dir':self.root} if context else {}))

    def test_eleven_logical_rows_are_eight_physical_slots(self):
        self.assertEqual(self.slots(), 8)
        self.assertEqual(self.authorize(), self.patents[0])
        with patch('common.uses_optional_commercial_discovery', return_value=True), \
             patch('common.plan_free_policy_matches_task', return_value=True), \
             patch('common.serper_free_enabled', return_value=False), \
             patch('common.signa_free_enabled', return_value=False), \
             patch('common.serpapi_free_enabled', return_value=True), \
             patch('common.provider_execution_error', return_value=''):
            plan={**self.plan,'execution_policy':{'commercial_freemium_allowlist':['serpapi'],
                'commercial_providers_enabled':True,'paid_execution_enabled':False}}
            self.assertEqual(default_discovery_plan_error(self.task,plan,task_dir=self.root), '')

    def test_no_context_and_old_revision_remain_conservative(self):
        self.assertEqual(serpapi_plan_physical_slots(self.task,self.plan),11)
        with self.assertRaisesRegex(ValueError,'SERPAPI_TASK_QUERY_LIMIT_EXCEEDED'):
            self.authorize(context=False)
        old={**self.task,'retrieval_workflow_revision':'api-first-v2'}
        self.assertEqual(self.slots(task=old),11)
        plan={**self.plan,'retrieval_workflow_revision':'api-first-v2'}
        with self.assertRaisesRegex(ValueError,'SERPAPI_TASK_QUERY_LIMIT_EXCEEDED'):
            self.authorize(task=old,plan=plan)

    def test_real_retained_response_can_reserve_future_logical_reuse(self):
        evidence=load_json(self.root/'evidence.json')
        evidence['source_runs']=[evidence['source_runs'][0]]
        atomic_write_json(self.root/'evidence.json',evidence)
        self.assertEqual(self.slots(),8)
        self.assertEqual(self.authorize(),self.patents[0])
        self.f.raw.write_text('{}')
        # No verified reuse remains; three future same-wire logical actions
        # reserve one NEW physical attempt, in addition to the old debit.
        self.assertEqual(self.slots(),9)
        self.assertEqual(self.authorize(),self.patents[0])

    def test_changed_material_or_unknown_original_submission_rejects(self):
        evidence=load_json(self.root/'evidence.json')
        evidence['source_runs'][0]['submission_state']='unknown'
        atomic_write_json(self.root/'evidence.json',evidence)
        self.assertEqual(self.slots(),11)
        self.f.raw.write_text('{}')
        with self.assertRaisesRegex(ValueError,'SERPAPI_TASK_QUERY_LIMIT_EXCEEDED'):
            self.authorize()

    def test_raw_and_original_receipt_tampering_do_not_release_slots(self):
        original=load_json(self.root/'evidence.json')
        for change in ({'finished_at':'2020-01-01T00:00:00Z'},
                       {'request_params':{**self.f.original['request_params'],'country':'jp'}}):
            with self.subTest(change=change):
                evidence=deepcopy(original)
                evidence['source_runs'][0].update(change)
                atomic_write_json(self.root/'evidence.json',evidence)
                self.assertEqual(self.slots(),11)
                with self.assertRaisesRegex(ValueError,'SERPAPI_TASK_QUERY_LIMIT_EXCEEDED'):
                    self.authorize()
        atomic_write_json(self.root/'evidence.json',original)
        self.f.raw.write_text('{}')
        self.assertEqual(self.slots(),11)
        with self.assertRaisesRegex(ValueError,'SERPAPI_TASK_QUERY_LIMIT_EXCEEDED'):
            self.authorize()

    def test_actual_eleven_and_retry_requests_still_exceed(self):
        plan=deepcopy(self.plan)
        plan['queries']['serpapi_google_patents'].extend(
            [{**self.patents[0],'query_id':'extra-'+str(i)} for i in range(3)])
        self.assertEqual(self.slots(plan),11)
        with self.assertRaisesRegex(ValueError,'SERPAPI_TASK_QUERY_LIMIT_EXCEEDED'):
            self.authorize(plan=plan)
        evidence=load_json(self.root/'evidence.json')
        evidence['source_runs'].extend([{**self.f.original,'run_id':'retry-'+str(i)} for i in range(3)])
        atomic_write_json(self.root/'evidence.json',evidence)
        self.assertEqual(self.slots(),11)
        with self.assertRaisesRegex(ValueError,'SERPAPI_TASK_QUERY_LIMIT_EXCEEDED'):
            self.authorize()


if __name__=='__main__':
    unittest.main()

"""Validated asset investigations are not fabricated database zero results."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from assessment_estimate import _recall_refs, _apply_recall_integrity
from common import sha256_file, sha256_json
from record_asset_provenance import asset_scope, INVESTIGATION_STEPS
import test_asset_scope


class AssetSufficiencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        original = test_asset_scope.AssetScopeTests()
        original.setUp()
        self.task = original.task
        self.task['screening_revision'] = 'recall-integrity-v1'
        self.path = Path(self.temp.name) / 'source.png'
        # Deliberately synthetic retained bytes: this test exercises binding,
        # never submits these objects as production investigation evidence.
        self.path.write_bytes(b'synthetic-image-binding-fixture')
        self.digest = sha256_file(self.path)
        self.registry = {'EV-PRODUCT': {'kind': 'provenance_document', 'path': str(self.path),
            'sha256': self.digest, 'source_url': 'https://example.org/fixture'}}
        self.runs, self.queries, self.checked = {}, [], []
        self.row = {'scenario_id':'product_entry', 'jurisdiction':'US', 'right_type':'copyright',
            'candidate_id':'', 'risk':'低', 'assessment_status':'assessed', 'reasoning':'Only observed functional body',
            'evidence_refs':[], 'counter_evidence':[]}
        self.row['scenario_sha256'] = self.task['assessment_scenarios'][0]['scenario_sha256']
        self.add_steps('copyright')

    def add_steps(self, right):
        self.row['right_type'] = right
        scope = asset_scope(self.task, 'product_entry', right)
        self.runs, self.queries, self.checked = {}, [], []
        for dimension in INVESTIGATION_STEPS[right]:
            qid, rid, eid = 'Q-' + dimension, 'R-' + dimension, 'EV-' + dimension
            query = {'query_id':qid,'operation':'provenance_review','jurisdiction':'US','right_type':right,
                'action_purpose':'provenance','execution_phase':'initial','search_dimension':dimension,
                'decision_workflow_revision':'scenario-triage-v1','scenario_id':'product_entry',
                'scenario_sha256':self.row['scenario_sha256'],'asset_scope_sha256':scope['scope_sha256']}
            run = {'run_id':rid,'provider':'asset_provenance','status':'success',
                **{k:query[k] for k in ('query_id','operation','jurisdiction','right_type')},
                'plan_entry_sha256':sha256_json(query)}
            payload = {'scenario_id':'product_entry','asset_scope_sha256':scope['scope_sha256'],
                'coverage_attestation':{'inventory_complete':True,'asset_ids':scope['asset_ids'],
                    'reviewed_asset_ids':scope['asset_ids']},
                'unresolved':['No private ownership or licence records supplied'], 'outstanding_actions':[],
                'artifacts':[{'path':str(self.path),'sha256':self.digest,'bytes':self.path.stat().st_size,'role':'source'}],
                'investigation_steps':[{'step':dimension,'status':'completed','reasoning':'Original actually read in fixture',
                    'artifact_sha256':[self.digest],'evidence_refs':['EV-PRODUCT']}]}
            self.registry[eid] = {'evidence_id':eid,'source_run_id':rid,'payload':payload,
                **{k:run[k] for k in ('provider','query_id','operation','jurisdiction','right_type','plan_entry_sha256')}}
            self.runs[rid] = run
            self.queries.append(query)
            self.checked.append({'query_id':qid,'complete':True,'investigation_status':'completed','evidence_refs':[eid]})
        self.row['evidence_refs'] = [ref for item in self.checked for ref in item['evidence_refs']]
        self.row['search_comparison'] = {'reasoning':'Actual scoped expression/function comparison',
            'evidence_refs':list(self.row['evidence_refs'])}

    def recall(self):
        scope = {k:self.row[k] for k in ('scenario_id','scenario_sha256','jurisdiction','right_type')}
        scope['queries'] = self.checked
        return _recall_refs(self.row,[scope],self.registry,self.runs,self.task,{'queries':{'asset_provenance':self.queries}})

    def test_completed_real_steps_with_unknown_legal_facts_are_comparison_refs(self):
        self.assertEqual(self.recall(), {'EV-visual_comparison'})
        self.assertTrue(self.registry['EV-visual_comparison']['payload']['unresolved'])
        self.add_steps('trade_dress')
        self.assertEqual(self.recall(), {'EV-functionality'})

    def test_partial_failed_placeholder_or_wrong_scope_cannot_support_low(self):
        mutations = [
            lambda: self.checked.pop(0),
            lambda: self.checked[0].update(complete=False),
            lambda: self.runs['R-visual_comparison'].update(status='failed'),
            lambda: self.runs['R-visual_comparison'].update(error_code='BROWSER_RATE_LIMITED'),
            lambda: self.registry['EV-visual_comparison']['payload'].update(artifacts=[]),
            lambda: self.registry['EV-visual_comparison']['payload'].update(investigation_steps=[]),
            lambda: self.registry['EV-visual_comparison']['payload'].update(scenario_id='brand_reuse'),
            lambda: self.registry['EV-visual_comparison']['payload'].update(asset_scope_sha256='stale'),
            lambda: self.registry['EV-visual_comparison']['payload'].update(outstanding_actions=['read missing original']),
            lambda: self.registry['EV-visual_comparison']['payload']['coverage_attestation'].update(reviewed_asset_ids=[]),
            lambda: self.registry['EV-visual_comparison']['payload']['artifacts'][0].update(sha256='0'*64),
            lambda: self.queries[1].update(scenario_sha256='stale'),
            lambda: self.queries[1].update(asset_scope_sha256='stale'),
            lambda: self.queries[1].update(q='different planned query'),
            lambda: self.queries[1].update(execution_phase='verification',triage_candidate_id='C1'),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.add_steps('copyright')
                mutate()
                self.assertEqual(self.recall(), set())

    def test_missing_marker_empty_inventory_and_candidate_do_not_gain_clearance(self):
        self.task.pop('specialty_workflow_revision')
        self.assertEqual(self.recall(), set())
        self.task['specialty_workflow_revision']='asset-scope-v1'
        self.row['candidate_id']='C1'
        self.assertEqual(self.recall(), set())
        self.row['candidate_id']=''
        self.task['product']['assets']=[]
        self.assertEqual(self.recall(), set())

    def test_sufficiency_keeps_only_the_scoped_row_not_an_overall_grade(self):
        scope = {k:self.row[k] for k in ('scenario_id','scenario_sha256','jurisdiction','right_type')}
        scope['queries']=self.checked
        scoped=deepcopy(self.row)
        with patch('workflow_v24.product_analysis_readiness',return_value={'gaps':[],'patent_claim_followup':{}}):
            _apply_recall_integrity([scoped],self.task,{'source_runs':list(self.runs.values())},{},
                {'queries':{'asset_provenance':self.queries}},[scope],self.registry,sufficiency_only=True)
        self.assertEqual(scoped['risk'],'低')
        self.assertNotIn('overall',scoped)
        self.assertNotIn('business_completion',scoped)
        self.row['search_comparison']['evidence_refs']=['EV-provenance']
        scoped=deepcopy(self.row)
        with patch('workflow_v24.product_analysis_readiness',return_value={'gaps':[],'patent_claim_followup':{}}):
            _apply_recall_integrity([scoped],self.task,{'source_runs':list(self.runs.values())},{},
                {'queries':{'asset_provenance':self.queries}},[scope],self.registry,sufficiency_only=True)
        self.assertIsNone(scoped['risk'])


if __name__ == '__main__':
    unittest.main()

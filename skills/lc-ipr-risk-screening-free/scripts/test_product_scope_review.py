"""Complete-product scope contracts; all fixtures are synthetic, no model calls."""
from copy import deepcopy
import json, unittest
from common import CURRENT_SCHEMA_VERSION, RECALL_INTEGRITY_REVISION, sha256_json
import assessment_estimate as estimates
from decision_workflow import default_assessment_scenarios, scenario_right_types
from record_independent_review import MODULE_BY_RIGHT
from report_review_host import review_prompt
import test_module_review as fixtures

class ProductScopeReviewTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ModuleReviewTests();f.setUp();self.addCleanup(f.tearDown)
        self.task={'schema_version':CURRENT_SCHEMA_VERSION,'screening_revision':RECALL_INTEGRITY_REVISION,
            'task_id':'SYNTHETIC','execution_policy_revision':'continuous-work-v2',
            'decision_workflow_revision':'scenario-triage-v1','primary_scenario_id':'product_entry',
            'assessment_scenarios':default_assessment_scenarios(),'target_jurisdictions':['US','GB']}
        self.rows=[]
        for s in self.task['assessment_scenarios']:
            for country in self.task['target_jurisdictions']:
                for right in sorted(scenario_right_types(s)):
                    r=deepcopy(f.legal_record()['judgment']['assessments'][0])
                    r.update(scenario_id=s['scenario_id'],scenario_sha256=s['scenario_sha256'],
                        jurisdiction=country,right_type=right,module_id=MODULE_BY_RIGHT[right],
                        risk=None,assessment_status='pending',pending_reasoning='Synthetic missing original',evidence_refs=[])
                    self.rows.append(r)
    def review(self, rows):
        return {'reviewer':'synthetic','review_context':{'session_id':'S','evidence_digest':'D',
            'first_review_visible':False,'execution':{'agent_id':'S','run_id':'R','input_digest':'D',
                'assessment_digest':sha256_json(rows),'host_audit':{'synthetic':True}}},'coverage_confidence_cap':'低',
            'coverage_confidence_reasoning':'Synthetic gaps','assessments':rows}
    def validate(self, rows, task=None, candidates=None):
        estimates._validate_review(self.review(rows),'D',{'E'},candidates or {},{'US','GB'},task or self.task)
    def test_all_pending_overall_scopes_remain_acceptable(self):self.validate(self.rows)
    def test_every_country_scenario_and_right_is_required_per_review(self):
        for i,r in enumerate(self.rows):
            with self.subTest(scope=(r['scenario_id'],r['jurisdiction'],r['right_type'])):
                with self.assertRaisesRegex(ValueError,'REVIEW_PRODUCT_SCOPE_MISSING'):self.validate(self.rows[:i]+self.rows[i+1:])
    def test_own_brand_cannot_replace_product_word_mark(self):
        rows=deepcopy(self.rows);rows[6]['assessment_object']='own_brand'
        self.assertEqual(rows[6]['right_type'],'trademark_word')
        with self.assertRaisesRegex(ValueError,'REVIEW_PRODUCT_SCOPE_MISSING'):self.validate(rows)
    def test_inferred_own_brand_is_not_default_product(self):
        rows=deepcopy(self.rows);rows[6]['scope_exclusion_basis']='unknown_own_brand'
        with self.assertRaisesRegex(ValueError,'REVIEW_PRODUCT_SCOPE_MISSING'):self.validate(rows)
    def test_specific_candidate_cannot_replace_product_scope(self):
        rows=deepcopy(self.rows);i=next(i for i,r in enumerate(rows) if r['right_type']=='patent');rows[i]['candidate_id']='C'
        with self.assertRaisesRegex(ValueError,'REVIEW_PRODUCT_SCOPE_MISSING'):
            self.validate(rows,candidates={'C':('patents',{'candidate_id':'C','right_type':'patent'})})
    def test_signal_only_cannot_replace_current_product_scope(self):
        rows=deepcopy(self.rows);rows[0].update(signal_only=True,assessment_status='assessed',evidence_refs=['E'])
        with self.assertRaisesRegex(ValueError,'REVIEW_PRODUCT_SCOPE_MISSING'):self.validate(rows)
    def test_additional_own_brand_scope_is_acceptable(self):
        self.validate(self.rows+[dict(self.rows[6],assessment_object='own_brand')])
    def test_explicit_task_exclusion_is_an_explained_product_scope(self):
        rows=deepcopy(self.rows);rows[0].update(out_of_scope=True,scope_reasoning='Explicit synthetic exclusion')
        task=deepcopy(self.task);task['assessment_scope_exclusions']=[dict(rows[0],reasoning='Synthetic task exclusion')]
        self.validate(rows,task)
    def test_institutional_inapplicability_does_not_remove_scope(self):
        rows=deepcopy(self.rows);rows[0]['scope_applicability']={'status':'not_applicable','reasoning':'Synthetic source','evidence_refs':['E']};rows[0]['evidence_refs']=['E']
        self.validate(rows)
        with self.assertRaisesRegex(ValueError,'REVIEW_PRODUCT_SCOPE_MISSING'):self.validate(rows[1:])
    def test_historical_unmarked_manual_policy_is_not_silently_migrated(self):
        task=deepcopy(self.task);task.pop('execution_policy_revision');review=self.review(self.rows[:1]);review['review_context']['execution'].pop('host_audit')
        estimates._validate_review(review,'D',{'E'},{},{'US','GB'},task)
    def test_native_host_attestation_still_requires_complete_scope(self):
        task=deepcopy(self.task);task.pop('execution_policy_revision');review=self.review(self.rows[:-1]);review['review_context']['execution']['host_audit']={'synthetic':True}
        with self.assertRaisesRegex(ValueError,'REVIEW_PRODUCT_SCOPE_MISSING'):
            estimates._validate_review(review,'D',{'E'},{},{'US','GB'},task)
    def test_current_task_remains_full_without_receipt_audit(self):
        review=self.review(self.rows[:-1]);review['review_context']['execution'].pop('host_audit')
        with self.assertRaisesRegex(ValueError,'REVIEW_PRODUCT_SCOPE_MISSING'):
            estimates._validate_review(review,'D',{'E'},{},{'US','GB'},self.task)
    def test_current_contract_does_not_depend_on_unbound_execution_flag(self):
        task=deepcopy(self.task);task['completion_policy_revision']='necessary-work-v3';task.pop('execution_policy_revision')
        review=self.review(self.rows[:-1]);review['review_context']['execution'].pop('host_audit')
        self.assertTrue(estimates.complete_product_review_required(task))
        with self.assertRaisesRegex(ValueError,'REVIEW_PRODUCT_SCOPE_MISSING'):
            estimates._validate_review(review,'D',{'E'},{},{'US','GB'},task)
    def test_digest_bound_legacy_stage_contract_accepts_its_partial_rows(self):
        task=deepcopy(self.task);task['completion_policy_revision']='necessary-work-v2'
        review=self.review(self.rows[:1]);review['review_context']['execution'].pop('host_audit')
        estimates._validate_review(review,'D',{'E'},{},{'US','GB'},task)
        self.assertFalse(estimates.complete_product_review_required(task))
    def test_invalid_audit_is_not_a_stage_opt_in(self):
        review=self.review(self.rows);review['review_context']['execution']['host_audit']='broken'
        with self.assertRaisesRegex(ValueError,'REVIEW_EXECUTION_AUDIT_INVALID'):
            estimates._validate_review(review,'D',{'E'},{},{'US','GB'},self.task)
    def test_stage_contract_cannot_disable_module_full_scope(self):
        task=deepcopy(self.task);task.update(completion_policy_revision='necessary-work-v2',final_review_execution_revision='module-double-review-v1')
        self.assertTrue(estimates.complete_product_review_required(task))
    def test_prompt_contract_matches_common_required_scope_definition(self):
        for slot in (1,2):
            for group in (None,{'right_types':['patent','utility_model'],'required_scopes':[]}):
                p={'task':self.task}
                if group:p['module_scope']=group
                prompt=review_prompt(p,slot)
                contract=json.loads(prompt.split('\n输出契约：\n',1)[1].split('\n材料包（审阅位 ',1)[0])
                scopes=contract['required_product_scopes'];rights=set(group['right_types']) if group else None
                expected=estimates.required_product_scopes(self.task,rights)
                self.assertEqual([{k:r[k] for k in ('scenario_id','jurisdiction','right_type')} for r in scopes],expected)
                self.assertTrue(all(r['assessment_object']=='product' for r in scopes));self.assertIn('own_brand不能替代',prompt)
                self.assertTrue(all(r['candidate_id'] is None for r in scopes))
    def test_module_scope_definition_delegates_to_shared_definition(self):
        import module_review
        self.assertEqual(module_review.required_scopes(self.task,module_review.GROUPS['technical']),
                         estimates.required_product_scopes(self.task,module_review.GROUPS['technical']))
    def test_empty_scope_definition_preserves_pre_scenario_tasks(self):
        self.assertEqual(estimates.required_product_scopes({'target_jurisdictions':['US']}),[])

if __name__=='__main__':unittest.main()

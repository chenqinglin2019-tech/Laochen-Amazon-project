"""Scenario/object investigation hints preserve coverage and historical semantics."""
from copy import deepcopy
import unittest
from common import sha256_json
from execution_efficiency import LEGACY_REVISION
from investigation_policy import project_work, resolve_discovery_work_policy, order_discovery_terms
import test_execution_efficiency


class InvestigationScopeV2Tests(unittest.TestCase):
    def setUp(self):
        f = test_execution_efficiency.InvestigationTests(); f.setUp(); self.task = f.task
        self.task['assessment_scenarios'] = [{'scenario_id': x} for x in ('product_entry', 'brand_reuse', 'genuine_resale')]

    def add_object(self, oid, *, brand=False):
        obj = deepcopy(self.task['product_scope']['objects'][0])
        obj.update(object_id=oid, kind='logo' if brand else 'product', relation='reference' if brand else 'integrated')
        self.task['product_scope']['objects'].append(obj)

    def test_reference_brand_does_not_upgrade_product_technical_scope(self):
        before = resolve_discovery_work_policy(self.task, scenario_id='product_entry', right_type='patent')
        self.add_object('reference', brand=True)
        self.assertEqual(before, resolve_discovery_work_policy(self.task, scenario_id='product_entry', right_type='patent'))
        self.assertEqual(resolve_discovery_work_policy(self.task, scenario_id='brand_reuse', right_type='patent')['intensity'], 'focused')

    def test_missing_same_scenario_object_stays_focused_without_dropping_right(self):
        self.add_object('new')
        self.assertEqual(resolve_discovery_work_policy(self.task, right_type='patent')['intensity'], 'focused')
        self.assertEqual(resolve_discovery_work_policy(self.task, object_ids=['towel'], right_type='patent')['intensity'], 'baseline')
        self.assertEqual(resolve_discovery_work_policy(self.task, object_ids=['towel'], right_type='patent', positive_candidate=True)['intensity'], 'focused')

    def test_object_bindings_and_candidate_links_do_not_share_cached_policy(self):
        self.add_object('new')
        self.task['product_scope']['candidate_links'] = [{'candidate_id':'C', 'object_ids':['towel']}]
        view = {'entries':[
            {'kind':'triage', 'candidate_id':'C', 'right_type':'patent'},
            {'kind':'source_lookup', 'object_ids':['new'], 'right_type':'patent'},
            {'kind':'source_lookup', 'object_ids':['towel'], 'right_type':'patent'}]}
        project_work(self.task, view)
        self.assertEqual([v['investigation_policy']['intensity'] for v in view['entries']], ['baseline','focused','baseline'])

    def test_genuine_resale_retains_existing_all_object_exception(self):
        row = deepcopy(self.task['investigation_profile'][0]); row['scenario_id']='genuine_resale'
        self.task['investigation_profile'].append(row)
        self.assertEqual(resolve_discovery_work_policy(self.task, scenario_id='genuine_resale', right_type='patent')['intensity'], 'baseline')
        self.add_object('reference', brand=True)
        self.assertEqual(resolve_discovery_work_policy(self.task, scenario_id='genuine_resale', right_type='patent')['intensity'], 'focused')

    def test_shared_query_uses_highest_valid_scope(self):
        from decision_workflow import default_assessment_scenarios, scenario_sha256
        self.task['assessment_scenarios'] = default_assessment_scenarios()
        self.task['decision_workflow_revision']='scenario-triage-v1'
        self.add_object('reference', brand=True)
        # Brand reuse supports mark rights. Both scopes are legitimate for a shared mark query.
        row = deepcopy(self.task['investigation_profile'][0]); row['right_type']='trademark_word'
        self.task['investigation_profile'].append(row)
        query={'query_id':'Q', 'right_type':'trademark_word', 'scenario_bindings':[
            {'scenario_id':s['scenario_id'],'scenario_sha256':scenario_sha256(s)} for s in self.task['assessment_scenarios']],
            'product_dependencies':[{'scenario_id':'product_entry','object_ids':['towel']},
                                    {'scenario_id':'brand_reuse','object_ids':['reference']}]}
        entry={'kind':'source_lookup','right_type':'trademark_word','query_id':'Q','scenario_id':'product_entry','plan_entry_sha256':sha256_json(query)}
        project_work(self.task, {'entries':[entry]}, {'queries':{'provider':[query]}})
        self.assertEqual(entry['investigation_policy']['intensity'], 'focused')

    def test_plan_priority_uses_highest_actual_term_scope(self):
        from investigation_policy import discovery_terms_intensity
        self.add_object('reference', brand=True)
        row=deepcopy(self.task['investigation_profile'][0]);row['right_type']='trademark_word'
        self.task['investigation_profile'].append(row)
        terms=[{'scenario_id':'product_entry','object_ids':['towel']}]
        self.assertEqual(discovery_terms_intensity(self.task,terms,right_type='trademark_word'),'baseline')
        terms.append({'scenario_id':'brand_reuse','object_ids':['reference']})
        self.assertEqual(discovery_terms_intensity(self.task,terms,right_type='trademark_word'),'focused')
        self.assertEqual(discovery_terms_intensity(self.task,[terms[0]],right_type='patent'),'baseline')

    def test_profile_cannot_assign_reference_object_to_product_scenario(self):
        from investigation_policy import validate_profile
        self.add_object('reference', brand=True)
        row=deepcopy(self.task['investigation_profile'][0]); row['object_id']='reference'
        with self.assertRaisesRegex(ValueError,'PROFILE_SCOPE_INVALID'):
            validate_profile(self.task,[row])

    def test_legacy_v1_is_not_migrated(self):
        self.add_object('reference',brand=True); self.task['execution_efficiency_revision']=LEGACY_REVISION
        before=deepcopy(self.task)
        self.assertEqual(resolve_discovery_work_policy(self.task,scenario_id='product_entry',right_type='patent')['intensity'],'focused')
        self.assertEqual(self.task,before)

    def test_term_scenario_binding_keeps_reference_clues_separate(self):
        terms=[{'kind':'structural_feature','scenario_id':'brand_reuse'}, {'kind':'product','scenario_id':'product_entry'}]
        self.assertEqual(order_discovery_terms(self.task,terms,right_type='patent'),terms)

if __name__=='__main__': unittest.main()

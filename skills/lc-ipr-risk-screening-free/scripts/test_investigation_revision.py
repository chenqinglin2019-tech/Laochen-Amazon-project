"""Actual scope edits and plan selection; no provider or model requests."""
from copy import deepcopy
import unittest
import test_execution_efficiency
from investigation_policy import bind_profile, resolve_discovery_work_policy, project_work


class InvestigationRevisionTests(unittest.TestCase):
    def setUp(self):
        fixture = test_execution_efficiency.InvestigationTests()
        fixture.setUp()
        self.task = fixture.task

    def test_changed_fact_reopens_only_related_profile_without_erasing_history(self):
        self.task['investigation_profile'] = bind_profile(self.task, self.task['investigation_profile'])
        history = deepcopy(self.task['investigation_profile'])
        self.task['product_scope']['facts'][0]['status'] = 'confirmed'
        policy = resolve_discovery_work_policy(self.task, right_type='patent')
        self.assertEqual(policy['intensity'], 'focused')
        self.assertEqual(len(policy['profile_revision_required']), 1)
        self.assertEqual(resolve_discovery_work_policy(self.task, right_type='copyright')['profile_revision_required'], [])
        self.assertEqual(self.task['investigation_profile'], history)

    def test_removed_fact_no_longer_crashes_other_work(self):
        self.task['product_scope']['facts'] = []
        view = project_work(self.task, {'entries': [{'kind':'source_lookup', 'right_type':'copyright', 'state':'ready'},
            {'kind':'plan_repair', 'right_type':'patent', 'state':'ready'}]})
        self.assertEqual(view['entries'][0]['state'], 'ready')
        self.assertTrue(view['entries'][1]['investigation_profile_gaps'])

    def test_metadata_changes_do_not_reopen_and_gap_is_stable(self):
        self.task['investigation_profile'] = bind_profile(self.task, self.task['investigation_profile'])
        before = resolve_discovery_work_policy(self.task, right_type='patent')
        self.task['product_scope']['facts'][0]['updated_at'] = '2099-01-01'
        after = resolve_discovery_work_policy(self.task, right_type='patent')
        self.assertEqual(before, after)

    def test_missing_fact_supplies_stable_repair_without_changing_completion_state(self):
        view = {'entries': [{'kind':'plan_repair','right_type':'patent','state':'ready',
            'reason':'API_DISCOVERY_TERMS_MISSING'}, {'kind':'source_lookup','right_type':'copyright','state':'ready'}]}
        project_work(self.task, view)
        self.assertEqual(view['entries'][0]['state'], 'ready')
        self.assertTrue(view['entries'][0]['minimum_information'])
        self.assertEqual(view['entries'][0]['investigation_policy']['completion_rule'], 'existing_coverage_only')
        self.assertEqual(view['entries'][1]['state'], 'ready')

    def test_actual_planner_prefers_baseline_product_term_without_dropping_other_clues(self):
        from api_first_planning import _eligible_scope_terms
        terms = [{'kind':'structural_feature','value':'woven edge','language':'en','derived_from':'product.structure[0]'},
                 {'kind':'product','value':'printed towel','language':'en','derived_from':'product.title'}]
        ordered = _eligible_scope_terms(self.task, terms, 'US', 'patent')
        self.assertEqual(ordered, terms[::-1])
        self.task['investigation_profile'][0]['intensity'] = 'focused'
        self.assertEqual(_eligible_scope_terms(self.task, terms, 'US', 'patent'), terms)

    def test_candidate_presence_does_not_imply_positive(self):
        view = {'entries':[{'kind':'triage','candidate_id':'C','right_type':'patent'},
                           {'kind':'candidate_verification','candidate_id':'C','right_type':'patent'}]}
        project_work(self.task, view)
        self.assertEqual(view['entries'][0]['investigation_policy']['intensity'], 'baseline')
        self.assertEqual(view['entries'][1]['investigation_policy']['intensity'], 'focused')

    def test_compact_action_card_keeps_question_and_stable_gap(self):
        from advance_work import action_card
        from pathlib import Path
        view = {'entries':[{'work_id':'W','kind':'plan_repair','right_type':'patent',
            'state':'ready','reason':'API_DISCOVERY_TERMS_MISSING'}]}
        project_work(self.task, view)
        card = action_card(Path('/offline/task'), view['entries'][0])
        self.assertEqual(card['investigation_policy']['questions'], ['是否存在材料、织造或功能处理线索'])
        self.assertEqual(card['minimum_information'], view['entries'][0]['minimum_information'])
        self.assertIn('Do not invent', card['action_hint'])

    def test_legacy_tasks_are_not_migrated(self):
        self.task.pop('execution_efficiency_revision')
        view = {'entries':[{'kind':'source_lookup','right_type':'patent'}]}
        before = deepcopy(view)
        self.assertEqual(project_work(self.task, view), before)

    def test_scope_and_profile_can_reference_same_new_source_in_one_recording(self):
        import test_product_scope
        from common import load_json
        fixture = test_product_scope.ScopeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.data['investigation_profile'] = [{'scenario_id':'product_entry', 'object_id':'pattern',
            'right_type':'patent', 'intensity':'baseline', 'reason':'Initial visible facts only',
            'fact_ids':['lock'], 'evidence_refs':['user'], 'questions':['Is a locking method claimed?'],
            'escalation_conditions':['An exact patent claim is supplied'], 'limitations':['Locking method unknown']}]
        fixture.save()
        task = load_json(fixture.run / 'task.json')
        row = task['investigation_profile'][0]
        self.assertNotEqual(row['evidence_refs'], ['user'])
        self.assertTrue(row['basis_sha256'])
        self.assertFalse(resolve_discovery_work_policy(task, right_type='patent')['profile_revision_required'])


if __name__ == '__main__':
    unittest.main()

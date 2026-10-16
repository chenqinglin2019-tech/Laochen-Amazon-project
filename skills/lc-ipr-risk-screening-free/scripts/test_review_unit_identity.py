"""Offline unit obligations and attempt identity regressions; no external calls."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from common import sha256_json
from execution_efficiency import DEFAULTS, REVISION


def review_packet(selected=0, excluded=0, unreviewed=0):
    import decision_workflow as workflow
    from adaptive_review import UNIT_COUNT_REVISION
    task = {'task_id': 'UNITS', 'product': {'input_role': 'actual_product'}, 'images': [],
        'target_jurisdictions': ['US'], 'primary_scenario_id': 'product_entry',
        'assessment_scenarios': workflow.default_assessment_scenarios()[:1],
        'decision_workflow_revision': workflow.REVISION,
        'review_policy_revision': 'final-double-review-v1',
        'final_review_execution_revision': 'adaptive-double-review-v2',
        'review_unit_count_revision': UNIT_COUNT_REVISION,
        'execution_efficiency_revision': REVISION, 'execution_efficiency': deepcopy(DEFAULTS)}
    evidence = {'collections': {'patents': [{'evidence_id': 'E1', 'payload': {'claims': 'shaft and guard'}}]}}
    candidates = {'patents': []}
    ledger = {'schema_version': workflow.LEDGER_SCHEMA_VERSION, 'task_id': task['task_id'], 'annotations': []}
    for i in range(selected + excluded + unreviewed):
        candidate = {'candidate_id': 'C' + str(i), 'right_type': 'patent', 'jurisdiction': 'US',
            'publication_number': 'US' + str(10000000 + i) + 'B2', 'evidence_refs': ['E1']}
        candidates['patents'].append(candidate)
        if i >= selected + excluded:
            continue
        ledger['annotations'].append(workflow.make_annotation(task, 'patents', candidate, {
            'annotation_id': 'A' + str(i), 'scenario_id': 'product_entry',
            'decision': 'selected' if i < selected else 'not_selected',
            'reason': 'Synthetic claim compared with product facts', 'reviewer': 'offline',
            'annotated_at': '2026-10-10T00:00:00Z', 'evidence_refs': ['E1'],
            'reading_level': 'result_record', 'basis_summary': 'Synthetic shaft and guard',
            'reopen_conditions': ['Product or source claims change']}, evidence=evidence))
    return {'task': task, 'candidates': candidates, 'materiality_ledger': ledger,
        'evidence': evidence, 'search_plan': {'queries': {}},
        'retained_originals': {'materials': []}}


class ReviewUnitCountingTests(unittest.TestCase):
    def count(self, packet):
        from adaptive_review import measure
        return measure(packet, {})['review_units']

    def test_selected_candidates_are_required_but_excluded_and_unreviewed_are_not(self):
        self.assertEqual(self.count(review_packet(selected=16, excluded=15, unreviewed=15)), 25)
        self.assertEqual(self.count(review_packet(excluded=40)), 9)

    def test_stale_selection_preserves_triage_gap_without_inventing_assessment(self):
        packet = review_packet(selected=1)
        packet['candidates']['patents'][0]['claims'] = [{'text': 'new material'}]
        from decision_workflow import triage_summary
        summary = triage_summary(packet['task'], packet['candidates'], packet['materiality_ledger'],
            evidence=packet['evidence'])
        self.assertEqual(summary['records'][0]['decision'], 'unreviewed')
        self.assertEqual(self.count(packet), 9)

    def test_each_selected_country_is_a_distinct_unit(self):
        import decision_workflow as workflow
        packet = review_packet(selected=1)
        task = packet['task']
        task['target_jurisdictions'].append('GB')
        original = packet['materiality_ledger']['annotations'][0]
        candidate = packet['candidates']['patents'][0]
        request = {key: original[key] for key in ('reason', 'reviewer', 'annotated_at',
            'evidence_refs', 'reading_level', 'basis_summary', 'reopen_conditions')}
        request.update(annotation_id='GB-A', scenario_id='product_entry', jurisdiction='GB', decision='selected')
        packet['materiality_ledger']['annotations'].append(workflow.make_annotation(
            task, 'patents', candidate, request, evidence=packet['evidence']))
        self.assertEqual(self.count(packet), 20)

    def test_unnecessary_reference_mark_does_not_add_candidate_assessment(self):
        import decision_workflow as workflow
        packet = review_packet()
        task = packet['task']; task['product']['input_role'] = 'reference_product'
        candidate = {'candidate_id': 'TM', 'right_type': 'trademark_word', 'jurisdiction': 'US', 'evidence_refs': ['E1']}
        packet['candidates']['trademarks'] = [candidate]
        packet['materiality_ledger']['annotations'] = [workflow.make_annotation(task, 'trademarks', candidate, {
            'annotation_id': 'TM-A', 'scenario_id': 'product_entry', 'decision': 'selected',
            'reason': 'Reference mark observed', 'reviewer': 'offline', 'annotated_at': '2026-10-10T00:00:00Z',
            'evidence_refs': ['E1'], 'reading_level': 'result_record', 'basis_summary': 'Reference mark',
            'reopen_conditions': ['Own mark supplied']}, evidence=packet['evidence'])]
        self.assertEqual(self.count(packet), 9)
        # Existing overall-scope obligations remain unchanged, even where a
        # reference mark does not create a substantive candidate obligation.
        task['assessment_scenarios'] = workflow.default_assessment_scenarios()
        request = {key: packet['materiality_ledger']['annotations'][0][key] for key in
            ('reason', 'reviewer', 'annotated_at', 'evidence_refs', 'reading_level', 'basis_summary', 'reopen_conditions')}
        request.update(annotation_id='TM-BRAND', scenario_id='brand_reuse', decision='selected')
        packet['materiality_ledger']['annotations'].append(workflow.make_annotation(
            task, 'trademarks', candidate, request, evidence=packet['evidence']))
        self.assertEqual(self.count(packet), 12)  # 11 whole-product scopes + brand candidate.

    def test_threshold_24_inclusive_and_25_uses_modules(self):
        from adaptive_review import prepare
        with patch('module_review.attach_originals', return_value={}):
            self.assertIsNotNone(prepare(review_packet(selected=15), '.', []))
            self.assertIsNone(prepare(review_packet(selected=16), '.', []))

    def test_unmeasurable_candidates_or_unknown_revision_use_modules(self):
        from adaptive_review import prepare
        variants = []
        packet = review_packet(selected=1); packet['task'].pop('decision_workflow_revision'); variants.append(packet)
        packet = review_packet(selected=1); packet['materiality_ledger']['task_id'] = 'other-task'; variants.append(packet)
        packet = review_packet(); packet['candidates']['patents'] = [None]; variants.append(packet)
        packet = review_packet(); packet['task']['review_unit_count_revision'] = 'unknown'; variants.append(packet)
        with patch('module_review.attach_originals', return_value={}):
            for packet in variants:
                with self.subTest(task=packet['task']):
                    self.assertIsNone(prepare(packet, '.', []))

    def test_historical_integrated_count_and_input_signature_are_preserved(self):
        packet = review_packet(selected=40)
        packet['task'].pop('review_unit_count_revision')
        before = deepcopy(packet)
        self.assertEqual(self.count(packet), 9)
        self.assertEqual(packet, before)
        from final_review import inputs
        args = (packet['evidence'], packet['candidates'], packet['materiality_ledger'], packet['search_plan'])
        old = inputs(*args, packet['task'])
        packet['task']['review_unit_count_revision'] = 'selected-scope-units-v1'
        self.assertNotEqual(sha256_json(old), sha256_json(inputs(*args, packet['task'])))


class FollowupSetIdentityTests(unittest.TestCase):
    def setUp(self):
        self.task = {'execution_efficiency_revision': 'execution-efficiency-v1', 'execution_efficiency': deepcopy(DEFAULTS)}
        self.action = {'action_id': 'old', 'kind': 'source_lookup', 'provider': 'p',
            'operation': 'candidate_detail', 'params': {'views': ['front', 'back']},
            'followup_basis': {'missing_fact': 'claims', 'existing_evidence_refs': ['E1', 'E2']}}
        self.annotation = {'annotation_id': 'A', 'candidate_id': 'C', 'candidate_content_sha256': 'bytes',
            'scenario_id': 'S', 'jurisdiction': 'US', 'right_type': 'patent', 'next_actions': [self.action]}

    def test_reordered_duplicate_refs_do_not_buy_attempt_or_rewrite_history(self):
        from followup_identity import renamed_attempt
        previous = {'query_id': 'Q', 'triage_decision_id': 'A', 'triage_action_id': 'old'}
        plan = {'queries': {'p': [previous]}}
        ledger = {'annotations': [self.annotation]}
        evidence = {'source_runs': [{'run_id': 'R', 'provider': 'p', 'query_id': 'Q',
            'plan_entry_sha256': sha256_json(previous), 'submission_state': 'unknown', 'status': 'failed'}]}
        before = deepcopy((plan, ledger, evidence))
        renamed = deepcopy(self.action); renamed['action_id'] = 'renamed'
        renamed['followup_basis']['existing_evidence_refs'] = ['E2', 'E1', 'E2']
        result = renamed_attempt(self.task, plan, evidence, ledger, 'p', {'query_id': 'new'}, self.annotation, renamed)
        self.assertEqual(result['reason'], 'TRIAGE_ATTEMPT_STATE_UNKNOWN')
        self.assertEqual((plan, ledger, evidence), before)

    def test_ordered_request_params_and_new_material_remain_distinct(self):
        from followup_identity import identity
        initial = identity(self.annotation, self.action)
        changed = deepcopy(self.action); changed['params']['views'].reverse()
        self.assertNotEqual(initial, identity(self.annotation, changed))
        changed = deepcopy(self.action); changed['followup_basis']['existing_evidence_refs'].append('E3')
        self.assertNotEqual(initial, identity(self.annotation, changed))
        annotation = dict(self.annotation, candidate_content_sha256='changed bytes')
        self.assertNotEqual(initial, identity(annotation, self.action))


if __name__ == '__main__':
    unittest.main()

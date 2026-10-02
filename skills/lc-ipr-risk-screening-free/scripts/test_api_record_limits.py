"""Bounded API field gaps require actual reading and scoped follow-up review."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from common import atomic_write_json
from candidate_api_actions import append
from necessary_completion import api_record_gap_entry, _delivery_limit_valid
from specialty_analysis import project, work_entries
import test_specialty_analysis as prior


class ApiRecordLimitTests(unittest.TestCase):
    def setUp(self):
        self.fx = prior.SpecialtyAnalysisTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        f = self.fx
        f.task.update(retrieval_workflow_revision='api-first-v3',
            completion_policy_revision='necessary-work-v3', assessment_policy='evidence-estimate-v1')
        f.save()
        f.intake()
        self.material = f.material()
        self.fact = f.fact('status', self.material, outcome='unknown')
        self.acceptance = {'complete': False, 'missing': ['current_status'],
            'supported': [], 'evidence_refs': ['E1']}
        self.mock = patch('trusted_api.accepted_verification', return_value=self.acceptance)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.caps = {}
        self.plan = {'queries': {}, 'candidate_action_gaps': append(f.task, f.evidence, {}, f.candidate,
            f.scope(), [], capabilities=self.caps)}
        atomic_write_json(f.path / 'search-plan.json', self.plan)
        atomic_write_json(f.path / 'source-capabilities.json', {'task_id': f.task['task_id'], 'sources': []})

    def batch(self):
        return self.fx.add('batch', batch_id='import:E1', received_evidence_refs=['E1'],
            disposition_by_evidence_ref={'E1': 'Read the returned record for exact current status'},
            received_material_event_ids=[self.material['event_id']],
            processed_material_event_ids=[self.material['event_id']],
            disposition_reasoning='All candidate source material read and accounted')

    def entry(self, **options):
        f = self.fx
        return api_record_gap_entry(f.task, f.evidence, f.candidates, f.ledger,
            self.plan, self.caps, f.scope(), **options)

    def limit(self):
        self.batch()
        planning = self.entry(require_review=False)
        self.assertIsNotNone(planning)
        gap = self.fx.status_plan_gap(self.fact, planning)
        self.fx.add('followup', gap_id=gap['gap_id'], gap_event_id=gap['event_id'], outcome='limited',
            result_review='The retained record and bounded operations do not return current status',
            remaining_impact='Current legal effect remains unknown',
            next_action_or_dependency='A new current status record becomes available',
            limit_evidence='Read record and exact planner field gap',
            limit_kind='evidence_not_obtainable_within_scope',
            restore_condition='A permitted source returns current status for this record')
        return self.entry()

    def test_planning_proof_precedes_followup_but_closed_proof_requires_it(self):
        self.assertIsNone(self.entry(require_review=False))
        self.batch()
        planning = self.entry(require_review=False)
        self.assertIsNotNone(planning)
        self.assertEqual(planning['state'], 'awaiting_review')
        self.assertIsNone(self.entry())

    def test_only_bound_unknown_fact_becomes_report_limitation(self):
        entry = self.limit()
        self.assertIsNotNone(entry)
        f = self.fx
        self.assertTrue(_delivery_limit_valid(entry, f.task, f.evidence, self.plan, self.caps,
            candidates=f.candidates, ledger=f.ledger))
        rows = work_entries(project(f.task, f.evidence, f.candidates, f.ledger,
            plan=self.plan, capabilities=self.caps, task_dir=f.path, source_work=[entry]))
        status = next(row for row in rows if row.get('specialty_reason') == 'SPECIALTY_FACT_REQUIRED')
        self.assertEqual(status['state'], 'blocked')
        self.assertEqual(status['fact_kind'], 'status')
        self.assertEqual(status['coverage_status'], 'unknown')
        self.assertTrue(any(row.get('fact_kind') == 'product' and row['state'] == 'awaiting_review' for row in rows))

    def test_recovered_route_and_tampered_receipt_reopen_work(self):
        entry = self.limit()
        f = self.fx
        forged = deepcopy(entry)
        forged['official_verification'] = 'verified'
        self.assertFalse(_delivery_limit_valid(forged, f.task, f.evidence, self.plan, self.caps,
            candidates=f.candidates, ledger=f.ledger))
        self.caps['serpapi_google_patents'] = {'provider': 'serpapi_google_patents', 'executable': True}
        self.assertIsNone(self.entry())

    def test_conflicting_or_resolved_fact_does_not_count_as_unknown(self):
        self.limit()
        self.fx.fact('status', self.material)
        self.assertIsNone(self.entry())

    def test_final_limit_does_not_claim_search_or_fact_completion(self):
        entry = self.limit()
        self.assertEqual(entry['coverage_status'], 'unknown')
        self.assertEqual(entry['official_verification'], 'not_verified')
        self.assertEqual(entry['required_facts'], ['current_status'])
        self.assertTrue(entry['delivery_limit']['followup_sha256'])


class DistinctiveApiRecordLimitTests(unittest.TestCase):
    def test_missing_goods_can_limit_unavailable_comparison_after_partial_reading(self):
        from test_distinctive_rights_stage_d import StageDTests
        from distinctive_rights import project as m07_project, work_entries as m07_work
        fixture = StageDTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.fx
        f.task['retrieval_workflow_revision'] = 'api-first-v3'
        f.save()
        f.intake()
        material = f.material(status='read')
        fact = f.fact('registration', material, outcome='unknown', api_fact='protection_content')
        actual = f.material(track='public_facts', source_form='product_original', document_id='PRODUCT')
        f.fact('public_facts', actual)
        f.add('enforcement_scope', needed=False, reasoning='No enforcement signal in this exact fixture',
            planned_query_ids=[], evidence_refs=['E1'])
        fixture.batch([material['event_id'], actual['event_id']])
        gap = fixture.gap(affected_event_ids=[fact['event_id']],
            affected_reason_codes=['M07_TRACK_FACT_PENDING', 'M07_TRADEMARK_COMPARISON_PENDING'],
            unavailable_comparison={'required_facts': ['protection_content'],
                'reasoning': 'Full goods/services are missing, so a complete relatedness comparison cannot be made',
                'readable_parts_review': 'The available mark text and actual product use were read; missing goods remain unknown'})
        fixture.follow(gap, 'limited', limit_kind='evidence_not_obtainable_within_scope',
            limit_evidence='No complete goods/services after bounded source attempts',
            restore_condition='The complete goods/services record is available', next_action_or_dependency='No executable current route')
        fixture.close('limited', covered_gap_event_ids=[gap['event_id']], limit_impact='Goods relatedness remains unknown',
            restore_condition='Full record becomes available', no_pending_recovery=True)
        acceptance = {'complete': False, 'missing': ['protection_content'], 'supported': [], 'evidence_refs': ['E1']}
        with patch('trusted_api.accepted_verification', return_value=acceptance):
            plan = {'queries': {}, 'candidate_action_gaps': append(f.task, f.evidence, {}, f.candidate, f.scope(), [], capabilities={})}
            source = api_record_gap_entry(f.task, f.evidence, f.candidates, f.ledger, plan, {}, f.scope())
            entries = m07_work(m07_project(f.task, f.evidence, f.candidates, f.ledger,
                plan=plan, capabilities={}, source_work=[source]))
            self.assertTrue(entries)
            self.assertTrue(all(row['state'] == 'blocked' for row in entries))
            self.assertTrue(all(_delivery_limit_valid(row, f.task, f.evidence, plan, {},
                candidates=f.candidates, ledger=f.ledger) for row in entries))
            self.assertTrue(any(row.get('comparison_limitation') for row in entries))

    def test_closed_m07_gap_inherits_exact_api_proof(self):
        from test_distinctive_rights_stage_d import StageDTests
        from distinctive_rights import project as m07_project, work_entries as m07_work
        fixture = StageDTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        materials, _, _ = fixture.ready()
        f = fixture.fx
        f.task['retrieval_workflow_revision'] = 'api-first-v3'
        f.save()
        material = next(row for row in f.task['distinctive_rights_events'] if row['event_id'] == materials[0])
        fact = f.fact('registration', material, fact_id='F-API-STATUS', outcome='unknown', api_fact='current_status')
        fixture.batch(materials)
        gap = fixture.gap(affected_event_ids=[fact['event_id']])
        fixture.follow(gap, 'limited', limit_kind='evidence_not_obtainable_within_scope',
            limit_evidence='Bounded returned record has no current status',
            restore_condition='An API record returns current status', next_action_or_dependency='No executable current route')
        fixture.close('limited', covered_gap_event_ids=[gap['event_id']], limit_impact='Status remains unknown',
            restore_condition='A current record becomes available', no_pending_recovery=True)
        acceptance = {'complete': False, 'missing': ['current_status'], 'supported': [], 'evidence_refs': ['E1']}
        with patch('trusted_api.accepted_verification', return_value=acceptance):
            plan = {'queries': {}, 'candidate_action_gaps': append(f.task, f.evidence, {}, f.candidate,
                f.scope(), [], capabilities={})}
            source = api_record_gap_entry(f.task, f.evidence, f.candidates, f.ledger, plan, {}, f.scope())
            self.assertIsNotNone(source)
            view = m07_project(f.task, f.evidence, f.candidates, f.ledger, plan=plan,
                capabilities={}, source_work=[source])
            entry = next(row for row in m07_work(view) if row.get('distinctive_reason') == 'M07_GAP_OPEN')
            self.assertEqual(entry['state'], 'blocked')
            self.assertEqual(entry['reason'], 'API_RECORD_FACT_GAP')
            self.assertEqual(view['status'], 'limited')
            self.assertTrue(_delivery_limit_valid(entry, f.task, f.evidence, plan, {}, candidates=f.candidates, ledger=f.ledger))


class UnavailableClaimInventoryTests(unittest.TestCase):
    def test_missing_full_claims_limits_inventory_but_readable_inventory_stays_work(self):
        f = prior.SpecialtyAnalysisTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.task.update(retrieval_workflow_revision='api-first-v3', completion_policy_revision='necessary-work-v3',
            assessment_policy='evidence-estimate-v1')
        f.save()
        f.intake()
        material = f.add('material', document_id='US-1', document_version='v1', evidence_refs=['E1'],
            acquired_at='2026-09-28T00:00:00Z', source_form='official_register',
            purposes=['identity', 'territory', 'status'], reading_locations=['header'],
            status='sufficient_for_listed_purposes', supported_facts=['identity', 'territory', 'status'],
            support_reasoning='Header supports only exact identity and status')
        for kind in ('identity', 'territory', 'status'):
            f.fact(kind, material)
        partial = f.add('material', document_id='US-1-CLAIMS', document_version='v1', evidence_refs=['E1'],
            acquired_at='2026-09-28T00:00:00Z', source_form='original_document', purposes=['protection'],
            reading_locations=['truncated claim excerpt'], status='read', support_reasoning='Read available excerpt; full claims absent')
        fact = f.fact('protection', partial, outcome='unknown')
        product = f.product_material()
        f.fact('product', product)
        for ref, materials in (('E1', [material['event_id'], partial['event_id']]), ('E2', [product['event_id']])):
            f.add('batch', batch_id='import:' + ref, received_evidence_refs=[ref],
                disposition_by_evidence_ref={ref: 'All available text read'}, received_material_event_ids=materials,
                processed_material_event_ids=materials, disposition_reasoning='No unread material')
        acceptance = {'complete': False, 'missing': ['protection_content'], 'supported': [], 'evidence_refs': ['E1']}
        with patch('trusted_api.accepted_verification', return_value=acceptance):
            plan = {'queries': {}, 'candidate_action_gaps': append(f.task, f.evidence, {}, f.candidate, f.scope(), [], capabilities={})}
            atomic_write_json(f.path / 'search-plan.json', plan)
            atomic_write_json(f.path / 'source-capabilities.json', {'task_id': f.task['task_id'], 'sources': []})
            source = api_record_gap_entry(f.task, f.evidence, f.candidates, f.ledger, plan, {}, f.scope(), require_review=False)
            gap = f.status_plan_gap(fact, source, obligation_bindings=[{'reason': 'SPECIALTY_FACT_REQUIRED',
                'fact_kind': 'protection', 'basis_event_id': fact['event_id'], 'reasoning': 'Complete claim set is absent'}],
                unavailable_comparison={'required_facts': ['protection_content'],
                    'reasoning': 'An independent claim inventory cannot be established from the excerpt',
                    'readable_parts_review': 'Header and supplied excerpt read; no complete claim is available'})
            f.add('followup', gap_id=gap['gap_id'], gap_event_id=gap['event_id'], outcome='limited',
                result_review='All permitted record operations exhausted with no full claims', remaining_impact='Claim scope unknown',
                next_action_or_dependency='A complete claim document becomes available',
                limit_evidence='Read partial document and exact API gap', limit_kind='evidence_not_obtainable_within_scope',
                restore_condition='Full claims become obtainable')
            source = api_record_gap_entry(f.task, f.evidence, f.candidates, f.ledger, plan, {}, f.scope())
            view = project(f.task, f.evidence, f.candidates, f.ledger, plan=plan, capabilities={}, source_work=[source])
            self.assertEqual(view['status'], 'limited')
            entries = work_entries(view)
            self.assertTrue(all(_delivery_limit_valid(row, f.task, f.evidence, plan, {},
                candidates=f.candidates, ledger=f.ledger) for row in entries))
            inventory = next(row for row in entries if row.get('specialty_reason') == 'SPECIALTY_INVENTORY_PENDING')
            self.assertEqual(inventory['state'], 'blocked')
            from business_status_stage_b import classify
            from final_review import REVISION
            assessment = {'status': 'incomplete', 'final_review': {'revision': REVISION,
                'status': 'complete', 'evidence_digest': 'reviewed-unavailable-claims'},
                'assessments': [{**f.scope(), 'assessment_status': 'pending',
                    'pending_reasoning': 'Full claims are unavailable; the compared excerpt cannot establish the whole protection scope'}]}
            stage = {'product': {'product_version': '1'}, 'progress': {'completed': 0, 'planned': 1},
                'stage_risk': {'judgments': [], 'overall': {}}}
            business = classify({**f.task, 'review_policy_revision': REVISION,
                'business_status_revision': 'business-status-stage-b-v1'}, stage,
                {'entries': entries, 'unresolved_scopes': [f.scope()]}, assessment,
                limitation_validator=lambda item: _delivery_limit_valid(item, f.task, f.evidence, plan, {},
                    candidates=f.candidates, ledger=f.ledger))
            self.assertEqual(business['business_status'], 'limited_round_closed')
            f.material()
            # Even if a stale source proof is passed, new readable material is
            # actionable and cannot be hidden behind the old limitation.
            reopened = work_entries(project(f.task, f.evidence, f.candidates, f.ledger,
                plan=plan, capabilities={}, source_work=[source]))
            self.assertTrue(any(row.get('reason') == 'SPECIALTY_INVENTORY_PENDING' and row['state'] == 'awaiting_review' for row in reopened))


if __name__ == '__main__':
    unittest.main()

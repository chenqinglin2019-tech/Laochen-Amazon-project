"""Synthetic offline API record -> M06 reading -> final pair -> actual HTML."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from common import (active_free_policy, atomic_write_json, now_iso, sha256_file, sha256_json,
    serper_free_enhancement, serpapi_free_enhancement, signa_free_enhancement)
from trusted_api import annotate_entry, accepted_verification
import test_specialty_analysis as specialty_fixture
from test_assessment_estimate import fixture as review_fixture
from test_final_review import receipt
from test_product_scope_review import pending_product_scope_rows
from candidate_triage_stage import record_selected_handoff
from assessment_estimate import compute_assessment
from report_estimate import build_bundle
import final_review


class ApiFinalIntegrationTests(unittest.TestCase):
    def test_retained_api_fields_to_read_specialty_and_final_html_without_official_call(self):
        self._exercise()

    def test_missing_full_claims_remain_unknown_through_final_pair_and_actual_html(self):
        self._exercise(missing_claims=True)

    def _exercise(self, *, missing_claims=False):
        f = specialty_fixture.SpecialtyAnalysisTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.task.update(retrieval_workflow_revision='api-first-v3', review_policy_revision=final_review.REVISION,
            assessment_policy='evidence-estimate-v1', report_presentation_revision='report-presentation-stage-a-v1',
            business_status_revision='business-status-stage-b-v1',
            stage_delivery_revision='stage-delivery-stage-d-v1', free_policy=active_free_policy(),
            free_policy_revision='automation-first-v1', screening_revision='recall-integrity-v1', outputs={})
        f.task.update(serper_free_enhancement=serper_free_enhancement(),
            serpapi_free_enhancement=serpapi_free_enhancement(enabled=True, retrieval_workflow_revision='api-first-v3'),
            signa_free_enhancement=signa_free_enhancement())
        f.task['retrieval_policy'] = json.loads((Path(__file__).resolve().parent.parent /
            'references/runtime-config.json').read_text())['api_first']
        f.task['product'].update(title='Synthetic strap integration fixture', input_role='actual_product', actual_asin='B000000001')
        from workflow_v24 import build_coverage_requirements_v24
        from coverage_v3 import build_requirements
        f.task['coverage_requirements'] = build_requirements(f.task,
            build_coverage_requirements_v24(f.task['target_jurisdictions'], screening_revision=f.task['screening_revision']))
        f.evidence.update(task_id=f.task['task_id'], schema_version='2.4-free', source_runs=[])
        f.candidates.update(task_id=f.task['task_id'], schema_version='2.4-free')
        record = {'publication_number': f.candidate['publication_number'], 'jurisdiction': 'US', 'right_type': 'patent',
            'current_status': 'active', 'current_owner': 'Synthetic Owner', 'claims': ['1. A strap and hook.']}
        if missing_claims:
            record.pop('claims')
            record['snippet'] = 'A strap and hook; complete claims are not returned.'
        raw = f.path / 'synthetic-api-record.json'
        raw.write_text(json.dumps(record))
        query = {**f.scope(), 'query_id': 'API-DETAIL', 'provider': 'serpapi_google_patents',
            'operation': 'candidate_detail', 'q': f.candidate['publication_number'],
            'patent_id': 'patent/' + f.candidate['publication_number'] + '/en', 'required': False,
            'requirement_ids': [], 'execute_by_default': False}
        if missing_claims:
            query.update(api_gap_revision='api-first-v3', missing_facts=['protection_content'])
        run = {**query, 'run_id': 'API-RUN', 'status': 'success', 'source_environment': 'production',
            'finished_at': now_iso(), 'raw_paths': [str(raw)], 'payload_digest': sha256_file(raw),
            'plan_entry_sha256': sha256_json(query)}
        entry = {**query, 'evidence_id': 'E1', 'source_run_id': run['run_id'],
            'plan_entry_sha256': run['plan_entry_sha256'], 'payload': {'records': [record]}}
        annotate_entry(f.task, entry, run)
        f.evidence['collections']['patents'] = [entry]
        f.evidence['source_runs'] = [run]
        import product_scope
        product_scope_data = f.task['product_scope']
        product_scope_data.update(reviewer='offline-agent', reasoning='Retained product and included strap scope', evidence_id='E-SCOPE')
        for obj in product_scope_data['objects']:
            obj.update(intent='default', description='strap', location='product record', reason='Actual product', source_refs=['E2'])
        for direction in product_scope_data['directions']:
            direction['reason'] = 'Included actual strap configuration'
        product_scope_data['scope_sha256'] = sha256_json(product_scope.content(product_scope_data))
        f.task['product']['scope_objects'] = deepcopy(product_scope_data['objects'])
        scope_payload = {'scope': product_scope.content(product_scope_data), 'sources': [],
            'result_task': {'execution_scenario_ids': f.task.get('execution_scenario_ids')}}
        scope_path = f.path / 'synthetic-product-scope.json'
        atomic_write_json(scope_path, scope_payload)
        f.evidence['collections']['product_scope'] = [{'evidence_id': 'E-SCOPE',
            'scope': scope_payload['scope'], 'payload': scope_payload, 'result_task': scope_payload['result_task'],
            'path': str(scope_path), 'sha256': sha256_file(scope_path)}]
        f.ledger['annotations'] = []
        f.task['candidate_triage_stage_events'] = []
        f.f.task, f.f.evidence = f.task, f.evidence
        annotation = f.f.annotation('selected')
        f.ledger['annotations'].append(annotation)
        f.save()
        f.handoff_id = record_selected_handoff(f.path, {**f.scope(), 'annotation_id': annotation['annotation_id'],
            'evidence_refs': ['E1'], 'reading_scope': {'level': 'result_record', 'sections': ['claims', 'status']},
            'verification_gaps': ['current_status'], 'reviewer': 'offline-agent',
            'reason': 'Read exact API identity and claim text'})['event_id']
        f.refresh()
        f.intake()
        fact_kinds = ['identity', 'territory', 'status', 'rights_holder']
        if not missing_claims:
            fact_kinds.append('protection')
        material = f.add('material', document_id=f.candidate['publication_number'], document_version='api-v1',
            evidence_refs=['E1'], acquired_at=run['finished_at'], source_form='trusted_api_record',
            purposes=fact_kinds + ([] if missing_claims else ['comparison']),
            reading_locations=['records[0].publication_number',
                'records[0].snippet' if missing_claims else 'records[0].claims', 'records[0].current_status'],
            status='sufficient_for_listed_purposes', supported_facts=fact_kinds,
            support_reasoning='Read complete retained fields for this exact US publication')
        for kind in fact_kinds:
            f.fact(kind, material, right_identity=f.candidate['publication_number'])
        product_material = f.product_material()
        f.fact('product', product_material)
        patent_materials = [material['event_id']]
        if missing_claims:
            partial = f.add('material', document_id=f.candidate['publication_number'], document_version='api-v1',
                evidence_refs=['E1'], acquired_at=run['finished_at'], source_form='trusted_api_record',
                purposes=['protection'], reading_locations=['records[0].snippet; claims field absent'],
                status='read', support_reasoning='Read available excerpt; it does not establish the complete claim scope')
            missing_fact = f.fact('protection', partial, outcome='unknown')
            patent_materials.append(partial['event_id'])
        else:
            inventory = f.add('inventory', document_id=f.candidate['publication_number'], document_version='api-v1',
                evidence_refs=['E1'], material_event_ids=[material['event_id']], reading_locations=['claim 1'],
                completeness_reasoning='The complete retained independent claim is read', units=[{
                    'unit_id': 'claim-1', 'kind': 'independent_claim', 'implementation_id': 'sold-strap',
                    'product_configuration': 'strap with hook', 'original_location': 'claim 1', 'necessary_elements': ['strap', 'hook']}])
            f.add('comparison', inventory_event_id=inventory['event_id'], unit_id='claim-1', disposition='compared',
                evidence_refs=['E1', 'E2'], reasoning='All listed elements compared to actual product', elements=[{
                    'element_id': name, 'result': 'corresponds', 'claim_quote': name, 'original_location': 'claim 1',
                    'product_fact': name, 'reasoning': 'The retained product shows this element',
                    'claim_evidence_refs': ['E1'], 'product_evidence_refs': ['E2']} for name in ('strap', 'hook')])
        for ref, material_ids in (('E1', patent_materials), ('E2', [product_material['event_id']])):
            f.add('batch', batch_id='import:' + ref if ref == 'E2' else 'API-RUN', received_evidence_refs=[ref],
                disposition_by_evidence_ref={ref: 'Read all retained material'},
                received_material_event_ids=material_ids,
                processed_material_event_ids=material_ids, disposition_reasoning='Accounted and compared where complete text permits')
        if not missing_claims:
            self.assertEqual(f.view()['status'], 'normal_complete')
        self.assertEqual(accepted_verification(f.task, f.evidence, f.candidate)['complete'], not missing_claims)
        plan = {'schema_version': '2.4-free', 'task_id': f.task['task_id'], 'queries': {'serpapi_google_patents': [query]},
            'free_policy': deepcopy(f.task['free_policy']), 'free_policy_revision': 'automation-first-v1'}
        for field in ('serper_free_enhancement', 'serpapi_free_enhancement', 'signa_free_enhancement'):
            plan[field] = deepcopy(f.task[field])
        plan['execution_policy'] = {'commercial_freemium_allowlist': ['serpapi'],
            'commercial_providers_enabled': True, 'paid_execution_enabled': False}
        plan.update(retrieval_workflow_revision='api-first-v3', retrieval_policy=deepcopy(f.task['retrieval_policy']))
        plan.update({key: f.task[key] for key in ('decision_workflow_revision', 'workflow_correction_revision')})
        if missing_claims:
            self._close_claim_gap(f, plan, missing_fact)
        base = review_fixture(f.path)[-2]['assessments'][0]
        scenario = f.task['assessment_scenarios'][0]
        row = {**base, **f.scope(), 'module_id': 'utility_patent', 'title': 'Synthetic API patent',
            'scenario_sha256': scenario['scenario_sha256'], 'evidence_refs': ['E1', 'E2'],
            'right_state': 'active', 'right_state_evidence_refs': ['E1'],
            'supporting_evidence': [{'reasoning': 'All retained claim elements correspond', 'evidence_refs': ['E1', 'E2']}],
            'confidence_basis': {}, 'comparison': {'criteria': [], 'unresolved': []}, 'findings': []}
        row['comparison'].update(implementations=[{'implementation_id': 'sold-strap', 'title': 'Strap',
            'description': 'The actual strap with hook', 'product_evidence_refs': ['E2']}], claims=[{
                'claim_id': '1', 'claim_type': 'independent', 'implementation_id': 'sold-strap',
                'claim_evidence_refs': ['E1'],
                'conclusion': 'supports_risk', 'elements': [{'claim_element': name, 'claim_quote': name,
                    'product_feature': name, 'product_evidence_refs': ['E2'], 'evidence_refs': ['E1'],
                    'result': 'supports_risk', 'reasoning': 'Exact retained feature correspondence'} for name in ('strap', 'hook')]}])
        if missing_claims:
            row.update(risk=None, assessment_status='pending',
                pending_reasoning='Full claims are unavailable after bounded follow-up; claim scope remains unknown',
                reasoning='The available excerpt and actual product were read; full claims remain unavailable',
                supporting_evidence=[], no_supporting_evidence_reasoning='No complete claim permits a risk conclusion',
                comparison={'criteria': [], 'unresolved': ['Full claims remain unavailable']},
                evidence_confidence='低', confidence_reasoning='The specific protection scope is missing')
        f.save()
        atomic_write_json(f.path / 'search-plan.json', plan)
        material_input = final_review.inputs(f.evidence, f.candidates, f.ledger, plan, f.task)
        # A candidate judgment cannot substitute for whole-product scope review.
        # These synthetic records do not establish clearance in the other scopes.
        overall_rows = pending_product_scope_rows(f.task)
        self.assertEqual(len(overall_rows), 22)
        reviews = [receipt(deepcopy([row, *overall_rows]), material_input, slot)
            for slot in ('first', 'second')]
        for review in reviews:
            review.update(coverage_confidence_cap='中',
                coverage_confidence_reasoning='This synthetic example verifies one candidate; other scopes remain unsearched')
        with patch('urllib.request.urlopen', side_effect=AssertionError('No official or API network request allowed')) as network:
            assessment = compute_assessment(f.task, f.evidence, f.candidates, plan, f.ledger, *reviews,
                evidence_root=f.path, task_dir=f.path)
            self.assertEqual(assessment['final_review']['status'], 'complete')
            overall = [value for value in assessment['assessments'] if not value.get('candidate_id')]
            self.assertEqual(len(overall), len(overall_rows))
            self.assertTrue(all(value['risk'] is None and value['assessment_status'] == 'pending'
                for value in overall))
            data, _ = build_bundle(f.path, f.task, f.evidence, assessment, f.candidates,
                {'task_id': f.task['task_id'], 'entries': []}, plan, output_dir=f.path / 'html')
            network.assert_not_called()
        page = (f.path / 'html/report.html').read_text()
        self.assertIn('最终报告 · 最终双审已完成', page)
        self.assertNotIn('待双审', page)
        self.assertIn('已采信 API 原记录字段', page)
        self.assertIn('来源更新时间：未知', page)
        self.assertNotIn('NECESSARY_09C_REVIEW_PENDING', data['business_status_stage_b']['gaps'])
        self.assertEqual(data['presentation_stage_a']['stage']['stage_risk']['overall']['review_status'], 'complete')
        self.assertFalse(f.evidence.get('stage_review_events'))
        if missing_claims:
            candidate_row = next(value for value in assessment['assessments'] if value.get('candidate_id') == f.candidate['candidate_id'])
            self.assertIsNone(candidate_row['risk'])
            self.assertEqual(candidate_row['assessment_status'], 'pending')
            self.assertIn('Full claims remain unavailable', page)
            self.assertIn('缺失或未采信字段：权利要求', page)
            self.assertEqual(data['overall']['risk'], None)

    def _close_claim_gap(self, f, plan, missing_fact):
        """Actual gap projection, retained exhausted fallback and M06 follow-up."""
        from candidate_api_actions import append
        from necessary_completion import api_record_gap_entry, _delivery_limit_valid
        from specialty_analysis import _current, _scope, project, work_entries
        # This synthetic retained snapshot contains the failed directed fallback
        # from the bounded investigation. The test itself makes no network calls.
        fallback = {**f.scope(), 'query_id': 'CLAIM-FALLBACK', 'provider': 'uspto_patent_browser',
            'operation': 'candidate_verification', 'q': f.candidate['publication_number'],
            'api_gap_revision': 'api-first-v3', 'missing_facts': ['protection_content'],
            'required': False, 'requirement_ids': [], 'execute_by_default': False,
            'fallback_basis': {'candidate_id': f.candidate['candidate_id'], 'missing_facts': ['protection_content'],
                'reviewed_evidence_refs': ['E1'], 'attempted_query_ids': ['API-DETAIL']}}
        plan['queries']['uspto_patent_browser'] = [fallback]
        f.evidence['source_runs'].append({**fallback, 'run_id': 'FALLBACK-RUN', 'status': 'access_limited',
            'reason': 'AUTH_REQUIRED', 'finished_at': now_iso(), 'plan_entry_sha256': sha256_json(fallback)})
        current = _current(f.task, f.evidence, f.candidates, f.ledger, None, _scope(f.scope()))
        requirements = [value for value in f.task['coverage_requirements']
            if value['jurisdiction'] == 'US' and value['right_type'] == 'patent']
        plan['candidate_action_gaps'] = append(f.task, f.evidence, plan['queries'], f.candidate,
            current, requirements, capabilities={})
        self.assertEqual(plan['candidate_action_gaps'][0]['required_facts'], ['protection_content'])
        f.save()
        atomic_write_json(f.path / 'search-plan.json', plan)
        atomic_write_json(f.path / 'source-capabilities.json', {'task_id': f.task['task_id'], 'sources': []})
        source = api_record_gap_entry(f.task, f.evidence, f.candidates, f.ledger, plan, {}, f.scope(), require_review=False)
        self.assertIsNotNone(source)
        gap = f.status_plan_gap(missing_fact, source,
            obligation_bindings=[{'reason': 'SPECIALTY_FACT_REQUIRED', 'fact_kind': 'protection',
                'basis_event_id': missing_fact['event_id'], 'reasoning': 'The full claim scope is absent'}],
            unavailable_comparison={'required_facts': ['protection_content'],
                'reasoning': 'The excerpt cannot establish an independent claim inventory',
                'readable_parts_review': 'Read the record header, supplied excerpt and actual product'},
            question='Complete claim scope is unavailable', affected_judgment='protection',
            minimum_action='Obtain the exact publication full claims',
            completion_condition='Complete claims become available', existing_material_check='Header and excerpt read',
            next_value='Full claim scope remains unknown')
        f.add('followup', gap_id=gap['gap_id'], gap_event_id=gap['event_id'], outcome='limited',
            result_review='API record and directed fallback did not return complete claims',
            remaining_impact='Claim inventory and infringement comparison remain unknown',
            next_action_or_dependency='A complete claim document becomes obtainable',
            limit_evidence='Retained record, actual reading and bounded fallback',
            limit_kind='evidence_not_obtainable_within_scope', restore_condition='Read the exact full claim document')
        source = api_record_gap_entry(f.task, f.evidence, f.candidates, f.ledger, plan, {}, f.scope())
        self.assertIsNotNone(source)
        view = project(f.task, f.evidence, f.candidates, f.ledger, plan=plan, capabilities={}, source_work=[source])
        self.assertEqual(view['status'], 'limited')
        entries = work_entries(view)
        self.assertTrue(entries)
        self.assertTrue(all(_delivery_limit_valid(value, f.task, f.evidence, plan, {},
            candidates=f.candidates, ledger=f.ledger) for value in entries))


if __name__ == '__main__':
    unittest.main()

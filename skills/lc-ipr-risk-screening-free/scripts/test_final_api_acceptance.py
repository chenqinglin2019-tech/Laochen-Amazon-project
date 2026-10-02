"""Accepted API facts satisfy finalization without inventing official flags."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import now_iso, sha256_file, active_free_policy, AUTOMATION_POLICY_REVISION
from trusted_api import annotate_entry
from finalize_assessment import (official_verification_complete, material_unverified,
    coverage_requirement_gaps, formal_rating_evidence_by_module)


class FinalApiAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = self.root / 'raw.json'
        self.raw.write_text('{"retained":"isolated offline fixture"}')
        self.requirement = {'requirement_id': 'US-PATENT-VERIFY', 'jurisdiction': 'US', 'right_type': 'patent',
            'phase': 'candidate_verification', 'completion_policy': 'any', 'routes': []}
        self.task = {'task_id': 'T1', 'schema_version': '2.4-free', 'retrieval_workflow_revision': 'api-first-v3',
            'target_jurisdictions': ['US'], 'coverage_requirements': [self.requirement],
            'free_policy': active_free_policy(), 'free_policy_revision': AUTOMATION_POLICY_REVISION}
        self.row = {'publication_number': 'US1234567B2', 'jurisdiction': 'US', 'right_type': 'patent',
            'current_status': 'active', 'current_owner': 'Example owner', 'claims': ['1. A hinge comprising ...']}
        self.candidate = {**deepcopy(self.row), 'candidate_id': 'C1', 'material': True,
            'disposition': 'material', 'material_reason': 'Related mechanism', 'materiality_annotation': {
                'decision': 'material', 'material': True, 'annotation_id': 'A1', 'reviewer': 'reviewer',
                'candidate_identity_fingerprint': 'fingerprint', 'annotated_at': now_iso()}}
        self.run = {'run_id': 'R1', 'provider': 'serpapi_google_patents', 'operation': 'candidate_detail',
            'query_id': 'Q1', 'jurisdiction': 'US', 'right_type': 'patent', 'plan_entry_sha256': 'f' * 64,
            'status': 'success', 'finished_at': now_iso(), 'source_environment': 'production',
            'raw_paths': [str(self.raw)], 'payload_digest': sha256_file(self.raw)}
        self.entry = {'evidence_id': 'E1', 'source_run_id': 'R1', 'provider': 'serpapi_google_patents',
            'operation': 'candidate_detail', 'query_id': 'Q1', 'jurisdiction': 'US', 'right_type': 'patent',
            'plan_entry_sha256': 'f' * 64, 'payload': {'records': [self.row]}}
        self.refresh()
        self.plan = {'task_id': 'T1', 'schema_version': '2.4-free', 'queries': {},
            'free_policy': deepcopy(self.task['free_policy']), 'free_policy_revision': AUTOMATION_POLICY_REVISION}

    def tearDown(self):
        self.tmp.cleanup()

    def refresh(self):
        annotate_entry(self.task, self.entry, self.run)
        self.evidence = {'source_runs': [self.run], 'collections': {'patents': [self.entry]}}
        self.candidates = {'patents': [self.candidate]}

    def accepted(self, **options):
        return official_verification_complete(self.candidate, strict=True, evidence=self.evidence,
            task=options.get('task', self.task), jurisdiction=options.get('jurisdiction', 'US'), right_type='patent')

    def test_complete_api_facts_need_no_official_flag_or_browser_route(self):
        self.assertTrue(self.accepted())
        self.assertNotIn('official_verification', self.candidate)
        self.assertEqual(material_unverified(self.candidates, strict=True, task=self.task,
            evidence=self.evidence, search_plan=self.plan), [])
        self.assertEqual(coverage_requirement_gaps(self.task, self.evidence, self.candidates, self.plan), [])

    def test_legacy_task_does_not_inherit_new_acceptance(self):
        self.assertFalse(self.accepted(task={**self.task, 'retrieval_workflow_revision': 'api-first-v2'}))

    def test_formal_rating_uses_the_same_accepted_api_references(self):
        evidence = formal_rating_evidence_by_module(self.task, self.evidence, self.candidates, self.plan)
        self.assertEqual(evidence['utility_patent'], {'E1'})

    def test_report_discloses_accepted_fields_provider_upstream_and_unknown_source_date(self):
        from report_estimate import build_verification_basis, _source_notes
        row = {'candidate_id': 'C1', 'jurisdiction': 'US', 'right_type': 'patent', 'evidence_refs': ['E1']}
        basis = build_verification_basis(self.task, self.evidence, {'assessments': [row]}, self.candidates, self.plan)
        facts = {fact['field']: fact for fact in basis['assessments'][0]['facts']}
        for field in ('legal_status', 'owner', 'claims'):
            self.assertEqual(facts[field]['basis'], 'trusted_api_record')
        self.assertNotIn('法律状态', basis['assessments'][0]['unverified_facts'])
        notes = '\n'.join(_source_notes({'verification_basis': basis}))
        self.assertIn('serpapi_google_patents', notes)
        self.assertIn('上游：', notes)
        self.assertIn('来源更新时间：未知', notes)

    def test_exact_accepted_direct_payload_remains_counter_evidence(self):
        from assessment_estimate import _apply_recall_integrity
        self.entry['payload'] = deepcopy(self.row)
        self.refresh()
        self.task['screening_revision'] = 'recall-integrity-v1'
        row = {'candidate_id': 'C1', 'jurisdiction': 'US', 'right_type': 'patent',
            'risk': '低', 'reasoning': 'A necessary claim element is absent', 'evidence_refs': ['E1'],
            'comparison': {'criteria': ['missing element']},
            'counter_evidence': [{'reasoning': 'The retained complete claim limits the protected combination', 'evidence_refs': ['E1']}]}
        with patch('workflow_v24.product_analysis_readiness', return_value={'gaps': [], 'patent_claim_followup': {}}):
            _apply_recall_integrity([row], self.task, self.evidence, self.candidates, self.plan, {},
                {'E1': self.entry}, sufficiency_only=True)
        self.assertEqual(len(row['counter_evidence']), 1)
        self.assertNotIn('unsubstantiated_counter_evidence', row)

    def test_wrong_number_country_and_truncated_claim_remain_gaps(self):
        for field, value in (('publication_number', 'US9999999B2'), ('jurisdiction', 'GB'), ('claims_truncated', True)):
            with self.subTest(field=field):
                original = deepcopy(self.row)
                self.row[field] = value
                self.refresh()
                self.assertFalse(self.accepted())
                self.row.clear()
                self.row.update(original)
        self.refresh()
        self.assertFalse(self.accepted(jurisdiction='GB'))

    def test_missing_status_or_historical_applicant_not_complete(self):
        for field in ('current_status', 'current_owner', 'claims'):
            with self.subTest(field=field):
                value = self.row.pop(field)
                self.row['applicant'] = 'Original applicant'
                self.refresh()
                self.assertFalse(self.accepted())
                self.row[field] = value

    def test_failed_empty_and_expired_api_receipts_not_complete(self):
        self.run['status'] = 'no_result'
        self.refresh()
        self.assertFalse(self.accepted())
        self.run['status'] = 'success'
        self.run['finished_at'] = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        self.refresh()
        self.assertFalse(self.accepted())

    def test_pending_duplicate_browser_row_does_not_recreate_satisfied_gap(self):
        self.plan['queries'] = {'uspto_patent_browser': [{'query_id': 'WEB1', 'required': True,
            'operation': 'candidate_verification', 'requirement_ids': ['US-PATENT-VERIFY']}]}
        self.assertEqual(coverage_requirement_gaps(self.task, self.evidence, self.candidates, self.plan), [])


if __name__ == '__main__':
    unittest.main()

"""Offline stale-derived-view regression; no real provider evidence or writes."""
from argparse import Namespace
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import decision_workflow as workflow
import merge_candidates as merger
from annotate_materiality import _append_scenario_decisions
from common import atomic_write_json, load_json, sha256_json
import test_decision_workflow as fixtures


class CandidateSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.DecisionWorkflowTests()
        self.f.setUp()
        self.f.task['workflow_correction_revision'] = workflow.CORRECTION_REVISION
        merger.apply_candidate_contract('patent', [self.f.candidate])
        self.entry = {'evidence_id': 'E-OFFICIAL', 'provider': 'synthetic',
            'payload': {'candidate_id': 'C1', 'jurisdiction': 'US', 'right_type': 'patent',
                'publication_number': self.f.candidate['publication_number'],
                'published_document': {'record_number': self.f.candidate['publication_number'],
                    'rendered_text': 'Synthetic independent claim: strap with hook.'},
                'official_verification': {'status': 'incomplete', 'authority_scope': 'published_document_only',
                    'authority': 'Synthetic office', 'identity_match': True, 'legal_status': '',
                    'checked_at': '2026-01-02T00:00:00Z'}}}
        self.f.evidence['collections']['official_verifications'] = [self.entry]

    def refresh(self):
        f = self.f
        f.candidate.update(merger.candidate_verification_view(f.task, 'patents', f.candidate, f.evidence,
            merger.verification_index(f.evidence['collections']['official_verifications'])))

    def test_new_evidence_old_candidate_is_rejected_even_when_review_cites_it(self):
        before = sha256_json([self.f.task, self.f.evidence, self.f.candidate, self.f.ledger])
        with self.assertRaisesRegex(ValueError, 'TRIAGE_CANDIDATE_VIEW_STALE'):
            self.f.annotation(evidence_refs=['E-OFFICIAL'])
        self.assertEqual(before, sha256_json([self.f.task, self.f.evidence, self.f.candidate, self.f.ledger]))

    def test_refreshed_view_binds_and_repeated_same_source_does_not_reopen(self):
        self.refresh()
        f = self.f
        f.ledger['annotations'].append(f.annotation('not_selected', evidence_refs=['E-OFFICIAL']))
        original = deepcopy(f.ledger)
        self.refresh()
        self.assertTrue(f.effective()['current'])
        repost = deepcopy(self.entry)
        repost['evidence_id'] = 'E-REPOST'
        repost['collected_at'] = '2026-01-03T00:00:00Z'
        f.evidence['collections']['official_verifications'].append(repost)
        self.refresh()
        self.assertTrue(f.effective()['current'])
        self.assertEqual(original, f.ledger)

    def test_actual_new_protection_text_still_reopens_after_refresh(self):
        self.refresh()
        f = self.f
        f.ledger['annotations'].append(f.annotation('not_selected', evidence_refs=['E-OFFICIAL']))
        fresh = deepcopy(self.entry)
        fresh['evidence_id'] = 'E-NEW-CLAIM'
        fresh['payload']['published_document']['rendered_text'] = 'Synthetic amended independent claim: strap without hook.'
        f.evidence['collections']['official_verifications'].append(fresh)
        with self.assertRaisesRegex(ValueError, 'TRIAGE_CANDIDATE_VIEW_STALE'):
            f.annotation(evidence_refs=['E-NEW-CLAIM'])
        self.refresh()
        self.assertFalse(f.effective()['current'])
        self.assertIn('TRIAGE_BASIS_CHANGED: candidate_content_sha256', f.effective()['reopen_reasons'])

    def test_actual_new_current_status_still_reopens(self):
        self.refresh()
        f = self.f
        f.ledger['annotations'].append(f.annotation(evidence_refs=['E-OFFICIAL']))
        fresh = deepcopy(self.entry)
        fresh['evidence_id'] = 'E-NEW-STATUS'
        fresh['payload']['official_verification'].update(status='verified', authority_scope='official_registry',
            legal_status='expired', checked_at='2026-01-04T00:00:00Z')
        f.evidence['collections']['official_verifications'].append(fresh)
        self.refresh()
        self.assertFalse(f.effective()['current'])
        self.assertEqual(f.candidate['official_verification']['legal_status'], 'expired')

    def test_historical_branch_keeps_original_binding_without_new_guard(self):
        self.f.task.pop('workflow_correction_revision')
        with patch.object(merger, 'candidate_verification_view', side_effect=AssertionError('legacy must not refresh')):
            self.assertEqual(self.f.annotation(evidence_refs=['E-OFFICIAL'])['decision'], 'selected')

    def test_pure_refresh_has_no_files_locks_source_or_plan_side_effects(self):
        before = sha256_json([self.f.task, self.f.evidence, self.f.candidate])
        official = merger.verification_index([self.entry])
        with (patch.object(merger, 'main', side_effect=AssertionError('no merge CLI')),
             patch.object(Path, 'read_bytes', side_effect=AssertionError('no source file reads')),
             patch.object(Path, 'read_text', side_effect=AssertionError('no source file reads'))):
            view = merger.candidate_verification_view(self.f.task, 'patents', self.f.candidate, self.f.evidence, official)
        self.assertIn('E-OFFICIAL', view['verification_refs'])
        self.assertEqual(before, sha256_json([self.f.task, self.f.evidence, self.f.candidate]))

    def test_batch_rejects_before_any_ledger_or_task_write(self):
        f = self.f
        request = {'candidate_id': 'C1', 'decision': 'not_selected', 'scenario_id': 'product_entry',
            'jurisdiction': 'US', 'right_type': 'patent', 'reason': 'Synthetic comparison',
            'evidence_refs': ['E-OFFICIAL'], 'reading_level': 'independent_claims',
            'basis_summary': 'Synthetic hook differs', 'reopen_conditions': ['New claim']}
        other = deepcopy(f.candidate)
        other.update(candidate_id='C2', publication_number='US22222222B2', evidence_refs=['E2'])
        f.candidates['patents'].append(other)
        f.evidence['collections']['patents'].append({'evidence_id':'E2','payload':{'publication_number':'US22222222B2','claims':'Synthetic other claim'}})
        first = {**request, 'candidate_id':'C2', 'evidence_refs':['E2']}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name,value in [('task.json',f.task),('evidence.json',f.evidence),('normalized-candidates.json',f.candidates),
                               ('materiality-annotations.json',f.ledger),('input.json',{'decisions':[first,request]})]:
                atomic_write_json(root/name,value)
            before = {p.name:p.read_bytes() for p in root.iterdir()}
            args = Namespace(input=root/'input.json',reviewer='offline-reviewer',candidate_id=None,decision=None,
                material=None,reason=None,material_reason=None,scenario_id=None,jurisdiction=None,right_type=None,
                evidence_ref=[],missing_information=[],next_actions_json=None,reading_level=None,basis_summary=None,reopen_condition=[])
            with self.assertRaisesRegex(ValueError,'TRIAGE_CANDIDATE_VIEW_STALE'):
                _append_scenario_decisions(root,f.task,f.candidates,args)
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})

    def test_batch_reuses_index_and_does_not_refresh_unrelated_candidate(self):
        self.refresh()
        f = self.f
        with patch.object(merger,'verification_index',wraps=merger.verification_index) as build:
            with workflow.decision_snapshot(f.task,f.evidence,f.candidates,None,f.ledger):
                f.annotation(evidence_refs=['E-OFFICIAL'])
                f.annotation(evidence_refs=['E-OFFICIAL'])
            self.assertEqual(build.call_count,1)
        unrelated = deepcopy(self.entry)
        unrelated['evidence_id']='E-OTHER'
        unrelated['payload'].update(candidate_id='C2',publication_number='US22222222B2')
        f.evidence['collections']['official_verifications'].append(unrelated)
        self.assertEqual(f.annotation(evidence_refs=['E-OFFICIAL'])['decision'],'selected')


if __name__ == '__main__':
    unittest.main()

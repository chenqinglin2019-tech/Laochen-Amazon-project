"""A failed historical acquisition can resolve against separately read bytes."""
from copy import deepcopy
from pathlib import Path
import unittest
from common import atomic_write_json, load_json, sha256_file, sha256_json
from candidate_followup import record_review, verify_review_sources, pending_review_entries
from test_candidate_followup import CandidateFollowupTests


class MaterialResolutionTests(unittest.TestCase):
    def setUp(self):
        self.f = CandidateFollowupTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        f.task['retrieval_workflow_revision'] = 'api-first-v3'
        self.old = f.annotate([f.exact()])
        row = {'query_id': 'Q1', 'operation': 'candidate_verification', 'q': 'US11111111B2',
               'triage_decision_id': self.old['annotation_id'], 'triage_action_id': 'LOOKUP-1'}
        f.plan['queries'] = {'uspto_patent_browser': [row]}
        raw = f.path / 'fault.xml'
        raw.write_text('<fault><message>Not acceptable</message></fault>')
        run = {'run_id': 'R1', 'provider': 'uspto_patent_browser', 'query_id': 'Q1',
               'plan_entry_sha256': sha256_json(row), 'status': 'failed', 'submission_state': 'unknown',
               'raw_paths': [str(raw)], 'payload_digest': sha256_file(raw)}
        f.evidence['source_runs'] = [run]
        f.evidence['recovery_reviews'] = [{'review_id': 'REC1', 'source_run_id': 'R1',
            'source_run_sha256': sha256_json(run), 'kind': 'unknown_check', 'outcome': 'submitted_failed'}]
        pdf = f.path / 'exact.pdf'
        pdf.write_bytes(b'%PDF-1.4\nretained synthetic exact document for isolated tests')
        self.doc = {'evidence_id': 'PDF1', 'kind': 'patent_document', 'authority_scope': 'published_document_only',
            'publication_number': f.candidate['publication_number'], 'jurisdiction': 'US',
            'candidate_id': 'C1', 'right_type': 'patent', 'path': str(pdf), 'sha256': sha256_file(pdf),
            'bytes': pdf.stat().st_size, 'page_count': 4}
        f.evidence['collections']['documents'] = [self.doc]
        self.current = f.f.annotation('not_selected', evidence_refs=['E1', 'PDF1'], reading_level='independent_claims')
        f.ledger['annotations'].append(self.current)
        f.save()
        self.request = {'candidate_id': 'C1', 'scenario_id': 'product_entry', 'jurisdiction': 'US',
            'right_type': 'patent', 'annotation_id': self.old['annotation_id'], 'action_id': 'LOOKUP-1',
            'query_id': 'Q1', 'run_id': 'R1', 'original_run_sha256': sha256_json(run),
            'outcome': 'resolved_by_material', 'result_evidence_refs': [],
            'resolved_annotation_id': self.current['annotation_id'],
            'resolved_annotation_sha256': sha256_json(self.current), 'resolved_facts': ['protection_content'],
            'original_response_reading': 'Actual fault, not an empty patent search and not figures.',
            'original_raw_sha256': {str(raw): sha256_file(raw)},
            'replacement_materials': [{'evidence_id': 'PDF1', 'publication_number': f.candidate['publication_number'],
                'jurisdiction': 'US', 'reading_level': 'independent_claims', 'pages_read': [1, 2, 3, 4],
                'identity_reading': 'Cover exactly identifies this publication; not a family member.',
                'content_reading': 'Actually read the retained independent claim pages.',
                'limitations': 'Does not establish current owner or legal effect.',
                'file_refs': [{'path': str(pdf), 'sha256': sha256_file(pdf)}]}],
            'reason': 'Exact replacement content was separately retained and read; source failure preserved.',
            'reviewer': 'isolated-offline-test'}

    def reject(self, mutation, pattern):
        request = deepcopy(self.request)
        mutation(request)
        with self.assertRaisesRegex(ValueError, pattern):
            record_review(self.f.path, request)

    def test_resolves_without_rewriting_failed_run_or_fabricating_result_evidence(self):
        before = deepcopy(self.f.evidence['source_runs'])
        event = record_review(self.f.path, self.request)
        self.assertEqual(event['outcome'], 'resolved_by_material')
        self.assertEqual(event['result_evidence_refs'], [])
        self.assertEqual(load_json(self.f.path / 'evidence.json')['source_runs'], before)
        task = load_json(self.f.path / 'task.json')
        self.assertEqual(pending_review_entries(task, self.f.evidence, self.f.plan, self.f.ledger), [])
        self.assertEqual(record_review(self.f.path, self.request)['event_id'], event['event_id'])

    def test_wrong_document_country_unread_page_and_changed_bytes_rejected(self):
        for key, value, error in [('publication_number','US999999B2','IDENTITY_INVALID'),
                                 ('jurisdiction','JP','IDENTITY_INVALID'),
                                 ('reading_level','abstract','IDENTITY_INVALID'),
                                 ('pages_read',[1, 99],'EXACT_DOCUMENT_REQUIRED')]:
            with self.subTest(key=key):
                self.reject(lambda r: r['replacement_materials'][0].update({key:value}), error)
        Path(self.doc['path']).write_bytes(b'%PDF-changed')
        with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH'):
            record_review(self.f.path, self.request)

    def test_no_api_evidence_laundering(self):
        self.reject(lambda r:r.update(result_evidence_refs=['PDF1']), 'SOURCE_MISMATCH')
        self.reject(lambda r:r.update(original_run_sha256='0'*64), 'ORIGINAL_RUN_NOT_RESOLVED')
        self.reject(lambda r:r.update(resolved_annotation_sha256='0'*64), 'UPDATED_DECISION_REQUIRED')
        self.reject(lambda r:r.update(resolved_facts=['rights_holder']), 'RESOLUTION_SCOPE_REQUIRED')

    def test_original_submission_unknown_and_unreviewed_failure_remain_open(self):
        self.f.evidence['recovery_reviews'] = []
        self.f.save()
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_RUN_NOT_RESOLVED'):
            record_review(self.f.path, self.request)
        run = self.f.evidence['source_runs'][0]
        run['submission_state'] = 'submitted'
        self.request['original_run_sha256'] = sha256_json(run)
        self.f.save()
        with self.assertRaisesRegex(ValueError, 'FAILURE_REVIEW_REQUIRED'):
            record_review(self.f.path, self.request)

    def test_legacy_has_no_new_outcome(self):
        self.f.task.pop('retrieval_workflow_revision')
        self.f.save()
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_RUN_NOT_RESOLVED'):
            record_review(self.f.path, self.request)

    def test_registered_identity_mismatch_not_repaired_by_request_label(self):
        self.doc['publication_number'] = 'JP11111111B2'
        self.f.save()
        # Current decision is stale after source changes; neither route may accept it.
        with self.assertRaisesRegex(ValueError, 'UPDATED_DECISION_REQUIRED|EXACT_DOCUMENT_REQUIRED'):
            record_review(self.f.path, self.request)

    def test_material_tamper_after_record_is_detected(self):
        record_review(self.f.path, self.request)
        task = load_json(self.f.path/'task.json')
        Path(self.doc['path']).write_bytes(b'%PDF-tampered')
        with self.assertRaisesRegex(ValueError, 'REPLACEMENT_FILE_CHANGED'):
            verify_review_sources(task, self.f.evidence)

    def test_source_success_with_unread_links_can_only_close_via_separate_material(self):
        run=self.f.evidence['source_runs'][0]
        run.update(status='success',submission_state='submitted')
        self.f.evidence['recovery_reviews']=[]
        self.request['original_run_sha256']=sha256_json(run)
        self.f.save()
        self.assertEqual(record_review(self.f.path,self.request)['outcome'],'resolved_by_material')

    def test_exact_application_and_immutable_new_decision_are_enforced(self):
        self.reject(lambda r:r['replacement_materials'][0].update(application_identity_reading={
            'pdf_cover':'29/999,999','ops':'US202429999999F'}),'APPLICATION_MISMATCH')
        record_review(self.f.path,self.request)
        changed=deepcopy(self.f.ledger)
        changed['annotations'][-1]['reason']='Retrospectively changed meaning'
        with self.assertRaisesRegex(ValueError,'DECISION_CHANGED'):
            verify_review_sources(load_json(self.f.path/'task.json'),self.f.evidence,ledger=changed)


    def test_only_user_information_can_remain(self):
        f = self.f
        action = {'action_id':'USER2','kind':'user_information','purpose':'hidden internals',
            'question':'What closure is actually fitted?', 'user_exclusive_reason':'Only the actual supplier has the internals',
            'followup_basis':f.basis(refs=['E1','PDF1'])}
        decision = f.f.annotation('needs_info', evidence_refs=['E1','PDF1'], reading_level='independent_claims',
            missing_information=['Actual hidden closure'], next_actions=[action])
        f.ledger['annotations'].append(decision)
        f.save()
        self.request.update(resolved_annotation_id=decision['annotation_id'], resolved_annotation_sha256=sha256_json(decision))
        event = record_review(f.path, self.request)
        self.assertEqual(event['material_resolution']['remaining_user_action_ids'], ['USER2'])
        # An executable source request remains blocking, even with the same replacement PDF.
        f.task = load_json(f.path/'task.json')
        decision = f.f.annotation('needs_info', evidence_refs=['E1','PDF1'], reading_level='independent_claims',
            missing_information=['Actual hidden closure'], next_actions=[f.exact()])
        f.ledger['annotations'].append(decision)
        f.save()
        self.request.update(resolved_annotation_id=decision['annotation_id'], resolved_annotation_sha256=sha256_json(decision))
        with self.assertRaisesRegex(ValueError, 'SOURCE_WORK_REMAINS'):
            record_review(f.path, self.request)


if __name__ == '__main__':
    unittest.main()

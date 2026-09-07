"""Qualified old fact proof, not wrapper metadata, supports current opinions."""
from copy import deepcopy
import unittest

from assessment_estimate import _historical_review_refs


class HistoricalReviewSupportTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(scenario_id='brand_reuse', scenario_sha256='scenario', jurisdiction='US',
                        right_type='trademark_word', candidate_id='CAND', evidence_refs=['EV-OLD'])
        payload = dict(candidate_id='CAND', jurisdiction='US', right_type='trademark_word',
                       serial_number='88778703', case_status='Abandoned')
        descriptor = dict(kind='historical_source_reuse', path='/old/evidence.json', sha256='filehash', bytes=100)
        item = dict(kind='retained_source_record', path='/old/evidence.json', sha256='filehash', bytes=100,
                    original_task_id='OLD', original_entry_sha256='entryhash', source_checked_at='old-date', payload=payload)
        self.registry = {'EV-REUSE': descriptor, 'EV-OLD': item}
        self.validated = deepcopy(self.registry)
        proof = {k: self.row[k] for k in ('scenario_id', 'scenario_sha256', 'jurisdiction', 'right_type')}
        proof.update(complete=True, authority_scope='original_official_verification', action_purpose='official_verification',
                     reuse_evidence_id='EV-REUSE', evidence_ids=['EV-OLD'], source_task_id='OLD',
                     source_evidence_sha256={'EV-OLD': 'entryhash'}, source_checked_at='old-date', payload=[deepcopy(payload)])
        self.coverage = [{**{k: self.row[k] for k in ('scenario_id', 'scenario_sha256', 'jurisdiction', 'right_type')},
                          'queries': [{'complete': True, 'historical_reuse': proof}]}]

    def result(self):
        return _historical_review_refs(self.row, self.coverage, self.registry, self.validated)

    def test_qualified_exact_original_reference_is_retained_without_rebinding(self):
        before = deepcopy((self.coverage, self.registry, self.validated))
        self.assertEqual(self.result(), {'EV-OLD'})
        self.assertEqual(before, (self.coverage, self.registry, self.validated))

    def test_wrapper_alone_or_incomplete_reuse_is_not_authority(self):
        for field in ('complete', 'historical_reuse'):
            with self.subTest(field=field):
                self.setUp()
                self.coverage[0]['queries'][0].pop(field)
                self.assertEqual(self.result(), set())
        self.setUp()
        self.validated.pop('EV-REUSE')
        self.assertEqual(self.result(), set())

    def test_cross_scope_candidate_and_changed_payload_are_rejected(self):
        for field in ('scenario_id', 'scenario_sha256', 'jurisdiction', 'right_type', 'candidate_id'):
            with self.subTest(field=field):
                self.setUp()
                self.row[field] = 'wrong'
                self.assertEqual(self.result(), set())
        self.setUp()
        for data in (self.registry, self.validated):
            data['EV-OLD']['payload']['case_status'] = 'Changed'
        self.assertEqual(self.result(), set())

    def test_entry_hash_source_bytes_task_and_original_date_must_match(self):
        for field in ('original_entry_sha256', 'path', 'sha256', 'bytes', 'original_task_id', 'source_checked_at'):
            with self.subTest(field=field):
                self.setUp()
                for data in (self.registry, self.validated):
                    data['EV-OLD'][field] = 'changed'
                self.assertEqual(self.result(), set())

    def test_recall_or_document_reuse_cannot_prove_current_official_status(self):
        for field, value in (('authority_scope', 'published_document_only'), ('action_purpose', 'recall')):
            with self.subTest(field=field):
                self.setUp()
                self.coverage[0]['queries'][0]['historical_reuse'][field] = value
                self.assertEqual(self.result(), set())


if __name__ == '__main__':
    unittest.main()

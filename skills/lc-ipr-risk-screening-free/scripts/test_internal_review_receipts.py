"""Recorder-to-review regressions; synthetic local materials, no network/model."""
from copy import deepcopy
from pathlib import Path
import json
import unittest

from common import atomic_write_json, load_json


class InternalReceiptTests(unittest.TestCase):
    def setUp(self):
        from offline_test_support import isolated_test_environment
        from test_product_feedback import ProductFeedbackTests
        self.environment = isolated_test_environment()
        self.environment.__enter__()
        self.addCleanup(self.environment.__exit__, None, None, None)
        self.f = ProductFeedbackTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.enable_structure_policy()
        self.f.save_request()

    def packet(self):
        from decision_workflow import LEDGER_SCHEMA_VERSION
        task = load_json(self.f.run / 'task.json')
        return {'task': task,
                'evidence': load_json(self.f.run / 'evidence.json'),
                'candidates': load_json(self.f.run / 'normalized-candidates.json'),
                'search_plan': self.f.plan, 'materiality_ledger': {
                    'schema_version': LEDGER_SCHEMA_VERSION, 'task_id': task['task_id'], 'annotations': []},
                'evidence_digest': 'offline-internal-receipt-materials'}

    def revise(self, *, withdraw=False):
        task = self.packet()['task']
        payload = self.f.fixture.payload
        payload['expected_scope_sha256'] = task['product_scope']['scope_sha256']
        fact = payload['scope']['facts'][1]
        fact.update(version=2, reason='Withdraw unknown mechanism.' if withdraw else 'Correct volunteered fact.',
                    status='unknown' if withdraw else 'confirmed', verification='unverified' if withdraw else 'claim_only')
        if not withdraw:
            fact['value'] = 'mechanical latch'
        else:
            fact['question'] = 'Which retained evidence establishes the actual mechanism?'
        self.f.fixture.save()
        return self.packet()['task']['product_change_history'][-1]

    def applicability(self):
        from record_product_applicability import record
        event = self.revise()
        task = self.packet()['task']
        request = {'schema_version': 'product-applicability-v1',
                   'product_version': task['product_change_version'],
                   'target_sha256': task['product_identity']['sha256'],
                   'scope_sha256': task['product_scope']['scope_sha256'],
                   'reviews': [{'change_id': event['change_id'], 'candidate_id': 'CAND-feedback',
                                'status': 'needs_info', 'reviewer': 'offline-reviewer',
                                'reason': 'The mechanism remains unverified.', 'source_refs': [self.f.source_id]}]}
        atomic_write_json(self.f.path, request)
        record(self.f.run, self.f.path)

    def attach(self, packet=None):
        from module_review import attach_originals
        packet = self.packet() if packet is None else packet
        attach_originals(packet, self.f.run)
        return packet

    def assert_full_and_modules(self, collection):
        from module_review import module_packet
        from adaptive_review import measure
        packet = self.packet()
        key = packet['evidence']['collections'][collection][-1]['sha256']
        for group in (None, 'technical', 'appearance', 'expression'):
            value = deepcopy(packet) if group is None else module_packet(packet, group)
            with self.subTest(group=group, collection=collection):
                self.attach(value)
                self.assertIn(key, {row['sha256'] for row in value['retained_originals']['inline_internal_receipts']})
                self.assertGreater(measure(value, {})['review_json_chars'], 0)

    def test_real_unavailable_feedback_is_inline_without_clearing_limit(self):
        from product_feedback import unavailable, assessment_gate
        self.assert_full_and_modules('product_feedback')
        packet = self.attach()
        self.assertTrue(unavailable(packet['task']))
        self.assertEqual(packet['task']['product_scope']['facts'][1]['verification'], 'claim_only')
        assessment_gate(packet['task'], [{'candidate_id': 'CAND-feedback', 'risk': '低'}])     # best-estimate: disclosed limit
        with self.assertRaisesRegex(ValueError, 'COMPARISON_PENDING'):
            assessment_gate({**packet['task'], 'best_estimate_revision': None}, [{'candidate_id': 'CAND-feedback', 'risk': '低'}])

    def test_real_fact_correction_full_and_module_projection(self):
        self.assertEqual(self.revise()['kind'], 'fact_correction')
        self.assert_full_and_modules('product_changes')

    def test_real_fact_withdrawal_full_and_module_projection(self):
        self.assertEqual(self.revise(withdraw=True)['kind'], 'fact_withdrawal')
        self.assert_full_and_modules('product_changes')

    def test_real_applicability_full_and_module_projection(self):
        self.applicability()
        self.assert_full_and_modules('product_applicability')

    def test_modified_or_missing_inline_history_is_rejected(self):
        from module_review import module_packet
        self.applicability()
        for field in ('product_feedback_history', 'product_change_history', 'product_applicability_reviews'):
            for mode in ('missing', 'changed', 'binding'):
                for group in (None, 'technical', 'appearance'):
                    packet = self.packet()
                    if group:
                        packet = module_packet(packet, group)
                    if mode == 'missing':
                        packet['task'].pop(field)
                    elif mode == 'binding':
                        packet['task'][field][-1]['candidate_id'] = 'OTHER-CANDIDATE'
                    else:
                        packet['task'][field][-1]['reason'] = 'Unrecorded rewritten decision'
                    with self.subTest(field=field, mode=mode, group=group), self.assertRaisesRegex(ValueError, 'INLINE_MISMATCH'):
                        self.attach(packet)

    def test_internal_receipt_tamper_rejects_real_original(self):
        self.applicability()
        for collection in ('product_feedback', 'product_changes', 'product_applicability'):
            path = Path(self.packet()['evidence']['collections'][collection][-1]['path'])
            saved = path.read_bytes()
            try:
                path.write_bytes(b'{}')
                with self.subTest(collection=collection), self.assertRaises(ValueError):
                    self.attach()
            finally:
                path.write_bytes(saved)

    def test_receipt_event_binding_and_foreign_task_rejected(self):
        self.applicability()
        for collection, identity in (('product_feedback', 'event_id'), ('product_changes', 'change_id'),
                                     ('product_applicability', 'review_id')):
            packet = self.packet()
            packet['evidence']['collections'][collection][-1][identity] = 'FOREIGN-EVENT'
            with self.subTest(collection=collection), self.assertRaisesRegex(ValueError, 'INLINE_MISMATCH'):
                self.attach(packet)
        packet = self.packet()
        packet['task']['task_id'] = 'OTHER-TASK'
        with self.assertRaisesRegex(ValueError, 'INLINE_MISMATCH'):
            self.attach(packet)

    def test_orphan_and_self_declared_internal_receipts_not_exempted(self):
        packet = self.packet()
        row = packet['evidence']['collections']['product_feedback'][0]
        packet['evidence']['collections']['unrecognized'] = [dict(row, kind='internal')]
        packet['evidence']['collections']['product_feedback'] = []
        with self.assertRaisesRegex(ValueError, 'INLINE_MISMATCH'):
            self.attach(packet)

    def test_feedback_without_formal_recorder_policy_cannot_claim_internal_status(self):
        from product_delivery import project
        task = self.packet()['task']
        task.pop('product_feedback_revision')
        task['product_delivery'] = project(task)
        atomic_write_json(self.f.run / 'task.json', task)
        with self.assertRaisesRegex(ValueError, 'CONTRACT_REQUIRED'):
            self.attach()

    def test_no_local_body_transmission_and_threshold_unchanged(self):
        from adaptive_review import prepare
        from report_review_host import review_payload_view
        payload = self.f.fixture.payload
        task = self.packet()['task']
        payload['expected_scope_sha256'] = task['product_scope']['scope_sha256']
        path = self.f.run / '本地 私有原文.txt'
        marker = 'UNTRANSMITTED-PRIVATE-ORIGINAL'
        path.write_text(marker, encoding='utf-8')
        payload['sources'].append({'source_id': 'local-document', 'kind': 'document', 'path': str(path)})
        payload['scope']['facts'][0]['source_refs'].append('local-document')
        self.f.fixture.save()
        packet = self.attach()
        self.assertNotIn(marker, json.dumps(review_payload_view(packet)))
        self.assertTrue(packet['retained_originals']['not_transmitted'])
        self.assertIsNotNone(prepare(packet, self.f.run, []))
        packet['evidence']['collections']['inline_large_fixture'] = [{'text': 'A' * 120001}]
        self.assertIsNone(prepare(packet, self.f.run, []))


if __name__ == '__main__':
    unittest.main()

"""Negative page provenance and lossless compact-report regressions."""
import copy
import unittest
from unittest.mock import patch

import report_estimate as report
import test_report_core_visuals as fixtures


class CorrectedVisualTests(unittest.TestCase):
    setUp = fixtures.CoreVisualTests.setUp
    tearDown = fixtures.CoreVisualTests.tearDown
    document = fixtures.CoreVisualTests.document
    build = fixtures.CoreVisualTests.build
    def test_out_of_range_and_wrong_child_identity_cannot_enter_board(self):
        doc, page = self.document()
        for changes, code in (({'page_number': 999}, 'PDF_PAGE_OUT_OF_RANGE'),
                              ({'publication_number': 'USD999999S'}, 'PDF_PAGE_IDENTITY_CONFLICT')):
            saved = copy.deepcopy(page)
            page.update(changes)
            data, _ = self.build()
            self.assertFalse(report._section_figures(data['sections']))
            self.assertIn(code, str(data['visual_gaps']))
            self.assertEqual(data['overall']['risk'], '中')
            page.clear()
            page.update(saved)

    def test_page_receipt_missing_wrong_parent_or_wrong_image_fails(self):
        _, page = self.document()
        valid = copy.deepcopy(page['page_verification'])
        for changed in ({}, {**valid, 'source_document_sha256': '0' * 64}, {**valid, 'image_sha256': '0' * 64}):
            page['page_verification'] = changed
            data, _ = self.build()
            self.assertFalse(report._section_figures(data['sections']))
            self.assertIn('PROVENANCE_MISSING_OR_STALE', str(data['visual_gaps']))

    def test_valid_page_does_not_render_again(self):
        self.document()
        with patch('pdf_page_evidence.render_page', side_effect=AssertionError('unexpected render')):
            data, _ = self.build()
            self.assertEqual(len(report._section_figures(data['sections'])), 1)

    def test_legacy_visual_policy_keeps_old_read_only_semantics(self):
        self.document(page=999)
        with patch.object(report, '_canonical'):
            data = report.build_report_data(self.root, self.task, self.evidence, self.assessment, {}, self.journal, {},
                output_dir=self.out, visual_policy_revision=report.LEGACY_VISUAL_POLICY_REVISION)
        self.assertEqual(report._section_figures(data['sections'])[0]['page_number'], 999)

    def test_unlocated_historical_page_remains_evidence_not_a_visual(self):
        from assessment_estimate import validate_supplement
        doc, page = self.document()
        page.pop('page_verification')
        page.pop('page_number')
        for item in (doc, page):
            item.update(kind='patent_document', checked_at='2026-09-07T00:00:00Z',
                        bytes=__import__('pathlib').Path(item['path']).stat().st_size)
        indexed = validate_supplement({'schema': 'test', 'evidence': [doc, page]}, self.root,
            task={'workflow_correction_revision': 'workflow-correction-v1',
                  'decision_workflow_revision': 'scenario-triage-v1'})
        self.assertIn(page['evidence_id'], indexed)
        data, _ = self.build()
        self.assertFalse(report._section_figures(data['sections']))
        self.assertTrue(data['visual_gaps'])


class CompactModelTests(unittest.TestCase):
    def test_all_complete_decisions_recover_without_duplicate_storage(self):
        row = {'candidate_id': 'C1', 'scenario_id': 'product_entry', 'right_type': 'patent',
               'decision': 'needs_info', 'annotation': {'reason': 'Missing abstract', 'evidence_refs': ['EV-1']}}
        data = {'coverage': {'triage': {'records': [row], 'counts': {'needs_info': 1}},
                 'scopes': [{'queues': {'needs_info': [row]}}]},
                'scenario_summaries': [{'completion': {'queues': {'needs_info': [row]}}}]}
        original = copy.deepcopy(data)
        compact = report._compact_report_data(data)
        self.assertEqual(data, original)
        self.assertEqual(len(compact['decision_records']), 1)
        queues = [compact['coverage']['triage']['records'], compact['coverage']['scopes'][0]['queues']['needs_info'],
                  compact['scenario_summaries'][0]['completion']['queues']['needs_info']]
        for queue in queues:
            self.assertEqual([report._queue_record(compact, item) for item in queue], [row])
        compact['decision_records'].clear()
        with self.assertRaisesRegex(ValueError, 'REFERENCE_MISSING'):
            report._queue_record(compact, queues[0][0])

    def test_unique_source_keeps_independent_file_hash_checks(self):
        a = {'path': 'files/a.pdf', 'source_path': '/tmp/a.pdf', 'sha256': 'a'}
        b = {'path': 'files/b.pdf', 'source_path': '/tmp/b.pdf', 'sha256': 'a'}
        self.assertEqual(list(report._unique_file_records([a, a, b], source=True)), [a, b])


if __name__ == '__main__':
    unittest.main()

"""Current-risk media policy, exact document derivation and legacy compatibility."""
import copy
import base64
import unittest
from unittest.mock import patch

import report_estimate as report
import test_report_estimate as fixtures

PNG = fixtures.PNG
# Synthetic 1x1 AVIF; self-contained fixture, not a business image or a runtime
# imaging dependency. Original evidence is never converted to create a report.
AVIF = base64.b64decode('AAAAIGZ0eXBhdmlmAAAAAGF2aWZtaWYxbWlhZk1BMUIAAADrbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAcGljdAAAAAAAAAAAAAAAAAAAAAAOcGl0bQAAAAAAAQAAAB5pbG9jAAAAAEQAAAEAAQAAAAEAAAETAAAAKQAAAChpaW5mAAAAAAABAAAAGmluZmUCAAAAAAEAAGF2MDFDb2xvcgAAAABqaXBycAAAAEtpcGNvAAAAFGlzcGUAAAAAAAAAAQAAAAEAAAAQcGl4aQAAAAADCAgIAAAADGF2MUOBAAwAAAAAE2NvbHJuY2x4AAEADQAGgAAAABdpcG1hAAAAAAAAAAEAAQQBAoMEAAAAMW1kYXQSAAoIGAAGiAhoNCAyGxTHh4ZlAgggnlAAAABIWtlc1jCwqa4ViKkOYA==')


class CoreVisualTests(unittest.TestCase):
    setUp = fixtures.EstimateReportTests.setUp
    tearDown = fixtures.EstimateReportTests.tearDown

    def build(self, content=None):
        with patch.object(report, '_canonical'):
            return report.build_bundle(self.root, self.task, self.evidence, self.assessment, {}, self.journal, {},
                                       output_dir=self.out, report_content=content)

    def document(self, *, role='patent_drawings', page=2, suffix=''):
        from pypdf import PdfWriter
        pdf = self.root / 'patent.pdf'
        writer = PdfWriter()
        for _ in range(10):
            writer.add_blank_page(width=100, height=100)
        writer.write(pdf)
        doc = {'evidence_id': 'PDF', 'path': str(pdf), 'sha256': report._sha(pdf.read_bytes()),
               'source_url': 'https://example.com/patent.pdf', 'jurisdiction': 'US', 'right_type': 'design',
               'publication_number': 'USD123456S'}
        image = self.root / ('page' + suffix + '.png')
        image.write_bytes(PNG + suffix.encode())
        derived = {'evidence_id': 'PAGE' + suffix, 'path': str(image), 'sha256': report._sha(image.read_bytes()),
                   'source_document': str(pdf), 'source_document_sha256': doc['sha256'],
                   'source_url': doc['source_url'], 'visual_role': role, 'page_number': page,
                   'source_checked_at': '2026-09-01T00:00:00Z', 'checked_at': '2026-09-07T00:00:00Z'}
        derived['page_verification'] = {'schema': 'IPR-PDF-PAGE/1.0', 'method': 'agent_page_verification',
            'source_document_sha256': doc['sha256'], 'page_count': 10, 'page_number': page or 2,
            'image_sha256': derived['sha256'], 'reviewer': 'offline-fixture',
            'reviewed_at': '2026-09-07T00:00:00Z', 'reasoning': 'Synthetic fixture page association.'}
        if not any(item.get('evidence_id') == 'PDF' for item in self.evidence['collections']):
            self.evidence['collections'].append(doc)
        self.evidence['collections'].append(derived)
        self.assessment['assessments'][0]['evidence_refs'] = ['PDF']
        self.assessment['assessments'][0]['publication_number'] = 'USD123456S'
        return doc, derived

    def test_new_build_defaults_to_core_policy_and_reuses_exact_pdf_pages(self):
        doc, page = self.document()
        data, manifest = self.build()
        figures = report._section_figures(data['sections'])
        self.assertEqual(data['visual_policy_revision'], report.VISUAL_POLICY_REVISION)
        self.assertEqual(manifest['visual_policy_revision'], report.VISUAL_POLICY_REVISION)
        self.assertEqual([item['evidence_id'] for item in figures], ['PAGE'])
        self.assertEqual(figures[0]['source_document_sha256'], doc['sha256'])
        self.assertEqual(figures[0]['source_evidence_id'], 'PDF')
        self.assertEqual(figures[0]['page_number'], 2)
        self.assertEqual(figures[0]['checked_at'], '2026-09-01T00:00:00Z')
        self.assertEqual(data['visual_gaps'], [])
        for filename in ('report.html', 'report.md', 'report-findings.csv'):
            rendered = (self.out / filename).read_text(encoding='utf-8-sig')
            self.assertIn('PAGE', rendered)
        self.assertIn('#page=2', (self.out / 'report.html').read_text())
        self.assertTrue((self.out / figures[0]['source_document_path']).is_file())

    def test_reading_reference_cannot_replace_registered_pdf_page_or_product(self):
        self.document()
        self.evidence['collections'].append({'evidence_id': 'PRODUCT', 'images': self.task['images']})
        self.assessment['assessments'][0]['evidence_refs'].append('PRODUCT')
        before, _ = self.build()
        original = copy.deepcopy(self.evidence)
        self.evidence['collections'].append({'evidence_id': 'READING', 'reviewed_sources': [
            {'evidence_id': identifier, 'reading_mode': 'already_read', 'reviewed_at': '2026-09-07T00:00:00Z'}
            for identifier in ('PDF', 'PAGE', 'PRODUCT')]})
        after, _ = self.build({})
        figures = report._section_figures(after['sections'])
        self.assertEqual([r['evidence_id'] for r in figures], ['PAGE', 'PRODUCT'])
        self.assertEqual(after['sections'], before['sections'])
        self.assertEqual(self.evidence['collections'][:-1], original['collections'])

    def test_registered_index_ignores_nested_unregistered_media_and_conflicts_fail(self):
        original = {'evidence_id': 'SOURCE', 'path': 'real.png', 'sha256': '1' * 64}
        shadow = {'evidence_id': 'SOURCE', 'path': 'wrong.png', 'sha256': '2' * 64}
        evidence = {'collections': {'sources': [original]}, 'source_runs': [{'nested': shadow}]}
        supplement = {'evidence': [{'evidence_id': 'READ', 'sources': [shadow]}]}
        self.assertEqual(report._registry(evidence, supplement, registered_only=True)['SOURCE'], original)
        self.assertEqual(report._registry(evidence, supplement)['SOURCE'], shadow)  # Frozen legacy behavior.
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_REGISTERED_EVIDENCE_ID'):
            report._registry(evidence, {'evidence': [shadow]}, registered_only=True)

    def test_registered_index_does_not_promote_nested_only_evidence_id(self):
        evidence = {'collections': {'sources': [{'evidence_id': 'RECEIPT', 'sources': [
            {'evidence_id': 'NESTED', 'path': 'not-registered.png', 'sha256': '2' * 64}]}]}}
        self.assertEqual(set(report._registry(evidence, registered_only=True)), {'RECEIPT'})

    def test_all_and_only_current_medium_high_critical_candidates(self):
        self.document()
        base = self.assessment['assessments'][0]
        rows = []
        for index, risk in enumerate(report.RISKS):
            rows.append({**copy.deepcopy(base), 'candidate_id': str(index), 'risk': risk})
        rows.extend([{**copy.deepcopy(base), **change} for change in (
            {'candidate_id': 'P', 'assessment_status': 'pending', 'aggregation_included': False},
            {'candidate_id': 'F', 'future_signal': True}, {'candidate_id': 'S', 'signal_only': True},
            {'candidate_id': '', 'risk': '高'}, {'candidate_id': 'O', 'out_of_scope': True})])
        self.assessment['assessments'] = rows
        data, _ = self.build()
        self.assertEqual([section['candidate_id'] for section in data['sections']], ['2', '3', '4'])

    def test_zero_failure_process_and_private_images_do_not_enter(self):
        _, page = self.document()
        base = self.assessment['assessments'][0]
        for index, change in enumerate(({'status': 'no_result'}, {'status': 'failed'}, {'status': 'access_limited'},
                {'status': 'needs_user_action'}, {'payload': {'search_metadata': {'stop_reason': 'zero_results'}}},
                {'role': 'login'}, {'role': 'private'})):
            image = self.root / ('bad-' + str(index) + '.png')
            image.write_bytes(PNG + str(index).encode())
            item = {**page, **change, 'evidence_id': 'BAD' + str(index), 'path': str(image),
                    'sha256': report._sha(image.read_bytes())}
            self.evidence['collections'].append(item)
            base['evidence_refs'].append(item['evidence_id'])
        process_image = self.root / 'process.png'
        process_image.write_bytes(PNG + b'process')
        process = {'evidence_id': 'PROCESS', 'payload': {'screenshot_path': str(process_image),
                   'screenshot_sha256': report._sha(process_image.read_bytes()), 'search_metadata': {'reported_total': 100}}}
        self.evidence['collections'].append(process)
        base['evidence_refs'].append('PROCESS')
        data, _ = self.build()
        self.assertEqual([item['evidence_id'] for item in report._section_figures(data['sections'])], ['PAGE'])

    def test_page_metadata_missing_is_not_guessed_and_risk_survives(self):
        self.document(page=None)
        data, _ = self.build()
        self.assertEqual(report._section_figures(data['sections']), [])
        self.assertEqual(data['overall']['risk'], '中')
        self.assertEqual(data['visual_gaps'][0]['missing_roles'], ['patent_drawings'])
        self.assertIn('准确页码', str(data['visual_gaps']))

    def test_wrong_document_hash_fails_without_name_based_fallback(self):
        _, page = self.document()
        page['source_document_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_SOURCE_HASHES'):
            self.build()

    def test_same_filename_different_document_is_not_a_derivative_match(self):
        doc, page = self.document()
        alternate = self.root / 'other'
        alternate.mkdir()
        other = alternate / 'patent.pdf'
        other.write_bytes(b'%PDF different original')
        page['source_document'] = str(other)
        page['source_document_sha256'] = report._sha(other.read_bytes())
        self.evidence['collections'].append({'evidence_id': 'OTHER', 'path': str(other),
                                             'sha256': page['source_document_sha256']})
        data, _ = self.build()
        self.assertEqual(report._section_figures(data['sections']), [])

    def test_referenced_family_or_prior_art_number_is_not_the_current_right(self):
        doc, _ = self.document()
        doc['publication_number'] = 'USD999999S'
        data, _ = self.build()
        self.assertEqual(report._section_figures(data['sections']), [])
        self.assertIn('未精确绑定', str(data['visual_gaps']))

    def test_enriched_page_registration_reuses_bytes_without_changing_old_entry(self):
        _, page = self.document(page=None)
        original = copy.deepcopy(page)
        self.evidence['collections'].append({**page, 'evidence_id': 'PAGE-ENRICHED', 'page_number': 2})
        data, _ = self.build()
        self.assertEqual(page, original)
        self.assertEqual(data['visual_gaps'], [])
        self.assertEqual([item['evidence_id'] for item in report._section_figures(data['sections'])], ['PAGE-ENRICHED'])

    def test_media_follows_its_run_not_an_unrelated_failed_attempt(self):
        doc, _ = self.document()
        doc.update(source_run_id='GOOD', query_id='Q')
        self.evidence['source_runs'] = [{'run_id': 'BAD', 'query_id': 'Q', 'status': 'failed'},
                                       {'run_id': 'GOOD', 'query_id': 'Q', 'status': 'success'}]
        data, _ = self.build()
        self.assertEqual(len(report._section_figures(data['sections'])), 1)
        doc['source_run_id'] = 'BAD'
        data, _ = self.build()
        self.assertEqual(report._section_figures(data['sections']), [])

    def test_exact_registry_identity_can_show_substantive_record_not_other_candidate(self):
        row = self.assessment['assessments'][0]
        row.update(right_type='trademark_word', module_id='word_mark')
        image = self.root / 'record.png'
        image.write_bytes(PNG + b'official')
        source = {'evidence_id': 'REGISTER', 'payload': {'candidate_id': row['candidate_id'], 'jurisdiction': 'US',
                  'right_type': 'trademark_word', 'official_verification': {'identity_match': True},
                  'browser_evidence': {'screenshot_path': str(image), 'screenshot_sha256': report._sha(image.read_bytes())}}}
        self.evidence['collections'].append(source)
        self.evidence['collections'].append({'evidence_id': 'PRODUCT', 'images': self.task['images']})
        row['evidence_refs'] = ['REGISTER', 'PRODUCT']
        data, _ = self.build()
        self.assertEqual([item['evidence_id'] for item in report._section_figures(data['sections'])], ['REGISTER'])
        row['comparison'] = {'visual_coverage': {'product_views': [{'artifact_sha256': report._sha(PNG), 'evidence_refs': ['PRODUCT']}]}}
        data, _ = self.build()
        self.assertEqual([item['evidence_id'] for item in report._section_figures(data['sections'])], ['REGISTER', 'PRODUCT'])
        source['payload']['candidate_id'] = 'OTHER'
        data, _ = self.build()
        self.assertEqual(report._section_figures(data['sections']), [])

    def test_explicit_content_cannot_hide_required_pages_or_add_unselected_image(self):
        self.document()
        automatic, _ = self.build()
        explicit, _ = self.build({})
        self.assertEqual(automatic['sections'], explicit['sections'])
        other = self.root / 'unselected.png'
        other.write_bytes(PNG + b'other')
        self.evidence['collections'].append({'evidence_id': 'UNSELECTED', 'path': str(other),
                                             'sha256': report._sha(other.read_bytes())})
        with self.assertRaisesRegex(ValueError, 'EXPLICIT_VISUAL_NOT_ELIGIBLE'):
            self.build({'sections': [{'blocks': [{'type': 'figures', 'items': [{'path': str(other)}]}]}]})

    def test_original_avif_comparison_is_hash_bound_and_embedded_without_conversion(self):
        row = self.assessment['assessments'][0]
        row.update(right_type='trademark_figurative', module_id='figurative_trade_dress')
        image = self.root / 'mark.png'
        image.write_bytes(PNG + b'mark')
        rights = {'evidence_id': 'REGISTER', 'path': str(image), 'sha256': report._sha(image.read_bytes()),
                  'candidate_id': row['candidate_id'], 'jurisdiction': 'US', 'right_type': 'trademark_figurative',
                  'visual_role': 'registry_record'}
        logo = self.root / 'logo.avif'
        logo.write_bytes(AVIF)
        product = {'evidence_id': 'LOGO', 'path': str(logo), 'sha256': report._sha(AVIF),
                   'visual_role': 'product_comparison', 'source_url': 'https://example.com/logo.avif'}
        self.evidence['collections'].extend([rights, product])
        row['evidence_refs'] = ['REGISTER', 'LOGO']
        data, _ = self.build()
        self.assertEqual([item['evidence_id'] for item in report._section_figures(data['sections'])], ['REGISTER'])
        row['comparison'] = {'visual_coverage': {'product_views': [{'artifact_sha256': product['sha256']}]}}
        with patch.object(report.mimetypes, 'guess_type', side_effect=lambda name: ('image/png', None) if str(name).endswith('.png') else (None, None)):
            data, _ = self.build()
        figures = report._section_figures(data['sections'])
        self.assertEqual([item['evidence_id'] for item in figures], ['REGISTER', 'LOGO'])
        self.assertEqual(figures[-1]['mime_type'], 'image/avif')
        self.assertEqual((self.out / figures[-1]['path']).read_bytes(), AVIF)
        self.assertIn('data:image/avif;base64,' + base64.b64encode(AVIF).decode(), (self.out / 'report.html').read_text())
        # A declared hash is sufficient even when an original image has no role;
        # but neither a product-only group nor a low-risk row becomes core media.
        product.pop('visual_role')
        data, _ = self.build()
        self.assertEqual([item['evidence_id'] for item in report._section_figures(data['sections'])], ['REGISTER', 'LOGO'])
        rights['candidate_id'] = 'OTHER'
        data, _ = self.build()
        self.assertEqual(report._section_figures(data['sections']), [])
        rights['candidate_id'] = row['candidate_id']
        row['risk'] = '低'
        data, _ = self.build()
        self.assertEqual(report._section_figures(data['sections']), [])

    def test_explicit_comparison_hash_does_not_import_sibling_gallery_or_failed_image(self):
        self.document()
        row = self.assessment['assessments'][0]
        extra = self.root / 'extra.png'
        extra.write_bytes(PNG + b'unrelated-gallery')
        wanted = {**self.task['images'][0]}
        sibling = {**wanted, 'path': str(extra), 'sha256': report._sha(extra.read_bytes())}
        self.evidence['collections'].append({'evidence_id': 'GALLERY', 'visual_role': 'product_comparison', 'images': [wanted, sibling]})
        row['evidence_refs'].append('GALLERY')
        row['comparison'] = {'visual_coverage': {'product_views': [{'artifact_sha256': wanted['sha256']}]}}
        data, _ = self.build()
        self.assertEqual([item['sha256'] for item in report._section_figures(data['sections']) if item['visual_role'] == 'product_comparison'], [wanted['sha256']])
        self.evidence['collections'][-1]['status'] = 'no_result'
        data, _ = self.build()
        self.assertEqual([item['evidence_id'] for item in report._section_figures(data['sections'])], ['PAGE'])

    def test_avif_rejects_non_avif_bytes_and_preserves_registered_hash_checks(self):
        path = self.root / 'source.avif'
        for content in (b'<svg onload="bad"/>', b'\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic'):
            path.write_bytes(content)
            item = {'path': str(path), 'sha256': report._sha(content)}
            bindings = {str(path.resolve()): {'sha256': item['sha256'], 'source_urls': set()}}
            with self.assertRaisesRegex(ValueError, 'REPORT_IMAGE_FORMAT'):
                report._local_info(self.root, self.out, item, bindings=bindings, image=True)
        path.write_bytes(AVIF)
        with self.assertRaisesRegex(ValueError, 'REPORT_SOURCE_HASH_MISMATCH'):
            report._local_info(self.root, self.out, {'path': str(path)}, bindings=bindings, image=True)

    def test_scenario_groups_share_file_bytes_without_losing_bindings(self):
        self.document()
        row = self.assessment['assessments'][0]
        row['scenario_id'] = 'first'
        self.assessment['assessments'].append({**copy.deepcopy(row), 'scenario_id': 'conditional'})
        data, _ = self.build()
        figures = report._section_figures(data['sections'])
        self.assertEqual([item['scenario_id'] for item in figures], ['first', 'conditional'])
        self.assertEqual(len({item['path'] for item in figures}), 1)
        self.assertEqual(len(data['sections']), 2)

    def test_product_only_is_not_core_evidence_and_counts_exclude_snapshot(self):
        product = {'evidence_id': 'PRODUCT', 'images': self.task['images']}
        self.evidence['collections'].append(product)
        row = self.assessment['assessments'][0]
        row['evidence_refs'] = ['PRODUCT']
        data, _ = self.build()
        self.assertEqual(report._section_figures(data['sections']), [])
        self.assertEqual(len(data['visual_evidence']), 1)
        self.document(suffix='rights')
        row['evidence_refs'].append('PRODUCT')
        data, _ = self.build()
        self.assertEqual(len(report._section_figures(data['sections'])), 2)
        self.assertIn('2 处图证展示', (self.out / 'report.html').read_text())

    def test_utility_requires_identity_claims_and_drawings_without_changing_grade(self):
        doc, _ = self.document(role='patent_drawings')
        doc.update(right_type='patent', publication_number='US1234567B2')
        self.assessment['assessments'][0].update(right_type='patent', module_id='utility_patent', publication_number='US1234567B2')
        data, _ = self.build()
        self.assertEqual(data['visual_gaps'][0]['missing_roles'], ['document_identity', 'patent_claims'])
        self.document(role='document_identity', page=1, suffix='front')
        self.document(role='patent_claims', page=7, suffix='claims')
        self.assessment['assessments'][0]['publication_number'] = 'US1234567B2'
        data, _ = self.build()
        self.assertEqual(data['visual_gaps'], [])
        self.assertEqual(data['overall']['risk'], '中')

    def test_tampering_fails_and_validation_recomputes_assessment_only_once(self):
        self.document()
        self.build()
        for name, value in [('evidence.json', self.evidence), ('normalized-candidates.json', {}),
                            ('search-plan.json', {}), ('browser-candidate-journal.json', self.journal)]:
            (self.root / name).write_bytes(report._json(value))
        (self.out / 'assessment.json').write_bytes(report._json(self.assessment))
        with patch('assessment_estimate.validate_assessment', return_value=[]) as validate, patch.object(report, '_canonical') as canonical:
            self.assertEqual(report.validate_run(self.root, self.task, output_dir=self.out), [])
            self.assertEqual(validate.call_count, 1)
            canonical.assert_not_called()
        with patch('assessment_estimate.validate_assessment', return_value=['INVALID']) as validate, patch.object(report, 'build_report_data') as build:
            self.assertIn('INVALID', report.validate_run(self.root, self.task, output_dir=self.out))
            build.assert_not_called()
        (self.out / 'report.html').write_text('tampered')
        with patch('assessment_estimate.validate_assessment', return_value=[]):
            self.assertIn('REPORT_ARTIFACT_MISMATCH: report.html', report.validate_run(self.root, self.task, output_dir=self.out))


if __name__ == '__main__':
    unittest.main()

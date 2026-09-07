#!/usr/bin/env python3
"""Behavior checks for five-level rendering, evidence integrity and portability."""
import base64
import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import report_estimate as report

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=')


class EstimateReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / 'out'
        (self.root / 'main.png').write_bytes(PNG)
        (self.root / 'source.txt').write_text('original evidence')
        self.task = {'task_id': 'IPRF-TEST', 'assessment_policy': report.POLICY, 'product': {'title': '蓝款', 'actual_asin': 'B012345678', 'brand': '自有品牌', 'intended_use': '外观功能均与链接一致'}, 'target_jurisdictions': ['US'], 'request': {'url': 'https://www.amazon.com/dp/B012345678'}}
        row = {'jurisdiction': 'US', 'right_type': 'design', 'module_id': 'appearance_patent', 'candidate_id': 'D1', 'title': '具体外观', 'risk': '中', 'evidence_confidence': '低', 'scope': '本件美国设计', 'reasoning': '整体对应与实质差异并存', 'supporting_evidence': [{'reasoning': '实线组合对应', 'evidence_refs': ['E1']}], 'counter_evidence': [{'reasoning': '鼻臂比例不同', 'evidence_refs': ['E1']}], 'assumptions': ['假定按链接制造'], 'confidence_reasoning': '整体差异效力有争议', 'human_checks': [{'priority': '第一', 'owner': '外观专利专业人士', 'question': '复核实线范围', 'evidence_needed': ['授权图'], 'raise_if': ['整体高度对应'], 'lower_if': ['差异足够']}], 'raise_if': ['保护整体高度对应'], 'lower_if': ['证明差异改变整体印象'], 'evidence_refs': ['E1'], 'aggregation_included': True}
        self.assessment = {'assessment_policy': report.POLICY, 'task_id': 'IPRF-TEST', 'generated_at': '2026-09-06', 'assessments': [row], 'overall': {'risk': '中', 'confidence': '低', 'reasons': ['具体冲突路径决定中风险']}, 'coverage': {'scopes': [], 'notes': ['检索有边界']}}
        self.evidence = {'collections': [{'evidence_id': 'E1', 'path': str(self.root / 'source.txt'), 'sha256': report._sha((self.root / 'source.txt').read_bytes()), 'source_url': 'https://example.com/source'}]}
        self.task['images'] = [{'role': 'main', 'path': str(self.root / 'main.png'), 'sha256': report._sha(PNG), 'source_url': 'https://example.com/record'}]
        self.journal = {'schema_version': '1.0', 'task_id': self.task['task_id'], 'entries': []}
        figure = {'path': str(self.root / 'main.png'), 'label': '真实截图', 'caption': '具体比较证据', 'url': 'https://example.com/record', 'alt': '真实证据'}
        self.content = {'scope': '外观功能均与链接一致', 'product_facts': {'main_visual': figure}, 'sections': [{'id': 'design', 'title': '外观证据', 'blocks': [{'type': 'figures', 'items': [figure] * 25}, {'type': 'p', 'html': '<a href="' + str(self.root / 'source.txt') + '">原文</a>'}]}]}

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **kwargs):
        # This class preserves the pre-core-policy artifact contract. New default
        # selection and rendering are exercised in test_report_core_visuals.
        original = report.build_report_data
        def legacy(*args, **options):
            return original(*args, **{**options, 'visual_policy_revision': None})
        with patch.object(report, '_canonical'), patch.object(report, 'build_report_data', side_effect=legacy):
            return report.build_bundle(self.root, self.task, self.evidence, self.assessment, {}, self.journal, {}, output_dir=self.out, report_content=kwargs.get('content', self.content))

    def test_all_formats_keep_reasons_and_grade(self):
        data, manifest = self.build()
        html = (self.out / 'report.html').read_text()
        md = (self.out / 'report.md').read_text()
        csv_text = (self.out / 'report-findings.csv').read_text(encoding='utf-8-sig')
        for text in ('实线组合对应', '鼻臂比例不同', '假定按链接制造', '整体差异效力有争议', '复核实线范围', '保护整体高度对应', '证明差异改变整体印象'):
            for output in (html, md, csv_text):
                self.assertIn(text, output)
        self.assertEqual(data['overall']['risk'], '中')
        self.assertEqual(len(data['modules']), 7)
        self.assertEqual(manifest['section_order'], report.SECTION_ORDER)
        self.assertNotIn('发布阻断项', html)

    def test_stage_report_keeps_null_risk_and_labels_pending(self):
        from common import RECALL_INTEGRITY_REVISION
        self.task.update(schema_version='2.4-free', screening_revision=RECALL_INTEGRITY_REVISION)
        self.assessment.update(status='incomplete', screening_revision=RECALL_INTEGRITY_REVISION)
        self.assessment['overall'].update(risk=None, business_completion='incomplete', known_scoped_risk=None)
        row = self.assessment['assessments'][0]
        row.update(risk=None, assessment_status='pending', aggregation_included=False,
                   screening_revision=RECALL_INTEGRITY_REVISION, counter_evidence=[],
                   no_counter_evidence_reasoning='No results means no risk')
        data, manifest = self.build()
        self.assertIsNone(manifest['overall']['risk'])
        self.assertEqual(manifest['business_completion'], 'incomplete')
        html = (self.out / 'report.html').read_text()
        md = (self.out / 'report.md').read_text()
        csv_text = (self.out / 'report-findings.csv').read_text(encoding='utf-8-sig')
        for output in (html, md):
            self.assertIn('阶段性报告', output)
            self.assertIn('待完成 · 尚未定级', output)
            self.assertNotIn('外观设计／外观专利**：未纳入本次评价', output)
        self.assertIn('risk-seal risk-seal-not_assessable', html)
        self.assertNotIn('risk-seal-neutral', html)
        for output in (html, md, csv_text):
            self.assertIn('未取得降低风险的证据', output)
            self.assertNotIn('No results means no risk', output)
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        pending = next(row for row in rows if row['row_type'] == 'pending')
        self.assertEqual(pending['risk'], '')
        self.assertEqual(next(row for row in rows if row['row_type'] == 'overall')['risk'], '')

    def test_strict_coverage_diagnostics_use_existing_code_wrapping(self):
        from common import RECALL_INTEGRITY_REVISION
        self.task.update(schema_version='2.4-free', screening_revision=RECALL_INTEGRITY_REVISION)
        self.assessment.update(status='incomplete', screening_revision=RECALL_INTEGRITY_REVISION)
        self.assessment['overall'].update(risk=None, business_completion='incomplete', known_scoped_risk=None)
        diagnostic = 'ASSESSMENT_PENDING:US:trademark_figurative:'
        long_diagnostic = 'PLANNED_QUERY_ACCESS_LIMITED:QRY-' + 'ab12' * 32
        self.assessment['coverage']['notes'] = [diagnostic, long_diagnostic, '保留全部缺口，不做裁剪。']
        data, _ = self.build(content=None)
        html = (self.out / 'report.html').read_text()
        for note in (diagnostic, long_diagnostic):
            self.assertIn('<li><code>' + note + '</code></li>', html)
            self.assertIn(note, data['coverage_notes'])
            self.assertIn(note, (self.out / 'report.md').read_text())
        self.assertIn('<li>保留全部缺口，不做裁剪。</li>', html)
        self.assertEqual(report._list_html([diagnostic]), '<ul><li>' + diagnostic + '</li></ul>')
        self.assertIn('&lt;script&gt;', report._list_html(['ERROR:<script>'], diagnostics=True))

    def test_stage_module_with_scored_and_pending_rows_labels_only_local_risk(self):
        from common import RECALL_INTEGRITY_REVISION
        self.task.update(schema_version='2.4-free', screening_revision=RECALL_INTEGRITY_REVISION)
        self.assessment.update(status='incomplete', screening_revision=RECALL_INTEGRITY_REVISION)
        self.assessment['overall'].update(risk=None, business_completion='incomplete', known_scoped_risk='低')
        self.assessment['assessments'][0]['risk'] = '低'
        pending = copy.deepcopy(self.assessment['assessments'][0])
        pending.update(candidate_id='', title='尚未完成的外观范围', risk=None,
                       assessment_status='pending', aggregation_included=False)
        self.assessment['assessments'].append(pending)
        data, _ = self.build()
        for filename in ('report.html', 'report.md'):
            text = (self.out / filename).read_text()
            self.assertIn('（已评局部）', text)
            self.assertIn('仍有 1 项待评范围或候选', text)
        csv_rows = list(csv.DictReader(io.StringIO(report.render_findings_csv(data))))
        module = next(row for row in csv_rows if row['row_type'] == 'module' and row['risk'] == '低')
        self.assertIn('不是该模块的最终等级', module['scope'])
        self.assertEqual(report._pill('低'), '<span class="risk-pill risk-pill-low">低风险</span>')

    def test_stage_report_displays_known_scoped_high_separately(self):
        from common import RECALL_INTEGRITY_REVISION
        self.task.update(schema_version='2.4-free', screening_revision=RECALL_INTEGRITY_REVISION)
        self.assessment.update(status='incomplete', screening_revision=RECALL_INTEGRITY_REVISION)
        self.assessment['overall'].update(risk=None, business_completion='incomplete', known_scoped_risk='高', known_scoped_confidence='低')
        self.assessment['assessments'][0]['risk'] = '高'
        data, _ = self.build()
        self.assertIn('已评范围最高风险：高', (self.out / 'report.html').read_text())
        self.assertIn('已评范围最高风险：高', (self.out / 'report.md').read_text())
        rows = list(csv.DictReader(io.StringIO(report.render_findings_csv(data))))
        self.assertEqual(next(row for row in rows if row['row_type'] == 'known_scoped_risk')['risk'], '高')
        self.assertEqual(next(row for row in rows if row['row_type'] == 'overall')['risk'], '')

    def test_all_26_figures_embed_original_bytes_no_limit(self):
        data, manifest = self.build()
        output = (self.out / 'report.html').read_text()
        self.assertEqual(len(data['visual_evidence']), 26)
        self.assertEqual(output.count('<img '), 26)
        self.assertEqual(output.count(base64.b64encode(PNG).decode()), 26)
        self.assertIsNone(data['offline_policy']['visual_limit'])

    def test_bundle_links_remain_portable(self):
        data, _ = self.build()
        self.assertEqual(len(list((self.out / 'files').iterdir())), 2)
        self.assertIn('href="files/', (self.out / 'report.html').read_text())
        (self.root / 'main.png').unlink()
        (self.root / 'source.txt').unlink()
        self.assertEqual(report.bundle_bytes(data, self.out)['report.html'], (self.out / 'report.html').read_bytes())

    def test_hash_mismatch_stops_instead_of_substituting(self):
        self.content['product_facts']['main_visual']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH'):
            self.build()

    def document_and_derived_image(self):
        pdf = self.root / 'original.pdf'
        pdf.write_bytes(b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n')
        document = {'evidence_id': 'E-PDF', 'path': str(pdf), 'sha256': report._sha(pdf.read_bytes()),
                    'source_url': 'https://example.com/original.pdf', 'kind': 'patent_document'}
        derived = {'evidence_id': 'E1', 'path': str(self.root / 'main.png'), 'sha256': report._sha(PNG),
                   'source_document': str(pdf), 'source_url': 'https://example.com/original.pdf', 'kind': 'design_drawings'}
        return pdf, document, derived

    def test_derived_image_and_source_pdf_keep_separate_frozen_hashes(self):
        pdf, document, derived = self.document_and_derived_image()
        # Forward references must work: the independent PDF follows the image.
        self.evidence = {'collections': [derived, document]}
        self.assessment['assessments'][0]['evidence_refs'].append('E-PDF')
        data, manifest = self.build(content=None)
        registered = report._registered_files(self.root, self.evidence)
        self.assertEqual(registered[str(pdf.resolve())]['sha256'], document['sha256'])
        self.assertEqual(registered[str((self.root / 'main.png').resolve())]['sha256'], derived['sha256'])
        self.assertNotEqual(document['sha256'], derived['sha256'])
        self.assertEqual({item['evidence_id']: item['sha256'] for item in data['evidence_index']},
                         {'E1': derived['sha256'], 'E-PDF': document['sha256']})
        self.assertTrue(manifest['artifacts']['report.html']['sha256'])

    def test_source_or_derived_tampering_still_fails(self):
        pdf, document, derived = self.document_and_derived_image()
        self.evidence = {'collections': [derived, document]}
        self.assessment['assessments'][0]['evidence_refs'].append('E-PDF')
        for path in (pdf, self.root / 'main.png'):
            original = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(original + b'tamper')
                with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH'):
                    self.build(content=None)
                path.write_bytes(original)

    def test_explicit_source_document_hash_and_legacy_source_only_binding(self):
        pdf, document, derived = self.document_and_derived_image()
        derived['source_document_sha256'] = document['sha256']
        registered = report._registered_files(self.root, derived)
        self.assertEqual(registered[str(pdf.resolve())]['sha256'], document['sha256'])
        for own_key in ('path', 'local_path', 'file_path'):
            image = {**derived, own_key: derived['path']}
            if own_key != 'path':
                image.pop('path')
            self.assertEqual(report._registered_files(self.root, image)[str(pdf.resolve())]['sha256'], document['sha256'])
        legacy = {'source_document': str(pdf), 'sha256': document['sha256']}
        self.assertEqual(report._registered_files(self.root, legacy)[str(pdf.resolve())]['sha256'], document['sha256'])

    def test_unregistered_or_contradictory_source_document_is_not_rehashed(self):
        _, document, derived = self.document_and_derived_image()
        with self.assertRaisesRegex(ValueError, 'SOURCE_DOCUMENT_NOT_REGISTERED'):
            report._registered_files(self.root, derived)
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_SOURCE_HASHES'):
            report._registered_files(self.root, document, {**derived, 'source_document_sha256': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'SOURCE_DOCUMENT_HASH_INVALID'):
            report._registered_files(self.root, document, {**derived, 'source_document_sha256': 'invalid'})

    def test_unknown_brand_and_enforcement_not_scored(self):
        self.assessment['assessments'].extend([{'module_id': 'word_mark', 'right_type': 'trademark_word', 'title': '未知品牌', 'out_of_scope': True, 'scope_reasoning': '品牌名称未提供', 'risk': None}, {'module_id': 'enforcement', 'right_type': 'enforcement', 'title': '历史案件', 'aggregation_included': False, 'risk': None, 'reasoning': '未关联本款'}])
        data, _ = self.build()
        self.assertIsNone(next(m for m in data['modules'] if m['module_id'] == 'word_mark')['risk'])
        rows = list(csv.DictReader(io.StringIO(report.render_findings_csv(data))))
        for row in rows[-2:]:
            self.assertEqual(row['risk'], '')
        self.assertEqual(data['overall']['risk'], '中')

    def test_canonical_cap_applies_to_module_only(self):
        self.assessment['assessments'][0]['evidence_confidence'] = '高'
        self.assessment['module_confidence_caps'] = {'appearance_patent': {'confidence': '中', 'reasoning': '范围不全'}}
        data, _ = self.build()
        self.assertEqual(data['modules'][0]['confidence'], '中')
        self.assertEqual(data['assessments'][0]['evidence_confidence'], '高')

    def test_presentation_cannot_override_product_or_decision(self):
        for patch_value, code in [
            ({'product_facts': {'asin': 'B099999999'}}, 'PRODUCT_FACT_OVERRIDE'),
            ({'lead': '本产品极低风险'}, 'DECISION_TEXT_OVERRIDE'),
            ({'summary': '没有任何侵权风险'}, 'DECISION_TEXT_OVERRIDE'),
            ({'scope': '不同的产品'}, 'DECISION_TEXT_OVERRIDE'),
            ({'module_confidence_caps': {'appearance_patent': {'confidence': '低'}}}, 'MODULE_CONFIDENCE_OVERRIDE'),
        ]:
            content = copy.deepcopy(self.content)
            content.update(patch_value)
            with self.subTest(content=patch_value), self.assertRaisesRegex(ValueError, code):
                self.build(content=content)

    def test_unregistered_file_cannot_be_added_by_template(self):
        unregistered = self.root / 'unregistered.txt'
        unregistered.write_text('not a frozen source')
        self.content['sections'] = [{'blocks': [{'type': 'p', 'html': '<a href="' + str(unregistered) + '">unregistered</a>'}]}]
        with self.assertRaisesRegex(ValueError, 'SOURCE_NOT_REGISTERED'):
            self.build()

    def test_external_path_and_symlink_cannot_escape_frozen_root(self):
        with tempfile.TemporaryDirectory() as external:
            outsider = Path(external) / 'unrelated.txt'
            outsider.write_text('unrelated file')
            link = self.root / 'escape.txt'
            link.symlink_to(outsider)
            for target in (outsider, link):
                self.content['sections'] = [{'blocks': [{'type': 'p', 'html': '<a href="' + str(target) + '">outside</a>'}]}]
                with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'OUTSIDE_EVIDENCE_ROOT'):
                    self.build()
            self.content['evidence_root'] = external
            with self.assertRaisesRegex(ValueError, 'EVIDENCE_ROOT_OVERRIDE'):
                self.build()

    def test_product_page_and_image_cdn_urls_keep_their_frozen_association(self):
        self.task['images'][0]['source_url'] = 'https://images.example/product.png'
        self.content['product_facts']['main_visual']['url'] = self.task['request']['url']
        self.content['sections'][0]['blocks'][0]['items'] = [{
            'path': str(self.root / 'main.png'), 'url': 'https://images.example/product.png'}]
        data, _ = self.build()
        self.assertEqual(data['product']['main_visual']['source_url'], self.task['request']['url'])
        self.assertEqual(data['sections'][0]['blocks'][0]['items'][0]['source_url'], 'https://images.example/product.png')

    def test_main_image_and_source_url_are_bound(self):
        other = self.root / 'other.png'
        other.write_bytes(PNG + b'other')
        self.evidence['collections'].append({'evidence_id': 'E-OTHER', 'path': str(other), 'sha256': report._sha(other.read_bytes())})
        self.content['product_facts']['main_visual'] = {'path': str(other)}
        with self.assertRaisesRegex(ValueError, 'MAIN_IMAGE_IDENTITY_MISMATCH'):
            self.build()
        self.content['product_facts']['main_visual'] = {'path': str(self.root / 'main.png'), 'url': 'https://unrelated.example/false-source'}
        with self.assertRaisesRegex(ValueError, 'SOURCE_URL_NOT_REGISTERED'):
            self.build()

    def test_no_script_or_executable_rich_text(self):
        self.content['sections'][0]['blocks'].append({'type': 'p', 'html': '<script>alert(1)</script><a href="javascript:alert(2)">文本</a><img src="https://example.com/tracker"><strong>保留粗体</strong>'})
        self.build()
        output = (self.out / 'report.html').read_text()
        self.assertNotIn('<script', output)
        self.assertNotIn('javascript:', output)
        self.assertNotIn('example.com/tracker', output)
        self.assertIn('<strong>保留粗体</strong>', output)

    def test_invalid_final_rating_rejected(self):
        self.assessment['assessments'][0]['risk'] = '无法判断'
        with self.assertRaisesRegex(ValueError, 'INVALID_FINAL_RATING'):
            self.build()

    def test_validation_detects_view_model_and_artifact_tampering(self):
        data, _ = self.build()
        for filename, value in [('evidence.json', self.evidence), ('assessment.json', self.assessment), ('normalized-candidates.json', {}), ('search-plan.json', {}), ('browser-candidate-journal.json', self.journal)]:
            (self.root / filename).write_bytes(report._json(value))
        (self.out / 'assessment.json').write_bytes(report._json(self.assessment))
        with patch.object(report, '_canonical'), patch('assessment_estimate.validate_assessment', return_value=[]):
            self.assertEqual(report.validate_run(self.root, self.task, output_dir=self.out), [])
            (self.out / 'report.html').write_text('tampered')
            self.assertIn('REPORT_ARTIFACT_MISMATCH: report.html', report.validate_run(self.root, self.task, output_dir=self.out))
            data['assessments'][0]['reasoning'] = '伪造推论'
            payloads = report.bundle_bytes(data, self.out)
            for filename, payload in payloads.items():
                (self.out / filename).write_bytes(payload)
            (self.out / 'report-manifest.json').write_bytes(report._json(report._manifest(data, payloads)))
            self.assertIn('REPORT_DATA_RECOMPUTE_MISMATCH', report.validate_run(self.root, self.task, output_dir=self.out))

    def test_default_report_uses_declared_main_and_only_reviewed_safe_images(self):
        self.task['images'] = [{'role': 'main', 'path': str(self.root / 'main.png'), 'sha256': report._sha(PNG)}]
        direct = {'evidence_id': 'IMG-CITED', 'path': str(self.root / 'main.png'), 'sha256': report._sha(PNG), 'source_url': 'https://example.com/figure'}
        private_path = self.root / 'private.png'
        private_path.write_bytes(PNG + b'private')
        self.evidence['collections'].extend([direct, {'evidence_id': 'IMG-ACCOUNT', 'path': str(private_path), 'sha256': report._sha(private_path.read_bytes()), 'role': 'account'}, {'evidence_id': 'IMG-UNREFERENCED', 'path': str(private_path), 'sha256': report._sha(private_path.read_bytes())}])
        self.assessment['assessments'][0]['evidence_refs'].extend(['IMG-CITED', 'IMG-ACCOUNT'])
        data, _ = self.build(content=None)
        self.assertEqual(data['product']['main_visual']['sha256'], report._sha(PNG))
        self.assertEqual(len(data['sections'][0]['blocks'][0]['items']), 1)
        self.assertEqual((self.out / 'report.html').read_text().count('<img '), 2)
        self.assertIn('IMG-CITED', data['sections'][0]['blocks'][0]['items'][0]['caption'])
        self.assertFalse(any(item.read_bytes() == private_path.read_bytes() for item in (self.out / 'files').iterdir()))
        # An explicit selection overrides automatic display even when empty.
        explicit, _ = self.build(content={})
        self.assertEqual(explicit['sections'], [])

    def test_default_visuals_have_no_count_cap_and_missing_images_are_explained(self):
        self.task['images'] = []
        empty, _ = self.build(content=None)
        self.assertEqual(empty['sections'], [])
        self.assertIn('尚未取得同时具备', (self.out / 'report.html').read_text())
        for index in range(14):
            source = self.root / ('cited-' + str(index) + '.png')
            source.write_bytes(PNG + bytes([index]))
            identifier = 'IMG-' + str(index)
            self.evidence['collections'].append({'evidence_id': identifier, 'payload': {'screenshot_path': str(source), 'screenshot_sha256': report._sha(source.read_bytes()), 'role': 'evidence'}})
            self.assessment['assessments'][0]['evidence_refs'].append(identifier)
        data, _ = self.build(content=None)
        self.assertEqual(len(data['sections'][0]['blocks'][0]['items']), 14)
        self.assertEqual((self.out / 'report.html').read_text().count('<img '), 14)

    def test_dates_change_note_coverage_dedup_and_overall_confidence_are_visible(self):
        self.content.update({'coverage_notes': ['一条唯一覆盖缺口', '  一条唯一覆盖缺口  '], 'evidence_cutoff': '2026-09-01', 'change_note': '本版仅重评既有证据，并未重跑检索。'})
        self.assessment['coverage']['notes'] = ['一条唯一覆盖缺口']
        self.assessment['overall']['coverage_confidence_reasoning'] = ['关键权属仍未知，因此限制总体置信度。']
        data, _ = self.build()
        self.assertEqual(data['coverage_notes'], ['一条唯一覆盖缺口'])
        html = (self.out / 'report.html').read_text()
        md = (self.out / 'report.md').read_text()
        csv_text = (self.out / 'report-findings.csv').read_text(encoding='utf-8-sig')
        for output in (html, md):
            self.assertEqual(output.count('一条唯一覆盖缺口'), 1)
            self.assertIn('2026-09-01', output)
            self.assertIn('2026-09-06', output)
            self.assertIn('本版仅重评既有证据，并未重跑检索。', output)
        for output in (html, md, csv_text):
            self.assertIn('关键权属仍未知，因此限制总体置信度。', output)
        self.assertEqual(html.count('<img '), 26)

    def test_module_cards_stay_compact_and_empty_evidence_reasons_survive_all_formats(self):
        row = self.assessment['assessments'][0]
        row.update({'supporting_evidence': [], 'no_supporting_evidence_reasoning': '没有形成具体冲突证据，不能据此宣称零风险。', 'counter_evidence': [], 'no_counter_evidence_reasoning': '尚未取得足够的排除证据。'})
        for index in range(13):
            candidate = copy.deepcopy(row)
            candidate.update({'candidate_id': 'D' + str(index + 2), 'title': '外观候选' + str(index + 2), 'reasoning': '独有完整候选推论' + str(index) + '。' + ('长论证。' * 80)})
            self.assessment['assessments'].append(candidate)
        data, _ = self.build()
        html = (self.out / 'report.html').read_text()
        module_section = html.split('<section id="modules"', 1)[1].split('<section id="visual"', 1)[0]
        self.assertNotIn('独有完整候选推论', module_section)
        self.assertIn('等 14 项', module_section)
        self.assertIn('独有完整候选推论12', html)
        csv_rows = list(csv.DictReader(io.StringIO((self.out / 'report-findings.csv').read_text(encoding='utf-8-sig'))))
        candidate_rows = [item for item in csv_rows if item['row_type'] == 'assessment']
        self.assertTrue(all(item['supporting_evidence'] == row['no_supporting_evidence_reasoning'] for item in candidate_rows))
        for output in (html, (self.out / 'report.md').read_text(), (self.out / 'report-findings.csv').read_text(encoding='utf-8-sig')):
            self.assertIn(row['no_supporting_evidence_reasoning'], output)
            self.assertIn(row['no_counter_evidence_reasoning'], output)

    def test_validation_uses_new_output_assessment_when_source_has_historical_result(self):
        self.build()
        for filename, value in [('evidence.json', self.evidence), ('normalized-candidates.json', {}), ('search-plan.json', {}), ('browser-candidate-journal.json', self.journal)]:
            (self.root / filename).write_bytes(report._json(value))
        (self.root / 'assessment.json').write_bytes(report._json({'legacy': True, 'overall': {'risk': None}}))
        (self.out / 'assessment.json').write_bytes(report._json(self.assessment))
        with patch.object(report, '_canonical'), patch('assessment_estimate.validate_assessment', return_value=[]) as validate:
            self.assertEqual(report.validate_run(self.root, self.task, output_dir=self.out), [])
            self.assertEqual(validate.call_args.args[2], self.assessment)
        self.assertTrue(json.loads((self.root / 'assessment.json').read_text())['legacy'])

    def test_secret_and_browser_session_fields_block_build_and_actual_artifact_validation(self):
        simulated_secret = 'SIMULATED-SECRET-DO-NOT-PUBLISH'
        with patch('validate_run.configured_secrets', return_value=[simulated_secret]):
            self.evidence['extra_note'] = simulated_secret
            with self.assertRaises(ValueError) as captured:
                self.build()
            self.assertEqual(str(captured.exception), 'CONFIGURED_SECRET_IN_REPORT_OR_EVIDENCE')
            self.assertNotIn(simulated_secret, str(captured.exception))
            self.assertFalse(self.out.exists())
            self.assertEqual(self.evidence['extra_note'], simulated_secret)
            del self.evidence['extra_note']
            self.evidence['diagnostic'] = {'profile_dir': '/private/session-profile'}
            with self.assertRaisesRegex(ValueError, '^FORBIDDEN_BROWSER_SESSION_FIELDS$'):
                self.build()
            self.assertFalse(self.out.exists())
            del self.evidence['diagnostic']
            self.build()
            original = (self.out / 'report.html').read_text()
            (self.out / 'report.html').write_text(original + simulated_secret)
            errors = report.validate_run(self.root, self.task, output_dir=self.out)
            self.assertEqual(errors, ['CONFIGURED_SECRET_IN_REPORT_OR_EVIDENCE'])
            self.assertNotIn(simulated_secret, str(errors))
            (self.out / 'report.html').write_text(original + '&quot;cookies&quot;: &quot;session-data&quot;')
            self.assertEqual(report.validate_run(self.root, self.task, output_dir=self.out), ['FORBIDDEN_BROWSER_SESSION_FIELDS'])

    def test_human_checks_prioritize_p1_and_preserve_unprioritized_visibility(self):
        original = copy.deepcopy(self.assessment['assessments'][0])
        rows = []
        for name, priority in [('条件候选', 'P2'), ('版权来源', 'P1'), ('后续观察', 'P3'), ('D938855', 'P1')]:
            row = copy.deepcopy(original)
            row.update({'title': name, 'candidate_id': name})
            row['human_checks'][0]['priority'] = priority
            rows.append(row)
        self.assessment['assessments'] = rows
        data, _ = self.build()
        gaps = report._gaps_html(data)
        group = gaps.index('其他候选的条件性核查')
        self.assertLess(gaps.index('P1 · 版权来源'), group)
        self.assertLess(gaps.index('P1 · D938855'), group)
        self.assertGreater(gaps.index('P2 · 条件候选'), group)
        self.assertGreater(gaps.index('P3 · 后续观察'), group)
        self.assertEqual(gaps.count('<details class="fold" open>'), 2)
        self.assertEqual(gaps.count('复核实线范围'), 4)
        for row in self.assessment['assessments']:
            row['human_checks'][0].pop('priority')
        unprioritized, _ = self.build()
        gaps = report._gaps_html(unprioritized)
        self.assertNotIn('其他候选的条件性核查', gaps)
        self.assertLess(gaps.index('条件候选'), gaps.index('版权来源'))
        self.assertEqual(gaps.count('<details class="fold" open>'), 1)


if __name__ == '__main__':
    unittest.main()

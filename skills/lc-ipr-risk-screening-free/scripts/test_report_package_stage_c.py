"""10C contracts: optional exports, real materials and stage carriers."""
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import load_json
import report_estimate as report
from report_package_stage_c import REVISION
import test_report_estimate as fixtures
import test_stage_delivery_stage_d as stage_fixtures
import test_report_presentation_stage_a as presentation_fixtures
from stage_delivery_stage_d import create_output, validate_output


class ReportPackageTests(unittest.TestCase):
    def fixture(self, exports=None):
        fixture = fixtures.EstimateReportTests('test_all_formats_keep_reasons_and_grade')
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.task.update(report_package_revision=REVISION, report_exports=exports or [])
        return fixture

    def test_core_only_keeps_real_materials_and_no_dangling_optional_links(self):
        fixture = self.fixture()
        data, manifest = fixture.build()
        for name in ('report.html', 'report-data.json', 'report-manifest.json'):
            self.assertTrue((fixture.out / name).is_file())
        for name in ('report.md', 'report-findings.csv'):
            self.assertFalse((fixture.out / name).exists())
        self.assertNotIn('href="report-findings.csv"', (fixture.out / 'report.html').read_text())
        self.assertEqual(set(manifest['artifacts']), {'report.html', 'report-data.json'})
        self.assertTrue(manifest['material_files'])
        for row in manifest['material_files']:
            self.assertEqual(report._sha((fixture.out / row['path']).read_bytes()), row['sha256'])
        self.assertEqual(data['report_package_stage_c']['actual_delivery'], 'not_verified')

    def test_requested_exports_are_in_manifest_and_missing_or_wrong_bytes_fail(self):
        fixture = self.fixture(['markdown', 'csv'])
        _, manifest = fixture.build()
        self.assertIn('report.md', manifest['artifacts'])
        self.assertIn('report-findings.csv', manifest['artifacts'])
        (fixture.out / 'report-findings.csv').unlink()
        self.assertIn('REPORT_ARTIFACT_MISMATCH: report-findings.csv', report.validate_run(fixture.root, fixture.task, output_dir=fixture.out))
        (fixture.out / 'report-findings.csv').write_text('wrong version')
        self.assertIn('REPORT_ARTIFACT_MISMATCH: report-findings.csv', report.validate_run(fixture.root, fixture.task, output_dir=fixture.out))

    def test_unrequested_actual_export_is_not_silently_ignored(self):
        fixture = self.fixture()
        fixture.build()
        (fixture.out / 'report.md').write_text('stale optional export')
        self.assertIn('REPORT_UNDECLARED_EXPORT: report.md', report.validate_run(fixture.root, fixture.task, output_dir=fixture.out))

    def test_retained_material_missing_from_bundle_is_delivery_defect(self):
        fixture = self.fixture()
        data, _ = fixture.build()
        material = data['report_package_stage_c']['materials'][0]
        (fixture.out / material['path']).unlink()
        self.assertIn('REPORT_SOURCE_CHANGED: ' + material['path'], report.validate_run(fixture.root, fixture.task, output_dir=fixture.out))

    def test_url_only_is_business_gap_and_no_fake_original(self):
        fixture = self.fixture()
        fixture.evidence['collections'][0].pop('path')
        fixture.evidence['collections'][0].pop('sha256')
        fixture.content['sections'] = []
        data, _ = fixture.build()
        package = data['report_package_stage_c']
        self.assertEqual(package['materials'], [])
        self.assertEqual(package['business_material_gaps'][0]['status'], 'not_obtained')
        self.assertEqual(package['business_material_gaps'][0]['evidence_id'], 'E1')

    def test_referenced_source_document_is_delivered_with_stable_evidence_id(self):
        fixture = self.fixture()
        source = fixture.root / 'original.txt'
        source.write_text('retained original behind derived evidence')
        fixture.evidence['collections'][0].update(source_document=str(source), source_document_sha256=report._sha(source.read_bytes()))
        data, manifest = fixture.build()
        originals = [row for row in manifest['material_files'] if row['sha256'] == report._sha(source.read_bytes())]
        self.assertEqual(originals[0]['evidence_ids'], ['E1'])
        self.assertEqual((fixture.out / originals[0]['path']).read_bytes(), source.read_bytes())
        self.assertEqual(len(data['report_package_stage_c']['materials']), 2)

    def test_actual_inline_evidence_is_accessible_without_claiming_original_file(self):
        fixture = self.fixture()
        record = fixture.evidence['collections'][0]
        record.pop('path'); record.pop('sha256')
        record['fact'] = 'actual retained observation in the registered record'
        fixture.content['sections'] = []
        data, _ = fixture.build()
        material = data['report_package_stage_c']['materials'][0]
        self.assertEqual(material['status'], 'retained_inline_evidence')
        self.assertEqual(material['original_file'], 'not_claimed')
        self.assertEqual(material['json_pointer'], '/evidence_index/0')
        self.assertIn('title="/evidence_index/0"', (fixture.out / 'report.html').read_text())

    def test_current_stage_reference_not_in_legacy_assessment_is_included(self):
        fixture = presentation_fixtures.PresentationStageATests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.fixture.task.update(report_package_revision=REVISION, report_exports=[])
        source = fixture.fixture.root / 'stage-source.txt'
        source.write_text('current stage evidence')
        fixture.fixture.evidence['collections'].append({'evidence_id': 'E2', 'path': str(source),
            'sha256': report._sha(source.read_bytes()), 'source_url': 'https://example.com/current'})
        fixture.stage['stage_risk']['judgments'][0]['evidence_refs'] = ['E2']
        data, _ = fixture.build()
        row = next(row for row in data['evidence_index'] if row['evidence_id'] == 'E2')
        self.assertEqual((fixture.fixture.out / row['path']).read_bytes(), source.read_bytes())

    def stage_fixture(self, carriers):
        fixture = stage_fixtures.StageDeliveryTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.task.update(report_package_revision=REVISION, stage_carriers=carriers)
        fixture.save()
        return fixture

    def test_stage_reply_keeps_validated_record_without_full_pack_or_html(self):
        fixture = self.stage_fixture(['reply'])
        out = fixture.root / 'stage'
        with patch('workflow_v24.work_view_from_dir', return_value=fixture.view):
            result = create_output(fixture.source, out)
            self.assertEqual(validate_output(fixture.source, out), [])
            self.assertIn('仍有可执行工作', result['reply'])
            self.assertFalse((out / 'stage-result.html').exists())
            self.assertFalse((out / 'report-data.json').exists())
            (out / 'stage-result.txt').write_text('another grade')
            self.assertEqual(validate_output(fixture.source, out), ['STAGE_ARTIFACT_MISMATCH:stage-result.txt'])

    def test_stage_requested_html_csv_share_model_and_missing_export_fails(self):
        fixture = self.stage_fixture(['html', 'csv'])
        out = fixture.root / 'stage'
        with patch('workflow_v24.work_view_from_dir', return_value=fixture.view):
            create_output(fixture.source, out)
            self.assertEqual(validate_output(fixture.source, out), [])
            self.assertFalse((out / 'stage-result.md').exists())
            rows = list(csv.DictReader(io.StringIO((out / 'stage-result.csv').read_text(encoding='utf-8-sig'))))
            self.assertTrue(any(row['type'] == 'work' for row in rows))
            self.assertEqual(len({row['model_sha256'] for row in rows}), 1)
            (out / 'stage-result.csv').unlink()
            self.assertEqual(validate_output(fixture.source, out), ['STAGE_ARTIFACT_MISMATCH:stage-result.csv'])

    def test_real_offline_publish_and_completion_accept_core_only(self):
        from test_evidence_delivery_integration import build_evidence_delivery_fixture
        from completion_check import validate_delivery
        with tempfile.TemporaryDirectory() as tmp:
            result = build_evidence_delivery_fixture(Path(tmp) / 'source', report_exports=[])
            source = Path(result['directory']); out = source / 'report'
            self.assertFalse((out / 'report.md').exists())
            self.assertFalse((out / 'report-findings.csv').exists())
            self.assertEqual(validate_delivery(source, out, first_review=source / 'first-review.json',
                second_review=source / 'second-review.json', adjudication=None), [])
            self.assertNotIn('report.md', load_json(out / 'delivery-validation.json')['required_artifacts'])


if __name__ == '__main__':
    unittest.main()

"""Independent source binding and bounded artifact-only repair, offline."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import atomic_write_json, load_json, sha256_file
from delivery_inspection_stage_d import inspect, repair, source_task_errors, dependency_refs
from test_evidence_delivery_integration import build_evidence_delivery_fixture
import test_stage_delivery_stage_d as stage_fixtures
from stage_delivery_stage_d import create_output, build_model

class InspectionTests(unittest.TestCase):
    def report(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        source = Path(tmp.name) / 'source'
        build_evidence_delivery_fixture(source, report_exports=['csv'], independent_inspection=True)
        return source, source / 'report'

    def test_report_reads_current_source_and_all_actual_files(self):
        source, out = self.report()
        before = {str(p): sha256_file(p) for p in source.rglob('*') if p.is_file()}
        record = inspect(source, out)
        self.assertEqual(record['errors'], [])
        self.assertIn('report-findings.csv', record['checked_files'])
        self.assertEqual(record['actual_delivery'], 'not_claimed')
        self.assertEqual(before, {str(p): sha256_file(p) for p in source.rglob('*') if p.is_file()})

    def test_current_product_change_blocks_self_consistent_old_bundle(self):
        source, out = self.report()
        task = load_json(source/'task.json'); task['product']['title'] = '另一产品'
        atomic_write_json(source/'task.json', task)
        record = inspect(source, out)
        self.assertIn('REPORT_CURRENT_SOURCE_TASK_MISMATCH', record['errors'])
        self.assertFalse(record['bounded_local_repair_allowed'])
        with self.assertRaisesRegex(ValueError, 'UPSTREAM_REQUIRED'):
            repair(source, out, source.parent/'repair')

    def test_csv_only_repair_preserves_source_and_other_artifacts(self):
        source, out = self.report()
        source_before = {p.name: sha256_file(p) for p in source.iterdir() if p.is_file()}
        html_hash = sha256_file(out/'report.html')
        (out/'report-findings.csv').write_text('broken')
        record = inspect(source, out)
        self.assertTrue(record['bounded_local_repair_allowed'], record['errors'])
        new = source.parent/'repair'
        fixed = repair(source, out, new)
        self.assertEqual(fixed['errors'], [])
        self.assertEqual(sha256_file(new/'report.html'), html_hash)
        self.assertEqual((out/'report-findings.csv').read_text(), 'broken')
        self.assertEqual(source_before, {p.name: sha256_file(p) for p in source.iterdir() if p.is_file()})
        self.assertFalse(fixed['automatic_investigation_resume'])

    def test_retained_material_copy_is_restored_without_reinvestigation(self):
        source, out = self.report()
        record=inspect(source,out)
        material=next(name for name in record['checked_files'] if name.startswith('files/'))
        digest=sha256_file(out/material)
        (out/material).unlink()
        record=inspect(source,out)
        self.assertTrue(record['bounded_local_repair_allowed'],record['errors'])
        new=source.parent/'restored'
        self.assertEqual(repair(source,out,new)['errors'],[])
        self.assertEqual(sha256_file(new/material),digest)

    def test_shared_result_tampering_is_not_a_local_export_error(self):
        source,out=self.report()
        data=load_json(out/'report-data.json');data['product']['title']='错对象'
        atomic_write_json(out/'report-data.json',data)
        record=inspect(source,out)
        self.assertTrue(record['errors'])
        self.assertFalse(record['bounded_local_repair_allowed'])

    def test_current_review_change_routes_upstream(self):
        source, out = self.report()
        review=load_json(source/'first-review.json'); review['reviewer_id']='changed-reviewer'
        atomic_write_json(source/'first-review.json', review)
        record=inspect(source,out)
        self.assertTrue(record['errors']); self.assertFalse(record['bounded_local_repair_allowed'])

    def test_missing_task_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            record=inspect(Path(tmp)/'missing',Path(tmp)/'out')
            self.assertEqual(record['status'],'blocked')
            self.assertFalse(record['bounded_local_repair_allowed'])

    def test_transitive_dependencies_require_registered_originals(self):
        registry={'O':{'row':{'evidence_refs':['E']}},'E':{'row':{}}}
        self.assertEqual(dependency_refs(registry,['O']),['E','O'])
        del registry['E']
        with self.assertRaisesRegex(ValueError,'REFERENCE_MISSING'):
            dependency_refs(registry,['O'])

    def stage(self):
        fixture=stage_fixtures.StageDeliveryTest(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.task['delivery_inspection_revision']='delivery-inspection-stage-d-v1'; fixture.save()
        return fixture

    def test_stage_local_carrier_repair(self):
        fixture=self.stage(); out=fixture.root/'out'
        with patch('workflow_v24.work_view_from_dir',return_value=fixture.view):
            create_output(fixture.source,out)
            (out/'stage-result.md').write_text('broken')
            record=inspect(fixture.source,out)
            self.assertTrue(record['bounded_local_repair_allowed'],record['errors'])
            fixed=repair(fixture.source,out,fixture.root/'fixed')
            self.assertEqual(fixed['errors'],[])

    def test_unknown_dependency_is_quarantined_without_lowering_overall(self):
        fixture=self.stage()
        fixture.evidence['collections']['source'][0]['evidence_refs']=['E2']
        # Freeze the direct original but intentionally omit its dependency fingerprint.
        from common import sha256_json
        fixture.evidence['stage_risk_events'][0]['ref_fingerprints']['E1']=sha256_json({'origin':'evidence','row':fixture.evidence['collections']['source'][0]})
        fixture.save()
        model=build_model(fixture.source,view=fixture.view)
        self.assertTrue(model['quarantined_judgments'])
        self.assertIsNone(model['stage_risk']['overall']['stage_risk'])

if __name__=='__main__': unittest.main()

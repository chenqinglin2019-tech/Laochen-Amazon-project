"""Real offline publication, semantic QA, copying and completion in one transaction."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import load_json, sha256_file
import delivery_versions_stage_e as versions
import report_estimate as report
from test_evidence_delivery_integration import build_evidence_delivery_fixture


class OperatorDeliveryTransactionTests(unittest.TestCase):
    def test_real_pipeline_checks_once_and_preserves_pending_facts(self):
        with tempfile.TemporaryDirectory(prefix='ipr-operator-transaction-') as root:
            directory = Path(root) / 'fixture'
            with patch.object(report, 'validate_run', wraps=report.validate_run) as validator:
                result = build_evidence_delivery_fixture(directory, operator_policy=True, transaction=True)
            outcome = result['transaction']
            self.assertEqual(validator.call_count, 1)
            self.assertEqual(outcome['validation_transaction']['semantic_checks'], 1)
            self.assertEqual(outcome['delivery_status'], 'entry_verified')
            self.assertEqual(outcome['completion']['status'], 'limited_round_closed')
            self.assertEqual(outcome['completion']['validation_errors'], [])
            entry = Path(result['delivered'])
            data = load_json(entry / 'report-data.json')
            assessment = load_json(entry / 'assessment.json')
            self.assertIsNone(data['overall']['risk'])
            self.assertEqual(data['overall']['listing_recommendation'], '暂缓上架')
            self.assertEqual(len(data['operator_view']['modules']), 9)
            for module in data['operator_view']['modules']:
                if module['query_status'] != '不适用' and module['risk'] is None:
                    self.assertEqual(module['risk_label'], '待定')
                    self.assertTrue(module['unfinished'])
            self.assertTrue(any(row.get('risk') is None and row.get('assessment_status') == 'pending'
                                for row in assessment['assessments']))
            self.assertIn('风险待定', (entry / 'report.html').read_text())
            contract = data['report_package_stage_c']
            for name in ('operator-appendix.html', 'technical-audit.html', 'query-progress.html', 'query-progress.json'):
                self.assertIn(name, contract['required_artifacts'])
                self.assertEqual((entry / name).read_bytes(), (directory / 'report' / name).read_bytes())
                self.assertEqual(sha256_file(entry / name), outcome['validation_transaction']['checked_files'][name])
            query_progress = load_json(entry / 'query-progress.json')
            self.assertEqual(query_progress, data['actual_query_execution_progress'])
            self.assertEqual(data['operator_view']['progress']['completed'], query_progress['completed_total']
                             if query_progress['planned_total'] is not None else None)
            version = load_json(directory / versions.JOURNAL)['versions'][0]
            self.assertEqual(version['state'], 'delivered')
            self.assertEqual(version['attempts'][-1]['step'], 'entry_verified')

    def _rejected_copy(self, mutator):
        with tempfile.TemporaryDirectory(prefix='ipr-operator-reject-') as root:
            directory = Path(root) / 'fixture'
            actual_copy = versions._copy_files
            def changed_copy(build, destination, files):
                actual_copy(build, destination, files)
                mutator(directory, Path(destination))
            with patch.object(report, 'validate_run', wraps=report.validate_run) as validator, \
                    patch.object(versions, '_copy_files', side_effect=changed_copy):
                with self.assertRaisesRegex(ValueError, 'DELIVERY_TRANSACTION_ENTRY_FAILED:entry_recheck'):
                    build_evidence_delivery_fixture(directory, operator_policy=True, transaction=True)
            self.assertEqual(validator.call_count, 1)
            version = load_json(directory / versions.JOURNAL)['versions'][0]
            self.assertEqual(version['state'], 'delivery_failed')
            self.assertIsNone(version['actual_entry'])
            self.assertEqual(version['attempts'][-1]['step'], 'entry_recheck')
            self.assertEqual(version['attempts'][-1]['status'], 'failed')
            self.assertFalse((Path(root) / 'fixture-delivered-completion.json').exists())
            return version['attempts'][-1]['error']

    def test_copy_tamper_does_not_reuse_staged_success(self):
        error = self._rejected_copy(lambda directory, target:
            (target / 'operator-appendix.html').write_text('tampered appendix', encoding='utf-8'))
        self.assertIn('DELIVERY_ACTUAL_FILE_MISSING_OR_CHANGED', error)

    def test_retained_original_change_does_not_reuse_staged_success(self):
        error = self._rejected_copy(lambda directory, target:
            (directory / 'product.png').write_bytes(b'changed original after validation'))
        self.assertIn('DELIVERY_ACTUAL_ENTRY_INSPECTION_FAILED', error)

    def test_query_progress_copy_tamper_does_not_reuse_staged_success(self):
        error = self._rejected_copy(lambda directory, target:
            (target / 'query-progress.json').write_text('{"completion_percent":100}'))
        self.assertIn('DELIVERY_ACTUAL_FILE_MISSING_OR_CHANGED', error)


if __name__ == '__main__':
    unittest.main()

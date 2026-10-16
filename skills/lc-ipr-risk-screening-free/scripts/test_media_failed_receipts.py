"""Readable failed receipts retain media without becoming successful queries."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from candidate_media import candidate_urls, collect
from common import atomic_write_json, load_json
from merge_candidates import merge, apply_candidate_contract
from provider_utils import record_result
from source_result_processing import append_parsed_rows, _retained_run
import test_media_budget_revision


class FailedReceiptMediaTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_media_budget_revision.MediaBudgetRevisionTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        task = load_json(self.root / 'task.json')
        task.update(schema_version='2.4-free', result_processing_revision='source-result-processing-v1',
                    workflow_correction_revision='workflow-correction-v1')
        atomic_write_json(self.root / 'task.json', task)

    def receipt(self, *, submitted='submitted', count=1):
        cards = [{'title': 'Retained design ' + str(i),
            'image_url': 'https://images.example.test/partial.png',
            'publication_number': 'USD123456' + str(i) + 'S1',
            'jurisdiction': 'US', 'right_type': 'design'} for i in range(count)]
        run = record_result(self.root, provider='public_source', operation='search',
            query='visible design cards', jurisdiction='US', evidence_type='patent',
            status='failed', normalized=None, raw_body=json.dumps({'candidates': cards}).encode(),
            raw_suffix='json', error_code='PARTIAL_CAPTURE_FAILED',
            detail='Visible rows retained before capture failure', submission_state=submitted)
        append_parsed_rows(self.root, run['run_id'], [{'position': i + 1, 'candidate': card,
            'reviewer': 'offline-test', 'reason': 'Read the retained card'} for i, card in enumerate(cards)])
        evidence = load_json(self.root / 'evidence.json')
        candidates = merge('patent', evidence['collections']['patents'],
                           {row['run_id']: row for row in evidence['source_runs']})
        apply_candidate_contract('patent', candidates)
        normalized = load_json(self.root / 'normalized-candidates.json')
        normalized['patents'] = candidates
        atomic_write_json(self.root / 'normalized-candidates.json', normalized)
        return run, evidence, candidates

    def test_failed_submitted_cards_download_once_keep_failure_and_query_counts(self):
        run, evidence, candidates = self.receipt(count=18)
        before = (self.root / 'evidence.json').read_bytes()
        with patch('candidate_media.download', side_effect=self.fixture.result) as download, \
                patch('source_result_processing._retained_run', wraps=_retained_run) as verify:
            results = collect(self.root, [row['candidate_id'] for row in candidates])
        self.assertEqual(download.call_count, 1)
        self.assertEqual(verify.call_count, 2)
        self.assertTrue(all(row['status'] == 'retained' for row in results.values()))
        self.assertEqual((self.root / 'evidence.json').read_bytes(), before)
        self.assertEqual(run['status'], 'failed')
        self.assertTrue(all(row['sources'][0]['status'] == 'failed' for row in candidates))

    def test_unknown_submission_stays_ineligible(self):
        _, evidence, candidates = self.receipt(submitted='unknown')
        before = (self.root / 'evidence.json').read_bytes()
        self.assertEqual(candidate_urls(self.root, candidates[0], evidence), [])
        with patch('candidate_media.download') as download:
            collect(self.root, [candidates[0]['candidate_id']])
        download.assert_not_called()
        self.assertEqual((self.root / 'evidence.json').read_bytes(), before)

    def test_original_tamper_rejected_before_download(self):
        run, _, candidates = self.receipt()
        path = self.root / run['raw_paths'][0]
        path.write_bytes(path.read_bytes() + b' ')
        with patch('candidate_media.download') as download, self.assertRaisesRegex(ValueError, 'CHANGED|HASH_MISMATCH'):
            collect(self.root, [candidates[0]['candidate_id']])
        download.assert_not_called()

    def test_failed_receipt_requires_registered_row_and_exact_source_binding(self):
        _, evidence, candidates = self.receipt()
        self.assertEqual(len(candidate_urls(self.root, candidates[0], evidence)), 1)
        changed = deepcopy(evidence); changed['collections']['patents'] = []
        self.assertEqual(candidate_urls(self.root, candidates[0], changed), [])
        changed = deepcopy(candidates[0]); changed['sources'][0]['evidence_id'] = 'unregistered'
        self.assertEqual(candidate_urls(self.root, changed, evidence), [])
        changed = deepcopy(candidates[0]); changed['sources'][0]['source_record_sha256'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH'):
            candidate_urls(self.root, changed, evidence)


if __name__ == '__main__':
    unittest.main()

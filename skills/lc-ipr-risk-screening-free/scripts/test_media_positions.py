"""Exact retained result positions disambiguate duplicate public image cards."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from candidate_media import candidate_urls, collect
from common import atomic_write_json, load_json, sha256_file
from source_result_processing import make_index
import test_media_budget_revision


class MediaPositionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_media_budget_revision.MediaBudgetRevisionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def receipt(self, *, duplicate=True, second_collection=False):
        self.fixture.distinct_urls(1)
        path = self.root / 'lens.json'
        raw = load_json(path)
        first = raw['visual_matches'][0]
        second = deepcopy(first) if duplicate else {**first, 'title': 'Different card',
            'image': 'https://images.example.test/different.png'}
        if second_collection:
            raw['exact_matches'] = [second]
        else:
            raw['visual_matches'].append(second)
        atomic_write_json(path, raw)
        evidence = load_json(self.root / 'evidence.json')
        run = next(row for row in evidence['source_runs'] if row['run_id'] == 'LENS-R')
        run['payload_digest'] = sha256_file(path)
        run['result_processing'] = make_index(load_json(self.root / 'task.json'),
            provider='serpapi_google_lens', evidence_type='copyright', status='success',
            submission_state='submitted', raw_body=path.read_bytes(), raw_suffix='json',
            normalized={}, coverage={'schema_valid': True, 'retrieved_hits': 2},
            payload_digest=run['payload_digest'])
        candidates = load_json(self.root / 'normalized-candidates.json')
        candidate = candidates['copyright_assets'][0]
        candidate['sources'][0].update(source_record_sha256=run['result_processing']['rows'][0]['raw_sha256'])
        atomic_write_json(self.root / 'evidence.json', evidence)
        atomic_write_json(self.root / 'normalized-candidates.json', candidates)
        return evidence, candidates, candidate

    def save_candidates(self, candidates):
        atomic_write_json(self.root / 'normalized-candidates.json', candidates)

    def test_exact_position_retains_duplicate_card_image_and_source_binding(self):
        evidence, candidates, candidate = self.receipt()
        candidate['sources'][0].update(source_position=2, source_collection='visual_matches')
        self.save_candidates(candidates)
        urls = candidate_urls(self.root, candidate, evidence)
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0]['source_position'], 2)
        with patch('candidate_media.download', side_effect=self.fixture.result) as download:
            result = collect(self.root, self.fixture.ids)
        self.assertEqual(download.call_count, 1)
        self.assertEqual(result['C0']['status'], 'retained')
        saved = load_json(self.root / 'supplemental-evidence.json')['evidence'][0]
        self.assertEqual(saved['source_position'], 2)

    def test_global_position_and_collection_must_both_match(self):
        evidence, _, candidate = self.receipt(second_collection=True)
        candidate['sources'][0].update(source_position=2, source_collection='exact_matches')
        self.assertEqual(candidate_urls(self.root, candidate, evidence)[0]['source_position'], 2)
        candidate['sources'][0]['source_collection'] = 'visual_matches'
        with self.assertRaisesRegex(ValueError, 'MEDIA_SOURCE_COLLECTION_MISMATCH'):
            candidate_urls(self.root, candidate, evidence)

    def test_position_hash_conflict_cannot_fall_back_to_matching_other_row(self):
        evidence, _, candidate = self.receipt(duplicate=False)
        candidate['sources'][0]['source_position'] = 2
        with self.assertRaisesRegex(ValueError, 'MEDIA_SOURCE_POSITION_HASH_MISMATCH'):
            candidate_urls(self.root, candidate, evidence)

    def test_missing_or_invalid_explicit_position_cannot_fall_back_to_hash(self):
        evidence, _, candidate = self.receipt(duplicate=False)
        for position in (None, 0, -1, True, '1', 99):
            with self.subTest(position=position):
                candidate['sources'][0]['source_position'] = position
                with self.assertRaisesRegex(ValueError, 'MEDIA_SOURCE_POSITION_'):
                    candidate_urls(self.root, candidate, evidence)

    def test_result_position_alias_and_conflicting_aliases(self):
        evidence, _, candidate = self.receipt()
        candidate['sources'][0]['result_position'] = 2
        self.assertEqual(candidate_urls(self.root, candidate, evidence)[0]['source_position'], 2)
        candidate['sources'][0]['source_position'] = 1
        with self.assertRaisesRegex(ValueError, 'MEDIA_SOURCE_POSITION_CONFLICT'):
            candidate_urls(self.root, candidate, evidence)

    def test_unpositioned_legacy_reference_requires_unique_hash(self):
        evidence, _, candidate = self.receipt(duplicate=False)
        self.assertEqual(len(candidate_urls(self.root, candidate, evidence)), 1)
        evidence, candidates, candidate = self.receipt()
        self.assertEqual(candidate_urls(self.root, candidate, evidence), [])
        self.save_candidates(candidates)
        with patch('candidate_media.download') as download:
            result = collect(self.root, self.fixture.ids)
        download.assert_not_called()
        self.assertEqual(result['C0']['status'], 'needs_info')

    def test_receipt_without_json_cards_supplies_no_link_instead_of_aborting(self):
        """An EPO OPS XML receipt carries a position but no card hash: it is skipped, not fatal."""
        evidence, _, candidate = self.receipt(duplicate=False)
        candidate['sources'][0].update(source_position=1)
        candidate['sources'][0].pop('source_record_sha256', None)
        index = {'rows': [{'position': 1, 'raw_sha256': 'a' * 64, 'collection': 'ops', 'collection_position': 1}]}
        with patch('source_result_processing._retained_run', return_value=(index, b'<ops/>')), \
                patch('source_result_processing._json_result_values', return_value=None):
            self.assertEqual(candidate_urls(self.root, candidate, evidence), [])

    def test_card_receipt_hash_conflict_still_raises_after_the_xml_skip(self):
        """The skip applies only to receipts without cards; a card receipt keeps its strict binding."""
        evidence, _, candidate = self.receipt(duplicate=False)
        candidate['sources'][0].update(source_position=1, source_record_sha256='b' * 64)
        with self.assertRaisesRegex(ValueError, 'MEDIA_SOURCE_POSITION_HASH_MISMATCH'):
            candidate_urls(self.root, candidate, evidence)

    def test_commit_rejects_position_changed_while_download_was_in_flight(self):
        _, candidates, candidate = self.receipt()
        candidate['sources'][0]['source_position'] = 1
        self.save_candidates(candidates)
        def changed(url, **kwargs):
            candidate['sources'][0]['source_position'] = 2
            self.save_candidates(candidates)
            return self.fixture.result(url, **kwargs)
        with patch('candidate_media.download', side_effect=changed), \
                self.assertRaisesRegex(ValueError, 'MEDIA_SOURCE_CHANGED_DURING_DOWNLOAD'):
            collect(self.root, self.fixture.ids)
        self.assertFalse((self.root / 'supplemental-evidence.json').exists())


if __name__ == '__main__':
    unittest.main()

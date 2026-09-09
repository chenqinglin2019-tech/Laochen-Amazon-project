"""Offline regressions for actual retained-card and document-identity failures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from common import API_FIRST_REVISION, api_discovery_patent_right_type, sha256_file, sha256_json
from merge_candidates import merge
from provider_utils import sanitize_for_evidence, sanitize_raw_evidence
import serper_client as serper
import serpapi_patents_client as patents
import serpapi_lens_client as lens


class RetainedCardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = {'search_metadata': {'status': 'Success'}, 'visual_matches': [
            {'title': 'Toy', 'link': 'https://example.test/toy?q=a%20b',
             'thumbnail': 'https://example.test/image?q=a%20b', 'position': 1},
            {'title': 'Second toy', 'link': 'https://example.test/second', 'position': 2}]}
        self.path = self.root / 'lens.json'
        self.path.write_bytes(sanitize_raw_evidence(json.dumps(self.raw).encode(), 'json'))
        self.run = {'run_id': 'RUN-1', 'query_id': 'QRY-1', 'provider': lens.PROVIDER,
                    'status': 'success', 'raw_paths': [str(self.path)],
                    'payload_digest': sha256_file(self.path), 'plan_entry_sha256': 'a' * 64}
        records = lens.normalize(self.raw, retrieval_workflow_revision=API_FIRST_REVISION)['candidates']
        self.entry = {'source_run_id': 'RUN-1', 'query_id': 'QRY-1', 'provider': lens.PROVIDER,
                      'plan_entry_sha256': 'a' * 64, 'payload': {'candidates': records}}
        self.evidence = {'collections': {'copyright_assets': [self.entry]}}

    def tearDown(self):
        self.temp.cleanup()

    def legacy(self):
        for record, original in zip(self.entry['payload']['candidates'], self.raw['visual_matches']):
            record.pop('source_record_hash_stage')
            record['source_record_sha256'] = sha256_json(original)

    def test_all_new_clients_hash_sanitized_retained_card(self):
        row = self.raw['visual_matches'][0]
        self.assertNotEqual(sha256_json(row), sha256_json(sanitize_for_evidence(row)))
        expected = sha256_json(sanitize_for_evidence(row))
        records = [lens.normalize(self.raw, retrieval_workflow_revision=API_FIRST_REVISION)['candidates'][0],
                   serper.normalize('serper_web', 'search', {'organic': [row]}, retrieval_workflow_revision=API_FIRST_REVISION)[0],
                   serper.normalize('serper_patents', 'patents', {'organic': [row]}, retrieval_workflow_revision=API_FIRST_REVISION)[0],
                   patents.normalize({'organic_results': [row]}, retrieval_workflow_revision=API_FIRST_REVISION)[0]]
        for record in records:
            self.assertEqual(record['source_record_sha256'], expected)
            self.assertEqual(record['source_record_hash_stage'], 'retained-v1')

    def test_legacy_projection_is_read_only_and_binds_exact_original(self):
        self.legacy()
        before = copy.deepcopy(self.evidence); raw_before = self.path.read_bytes()
        projected = lens.retained_source_records(self.evidence, self.run, self.root)
        expected = json.loads(raw_before)['visual_matches']
        self.assertEqual([r['source_record_sha256'] for r in projected], [sha256_json(c) for c in expected])
        self.assertEqual(projected[0]['original_source_record_sha256'], sha256_json(self.raw['visual_matches'][0]))
        self.assertFalse(projected[0]['normalization_provenance']['original_hash_verified'])
        self.assertEqual(self.evidence, before); self.assertEqual(self.path.read_bytes(), raw_before)
        rows = merge('copyright', [self.entry], {'RUN-1': self.run})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['sources'][0]['normalization_provenance']['payload_digest'], self.run['payload_digest'])

    def test_changed_fields_dropped_cards_order_and_binding_never_convert(self):
        for mutation in ('title', 'drop', 'order', 'plan', 'stage', 'raw'):
            with self.subTest(mutation=mutation):
                evidence, run = copy.deepcopy(self.evidence), dict(self.run)
                records = evidence['collections']['copyright_assets'][0]['payload']['candidates']
                for r in records:
                    r.pop('source_record_hash_stage')
                if mutation == 'title': records[0]['title'] = 'Different card'
                elif mutation == 'drop': records.pop()
                elif mutation == 'order': records.reverse()
                elif mutation == 'plan': run['plan_entry_sha256'] = 'b' * 64
                elif mutation == 'stage': records[0]['source_record_hash_stage'] = 'unknown'
                else: run['payload_digest'] = 'b' * 64
                with self.assertRaises(ValueError): lens.retained_source_records(evidence, run, self.root)

    def test_new_stage_bad_hash_cannot_use_legacy_conversion(self):
        self.entry['payload']['candidates'][0]['source_record_sha256'] = 'f' * 64
        with self.assertRaises(ValueError): lens.retained_source_records(self.evidence, self.run, self.root)

    def test_historical_normalization_has_no_new_stage(self):
        self.assertNotIn('source_record_hash_stage', lens.normalize(self.raw)['candidates'][0])
        self.assertNotIn('source_record_sha256', lens.normalize(self.raw)['candidates'][0])


class PatentTypeTests(unittest.TestCase):
    def cards(self, publication, revision=API_FIRST_REVISION):
        return serper.normalize('serper_patents', 'patents', {'organic': [
            {'title': 'Indexed toy', 'link': 'https://patents.google.com/patent/' + publication + '/en'}]},
            retrieval_workflow_revision=revision)

    def test_office_specific_document_types(self):
        for publication, actual in {'US20200226832A1': 'patent', 'US9047691B2': 'patent',
                'USD1144620S1': 'design', 'US1144620S1': 'design', 'CN112512386B': 'patent',
                'CN123456789U': 'utility_model', 'CN123456789S': 'design', 'WO2024000001A1': 'patent',
                'EP1234567B1': 'patent', 'JP1234567U': 'utility_model',
                'AU2013312306B2': 'patent', 'TWI571817B': 'patent',
                'TWM123456U': 'utility_model', 'TWD123456S': 'design'}.items():
            with self.subTest(publication=publication):
                self.assertEqual(api_discovery_patent_right_type(publication), actual)
                self.assertEqual(self.cards(publication)[0]['right_type'], actual)

    def test_query_intent_cannot_duplicate_or_change_actual_document_type(self):
        for publication in ('US20200226832A1', 'US9047691B2', 'CN112512386B'):
            with self.subTest(publication=publication):
                # Replay legacy API-first cards that omitted the intrinsic type.
                cards = self.cards(publication)
                for card in cards: card.pop('right_type'); card.pop('right_type_status')
                entries = [{'provider': 'serper_patents', 'source_run_id': f'R-{right}',
                            'right_type': right, 'payload': {'candidates': copy.deepcopy(cards)}} for right in ('patent', 'design')]
                rows = merge('patent', entries, {})
                self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['right_type'], 'patent')
                self.assertEqual(len(rows[0]['sources']), 2)
                self.assertEqual(rows[0]['source_indexes'], ['google_patents'])

    def test_unknown_number_never_inherits_design_intent(self):
        for publication in ('US1234567', 'ZZ123456A1', 'USPP12345P2'):
            with self.subTest(publication=publication):
                cards = self.cards(publication)
                rows = merge('patent', [{'provider': 'serper_patents', 'right_type': 'design', 'payload': {'candidates': cards}}], {})
                self.assertEqual(rows[0]['right_type'], 'unknown')
                self.assertEqual(rows[0]['right_type_status'], 'unresolved')
                self.assertIn(':unknown:', rows[0]['normalization_key'])

    def test_legacy_no_marker_and_web_container_semantics_unchanged(self):
        rows = merge('patent', [{'provider': 'serper_patents', 'right_type': 'design',
                               'payload': {'candidates': self.cards('US9047691B2', None)}}], {})
        self.assertEqual(rows[0]['right_type'], 'design')
        web = serper.normalize('serper_web', 'search', {'organic': [{'title': 'Toy provenance', 'link': 'https://example.test/toy'}]}, retrieval_workflow_revision=API_FIRST_REVISION)
        rows = merge('enforcement', [{'provider': 'serper_web', 'right_type': 'trade_dress', 'payload': {'candidates': web}}], {})
        self.assertEqual(rows[0]['right_type'], 'trade_dress')


if __name__ == '__main__':
    unittest.main()

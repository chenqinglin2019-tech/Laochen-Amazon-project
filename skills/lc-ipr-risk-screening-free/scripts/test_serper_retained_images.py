"""Offline replay of Serper Images cards hashed before evidence sanitization."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from common import API_FIRST_REVISION, sha256_file, sha256_json
from provider_utils import sanitize_raw_evidence
from api_first_planning import source_files_error, source_card_state
from merge_candidates import merge, apply_candidate_contract
import serper_client as serper


class SerperRetainedImagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = {'images': [
            {'title': 'First image', 'link': 'https://example.test/toy?q=a%20b',
             'imageUrl': 'https://example.test/large.png?q=a%20b',
             'thumbnailUrl': 'https://example.test/thumb.png?q=a%20b', 'position': 1},
            {'title': 'Second image', 'link': 'https://example.test/other',
             'imageUrl': 'https://example.test/other.png', 'position': 2}]}
        self.path = self.root / 'images.json'
        self.path.write_bytes(sanitize_raw_evidence(json.dumps(self.raw).encode(), 'json'))
        self.row = {'query_id': 'QRY-IMAGES', 'jurisdiction': 'US', 'right_type': 'copyright'}
        self.run = {'run_id': 'RUN-IMAGES', 'query_id': self.row['query_id'],
                    'provider': 'serper_images', 'operation': 'images', 'status': 'success',
                    'raw_paths': [str(self.path)], 'payload_digest': sha256_file(self.path),
                    'plan_entry_sha256': sha256_json(self.row), 'jurisdiction': 'US', 'right_type': 'copyright'}
        self.entry = {**{k: self.run[k] for k in ('query_id', 'provider', 'operation', 'plan_entry_sha256', 'jurisdiction', 'right_type')},
                      'evidence_id': 'EV-IMAGES', 'source_run_id': self.run['run_id'],
                      'payload': {'candidates': serper.normalize('serper_images', 'images', self.raw,
                                 retrieval_workflow_revision=API_FIRST_REVISION)}}
        self.evidence = {'source_runs': [self.run], 'collections': {'copyright_assets': [self.entry]}}

    def tearDown(self):
        self.temp.cleanup()

    def legacy(self):
        for old, raw in zip(self.entry['payload']['candidates'], self.raw['images']):
            old.pop('source_record_hash_stage')
            old['source_record_sha256'] = sha256_json(raw)

    def test_new_stage_matches_retained_images_and_legacy_projection_preserves_receipt(self):
        retained = json.loads(self.path.read_text())['images']
        new = serper.retained_source_records(self.evidence, self.run, self.root)
        self.assertEqual([c['source_record_sha256'] for c in new], [sha256_json(c) for c in retained])
        self.assertNotIn('normalization_provenance', new[0])
        self.legacy()
        before = copy.deepcopy(self.evidence); raw_before = self.path.read_bytes()
        projected = serper.retained_source_records(self.evidence, self.run, self.root)
        self.assertEqual([c['source_record_sha256'] for c in projected], [sha256_json(c) for c in retained])
        self.assertEqual(projected[0]['original_source_record_sha256'], sha256_json(self.raw['images'][0]))
        self.assertEqual(projected[0]['normalization_provenance']['revision'], 'serper-images-retained-projection-v1')
        self.assertFalse(projected[0]['normalization_provenance']['original_hash_verified'])
        self.assertEqual(self.evidence, before); self.assertEqual(self.path.read_bytes(), raw_before)
        self.assertIsNone(source_files_error(self.root, self.evidence, self.run))
        rows = merge('copyright', [self.entry], {self.run['run_id']: self.run})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['sources'][0]['source_record_sha256'], sha256_json(retained[0]))
        self.assertEqual(rows[0]['sources'][0]['normalization_provenance']['payload_digest'], self.run['payload_digest'])

    def test_wrong_stage_fields_count_order_identity_and_raw_are_rejected(self):
        self.legacy()
        for change in ('title', 'thumbnail', 'drop', 'order', 'query', 'operation', 'plan', 'provider', 'raw', 'missing_hash', 'stage'):
            with self.subTest(change=change):
                e=copy.deepcopy(self.evidence); r=copy.deepcopy(self.run)
                cards=e['collections']['copyright_assets'][0]['payload']['candidates']
                if change=='title':cards[0]['title']='different'
                elif change=='thumbnail':cards[0]['thumbnail_url']='https://example.test/different.png'
                elif change=='drop':cards.pop()
                elif change=='order':cards.reverse()
                elif change=='query':r['query_id']='another'
                elif change=='operation':r['operation']='search'
                elif change=='plan':r['plan_entry_sha256']='b'*64
                elif change=='provider':r['provider']='serper_web'
                elif change=='raw':r['payload_digest']='b'*64
                elif change=='missing_hash':cards[0].pop('source_record_sha256')
                else:cards[0]['source_record_hash_stage']='unknown'
                with self.assertRaises(ValueError):serper.retained_source_records(e,r,self.root)
                self.assertIn(source_files_error(self.root,e,r), {'API_DISCOVERY_SOURCE_CARDS_INVALID','API_DISCOVERY_SOURCE_FILES_INVALID'})

    def test_new_bad_hash_never_downgrades_and_old_unmarked_behavior_is_unchanged(self):
        self.entry['payload']['candidates'][0]['source_record_sha256']='f'*64
        with self.assertRaises(ValueError):serper.retained_source_records(self.evidence,self.run,self.root)
        self.assertEqual(source_files_error(self.root,self.evidence,self.run),'API_DISCOVERY_SOURCE_CARDS_INVALID')
        old=serper.normalize('serper_images','images',self.raw)
        self.assertNotIn('source_record_sha256',old[0])
        entry={**self.entry,'payload':{'candidates':old}}
        self.assertEqual(len(merge('copyright',[entry],{})),2)

    def test_projection_does_not_skip_unmerged_or_unreviewed_cards(self):
        # Reuse a real scenario task fixture, with no credential/network functions.
        from test_api_first_planning import ApiFirstPlanningTests
        fixture=ApiFirstPlanningTests();fixture.setUp()
        try:
            self.legacy()
            candidates={'patents':[],'trademarks':[],'copyright_assets':[],'enforcement':[]}
            error,_=source_card_state(fixture.task,self.evidence,candidates,fixture.ledger,self.row,self.run)
            self.assertEqual(error,'API_DISCOVERY_MERGE_REQUIRED')
            candidates['copyright_assets']=merge('copyright',[self.entry],{self.run['run_id']:self.run})
            apply_candidate_contract('copyright',candidates['copyright_assets'])
            error,_=source_card_state(fixture.task,self.evidence,candidates,fixture.ledger,self.row,self.run)
            self.assertEqual(error,'API_DISCOVERY_TRIAGE_REQUIRED')
        finally:fixture.tearDown()

    def test_empty_response_and_wrong_success_state_are_not_interchangeable(self):
        self.path.write_text(json.dumps({'images':[]}));self.run['payload_digest']=sha256_file(self.path)
        self.entry['payload']['candidates']=[];self.run['status']='no_result'
        self.assertEqual(serper.retained_source_records(self.evidence,self.run,self.root),[])
        self.assertIsNone(source_files_error(self.root,self.evidence,self.run))
        self.run['status']='success'
        with self.assertRaises(ValueError):serper.retained_source_records(self.evidence,self.run,self.root)


if __name__=='__main__':unittest.main()

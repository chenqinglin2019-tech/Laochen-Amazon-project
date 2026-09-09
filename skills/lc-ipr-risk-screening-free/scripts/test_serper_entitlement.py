"""Offline original-page proof, accounting and normalization regressions."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import common
import serper_entitlement as entitlement
import serper_client as serper
import serpapi_patents_client as serpapi
import serpapi_lens_client as lens
import signa_client as signa
from free_search_budget import reserve_search
from merge_candidates import merge
from provider_utils import ProviderError


class AccountProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.key = 'synthetic-secret-key-do-not-print'
        self.now = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
        self.patch = patch.dict(os.environ, {'LC_IPR_TEST_MODE': '1', 'LC_IPR_FREE_SEARCH_LEDGER_DIR': str(self.root / 'ledger')})
        self.patch.start()

    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()

    def capture(self, suffix=''):
        cred = entitlement.fingerprint(self.key); account = entitlement.fingerprint('fixture-account')
        text = (f'Account: [account-sha256:{account}]\nAPI key: [credential-sha256:{cred}]\n'
                'Free credits remaining: 25\nPaid credits: 0\nAuto recharge: Disabled\n'
                'Patents credits per request: 2\nSearch credits per request: 1\nImages credits per request: 1\n' + suffix)
        return {'schema': entitlement.CAPTURE_SCHEMA, 'collector': 'cdp-serper-account-v1',
                'captured_at': self.now.isoformat(), 'credential_fingerprint': cred,
                'account_fingerprint': account, 'source_environment': 'test_fixture',
                'pages': [{'url': 'https://serper.dev/dashboard', 'captured_at': self.now.isoformat(),
                           'text': text, 'sha256': entitlement.fingerprint(text)}]}

    def alter(self, capture, old, new):
        capture['pages'][0]['text'] = capture['pages'][0]['text'].replace(old, new)
        capture['pages'][0]['sha256'] = entitlement.fingerprint(capture['pages'][0]['text'])
        return capture

    def install(self, capture=None):
        source = self.root / 'capture.json'; source.write_text(json.dumps(capture or self.capture()))
        output = self.root / 'proof.json'
        entitlement.create_entitlement(source, output, self.key, now=self.now)
        return output

    def test_valid_proof_is_recomputed_from_retained_original(self):
        path = self.install()
        proof = entitlement.load_entitlement(self.key, 'patents', path=path, now=self.now)
        self.assertEqual(proof['free_credit_units'], 25)
        self.assertEqual(proof['operation_credit_units']['patents'], 2)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.key, path.read_text())

    def test_handwritten_verification_fields_cannot_override_original(self):
        path = self.install(); data = json.loads(path.read_text()); data['free_credit_units'] = 999
        path.write_text(json.dumps(data))
        with self.assertRaises(ProviderError): entitlement.load_entitlement(self.key, 'patents', path=path, now=self.now)

    def test_changed_capture_fails_even_when_proof_claims_verified(self):
        path = self.install(); source = path.with_name('proof.capture.json'); source.write_text(source.read_text() + ' ')
        with self.assertRaises(ProviderError): entitlement.load_entitlement(self.key, 'patents', path=path, now=self.now)

    def test_missing_original_cannot_authorize(self):
        path = self.install(); path.with_name('proof.capture.json').unlink()
        with self.assertRaises(ProviderError): entitlement.load_entitlement(self.key, 'patents', path=path, now=self.now)

    def test_unknown_paid_recharge_and_operation_cost_fail_closed(self):
        for old, new in [('Paid credits: 0', 'Paid balance: unknown'), ('Auto recharge: Disabled', 'Auto recharge: unknown'),
                         ('Free credits remaining: 25', 'Queries remaining: 25')]:
            with self.subTest(old=old), self.assertRaises(ProviderError):
                entitlement.validate_capture(self.alter(self.capture(), old, new), self.key, now=self.now)
        path = self.install(self.alter(self.capture(), 'Patents credits per request: 2', 'Patents pricing: unknown'))
        with self.assertRaises(ProviderError): entitlement.load_entitlement(self.key, 'patents', path=path, now=self.now)

    def test_paid_balance_and_auto_recharge_are_rejected(self):
        for old, new in [('Paid credits: 0', 'Paid credits: 25'), ('Auto recharge: Disabled', 'Auto recharge: Enabled')]:
            with self.subTest(new=new), self.assertRaises(ProviderError) as raised:
                entitlement.validate_capture(self.alter(self.capture(), old, new), self.key, now=self.now)
            self.assertEqual(raised.exception.code, 'PAID_QUOTA_USAGE_DETECTED')

    def test_credential_account_host_and_redaction_binding(self):
        bad = []
        c = self.capture(); c['credential_fingerprint'] = '0' * 64; bad.append(c)
        c = self.capture(); c['account_fingerprint'] = '0' * 64; bad.append(c)
        c = self.capture(); c['pages'][0]['url'] = 'https://serper.dev.example.invalid/dashboard'; bad.append(c)
        bad.append(self.alter(self.capture(), 'Account:', self.key + ' Account:'))
        bad.append(self.capture('Email: sensitive@example.test\n'))
        for c in bad:
            with self.assertRaises(ProviderError): entitlement.validate_capture(c, self.key, now=self.now)

    def test_conflicting_original_values_do_not_choose_favorable_one(self):
        with self.assertRaises(ProviderError):
            entitlement.validate_capture(self.capture('Paid credits: 100\n'), self.key, now=self.now)

    def test_exact_thirty_minute_expiry_and_future_time(self):
        path = self.install()
        with self.assertRaises(ProviderError): entitlement.load_entitlement(self.key, 'patents', path=path, now=self.now + timedelta(minutes=30))
        with self.assertRaises(ProviderError): entitlement.load_entitlement(self.key, 'patents', path=path, now=self.now - timedelta(minutes=2))

    def test_fixture_proof_cannot_run_in_production(self):
        path = self.install()
        with patch.dict(os.environ, {'LC_IPR_TEST_MODE': '0'}), self.assertRaises(ProviderError):
            entitlement.load_entitlement(self.key, 'patents', path=path, now=self.now)


class CreditUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def reserve(self, query, *, task='task1', key='fixture-key', provider='serper', units=2, remaining=5, **kwargs):
        return reserve_search(provider, key, 'https://example.invalid', remaining=remaining, task_dir=self.root / task,
                              query_id=query, max_queries_per_task=30, credit_units=units,
                              ledger_dir=self.root / 'ledger', **kwargs)

    def test_credit_units_are_not_request_count_and_cross_task_shared(self):
        result = self.reserve('p1'); self.assertEqual(result['reserved_requests'], 1)
        self.assertEqual(result['reserved_credit_units'], 2)
        self.assertEqual(result['local_free_credit_units_left'], 3)
        self.reserve('p2', task='task2')
        with self.assertRaises(ProviderError): self.reserve('p3', task='task3')
        self.assertEqual(self.reserve('web', units=1)['local_free_credit_units_left'], 0)

    def test_changed_key_same_proved_account_cannot_reset_balance(self):
        account = entitlement.fingerprint('same-account')
        self.reserve('p1', remaining=2, account_identity=account)
        with self.assertRaises(ProviderError): self.reserve('p2', key='new-key', account_identity=account)

    def test_lost_result_and_new_attempt_cannot_refund_units(self):
        self.reserve('p1')
        result = self.reserve('p1', attempt_id='retry1', retry_reason='Retained response file is missing')
        self.assertEqual(result['local_free_credit_units_left'], 1)
        with self.assertRaises(ProviderError): self.reserve('p1', attempt_id='retry2', retry_reason='Still missing')

    def test_patents_and_lens_share_serpapi_account(self):
        self.reserve('patents', provider='serpapi', remaining=1, units=1)
        with self.assertRaises(ProviderError): self.reserve('lens', task='task2', provider='serpapi', units=1)

    def test_legacy_one_unit_ledger_continues_conservatively(self):
        self.reserve('old', units=1)
        file = next((self.root / 'ledger').glob('*.json')); data = json.loads(file.read_text())
        data.pop('reservation_credit_units'); file.write_text(json.dumps(data))
        self.assertEqual(self.reserve('new')['local_free_credit_units_left'], 2)

    def test_authorized_unknown_credits_track_requests_without_inventing_balance(self):
        for i in range(30):
            result = self.reserve(str(i), remaining=None, units=None, balance_verified=False)
        self.assertEqual(result['local_task_attempts_reserved'], 30)
        self.assertIsNone(result['reserved_credit_units']); self.assertIsNone(result['local_free_credit_units_left'])
        with self.assertRaises(ProviderError) as raised:
            self.reserve('31', remaining=None, units=None, balance_verified=False)
        self.assertEqual(raised.exception.code, 'FREE_SEARCH_TASK_RESERVATIONS_EXHAUSTED')
        next_task = self.reserve('1', task='task2', remaining=None, units=None, balance_verified=False)
        self.assertEqual(next_task['local_task_attempts_reserved'], 1)
        with self.assertRaises(ProviderError) as raised:
            self.reserve('verified', task='task2')
        self.assertEqual(raised.exception.code, 'FREE_SEARCH_UNCERTAIN_CREDITS')


class ApiFieldsTests(unittest.TestCase):
    def test_numberless_patent_card_survives_as_discovery_not_patent_number(self):
        raw = {'title': 'Unnumbered indexed toy', 'link': 'https://example.test/toy'}
        cards = serper.normalize('serper_patents', 'patents', {'organic': [raw]}, retrieval_workflow_revision=common.API_FIRST_REVISION)
        entries = [{'provider': 'serper_patents', 'source_run_id': 'R', 'evidence_id': 'E',
                    'jurisdiction': 'US', 'right_type': 'patent', 'payload': {'candidates': cards}}]
        result = merge('patent', entries, {'R': {'payload_digest': '1' * 64}})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['publication_number'], '')
        self.assertIn(':discovery:', result[0]['normalization_key'])
        self.assertEqual(result[0]['sources'][0]['source_record_sha256'], common.sha256_json(raw))

    def test_malformed_cards_are_not_silently_dropped_in_new_workflow(self):
        for bad in [None, 'not-a-record', {}]:
            with self.assertRaises(ProviderError):
                serper.normalize('serper_patents', 'patents', {'organic': [bad]}, retrieval_workflow_revision=common.API_FIRST_REVISION)
            with self.assertRaises(ProviderError):
                serpapi.normalize({'organic_results': [bad]}, retrieval_workflow_revision=common.API_FIRST_REVISION)

    def test_lens_card_hash_tracks_the_actual_match_record(self):
        raw = {'title': 'Toy photo', 'link': 'https://example.test/toy', 'thumbnail': 'https://example.test/toy.jpg'}
        payload = {'search_metadata': {'status': 'Success'}, 'visual_matches': [raw]}
        card = lens.normalize(payload, retrieval_workflow_revision=common.API_FIRST_REVISION)['candidates'][0]
        self.assertEqual(card['source_record_sha256'], common.sha256_json(raw))
        self.assertEqual(card['source_index'], 'google_lens')
        self.assertEqual(card['right_type'], 'copyright')
        self.assertNotIn('source_record_sha256', lens.normalize(payload)['candidates'][0])

    def test_structured_fields_and_same_upstream_survive_merge(self):
        raw = {'title': 'Layered toy', 'link': 'https://patents.google.com/patent/USD123456S1/en',
               'publicationNumber': 'US D123456 S1', 'inventor': 'Inventor A', 'assignee': 'Owner A',
               'priorityDate': '2020-01-01', 'filingDate': '2021-01-01', 'publicationDate': '2022-01-01',
               'thumbnailUrl': 'https://example.test/thumb.png', 'pdfUrl': 'https://example.test/original.pdf',
               'figures': [{'imageUrl': 'https://example.test/fig1.png'}], 'position': 1}
        first = serper.normalize('serper_patents', 'patents', {'organic': [raw]}, retrieval_workflow_revision=common.API_FIRST_REVISION)[0]
        second = serpapi.normalize({'organic_results': [{**raw, 'assignee': 'Owner B'}]}, retrieval_workflow_revision=common.API_FIRST_REVISION)[0]
        entries = [{'provider': p, 'evidence_id': 'E' + str(i), 'source_run_id': 'R' + str(i), 'payload': {'candidates': [c]}}
                   for i, (p, c) in enumerate([('serper_patents', first), ('serpapi_google_patents', second)])]
        rows = merge('patent', entries, {f'R{i}': {'raw_paths': [f'raw-{i}.json'], 'payload_digest': str(i) * 64} for i in range(2)})
        self.assertEqual(len(rows), 1); row = rows[0]
        self.assertEqual(row['source_indexes'], ['google_patents'])
        self.assertEqual(len(row['sources']), 2)
        self.assertEqual(row['thumbnail_url'], raw['thumbnailUrl'])
        self.assertEqual(row['publication_number'], 'USD123456S1')
        self.assertEqual(row['conflicts']['assignee'], ['Owner A', 'Owner B'])
        self.assertEqual(row['sources'][1]['record_fields']['assignee'], 'Owner B')
        self.assertEqual(row['sources'][0]['source_record_sha256'], common.sha256_json(raw))
        self.assertEqual(row['official_verification']['status'], 'not_checked')
        self.assertFalse(row['authoritative_for_final_rating'])

    def test_declared_publication_url_conflict_is_retained(self):
        item = serper.google_patent_fields({'publicationNumber': 'US123A1', 'link': 'https://patents.google.com/patent/US456B2/en'})
        self.assertEqual(item['publication_number'], 'US123A1')
        self.assertEqual(item['source_identity_conflict']['url_publication'], 'US456B2')

    def test_legacy_limits_and_normalization_are_unchanged(self):
        self.assertEqual(common.serper_free_enhancement(True)['max_queries_per_task'], 10)
        self.assertEqual(common.serpapi_free_enhancement(True)['max_queries_per_task'], 3)
        self.assertNotIn('source_index', serper.normalize('serper_web', 'search', {'organic': [{'title': 'x'}]})[0])
        self.assertNotIn('source_index', serpapi.normalize({'organic_results': [{'title': 'x'}]})[0])


class ApiPlanAndExecutionTests(unittest.TestCase):
    def setUp(self):
        from workflow_v24 import bind_scenario_action
        from offline_test_support import offline_environment
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('create_task.py')),
                        '--url', 'https://www.amazon.com/dp/B012345678', '--jurisdictions', 'US',
                        '--output-dir', str(self.root), '--enable-serper-free', '--enable-serpapi-free'],
                       env=offline_environment(), capture_output=True, check=True)
        self.task = common.load_json(self.root / 'task.json')
        requirement = next(r for r in self.task['coverage_requirements'] if r['jurisdiction'] == 'US' and r['right_type'] == 'patent')
        self.row = {'q': 'layered toy', 'num': 10, 'gl': 'us', 'hl': 'en', 'right_type': 'patent',
                    'search_language': 'en', 'operation': 'patents', 'jurisdiction': 'US', 'required': False,
                    'required_for': 'discovery_only', 'requirement_ids': [requirement['requirement_id']],
                    'wave': 1, 'derived_from': ['product.structure[0]'], 'role': 'discovery_only',
                    'execute_by_default': True, 'authoritative_for_final_rating': False,
                    'retrieval_workflow_revision': common.API_FIRST_REVISION, 'source_index': 'google_patents',
                    'discovery_intent_id': 'INT-TEST', 'discovery_role': 'primary', 'refinement_round': 0,
                    'discovery_scope': {'mode': 'bounded', 'max_pages': 1, 'max_candidates': 10, 'review_all_returned': True}}
        self.row = bind_scenario_action(self.task, 'serper_patents', self.row, purpose='discovery', obligation_key='INT-TEST')
        self.plan = {k: copy.deepcopy(v) for k, v in self.task.items() if k != 'coverage_requirements'}
        self.plan['queries'] = {'serper_patents': [self.row]}
        self.plan['retrieval_policy_sha256'] = common.sha256_json(self.task['retrieval_policy'])
        self.save()

    def tearDown(self): self.temp.cleanup()

    def save(self):
        for name, obj in [('task', self.task), ('search-plan', self.plan), ('evidence', {'schema_version': self.task['schema_version'], 'task_id': self.task['task_id'], 'source_runs': []})]:
            common.atomic_write_json(self.root / (name + '.json'), obj)

    def authorize(self):
        return common.authorize_serper_free_plan_entry(self.task, self.plan, 'serper_patents', 'patents', self.row['query_id'])

    def test_new_discovery_can_link_requirement_and_use_wave_one(self):
        self.assertEqual(self.authorize()['requirement_ids'], self.row['requirement_ids'])
        self.assertEqual(self.task['serper_free_enhancement']['max_queries_per_task'], 30)
        self.assertEqual(self.task['serpapi_free_enhancement']['max_queries_per_task'], 10)

    def test_mutated_scope_or_authority_is_rejected(self):
        for key, value in [('required', True), ('authoritative_for_final_rating', True), ('requirement_ids', ['UNKNOWN']), ('wave', 3)]:
            original = self.row[key]; self.row[key] = value
            with self.assertRaises(ValueError): self.authorize()
            self.row[key] = original

    def test_request_localization_is_hash_bound(self):
        self.row['hl'] = 'de'; self.row['search_language'] = 'de'
        with self.assertRaisesRegex(ValueError, 'QUERY_ID_CONTENT_MISMATCH'): self.authorize()

    def test_missing_revision_cannot_take_new_caps_or_scope(self):
        self.task.pop('retrieval_workflow_revision')
        self.assertEqual(common.serper_free_enhancement_error(self.task), 'SERPER_FREE_ENHANCEMENT_INVALID')
        with self.assertRaises(ValueError): self.authorize()

    def test_unverified_account_stops_before_network_or_reservation(self):
        with (patch.object(serper, 'settings', return_value=({}, 'http://127.0.0.1:12345', 'fixture-key')),
             patch.object(serper, 'load_entitlement', side_effect=ProviderError('FREE_ACCOUNT_UNVERIFIED', 'access_limited', 'No official proof')),
             patch.object(serper, 'reserve_search') as reserve,
             patch.object(serper, 'call') as call,
             patch.object(serper, 'record_result', side_effect=lambda *args, **kwargs: kwargs)):
            result = serper.execute(self.root, self.row['query_id'])
        self.assertEqual(result['error_code'], 'FREE_ACCOUNT_UNVERIFIED'); call.assert_not_called(); reserve.assert_not_called()
        self.assertFalse(result['quota']['network_request_attempted'])

    def test_verified_account_reserves_before_request_and_cannot_repeat(self):
        account = {'proof_sha256': '1' * 64, 'capture_sha256': '2' * 64, 'expires_at': '2026-09-09T12:00:00+00:00',
                   'account_fingerprint': '3' * 64, 'free_credit_units': 6, 'operation_credit_units': {'patents': 2}}
        def call(operation, request, *, attempt_state, connection):
            self.assertEqual(request['gl'], 'us'); self.assertEqual(request['hl'], 'en')
            ledgers = list((self.root / 'ledger').glob('*.json')); self.assertEqual(len(ledgers), 1)
            self.assertEqual(json.loads(ledgers[0].read_text())['remaining'], 4)
            attempt_state['network_request_attempted'] = True
            return {'organic': []}, {}, b'{"organic":[]}'
        with patch.dict(os.environ, {'LC_IPR_TEST_MODE': '1', 'LC_IPR_FREE_SEARCH_LEDGER_DIR': str(self.root / 'ledger')}), \
             patch.object(serper, 'settings', return_value=({}, 'http://127.0.0.1:12345', 'fixture-key')), \
             patch.object(serper, 'load_entitlement', return_value=account), \
             patch.object(serper, 'call', side_effect=call) as network, \
             patch.object(serper, 'record_result', side_effect=lambda *args, **kwargs: kwargs):
            result = serper.execute(self.root, self.row['query_id'])
            repeated = serper.execute(self.root, self.row['query_id'])
        self.assertEqual(result['status'], 'no_result')
        self.assertEqual(result['quota']['reserved_credit_units'], 2)
        self.assertTrue(result['normalized']['search_metadata']['truncated'])
        self.assertEqual(repeated['error_code'], 'FREE_SEARCH_ALREADY_RESERVED')
        self.assertEqual(network.call_count, 1)

    def test_explicit_existing_balance_uses_requests_without_account_page_probe(self):
        self.task['serper_existing_balance_authorization'] = {
            'authorized': True, 'source': 'explicit_user_instruction',
            'authorized_at': datetime.now(timezone.utc).isoformat(), 'max_requests': 30,
            'allow_recharge': False, 'allow_new_purchase': False}
        self.save()
        def call(operation, request, *, attempt_state, connection):
            attempt_state['network_request_attempted'] = True
            return {'organic': [], 'credits': 2}, {}, b'{"organic":[],"credits":2}'
        with patch.object(serper, 'settings', return_value=({}, 'http://127.0.0.1:12345', 'fixture-key')), \
             patch.object(serper, 'load_entitlement') as proof, \
             patch.object(serper, 'call', side_effect=call), \
             patch.object(serper, 'record_result', side_effect=lambda *args, **kwargs: kwargs), \
             patch('free_search_budget._root', return_value=self.root / 'ledger'), \
             patch.dict(os.environ, {'LC_IPR_TEST_MODE': '0'}):
            result = serper.execute(self.root, self.row['query_id'])
        proof.assert_not_called()
        self.assertEqual(result['source_environment'], 'user_authorized_existing_balance')
        self.assertFalse(result['quota']['balance_verified'])
        self.assertIsNone(result['quota']['reserved_credit_units'])
        self.assertEqual(result['quota']['reported_credit_units'], 2)
        self.assertEqual(result['quota']['reserved_requests'], 1)
        self.assertNotIn('entitlement_sha256', result['quota'])

    def test_existing_balance_authorization_requires_exact_new_task_contract(self):
        authorization = {'authorized': True, 'source': 'explicit_user_instruction',
                         'authorized_at': datetime.now(timezone.utc).isoformat(), 'max_requests': 30,
                         'allow_recharge': False, 'allow_new_purchase': False}
        for key, value in [('authorized', False), ('source', 'configured_default'), ('allow_recharge', True),
                           ('max_requests', 31), ('authorized_at', 'unknown')]:
            self.task['serper_existing_balance_authorization'] = {**authorization, key: value}
            with self.assertRaises(ProviderError): serper.existing_balance_authorization(self.task)
        self.task['serper_existing_balance_authorization'] = authorization
        self.task.pop('retrieval_workflow_revision')
        with self.assertRaises(ProviderError): serper.existing_balance_authorization(self.task)

    def test_zero_in_authorization_hash_is_not_an_exhausted_balance(self):
        run = {'provider': 'serper_patents', 'status': 'success', 'quota': {
            'balance_authorization_sha256': 'a0bc' + 'a' * 60,
            'balance_authorization': {'authorized': True, 'max_requests': 30},
            'paid_credit_units': 0, 'reported_credit_units': 0,
            'reserved_credit_units': None, 'local_free_credit_units_left': None}}
        self.assertIsNone(serper.persisted_provider_block({'source_runs': [run]}, entitlement_recheck=True))

    def test_removed_scenario_revision_cannot_bypass_direct_refinement_guard(self):
        self.row.update(discovery_role='refinement', refinement_round=2, parent_query_id='MISSING-PARENT',
                        parent_plan_entry_sha256='1' * 64)
        self.row['query_id'] = common._serper_expected_query_id('serper_patents', 'patents', 'US', self.row)
        for missing in (None, 'decision_workflow_revision', 'workflow_correction_revision', 'retrieval_policy'):
            original = self.task.pop(missing, None) if missing else None
            self.save()
            with patch.object(serper, 'call') as call, patch.object(serper, 'settings') as settings:
                with self.assertRaises((ProviderError, ValueError)): serper.execute(self.root, self.row['query_id'])
            call.assert_not_called(); settings.assert_not_called()
            if missing: self.task[missing] = original

    def test_signa_strips_new_metadata_without_weakening_body_allowlist(self):
        from api_first_planning import make_row
        refs = [r['requirement_id'] for r in self.task['coverage_requirements']
                if r['jurisdiction'] == 'US' and r['right_type'] == 'trademark_word']
        row = make_row(self.task, 'signa', {'kind': 'brand', 'value': 'FIXTURE', 'language': 'en',
                                         'derived_from': 'product.brand'}, 'US', 'trademark_word', refs)
        body = signa._request_from_plan(row, 25, task=self.task)
        self.assertEqual(set(body), {'query', 'strategies', 'filters', 'options', 'limit'})
        self.assertEqual(body['query'], 'FIXTURE'); self.assertEqual(body['limit'], 25)
        with self.assertRaises(ProviderError): signa._request_from_plan({**row, 'unexpected_field': True}, 25, task=self.task)
        with self.assertRaises(ProviderError): signa._request_from_plan(row, 25)


if __name__ == '__main__': unittest.main()

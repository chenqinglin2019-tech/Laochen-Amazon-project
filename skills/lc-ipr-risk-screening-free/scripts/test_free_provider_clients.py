"""Safety/contract tests for the 2.4 provider implementation (no live credentials)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import epo_ops_client as epo
import euipo_client as euipo
import eps_client as eps
import inpi_client as inpi
import serpapi_lens_client as lens
import serpapi_patents_client as patents
import serper_client as serper
from provider_utils import ProviderError


class SerperEntitlementTests(unittest.TestCase):
    def test_v24_even_configured_key_cannot_send_unverified_metered_request(self):
        from common import atomic_write_json, load_json
        from workflow_v24 import generate_plan, product_identity_digest
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            subprocess.run([sys.executable, str(Path(__file__).with_name('create_task.py')), '--url', 'https://www.amazon.com/dp/B012345678', '--jurisdictions', 'US', '--output-dir', str(path), '--enable-serper-free', '--enable-serpapi-free'], capture_output=True, check=True)
            task = load_json(path / 'task.json')
            # Preserve the historical 2.4 account-proof/fallback expectation.
            task.pop('retrieval_workflow_revision', None)
            task.pop('retrieval_policy', None)
            task['serper_free_enhancement']['max_queries_per_task'] = 10
            task['serpapi_free_enhancement']['max_queries_per_task'] = 3
            task['serpapi_free_enhancement']['fallback_only_when_serper_enabled'] = True
            task.pop('recall_planning_revision', None)  # Isolate the existing account-entitlement contract.
            task['state'] = 'collecting'
            task['product'].update(title='hinged phone stand', language='en', structure=['hinged housing'])
            task['query_terms'] = [{'kind': 'structural_feature', 'value': 'hinged housing', 'language': 'en', 'derived_from': 'product.structure[0]'}]
            task['product']['analysis'] = {'status': 'confirmed', 'identity_sha256': product_identity_digest(task['product'], task=task)}
            atomic_write_json(path / 'task.json', task)
            plan = generate_plan(path)
            query = plan['queries']['serper_patents'][0]
            with patch.object(serper, 'credential', return_value='configured-fixture-key'), patch.object(serper, 'call') as call, patch.object(serper, 'http_json') as network:
                result = serper.execute(path, query['query_id'])
            call.assert_not_called()
            network.assert_not_called()
            self.assertEqual(result['error_code'], 'FREE_ACCOUNT_UNVERIFIED')
            self.assertEqual(result['status'], 'access_limited')
            self.assertFalse(result['quota']['network_request_attempted'])
            self.assertEqual(serper.consumed_queries(load_json(path / 'evidence.json')), 0)
            fallback = [row for row in plan['queries']['serpapi_google_patents'] if row.get('fallback_query_id') == query['query_id']]
            self.assertTrue(fallback)

class SearchEnvelopeTests(unittest.TestCase):
    def test_epo_unrelated_xml_cannot_be_zero(self):
        for body in (b'<html/>', b'<error>busy</error>', b'<world-patent-data/>', b'<biblio-search total-result-count="1"><search-result/></biblio-search>'):
            with self.subTest(body=body), self.assertRaises(ProviderError):
                epo.normalize_search(body)

    def test_epo_explicit_zero(self):
        value = epo.search_response(b'<world-patent-data><biblio-search total-result-count="0"><search-result/></biblio-search></world-patent-data>')
        self.assertEqual(value['candidates'], [])
        self.assertFalse(value['search_metadata']['truncated'])

    def test_epo_page_does_not_equal_total(self):
        value = epo.search_response(b'<world-patent-data><biblio-search total-result-count="500"><search-result><publication-reference><document-id document-id-type="docdb"><country>EP</country><doc-number>1004359</doc-number><kind>B1</kind></document-id></publication-reference></search-result></biblio-search></world-patent-data>')
        self.assertEqual(value['search_metadata']['total_hits'], 500)
        self.assertEqual(value['search_metadata']['retrieved_hits'], 1)
        self.assertTrue(value['search_metadata']['truncated'])
        self.assertIsNone(value['search_metadata']['reviewed_hits'])

    def test_epo_positive_document_outside_search_envelope_is_not_search(self):
        with self.assertRaises(ProviderError):
            epo.search_response(b'<world><exchange-document country="EP" doc-number="1004359" kind="B1"/></world>')

    def test_epo_missing_number_is_schema_error(self):
        with self.assertRaises(ProviderError):
            epo.normalize_search(b'<world><exchange-document country="EP" kind="A1"/></world>')

    def test_epo_v24_biblio_keeps_publications_separate_and_clean_classes(self):
        body = b'''<world-patent-data><biblio-search total-result-count="2"><range begin="1" end="2"/><search-result>
        <exchange-documents><exchange-document country="EP" doc-number="1004359" kind="B1" family-id="F1"><bibliographic-data>
        <invention-title lang="en">Hinged housing</invention-title><parties><applicants><applicant><applicant-name><name>Applicant A</name></applicant-name></applicant></applicants></parties>
        <classifications-ipcr><classification-ipcr><text>G06F 3/16 20060101AFI20110603BHEP</text></classification-ipcr></classifications-ipcr>
        <patent-classifications><patent-classification><classification-scheme scheme="CPC"/><section>G</section><class>06</class><subclass>F</subclass><main-group>3</main-group><subgroup>16</subgroup></patent-classification></patent-classifications>
        </bibliographic-data><abstract lang="en"><p>A housing with a hinge.</p></abstract></exchange-document></exchange-documents>
        <exchange-documents><exchange-document country="US" doc-number="1004359" kind="A1"><bibliographic-data><invention-title lang="en">Other document</invention-title></bibliographic-data></exchange-document></exchange-documents>
        </search-result></biblio-search></world-patent-data>'''
        value = epo.search_response(body, include_biblio=True, require_range=True)
        first, second = value['candidates']
        self.assertEqual(first['owners'], ['Applicant A'])
        self.assertEqual(first['abstract'], 'A housing with a hinge.')
        self.assertEqual(first['ipc_classes'], ['G06F3/16'])
        self.assertEqual(first['cpc_classes'], ['G06F3/16'])
        self.assertEqual(first['family_id'], 'F1')
        self.assertNotIn('owners', second)
        self.assertNotIn('abstract', second)
        self.assertFalse(value['search_metadata']['truncated'])
        self.assertTrue(value['search_metadata']['range_verified'])
        self.assertNotIn('title', epo.normalize_search(body)[0])

    def test_epo_response_page_must_match_actual_requested_page(self):
        body = b'<world><biblio-search total-result-count="60"><range begin="1" end="25"/><search-result><exchange-document country="EP" doc-number="1004359" kind="B1"/></search-result></biblio-search></world>'
        with self.assertRaises(ProviderError) as raised:
            epo.search_response(body, '26-50', require_range=True)
        self.assertEqual(raised.exception.code, 'RESPONSE_RANGE_MISMATCH')
        with self.assertRaises(ProviderError):
            epo.search_response(body.replace(b'<range begin="1" end="25"/>', b''), require_range=True)

    def test_epo_official_range_header_and_versioned_search_constituents(self):
        self.assertTrue(epo.search_path('ti=hinge', '2.4-free').startswith('published-data/search/biblio,abstract?'))
        self.assertTrue(epo.search_path('ti=hinge', '2.3-free').startswith('published-data/search?'))
        config = {'http': {'timeout_seconds': 3}}
        with patch.object(epo, 'settings', return_value=(config, 'https://ops.epo.org/3.2/rest-services', '', 'fixture-key', '')), patch.object(epo, 'access_token', return_value=('fixture-token', {})), patch.object(epo, 'EpoQuotaLedger'), patch.object(epo, 'http_request', return_value=(200, {}, b'<world/>')) as request:
            epo.ops_get('published-data/search', '26-50')
        self.assertEqual(request.call_args.kwargs['headers']['X-OPS-Range'], '26-50')
        self.assertNotIn('Range', request.call_args.kwargs['headers'])

    @patch.object(euipo, 'source_profile', return_value=('production', True))
    def test_euipo_missing_collection_cannot_be_zero(self, _):
        for payload in ({}, {'message': 'try later'}, {'trademarks': None}, {'trademarks': [{}]}, {'error': 'quota', 'trademarks': []}):
            with self.subTest(payload=payload), self.assertRaises(ProviderError):
                euipo.normalize('trademark', payload)

    @patch.object(euipo, 'source_profile', return_value=('production', True))
    def test_euipo_zero_and_pagination(self, _):
        rows = euipo.normalize('trademark', {'trademarks': [], 'totalElements': 0})
        self.assertFalse(euipo.search_metadata({'totalElements': 0}, rows, 0, 25)['truncated'])
        self.assertTrue(euipo.search_metadata({'totalElements': 500}, [{}] * 25, 0, 25)['truncated'])
        self.assertTrue(euipo.search_metadata({}, [], 0, 25)['truncated'])
        with self.assertRaises(ProviderError):
            euipo.search_metadata({'totalElements': 50}, [], 0, 25)

class EpsTests(unittest.TestCase):
    def test_identity_and_authority_are_separate(self):
        body = b'<ep-patent-document country="EP" doc-number="1004359" kind="B1" date-publ="20130904"><claims lang="en"><claim num="1">A device comprising X.</claim></claims><description>A device.</description></ep-patent-document>'
        value = eps.normalize_document('EP1004359B1', body, 'CAND-1')['candidates'][0]
        self.assertEqual(value['claims'][0]['number'], '1')
        self.assertFalse(value['authoritative_for_final_rating'])
        self.assertEqual(value['current_national_effect'], 'not_checked')
        self.assertEqual(value['candidate_id'], 'CAND-1')
        with self.assertRaises(ProviderError):
            eps.normalize_document('EP1004359A1', body)

    def test_eps_login_page_and_incomplete_identifier_rejected(self):
        with self.assertRaises(ProviderError): eps.normalize_document('EP1004359B1', b'<html>login</html>')
        for value in ('EP1004359', 'US1004359B1', '../a', 'EP1004359B1?x=1'):
            with self.subTest(value=value), self.assertRaises(ProviderError): eps.document_identity(value)

    def test_rolling_quota_shared_and_recovers_after_window(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = [1_800_000_000]
            first = eps.EpsQuotaLedger(Path(directory), lambda: clock[0])
            second = eps.EpsQuotaLedger(Path(directory), lambda: clock[0])
            reservation = first.reserve(100)
            self.assertEqual(second.read()['entries'][0]['bytes'], 100)
            first.settle(reservation, 45)
            self.assertEqual(second.read()['entries'][0]['bytes'], 45)
            clock[0] += eps.WINDOW_SECONDS + 1
            self.assertEqual(second.read()['entries'], [])

    def test_quota_hard_stop_and_atomic_reservations(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(eps, 'FREE_LIMIT', 250), patch.object(eps, 'STOP_MARGIN', 0):
            def attempt(_):
                try: return eps.EpsQuotaLedger(Path(directory)).reserve(100)
                except ProviderError: return None
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(attempt, range(4)))
            self.assertEqual(len([x for x in results if x]), 2)

    def test_unknown_usage_is_not_released_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = eps.EpsQuotaLedger(Path(directory))
            reservation = ledger.reserve(100)
            ledger.settle(reservation)
            self.assertEqual(ledger.read()['entries'][0]['bytes'], 100)
            ledger.path.write_text('{bad')
            with self.assertRaises(ProviderError): ledger.reserve(100)

    def test_server_quota_and_backward_clock_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = [1_800_000_000]
            ledger = eps.EpsQuotaLedger(Path(directory), lambda: clock[0])
            reservation = ledger.reserve(100); ledger.settle(reservation, 10, blocked=True)
            with self.assertRaises(ProviderError): ledger.reserve(100)
            clock[0] -= 100
            with self.assertRaises(ProviderError): ledger.reserve(100)

class InpiTests(unittest.TestCase):
    def test_real_documented_routes_and_bounds(self):
        path, params = inpi.search_request({'right_type':'patent','q':'[(TIT OU ABFR)=(taille* haie*)]','collections':['FR','EP'],'position':0,'size':25})
        self.assertEqual(path, '/services/apidiffusion/api/brevets/search')
        self.assertEqual(params['query'], '[(TIT OU ABFR)=(taille* haie*)]')
        self.assertEqual(inpi.notice_path({'right_type':'patent','identifier':'EP3813503'}), '/services/apidiffusion/api/brevets/notice/pubnum/EP3813503')
        with self.assertRaises(ProviderError): inpi.search_request({'right_type':'design','q':'[DesignTitle=chair]','collections':['EU']})

    def test_solr_search_zero_and_truncation(self):
        zero = inpi.normalize_search(b'<response><result name="response" numFound="0"/></response>', 'patent')
        self.assertFalse(zero['search_metadata']['truncated'])
        body = b'<response><result numFound="500"><doc><str name="PUBN">FR2979290</str><str name="TIT">Device</str></doc></result></response>'
        value = inpi.normalize_search(body, 'patent')
        self.assertEqual(value['candidates'][0]['publication_number'], 'FR2979290')
        self.assertTrue(value['search_metadata']['truncated'])

    def test_unvalidated_schema_is_a_gap(self):
        for body in (b'<html>login</html>', b'<response/>', b'<response><result numFound="4"/></response>'):
            with self.subTest(body=body), self.assertRaises(ProviderError):
                inpi.normalize_search(body, 'patent')

    def test_national_identity_and_foreign_scope(self):
        body = b'<notice><ApplicationNumber>FR4216963</ApplicationNumber><DEPOSANT>Owner</DEPOSANT><MarkCurrentStatusCode>REGISTERED</MarkCurrentStatusCode><ClassNumber>9</ClassNumber></notice>'
        value = inpi.normalize_notice(body, {'right_type':'trademark_word','identifier':'FR4216963','jurisdiction':'FR'})
        self.assertTrue(value['official_verification']['identity_match'])
        self.assertEqual(value['official_verification']['status'], 'verified')
        value = inpi.normalize_notice(body, {'right_type':'trademark_word','identifier':'FR4216963','jurisdiction':'DE'})
        self.assertFalse(value['authoritative_for_final_rating'])
        with self.assertRaises(ProviderError):
            inpi.normalize_notice(body, {'right_type':'trademark_word','identifier':'FR4216964','jurisdiction':'FR'})

    def test_missing_media_prevents_full_design_verification(self):
        value = inpi.normalize_notice(b'<notice><DesignApplicationNumber>FR20140182</DesignApplicationNumber><DEPOSANT>Owner</DEPOSANT><DesignCurrentStatusCode>REGISTERED</DesignCurrentStatusCode><ClassNumber>1</ClassNumber></notice>', {'right_type':'design','identifier':'FR20140182','jurisdiction':'FR'})
        self.assertEqual(value['official_verification']['status'], 'partial')
        self.assertIn('official_media', value['official_verification']['reason'])

class LensTests(unittest.TestCase):
    def test_only_captured_public_image(self):
        url='https://m.media-amazon.com/images/I/test.jpg'
        task={'images':[{'source_url':url,'sha256':'a'*64}]}
        self.assertEqual(lens.public_product_image(task, {'image_url':url}), url)
        for value in ('file:///tmp/a.jpg','http://127.0.0.1/x','https://media-amazon.com.evil.com/a', url+'?token=secret'):
            with self.subTest(value=value), self.assertRaises(ProviderError): lens.public_product_image(task, {'image_url':value})
        with self.assertRaises(ProviderError): lens.public_product_image({'images':[]}, {'image_url':url})

    def test_lens_is_discovery_not_copyright_proof(self):
        value=lens.normalize({'search_metadata':{'status':'Success'},'visual_matches':[{'link':'https://example.org/work','title':'Work'}]})
        self.assertFalse(value['candidates'][0]['authoritative_for_final_rating'])
        self.assertTrue(value['search_metadata']['truncated'])
        with self.assertRaises(ProviderError): lens.normalize({'search_metadata':{'status':'Success'}})

    def test_shared_patents_lens_budget_and_stop(self):
        evidence={'source_runs':[{'provider':'serpapi_google_lens','operation':'image_search','quota':{'network_request_attempted':True}}, {'provider':'serpapi_google_patents','operation':'patent_search','quota':{'network_request_attempted':True}}]}
        # Existing patents operation remains centralized in its constant.
        evidence['source_runs'][1]['operation']=patents.SERPAPI_OPERATION
        self.assertEqual(patents.consumed_queries(evidence), 2)
        evidence['source_runs'][0]['error_code']='PAID_PLAN_REQUIRED'
        self.assertIn('paid_plan', patents.persisted_quota_block_reason(evidence))

if __name__ == '__main__':
    unittest.main()

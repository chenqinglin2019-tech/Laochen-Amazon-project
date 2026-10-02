"""Synthetic OPS availability/page responses; no source traffic or IP facts."""
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import atomic_write_json, load_json, load_skill_config
from provider_utils import ProviderError, enforce_task_limit
import epo_ops_client as ops


def inquiry(number='D123', country='US', kind='S1', link='US/D123/S1/fullimage'):
    return ('''<ops:world-patent-data xmlns:ops="http://ops.epo.org"><ops:document-inquiry>
      <ops:inquiry-result><publication-reference><document-id document-id-type="docdb">
      <country>{country}</country><doc-number>{number}</doc-number><kind>{kind}</kind>
      </document-id></publication-reference><ops:document-instance link="{link}" number-of-pages="8">
      <ops:document-format-options><ops:document-format>application/pdf</ops:document-format>
      <ops:document-format>application/tiff</ops:document-format></ops:document-format-options>
      <ops:document-section name="DRAWINGS" start-page="2"/>
      </ops:document-instance></ops:inquiry-result></ops:document-inquiry></ops:world-patent-data>'''
      .format(country=country,number=number,kind=kind,link=link)).encode()


class OpsImagesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.task={'task_id':'SYNTHETIC-OPS','schema_version':'2.4-free','retrieval_workflow_revision':'api-first-v3'}
        atomic_write_json(self.root/'task.json',self.task)
        atomic_write_json(self.root/'evidence.json',{'source_runs':[]})
        from PIL import Image
        buffer=BytesIO()
        Image.new('RGB',(5,4),'white').save(buffer,format='TIFF')
        self.page=buffer.getvalue()
        self.request={'task_dir':self.root,'task_id':self.task['task_id'],'query_id':'Q1','maximum':18,
                      'trace_ids':[],'received_count':0}

    def retrieve(self):
        return ops.retrieve_images(self.root,'USD123S',right_type='design',candidate_id='C1',task_request=self.request)

    def test_same_record_metadata_then_full_drawing_tiff(self):
        with patch('epo_ops_client.ops_get',side_effect=[(inquiry(),{}),(self.page,{})]) as get:
            body,headers,normalized=self.retrieve()
        self.assertEqual(get.call_args_list[0].args[0],'published-data/publication/epodoc/USD123S/images')
        self.assertEqual(get.call_args_list[0].kwargs['accept'],'application/ops+xml')
        self.assertEqual(get.call_args_list[1].args,('published-data/images/US/D123/S1/fullimage','2'))
        self.assertEqual(get.call_args_list[1].kwargs['accept'],'application/tiff')
        record=normalized['candidates'][0]
        self.assertEqual(record['publication_number'],'USD123S')
        self.assertEqual(record['identifiers'],['USD123S1'])
        self.assertEqual(record['media'][0]['page_number'],2)
        self.assertTrue(Path(record['media'][0]['path']).is_file())
        self.assertFalse(record['media_acquisition']['complete'])
        self.assertEqual(body,inquiry())

    def test_wrong_identity_country_or_kind_never_fetches_page(self):
        for payload in (inquiry(number='D999'),inquiry(country='JP'),inquiry(kind='A1')):
            with self.subTest(payload=payload),patch('epo_ops_client.ops_get',return_value=(payload,{})) as get:
                with self.assertRaisesRegex(ProviderError,'(identif|match)'):
                    self.retrieve()
                self.assertEqual(get.call_count,1)

    def test_foreign_link_and_thumbnail_cannot_substitute_full_page(self):
        for link in ('https://example.invalid/page','JP/D123/S1/fullimage','US/D123/S1/thumbnail'):
            with self.subTest(link=link),patch('epo_ops_client.ops_get',return_value=(inquiry(link=link),{})) as get:
                result=self.retrieve()[2]['candidates'][0]
                self.assertFalse(result['media'])
                self.assertEqual(get.call_count,1)

    def test_unreadable_page_is_not_a_verified_drawing(self):
        with patch('epo_ops_client.ops_get',side_effect=[(inquiry(),{}),(b'not image',{})]):
            with self.assertRaisesRegex(ProviderError,'not a readable image'):
                self.retrieve()

    def test_ten_original_requests_plus_each_two_stage_request_obey_configured_cap(self):
        prior=[{'run_id':'old'+str(i),'query_id':'old'+str(i),'provider':'epo_ops',
                'operation':'candidate_detail','status':'failed','submission_state':'unknown'} for i in range(10)]
        atomic_write_json(self.root/'evidence.json',{'source_runs':prior})
        attempts=[{'request_id':'HTTP'+str(i),'query_id':'Q'+str(i//2)} for i in range(8)]
        trace={'task_id':self.task['task_id'],'attempts':attempts}
        atomic_write_json(self.root/'epo-data-http-attempts.json',trace)
        with self.assertRaises(ProviderError) as caught:
            enforce_task_limit(self.root,'epo_ops','candidate_detail',18)
        self.assertEqual(caught.exception.code,'FREE_QUOTA_EXHAUSTED')
        enforce_task_limit(self.root,'epo_ops','candidate_detail',20)
        trace['attempts'].extend([{'request_id':'HTTP8','query_id':'Q4'},{'request_id':'HTTP9','query_id':'Q4'}])
        atomic_write_json(self.root/'epo-data-http-attempts.json',trace)
        with self.assertRaises(ProviderError) as caught:
            enforce_task_limit(self.root,'epo_ops','candidate_detail',20)
        self.assertEqual(caught.exception.code,'FREE_QUOTA_EXHAUSTED')
        self.assertEqual(len(load_json(self.root/'epo-data-http-attempts.json')['attempts']),10)

    def test_invalid_task_http_ledger_fails_closed_without_reset(self):
        for value in ([], {"task_id":self.task["task_id"], "attempts":[{"request_id":[], "query_id":"Q1"}]},
                      {"task_id":"other", "attempts":[]}):
            with self.subTest(value=value):
                atomic_write_json(self.root/'epo-data-http-attempts.json',value)
                with self.assertRaises(ProviderError) as caught:
                    enforce_task_limit(self.root,'epo_ops','candidate_detail',18)
                self.assertEqual(caught.exception.code,'EPO_TASK_HTTP_LEDGER_INVALID')
                self.assertEqual(load_json(self.root/'epo-data-http-attempts.json'),value)

    def test_legacy_images_requests_keep_original_accept_and_no_task_trace(self):
        config=load_skill_config()
        with patch('epo_ops_client.settings',return_value=(config,'http://127.0.0.1','http://127.0.0.1/auth','synthetic','synthetic')), \
             patch('epo_ops_client.access_token',return_value=('synthetic-token',{})), \
             patch('epo_ops_client.EpoQuotaLedger'), \
             patch('epo_ops_client.http_request',return_value=(200,{},b'legacy')) as http:
            body,_=ops.ops_get('published-data/images/epodoc/USD123S/fullimage')
        self.assertEqual(body,b'legacy')
        self.assertEqual(http.call_args.kwargs['headers']['Accept'],'application/exchange+xml')
        self.assertFalse((self.root/'epo-data-http-attempts.json').exists())

    def test_each_data_http_is_reserved_and_cap_stops_before_second_page(self):
        prior=[{'run_id':'old'+str(i),'query_id':'old'+str(i),'provider':'epo_ops','operation':'candidate_detail',
                'status':'failed','submission_state':'unknown'} for i in range(17)]
        atomic_write_json(self.root/'evidence.json',{'source_runs':prior})
        config=load_skill_config()
        with patch('epo_ops_client.settings',return_value=(config,'http://127.0.0.1','http://127.0.0.1/auth','synthetic','synthetic')), \
             patch('epo_ops_client.access_token',return_value=('synthetic-token',{})), \
             patch('epo_ops_client.EpoQuotaLedger'), \
             patch('epo_ops_client.http_request',return_value=(200,{},inquiry())) as http:
            with self.assertRaisesRegex(ProviderError,'Per-task free query cap'):
                self.retrieve()
        self.assertEqual(http.call_count,1)
        self.assertEqual(http.call_args.kwargs['headers']['Accept'],'application/ops+xml')
        attempts=load_json(self.root/'epo-data-http-attempts.json')['attempts']
        self.assertEqual(len(attempts),1)
        self.assertEqual(self.request['trace_ids'],[attempts[0]['request_id']])
        with self.assertRaisesRegex(ProviderError,'Per-task free query cap'):
            enforce_task_limit(self.root,'epo_ops','candidate_detail',18)
        # A stored final receipt binds the prior reservation and is not counted
        # a second time. Reservations also survive an interrupted recorder.
        prior.append({'run_id':'new','query_id':'Q1','provider':'epo_ops','operation':'candidate_detail','status':'failed',
                      'submission_state':'submitted','metadata':{'response_receipt':{'ops_http_trace_ids':self.request['trace_ids']}}})
        atomic_write_json(self.root/'evidence.json',{'source_runs':prior})
        enforce_task_limit(self.root,'epo_ops','candidate_detail',19)

    def test_received_fault_known_submitted_without_zero_or_rewrite(self):
        body=b'<fault><code>CLIENT.NotAcceptable</code><message>RESTEASY003635 No match for accept header</message></fault>'
        error,state=ops.classify_ops_failure(ProviderError('PROVIDER_HTTP_ERROR','failed','HTTP406',406,body,{},'data'),'images')
        self.assertEqual((error.code,state),('PROVIDER_HTTP_ERROR','submitted'))
        error,state=ops.classify_ops_failure(ProviderError('PROVIDER_HTTP_ERROR','failed','HTTP404',404,body,{},'data'),'fulltext')
        self.assertEqual((error.code,state),('PROVIDER_HTTP_ERROR','submitted'))
        self.assertEqual(ops.classify_ops_failure(ProviderError('PROVIDER_TIMEOUT','failed','No reply'),'images')[1],'unknown')


if __name__=='__main__':
    unittest.main()

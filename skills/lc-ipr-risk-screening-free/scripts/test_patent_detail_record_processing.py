"""Offline single-record receipts; no source request or business data mutation."""
from __future__ import annotations
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import atomic_write_json,load_json,sha256_bytes,sha256_json,sha256_file
from source_result_processing import make_index,progress,append_record_content_review,append_dispositions,detail_record_binding,_json_result_values
from trusted_api import _exact_detail_candidate,record_facts

class DetailRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.task={'task_id':'DETAIL-TEST','retrieval_workflow_revision':'api-first-v3','result_processing_revision':'source-result-processing-v1'}
        self.candidate={'candidate_id':'C1','publication_number':'USD1127104S','application_number':'US202429934258F','jurisdiction':'US','right_type':'design'}
        self.raw={'search_metadata':{'status':'Success'},'search_parameters':{'engine':'google_patents_details','patent_id':'patent/USD1127104S1/en'},
            'publication_number':'USD1127104S1','title':'Toy','claims':['The ornamental design as shown.'],'images':['https://example.test/figure.png'],
            'similar_documents':[{'publication_number':'USD999S1'}],'patent_citations':[{'publication_number':'US999A1'}]}
        self.annotation={'annotation_id':'A1','candidate_id':'C1','next_actions':[{'action_id':'ACT1','target_locator':{'kind':'publication_number','value':'USD1127104S1','evidence_refs':['EV-ORIGINAL'],'unique_reason':'Read exact full original and application.'}}]}
        path=self.root/'original.txt';path.write_text('Publication number USD1127104S1\nUSD1127104S\nUS202429934258F',encoding='utf-8')
        self.original={'evidence_id':'EV-ORIGINAL','candidate_id':'C1','publication_number':'USD1127104S1','jurisdiction':'US','path':str(path),'sha256':sha256_file(path)}
        self.payload={'candidate_id':'C1','publication_number':'USD1127104S1','jurisdiction':'US','right_type':'design','claims':self.raw['claims'],'images':self.raw['images']}
        self.save()
    def save(self,old=True):
        path=self.root/'raw'/'serpapi_google_patents'/'record.json';path.parent.mkdir(parents=True,exist_ok=True)
        body=json.dumps(self.raw,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode();path.write_bytes(body)
        digest=sha256_bytes(body);self.payload['source_record_sha256']=digest
        index=make_index(self.task,provider='serpapi_google_patents',evidence_type='patent',status='success',submission_state='submitted',raw_body=body,raw_suffix='json',normalized=self.payload,coverage={},payload_digest=digest)
        if old:index.update(returned_count=None,returned_count_basis='unknown',rows=[])
        self.run={'run_id':'R1','provider':'serpapi_google_patents','operation':'candidate_detail','jurisdiction':'US','status':'success','submission_state':'submitted',
            'raw_paths':[str(path)],'payload_digest':digest,'result_processing':index,'request_params':{'candidate_id':'C1','patent_id':'patent/USD1127104S1/en'},
            'metadata':{'triage_decision_id':'A1','triage_decision_sha256':sha256_json(self.annotation),'triage_action_id':'ACT1'}}
        self.entry={'evidence_id':'E1','source_run_id':'R1','provider':'serpapi_google_patents','operation':'candidate_detail','payload':self.payload,
            'trusted_api_record':{'raw_paths':[str(path)]}}
        self.evidence={'source_runs':[self.run],'collections':{'patents':[self.entry]}}
        for name,data in [('task.json',self.task),('evidence.json',self.evidence),('normalized-candidates.json',{'patents':[self.candidate]}),('materiality-annotations.json',{'annotations':[self.annotation]}),('supplemental-evidence.json',{'evidence':[self.original]})]:atomic_write_json(self.root/name,data)
    def review(self):
        return append_record_content_review(self.root,'R1',{'reading_units':['identity','document_text','claims','image_links'],'reviewer':'reader','reason':'Read exact identity and text; image links remain unread images.'})
    def test_old_index_projected_without_candidates_or_run_rewrite(self):
        before=copy.deepcopy(self.run);state=progress(self.root,self.run,self.evidence)
        self.assertEqual((state['returned_count'],state['parsed_count']), (1,0));self.assertEqual(state['pending_parse_positions'],[])
        self.assertFalse(state['material_processing_complete']);state=self.review();self.assertTrue(state['material_processing_complete']);self.assertFalse(state['zero_proven'])
        saved=load_json(self.root/'evidence.json');self.assertEqual(saved['source_runs'][0],before);self.assertEqual(len(saved['collections']['patents']),1)
        self.assertEqual(len(_json_result_values(json.dumps(self.raw).encode(),'serpapi_google_patents')),1)
    def test_explicit_original_identity_and_consumer_same_projection(self):
        proof=detail_record_binding(self.root,self.run,self.evidence);self.assertTrue(proof['locator_proof'])
        clone=_exact_detail_candidate(self.task,self.entry,self.candidate,self.evidence);self.assertEqual(clone['publication_number'],'USD1127104S1');self.assertEqual(self.candidate['publication_number'],'USD1127104S')
        self.original['publication_number']='USD999S1';atomic_write_json(self.root/'supplemental-evidence.json',{'evidence':[self.original]})
        with self.assertRaisesRegex(ValueError,'ORIGINAL_IDENTITY'):detail_record_binding(self.root,self.run,self.evidence)
        self.assertEqual(_exact_detail_candidate(self.task,self.entry,self.candidate,self.evidence),self.candidate)
    def test_explicit_candidate_id_mismatch_rejects_before_file_reads(self):
        other={**self.candidate,'candidate_id':'OTHER'}
        with patch('common.load_json',side_effect=AssertionError('No I/O for explicit different candidate')):
            self.assertEqual(_exact_detail_candidate(self.task,self.entry,other,self.evidence),other)
        for candidate in (self.candidate,{k:v for k,v in self.candidate.items() if k != 'candidate_id'}):
            with patch('common.load_json',wraps=load_json) as read:
                _exact_detail_candidate(self.task,self.entry,candidate,self.evidence)
                self.assertGreater(read.call_count,0)

    def test_no_suffix_guess_no_other_country_no_wrong_request(self):
        self.run['metadata']['triage_decision_id']='wrong'
        with self.assertRaisesRegex(ValueError,'EXPLICIT_LOCATOR'):progress(self.root,self.run,self.evidence)
        self.run['metadata']['triage_decision_id']='A1';self.run['jurisdiction']='GB'
        with self.assertRaisesRegex(ValueError,'IDENTITY_MISMATCH'):progress(self.root,self.run,self.evidence)
        self.run['jurisdiction']='US';self.run['request_params']['patent_id']='patent/USD999S1/en'
        with self.assertRaisesRegex(ValueError,'IDENTITY_MISMATCH'):progress(self.root,self.run,self.evidence)
    def test_tamper_original_raw_or_material_change_invalidates(self):
        self.review();saved=load_json(self.root/'evidence.json');self.candidate['title']='Changed material';atomic_write_json(self.root/'normalized-candidates.json',{'patents':[self.candidate]})
        with self.assertRaisesRegex(ValueError,'REVIEW_CHANGED'):progress(self.root,self.run,saved)
        self.candidate.pop('title');atomic_write_json(self.root/'normalized-candidates.json',{'patents':[self.candidate]})
        Path(self.original['path']).write_text('wrong original')
        with self.assertRaises(ValueError):progress(self.root,self.run,saved)
    def test_failed_empty_malformed_envelope_not_whole_record(self):
        for changed in [{'search_metadata':{'status':'Error'}},{'title':''},{'claims':['ok',{}]},{'publication_number':'USD999S1'},{'search_metadata':[]},{'abstract':{}}]:
            raw={**self.raw,**changed};self.assertIsNone(_json_result_values(json.dumps(raw).encode(),'serpapi_google_patents'))
        self.run['status']='failed'
        with self.assertRaisesRegex(ValueError,'RECEIPT_INVALID'):progress(self.root,self.run,self.evidence)
    def test_new_record_review_appends_when_material_input_changes(self):
        self.review();old=load_json(self.root/'evidence.json')['record_content_reviews'][0]
        self.candidate['title']='New material observation';atomic_write_json(self.root/'normalized-candidates.json',{'patents':[self.candidate]})
        state=self.review();saved=load_json(self.root/'evidence.json')
        self.assertTrue(state['material_processing_complete']);self.assertEqual(len(saved['record_content_reviews']),2)
        self.assertEqual(saved['record_content_reviews'][0],old)
        self.assertEqual(saved['record_content_reviews'][1]['previous_event_sha256'],old['event_sha256'])

    def test_search_disposition_cannot_replace_whole_record_read(self):
        with self.assertRaisesRegex(ValueError,'WHOLE_RECORD_REVIEW_REQUIRED'):append_dispositions(self.root,'R1',[{'position':1,'outcome':'non_candidate','reviewer':'r','reason':'not relevant'}])
    def test_normalizer_preserves_general_truncation(self):
        from serpapi_patent_details_client import _normalize
        raw={**self.raw,'truncated':True,'protection_content_truncated':True}
        item={'q':'USD1127104S1','patent_id':'patent/USD1127104S1/en','candidate_id':'C1','right_type':'design','jurisdiction':'US'}
        normalized=_normalize(raw,item,retrieval_workflow_revision='api-first-v3')
        self.assertTrue(normalized['truncated']);self.assertTrue(normalized['protection_content_truncated'])
        self.assertNotIn('protection_content',record_facts(normalized,self.entry))

    def test_truncation_preserved_and_image_links_never_satisfy_figures(self):
        self.raw['claims_truncated']=True;self.payload['claims_truncated']=True;self.save();state=self.review()
        self.assertIn('claims_truncated',state['record_content_review']['limitations'])
        facts=record_facts(self.payload,self.entry);self.assertNotIn('protection_content',facts);self.assertNotIn('representative_figures',facts)
    def test_legacy_not_upgraded(self):
        self.task['retrieval_workflow_revision']='api-first-v2';atomic_write_json(self.root/'task.json',self.task)
        self.assertIsNone(progress(self.root,self.run,self.evidence)['returned_count'])

if __name__=='__main__':unittest.main()

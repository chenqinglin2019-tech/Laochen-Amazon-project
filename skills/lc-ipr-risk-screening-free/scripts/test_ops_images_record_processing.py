"""Offline exact OPS images records, including genuine retained TIFF validation."""
import copy
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from common import atomic_write_json,load_json,sha256_file,sha256_json
from source_result_processing import make_index,progress,append_record_content_review,_ops_images_metadata,locate_one_to_one

XML='''<ops:world-patent-data xmlns="http://www.epo.org/exchange" xmlns:ops="http://ops.epo.org"><ops:document-inquiry><ops:publication-reference><document-id document-id-type="epodoc"><doc-number>USD123S</doc-number></document-id></ops:publication-reference><ops:inquiry-result><publication-reference><document-id document-id-type="docdb"><country>US</country><doc-number>D123</doc-number><kind>S</kind></document-id></publication-reference><ops:document-instance system="ops.epo.org" number-of-pages="4" desc="FullDocument" link="published-data/images/US/D123/S/fullimage"><ops:document-format-options><ops:document-format>application/tiff</ops:document-format></ops:document-format-options><ops:document-section name="DRAWINGS" start-page="3"/></ops:document-instance></ops:inquiry-result></ops:document-inquiry></ops:world-patent-data>'''

class OpsImagesRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.task={'task_id':'OPS-IMAGE-TEST','retrieval_workflow_revision':'api-first-v3','result_processing_revision':'source-result-processing-v1'}
        raw=self.root/'record.xml';raw.write_text(XML)
        image=self.root/'page.tiff';Image.new('RGB',(8,12),'white').save(image,format='TIFF')
        self.media={'path':str(image),'sha256':sha256_file(image),'bytes':image.stat().st_size,'width':8,'height':12,'mime_type':'image/tiff',
            'publication_number':'USD123S','page_number':3,'source_path':'published-data/images/US/D123/S/fullimage','is_thumbnail':False}
        self.candidate={'candidate_id':'C1','publication_number':'USD123S','jurisdiction':'US','right_type':'design'}
        self.row={**self.candidate,'detail_operations':['images'],'media':[self.media],'images':[self.media],
            'media_acquisition':{'available_document_pages':4,'acquired_page_numbers':[3],'retained':1,'requested':1,'complete':False,'limitation':'Only page 3; all views incomplete.'}}
        payload={'detail_operation':'images','candidates':[self.row]}
        index=make_index(self.task,provider='epo_ops',evidence_type='patent',status='success',submission_state='submitted',raw_body=raw.read_bytes(),raw_suffix='xml',normalized=payload,coverage={},payload_digest=sha256_file(raw))
        index.update(returned_count=None,returned_count_basis='unknown',rows=[])
        self.run={'run_id':'R1','provider':'epo_ops','operation':'candidate_detail','jurisdiction':'US','status':'success','submission_state':'submitted',
            'request_params':{'detail_operation':'images','q':'USD123S','document':'USD123S','candidate_id':'C1'},'raw_paths':[str(raw)],'payload_digest':sha256_file(raw),'result_processing':index}
        self.evidence={'source_runs':[self.run],'collections':{'patents':[{'evidence_id':'E1','source_run_id':'R1','payload':payload}]}}
        for name,data in [('task.json',self.task),('evidence.json',self.evidence),('normalized-candidates.json',{'patents':[self.candidate]})]:atomic_write_json(self.root/name,data)
    def review(self):
        return append_record_content_review(self.root,'R1',{'reading_units':['identity','image_metadata','retained_media'],'reviewer':'reader','reason':'Read metadata and actual page 3 TIFF; all remaining views unresolved.'})
    def test_exact_old_receipt_read_without_search_cards_or_run_mutation(self):
        prior=copy.deepcopy(self.run);state=progress(self.root,self.run,self.evidence)
        self.assertEqual((state['returned_count'],state['parsed_count'],state['unlocated_parsed_count']),(1,1,0));self.assertEqual(state['pending_parse_positions'],[])
        state=self.review();self.assertTrue(state['material_processing_complete']);self.assertFalse(state['zero_proven'])
        self.assertIn('Only page 3; all views incomplete.',state['record_content_review']['limitations'])
        saved=load_json(self.root/'evidence.json');self.assertEqual(saved['source_runs'][0],prior);self.assertEqual(saved['collections'],self.evidence['collections'])
        normalized=locate_one_to_one(self.task,'epo_ops','patent',XML.encode(),'xml',copy.deepcopy(self.evidence['collections']['patents'][0]['payload']))
        self.assertNotIn('source_position',normalized['candidates'][0])
    def test_wrong_country_number_or_operation_rejected(self):
        self.run['request_params']['document']='USD999S'
        with self.assertRaisesRegex(ValueError,'IDENTITY_INVALID'):progress(self.root,self.run,self.evidence)
        self.run['request_params']['document']='USD123S';self.run['jurisdiction']='GB'
        with self.assertRaisesRegex(ValueError,'IDENTITY_INVALID'):progress(self.root,self.run,self.evidence)
        self.run['jurisdiction']='US';self.run['request_params']['detail_operation']='biblio'
        with self.assertRaisesRegex(ValueError,'IDENTITY_INVALID'):progress(self.root,self.run,self.evidence)
    def test_failed_no_unsubmitted_promotion(self):
        for key,value in [('status','failed'),('submission_state','not_submitted')]:
            original=self.run[key];self.run[key]=value
            with self.assertRaises(ValueError):progress(self.root,self.run,self.evidence)
            self.run[key]=original
    def test_bad_raw_structure_or_fault_not_image_receipt(self):
        for body in [XML.replace('USD123S','USD999S'),XML.replace('US/D123/S','US/D999/S'),XML.replace('</ops:inquiry-result>','<ops:fault>error</ops:fault></ops:inquiry-result>'),'<fault xmlns="http://ops.epo.org"><code>SERVER.EntityNotFound</code><message>No results found</message></fault>']:
            self.assertIsNone(_ops_images_metadata(body.encode()))
    def test_hash_and_media_metadata_tamper_rejected(self):
        Path(self.media['path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):progress(self.root,self.run,self.evidence)
    def test_unread_urls_or_thumbnails_cannot_complete_reading(self):
        self.media['is_thumbnail']=True
        with self.assertRaisesRegex(ValueError,'MEDIA_INVALID'):progress(self.root,self.run,self.evidence)
        self.media['is_thumbnail']=False;self.row['media']=[];self.row['images']=[]
        with self.assertRaisesRegex(ValueError,'MEDIA_INVALID'):progress(self.root,self.run,self.evidence)
    def test_only_correct_reading_units_can_close(self):
        with self.assertRaisesRegex(ValueError,'READING_REQUIRED'):append_record_content_review(self.root,'R1',{'reading_units':['identity','image_metadata'],'reviewer':'r','reason':'Only metadata read'})
        self.assertFalse(progress(self.root,self.run,self.evidence)['material_processing_complete'])

    def test_merge_materialization_reuses_exact_page_read_and_preserves_old_signature(self):
        self.review()
        saved=load_json(self.root/'evidence.json')
        # Construct a historical-format receipt in this isolated fixture.
        prior=saved['record_content_reviews'][0]
        prior['binding']['candidate_content_sha256']='a'*64
        prior['event_sha256']=sha256_json({k:v for k,v in prior.items() if k!='event_sha256'})
        atomic_write_json(self.root/'evidence.json',saved)
        original=copy.deepcopy(prior)
        self.candidate.update(media=[self.media],images=[self.media],
                              media_acquisition=self.row['media_acquisition'])
        atomic_write_json(self.root/'normalized-candidates.json',{'patents':[self.candidate]})
        state=progress(self.root,self.run,saved)
        self.assertTrue(state['material_processing_complete'])
        self.assertEqual(state['record_content_review'],original)
        self.review()
        after=load_json(self.root/'evidence.json')
        self.assertEqual(after['record_content_reviews'],[original])

    def test_review_still_binds_original_raw_run_page_and_candidate_identity(self):
        self.review();saved=load_json(self.root/'evidence.json')
        changes=[('run',lambda run:run.update(query_id='different-query')),
                 ('run',lambda run:run.update(plan_entry_sha256='f'*64)),
                 ('candidate',lambda candidate:candidate.update(publication_number='USD999S')),
                 ('candidate',lambda candidate:candidate.update(jurisdiction='JP')),
                 ('media',lambda media:media.update(page_number=4)),
                 ('media',lambda media:media.update(sha256='0'*64))]
        for kind,change in changes:
            with self.subTest(kind=kind,change=change):
                altered=copy.deepcopy(saved);run=altered['source_runs'][0]
                candidate=copy.deepcopy(self.candidate)
                if kind=='run':change(run)
                elif kind=='candidate':change(candidate)
                else:change(altered['collections']['patents'][0]['payload']['candidates'][0]['media'][0])
                atomic_write_json(self.root/'normalized-candidates.json',{'patents':[candidate]})
                with self.assertRaises(ValueError):progress(self.root,run,altered)
        atomic_write_json(self.root/'normalized-candidates.json',{'patents':[self.candidate]})
        Path(self.run['raw_paths'][0]).write_text(XML+'<!--changed-->')
        with self.assertRaises(ValueError):progress(self.root,self.run,saved)

    def test_legacy_read_signature_tamper_is_not_a_compatibility_projection(self):
        self.review();saved=load_json(self.root/'evidence.json')
        saved['record_content_reviews'][0]['binding']['candidate_content_sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'REVIEW_CHANGED'):progress(self.root,self.run,saved)



    def handoff(self,evidence=None,candidate=None,ref=None):
        from candidate_handoff import _source_state
        source={'provider':'epo_ops','evidence_id':'E1','source_run_id':'R1'}
        source.update(ref or {})
        return _source_state(source,evidence or load_json(self.root/'evidence.json'),
            self.root,candidate or self.candidate)

    def test_handoff_consumes_exact_whole_record_without_position_or_signature_rewrite(self):
        self.assertEqual(self.handoff()[0],'pending')
        self.review();saved=load_json(self.root/'evidence.json')
        before=copy.deepcopy(saved)
        self.assertEqual(self.handoff(),('ready','REVIEWED_WHOLE_RECORD_SOURCE'))
        self.assertEqual(saved,before)
        self.assertNotIn('result_dispositions',saved)
        self.assertEqual(saved['record_content_reviews'][0]['reading_units'],
            ['identity','image_metadata','retained_media'])
        self.assertIn('Only page 3; all views incomplete.',saved['record_content_reviews'][0]['limitations'])

    def test_handoff_wrong_candidate_evidence_number_position_or_hash_is_pending(self):
        self.review()
        for kwargs in [
                {'candidate':{**self.candidate,'candidate_id':'C2'}},
                {'candidate':{**self.candidate,'publication_number':'USD999S'}},
                {'candidate':{**self.candidate,'jurisdiction':'GB'}},
                {'ref':{'source_position':10}},
                {'ref':{'source_record_sha256':'0'*64}},
                {'ref':{'plan_entry_sha256':'f'*64}},
                {'ref':{'provider':'serper_web'}}]:
            with self.subTest(kwargs=kwargs):self.assertEqual(self.handoff(**kwargs)[0],'pending')
        saved=load_json(self.root/'evidence.json')
        saved['collections']['patents'].append({'evidence_id':'WRONG','source_run_id':'R-OTHER'})
        self.assertEqual(self.handoff(evidence=saved,ref={'evidence_id':'WRONG'})[0],'pending')

    def test_handoff_tampered_raw_page_media_run_or_old_reading_cannot_be_ready(self):
        self.review();saved=load_json(self.root/'evidence.json')
        for changed in ('raw','media','page','run','reading'):
            with self.subTest(changed=changed):
                evidence=copy.deepcopy(saved)
                raw=Path(self.run['raw_paths'][0]);raw_bytes=raw.read_bytes()
                media=Path(self.media['path']);media_bytes=media.read_bytes()
                if changed=='raw':raw.write_bytes(raw_bytes+b'changed')
                elif changed=='media':media.write_bytes(b'changed')
                elif changed=='page':evidence['collections']['patents'][0]['payload']['candidates'][0]['media'][0]['page_number']=4
                elif changed=='run':evidence['source_runs'][0]['plan_entry_sha256']='f'*64
                else:evidence['record_content_reviews'][0]['reason']='changed signed read'
                self.assertEqual(self.handoff(evidence=evidence)[0],'pending')
                raw.write_bytes(raw_bytes);media.write_bytes(media_bytes)

    def test_handoff_project_can_register_exact_read_source_after_canonical_materialization(self):
        from candidate_handoff import project,record_batch
        self.task.update(candidate_handoff_revision='candidate-handoff-v1',target_jurisdictions=['US'],
            assessment_scenarios=[{'scenario_id':'S1','type':'product_entry'}])
        self.candidate.update(media=[self.media],images=[self.media],sources=[
            {'provider':'epo_ops','evidence_id':'E1','source_run_id':'R1'}])
        atomic_write_json(self.root/'task.json',self.task)
        atomic_write_json(self.root/'normalized-candidates.json',{'patents':[self.candidate]})
        self.review();saved=load_json(self.root/'evidence.json');prior=copy.deepcopy(saved)
        view=project(self.task,saved,{'patents':[self.candidate]},self.root)
        self.assertEqual(view['rows'][0]['pending_sources'],[])
        self.assertEqual(view['rows'][0]['handoff_state'],'ready')
        event=record_batch(self.root,{'candidate_ids':['C1'],'reviewer':'reader',
            'reason':'Original page 3 read; remaining views stay unassessed',
            'scope_reviews':[{'candidate_id':'C1','scenario_id':'S1','jurisdiction':'US',
                'applicability':'applicable','reason':'Exact US source identity; no all-views assertion',
                'evidence_refs':['E1']}]})
        self.assertEqual(event['candidates'][0]['pending_sources'],[])
        self.assertEqual(load_json(self.root/'evidence.json'),prior)

if __name__=='__main__':unittest.main()

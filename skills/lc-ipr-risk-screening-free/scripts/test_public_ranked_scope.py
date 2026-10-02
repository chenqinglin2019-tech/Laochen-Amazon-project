"""A reviewed public ranking can end its bounded scope, never prove clearance."""
from copy import deepcopy
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import unittest
from common import sha256_json
from discovery_semantics import _current_public_ranked_scope_wait,public_ranked_scope_entry

class PublicRankedScopeTests(unittest.TestCase):
    def setUp(self):
        self.task={'retrieval_workflow_revision':'api-first-v3','public_discovery_routing_revision':'public-discovery-v1'}
        self.row={'query_id':'Q1','operation':'image_search','jurisdiction':'US','right_type':'copyright',
            'discovery_scope':{'mode':'bounded','max_pages':1,'review_all_returned':True}}
        self.run={'run_id':'R1','query_id':'Q1','provider':'serpapi_google_lens','status':'success',
            'plan_entry_sha256':sha256_json(self.row),'metadata':{'search_coverage':{
                'schema_valid':True,'truncated':True,'total_hits':None,'retrieved_hits':59,
                'stop_reason':'ranked_search_total_unknown'}}}
        self.after={'next_action':'awaiting_capability','problem_covered':False,'source_run_id':'R1',
            'source_run_sha256':sha256_json(self.run),'plan_entry_sha256':sha256_json(self.row),
            'review_sha256':'SEM-SHA','uncovered_clues':['author','first-publication']}
        self.review={'role':'review','parent_query_id':'Q1','source_run_id':'R1','outcome':'stop_bounded_discovery'}
        self.task['discovery_followups']=[self.review]
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.validation=self.stack.enter_context(patch('api_first_planning.review_validation',return_value=None))
        self.files=self.stack.enter_context(patch('api_first_planning.source_files_error',return_value=None))
        self.operation=self.stack.enter_context(patch('discovery_semantics._retained_ranked_operation_review',return_value={'review_id':'ORIGINAL-OP'}))
        self.processing=self.stack.enter_context(patch('source_result_processing.progress',return_value={
            'material_processing_complete':True,'returned_count':59}))
    def check(self, provider='serpapi_google_lens'):
        return _current_public_ranked_scope_wait(self.task,{}, {},{}, {},None,Path('/tmp/task'),
            provider,self.row,self.after,self.run)
    def test_actual_current_scope_is_limited_not_complete(self):
        proof=self.check();self.assertIsNotNone(proof)
        entry=public_ranked_scope_entry({'provider':'serpapi_google_lens'},self.row,self.after,self.run,proof)
        self.assertEqual(entry['state'],'blocked');self.assertEqual(entry['coverage_status'],'unknown')
        self.assertEqual(entry['reason'],'BOUNDED_PUBLIC_DISCOVERY_SCOPE_LIMITED')
        self.assertEqual(entry['uncovered_clues'],['author','first-publication'])
        self.assertNotIn('completed',entry);self.assertTrue(entry['resume_condition'])
    def test_unread_cards_failed_acceptance_raw_or_decision_remain_pending(self):
        for mock,value in [(self.validation,'CARD_REVIEW_REQUIRED'),(self.files,'RAW_FILE_CHANGED'),
            (self.operation,False),(self.processing,{'material_processing_complete':False,'returned_count':59}),
            (self.processing,{'material_processing_complete':True,'returned_count':58})]:
            old=mock.return_value;mock.return_value=value;self.assertIsNone(self.check());mock.return_value=old
    def test_exact_us_design_api_scope_uses_raw_design_filter_and_original_review(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as tmp:
            self.row.update(right_type='design',operation='search',type='DESIGN',country='US',
                q='ball toy',num=10)
            self.row['discovery_scope']['max_candidates']=10
            self.run.update(provider='serpapi_google_patents',plan_entry_sha256=sha256_json(self.row))
            coverage=self.run['metadata']['search_coverage']
            coverage.update(retrieved_hits=10,stop_reason='bounded_discovery_total_unknown')
            raw=Path(tmp)/'response.json'
            self.run['raw_paths']=[str(raw)]
            params={'engine':'google_patents','q':'ball toy','type':'DESIGN','country':'US','num':'10'}
            raw.write_text(json.dumps({'search_parameters':params}),encoding='utf-8')
            self.after.update(source_run_sha256=sha256_json(self.run),plan_entry_sha256=sha256_json(self.row))
            self.processing.return_value={'material_processing_complete':True,'returned_count':10}
            proof=self.check('serpapi_google_patents')
            self.assertIsNotNone(proof);self.assertEqual(proof['retrieval_scope_kind'],'bounded_us_design_api')
            for key,value in [('type','UTILITY'),('country','GB'),('q','other query'),('num','20'),('engine','google')]:
                changed={**params,key:value};raw.write_text(json.dumps({'search_parameters':changed}),encoding='utf-8')
                self.assertIsNone(self.check('serpapi_google_patents'))
            raw.write_text(json.dumps({'search_parameters':params}),encoding='utf-8')
            self.row['discovery_scope']['max_candidates']=25
            self.run['plan_entry_sha256']=sha256_json(self.row)
            self.after.update(source_run_sha256=sha256_json(self.run),plan_entry_sha256=sha256_json(self.row))
            self.assertIsNone(self.check('serpapi_google_patents'))

    def test_public_enforcement_api_full_bounded_receipt_has_no_exhaustive_claim(self):
        self.row.update(operation='search',right_type='enforcement',q='toy litigation',gl='us',hl='en',num=10)
        self.row['discovery_scope']['max_candidates']=10
        self.run.update(provider='serper_web',plan_entry_sha256=sha256_json(self.row),
            request_params={k:self.row[k] for k in ('q','gl','hl','num')})
        self.run['metadata']['search_coverage'].update(retrieved_hits=3,stop_reason='bounded_discovery_total_unknown')
        self.after.update(source_run_sha256=sha256_json(self.run),plan_entry_sha256=sha256_json(self.row))
        self.processing.return_value={'material_processing_complete':True,'returned_count':3}
        proof=self.check('serper_web');self.assertEqual(proof['retrieval_scope_kind'],'bounded_public_enforcement_api')
        self.assertEqual(public_ranked_scope_entry({},self.row,self.after,self.run,proof)['coverage_status'],'unknown')
        for key,value in [('gl','gb'),('q','other'),('num',20)]:
            old=self.run['request_params'][key];self.run['request_params'][key]=value
            self.after['source_run_sha256']=sha256_json(self.run);self.assertIsNone(self.check('serper_web'))
            self.run['request_params'][key]=old
        self.after['source_run_sha256']=sha256_json(self.run)
        self.processing.return_value={'material_processing_complete':False,'returned_count':3}
        self.assertIsNone(self.check('serper_web'))

    def zero_fixture(self):
        self.native_fixture();self.run['status']='no_result'
        self.run['metadata']['search_coverage'].update(truncated=False,retrieved_hits=0,total_hits=0,
            stop_reason='query_exhausted',empty_fault_receipt=True,range_verified=False)
        self.after['source_run_sha256']=sha256_json(self.run)
        self.processing.return_value={'material_processing_complete':True,'returned_count':0,'zero_proven':True}

    def test_exact_native_zero_needs_current_same_direction_bounded_investigation(self):
        self.zero_fixture()
        shared={'query_id':'SHARED','processed_record_count':25,'total_record_count':7047,
            'unretrieved_record_count':7022,'relation':'same_current_direction_scope'}
        with patch('discovery_semantics._same_direction_native_limit',return_value=shared):
            proof=self.check('epo_ops');self.assertEqual(proof['processed_record_count'],0)
            self.assertEqual(proof['shared_direction_scope'],shared)
            entry=public_ranked_scope_entry({},self.row,self.after,self.run,proof)
            self.assertEqual(entry['coverage_status'],'unknown');self.assertIn('7022',entry['reasoning'])
            for key,value in [('zero_proven',False),('material_processing_complete',False),('returned_count',1)]:
                old=self.processing.return_value[key];self.processing.return_value[key]=value
                self.assertIsNone(self.check('epo_ops'));self.processing.return_value[key]=old
            self.files.return_value='RAW_FILE_CHANGED';self.assertIsNone(self.check('epo_ops'))
        with patch('discovery_semantics._same_direction_native_limit',return_value=None):
            self.assertIsNone(self.check('epo_ops'))

    def test_shared_investigation_rejects_other_country_direction_and_unread_scope(self):
        from discovery_semantics import _same_direction_native_limit
        self.zero_fixture()
        deps=[{'scenario_id':'product_entry','direction_id':'drive','sha256':'real'}]
        self.row['product_dependencies']=deps
        self.after.update(direction_id='drive',scenario_id='product_entry',jurisdiction='US',right_type='patent')
        other={**self.row,'query_id':'OTHER','action_purpose':'discovery','refinement_round':2}
        plan={'queries':{'epo_ops':[self.row,other]}}
        success={'run_id':'ACTUAL','status':'success'}
        with patch('assessment_v24.bound_runs',return_value=[success]), \
                patch('discovery_semantics.current',return_value={'review_sha256':'CURRENT'}), \
                patch('discovery_semantics._current_public_ranked_scope_wait',return_value={'retrieval_scope_kind':'bounded_native_api_range'}) as checked:
            def shared():return _same_direction_native_limit(self.task,plan,{}, {},{},None,Path('/tmp/task'),'epo_ops',self.row,self.after)
            proof=shared();self.assertEqual(proof['relation'],'same_current_direction_scope')
            self.assertNotIn('parent_query_id',proof)
            for key,value in [('jurisdiction','GB'),('right_type','design'),('product_dependencies',[])]:
                old=other[key];other[key]=value;self.assertIsNone(shared());other[key]=old
            checked.return_value=None;self.assertIsNone(shared())

    def native_fixture(self):
        self.row.update(operation='search',right_type='patent',range='1-25')
        self.row['discovery_scope']['max_candidates']=25
        self.run.update(provider='epo_ops',plan_entry_sha256=sha256_json(self.row),request_params={'range':'1-25'})
        self.run['metadata']['search_coverage'].update(retrieved_hits=25,total_hits=1083,
            stop_reason='page_limit',range_verified=True,range_start=1,range_end=25)
        self.after.update(source_run_sha256=sha256_json(self.run),plan_entry_sha256=sha256_json(self.row))
        self.processing.return_value={'material_processing_complete':True,'returned_count':25}

    def test_native_frozen_range_is_limited_with_true_unretrieved_count(self):
        self.native_fixture();proof=self.check('epo_ops');self.assertIsNotNone(proof)
        self.assertEqual(proof['total_record_count'],1083)
        self.assertEqual(proof['unretrieved_record_count'],1058)
        entry=public_ranked_scope_entry({},self.row,self.after,self.run,proof)
        self.assertEqual(entry['coverage_status'],'unknown');self.assertEqual(entry['state'],'blocked')
        self.assertEqual(entry['unretrieved_result_row_count'],1058)
        self.assertIn('分页能力有效',entry['reasoning'])
        self.assertIn('1058',entry['reasoning'])

    def test_native_range_unread_or_changed_fields_do_not_end_scope(self):
        self.native_fixture();coverage=self.run['metadata']['search_coverage'];original=deepcopy(coverage)
        for key,value in [('range_verified',False),('range_start',2),('range_end',24),
            ('total_hits',None),('total_hits',25),('retrieved_hits',24),('stop_reason','query_exhausted')]:
            coverage[key]=value;self.after['source_run_sha256']=sha256_json(self.run)
            self.assertIsNone(self.check('epo_ops'));coverage.clear();coverage.update(original)
        self.run['request_params']['range']='26-50';self.after['source_run_sha256']=sha256_json(self.run)
        self.assertIsNone(self.check('epo_ops'))
        self.run['request_params']['range']='1-25';self.after['source_run_sha256']=sha256_json(self.run)
        self.processing.return_value={'material_processing_complete':False,'returned_count':25}
        self.assertIsNone(self.check('epo_ops'))

    def test_existing_active_page_is_not_hidden_by_parent_stop(self):
        self.native_fixture()
        from discovery_semantics import _current_public_ranked_scope_wait
        plan={'queries':{'epo_ops':[{'query_id':'Q2','parent_query_id':'Q1','discovery_role':'pagination'}]}}
        with patch('api_first_planning.pagination_parent_stop_valid',return_value=False):
            self.assertIsNone(_current_public_ranked_scope_wait(self.task,plan,{}, {},{},None,
                Path('/tmp/task'),'epo_ops',self.row,self.after,self.run))
        with patch('api_first_planning.pagination_parent_stop_valid',return_value=True):
            self.assertIsNotNone(_current_public_ranked_scope_wait(self.task,plan,{}, {},{},None,
                Path('/tmp/task'),'epo_ops',self.row,self.after,self.run))
        plan['queries']['epo_ops'][0]['discovery_role']='refinement'
        self.assertIsNotNone(_current_public_ranked_scope_wait(self.task,plan,{}, {},{},None,
            Path('/tmp/task'),'epo_ops',self.row,self.after,self.run))
        self.assertEqual(plan['queries']['epo_ops'][0]['query_id'],'Q2')

    def test_failed_cross_record_tampered_and_legacy_are_rejected(self):
        original=deepcopy(self.run)
        for key,value in [('status','failed'),('query_id','OTHER'),('provider','epo_ops')]:
            self.run[key]=value;self.after['source_run_sha256']=sha256_json(self.run)
            self.assertIsNone(self.check());self.run.clear();self.run.update(deepcopy(original))
        self.after['source_run_sha256']='changed';self.assertIsNone(self.check())
        self.after['source_run_sha256']=sha256_json(self.run)
        for revision in ['api-first-v2','api-first-v1']:
            self.task['retrieval_workflow_revision']=revision;self.assertIsNone(self.check())
    def test_known_total_zero_count_nonranking_or_changed_scope_are_not_public_limit(self):
        coverage=self.run['metadata']['search_coverage'];original=deepcopy(coverage)
        for key,value in [('total_hits',100),('retrieved_hits',0),('truncated',False),
            ('schema_valid',False),('stop_reason','page_limit')]:
            coverage[key]=value;self.after['source_run_sha256']=sha256_json(self.run)
            self.assertIsNone(self.check());coverage.clear();coverage.update(original)
        self.after['source_run_sha256']=sha256_json(self.run)
        self.row['discovery_scope']['max_pages']=2
        self.run['plan_entry_sha256']=sha256_json(self.row);self.after['plan_entry_sha256']=sha256_json(self.row)
        self.after['source_run_sha256']=sha256_json(self.run);self.assertIsNone(self.check())

class PublicScopeProjectionTests(unittest.TestCase):
    def test_only_exact_duplicate_truncation_is_removed_after_validated_scope_limit(self):
        from necessary_completion import refine_work_view
        scope={'scenario_id':'product_entry','jurisdiction':'US','right_type':'copyright',
            'provider':'serpapi_google_lens','query_id':'Q1'}
        limited={**scope,'kind':'plan_repair','state':'blocked','reason':'BOUNDED_PUBLIC_DISCOVERY_SCOPE_LIMITED'}
        duplicate={**scope,'kind':'source_lookup','state':'awaiting_review','reason':'API_RETURNED_SCOPE_TRUNCATED'}
        unread={**scope,'kind':'agent_read','state':'awaiting_review','reason':'RETAINED_ORIGINAL_REQUIRES_READING'}
        other={**duplicate,'query_id':'Q2'}
        view={'entries':[limited,duplicate,unread,other]}
        plan={'queries':{'serpapi_google_lens':[{'query_id':'Q1'}]}}
        with patch('necessary_completion.enabled',return_value=True), \
             patch('workflow_v24.product_analysis_readiness',return_value={'gaps':[]}), \
             patch('completion_policy.evidence_delivery_enabled',return_value=False), \
             patch('necessary_completion._current_semantic_wait',return_value=True):
            output=refine_work_view({},view,plan,{})
            self.assertNotIn(duplicate,output['entries']);self.assertIn(limited,output['entries'])
            self.assertIn(unread,output['entries']);self.assertIn(other,output['entries'])
        with patch('necessary_completion.enabled',return_value=True), \
             patch('workflow_v24.product_analysis_readiness',return_value={'gaps':[]}), \
             patch('completion_policy.evidence_delivery_enabled',return_value=False), \
             patch('necessary_completion._current_semantic_wait',return_value=False):
            output=refine_work_view({},view,plan,{})
            self.assertIn(duplicate,output['entries'])

class OriginalOperationReviewTests(unittest.TestCase):
    def test_reuse_checks_original_review_without_creating_new_acceptance(self):
        from discovery_semantics import _retained_ranked_operation_review
        original={'run_id':'ORIGINAL','submission_state':'submitted'}
        logical={'run_id':'LOGICAL','submission_state':'not_submitted',
            'metadata':{'physical_response_reuse':{'source_run_id':'ORIGINAL'}}}
        review={'provider':'serpapi_google_lens','source_run_id':'ORIGINAL','decision':'accepted'}
        task={'source_operation_reviews':[review]}
        with patch('runtime_v24.physical_response_source',return_value=original) as source, \
             patch('source_operation.verify',return_value=None) as verify:
            found=_retained_ranked_operation_review(task,{}, {},Path('/tmp/task'),'serpapi_google_lens',logical)
            self.assertEqual(found,review);source.assert_called_once()
            self.assertEqual(verify.call_args.args[0]['source_operation_reviews'],[review])
        with patch('runtime_v24.physical_response_source',return_value=None):
            self.assertIsNone(_retained_ranked_operation_review(task,{}, {},Path('/tmp/task'),'serpapi_google_lens',logical))
        with patch('runtime_v24.physical_response_source',return_value=original), \
             patch('source_operation.verify',side_effect=ValueError('SOURCE_OPERATION_RECEIPT_CHANGED')):
            self.assertIsNone(_retained_ranked_operation_review(task,{}, {},Path('/tmp/task'),'serpapi_google_lens',logical))

if __name__=='__main__':unittest.main()

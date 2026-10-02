"""02A image/fact delivery contracts; retained synthetic sources, no network."""
from unittest.mock import patch
import unittest

from common import atomic_write_json, load_json, sha256_json
from product_delivery import selected_public_image, query_row_binding, validate_image_query
from record_product_scope import record as record_scope
from workflow_v24 import generate_plan, term_records
import test_product_entry as entry_fixture


class ProductDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.f = entry_fixture.ProductEntryTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        (self.f.root/'back.png').write_bytes(entry_fixture.PNG)
        self.f.data['schema_version'] = 'product-input-v2'
        self.f.data['sources'].append({'source_id':'back','kind':'image','path':'back.png'})
        self.f.data['image_selection'] = {'status':'selected','source_id':'back','selected_by':'agent',
            'reason':'The second supplied file shows the complete target product.'}
        self.f.write_input(); self.f.ready()
        self.run = self.f.run
        task=load_json(self.run/'task.json')
        # These cases target the pre-v3 browser planning contract. Keep the
        # newly created task defaults from changing their route expectations.
        task.pop('retrieval_workflow_revision',None)
        task['source_operation_revision']='source-operation-v1'
        from workflow_v24 import build_coverage_requirements_v24
        task['coverage_requirements']=build_coverage_requirements_v24(
            task['target_jurisdictions'],screening_revision=task.get('screening_revision'),
            specialty_workflow_revision=task.get('specialty_workflow_revision'))
        from common import serper_free_enhancement, serpapi_free_enhancement
        task['serper_free_enhancement']=serper_free_enhancement(False)
        task['serpapi_free_enhancement']=serpapi_free_enhancement(False)
        task['product_scope_required']=True
        atomic_write_json(self.run/'task.json',task)
        ev=task['product_identity']['evidence_id']
        self.payload={'schema_version':'product-scope-input-v2','expected_scope_sha256':'','sources':[],
            'scope':{'status':'reviewed','reviewer':'offline-agent','reasoning':'Separate observed shape from a mechanism claim.',
                'delivery_revision':'image-fact-v1','image_permissions':[],
                'objects':[{'object_id':'back-pattern','kind':'pattern','relation':'integrated','intent':'default',
                    'description':'Back pattern','location':'second image, back','reason':'Visible on the rear view.',
                    'right_types':['copyright'],'source_refs':[ev],
                    'visual_evidence':{'image_ids':['IMG-002'],'main_visibility':'limited',
                                       'limitation_reason':'Rear pattern is small in the selected whole-product image.'}}],
                'facts':[{'fact_id':'shape','version':1,'source_path':'product.title','value':'Folding stand',
                    'status':'confirmed','nature':'direct_observation','verification':'verified',
                    'applies_to':{'product_id':task['product']['product_id']},'source_refs':[ev],
                    'reason':'The supplied full view shows the stand.'},
                    {'fact_id':'hinge-claim','version':1,'source_path':'product.structure[0]','value':'hinged support',
                    'status':'confirmed','nature':'user_statement','verification':'claim_only',
                    'applies_to':{'product_id':task['product']['product_id']},'source_refs':[ev],
                    'reason':'Text states the mechanism; internal operation has not been observed.'}],
                'directions':[{'direction_id':'shape','scenario_id':'product_entry','right_type':'design',
                    'fact_ids':['shape'],'object_ids':[],'reason':'Overall outline is observable.'},
                    {'direction_id':'claim-search','scenario_id':'product_entry','right_type':'patent',
                    'fact_ids':['hinge-claim'],'object_ids':[],'reason':'Claim may be used as a search lead.'},
                    {'direction_id':'pattern','scenario_id':'product_entry','right_type':'copyright',
                    'fact_ids':['shape'],'object_ids':['back-pattern'],'reason':'Rear pattern requires its own coverage.'}]},
            'query_terms':[{'kind':'design','value':'folding stand','language':'en','derived_from':'product.title'},
                           {'kind':'structural_feature','value':'hinged support','language':'en','derived_from':'product.structure[0]'}]}
        self.scope_path=self.f.root/'delivery-scope.json'

    def save(self):
        atomic_write_json(self.scope_path,self.payload)
        return record_scope(self.run,self.scope_path)

    def test_new_scenario_followup_binds_current_fact_versions_without_mutating_input(self):
        from copy import deepcopy
        from product_delivery import validate_fact_query
        from workflow_v24 import bind_scenario_action
        self.save()
        task = load_json(self.run / "task.json")
        original = {"operation": "candidate_verification", "jurisdiction": "US",
                    "right_type": "patent", "q": "US11111111B2",
                    "candidate_id": "C1", "derived_from": ["product.structure[0]"]}
        before = deepcopy(original)
        bound = bind_scenario_action(task, "uspto_patent_browser", original,
                                     purpose="needs_info:exact abstract", scenario_id="product_entry")
        self.assertEqual(original, before)
        self.assertIsNone(validate_fact_query(task, bound))
        self.assertEqual(bound["product_fact_refs"][0]["fact_id"], "hinge-claim")
        task["product_scope"]["facts"][1]["version"] += 1
        self.assertEqual(validate_fact_query(task, bound), "PRODUCT_FACT_VERSION_REVIEW_REQUIRED")

    def test_amazon_recapture_refreshes_delivery_view_without_rewriting_scope(self):
        from copy import deepcopy
        from product_delivery import project
        other = entry_fixture.ProductEntryTests(); other.setUp(); self.addCleanup(other.doCleanups)
        other.create(amazon=True); other.preflight()
        capture = other.capture()
        from datetime import datetime, timedelta, timezone
        first = load_json(capture)
        first['collected_at'] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        atomic_write_json(capture, first)
        other.cli('record_browser_product.py', '--task-dir', other.run, '--capture', capture)
        task = load_json(other.run/'task.json')
        task['product_scope_required'] = True  # Enable the current contract on this historical fixture.
        atomic_write_json(other.run/'task.json', task)
        payload = deepcopy(self.payload)
        payload['scope']['objects'] = []
        payload['scope']['facts'] = payload['scope']['facts'][:1]
        fact = payload['scope']['facts'][0]
        fact['applies_to']['product_id'] = task['product']['product_id']
        fact['source_refs'] = [task['product_identity']['evidence_id']]
        payload['scope']['directions'] = payload['scope']['directions'][:1]
        payload['scope']['directions'][0]['object_ids'] = []
        payload['query_terms'] = payload['query_terms'][:1]
        file = other.root/'scope.json'; atomic_write_json(file, payload); record_scope(other.run, file)
        before = load_json(other.run/'task.json')['product_scope']
        data = load_json(capture)
        # Actual acceptance timestamps must be recent; change non-identity
        # metadata to ensure a distinct original receipt without altering facts.
        data['collected_at'] = entry_fixture.now_iso(); data['manufacturer'] = 'Corrected manufacturer'
        second = other.root/'second-capture.json'; atomic_write_json(second, data)
        other.cli('record_browser_product.py', '--task-dir', other.run, '--capture', second)
        current = load_json(other.run/'task.json')
        self.assertEqual(current['product_scope'], before)
        self.assertEqual(current['product_delivery'], project(current))
        from product_scope import verify
        verify(current, load_json(other.run/'evidence.json'), other.run)
        self.assertEqual(len(load_json(other.run/'evidence.json')['collections']['product_scope']), 1)

    def test_second_image_selected_with_reason_and_target_binding(self):
        task=load_json(self.run/'task.json')
        self.assertEqual([v['role'] for v in task['images']],['product_view','main'])
        image=task['product']['query_image']
        self.assertEqual(image['image_id'],'IMG-002')
        self.assertEqual(image['sha256'],task['images'][1]['sha256'])
        self.assertTrue(image['reason'])
        self.save(); task=load_json(self.run/'task.json')
        self.assertEqual(task['product_delivery_revision'],'image-fact-v1')
        self.assertEqual(task['product_scope']['objects'][0]['visual_evidence']['image_ids'],['IMG-002'])
        self.assertEqual(set(task['product_delivery']) & {'product_range','facts_and_clues','objects_and_marks','gaps_and_conflicts'},
                         {'product_range','facts_and_clues','objects_and_marks','gaps_and_conflicts'})
        self.assertTrue(any(g['kind']=='image_route' for g in task['product_delivery']['gaps_and_conflicts']))
        self.assertEqual(task['product_delivery']['can_continue_direction_ids'], ['shape','claim-search','pattern'])
        self.assertEqual(next(g for g in task['product_delivery']['gaps_and_conflicts']
                              if g['kind'] == 'image_visibility')['affected_direction_ids'], ['pattern'])

    def test_delivery_projection_tamper_blocks_planning(self):
        self.save(); task=load_json(self.run/'task.json')
        task['product_delivery']['facts_and_clues'][0]['value']='invented'
        atomic_write_json(self.run/'task.json',task)
        with self.assertRaisesRegex(ValueError,'PRODUCT_DELIVERY_PROJECTION_CHANGED'): generate_plan(self.run)

    def test_claim_is_stable_search_lead_and_local_image_does_not_route(self):
        self.save(); task=load_json(self.run/'task.json')
        claim=next(t for t in term_records(task) if t['derived_from']=='product.structure[0]')
        self.assertEqual((claim['fact_id'],claim['fact_version'],claim['fact_nature'],claim['fact_verification']),
                         ('hinge-claim',1,'user_statement','claim_only'))
        self.assertIsNone(selected_public_image(task))
        plan=generate_plan(self.run)
        self.assertFalse(plan['queries'].get('serpapi_google_lens'))
        self.assertTrue(any(g['code']=='QUERY_IMAGE_ROUTE_UNAVAILABLE' for g in plan['planning_gaps']))
        self.assertTrue(any(plan['queries'].values()))
        claimed=[row for rows in plan['queries'].values() for row in rows
                 if 'product.structure[0]' in row.get('derived_from',[])]
        self.assertTrue(claimed)
        self.assertEqual(claimed[0]['product_fact_refs'][0]['version'],1)

    def test_fact_version_change_defers_old_query_without_rewriting_plan(self):
        self.save(); plan=generate_plan(self.run)
        provider,row=next((provider,row) for provider,rows in plan['queries'].items() for row in rows
                          if 'product.structure[0]' in row.get('derived_from',[]))
        self.payload['expected_scope_sha256']=load_json(self.run/'task.json')['product_scope']['scope_sha256']
        self.payload['scope']['facts'][1]['version']=2
        self.save()
        from workflow_v24 import scenario_dispatch_block_from_dir
        result=scenario_dispatch_block_from_dir(self.run,provider,row)
        self.assertEqual(result['reason'],'PRODUCT_FACT_VERSION_REVIEW_REQUIRED')
        self.assertEqual(load_json(self.run/'search-plan.json')['queries'][provider][0]['product_fact_refs'][0]['version'],1)

    def test_unsupported_claim_upgrade_and_missing_image_limit_rejected(self):
        self.payload['scope']['facts'][1]['nature']='page_claim'
        self.payload['scope']['facts'][1]['verification']='verified'
        with self.assertRaisesRegex(ValueError,'CLAIM_CANNOT'): self.save()
        self.payload['scope']['facts'][1]['verification']='claim_only'
        with self.assertRaisesRegex(ValueError,'PAGE_CLAIM_SOURCE'): self.save()
        self.payload['scope']['facts'][1]['nature']='user_statement'
        self.payload['scope']['objects'][0]['visual_evidence']['limitation_reason']=''
        with self.assertRaisesRegex(ValueError,'IMAGE_LIMITATION'): self.save()
        self.assertNotIn('product_delivery_revision',load_json(self.run/'task.json'))

    def test_report_discloses_default_source_claim_and_main_limit(self):
        import report_estimate
        self.save()
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        original=report_estimate.build_report_data; captured=[]
        def build(*args,**kwargs):
            data=original(self.run,task,evidence,*args[3:],**kwargs)
            captured.append(data); return data
        with patch.object(report_estimate,'build_report_data',side_effect=build), patch.object(self.f,'ready',return_value=task):
            self.f.test_render_user_material_source_without_empty_amazon_link()
        for rendered in (report_estimate.render_html(captured[0],self.run),report_estimate.render_markdown(captured[0])):
            for text in ('系统默认','仅确认存在该声明','主图呈现限制','IMG-002','hinge-claim'):
                self.assertIn(text,rendered)

    def test_unresolved_main_image_keeps_images_as_views(self):
        other=entry_fixture.ProductEntryTests(); other.setUp(); self.addCleanup(other.doCleanups)
        other.data['schema_version']='product-input-v2'
        other.data['image_selection']={'status':'needs_clarification','reason':'Two whole-product photos show different versions.',
                                       'question':'Which pictured version is the target?'}
        other.write_input(); other.ready()
        task=load_json(other.run/'task.json')
        self.assertEqual(task['product']['query_image']['status'],'needs_clarification')
        self.assertFalse(any(image['role']=='main' for image in task['images']))

    def test_other_public_url_requires_retained_file_and_review(self):
        other=entry_fixture.ProductEntryTests(); other.setUp(); self.addCleanup(other.doCleanups)
        other.data['schema_version']='product-input-v2'
        other.data['image_selection']={'status':'selected','source_id':'image-1','selected_by':'agent',
                                       'reason':'The reviewed whole-product image is the query main.'}
        other.data['sources'][0].update(source_url='https://example.com/product.png',
            public_url_review={'status':'confirmed','reviewer':'offline-agent',
                               'reason':'The retained file was compared to this declared URL.'})
        other.write_input(); other.ready()
        task=load_json(other.run/'task.json')
        self.assertEqual(task['product']['query_image']['source_kind'],'other_public_url')
        self.assertEqual(task['images'][0]['source_url'],'https://example.com/product.png')
        another=entry_fixture.ProductEntryTests(); another.setUp(); self.addCleanup(another.doCleanups)
        another.data['schema_version']='product-input-v2'
        another.data['image_selection']=other.data['image_selection']
        another.data['sources'][0]['source_url']='https://example.com/product.png'
        another.write_input()
        from product_entry import load_materials
        with self.assertRaisesRegex(ValueError,'PUBLIC_URL_REVIEW_REQUIRED'):
            load_materials(another.input)
        another.data['sources'][0]['public_url_review']={'status':'confirmed','reviewer':'offline-agent',
            'reason':'Synthetic source claim.'}
        another.data['sources'][0]['source_url']='https://127.0.0.1/private.png'
        another.write_input()
        with self.assertRaisesRegex(ValueError,'PUBLIC_URL_REVIEW_REQUIRED'):
            load_materials(another.input)

    def test_public_main_permission_is_provider_specific_and_revocable(self):
        other=entry_fixture.ProductEntryTests(); other.setUp(); self.addCleanup(other.doCleanups)
        other.cli('create_task.py','--url','https://www.amazon.com/dp/B000000001','--jurisdictions','US',
                  '--enable-serpapi-free','--output-dir',other.run)
        other.preflight()
        capture=other.capture(); capture_data=load_json(capture)
        capture_data['visible_ip_claims']=['Magnetic lock']
        atomic_write_json(capture,capture_data)
        other.cli('record_browser_product.py','--task-dir',other.run,'--capture',capture)
        from runtime_v24 import preflight_evidence
        self.assertEqual(preflight_evidence(other.run),'collecting')
        task=load_json(other.run/'task.json'); task['product_scope_required']=True
        atomic_write_json(other.run/'task.json',task)
        ev=task['product_identity']['evidence_id']
        scope={'schema_version':'product-scope-input-v2','expected_scope_sha256':'',
            'query_terms':[{'kind':'design','value':'folding stand','language':'en','derived_from':'product.title'}],
            'sources':[{'source_id':'permission','kind':'user_statement','text':'Allow this Amazon main image URL for SerpApi image discovery.'}],
            'scope':{'status':'reviewed','reviewer':'offline-agent','reasoning':'Permission is limited to one provider and purpose.',
                'delivery_revision':'image-fact-v1','objects':[],
                'facts':[{'fact_id':'title','version':1,'source_path':'product.title','value':'Folding stand',
                    'status':'confirmed','nature':'direct_observation','verification':'verified',
                    'applies_to':{'product_id':task['product']['product_id']},'source_refs':[ev],
                    'reason':'Current target page title.'},
                    {'fact_id':'magnetic-claim','version':1,'source_path':'product.visible_ip_claims[0]',
                    'value':'Magnetic lock','status':'confirmed','nature':'page_claim','verification':'claim_only',
                    'applies_to':{'product_id':task['product']['product_id']},'source_refs':[ev],
                    'reason':'The page states this; internal construction is unverified.'}],
                'directions':[{'direction_id':'outline','scenario_id':'product_entry','right_type':'design',
                    'fact_ids':['title'],'object_ids':[],'reason':'Target identity and shape.'}],
                'image_permissions':[{'provider':'serpapi_google_lens','purpose':'image_discovery','status':'allowed',
                    'source_refs':['permission'],'reason':'User specified this receiver and purpose.'}]}}
        file=other.root/'permission-scope.json';atomic_write_json(file,scope)
        record_scope(other.run,file);task=load_json(other.run/'task.json')
        self.assertEqual(task['product_scope']['facts'][1]['verification'],'claim_only')
        image=selected_public_image(task)
        self.assertEqual(image['image_id'],'IMG-001')
        row={'image_url':image['source_url'],**query_row_binding(task,image)}
        self.assertIsNone(validate_image_query(task,'serpapi_google_lens',row))
        self.assertIsNone(selected_public_image(task,provider='other_provider'))
        plan=generate_plan(other.run)
        lens=plan['queries'].get('serpapi_google_lens',[])
        if not lens:
            # Offline optional provider credentials are absent; add a normal
            # planner-built row to verify the real submission boundary.
            from api_first_planning import make_row
            term=next(t for t in term_records(task) if t['derived_from']=='product.title')
            image_term={**term,'discovery_channel':'image','image_url':image['source_url']}
            lens=[make_row(task,'serpapi_google_lens',image_term,'US','design',[])]
            plan['queries']['serpapi_google_lens']=lens
            atomic_write_json(other.run/'search-plan.json',plan)
        self.assertEqual(lens[0]['query_image_id'],'IMG-001')
        scope['expected_scope_sha256']=task['product_scope']['scope_sha256']
        scope['scope']['image_permissions'][0]['status']='not_allowed'
        atomic_write_json(file,scope);record_scope(other.run,file)
        task=load_json(other.run/'task.json')
        self.assertEqual(validate_image_query(task,'serpapi_google_lens',row),
                         'QUERY_IMAGE_INPUT_OR_PERMISSION_UNAVAILABLE')
        from runtime_v24 import execute_api_plan
        before=(other.run/'evidence.json').read_bytes()
        with patch('subprocess.run',side_effect=AssertionError('Provider must not run')):
            result=execute_api_plan(other.run,query_ids_filter=[lens[0]['query_id']],include_optional=True,phase='discovery')
        self.assertEqual(result['results'][0]['dispatch'],'deferred')
        self.assertEqual(result['results'][0]['submission_state'],'not_submitted')
        self.assertEqual(before,(other.run/'evidence.json').read_bytes())


if __name__=='__main__': unittest.main()

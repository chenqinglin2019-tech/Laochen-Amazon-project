"""02B retained change, impact and applicability contracts; offline fixtures."""
from copy import deepcopy
import unittest

from common import atomic_write_json, load_json
from product_change import assessment_gate, dispatch_reason, verify
from record_product_applicability import record as record_applicability
from record_product_image import record as record_image
from record_user_product import record as record_user_product
from record_product_scope import record as record_scope
from workflow_v24 import generate_plan
import test_product_delivery as delivery_fixture
import test_product_entry as entry_fixture


class ProductChangeTests(unittest.TestCase):
    def setUp(self):
        self.f=delivery_fixture.ProductDeliveryTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.run=self.f.run

    def test_fact_withdrawal_maps_query_candidate_and_requires_applicability(self):
        self.f.save(); plan=generate_plan(self.run)
        query=next(row for rows in plan['queries'].values() for row in rows
                   if 'product.structure[0]' in row.get('derived_from',[]))
        evidence=load_json(self.run/'evidence.json')
        evidence['source_runs'].append({'run_id':'SRC-change-fixture','query_id':query['query_id'],
            'provider':'fixture','status':'success'})
        evidence['source_runs'].append({'run_id':'SRC-other-fixture','query_id':'QRY-other',
            'provider':'fixture','status':'success'})
        atomic_write_json(self.run/'evidence.json',evidence)
        task=load_json(self.run/'task.json')
        atomic_write_json(self.run/'normalized-candidates.json',{'schema_version':'2.4-free','task_id':task['task_id'],
            'patents':[{'candidate_id':'CAND-change','jurisdiction':'US','right_type':'patent',
                'sources':[{'source_run_id':'SRC-change-fixture'}],
                'evidence_refs':[task['product_identity']['evidence_id']]},
                {'candidate_id':'CAND-indirect','jurisdiction':'US','right_type':'patent',
                 'sources':[{'source_run_id':'SRC-other-fixture'}],
                 'evidence_refs':[task['product_identity']['evidence_id']]},
                {'candidate_id':'CAND-unrelated','jurisdiction':'US','right_type':'design',
                 'sources':[{'source_run_id':'SRC-other-fixture'}],
                 'evidence_refs':[task['product_identity']['evidence_id']]}],
            'trademarks':[],'copyright_assets':[],'enforcement':[]})
        self.f.payload['expected_scope_sha256']=task['product_scope']['scope_sha256']
        fact=self.f.payload['scope']['facts'][1]
        fact.update(version=2,status='unknown',verification='unverified',
                    question='Which mechanism is actually present?',
                    reason='Earlier user description has been withdrawn pending a new view.')
        self.f.save(); task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        event=task['product_change_history'][-1]
        self.assertEqual(event['kind'],'fact_withdrawal')
        self.assertIn(query['query_id'],event['affected_query_ids'])
        self.assertEqual(event['affected_candidate_ids'],['CAND-change','CAND-indirect'])
        self.assertEqual(event['expanded_candidate_ids'],['CAND-indirect'])
        self.assertEqual(event['fact_changes'][0]['before']['version'],1)
        self.assertEqual(event['fact_changes'][0]['after']['version'],2)
        with self.assertRaisesRegex(ValueError,'APPLICABILITY_REVIEW_REQUIRED'):
            assessment_gate(task,evidence,[])
        payload={'schema_version':'product-applicability-v1','product_version':task['product_change_version'],
            'target_sha256':task['product_identity']['sha256'],
            'scope_sha256':task['product_scope']['scope_sha256'],
            'reviews':[{'change_id':event['change_id'],'candidate_id':'CAND-change','status':'usable',
                'reviewer':'offline-agent','reason':'The retained candidate concerns the same product category; its old query claim is not treated as a verified mechanism.',
                'source_refs':[task['product_identity']['evidence_id']]},
                {'change_id':event['change_id'],'candidate_id':'CAND-indirect','status':'usable',
                'reviewer':'offline-agent','reason':'Comparison impact checked within the same patent scope.',
                'source_refs':[task['product_identity']['evidence_id']]}]}
        path=self.f.f.root/'applicability.json'; atomic_write_json(path,payload)
        self.assertEqual(record_applicability(self.run,path),'success')
        task=load_json(self.run/'task.json'); assessment_gate(task,evidence,[])
        self.assertEqual(record_applicability(self.run,path),'success')
        payload['reviews'][0]['reason']='Changed silently'; atomic_write_json(path,payload)
        with self.assertRaisesRegex(ValueError,'IMMUTABLE'): record_applicability(self.run,path)
        task['product_change_history'][0]['reason']='tampered'; atomic_write_json(self.run/'task.json',task)
        with self.assertRaisesRegex(ValueError,'EVENT_CHANGED'): verify(task,evidence,self.run)

    def test_explicit_amazon_target_change_keeps_prior_capture_and_requires_new_scope(self):
        other=entry_fixture.ProductEntryTests(); other.setUp(); self.addCleanup(other.doCleanups)
        other.create(amazon=True,country=None); other.preflight()
        first=other.capture(); other.cli('record_browser_product.py','--task-dir',other.run,'--capture',first)
        before=load_json(other.run/'task.json')
        new_url='https://www.amazon.com/dp/B000000003'
        review={'kind':'target_change','expected_target_sha256':before['product_identity']['sha256'],
                'actual_asin':'B000000003','variant':{'label':'Selected option','value':'White','confirmed':True},
                'new_url':new_url,'reason':'Seller explicitly changed the target from black to white.',
                'user_statement':'Use the white child as the target instead of the black child.'}
        review_path=other.root/'change-review.json'; atomic_write_json(review_path,review)
        second=other.capture('B000000003','White')
        capture=load_json(second); capture['requested_url']=new_url; capture['final_url']=new_url
        atomic_write_json(second,capture)
        other.cli('record_browser_product.py','--task-dir',other.run,'--capture',second,
                  '--change-review',review_path)
        task=load_json(other.run/'task.json'); evidence=load_json(other.run/'evidence.json')
        self.assertNotEqual(task['product_identity']['sha256'],before['product_identity']['sha256'])
        self.assertTrue(task['product_change_pending'])
        self.assertEqual(task['request']['url'],new_url)
        self.assertEqual(len(evidence['collections']['product']),2)
        self.assertEqual(dispatch_reason(task,{'query_id':'old-row'}),'PRODUCT_TARGET_CHANGE_REVIEW_REQUIRED')
        verify(task,evidence,other.run)
        ev=task['product_identity']['evidence_id']
        scope={'schema_version':'product-scope-input-v2','expected_scope_sha256':'','sources':[],
            'scope':{'status':'reviewed','reviewer':'offline-agent','reasoning':'New white target reviewed separately.',
                'delivery_revision':'image-fact-v1','image_permissions':[],'objects':[],
                'facts':[{'fact_id':'title','version':1,'source_path':'product.title','value':'Folding stand',
                    'status':'confirmed','nature':'direct_observation','verification':'verified',
                    'applies_to':{'product_id':task['product']['product_id']},'source_refs':[ev],
                    'reason':'Current target page title.'}],
                'directions':[{'direction_id':'outline','scenario_id':'product_entry','right_type':'design',
                    'fact_ids':['title'],'object_ids':[],'reason':'Current shape.'}]},
            'query_terms':[{'kind':'design','value':'folding stand','language':'en','derived_from':'product.title'}]}
        path=other.root/'new-scope.json'; atomic_write_json(path,scope)
        self.assertEqual(record_scope(other.run,path),'success')
        task=load_json(other.run/'task.json')
        self.assertFalse(task['product_change_pending'])
        self.assertEqual(task['product_scope']['facts'][0]['applies_to']['product_id'],task['product']['product_id'])
        from runtime_v24 import preflight_evidence
        self.assertEqual(preflight_evidence(other.run),'collecting')
        plan=generate_plan(other.run)
        new_rows=[row for rows in plan['queries'].values() for row in rows]
        self.assertTrue(new_rows)
        self.assertTrue(all(row.get('product_target_sha256')==task['product_identity']['sha256']
                            for row in new_rows if row.get('decision_workflow_revision')))

    def test_recompression_retains_original_and_does_not_reopen_queries(self):
        self.f.save(); before=load_json(self.run/'task.json')
        image=self.f.f.root/'compressed.png'; image.write_bytes(entry_fixture.PNG+b'lossless-fixture')
        payload={'schema_version':'product-image-change-v1','relation':'recompression',
            'original_image_id':'IMG-002','expected_target_sha256':before['product_identity']['sha256'],
            'expected_scope_sha256':before['product_scope']['scope_sha256'],'path':str(image),
            'review':{'reviewer':'offline-agent','reason':'Pixel content and object references are unchanged.',
                      'content_effect':'same_content'}}
        path=self.f.f.root/'image-change.json'; atomic_write_json(path,payload)
        self.assertEqual(record_image(self.run,path),'success')
        self.assertEqual(record_image(self.run,path),'success')
        self.assertEqual(load_json(self.run/'task.json'),before)
        ledger=load_json(self.run/'image-relationships.json')
        self.assertEqual(len(ledger['items']),1)
        self.assertEqual(ledger['items'][0]['original_image_id'],'IMG-002')
        self.assertNotEqual(ledger['items'][0]['sha256'],before['images'][1]['sha256'])
        evidence=load_json(self.run/'evidence.json')
        verify(before,evidence,self.run)
        ledger['items'][0]['reason']='silently changed'
        atomic_write_json(self.run/'image-relationships.json',ledger)
        with self.assertRaises(ValueError): verify(before,evidence,self.run)

    def test_supplemental_view_requires_affected_scope_update(self):
        self.f.save(); before=load_json(self.run/'task.json')
        image=self.f.f.root/'new-view.png'; image.write_bytes(entry_fixture.PNG+b'new-view-fixture')
        payload={'schema_version':'product-image-change-v1','relation':'additional_view',
            'original_image_id':'IMG-002','expected_target_sha256':before['product_identity']['sha256'],
            'expected_scope_sha256':before['product_scope']['scope_sha256'],'path':str(image),
            'affected_fact_ids':[],'affected_object_ids':['back-pattern'],
            'review':{'reviewer':'offline-agent','reason':'A closer rear view may change pattern coverage.',
                      'content_effect':'new_information'}}
        path=self.f.f.root/'new-view.json'; atomic_write_json(path,payload)
        self.assertEqual(record_image(self.run,path),'success')
        task=load_json(self.run/'task.json'); event=task['product_change_history'][-1]
        self.assertTrue(task['product_change_pending'])
        self.assertEqual(event['affected_direction_ids'],['pattern'])
        self.assertEqual(dispatch_reason(task,{'query_id':'old-row'}),'PRODUCT_TARGET_CHANGE_REVIEW_REQUIRED')
        self.f.payload['expected_scope_sha256']=task['product_scope']['scope_sha256']
        with self.assertRaisesRegex(ValueError,'SUPPLEMENT_SCOPE_BINDING_REQUIRED'): self.f.save()
        self.f.payload['scope']['objects'][0]['visual_evidence']['image_ids'].append(event['image_id'])
        self.f.save(); task=load_json(self.run/'task.json')
        self.assertFalse(task['product_change_pending'])
        self.assertIn(event['image_id'],task['product_scope']['objects'][0]['visual_evidence']['image_ids'])

    def test_user_material_target_replacement_keeps_prior_snapshot(self):
        self.f.save(); old=load_json(self.run/'task.json')
        old_plan=generate_plan(self.run)
        old_query_ids={row['query_id'] for rows in old_plan['queries'].values() for row in rows}
        materials=deepcopy(self.f.f.data)
        materials['product']['title']='Revised folding stand'
        new_input=self.f.f.root/'new-product.json'; atomic_write_json(new_input,materials)
        review={'kind':'target_change','expected_target_sha256':old['product_identity']['sha256'],
                'reason':'Seller changed the item to a revised stand.',
                'user_statement':'The revised folding stand is now the target.'}
        review_path=self.f.f.root/'user-change-review.json'; atomic_write_json(review_path,review)
        self.assertEqual(record_user_product(self.run,product_input=new_input,change_review_path=review_path),'success')
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        self.assertNotEqual(task['product']['product_id'],old['product']['product_id'])
        self.assertEqual(task['product']['title'],'Revised folding stand')
        self.assertTrue(task['product_change_pending'])
        self.assertEqual(len(evidence['collections']['product']),2)
        self.assertEqual(len(task['product_change_history']),1)
        verify(task,evidence,self.run)
        self.f.payload['expected_scope_sha256']=''
        self.f.payload['scope']['reasoning']='New product version reviewed against retained inputs.'
        new_ev=task['product_identity']['evidence_id']
        for row in self.f.payload['scope']['facts']+self.f.payload['scope']['objects']:
            row['source_refs']=[new_ev]
            if 'applies_to' in row: row['applies_to']['product_id']=task['product']['product_id']
        self.f.save()
        task=load_json(self.run/'task.json')
        self.assertFalse(task['product_change_pending'])
        plan=generate_plan(self.run,expand=True)
        all_rows=[row for rows in plan['queries'].values() for row in rows]
        self.assertTrue(old_query_ids <= {row['query_id'] for row in all_rows})
        self.assertTrue(any(row.get('product_target_sha256')==task['product_identity']['sha256']
                            and row['query_id'] not in old_query_ids for row in all_rows))
        self.assertEqual(dispatch_reason(task,{'query_id':next(iter(old_query_ids))}),
                         'PRODUCT_CHANGE_QUERY_REVIEW_REQUIRED')


if __name__=='__main__': unittest.main()

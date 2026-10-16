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


class AdditiveScopeChangeTests(unittest.TestCase):
    """best-estimate-risk-v2: an added direction/right type reopens nothing and records applicability itself."""

    def setUp(self):
        self.f=delivery_fixture.ProductDeliveryTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.run=self.f.run

    def additive_save(self, marker):
        self.f.save(); generate_plan(self.run)
        task=load_json(self.run/'task.json')
        task['assessment_revision']='known-findings-risk-v1'; task['best_estimate_revision']=marker
        atomic_write_json(self.run/'task.json',task)
        ref=task['product_identity']['evidence_id']
        atomic_write_json(self.run/'normalized-candidates.json',{'schema_version':'2.4-free','task_id':task['task_id'],
            'patents':[{'candidate_id':'CAND-pat','jurisdiction':'US','right_type':'patent','sources':[],'evidence_refs':[ref]}],
            'trademarks':[],'copyright_assets':[],
            'enforcement':[{'candidate_id':'CAND-web','jurisdiction':'US','right_type':'unknown','sources':[],'evidence_refs':[ref]}]})
        self.f.payload['expected_scope_sha256']=task['product_scope']['scope_sha256']
        scope=self.f.payload['scope']
        product=scope['objects'][0]
        product['right_types']=sorted(set(product['right_types'])|{'enforcement'})
        base=scope['directions'][-1]
        scope['directions'].append({**deepcopy(base),'direction_id':'DIR-enforcement-added','right_type':'enforcement',
                                    'object_ids':[product['object_id']],'reason':'Public enforcement signals for the product.'})
        self.f.save()
        return load_json(self.run/'task.json'), load_json(self.run/'evidence.json')

    def test_additive_change_reopens_no_query_and_records_usable_applicability(self):
        task,evidence=self.additive_save('best-estimate-risk-v2')
        event=task['product_change_history'][-1]
        self.assertTrue(event['additive'])
        self.assertEqual(event['affected_query_ids'],[])
        self.assertEqual(event['affected_candidate_ids'],['CAND-web'])
        rows=task['product_applicability_reviews']
        self.assertEqual([(r['candidate_id'],r['status'],r['reviewer']) for r in rows],
                         [('CAND-web','usable','program:additive_scope_change')])
        verify(task,evidence,self.run)
        assessment_gate(task,evidence,[])        # nothing left for an Agent to review

    def test_v1_task_keeps_the_round_6_impact(self):
        task,evidence=self.additive_save('best-estimate-risk-v1')
        event=task['product_change_history'][-1]
        self.assertNotIn('additive',event)
        self.assertFalse(task.get('product_applicability_reviews'))

    def test_additive_delta_predicate(self):
        from product_change import additive_delta
        obj={'object_id':'O','kind':'product','relation':'target','right_types':['patent'],'description':'d'}
        old={'facts':[],'objects':[obj],'directions':[{'direction_id':'D1','scenario_id':'s','right_type':'patent','fact_ids':[],'object_ids':['O']}]}
        grown={**old,'objects':[{**obj,'right_types':['patent','enforcement']}],
               'directions':old['directions']+[{'direction_id':'D2','scenario_id':'s','right_type':'enforcement','fact_ids':[],'object_ids':['O']}]}
        self.assertTrue(additive_delta(old,grown))
        self.assertFalse(additive_delta(old,{**grown,'objects':[{**obj,'description':'changed','right_types':['patent','enforcement']}]}))
        self.assertFalse(additive_delta(old,{**old,'objects':[{**obj,'right_types':[]}]}))
        self.assertFalse(additive_delta(old,old))


class RebaseProgressTests(unittest.TestCase):
    """best-estimate-risk-v2: stale version items after an additive change are re-planned/retired by the program."""

    def test_unsubmitted_query_is_replanned_and_covered_items_removed(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import product_change
        root = Path(tempfile.mkdtemp()); self.addCleanup(__import__('shutil').rmtree, root, True)
        task = {'task_id': 'T', 'assessment_revision': 'known-findings-risk-v1', 'best_estimate_revision': 'best-estimate-risk-v2',
                'product_change_revision': 'product-change-v1', 'product_change_version': 2,
                'product_change_history': [{'change_id': 'CHG-1', 'version': 2, 'additive': True}]}
        atomic_write_json(root / 'task.json', task)
        atomic_write_json(root / 'evidence.json', {'task_id': 'T', 'review_progress_events': [{'kind': 'initialize'}],
            'source_runs': [{'query_id': 'Q-done', 'submission_state': 'submitted'},
                            {'query_id': 'Q-old', 'submission_state': 'submitted'}]})
        scope = lambda right, version: {'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': right,
                                        'product_version': version}
        items = [{'item_id': 'ITEM-a', 'kind': 'query', 'query_id': 'Q-new', 'state': 'planned', 'scope': scope('design', '1'),
                  'module_ids': ['appearance_patent'], 'acceptance_condition': 'c'},
                 {'item_id': 'ITEM-b', 'kind': 'query', 'query_id': 'Q-done', 'state': 'completed', 'scope': scope('patent', '1'),
                  'module_ids': ['utility_patent'], 'acceptance_condition': 'c'},
                 {'item_id': 'ITEM-c', 'kind': 'query', 'query_id': 'Q-cur', 'state': 'planned', 'scope': scope('patent', '2'),
                  'module_ids': ['utility_patent'], 'acceptance_condition': 'c'},
                 {'item_id': 'ITEM-d', 'kind': 'query', 'query_id': 'Q-old', 'state': 'completed', 'scope': scope('copyright', '1'),
                  'module_ids': ['copyright_ip'], 'acceptance_condition': 'c'}]
        calls = []
        with patch('review_progress_stage_a.ledger', return_value={'items': items}), \
                patch('review_progress_stage_a.record_event', side_effect=lambda d, r: calls.append(r)):
            result = product_change.rebase_progress(root)
        self.assertEqual([c['kind'] for c in calls], ['add', 'remove', 'remove'])
        self.assertEqual(calls[0]['items'][0]['query_id'], 'Q-new')
        self.assertEqual(calls[0]['items'][0]['scope']['product_version'], '2')
        self.assertEqual(sorted(result['removed']), ['ITEM-a', 'ITEM-b'])
        self.assertEqual(result['left'], ['ITEM-d'])           # submitted, nothing covers it: left for the Agent
        self.assertTrue(all(c['actor'] == 'program:additive_scope_change' for c in calls))

    def test_non_additive_change_is_left_alone(self):
        import tempfile
        from pathlib import Path
        import product_change
        root = Path(tempfile.mkdtemp()); self.addCleanup(__import__('shutil').rmtree, root, True)
        atomic_write_json(root / 'task.json', {'task_id': 'T', 'assessment_revision': 'known-findings-risk-v1',
            'best_estimate_revision': 'best-estimate-risk-v2', 'product_change_revision': 'product-change-v1',
            'product_change_version': 2, 'product_change_history': [{'change_id': 'CHG-1', 'version': 2}]})
        self.assertEqual(product_change.rebase_progress(root)['reason'], 'LATEST_CHANGE_NOT_ADDITIVE')

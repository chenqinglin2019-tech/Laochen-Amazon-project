"""02C minimum-fact request, scope update and targeted comparison closure."""
import unittest

from common import atomic_write_json, load_json
from product_change import assessment_gate as change_assessment_gate
from product_feedback import assessment_gate, pending, verify
from product_scope import direction_state, work_entries
from record_product_applicability import record as record_applicability
from record_product_feedback import record as record_feedback
from workflow_v24 import generate_plan
from assessment_estimate import review_digest
import test_product_delivery as delivery_fixture


class ProductFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = delivery_fixture.ProductDeliveryTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.run = self.fixture.run
        self.fixture.save()
        self.plan = generate_plan(self.run)
        task = load_json(self.run/'task.json')
        self.source_id = task['product_identity']['evidence_id']
        self.candidates = {'schema_version':'2.4-free','task_id':task['task_id'],
            'patents':[{'candidate_id':'CAND-feedback','jurisdiction':'US','right_type':'patent',
                        'sources':[],'evidence_refs':[self.source_id]}],
            'trademarks':[],'copyright_assets':[],'enforcement':[]}
        atomic_write_json(self.run/'normalized-candidates.json',self.candidates)
        self.request = {'schema_version':'product-feedback-v1','action':'request',
            'stage':'candidate_comparison','expected_target_sha256':task['product_identity']['sha256'],
            'expected_scope_sha256':task['product_scope']['scope_sha256'],
            'direction_id':'claim-search','fact_id':'hinge-claim','candidate_id':'CAND-feedback',
            'jurisdiction':'US','purpose':'Compare whether the retained patent claim covers the actual lock mechanism.',
            'minimum_information':'One clear view or technical document showing the internal lock mechanism.',
            'question':'Does the sold stand use a magnet or a mechanical latch?',
            'reason':'The earlier description says hinged support but does not identify the lock.',
            'requester':'comparison-reviewer','source_refs':[self.source_id]}
        self.path = self.fixture.f.root/'feedback.json'

    def save_request(self):
        atomic_write_json(self.path,self.request)
        return record_feedback(self.run,self.path)

    def test_comparison_feedback_closes_only_after_revised_fact_and_applicability(self):
        task_before=load_json(self.run/'task.json')
        evidence_before=load_json(self.run/'evidence.json')
        digest_before=review_digest(evidence_before,self.candidates,{},self.plan,task_before)
        self.assertEqual(self.save_request(),'success')
        self.assertEqual(self.save_request(),'success')
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        request=pending(task)[0]
        self.assertEqual(len(pending(task)),1)
        self.assertTrue(any(gap.get('kind')=='downstream_fact_feedback'
                            and gap.get('fact_id')=='hinge-claim'
                            for gap in task['product_delivery']['gaps_and_conflicts']))
        self.assertNotEqual(digest_before,review_digest(evidence,self.candidates,{},self.plan,task))
        entry=next(row for row in work_entries(task) if row.get('reason')=='PRODUCT_FACT_FEEDBACK_PENDING')
        self.assertEqual((entry['candidate_id'],entry['jurisdiction'],entry['direction_id']),
                         ('CAND-feedback','US','claim-search'))
        self.assertEqual(entry['minimum_information'],self.request['minimum_information'])
        self.assertEqual(direction_state(task,next(row for row in task['product_scope']['directions']
                                              if row['direction_id']=='shape')),'ready')
        assessment_gate(task,[{'candidate_id':'CAND-unrelated','risk':'中'}])
        with self.assertRaisesRegex(ValueError,'COMPARISON_PENDING'):
            assessment_gate(task,[{'candidate_id':'CAND-feedback','risk':'低'}])
        resolution={'schema_version':'product-feedback-v1','action':'resolve',
            'request_id':request['request_id'],'expected_target_sha256':task['product_identity']['sha256'],
            'expected_scope_sha256':task['product_scope']['scope_sha256'],
            'reviewer':'offline-agent','reason':'The requested lock evidence has been reviewed.',
            'source_refs':[self.source_id]}
        atomic_write_json(self.path,resolution)
        with self.assertRaisesRegex(ValueError,'FACT_NOT_RESOLVED'):
            record_feedback(self.run,self.path)
        # A more precise claim alone remains insufficient for comparison.
        self.fixture.payload['expected_scope_sha256']=task['product_scope']['scope_sha256']
        fact=self.fixture.payload['scope']['facts'][1]
        fact.update(version=2,value='mechanical latch',status='confirmed',
                    nature='direct_observation',verification='verified',
                    reason='A synthetic technical document shows the latch.')
        self.fixture.payload['sources']=[{'source_id':'lock-document','kind':'document',
                                          'text':'Synthetic document: mechanical latch cross-section.'}]
        fact['source_refs']=[self.source_id,'lock-document']
        self.fixture.save()
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        source=next(row['evidence_id'] for row in evidence['collections']['scope_sources']
                    if row.get('text','').startswith('Synthetic document:'))
        resolution.update(expected_scope_sha256=task['product_scope']['scope_sha256'],
                          source_refs=[source])
        atomic_write_json(self.path,resolution)
        self.assertEqual(record_feedback(self.run,self.path),'success')
        self.assertEqual(record_feedback(self.run,self.path),'success')
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        verify(task,evidence,self.run)
        self.assertFalse(pending(task))
        self.assertFalse(any(gap.get('kind')=='downstream_fact_feedback'
                             for gap in task['product_delivery']['gaps_and_conflicts']))
        self.assertFalse(any(row.get('reason')=='PRODUCT_FACT_FEEDBACK_PENDING' for row in work_entries(task)))
        self.assertNotEqual(digest_before,review_digest(evidence,self.candidates,{},self.plan,task))
        event=task['product_change_history'][-1]
        self.assertIn('CAND-feedback',event['affected_candidate_ids'])
        with self.assertRaisesRegex(ValueError,'APPLICABILITY_REVIEW_REQUIRED'):
            change_assessment_gate(task,evidence,[])
        review={'schema_version':'product-applicability-v1','product_version':task['product_change_version'],
            'target_sha256':task['product_identity']['sha256'],
            'scope_sha256':task['product_scope']['scope_sha256'],
            'reviews':[{'change_id':event['change_id'],'candidate_id':'CAND-feedback',
                'status':'usable','reviewer':'offline-agent',
                'reason':'The old candidate remains relevant; comparison must use the newly verified latch fact.',
                'source_refs':[source]}]}
        atomic_write_json(self.path,review)
        self.assertEqual(record_applicability(self.run,self.path),'success')
        task=load_json(self.run/'task.json')
        change_assessment_gate(task,load_json(self.run/'evidence.json'),[])

    def test_request_rejects_wrong_candidate_and_retained_receipt_tampering(self):
        bad=dict(self.request,candidate_id='CAND-nonexistent')
        atomic_write_json(self.path,bad)
        with self.assertRaisesRegex(ValueError,'CANDIDATE_MISMATCH'):
            record_feedback(self.run,self.path)
        self.assertNotIn('product_feedback_history',load_json(self.run/'task.json'))
        self.save_request()
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        row=task['product_feedback_history'][0]
        row['question']='silently changed'
        with self.assertRaisesRegex(ValueError,'EVENT_INVALID'):
            verify(task,evidence,self.run)

    def test_search_planning_feedback_uses_same_fact_without_candidate(self):
        request=dict(self.request,stage='search_planning',purpose='Choose a precise structural search term.')
        request.pop('candidate_id')
        atomic_write_json(self.path,request)
        self.assertEqual(record_feedback(self.run,self.path),'success')
        task=load_json(self.run/'task.json')
        work=next(row for row in work_entries(task) if row.get('reason')=='PRODUCT_FACT_FEEDBACK_PENDING')
        self.assertIsNone(work['candidate_id'])
        self.assertEqual(work['purpose'],request['purpose'])
        self.assertEqual(work['jurisdiction'],'US')
        assessment_gate(task,[{'candidate_id':'CAND-feedback','risk':'中'}])
        self.fixture.payload['expected_scope_sha256']=task['product_scope']['scope_sha256']
        fact=self.fixture.payload['scope']['facts'][1]
        fact.update(version=2,value='hinged support with button release',
                    reason='A synthetic product description adds button release.',
                    verification='claim_only')
        self.fixture.payload['sources']=[{'source_id':'new-description','kind':'document',
                                          'text':'Synthetic description: button release.'}]
        fact['source_refs']=[self.source_id,'new-description']
        self.fixture.save()
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        source=next(row['evidence_id'] for row in evidence['collections']['scope_sources']
                    if row.get('text','').startswith('Synthetic description:'))
        resolution={'schema_version':'product-feedback-v1','action':'resolve',
            'request_id':pending(task)[0]['request_id'],
            'expected_target_sha256':task['product_identity']['sha256'],
            'expected_scope_sha256':task['product_scope']['scope_sha256'],
            'reviewer':'offline-agent','reason':'The extra phrase is a scoped search lead only.',
            'source_refs':[source]}
        atomic_write_json(self.path,resolution)
        self.assertEqual(record_feedback(self.run,self.path),'success')
        self.assertFalse(pending(load_json(self.run/'task.json')))

    def test_comparison_feedback_rejects_new_unverified_claim(self):
        self.save_request()
        task=load_json(self.run/'task.json')
        request_id=pending(task)[0]['request_id']
        self.fixture.payload['expected_scope_sha256']=task['product_scope']['scope_sha256']
        fact=self.fixture.payload['scope']['facts'][1]
        fact.update(version=2,value='button-release latch',status='confirmed',
                    verification='claim_only',reason='A synthetic seller statement names the latch.')
        self.fixture.payload['sources']=[{'source_id':'seller-statement','kind':'document',
                                          'text':'Synthetic seller statement: button-release latch.'}]
        fact['source_refs']=[self.source_id,'seller-statement']
        self.fixture.save()
        task=load_json(self.run/'task.json'); evidence=load_json(self.run/'evidence.json')
        source=next(row['evidence_id'] for row in evidence['collections']['scope_sources']
                    if row.get('text','').startswith('Synthetic seller statement:'))
        resolution={'schema_version':'product-feedback-v1','action':'resolve',
            'request_id':request_id,'expected_target_sha256':task['product_identity']['sha256'],
            'expected_scope_sha256':task['product_scope']['scope_sha256'],
            'reviewer':'offline-agent','reason':'The seller gave a description.',
            'source_refs':[source]}
        atomic_write_json(self.path,resolution)
        with self.assertRaisesRegex(ValueError,'FACT_NOT_RESOLVED'):
            record_feedback(self.run,self.path)
        self.assertEqual(pending(load_json(self.run/'task.json'))[0]['request_id'],request_id)


if __name__=='__main__': unittest.main()

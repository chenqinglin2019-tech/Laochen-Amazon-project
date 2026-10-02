"""02C minimum-fact request, scope update and targeted comparison closure."""
import unittest

from common import atomic_write_json, load_json
from product_change import assessment_gate as change_assessment_gate
from product_feedback import (assessment_gate, pending, verify, outstanding, unavailable,
    STRUCTURE_POLICY, structure_limit_valid)
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

    def enable_structure_policy(self):
        task = load_json(self.run/'task.json')
        task['product_structure_policy'] = STRUCTURE_POLICY
        from product_delivery import project
        task['product_delivery'] = project(task)
        atomic_write_json(self.run/'task.json', task)
        return task

    def test_adopt_structure_policy_refreshes_projection_without_changing_archived_facts(self):
        self.save_request()
        before_task = load_json(self.run/'task.json')
        before_evidence = (self.run/'evidence.json').read_bytes()
        request = {'action': 'adopt_structure_policy', 'reviewer': 'user-authorized-agent',
                   'reason': 'User explicitly requested no structure questions'}
        atomic_write_json(self.path, request)
        self.assertEqual(record_feedback(self.run, self.path), 'success')
        task = load_json(self.run/'task.json')
        evidence = load_json(self.run/'evidence.json')
        from product_scope import verify as verify_scope
        verify_scope(task, evidence, self.run)
        self.assertEqual(task['product_scope'], before_task['product_scope'])
        self.assertEqual(task['product_feedback_history'], before_task['product_feedback_history'])
        self.assertEqual((self.run/'evidence.json').read_bytes(), before_evidence)
        self.assertFalse(pending(task))
        self.assertEqual(len(unavailable(task)), 1)
        self.assertEqual(task['workflow_policy_updates'][-1]['reason'], request['reason'])

    def test_structure_request_records_unavailable_without_user_question(self):
        before = self.enable_structure_policy()['product_scope']['facts'][1].copy()
        self.assertEqual(self.save_request(), 'success')
        self.assertEqual(self.save_request(), 'success')
        task = load_json(self.run/'task.json'); evidence = load_json(self.run/'evidence.json')
        verify(task, evidence, self.run)
        self.assertFalse(pending(task))
        self.assertEqual(outstanding(task)[0]['kind'], 'unavailable')
        self.assertEqual(len(unavailable(task)), 1)
        row = next(row for row in work_entries(task) if row.get('candidate_id') == 'CAND-feedback')
        self.assertEqual((row['state'], row['reason'], row['question']),
                         ('blocked', 'PRODUCT_STRUCTURE_UNAVAILABLE', ''))
        self.assertTrue(structure_limit_valid(row, task, evidence, self.run))
        from necessary_completion import _delivery_limit_valid
        self.assertTrue(_delivery_limit_valid(row, task, evidence, self.plan, {}, task_dir=self.run))
        row['delivery_limit']['fact_sha256']['hinge-claim'] = 'forged'
        self.assertFalse(structure_limit_valid(row, task, evidence, self.run))
        self.assertEqual(task['product_scope']['facts'][1], before)
        self.assertEqual(before['nature'], 'user_statement')
        self.assertEqual(before['verification'], 'claim_only')
        with self.assertRaisesRegex(ValueError, 'COMPARISON_PENDING'):
            assessment_gate(task, [{'candidate_id':'CAND-feedback', 'risk':'低'}])

    def test_historical_request_becomes_unavailable_without_rewriting_receipt(self):
        self.save_request()
        prior = load_json(self.run/'task.json')['product_feedback_history']
        task = self.enable_structure_policy()
        self.assertEqual(task['product_feedback_history'], prior)
        self.assertFalse(pending(task))
        self.assertEqual(unavailable(task)[0]['kind'], 'requested')
        self.assertFalse(any(row['state'] == 'awaiting_user' and row.get('candidate_id') == 'CAND-feedback'
                             for row in work_entries(task)))
        verify(task, load_json(self.run/'evidence.json'), self.run)

    def test_missing_structure_fact_is_unknown_and_no_user_work(self):
        self.enable_structure_policy()
        task = load_json(self.run/'task.json')
        self.fixture.payload['expected_scope_sha256'] = task['product_scope']['scope_sha256']
        fact = self.fixture.payload['scope']['facts'][1]
        fact.update(version=2, status='unknown', verification='unverified', question='What is inside?')
        self.fixture.save()
        task = load_json(self.run/'task.json'); evidence = load_json(self.run/'evidence.json')
        row = next(row for row in work_entries(task) if row.get('direction_id') == 'claim-search')
        self.assertEqual((row['state'], row['question']), ('blocked', ''))
        self.assertTrue(structure_limit_valid(row, task, evidence, self.run))
        self.assertEqual(task['product_scope']['facts'][1]['status'], 'unknown')
        gap = next(row for row in task['product_delivery']['gaps_and_conflicts'] if row.get('fact_id') == 'hinge-claim')
        self.assertEqual((gap['question'], gap['judgment']), ('', '无法判定'))
        # The unknown term still cannot be dispatched as a confirmed fact.
        self.assertNotEqual(direction_state(task, task['product_scope']['directions'][1]), 'ready')

    def test_spontaneous_structure_claim_stays_unverified_then_verified_fact_can_resolve(self):
        self.enable_structure_policy()
        self.save_request()
        task = load_json(self.run/'task.json')
        request_id = outstanding(task)[0]['request_id']
        fact = self.fixture.payload['scope']['facts'][1]
        fact.update(version=2, value='mechanical latch', status='confirmed',
                    nature='user_statement', verification='claim_only', reason='User volunteered a latch statement.')
        self.fixture.payload['expected_scope_sha256'] = task['product_scope']['scope_sha256']
        self.fixture.payload['sources'] = [{'source_id':'new-user', 'kind':'user_statement',
                                           'text':'Synthetic volunteered statement: mechanical latch.'}]
        fact['source_refs'] = [self.source_id, 'new-user']
        self.fixture.save()
        task = load_json(self.run/'task.json'); evidence = load_json(self.run/'evidence.json')
        source = next(row['evidence_id'] for row in evidence['collections']['scope_sources']
                      if row.get('text', '').startswith('Synthetic volunteered'))
        resolution = {'schema_version':'product-feedback-v1', 'action':'resolve',
            'request_id':request_id, 'expected_target_sha256':task['product_identity']['sha256'],
            'expected_scope_sha256':task['product_scope']['scope_sha256'], 'reviewer':'agent',
            'reason':'Review volunteered information.', 'source_refs':[source]}
        atomic_write_json(self.path, resolution)
        with self.assertRaisesRegex(ValueError, 'FACT_NOT_RESOLVED'):
            record_feedback(self.run, self.path)
        self.assertFalse(pending(task)); self.assertTrue(unavailable(task))
        self.assertEqual(task['product_scope']['facts'][1]['verification'], 'claim_only')
        # Separate actual evidence is needed; a statement is never auto-upgraded.
        fact.update(version=3, nature='direct_observation', verification='verified',
                    reason='A retained technical document now shows the actual latch.')
        self.fixture.payload['expected_scope_sha256'] = task['product_scope']['scope_sha256']
        self.fixture.payload['sources'] = [{'source_id':'latch-document', 'kind':'document',
                                           'text':'Synthetic technical section: actual latch.'}]
        fact['source_refs'] = [self.source_id, 'latch-document']
        self.fixture.save()
        task = load_json(self.run/'task.json'); evidence = load_json(self.run/'evidence.json')
        source = next(row['evidence_id'] for row in evidence['collections']['scope_sources']
                      if row.get('text', '').startswith('Synthetic technical section'))
        resolution.update(expected_scope_sha256=task['product_scope']['scope_sha256'], source_refs=[source])
        atomic_write_json(self.path, resolution)
        self.assertEqual(record_feedback(self.run, self.path), 'success')
        task = load_json(self.run/'task.json')
        self.assertFalse(outstanding(task))
        self.assertEqual(task['product_scope']['facts'][1]['verification'], 'verified')

    def test_structural_question_from_material_bullet_is_unavailable(self):
        self.enable_structure_policy()
        task = load_json(self.run/'task.json')
        self.fixture.payload['expected_scope_sha256'] = task['product_scope']['scope_sha256']
        fact = self.fixture.payload['scope']['facts'][1]
        fact.update(version=2, source_path='product.bullets[0]', value='Synthetic PU foam claim',
                    nature='page_claim', verification='claim_only')
        self.fixture.payload['sources'] = [{'source_id':'page-copy','kind':'document',
                                           'text':'Synthetic retained page: PU foam.'}]
        fact['source_refs'] = [self.source_id,'page-copy']
        # This source is deliberately a page bullet rather than product.structure.
        self.fixture.save()
        task = load_json(self.run/'task.json')
        self.request.update(expected_scope_sha256=task['product_scope']['scope_sha256'],
            purpose='比较独立项所需内部构造与回弹事实',
            minimum_information='实物或供应商结构资料：独立包覆层、内部空腔、是否预压缩，以及恢复原形实测秒数',
            question='拟售实物是否有独立柔软外套，内部有无空腔、预压缩，恢复原形约几秒？')
        self.save_request()
        task = load_json(self.run/'task.json'); evidence = load_json(self.run/'evidence.json')
        self.assertFalse(pending(task))
        self.assertEqual(unavailable(task)[0]['structure_classification']['basis'],
                         'legacy_requested_technical_information')
        row = next(row for row in work_entries(task) if row.get('candidate_id') == 'CAND-feedback')
        self.assertEqual((row['state'], row['question']), ('blocked', ''))
        self.assertTrue(structure_limit_valid(row, task, evidence, self.run))

    def test_unknown_structure_fact_from_bullet_uses_category_without_prompt(self):
        self.enable_structure_policy()
        task = load_json(self.run/'task.json')
        self.fixture.payload['expected_scope_sha256'] = task['product_scope']['scope_sha256']
        fact = self.fixture.payload['scope']['facts'][1]
        fact.update(version=2, source_path='product.bullets[0]', value='Synthetic mechanism claim',
                    information_category='actual_structure', status='unknown', verification='unverified',
                    nature='page_claim', question='What is the actual internal structure?')
        self.fixture.payload['sources'] = [{'source_id':'page-copy','kind':'document',
                                           'text':'Synthetic retained page mechanism statement.'}]
        fact['source_refs'] = [self.source_id,'page-copy']
        self.fixture.save()
        task = load_json(self.run/'task.json'); evidence = load_json(self.run/'evidence.json')
        row = next(row for row in work_entries(task) if row.get('direction_id') == 'claim-search')
        self.assertEqual((row['state'], row['question']), ('blocked', ''))
        self.assertTrue(structure_limit_valid(row, task, evidence, self.run))
        self.assertEqual(task['product_scope']['facts'][1]['source_path'], 'product.bullets[0]')
        self.assertEqual(task['product_scope']['facts'][1]['status'], 'unknown')

    def test_explicit_structure_category_does_not_depend_on_source_path_or_language(self):
        self.enable_structure_policy()
        self.request.update(stage='search_planning', direction_id='shape', fact_id='shape',
                            information_category='actual_structure', minimum_information='Section drawing.')
        self.request.pop('candidate_id')
        self.save_request()
        task = load_json(self.run/'task.json')
        self.assertFalse(pending(task))
        self.assertEqual(unavailable(task)[0]['structure_classification'],
                         {'basis':'explicit_information_category', 'category':'actual_structure'})

    def test_historical_authorization_question_is_not_structural_by_source_alone(self):
        self.enable_structure_policy()
        self.request.update(purpose='Check actual authorization.',
                            minimum_information='An existing license grant.', question='Is use licensed?')
        self.save_request()
        task = load_json(self.run/'task.json')
        self.assertEqual(len(pending(task)), 1)
        self.assertFalse(unavailable(task))

    def test_explicit_nonstructural_authorization_is_not_suppressed(self):
        self.enable_structure_policy()
        self.request.update(information_category='other', purpose='Check actual authorization.',
                            minimum_information='An existing license grant.', question='Is use licensed?')
        self.save_request()
        task = load_json(self.run/'task.json')
        self.assertEqual(len(pending(task)), 1)
        self.assertFalse(unavailable(task))

    def test_nonstructural_feedback_retains_original_user_dependency(self):
        self.enable_structure_policy()
        self.request.update(stage='search_planning', direction_id='shape', fact_id='shape', purpose='Confirm exact sold-product outline.')
        self.request.pop('candidate_id')
        self.save_request()
        task = load_json(self.run/'task.json')
        self.assertEqual(len(pending(task)), 1)
        self.assertFalse(unavailable(task))
        row = next(row for row in work_entries(task) if row.get('reason') == 'PRODUCT_FACT_FEEDBACK_PENDING')
        self.assertEqual(row['state'], 'awaiting_user')

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

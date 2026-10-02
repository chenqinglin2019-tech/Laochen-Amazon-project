"""03B semantic review fixtures; never call a real source."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
from discovery_semantics import current, work_entries
from record_discovery_semantics import record
from workflow_v24 import generate_plan, scenario_dispatch_block_from_dir
import test_product_scope as scope_fixture


class DiscoverySemanticsTests(unittest.TestCase):
    def setUp(self):
        self.f = scope_fixture.ScopeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        task=load_json(self.f.run/'task.json')
        task['discovery_semantics_revision']='discovery-semantics-v1'
        atomic_write_json(self.f.run/'task.json',task)
        self.task = self.f.save()
        self.plan = generate_plan(self.f.run)
        self.provider,self.row = next((provider,row) for provider,rows in self.plan['queries'].items()
            for row in rows if row.get('action_purpose') == 'discovery' and row.get('right_type') == 'design')
        self.input = self.f.f.root/'semantic-review.json'

    def save(self, payload):
        atomic_write_json(self.input,payload)
        return record(self.f.run,self.input)

    def direction(self, **overrides):
        return self.save({
            'stage':'direction','scenario_id':'product_entry','jurisdiction':'US','right_type':'design',
            'reviewer':'semantic-agent','reason':'Checked the scoped facts and design direction.',
            'clues':[{'clue_id':'fact:shape','disposition':'included','reason':'Visible product outline matters.'}],
            'directions':[{'direction_id':'outline','question':'Which protected overall shapes resemble this stand?',
                'clue_ids':['fact:shape'],'method':'Shape and use search',
                'proposed_sources':['uspto_patent_browser'],'evidence_needed':'Reviewed design result set',
                'supplement_trigger':'Shape variants or truncated results'}], **overrides})

    def before(self, **overrides):
        return self.save({
            'stage':'before','scenario_id':'product_entry','jurisdiction':'US','right_type':'design',
            'direction_id':'outline','query_id':self.row['query_id'],
            'reviewer':'semantic-agent','reason':'Checked the actual planned expression.',
            'semantic_fit':'full','expression_reason':'Folding stand describes the visible overall shape.',
            'concepts_in_query':['folding stand'],'uncovered_clues':[],
            'independent_structure':False,'whole_product_constraint':False,**overrides})

    def source(self, *, status='success'):
        evidence=load_json(self.f.run/'evidence.json')
        run={'run_id':'RUN-SEMANTIC','provider':self.provider,'query_id':self.row['query_id'],
            'plan_entry_sha256':sha256_json(self.row),'status':status,'submission_state':'submitted',
            'metadata':{'search_coverage':{'pages_retrieved':1}}}
        evidence.setdefault('source_runs',[]).append(run)
        evidence.setdefault('collections',{}).setdefault('patents',[]).append({
            'evidence_id':'EV-SEMANTIC','source_run_id':run['run_id'],'payload':{'candidates':[]}})
        atomic_write_json(self.f.run/'evidence.json',evidence)
        return run

    def after(self, **overrides):
        return self.save({
            'stage':'after','scenario_id':'product_entry','jurisdiction':'US','right_type':'design',
            'direction_id':'outline','query_id':self.row['query_id'],'source_run_id':'RUN-SEMANTIC',
            'evidence_refs':['EV-SEMANTIC'],'reviewer':'semantic-agent',
            'reason':'Reviewed the actual returned set against the original design question.',
            'original_problem_checked':True,'problem_covered':True,
            'result_reason':'The recorded result and expression address the overall shape.',
            'uncovered_clues':[],'excluded_by_narrowing':[],'next_action':'none',**overrides})

    def test_hash_bound_unsubmitted_cancellation_does_not_recreate_before_review(self):
        self.direction()
        self.plan.setdefault('execution_dispositions', []).append({
            'query_id':self.row['query_id'],'plan_entry_sha256':sha256_json(self.row),
            'status':'cancelled','reason':'Wrong expression withdrawn before submission.'})
        evidence=load_json(self.f.run/'evidence.json')
        entries=work_entries({**load_json(self.f.run/'task.json'),'retrieval_workflow_revision':'api-first-v3'},self.plan,evidence)
        self.assertFalse(any(r.get('query_id')==self.row['query_id'] for r in entries))
        self.plan['execution_dispositions'][0]['plan_entry_sha256']='tampered'
        entries=work_entries({**load_json(self.f.run/'task.json'),'retrieval_workflow_revision':'api-first-v3'},self.plan,evidence)
        self.assertTrue(any(r.get('query_id')==self.row['query_id'] and
            r['reason']=='DISCOVERY_EXPRESSION_REVIEW_REQUIRED' for r in entries))

    def test_cancelled_query_actual_response_still_requires_result_review(self):
        self.direction();self.before();self.source()
        self.plan.setdefault('execution_dispositions', []).append({
            'query_id':self.row['query_id'],'plan_entry_sha256':sha256_json(self.row),
            'status':'cancelled','reason':'No further submission; retained response remains.'})
        entries=work_entries({**load_json(self.f.run/'task.json'),'retrieval_workflow_revision':'api-first-v3'},self.plan,
            load_json(self.f.run/'evidence.json'))
        self.assertTrue(any(r.get('query_id')==self.row['query_id'] and
            r['reason']=='DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED' for r in entries))

    def test_two_checks_gate_dispatch_and_complete_direction(self):
        self.assertEqual(scenario_dispatch_block_from_dir(self.f.run,self.provider,self.row)['code'],
                         'DISCOVERY_DIRECTION_REVIEW_REQUIRED')
        self.direction()
        self.assertEqual(scenario_dispatch_block_from_dir(self.f.run,self.provider,self.row)['code'],
                         'DISCOVERY_EXPRESSION_REVIEW_REQUIRED')
        self.before()
        self.assertIsNone(scenario_dispatch_block_from_dir(self.f.run,self.provider,self.row))
        self.source()
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,load_json(self.f.run/'evidence.json'))
        self.assertTrue(any(v['reason']=='DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED' for v in entries))
        self.after()
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,load_json(self.f.run/'evidence.json'))
        self.assertFalse(any(v.get('direction_id')=='outline' for v in entries))

    def test_current_copyright_provenance_direction_does_not_create_query_missing(self):
        import product_scope as ps
        task=load_json(self.f.run/'task.json')
        review=self.save({
            'stage':'direction','scenario_id':'product_entry','jurisdiction':'US','right_type':'copyright',
            'reviewer':'semantic-agent','reason':'The integrated pattern needs source and expression review.',
            'clues':[{'clue_id':'fact:shape','disposition':'included','reason':'The product image shows it.'},
                     {'clue_id':'object:pattern','disposition':'included','reason':'It is part of the sold product.'}],
            'directions':[{'direction_id':'pattern','question':'Who created or owns the integrated pattern?',
                'clue_ids':['fact:shape','object:pattern'],'method':'Review retained provenance and visual materials',
                'proposed_sources':['asset_provenance'],'evidence_needed':'Bound source and image review',
                'supplement_trigger':'Unresolved source ownership'}]})
        task=load_json(self.f.run/'task.json')
        direction=ps.directions(task,'product_entry','copyright')[0]
        basis=next(item for item in review['directions'] if item['direction_id']=='pattern')
        self.assertTrue(__import__('discovery_semantics')._direction_has_local_provenance_route(
            task,self.plan,direction,basis,'US'))
        entries=work_entries(task,self.plan,load_json(self.f.run/'evidence.json'))
        self.assertFalse(any(v.get('direction_id')=='pattern'
                             and v['reason']=='DISCOVERY_DIRECTION_QUERY_MISSING' for v in entries))

    def test_provenance_cannot_waive_unbound_or_official_discovery_direction(self):
        import product_scope as ps
        from discovery_semantics import _direction_has_local_provenance_route
        task=load_json(self.f.run/'task.json')
        direction=ps.directions(task,'product_entry','copyright')[0]
        basis={'proposed_sources':['asset_provenance']}
        plan=deepcopy(self.plan)
        for row in plan['queries']['asset_provenance']:
            if row.get('right_type')=='copyright':
                row['product_dependencies'][0]['direction_id']='different-direction'
        self.assertFalse(_direction_has_local_provenance_route(task,plan,direction,basis,'US'))
        # Even a correctly bound local row does not replace patent/design/mark
        # discovery, because those rights are outside the provenance-only set.
        plan=deepcopy(self.plan)
        row=next(row for row in plan['queries']['asset_provenance'] if row.get('right_type')=='copyright')
        for right in ('patent','design','trademark_figurative'):
            non_provenance_direction={**direction,'right_type':right}
            self.assertFalse(_direction_has_local_provenance_route(
                task,plan,non_provenance_direction,basis,'US'))

    def test_unregistered_design_query_gap_obeys_canonical_jurisdiction_coverage(self):
        from workflow_v24 import build_coverage_requirements_v24
        task=load_json(self.f.run/'task.json')
        self.f.data['scope']['directions'].append({'direction_id':'unreg','scenario_id':'product_entry',
            'right_type':'unregistered_design','fact_ids':['shape'],'object_ids':['pattern'],
            'reason':'Review unregistered appearance protection.'})
        task=self.f.update()
        task['coverage_requirements']=build_coverage_requirements_v24(['US'])
        atomic_write_json(self.f.run/'task.json',task)
        self.save({'stage':'direction','scenario_id':'product_entry','jurisdiction':'US',
            'right_type':'unregistered_design','reviewer':'semantic-agent',
            'reason':'Reviewed the US scope and applicable protection routes.',
            'clues':[{'clue_id':'fact:shape','disposition':'included','reason':'Visible outline is in scope.'},
                     {'clue_id':'object:pattern','disposition':'included','reason':'Integrated pattern is in scope.'}],
            'directions':[{'direction_id':'unreg','question':'Does an applicable unregistered design right cover this product?',
                'clue_ids':['fact:shape','object:pattern'],'method':'Review applicable US protection and coverage.',
                'proposed_sources':['asset_provenance'],'evidence_needed':'Applicable right and provenance basis.',
                'supplement_trigger':'A legally applicable right or source is identified.'}]})
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,load_json(self.f.run/'evidence.json'))
        self.assertFalse(any(v.get('right_type')=='unregistered_design' and v.get('jurisdiction')=='US'
                             and v['reason']=='DISCOVERY_DIRECTION_QUERY_MISSING' for v in entries))

        task=load_json(self.f.run/'task.json')
        task['target_jurisdictions'].append('GB')
        task['coverage_requirements']=build_coverage_requirements_v24(['US','GB'])
        atomic_write_json(self.f.run/'task.json',task)
        self.save({'stage':'direction','scenario_id':'product_entry','jurisdiction':'GB',
            'right_type':'unregistered_design','reviewer':'semantic-agent',
            'reason':'Reviewed the GB scope and applicable protection routes.',
            'clues':[{'clue_id':'fact:shape','disposition':'included','reason':'Visible outline is in scope.'},
                     {'clue_id':'object:pattern','disposition':'included','reason':'Integrated pattern is in scope.'}],
            'directions':[{'direction_id':'unreg','question':'Does an applicable unregistered design right cover this product?',
                'clue_ids':['fact:shape','object:pattern'],'method':'Review applicable GB protection and coverage.',
                'proposed_sources':['asset_provenance'],'evidence_needed':'Applicable right and provenance basis.',
                'supplement_trigger':'A legally applicable right or source is identified.'}]})
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,load_json(self.f.run/'evidence.json'))
        self.assertTrue(any(v.get('right_type')=='unregistered_design' and v.get('jurisdiction')=='GB'
                            and v['reason']=='DISCOVERY_DIRECTION_QUERY_MISSING' for v in entries))

    def test_empty_reviewed_figurative_inventory_closes_only_its_current_direction(self):
        from discovery_semantics import _empty_figurative_inventory_closes_current_direction
        direction = {'direction_id': 'own-figurative-mark', 'clue_ids': ['fact:brand', 'object:logo']}
        review = {'clues': [{'clue_id': 'fact:brand', 'disposition': 'irrelevant'},
                            {'clue_id': 'object:logo', 'disposition': 'irrelevant'}],
                  'directions': [{'direction_id': direction['direction_id'], 'clue_ids': direction['clue_ids']}]}
        with patch('record_asset_provenance.specialty_enabled', return_value=True), \
             patch('record_asset_provenance.asset_scope', return_value={'inventory_reviewed': True, 'asset_ids': []}):
            self.assertTrue(_empty_figurative_inventory_closes_current_direction(
                self.task, 'product_entry', 'trademark_figurative', direction, review))
            self.assertFalse(_empty_figurative_inventory_closes_current_direction(
                self.task, 'product_entry', 'trademark_word', direction, review))
            self.assertFalse(_empty_figurative_inventory_closes_current_direction(
                self.task, 'product_entry', 'trademark_figurative', direction,
                {**review, 'clues': [*review['clues'], {'clue_id': 'fact:brand', 'disposition': 'included'}]}))
        with patch('record_asset_provenance.specialty_enabled', return_value=True), \
             patch('record_asset_provenance.asset_scope', return_value={'inventory_reviewed': True, 'asset_ids': ['logo']}):
            self.assertFalse(_empty_figurative_inventory_closes_current_direction(
                self.task, 'product_entry', 'trademark_figurative', direction, review))

    def test_empty_brand_inventory_and_word_mark_information_wait_do_not_make_query_gap(self):
        from discovery_semantics import _empty_own_word_mark_waits_for_information
        direction = {'direction_id': 'own-word-mark', 'right_type': 'trademark_word'}
        review = {'clues': [{'clue_id': 'fact:own-brand-use', 'disposition': 'awaiting_information'}],
                  'directions': [{'direction_id': 'own-word-mark', 'clue_ids': ['fact:own-brand-use']}]}
        with patch('record_asset_provenance.specialty_enabled', return_value=True), \
             patch('record_asset_provenance.asset_scope', return_value={'inventory_reviewed': True, 'asset_ids': []}):
            self.assertTrue(_empty_own_word_mark_waits_for_information(
                self.task, 'product_entry', 'trademark_word', direction, review))
            self.assertFalse(_empty_own_word_mark_waits_for_information(
                self.task, 'product_entry', 'patent', direction, review))
            self.assertFalse(_empty_own_word_mark_waits_for_information(
                self.task, 'product_entry', 'trademark_word', direction,
                {**review, 'clues': [{'clue_id': 'fact:own-brand-use', 'disposition': 'included'}]}))
        with patch('record_asset_provenance.specialty_enabled', return_value=True), \
             patch('record_asset_provenance.asset_scope', return_value={'inventory_reviewed': True, 'asset_ids': ['logo']}):
            self.assertFalse(_empty_own_word_mark_waits_for_information(
                self.task, 'product_entry', 'trademark_word', direction, review))

    def test_reference_alone_or_unreviewed_structure_does_not_pass(self):
        self.direction()
        self.before(semantic_fit='mismatch',expression_reason='Only the product name is present.')
        self.assertEqual(scenario_dispatch_block_from_dir(self.f.run,self.provider,self.row)['code'],
                         'DISCOVERY_EXPRESSION_MISMATCH')
        with self.assertRaisesRegex(ValueError,'EXPRESSION_REVIEW_INCOMPLETE'):
            self.before(semantic_fit='full',uncovered_clues=['fact:shape'])

    def test_insufficient_clue_retains_work_and_scope_change_invalidates_review(self):
        self.direction(clues=[{'clue_id':'fact:shape','disposition':'awaiting_information',
                              'reason':'Need a clearer view of the outline.'}])
        self.before()
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,load_json(self.f.run/'evidence.json'))
        self.assertTrue(any(v['reason']=='DISCOVERY_CLUE_AWAITING_INFORMATION' for v in entries))
        self.assertTrue(any(v['reason']=='DISCOVERY_CLUE_AWAITING_INFORMATION'
                            and v['kind']=='user_information' and v['state']=='awaiting_user'
                            for v in entries))
        self.f.data['scope']['facts'][1]['value']='Changed shape'
        self.f.update()
        self.assertEqual(scenario_dispatch_block_from_dir(self.f.run,self.provider,self.row)['code'],
                         'PRODUCT_SCOPE_REVIEW_REQUIRED')

    def test_unrelated_fact_update_keeps_direction_review(self):
        self.direction();self.before()
        old=load_json(self.f.run/'task.json')['product_scope']['scope_sha256']
        self.f.data['scope']['facts'][0]['status']='confirmed'
        self.f.data['scope']['facts'][0]['reason']='Later source confirmed the separate lock fact.'
        self.f.update()
        task=load_json(self.f.run/'task.json')
        self.assertNotEqual(old,task['product_scope']['scope_sha256'])
        self.assertIsNotNone(current(task,self.plan,load_json(self.f.run/'evidence.json'),
            stage='before',scenario_id='product_entry',jurisdiction='US',right_type='design',
            direction_id='outline',provider=self.provider,row=self.row))
        self.assertIsNone(scenario_dispatch_block_from_dir(self.f.run,self.provider,self.row))

    def test_unmapped_important_fact_needs_explicit_disposition(self):
        self.f.data['scope']['directions']=[item for item in self.f.data['scope']['directions']
                                            if item['direction_id']!='locking']
        self.f.update()
        with self.assertRaisesRegex(ValueError,'INVENTORY_INCOMPLETE'):
            self.direction()
        self.direction(unmapped_clues=[{'clue_id':'fact:lock','disposition':'awaiting_information',
            'reason':'The lock mechanism lacks minimum detail and remains a patent-direction question.'}])
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,load_json(self.f.run/'evidence.json'))
        self.assertTrue(any(item['reason']=='DISCOVERY_CLUE_AWAITING_INFORMATION' for item in entries))

    def test_narrowed_query_cannot_close_uncovered_problem(self):
        self.direction();self.before(semantic_fit='partial',uncovered_clues=['fact:shape'])
        self.source(status='no_result')
        with self.assertRaisesRegex(ValueError,'RESULT_REVIEW_INCOMPLETE'):
            self.after()
        self.after(problem_covered=False,uncovered_clues=['fact:shape'],
                   excluded_by_narrowing=['side profile'],next_action='refine')
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,load_json(self.f.run/'evidence.json'))
        self.assertTrue(any(v['reason']=='DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED' for v in entries))

    def test_after_waiting_information_requires_exact_open_direction_clue(self):
        self.direction(clues=[{'clue_id':'fact:shape','disposition':'awaiting_information',
            'reason':'Need a clear view before comparing the outline.'}])
        self.before()
        self.source()
        self.after(problem_covered=False,uncovered_clues=['fact:shape'],
            excluded_by_narrowing=['Search terms do not resolve the missing outline detail.'],
            next_action='awaiting_information')
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,
                             load_json(self.f.run/'evidence.json'))
        self.assertTrue(any(item.get('clue_id')=='fact:shape' and item['state']=='awaiting_user'
                            for item in entries))
        self.assertFalse(any(item.get('query_id')==self.row['query_id'] and
                             item['reason']=='DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED'
                             for item in entries))
        self.after(problem_covered=False,uncovered_clues=['Need more information'],
            excluded_by_narrowing=['The actual query did not obtain the missing information.'],
            next_action='awaiting_information')
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,
                             load_json(self.f.run/'evidence.json'))
        self.assertTrue(any(item.get('query_id')==self.row['query_id'] and
                            item['reason']=='DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED'
                            for item in entries))

    def test_bounded_stop_wait_requires_current_full_triage_and_exact_single_page_limit(self):
        self.direction(); self.before()
        run=self.source()
        run['metadata']={'search_coverage':{'truncated':True,'unretrieved_result_row_count':796}}
        evidence=load_json(self.f.run/'evidence.json')
        evidence['source_runs'][-1]=run
        atomic_write_json(self.f.run/'evidence.json',evidence)
        self.after(problem_covered=False,uncovered_clues=['796 result rows were not retrieved.'],
            excluded_by_narrowing=['Only the current page was retained.'],next_action='awaiting_capability')
        task=load_json(self.f.run/'task.json')
        task['retrieval_workflow_revision']='api-first-v2'
        task['source_operation_revision']='source-operation-v1'
        task.setdefault('discovery_followups',[]).append({'role':'review',
            'parent_query_id':self.row['query_id'],'source_run_id':run['run_id'],
            'outcome':'stop_bounded_discovery','review_id':'API-STOP-1'})
        task['source_operation_reviews']=[{'provider':self.provider,'query_id':self.row['query_id'],
            'source_run_id':run['run_id'],'decision':'accepted',
            'checks':{'pagination':'single_page'}}]
        with patch('api_first_planning.review_validation',return_value=None) as api_review_validation, \
             patch('api_first_planning.source_files_error',return_value=None), \
             patch('source_operation.validate',return_value=(self.row,run)), \
             patch('source_operation.verify'):
            entries=work_entries(task,self.plan,evidence,candidates={},ledger={},
                task_dir=self.f.run)
            api_review_validation.assert_called_once()
            self.assertTrue(any(item.get('query_id')==self.row['query_id']
                and item['state']=='awaiting_access'
                and item['reason']=='BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED'
                and item['unretrieved_result_row_count']==796 for item in entries))
            self.assertFalse(any(item.get('query_id')==self.row['query_id']
                and item['reason']=='DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED' for item in entries))
            run['metadata']={'range_start':1,'range_end':25,'range_verified':True,
                'retrieved_hits':25,'total_hits':1048,'schema_valid':True,'truncated':True,
                'stop_reason':'page_limit'}
            evidence['source_runs'][-1]=run
            atomic_write_json(self.f.run/'evidence.json',evidence)
            self.after(problem_covered=False,uncovered_clues=['796 result rows were not retrieved.'],
                excluded_by_narrowing=['Only a verified 1-25 range was retained.'],
                next_action='awaiting_capability')
            task=load_json(self.f.run/'task.json')
            task['retrieval_workflow_revision']='api-first-v2'
            task['source_operation_revision']='source-operation-v1'
            task['discovery_followups']=[{'role':'review','parent_query_id':self.row['query_id'],
                'source_run_id':run['run_id'],'outcome':'stop_bounded_discovery','review_id':'API-STOP-1'}]
            task['source_operation_reviews']=[{'provider':self.provider,'query_id':self.row['query_id'],
                'source_run_id':run['run_id'],'decision':'accepted','checks':{'pagination':'single_page'}}]
            entries=work_entries(task,self.plan,evidence,candidates={},ledger={},
                task_dir=self.f.run)
            self.assertTrue(any(item.get('query_id')==self.row['query_id']
                and item['state']=='awaiting_access'
                and item['reason']=='BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED'
                and item['unretrieved_result_row_count'] is None for item in entries))
            task['source_operation_reviews'][0]['checks']['pagination']='unknown'
            entries=work_entries(task,self.plan,evidence,candidates={},ledger={},
                task_dir=self.f.run)
            self.assertTrue(any(item.get('query_id')==self.row['query_id']
                and item['state']=='ready'
                and item['reason']=='DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED' for item in entries))
        task['source_operation_reviews'][0]['checks']['pagination']='single_page'
        with patch('api_first_planning.review_validation',return_value='API_DISCOVERY_TRIAGE_REQUIRED'), \
             patch('api_first_planning.source_files_error',return_value=None), \
             patch('source_operation.validate',return_value=(self.row,run)), \
             patch('source_operation.verify'):
            entries=work_entries(task,self.plan,evidence,candidates={},ledger={},task_dir=self.f.run)
        self.assertTrue(any(item.get('query_id')==self.row['query_id']
            and item['state']=='ready' for item in entries))
        task['discovery_followups'].clear()
        entries=work_entries(task,self.plan,evidence,candidates={},ledger={},task_dir=self.f.run)
        self.assertTrue(any(item.get('query_id')==self.row['query_id']
            and item['state']=='ready' for item in entries))

    def test_hash_bound_non_result_fault_can_wait_without_claiming_zero_or_coverage(self):
        self.direction(); self.before()
        run=self.source(status='no_result')
        self.after(problem_covered=False,uncovered_clues=['The source fault returned no usable result envelope.'],
            excluded_by_narrowing=['No result set was received.'],next_action='awaiting_capability')
        task=load_json(self.f.run/'task.json')
        task['retrieval_workflow_revision']='api-first-v2'
        task['source_operation_revision']='source-operation-v1'
        task.setdefault('discovery_followups',[]).append({'role':'review',
            'parent_query_id':self.row['query_id'],'source_run_id':run['run_id'],
            'outcome':'stop_bounded_discovery','review_id':'API-STOP-FAULT'})
        task['source_operation_reviews']=[{'provider':self.provider,'query_id':self.row['query_id'],
            'source_run_id':run['run_id'],'decision':'rejected','checks':{
                'pagination':'unknown','field_effect':'unknown'}}]
        evidence=load_json(self.f.run/'evidence.json')
        with patch('api_first_planning._receipt_classified_failure',return_value=True), \
             patch('api_first_planning.review_validation',return_value=None), \
             patch('api_first_planning.source_files_error',return_value=None), \
             patch('source_operation.validate',return_value=(self.row,run)), \
             patch('source_operation.verify'):
            entries=work_entries(task,self.plan,evidence,candidates={},ledger={},task_dir=self.f.run)
            waiting=next(item for item in entries if item.get('query_id')==self.row['query_id'])
            self.assertEqual((waiting['state'],waiting['reason']),('awaiting_access','SOURCE_FAULT_UNVERIFIED'))
            self.assertEqual(waiting['coverage_status'],'unknown')
            self.assertNotIn('problem_covered',waiting)
        task['source_operation_reviews'][0]['decision']='accepted'
        with patch('api_first_planning._receipt_classified_failure',return_value=True), \
             patch('api_first_planning.review_validation',return_value=None), \
             patch('api_first_planning.source_files_error',return_value=None), \
             patch('source_operation.validate',return_value=(self.row,run)), \
             patch('source_operation.verify'):
            entries=work_entries(task,self.plan,evidence,candidates={},ledger={},task_dir=self.f.run)
            self.assertTrue(any(item.get('query_id')==self.row['query_id']
                and item['state']=='ready' and item['reason']=='DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED'
                for item in entries))

    def test_review_receipt_change_and_idempotence(self):
        first=self.direction()
        self.assertEqual(first['review_id'],self.direction()['review_id'])
        self.assertEqual(len(load_json(self.f.run/'task.json')['discovery_semantic_reviews']),1)
        path=self.f.run/'raw'/'discovery_semantics'/(first['review_id']+'.json')
        from pathlib import Path
        Path(path).write_text('{}')
        with self.assertRaisesRegex(ValueError,'RECEIPT_CHANGED'):
            self.before()

    def test_direction_review_is_actionable_and_country_specific(self):
        from workflow_v24 import work_view_from_dir
        from advance_work import actionable_packet
        view=work_view_from_dir(self.f.run)
        self.assertTrue(any(item['reason']=='DISCOVERY_DIRECTION_REVIEW_REQUIRED'
                            for item in actionable_packet(view)['agent']))
        self.direction()
        task=load_json(self.f.run/'task.json')
        task['target_jurisdictions'].append('GB')
        evidence=load_json(self.f.run/'evidence.json')
        self.assertIsNone(current(task,self.plan,evidence,stage='direction',scenario_id='product_entry',
                                  jurisdiction='GB',right_type='design'))

    def test_independent_structure_and_classification_need_separate_bases(self):
        self.f.data['scope']['facts'][0]['status']='confirmed'
        self.f.add_lock_term()
        self.f.data['query_terms'].append({'kind':'cpc','value':'A47B9/00','language':'',
                                           'derived_from':'product.structure[0]'})
        self.f.update()
        plan=generate_plan(self.f.run,expand=True)
        patent=[(provider,row) for provider,rows in plan['queries'].items() for row in rows
                if row.get('action_purpose')=='discovery' and row.get('right_type')=='patent']
        structure=next((provider,row) for provider,row in patent
                       if row['discovery_scope']['expression_basis']['kind']=='structural_feature')
        classification=next((provider,row) for provider,row in patent
                            if row['discovery_scope']['expression_basis']['kind']=='cpc')
        self.assertNotIn('folding',structure[1]['q'].lower())
        self.save({'stage':'direction','scenario_id':'product_entry','jurisdiction':'US','right_type':'patent',
            'reviewer':'semantic-agent','reason':'The locking mechanism is independently material.',
            'clues':[{'clue_id':'fact:lock','disposition':'included','reason':'Separate structure question.'}],
            'directions':[{'direction_id':'locking','clue_ids':['fact:lock'],
                'question':'How is the hinge locked?','method':'Structure and classification recall',
                'proposed_sources':['uspto_patent_browser'],'evidence_needed':'Reviewed patent results',
                'supplement_trigger':'Missing structure or truncated results'}]})
        for provider,row in (structure,classification):
            payload={'stage':'before','scenario_id':'product_entry','jurisdiction':'US','right_type':'patent',
                'direction_id':'locking','query_id':row['query_id'],'reviewer':'semantic-agent',
                'reason':'Inspected the submitted field and expression.','semantic_fit':'full',
                'expression_reason':'This expression independently tests the hinged lock.',
                'concepts_in_query':['hinge lock'],'uncovered_clues':[],
                'independent_structure':True,'whole_product_constraint':False}
            if row is classification[1]:
                with self.assertRaisesRegex(ValueError,'CLASSIFICATION_REVIEW_REQUIRED'):
                    self.save(payload)
                payload['classification_basis']={'source':'candidate or product clue review',
                    'meaning':'Hinged support classification','applicability':'Observed locking feature'}
            self.save(payload)
        self.assertIsNone(__import__('discovery_semantics').dispatch_error(
            load_json(self.f.run/'task.json'),plan,load_json(self.f.run/'evidence.json'),*structure))

    def test_translated_expression_requires_original_and_source(self):
        from api_first_planning import make_row
        term={'kind':'translation','value':'folding stand','language':'en',
              'derived_from':'product.title','strategy':'boolean'}
        row=make_row(self.task,self.provider,term,'US','design',self.row['requirement_ids'])
        index=next(i for i,item in enumerate(self.plan['queries'][self.provider])
                   if item['query_id']==self.row['query_id'])
        self.plan['queries'][self.provider][index]=row
        atomic_write_json(self.f.run/'search-plan.json',self.plan)
        self.row=row
        self.direction()
        with self.assertRaisesRegex(ValueError,'LANGUAGE_REVIEW_REQUIRED'):
            self.before()
        self.before(language_basis={'original':'折叠支架','submitted':'folding stand',
            'source':'Agent translation of the supplied description',
            'relationship':'Same visible overall form; reviewed translation, not a new product fact.'})

    def test_pre_execution_reviews_cannot_be_backfilled_after_submission(self):
        self.source()
        with self.assertRaisesRegex(ValueError,'DIRECTION_REVIEW_TOO_LATE'):
            self.direction()
        evidence=load_json(self.f.run/'evidence.json')
        evidence['source_runs']=[]
        atomic_write_json(self.f.run/'evidence.json',evidence)
        self.direction()
        self.source()
        with self.assertRaisesRegex(ValueError,'EXPRESSION_REVIEW_TOO_LATE'):
            self.before()

    def test_executed_query_missing_before_routes_to_plan_repair_without_backfill(self):
        self.direction()
        self.source()
        task=load_json(self.f.run/'task.json'); evidence=load_json(self.f.run/'evidence.json')
        rows=[item for item in work_entries(task,self.plan,evidence)
              if item.get('query_id') == self.row['query_id']]
        self.assertTrue(rows)
        self.assertTrue(all(item['reason']=='DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED'
                            and item['kind']=='plan_repair' for item in rows))
        self.assertTrue(all(item.get('historical_expression_review_missing') for item in rows))
        self.assertTrue(all(item['source_run_id']=='RUN-SEMANTIC' for item in rows))
        from discovery_semantics import dispatch_error
        self.assertEqual(dispatch_error(task,self.plan,evidence,self.provider,self.row),
                         'DISCOVERY_EXPRESSION_REVIEW_REQUIRED')
        with self.assertRaisesRegex(ValueError,'EXPRESSION_REVIEW_TOO_LATE'):
            self.before()

    def test_not_submitted_query_still_requires_preflight_review(self):
        self.direction()
        evidence=load_json(self.f.run/'evidence.json')
        entries=work_entries(load_json(self.f.run/'task.json'),self.plan,evidence)
        self.assertTrue(any(item.get('query_id')==self.row['query_id']
                            and item['reason']=='DISCOVERY_EXPRESSION_REVIEW_REQUIRED'
                            for item in entries))

    def test_one_multi_office_query_has_one_run_and_separate_country_reviews(self):
        from api_first_planning import make_row
        from common import authorize_signa_free_plan_entry, signa_free_enhancement
        from workflow_v24 import build_coverage_requirements_v24, term_records
        from discovery_budget import snapshot as budget_snapshot
        from discovery_semantics import dispatch_error
        task=load_json(self.f.run/'task.json')
        task['target_jurisdictions'].append('GB')
        task['coverage_requirements']=build_coverage_requirements_v24(task['target_jurisdictions'],
            screening_revision=task.get('screening_revision'),
            specialty_workflow_revision=task.get('specialty_workflow_revision'))
        task['signa_free_enhancement']=signa_free_enhancement(True)
        atomic_write_json(self.f.run/'task.json',task)
        term=next(item for item in term_records(task) if item.get('kind')=='brand' and item.get('value')=='OWN')
        row=make_row(task,'signa',term,'US,GB','trademark_word',[])
        (self.f.run/'search-plan.json').unlink()
        plan=generate_plan(self.f.run)
        plan['queries']={provider:[item for item in values if item.get('right_type')!='trademark_word']
                         for provider,values in plan['queries'].items()}
        plan['queries']['signa']=[row]
        atomic_write_json(self.f.run/'search-plan.json',plan)
        self.assertEqual(authorize_signa_free_plan_entry(task,plan,row['query_id'])['filters']['offices'],['US','GB'])
        evidence=load_json(self.f.run/'evidence.json')
        self.assertEqual(dispatch_error(task,plan,evidence,'signa',row),'DISCOVERY_DIRECTION_REVIEW_REQUIRED')
        for country in ('US','GB'):
            self.save({'stage':'direction','scenario_id':'product_entry','jurisdiction':country,
                'right_type':'trademark_word','reviewer':'semantic-agent','reason':'Reviewed this country scope.',
                'clues':[{'clue_id':'object:own','disposition':'included','reason':'Own mark is in scope.'}],
                'directions':[{'direction_id':'own-mark','clue_ids':['object:own'],
                    'question':'Which word marks conflict with OWN?','method':'Native multi-office word search',
                    'proposed_sources':['signa'],'evidence_needed':'Reviewed source results',
                    'supplement_trigger':'Relevant country missing or truncated'}]})
            self.save({'stage':'before','scenario_id':'product_entry','jurisdiction':country,
                'right_type':'trademark_word','direction_id':'own-mark','query_id':row['query_id'],
                'reviewer':'semantic-agent','reason':'Verified this office is in the actual request.',
                'semantic_fit':'full','expression_reason':'OWN and the target office are both submitted.',
                'concepts_in_query':['OWN',country],'uncovered_clues':[],
                'independent_structure':False,'whole_product_constraint':False})
            if country=='US':
                self.assertEqual(dispatch_error(load_json(self.f.run/'task.json'),plan,evidence,'signa',row),
                                 'DISCOVERY_DIRECTION_REVIEW_REQUIRED')
        task=load_json(self.f.run/'task.json')
        self.assertIsNone(dispatch_error(task,plan,evidence,'signa',row))
        from unittest.mock import patch
        import subprocess
        from common import sha256_file
        from runtime_v24 import execute_api_plan
        calls=[]
        def offline_client(command, **kwargs):
            calls.append(command)
            retained=self.f.run/'raw'/'shared-signa.json'
            atomic_write_json(retained,{'offices':['US','GB'],'results':[]})
            run={'run_id':'RUN-SHARED','provider':'signa','query_id':row['query_id'],
                'plan_entry_sha256':sha256_json(row),'jurisdiction':'US,GB','right_type':'trademark_word',
                'operation':row['operation'],'status':'no_result','submission_state':'submitted',
                'raw_paths':[str(retained)],'payload_digest':sha256_file(retained),
                'metadata':{'search_coverage':{'pages_retrieved':1,'schema_valid':True,
                    'truncated':False,'total_hits':0,'retrieved_hits':0}}}
            current=load_json(self.f.run/'evidence.json')
            current['source_runs'].append(run)
            current.setdefault('collections',{}).setdefault('trademarks',[]).append({
                'evidence_id':'EV-SHARED','source_run_id':run['run_id'],'payload':{'candidates':[]}})
            atomic_write_json(self.f.run/'evidence.json',current)
            return subprocess.CompletedProcess(command,0,'{"status":"no_result"}','')
        with patch('runtime_v24.capabilities',return_value=[{'provider':'signa','executable':True}]), \
                patch('run_api_plan.command_for',return_value=['offline-signa-client']) as command_for, \
                patch('runtime_v24.subprocess.run',side_effect=offline_client):
            execution=execute_api_plan(self.f.run,query_ids_filter=[row['query_id']],include_optional=True,
                                       phase='discovery')
        self.assertEqual(len(calls),1)
        command_for.assert_called_once()
        self.assertEqual(execution['counts']['executed'],1)
        evidence=load_json(self.f.run/'evidence.json')
        for country in ('US','GB'):
            self.save({'stage':'after','scenario_id':'product_entry','jurisdiction':country,
                'right_type':'trademark_word','direction_id':'own-mark','query_id':row['query_id'],
                'source_run_id':'RUN-SHARED','evidence_refs':['EV-SHARED'],
                'reviewer':'semantic-agent','reason':'Reviewed this office result against its own scope.',
                'original_problem_checked':True,'problem_covered':True,
                'result_reason':'The recorded request and zero-result receipt cover this office question.',
                'uncovered_clues':[],'excluded_by_narrowing':[],'next_action':'none'})
        task=load_json(self.f.run/'task.json')
        entries=work_entries(task,plan,evidence)
        self.assertFalse(any(item.get('direction_id')=='own-mark' for item in entries))
        self.assertEqual(len([item for item in evidence['source_runs'] if item['run_id']=='RUN-SHARED']),1)
        usage=budget_snapshot(task,plan,evidence,row)
        self.assertEqual(usage['pages_acquired'],1)
        self.assertEqual(len(usage['routes']),1)


if __name__ == '__main__':
    unittest.main()

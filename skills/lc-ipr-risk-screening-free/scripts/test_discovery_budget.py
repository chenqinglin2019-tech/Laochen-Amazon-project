"""03A purpose/version limits using retained synthetic receipts only."""
from copy import deepcopy
import unittest

from common import sha256_json
from discovery_budget import REVISION, dispatch_block, pagination_block, purpose_id, snapshot
from workflow_v24 import append_next_pages, product_identity_digest
import test_api_first_v2 as fixture


class AdvisoryGapReuseTests(unittest.TestCase):
    def fixture(self):
        from api_first_planning import intent_id
        term={'kind':'design','value':'transparent ball','language':'en','derived_from':'product.title'}
        intent=intent_id('US','design','text',term)
        row={'query_id':'Q1','jurisdiction':'US','right_type':'design','search_dimension':'text',
            'discovery_intent_id':intent,'discovery_scope':{'expression_basis':{
                'kind':'design','value':'transparent ball','language':'en','source':'product.title',
                'term_sha256':sha256_json(term)}}}
        gap={'code':'API_DISCOVERY_PURPOSE_EXPRESSION_REVIEW_REQUIRED','blocking_planning':False,
            'jurisdiction':'US','right_type':'design','search_dimension':'text',
            'discovery_intent_id':intent,'derived_from':['product.title'],'term_id':'old-advisory-hash'}
        return {'retrieval_workflow_revision':'api-first-v3'}, {'terms':[term],'queries':{'provider':[row]}},gap

    def test_same_frozen_expression_advisory_does_not_duplicate_query(self):
        from api_first_planning import _advisory_gap_has_frozen_query
        task,plan,gap=self.fixture()
        self.assertTrue(_advisory_gap_has_frozen_query(task,plan,gap))
        gap['code']='API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP'
        plan['execution_dispositions']=[{'query_id':'Q1','status':'cancelled'}]
        self.assertTrue(_advisory_gap_has_frozen_query(task,plan,gap))
        plan['terms'][0]['fact_version']=2
        self.assertTrue(_advisory_gap_has_frozen_query(task,plan,gap))

    def test_real_scope_expression_and_blocking_changes_remain(self):
        from api_first_planning import _advisory_gap_has_frozen_query
        for key,value in [('jurisdiction','GB'),('right_type','copyright'),('search_dimension','image'),
                          ('discovery_intent_id','different'),('blocking_planning',True),
                          ('derived_from',['product.other']),('code','API_DISCOVERY_BUDGET_EXHAUSTED')]:
            task,plan,gap=self.fixture();gap[key]=value
            self.assertFalse(_advisory_gap_has_frozen_query(task,plan,gap))
        task,plan,gap=self.fixture();plan['terms'][0]['value']='different ball'
        self.assertFalse(_advisory_gap_has_frozen_query(task,plan,gap))
        task,plan,gap=self.fixture();task['retrieval_workflow_revision']='api-first-v2'
        self.assertFalse(_advisory_gap_has_frozen_query(task,plan,gap))


class DiscoveryBudgetTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.ApiFirstV2Tests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.task['discovery_budget_revision'] = REVISION
        # These 03A fixtures predate 04C execution receipts; keep the frozen
        # legacy card-hash accounting contract under test explicitly.
        self.f.task.pop('candidate_acquisition_revision', None)
        self.f.regenerate()
        self.task = self.f.task
        self.base = self.f.primary()
        self.evidence = {'schema_version':self.task['schema_version'],
                         'task_id':self.task['task_id'],'source_runs': [], 'collections': {}}

    def row(self, provider, name, *, version=0, role='fallback'):
        value = deepcopy(self.base)
        value.update(query_id=name, refinement_round=version, discovery_role=role)
        return provider, value

    def receipt(self, provider, row, *, pages=1, cards=0, status='success', state='submitted'):
        run_id = 'RUN-' + str(len(self.evidence['source_runs']))
        run = {'run_id':run_id,'provider':provider,'query_id':row['query_id'],
            'plan_entry_sha256':sha256_json(row),'status':status,'submission_state':state,
            'metadata':{'search_coverage':{'pages_retrieved':pages}}}
        self.evidence['source_runs'].append(run)
        if cards:
            self.evidence['collections'].setdefault('patents', []).append({
                'source_run_id':run_id,'payload':{'candidates':[
                    {'source_record_sha256':f'{i:064x}'} for i in range(cards)]}})
        return run

    def test_three_independent_browser_purposes_do_not_share_old_scope_cap(self):
        from workflow_v24 import scenario_dispatch_block_from_dir
        self.f.task['query_terms'] = [
            {'kind':'structural_feature','value':value,'language':'en',
             'derived_from':f'product.structure[{i}]'}
            for i, value in enumerate(('hinge lock','release button','folding link'))]
        self.f.task['product']['structure'] = [t['value'] for t in self.f.task['query_terms']]
        self.f.task['product']['analysis']['identity_sha256'] = product_identity_digest(
            self.f.task['product'], task=self.f.task)
        self.f.no_api()
        rows = [row for provider, values in self.f.plan['queries'].items()
                if provider.endswith('browser') for row in values
                if row.get('right_type') == 'patent' and row.get('discovery_role') == 'browser_fallback']
        self.assertGreaterEqual(len({row['discovery_intent_id'] for row in rows}), 3)
        for row in rows:
            self.assertIsNone(scenario_dispatch_block_from_dir(self.f.path,'uspto_patent_browser',row))
        self.assertFalse(any(g['code']=='API_DISCOVERY_BROWSER_SCOPE_LIMIT'
                             for g in self.f.plan['planning_gaps']))

    def test_shared_pages_routes_unknown_and_browser_cards(self):
        a = self.row('serper_patents','Q-A',role='primary')
        b = self.row('epo_ops','Q-B')
        browser = self.row('uspto_patent_browser','Q-C',role='browser_fallback')
        plan = {'queries':{a[0]:[a[1]],b[0]:[b[1]]}}
        self.receipt(*a,pages=5)
        state = snapshot(self.task,plan,self.evidence,a[1])
        self.assertEqual(state['remaining_pages'],3)
        self.assertEqual(len(state['routes']),2)
        self.receipt(*b,pages=3)
        self.assertEqual(dispatch_block(self.task,plan,self.evidence,*b),'DISCOVERY_VERSION_PAGE_LIMIT')
        self.evidence['source_runs'].pop()
        plan['queries'][browser[0]]=[browser[1]]
        self.assertEqual(dispatch_block(self.task,plan,self.evidence,*browser),'DISCOVERY_ROUTE_LIMIT')
        del plan['queries'][b[0]]
        self.assertIsNone(dispatch_block(self.task,plan,self.evidence,*browser))
        unknown=self.receipt(*browser,pages=0,status='failed',state='unknown')
        self.assertEqual(snapshot(self.task,plan,self.evidence,browser[1])['remaining_pages'],3)
        self.assertIn(('uspto_patent_browser',browser[1]['operation'],'browser'),
                      snapshot(self.task,plan,self.evidence,browser[1])['routes'])
        plan['queries'][b[0]]=[b[1]]
        self.assertEqual(dispatch_block(self.task,plan,self.evidence,*b),'DISCOVERY_ROUTE_LIMIT')
        del plan['queries'][b[0]]
        self.evidence['source_runs'].remove(unknown)
        self.receipt(*browser,pages=2,cards=57)
        state=snapshot(self.task,plan,self.evidence,browser[1])
        self.assertEqual(state['browser_candidates_acquired'],57)
        self.assertEqual(state['remaining_pages'],1)
        self.assertEqual(dispatch_block(self.task,plan,self.evidence,*browser),'DISCOVERY_BROWSER_CANDIDATE_LIMIT')
        self.assertEqual(len(self.evidence['collections']['patents'][0]['payload']['candidates']),57)

    def test_browser_refinement_uses_same_purpose_and_two_round_limit(self):
        from api_first_planning import append_followup
        import test_api_first_planning as planning_fixture
        self.f.no_api()
        parent = next(row for row in self.f.plan['queries']['uspto_patent_browser']
                      if row.get('right_type') == 'patent')
        purpose = parent['discovery_intent_id']
        for version in (1, 2):
            request = planning_fixture.ApiFirstPlanningTests.request(
                self.f, parent, provider='uspto_patent_browser', value=f'spherical drive {version}')
            request['term']['strategy'] = 'boolean'
            row = append_followup(self.f.path, request)
            self.f.reload()
            self.assertEqual(row['discovery_intent_id'], purpose)
            self.assertEqual(row['refinement_round'], version)
            self.assertEqual(row['execution_phase'], 'discovery_fallback')
            self.assertEqual(row['discovery_scope']['max_pages'], 1)
            parent = row
        request = planning_fixture.ApiFirstPlanningTests.request(
            self.f, parent, provider='uspto_patent_browser', value='spherical drive third')
        request['term']['strategy'] = 'boolean'
        with self.assertRaisesRegex(ValueError, 'ROUND_LIMIT'):
            append_followup(self.f.path, request)

    def test_browser_refinement_cards_count_toward_current_version_limit(self):
        browser = self.row('uspto_patent_browser', 'Q-REFINE', version=1, role='refinement')
        plan = {'queries': {'uspto_patent_browser': [browser[1]]}}
        self.receipt(*browser, pages=1, cards=50)
        self.assertEqual(snapshot(self.task, plan, self.evidence, browser[1])['browser_candidates_acquired'], 50)
        self.assertEqual(dispatch_block(self.task, plan, self.evidence, *browser),
                         'DISCOVERY_BROWSER_CANDIDATE_LIMIT')

    def test_expression_versions_are_distinct_but_field_syntax_stays_same_version(self):
        initial=self.row('serper_patents','Q-INITIAL',role='primary')
        syntax=self.row('epo_ops','Q-SYNTAX')
        revised=self.row('serper_patents','Q-REVISED',version=1,role='refinement')
        plan={'queries':{'serper_patents':[initial[1],revised[1]],'epo_ops':[syntax[1]]}}
        self.receipt(*initial,pages=1)
        self.assertEqual(snapshot(self.task,plan,self.evidence,syntax[1])['remaining_pages'],7)
        self.assertEqual(snapshot(self.task,plan,self.evidence,revised[1])['remaining_pages'],8)
        self.assertEqual(initial[1]['discovery_intent_id'],revised[1]['discovery_intent_id'])
        original={'derived_from':'product.structure[0]','value':'hinge lock','language':'en'}
        translated={**original,'value':'Scharnierverriegelung','language':'de'}
        self.assertEqual(purpose_id('DE','patent','text',original),
                         purpose_id('DE','patent','text',translated))
        with self.assertRaisesRegex(ValueError,'NEW_PURPOSE_REASON_REQUIRED'):
            purpose_id('DE','patent','text',{**original,'discovery_problem_id':'internal-lock'})

    def test_same_clue_synonym_requires_review_instead_of_minting_new_purpose(self):
        from workflow_v24 import product_identity_digest
        from api_first_planning import next_work_entries
        self.f.task['query_terms'] = [
            {'kind':'structural_feature','value':value,'language':'en',
             'derived_from':'product.structure[0]'}
            for value in ('hinge lock','hinge latch')]
        self.f.task['product']['structure']=['hinge lock']
        self.f.task['product']['analysis']['identity_sha256']=product_identity_digest(
            self.f.task['product'],task=self.f.task)
        self.f.regenerate()
        patent_rows=[row for provider, rows in self.f.plan['queries'].items()
                     for row in rows if row.get('right_type')=='patent'
                     and row.get('discovery_role')=='primary'
                     and row.get('search_dimension')=='text']
        self.assertEqual(len(patent_rows),1)
        self.assertTrue(any(g['code']=='API_DISCOVERY_PURPOSE_EXPRESSION_REVIEW_REQUIRED'
                            for g in self.f.plan['planning_gaps']))
        work=next_work_entries(self.f.task,self.f.plan,self.f.evidence,
                               self.f.candidates,self.f.ledger)
        self.assertTrue(any(item.get('reason')=='API_DISCOVERY_PURPOSE_EXPRESSION_REVIEW_REQUIRED'
                            and item.get('state')=='ready' for item in work))

    def test_distinct_problem_on_same_clue_requires_explicit_difference(self):
        from workflow_v24 import product_identity_digest
        clue={'kind':'structural_feature','value':'hinge lock','language':'en',
              'derived_from':'product.structure[0]'}
        old_id=purpose_id('US','patent','text',clue,self.task['primary_scenario_id'])
        self.f.task['query_terms']=[clue,{**clue,'value':'release actuator',
            'discovery_problem_id':'independent-release-actuator',
            'discovery_problem_reason':'The release actuator is independently relevant to the claim.',
            'different_from_purpose_id':old_id}]
        self.f.task['product']['structure']=['hinge lock']
        self.f.task['product']['analysis']['identity_sha256']=product_identity_digest(
            self.f.task['product'],task=self.f.task)
        self.f.regenerate()
        rows=[row for provider, values in self.f.plan['queries'].items()
              for row in values if row.get('right_type')=='patent'
              and row.get('discovery_role')=='primary'
              and row.get('search_dimension')=='text']
        self.assertEqual(len({row['discovery_intent_id'] for row in rows}),2)
        new=next(row for row in rows if row['discovery_intent_id']!=old_id)
        self.assertEqual(new['discovery_scope']['purpose_basis']['different_from_purpose_id'],old_id)

    def test_api_next_page_inherits_purpose_version_and_exact_parent_receipt(self):
        from common import atomic_write_json
        from api_first_planning import make_row, dispatch_block as plan_dispatch_block
        from workflow_v24 import scenario_dispatch_block
        term=self.task['query_terms'][0]
        parent=make_row(self.task,'epo_ops',term,'US','patent',self.base['requirement_ids'])
        # Explicitly freeze room for two ten-result pages; the default one-page
        # scope must not silently receive another page merely because total>25.
        parent['range']='1-10'
        parent['discovery_scope'].update(max_pages=2,max_candidates=25)
        from workflow_v24 import bind_scenario_action
        parent=bind_scenario_action(self.task,'epo_ops',parent,purpose='discovery',
                                   obligation_key=parent['discovery_intent_id'])
        plan=deepcopy(self.f.plan)
        plan['queries'].setdefault('epo_ops',[]).append(parent)
        run=self.receipt('epo_ops',parent)
        run['metadata']['search_coverage'].update(total_hits=100,retrieved_hits=10,schema_valid=True)
        atomic_write_json(self.f.path/'evidence.json',self.evidence)
        append_next_pages(self.f.path,plan)
        page=plan['queries']['epo_ops'][-1]
        self.assertEqual((page['discovery_intent_id'],page['refinement_round'],page['range']),
                         (parent['discovery_intent_id'],0,'11-20'))
        self.assertEqual(page['discovery_role'],'pagination')
        self.assertIsNone(pagination_block(self.task,plan,self.evidence,'epo_ops',page))
        self.assertIsNone(plan_dispatch_block(self.task,plan,self.evidence,
                                               self.f.candidates,self.f.ledger,'epo_ops',page))
        self.assertIsNone(scenario_dispatch_block(self.task,plan,'epo_ops',page,
            self.f.candidates,self.f.ledger,self.evidence))
        tampered=deepcopy(page); tampered['range']='21-30'
        self.assertEqual(pagination_block(self.task,plan,self.evidence,'epo_ops',tampered),
                         'DISCOVERY_PAGINATION_POSITION_INVALID')
        run['metadata']['search_coverage']['pages_retrieved']=8
        self.evidence['source_runs'][0]=run
        self.assertEqual(dispatch_block(self.task,plan,self.evidence,'epo_ops',page),
                         'DISCOVERY_VERSION_PAGE_LIMIT')


    def bounded_epo_parent(self, *, pages=1, candidates=25, returned=25):
        from common import atomic_write_json
        from api_first_planning import make_row
        from workflow_v24 import bind_scenario_action
        parent=make_row(self.task,'epo_ops',self.task['query_terms'][0],'US','patent',self.base['requirement_ids'])
        parent['range']=f'1-{returned}'
        parent['discovery_scope'].update(max_pages=pages,max_candidates=candidates)
        parent=bind_scenario_action(self.task,'epo_ops',parent,purpose='discovery',
                                   obligation_key=parent['discovery_intent_id'])
        plan=deepcopy(self.f.plan)
        plan['queries'].setdefault('epo_ops',[]).append(parent)
        run=self.receipt('epo_ops',parent)
        run['metadata']['search_coverage'].update(total_hits=1048,retrieved_hits=returned,schema_valid=True,truncated=True)
        atomic_write_json(self.f.path/'evidence.json',self.evidence)
        return plan,parent,run

    def test_frozen_one_page_scope_never_appends_second_page(self):
        plan,parent,run=self.bounded_epo_parent()
        before=deepcopy(plan['queries'])
        append_next_pages(self.f.path,plan)
        self.assertEqual(plan['queries'],before)
        self.assertEqual(plan['pagination_gaps'][0]['code'],'DISCOVERY_SCOPE_PAGE_LIMIT')
        self.assertEqual(run['metadata']['search_coverage']['total_hits'],1048)
        self.assertTrue(run['metadata']['search_coverage']['truncated'])

    def test_frozen_candidate_bound_cannot_fit_next_complete_page(self):
        plan,parent,_=self.bounded_epo_parent(pages=2,candidates=25)
        append_next_pages(self.f.path,plan)
        self.assertEqual(len(plan['queries']['epo_ops']),1)
        self.assertEqual(plan['pagination_gaps'][0]['code'],'DISCOVERY_SCOPE_CANDIDATE_LIMIT')

    def test_pagination_chain_consumes_original_bound_and_preserves_existing_rows(self):
        from common import atomic_write_json
        plan,parent,_=self.bounded_epo_parent(pages=3,candidates=25,returned=10)
        append_next_pages(self.f.path,plan)
        page=plan['queries']['epo_ops'][-1]
        self.assertEqual(page['range'],'11-20')
        run=self.receipt('epo_ops',page)
        run['metadata']['search_coverage'].update(total_hits=1048,retrieved_hits=10,schema_valid=True,truncated=True)
        atomic_write_json(self.f.path/'evidence.json',self.evidence)
        before=deepcopy(plan['queries'])
        append_next_pages(self.f.path,plan)
        self.assertEqual(plan['queries'],before)
        self.assertTrue(any(g['code']=='DISCOVERY_SCOPE_CANDIDATE_LIMIT' for g in plan['pagination_gaps']))
        self.assertEqual(parent['discovery_scope']['max_pages'],3)
        self.assertEqual(page['discovery_scope']['max_pages'],1)

    def test_only_validated_current_parent_stop_blocks_next_page(self):
        from common import atomic_write_json
        from unittest.mock import patch
        plan,parent,run=self.bounded_epo_parent(pages=2,candidates=25,returned=10)
        self.task['discovery_followups']=[{'role':'review','outcome':'stop_bounded_discovery',
            'parent_query_id':parent['query_id'],'source_run_id':run['run_id']}]
        atomic_write_json(self.f.path/'task.json',self.task)
        with patch('api_first_planning.review_validation',return_value=None) as validate:
            append_next_pages(self.f.path,plan)
            self.assertEqual(len(plan['queries']['epo_ops']),1)
            self.assertEqual(plan['pagination_gaps'][0]['code'],'API_DISCOVERY_BOUNDED_STOP')
            validate.assert_called_once()
        with patch('api_first_planning.review_validation',return_value='API_DISCOVERY_TRIAGE_CHANGED'):
            append_next_pages(self.f.path,plan)
            self.assertEqual(plan['queries']['epo_ops'][-1]['range'],'11-20')


if __name__=='__main__': unittest.main()

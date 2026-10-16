"""r7 (search-guard-v1): the patent search of a new task always runs, with names that find the product itself.

Owner's runs of 2026-10-16: the basket's USD1035381S1 was never searched (SerpApi had no searches left and EPO was never
tried), the eyeliner's design query was flooded by "cosmetic applicator" / "makeup applicator" (230 results, nine
eyeliner designs never read), image and web searches used loose feature phrases, refused detail requests were recorded
as unknown submissions, and the r6 prompt lost the comparison-criteria format (rows rated 低 became 待定).
"""
import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

import search_guard

EYELINER = {'article_names': [
    {'value': 'eyeliner stamp', 'derived_from': 'product.title'},
    {'value': 'eyeliner stamp pen', 'derived_from': 'product.title'},
    {'value': 'eyeliner applicator', 'derived_from': 'product.title'},
    {'value': 'eyeliner pen', 'derived_from': 'product.title'},
    {'value': 'cosmetic stamp', 'derived_from': 'product.title', 'broad': True},
    {'value': 'cosmetic applicator', 'derived_from': 'product.title', 'broad': True},
    {'value': 'makeup applicator', 'derived_from': 'product.title', 'broad': True}],
    'function_concepts': [
        {'label': '眼线压印', 'terms': ['stamp', 'stamping', 'imprinting'], 'derived_from': 'product.bullets'},
        {'label': '折叠与旋转调角', 'terms': ['foldable', 'folding', 'rotating'], 'derived_from': 'product.bullets'}]}
BASKET = {'article_names': [
    {'value': 'rolling grill basket', 'derived_from': 'product.title'},
    {'value': 'cylindrical grill basket', 'derived_from': 'product.title'},
    {'value': 'grill basket', 'derived_from': 'product.title', 'broad': True},
    {'value': 'grilling basket', 'derived_from': 'product.title', 'broad': True},
    {'value': 'barbecue basket', 'derived_from': 'product.title', 'broad': True},
    {'value': 'roasting basket', 'derived_from': 'product.title', 'broad': True}],
    'function_concepts': [{'label': '滚动翻料', 'terms': ['rolling', 'rotating'], 'derived_from': 'product.bullets'}]}
CAT = {'article_names': [
    {'value': 'cat teaser', 'derived_from': 'product.title'},
    {'value': 'teaser wand', 'derived_from': 'product.title'},
    {'value': 'cat wand', 'derived_from': 'product.title'},
    {'value': 'interactive cat toy', 'derived_from': 'product.title'},
    {'value': 'electric cat teaser', 'derived_from': 'product.title'},
    {'value': 'cat toy', 'derived_from': 'product.title', 'broad': True},
    {'value': 'pet toy', 'derived_from': 'product.title', 'broad': True}],
    'function_concepts': [{'label': '电机驱动', 'terms': ['motor', 'motorized'], 'derived_from': 'product.bullets'}]}
MARKED = {search_guard.TASK_FIELD: search_guard.REVISION}


class DesignNamesTests(unittest.TestCase):
    def test_core_words_of_the_three_products(self):
        self.assertEqual(search_guard.core_words([r['value'] for r in EYELINER['article_names'] if not r.get('broad')]),
                         ['eyeliner', 'stamp', 'pen'])
        self.assertEqual(search_guard.core_words([r['value'] for r in CAT['article_names'] if not r.get('broad')]),
                         ['cat', 'teaser'])
        self.assertTrue(search_guard.shares_core('grilling basket', ['rolling', 'grill', 'basket', 'cylindrical']))
        self.assertFalse(search_guard.shares_core('cosmetic applicator', ['eyeliner', 'stamp', 'pen']))
        self.assertFalse(search_guard.shares_core('pencil case', ['pen']))      # short words match whole only

    def test_the_eyeliner_design_query_leaves_out_the_tool_names_only(self):
        import recall
        specific, category, upper, excluded = recall.design_name_levels(EYELINER, guard=True)
        self.assertEqual((category, upper, excluded), (['cosmetic stamp'], [], ['cosmetic applicator', 'makeup applicator']))
        self.assertEqual(recall.name_levels(EYELINER), (specific, ['cosmetic stamp', 'cosmetic applicator',
                                                                   'makeup applicator'], []))
        old = recall.compose_terms(EYELINER, phrases=True)
        new = recall.compose_terms(EYELINER, phrases=True, guard=True)
        self.assertEqual(new[0]['value'], '("eyeliner stamp" OR "eyeliner applicator" OR "eyeliner pen" OR "cosmetic stamp")')
        self.assertEqual([t['value'] for t in old[1:]], [t['value'] for t in new[1:]])   # utility groups unchanged
        self.assertIn('外观不检索、只用于发明检索的宽泛名："cosmetic applicator"、"makeup applicator"',
                      new[0]['discovery_problem_reason'])
        levels = recall.recorded_levels({'query_terms': new})
        self.assertEqual(levels['design_excluded'], ['cosmetic applicator', 'makeup applicator'])
        import precision
        self.assertIn('cosmetic applicator', precision.broad_names({'query_terms': new}))

    def test_the_basket_and_the_cat_keep_their_queries(self):
        import recall
        for concepts in (BASKET, CAT):
            self.assertEqual([t['value'] for t in recall.compose_terms(concepts, phrases=True)],
                             [t['value'] for t in recall.compose_terms(concepts, phrases=True, guard=True)])

    def test_image_web_and_enforcement_search_by_the_product_names(self):
        term = search_guard.names_term(EYELINER)
        self.assertEqual(term['value'], '("eyeliner stamp" OR "eyeliner applicator" OR "eyeliner pen")')
        self.assertEqual((term['derived_from'], term['strategy']), ('product.title', 'boolean'))
        from discovery_budget import purpose_id
        purpose_id('US', 'copyright', 'text', term)        # a valid new purpose (reason and origin present)
        loose = {'value': 'stamp pen set', 'kind': 'design', 'derived_from': 'product.title'}
        feature = {'value': 'dual applicator heads', 'kind': 'structural_feature', 'derived_from': 'images[0].sha256'}
        self.assertEqual(search_guard.scope_terms(MARKED, 'copyright', [loose, term, feature]), [term])
        self.assertEqual(search_guard.scope_terms(MARKED, 'enforcement', [loose, feature, term]), [term])
        self.assertEqual(search_guard.scope_terms(MARKED, 'trademark_word', [loose, term]), [loose])
        self.assertEqual(search_guard.scope_terms({}, 'copyright', [loose, term, feature]), [loose, term, feature])
        from api_first_planning import provider_params
        enforcement = provider_params('serper_web', term, 'US', 'enforcement', retrieval_revision='api-first-v3',
                                      public_discovery_revision='public-discovery-v1', schedule_a=True)
        self.assertIn('"eyeliner stamp"', enforcement['q'])
        self.assertIn('"Schedule A"', enforcement['q'])

    def test_recompiled_rows_match_the_planned_query(self):
        from api_first_planning import provider_params, task_params
        term = search_guard.names_term(EYELINER)
        task = {**MARKED, 'retrieval_workflow_revision': 'api-first-v3', 'public_discovery_routing_revision':
                'public-discovery-v1', 'stability_revision': 'report-always-v1'}
        planned = provider_params('serper_web', term, 'US', 'enforcement', retrieval_revision='api-first-v3',
                                  public_discovery_revision='public-discovery-v1', schedule_a=True)
        self.assertEqual(task_params(task, 'serper_web', term, 'US', 'enforcement')['q'], planned['q'])
        self.assertNotEqual(task_params({}, 'serper_web', term, 'US', 'enforcement')['q'], planned['q'])


class CapacityTests(unittest.TestCase):
    def test_routes(self):
        known = {'state': 'known', 'available': 9, 'needed_discovery': 4, 'epo_executable': True, 'renewal_date': '2026-10-21'}
        self.assertEqual(search_guard.route_for(known), 'serpapi')
        self.assertEqual(search_guard.route_for({**known, 'available': 0}), 'epo')
        self.assertEqual(search_guard.route_for({**known, 'available': 3, 'epo_executable': False}), 'none')
        self.assertEqual(search_guard.route_for({'state': 'unknown'}), 'serpapi')
        self.assertIn('2026-10-21', search_guard.notice({**known, 'available': 0, 'route': 'epo'}))
        self.assertIn('不出报告', search_guard.notice({**known, 'available': 0, 'epo_executable': False, 'route': 'none'}))

    def test_the_balance_is_read_once_and_the_key_never_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'task.json').write_text(json.dumps({**MARKED, 'query_terms': []}), encoding='utf-8')
            (root / 'source-capabilities.json').write_text(json.dumps({'sources': [
                {'provider': 'epo_ops', 'executable': True}]}), encoding='utf-8')
            payload = {'plan_searches_left': 0, 'extra_credits': 0, 'searches_per_month': 250, 'this_month_usage': 250,
                       'plan_renewal_date': '2026-10-21', 'account_status': 'Active'}
            seen = []
            def fetch(url, **kwargs):
                seen.append(url)
                return payload, {}, b''
            with mock.patch('serpapi_patents_client.settings', return_value=({}, 'https://serpapi.com', 'SECRET-KEY')), \
                    mock.patch('common.serpapi_free_enabled', return_value=True), \
                    mock.patch('source_policy.enabled', return_value=True), \
                    mock.patch('free_search_budget.peek', return_value=None):
                record = search_guard.check_capacity(root, fetch=fetch)
            self.assertEqual(len(seen), 1)
            self.assertTrue(seen[0].startswith('https://serpapi.com/account.json'))
            self.assertEqual((record['available'], record['route'], record['renewal_date']), (0, 'epo', '2026-10-21'))
            text = (root / search_guard.CAPACITY_FILE).read_text(encoding='utf-8')
            self.assertNotIn('SECRET-KEY', text)
            task = json.loads((root / 'task.json').read_text(encoding='utf-8'))
            self.assertTrue(search_guard.serpapi_discovery_blocked(task, root))
            self.assertEqual(search_guard.detail_cap(root), 0)

    def test_the_local_ledger_is_read_without_writing(self):
        import free_search_budget as budget
        with tempfile.TemporaryDirectory() as folder:
            ledger = Path(folder)
            account = budget._digest('lc-ipr-free-search\0serpapi\0https://serpapi.com\0KEY')
            state = {'schema': 'FREE-SEARCH-BUDGET/1.0', 'account': account, 'cycle': '2026-10-21', 'remaining': 0,
                     'reservations': [], 'task_usage': {}, 'reservation_credit_units': {}}
            path = ledger / (account + '.json')
            path.write_text(json.dumps(state), encoding='utf-8')
            before = path.read_bytes()
            self.assertEqual(budget.peek('serpapi', 'KEY', 'https://serpapi.com', ledger_dir=ledger,
                                         renewal_date='2026-10-21', today='2026-10-16'), 0)
            # a later renewal date after the old one has passed: the next reservation resets the ledger
            self.assertIsNone(budget.peek('serpapi', 'KEY', 'https://serpapi.com', ledger_dir=ledger,
                                          renewal_date='2026-11-21', today='2026-10-22'))
            self.assertEqual(path.read_bytes(), before)

    def test_the_design_fallback_is_epo_for_marked_tasks(self):
        from provider_routing import priority
        import recall
        self.assertEqual(recall.routing_revision({'recall_revision': recall.REVISION, **MARKED}), recall.GUARD_ROUTING_REVISION)
        self.assertEqual(priority('US', 'design', 'discovery', revision=recall.GUARD_ROUTING_REVISION)[:2],
                         [('serpapi_google_patents', 'preferred'), ('epo_ops', 'fallback')])
        self.assertNotIn('epo_ops', dict(priority('US', 'design', 'discovery', revision=recall.ROUTING_REVISION)))
        from api_first_planning import provider_params
        term = {'value': '("grill basket" OR "grilling basket")', 'kind': 'design', 'language': 'en',
                'derived_from': 'product.title', 'strategy': 'boolean'}
        params = provider_params('epo_ops', term, 'US', 'design', epo_query_revision='ops-cql-v1', us_only=True)
        self.assertEqual(params['q'], '(pn=US) and ((ta="grill basket" or ta="grilling basket"))')

    def test_a_run_without_any_patent_search_is_seen(self):
        plan = {'queries': {'serpapi_google_patents': [
            {'query_id': 'Q%d' % n, 'jurisdiction': 'US', 'right_type': right, 'operation': 'search',
             'action_purpose': 'discovery'} for n, right in enumerate(('design', 'patent', 'patent', 'patent'))]}}
        refused = {'source_runs': [{'query_id': 'Q0', 'status': 'access_limited', 'error_code': 'FREE_QUOTA_EXHAUSTED'}] +
                   [{'query_id': 'Q%d' % n, 'status': 'access_limited', 'error_code': 'PROVIDER_STOPPED_THIS_PASS'}
                    for n in (1, 2, 3)]}
        self.assertEqual(search_guard.patent_discovery_outcome({}, refused, plan),
                         (4, 0, ['FREE_QUOTA_EXHAUSTED', 'PROVIDER_STOPPED_THIS_PASS']))
        refused['source_runs'][0].update(status='success', error_code='')
        self.assertEqual(search_guard.patent_discovery_outcome({}, refused, plan)[:2], (4, 1))

    def test_a_refusal_before_sending_is_not_an_unknown_submission(self):
        self.assertTrue(search_guard.pre_network_quota(
            'Shared local free allowance is exhausted; a higher remote balance alone cannot release uncertain consumption'))
        self.assertTrue(search_guard.pre_network_quota('SerpApi available account searches are exhausted'))
        self.assertFalse(search_guard.pre_network_quota('Provider response is not valid JSON'))
        text = (Path(__file__).parent / 'runtime_v24.py').read_text(encoding='utf-8')
        self.assertIn('search_guard.pre_network_quota(result.get("stderr"))', text)


class DetailCapTests(unittest.TestCase):
    def test_eight_details_same_form_and_core_first(self):
        import core_focus
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = [{'scope': {'candidate_id': 'D%d' % n}, 'tier': 'same' if n < 3 else 'similar'} for n in range(6)]
            text = [{'scope': {'candidate_id': 'U%d' % n}, 'tier': 'core' if n < 4 else 'related'} for n in range(6)]
            for mode, rows in (('image', image), ('text', text)):
                (root / ('recall-screen-' + mode)).mkdir()
                (root / ('recall-screen-' + mode) / 'kept.json').write_text(json.dumps({'rows': rows}), encoding='utf-8')
            core_focus.save_priorities(root, {row['scope']['candidate_id']: 'core' for row in image + text})
            (root / search_guard.CAPACITY_FILE).write_text(json.dumps({
                'schema': search_guard.CAPACITY_SCHEMA, 'state': 'known', 'available': 40, 'needed_discovery': 4}),
                encoding='utf-8')
            queries = {'serpapi_google_patents': []}
            def plan(cid):
                issue = search_guard.detail_issue(MARKED, {}, queries, {'candidate_id': cid}, root)
                if not issue:
                    queries['serpapi_google_patents'].append({'operation': 'candidate_detail', 'candidate_id': cid})
                return issue
            # seven same-form / core candidates hold seven of the eight places whatever order they arrive in: one
            # similar-tier design may take the eighth, a second lower-ranked candidate may not
            self.assertEqual(plan('D5'), '')
            self.assertEqual(plan('U5'), 'SEARCH_GUARD_DETAIL_CAP_REACHED')
            for cid in ('D0', 'D1', 'D2', 'U0', 'U1', 'U2', 'U3'):
                self.assertEqual(plan(cid), '')
            self.assertEqual(len(queries['serpapi_google_patents']), search_guard.DETAIL_CAP)
            self.assertEqual(plan('D4'), 'SEARCH_GUARD_DETAIL_CAP_REACHED')
            self.assertEqual(plan('D0'), '')                    # an already planned candidate is not refused
            self.assertEqual(search_guard.detail_issue({}, {}, queries, {'candidate_id': 'U5'}, root), '')


class ReviewTests(unittest.TestCase):
    def test_the_r6_prompt_states_the_criteria_format_again(self):
        from test_r6_report_always import _packet
        import report_review_host as host
        packet = _packet('appearance', index={'CAND-d': {'jurisdiction': 'US', 'right_type': 'design',
                                                         'publication_number': 'USD1', 'title': 'x',
                                                         'evidence': [{'ref': 'EV-d', 'role': 'document', 'label': 'x'}]}})
        packet['task'].update(design_assessment_revision='design-overall-v1', pipeline_robust_revision='robust-v1')
        text = host.review_prompt(packet, 1)
        self.assertIn('{criterion, result, reasoning, evidence_refs}', text)
        self.assertIn('只给 article 和 main_body_form 两项', text)
        self.assertNotIn('candidate_counter_refs', text)

    def test_text_criteria_keep_a_low_row(self):
        from test_r6_report_always import _packet, _row, _task, _scope_rows
        from module_repair import derive, REVISION, REVISION_V2
        task = _task()
        row = _row(task, comparison={'criteria': ['项1：柔性细颈不对应。', '项5：产品没有储墨腔。']})
        raw = {'assessments': [row] + _scope_rows(task), 'future_applications': [], 'enforcement_signals': [],
               'final_review_statement': {'overall': '总体。', 'scope': '范围。', 'limitations': '限制。'}}
        old, old_record = derive(raw, _packet())
        self.assertEqual(old_record['revision'], REVISION)
        self.assertEqual(old['assessments'][0]['assessment_status'], 'pending')        # the r6 behaviour
        packet = _packet()
        packet['task'].update(MARKED)
        new, record = derive(raw, packet)
        self.assertEqual(record['revision'], REVISION_V2)
        kept = new['assessments'][0]
        self.assertEqual((kept['risk'], kept['assessment_status']), ('低', 'assessed'))
        self.assertEqual(kept['comparison']['criteria'][0], {'criterion': '比较依据1', 'result': 'unknown',
                                                              'reasoning': '项1：柔性细颈不对应。', 'evidence_refs': []})
        # a validation recomputes with the recorded revision
        self.assertEqual(derive(raw, packet, revision=REVISION)[1]['revision'], REVISION)
        self.assertEqual(derive(raw, packet, revision=record['revision']), (new, record))


class GrantedApplicationTests(unittest.TestCase):
    PAGE = ('<dd itemprop="publicationNumber">US20090293905A1</dd>'
            '<dd itemprop="events" itemscope repeat><time>2009-12-03</time><span itemprop="title">Publication of '
            'US20090293905A1</span><span itemprop="type">publication</span><span itemprop="documentId">'
            'patent/US20090293905A1/en</span></dd>'
            '<dd itemprop="events" itemscope repeat><span itemprop="title">Application granted</span>'
            '<span itemprop="type">granted</span></dd>'
            '<dd itemprop="events" itemscope repeat><span itemprop="title">Publication of US8156949B2</span>'
            '<span itemprop="type">publication</span><span itemprop="documentId">patent/US8156949B2/en</span></dd>')

    def test_the_page_names_the_granted_publication(self):
        import core_focus
        self.assertEqual(core_focus.page_granted_publication(self.PAGE), 'US8156949B2')
        granted_page = self.PAGE.replace('<dd itemprop="publicationNumber">US20090293905A1</dd>',
                                         '<dd itemprop="publicationNumber">US8156949B2</dd>')
        self.assertIsNone(core_focus.page_granted_publication(granted_page))


class BoundaryTests(unittest.TestCase):
    def test_the_boundary_names_epo_when_epo_ran_the_design_query(self):
        from module_review import design_search_boundary
        rows = [{'right_type': 'design', 'publication_number': 'USD1035381S', 'candidate_nature': 'patent_search_result',
                 'publication_date': '2024-07-16', 'sources': [{'provider': 'epo_ops'}]}]
        old = design_search_boundary({'patents': rows})
        self.assertIn('Google Patents', old['note'])
        self.assertIn('EPO', design_search_boundary({'patents': rows}, guard=True)['note'])
        google = deepcopy(rows)
        google[0]['sources'] = [{'provider': 'serpapi_google_patents'}]
        self.assertEqual(design_search_boundary({'patents': google}, guard=True), design_search_boundary({'patents': google}))


class PipelineTests(unittest.TestCase):
    def _pipeline(self, root, task):
        import run_pipeline
        (root / 'task.json').write_text(json.dumps(task), encoding='utf-8')
        return run_pipeline.Pipeline(run_pipeline.parser().parse_args(['--task-dir', str(root)]))

    def _capacity(self, root, available, epo):
        record = {'schema': search_guard.CAPACITY_SCHEMA, 'state': 'known', 'available': available,
                  'needed_discovery': 4, 'epo_executable': epo, 'renewal_date': '2026-10-21'}
        record['route'] = search_guard.route_for(record)
        (root / search_guard.CAPACITY_FILE).write_text(json.dumps(record), encoding='utf-8')

    def test_no_route_stops_before_the_run_and_epo_is_announced(self):
        import run_pipeline
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pipeline = self._pipeline(root, {**MARKED})
            done = mock.Mock(returncode=0, stdout='{}', stderr='')
            self._capacity(root, 0, False)
            with mock.patch('subprocess.run', return_value=done):
                with self.assertRaises(run_pipeline.StageFailed) as caught:
                    pipeline.capacity_check('credentials')
            self.assertEqual(caught.exception.code, 'PIPELINE_PATENT_SEARCH_UNAVAILABLE')
            self.assertIn('2026-10-21', caught.exception.detail)
            self._capacity(root, 0, True)
            with mock.patch('subprocess.run', return_value=done):
                self.assertEqual(pipeline.capacity_check('credentials')['serpapi_route'], 'epo')
            self.assertIn('EPO', pipeline.search_notice()['search_notice'])
            unmarked = self._pipeline(root, {})
            self.assertEqual(unmarked.capacity_check('credentials'), {})

    def test_a_run_whose_patent_searches_all_failed_stops_before_the_review(self):
        import run_pipeline
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pipeline = self._pipeline(root, {**MARKED})
            (root / 'search-plan.json').write_text(json.dumps({'queries': {'serpapi_google_patents': [
                {'query_id': 'Q1', 'jurisdiction': 'US', 'right_type': 'design', 'operation': 'search'}]}}), encoding='utf-8')
            (root / 'evidence.json').write_text(json.dumps({'source_runs': [
                {'query_id': 'Q1', 'status': 'access_limited', 'error_code': 'FREE_QUOTA_EXHAUSTED'}]}), encoding='utf-8')
            with self.assertRaises(run_pipeline.StageFailed) as caught:
                pipeline.patent_search_check()
            self.assertEqual(caught.exception.code, 'PIPELINE_PATENT_SEARCH_NOT_EXECUTED')
            (root / 'evidence.json').write_text(json.dumps({'source_runs': [
                {'query_id': 'Q1', 'status': 'success'}]}), encoding='utf-8')
            pipeline.patent_search_check()


class MarkerTests(unittest.TestCase):
    def test_new_tasks_carry_the_marker(self):
        text = (Path(__file__).parent / 'create_task.py').read_text(encoding='utf-8')
        self.assertIn('task[SEARCH_GUARD_FIELD] = SEARCH_GUARD_REVISION', text)
        self.assertFalse(search_guard.enabled({}))
        self.assertTrue(search_guard.enabled(MARKED))


if __name__ == '__main__':
    unittest.main()

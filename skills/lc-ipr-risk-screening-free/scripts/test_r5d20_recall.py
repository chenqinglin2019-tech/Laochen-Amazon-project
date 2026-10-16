"""r5d20 (owner authorization 2026-10-14): US patents and designs searched on Google Patents in patent language.

Owner's B0GLNPC6K8 run: USD1152251S "Cat teaser" was never retrieved - the only design query was the listing phrase
"butterfly cat toy" (zero results) and invention patents went to EPO title/abstract words only. Recall tasks compose
concept groups (article names, head nouns + modifiers, one function concept each) for Google Patents with 100 results,
the document type and the in-force date floor; EPO is a US-only fallback; a reviewer's refine words are planned first;
large result sets get a list screen. Tasks without ``recall_revision`` keep every old behaviour.
"""
import unittest
from unittest import mock

import recall

TASK = {'recall_revision': recall.REVISION, 'created_at': '2026-10-13T11:00:00Z'}
SOURCES = {'product.title', 'product.bullets', 'product.bullets[0]', 'images[0].sha256'}
CAT = {'article_names': [{'value': v, 'derived_from': 'product.title'} for v in
                         ('cat teaser', 'teaser wand', 'cat wand', 'interactive cat toy')]
                        + [{'value': v, 'derived_from': 'product.title', 'broad': True} for v in ('cat toy', 'pet toy')],
       'function_concepts': [
           {'label': '电机驱动', 'terms': ['motor', 'motorized', 'electric', 'driven'], 'derived_from': 'product.bullets[3]'},
           {'label': '旋转', 'terms': ['rotate', 'rotating', 'rotation', 'spin'], 'derived_from': 'product.bullets'},
           {'label': '触碰唤醒', 'terms': ['touch', 'sensor', 'wake'], 'derived_from': 'product.bullets'}]}


class ConceptTests(unittest.TestCase):
    def test_cat_teaser_groups_reach_the_known_design_title(self):
        from api_first_planning import google_query
        from epo_query import compile_ops_query
        from workflow_v24 import boolean_tokens
        terms = recall.compose_terms(recall.parse_concepts(CAT, SOURCES))
        groups = [(t['recall_group'], t['discovery_problem_id']) for t in terms]
        self.assertEqual(groups, [('design', 'recall-v1:design-names'), ('design', 'recall-v1:design-broad'),
                                  ('patent', 'recall-v1:function-1'), ('patent', 'recall-v1:function-2'),
                                  ('patent', 'recall-v1:function-3')])
        names = google_query(terms[0])
        self.assertIn('"cat teaser"', names)          # USD1152251S and USD1108038S1 are titled "Cat teaser"
        self.assertNotIn('butterfly', names)
        self.assertNotIn('"pet toy"', names)          # broad names stay out of the names group (live check: flooding)
        self.assertEqual(google_query(terms[1]), '( teaser OR wand OR toy ) ( cat OR interactive OR pet )')
        self.assertIn('"pet toy"', google_query(terms[2]))   # utility full text keeps the broad names
        self.assertIn('( motor OR motorized OR electric OR driven )', google_query(terms[2]))
        for term in terms:
            boolean_tokens(term['value'])
            self.assertTrue(compile_ops_query(countries=['US'], field='ta', value=term['value'],
                                              strategy='boolean').startswith('(pn=US) and '))
        self.assertEqual(terms[2]['derived_from'], 'product.bullets')     # one bullet counts as the whole list

    def test_invalid_groups_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'RECALL_ARTICLE_NAMES_COUNT_INVALID'):
            recall.parse_concepts({'article_names': ['cat teaser'], 'function_concepts': []}, SOURCES)
        with self.assertRaisesRegex(ValueError, 'RECALL_ARTICLE_NAME_INVALID'):
            recall.parse_concepts({'article_names': ['cat teaser', 'best cat toy ever made'], 'function_concepts': []}, SOURCES)
        with self.assertRaisesRegex(ValueError, 'RECALL_ARTICLE_NAME_INVALID'):
            recall.parse_concepts({'article_names': [{'value': 'cat toy', 'derived_from': 'product.specifications'},
                                                     'pet toy'], 'function_concepts': []}, SOURCES)
        with self.assertRaisesRegex(ValueError, 'RECALL_FUNCTION_CONCEPT_INVALID'):
            recall.parse_concepts({'article_names': ['cat toy', 'pet toy'],
                                   'function_concepts': [{'label': 'x', 'terms': [], 'derived_from': 'product.title'}]},
                                  SOURCES)
        # promotion words are dropped, not kept
        parsed = recall.parse_concepts({'article_names': ['premium grill basket', 'grilling basket'],
                                        'function_concepts': []}, SOURCES)
        self.assertEqual([row['value'] for row in parsed['article_names']], ['grill basket', 'grilling basket'])
        fallback = recall.compose_terms(recall.program_concepts('rolling grill basket'))
        self.assertEqual([t['recall_group'] for t in fallback], ['design', 'design', 'patent'])

    def test_wire_parameters(self):
        self.assertEqual(recall.serpapi_params(TASK, 'design'), {'type': 'DESIGN', 'after': 'priority:20101013'})
        self.assertEqual(recall.serpapi_params(TASK, 'patent'), {'type': 'PATENT', 'after': 'priority:20051013'})
        self.assertEqual(recall.serpapi_params(TASK, 'design', {'discovery_problem_id': 'recall-v1:design-broad'})['sort'], 'new')
        self.assertEqual(recall.serpapi_params({}, 'design'), {})
        self.assertEqual(recall.results_per_query(TASK, 'serpapi_google_patents', 100), 100)
        self.assertEqual(recall.results_per_query(TASK, 'serper_web', 100), 10)
        self.assertEqual(recall.results_per_query({}, 'serpapi_google_patents', 100), 10)
        self.assertEqual(recall.results_per_query({}, 'serpapi_google_patents', 10), 10)

    def test_routing_and_eligible_terms(self):
        from provider_routing import priority
        self.assertEqual(priority('US', 'patent', 'discovery', revision=recall.ROUTING_REVISION),
                         [('serpapi_google_patents', 'preferred'), ('epo_ops', 'fallback')])
        self.assertEqual(priority('US', 'patent', 'discovery', revision='api-first-v3')[0], ('epo_ops', 'preferred'))
        self.assertEqual(priority('US', 'design', 'discovery', revision=recall.ROUTING_REVISION),
                         priority('US', 'design', 'discovery', revision='api-first-v3'))
        self.assertEqual(recall.routing_revision(TASK), recall.ROUTING_REVISION)
        self.assertEqual(recall.routing_revision({'retrieval_workflow_revision': 'api-first-v3'}), 'api-first-v3')


class TermRecordTests(unittest.TestCase):
    def test_recall_group_travels_only_in_recall_tasks(self):
        from workflow_v24 import term_records
        terms = recall.compose_terms(recall.parse_concepts(CAT, SOURCES))
        base = {'product': {'title': 'Automatic Butterfly Cat Toy'}, 'query_terms': terms}
        with mock.patch('discovery_budget.enabled', return_value=True), \
                mock.patch('workflow_v24.recall_integrity_enabled', return_value=False):
            recorded = term_records(dict(base, **TASK))
            self.assertEqual({row.get('recall_group') for row in recorded if row['kind'] in {'design', 'function'}},
                             {'design', 'patent'})
            with self.assertRaisesRegex(ValueError, 'unsupported recall_group'):
                term_records(dict(base))
            bad = [dict(terms[0], recall_group='copyright')]
            with self.assertRaisesRegex(ValueError, 'unsupported recall_group'):
                term_records(dict(base, query_terms=bad, **TASK))


class SerpApiWireTests(unittest.TestCase):
    def test_client_sends_type_date_floor_and_order(self):
        import serpapi_patents_client as client
        seen = {}

        def fake(url, timeout, retries):
            seen['url'] = url
            return {'search_metadata': {'status': 'Success'}, 'organic_results': []}, {}, b'{}'
        with mock.patch.object(client, 'http_json', side_effect=fake):
            client.search('https://serpapi.com', 'KEY', 5, {'q': 'basket', 'num': 100, 'country': 'US', 'type': 'PATENT',
                                                             'after': 'priority:20051013'})
            self.assertIn('type=PATENT', seen['url'])
            self.assertIn('after=priority%3A20051013', seen['url'])
            client.search('https://serpapi.com', 'KEY', 5, {'q': 'basket', 'num': 100, 'country': 'US', 'type': 'DESIGN',
                                                             'after': 'priority:20101013', 'sort': 'new'})
            self.assertIn('sort=new', seen['url'])
            client.search('https://serpapi.com', 'KEY', 5, {'q': 'basket', 'num': 10, 'country': 'US'})
            self.assertNotIn('after=', seen['url'])
            self.assertNotIn('type=', seen['url'])


class RefineTests(unittest.TestCase):
    def test_reviewer_words_become_the_first_rewrite(self):
        import auto_refine
        row = {'query_id': 'Q1', 'right_type': 'design', 'derived_from': ['product.title']}
        task = dict(TASK, discovery_semantic_reviews=[
            {'stage': 'after', 'query_id': 'Q1', 'next_action': 'refine',
             'refine_query': {'names': ['cat teaser', 'teaser wand'], 'functions': []}}])
        term = auto_refine._reviewer_term(task, row)
        self.assertEqual(term['value'], '("cat teaser" OR "teaser wand")')
        self.assertEqual((term['kind'], term['recall_group']), ('design', 'design'))
        patent = auto_refine._reviewer_term(dict(task, discovery_semantic_reviews=[
            {'stage': 'after', 'query_id': 'Q1', 'next_action': 'refine',
             'refine_query': {'names': ['cat toy'], 'functions': ['motor', 'electric']}}]), dict(row, right_type='patent'))
        self.assertEqual(patent['value'], '"cat toy" AND (motor OR electric)')
        self.assertIsNone(auto_refine._reviewer_term({}, row))
        self.assertIsNone(auto_refine._reviewer_term(dict(task, discovery_semantic_reviews=[
            {'stage': 'after', 'query_id': 'Q1', 'next_action': 'awaiting_capability',
             'refine_query': {'names': ['cat teaser']}}]), row))

    def test_cancelled_unsent_rewrite_no_longer_counts(self):
        import auto_refine
        from common import sha256_json
        child = {'query_id': 'Q2', 'parent_query_id': 'Q1', 'discovery_role': 'refinement'}
        plan = {'execution_dispositions': [{'query_id': 'Q2', 'plan_entry_sha256': sha256_json(child), 'status': 'cancelled'}]}
        self.assertTrue(auto_refine.cancelled_unsent(plan, {'source_runs': []}, child))
        self.assertFalse(auto_refine.cancelled_unsent(plan, {'source_runs': [{'query_id': 'Q2', 'submission_state': 'submitted'}]}, child))
        self.assertFalse(auto_refine.cancelled_unsent({'execution_dispositions': []}, {}, child))

    def test_review_host_keeps_a_usable_proposal(self):
        import discovery_review_host as host
        ctx = {'template': {'stage': 'after'}, 'fit': 'partial', 'truncated': True, 'evidence_ids': ['EV-1']}
        row = {'reason': '过窄', 'problem_covered': False, 'result_reason': '只有一条', 'uncovered_clues': ['fact:F-TITLE'],
               'excluded_by_narrowing': ['以 cat teaser 命名的外观'], 'next_action': 'refine',
               'refine_query': {'names': ['cat teaser', 'best toy'], 'functions': []}}
        event = host._fill_after(ctx, row, 'S1')[0]
        self.assertEqual(event['refine_query'], {'names': ['cat teaser', 'toy'], 'functions': []})
        event = host._fill_after(ctx, dict(row, refine_query={'names': []}), 'S1')[0]
        self.assertNotIn('refine_query', event)


class ScreenTests(unittest.TestCase):
    def packet(self, mode='text'):
        units = [{'unit_id': 'U%d' % i, 'template': {'candidate_id': 'C%d' % i, 'scenario_id': 'product_entry',
                                                    'jurisdiction': 'US', 'right_type': 'patent'},
                  'guide': {'included_product_objects': {'PRODUCT': ['DIR-patent']}},
                  'card': {'title': 'Title %d' % i, 'abstract': 'abstract text'}, 'evidence_refs': ['EV-%d' % i],
                  'reading_level': 'abstract', 'exclusion_allowed': i != 2, 'image_id': None if i == 3 else 'IMG-%d' % i}
                 for i in range(4)]
        return {'screen_mode': mode, 'units': units, 'objects': [{'object_id': 'PRODUCT', 'description': '逗猫棒'}]}

    def test_kept_ids_are_validated_and_only_eligible_cards_are_let_go(self):
        import recall_screen as rs
        packet = self.packet()
        with self.assertRaisesRegex(ValueError, 'RECALL_SCREEN_OUTPUT_INVALID'):
            rs.kept_ids({'keep': 'U0'}, packet)
        with self.assertRaisesRegex(ValueError, 'RECALL_SCREEN_UNKNOWN_ID'):
            rs.kept_ids({'keep': ['U9']}, packet)
        rows = rs.decisions(packet, rs.kept_ids({'keep': ['U0']}, packet), 'S1')
        self.assertEqual([row['candidate_id'] for row in rows], ['C1', 'C3'])     # C2 cannot be excluded on its card
        self.assertEqual((rows[0]['decision'], rows[0]['reviewer'], rows[0]['reading_level']),
                         ('not_selected', 'native-recall-screen-S1', 'abstract'))
        self.assertIn('标题与摘要开头', rows[0]['comparison']['applicability_limit'])
        image = self.packet('image')
        rows = rs.decisions(image, rs.kept_ids({'keep': []}, image), 'S1')
        self.assertEqual([row['candidate_id'] for row in rows], ['C0', 'C1', 'C2'])  # C3 has no picture
        self.assertEqual(rows[0]['reading_level'], 'image_comparison')

    def test_small_sets_and_old_tasks_never_run(self):
        import recall_screen as rs
        entries = [{'candidate_id': 'C%d' % i, 'right_type': 'patent'} for i in range(rs.TEXT_MIN - 1)]
        with mock.patch('text_triage_host.pending_entries', return_value=entries), \
                mock.patch('recall_screen.load_json', return_value=TASK):
            self.assertEqual(rs.text_pending('RUN'), [])
        with mock.patch('text_triage_host.pending_entries', return_value=entries * 2 + [{'candidate_id': 'X', 'right_type': 'patent'}]), \
                mock.patch('recall_screen.load_json', return_value=TASK):
            self.assertTrue(rs.text_pending('RUN'))
        with mock.patch('recall_screen.load_json', return_value={}):
            self.assertEqual(rs.text_pending('RUN'), [])
            self.assertEqual(rs.image_pending('RUN'), [])


if __name__ == '__main__':
    unittest.main()


import test_text_triage_host as text_fixture


class ScreenIntegrationTests(text_fixture.TextHostFixture):
    """The text list screen on a real scoped task directory, through the ordinary scheduling and recorder."""

    def screen_native(self, command, prompt, workspace, trace_path, stderr_path, timeout):
        import json
        from types import SimpleNamespace
        from common import load_json
        packet = load_json(trace_path.parent / 'packet.json')
        keep = [unit['unit_id'] for unit in packet['units'] if unit['template']['candidate_id'] == 'P0']
        self.calls.append(sorted(unit['template']['candidate_id'] for unit in packet['units']))
        stderr_path.write_text('synthetic list-screen output only')
        events = [{'type': 'thread.started', 'thread_id': 'screen-1'}, {'type': 'turn.started'},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({'keep': keep})}},
                  {'type': 'turn.completed'}]
        text = '\n'.join(map(json.dumps, events))
        trace_path.write_text(text)
        return SimpleNamespace(returncode=0, pid=7001), text, ''

    def test_let_go_cards_are_recorded_and_kept_or_thin_cards_stay_for_the_hosts(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        from common import atomic_write_json, load_json
        import recall_screen
        import text_triage_host
        task = load_json(self.root / 'task.json')
        task['recall_revision'] = recall.REVISION
        task.pop('candidate_precision_revision', None)     # the r5d20 list-screen contract (r5d21 tasks: screen is triage)
        atomic_write_json(self.root / 'task.json', task)
        with patch.object(recall_screen, 'TEXT_MIN', 1), \
                patch('report_review_host.run_native_logged', side_effect=self.screen_native), \
                patch('review_isolation.select_backend', return_value='macos-sandbox'), \
                patch('native_review_jobs._probe', return_value=[]), \
                patch('macos_review_host.require_chatgpt_auth'), redirect_stdout(StringIO()):
            summary = recall_screen.run(self.root, binary=self.binary, isolation='macos-sandbox', mode='text')
        self.assertEqual(self.calls, [['P0', 'P1', 'P2']])
        self.assertEqual(summary['text']['recorded'], 1)
        rows = {row['candidate_id']: row for row in self.annotations()}
        self.assertEqual(set(rows), {'P1'})
        self.assertEqual((rows['P1']['decision'], rows['P1']['reviewer']), ('not_selected', 'native-recall-screen-screen-1'))
        self.assertIn('检索结果初筛', rows['P1']['reason'])
        left = sorted(entry['candidate_id'] for entry in text_triage_host.pending_entries(self.root))
        self.assertEqual(left, ['P0', 'P2'])          # kept, and a title-only card that cannot be excluded on its card

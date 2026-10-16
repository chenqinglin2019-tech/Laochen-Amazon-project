"""r5d25: fewer, more precise candidates, and three contradictions of the B0GLNPC6K8 / B0H16FDSD8 real runs.

Owner direction (2026-10-15): reliability through fewer, more precise candidates, never through wider searches.
* The head-noun x modifier design group, read newest first, returned trailer connectors, building blocks and ride-on
  cars for the cat teaser (100 results, 2 selected); quoted title phrases with the product's own category name and no
  upper category returned 56 cat toys holding every selected design, and 21 grill baskets holding all five graded.
* Designs graded 中 or 高 carried no comparison, so the frozen report printed them as "已入选待比较".
* The core round reviewed returned searches before merging their cards: "result_count: 0" for 2 and 4 results.
* A search cut by the network was never sent again; final-review sessions cut by the network waited for the pass.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import atomic_write_json, load_json, sha256_json
import recall

CAT = {'article_names': [{'value': value, 'derived_from': 'product.title'} for value in
                         ('cat teaser', 'teaser wand', 'cat wand', 'interactive cat toy', 'electric cat teaser')]
       + [{'value': 'cat toy', 'derived_from': 'product.title', 'broad': True},
          {'value': 'pet toy', 'derived_from': 'product.title', 'broad': True}],
       'function_concepts': [{'label': '电机驱动', 'terms': ['motor', 'motorized', 'electric', 'motor driven'],
                              'derived_from': 'product.bullets'}]}
BASKET = {'article_names': [{'value': value, 'derived_from': 'product.title'} for value in
                            ('rolling grill basket', 'cylindrical grill basket')]
          + [{'value': value, 'derived_from': 'product.title', 'broad': True} for value in
             ('grill basket', 'grilling basket', 'barbecue basket', 'roasting basket')],
          'function_concepts': []}
TASK = {'recall_revision': recall.REVISION, 'created_at': '2026-10-15T04:26:26Z',
        'design_query_revision': recall.TITLE_PHRASES_REVISION}


class TitlePhraseTests(unittest.TestCase):
    def test_the_cat_teaser_gets_one_design_query_of_title_phrases(self):
        terms = recall.compose_terms(CAT, phrases=True)
        designs = [term for term in terms if term['recall_group'] == 'design']
        self.assertEqual([term['value'] for term in designs], ['("cat teaser" OR "teaser wand" OR "cat wand" OR "cat toy")'])
        self.assertEqual(designs[0]['discovery_problem_id'], recall.PHRASES_PROBLEM)
        self.assertNotIn('sort', recall.serpapi_params(TASK, 'design', designs[0]))      # read by relevance

    def test_the_grill_basket_keeps_its_category_names(self):
        designs = [term['value'] for term in recall.compose_terms(BASKET, phrases=True) if term['recall_group'] == 'design']
        self.assertEqual(designs, ['("grill basket" OR "grilling basket" OR "barbecue basket" OR "roasting basket")'])

    def test_utility_queries_drop_the_upper_category(self):
        patents = [term['value'] for term in recall.compose_terms(CAT, phrases=True) if term['recall_group'] == 'patent']
        self.assertEqual(len(patents), 1)
        self.assertIn('"cat toy"', patents[0])
        self.assertNotIn('pet toy', patents[0])

    def test_name_levels(self):
        concepts = {'article_names': [{'value': 'cat teaser'}, {'value': 'cat toy', 'broad': True},
                                      {'value': 'pet toy', 'broad': True}, {'value': 'toy', 'broad': True},
                                      {'value': 'kitchen tool', 'broad': True}]}
        self.assertEqual(recall.name_levels(concepts), (['cat teaser'], [], ['cat toy', 'pet toy', 'toy', 'kitchen tool']))
        concepts['article_names'].insert(1, {'value': 'interactive cat toy'})
        self.assertEqual(recall.name_levels(concepts)[1], ['cat toy'])

    def test_the_recorded_levels_keep_the_specific_names_apart(self):
        import precision
        task = {**TASK, 'query_terms': recall.compose_terms(CAT, phrases=True)}
        self.assertEqual(precision.specific_names(task),
                         ['cat teaser', 'teaser wand', 'cat wand', 'interactive cat toy', 'electric cat teaser'])
        self.assertEqual(precision.broad_names(task), {'cat toy', 'pet toy'})
        self.assertIsNone(precision.title_matches('Cat toy', precision.specific_names(task)))

    def test_a_reviewer_rewrite_never_brings_back_the_upper_category(self):
        import auto_refine
        import precision
        task = {**TASK, 'candidate_precision_revision': precision.REVISION,
                'query_terms': recall.compose_terms(CAT, phrases=True),
                'discovery_semantic_reviews': [{'stage': 'after', 'query_id': 'Q1', 'next_action': 'refine',
                                                'refine_query': {'names': ['pet toy', 'cat wand'], 'functions': ['motor']}}]}
        term = auto_refine._reviewer_term(task, {'query_id': 'Q1', 'right_type': 'patent', 'derived_from': ['product.bullets']})
        self.assertEqual(term['value'], '"cat wand" AND motor')

    def test_tasks_without_the_marker_keep_the_earlier_groups(self):
        terms = recall.compose_terms(CAT)
        self.assertEqual([term['discovery_problem_id'] for term in terms if term['recall_group'] == 'design'],
                         ['recall-v1:design-names', 'recall-v1:design-broad'])
        self.assertFalse(recall.phrases_enabled({'recall_revision': recall.REVISION}))
        self.assertIsNone(recall.recorded_levels({'query_terms': terms}))

    def test_the_phrase_terms_compile_and_record(self):
        from api_first_planning import google_query
        from workflow_v24 import boolean_tokens, term_records
        terms = recall.compose_terms(CAT, phrases=True)
        self.assertEqual(google_query(terms[0]), '( "cat teaser" OR "teaser wand" OR "cat wand" OR "cat toy" )')
        for term in terms:
            boolean_tokens(term['value'])
        base = {'product': {'title': 'Automatic Butterfly Cat Toy'}, 'query_terms': terms, **TASK}
        with mock.patch('discovery_budget.enabled', return_value=True), \
                mock.patch('workflow_v24.recall_integrity_enabled', return_value=False):
            recorded = term_records(base)
        design = [row for row in recorded if row.get('recall_group') == 'design']
        self.assertEqual(len(design), 1)
        self.assertEqual(recall.recorded_levels({'query_terms': recorded})['upper'], ['pet toy'])

    def test_new_tasks_carry_the_marker(self):
        text = (Path(__file__).parent / 'create_task.py').read_text(encoding='utf-8')
        self.assertIn("task['design_query_revision'] = TITLE_PHRASES_REVISION", text)


class GradedDesignComparisonTests(unittest.TestCase):
    def test_a_graded_design_states_its_comparison(self):
        import design_overall
        from report_review_host import CANDIDATE_BINDING_RULE
        self.assertIn(design_overall.GRADED_CLAUSE, design_overall.binding_rule(CANDIDATE_BINDING_RULE))

    def test_the_frozen_report_labels_such_a_row_compared(self):
        from operator_report import _comparison_performed
        row = {'risk': '高', 'comparison': {'criteria': [
            {'criterion': 'article', 'result': 'supports_risk', 'reasoning': '同为烧烤篮', 'evidence_refs': ['EV-1']},
            {'criterion': 'main_body_form', 'result': 'supports_risk', 'reasoning': '等径圆筒网篮', 'evidence_refs': ['EV-1']}]}}
        self.assertTrue(_comparison_performed([row]))
        self.assertFalse(_comparison_performed([{'risk': '高', 'comparison': None}]))     # "已入选待比较" before r5d25


class CoreRoundOrderTests(unittest.TestCase):
    def test_returned_cards_are_merged_before_the_result_review(self):
        import run_pipeline as rp
        with tempfile.TemporaryDirectory() as temp:
            subject = rp.Pipeline(rp.parser().parse_args(['--task-dir', temp]))
            commands = []

            def call(stage, command, **kwargs):
                commands.append([str(part) for part in command])
                return 0, '', ''
            with mock.patch.object(subject, 'call', side_effect=call), \
                    mock.patch.object(subject, 'ready_sources', return_value=1), \
                    mock.patch.object(subject, 'run_parallel', return_value=[(0, '', ''), (0, '', '')]), \
                    mock.patch.object(subject, 'parallel_hosts', return_value={}), \
                    mock.patch.object(subject, 'refine'), \
                    mock.patch.object(subject, 'host_flags', return_value=[]):
                subject.core_round('core', True, [], 1)
        names = [next(Path(part).name for part in command if part.endswith('.py'))
                 + (' ' + command[command.index('--stages') + 1] if '--stages' in command else '') for command in commands]
        self.assertLess(names.index('merge_candidates.py'), names.index('discovery_review_host.py after'))
        self.assertLess(names.index('triage_defaults.py'), names.index('discovery_review_host.py after'))
        self.assertLess(names.index('advance_work.py'), names.index('merge_candidates.py'))


class NetworkRetryTests(unittest.TestCase):
    def setUp(self):
        import pipeline_robust
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = {'query_id': 'QRY-1', 'q': '("cat toy") AND (touch OR wake)', 'right_type': 'patent', 'jurisdiction': 'US',
                    'operation': 'search'}
        atomic_write_json(self.root / 'task.json', {
            'task_id': 'T', 'pipeline_robust_revision': pipeline_robust.REVISION,
            'retrieval_workflow_revision': 'api-first-v3', 'assessment_revision': 'known-findings-risk-v1',
            'presentation_policy_revision': 'operator-report-v1',
            'continuous_recovery_revision': 'continuous-recovery-stage-b-v1'})
        atomic_write_json(self.root / 'search-plan.json', {'queries': {'serpapi_google_patents': [self.row]}})

    def write_runs(self, *codes, raw=False):
        runs = [{'run_id': 'ATT-%d' % index, 'query_id': 'QRY-1', 'provider': 'serpapi_google_patents',
                 'operation': 'search', 'jurisdiction': 'US', 'right_type': 'patent', 'status': 'failed',
                 'submission_state': 'submitted', 'error_code': code, 'raw_paths': ['raw/x.json'] if raw else [],
                 'request_params': {'q': self.row['q'], 'num': 100, 'country': 'US', 'right_type': 'patent'},
                 'plan_entry_sha256': sha256_json(self.row)} for index, code in enumerate(codes)]
        atomic_write_json(self.root / 'evidence.json', {'task_id': 'T', 'source_runs': runs})

    def state(self):
        import recovery_stage_b
        return recovery_stage_b.recovery_state(load_json(self.root / 'task.json'), load_json(self.root / 'evidence.json'),
                                               'serpapi_google_patents', self.row)['state']

    def test_a_search_cut_by_the_network_is_sent_once_more(self):
        import pipeline_robust
        self.write_runs('PROVIDER_NETWORK_ERROR')
        self.assertEqual(self.state(), 'awaiting_review')
        self.assertEqual(pipeline_robust.retry_network_failures(self.root)['retry_allowed'], ['ATT-0'])
        self.assertEqual(self.state(), 'ready')
        self.assertEqual(pipeline_robust.retry_network_failures(self.root)['recorded'], 0)      # once

    def test_a_second_failure_stays_a_limitation(self):
        import pipeline_robust
        self.write_runs('PROVIDER_NETWORK_ERROR', 'PROVIDER_NETWORK_ERROR')
        self.assertEqual(pipeline_robust.retry_network_failures(self.root)['recorded'], 0)
        self.assertEqual(self.state(), 'blocked')

    def test_other_failures_are_left_alone(self):
        import pipeline_robust
        self.write_runs('PROVIDER_RATE_LIMITED')
        self.assertEqual(pipeline_robust.retry_network_failures(self.root)['recorded'], 0)
        self.write_runs('PROVIDER_NETWORK_ERROR', raw=True)            # an answer was received and kept
        self.assertEqual(pipeline_robust.retry_network_failures(self.root)['recorded'], 0)


class ImmediateRerunTests(unittest.TestCase):
    class Proc:
        def __init__(self, code):
            self.returncode = code

    def test_a_cut_session_runs_again_in_its_own_worker(self):
        import module_review
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(root, ignore_errors=True))
        jobs = [{'command': [name], 'prompt': 'x' * size, 'workspace': root, 'trace_path': root / name,
                 'stderr_path': root / ('e' + name)} for name, size in (('a', 10), ('b', 20))]
        fresh = {'command': ['a2'], 'prompt': 'x', 'workspace': root, 'trace_path': root / 'a2', 'stderr_path': root / 'ea2'}
        started = []

        def run(command, *args):
            started.append(command[0])
            return (self.Proc(1 if command[0] == 'a' else 0), command[0], '')
        rerun = mock.Mock(side_effect=lambda job, outcome: fresh if job['command'] == ['a'] else None)
        with mock.patch('report_review_host.run_native_logged', side_effect=run):
            outcomes = module_review.run_jobs(jobs, 30, 2, rerun=rerun)
        self.assertEqual([text for _, text, _ in outcomes], ['a2', 'b'])
        self.assertEqual(sorted(started), ['a', 'a2', 'b'])
        self.assertEqual(rerun.call_count, 2)

    def test_six_model_slots(self):
        import model_slots
        self.assertEqual(model_slots.SLOTS, 6)


class SearchBoundaryTests(unittest.TestCase):
    def test_the_newest_design_grant_in_the_results(self):
        import module_review
        candidates = {'patents': [
            {'right_type': 'design', 'publication_number': 'USD1143364S1', 'grant_date': '2026-08-18',
             'candidate_nature': 'patent_search_result'},
            {'right_type': 'design', 'publication_number': 'USD1019021S1', 'publication_date': '2024-03-19',
             'candidate_nature': 'patent_search_result'},
            {'right_type': 'patent', 'publication_number': 'US12507671B1', 'grant_date': '2026-09-30',
             'candidate_nature': 'patent_search_result'}]}
        boundary = module_review.design_search_boundary(candidates)
        self.assertEqual((boundary['latest_us_design_grant_in_results'], boundary['us_design_results']), ('2026-08-18', 2))
        self.assertIn('2026-08-18', boundary['note'])
        self.assertIsNone(module_review.design_search_boundary({'patents': []}))


if __name__ == '__main__':
    unittest.main()

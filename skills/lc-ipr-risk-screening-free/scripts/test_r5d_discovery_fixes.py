"""r5d fixes from the r5c real run: claim-style terms first, the reviewer's "search again" carried out by the program,
bounded closure of exhausted purposes, marketplace listing cards, product images in discovery reviews, API media
classification, design-patent comparison and the marking stage after discovery."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("LC_IPR_OFFLINE_TESTS", "1")

TERM = {'kind': 'function', 'derived_from': 'product.title', 'language': 'en', 'strategy': 'boolean'}


class UnderstandingTermTests(unittest.TestCase):
    def scope(self):
        return {'scope': {'facts': [{'source_path': 'product.title'}, {'source_path': 'product.bullets[0]'},
                                    {'source_path': 'images[0].sha256'}], 'objects': [{}]}}

    def test_promotion_words_are_removed_and_short_leftovers_dropped(self):
        import product_understanding_host as host
        self.assertEqual(host.clean_term('universal lid securing strap'), 'lid securing strap')
        self.assertEqual(host.clean_term('Reusable Premium strap'), '')

    def test_model_terms_come_before_the_program_fallback(self):
        import product_understanding_host as host
        analysis = {'product': {}, 'analysis': {}, 'query_terms': [
            {'value': 'lid securing strap', 'kind': 'design', 'language': 'en', 'derived_from': 'product.title'},
            {'value': 'lid securing strap', 'kind': 'function', 'language': 'en', 'derived_from': 'product.title'},
            {'value': 'flexible silicone latch straps', 'kind': 'structural_feature', 'language': 'en',
             'derived_from': 'product.bullets[0]'}]}
        raw = {'query_terms': [{'value': 'universal casserole lid strap', 'kind': 'function', 'derived_from': 'product.title'},
                               {'value': 'strap openings knob', 'kind': 'structural_feature', 'derived_from': 'images[0].sha256'}]}
        with patch.object(host, 'dry_validate', lambda *a: True), patch.object(host, 'clue_dispositions', lambda *a: []):
            _, result, _ = host.apply_refinement({'product': {'bullets': ['b']}}, {}, self.scope(), analysis, raw)
        values = [(row['kind'], row['value']) for row in result['query_terms']]
        self.assertEqual(values, [('design', 'lid securing strap'), ('function', 'casserole lid strap'),
                                  ('structural_feature', 'strap openings knob')])

    def test_a_term_from_a_path_that_is_not_a_scope_fact_is_rejected(self):
        import product_understanding_host as host
        raw = {'query_terms': [{'value': 'lid strap', 'kind': 'function', 'derived_from': 'product.bullets[3]'}]}
        analysis = {'product': {}, 'analysis': {}, 'query_terms': []}
        with patch.object(host, 'dry_validate', lambda *a: True), self.assertRaises(ValueError):
            host.apply_refinement({'product': {'bullets': ['a', 'b', 'c', 'd']}}, {}, self.scope(), analysis, raw)

    def test_prompt_names_the_allowed_sources(self):
        import product_understanding_host as host
        text = host.native_prompt({'product': {'title': 't'}}, {'product.title', 'images[0].sha256'})
        self.assertIn('derived_from 只能取 product.title', text)
        self.assertIn('images[0].sha256', text)
        self.assertIn('universal', text)


class AutoRefineTests(unittest.TestCase):
    def task(self):
        return {'task_id': 'T', 'discovery_refinement_revision': 'auto-refine-v1', 'epo_query_revision': 'ops-cql-v1',
                'retrieval_policy': {'max_refinement_rounds': 2}}

    def plan(self, rows):
        terms = [{**TERM, 'value': 'universal lid securing strap'}, {**TERM, 'value': 'casserole dish lid strap'},
                 {**TERM, 'value': 'lid securing strap'}, {**TERM, 'kind': 'brand', 'value': 'Mella'},
                 {**TERM, 'value': 'slow cooker lid strap', 'derived_from': 'product.bullets[0]'}]
        return {'terms': terms, 'queries': rows}

    def row(self, value, provider='epo_ops', round_=0, query_id='Q1', parent=None):
        from api_first_planning import provider_params
        q = provider_params(provider, {**TERM, 'value': value}, 'US', 'patent', epo_query_revision='ops-cql-v1')['q']
        row = {'query_id': query_id, 'q': q, 'jurisdiction': 'US', 'right_type': 'patent', 'search_dimension': 'text',
               'discovery_intent_id': 'INT-1', 'derived_from': ['product.title'], 'refinement_round': round_,
               'discovery_role': 'refinement' if parent else 'primary'}
        if parent:
            row['parent_query_id'] = parent
        return row

    def test_next_unused_term_of_the_same_clue_on_the_same_engine_first(self):
        import auto_refine
        primary = self.row('universal lid securing strap')
        plan = self.plan({'epo_ops': [primary]})
        with patch('common.serpapi_free_enabled', lambda task: True), patch.object(auto_refine, '_budget_left', lambda *a: True):
            options = auto_refine.options(self.task(), plan, {}, 'epo_ops', primary)
        self.assertEqual([(engine, term['value']) for engine, term in options][:2],
                         [('epo_ops', 'casserole dish lid strap'), ('epo_ops', 'lid securing strap')])
        self.assertNotIn('Mella', [term['value'] for _, term in options])

    def test_second_rewrite_moves_to_google_patents_and_skips_used_expressions(self):
        import auto_refine
        primary = self.row('universal lid securing strap')
        child = self.row('casserole dish lid strap', round_=1, query_id='Q2', parent='Q1')
        plan = self.plan({'epo_ops': [primary, child]})
        with patch('common.serpapi_free_enabled', lambda task: True), patch.object(auto_refine, '_budget_left', lambda *a: True):
            options = auto_refine.options(self.task(), plan, {}, 'epo_ops', child)
        self.assertEqual(options[0][0], 'serpapi_google_patents')
        self.assertNotIn('casserole dish lid strap', [term['value'] for engine, term in options if engine == 'epo_ops'])
        self.assertTrue(auto_refine.has_child(plan, primary))
        self.assertFalse(auto_refine.has_child(plan, child))

    def test_round_limit_or_no_budget_means_exhausted(self):
        import auto_refine
        leaf = self.row('lid securing strap', round_=2, query_id='Q3', parent='Q2')
        plan = self.plan({'epo_ops': [leaf]})
        self.assertTrue(auto_refine.exhausted(self.task(), plan, {}, 'epo_ops', leaf))
        primary = self.row('universal lid securing strap')
        with patch('common.serpapi_free_enabled', lambda task: False), patch.object(auto_refine, '_budget_left', lambda *a: False):
            self.assertTrue(auto_refine.exhausted(self.task(), self.plan({'epo_ops': [primary]}), {}, 'epo_ops', primary))

    def test_rights_without_text_terms_are_never_rewritten(self):
        import auto_refine
        row = {**self.row('universal lid securing strap'), 'right_type': 'copyright'}
        self.assertEqual(auto_refine.options(self.task(), self.plan({'serper_images': [row]}), {}, 'serper_images', row), [])

    def test_disabled_for_tasks_without_the_marker(self):
        import auto_refine
        self.assertFalse(auto_refine.enabled({'task_id': 'T'}))
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'task.json').write_text('{"task_id": "T"}', encoding='utf-8')
            self.assertEqual(auto_refine.run(Path(tmp))['status'], 'not_enabled')


class AutoRefineRunTests(unittest.TestCase):
    def setup_root(self, root, plan=None, evidence=None):
        for name in ('task.json', 'normalized-candidates.json', 'materiality-annotations.json'):
            (root / name).write_text(json.dumps({'discovery_refinement_revision': 'auto-refine-v1'}), encoding='utf-8')
        (root / 'search-plan.json').write_text(json.dumps(plan or {'queries': {}}), encoding='utf-8')
        (root / 'evidence.json').write_text(json.dumps(evidence or {'source_runs': []}), encoding='utf-8')

    def test_a_refinement_is_appended_and_exhaustion_stops(self):
        import auto_refine
        calls = []
        row = {'query_id': 'Q1', 'right_type': 'patent'}
        entry = {'reason': auto_refine.REPLAN_REASON, 'query_id': 'Q1', 'source_run_id': 'R1'}
        common = [patch.object(auto_refine, 'pending', lambda root: [entry]),
                  patch('workflow_v24.plan_row_index', lambda plan: {'Q1': [('epo_ops', row)]}),
                  patch('workflow_v24.scenario_supplement', lambda *a, **k: {}),
                  patch('api_first_planning.triage_digest', lambda *a, **k: 'd'),
                  patch('api_first_planning.append_followup',
                        lambda root, request: calls.append(request) or {'query_id': 'Q2'})]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_root(root)
            for item in common:
                item.start()
            try:
                with patch.object(auto_refine, 'options', lambda *a: [('epo_ops', {**TERM, 'value': 'lid securing strap'})]):
                    summary = auto_refine.run(root)
                self.assertEqual([call['role'] for call in calls], ['refinement'])
                self.assertEqual(summary['refined'][0]['refinement_query_id'], 'Q2')
                calls.clear()
                with patch.object(auto_refine, 'options', lambda *a: []):
                    summary = auto_refine.run(root)
                self.assertEqual([(call['role'], call['outcome']) for call in calls], [('review', 'stop_bounded_discovery')])
            finally:
                for item in common:
                    item.stop()

    def test_the_parent_expression_closes_only_after_its_follow_up_returned(self):
        import auto_refine
        from common import sha256_json
        parent = {'query_id': 'Q1', 'action_purpose': 'discovery', 'discovery_role': 'primary'}
        child = {'query_id': 'Q2', 'action_purpose': 'discovery', 'discovery_role': 'refinement', 'parent_query_id': 'Q1'}
        plan = {'queries': {'epo_ops': [parent, child]}}
        run = lambda q, row, rid: {'run_id': rid, 'provider': 'epo_ops', 'query_id': q, 'plan_entry_sha256': sha256_json(row),
                                   'status': 'no_result', 'submission_state': 'submitted'}
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('api_first_planning.current_followup_review', lambda *a: None), \
                    patch('api_first_planning.triage_digest', lambda *a, **k: 'd'), \
                    patch('workflow_v24.scenario_supplement', lambda *a, **k: {}), \
                    patch('api_first_planning.append_followup', lambda root, request: calls.append(request)):
                self.setup_root(root, plan, {'source_runs': [run('Q1', parent, 'R1')]})
                summary = {'parents_closed': [], 'skipped': []}
                auto_refine.close_carried_parents(root, summary)
                self.assertEqual(calls, [])
                self.setup_root(root, plan, {'source_runs': [run('Q1', parent, 'R1'), run('Q2', child, 'R2')]})
                auto_refine.close_carried_parents(root, summary)
            self.assertEqual([(call['parent_query_id'], call['source_run_id'], call['outcome']) for call in calls],
                             [('Q1', 'R1', 'stop_bounded_discovery')])
            self.assertEqual(summary['parents_closed'], ['Q1'])


class ProgressRegistrationTests(unittest.TestCase):
    def test_a_new_unsubmitted_row_is_registered_without_waiting_for_a_deferral(self):
        import mechanical_ledger
        recorded = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'task.json').write_text(json.dumps({'discovery_refinement_revision': 'auto-refine-v1',
                'assessment_scenarios': [{'scenario_id': 'product_entry'}]}), encoding='utf-8')
            (root / 'search-plan.json').write_text(json.dumps({'queries': {'serpapi_google_patents': [
                {'query_id': 'Q-OLD'}, {'query_id': 'Q-NEW'}]}}), encoding='utf-8')
            (root / 'evidence.json').write_text('{"source_runs": []}', encoding='utf-8')
            item = lambda entry: ({'item_id': 'ITEM-' + entry['query_id'], 'kind': 'query', 'query_id': entry['query_id'],
                                   'module_ids': ['technical']}, None)
            with patch('host_triage.enabled', lambda task: True), \
                    patch('review_progress_stage_a.enabled', lambda task: True), \
                    patch('review_progress_stage_a._events', lambda evidence: [{'kind': 'initialize'}]), \
                    patch('review_progress_stage_a.ledger', lambda task, evidence: {'items': [
                        {'kind': 'query', 'provider': 'serpapi_google_patents', 'query_id': 'Q-OLD'}]}), \
                    patch('review_progress_stage_a.record_event', lambda root, request: recorded.append(request)), \
                    patch('workflow_v24.work_view_from_dir', lambda root: {'entries': []}), \
                    patch('input_template.progress_item', lambda task, plan, entry: item(entry)), \
                    patch('input_template.progress_defaults', lambda value: value), \
                    patch.object(mechanical_ledger, '_progress_upstream', lambda *a: 'EV-UP'):
                outcome = mechanical_ledger.auto_review_progress(root)
        self.assertEqual(outcome['registered'], 1)
        self.assertEqual([entry['query_id'] for entry in recorded[0]['items']], ['Q-NEW'])


class MemoKeyTests(unittest.TestCase):
    def test_temporary_dot_files_do_not_enter_the_view_key(self):
        import work_view_memo
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'task.json').write_text('{}', encoding='utf-8')
            key = work_view_memo.state_key(root, {})
            (root / '.task.json.tmp123').write_text('x', encoding='utf-8')
            self.assertEqual(work_view_memo.state_key(root, {}), key)


class ExhaustedWaitTests(unittest.TestCase):
    def test_exhausted_stopped_search_is_a_bounded_limitation(self):
        import discovery_semantics as ds
        task = {'discovery_refinement_revision': 'auto-refine-v1'}
        after = {'problem_covered': False, 'next_action': 'refine'}
        stop = {'outcome': 'stop_bounded_discovery'}
        with patch('auto_refine.exhausted', lambda *a: True), \
                patch('api_first_planning.current_followup_review', lambda *a: stop), \
                patch('api_first_planning.review_validation', lambda *a: None), \
                patch('api_first_planning.source_files_error', lambda *a: None):
            self.assertIs(ds.refinement_exhausted_wait(task, {}, {}, {}, {}, None, Path('.'), 'epo_ops', {}, after,
                                                       {'run_id': 'R'}), stop)
            self.assertIsNone(ds.refinement_exhausted_wait({}, {}, {}, {}, {}, None, Path('.'), 'epo_ops', {}, after,
                                                           {'run_id': 'R'}))
            self.assertIsNone(ds.refinement_exhausted_wait(task, {}, {}, {}, {}, None, Path('.'), 'epo_ops', {},
                                                           {**after, 'problem_covered': True}, {'run_id': 'R'}))
        with patch('auto_refine.exhausted', lambda *a: False):
            self.assertIsNone(ds.refinement_exhausted_wait(task, {}, {}, {}, {}, None, Path('.'), 'epo_ops', {}, after,
                                                           {'run_id': 'R'}))


class RoutingTests(unittest.TestCase):
    def test_us_patent_text_never_goes_to_serper_patents_on_new_tasks(self):
        import api_first_planning as ap
        task = {'retrieval_workflow_revision': 'api-first-v3', 'discovery_refinement_revision': 'auto-refine-v1'}
        caps = {'epo_ops': {'executable': True}}
        with patch('common.serper_free_enabled', lambda task: True), patch('common.serpapi_free_enabled', lambda task: True), \
                patch('common.signa_free_enabled', lambda task: False):
            new = list(ap._preferred_providers(task, 'patent', {**TERM, 'value': 'lid strap'}, caps, 'US'))
            old = list(ap._preferred_providers({**task, 'discovery_refinement_revision': None}, 'patent',
                                               {**TERM, 'value': 'lid strap'}, caps, 'US'))
        self.assertNotIn('serper_patents', new)
        self.assertEqual(new[0], 'epo_ops')
        self.assertIn('serpapi_google_patents', new)
        self.assertIn('serper_patents', old)


class MarketplaceRuleTests(unittest.TestCase):
    def card(self, url, title='3-Pack Silicone Latch Strap for Slow Cooker Lid'):
        return {'right_type': 'unknown', 'candidate_nature': 'visual_match', 'url': url, 'title': title}

    def test_marketplace_listing_cards_are_default_not_selected_on_new_tasks(self):
        import triage_defaults as td
        identity = {'brand': 'mella', 'stem': 'lid latch the reusable', 'title_prefix': '', 'asins': []}
        self.assertEqual(td.rule_for(self.card('https://www.ebay.com/itm/398372342204'), identity, marketplace=True),
                         'marketplace')
        self.assertIsNone(td.rule_for(self.card('https://www.ebay.com/itm/398372342204'), identity))
        self.assertIsNone(td.rule_for(self.card('https://mellahome.com/products/x'), identity, marketplace=True))
        self.assertIsNone(td.rule_for(self.card('https://www.amazon.com/clp/B0X', 'Strap US 11401089 B2 patented'),
                                      identity, marketplace=True))
        self.assertIsNone(td.rule_for(self.card('https://www.amazon.com/clp/B0X', 'Lid strap patent infringement lawsuit'),
                                      identity, marketplace=True))
        self.assertIsNone(td.rule_for({**self.card('https://www.amazon.com/clp/B0X'), 'right_type': 'design'},
                                      identity, marketplace=True))


class MaterialClassificationTests(unittest.TestCase):
    def test_api_media_rows_and_identical_copies_are_public_originals(self):
        import review_material_policy as rmp
        packet = {'task': {}, 'evidence': {'collections': {
            'patents': [{'evidence_id': 'EV-1', 'payload': {'media': [
                {'path': '/r/media/a.png', 'sha256': 'a' * 64, 'url': 'https://patentimages.example/a.png', 'source_field': 'images[0]'},
                {'path': '/r/media/b.png', 'sha256': 'b' * 64}]}}],
            'sources': [{'evidence_id': 'EV-2', 'path': '/r/dossier/b.png', 'sha256': 'b' * 64,
                         'source_url': 'https://patentimages.example/b.png'},
                        {'evidence_id': 'EV-3', 'path': '/r/screens/c.png', 'sha256': 'c' * 64, 'url': 'https://x/c'}]}}}
        with patch('report_review_host.review_payload_view', lambda value: value):
            rows = {row['path']: row['public'] for row in rmp.file_inventory(packet)}
        self.assertEqual(rows, {'/r/media/a.png': True, '/r/media/b.png': True, '/r/dossier/b.png': True,
                                '/r/screens/c.png': False})


class DesignComparisonTests(unittest.TestCase):
    def unit(self):
        return {'unit_id': 'CMP-1', 'kind': 'design', 'candidate_id': 'C', 'scenario_id': 'product_entry',
                'jurisdiction': 'US', 'right_type': 'design', 'intake_event_id': 'I', 'claims_material_event_id': 'M',
                'document_version': 'v', 'claims_evidence_ref': 'EV-R', 'product_evidence_ref': 'EV-P',
                'publication_number': 'USD887770S1', 'title': 'Lid to pot secure device', 'design_claim': 'ornamental',
                'listed_views': 3, 'views': [{'view_id': 'D00000', 'attachment': 'd0.png', 'evidence_id': 'EV-D0'},
                                             {'view_id': 'D00001', 'attachment': 'd1.png', 'evidence_id': 'EV-D1'}]}

    def answer(self, **extra):
        row = {'unit_id': 'CMP-1', 'product_state': '使用状态', 'overall_visual_relationship': '整体视觉印象不同',
               'perspective_limitations': '无底面角度', 'similarities': ['跨盖'], 'differences': ['交叉带'], 'unknowns': [],
               'views': [{'view_id': 'D00000', 'result': 'unknown', 'reasoning': '无此角度', 'image_ids': [],
                          'right_location': '', 'product_location': ''},
                         {'view_id': 'D00001', 'result': 'differs', 'reasoning': '带体形态不同', 'image_ids': ['IMG-001'],
                          'right_location': '附图带体', 'product_location': '主图带体'}],
               'design_scope_parts': [{'part_id': 'strap_body', 'description': '带体', 'treatment': 'claimed',
                                       'interpretation_basis': '实线'}]}
        row.update(extra)
        return row

    def test_views_are_validated_and_recorded_as_design_inventory_and_comparison(self):
        import comparison_host as ch
        decision = ch.design_decision(self.answer(), self.unit(), {'IMG-001'}, 's1')
        request = ch.transaction_request(decision, 'native-comparison-s1', 'FB-1')
        inventory, close = request['events']
        self.assertEqual(inventory['units'][0]['kind'], 'design')
        self.assertEqual(inventory['units'][0]['necessary_views'], ['D00000', 'D00001'])
        self.assertIn('3 幅附图', inventory['completeness_reasoning'])
        comparison = close['comparison']
        self.assertEqual(comparison['registered_basis'], 'registered')
        self.assertEqual([view['right_evidence_refs'] for view in comparison['views']], [['EV-D0'], ['EV-D1']])
        self.assertEqual(close['gap']['product_feedback_request_id'], 'FB-1')
        self.assertIn('1 幅未取回', comparison['perspective_limitations'])
        self.assertFalse(ch.screening(decision))

    def test_unknown_scope_part_missing_view_or_unsupported_difference_is_rejected(self):
        import comparison_host as ch
        broken = [self.answer(design_scope_parts=[{'part_id': 'strap', 'treatment': 'unknown', 'interpretation_basis': 'x'}]),
                  self.answer(views=self.answer()['views'][:1]),
                  self.answer(views=[self.answer()['views'][0], {**self.answer()['views'][1], 'image_ids': []}]),
                  self.answer(overall_visual_relationship='相似度 80%')]
        for raw in broken:
            with self.assertRaises(ValueError):
                ch.design_decision(raw, self.unit(), {'IMG-001'}, 's1')


class DiscoveryImageTests(unittest.TestCase):
    def test_an_image_fact_is_shown_as_the_attached_image(self):
        import discovery_review_host as host
        scope = {'facts': [{'fact_id': 'F-VIEW', 'source_path': 'images[0].sha256', 'value': 'a' * 64, 'status': 'confirmed'},
                           {'fact_id': 'F-TITLE', 'source_path': 'product.title', 'value': 'Lid Latch', 'status': 'confirmed'}]}
        images = {'a' * 64: {'image_id': 'IMG-001', 'attachment': 'image-aaa.jpg'}}
        self.assertIn('附图 image-aaa.jpg', host._clue_text(scope, 'fact:F-VIEW', images)['text'])
        self.assertEqual(host._clue_text(scope, 'fact:F-TITLE', images)['text'], 'Lid Latch')
        self.assertIn('不要要求补原图', host.prompt({'stage': 'direction', 'units': []}))


class MarkingStageTests(unittest.TestCase):
    def test_marking_follows_discovery(self):
        import run_pipeline as rp
        self.assertLess(rp.STAGES.index('core'), rp.STAGES.index('marking'))
        self.assertLess(rp.STAGES.index('marking'), rp.STAGES.index('readiness'))
        self.assertLess(rp.STAGES.index('sources'), rp.STAGES.index('marking'))

    def test_a_compared_patent_without_differing_elements_resolves_the_marking(self):
        import run_pipeline as rp
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / 'checkpoints').mkdir()
            (run / 'task.json').write_text(json.dumps({'target_jurisdictions': ['US'], 'query_terms': [{'value': 'x'}],
                'specialty_analysis_events': [
                    {'kind': 'comparison', 'candidate_id': 'C1', 'unit_id': 'u1',
                     'elements': [{'result': 'corresponds'}, {'result': 'unknown'}]},
                    {'kind': 'comparison', 'candidate_id': 'C2', 'unit_id': 'u1',
                     'elements': [{'result': 'differs'}, {'result': 'corresponds'}]}]}), encoding='utf-8')
            (run / 'evidence.json').write_text(json.dumps({'collections': {'patents': [
                {'evidence_id': 'EV-1', 'payload': {'publication_number': 'US11401089B2', 'title': 'Securing a lid'}},
                {'evidence_id': 'EV-2', 'payload': {'publication_number': 'US6058808A', 'title': 'Waste drum'}}]}}),
                encoding='utf-8')
            (run / 'core-dossier.json').write_text(json.dumps({'candidates': [
                {'candidate_id': 'C1', 'right_type': 'patent', 'jurisdiction': 'US', 'detail_evidence_id': 'EV-1'},
                {'candidate_id': 'C2', 'right_type': 'patent', 'jurisdiction': 'US', 'detail_evidence_id': 'EV-2'}]}),
                encoding='utf-8')
            args = rp.parser().parse_args(['--task-dir', str(run), '--skip-auth'])
            pipeline = rp.Pipeline(args)
            calls = []
            with patch.object(rp.Pipeline, 'marking_entry', lambda self: {'reason': 'PATENT_MARKING_RESOLUTION_REQUIRED'}), \
                    patch.object(rp.Pipeline, 'call', lambda self, stage, command, **k: calls.append(command) or (0, '{}', '')):
                outcome = pipeline.s_marking()
            self.assertEqual(outcome['candidates'], ['US11401089B2'])
            payload = json.loads((run / 'checkpoints' / '1b-marking-auto.json').read_text(encoding='utf-8'))
            followup = payload['product']['patent_claim_followup']
            self.assertEqual(followup['evidence_ids'], ['EV-1'])
            self.assertIn('未经权利人或官网确认', followup['findings'])
            self.assertTrue(any('--revise' in command for command in calls))


if __name__ == '__main__':
    unittest.main()

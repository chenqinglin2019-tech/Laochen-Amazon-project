"""Real provenance/visual scope routes, without live calls or credentials."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import common
import product_scope as ps
from api_first_planning import (_eligible_scope_terms, _scope_image_term,
                                _preferred_providers, provider_params)
from coverage_v3 import build_requirements


class PublicRouteTests(unittest.TestCase):
    def task(self, revision='api-first-v3'):
        return {'schema_version': '2.4-free', 'retrieval_workflow_revision': revision,
                'public_discovery_routing_revision': 'public-discovery-v1',
                'decision_workflow_revision': 'scenario-triage-v1',
                'workflow_correction_revision': 'workflow-correction-v1',
                'retrieval_policy': {'enabled': True},
                'serper_free_enhancement': common.serper_free_enhancement(True, revision),
                'serpapi_free_enhancement': common.serpapi_free_enhancement(True, revision),
                'signa_free_enhancement': common.signa_free_enhancement(False),
                'product_scope_revision': ps.REVISION,
                'product_scope': {'status': 'reviewed', 'objects': [{
                    'object_id': 'animal', 'scope_status': 'included',
                    'right_types': ['copyright', 'trade_dress', 'unregistered_design'],
                    'visual_evidence': {'image_ids': ['IMG-001']}}], 'facts': [],
                    'directions': [{'direction_id': 'animal-' + right,
                        'scenario_id': 'product_entry', 'right_type': right,
                        'fact_ids': [], 'object_ids': ['animal']} for right in
                        ('copyright', 'trade_dress', 'unregistered_design', 'enforcement')]}}

    def test_provenance_stays_separate_from_recall_in_every_territory(self):
        for country in ('US', 'GB', 'EU', 'FR', 'DE', 'IT', 'ES', 'JP'):
            for right in ('copyright', 'trade_dress', 'unregistered_design'):
                task = self.task()
                original = {'requirement_id': 'COV-%s-%s-PROVENANCE' % (country, right),
                    'jurisdiction': country, 'right_type': right, 'phase': 'provenance',
                    'required_for': 'low_risk', 'completion_policy': 'any',
                    'required_axes': ['provenance', 'visual_comparison'],
                    'routes': [{'provider': 'asset_provenance', 'operation': 'provenance_review',
                                'method': 'agent', 'priority': 1, 'required': False}]}
                before = deepcopy(original)
                result = build_requirements(task, [original])
                self.assertEqual(original, before)
                self.assertEqual(result[0], before)
                self.assertEqual(result[1]['phase'], 'official_recall')
                self.assertEqual(result[1]['required_for'], 'discovery_only')
                self.assertEqual({r['provider'] for r in result[1]['routes']},
                                 {'serpapi_google_lens', 'serper_images', 'serper_web'})
                task.pop('public_discovery_routing_revision')
                self.assertEqual(build_requirements(task, [original]), [original])
                task['retrieval_workflow_revision'] = 'api-first-v2'
                self.assertEqual(build_requirements(task, [original]), [original])

    def test_image_clue_reaches_scope_without_text_or_invented_fact(self):
        task = self.task()
        before = deepcopy(task)
        image = {'image_id': 'IMG-001', 'source_url': 'https://example.test/main.jpg'}
        for right in ('copyright', 'trade_dress', 'unregistered_design'):
            term = _scope_image_term(task, image, right)
            self.assertEqual(term['derived_from'], 'product.scope_objects[0]')
            self.assertTrue(ps.term_allowed(task, term, right))
            self.assertEqual(term['value'], image['source_url'])
            self.assertEqual(list(_preferred_providers(task, right, term, {}, 'US')),
                             ['serpapi_google_lens'])
        self.assertEqual(task, before)
        self.assertIsNone(_scope_image_term(task, {**image, 'image_id': 'OTHER'}, 'copyright'))
        task['product_scope']['objects'][0]['scope_status'] = 'default_excluded'
        self.assertIsNone(_scope_image_term(task, image, 'copyright'))
        task['product_scope']['objects'][0]['scope_status'] = 'included'
        task['product_scope']['directions'] = []
        self.assertIsNone(_scope_image_term(task, image, 'copyright'))

    def test_enforcement_rejects_placeholder_and_unbound_terms(self):
        task = self.task()
        terms = [{'kind': 'design', 'value': 'plush rabbit ball', 'language': 'en',
                  'derived_from': 'product.scope_objects[0]'},
                 {'kind': 'manufacturer', 'value': 'Generic', 'language': 'en',
                  'derived_from': 'product.scope_objects[0]'},
                 {'kind': 'product', 'value': 'unrelated product', 'language': 'en',
                  'derived_from': 'product.title'}]
        self.assertEqual(_eligible_scope_terms(task, terms, 'US', 'enforcement'), terms[:1])
        task['product_scope']['directions'] = []
        self.assertEqual(_eligible_scope_terms(task, terms, 'US', 'enforcement'), [])

    def test_enforcement_wire_expression_and_legacy_contract(self):
        term = {'kind': 'design', 'value': 'plush rabbit ball', 'strategy': 'phrase'}
        for country in ('US', 'GB', 'EU', 'DE', 'FR', 'JP'):
            result = provider_params('serper_web', term, country, 'enforcement',
                                     retrieval_revision='api-first-v3',
                                     public_discovery_revision='public-discovery-v1')
            self.assertIn('"plush rabbit ball"', result['q'])
            self.assertIn('lawsuit OR litigation OR infringement', result['q'])
            self.assertNotIn('product_dependencies', result)
        self.assertEqual(provider_params('serper_web', term, 'US', 'enforcement',
            retrieval_revision='api-first-v2')['q'], '"plush rabbit ball"')

    def test_full_plan_reaches_image_only_copyright_and_bound_enforcement(self):
        import test_product_scope as fixture_module
        from workflow_v24 import build_coverage_requirements_v24, generate_plan
        fixture = fixture_module.ScopeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.data['scope']['objects'][1].update(
            right_types=['copyright', 'trade_dress'],
            visual_evidence={'image_ids': ['IMG-001']})
        # No copyright direction consumes the English title term.
        fixture.data['scope']['directions'][2]['fact_ids'] = []
        fixture.data['scope']['directions'].extend([
            {'direction_id':'dress', 'scenario_id':'product_entry', 'right_type':'trade_dress',
             'fact_ids':[], 'object_ids':['pattern'], 'reason':'Visible appearance.'},
            {'direction_id':'signals', 'scenario_id':'product_entry', 'right_type':'enforcement',
             'fact_ids':['shape'], 'object_ids':['pattern'], 'reason':'Related product signals.'}])
        task = common.load_json(fixture.run / 'task.json')
        task.update(retrieval_workflow_revision='api-first-v3', source_operation_revision='source-operation-v2',
                    public_discovery_routing_revision='public-discovery-v1',
                    serper_free_enhancement=common.serper_free_enhancement(True, 'api-first-v3'),
                    serpapi_free_enhancement=common.serpapi_free_enhancement(True, 'api-first-v3'))
        task['coverage_requirements'] = build_requirements(task,
            build_coverage_requirements_v24(task['target_jurisdictions'],
                screening_revision=task.get('screening_revision'),
                specialty_workflow_revision=task.get('specialty_workflow_revision')))
        common.atomic_write_json(fixture.run / 'task.json', task)
        fixture.save()
        with patch('product_delivery.selected_public_image', return_value={
            'image_id':'IMG-001', 'source_url':'https://example.test/main.jpg'}):
            plan = generate_plan(fixture.run)
        rows = [(provider,row) for provider,values in plan['queries'].items() for row in values]
        copyright_rows = [row for provider,row in rows
                          if provider == 'serpapi_google_lens' and row['right_type'] == 'copyright']
        self.assertTrue(copyright_rows)
        self.assertTrue(all(row['product_dependencies'] for row in copyright_rows))
        self.assertTrue(any(term.get('image_only') for term in plan['terms']))
        enforcement = [row for _,row in rows if row['right_type'] == 'enforcement']
        self.assertTrue(enforcement)
        self.assertTrue(all(row['product_dependencies'] and 'infringement' in row['q'] for row in enforcement))
        with patch('product_delivery.selected_public_image', return_value={
            'image_id':'IMG-001', 'source_url':'https://example.test/main.jpg'}):
            expanded = generate_plan(fixture.run, expand=True)
        self.assertEqual(expanded['queries'], plan['queries'])

    def test_cancelled_unsubmitted_bug_row_is_retained_and_corrected(self):
        import test_product_scope as fixture_module
        from workflow_v24 import build_coverage_requirements_v24, generate_plan, validated_query_cancellation
        fixture = fixture_module.ScopeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.data['scope']['directions'].append({
            'direction_id':'signals', 'scenario_id':'product_entry', 'right_type':'enforcement',
            'fact_ids':['shape'], 'object_ids':['pattern'], 'reason':'Related product signals.'})
        task = common.load_json(fixture.run / 'task.json')
        task.update(retrieval_workflow_revision='api-first-v3', source_operation_revision='source-operation-v2',
                    serper_free_enhancement=common.serper_free_enhancement(True, 'api-first-v3'),
                    serpapi_free_enhancement=common.serpapi_free_enhancement(True, 'api-first-v3'))
        task.pop('public_discovery_routing_revision', None)
        legacy = build_coverage_requirements_v24(task['target_jurisdictions'],
            screening_revision=task.get('screening_revision'),
            specialty_workflow_revision=task.get('specialty_workflow_revision'))
        task['coverage_requirements'] = build_requirements(task, legacy)
        common.atomic_write_json(fixture.run / 'task.json', task)
        fixture.save()
        with patch('product_delivery.selected_public_image', return_value=None):
            before = generate_plan(fixture.run)
        old = [row for rows in before['queries'].values() for row in rows if row['right_type']=='enforcement']
        self.assertTrue(old)
        task = common.load_json(fixture.run / 'task.json')
        task['public_discovery_routing_revision'] = 'public-discovery-v1'
        task['coverage_requirements'] = build_requirements(task, legacy)
        common.atomic_write_json(fixture.run / 'task.json', task)
        before['execution_dispositions'] = [{'query_id':row['query_id'],
            'plan_entry_sha256':common.sha256_json(row), 'status':'cancelled',
            'reason':'PLAN_GENERATION_BUG: missing enforcement signal expression, never submitted.'} for row in old]
        common.atomic_write_json(fixture.run / 'search-plan.json', before)
        with patch('product_delivery.selected_public_image', return_value=None):
            after = generate_plan(fixture.run, expand=True)
        all_rows = [row for rows in after['queries'].values() for row in rows]
        for row in old:
            self.assertIn(row, all_rows)
            self.assertTrue(validated_query_cancellation(task, after, row))
        active = [row for row in all_rows if row['right_type']=='enforcement'
                  and not validated_query_cancellation(task, after, row)]
        self.assertTrue(active)
        self.assertTrue(all('infringement' in row['q'] and row['product_dependencies'] for row in active))


if __name__ == '__main__':
    unittest.main()

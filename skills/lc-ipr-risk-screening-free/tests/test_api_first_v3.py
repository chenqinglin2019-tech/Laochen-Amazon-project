"""Offline api-first-v3 route, identity, and operation acceptance contracts."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import common
from coverage_v3 import build_requirements
from provider_routing import priority
from source_operation import record_operation_acceptance


class V3PlanningTests(unittest.TestCase):
    def test_usable_serpapi_precedes_browser_and_retains_us_design_filter(self):
        from test_api_first_planning import ApiFirstPlanningTests
        from common import atomic_write_json
        from workflow_v24 import generate_plan, scenario_dispatch_block_from_dir
        fixture = ApiFirstPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        task = fixture.task
        task['retrieval_workflow_revision'] = 'api-first-v3'
        task['source_operation_revision'] = 'source-operation-v2'
        task['completion_policy_revision'] = 'necessary-work-v3'
        task['serper_free_enhancement'] = common.serper_free_enhancement(True, 'api-first-v3')
        task['serpapi_free_enhancement'] = common.serpapi_free_enhancement(True, 'api-first-v3')
        task['coverage_requirements'] = build_requirements(task, task['coverage_requirements'])
        snapshot = {'task_id': task['task_id'], 'sources': [
            {'provider': provider, 'executable': provider == 'serpapi_google_patents',
             'state': 'ready' if provider == 'serpapi_google_patents' else 'unavailable'}
            for provider in ('epo_ops', 'serper_patents', 'serpapi_google_patents')]}
        atomic_write_json(fixture.path / 'source-capabilities.json', snapshot)
        plan = fixture.regenerate()
        rows = plan['queries']['serpapi_google_patents']
        self.assertTrue(any(row['right_type'] == 'patent' for row in rows))
        design = [row for row in rows if row['right_type'] == 'design' and row['jurisdiction'] == 'US']
        self.assertTrue(design)
        self.assertTrue(all(row.get('type') == 'DESIGN' for row in design))
        self.assertFalse(plan['queries'].get('uspto_patent_browser'))
        for row in rows:
            self.assertIsNone(scenario_dispatch_block_from_dir(fixture.path, 'serpapi_google_patents', row))
            self.assertEqual(common.authorize_serpapi_free_plan_entry(task, plan, row['operation'], row['query_id']), row)
        all_intents = [row['discovery_intent_id'] for values in plan['queries'].values()
                       for row in values if row.get('discovery_role') == 'primary']
        self.assertEqual(len(all_intents), len(set(all_intents)))
        self.assertEqual(generate_plan(fixture.path, expand=True)['queries'], plan['queries'])

    def test_new_lens_rights_do_not_change_legacy_or_text_routes(self):
        from api_first_planning import _preferred_providers
        term = {'discovery_channel': 'image', 'image_url': 'https://example.test/product.png'}
        for revision in ('api-first-v2', 'api-first-v3'):
            task = {'schema_version': '2.4-free', 'retrieval_workflow_revision': revision,
                'decision_workflow_revision': 'scenario-triage-v1',
                'workflow_correction_revision': 'workflow-correction-v1',
                'retrieval_policy': {'enabled': True},
                'serpapi_free_enhancement': common.serpapi_free_enhancement(True, revision),
                'serper_free_enhancement': common.serper_free_enhancement(True, revision)}
            for right in ('trade_dress', 'unregistered_design'):
                providers = list(_preferred_providers(task, right, term, {}, 'GB'))
                self.assertEqual('serpapi_google_lens' in providers, revision == 'api-first-v3')
                self.assertNotIn('serpapi_google_lens', list(_preferred_providers(task, right, {}, {}, 'GB')))

    def test_us_design_keeps_serper_and_distinctive_rights_get_lens_web(self):
        design = priority('US', 'design', 'discovery', revision='api-first-v3')
        self.assertEqual(design[0][0], 'serpapi_google_patents')
        self.assertIn(('serper_patents', 'web_fallback'), design)
        for country in ('US', 'GB', 'EU', 'DE', 'FR', 'JP'):
            self.assertIn('epo_ops', [provider for provider, _ in
                priority(country, 'patent', 'discovery', revision='api-first-v3')])
        for right in ('trade_dress', 'unregistered_design'):
            routes = priority('US', right, 'discovery', revision='api-first-v3')
            self.assertEqual(routes[0][0], 'serpapi_google_lens')
            self.assertIn(('serper_web', 'web_fallback'), routes)
        self.assertIn(('public_web_browser', 'targeted_web_fallback'),
                      priority('US', 'enforcement', 'discovery', revision='api-first-v3'))

    def test_coverage_separates_discovery_from_original_official_gaps(self):
        task = {
            'retrieval_workflow_revision': 'api-first-v3',
            'signa_free_enhancement': common.signa_free_enhancement(False),
            'serper_free_enhancement': common.serper_free_enhancement(False, 'api-first-v3'),
            'serpapi_free_enhancement': common.serpapi_free_enhancement(False, 'api-first-v3'),
        }
        legacy = [{
            'requirement_id': 'COV-US-DESIGN-RECALL', 'jurisdiction': 'US',
            'right_type': 'design', 'phase': 'official_recall', 'required_for': 'low_risk',
            'completion_policy': 'all',
            'routes': [{'provider': 'uspto_patent_browser', 'operation': 'patent_recall',
                        'method': 'cdp_assisted'}, {'provider': 'asset_provenance',
                        'operation': 'provenance_review', 'method': 'agent'}],
        }, {
            'requirement_id': 'COV-US-DESIGN-VERIFY', 'jurisdiction': 'US',
            'right_type': 'design', 'phase': 'candidate_verification', 'required_for': 'formal',
            'completion_policy': 'all',
            'routes': [{'provider': 'uspto_patent_browser', 'operation': 'candidate_verification',
                        'method': 'cdp_assisted'}],
        }]
        result = build_requirements(task, legacy)
        recall, verification = result
        self.assertEqual([route['provider'] for route in recall['routes']], ['asset_provenance'])
        self.assertTrue(recall['gap_only_routes'][0]['gap_only'])
        self.assertEqual(recall['routes'][0]['provider'], 'asset_provenance')
        self.assertEqual(verification, legacy[1])

    def test_v3_generate_plan_exposes_visual_and_enforcement_routes(self):
        import test_product_scope as product_fixture
        from common import atomic_write_json, load_json, serper_free_enhancement, serpapi_free_enhancement
        from workflow_v24 import build_coverage_requirements_v24, generate_plan
        fixture = product_fixture.ScopeTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.data['scope']['objects'][1]['right_types'] = ['copyright','trade_dress','unregistered_design']
        fixture.data['scope']['directions'].extend([
            {'direction_id':'dress','scenario_id':'product_entry','right_type':'trade_dress',
             'fact_ids':['shape'],'object_ids':['pattern'],'reason':'Distinctive appearance signal.'},
            {'direction_id':'unregistered','scenario_id':'product_entry','right_type':'unregistered_design',
             'fact_ids':['shape'],'object_ids':['pattern'],'reason':'Unregistered design comparison.'},
            {'direction_id':'enforcement','scenario_id':'product_entry','right_type':'enforcement',
             'fact_ids':['shape'],'object_ids':['pattern'],'reason':'Product-related litigation signals.'},
        ])
        task = load_json(fixture.run / 'task.json')
        task['target_jurisdictions'] = ['GB']
        task['retrieval_workflow_revision'] = 'api-first-v3'
        task['public_discovery_routing_revision'] = 'public-discovery-v1'
        task['source_operation_revision'] = 'source-operation-v2'
        task['serper_free_enhancement'] = serper_free_enhancement(True, 'api-first-v3')
        task['serpapi_free_enhancement'] = serpapi_free_enhancement(True, 'api-first-v3')
        legacy = build_coverage_requirements_v24(task['target_jurisdictions'],
            screening_revision=task.get('screening_revision'),
            specialty_workflow_revision=task.get('specialty_workflow_revision'))
        task['coverage_requirements'] = build_requirements(task, legacy)
        atomic_write_json(fixture.run / 'task.json', task)
        task = fixture.save()
        with patch('product_delivery.selected_public_image',return_value={
                'source_url':'https://example.test/retained-product.png'}):
            plan = generate_plan(fixture.run)
        rows = [(provider, row) for provider, values in plan['queries'].items() for row in values]
        # The actual plan reaches enforcement and public-image discovery; GB
        # keeps the unregistered-design comparison in its relevant territory.
        enforcement = [row for provider, row in rows if row.get('right_type') == 'enforcement']
        self.assertTrue(enforcement)
        self.assertTrue(all(row.get('required_for') == 'discovery_only' for row in enforcement))
        lens_rights = {row['right_type'] for provider, row in rows
                       if provider == 'serpapi_google_lens' and row.get('search_dimension') == 'image'}
        self.assertTrue({'trade_dress','unregistered_design'} <= lens_rights)


class V3AcceptanceTests(unittest.TestCase):
    def test_signa_known_record_authorization_is_exact_and_v3_only(self):
        task = {
            'schema_version': '2.4-free', 'task_id': 'T-v3',
            'retrieval_workflow_revision': 'api-first-v3',
            'free_policy': common.active_free_policy(),
            'free_policy_revision': common.AUTOMATION_POLICY_REVISION,
            'target_jurisdictions': ['US'],
            'screening_revision': common.RECALL_INTEGRITY_REVISION,
            'specialty_workflow_revision': 'asset-scope-v1',
            'signa_free_enhancement': common.signa_free_enhancement(True),
            'serper_free_enhancement': common.serper_free_enhancement(False, 'api-first-v3'),
            'serpapi_free_enhancement': common.serpapi_free_enhancement(False, 'api-first-v3'),
            'decision_workflow_revision': 'scenario-triage-v1',
            'workflow_correction_revision': 'workflow-correction-v1',
            'retrieval_policy': {'enabled': True},
        }
        from decision_workflow import default_assessment_scenarios
        task['assessment_scenarios'] = default_assessment_scenarios()
        task['primary_scenario_id'] = 'product_entry'
        from workflow_v24 import build_coverage_requirements_v24
        task['coverage_requirements'] = build_coverage_requirements_v24(
            ['US'], screening_revision=task['screening_revision'],
            specialty_workflow_revision=task['specialty_workflow_revision'])
        task['coverage_requirements'] = build_requirements(task, task['coverage_requirements'])
        row = {
            'operation': 'candidate_detail', 'jurisdiction': 'US',
            'right_type': 'trademark_figurative', 'candidate_id': 'C-1',
            'provider_record_id': 'tm_12345', 'missing_facts': ['goods_services'],
            'q': '12345678', 'record_number': '12345678',
            'api_gap_revision': 'api-first-v3', 'gap_reason': 'goods/services were truncated',
            'judgment_impact': 'Needed for candidate comparison.',
            'action_purpose': 'document_content', 'evidence_obligation_id': 'OBL-1',
            'scenario_id': 'product_entry',
            'scenario_sha256': task['assessment_scenarios'][0]['scenario_sha256'],
            'triage_decision_id': 'ANN-1', 'triage_decision_sha256': 'a' * 64,
            'triage_jurisdiction': 'US', 'triage_candidate_id': 'C-1',
            'decision_workflow_revision': 'scenario-triage-v1',
            'workflow_correction_revision': 'workflow-correction-v1',
            'retrieval_workflow_revision': 'api-first-v3',
            'required': False, 'required_for': 'comparison',
            'role': common.SIGNA_FREE_ROLE, 'execute_by_default': True,
            'authoritative_for_final_rating': False,
        }
        row['query_id'] = common.signa_record_operation_query_id(row)
        plan = {
            'schema_version': task['schema_version'], 'task_id': task['task_id'],
            'free_policy': task['free_policy'], 'free_policy_revision': task['free_policy_revision'],
            'signa_free_enhancement': task['signa_free_enhancement'],
            'serper_free_enhancement': task['serper_free_enhancement'],
            'serpapi_free_enhancement': task['serpapi_free_enhancement'],
            'queries': {'signa': [row]},
            'retrieval_workflow_revision': 'api-first-v3',
        }
        self.assertEqual(common.authorize_signa_free_plan_entry(task, plan, row['query_id']), row)
        self.assertEqual(common.provider_execution_error(task, 'signa', 'candidate_detail',
            jurisdiction='US', right_type='trademark_figurative'), '')
        from provider_utils import PLAN_META_KEYS, query_identity
        from workflow_v24 import SCENARIO_META_KEYS
        identity = {key: value for key, value in row.items()
                    if key not in PLAN_META_KEYS or key in SCENARIO_META_KEYS}
        identity['right_type'] = row['right_type']
        self.assertEqual(row['query_id'], query_identity('signa', row['operation'], 'US', row['q'], identity))
        status_gap = dict(row, missing_facts=['current_status', 'territory'])
        status_gap['query_id'] = common.signa_record_operation_query_id(status_gap)
        self.assertEqual(common.authorize_signa_free_plan_entry(task,
            dict(plan, queries={'signa': [status_gap]}), status_gap['query_id']), status_gap)
        for mutate in (
            {'jurisdiction': 'GB'},
            {'required': True}, {'missing_facts': []},
        ):
            altered = dict(row, **mutate)
            altered['query_id'] = common.signa_record_operation_query_id(altered)
            invalid_plan = dict(plan, queries={'signa': [altered]})
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                common.authorize_signa_free_plan_entry(task, invalid_plan, altered['query_id'])

    def test_recorded_response_acceptance_binds_payload_and_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            row = {'query_id': 'Q1', 'operation': 'candidate_detail', 'jurisdiction': 'US',
                   'right_type': 'trademark_figurative', 'candidate_id': 'C1',
                   'provider_record_id': 'tm_123', 'record_number':'12345678',
                   'missing_facts': ['goods_services']}
            from common import atomic_write_bytes, sha256_bytes, sha256_json
            raw = root / 'raw.json'
            body = b'{"official":"response"}'
            atomic_write_bytes(raw, body)
            run = {'run_id': 'R1', 'provider': 'signa', 'operation': 'candidate_detail',
                   'query_id': 'Q1', 'jurisdiction': 'US', 'right_type': 'trademark_figurative',
                   'status': 'success', 'submission_state': 'submitted',
                   'plan_entry_sha256': sha256_json(row), 'payload_digest': sha256_bytes(body),
                   'raw_paths': [str(raw)]}
            task = {'retrieval_workflow_revision': 'api-first-v3', 'task_id': 'T1',
                    'source_operation_revision': 'source-operation-v2',
                    'signa_free_enhancement': common.signa_free_enhancement(True)}
            context = {'credential_fingerprint_sha256': 'cred-hash',
                       'permission_fingerprint_sha256': 'permission-hash',
                       'adapter_version': 'adapter-v1'}
            task['operation_acceptance_contexts'] = {'signa': context}
            evidence = {'task_id': 'T1', 'source_runs': [run],
                        'collections': {'trademarks': [{'source_run_id': 'R1'}]}}
            entry = {'evidence_id': 'EV1', 'source_run_id': 'R1', 'query_id': 'Q1',
                     'provider': 'signa', 'operation': 'candidate_detail',
                     'jurisdiction': 'US', 'right_type': 'trademark_figurative',
                     'plan_entry_sha256': sha256_json(row),
                     'payload': {'candidate_id': 'C1', 'provider_record_id': 'tm_123',
                     'record_identity': 'tm_123', 'record_scope': 'target_record',
                     'registration_number':'12345678',
                     'jurisdiction': 'US', 'right_type': 'trademark_figurative'}}
            import trusted_api
            trusted_api.annotate_entry(task, entry, run)
            evidence['collections'] = {'trademarks': [entry]}
            with patch('common.assert_provider_execution_allowed'), \
                 patch('source_operation.operation_acceptance_context', return_value=context), \
                 patch('source_operation.load_skill_config', return_value={'providers': {'signa': {
                    'network_enabled_when_opted_in': True, 'allow_paid': False,
                    'allow_overage': False, 'allow_automatic_recharge': False,
                    'credential_key': 'SIGNA_API_KEY'}}}):
                accepted = record_operation_acceptance(root, task, evidence, row, run, entry)
            self.assertEqual(accepted['state'], 'accepted')
            self.assertEqual(accepted['kind'], 'source_operation_acceptance_v1')
            self.assertEqual(accepted['proof']['source_run_sha256'], sha256_json(run))
            evidence['operation_acceptances'] = [accepted]
            import source_operation
            with patch('source_operation._current_acceptance_context', return_value=(
                    accepted['proof']['adapter_sha256'], accepted['proof']['controls_sha256'])):
                self.assertTrue(source_operation.current_operation_acceptance(task, evidence, 'signa', row))
            evidence['source_runs'].append({**run, 'run_id': 'R2', 'status': 'failed',
                'finished_at': '2026-09-29T00:00:00Z'})
            with patch('source_operation._current_acceptance_context', return_value=(
                    accepted['proof']['adapter_sha256'], accepted['proof']['controls_sha256'])):
                self.assertFalse(source_operation.current_operation_acceptance(task, evidence, 'signa', row))
            with patch('common.assert_provider_execution_allowed'):
                with self.assertRaisesRegex(ValueError, 'IDENTITY_MISMATCH'):
                    wrong = {**entry, 'payload': {**entry['payload'], 'jurisdiction': 'GB'}}
                    trusted_api.annotate_entry(task, wrong, run)
                    record_operation_acceptance(root, task, evidence, row, run,
                        wrong)
                with self.assertRaisesRegex(ValueError, 'SOURCE_OPERATION_RECORD_IDENTITY_MISMATCH'):
                    wrong = {**entry, 'payload': {**entry['payload'], 'registration_number':'87654321'}}
                    trusted_api.annotate_entry(task, wrong, run)
                    record_operation_acceptance(root, task, evidence, row, run, wrong)
                with self.assertRaisesRegex(ValueError, 'IDENTITY_MISMATCH'):
                    wrong = {**entry, 'payload': {**entry['payload'], 'provider_record_id': 'tm_other'}}
                    trusted_api.annotate_entry(task, wrong, run)
                    record_operation_acceptance(root, task, evidence, row, run, wrong)

    def test_provider_record_result_persists_reusable_acceptance(self):
        import json
        import provider_utils
        import source_operation
        import trusted_api
        from common import atomic_write_json, sha256_json
        from source_operation import work_entries
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = {'schema_version':'2.4-free','task_id':'T-END2END',
                'retrieval_workflow_revision':'api-first-v3','source_operation_revision':'source-operation-v2',
                'workflow_correction_revision':'workflow-correction-v1',
                'free_policy':common.active_free_policy(),'free_policy_revision':common.AUTOMATION_POLICY_REVISION,
                'target_jurisdictions':['US'],'signa_free_enhancement':common.signa_free_enhancement(True),
                'serper_free_enhancement':common.serper_free_enhancement(False,'api-first-v3'),
                'serpapi_free_enhancement':common.serpapi_free_enhancement(False,'api-first-v3'),
                'coverage_requirements':[], 'product':{}}
            row = {'query_id':'Q-END2END','operation':'candidate_detail','jurisdiction':'US',
                'right_type':'trademark_figurative','candidate_id':'C1','provider_record_id':'tm_123',
                'record_number':'12345678','missing_facts':['goods_services'],'required':False,
                'required_for':'comparison','role':common.SIGNA_FREE_ROLE,'execute_by_default':True,
                'authoritative_for_final_rating':False,'retrieval_workflow_revision':'api-first-v3',
                'scenario_id':'product_entry','scenario_sha256':'a'*64,'action_purpose':'document_content',
                'evidence_obligation_id':'OBL-1','triage_decision_id':'ANN-1','triage_decision_sha256':'b'*64,
                'triage_candidate_id':'C1','triage_jurisdiction':'US'}
            row['query_id'] = common.signa_record_operation_query_id(row)
            plan = {'schema_version':task['schema_version'],'task_id':task['task_id'],
                'retrieval_workflow_revision':'api-first-v3','queries':{'signa':[row]}}
            evidence = {'schema_version':task['schema_version'],'task_id':task['task_id'],
                'source_runs':[],'collections':{}}
            for name, value in (('task.json',task),('search-plan.json',plan),('evidence.json',evidence)):
                atomic_write_json(root/name,value)
            record = {'provider_record_id':'tm_123','record_identity':'tm_123','record_scope':'target_record',
                'registration_number':'12345678','candidate_id':'C1','jurisdiction':'US',
                'right_type':'trademark_figurative','goods_services':['toys']}
            raw = json.dumps({'record':record}).encode()
            context = {'credential_fingerprint_sha256':'cred','permission_fingerprint_sha256':'perm',
                       'adapter_version':'adapter'}
            with patch('common.authorize_signa_free_plan_entry',return_value=row), \
                 patch('provider_utils.require_provider_operation',return_value=False), \
                 patch('provider_utils.authorize_exact_plan_execution'), \
                 patch('source_result_processing.locate_one_to_one',side_effect=lambda task,*args,**kwargs: args[-1]), \
                 patch('source_result_processing.make_index',return_value=None), \
                 patch('source_operation.operation_acceptance_context',return_value=context), \
                 patch('source_operation.load_skill_config',return_value={'providers':{'signa':{
                    'network_enabled_when_opted_in':True,'allow_paid':False,'allow_overage':False,
                    'allow_automatic_recharge':False}}}), \
                 patch('common.assert_provider_execution_allowed'):
                run = provider_utils.record_result(root,provider='signa',operation='candidate_detail',
                    query='12345678',jurisdiction='US',evidence_type='trademark',status='success',
                    normalized=record,raw_body=raw,request_params={'q':'12345678','right_type':'trademark_figurative',
                        'candidate_id':'C1','provider_record_id':'tm_123','record_number':'12345678',
                        'missing_facts':['goods_services']},query_id=row['query_id'],submission_state='submitted')
            saved = common.load_json(root/'evidence.json')
            self.assertIn('operation_acceptances',saved,saved)
            self.assertEqual(len(saved['operation_acceptances']),1)
            self.assertEqual(saved['operation_acceptances'][0]['state'],'accepted')
            proof = saved['operation_acceptances'][0]['proof']
            with patch('source_operation._current_acceptance_context',return_value=(
                    proof['adapter_sha256'],proof['controls_sha256'])):
                self.assertEqual(work_entries(task,plan,saved,root),[])
            # The first valid response can authorize the same provider operation
            # after a newly planned query ID; it does not authorize changed controls.
            second = dict(row,query_id='Q-SECOND')
            with patch('source_operation._current_acceptance_context',return_value=(
                    saved['operation_acceptances'][0]['proof']['adapter_sha256'],
                    saved['operation_acceptances'][0]['proof']['controls_sha256'])):
                self.assertTrue(source_operation.current_operation_acceptance(task,saved,'signa',second))
            with patch('source_operation._current_acceptance_context',return_value=('changed-adapter','changed-controls')):
                self.assertFalse(source_operation.current_operation_acceptance(task,saved,'signa',second))


if __name__ == '__main__':
    unittest.main()

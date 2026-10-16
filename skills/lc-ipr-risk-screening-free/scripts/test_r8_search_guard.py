"""r8 (search-guard-v2): the owner's r7 runs B0GLNPC6K8-US-r7 / B0H16FDSD8-US-r7 stopped at publication.

The planner sent the US design query to EPO, but the task's route table never listed EPO for designs: the frozen client
refused the row, recording that refusal raised in the API lane and every EPO search queued behind it was never sent.
The product-name image, web and enforcement searches were cancelled before sending as a new purpose without a parent.
Publication then found scopes with no search and no disclosed limitation. The owner also asked for a SerpApi backup key.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import search_guard

V1 = {search_guard.TASK_FIELD: 'search-guard-v1'}
V2 = {search_guard.TASK_FIELD: search_guard.REVISION}


class MarkerTests(unittest.TestCase):
    def test_new_tasks_get_v2_and_v1_tasks_stay_guarded(self):
        self.assertEqual(search_guard.REVISION, 'search-guard-v2')
        self.assertTrue(search_guard.enabled(V1) and search_guard.enabled(V2))
        self.assertFalse(search_guard.enabled({}))
        self.assertTrue(search_guard.design_epo_route(V2))
        self.assertFalse(search_guard.design_epo_route(V1))


class DesignRouteTests(unittest.TestCase):
    def requirements(self, marker):
        from workflow_v24 import build_coverage_requirements_v24
        from coverage_v3 import build_requirements
        task = {'retrieval_workflow_revision': 'api-first-v3', 'target_jurisdictions': ['US'],
                'screening_revision': 'recall-integrity-v1', 'specialty_workflow_revision': 'asset-scope-v1', **marker}
        with mock.patch('common.serpapi_free_enabled', return_value=True), \
                mock.patch('common.serper_free_enabled', return_value=True):
            rows = build_requirements(task, build_coverage_requirements_v24(
                ['US'], screening_revision='recall-integrity-v1', specialty_workflow_revision='asset-scope-v1'))
        return {(row['right_type'], row['phase']): row for row in rows}

    def test_v2_lists_epo_for_us_designs_and_v1_keeps_its_table(self):
        new, old = self.requirements(V2), self.requirements(V1)
        design = new[('design', 'official_recall')]
        self.assertIn(('epo_ops', 'search', 'fallback'),
                      [(r['provider'], r['operation'], r.get('provider_role')) for r in design['routes']])
        self.assertNotIn('epo_ops', [r['provider'] for r in old[('design', 'official_recall')]['routes']])
        # nothing else changes
        for key in new:
            if key != ('design', 'official_recall'):
                self.assertEqual(new[key], old[key])

    def test_the_route_policy_accepts_the_epo_design_search(self):
        from provider_utils import coverage_route_policy
        for marker, allowed in ((V2, True), (V1, False)):
            task = {'schema_version': '2.4-free', 'coverage_requirements': list(self.requirements(marker).values())}
            with mock.patch('provider_utils.task_free_policy_valid', return_value=True), \
                    mock.patch('provider_utils.canonical_coverage_requirements_match', return_value=True):
                self.assertEqual(coverage_route_policy(task, 'epo_ops', 'search', jurisdiction='US',
                                                       right_type='design')[0], allowed)


class NamesPurposeTests(unittest.TestCase):
    def row(self, problem):
        import recall
        return {'action_purpose': 'discovery', 'jurisdiction': 'US', 'right_type': 'copyright', 'search_dimension': 'text',
                'discovery_scope': {'purpose_basis': {'scenario_id': 'product_entry', 'clue_source': 'product.title',
                                                      'problem_id': problem, 'problem_reason': 'x',
                                                      'different_from_purpose_id': recall.LISTING_PHRASE}}}

    def test_the_names_term_is_not_cancelled_as_a_new_purpose(self):
        import discovery_budget
        row = self.row(search_guard.NAMES_PROBLEM)
        with mock.patch('discovery_budget.enabled', return_value=True), \
                mock.patch('discovery_budget.purpose_id', return_value='INT-x'), \
                mock.patch('discovery_budget.snapshot', return_value={'routes': [], 'pages_acquired': 0,
                                                                     'browser_candidates_acquired': 0}), \
                mock.patch('recall.enabled', return_value=True):
            row['discovery_intent_id'] = 'INT-x'
            self.assertIsNone(discovery_budget.dispatch_block({**V1, 'recall_revision': 'recall-v1'}, {'queries': {}}, {},
                                                              'serper_images', row))
            other = self.row('someone-else:problem')
            other['discovery_intent_id'] = 'INT-x'
            self.assertEqual(discovery_budget.dispatch_block({**V1}, {'queries': {}}, {}, 'serper_images', other),
                             'DISCOVERY_NEW_PURPOSE_PARENT_REQUIRED')


class LaneTests(unittest.TestCase):
    def test_a_refused_gap_returns_instead_of_stopping_the_lane(self):
        import runtime_v24
        from provider_utils import ProviderError
        refusal = ProviderError('PROVIDER_OPERATION_NOT_CONFIGURED', 'failed',
                                'Provider operation is not configured for this task: epo_ops/search')
        with mock.patch('runtime_v24.record_gap', side_effect=refusal):
            result = runtime_v24._refusal_safe_gap(Path('.'), 'epo_ops', {'query_id': 'QRY-1', 'operation': 'search'},
                                                   'API_EXECUTION_FAILED', 'client failed')
        self.assertEqual((result['status'], result['error_code'], result['submission_state'], result['recorded']),
                         ('failed', 'PROVIDER_OPERATION_NOT_CONFIGURED', 'not_submitted', False))

    def test_guard_tasks_use_the_safe_recorder(self):
        text = (Path(__file__).resolve().parent / 'runtime_v24.py').read_text(encoding='utf-8')
        self.assertIn('record_gap = _refusal_safe_gap if search_guard.enabled(task) else globals()["record_gap"]', text)


class CancelledScopeTests(unittest.TestCase):
    def setUp(self):
        self.row = {'query_id': 'QRY-a', 'right_type': 'design'}
        self.plan = {'queries': {'epo_ops': [self.row]}}
        self.group = {'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design',
                      'gaps': ['OBLIGATION_INCOMPLETE:OBL-1'],
                      'obligations': [{'evidence_obligation_id': 'OBL-1', 'complete': False, 'query_ids': ['QRY-a']}]}
        self.view = {'unresolved_scopes': [{'scenario_id': 'product_entry', 'jurisdiction': 'US', 'right_type': 'design'}]}

    def limits(self, evidence, cancelled=True, task=None):
        import necessary_completion as nc
        record = {'query_id': 'QRY-a', 'status': 'cancelled', 'reason': 'PROGRESS_DIAGNOSIS_OR_REPAIR_REQUIRED'}
        with mock.patch('workflow_v24.validated_query_cancellation', return_value=record if cancelled else None), \
                mock.patch('workflow_v24.plan_row_index', return_value={'QRY-a': [('epo_ops', self.row)]}):
            return nc._cancelled_discovery_limits(task if task is not None else {'stability_revision': 'report-always-v1'}, self.plan, evidence,
                                                  [self.group], self.view, set())

    def test_a_scope_whose_searches_were_all_cancelled_is_disclosed(self):
        [limit] = self.limits({'source_runs': []})
        self.assertEqual((limit['right_type'], limit['reason'], limit['state']),
                         ('design', 'DISCOVERY_CANCELLED_BEFORE_SUBMISSION', 'blocked'))
        self.assertIn('不能据此认为不存在相关权利', limit['reasoning'])

    def test_sent_or_live_searches_and_old_tasks_keep_the_refusal(self):
        sent = {'source_runs': [{'provider': 'epo_ops', 'query_id': 'QRY-a', 'submission_state': 'submitted'}]}
        self.assertEqual(self.limits(sent), [])
        self.assertEqual(self.limits({'source_runs': []}, cancelled=False), [])
        self.assertEqual(self.limits({'source_runs': []}, task={}), [])
        self.group['gaps'].append('SELECTED_FACT_MISSING:CAND-1:current_status')
        self.assertEqual(self.limits({'source_runs': []}), [])


class BackupKeyTests(unittest.TestCase):
    def test_choose_slot(self):
        known = lambda n: {'state': 'known', 'available': n}
        self.assertEqual(search_guard.choose_slot(known(50), known(250), 12), 'primary')
        self.assertEqual(search_guard.choose_slot(known(0), known(250), 12), 'backup')
        self.assertEqual(search_guard.choose_slot(known(5), known(8), 12), 'backup')
        self.assertEqual(search_guard.choose_slot(known(5), known(5), 12), 'primary')
        self.assertEqual(search_guard.choose_slot(known(0), None, 12), 'primary')
        self.assertEqual(search_guard.choose_slot(known(0), {'state': 'unknown'}, 12), 'primary')
        self.assertEqual(search_guard.choose_slot({'state': 'unknown'}, known(250), 12), 'backup')

    def test_the_selected_slot_reaches_every_serpapi_client(self):
        import common
        text = 'SERPER_API_KEY=\nSERPAPI_API_KEY="MAIN-KEY"\nSERPAPI_API_KEY_BACKUP="SPARE-KEY"\n'
        self.assertNotIn('SERPAPI_API_KEY_BACKUP', common.ENV_CREDENTIALS.values())   # the 12 fields stay as they are
        with mock.patch('common._private_credential_text', return_value=text), \
                mock.patch('common.offline_credentials_disabled', return_value=False), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(search_guard.SLOT_ENV, None)
            self.assertEqual(common.credential({}, 'serpapi_api_key'), 'MAIN-KEY')
            search_guard.apply_slot({'key_slot': 'backup'})
            self.assertEqual(common.credential({}, 'serpapi_api_key'), 'SPARE-KEY')
            self.assertEqual(common.serpapi_slot_key('primary'), 'MAIN-KEY')
            self.assertIn('SPARE-KEY', common.configured_credential_values())
            self.assertIn('MAIN-KEY', common.configured_credential_values())
            search_guard.apply_slot({'key_slot': 'primary'})
            self.assertEqual(common.credential({}, 'serpapi_api_key'), 'MAIN-KEY')
            self.assertNotIn(search_guard.SLOT_ENV, os.environ)
        # a selected backup slot without a backup value falls back to the main key; a duplicate backup line is ignored
        with mock.patch('common._private_credential_text', return_value='SERPAPI_API_KEY="MAIN-KEY"\n'), \
                mock.patch('common.offline_credentials_disabled', return_value=False), \
                mock.patch.dict(os.environ, {search_guard.SLOT_ENV: 'backup'}, clear=False):
            self.assertEqual(common.credential({}, 'serpapi_api_key'), 'MAIN-KEY')
            self.assertEqual(common.serpapi_slot_key('backup'), '')
        with mock.patch('common._private_credential_text',
                        return_value='SERPAPI_API_KEY_BACKUP=A\nSERPAPI_API_KEY_BACKUP=B\n'), \
                mock.patch('common.offline_credentials_disabled', return_value=False):
            self.assertEqual(common.serpapi_slot_key('backup'), '')

    def test_the_backup_is_read_and_chosen_without_recording_any_key(self):
        payloads = {'MAIN-KEY': {'plan_searches_left': 0, 'extra_credits': 0, 'plan_renewal_date': '2026-10-21'},
                    'SPARE-KEY': {'plan_searches_left': 250, 'extra_credits': 0, 'plan_renewal_date': '2026-11-14'}}
        def fetch(url, **kwargs):
            key = next(k for k in payloads if k in url)
            return payloads[key], {}, b''
        keys = {'primary': 'MAIN-KEY', 'backup': 'SPARE-KEY'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'task.json').write_text(json.dumps({**V2, 'query_terms': []}), encoding='utf-8')
            with mock.patch('serpapi_patents_client.settings', return_value=({}, 'https://serpapi.com', 'MAIN-KEY')), \
                    mock.patch('common.serpapi_slot_key', side_effect=lambda slot: keys[slot]), \
                    mock.patch('common.serpapi_free_enabled', return_value=True), \
                    mock.patch('source_policy.enabled', return_value=True), \
                    mock.patch('free_search_budget.peek', return_value=None), \
                    mock.patch.dict(os.environ, {'LC_IPR_TEST_MODE': ''}, clear=False):
                os.environ.pop(search_guard.SLOT_ENV, None)
                record = search_guard.check_capacity(root, fetch=fetch)
                self.assertEqual(os.environ.get(search_guard.SLOT_ENV), 'backup')
                os.environ.pop(search_guard.SLOT_ENV, None)
            self.assertEqual((record['key_slot'], record['available'], record['route'], record['renewal_date']),
                             ('backup', 250, 'serpapi', '2026-11-14'))
            self.assertEqual(record['accounts']['primary']['available'], 0)
            text = (root / search_guard.CAPACITY_FILE).read_text(encoding='utf-8')
            self.assertNotIn('MAIN-KEY', text)
            self.assertNotIn('SPARE-KEY', text)
            self.assertIn('改用备用 key', search_guard.notice(record))

    def test_a_task_that_already_sent_a_serpapi_request_keeps_its_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / search_guard.CAPACITY_FILE).write_text(json.dumps(
                {'schema': search_guard.CAPACITY_SCHEMA, 'key_slot': 'primary'}), encoding='utf-8')
            (root / 'evidence.json').write_text(json.dumps({'source_runs': [
                {'provider': 'serpapi_google_patents', 'submission_state': 'submitted'}]}), encoding='utf-8')
            self.assertTrue(search_guard._serpapi_used(root))

    def test_the_backup_key_is_saved_privately_without_touching_the_main_key(self):
        import configure_backup_key
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env').write_text('SERPAPI_API_KEY="MAIN"\nSERPER_API_KEY=\n', encoding='utf-8')
            result = configure_backup_key.configure(root, {'SERPAPI_API_KEY_BACKUP': 'SPARE'})
            self.assertEqual(result['api_key_names'], ['SERPAPI_API_KEY_BACKUP'])
            configure_backup_key.configure(root, {'SERPAPI_API_KEY_BACKUP': 'SPARE-2'})
            text = (root / '.env').read_text(encoding='utf-8')
            self.assertEqual(text, 'SERPAPI_API_KEY="MAIN"\nSERPER_API_KEY=\nSERPAPI_API_KEY_BACKUP="SPARE-2"\n')
            if os.name == 'posix':
                self.assertEqual((root / '.env').stat().st_mode & 0o777, 0o600)
            for bad in ({'SERPAPI_API_KEY': 'X'}, {'SERPAPI_API_KEY_BACKUP': ' X'}, {'SERPAPI_API_KEY_BACKUP': 'a"b'}):
                with self.assertRaises(ValueError):
                    configure_backup_key.configure(root, bad)

    def test_the_pipeline_reapplies_the_recorded_slot(self):
        text = (Path(__file__).resolve().parent / 'run_pipeline.py').read_text(encoding='utf-8')
        self.assertIn('self.recorded_key_slot()', text)
        self.assertIn('search_guard.apply_slot(record)', text)


if __name__ == '__main__':
    unittest.main()

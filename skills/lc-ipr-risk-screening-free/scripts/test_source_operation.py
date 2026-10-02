"""03C source-operation contract tests; retained responses are local fixtures."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_file, sha256_json
from record_source_operation import record
from runtime_v24 import operation_accepted, resolved_capabilities
from source_operation import work_entries
import source_operation_registry as registry


class SourceOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {'task_id': 'OFFLINE-03C', 'source_operation_revision': 'source-operation-v1',
                     'completion_policy_revision': 'necessary-work-v3'}
        self.row = {'query_id': 'Q-1', 'jurisdiction': 'US', 'right_type': 'design',
                    'operation': 'search', 'query_compiler_revision': 'fields-v1',
                    'search_dimension': 'classification', 'q': 'locarno:21-01'}
        self.plan = {'task_id': self.task['task_id'], 'queries': {'source_browser': [self.row]}}
        raw = self.root / 'raw' / 'response.json'
        atomic_write_json(raw, {'items': [{'id': 'one'}], 'page': 1})
        self.run = {'run_id': 'RUN-1', 'provider': 'source_browser', 'query_id': 'Q-1',
                    'plan_entry_sha256': sha256_json(self.row), 'operation': 'search',
                    'jurisdiction': 'US', 'right_type': 'design', 'status': 'success',
                    'submission_state': 'submitted', 'raw_paths': [str(raw)],
                    'payload_digest': sha256_file(raw)}
        self.evidence = {'task_id': self.task['task_id'], 'source_runs': [self.run],
                         'collections': {'patents': [{'evidence_id': 'EV-1', 'source_run_id': 'RUN-1'}]}}
        self.save()
        self.input = self.root / 'review-input.json'

    def save(self):
        for name, value in (('task.json', self.task), ('search-plan.json', self.plan),
                            ('evidence.json', self.evidence)):
            atomic_write_json(self.root / name, value)

    def review(self, decision='accepted', **checks):
        payload = {'provider': 'source_browser', 'query_id': 'Q-1', 'source_run_id': 'RUN-1',
                   'reviewer': 'source-maintainer', 'reason': 'Checked request parameters and retained response.',
                   'decision': decision, 'checks': {'request_response_binding': True,
                       'field_effect': 'verified', 'pagination': 'single_page',
                       'known_number': 'not_applicable', 'original_content': 'not_applicable',
                       'current_status': 'not_applicable', **checks}}
        atomic_write_json(self.input, payload)
        return record(self.root, self.input)

    def caps(self):
        return resolved_capabilities(load_json(self.root / 'task.json'),
            load_json(self.root / 'evidence.json'), load_json(self.root / 'search-plan.json'),
            {'source_browser': {'provider': 'source_browser', 'executable': False,
                                'reason': 'browser_adapter_requires_real_route_acceptance'}}, self.root)

    def test_success_response_does_not_accept_field_or_pagination(self):
        self.assertFalse(operation_accepted(self.caps()['source_browser'], self.row))

        self.assertTrue(any(item['reason'] == 'SOURCE_OPERATION_REVIEW_REQUIRED'
            for item in work_entries(self.task, self.plan, self.evidence, self.root)))
        with self.assertRaisesRegex(ValueError, 'FIELD_UNVERIFIED'):
            self.review(field_effect='not_applicable')
        with self.assertRaisesRegex(ValueError, 'ACCEPTANCE_UNSUPPORTED'):
            self.review(pagination='unknown')
        self.review()
        self.assertTrue(operation_accepted(self.caps()['source_browser'], self.row))
        self.assertFalse(operation_accepted(self.caps()['source_browser'],
            {**self.row, 'search_dimension': 'text'}))
        self.assertEqual(work_entries(load_json(self.root / 'task.json'), self.plan,
                                      self.evidence, self.root), [])

    def test_repeating_identical_operation_review_reuses_retained_receipt(self):
        first = self.review()
        original = (self.root / 'task.json').read_bytes()
        second = self.review()
        self.assertEqual(second, first)
        self.assertEqual((self.root / 'task.json').read_bytes(), original)
        self.assertEqual(len(list((self.root / 'raw' / 'source_operation').glob('*.json'))), 1)

    def test_operation_batch_validates_all_before_any_write(self):
        self.review()
        request = load_json(self.input)
        before = (self.root / 'task.json').read_bytes()
        count = len(list((self.root / 'raw' / 'source_operation').glob('*.json')))
        atomic_write_json(self.input, {'reviews': [{**request, 'reason': 'New valid reason'},
            {**request, 'query_id': 'MISSING'}]})
        with self.assertRaisesRegex(ValueError, 'QUERY_REQUIRED'):
            record(self.root, self.input)
        self.assertEqual((self.root / 'task.json').read_bytes(), before)
        self.assertEqual(len(list((self.root / 'raw' / 'source_operation').glob('*.json'))), count)
        atomic_write_json(self.input, {'reviews': [request, request]})
        result = record(self.root, self.input)
        self.assertEqual(result['recorded_count'], 0)
        self.assertEqual(len(result['reviews']), 2)

    def test_anomaly_revokes_prior_acceptance_without_erasing_history(self):
        self.review()
        self.review(decision='rejected', field_effect='failed', pagination='failed')
        self.assertFalse(operation_accepted(self.caps()['source_browser'], self.row))
        self.assertEqual(len(load_json(self.root / 'task.json')['source_operation_reviews']), 2)
        self.assertTrue(any(item['reason'] == 'SOURCE_OPERATION_REJECTED_REPLAN_REQUIRED'
            for item in work_entries(load_json(self.root / 'task.json'), self.plan,
                                     self.evidence, self.root)))

    def test_reaccept_after_rejection_appends_new_review_even_when_original_body_matches(self):
        first = self.review()
        self.review(decision='rejected', field_effect='failed', pagination='failed')
        accepted = self.review()
        self.assertNotEqual(accepted['review_id'], first['review_id'])
        self.assertEqual(len(load_json(self.root / 'task.json')['source_operation_reviews']), 3)
        self.assertTrue(operation_accepted(self.caps()['source_browser'], self.row))

    def test_rejected_ancestor_review_retires_after_accepted_fallback(self):
        parent = self.row
        parent.update({'provider_role': 'preferred', 'discovery_role': 'primary',
                       'discovery_intent_id': 'INT-1'})
        self.run['plan_entry_sha256'] = sha256_json(parent)
        self.evidence['source_runs'][0] = self.run
        self.save()
        self.review(decision='rejected', field_effect='failed', pagination='failed')
        fallback = {**parent, 'query_id': 'Q-FALLBACK', 'provider_role': 'fallback',
                    'discovery_role': 'browser_fallback', 'discovery_intent_id': 'INT-1',
                    'parent_query_id': parent['query_id'],
                    'parent_plan_entry_sha256': sha256_json(parent)}
        self.plan['queries'] = {'source_browser': [parent], 'pps_browser': [fallback]}
        raw = self.root / 'raw' / 'fallback-response.json'
        atomic_write_json(raw, {'items': [{'id': 'fallback'}], 'page': 1})
        fallback_run = {**self.run, 'run_id': 'RUN-FALLBACK', 'provider': 'pps_browser',
                        'query_id': fallback['query_id'], 'plan_entry_sha256': sha256_json(fallback),
                        'raw_paths': [str(raw)], 'payload_digest': sha256_file(raw)}
        self.evidence['source_runs'].append(fallback_run)
        self.evidence['collections']['patents'].append(
            {'evidence_id': 'EV-FALLBACK', 'source_run_id': 'RUN-FALLBACK'})
        self.task = load_json(self.root / 'task.json')
        self.save()
        atomic_write_json(self.input, {'provider': 'pps_browser', 'query_id': 'Q-FALLBACK',
            'source_run_id': 'RUN-FALLBACK', 'reviewer': 'source-maintainer',
            'reason': 'Fallback request and retained response were checked.', 'decision': 'accepted',
            'checks': {'request_response_binding': True, 'field_effect': 'verified',
                'pagination': 'single_page', 'known_number': 'not_applicable',
                'original_content': 'not_applicable', 'current_status': 'not_applicable'}})
        record(self.root, self.input)
        entries = work_entries(load_json(self.root / 'task.json'), self.plan,
                               self.evidence, self.root)
        self.assertEqual(entries, [])

        # Invalid lineage must not retire the rejected source's review work.
        self.plan['queries']['pps_browser'][0]['parent_plan_entry_sha256'] = '0' * 64
        entries = work_entries(load_json(self.root / 'task.json'), self.plan,
                               self.evidence, self.root)
        self.assertTrue(any(item['query_id'] == parent['query_id'] and
                            item['reason'] == 'SOURCE_OPERATION_REJECTED_REPLAN_REQUIRED'
                            for item in entries))

    def test_generated_operation_work_has_dispatch_cards(self):
        from advance_work import action_card
        for decision in (None, 'rejected'):
            if decision:
                self.review(decision=decision, field_effect='failed')
            entries = work_entries(load_json(self.root / 'task.json'), self.plan,
                                   self.evidence, self.root)
            self.assertTrue(entries)
            card = action_card(self.root, entries[0])
            self.assertEqual(card['action'], 'review_source_operation_or_replan')
            self.assertEqual(card['query_id'], 'Q-1')
            self.assertFalse(operation_accepted(self.caps()['source_browser'], self.row))
        changed = {**self.evidence, 'source_runs': [{**self.run, 'operation': 'detail'}]}
        entries = work_entries(load_json(self.root / 'task.json'), self.plan, changed, self.root)
        self.assertEqual(entries[0]['reason'], 'SOURCE_OPERATION_RUN_BINDING_INVALID')
        self.assertEqual(action_card(self.root, entries[0])['action'], 'review_source_operation_or_replan')

    def test_changed_response_or_query_invalidates_acceptance(self):
        self.review()
        self.task = load_json(self.root / 'task.json')
        self.evidence['source_runs'][0]['payload_digest'] = '0' * 64
        self.save()
        with self.assertRaisesRegex(ValueError, 'RUN_CHANGED'):
            self.caps()

    def test_changed_query_keeps_old_review_but_does_not_accept_new_expression(self):
        self.review()
        self.task = load_json(self.root / 'task.json')
        self.row['q'] = 'locarno:21-02'
        self.save()
        self.assertFalse(operation_accepted(self.caps()['source_browser'], self.row))
        self.assertEqual(len(self.task['source_operation_reviews']), 1)

    def test_fixture_response_cannot_be_accepted_as_live_capability(self):
        self.run['source_environment'] = 'offline'
        self.save()
        with self.assertRaisesRegex(ValueError, 'NON_PRODUCTION_RESPONSE'):
            self.review()

    def test_maintainer_registry_reuses_exact_acceptance_in_another_task(self):
        review = self.review()
        path = self.root / 'maintainer-registry.json'
        atomic_write_json(path, {'schema_version': 'source-operation-registry-v1', 'entries': []})
        with patch.object(registry, 'REGISTRY_PATH', path):
            registry.promote(self.root, review['review_id'], maintainer='source-maintainer',
                             acceptance_reason='Inspected the retained request and response binding.',
                             input_mode='classification field',
                             limitations='One-page fixture contract; live source review required.',
                             adapter_version='fields-v1', path=path)
            self.assertEqual(len(registry.read()['entries']), 1)
            second = {'task_id': 'SECOND', 'source_operation_revision': 'source-operation-v1',
                      'completion_policy_revision': 'necessary-work-v3'}
            plan = {'task_id': 'SECOND', 'queries': {'source_browser': [self.row]}}
            evidence = {'task_id': 'SECOND', 'source_runs': []}
            cap = {'provider': 'source_browser', 'executable': False,
                   'operations': registry.operations_for('source_browser'),
                   'operation_states': registry.current_entries('source_browser')}
            from necessary_completion import sanitize_snapshots
            frozen = sanitize_snapshots(second, {'source-capabilities.json':
                {'task_id': 'SECOND', 'sources': [cap]}})
            cap = frozen['source-capabilities.json']['sources'][0]
            resolved = resolved_capabilities(second, evidence, plan,
                                             {'source_browser': cap}, self.root)
            self.assertTrue(operation_accepted(resolved['source_browser'], self.row))
            self.assertFalse(operation_accepted(resolved['source_browser'],
                                                {**self.row, 'search_dimension': 'text'}))
            forged = {'source_browser': {**cap, 'operations': [{**self.row,
                'registry_entry_sha256': '0' * 64}]}}
            self.assertFalse(operation_accepted(resolved_capabilities(second, evidence, plan,
                forged, self.root)['source_browser'], self.row))
            anomaly = self.review(decision='rejected', field_effect='failed', pagination='failed')
            original = resolved_capabilities(load_json(self.root / 'task.json'),
                load_json(self.root / 'evidence.json'), load_json(self.root / 'search-plan.json'),
                {'source_browser': cap}, self.root)
            self.assertFalse(operation_accepted(original['source_browser'], self.row))
            registry.promote(self.root, anomaly['review_id'], maintainer='source-maintainer',
                             acceptance_reason='Field ignored and first page repeated.',
                             input_mode='classification field', limitations='Unavailable pending adapter repair.',
                             adapter_version='fields-v1', state='unvalidated', path=path)
            self.assertEqual(len(registry.read()['entries']), 2)
            self.assertEqual(registry.operations_for('source_browser'), [])
            self.assertEqual(registry.current_entries('source_browser')[0]['state'], 'unvalidated')
            self.assertFalse(operation_accepted(resolved_capabilities(second, evidence, plan,
                {'source_browser': cap}, self.root)['source_browser'], self.row))
            old_local = load_json(self.root / 'task.json')
            old_local['source_operation_reviews'] = [review]
            self.assertFalse(operation_accepted(resolved_capabilities(old_local,
                load_json(self.root / 'evidence.json'), load_json(self.root / 'search-plan.json'),
                {'source_browser': cap}, self.root)['source_browser'], self.row))

    def test_maintainer_unavailable_state_defers_exact_dispatch(self):
        import test_scenario_planning as fixture_module
        from workflow_v24 import scenario_dispatch_block
        fixture = fixture_module.ScenarioPlanningTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        provider, row = next((provider, row) for provider, rows in fixture.plan['queries'].items()
                             for row in rows)
        key = tuple(row.get(name, '') for name in ('jurisdiction', 'right_type',
            'operation', 'query_compiler_revision', 'search_dimension'))
        with patch.object(registry, 'latest_states', return_value={key: 'unavailable'}):
            block = scenario_dispatch_block(fixture.task, fixture.plan, provider, row,
                fixture.candidates, fixture.ledger, fixture.evidence)
        self.assertEqual(block['reason'], 'SOURCE_OPERATION_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()

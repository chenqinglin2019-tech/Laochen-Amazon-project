"""03C scope cancellation is bound to a confirmed, retained change identity."""
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from common import CURRENT_SCHEMA_VERSION, RECALL_INTEGRITY_REVISION, atomic_write_json, sha256_json
from scope_cancellation import record
from workflow_v24 import validated_query_cancellation


class ScopeCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = {'query_id': 'Q-removed', 'jurisdiction': 'US', 'right_type': 'design',
                    'operation': 'search', 'product_dependencies': [
                        {'scenario_id': 'product_entry', 'direction_id': 'outline'}]}
        event = {'change_id': 'CHG-1', 'kind': 'scope_change', 'scope_sha256': 'new-scope',
                 'affected_query_ids': ['Q-removed'], 'affected_direction_ids': ['outline'],
                 'reason': 'User confirmed the outline is outside the target scope.'}
        event['sha256'] = sha256_json(event)
        self.task = {'task_id': 'OFFLINE-03C', 'schema_version': CURRENT_SCHEMA_VERSION,
                     'screening_revision': RECALL_INTEGRITY_REVISION,
                     'source_operation_revision': 'source-operation-v1',
                     'product_scope_revision': 'object-scope-v1',
                     'product_scope': {'status': 'reviewed', 'scope_sha256': 'new-scope',
                                       'directions': [], 'objects': [], 'facts': []},
                     'product_change_pending': False, 'product_change_history': [event]}
        self.plan = {'task_id': 'OFFLINE-03C', 'schema_version': CURRENT_SCHEMA_VERSION,
                     'screening_revision': RECALL_INTEGRITY_REVISION,
                     'queries': {'browser': [self.row]}, 'execution_dispositions': []}

    def save(self):
        atomic_write_json(self.root / 'task.json', self.task)
        atomic_write_json(self.root / 'search-plan.json', self.plan)

    def test_unbound_cancellation_does_not_suppress_removed_direction(self):
        self.plan['execution_dispositions'].append({'query_id': 'Q-removed',
            'plan_entry_sha256': sha256_json(self.row), 'status': 'cancelled',
            'reason': 'Scope changed'})
        self.assertIsNone(validated_query_cancellation(self.task, self.plan, self.row))
        self.save()
        item = record(self.root, 'Q-removed', 'CHG-1', 'reviewer',
                      'Confirmed scope change removes the entire query direction.')
        self.plan['execution_dispositions'].append(item)
        self.assertEqual(validated_query_cancellation(self.task, self.plan, self.row), item)
        self.assertEqual(len(self.plan['execution_dispositions']), 2)

    def test_pending_change_cannot_cancel(self):
        self.task['product_change_pending'] = True
        self.save()
        with self.assertRaisesRegex(ValueError, 'CHANGE_UNCONFIRMED'):
            record(self.root, 'Q-removed', 'CHG-1', 'reviewer', 'Still pending')

    def test_candidate_links_preserve_exact_business_scope_cancellation(self):
        event = self.task['product_change_history'][0]
        event.update(version=3, target_sha256='target')
        event['sha256'] = sha256_json({k: v for k, v in event.items() if k != 'sha256'})
        self.task.update(product_change_version=3, product_identity={'sha256': 'target'})
        self.save()
        item = record(self.root, 'Q-removed', 'CHG-1', 'reviewer', 'Confirmed removal')
        self.plan['execution_dispositions'].append(item)
        self.task['product_scope'].update(scope_sha256='linked-scope', candidate_links=[{'candidate_id': 'new'}])
        self.assertEqual(validated_query_cancellation(self.task, self.plan, self.row), item)
        self.task['product_scope']['facts'] = [{'fact_id': 'changed', 'value': 'new'}]
        self.assertIsNone(validated_query_cancellation(self.task, self.plan, self.row))
        self.task['product_scope']['facts'] = []
        self.task['product_change_version'] = 4
        self.assertIsNone(validated_query_cancellation(self.task, self.plan, self.row))

    def test_obsolete_local_mark_target_requires_reviewed_empty_new_scope(self):
        self.task['product_scope']['directions'] = [{'scenario_id': 'product_entry',
            'direction_id': 'outline', 'right_type': 'trademark_figurative'}]
        self.row.update(operation='provenance_review', right_type='trademark_figurative',
            action_purpose='provenance', derived_from=['product.mark_inventory'],
            search_dimension='classification', asset_scope_sha256='old-inventory')
        scope = {'inventory_reviewed': True, 'asset_ids': [], 'scope_sha256': 'new-inventory'}
        with patch('product_scope.direction_state', return_value='ready'), \
             patch('record_asset_provenance.asset_scope', return_value=scope):
            self.save()
            item = record(self.root, 'Q-removed', 'CHG-1', 'reviewer', 'Confirmed empty inventory replaces old local target')
            self.assertEqual(item['status'], 'cancelled')
            from scope_cancellation import scope_change_required
            for invalid in ({**scope, 'inventory_reviewed': False}, {**scope, 'asset_ids': ['logo']},
                            {**scope, 'scope_sha256': 'old-inventory'}):
                with patch('record_asset_provenance.asset_scope', return_value=invalid):
                    self.assertFalse(scope_change_required(self.task, self.row))
            self.row['operation'] = 'trademark_recall'
            self.assertFalse(scope_change_required(self.task, self.row))


if __name__ == '__main__':
    unittest.main()

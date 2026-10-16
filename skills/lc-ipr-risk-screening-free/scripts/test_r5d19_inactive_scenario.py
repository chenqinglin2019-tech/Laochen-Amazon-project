"""r5d19 (run B0H16FDSD8 resumed, 2026-10-14): a conditional scenario the task never activated.

The owner said "own brand, ignore the reference brand", so the product scope left brand_reuse out of
execution_scenario_ids and gave it no necessary work. The final review still asks for its two trademark rows; in both
chains the expression module wrote them out_of_scope, and the validator refused that three times
(OUT_OF_SCOPE_NOT_BOUND_TO_TASK) because only assessment_scope_exclusions counted as a task binding. The resumed run
then stopped in the final review with every other module finished.

Golden replay of the real run (scratchpad golden19/g19.py): the r5d18 code refuses the retained answers again
(FINAL_REVIEW_SLOT_RETRY_LIMIT_REACHED); with this rule the host keeps all six real module answers, runs only the two
chain summaries, adjudication settles every unit automatically and the report is published.
"""
from copy import deepcopy
import unittest
from unittest import mock

import assessment_estimate as estimates
import pipeline_robust
import prepare_adjudication as pa
import test_product_scope_review as scope_fixtures


class InactiveConditionalScenarioTests(unittest.TestCase):
    def setUp(self):
        self.base = scope_fixtures.ProductScopeReviewTests('test_all_pending_overall_scopes_remain_acceptable')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.task = deepcopy(self.base.task)
        self.task['execution_scenario_ids'] = ['product_entry']

    def excluded(self, scenario='brand_reuse', rows=None):
        rows = deepcopy(rows if rows is not None else self.base.rows)
        for row in rows:
            if row['scenario_id'] == scenario:
                row.pop('pending_reasoning', None)
                row.update(out_of_scope=True, risk=None, assessment_status='assessed',
                           scope_reasoning='The owner sells under an own brand and asked to ignore the reference brand.')
        return rows

    def test_rows_of_an_inactive_conditional_scenario_may_be_out_of_scope(self):
        rows = self.excluded()
        self.assertTrue(any(row['scenario_id'] == 'brand_reuse' and row['out_of_scope'] for row in rows))
        self.base.validate(rows, self.task)

    def test_the_answers_of_earlier_runs_stay_valid(self):
        # B0GLNPC6K8 answered these rows pending, B0HF19R4YF rated them; neither changes.
        self.base.validate(self.base.rows, self.task)

    def test_an_activated_conditional_scenario_still_needs_a_task_exclusion(self):
        task = deepcopy(self.task)
        task['execution_scenario_ids'] = ['product_entry', 'brand_reuse']
        with self.assertRaisesRegex(ValueError, 'OUT_OF_SCOPE_NOT_BOUND_TO_TASK'):
            self.base.validate(self.excluded(), task)

    def test_the_primary_scenario_is_never_excluded_this_way(self):
        with self.assertRaisesRegex(ValueError, 'OUT_OF_SCOPE_NOT_BOUND_TO_TASK'):
            self.base.validate(self.excluded('product_entry'), self.task)

    def test_a_task_without_the_execution_record_keeps_the_explicit_rule(self):
        task = deepcopy(self.task)
        task.pop('execution_scenario_ids')
        with self.assertRaisesRegex(ValueError, 'OUT_OF_SCOPE_NOT_BOUND_TO_TASK'):
            self.base.validate(self.excluded(), task)

    def test_an_older_execution_policy_keeps_the_explicit_rule(self):
        task = deepcopy(self.task)
        task['completion_policy_revision'] = 'necessary-work-v3'
        task.pop('execution_policy_revision')
        with self.assertRaisesRegex(ValueError, 'OUT_OF_SCOPE_NOT_BOUND_TO_TASK'):
            self.base.validate(self.excluded(), task)

    def test_the_out_of_scope_contract_itself_is_unchanged(self):
        for change in ({'scope_reasoning': ''}, {'risk': '低'}, {'title': ''}):
            rows = self.excluded()
            next(row for row in rows if row['scenario_id'] == 'brand_reuse').update(change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'OUT_OF_SCOPE_CONTRACT_INVALID'):
                self.base.validate(rows, self.task)

    def test_every_required_scope_is_still_required(self):
        rows = [row for row in self.excluded()
                if not (row['scenario_id'] == 'brand_reuse' and row['right_type'] == 'trademark_word'
                        and row['jurisdiction'] == 'US')]
        with self.assertRaisesRegex(ValueError, 'REVIEW_PRODUCT_SCOPE_MISSING'):
            self.base.validate(rows, self.task)

    def test_the_rule_is_read_from_the_task_not_from_the_row(self):
        row = next(row for row in self.excluded() if row['scenario_id'] == 'brand_reuse')
        self.assertTrue(estimates._scope_excluded(row, self.task))
        self.assertFalse(estimates._scope_excluded(dict(row, scenario_id='product_entry'), self.task))
        self.assertFalse(estimates._scope_excluded(dict(row, scenario_id='no_such_scenario'), self.task))
        broken = deepcopy(self.task)
        broken['execution_scenario_ids'] = 'product_entry'
        self.assertFalse(estimates._scope_excluded(row, broken))     # a malformed record never widens the rule



class DivergentInactiveRowsTests(unittest.TestCase):
    """One review writes such a row out of scope, the other pending: no grade on either side, no checkpoint 3."""

    def setUp(self):
        base = scope_fixtures.ProductScopeReviewTests('test_all_pending_overall_scopes_remain_acceptable')
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.task = dict(deepcopy(base.task), execution_scenario_ids=['product_entry'],
                         pipeline_robust_revision=pipeline_robust.REVISION)

    @staticmethod
    def row(scenario='brand_reuse', **change):
        out = {'scenario_id': scenario, 'jurisdiction': 'US', 'right_type': 'trademark_word', 'candidate_id': None,
               'assessment_object': 'product', 'risk': None, 'assessment_status': 'assessed', 'out_of_scope': True,
               'scope_reasoning': 'Own brand; the reference brand is ignored.'}
        out.update(change)
        return {key: value for key, value in out.items() if value is not None or key in ('risk', 'candidate_id')}

    def pending(self, scenario='brand_reuse'):
        return self.row(scenario, out_of_scope=None, scope_reasoning=None, assessment_status='pending',
                        pending_reasoning='No search for the reference brand was run.')

    def settle(self, first, second, task=None):
        decision = dict(first, adjudication_reasoning='')
        with mock.patch('assessment_estimate.best_estimate_v2', return_value=False):
            agreed, _ = pa._auto_complete(task or self.task, {}, [decision], {'1': first}, {'2': second}, {}, [])
        return agreed, decision

    def test_out_of_scope_against_pending_is_carried_as_drafted(self):
        for first, second in ((self.row(), self.pending()), (self.pending(), self.row())):
            agreed, decision = self.settle(first, second)
            with self.subTest(first=first.get('assessment_status')):
                self.assertEqual(agreed, 1)
                self.assertIsNone(decision['risk'])
                self.assertEqual(decision.get('out_of_scope'), first.get('out_of_scope'))
                self.assertIn('未纳入范围', decision['adjudication_reasoning'])
                self.assertIn('不赋予风险等级', decision['adjudication_reasoning'])

    def test_everything_else_stays_with_the_chief(self):
        active = dict(self.task, execution_scenario_ids=['product_entry', 'brand_reuse'])
        older = {key: value for key, value in self.task.items() if key != 'pipeline_robust_revision'}
        for label, first, second, task in (
                ('activated scenario', self.row(), self.pending(), active),
                ('primary scenario', self.row('product_entry'), self.pending('product_entry'), None),
                ('one side graded', self.row(), self.row(out_of_scope=None, scope_reasoning=None, risk='低'), None),
                ('task before r5d4', self.row(), self.pending(), older)):
            agreed, decision = self.settle(first, second, task)
            with self.subTest(label):
                self.assertEqual((agreed, decision['adjudication_reasoning']), (0, ''))


if __name__ == '__main__':
    unittest.main()

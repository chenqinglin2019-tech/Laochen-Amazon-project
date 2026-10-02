"""Offline budget-stop delivery with all original integrity/review gates active."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_json
import execution_budget as budget
from assessment_estimate import review_digest
from final_review import inputs, prepare_rows
from offline_test_support import isolated_test_environment
from publish_report import publish
from report_estimate import validate_run
from test_evidence_delivery_integration import build_evidence_delivery_fixture
from workflow_v24 import work_view_from_dir


class BudgetDeliveryTests(unittest.TestCase):
    def fixture(self, scenario='pending'):
        temporary = tempfile.TemporaryDirectory(prefix='ipr-budget-delivery-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'source'
        build_evidence_delivery_fixture(self.root, scenario=scenario, operator_policy=True)
        self.task = load_json(self.root / 'task.json')
        self.evidence = load_json(self.root / 'evidence.json')
        self.plan = load_json(self.root / 'search-plan.json')
        self.candidates = load_json(self.root / 'normalized-candidates.json')
        self.ledger = load_json(self.root / 'materiality-annotations.json')
        self.task.update(execution_policy_revision='continuous-work-v2', execution_budget_revision=budget.REVISION,
                         execution_budget=deepcopy(budget.DEFAULTS))
        atomic_write_json(self.root / 'task.json', self.task)
        journal = budget._read(self.root, self.task, budget.policy(self.task))
        journal['used_seconds'] = budget.DEFAULTS['active_seconds']
        atomic_write_json(self.root / budget.JOURNAL, journal)
        removed = next(run for run in self.evidence['source_runs'] if run.get('right_type') == 'patent')
        self.query = removed['query_id']
        self.evidence['source_runs'] = [run for run in self.evidence['source_runs'] if run.get('query_id') != self.query]
        lost = {row.get('evidence_id') for rows in self.evidence['collections'].values() for row in rows
                if row.get('source_run_id') == removed['run_id'] or row.get('query_id') == self.query}
        for key, rows in self.evidence['collections'].items():
            self.evidence['collections'][key] = [row for row in rows if row.get('evidence_id') not in lost]
        atomic_write_json(self.root / 'evidence.json', self.evidence)
        def prune(value):
            if isinstance(value, dict):
                return {k: [ref for ref in v if ref not in lost] if k == 'evidence_refs' and isinstance(v, list)
                        else prune(v) for k, v in value.items()}
            return [prune(v) for v in value] if isinstance(value, list) else value
        digest = review_digest(self.evidence, self.candidates, self.ledger, self.plan, self.task)
        for name in ('first-review.json', 'second-review.json'):
            review = prune(load_json(self.root / name))
            rows, binding = prepare_rows({'final_review_statement': review['review_context']['final_review']['statement']},
                                        review['assessments'], inputs(self.evidence, self.candidates, self.ledger, self.plan, self.task))
            review['assessments'] = rows
            ctx = review['review_context']; ctx.update(evidence_digest=digest, final_review=binding)
            ctx['execution'].update(input_digest=digest, assessment_digest=sha256_json(rows), final_review_digest=sha256_json(binding))
            atomic_write_json(self.root / name, review)
        self.first, self.second = self.root / 'first-review.json', self.root / 'second-review.json'
        self.view = work_view_from_dir(self.root, first_review=load_json(self.first), second_review=load_json(self.second))
        self.entry = next(row for row in self.view['entries'] if row.get('query_id') == self.query)

    def publish(self, mode='evidence'):
        return publish(self.root, self.first, self.second, output_dir=self.root / ('output-' + mode), mode=mode)

    def test_stopped_unexecuted_query_delivers_nine_pending_cards(self):
        with isolated_test_environment():
            self.fixture(); result = self.publish()
            self.assertEqual(result['business_completion'], 'incomplete')
            self.assertEqual(result['delivery_status'], 'completed')
            data = load_json(self.root / 'output-evidence/report-data.json')
            self.assertIsNone(data['overall']['risk'])
            self.assertEqual(data['overall']['listing_recommendation'], '暂缓上架')
            self.assertEqual(len(data['operator_view']['modules']), 9)
            for card in data['operator_view']['modules']:
                if card['risk'] is None and card['query_status'] != '不适用':
                    self.assertEqual(card['risk_label'], '待定'); self.assertTrue(card['unfinished'])
            limits = data['publication']['limitations']
            self.assertTrue(any(row.get('limitation_kind') == 'internal_execution_budget' and
                                row.get('source_query_performed') is False and row.get('query_id') == self.query for row in limits))
            self.assertEqual(validate_run(self.root, load_json(self.root / 'output-evidence/task.json'),
                                          output_dir=self.root / 'output-evidence'), [])

    def test_source_stop_remains_disclosed_during_reserved_review(self):
        from review_readiness import preparation_issues_from_dir
        with isolated_test_environment():
            self.fixture()
            journal = load_json(self.root / budget.JOURNAL)
            journal['used_seconds'] = budget.DEFAULTS['active_seconds'] - budget.DEFAULTS['review_reserve_seconds']
            atomic_write_json(self.root / budget.JOURNAL, journal)
            with budget.execution_budget(self.root, 'review'):
                view = work_view_from_dir(self.root, first_review=load_json(self.first), second_review=load_json(self.second))
                entry = next(row for row in view['entries'] if row.get('query_id') == self.query)
                self.assertEqual(entry['limitation_kind'], 'internal_execution_budget')
                self.assertTrue(preparation_issues_from_dir(self.root)['ready'])

    def test_known_high_survives_budget_stop_and_final_is_rejected(self):
        with isolated_test_environment():
            self.fixture('mixed_high'); self.publish()
            data = load_json(self.root / 'output-evidence/report-data.json')
            self.assertEqual(data['overall']['risk'], '高')
            self.assertEqual(data['overall']['listing_recommendation'], '不建议上架')
            with self.assertRaisesRegex(ValueError, 'PUBLICATION_NECESSARY_WORK_INCOMPLETE'):
                self.publish('final')

    def test_budget_proof_cannot_hide_read_triage_unknown_or_integrity_work(self):
        with isolated_test_environment():
            self.fixture()
            for mutation in ({'kind': 'agent_read'}, {'kind': 'triage'}, {'candidate_id': 'selected-candidate'},
                             {'state': 'submission_unknown', 'underlying_state': 'submission_unknown'},
                             {'integrity_failure': True}, {'source_run_refs': [{'run_id': 'unread-original'}]}):
                with self.subTest(mutation=mutation):
                    self.assertIsNone(budget.delivery_limit(self.task, self.evidence, self.plan,
                        {**self.entry, **mutation}, self.root))
            evidence = deepcopy(self.evidence)
            evidence['source_runs'].append({'run_id': 'uncertain', 'query_id': self.query, 'submission_state': 'unknown'})
            self.assertIsNone(budget.delivery_limit(self.task, evidence, self.plan, self.entry, self.root))
            evidence = deepcopy(self.evidence)
            evidence['collections']['available'] = [{'query_id': self.query, 'payload': {'documents': ['readable-original']}}]
            self.assertIsNone(budget.delivery_limit(self.task, evidence, self.plan, self.entry, self.root))

    def test_interrupted_api_or_browser_submission_cannot_be_called_unexecuted(self):
        with isolated_test_environment():
            self.fixture()
            for name, payload in (
                ('execution-status.json', {'pending_submissions': {self.query: {'submission_state': 'unknown'}}}),
                ('execution-status.json', {'results': [{'query_id': self.query, 'dispatch': 'executed'}]}),
                ('browser-execution-status.json', {'queries': [{'query_id': self.query, 'submission_state': 'unknown'}]})):
                with self.subTest(name=name, payload=payload):
                    atomic_write_json(self.root / name, payload)
                    self.assertIsNone(budget.delivery_limit(self.task, self.evidence, self.plan, self.entry, self.root))
                    (self.root / name).unlink()
            evidence = deepcopy(self.evidence)
            evidence['progress_events'] = [{'kind': 'begin', 'query_id': self.query}]
            self.assertIsNone(budget.delivery_limit(self.task, evidence, self.plan, self.entry, self.root))

    def test_missing_review_and_altered_original_remain_rejected(self):
        with isolated_test_environment():
            self.fixture()
            original = self.second.read_bytes(); self.second.unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                self.publish()
            self.second.write_bytes(original)
            (self.root / 'public-source.html').write_text('changed original')
            with self.assertRaises(ValueError):
                self.publish()

    def test_resumed_budget_invalidates_published_limit(self):
        with isolated_test_environment():
            self.fixture(); self.publish()
            journal = load_json(self.root / budget.JOURNAL); journal['used_seconds'] = 0
            atomic_write_json(self.root / budget.JOURNAL, journal)
            self.assertIsNone(budget.delivery_limit(self.task, self.evidence, self.plan, self.entry, self.root))
            self.assertTrue(validate_run(self.root, load_json(self.root / 'output-evidence/task.json'),
                                         output_dir=self.root / 'output-evidence'))

    def test_dispatch_publish_reaches_partial_gate_after_stop(self):
        import advance_work
        import io
        from contextlib import redirect_stdout
        with isolated_test_environment():
            self.fixture()
            chief = self.root / 'adjudication.json'; first, second = load_json(self.first), load_json(self.second)
            atomic_write_json(chief, {'reviewer': 'offline-chief', 'review_context': {
                'session_id': 'offline-chief', 'evidence_digest': first['review_context']['evidence_digest']},
                'decisions': [], 'review_refs': {'first': sha256_json(first), 'second': sha256_json(second)}})
            with patch('sys.argv', ['advance_work.py', '--task-dir', str(self.root), '--publish',
                      '--output-dir', str(self.root / 'dispatch-output')]), redirect_stdout(io.StringIO()):
                advance_work.main()
            self.assertTrue((self.root / 'dispatch-output/report.html').is_file())


if __name__ == '__main__':
    unittest.main()

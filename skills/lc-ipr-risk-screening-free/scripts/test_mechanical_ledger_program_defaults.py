"""Program-default closures: a 03C acceptance only from the exact acceptance proof of the retained response, and an
after-result review that ends a bounded single-page public scope only when the work view's own proof holds."""
from contextlib import ExitStack
from unittest.mock import patch
import unittest

from common import atomic_write_json, load_json, sha256_file, sha256_json


class ProgramDefaultFixture(unittest.TestCase):
    CONTEXT = {'credential_fingerprint_sha256': 'c' * 64, 'permission_fingerprint_sha256': 'p' * 64,
               'adapter_version': 'a' * 64}

    def setUp(self):
        import test_discovery_semantics as fixtures
        self.h = fixtures.DiscoverySemanticsTests('test_unmapped_only_rereview_keeps_submitted_chain')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.root = self.h.f.run
        task = load_json(self.root / 'task.json')
        task['retrieval_workflow_revision'] = 'api-first-v3'
        atomic_write_json(self.root / 'task.json', task)
        # The fixture's design discovery row becomes a frozen single-page US design search on SerpApi.
        plan = load_json(self.root / 'search-plan.json')
        rows = plan['queries'].pop(self.h.provider)
        row = next(r for r in rows if r['query_id'] == self.h.row['query_id'])
        rest = [r for r in rows if r is not row]
        if rest:
            plan['queries'][self.h.provider] = rest
        row.update(operation='search', type='DESIGN', country='US', num=10)
        row['discovery_scope'].update(max_pages=1, max_candidates=10)
        plan['queries']['serpapi_google_patents'] = [row]
        atomic_write_json(self.root / 'search-plan.json', plan)
        self.row, self.provider = row, 'serpapi_google_patents'
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target, value in (('common.assert_provider_execution_allowed', None),
                              ('source_operation.operation_acceptance_context', self.CONTEXT),
                              ('source_operation.load_skill_config', {'providers': {'serpapi_google_patents': {}}})):
            self.stack.enter_context(patch(target, return_value=value))
        if not (self.root / 'normalized-candidates.json').is_file():
            atomic_write_json(self.root / 'normalized-candidates.json', {})
        self.h.direction()
        self.h.before()

    def retained_run(self, run_id, q=None, **coverage):
        """One retained SerpApi design response with its trusted receipt entry, appended to the evidence."""
        from trusted_api import annotate_entry
        raw = self.root / 'raw' / 'serpapi_google_patents' / (run_id + '.json')
        raw.parent.mkdir(parents=True, exist_ok=True)
        params = {'engine': 'google_patents', 'q': self.row['q'] if q is None else q, 'type': 'DESIGN',
                  'country': 'US', 'num': '10'}
        atomic_write_json(raw, {'search_parameters': params, 'organic_results': []})
        run = {'run_id': run_id, 'provider': self.provider, 'query_id': self.row['query_id'],
               'plan_entry_sha256': sha256_json(self.row), 'operation': 'search', 'jurisdiction': 'US',
               'right_type': 'design', 'status': 'success', 'submission_state': 'submitted',
               'source_environment': 'commercial_account_capacity', 'raw_paths': [str(raw)],
               'payload_digest': sha256_file(raw), 'finished_at': '2026-10-11T00:00:00Z',
               'request_params': {'country': 'US', 'num': 10, 'q': self.row['q'], 'right_type': 'design'},
               'metadata': {'search_coverage': {'schema_valid': True, 'truncated': True, 'total_hits': None,
                   'retrieved_hits': 10, 'reviewed_hits': None, 'stop_reason': 'bounded_discovery_total_unknown',
                   **coverage}}}
        entry = {'evidence_id': 'EV-' + run_id, 'source_run_id': run_id, 'provider': self.provider,
                 'operation': 'search', 'query_id': self.row['query_id'], 'jurisdiction': 'US', 'right_type': 'design',
                 'plan_entry_sha256': sha256_json(self.row), 'payload': {'candidates': [], 'status': 'success'}}
        annotate_entry(load_json(self.root / 'task.json'), entry, run)
        evidence = load_json(self.root / 'evidence.json')
        evidence.setdefault('source_runs', []).append(run)
        evidence['collections'].setdefault('patents', []).append(entry)
        atomic_write_json(self.root / 'evidence.json', evidence)
        return run, entry

    def accept(self, run, entry):
        """The persisted first-response acceptance of the operation (what provider_utils writes after a real call)."""
        from source_operation import record_operation_acceptance
        task, evidence = load_json(self.root / 'task.json'), load_json(self.root / 'evidence.json')
        acceptance = record_operation_acceptance(self.root, task, evidence, self.row, run, entry)
        self.assertEqual(acceptance['state'], 'accepted')
        evidence.setdefault('operation_acceptances', []).append(acceptance)
        atomic_write_json(self.root / 'evidence.json', evidence)
        return acceptance

    def snapshot(self):
        files = {name: (self.root / name).read_bytes() for name in ('task.json', 'evidence.json')}
        receipts = set((self.root / 'raw' / 'discovery_semantics').glob('*.json'))
        return files, receipts


class OperationReviewTests(ProgramDefaultFixture):
    def test_reviews_come_only_from_the_exact_acceptance_proof(self):
        import mechanical_ledger as ml
        import source_operation as so
        first, first_entry = self.retained_run('RUN-FIRST')
        self.accept(first, first_entry)
        self.retained_run('RUN-SECOND')          # same operation, later response: proven by re-running the acceptance
        result = ml.auto_operation_reviews(self.root)
        self.assertEqual((result['status'], result['recorded'], result['left_for_agent']), ('done', 2, []))
        task = load_json(self.root / 'task.json')
        reviews = task['source_operation_reviews']
        self.assertEqual({r['source_run_id'] for r in reviews}, {'RUN-FIRST', 'RUN-SECOND'})
        for review in reviews:
            self.assertEqual((review['reviewer'], review['decision'], review['checks']['pagination'],
                              review['checks']['request_response_binding'], review['checks']['field_effect']),
                             (ml.OPERATION_REVIEWER, 'accepted', 'single_page', True, 'verified'))
        by_run = {r['source_run_id']: r['reason'] for r in reviews}
        self.assertIn('已持久化', by_run['RUN-FIRST'])
        self.assertIn('重算一致', by_run['RUN-SECOND'])
        so.verify(task, load_json(self.root / 'search-plan.json'), load_json(self.root / 'evidence.json'), self.root)
        self.assertEqual(len(list((self.root / 'raw' / 'source_operation').glob('*.json'))), 2)
        self.assertEqual(ml.auto_operation_reviews(self.root)['recorded'], 0)        # idempotent

    def test_without_a_current_proof_or_an_exact_request_echo_nothing_is_accepted(self):
        import mechanical_ledger as ml
        run, entry = self.retained_run('RUN-ONLY')
        before = (self.root / 'task.json').read_bytes()
        result = ml.auto_operation_reviews(self.root)                                # no acceptance at all
        self.assertEqual((result['recorded'], [e['reason'] for e in result['left_for_agent']]),
                         (0, ['OPERATION_ACCEPTANCE_MISSING']))
        self.assertEqual((self.root / 'task.json').read_bytes(), before)
        self.accept(run, entry)
        with patch('source_operation.operation_acceptance_context',
                   return_value={**self.CONTEXT, 'credential_fingerprint_sha256': 'n' * 64}):
            result = ml.auto_operation_reviews(self.root)                            # proof no longer current
        self.assertEqual((result['recorded'], [e['reason'] for e in result['left_for_agent']]),
                         (0, ['OPERATION_ACCEPTANCE_NOT_CURRENT']))
        self.assertEqual(ml.auto_operation_reviews(self.root)['recorded'], 1)
        self.retained_run('RUN-CHANGED', q='other query')                           # response echoes another request
        result = ml.auto_operation_reviews(self.root)
        self.assertEqual((result['recorded'], [e['reason'] for e in result['left_for_agent']]),
                         (0, ['REQUEST_ECHO_UNPROVEN:search_parameters']))
        self.assertEqual({r['source_run_id'] for r in load_json(self.root / 'task.json')['source_operation_reviews']},
                         {'RUN-ONLY'})

    def test_steps_are_registered_after_the_existing_ones(self):
        import mechanical_ledger as ml
        self.assertEqual(list(ml.STEPS)[-2:], ['operation_reviews', 'bounded_stop'])
        self.assertEqual(ml.auto_operation_reviews(self.root)['status'], 'done')     # nothing retained: nothing to do


class BoundedStopTests(ProgramDefaultFixture):
    def setUp(self):
        super().setUp()
        import mechanical_ledger as ml
        self.run, self.entry = self.retained_run('RUN-BOUNDED')
        self.accept(self.run, self.entry)
        self.assertEqual(ml.auto_operation_reviews(self.root)['recorded'], 1)       # the real 03C review of this response
        self.progress = self.stack.enter_context(patch('source_result_processing.progress',
            return_value={'material_processing_complete': True, 'returned_count': 10}))
        self.stack.enter_context(patch('api_first_planning.review_validation', return_value=None))
        self.stack.enter_context(patch('api_first_planning.source_files_error', return_value=None))

    def entries(self):
        import discovery_semantics as ds
        task, plan, evidence = (load_json(self.root / name) for name in ('task.json', 'search-plan.json', 'evidence.json'))
        return [e for e in ds.work_entries(task, plan, evidence, candidates={},
                                           ledger=load_json(self.root / 'materiality-annotations.json'), task_dir=self.root)
                if e.get('query_id') == self.row['query_id']]

    def host_pending(self):
        import discovery_review_host as host
        def view(*_args, **_kwargs):
            return {'entries': [{**e, 'work_id': 'WORK-%d' % i} for i, e in enumerate(self.entries())]}
        with patch('workflow_v24.work_view_from_dir', side_effect=view):
            return host.pending(self.root, 'after')

    def test_program_after_review_ends_the_bounded_scope_and_the_host_after_stage(self):
        import discovery_semantics as ds
        import mechanical_ledger as ml
        self.assertEqual([e['reason'] for e in self.entries()], ['DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED'])
        self.assertEqual(len(self.host_pending()), 1)
        result = ml.auto_bounded_stop(self.root)
        self.assertEqual((result['status'], result['closed_count'], result['left_for_agent']), ('done', 1, []))
        closed = result['closed'][0]
        self.assertEqual((closed['query_id'], closed['source_run_id'], closed['retrieval_scope_kind'],
                          closed['followup_recorded'], closed['direction_id']),
                         (self.row['query_id'], 'RUN-BOUNDED', 'bounded_us_design_api', True, 'outline'))
        task = load_json(self.root / 'task.json')
        after = [e for e in task['discovery_semantic_reviews'] if e['stage'] == 'after']
        self.assertEqual(len(after), 1)
        after = after[0]
        self.assertEqual((after['reviewer'], after['problem_covered'], after['next_action'], after['uncovered_clues'],
                          after['excluded_by_narrowing'], after['evidence_refs'], after['original_problem_checked']),
                         (ml.BOUNDED_STOP_REVIEWER, False, 'awaiting_capability', ['fact:shape'], [], ['EV-RUN-BOUNDED'], True))
        self.assertIn('不是覆盖声明', after['reason'])
        self.assertTrue((self.root / 'raw' / 'discovery_semantics' / (after['review_id'] + '.json')).is_file())
        followup = task['discovery_followups'][-1]
        self.assertEqual((followup['outcome'], followup['reviewer'], followup['source_run_id'], followup['role']),
                         ('stop_bounded_discovery', ml.BOUNDED_STOP_REVIEWER, 'RUN-BOUNDED', 'review'))
        ds.verify(task, load_json(self.root / 'search-plan.json'), load_json(self.root / 'evidence.json'), self.root)
        entries = self.entries()
        self.assertEqual([e['reason'] for e in entries], ['BOUNDED_PUBLIC_DISCOVERY_SCOPE_LIMITED'])
        self.assertEqual((entries[0]['state'], entries[0]['coverage_status'], entries[0]['uncovered_clues']),
                         ('blocked', 'unknown', ['fact:shape']))
        self.assertEqual(self.host_pending(), [])                                       # no after session for this unit
        again = ml.auto_bounded_stop(self.root)
        self.assertEqual((again['closed_count'], again['left_for_agent']), (0, []))
        self.assertEqual(len([e for e in load_json(self.root / 'task.json')['discovery_semantic_reviews']
                              if e['stage'] == 'after']), 1)

    def test_an_unproven_scope_writes_nothing(self):
        import mechanical_ledger as ml
        self.progress.return_value = {'material_processing_complete': False, 'returned_count': 10}
        files, receipts = self.snapshot()
        result = ml.auto_bounded_stop(self.root)
        self.assertEqual((result['closed_count'], [e['reason'] for e in result['left_for_agent']]),
                         (0, ['BOUNDED_SCOPE_PROOF_FAILED']))
        self.assertEqual(self.snapshot(), (files, receipts))
        self.assertEqual([e['reason'] for e in self.entries()], ['DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED'])

    def test_a_proof_that_fails_after_persisting_is_rolled_back(self):
        import mechanical_ledger as ml
        files, receipts = self.snapshot()
        def progress(*_args, **_kwargs):
            # complete while nothing has been persisted, incomplete as soon as the program receipt exists on disk
            persisted = set((self.root / 'raw' / 'discovery_semantics').glob('*.json')) != receipts
            return {'material_processing_complete': not persisted, 'returned_count': 10}
        self.progress.side_effect = progress
        result = ml.auto_bounded_stop(self.root)
        self.assertEqual(result['closed_count'], 0)
        self.assertTrue(result['left_for_agent'][0]['reason'].startswith('ROLLED_BACK:PERSISTED_PROOF_FAILED'))
        self.assertEqual(self.snapshot(), (files, receipts))
        self.assertEqual([e['reason'] for e in self.entries()], ['DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED'])

    def test_without_the_operation_review_the_unit_stays_with_the_agent(self):
        import mechanical_ledger as ml
        task = load_json(self.root / 'task.json')
        task['source_operation_reviews'] = []
        atomic_write_json(self.root / 'task.json', task)
        files, receipts = self.snapshot()
        result = ml.auto_bounded_stop(self.root)
        self.assertEqual((result['closed_count'], [e['reason'] for e in result['left_for_agent']]),
                         (0, ['BOUNDED_SCOPE_PROOF_FAILED']))
        self.assertEqual(self.snapshot(), (files, receipts))


if __name__ == '__main__':
    unittest.main()

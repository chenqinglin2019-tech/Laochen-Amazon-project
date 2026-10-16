"""Program-written ledger entries: only exact, hash-bound bindings; everything else stays manual."""
import unittest
from pathlib import Path

from common import atomic_write_json, load_json
from offline_test_support import isolated_test_environment


class MechanicalDispositionTests(unittest.TestCase):
    def setUp(self):
        import test_execution_efficiency
        import host_triage
        from source_result_processing import REVISION
        self.environment = isolated_test_environment()
        self.environment.__enter__()
        self.addCleanup(self.environment.__exit__, None, None, None)
        media = test_execution_efficiency.MediaTests()
        media.setUp()
        self.addCleanup(media.doCleanups)
        self.media = media
        self.root = media.f.root
        task = load_json(self.root / 'task.json')
        task.update(result_processing_revision=REVISION, host_triage_revision=host_triage.REVISION,
                    host_triage=dict(host_triage.DEFAULTS))
        atomic_write_json(self.root / 'task.json', task)
        # The shared fixture rewrote the run's receipt digest; start from no dispositions.
        evidence = load_json(self.root / 'evidence.json')
        evidence['result_dispositions'] = []
        atomic_write_json(self.root / 'evidence.json', evidence)

    def progress(self):
        from source_result_processing import progress
        evidence = load_json(self.root / 'evidence.json')
        run = next(r for r in evidence['source_runs'] if r['run_id'] == 'LENS-R')
        return progress(self.root, run, evidence)

    def test_every_hash_bound_row_gets_a_labelled_mechanical_disposition(self):
        import mechanical_ledger as ml
        before = self.progress()
        self.assertEqual(len(before['pending_positions']), 18)
        result = ml.auto_bind_dispositions(self.root)
        self.assertEqual((result['status'], result['bound_positions'], result['runs']), ('done', 18, 1))
        after = self.progress()
        self.assertEqual(after['pending_positions'], [])
        events = load_json(self.root / 'evidence.json')['result_dispositions']
        self.assertEqual({e['reviewer'] for e in events}, {ml.SOURCE_BINDING_REVIEWER})
        self.assertTrue(all(e['outcome'] == 'candidate' and len(e['candidate_ids']) == 1 for e in events))
        self.assertIn('机械绑定', events[0]['reason'])

    def test_second_run_is_idempotent(self):
        import mechanical_ledger as ml
        ml.auto_bind_dispositions(self.root)
        again = ml.auto_bind_dispositions(self.root)
        self.assertEqual(again['bound_positions'], 0)
        self.assertEqual(len(load_json(self.root / 'evidence.json')['result_dispositions']), 18)

    def test_rows_without_an_exact_candidate_binding_are_left_for_the_agent(self):
        import mechanical_ledger as ml
        candidates = load_json(self.root / 'normalized-candidates.json')
        rows = candidates['copyright_assets']
        rows[0]['sources'][0]['source_position'] = 2          # contradicts the row hash
        rows[1]['sources'][0] = {'source_run_id': 'LENS-R'}   # no position and no hash: not a binding
        atomic_write_json(self.root / 'normalized-candidates.json', candidates)
        result = ml.auto_bind_dispositions(self.root)
        self.assertEqual(result['bound_positions'], 16)
        pending = self.progress()['pending_positions']
        self.assertEqual(len(pending), 2)

    def test_task_without_host_marker_is_not_touched(self):
        import mechanical_ledger as ml
        task = load_json(self.root / 'task.json')
        task.pop('host_triage_revision')
        task.pop('host_triage')
        atomic_write_json(self.root / 'task.json', task)
        before = (self.root / 'evidence.json').read_bytes()
        self.assertEqual(ml.auto_bind_dispositions(self.root)['status'], 'not_applicable')
        self.assertEqual((self.root / 'evidence.json').read_bytes(), before)


class MechanicalLinkTests(unittest.TestCase):
    def setUp(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch
        import test_product_entry
        import test_product_scope
        import host_triage
        from PIL import Image
        self.environment = isolated_test_environment()
        self.environment.__enter__()
        self.addCleanup(self.environment.__exit__, None, None, None)
        stream = io.BytesIO()
        Image.new('RGB', (20, 20), 'red').save(stream, format='PNG')
        scope = test_product_scope.ScopeTests()
        with patch.object(test_product_entry, 'PNG', stream.getvalue()), redirect_stdout(io.StringIO()):
            scope.setUp()
        self.addCleanup(scope.doCleanups)
        self.scope, self.root = scope, scope.run
        source = load_json(self.root / 'task.json')['product_identity']['evidence_id']
        data = scope.data['scope']
        data['facts'][0].update(status='confirmed', reason='User supplied locking mechanism.')
        data['facts'][0].pop('question', None)
        for item in data['objects']:
            if item['object_id'] == 'pattern':
                item['right_types'] = ['copyright', 'patent']
        data['objects'].append({'object_id': 'body', 'kind': 'product', 'relation': 'target', 'intent': 'default',
            'description': 'body', 'location': 'supplied product image', 'reason': 'Source review supports this relationship.',
            'right_types': ['patent'], 'source_refs': [source]})
        data['directions'].append({'direction_id': 'body-structure', 'scenario_id': 'product_entry', 'right_type': 'patent',
            'fact_ids': ['shape'], 'object_ids': ['body'], 'reason': 'Body structure.'})
        evidence = load_json(self.root / 'evidence.json')
        evidence['collections'].setdefault('patents', []).extend(
            {'evidence_id': 'EV-P%d' % i, 'provider': 'synthetic', 'collected_at': '2026-10-01T00:00:00Z',
             'payload': {'n': i}} for i in range(3))
        evidence['source_runs'].append({'run_id': 'R-P0', 'query_id': 'Q-P0', 'provider': 'synthetic'})
        atomic_write_json(self.root / 'evidence.json', evidence)
        self.candidates = {'patents': [
            {'candidate_id': 'P0', 'right_type': 'patent', 'jurisdiction': 'US',
             'sources': [{'evidence_id': 'EV-P0', 'source_run_id': 'R-P0'}]},
            {'candidate_id': 'P1', 'right_type': 'patent', 'jurisdiction': 'US', 'sources': [{'evidence_id': 'EV-P1'}]}],
            'trademarks': [], 'enforcement': [],
            'copyright_assets': [{'candidate_id': 'C2', 'right_type': 'copyright', 'jurisdiction': 'US',
                                  'sources': [{'evidence_id': 'EV-P2'}]}]}
        atomic_write_json(self.root / 'normalized-candidates.json', self.candidates)
        with redirect_stdout(io.StringIO()):
            self.task = scope.save()
        self.task.update(host_triage_revision=host_triage.REVISION, host_triage=dict(host_triage.DEFAULTS))
        atomic_write_json(self.root / 'task.json', self.task)
        self.plan = {'queries': {'synthetic': [{'query_id': 'Q-P0', 'product_dependencies': [
            {'direction_id': 'body-structure', 'object_ids': ['body']}]}]}}

    def test_query_dependency_narrows_the_link_and_other_candidates_use_all_included_objects(self):
        import candidate_scope_link as link
        evidence = load_json(self.root / 'evidence.json')
        links, left = link.plan_links(self.task, self.candidates, evidence, self.plan)
        by_id = {row['candidate_id']: row for row in links}
        self.assertEqual(by_id['P0']['object_ids'], ['body'])              # its own query was planned for body
        self.assertEqual(by_id['C2']['object_ids'], ['pattern'])           # only included object for copyright
        self.assertEqual(by_id['P1']['object_ids'], ['pattern', 'body'])   # no query binding: all included compatible
        self.assertEqual(left, [])
        self.assertTrue(all('候选相关性由随后的分流决定' in row['reason'] for row in links))
        self.assertTrue(all(set(row['source_refs']) <= {'EV-P0', 'EV-P1', 'EV-P2'} for row in links))

    def test_recording_goes_through_the_ordinary_scope_recorder_and_keeps_history(self):
        import mechanical_ledger as ml
        import product_scope as ps
        atomic_write_json(self.root / 'search-plan.json', self.plan)
        before = load_json(self.root / 'task.json')
        result = ml.auto_link_candidates(self.root)
        self.assertEqual(result['linked'], 3)
        after = load_json(self.root / 'task.json')
        self.assertEqual({l['candidate_id'] for l in after['product_scope']['candidate_links']}, {'P0', 'P1', 'C2'})
        self.assertNotEqual(after['product_scope']['scope_sha256'], before['product_scope']['scope_sha256'])
        self.assertEqual(after['product_change_version'], before.get('product_change_version'))   # not a product change
        self.assertEqual(len(after['product_scope_history']), len(before['product_scope_history']) + 1)
        ps.verify(after, load_json(self.root / 'evidence.json'), self.root)
        again = ml.auto_link_candidates(self.root)
        self.assertEqual(again['linked'], 0)
        self.assertEqual(again['left_for_agent'], [])


class MechanicalProgressTests(unittest.TestCase):
    """09A registration of planned queries; owners and acceptance text come from the right type."""

    def setUp(self):
        import tempfile
        import host_triage
        import review_progress_stage_a as rp
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = {'task_id': 'T09A', 'review_progress_revision': rp.REVISION, 'product_change_version': '1',
                     'target_jurisdictions': ['US', 'GB'], 'assessment_scenarios': [{'scenario_id': 'S1'}],
                     'host_triage_revision': host_triage.REVISION, 'host_triage': dict(host_triage.DEFAULTS)}
        self.evidence = {'task_id': 'T09A', 'source_runs': [], 'review_progress_events': [], 'collections': {}}
        self.rows = [{'query_id': 'Q-PAT', 'jurisdiction': 'US', 'right_type': 'patent', 'scenario_id': 'S1'},
                     {'query_id': 'Q-DES', 'jurisdiction': 'GB', 'right_type': 'design', 'scenario_id': 'S1'}]
        self.plan = {'queries': {'registry': self.rows}}
        self.save()

    def save(self):
        atomic_write_json(self.root / 'task.json', self.task)
        atomic_write_json(self.root / 'evidence.json', self.evidence)
        atomic_write_json(self.root / 'search-plan.json', self.plan)

    def run_step(self, entries):
        from unittest.mock import patch
        import mechanical_ledger as ml
        view = {'entries': [{'reason': 'REVIEW_PROGRESS_QUERY_NOT_PLANNED', 'kind': 'plan_repair', 'state': 'ready',
                             'scenario_id': 'S1', 'query_id': q, 'work_id': 'W-' + q} for q in entries]}
        with patch('workflow_v24.work_view_from_dir', return_value=view):
            result = ml.auto_review_progress(self.root)
        self.evidence = load_json(self.root / 'evidence.json')
        return result

    def test_initialize_registers_every_planned_query_with_owner_modules_and_standard_text(self):
        result = self.run_step(['Q-PAT', 'Q-DES'])
        self.assertEqual((result['status'], result['registered']), ('initialized', 2))
        event = self.evidence['review_progress_events'][0]
        self.assertEqual((event['kind'], event['actor']), ('initialize', 'program:review-progress-v1'))
        items = {i['query_id']: i for i in event['items']}
        self.assertEqual(items['Q-PAT']['module_ids'], ['pending_application', 'utility_patent'])
        self.assertEqual(items['Q-DES']['module_ids'], ['appearance_patent', 'pending_application'])
        self.assertIn('原始回执可核对', items['Q-PAT']['acceptance_condition'])
        self.assertEqual(items['Q-PAT']['scope'], {'scenario_id': 'S1', 'jurisdiction': 'US', 'right_type': 'patent',
                                                   'product_version': '1'})

    def test_later_rows_need_a_real_upstream_event_and_are_otherwise_left_for_the_agent(self):
        self.run_step(['Q-PAT'])
        self.rows.append({'query_id': 'Q-NEXT', 'jurisdiction': 'US', 'right_type': 'patent', 'scenario_id': 'S1',
                          'discovery_scope': {'pagination_basis': {'source_run_id': 'RUN-1'}}})
        self.rows.append({'query_id': 'Q-ORPHAN', 'jurisdiction': 'GB', 'right_type': 'patent', 'scenario_id': 'S1'})
        self.evidence['source_runs'].append({'run_id': 'RUN-1', 'provider': 'registry', 'query_id': 'Q-PAT',
                                             'submission_state': 'submitted', 'status': 'success'})
        self.save()
        result = self.run_step(['Q-NEXT', 'Q-ORPHAN'])
        self.assertEqual((result['status'], result['registered']), ('added', 1))
        self.assertEqual([r['reason'] for r in result['left_for_agent']], ['UPSTREAM_EVENT_REQUIRED'])
        event = self.evidence['review_progress_events'][-1]
        self.assertEqual((event['kind'], event['upstream_ref']), ('add', 'RUN-1'))

    def test_task_without_host_marker_or_plan_is_not_touched(self):
        import mechanical_ledger as ml
        self.task.pop('host_triage_revision')
        self.task.pop('host_triage')
        self.save()
        self.assertEqual(ml.auto_review_progress(self.root)['status'], 'not_applicable')
        self.assertEqual(self.evidence['review_progress_events'], [])


class MechanicalHandoffTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        import host_triage
        import decision_workflow as workflow
        from candidate_handoff import REVISION
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        from pathlib import Path
        self.path = Path(temporary.name)
        self.task = {'task_id': 'TASK-HANDOFF', 'state': 'collecting', 'candidate_handoff_revision': REVISION,
                     'candidate_identity_revision': 'candidate-identity-v1',
                     'workflow_correction_revision': 'workflow-correction-v1',
                     'decision_workflow_revision': workflow.REVISION,
                     'triage_scope_revision': workflow.TRIAGE_SCOPE_REVISION,
                     'host_triage_revision': host_triage.REVISION, 'host_triage': dict(host_triage.DEFAULTS),
                     'assessment_scenarios': [{'scenario_id': 'product_entry', 'type': 'product_entry'},
                                              {'scenario_id': 'brand_reuse', 'type': 'brand_reuse'}],
                     'execution_scenario_ids': ['product_entry'], 'target_jurisdictions': ['US', 'GB']}
        self.evidence = {'collections': {'patents': [{'evidence_id': 'EV-IMPORT', 'collected_at': '2026-09-24T00:00:00Z'}],
                                         'trademarks': [{'evidence_id': 'EV-TM', 'collected_at': '2026-09-24T00:00:00Z'}]},
                         'source_runs': []}
        self.candidates = {'patents': [
            {'candidate_id': 'C-US', 'right_type': 'patent', 'jurisdiction': 'US', 'sources': [{'evidence_id': 'EV-IMPORT', 'source_anchor': 'S1'}]},
            {'candidate_id': 'C-WO', 'right_type': 'patent', 'jurisdiction': 'WO', 'sources': [{'evidence_id': 'EV-IMPORT', 'source_anchor': 'S2'}]}],
            'trademarks': [{'candidate_id': 'T-GB', 'right_type': 'trademark_word', 'jurisdiction': 'GB', 'mark_text': 'X',
                            'sources': [{'evidence_id': 'EV-TM', 'source_anchor': 'S3'}]}]}
        for name, value in (('task', self.task), ('evidence', self.evidence), ('normalized-candidates', self.candidates)):
            atomic_write_json(self.path / (name + '.json'), value)

    def test_origin_scope_is_applicable_foreign_is_unknown_and_inactive_scenario_not_applicable(self):
        import mechanical_ledger as ml
        from candidate_handoff import load_ledger, project
        result = ml.auto_candidate_handoff(self.path)
        self.assertEqual(result['handed_off'], 3)
        batch = load_ledger(self.path, self.task)['batches'][0]
        self.assertEqual(batch['reviewer'], ml.HANDOFF_REVIEWER)
        found = {(r['candidate_id'], r['scenario_id'], r['jurisdiction']): r['applicability'] for r in batch['scope_reviews']}
        self.assertEqual(found[('C-US', 'product_entry', 'US')], 'applicable')
        self.assertEqual(found[('C-WO', 'product_entry', 'UNLOCATED')], 'unknown')
        self.assertEqual(found[('T-GB', 'product_entry', 'GB')], 'applicable')
        self.assertEqual(found[('T-GB', 'brand_reuse', 'GB')], 'not_applicable')
        view = project(self.task, self.evidence, self.candidates, self.path)
        self.assertTrue(view['candidate_handoff_complete'])
        self.assertEqual(ml.auto_candidate_handoff(self.path)['handed_off'], 0)

    def test_only_new_tasks_with_the_marker_are_touched(self):
        import mechanical_ledger as ml
        self.task.pop('host_triage_revision')
        self.task.pop('host_triage')
        atomic_write_json(self.path / 'task.json', self.task)
        self.assertEqual(ml.auto_candidate_handoff(self.path)['status'], 'not_applicable')
        self.assertFalse((self.path / 'candidate-handoffs.json').exists())


if __name__ == '__main__':
    unittest.main()

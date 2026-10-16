"""Discovery review host: compact judgments are written through the unchanged 03B recorder."""
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
import json
import threading
import unittest

from common import atomic_write_json, load_json


class DiscoveryReviewHostTests(unittest.TestCase):
    def setUp(self):
        import host_triage
        import test_discovery_semantics as fixtures
        import discovery_semantics as ds
        self.h = fixtures.DiscoverySemanticsTests('test_two_checks_gate_dispatch_and_complete_direction')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.root = self.h.f.run
        task = load_json(self.root / 'task.json')
        task.update(host_triage_revision=host_triage.REVISION, host_triage=dict(host_triage.DEFAULTS))
        atomic_write_json(self.root / 'task.json', task)

        def view(*_a, **_k):
            current = load_json(self.root / 'task.json')
            plan = load_json(self.root / 'search-plan.json')
            entries = ds.work_entries(current, plan, load_json(self.root / 'evidence.json'))
            return {'entries': [{**e, 'work_id': 'WORK-%d' % i} for i, e in enumerate(entries)]}
        patcher = patch('workflow_v24.work_view_from_dir', side_effect=view)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.binary = self.root / 'native-dummy'
        self.binary.write_text('never executed')
        self.calls, self.lock, self.mode = [], threading.Lock(), {}

    # ---- fake native session ----------------------------------------------------------------
    def raw(self, packet):
        rows = []
        for unit in packet['units']:
            if packet['stage'] == 'direction':
                row = {'unit_id': unit['unit_id'], 'reason': 'Checked the scoped facts and the direction inventory.',
                       'clues': {c['clue_id']: {'disposition': 'included', 'reason': 'The retained product fact matters here.'}
                                 for c in unit['clues']},
                       'unmapped_clues': {c['clue_id']: {'disposition': 'irrelevant', 'reason': 'Not related to this right.'}
                                          for c in unit['unmapped_clues']},
                       'directions': {d['direction_id']: {'question': 'Which protected subject matter resembles this?',
                                                         'method': 'Shape and use search', 'evidence_needed': 'Reviewed result set',
                                                         'supplement_trigger': 'Variants or truncated results'}
                                      for d in unit['directions']}}
            elif packet['stage'] == 'before':
                row = {'unit_id': unit['unit_id'], 'reason': 'Checked the actual planned expression.',
                       'semantic_fit': 'full', 'expression_reason': 'The expression names the visible structure.',
                       'concepts_in_query': ['folding stand'], 'uncovered_clues': [],
                       'independent_structure': False, 'whole_product_constraint': False}
                if unit['needs_classification_basis']:
                    row['classification_basis'] = {'source': 'Locarno', 'meaning': 'Stands', 'applicability': 'Applies'}
                if unit['needs_language_basis']:
                    row['language_basis'] = {'original': 'a', 'submitted': 'b', 'source': 'c', 'relationship': 'd'}
            else:
                row = {'unit_id': unit['unit_id'], 'reason': 'Read the retained response.', 'problem_covered': True,
                       'result_reason': 'The query expressed the direction and the response was not truncated.',
                       'uncovered_clues': [], 'excluded_by_narrowing': [], 'next_action': 'none'}
            row.update(self.mode.get('patch', {}).get(unit['unit_id'][:3], {}))
            rows.append(row)
        return {'units': rows}

    def native(self, command, prompt, workspace, trace_path, stderr_path, timeout):
        packet = load_json(trace_path.parent / 'packet.json')
        with self.lock:
            number = len(self.calls) + 1
            self.calls.append(packet['stage'])
        stderr_path.write_text('synthetic native output only')
        raw = self.raw(packet)
        events = [{'type': 'thread.started', 'thread_id': 'disc-%d' % number}, {'type': 'turn.started'},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(raw)}},
                  {'type': 'turn.completed'}]
        text = '\n'.join(map(json.dumps, events))
        trace_path.write_text(text)
        return SimpleNamespace(returncode=0, pid=6000 + number), text, ''

    def run_host(self, **kwargs):
        import discovery_review_host as host
        with patch('report_review_host.run_native_logged', side_effect=self.native), \
             patch('review_isolation.select_backend', return_value='macos-sandbox'), \
             patch('native_review_jobs._probe', return_value=[]), \
             patch('macos_review_host.require_chatgpt_auth'), redirect_stdout(StringIO()):
            return host.run(self.root, binary=self.binary, isolation='macos-sandbox', deadline=None, **kwargs)

    def reviews(self, stage):
        return [r for r in load_json(self.root / 'task.json').get('discovery_semantic_reviews', []) if r['stage'] == stage]

    # ---- tests ----------------------------------------------------------------------------------
    def test_direction_and_before_reviews_are_recorded_through_the_03b_recorder(self):
        result = self.run_host(stages=('direction', 'before'))
        self.assertEqual(result['unresolved'], [], result)
        directions = self.reviews('direction')
        self.assertTrue(directions)
        self.assertTrue(all(r['reviewer'].startswith('native-discovery-') for r in directions))
        # Planned providers, not the model, supply the proposed sources.
        row = next(r for r in directions if r['right_type'] == 'design')
        planned = {p for p, rows in self.h.plan['queries'].items() for q in rows
                   if q.get('action_purpose') == 'discovery' and q.get('right_type') == 'design'}
        self.assertTrue(set(row['directions'][0]['proposed_sources']) <= planned)
        before = self.reviews('before')
        self.assertTrue(before)
        self.assertTrue(any(r['query_id'] == self.h.row['query_id'] for r in before))
        self.assertEqual(self.calls.count('direction') >= 1 and self.calls.count('before') >= 1, True)

    def test_after_review_uses_the_run_evidence_and_the_unchanged_conditions(self):
        self.run_host(stages=('direction', 'before'))
        run = self.h.source(status='success')
        result = self.run_host(stages=('after',))
        self.assertEqual(result['unresolved'], [], result)
        after = [r for r in self.reviews('after') if r['source_run_id'] == run['run_id']]
        self.assertEqual(len(after), 1)
        self.assertTrue(after[0]['problem_covered'])
        self.assertTrue(after[0]['original_problem_checked'])
        self.assertIn('EV-SEMANTIC', after[0]['evidence_refs'])

    def test_after_unit_carries_the_route_limits_and_the_prompt_explains_each_next_action(self):
        import discovery_review_host as host
        self.run_host(stages=('direction', 'before'))
        self.h.source(status='success')
        seen = []
        original = host.prompt
        with patch.object(host, 'prompt', side_effect=lambda packet: seen.append(packet) or original(packet)):
            self.run_host(stages=('after',))
        packet = next(p for p in seen if p['stage'] == 'after')
        unit = packet['units'][0]
        self.assertEqual(set(unit['route_scope']), {'mode', 'max_pages', 'max_candidates', 'review_all_returned'})
        self.assertIn('refinement_round', unit)
        self.assertIn('max_refinement_rounds', unit)
        text = original(packet)
        for word in ('refine=', 'awaiting_capability=', '不要选 refine'):
            self.assertIn(word, text)

    def test_invalid_judgment_stays_open_and_valid_units_are_still_recorded(self):
        # semantic_fit=partial without uncovered clues is internally inconsistent.
        self.mode['patch'] = {'BEF': {'semantic_fit': 'partial', 'uncovered_clues': []}}
        self.run_host(stages=('direction',))
        result = self.run_host(stages=('before',))
        self.assertTrue(result['unresolved'])
        self.assertTrue(all(u['reason'] == 'SEMANTIC_FIT_AND_UNCOVERED_CLUES_INCONSISTENT' for u in result['unresolved']))
        self.assertEqual(self.reviews('before'), [])
        self.assertTrue(self.reviews('direction'))

    def test_direction_inventory_must_be_covered(self):
        self.mode['patch'] = {'DIR': {'clues': {}}}
        result = self.run_host(stages=('direction',))
        self.assertTrue(result['unresolved'])
        self.assertEqual(self.reviews('direction'), [])

    def test_task_without_host_marker_is_refused(self):
        task = load_json(self.root / 'task.json')
        task.pop('host_triage_revision')
        task.pop('host_triage')
        atomic_write_json(self.root / 'task.json', task)
        import discovery_review_host as host
        with self.assertRaisesRegex(ValueError, 'NEW_TASK_REQUIRED'):
            host.run(self.root, binary=self.binary)


if __name__ == '__main__':
    unittest.main()

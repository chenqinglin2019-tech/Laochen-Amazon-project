"""Text triage host: real scoped task directory, compact judgments, ordinary recorder."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
import json
import threading
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json
from offline_test_support import isolated_test_environment

SNIPPETS = ['Folding stand with a hinged support arm and a locking latch for tablets.',
            'Method of dyeing woven cotton fabric with reactive dyes in a continuous bath.',
            '']


class TextHostFixture(unittest.TestCase):
    """Scoped real-task directory with a host-triage task; subclasses add the cases."""

    def setUp(self):
        import test_product_entry
        import test_product_scope
        import host_triage
        from PIL import Image
        self.environment = isolated_test_environment()
        self.environment.__enter__()
        self.addCleanup(self.environment.__exit__, None, None, None)
        stream = BytesIO()
        Image.new('RGB', (20, 20), 'red').save(stream, format='PNG')
        scope = test_product_scope.ScopeTests()
        with patch.object(test_product_entry, 'PNG', stream.getvalue()), redirect_stdout(StringIO()):
            scope.setUp()
        self.addCleanup(scope.doCleanups)
        self.root = scope.run
        source = load_json(self.root / 'task.json')['product_identity']['evidence_id']
        data = scope.data['scope']
        data['facts'][0].update(status='confirmed', reason='User supplied locking mechanism.')
        data['facts'][0].pop('question', None)
        for item in data['objects']:
            if item['object_id'] == 'pattern':
                item['right_types'] = ['copyright', 'patent']
        data['directions'][0].update(object_ids=['pattern'])
        evidence = load_json(self.root / 'evidence.json')
        candidates = []
        for number, snippet in enumerate(SNIPPETS):
            eid = 'EV-P%d' % number
            evidence.setdefault('collections', {}).setdefault('patents', []).append(
                {'evidence_id': eid, 'provider': 'synthetic', 'collected_at': '2026-10-01T00:00:00Z',
                 'payload': {'publication_number': 'US10%d' % number}})
            row = {'candidate_id': 'P%d' % number, 'jurisdiction': 'US', 'right_type': 'patent',
                   'publication_number': 'US100000%dB2' % number, 'title': 'Synthetic patent %d' % number,
                   'figures': ['f%d' % i for i in range(30)],
                   'sources': [{'evidence_id': eid, 'provider': 'synthetic'}], 'evidence_refs': [eid]}
            if snippet:
                row['snippet'] = snippet
            candidates.append(row)
        extra_evidence, extra_candidates = self.extra_enforcement()
        evidence.setdefault('collections', {}).setdefault('enforcement', []).extend(extra_evidence)
        atomic_write_json(self.root / 'evidence.json', evidence)
        atomic_write_json(self.root / 'normalized-candidates.json',
                          {'patents': candidates, 'trademarks': [], 'copyright_assets': [],
                           'enforcement': extra_candidates})
        data['candidate_links'] = [{'candidate_id': row['candidate_id'], 'object_ids': ['pattern'],
            'reason': 'Returned for the pattern object', 'source_refs': [source]}
            for row in candidates + extra_candidates]
        with redirect_stdout(StringIO()):
            task = scope.save()
        task.update(host_triage_revision=host_triage.REVISION, host_triage={**host_triage.DEFAULTS, 'text_batch_units': 3})
        atomic_write_json(self.root / 'task.json', task)
        from workflow_v24 import generate_plan
        with redirect_stdout(StringIO()):
            generate_plan(self.root)
        self.binary = self.root / 'native-dummy'
        self.binary.write_text('never executed')
        self.calls, self.lock, self.mode = [], threading.Lock(), {}

    # ----- helpers -------------------------------------------------------------------------------
    def extra_enforcement(self):
        """(evidence rows, candidate rows) of additional enforcement-collection leads; none by default."""
        return [], []

    def entries(self):
        import text_triage_host
        return text_triage_host.pending_entries(self.root)

    def raw(self, packet, **special):
        rows = []
        for unit in packet['units']:
            cid = unit['template']['candidate_id']
            row = {'unit_id': unit['unit_id'], 'decision': 'selected',
                   'candidate_content': 'Retained card describes ' + cid + ' with a latch',
                   'product_content': 'The included pattern object of the product',
                   'relationship': 'The latch described on the card may correspond to the product locking part',
                   'investigation_question': 'Do the claims cover the product locking mechanism?'}
            if cid == 'P1':
                row.update(decision='not_selected',
                           difference='The card concerns a textile dyeing process, the product has no dyeing step')
                row.pop('investigation_question')
            row.update(special.get(cid, {}))
            rows.append(row)
        return {'decisions': rows}

    def native(self, command, prompt, workspace, trace_path, stderr_path, timeout):
        packet = load_json(trace_path.parent / 'packet.json')
        with self.lock:
            number = len(self.calls) + 1
            self.calls.append([u['template']['candidate_id'] for u in packet['units']])
            broken = self.mode.get('break_first') and number == 1
        stderr_path.write_text('synthetic native output only')
        raw = self.raw(packet)
        if broken:
            raw['decisions'] = raw['decisions'][:-1]
        events = [{'type': 'thread.started', 'thread_id': 'text-%d' % number}, {'type': 'turn.started'},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(raw)}},
                  {'type': 'turn.completed'}]
        text = '\n'.join(map(json.dumps, events))
        trace_path.write_text(text)
        return SimpleNamespace(returncode=0, pid=5000 + number), text, ''

    def run_host(self, **kwargs):
        import text_triage_host
        with patch('report_review_host.run_native_logged', side_effect=self.native), \
             patch('review_isolation.select_backend', return_value='macos-sandbox'), \
             patch('native_review_jobs._probe', return_value=[]), \
             patch('macos_review_host.require_chatgpt_auth'), redirect_stdout(StringIO()):
            return text_triage_host.run(self.root, binary=self.binary, isolation='macos-sandbox', **kwargs)

    def annotations(self):
        return load_json(self.root / 'materiality-annotations.json')['annotations']


class TextHostTests(TextHostFixture):
    # ----- tests ---------------------------------------------------------------------------------
    def test_packet_is_compact_and_title_only_card_cannot_exclude(self):
        import text_triage_host
        packet, images = text_triage_host.prepare_packet(self.root, self.entries())
        self.assertEqual(images, {})
        units = {u['template']['candidate_id']: u for u in packet['units']}
        self.assertEqual(set(units), {'P0', 'P1', 'P2'})
        self.assertTrue(units['P0']['exclusion_allowed'])
        self.assertEqual(units['P0']['reading_level'], 'abstract')
        self.assertFalse(units['P2']['exclusion_allowed'])
        self.assertEqual(units['P2']['reading_level'], 'result_record')
        self.assertNotIn('figures', units['P0']['card'])
        self.assertEqual(units['P0']['guide']['included_product_objects'], {'pattern': ['locking']})
        self.assertNotIn('candidate_links', json.dumps(packet['objects']))

    def test_compact_output_expands_into_valid_ordinary_records(self):
        import text_triage_host
        entries = self.entries()
        packet, _ = text_triage_host.prepare_packet(self.root, entries)
        directory = self.root / 'commit'
        directory.mkdir()
        outcome = text_triage_host.commit(self.root, entries, packet, self.raw(packet), 'synthetic', directory)
        self.assertEqual(outcome, {'recorded': 3, 'rejected': []})
        rows = {row['candidate_id']: row for row in self.annotations()}
        self.assertEqual({k: v['decision'] for k, v in rows.items()},
                         {'P0': 'selected', 'P1': 'not_selected', 'P2': 'selected'})
        first = rows['P0']
        self.assertEqual(first['reviewer'], 'native-text-synthetic')
        self.assertEqual(first['reading_level'], 'abstract')
        self.assertIn('latch', first['reason'])          # report-facing sentence is the model's own
        self.assertEqual(first['candidate_relation']['product_object_ids'], ['pattern'])
        self.assertEqual(first['candidate_relation']['direction_ids'], ['locking'])
        self.assertIn('差异', rows['P1']['reason'])
        self.assertTrue(rows['P1']['comparison']['applicability_limit'])
        self.assertEqual(rows['P2']['reading_level'], 'result_record')
        self.assertEqual(text_triage_host.pending_entries(self.root), [])

    def test_needs_info_uses_the_existing_followup_contract(self):
        import text_triage_host
        entries = self.entries()
        packet, _ = text_triage_host.prepare_packet(self.root, entries)
        action = {'kind': 'agent_read', 'purpose': 'Read the retained representative figure of P2',
                  'max_attempts': 1, 'required_facts': ['representative_figures'],
                  'reading_scope': {'level': 'representative_figures', 'page_numbers': [1]},
                  'evidence_refs': ['EV-P2'],
                  'followup_basis': {'missing_fact': 'The card has only a title', 'decision_effect': 'Cannot relate it to the latch',
                                     'evidence_needed': 'Representative figure', 'existing_material_review': 'Title and number reviewed',
                                     'completion_condition': 'Figure read and compared', 'new_value': 'Shows the closure shape',
                                     'existing_evidence_refs': ['EV-P2']}}
        raw = self.raw(packet, P2={'decision': 'needs_info', 'missing_information': ['Representative figure showing the closure'],
                                   'missing_fact_effect': 'Title alone does not show the closure',
                                   'completion_condition': 'Read the retained figure and compare',
                                   'existing_material_review': 'Title and publication number only',
                                   'next_actions': [action]})
        for row in raw['decisions']:
            if row['decision'] != 'selected':
                row.pop('investigation_question', None)
        directory = self.root / 'commit'
        directory.mkdir()
        outcome = text_triage_host.commit(self.root, entries, packet, raw, 'synthetic', directory)
        self.assertEqual(outcome['recorded'], 3, outcome)
        row = next(r for r in self.annotations() if r['candidate_id'] == 'P2')
        self.assertEqual(row['decision'], 'needs_info')
        self.assertTrue(row['next_actions'][0]['action_id'].startswith('TEXT-ACTION-'))
        self.assertEqual(row['next_actions'][0]['followup_basis']['obligation_ids'],
                         [next(u['unit_id'] for u in packet['units'] if u['template']['candidate_id'] == 'P2')])

    def test_selected_decisions_are_handed_off_mechanically_after_triage(self):
        import mechanical_ledger as ml
        import text_triage_host
        task = load_json(self.root / 'task.json')
        task.update(triage_stage_revision='candidate-triage-stage-v1', triage_followup_revision='candidate-followup-v1')
        atomic_write_json(self.root / 'task.json', task)
        entries = self.entries()
        packet, _ = text_triage_host.prepare_packet(self.root, entries)
        directory = self.root / 'commit'
        directory.mkdir()
        text_triage_host.commit(self.root, entries, packet, self.raw(packet), 'synthetic', directory)
        result = ml.auto_selected_handoff(self.root)
        self.assertEqual((result['handed_off'], result['left_for_agent']), (2, []))
        events = load_json(self.root / 'task.json')['candidate_triage_stage_events']
        handoffs = [e for e in events if e['kind'] == 'selected_handoff']
        self.assertEqual({e['candidate_id'] for e in handoffs}, {'P0', 'P2'})
        self.assertTrue(all(e['reviewer'] == ml.SELECTED_HANDOFF_REVIEWER for e in handoffs))
        self.assertTrue(all(e['reading_scope']['level'] in {'abstract', 'result_record'} for e in handoffs))
        self.assertEqual(ml.auto_selected_handoff(self.root)['handed_off'], 0)

    def test_exclusion_without_readable_card_content_is_rejected_whole(self):
        import text_triage_host
        packet, _ = text_triage_host.prepare_packet(self.root, self.entries())
        raw = self.raw(packet, P2={'decision': 'not_selected', 'difference': 'Looks unrelated from the title'})
        with self.assertRaisesRegex(ValueError, 'TEXT_INSUFFICIENT_CARD_CANNOT_EXCLUDE'):
            text_triage_host.decisions_from_output(raw, packet, 'synthetic')

    def test_missing_unit_foreign_scope_and_unknown_object_are_rejected(self):
        import text_triage_host
        packet, _ = text_triage_host.prepare_packet(self.root, self.entries())
        short = self.raw(packet)
        short['decisions'].pop()
        with self.assertRaisesRegex(ValueError, 'COVERAGE'):
            text_triage_host.decisions_from_output(short, packet, 's')
        foreign = self.raw(packet, P0={'candidate_id': 'P1'})
        with self.assertRaisesRegex(ValueError, 'SCOPE_MISMATCH'):
            text_triage_host.decisions_from_output(foreign, packet, 's')
        wrong = self.raw(packet, P0={'object_ids': ['not-an-object']})
        with self.assertRaisesRegex(ValueError, 'OBJECT_NOT_INCLUDED'):
            text_triage_host.decisions_from_output(wrong, packet, 's')
        vague = self.raw(packet, P0={'relationship': '  '})
        with self.assertRaisesRegex(ValueError, 'CONCRETE_COMPARISON'):
            text_triage_host.decisions_from_output(vague, packet, 's')

    def test_changed_candidate_between_preparation_and_commit_is_refused(self):
        import text_triage_host
        entries = self.entries()
        packet, _ = text_triage_host.prepare_packet(self.root, entries)
        candidates = load_json(self.root / 'normalized-candidates.json')
        candidates['patents'][0]['snippet'] = 'Replaced abstract text that changes the candidate content entirely.'
        atomic_write_json(self.root / 'normalized-candidates.json', candidates)
        directory = self.root / 'commit'
        directory.mkdir()
        with self.assertRaises(ValueError):
            text_triage_host.commit(self.root, entries, packet, self.raw(packet), 'synthetic', directory)
        self.assertEqual(self.annotations(), [])

    def test_one_invalid_unit_does_not_lose_the_valid_ones(self):
        import text_triage_host
        import annotate_materiality
        entries = self.entries()
        packet, _ = text_triage_host.prepare_packet(self.root, entries)
        real = annotate_materiality._append_scenario_decisions
        def picky(task_dir, task, candidates, args):
            rows = json.loads(Path(args.input).read_text(encoding='utf-8'))['decisions']
            if any(row['candidate_id'] == 'P1' for row in rows):
                raise ValueError('INVALID_TRIAGE_DECISION: synthetic recorder rejection')
            return real(task_dir, task, candidates, args)
        directory = self.root / 'commit'
        directory.mkdir()
        with patch('annotate_materiality._append_scenario_decisions', side_effect=picky):
            outcome = text_triage_host.commit(self.root, entries, packet, self.raw(packet), 'synthetic', directory)
        self.assertEqual(outcome['recorded'], 2)
        self.assertEqual([r['candidate_id'] for r in outcome['rejected']], ['P1'])
        self.assertEqual({row['candidate_id'] for row in self.annotations()}, {'P0', 'P2'})

    def test_host_run_records_batches_and_never_invents_exclusions_on_failure(self):
        result = self.run_host(deadline=None)
        self.assertEqual([b['status'] for b in result['batches']], ['recorded'])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.annotations()), 3)

    def test_invalid_session_output_is_split_and_retried(self):
        self.mode['break_first'] = True
        result = self.run_host(deadline=None)
        statuses = [b['status'] for b in result['batches']]
        self.assertTrue(statuses and all(s == 'recorded' for s in statuses), result)
        self.assertGreater(len(self.calls), 1)
        self.assertEqual(len(self.annotations()), 3)

    def test_task_without_host_marker_is_refused(self):
        import text_triage_host
        task = load_json(self.root / 'task.json')
        task.pop('host_triage_revision')
        task.pop('host_triage')
        atomic_write_json(self.root / 'task.json', task)
        with self.assertRaisesRegex(ValueError, 'NEW_TASK_REQUIRED'):
            text_triage_host.run(self.root, binary=self.binary)

    def test_analysis_budget_is_separate_and_charged(self):
        import host_triage
        task = load_json(self.root / 'task.json')
        self.assertEqual(host_triage.remaining_seconds(self.root, task), host_triage.DEFAULTS['analysis_seconds'])
        with host_triage.analysis_budget(self.root, task) as deadline:
            self.assertGreater(deadline, 0)
        journal = load_json(self.root / host_triage.JOURNAL)
        self.assertEqual(journal['invocations'], 1)
        self.assertGreaterEqual(journal['used_seconds'], 0)
        task['host_triage']['analysis_seconds'] = 1
        journal['used_seconds'] = 5
        atomic_write_json(self.root / host_triage.JOURNAL, journal)
        with self.assertRaisesRegex(ValueError, 'ANALYSIS_BUDGET_EXHAUSTED'):
            with host_triage.analysis_budget(self.root, task):
                pass


if __name__ == '__main__':
    unittest.main()

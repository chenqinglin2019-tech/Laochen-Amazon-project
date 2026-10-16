"""Claims-level second pass: quotes must be in the retained claims, only downgrades, calibration never writes."""
from contextlib import redirect_stdout
from io import StringIO
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common import atomic_write_json, load_json
from test_text_triage_host import TextHostFixture

CLAIM_A = ('1. A locking device for a container lid, comprising a rigid hinged support arm, a torsion spring '
           'arranged inside the arm and a latch member that engages a rim of the container.')
CLAIM_A_DEP = '2. The locking device according to claim 1, wherein the latch member is made of steel.'
CLAIM_B = ('7. A method of closing a container, comprising inserting a threaded fastener through a boss of the '
           'lid and tightening the fastener with a tool.')
CLAIMS = {'P0': [CLAIM_A, CLAIM_A_DEP, CLAIM_B], 'P1': [CLAIM_A, CLAIM_A_DEP]}


class ClaimsHostTests(TextHostFixture):
    """P0 and P1 are first selected by the text host (abstract level), then their claims are retained."""

    def setUp(self):
        super().setUp()
        import text_triage_host
        entries = [e for e in self.entries() if e['candidate_id'] in {'P0', 'P1'}]
        packet, _ = text_triage_host.prepare_packet(self.root, entries)
        raw = {'decisions': [{'unit_id': u['unit_id'], 'decision': 'selected',
                              'relationship': 'The card describes a lid latch that may match the product locking part',
                              'investigation_question': 'Do the independent claims cover the product?'}
                             for u in packet['units']]}
        directory = self.root / 'first-pass'
        directory.mkdir()
        text_triage_host.commit(self.root, entries, packet, raw, 'synthetic', directory)
        evidence = load_json(self.root / 'evidence.json')
        for number, claims in CLAIMS.items():
            evidence['collections']['patents'].append({'evidence_id': 'EV-D' + number, 'provider': 'serpapi_google_patents',
                'operation': 'candidate_detail', 'collected_at': '2026-10-02T00:00:00Z',
                'payload': {'candidate_id': number, 'publication_number': 'US100000%sB2' % number[1], 'claims': claims}})
        atomic_write_json(self.root / 'evidence.json', evidence)
        self.mark(True)

    def mark(self, on):
        task = load_json(self.root / 'task.json')
        if on:
            task['claims_triage_revision'] = 'claims-triage-v1'
        else:
            task.pop('claims_triage_revision', None)
        atomic_write_json(self.root / 'task.json', task)

    def packet(self):
        import claims_triage_host as ch
        entries = ch.pending_entries(self.root)
        return entries, ch.prepare_packet(self.root, entries)[0]

    def raw(self, packet, **by_candidate):
        rows = []
        for unit in packet['units']:
            cid = unit['template']['candidate_id']
            row = {'unit_id': unit['unit_id'], 'decision': 'keep_selected'}
            row.update(by_candidate.get(cid, {}))
            rows.append(row)
        return {'decisions': rows}

    EXCLUDE_P0 = {'decision': 'not_selected', 'claim_numbers': [1, 7],
        'quotes': [{'claim': 1, 'text': 'a rigid hinged support arm, a torsion spring arranged inside the arm'},
                   {'claim': 7, 'text': 'inserting a threaded fastener through a boss of the lid'}],
        'relationship': 'The product is a flexible strap with openings, not a hinged arm with a spring or a fastener.',
        'difference': 'Both independent claims need a rigid hinged arm with a spring or a threaded fastener in a boss; '
                      'the product is a one-piece flexible strap.'}

    # -------------------------------------------------------------------------------------------------
    def test_off_by_default_and_only_current_selected_with_retained_claims_are_pending(self):
        import claims_triage_host as ch
        entries, packet = self.packet()
        self.assertEqual({e['candidate_id'] for e in entries}, {'P0', 'P1'})
        units = {u['template']['candidate_id']: u for u in packet['units']}
        self.assertEqual([c['number'] for c in units['P0']['independent_claims']], [1, 7])   # 2 is dependent
        self.assertEqual([c['number'] for c in units['P1']['independent_claims']], [1])
        self.mark(False)
        self.assertEqual(ch.pending_entries(self.root), [])

    def test_a_quote_that_is_not_in_the_retained_claims_voids_the_whole_output(self):
        import claims_triage_host as ch
        _, packet = self.packet()
        forged = {**self.EXCLUDE_P0, 'quotes': [
            {'claim': 1, 'text': 'a rigid hinged support arm, a torsion spring arranged inside the arm'},
            {'claim': 7, 'text': 'a quantum entanglement module configured to sync with the lid'}]}
        with self.assertRaisesRegex(ValueError, 'CLAIMS_QUOTE_NOT_IN_RETAINED_CLAIM'):
            ch.decisions_from_output(self.raw(packet, P0=forged), packet, 's')

    def test_every_independent_claim_must_be_addressed_and_quoted(self):
        import claims_triage_host as ch
        _, packet = self.packet()
        partial = {**self.EXCLUDE_P0, 'claim_numbers': [1]}
        with self.assertRaisesRegex(ValueError, 'CLAIMS_ALL_INDEPENDENT_CLAIMS_MUST_BE_ADDRESSED'):
            ch.decisions_from_output(self.raw(packet, P0=partial), packet, 's')
        missing_quote = {**self.EXCLUDE_P0, 'quotes': self.EXCLUDE_P0['quotes'][:1]}
        with self.assertRaisesRegex(ValueError, 'CLAIMS_QUOTE_PER_INDEPENDENT_CLAIM_REQUIRED'):
            ch.decisions_from_output(self.raw(packet, P0=missing_quote), packet, 's')
        short = {**self.EXCLUDE_P0, 'quotes': [{'claim': 1, 'text': 'a rigid'}, self.EXCLUDE_P0['quotes'][1]]}
        with self.assertRaisesRegex(ValueError, 'CLAIMS_QUOTE_INVALID'):
            ch.decisions_from_output(self.raw(packet, P0=short), packet, 's')
        numeric = {**self.EXCLUDE_P0, 'difference': 'Similarity score 12% against the product strap'}
        with self.assertRaisesRegex(ValueError, 'CLAIMS_NUMERIC_SCORE_IS_NOT_A_TRIAGE_BASIS'):
            ch.decisions_from_output(self.raw(packet, P0=numeric), packet, 's')

    def test_only_downgrades_exist_and_unknown_decisions_are_rejected(self):
        import claims_triage_host as ch
        _, packet = self.packet()
        with self.assertRaisesRegex(ValueError, 'CLAIMS_DECISION_INVALID'):
            ch.decisions_from_output(self.raw(packet, P0={'decision': 'selected'}), packet, 's')
        with self.assertRaisesRegex(ValueError, 'CLAIMS_OUTPUT_UNIT_COVERAGE_INVALID'):
            ch.decisions_from_output({'decisions': self.raw(packet)['decisions'][:1]}, packet, 's')

    def test_commit_records_through_the_reopen_transaction_and_keeps_the_history(self):
        import claims_triage_host as ch
        before = load_json(self.root / 'materiality-annotations.json')['annotations']
        entries, packet = self.packet()
        directory = self.root / 'claims-commit'
        directory.mkdir()
        outcome = ch.commit(self.root, entries, packet, self.raw(packet, P0=self.EXCLUDE_P0), 'synthetic', directory)
        self.assertEqual((outcome['recorded'], outcome['kept_selected'], outcome['rejected']), (1, 1, []))
        after = load_json(self.root / 'materiality-annotations.json')['annotations']
        self.assertEqual(len(after), len(before) + 1)                  # append-only: the old selection is retained
        new = after[-1]
        self.assertEqual((new['candidate_id'], new['decision'], new['reading_level']), ('P0', 'not_selected', 'independent_claims'))
        self.assertTrue(new['reviewer'].startswith('native-claims-'))
        self.assertIn('EV-DP0', new['evidence_refs'])
        self.assertIn('权利要求1', new['comparison']['candidate_content'])
        # the second candidate was kept and is not offered again as a downgrade of the first
        self.assertEqual({e['candidate_id'] for e in ch.pending_entries(self.root)}, {'P1'})
        import candidate_triage_stage as stage
        task = load_json(self.root / 'task.json')
        if stage.enabled(task):
            self.assertEqual([row['kind'] for row in stage.events(task)], ['reopen', 'reopen_review'])
            reopen = stage.events(task)[0]
            self.assertEqual([item['annotation_id'] for item in reopen['affected']],
                             [r['annotation_id'] for r in before if r['candidate_id'] == 'P0'])
            self.assertEqual(reopen['change_evidence_refs'], ['EV-DP0'])
        else:
            self.skipTest('fixture task has no triage stage revision')

    def test_nothing_is_written_when_every_unit_is_kept(self):
        import claims_triage_host as ch
        before = (self.root / 'materiality-annotations.json').read_bytes()
        entries, packet = self.packet()
        directory = self.root / 'claims-kept'
        directory.mkdir()
        outcome = ch.commit(self.root, entries, packet, self.raw(packet), 'synthetic', directory)
        self.assertEqual((outcome['recorded'], outcome['kept_selected']), (0, 2))
        self.assertEqual((self.root / 'materiality-annotations.json').read_bytes(), before)

    def test_an_input_change_between_packet_and_commit_is_refused(self):
        import claims_triage_host as ch
        entries, packet = self.packet()
        evidence = load_json(self.root / 'evidence.json')
        for entry in evidence['collections']['patents']:
            if entry['evidence_id'] == 'EV-DP0':
                entry['payload']['claims'] = [CLAIM_A]
        atomic_write_json(self.root / 'evidence.json', evidence)
        with self.assertRaisesRegex(ValueError, 'CLAIMS_INPUT_CHANGED_BEFORE_COMMIT'):
            ch.commit(self.root, entries, packet, self.raw(packet, P0=self.EXCLUDE_P0), 's', self.root)

    def test_independent_claim_parser(self):
        import claims_triage_host as ch
        rows = ch.parse_claims([CLAIM_A, CLAIM_A_DEP, CLAIM_B, 'cancelled', 5,
            '3. A kit comprising the device of claim 1 and a case.'])
        self.assertEqual([(r['number'], r['independent']) for r in rows], [(1, True), (2, False), (7, True), (3, False)])

    # ----- calibration ------------------------------------------------------------------------------
    def calibrate_with(self, recorded, host_excludes):
        """Record independent-claims decisions by someone else (candidate -> decision) and run the calibration."""
        import claims_triage_host as ch
        ledger = load_json(self.root / 'materiality-annotations.json')
        for row in [r for r in ledger['annotations'] if r['candidate_id'] in recorded]:
            ledger['annotations'].append({**row, 'annotation_id': 'MANUAL-' + row['candidate_id'],
                'decision': recorded[row['candidate_id']], 'reviewer': 'main-agent', 'reading_level': 'independent_claims'})
        atomic_write_json(self.root / 'materiality-annotations.json', ledger)

        def native(command, prompt, workspace, trace_path, stderr_path, timeout):
            packet = load_json(trace_path.parent / 'packet.json')
            stderr_path.write_text('synthetic')
            rows = []
            for unit in packet['units']:
                row = {'unit_id': unit['unit_id'], 'decision': 'keep_selected'}
                if unit['template']['candidate_id'] in host_excludes:
                    row.update(self.EXCLUDE_P0)
                rows.append(row)
            events = [{'type': 'thread.started', 'thread_id': 'claims-2'}, {'type': 'turn.started'},
                      {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({'decisions': rows})}},
                      {'type': 'turn.completed'}]
            text = '\n'.join(map(json.dumps, events))
            trace_path.write_text(text)
            return SimpleNamespace(returncode=0, pid=7100), text, ''

        with patch('report_review_host.run_native_logged', side_effect=native), \
             patch('review_isolation.select_backend', return_value='macos-sandbox'), \
             patch('native_review_jobs._probe', return_value=[]), patch('macos_review_host.require_chatgpt_auth'), \
             redirect_stdout(StringIO()):
            return ch.calibrate(self.root, binary=self.binary, isolation='macos-sandbox')

    def test_calibration_without_a_kept_selected_control_is_inconclusive_not_passed(self):
        report = self.calibrate_with({'P0': 'not_selected', 'P1': 'not_selected'}, host_excludes={'P0'})
        self.assertEqual(report['unsafe_disagreements'], 0)
        self.assertEqual(report['positive_controls'], 0)
        self.assertEqual(report['verdict'], 'inconclusive_no_positive_control')
        self.assertFalse(report['passed'])

    def test_calibration_passes_only_with_a_control_the_host_also_kept(self):
        report = self.calibrate_with({'P0': 'not_selected', 'P1': 'selected'}, host_excludes={'P0'})
        self.assertEqual((report['verdict'], report['positive_controls'], report['agree']), ('passed', 1, 2))
        self.assertTrue(report['passed'])

    def test_comparison_classes(self):
        import claims_triage_host as ch
        verdict = ch.compare({'A': 'not_selected', 'B': 'keep_selected', 'C': 'not_selected', 'D': 'keep_selected'},
                             {'A': 'not_selected', 'B': 'not_selected', 'C': 'selected', 'D': 'selected'})
        self.assertEqual(verdict, {'agree': ['A', 'D'], 'conservative': ['B'], 'unsafe': ['C']})
        self.assertEqual(ch.compare({'X': 'keep_selected'}, {})['agree'], [])

    def test_calibration_runs_sessions_without_writing_the_ledger_and_fails_on_an_unsafe_exclusion(self):
        import claims_triage_host as ch
        # a recorded independent-claims decision made by someone else: P0 stayed selected, P1 was set aside
        task = load_json(self.root / 'task.json')
        ledger = load_json(self.root / 'materiality-annotations.json')
        base = [r for r in ledger['annotations'] if r['candidate_id'] in {'P0', 'P1'}]
        for row in base:
            kept = row['candidate_id'] == 'P0'
            ledger['annotations'].append({**row, 'annotation_id': 'MANUAL-' + row['candidate_id'],
                'decision': 'selected' if kept else 'not_selected', 'reviewer': 'main-agent',
                'reading_level': 'independent_claims'})
        atomic_write_json(self.root / 'materiality-annotations.json', ledger)
        frozen = (self.root / 'materiality-annotations.json').read_bytes()
        calls, lock = [], threading.Lock()

        def native(command, prompt, workspace, trace_path, stderr_path, timeout):
            packet = load_json(trace_path.parent / 'packet.json')
            with lock:
                calls.append(len(calls))
            stderr_path.write_text('synthetic')
            rows = []
            for unit in packet['units']:
                cid = unit['template']['candidate_id']
                row = {'unit_id': unit['unit_id'], 'decision': 'keep_selected'}
                if cid == 'P0':        # unsafe: the recorded review kept it selected
                    row.update(self.EXCLUDE_P0)
                rows.append(row)
            events = [{'type': 'thread.started', 'thread_id': 'claims-1'}, {'type': 'turn.started'},
                      {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({'decisions': rows})}},
                      {'type': 'turn.completed'}]
            text = '\n'.join(map(json.dumps, events))
            trace_path.write_text(text)
            return SimpleNamespace(returncode=0, pid=7000 + len(calls)), text, ''

        with patch('report_review_host.run_native_logged', side_effect=native), \
             patch('review_isolation.select_backend', return_value='macos-sandbox'), \
             patch('native_review_jobs._probe', return_value=[]), patch('macos_review_host.require_chatgpt_auth'), \
             redirect_stdout(StringIO()):
            report = ch.calibrate(self.root, binary=self.binary, isolation='macos-sandbox')
        self.assertEqual(report['compared'], 2)
        self.assertEqual(report['unsafe_candidates'], ['P0'])
        self.assertEqual((report['verdict'], report['positive_controls']), ('failed_unsafe', 1))
        self.assertFalse(report['passed'])
        self.assertEqual(report['agree'], 0)
        self.assertEqual(report['conservative_disagreements'], 1)       # P1: host kept, recorded set aside
        self.assertEqual((self.root / 'materiality-annotations.json').read_bytes(), frozen)
        self.assertTrue((self.root / 'claims-triage-calibration' / 'calibration.json').is_file())


if __name__ == '__main__':
    unittest.main()

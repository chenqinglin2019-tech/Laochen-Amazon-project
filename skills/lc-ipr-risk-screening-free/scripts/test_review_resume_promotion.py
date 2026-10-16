"""A one-ID roll-up slip in one module must neither cost the report nor a second session of that module."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from common import load_json
from test_review_identity_recovery import recovery_fixture, snapshot
import module_review as mr


def omit_rollup_once(fixture, slot):
    """Let one module cite an ID in a nested field and forget it in the row's own roll-up list."""
    native, done = fixture.native, []
    def run(*args):
        process, text, stderr = native(*args)
        if (args[3].parent.parent.name, args[3].parent.name) == slot and not done:
            events = [json.loads(line) for line in text.splitlines()]
            for event in events:
                if event.get('type') == 'item.completed':
                    raw = json.loads(event['item']['text'])
                    row = raw['assessments'][0]
                    row['evidence_refs'] = ['E-IMAGE']
                    row['confidence_basis'] = {'scope': {'satisfied': True, 'reasoning': 'Read the supplied material',
                                                         'evidence_refs': ['E-TEXT']}}
                    event['item']['text'] = json.dumps(raw)
            text = '\n'.join(json.dumps(event) for event in events) + '\n'
            args[3].write_text(text, encoding='utf-8')
            done.append(True)
        return process, text, stderr
    fixture.native = run


def omit_rollup_always(fixture, slot):
    """Every turn of this slot cites an ID in a nested field and forgets it in the row's own roll-up list."""
    native = fixture.native
    def run(*args):
        process, text, stderr = native(*args)
        if (args[3].parent.parent.name, args[3].parent.name) == slot:
            events = [json.loads(line) for line in text.splitlines()]
            for event in events:
                if event.get('type') == 'item.completed':
                    raw = json.loads(event['item']['text'])
                    row = raw['assessments'][0]
                    row['evidence_refs'] = ['E-IMAGE']
                    row['confidence_basis'] = {'scope': {'satisfied': True, 'reasoning': 'Read the supplied material',
                                                         'evidence_refs': ['E-TEXT']}}
                    event['item']['text'] = json.dumps(raw)
            text = '\n'.join(json.dumps(event) for event in events) + '\n'
            args[3].write_text(text, encoding='utf-8')
        return process, text, stderr
    fixture.native = run


def strict_rows():
    """The pre-derivation behaviour: the row's own roll-up list is taken as the model wrote it."""
    return patch('module_review.derive_rows', side_effect=lambda rows: (list(rows), {}))


class RollupResumeTests(unittest.TestCase):
    def test_roll_up_slip_alone_never_fails_a_review_and_is_recorded_on_the_receipt(self):
        with recovery_fixture(kind='seven-country-large') as fixture:
            omit_rollup_once(fixture, ('1', 'technical'))
            reviews = fixture.run()
            self.assertEqual(len(fixture.calls), 8)
            execution = reviews[0]['review_context']['execution']['module_execution']
            derivation = execution['row_derivation']
            self.assertEqual(derivation['revision'], mr.ROW_DERIVATION_REVISION)
            self.assertEqual(list(derivation['added_evidence_refs'].values()), [['E-TEXT']])
            raw = execution['modules'][0]['judgment']['assessments'][0]
            self.assertEqual(raw['evidence_refs'], ['E-IMAGE'])
            self.assertEqual(reviews[0]['assessments'][0]['evidence_refs'], ['E-IMAGE', 'E-TEXT'])
            self.assertNotIn('row_derivation', reviews[1]['review_context']['execution']['module_execution'])
            mr.validate_execution(reviews[0], required=True)

    def test_a_failed_module_leaves_its_peers_audited_and_resume_reuses_the_turn_without_a_new_session(self):
        with recovery_fixture(kind='seven-country-large') as fixture:
            omit_rollup_once(fixture, ('1', 'technical'))
            with strict_rows(), self.assertRaisesRegex(ValueError, 'ROW_EVIDENCE_REFS_MUST_INCLUDE_ARGUMENT_REFS'):
                fixture.run()
            for chain, group in (('1', 'appearance'), ('1', 'expression'), ('2', 'technical'),
                                 ('2', 'appearance'), ('2', 'expression')):
                audit = load_json(fixture.output / chain / group / 'audit.json')
                self.assertNotIn('recovered_from_retained_trace', audit)
            before = len(fixture.calls)
            reviews = fixture.run(resume=True)
            self.assertEqual([call for call in fixture.calls[before:] if call[1] != 'summary'], [])
            self.assertEqual(len(reviews), 2)

    def test_an_archived_turn_that_is_valid_again_is_promoted_not_rerun(self):
        with recovery_fixture(kind='seven-country-large') as fixture:
            omit_rollup_once(fixture, ('1', 'technical'))
            with strict_rows(), self.assertRaises(ValueError):
                fixture.run()
            slot = fixture.output / '1' / 'technical'
            original_trace = (slot / 'events.jsonl').read_bytes()
            # what a first resume would have left behind: the content-invalid turn archived, and a fresh turn
            # that never completed in the slot (a timeout)
            attempt = slot.with_name('technical.attempt-1')
            shutil.copytree(slot, attempt)
            for name in ('agent-judgment.json', 'audit.json', 'events.execution.json'):
                (slot / name).unlink(missing_ok=True)
            (slot / 'events.jsonl').write_text('{"type":"thread.started","thread_id":"x"}\n{"type":"turn.started"}\n',
                                               encoding='utf-8')
            before = len(fixture.calls)
            fixture.run(resume=True)
            self.assertEqual([call for call in fixture.calls[before:] if call[1] != 'summary'], [])
            self.assertEqual((slot / 'events.jsonl').read_bytes(), original_trace)
            self.assertTrue(any(path.name.startswith('technical.attempt-') and path.name != 'technical.attempt-1'
                                for path in slot.parent.iterdir()))
            receipt = load_json(fixture.output / 'freeze-receipt.json')
            self.assertTrue(any(row.get('promoted_from') == 'technical.attempt-1' for row in receipt['resume_attempts']))

    def test_a_different_packet_is_never_promoted(self):
        with recovery_fixture(kind='seven-country-large') as fixture:
            omit_rollup_once(fixture, ('1', 'technical'))
            with strict_rows(), self.assertRaises(ValueError):
                fixture.run()
            slot = fixture.output / '1' / 'technical'
            attempt = slot.with_name('technical.attempt-1')
            shutil.copytree(slot, attempt)
            packet = load_json(attempt / 'packet.json')
            packet['module_scope']['required_scopes'] = packet['module_scope']['required_scopes'][:-1]
            (attempt / 'packet.json').write_text(json.dumps(packet), encoding='utf-8')
            packet_here = json.loads((slot / 'packet.json').read_text(encoding='utf-8'))
            self.assertIsNone(mr.valid_archived_attempt(slot, packet_here, 'prompt', lambda record: None, 'd', 'f'))


class SlotRetryCapTests(unittest.TestCase):
    LIMITS = {'max_slot_retries': 1}

    def test_a_slot_whose_finished_answers_were_refused_twice_is_not_run_a_third_time(self):
        with recovery_fixture(kind='seven-country-large') as fixture:
            omit_rollup_always(fixture, ('1', 'technical'))
            with strict_rows(), patch('execution_budget.policy', return_value=self.LIMITS):
                with self.assertRaisesRegex(ValueError, 'ROW_EVIDENCE_REFS_MUST_INCLUDE_ARGUMENT_REFS'):
                    fixture.run()                                   # first finished answer refused
                first = len(fixture.calls)
                with self.assertRaisesRegex(ValueError, 'ROW_EVIDENCE_REFS_MUST_INCLUDE_ARGUMENT_REFS'):
                    fixture.run(resume=True)                        # the one allowed retry, refused again
                second = len(fixture.calls)
                self.assertGreater(second, first)
                with self.assertRaisesRegex(ValueError, 'FINAL_REVIEW_SLOT_RETRY_LIMIT_REACHED: 1/technical'):
                    fixture.run(resume=True)
                self.assertEqual(len(fixture.calls), second)         # nothing was started

    def test_an_interrupted_turn_is_not_a_content_failure_and_is_retried(self):
        with recovery_fixture(kind='seven-country-large', fail_slot=('1', 'technical')) as fixture:
            with patch('execution_budget.policy', return_value=self.LIMITS):
                with self.assertRaisesRegex(ValueError, 'EXECUTION_FAILED'):
                    fixture.run()
                before = len(fixture.calls)
                reviews = fixture.run(resume=True)
                self.assertEqual(len(reviews), 2)
                self.assertGreater(len(fixture.calls), before)

    def test_tasks_without_the_allowance_are_unaffected(self):
        with recovery_fixture(kind='seven-country-large') as fixture:
            omit_rollup_always(fixture, ('1', 'technical'))
            with strict_rows():
                for _ in range(3):
                    with self.assertRaisesRegex(ValueError, 'ROW_EVIDENCE_REFS_MUST_INCLUDE_ARGUMENT_REFS'):
                        fixture.run(resume=_ > 0)


class PreflightTests(unittest.TestCase):
    def preflight(self, fixture, **kwargs):
        from review_preflight import preflight
        frozen = fixture.output / 'frozen-input.json'
        if not frozen.exists():        # the real host names its retained freeze frozen-input.json
            shutil.copyfile(fixture.output / 'frozen.json', frozen)
        with patch('review_isolation.resolve_codex_binary', return_value=fixture.binary):
            return preflight(fixture.source, fixture.output, isolation='auto', **kwargs)

    def test_dry_run_writes_nothing_and_reports_sizes_and_the_pass_estimate(self):
        with recovery_fixture(kind='seven-country-large') as fixture:
            shutil.copyfile(fixture.output / 'frozen.json', fixture.output / 'frozen-input.json')
            state = {path: path.read_bytes() for path in fixture.source.rglob('*') if path.is_file()}
            before = snapshot(fixture.output)
            report = self.preflight(fixture)
            self.assertEqual({path: path.read_bytes() for path in fixture.source.rglob('*') if path.is_file()}, state)
            self.assertEqual(snapshot(fixture.output), before)
            self.assertEqual(fixture.calls, [])
            self.assertEqual(sorted(report['modules']), ['appearance', 'expression', 'technical'])
            for entry in report['modules'].values():
                self.assertGreater(entry['prompt_chars_chain_1'], 0)
            self.assertEqual(report['estimate']['fresh_module_sessions'], 6)
            self.assertGreater(report['estimate']['needed_seconds'], 0)
            self.assertEqual([row for row in report['problems'] if row['stage'] != 'budget'], [])

    def test_oversized_prompt_is_reported_before_any_session(self):
        with recovery_fixture(kind='seven-country-large') as fixture:
            with patch('review_preflight.PROMPT_LIMIT', 1000):
                report = self.preflight(fixture)
            codes = {row['code'] for row in report['problems']}
            self.assertIn('REPORT_REVIEW_HOST_INPUT_TOO_LARGE_AFTER_LOSSLESS_ENCODING', codes)
            self.assertFalse(report['ready'])

    def test_resumed_slots_are_classified_and_a_complete_run_needs_nothing(self):
        with recovery_fixture(kind='seven-country-large') as fixture:
            fixture.run()
            report = self.preflight(fixture, resume_existing=True)
            self.assertTrue(all(row['state'] == 'retained' for row in report['slots'].values()))
            self.assertEqual(report['estimate']['fresh_module_sessions'], 0)

    def test_cli_flag_prints_the_report_and_exits_by_readiness_without_starting_a_model(self):
        import io
        import sys
        from contextlib import redirect_stdout
        import report_review_host as host
        with recovery_fixture(kind='seven-country-large') as fixture:
            shutil.copyfile(fixture.output / 'frozen.json', fixture.output / 'frozen-input.json')
            argv = ['report_review_host.py', '--task-dir', str(fixture.source), '--output-dir', str(fixture.output),
                    '--preflight', '--isolation', 'tool-free-process']
            out = io.StringIO()
            with patch.object(sys, 'argv', argv), patch('review_isolation.resolve_codex_binary', return_value=fixture.binary), \
                 patch('report_review_host.run_native_logged', side_effect=AssertionError('no session may start')), \
                 redirect_stdout(out), self.assertRaises(SystemExit) as raised:
                host.main()
            report = json.loads(out.getvalue())
            self.assertEqual(report['schema'], 'IPR-REVIEW-PREFLIGHT/1.0')
            self.assertEqual(raised.exception.code, 0 if report['ready'] else 1)
            self.assertEqual(fixture.calls, [])

    def test_a_directory_left_by_a_preparation_failure_is_reused_instead_of_forcing_a_new_name(self):
        import os
        import report_review_host as host
        with recovery_fixture(kind='seven-country-large') as fixture:
            inert = fixture.root / 'left-by-a-failed-preparation'
            inert.mkdir()
            shutil.copyfile(fixture.output / 'frozen.json', inert / 'frozen-input.json')
            os.chmod(fixture.binary, 0o755)
            with patch('report_review_host.run_native_logged', side_effect=fixture.native), \
                 patch('native_review_jobs._probe', return_value=[]), patch('report_review_host._probe', return_value=[]), \
                 patch('macos_review_host.require_chatgpt_auth'), \
                 patch('review_isolation.login_status', return_value=None), \
                 patch('review_isolation.inspect_native_capability', return_value={'status': 'available'}):
                paths = host.run_pair(fixture.source, inert, fixture.binary, max_parallel=2,
                                      isolation='tool-free-process')
            self.assertEqual(len(paths), 2)
            self.assertEqual(len(fixture.calls), 8)
            # a directory a model has already written into is never silently replaced
            with self.assertRaisesRegex(ValueError, 'REPORT_REVIEW_HOST_NEW_OUTPUT_REQUIRED'):
                host.run_pair(fixture.source, inert, fixture.binary, max_parallel=2, isolation='tool-free-process')

    def test_inert_output_directory_is_recognised_only_when_it_is_the_hosts_own_and_untouched(self):
        from report_review_host import inert_output
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent)
            self.assertFalse(inert_output(root))                      # not a host directory at all
            (root / 'frozen-input.json').write_text('{}')
            self.assertTrue(inert_output(root))
            (root / '1').mkdir()
            (root / '1' / 'prompt.txt').write_text('p')
            (root / '1' / 'M1.png').write_bytes(b'x')
            self.assertTrue(inert_output(root))
            (root / '1' / 'events.jsonl').write_text('{}')
            self.assertFalse(inert_output(root))                      # a model produced something
            (root / '1' / 'events.jsonl').unlink()
            (root / 'notes.docx').write_text('user file')
            self.assertFalse(inert_output(root))                      # never touch foreign files


if __name__ == '__main__':
    unittest.main()

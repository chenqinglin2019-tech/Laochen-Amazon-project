"""Native model mistakes retry only their own slots; corrupt host artifacts do not."""
import json
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json
from test_review_identity_recovery import recovery_fixture, snapshot
from test_review_output_recovery import change_native_once


def message_once(fixture, slot, message):
    """Keep a complete native turn; replace only its final message once."""
    native, changed = fixture.native, []
    def run(*args):
        process, text, stderr = native(*args)
        if (args[3].parent.parent.name, args[3].parent.name) == slot and not changed:
            events = [json.loads(line) for line in text.splitlines()]
            for event in events:
                if event.get('type') == 'item.completed':
                    event['item']['text'] = message
            text = '\n'.join(json.dumps(event) for event in events) + '\n'
            args[3].write_text(text, encoding='utf-8')
            changed.append(True)
        return process, text, stderr
    fixture.native = run


def invalid_json_once(fixture, slot):
    native, changed = fixture.native, []
    def run(*args):
        process, text, stderr = native(*args)
        if (args[3].parent.parent.name, args[3].parent.name) == slot and not changed:
            events = [json.loads(line) for line in text.splitlines()]
            for event in events:
                if event.get('type') == 'item.completed':
                    event['item']['text'] = '{"assessments": ['
            text = '\n'.join(json.dumps(event) for event in events) + '\n'
            args[3].write_text(text, encoding='utf-8')
            changed.append(True)
        return process, text, stderr
    fixture.native = run


class BoundaryRecoveryTests(unittest.TestCase):
    def test_message_shape_errors_have_a_content_type(self):
        from report_review_host import parse_agent_trace
        from review_judgment import ModelJudgmentError
        for value in ([], 7, 'text', True, None, {}, {'assessments': {}},
                      {'assessments': [], 'future_applications': None},
                      {'assessments': [], 'enforcement_signals': {}}):
            with self.subTest(value=value):
                events = [{'type': 'thread.started', 'thread_id': 'one'},
                          {'type': 'turn.started'},
                          {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(value)}},
                          {'type': 'turn.completed'}]
                with self.assertRaisesRegex(ModelJudgmentError, 'REPORT_REVIEW_HOST_OUTPUT_INVALID'):
                    parse_agent_trace('\n'.join(json.dumps(row) for row in events))

    def test_wrong_message_shapes_resume_each_review_mode(self):
        for kind, group in (('visual', 'integrated'), ('seven-country-large', 'technical'),
                            ('seven-country-large', 'summary')):
            for value in ([], None, {'assessments': {}},
                          {'assessments': [], 'future_applications': None},
                          {'assessments': [], 'enforcement_signals': {}}):
                with self.subTest(group=group, value=value), recovery_fixture(kind=kind) as fixture:
                    message_once(fixture, ('2', group), json.dumps(value))
                    self.assert_retry(fixture, group)

    def test_wrong_shape_still_checks_unsigned_host_files_and_known_image_bytes(self):
        for value in ([], {'assessments': {}}):
            for name in ('sandbox.sb', 'stderr.log', 'image', 'events.jsonl'):
                for damage in ('missing', 'changed'):
                    # Unsigned stderr/profile have no persisted expected hash.
                    # Signed profile byte changes are covered separately below.
                    # A missing unsigned trace is a normal interrupted execution.
                    if (name, damage) in (('stderr.log', 'changed'), ('sandbox.sb', 'changed'),
                                          ('events.jsonl', 'missing')):
                        continue
                    with self.subTest(value=value, name=name, damage=damage), recovery_fixture() as fixture:
                        message_once(fixture, ('2', 'integrated'), json.dumps(value))
                        with self.assertRaises(ValueError): fixture.run()
                        directory = fixture.output / '2/integrated'
                        path = next(directory.glob('*.png')) if name == 'image' else directory / name
                        if damage == 'missing': path.unlink()
                        else: path.write_bytes(path.read_bytes() + b'broken')
                        before, calls = snapshot(fixture.output), len(fixture.calls)
                        with self.assertRaises(ValueError): fixture.run(resume=True)
                        self.assertEqual(snapshot(fixture.output), before)
                        self.assertEqual(len(fixture.calls), calls)

    def test_wrong_shape_still_rejects_a_changed_isolation_backend(self):
        with recovery_fixture() as fixture:
            message_once(fixture, ('2', 'integrated'), '[]')
            with self.assertRaises(ValueError): fixture.run()
            directory = fixture.output / '2/integrated'
            (directory / 'sandbox.sb').unlink()
            (directory / 'isolation-policy.json').write_text('{}', encoding='utf-8')
            before, calls = snapshot(fixture.output), len(fixture.calls)
            with self.assertRaisesRegex(ValueError, 'ISOLATION_BACKEND_CHANGED'):
                fixture.run(resume=True)
            self.assertEqual(snapshot(fixture.output), before)
            self.assertEqual(len(fixture.calls), calls)

    def test_non_string_native_message_is_not_retryable_content(self):
        from review_judgment import ModelJudgmentError
        for value in (None, [], {}, 7):
            with self.subTest(value=value), recovery_fixture() as fixture:
                message_once(fixture, ('2', 'integrated'), value)
                with self.assertRaises(ValueError) as caught: fixture.run()
                self.assertNotIsInstance(caught.exception, ModelJudgmentError)
                before, calls = snapshot(fixture.output), len(fixture.calls)
                with self.assertRaisesRegex(ValueError, 'REPORT_REVIEW_HOST_OUTPUT_INVALID'):
                    fixture.run(resume=True)
                self.assertEqual(snapshot(fixture.output), before)
                self.assertEqual(len(fixture.calls), calls)

    def test_later_integrity_failure_prevents_earlier_shape_error_archive(self):
        with recovery_fixture() as fixture:
            message_once(fixture, ('1', 'integrated'), '[]')
            with self.assertRaises(ValueError): fixture.run()
            (fixture.output / '2/integrated/sandbox.sb').unlink()
            before, calls = snapshot(fixture.output), len(fixture.calls)
            # The peer's completed turn is now captured with its real audit before the failed slot stops the run,
            # so a missing signed file is reported by the audit check; an unsigned one by the host-file check.
            with self.assertRaisesRegex(ValueError, 'HOST_FILES_MISSING|RETAINED_AUDIT_CHANGED'):
                fixture.run(resume=True)
            self.assertEqual(snapshot(fixture.output), before)
            self.assertEqual(len(fixture.calls), calls)

    def test_failed_module_does_not_cost_its_peers_their_real_audits(self):
        """Every finished session is persisted with its real audit before a validation failure stops the run."""
        for kind, failed, peer in (('visual', ('1', 'integrated'), ('2', 'integrated')),
                                   ('seven-country-large', ('1', 'technical'), ('2', 'technical'))):
            with self.subTest(kind=kind), recovery_fixture(kind=kind) as fixture:
                message_once(fixture, failed, '[]')
                with self.assertRaises(ValueError):
                    fixture.run()
                audit = load_json(fixture.output / peer[0] / peer[1] / 'audit.json')
                self.assertNotIn('recovered_from_retained_trace', audit)
                self.assertIsNotNone(audit.get('process_id'))
                self.assertEqual(audit.get('exit_code'), 0)
                before = len(fixture.calls)
                fixture.run(resume=True)
                self.assertEqual([call for call in fixture.calls[before:] if call[1] != 'summary'], [failed])

    def test_applicability_status_types_resume_without_coercion(self):
        for kind, group in (('visual', 'integrated'), ('seven-country-large', 'technical')):
            for status in ([], {}, 7, True, None, 'unknown', 'missing'):
                with self.subTest(group=group, status=status), recovery_fixture(kind=kind) as fixture:
                    def change(raw):
                        value = {'reasoning': 'Synthetic status test', 'evidence_refs': ['E-IMAGE']}
                        if status != 'missing': value['status'] = status
                        raw['assessments'][0]['scope_applicability'] = value
                    change_native_once(fixture, ('2', group), change)
                    self.assert_retry(fixture, group)

    def test_applicability_optional_and_legal_states_still_validate(self):
        for status in (None, 'applicable', 'not_applicable', 'unassessed'):
            with self.subTest(status=status), recovery_fixture() as fixture:
                change_native_once(fixture, ('2', 'integrated'), lambda raw:
                    raw['assessments'][0].update(scope_applicability=None if status is None else {
                        'status': status, 'reasoning': 'Synthetic applicability basis', 'evidence_refs': ['E-IMAGE']}))
                fixture.run()
                before, calls = snapshot(fixture.output), len(fixture.calls)
                fixture.run(resume=True)
                self.assertEqual(snapshot(fixture.output), before)
                self.assertEqual(len(fixture.calls), calls)

    def test_signed_invalid_status_cannot_hide_corrupt_audit_or_originals(self):
        for name in ('audit.json', 'events.jsonl', 'agent-judgment.json', 'sandbox.sb', 'image'):
            for damage in ('missing', 'changed'):
                # Audit absence has an existing complete-log recovery contract.
                if name == 'audit.json' and damage == 'missing': continue
                with self.subTest(name=name, damage=damage), recovery_fixture() as fixture:
                    change_native_once(fixture, ('2', 'integrated'), lambda raw:
                        raw['assessments'][0].update(scope_applicability={'status': []}))
                    with self.assertRaises(ValueError): fixture.run()
                    directory = fixture.output / '2/integrated'
                    self.assertTrue((directory / 'audit.json').is_file())
                    path = next(directory.glob('*.png')) if name == 'image' else directory / name
                    if damage == 'missing': path.unlink()
                    else: path.write_bytes(path.read_bytes() + b'broken')
                    before, calls = snapshot(fixture.output), len(fixture.calls)
                    with self.assertRaises(ValueError): fixture.run(resume=True)
                    self.assertEqual(snapshot(fixture.output), before)
                    self.assertEqual(len(fixture.calls), calls)

    def assert_retry(self, fixture, group):
        with self.assertRaises(ValueError):
            fixture.run()
        before = snapshot(fixture.output / '1')
        failed = snapshot(fixture.output / '2' / group)
        calls = len(fixture.calls)
        fixture.run(resume=True)
        expected = [('2', group)]
        if group == 'technical':
            expected += [('1', 'summary'), ('2', 'summary')]
        self.assertCountEqual(fixture.calls[calls:], expected)
        after = snapshot(fixture.output / '1')
        self.assertEqual({key: after[key] for key in before}, before)
        self.assertEqual(snapshot(fixture.output / '2' / (group + '.attempt-1')), failed)
        complete, calls = snapshot(fixture.output), len(fixture.calls)
        with patch('native_review_jobs.tempfile.mkdtemp', side_effect=AssertionError('no new workspace')):
            fixture.run(resume=True)
        self.assertEqual(len(fixture.calls), calls)
        self.assertEqual(snapshot(fixture.output), complete)

    def test_invalid_message_json_recovers_small_module_and_summary(self):
        for kind, group in (('visual', 'integrated'), ('seven-country-large', 'technical'),
                            ('seven-country-large', 'summary')):
            with self.subTest(group=group), recovery_fixture(kind=kind) as fixture:
                invalid_json_once(fixture, ('2', group))
                self.assert_retry(fixture, group)

    def test_invalid_row_enum_types_recover_without_coercion(self):
        for kind, group in (('visual', 'integrated'), ('seven-country-large', 'technical')):
            for field in ('right_type', 'right_state'):
                for value in ([], {}, None, 7):
                    with self.subTest(group=group, field=field, value=value), recovery_fixture(kind=kind) as fixture:
                        change_native_once(fixture, ('2', group),
                            lambda raw: raw['assessments'][0].update({field: value}))
                        self.assert_retry(fixture, group)

    def test_invalid_message_does_not_hide_missing_host_files_or_images(self):
        for name in ('sandbox.sb', 'stderr.log', 'image'):
            with self.subTest(name=name), recovery_fixture() as fixture:
                invalid_json_once(fixture, ('2', 'integrated'))
                with self.assertRaises(ValueError): fixture.run()
                directory = fixture.output / '2/integrated'
                path = next(directory.glob('*.png')) if name == 'image' else directory / name
                path.unlink()
                before, calls = snapshot(fixture.output), len(fixture.calls)
                with self.assertRaisesRegex(ValueError, 'HOST_FILES_MISSING|IMAGE_CHANGED'):
                    fixture.run(resume=True)
                self.assertEqual(snapshot(fixture.output), before)
                self.assertEqual(len(fixture.calls), calls)

    def test_outer_event_log_corruption_never_retries(self):
        with recovery_fixture() as fixture:
            invalid_json_once(fixture, ('2', 'integrated'))
            with self.assertRaises(ValueError): fixture.run()
            path = fixture.output / '2/integrated/events.jsonl'
            path.write_text(path.read_text(encoding='utf-8') + '{broken event\n', encoding='utf-8')
            before, calls = snapshot(fixture.output), len(fixture.calls)
            with self.assertRaises(json.JSONDecodeError): fixture.run(resume=True)
            self.assertEqual(snapshot(fixture.output), before)
            self.assertEqual(len(fixture.calls), calls)

    def test_changed_reuse_selection_recovers_without_rewriting_previous_reviews(self):
        from module_review import run_module_pair
        from review_readiness import prepare_review_context, freeze_input
        for kind, group in (('visual', 'integrated'), ('seven-country-large', 'technical')):
            with self.subTest(group=group), recovery_fixture(kind=kind) as fixture:
                fixture.run()
                old, old_bytes = fixture.output, snapshot(fixture.output)
                task = load_json(fixture.source / 'task.json')
                task['product']['title'] = 'Updated product facts'
                atomic_write_json(fixture.source / 'task.json', task)
                fixture.output = fixture.root / 'review-next'; fixture.output.mkdir()
                fixture.context = prepare_review_context(fixture.source)
                fixture.meta = freeze_input(fixture.source, fixture.output / 'frozen.json', prepared_context=fixture.context)
                fixture.frozen = load_json(fixture.output / 'frozen.json')
                native, changed = fixture.native, []
                def stale(*args):
                    proc, text, stderr = native(*args)
                    if (args[3].parent.parent.name, args[3].parent.name) == ('2', group) and not changed:
                        packet = load_json(args[3].parent / 'packet.json')
                        self.assertTrue(packet['review_reuse']['changed_unit_ids'])
                        events = [json.loads(line) for line in text.splitlines()]
                        for event in events:
                            if event.get('type') == 'item.completed':
                                raw = json.loads(event['item']['text'])
                                raw.update(assessments=[], reused_unit_ids=packet['review_reuse']['changed_unit_ids'])
                                event['item']['text'] = json.dumps(raw)
                        text = '\n'.join(json.dumps(event) for event in events) + '\n'
                        args[3].write_text(text, encoding='utf-8'); changed.append(True)
                    return proc, text, stderr
                def run(*, resume=False):
                    with patch('report_review_host.run_native_logged', side_effect=stale), \
                            patch('native_review_jobs._probe', return_value=[]), \
                            patch('macos_review_host.require_chatgpt_auth'):
                        return run_module_pair(fixture.source, fixture.output, fixture.binary,
                            fixture.frozen, fixture.meta, fixture.context, timeout=10, max_parallel=2,
                            resume_existing=resume, isolation='macos-sandbox',
                            previous_first=old / '1/review.json', previous_second=old / '2/review.json')
                fixture.run = run
                self.assert_retry(fixture, group)
                self.assertEqual(snapshot(old), old_bytes)


if __name__ == '__main__':
    unittest.main()

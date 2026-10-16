"""Invalid model content must be recoverable without relaxing integrity gates."""
import json
import unittest
from unittest.mock import patch

from common import load_json
from test_review_identity_recovery import recovery_fixture, snapshot


def change_native_once(fixture, slot, change):
    native = fixture.native
    changed = []
    def run(command, prompt, workspace, trace_path, stderr_path, timeout):
        proc, text, stderr = native(command, prompt, workspace, trace_path, stderr_path, timeout)
        current = (trace_path.parent.parent.name, trace_path.parent.name)
        if current == slot and not changed:
            events = [json.loads(line) for line in text.splitlines()]
            for event in events:
                if event.get('type') == 'item.completed':
                    raw = json.loads(event['item']['text'])
                    change(raw)
                    event['item']['text'] = json.dumps(raw)
            text = '\n'.join(json.dumps(event) for event in events) + '\n'
            trace_path.write_text(text, encoding='utf-8')
            changed.append(True)
        return proc, text, stderr
    fixture.native = run


class ReviewOutputRecoveryTests(unittest.TestCase):
    def test_signal_content_errors_are_typed_but_unknown_validation_errors_are_not(self):
        from assessment_estimate import validate_review_signals
        from annotate_materiality import candidate_index
        from review_judgment import ModelJudgmentError
        from test_assessment_workflow_correction import CorrectedAssessmentTests
        fixture = CorrectedAssessmentTests(); fixture.setUp()
        try:
            signal = fixture.signal(qualified=True)
            task, _, candidates, _, _, _, _ = fixture.values
            index, errors = candidate_index(candidates)
            self.assertEqual(errors, [])
            signal['candidate_id'] = 'not-a-candidate'
            with self.assertRaisesRegex(ModelJudgmentError, 'FUTURE_SIGNAL_CANDIDATE_SCOPE_INVALID'):
                validate_review_signals({'future_applications': [signal]}, set(signal['evidence_refs']), index, task)
            with patch('assessment_estimate._future_review_qualified', side_effect=ValueError('UNEXPECTED_VALIDATOR_FAILURE')):
                try:
                    validate_review_signals({'future_applications': [signal]}, set(signal['evidence_refs']), index, task)
                except ValueError as exc:
                    self.assertNotIsInstance(exc, ModelJudgmentError)
                    self.assertEqual(str(exc), 'UNEXPECTED_VALIDATOR_FAILURE')
                else:
                    self.fail('Unexpected validator errors must propagate')
        finally:
            fixture.tearDown()

    def test_recorder_based_untransmitted_content_errors_resume(self):
        # Combine the real recorder's private-material contract with the small
        # scheduling fixture. Both original validators run; no acceptance gate
        # is replaced with a successful stub.
        import module_review
        from test_second_round_review_policy import MaterialPolicyTests
        fixture = MaterialPolicyTests(); fixture.setUp()
        try:
            fixture.attach()
            private = fixture.packet
            hashes = {row['sha256'] for row in private['retained_originals']['not_transmitted']}
            limitation = 'The local original was not transmitted or read.'
            variants = (
                ('visual', 'integrated', lambda raw: raw.pop('untransmitted_material_acknowledgements')),
                ('visual', 'integrated', lambda raw: next(iter(raw['untransmitted_material_acknowledgements'].values())).update(original_read=True)),
                ('visual', 'integrated', lambda raw: raw['final_review_statement'].update(limitations='Missing local limitation.')),
                ('seven-country-large', 'summary', lambda raw: raw['final_review_statement'].update(limitations='Missing module limitation.')),
            )
            actual = module_review.validate_original_observations
            def validate(raw, packet):
                actual(raw, packet)
                if packet.get('modules'):
                    actual(raw, {'task': private['task'], 'modules': packet['modules']})
                else:
                    actual(raw, private)
            for kind, group, change in variants:
                with self.subTest(kind=kind, group=group), recovery_fixture(kind=kind) as f:
                    native = f.native
                    def supplied(*args):
                        proc, text, stderr = native(*args)
                        events = [json.loads(line) for line in text.splitlines()]
                        for event in events:
                            if event.get('type') == 'item.completed':
                                raw = json.loads(event['item']['text'])
                                raw['untransmitted_material_acknowledgements'] = {
                                    key: {'original_read': False, 'limitations': limitation} for key in hashes}
                                raw['final_review_statement']['limitations'] += ' ' + limitation
                                event['item']['text'] = json.dumps(raw)
                        text = '\n'.join(json.dumps(event) for event in events) + '\n'
                        args[3].write_text(text, encoding='utf-8')
                        return proc, text, stderr
                    f.native = supplied
                    change_native_once(f, ('2', group), change)
                    with patch.object(module_review, 'validate_original_observations', side_effect=validate):
                        with self.assertRaisesRegex(ValueError, 'UNTRANSMITTED'):
                            f.run()
                        self.assertFalse((f.output / '2' / group / 'audit.json').exists())
                        calls = len(f.calls); before = snapshot(f.output / '1')
                        f.run(resume=True)
                        self.assertEqual(f.calls[calls:], [('2', group)])
                        after = snapshot(f.output / '1')
                        self.assertEqual({key: after[key] for key in before}, before)
        finally:
            fixture.doCleanups()

    def test_invalid_final_fields_retry_only_failed_position(self):
        variants = (
            ('empty-statement', lambda raw: raw.update(final_review_statement={})),
            ('numeric-statement', lambda raw: raw['final_review_statement'].update(overall=7)),
            ('wrong-statement-type', lambda raw: raw.update(final_review_statement=7)),
            ('confidence', lambda raw: raw.update(coverage_confidence_cap='invalid')),
            ('confidence-null', lambda raw: raw.update(coverage_confidence_cap=None)),
            ('confidence-list', lambda raw: raw.update(coverage_confidence_cap=[])),
            ('confidence-object', lambda raw: raw.update(coverage_confidence_cap={})),
            ('confidence-reason', lambda raw: raw.update(coverage_confidence_reasoning='')),
            ('confidence-reason-type', lambda raw: raw.update(coverage_confidence_reasoning=7)),
            ('reviewer', lambda raw: raw.update(reviewer='')),
        )
        for kind, group in (('visual', 'integrated'), ('seven-country-large', 'summary')):
            for name, change in variants:
                with self.subTest(kind=kind, invalid=name), recovery_fixture(kind=kind) as f:
                    change_native_once(f, ('2', group), change)
                    with self.assertRaises(ValueError):
                        f.run()
                    before, calls = snapshot(f.output / '1'), len(f.calls)
                    failed = snapshot(f.output / '2' / group)
                    f.run(resume=True)
                    self.assertEqual(f.calls[calls:], [('2', group)])
                    after = snapshot(f.output / '1')
                    self.assertEqual({key: after[key] for key in before}, before)
                    self.assertEqual(snapshot(f.output / '2' / (group + '.attempt-1')), failed)
                    self.assertEqual(load_json(f.output / 'freeze-receipt.json')['status'], 'pair_validated')

    def test_content_failure_never_hides_peer_integrity_failure(self):
        with recovery_fixture() as f:
            change_native_once(f, ('1', 'integrated'), lambda raw: raw.update(coverage_confidence_cap='invalid'))
            with self.assertRaises(ValueError):
                f.run()
            (f.output / '2/integrated/packet.json').write_text('{}', encoding='utf-8')
            before, calls = snapshot(f.output), len(f.calls)
            with self.assertRaisesRegex(ValueError, 'PACKET_OR_PROMPT_CHANGED'):
                f.run(resume=True)
            self.assertEqual(snapshot(f.output), before)
            self.assertEqual(len(f.calls), calls)

    def test_invalid_signal_retries_own_module_then_own_summary(self):
        with recovery_fixture(kind='seven-country-large') as f:
            change_native_once(f, ('2', 'technical'), lambda raw: raw.update(future_applications=[{}]))
            with self.assertRaisesRegex(ValueError, 'SUPPLEMENTAL_SIGNAL_EVIDENCE_REQUIRED'):
                f.run()
            calls = len(f.calls)
            retained = {group: snapshot(f.output / '2' / group) for group in ('appearance', 'expression')}
            f.run(resume=True)
            self.assertCountEqual(f.calls[calls:], [('2', 'technical'), ('1', 'summary'), ('2', 'summary')])
            # Neither summary existed on the interrupted initial run. No peer
            # module may repeat; the two newly necessary summaries each run once.
            for group, before in retained.items():
                after = snapshot(f.output / '2' / group)
                self.assertEqual({key: after[key] for key in before}, before)

    def test_tool_activity_never_becomes_a_retryable_content_failure(self):
        with recovery_fixture() as f:
            native = f.native
            def with_tool(*args):
                proc, text, stderr = native(*args)
                if args[3].parent.parent.name == '2':
                    events = [json.loads(line) for line in text.splitlines()]
                    events.insert(2, {'type': 'item.completed', 'item': {'type': 'command_execution'}})
                    text = '\n'.join(json.dumps(event) for event in events) + '\n'
                    args[3].write_text(text, encoding='utf-8')
                return proc, text, stderr
            f.native = with_tool
            with self.assertRaisesRegex(ValueError, 'TOOL_ACTIVITY_FORBIDDEN'):
                f.run()
            before, calls = snapshot(f.output), len(f.calls)
            with self.assertRaisesRegex(ValueError, 'TOOL_ACTIVITY_FORBIDDEN'):
                f.run(resume=True)
            self.assertEqual(snapshot(f.output), before)
            self.assertEqual(len(f.calls), calls)


if __name__ == '__main__':
    unittest.main()

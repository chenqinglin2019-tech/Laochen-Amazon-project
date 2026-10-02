"""Preflight never rebinds reviews or mutates inputs."""
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import review_readiness as mod
from record_independent_review import validate_host_input_digest

class ReviewReadinessTests(unittest.TestCase):
    def test_prepared_context_calls_readiness_once_and_checks_actual_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(mod, '_preparation_integrity', return_value={'original': 'SHA'}), \
                 patch.object(mod, 'current_digest', return_value='D'), \
                 patch.object(mod, 'readiness', return_value={'ready': True, 'input_digest': 'D'}) as gate:
                context = mod.prepare_review_context(root)
                self.assertEqual(context.validate(root)['input_digest'], 'D')
                frozen = root / 'frozen.json'
                frozen.write_text('{}')
                context.bind_freeze(frozen)
                context.validate(root, frozen=True)
                gate.assert_called_once_with(root.resolve())
                frozen.write_text('{"changed": true}')
                with self.assertRaisesRegex(ValueError, 'FREEZE_CHANGED'):
                    context.validate(root, frozen=True)
                with patch.object(mod, '_preparation_integrity', return_value={'original': 'ALTERED'}):
                    with self.assertRaisesRegex(ValueError, 'INPUT_CHANGED'):
                        context.validate(root)
                with patch.object(mod, 'current_digest', return_value='NEW'):
                    with self.assertRaisesRegex(ValueError, 'INPUT_CHANGED'):
                        context.validate(root)
            with self.assertRaisesRegex(ValueError, 'NOT_ISSUED'):
                mod.PreparedReviewContext(root, {'ready': True}, {}, object())
            with self.assertRaisesRegex(ValueError, 'NOT_ISSUED'):
                mod.freeze_input(root, root / 'other.json', prepared_context={'ready': True})

    def test_prepared_freeze_writes_before_binding_and_does_not_repeat_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'freeze.json'
            task = {'task_id': 'T1'}
            with patch.object(mod, '_preparation_integrity', return_value={}), \
                 patch.object(mod, 'current_digest', return_value='same'), \
                 patch.object(mod, 'readiness', return_value={'ready': True, 'input_digest': 'same'}) as gate, \
                 patch.object(mod, 'load_json', side_effect=lambda path: task if str(path).endswith('task.json') else {'queries': {}}), \
                 patch('workflow_v24._scenario_context', return_value=({}, {}, {})), \
                 patch('workflow_v24.scenario_supplement', return_value={}), \
                 patch('assessment_estimate.review_digest', return_value='same'):
                context = mod.prepare_review_context(root)
                mod.freeze_input(root, target, prepared_context=context)
                context.validate(root, frozen=True)
                gate.assert_called_once()
                self.assertTrue(target.is_file())

    def test_stale_review_removed_from_dispatch_only(self):
        review = {'review_context': {'evidence_digest': 'old'}}
        with patch.object(mod, 'current_digest', return_value='current'), patch(
                'workflow_v24.work_view_from_dir', return_value={'entries': []}) as derive:
            view = mod.dispatch_view(Path('/task'), first_review=review)
        derive.assert_called_once_with(Path('/task'), first_review=None, second_review=None)
        self.assertEqual(review['review_context']['evidence_digest'], 'old')
        self.assertEqual(view['invalidated_reviews'][0]['reason'], 'REVIEW_INPUT_CHANGED')

    def test_current_invalid_review_reaches_validator(self):
        with patch.object(mod, 'current_digest', return_value='current'), patch(
                'workflow_v24.work_view_from_dir', side_effect=ValueError('invalid attestation')):
            with self.assertRaisesRegex(ValueError, 'invalid attestation'):
                mod.dispatch_view(Path('/task'), first_review={'review_context': {'evidence_digest': 'current'}})

    def test_malformed_review_not_ignored(self):
        with patch.object(mod, 'current_digest', return_value='current'):
            with self.assertRaisesRegex(ValueError, 'REVIEW_CONTEXT_INVALID'):
                mod.dispatch_view(Path('/task'), first_review={})

    def test_readiness_blocks_work_and_stale_scope(self):
        view = {'entries': [{'state': 'awaiting_review', 'reason': 'MATERIAL'}],
                'review_progress': {'items': [{'item_id': 'I1', 'state': 'completed', 'scope': {'product_version': '2'}}]}}
        with patch.object(mod, 'dispatch_view', return_value=view), patch.object(
                mod, 'load_json', return_value={'product_change_version': 3}), patch.object(
                mod, 'current_digest', return_value='current'):
            result = mod.readiness(Path('/task'))
            self.assertFalse(result['ready'])
            self.assertEqual(len(result['stale_progress_items']), 1)
            view['entries'] = [{'state': 'awaiting_user'}]
            view['review_progress']['items'] = []
            result = mod.readiness(Path('/task'))
            self.assertTrue(result['ready'])
            self.assertEqual(result['external_dependencies'], [{'state': 'awaiting_user'}])

    def test_host_digest_never_silently_rebound(self):
        task = {'execution_policy_revision': 'continuous-work-v2'}
        with self.assertRaisesRegex(ValueError, 'REQUIRED'):
            validate_host_input_digest({}, 'current', task)
        with self.assertRaisesRegex(ValueError, 'MISMATCH'):
            validate_host_input_digest({'input_digest': 'old'}, 'current', task)
        validate_host_input_digest({'input_digest': 'current'}, 'current', task)
        validate_host_input_digest({}, 'current', {})

    def test_freeze_refuses_unready_input_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'freeze.json'
            with patch.object(mod, 'readiness', return_value={'ready': False, 'blockers': [{'reason': 'PLAN'}]}), \
                 patch('common.atomic_write_json') as write:
                with self.assertRaisesRegex(ValueError, 'REVIEW_INPUT_NOT_READY'):
                    mod.freeze_input(Path('/task'), target)
            write.assert_not_called()
            self.assertFalse(target.exists())

    def test_freeze_is_bound_and_removed_if_inputs_change_during_export(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'freeze.json'
            task = {'task_id': 'T1'}
            with patch.object(mod, 'readiness', return_value={'ready': True, 'input_digest': 'same'}), \
                 patch.object(mod, 'load_json', side_effect=lambda path: task if str(path).endswith('task.json') else {'queries': {}}), \
                 patch('workflow_v24._scenario_context', return_value=({'candidates': []}, {'items': []}, {'evidence': []})), \
                 patch('workflow_v24.scenario_supplement', return_value={}), \
                 patch('assessment_estimate.review_digest', return_value='same'), \
                 patch.object(mod, 'current_digest', side_effect=['same', 'changed']):
                with self.assertRaisesRegex(ValueError, 'CHANGED_DURING_EXPORT'):
                    mod.freeze_input(Path('/task'), target)
            self.assertFalse(target.exists())

    def test_freeze_exports_common_payload_when_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'freeze.json'
            task = {'task_id': 'T1'}
            with patch.object(mod, 'readiness', return_value={'ready': True, 'input_digest': 'same'}), \
                 patch.object(mod, 'load_json', side_effect=lambda path: task if str(path).endswith('task.json') else {'queries': {}}), \
                 patch('workflow_v24._scenario_context', return_value=({'candidates': []}, {'items': []}, {'evidence': []})), \
                 patch('workflow_v24.scenario_supplement', return_value={}), \
                 patch('assessment_estimate.review_digest', return_value='same'), \
                 patch.object(mod, 'current_digest', side_effect=['same', 'same']):
                result = mod.freeze_input(Path('/task'), target)
            payload = json.loads(target.read_text())
            self.assertEqual(result['input_digest'], 'same')
            self.assertEqual(payload['evidence_digest'], 'same')
            self.assertFalse(payload['review_protocol']['first_review_visible'])
            with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS'):
                mod.freeze_input(Path('/task'), target)

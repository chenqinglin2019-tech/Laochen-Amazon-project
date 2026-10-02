"""Process-local delivery capability binding; offline, with real file hashes.

Only the expensive semantic validator is replaced. Source snapshots, retained
originals, package contracts, output hashes and local references use real code.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from common import atomic_write_json, load_json, sha256_file
import delivery_validation as validation
from delivery_versions_stage_e import _snapshot
from report_package_stage_c import CORE, OPERATOR_APPENDICES, REVISION


class DeliveryValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.output = self.root / 'build'
        self.source.mkdir()
        self.output.mkdir()
        self.task = {'task_id': 'offline-capability-test',
                     'presentation_policy_revision': 'operator-report-v1',
                     'assessment_policy': 'known-findings-v1',
                     'final_review_execution_revision': 'module-double-review-v1'}
        atomic_write_json(self.source / 'task.json', self.task)
        self.original = self.source / 'original.xml'
        self.original.write_bytes(b'<record id="US-1"><name>original</name></record>')
        atomic_write_json(self.source / 'evidence.json', {'records': [{
            'evidence_id': 'E1', 'path': 'original.xml', 'sha256': sha256_file(self.original)}]})
        atomic_write_json(self.source / 'search-plan.json', {'queries': [{'query_id': 'Q1', 'territory': 'US'}]})
        atomic_write_json(self.source / 'source-capabilities.json', {'provider': 'offline', 'permission': True})
        self.reviews = {'first_review': str(self.source / 'first-review.json'),
                        'second_review': str(self.source / 'second-review.json'), 'adjudication': None}
        for name in ('first_review', 'second_review'):
            atomic_write_json(Path(self.reviews[name]), {'reviewer': name, 'status': 'passed', 'input_digest': 'frozen'})
        (self.output / 'files').mkdir()
        shutil.copyfile(self.original, self.output / 'files' / 'original.xml')
        self.model = {'presentation_policy_revision': 'operator-report-v1',
                      'visual_evidence': [], 'linked_files': [], 'evidence_index': [{
                          'evidence_id': 'E1', 'path': 'files/original.xml',
                          'sha256': sha256_file(self.output / 'files' / 'original.xml')}],
                      'report_package_stage_c': {'revision': REVISION, 'exports': [],
                                                'required_artifacts': [*CORE, *OPERATOR_APPENDICES]}}
        atomic_write_json(self.output / 'report-data.json', self.model)
        atomic_write_json(self.output / 'report-manifest.json', {'test': 'offline'})
        atomic_write_json(self.output / 'assessment.json', {'risk': 'low'})
        atomic_write_json(self.output / 'task.json', self.task)
        (self.output / 'report.html').write_text(
            '<a href="files/original.xml">original</a>'
            '<a href="report-data.json#/evidence_index/0">record</a>'
            '<a href="reference.html#proof">proof</a>', encoding='utf-8')
        (self.output / 'reference.html').write_text('<div id="proof">local reference</div>', encoding='utf-8')
        for name in OPERATOR_APPENDICES:
            (self.output / name).write_text('<p>offline appendix</p>', encoding='utf-8')
        # A real content fingerprint isolates the transaction behavior from
        # concurrent edits to the shared production scripts by other agents.
        self.implementation = self.root / 'implementation.py'
        self.implementation.write_text('revision = 1\n', encoding='utf-8')
        self.impl_patch = patch.object(validation, '_implementation', side_effect=lambda: {
            'implementation.py': sha256_file(self.implementation)})
        self.impl_patch.start()
        self.addCleanup(self.impl_patch.stop)

    def begin(self):
        return validation.begin(self.source, **self.reviews)

    def validated(self):
        context = self.begin()
        with patch('report_estimate.validate_run', return_value=[]) as semantic:
            self.assertEqual(context.validate_staged(self.output), [])
            semantic.assert_called_once_with(self.source.resolve(), self.task, output_dir=self.output.resolve())
        return context

    def test_one_semantic_check_then_zero_for_copy_and_repeated_verification(self):
        context = self.begin()
        target = self.root / 'entry'
        with patch('report_estimate.validate_run', return_value=[]) as semantic:
            self.assertEqual(context.validate_staged(self.output), [])
            shutil.copytree(self.output, target)
            for directory in (self.output, target, target):
                self.assertEqual(context.verify(directory, source=self.source, reviews=self.reviews), [])
            self.assertEqual(semantic.call_count, 1)
            with self.assertRaisesRegex(ValueError, 'CONTEXT_ALREADY_USED'):
                context.validate_staged(target)
        self.assertEqual(context.semantic_checks, 1)
        audit = context.audit()
        self.assertEqual(audit['semantic_checks'], 1)
        self.assertEqual(audit['checked_files']['files/original.xml'], sha256_file(self.original))
        self.assertEqual(context._snapshot, _snapshot(self.source, self.reviews))
        audit['checked_files']['report.html'] = 'forged'
        self.assertEqual(context.verify(target), [])

    def test_changed_source_fact_refuses_reuse_without_semantic_call(self):
        context = self.validated()
        atomic_write_json(self.source / 'search-plan.json', {'queries': [{'query_id': 'Q2', 'territory': 'JP'}]})
        with patch('report_estimate.validate_run') as semantic:
            self.assertIn('DELIVERY_VALIDATION_CONTEXT_INPUT_CHANGED', context.verify(self.output))
        semantic.assert_not_called()

    def test_changed_policy_refuses_reuse(self):
        context = self.validated()
        task = deepcopy(self.task)
        task['assessment_policy'] = 'other-policy'
        atomic_write_json(self.source / 'task.json', task)
        self.assertIn('DELIVERY_VALIDATION_CONTEXT_INPUT_CHANGED', context.verify(self.output))

    def test_changed_review_payload_and_substituted_review_path_refuse_reuse(self):
        context = self.validated()
        other = self.source / 'other-review.json'
        atomic_write_json(other, load_json(Path(self.reviews['first_review'])))
        replacement = {**self.reviews, 'first_review': str(other)}
        self.assertIn('DELIVERY_VALIDATION_CONTEXT_REVIEWS_MISMATCH', context.verify(self.output, reviews=replacement))
        atomic_write_json(Path(self.reviews['second_review']), {'status': 'failed'})
        self.assertIn('DELIVERY_VALIDATION_CONTEXT_INPUT_CHANGED', context.verify(self.output))

    def test_changed_source_original_bytes_detected_with_unchanged_evidence_json(self):
        context = self.validated()
        before = (self.source / 'evidence.json').read_bytes()
        self.original.write_bytes(b'changed original')
        self.assertEqual(before, (self.source / 'evidence.json').read_bytes())
        self.assertIn('DELIVERY_VALIDATION_CONTEXT_INPUT_CHANGED', context.verify(self.output))

    def test_changed_or_missing_output_bytes_refuse_reuse(self):
        for name in ('report-data.json', 'report.html', 'assessment.json', 'task.json',
                     'operator-appendix.html', 'technical-audit.html', 'files/original.xml'):
            with self.subTest(name=name):
                context = self.validated()
                path = self.output / name
                before = path.read_bytes()
                path.write_bytes(before + b'changed')
                self.assertIn('DELIVERY_ACTUAL_FILE_MISSING_OR_CHANGED:' + name, context.verify(self.output))
                path.write_bytes(before)
        context = self.validated()
        (self.output / 'files' / 'original.xml').unlink()
        self.assertIn('DELIVERY_ACTUAL_FILE_MISSING_OR_CHANGED:files/original.xml', context.verify(self.output))

    def test_local_link_target_and_anchor_are_checked_on_every_verify(self):
        context = self.validated()
        reference = self.output / 'reference.html'
        reference.write_text('<p>anchor removed</p>', encoding='utf-8')
        self.assertIn('DELIVERY_LOCAL_ANCHOR_UNAVAILABLE:reference.html#proof', context.verify(self.output))
        reference.unlink()
        self.assertIn('DELIVERY_LOCAL_REFERENCE_UNAVAILABLE:reference.html#proof', context.verify(self.output))

    def test_invalid_local_json_pointer_and_escape_are_rejected(self):
        for link, error in (
            ('report-data.json#/evidence_index/999', 'DELIVERY_JSON_REFERENCE_UNAVAILABLE:'),
            ('../outside.json', 'DELIVERY_LOCAL_REFERENCE_OUTSIDE_ROOT:')):
            with self.subTest(link=link):
                (self.output / 'report.html').write_text('<a href="' + link + '">link</a>', encoding='utf-8')
                context = self.validated()
                self.assertIn(error + link, context.verify(self.output))

    def test_wrong_source_path_refuses_even_identical_source_copy(self):
        context = self.validated()
        copy = self.root / 'other-source'
        shutil.copytree(self.source, copy)
        self.assertIn('DELIVERY_VALIDATION_CONTEXT_SOURCE_MISMATCH', context.verify(self.output, source=copy))

    def test_saved_passed_flags_never_create_reusable_capability(self):
        context = self.begin()
        passed = {'status': 'passed', 'semantic_checks': 1, 'checked_files': {}, 'schema': 'IPR-DELIVERY-TRANSACTION/1.0'}
        atomic_write_json(self.output / 'delivery-validation.json', passed)
        self.assertEqual(context.verify(self.output), ['DELIVERY_VALIDATION_CONTEXT_NOT_VALIDATED'])
        with self.assertRaisesRegex(ValueError, 'CONTEXT_NOT_VALIDATED'):
            context.audit()
        for fake in (passed, load_json(self.output / 'delivery-validation.json'), object(), None):
            with self.subTest(fake=type(fake).__name__), self.assertRaisesRegex(ValueError, 'CONTEXT_REQUIRED'):
                validation.require(fake)

    def test_fake_context_token_and_subclass_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'CONTEXT_REQUIRED'):
            validation.DeliveryValidationContext(object(), self.source, self.reviews)
        fake = object.__new__(validation.DeliveryValidationContext)
        fake._token = object()
        with self.assertRaisesRegex(ValueError, 'CONTEXT_REQUIRED'):
            validation.require(fake)
        class FakeSubclass(validation.DeliveryValidationContext):
            pass
        fake = object.__new__(FakeSubclass)
        fake._token = self.begin()._token
        with self.assertRaisesRegex(ValueError, 'CONTEXT_REQUIRED'):
            validation.require(fake)
        self.assertIs(validation.require(self.begin()).__class__, validation.DeliveryValidationContext)

    def test_legacy_policy_not_silently_enrolled(self):
        atomic_write_json(self.source / 'task.json', {'task_id': 'legacy'})
        with self.assertRaisesRegex(ValueError, 'NEW_POLICY_REQUIRED'):
            self.begin()

    def test_implementation_change_invalidates_current_process_capability(self):
        context = self.validated()
        self.implementation.write_text('revision = 2\n', encoding='utf-8')
        with patch('report_estimate.validate_run') as semantic:
            self.assertIn('DELIVERY_VALIDATION_CONTEXT_IMPLEMENTATION_CHANGED', context.verify(self.output))
        semantic.assert_not_called()

    def test_change_before_validation_does_not_spend_semantic_check(self):
        context = self.begin()
        atomic_write_json(self.source / 'source-capabilities.json', {'permission': False})
        with patch('report_estimate.validate_run') as semantic:
            self.assertIn('DELIVERY_VALIDATION_CONTEXT_INPUT_CHANGED', context.validate_staged(self.output))
        semantic.assert_not_called()
        self.assertEqual(context.semantic_checks, 0)

    def test_semantic_failure_cannot_authorize_reuse_or_audit(self):
        context = self.begin()
        with patch('report_estimate.validate_run', return_value=['REAL_SEMANTIC_FAILURE']) as semantic:
            self.assertEqual(context.validate_staged(self.output), ['REAL_SEMANTIC_FAILURE'])
            self.assertEqual(context.verify(self.output), ['DELIVERY_VALIDATION_CONTEXT_NOT_VALIDATED'])
            semantic.assert_called_once()
        with self.assertRaisesRegex(ValueError, 'CONTEXT_NOT_VALIDATED'):
            context.audit()

    def test_output_mutation_during_semantic_check_refuses_binding(self):
        context = self.begin()
        def mutate(*args, **kwargs):
            (self.output / 'report.html').write_text('changed during check', encoding='utf-8')
            return []
        with patch('report_estimate.validate_run', side_effect=mutate) as semantic:
            self.assertEqual(context.validate_staged(self.output), ['DELIVERY_VALIDATION_OUTPUT_CHANGED_DURING_CHECK'])
            self.assertEqual(context.verify(self.output), ['DELIVERY_VALIDATION_CONTEXT_NOT_VALIDATED'])
            semantic.assert_called_once()

    def test_source_or_implementation_mutation_during_check_refuses_binding(self):
        for filename, message in ((self.original, 'DELIVERY_VALIDATION_CONTEXT_INPUT_CHANGED'),
                                  (self.implementation, 'DELIVERY_VALIDATION_CONTEXT_IMPLEMENTATION_CHANGED')):
            with self.subTest(filename=filename.name):
                before = filename.read_bytes()
                context = self.begin()
                def mutate(*args, **kwargs):
                    filename.write_bytes(b'changed during check')
                    return []
                with patch('report_estimate.validate_run', side_effect=mutate):
                    self.assertIn(message, context.validate_staged(self.output))
                self.assertEqual(context.verify(self.output), ['DELIVERY_VALIDATION_CONTEXT_NOT_VALIDATED'])
                filename.write_bytes(before)


if __name__ == '__main__':
    unittest.main()

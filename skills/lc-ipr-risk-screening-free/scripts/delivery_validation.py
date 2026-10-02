"""One independent semantic check within an immutable local delivery transaction.

The capability lives in this process only. Saved success flags never authorize
reuse; source, review, implementation and every delivered byte are checked again.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from common import load_json, sha256_file, sha256_json
from runtime_timing import timed_step

_TOKEN = object()


def enabled(task):
    return task.get('presentation_policy_revision') == 'operator-report-v1'


def _implementation():
    root = Path(__file__).resolve().parent.parent
    paths = list((root / 'scripts').glob('*.py'))
    paths += list((root / 'assets').glob('*.css')) + list((root / 'assets').glob('*.html'))
    paths.append(root / 'references' / 'report-format-lock.json')
    return {str(path.relative_to(root)): sha256_file(path) for path in paths
            if path.is_file() and not path.name.startswith('test_')}


class DeliveryValidationContext:
    __slots__ = ('_source', '_reviews', '_snapshot', '_implementation', '_files',
                 '_model', '_checks', '_token')

    def __init__(self, token, source, reviews):
        if token is not _TOKEN:
            raise ValueError('DELIVERY_VALIDATION_CONTEXT_REQUIRED')
        from delivery_versions_stage_e import _snapshot
        self._source = Path(source).resolve()
        self._reviews = {key: str(Path(value).resolve()) if value else None
                         for key, value in reviews.items()}
        self._snapshot = _snapshot(self._source, self._reviews)
        self._implementation = _implementation()
        self._files = None
        self._model = None
        self._checks = 0
        self._token = token

    @property
    def semantic_checks(self):
        return self._checks

    def _input_errors(self, source=None, reviews=None):
        from delivery_versions_stage_e import _snapshot
        errors = []
        if self._token is not _TOKEN or (source is not None and Path(source).resolve() != self._source):
            return ['DELIVERY_VALIDATION_CONTEXT_SOURCE_MISMATCH']
        if reviews is not None:
            paths = {key: str(Path(value).resolve()) if value else None for key, value in reviews.items()}
            if paths != self._reviews:
                errors.append('DELIVERY_VALIDATION_CONTEXT_REVIEWS_MISMATCH')
        if _snapshot(self._source, self._reviews) != self._snapshot:
            errors.append('DELIVERY_VALIDATION_CONTEXT_INPUT_CHANGED')
        if _implementation() != self._implementation:
            errors.append('DELIVERY_VALIDATION_CONTEXT_IMPLEMENTATION_CHANGED')
        return errors

    def validate_staged(self, directory):
        """Run the real validator once, then bind its successful exact bytes."""
        from report_estimate import validate_run, _resolve, _unique_file_records
        from report_package_stage_c import report_files
        if self._files is not None:
            raise ValueError('DELIVERY_VALIDATION_CONTEXT_ALREADY_USED')
        out = Path(directory).resolve()
        errors = self._input_errors()
        if errors:
            return errors
        model = load_json(out / 'report-data.json')
        names = [*report_files(model), 'assessment.json', 'task.json']
        names += [row['path'] for row in _unique_file_records(
            model['visual_evidence'] + model['evidence_index'] + model['linked_files'])]
        before = {name: sha256_file(_resolve(out, name)) for name in dict.fromkeys(names)}
        self._checks += 1
        with timed_step(self._source, 'independent_semantic_check'):
            errors = validate_run(self._source, load_json(out / 'task.json'), output_dir=out)
        errors += self._input_errors()
        if errors:
            return list(dict.fromkeys(errors))
        model = load_json(out / 'report-data.json')
        after = {name: sha256_file(_resolve(out, name)) for name in dict.fromkeys(names)}
        if after != before:
            return ['DELIVERY_VALIDATION_OUTPUT_CHANGED_DURING_CHECK']
        self._files = after
        self._model = sha256_json(model)
        # Detect source changes even while the successful output is being bound.
        errors = self._input_errors()
        if errors:
            self._files = None
            self._model = None
        return errors

    def verify(self, directory, *, source=None, reviews=None):
        """Recheck all frozen inputs, originals, output bytes and local references."""
        from delivery_versions_stage_e import _file_errors
        if self._files is None or self._checks != 1:
            return ['DELIVERY_VALIDATION_CONTEXT_NOT_VALIDATED']
        errors = self._input_errors(source, reviews)
        if not errors:
            errors += _file_errors(Path(directory).resolve(), self._files)
        errors += self._input_errors(source, reviews)
        return list(dict.fromkeys(errors))

    def audit(self):
        if self._files is None:
            raise ValueError('DELIVERY_VALIDATION_CONTEXT_NOT_VALIDATED')
        return {'schema': 'IPR-DELIVERY-TRANSACTION/1.0', 'semantic_checks': self._checks,
                'source_snapshot_sha256': sha256_json(self._snapshot),
                'implementation_sha256': sha256_json(self._implementation),
                'result_version_sha256': self._model, 'checked_files': deepcopy(self._files),
                'reuse_boundary': 'current_process_immutable_transaction'}


def begin(task_dir, *, first_review, second_review, adjudication=None):
    if not enabled(load_json(Path(task_dir) / 'task.json')):
        raise ValueError('DELIVERY_VALIDATION_TRANSACTION_NEW_POLICY_REQUIRED')
    return DeliveryValidationContext(_TOKEN, task_dir, {
        'first_review': first_review, 'second_review': second_review, 'adjudication': adjudication})


def require(value):
    if type(value) is not DeliveryValidationContext or value._token is not _TOKEN:
        raise ValueError('DELIVERY_VALIDATION_CONTEXT_REQUIRED')
    return value

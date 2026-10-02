"""10D independent, read-only inspection and bounded local artifact repair."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from common import atomic_write_bytes, atomic_write_json, load_json, now_iso, sha256_file, sha256_json

REVISION = 'delivery-inspection-stage-d-v1'
RENDERED = {'report.html', 'report.md', 'report-findings.csv', 'stage-result.txt',
            'stage-result.html', 'stage-result.md', 'stage-result.csv'}


def enabled(task):
    value = task.get('delivery_inspection_revision')
    if value is None:
        return False
    if value != REVISION:
        raise ValueError('DELIVERY_INSPECTION_REVISION_INVALID')
    return True


def task_binding(task):
    return {key: value for key, value in task.items() if key not in
        {'state', 'history', 'updated_at', 'outputs', 'assessment_policy', 'assessment_revision'}}


def source_task_errors(source, output_task):
    current = load_json(Path(source) / 'task.json')
    if task_binding(current) != task_binding(output_task):
        return ['REPORT_CURRENT_SOURCE_TASK_MISMATCH']
    if current.get('assessment_revision') is not None and current.get('assessment_revision') != output_task.get('assessment_revision'):
        return ['REPORT_CURRENT_SOURCE_REVISION_MISMATCH']
    if current.get('assessment_policy') != output_task.get('assessment_policy'):
        return ['REPORT_CURRENT_SOURCE_POLICY_MISMATCH']
    return []


def dependency_refs(registry, refs):
    """Find referenced originals through existing outcome records; do not invent dependencies."""
    pending, seen = list(refs), set()
    while pending:
        ref = pending.pop()
        if ref in seen:
            continue
        if ref not in registry:
            raise ValueError('STAGE_DEPENDENCY_REFERENCE_MISSING')
        seen.add(ref)
        row = registry[ref]['row']
        for key in ('evidence_refs', 'outcome_refs'):
            children = row.get(key, [])
            if not isinstance(children, list) or any(not isinstance(item, str) for item in children):
                raise ValueError('STAGE_DEPENDENCY_BOUNDARY_UNPROVEN')
            pending.extend(children)
    return sorted(seen)


def _hashes(directory):
    return {name: sha256_file(Path(directory) / name) if (Path(directory) / name).is_file() else None
        for name in ('task.json', 'evidence.json', 'normalized-candidates.json', 'search-plan.json',
            'materiality-annotations.json', 'source-capabilities.json', 'supplemental-evidence.json',
            'browser-candidate-journal.json', 'browser-execution-status.json', 'first-review.json', 'second-review.json', 'adjudication.json')}


def _route(error):
    if error.startswith(('REPORT_ARTIFACT_MISMATCH:', 'STAGE_ARTIFACT_MISMATCH:')):
        path = error.split(':', 1)[1].strip()
        if path in RENDERED:
            return {'error': error, 'owner': '10D_local_export', 'file': path, 'effect': 'single_artifact'}
    if error.startswith('REPORT_SOURCE_CHANGED: files/'):
        return {'error': error, 'owner': '10D_material_copy', 'file': error.split(':', 1)[1].strip(), 'effect': 'material_and_references'}
    if error == 'REPORT_MANIFEST_MISMATCH':
        return {'error': error, 'owner': '10D_manifest', 'effect': 'manifest'}
    if 'TASK' in error or 'IDENTITY' in error or 'PRODUCT' in error:
        owner = '02_product_and_scope'
    elif 'REVIEW' in error or 'ASSESSMENT' in error:
        owner = '09_review_and_shared_result'
    else:
        owner = 'original_source_or_shared_result'
    return {'error': error, 'owner': owner, 'effect': 'shared_result_or_dependency', 'file': None}


def inspect(task_dir, output_dir, *, kind=None, first_review=None, second_review=None, adjudication=None,
            validation_context=None):
    source, out = Path(task_dir).resolve(), Path(output_dir).resolve()
    from completion_check import review_paths
    reviews = review_paths(source, first_review, second_review, adjudication)
    def snapshot():
        return _hashes(source) | {key: sha256_file(path) if path.is_file() else None
            for key, path in zip(('actual_first_review', 'actual_second_review', 'actual_adjudication'), reviews)}
    before = snapshot()
    kind = kind or ('stage' if (out / 'stage-result.json').is_file() else 'report')
    model = {}
    try:
        if kind == 'stage':
            from stage_delivery_stage_d import build_model, validate_output, _payloads
            saved = load_json(out / 'stage-result.json')
            model = build_model(source, generated_at=saved['generated_at'])
            errors = validate_output(source, out)
            files = (out / 'stage-manifest.json', out / 'stage-result.json')
            manifest = load_json(files[0])
            files += tuple(out / name for name in _payloads(model))
            version = sha256_json(model)
        elif kind == 'report':
            from completion_check import validate_delivery, review_paths
            from report_package_stage_c import report_files
            from report_estimate import _unique_file_records, _resolve
            model = load_json(out / 'report-data.json')
            task = load_json(out / 'task.json')
            first, second, chief = review_paths(source, first_review, second_review, adjudication)
            errors = source_task_errors(source, task)
            validation_options = {'validation_context': validation_context} if validation_context is not None else {}
            errors += validate_delivery(source, out, first_review=first, second_review=second,
                adjudication=chief if chief.is_file() else None, require_receipt=(out / 'delivery-validation.json').is_file(),
                **validation_options)
            files = tuple(out / name for name in report_files(model))
            files += tuple(_resolve(out, row['path']) for row in _unique_file_records(
                model['visual_evidence'] + model['evidence_index'] + model['linked_files']))
            version = sha256_json(model)
        else:
            raise ValueError('DELIVERY_INSPECTION_TYPE_INVALID')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors = ['DELIVERY_INSPECTION_READ_ERROR:' + type(exc).__name__]
        files, version = (), None
    if before != snapshot():
        errors.append('DELIVERY_INSPECTION_SOURCE_CHANGED_DURING_CHECK')
    files += tuple(out / name for name in ('task.json', 'assessment.json', 'delivery-validation.json', 'stage-validation.json') if (out / name).is_file())
    errors = list(dict.fromkeys(errors))
    routes = [_route(error) for error in errors]
    if not isinstance(model, dict):
        model = {}
    presentation = model.get('presentation_stage_a', {})
    stage = model if kind == 'stage' else presentation.get('stage', {}) if isinstance(presentation, dict) else {}
    if not isinstance(stage, dict):
        stage = {}
    risk = stage.get('stage_risk', {})
    if not isinstance(risk, dict):
        risk = {}
    local_only = bool(errors) and all(row['owner'] in {'10D_local_export', '10D_material_copy', '10D_manifest'} for row in routes)
    transaction = {'validation_transaction': validation_context.audit()} if validation_context is not None and not errors else {}
    return {'schema': 'IPR-DELIVERY-INSPECTION/1.0', 'revision': REVISION, 'checked_at': now_iso(),
        'task_id': model.get('task_id'), 'delivery_type': kind,
        'result_version_sha256': version, 'source_hashes': before,
        'status': 'locally_validated' if not errors else 'blocked', 'errors': errors,
        'checked_files': {str(path.relative_to(out)): sha256_file(path) if path.is_file() else None for path in dict.fromkeys(files)},
        'repair_routes': routes, 'bounded_local_repair_allowed': local_only,
        'repair_files': sorted({row['file'] for row in routes if row.get('file')}) if local_only else [],
        'quarantined_judgments': deepcopy(stage.get('quarantined_judgments', [])),
        'independent_valid_judgments': [row['event_id'] for row in risk.get('judgments', []) if row.get('applicability') == 'current'],
        'overall_applicability': risk.get('overall', {}).get('applicability'),
        'business_status': model.get('business_status_stage_b', {}).get('business_status'),
        'actual_delivery': 'not_claimed', 'automatic_investigation_resume': False, **transaction}


def repair(task_dir, output_dir, new_output_dir, **options):
    """Restore only proved output defects into a NEW local bundle; reuse existing work."""
    source, old, new = Path(task_dir).resolve(), Path(output_dir).resolve(), Path(new_output_dir).resolve()
    if new.exists() or new == source or old == new or old in new.parents:
        raise ValueError('DELIVERY_REPAIR_NEW_DIRECTORY_REQUIRED')
    record = inspect(source, old, **options)
    if not record['bounded_local_repair_allowed']:
        raise ValueError('DELIVERY_REPAIR_UPSTREAM_REQUIRED')
    from report_estimate import _resolve
    new.mkdir(parents=True)
    for name in dict.fromkeys([*record['checked_files'], 'task.json', 'assessment.json',
            'delivery-validation.json', 'stage-validation.json']):
        path = _resolve(old, name)
        if path.is_file():
            payload = path.read_bytes()
            if name in record['checked_files'] and sha256_file(path) != record['checked_files'][name]:
                raise ValueError('DELIVERY_REPAIR_OUTPUT_CHANGED_DURING_COPY')
            atomic_write_bytes(_resolve(new, name), payload)
    if record['delivery_type'] == 'report':
        from report_estimate import bundle_bytes, _manifest, _unique_file_records
        data = load_json(old / 'report-data.json')
        payloads = bundle_bytes(data, new)
        for name in record['repair_files']:
            if name in payloads:
                atomic_write_bytes(new / name, payloads[name])
            else:
                item = next(row for row in _unique_file_records(data['visual_evidence'] + data['evidence_index'] + data['linked_files']) if row['path'] == name)
                payload = Path(item['source_path']).read_bytes()
                if sha256_file(Path(item['source_path'])) != item['sha256']:
                    raise ValueError('DELIVERY_REPAIR_SOURCE_MATERIAL_CHANGED')
                atomic_write_bytes(new / name, payload)
        atomic_write_json(new / 'report-manifest.json', _manifest(data, payloads))
        receipt = new / 'delivery-validation.json'
        if receipt.is_file():
            value = load_json(receipt)
            value.update(manifest_sha256=sha256_file(new / 'report-manifest.json'), validated_at=now_iso())
            atomic_write_json(receipt, value)
    else:
        from stage_delivery_stage_d import _payloads, build_model
        saved = load_json(old / 'stage-result.json')
        data = build_model(source, generated_at=saved['generated_at'])
        payloads = _payloads(data)
        for name in record['repair_files']:
            atomic_write_bytes(new / name, payloads[name])
        manifest = load_json(old / 'stage-manifest.json')
        manifest['artifacts'] = {name: {'bytes': len(payload), 'sha256': sha256_file(new / name)} for name, payload in payloads.items()}
        atomic_write_json(new / 'stage-manifest.json', manifest)
        receipt = new / 'stage-validation.json'
        if receipt.is_file():
            value = load_json(receipt)
            value.update(manifest_sha256=sha256_file(new / 'stage-manifest.json'), validated_at=now_iso())
            atomic_write_json(receipt, value)
    verified = inspect(source, new, **options)
    if verified['errors'] or record['source_hashes'] != verified['source_hashes']:
        raise ValueError('DELIVERY_REPAIR_REVALIDATION_FAILED')
    verified['repair_of'] = {'output_dir': str(old), 'result_version_sha256': record['result_version_sha256'],
        'files': record['repair_files'], 'input_inspection_sha256': sha256_json(record)}
    atomic_write_json(new / 'delivery-inspection.json', verified)
    return verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--kind', choices=('report', 'stage'))
    parser.add_argument('--record', type=Path)
    parser.add_argument('--repair-to', type=Path)
    for name in ('first-review', 'second-review', 'adjudication'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    options = dict(kind=args.kind, first_review=args.first_review, second_review=args.second_review, adjudication=args.adjudication)
    record = repair(args.task_dir, args.output_dir, args.repair_to, **options) if args.repair_to else inspect(args.task_dir, args.output_dir, **options)
    if args.record:
        if args.record.exists():
            raise ValueError('DELIVERY_INSPECTION_NEW_RECORD_REQUIRED')
        atomic_write_json(args.record, record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if record['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

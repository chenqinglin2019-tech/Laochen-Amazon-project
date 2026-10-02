"""10E: frozen builds, verified local entries, retry and historical correction links.

No hosting, network, monitoring, investigation or automatic pause resume.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import uuid
from common import atomic_write_bytes, atomic_write_json, load_json, now_iso, sha256_file, sha256_json
from execution_lock import execution_lock
from delivery_inspection_stage_d import inspect, task_binding

REVISION = 'delivery-versions-stage-e-v1'
JOURNAL = 'delivery-versions.json'
INPUTS = ('task.json', 'evidence.json', 'search-plan.json', 'normalized-candidates.json',
    'materiality-annotations.json', 'supplemental-evidence.json', 'source-capabilities.json',
    'browser-execution-status.json', 'browser-candidate-journal.json')


def enabled(task):
    value = task.get('delivery_versions_revision')
    if value is None:
        return False
    if value != REVISION:
        raise ValueError('DELIVERY_VERSIONS_REVISION_INVALID')
    return True


def _read(source):
    task = load_json(source / 'task.json')
    if not enabled(task):
        raise ValueError('DELIVERY_VERSIONS_NEW_TASK_REQUIRED')
    value = load_json(source / JOURNAL) if (source / JOURNAL).is_file() else {
        'schema': 'IPR-DELIVERY-VERSIONS/1.0', 'task_id': task['task_id'], 'versions': [], 'corrections': []}
    if value.get('schema') != 'IPR-DELIVERY-VERSIONS/1.0' or value.get('task_id') != task['task_id']:
        raise ValueError('DELIVERY_VERSIONS_TASK_MISMATCH')
    return value


def _version(journal, version_id):
    return next(row for row in journal['versions'] if row['version_id'] == version_id)


def _retained_files(source, values):
    """Bind bytes of declared retained material and actual host audit logs."""
    paths = set()
    file_keys = {'path', 'local_path', 'source_path', 'file_path', 'source_document',
        'audit_log_path', 'raw_path', 'raw_paths', 'source_document_source_path'}
    def walk(value):
        if isinstance(value, list):
            for item in value: walk(item)
        elif isinstance(value, dict):
            bound = any(key.endswith('sha256') or key in {'sha256', 'payload_digest'} for key in value)
            for key, child in value.items():
                if bound and key in file_keys:
                    for name in child if isinstance(child, list) else [child]:
                        if isinstance(name, str) and name and '://' not in name:
                            path = Path(name).expanduser()
                            paths.add((path if path.is_absolute() else source / path).resolve())
                walk(child)
    walk(list(values.values()))
    return {str(path): sha256_file(path) if path.is_file() else None for path in sorted(paths)}


def _snapshot(source, reviews):
    values = {name: load_json(source / name) if (source / name).is_file() else None for name in INPUTS}
    task = values['task.json']
    values['task.json'] = task_binding(task) | {key: task.get(key) for key in
        ('assessment_policy', 'assessment_revision', 'presentation_policy_revision', 'final_review_execution_revision')}
    for name, path in reviews.items():
        values[name] = load_json(Path(path)) if path and Path(path).is_file() else None
    values['retained_files'] = _retained_files(source, values)
    return values


def _model(build, kind):
    return load_json(build / ('stage-result.json' if kind == 'stage' else 'report-data.json'))


def _stage(model, kind):
    return model if kind == 'stage' else model.get('presentation_stage_a', {}).get('stage', {})


def _risk_signature(stage):
    risk = stage.get('stage_risk', {})
    return {'identity_errors': stage.get('identity_errors', []), 'product': stage.get('product'),
        'judgments': risk.get('judgments', []), 'signals': risk.get('signals', []),
        'overall': risk.get('overall'), 'review_label': stage.get('review_label'),
        'quarantined_judgments': stage.get('quarantined_judgments', [])}


def begin_build(task_dir, build_dir, *, kind='report', first_review=None, second_review=None,
                adjudication=None, correction_id=None):
    source, build = Path(task_dir).resolve(), Path(build_dir).resolve()
    if kind not in {'report', 'stage'} or source == build or build.exists():
        raise ValueError('DELIVERY_BUILD_NEW_DIRECTORY_REQUIRED')
    reviews = {name: str(Path(path).resolve()) if path else str(source / default)
        for name, path, default in (('first_review', first_review, 'first-review.json'),
            ('second_review', second_review, 'second-review.json'), ('adjudication', adjudication, 'adjudication.json'))}
    with execution_lock(source, 'delivery'):
        journal = _read(source)
        correction = next((row for row in journal['corrections'] if row['correction_id'] == correction_id), None)
        if correction_id and correction is None:
            raise ValueError('DELIVERY_CORRECTION_UNKNOWN')
        row = {'version_id': 'DV-' + uuid.uuid4().hex, 'task_id': journal['task_id'],
            'delivery_type': kind, 'created_at': now_iso(), 'build_dir': str(build),
            'snapshot': _snapshot(source, reviews), 'review_paths': reviews,
            'state': 'building', 'actual_entry': None, 'attempts': [], 'correction_id': correction_id,
            'previous_version_id': correction['previous_version_id'] if correction else None}
        row['snapshot_sha256'] = sha256_json(row['snapshot'])
        journal['versions'].append(row)
        atomic_write_json(source / JOURNAL, journal)
    return row['version_id']


def fail_build(task_dir, version_id, error):
    source = Path(task_dir).resolve()
    with execution_lock(source, 'delivery'):
        journal = _read(source); row = _version(journal, version_id)
        row.update(state='build_failed', failed_step='build_or_validation', failure=type(error).__name__ + ':' + str(error).split(':')[0])
        atomic_write_json(source / JOURNAL, journal)


def _options(row):
    return {name: path for name, path in row['review_paths'].items()}


def finish_build(task_dir, version_id, *, validation_context=None):
    source = Path(task_dir).resolve()
    with execution_lock(source, 'delivery'):
        journal = _read(source); row = _version(journal, version_id); build = Path(row['build_dir'])
        if row['state'] not in {'building', 'build_failed'}:
            raise ValueError('DELIVERY_BUILD_STATE_INVALID')
        if _snapshot(source, row['review_paths']) != row['snapshot']:
            raise ValueError('DELIVERY_BUILD_INPUTS_CHANGED')
        validation_options = {'validation_context': validation_context} if validation_context is not None else {}
        inspection = inspect(source, build, kind=row['delivery_type'], **_options(row), **validation_options)
        if inspection['errors']:
            raise ValueError('DELIVERY_BUILD_INSPECTION_FAILED')
        model = _model(build, row['delivery_type'])
        files = inspection['checked_files']
        if (build / 'delivery-inspection.json').is_file():
            files['delivery-inspection.json'] = sha256_file(build / 'delivery-inspection.json')
        row.update(state='build_verified', model_sha256=sha256_json(model), files=files,
            stage=deepcopy(_stage(model, row['delivery_type'])), verified_at=now_iso(),
            source_snapshot_sha256=row['snapshot_sha256'],
            business_status=model.get('business_status_stage_b', {}).get('business_status', 'not_claimed'))
        if row['correction_id']:
            correction = next(r for r in journal['corrections'] if r['correction_id'] == row['correction_id'])
            previous = _version(journal, row['previous_version_id'])
            if correction['kind'] == 'display' and (row['model_sha256'] != previous['model_sha256'] or row['snapshot'] != previous['snapshot']):
                raise ValueError('DELIVERY_DISPLAY_CORRECTION_CHANGED_SUBSTANCE')
        if _snapshot(source, row['review_paths']) != row['snapshot']:
            raise ValueError('DELIVERY_BUILD_INPUTS_CHANGED')
        atomic_write_json(source / JOURNAL, journal)
    return {'version_id': version_id, 'delivery_status': 'not_delivered', 'build_status': 'verified', 'actual_entry': None}


def _changes(source, row):
    current = _snapshot(source, row['review_paths'])
    changed = [name for name in current if current[name] != row['snapshot'].get(name)]
    result = {'applicable': not changed, 'change_type': 'unchanged', 'changed_inputs': changed,
        'automatic_investigation_resume': False, 'monitoring_started': False}
    if not changed:
        return result
    # Only proved append-only completion events can be progress-only. Added facts,
    # runs, changed plans, scopes, candidates or reviews are never guessed harmless.
    before = row['snapshot'].get('evidence.json') or {}
    after = current.get('evidence.json') or {}
    old_events, new_events = before.get('review_progress_events', []), after.get('review_progress_events', [])
    reduced = lambda value: {k: v for k, v in value.items() if k != 'review_progress_events'}
    control_old, control_new = before.get('continuation_events', []), after.get('continuation_events', [])
    control_only = changed == ['evidence.json'] and (
        {k: v for k, v in before.items() if k != 'continuation_events'} ==
        {k: v for k, v in after.items() if k != 'continuation_events'}) and (
        isinstance(control_old, list) and isinstance(control_new, list) and len(control_new) > len(control_old)
        and control_new[:len(control_old)] == control_old and all(e.get('kind') == 'pause' for e in control_new[len(control_old):]))
    progress_only = changed == ['evidence.json'] and reduced(before) == reduced(after) and (
        isinstance(old_events, list) and isinstance(new_events, list) and len(new_events) > len(old_events)
        and new_events[:len(old_events)] == old_events and all(event.get('kind') == 'complete' for event in new_events[len(old_events):]))
    from stage_delivery_stage_d import build_model
    # Re-evaluate actual inputs at this version's fixed presentation cutoff.
    # The clock passing between copy and entry checks is not a new fact.
    cutoff = (row.get('stage') or {}).get('generated_at') or row.get('created_at')
    stage = build_model(source, generated_at=cutoff)
    result.update(current_stage=stage, change_type='substantive_or_unproven', applicable=False,
        repair_owner='original_scope_evidence_or_review_chain')
    if (progress_only or control_only) and row.get('stage') and _risk_signature(stage) == _risk_signature(row['stage']) and not stage['identity_errors']:
        result.update(applicable=True, change_type='progress_only' if progress_only else 'pause_only', repair_owner=None,
            frozen_progress_cutoff=row['stage'].get('progress_cutoff'),
            current_progress=stage['progress'], grade_cutoff=row['stage'].get('grade_cutoff'),
            active_pauses=stage.get('work', {}).get('entries', []),
            disclosure='交付保留原进度／评级截止；较新完成位置未纳入本版评级。' if progress_only else '调查暂停仍有效；本次仅交接原有效成果，不恢复调查。')
    return result


def _file_errors(directory, files):
    from report_estimate import _resolve
    errors = []
    for name, digest in files.items():
        path = _resolve(directory, name)
        if not path.is_file() or sha256_file(path) != digest:
            errors.append('DELIVERY_ACTUAL_FILE_MISSING_OR_CHANGED:' + name)
    # Report links must resolve locally. Retained originals in files/ keep their
    # source-site links unchanged; their bytes are still checked above.
    for name in files:
        if name.endswith('.html') and not name.startswith('files/') and (directory / name).is_file():
            html = (directory / name).read_text()
            from urllib.parse import unquote, urlsplit
            for link in re.findall(r'(?:href|src)=["\']([^"\']+)["\']', html):
                parsed = urlsplit(link)
                if parsed.scheme or parsed.netloc:
                    continue  # Offline retained material does not require a live site refresh.
                try:
                    target = _resolve(directory, unquote(parsed.path)) if parsed.path else directory / name
                except ValueError:
                    errors.append('DELIVERY_LOCAL_REFERENCE_OUTSIDE_ROOT:' + link)
                    continue
                if not target.is_file():
                    errors.append('DELIVERY_LOCAL_REFERENCE_UNAVAILABLE:' + link)
                elif parsed.fragment and target.suffix == '.json':
                    try:
                        fragment = unquote(parsed.fragment)
                        if not fragment.startswith('/'):
                            raise ValueError('JSON_POINTER_REQUIRED')
                        value = load_json(target)
                        for token in fragment[1:].split('/'):
                            token = token.replace('~1', '/').replace('~0', '~')
                            value = value[int(token)] if isinstance(value, list) else value[token]
                    except (OSError, ValueError, TypeError, KeyError, IndexError):
                        errors.append('DELIVERY_JSON_REFERENCE_UNAVAILABLE:' + link)
                elif parsed.fragment and target.suffix in {'.html', '.htm'}:
                    fragment = unquote(parsed.fragment)
                    if not re.search(r'(?:id|name)=["\']' + re.escape(fragment) + r'["\']', target.read_text()):
                        errors.append('DELIVERY_LOCAL_ANCHOR_UNAVAILABLE:' + link)
    return errors


def _copy_files(build, destination, files):
    from report_estimate import _resolve
    for name, digest in files.items():
        src = _resolve(build, name); payload = src.read_bytes()
        if sha256_file(src) != digest:
            raise ValueError('DELIVERY_BUILD_BYTES_CHANGED')
        atomic_write_bytes(_resolve(destination, name), payload)


def deliver(task_dir, version_id, destination, *, validation_context=None):
    """Explicit local entry only: copy frozen bytes, independently re-read destination."""
    source, target = Path(task_dir).resolve(), Path(destination).resolve()
    with execution_lock(source, 'delivery'):
        journal = _read(source); row = _version(journal, version_id); build = Path(row['build_dir'])
        if row['state'] not in {'build_verified', 'delivery_failed'}:
            raise ValueError('DELIVERY_RETRY_STATE_INVALID')
        if target.exists() or source == target or build == target or build in target.parents:
            raise ValueError('DELIVERY_NEW_ENTRY_DIRECTORY_REQUIRED')
        attempt = {'attempt_id': uuid.uuid4().hex, 'started_at': now_iso(), 'destination': str(target), 'step': 'snapshot_check'}
        row['attempts'].append(attempt)
        created = False
        try:
            validation_options = {'validation_context': validation_context} if validation_context is not None else {}
            changes = _changes(source, row)
            attempt['known_changes'] = changes
            if not changes['applicable']:
                raise ValueError('DELIVERY_SNAPSHOT_NO_LONGER_APPLICABLE')
            attempt['step'] = 'build_recheck'
            errors = _file_errors(build, row['files'])
            if errors:
                raise ValueError(errors[0])
            if changes['change_type'] == 'unchanged':
                errors = inspect(source, build, kind=row['delivery_type'], **_options(row), **validation_options)['errors']
                if errors:
                    raise ValueError('DELIVERY_BUILD_RECHECK_FAILED')
            attempt['step'] = 'copy'
            target.mkdir(parents=True, exist_ok=False)
            created = True
            from runtime_timing import timed_step
            timing_source = source if row['snapshot']['task.json'].get('presentation_policy_revision') == 'operator-report-v1' else None
            with timed_step(timing_source, 'delivery_copy'):
                _copy_files(build, target, row['files'])
            attempt['step'] = 'entry_recheck'
            with timed_step(timing_source, 'actual_entry_check'):
                errors = _file_errors(target, row['files'])
                if errors:
                    raise ValueError(errors[0])
                if changes['change_type'] == 'unchanged' and inspect(source, target, kind=row['delivery_type'], **_options(row), **validation_options)['errors']:
                    raise ValueError('DELIVERY_ACTUAL_ENTRY_INSPECTION_FAILED')
            after = _changes(source, row)
            if not after['applicable'] or after.get('current_stage') != changes.get('current_stage'):
                raise ValueError('DELIVERY_CHANGED_DURING_ENTRY_CHECK')
            carrier = next(name for name in ('report.html', 'stage-result.html', 'stage-result.txt', 'stage-result.md', 'stage-result.csv') if name in row['files'])
            # Mutable status lives OUTSIDE accepted files. Never patch a published report.
            row.update(state='delivered', actual_entry=str(target / carrier), delivered_dir=str(target), delivered_at=now_iso())
            attempt.update(step='entry_verified', status='passed', finished_at=now_iso())
            if row['correction_id']:
                correction = next(r for r in journal['corrections'] if r['correction_id'] == row['correction_id'])
                previous = _version(journal, row['previous_version_id'])
                affected = correction.get('affected_judgment_ids', [])
                new_judgments = row['stage'].get('stage_risk', {}).get('judgments', [])
                old_judgments = previous['stage'].get('stage_risk', {}).get('judgments', [])
                affected_scopes = [j['scope'] for j in old_judgments if j['event_id'] in affected]
                replacement = correction['kind'] == 'display' or (not row['stage'].get('identity_errors') and bool(affected_scopes) and all(any(
                    {k: v for k, v in j.get('scope', {}).items() if k != 'product_version'} ==
                    {k: v for k, v in scope.items() if k != 'product_version'} and j.get('applicability') == 'current' and j.get('review_status') == 'chief_reviewed'
                    for j in new_judgments) for scope in affected_scopes))
                correction.update(new_version_id=version_id, status='replaced' if replacement else 'interim_stage_delivered')
                previous['replacement_version_id'] = version_id if replacement else None
            atomic_write_json(source / JOURNAL, journal)
            return {'status': 'delivered', 'delivery_status': 'entry_verified', 'version_id': version_id,
                'entry': row['actual_entry'], 'delivery_type': row['delivery_type'], 'known_changes': changes,
                'correction': correction if row['correction_id'] else None,
                'frozen_business_status': row.get('business_status'), 'business_completion': 'not_claimed', 'downloaded_old_copies_updated': False, 'automatic_investigation_resume': False}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            if created and target.is_dir():
                quarantine = target.parent / ('.failed-delivery-' + attempt['attempt_id'])
                try:
                    target.rename(quarantine)
                    attempt['quarantined_dir'] = str(quarantine)
                except OSError:
                    attempt['quarantine_failed'] = True
            row.update(state='delivery_failed', actual_entry=None)
            attempt.update(status='failed', finished_at=now_iso(), error=type(exc).__name__ + ':' + str(exc).split(':')[0])
            atomic_write_json(source / JOURNAL, journal)
            return {'status': 'delivery_failed', 'delivery_status': 'failed', 'version_id': version_id,
                'entry': None, 'failed_step': attempt['step'], 'error': attempt['error'],
                'frozen_business_status': row.get('business_status'), 'business_recheck_required': attempt['step'] == 'snapshot_check',
                'automatic_investigation_resume': False}


def record_correction(task_dir, previous_version_id, request):
    source = Path(task_dir).resolve()
    with execution_lock(source, 'delivery'):
        journal = _read(source); old = _version(journal, previous_version_id)
        if old['state'] != 'delivered' or request.get('kind') not in {'display', 'material'} or (
            not isinstance(request.get('reason'), str) or not request['reason'].strip() or
            not isinstance(request.get('changes'), list) or not request['changes'] or
            any(not isinstance(text, str) or not text.strip() for text in request['changes'])):
            raise ValueError('DELIVERY_CORRECTION_DETAILS_REQUIRED')
        row = {key: deepcopy(request.get(key)) for key in ('kind', 'reason', 'changes', 'affected_judgment_ids', 'upstream_refs')}
        row.update(correction_id='DC-' + uuid.uuid4().hex, previous_version_id=previous_version_id,
            previous_entry=old['actual_entry'], affected_scopes=[], judgment_impact='事实、引用对象、范围与等级未变；复用有效审阅。',
            recorded_at=now_iso(), status='pending', downloaded_old_copies_updated=False,
            continuation_owner='08C_original_task_reconciliation', automatic_investigation_resume=False)
        if row['kind'] == 'material':
            refs, ids = row.get('upstream_refs'), row.get('affected_judgment_ids')
            if not isinstance(refs, list) or not refs or not isinstance(ids, list) or not ids:
                raise ValueError('DELIVERY_MATERIAL_UPSTREAM_REQUIRED')
            task = load_json(source / 'task.json'); evidence = load_json(source / 'evidence.json')
            from stage_risk_stage_b import _upstream_exists, snapshot
            snapshot(task, evidence, task_dir=source)  # Validate the original 09 event chain; do not create a second judgment ledger.
            old_ids = {j['event_id'] for j in old.get('stage', {}).get('stage_risk', {}).get('judgments', [])}
            if not set(ids) <= old_ids or not all(_upstream_exists(task, evidence, ref) for ref in refs):
                raise ValueError('DELIVERY_MATERIAL_UPSTREAM_UNKNOWN')
            invalidations = {e.get('judgment_id'): e for e in evidence.get('stage_risk_events', []) if e.get('kind') == 'invalidate'}
            if any(jid not in invalidations or invalidations[jid]['upstream_ref'] not in refs for jid in ids):
                raise ValueError('DELIVERY_ORIGINAL_JUDGMENT_INVALIDATION_REQUIRED')
            row['affected_scopes'] = [deepcopy(j['scope']) for j in old['stage']['stage_risk']['judgments'] if j['event_id'] in ids]
            row['judgment_impact'] = [{'judgment_id': jid, 'impact': invalidations[jid]['impact'],
                'recovery_action': invalidations[jid]['recovery_action']} for jid in ids]
        journal['corrections'].append(row)
        atomic_write_json(source / JOURNAL, journal)
        return row


def status(task_dir):
    """Read current known applicability without changing old files or restoring pauses."""
    source = Path(task_dir).resolve(); journal = _read(source)
    rows = []
    for row in journal['versions']:
        item = {key: row.get(key) for key in ('version_id', 'state', 'actual_entry', 'previous_version_id', 'replacement_version_id', 'correction_id')}
        if row.get('files'):
            try:
                changes = _changes(source, row)
            except (OSError, ValueError, TypeError, KeyError):
                changes = {'applicable': False, 'change_type': 'source_integrity_unavailable',
                    'repair_owner': 'original_source_or_review_chain'}
            correction = next((r for r in journal['corrections'] if r['previous_version_id'] == row['version_id'] and r['kind'] == 'material'), None)
            item.update(applicability='pending_recheck' if not changes['applicable'] or correction else 'current',
                known_changes=changes, affected_judgment_ids=correction.get('affected_judgment_ids', []) if correction else [])
            if row.get('replacement_version_id'):
                item['applicability'] = 'superseded'
            try:
                entry_failed = row['state'] == 'delivered' and bool(_file_errors(Path(row['delivered_dir']), row['files']))
            except (OSError, ValueError, TypeError, KeyError):
                entry_failed = True
            if entry_failed:
                item.update(entry_status='unavailable_or_changed', accessible_entry=None)
            else:
                item.update(entry_status='verified_at_recorded_time' if row['state'] == 'delivered' else 'not_delivered', accessible_entry=row.get('actual_entry'))
        rows.append(item)
    return {'task_id': journal['task_id'], 'versions': rows, 'corrections': journal['corrections'],
        'automatic_investigation_resume': False, 'monitoring_started': False, 'downloaded_old_copies_updated': False}


def entry_errors(task_dir, output_dir):
    source, out = Path(task_dir).resolve(), Path(output_dir).resolve()
    try:
        journal = _read(source)
        row = next((r for r in reversed(journal['versions']) if r.get('delivered_dir') == str(out) and r['state'] == 'delivered'), None)
        if not row:
            return ['DELIVERY_ACTUAL_ENTRY_NOT_VERIFIED']
        current = next(r for r in status(source)['versions'] if r['version_id'] == row['version_id'])
        if current['applicability'] not in {'current'}:
            return ['DELIVERY_ENTRY_KNOWN_INVALID_OR_SUPERSEDED']
        return _file_errors(out, row['files'])
    except (OSError, ValueError, TypeError, KeyError, StopIteration):
        return ['DELIVERY_ENTRY_CHECK_FAILED']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task-dir', type=Path, required=True)
    p.add_argument('--action', choices=('deliver', 'status', 'adopt', 'correction', 'retry-build'), required=True)
    p.add_argument('--version-id'); p.add_argument('--destination', type=Path)
    p.add_argument('--build-dir', type=Path); p.add_argument('--kind', choices=('report', 'stage'), default='report')
    p.add_argument('--correction-id'); p.add_argument('--input', type=Path)
    for name in ('first-review', 'second-review', 'adjudication'): p.add_argument('--' + name, type=Path)
    args = p.parse_args()
    required = {'deliver': ('version_id', 'destination'), 'adopt': ('build_dir',),
        'correction': ('version_id', 'input'), 'retry-build': ('version_id',)}
    if any(getattr(args, key) is None for key in required.get(args.action, ())):
        p.error('Missing action-specific arguments: ' + ', '.join(required[args.action]))
    if args.action == 'status': result = status(args.task_dir)
    elif args.action == 'retry-build':
        try:
            result = finish_build(args.task_dir, args.version_id)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            fail_build(args.task_dir, args.version_id, exc)
            raise
    elif args.action == 'deliver':
        result = deliver(args.task_dir, args.version_id, args.destination)
        if result.get('delivery_status') == 'entry_verified':
            # Keep the Stop hook on the verified entry and its own review files.
            from codex_guard import update_bound_paths
            bound = _version(_read(args.task_dir.resolve()), args.version_id).get('review_paths') or {}
            update_bound_paths(args.task_dir.resolve(), output_dir=args.destination,
                **{key: bound[key] for key in ('first_review', 'second_review', 'adjudication') if bound.get(key)})
    elif args.action == 'correction': result = record_correction(args.task_dir, args.version_id, load_json(args.input))
    else:
        # Adopt a repaired valid bundle without rerunning investigation/review or overwriting it.
        source = args.task_dir.resolve(); build = args.build_dir.resolve()
        if source == build or not build.is_dir(): raise ValueError('DELIVERY_ADOPT_BUILD_REQUIRED')
        with execution_lock(source, 'delivery'):
            journal = _read(source)
            correction = next((r for r in journal['corrections'] if r['correction_id'] == args.correction_id), None)
            if args.correction_id and correction is None: raise ValueError('DELIVERY_CORRECTION_UNKNOWN')
            from completion_check import review_paths
            paths = review_paths(source, args.first_review, args.second_review, args.adjudication)
            reviews = dict(zip(('first_review', 'second_review', 'adjudication'), map(str, paths)))
            row = {'version_id': 'DV-' + uuid.uuid4().hex, 'task_id': journal['task_id'], 'created_at': now_iso(),
                'build_dir': str(build), 'delivery_type': args.kind, 'review_paths': reviews, 'snapshot': _snapshot(source, reviews),
                'state': 'building', 'attempts': [], 'actual_entry': None, 'correction_id': args.correction_id,
                'previous_version_id': correction['previous_version_id'] if correction else None}
            row['snapshot_sha256'] = sha256_json(row['snapshot']); journal['versions'].append(row)
            atomic_write_json(source / JOURNAL, journal)
        try:
            result = finish_build(source, row['version_id'])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            fail_build(source, row['version_id'], exc)
            raise
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get('status') == 'delivery_failed': raise SystemExit(1)


if __name__ == '__main__': main()

"""Same unchanged candidate question cannot acquire another attempt by renaming IDs."""
from copy import deepcopy
import re
from common import sha256_json
from execution_efficiency import enabled


def identity(annotation, action, *, content_sha256=None, request_params=None):
    basis = action.get('followup_basis') or {}
    # References are an unordered set. Recompute historical actions in this
    # form too; their original events/signatures are never rewritten. Request
    # parameter lists below remain ordered because order may change the call.
    evidence_refs = basis.get('existing_evidence_refs', [])
    if not isinstance(evidence_refs, list) or any(not isinstance(ref, str) for ref in evidence_refs):
        raise ValueError('FOLLOWUP_IDENTITY_EVIDENCE_REFS_INVALID')
    return sha256_json({'scope': {k: annotation.get(k) for k in
        ('candidate_id', 'scenario_id', 'jurisdiction', 'right_type', 'candidate_content_sha256', 'product_identity_sha256')},
        'missing_fact': ' '.join(str(basis.get('missing_fact') or '').casefold().split()),
        'kind': action.get('kind'), 'provider': action.get('provider'), 'operation': action.get('operation'),
        'params': action.get('params') if request_params is None else request_params,
        'evidence': content_sha256 if content_sha256 is not None else sorted(set(evidence_refs))})


def renamed_attempt(task, plan, evidence, ledger, provider, row, annotation, action, *, candidate=None, supplement=None):
    if not enabled(task) or not (action.get('followup_basis') or {}).get('missing_fact'):
        return None
    from execution_efficiency import revised
    if revised(task):
        return _content_attempt(task, plan, evidence, ledger, provider, row, annotation, action,
                                candidate=candidate, supplement=supplement)
    current = identity(annotation, action)
    old_pairs = {(old.get('annotation_id'), previous.get('action_id'))
        for old in ledger.get('annotations', []) for previous in old.get('next_actions', [])
        if identity(old, previous) == current}
    old_rows = [r for r in plan.get('queries', {}).get(provider, [])
                if r.get('query_id') != row.get('query_id')
                and (r.get('triage_decision_id'), r.get('triage_action_id')) in old_pairs]
    for old in old_rows:
        for run in reversed(evidence.get('source_runs', [])):
            if (run.get('provider') == provider and run.get('query_id') == old.get('query_id')
                    and run.get('plan_entry_sha256') == sha256_json(old)
                    and run.get('submission_state') in {'submitted', 'unknown'}):
                return {'reason': 'TRIAGE_ATTEMPT_STATE_UNKNOWN' if run.get('submission_state') == 'unknown'
                        else 'TRIAGE_REVIEW_REQUIRED' if run.get('status') in {'success', 'no_result'}
                        else 'TRIAGE_BOUNDED_ACTION_ALREADY_ATTEMPTED',
                        'original_query_id': old['query_id'], 'source_run_id': run['run_id']}
    return None


CONTENT_FIELD = 'existing_evidence_content_sha256'


def bind_action_contents(task, annotation, candidate, evidence, supplement=None):
    """Only the recorder derives a new action's immutable factual basis."""
    from execution_efficiency import revised
    if not revised(task) or annotation.get('decision') != 'needs_info':
        return annotation
    from decision_workflow import basis_evidence_sha256
    result = deepcopy(annotation)
    for action in result.get('next_actions', []):
        basis = action.get('followup_basis')
        if not isinstance(basis, dict):
            continue  # Existing validators explain an incomplete action.
        refs = basis.get('existing_evidence_refs')
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError('FOLLOWUP_IDENTITY_EVIDENCE_REFS_INVALID')
        digest = basis_evidence_sha256(sorted(set(refs)), evidence, supplement, candidate=candidate, task=task)
        if CONTENT_FIELD in basis and basis[CONTENT_FIELD] != digest:
            raise ValueError('FOLLOWUP_IDENTITY_CONTENT_MISMATCH')
        basis[CONTENT_FIELD] = digest
    return result


def _content_digest(task, annotation, action, evidence, supplement, candidate, *, current=False):
    from decision_workflow import basis_evidence_sha256
    basis = action.get('followup_basis') or {}
    refs = basis.get('existing_evidence_refs', [])
    stored = basis.get(CONTENT_FIELD)
    if stored is not None and not re.fullmatch(r'[0-9a-f]{64}', str(stored)):
        raise ValueError('FOLLOWUP_IDENTITY_CONTENT_INVALID')
    if stored is not None and not current:
        return stored  # Protected by the immutable annotation, never rebind old content.
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        raise ValueError('FOLLOWUP_IDENTITY_EVIDENCE_REFS_INVALID')
    actual = basis_evidence_sha256(sorted(set(refs)), evidence, supplement, candidate=candidate, task=task)
    if stored is not None:
        if actual != stored:
            raise ValueError('FOLLOWUP_IDENTITY_CONTENT_MISMATCH')
        return stored
    # Compatibility: only reconstruct an unsigned action subset while the
    # original full annotation still names exactly the same retained facts.
    if basis_evidence_sha256(annotation.get('evidence_refs', []), evidence, supplement,
            candidate=candidate, task=task) != annotation.get('basis_sha256'):
        raise ValueError('FOLLOWUP_IDENTITY_HISTORY_REVIEW_REQUIRED')
    return actual


def _request_params(row):
    from provider_utils import PLAN_META_KEYS
    return {key: value for key, value in row.items() if key not in PLAN_META_KEYS}


def _request_identity(provider, row):
    return sha256_json({'provider': provider, 'operation': row.get('operation'),
        'jurisdiction': row.get('jurisdiction'), 'params': _request_params(row)})


def _content_attempt(task, plan, evidence, ledger, provider, row, annotation, action, *, candidate, supplement):
    from recovery_stage_b import effective_submission, effective_result, recovery_state
    current_request = _request_identity(provider, row)
    current = identity(annotation, action, content_sha256=_content_digest(
        task, annotation, action, evidence, supplement, candidate, current=True), request_params=_request_params(row))
    histories = {(old.get('annotation_id'), previous.get('action_id')): (old, previous)
        for old in ledger.get('annotations', []) for previous in old.get('next_actions', [])
        if previous.get('kind') == 'source_lookup' and previous.get('provider') == provider}
    matches, unknown, pending = [], [], []
    for old_row in plan.get('queries', {}).get(provider, []):
        if old_row.get('query_id') == row.get('query_id'):
            continue
        pair = histories.get((old_row.get('triage_decision_id'), old_row.get('triage_action_id')))
        if pair is None:
            continue
        old, previous = pair
        if _request_identity(provider, old_row) != current_request:
            continue
        runs = [run for run in evidence.get('source_runs', []) if run.get('provider') == provider
            and run.get('query_id') == old_row.get('query_id')
            and run.get('plan_entry_sha256') == sha256_json(old_row)
            and run.get('status') not in {'cancelled', 'not_applicable'}]
        for run in runs:
            if effective_submission(evidence, run) == 'unknown':
                unknown.append((old_row, run))
        state = recovery_state(task, evidence, provider, old_row) if runs else None
        if state and state.get('reason') == 'SOURCE_RESULT_PENDING':
            pending.append((old_row, runs[-1]))
        # Unknown wire submissions cannot be retried even after new facts.
        attempted = [run for run in runs if effective_submission(evidence, run) == 'submitted']
        if not attempted:
            continue
        try:
            digest = _content_digest(task, old, previous, evidence, supplement, candidate)
        except ValueError as exc:
            matches.append((old_row, attempted[-1], str(exc)))
            continue
        if identity(old, previous, content_sha256=digest, request_params=_request_params(old_row)) == current:
            matches.extend((old_row, run, None) for run in attempted)
    if unknown:
        old_row, run = unknown[-1]
        return {'reason': 'TRIAGE_ATTEMPT_STATE_UNKNOWN', 'original_query_id': old_row['query_id'],
                'source_run_id': run['run_id']}
    if pending:
        old_row, run = pending[-1]
        return {'reason': 'SOURCE_RESULT_PENDING', 'original_query_id': old_row['query_id'],
                'source_run_id': run['run_id']}
    if matches:
        old_row, run, error = matches[-1]
        return {'reason': error or ('TRIAGE_REVIEW_REQUIRED' if effective_result(evidence, run) in {'success', 'no_result'}
                                   else 'TRIAGE_BOUNDED_ACTION_ALREADY_ATTEMPTED'),
                'original_query_id': old_row['query_id'], 'source_run_id': run['run_id']}
    return None

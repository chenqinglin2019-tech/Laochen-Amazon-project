"""02C source-bound requests for a minimum product fact and its resolution.

Requests are work in the existing product queue, never a second fact store.
Only a later versioned product scope can satisfy the requested fact.
"""
from __future__ import annotations

from pathlib import Path

from common import load_json, resolve_retained_path, sha256_json

REVISION = 'product-feedback-v1'


def enabled(task):
    value = task.get('product_feedback_revision')
    if value is None: return False
    if value != REVISION: raise ValueError('PRODUCT_FEEDBACK_REVISION_INVALID')
    return True


def history(task):
    if not enabled(task): return []
    rows = task.get('product_feedback_history', [])
    if not isinstance(rows, list): raise ValueError('PRODUCT_FEEDBACK_HISTORY_INVALID')
    return rows


def pending(task):
    rows = history(task)
    resolved = {row['request_id'] for row in rows if row.get('kind') == 'resolved'}
    current = task.get('product_identity',{}).get('sha256')
    return [row for row in rows if row.get('kind') == 'requested'
            and row['request_id'] not in resolved and row.get('target_sha256') == current]


def verify(task, evidence, task_dir):
    rows = history(task)
    if not rows: return
    receipts = evidence.get('collections', {}).get('product_feedback', [])
    if not isinstance(receipts, list) or len(receipts) != len(rows):
        raise ValueError('PRODUCT_FEEDBACK_RECEIPT_MISSING')
    known = {item.get('evidence_id') for group in evidence.get('collections', {}).values()
             if isinstance(group, list) for item in group if isinstance(item, dict)}
    requests, resolved, ids = {}, set(), set()
    for row in rows:
        if not isinstance(row,dict): raise ValueError('PRODUCT_FEEDBACK_EVENT_INVALID')
        eid = row.get('event_id')
        if (not eid or eid in ids
                or row.get('sha256') != sha256_json({k:v for k,v in row.items() if k!='sha256'})
                or not isinstance(row.get('source_refs'), list) or not row['source_refs']
                or not set(row['source_refs']) <= known):
            raise ValueError('PRODUCT_FEEDBACK_EVENT_INVALID')
        ids.add(eid)
        matches = [item for item in receipts if item.get('event_id') == eid]
        if len(matches) != 1 or task_dir is None:
            raise ValueError('PRODUCT_FEEDBACK_RECEIPT_MISSING')
        path = resolve_retained_path(Path(task_dir), matches[0].get('path',''),
                                     expected_sha256=matches[0].get('sha256',''))
        if load_json(path) != row: raise ValueError('PRODUCT_FEEDBACK_RECEIPT_CHANGED')
        if row.get('kind') == 'requested':
            if (row.get('request_id') in requests or not row.get('purpose')
                    or not row.get('minimum_information') or not row.get('question')
                    or not row.get('direction_id') or not row.get('fact_id')):
                raise ValueError('PRODUCT_FEEDBACK_REQUEST_INVALID')
            requests[row['request_id']] = row
        elif row.get('kind') == 'resolved':
            request = requests.get(row.get('request_id'))
            change = next((item for item in task.get('product_change_history',[])
                           if item.get('change_id')==row.get('change_id')), None)
            if (not request or row['request_id'] in resolved
                    or row.get('target_sha256') != request.get('target_sha256')
                    or row.get('scope_sha256') == request.get('scope_sha256')
                    or row.get('fact_version', 0) <= request.get('fact_version', 0)
                    or not change or change.get('target_sha256')!=row.get('target_sha256')
                    or change.get('version',0)<=request.get('product_change_version',1)
                    or not any(item.get('id')==request.get('fact_id')
                               and (item.get('after') or {}).get('version')==row.get('fact_version')
                               for item in change.get('fact_changes',[]))
                    or not row.get('reason')):
                raise ValueError('PRODUCT_FEEDBACK_RESOLUTION_INVALID')
            resolved.add(row['request_id'])
        else:
            raise ValueError('PRODUCT_FEEDBACK_EVENT_INVALID')


def affected_candidate_ids(task):
    return {row['candidate_id'] for row in pending(task) if row.get('candidate_id')}


def assessment_gate(task, assessments):
    affected = affected_candidate_ids(task)
    if any(row.get('candidate_id') in affected and row.get('risk') in {'极低','低','中','高','极高'}
           and not row.get('out_of_scope') for row in assessments):
        raise ValueError('PRODUCT_FEEDBACK_COMPARISON_PENDING')

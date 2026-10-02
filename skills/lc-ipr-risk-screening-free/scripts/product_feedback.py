"""02C source-bound requests for a minimum product fact and its resolution.

Requests and unavailable-structure limits share the existing product queue.
Only a later versioned product scope can satisfy the missing fact; choosing not
to prompt the user never establishes a structure or comparison conclusion.
"""
from __future__ import annotations

from pathlib import Path
import re

from common import load_json, resolve_retained_path, sha256_json

REVISION = 'product-feedback-v1'
STRUCTURE_POLICY = 'use_provided_else_unavailable_v1'
STRUCTURE_CATEGORIES = {'actual_structure', 'material_composition', 'product_performance'}


def structure_policy_enabled(task):
    value = task.get('product_structure_policy')
    if value is None: return False
    if value != STRUCTURE_POLICY: raise ValueError('PRODUCT_STRUCTURE_POLICY_INVALID')
    return True


def structural_fact(fact):
    if fact.get('information_category') == 'other': return False
    if fact.get('information_category') in STRUCTURE_CATEGORIES: return True
    # Explicit fact paths avoid guessing from a brand/packaging question.
    path = fact.get('source_path', '')
    if not isinstance(path, str): return False
    return any(path == 'product.' + field or path.startswith('product.' + field + '[')
               or path.startswith('product.' + field + '.') for field in
               ('structure', 'structural_features', 'working_principle', 'materials', 'material'))


# Migration only: match concrete requested technical information, never a broad
# "product" keyword or the source location (which may be an Amazon bullet).
LEGACY_STRUCTURE_PATTERNS = (
    r'内部(?:结构|构造|空腔|有无|和定量)', r'实(?:际|物).*?(?:结构|构造)', r'供应商结构资料',
    r'独立(?:柔软)?外套', r'独立包覆层', r'布料外套', r'预压缩', r'恢复原形.*?(?:秒|实测)',
    r'(?i)internal (?:structure|construction|cavity|mechanism)', r'(?i)(?:pre[- ]compressed|precompression)',
    r'(?i)(?:separate|independent) (?:soft )?(?:cover|sleeve)',
    r'(?i)(?:recovery|rebound) (?:time|seconds)',
)


def structure_request_classification(task, request):
    """Return auditable purpose classification, separate from source provenance."""
    category = request.get('information_category')
    if category == 'other': return None
    if request.get('kind') == 'unavailable' and isinstance(request.get('structure_classification'), dict):
        return request['structure_classification']
    if category in STRUCTURE_CATEGORIES:
        return {'basis':'explicit_information_category', 'category':category}
    requested_text = ' '.join(str(request.get(field) or '') for field in ('minimum_information', 'question'))
    if (re.search(r'(?i)许可|授权|品牌|商标|权利人|权属|license|authoriz|copyright|trademark|ownership', requested_text)
            and not any(re.search(pattern, requested_text) for pattern in LEGACY_STRUCTURE_PATTERNS)):
        return None  # Legal entitlement is not an actual-structure request.
    fact = next((row for row in task.get('product_scope', {}).get('facts', [])
                 if row.get('fact_id') == request.get('fact_id')), {})
    if fact.get('information_category') in STRUCTURE_CATEGORIES:
        return {'basis':'fact_information_category', 'category':fact['information_category'],
                'source_path':fact['source_path']}
    if structural_fact(fact):
        return {'basis':'structural_fact_source_path', 'source_path':fact['source_path']}
    if request.get('right_type') not in {'patent','utility_model','design','unregistered_design','trade_dress'}:
        return None
    for field in ('minimum_information', 'question', 'purpose'):
        value = request.get(field, '')
        if not isinstance(value, str): continue
        for pattern in LEGACY_STRUCTURE_PATTERNS:
            match = re.search(pattern, value)
            if match:
                return {'basis':'legacy_requested_technical_information', 'field':field,
                        'matched_text':match.group(0), 'pattern':pattern}
    return None


def structure_request_unavailable(task, request):
    return structure_policy_enabled(task) and structure_request_classification(task, request) is not None


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


def outstanding(task):
    rows = history(task)
    resolved = {row['request_id'] for row in rows if row.get('kind') == 'resolved'}
    current = task.get('product_identity',{}).get('sha256')
    return [row for row in rows if row.get('kind') in {'requested', 'unavailable'}
            and row['request_id'] not in resolved and row.get('target_sha256') == current]



def pending(task):
    return [row for row in outstanding(task) if not structure_request_unavailable(task, row)]


def unavailable(task):
    return [row for row in outstanding(task) if structure_request_unavailable(task, row)]


def structure_limitation_entry(task, *, request=None, fact_ids=None, direction_id=None):
    """Project missing structure without establishing a product fact or asking users."""
    if not structure_policy_enabled(task): return None
    scope = task.get('product_scope', {})
    if request is not None:
        if request not in unavailable(task): return None
        fact_ids, direction_id = [request['fact_id']], request['direction_id']
    facts = {row['fact_id']: row for row in scope.get('facts', [])}
    ids = sorted(set(fact_ids or []))
    if not ids or any(fid not in facts for fid in ids): return None
    if request is None and any(not structural_fact(facts[fid]) for fid in ids): return None
    if request is None and any(facts[fid].get('status') == 'confirmed' for fid in ids): return None
    direction = next((row for row in scope.get('directions', [])
                      if row['direction_id'] == direction_id and set(ids) <= set(row['fact_ids'])), None)
    if direction is None: return None
    proof = {'kind': 'product_structure_unavailable', 'policy': STRUCTURE_POLICY,
             'target_sha256': task.get('product_identity', {}).get('sha256'),
             'scope_sha256': scope.get('scope_sha256'), 'direction_id': direction_id,
             'fact_sha256': {fid: sha256_json(facts[fid]) for fid in ids},
             'request_id': request['request_id'] if request else None,
             'request_sha256': sha256_json(request) if request else None,
             'request_classification': structure_request_classification(task, request) if request else None}
    refs = list(dict.fromkeys(ref for fid in ids for ref in facts[fid].get('source_refs', [])))
    if request: refs = list(dict.fromkeys(refs + request['source_refs']))
    return {'kind': 'product_information_limit', 'state': 'blocked',
            'reason': 'PRODUCT_STRUCTURE_UNAVAILABLE', 'direction_id': direction_id,
            'scenario_id': direction['scenario_id'], 'right_type': direction['right_type'],
            'candidate_id': (request.get('candidate_id') or None) if request else None,
            'jurisdiction': request.get('jurisdiction') if request else None,
            'fact_ids': ids, 'evidence_refs': refs, 'delivery_limit': proof,
            'official_verification': 'not_verified', 'question': '', 'question_asked': False,
            'reasoning': '已有资料不足以核实实际结构；按默认规则视为用户无法提供补充，依赖该结构的要素为 unknown／无法判定。',
            'resume_condition': '用户主动提供相关资料后，按来源性质留存并重新审阅受影响事实与比较。'}


def structure_limit_valid(entry, task, evidence, task_dir):
    proof = entry.get('delivery_limit', {})
    if not isinstance(proof, dict): return False
    if proof.get('kind') != 'product_structure_unavailable' or task_dir is None: return False
    try:
        from product_scope import verify as verify_scope
        verify_scope(task, evidence, task_dir)
        request = next((row for row in unavailable(task)
                        if row['request_id'] == proof.get('request_id')), None)
        if proof.get('request_id') and request is None: return False
        expected = structure_limitation_entry(task, request=request,
            fact_ids=list(proof.get('fact_sha256', {})), direction_id=proof.get('direction_id'))
        if expected is None: return False
        expected_proof = expected['delivery_limit']
        if proof.get('specialty_gap_event_id'):
            from specialty_analysis import events, _unknown_bindings
            rows = events(task)
            gap = next((row for row in rows if row.get('event_id') == proof['specialty_gap_event_id']), {})
            follow = next((row for row in reversed(rows) if row.get('kind') == 'followup'
                           and row.get('gap_event_id') == gap.get('event_id')), {})
            if (not request or gap.get('action_kind') != 'user_fact'
                    or gap.get('product_feedback_request_id') != request['request_id']
                    or follow.get('outcome') not in {'waiting', 'limited'}
                    or not _unknown_bindings(task, gap, rows)):
                return False
            expected_proof = {**expected_proof, 'specialty_gap_event_id': gap['event_id'],
                'specialty_gap_sha256': sha256_json(gap), 'followup_sha256': sha256_json(follow),
                'unknown_bindings': _unknown_bindings(task, gap, rows)}
        if proof.get('m07_gap_event_id'):
            from distinctive_rights import events
            rows = events(task)
            gap = next((row for row in rows if row.get('event_id') == proof['m07_gap_event_id']), {})
            follow = next((row for row in reversed(rows) if row.get('kind') == 'followup'
                           and row.get('gap_event_id') == gap.get('event_id')), {})
            if (not request or gap.get('action_kind') != 'user_fact'
                    or gap.get('product_feedback_request_id') != request['request_id']
                    or follow.get('outcome') not in {'waiting', 'limited'}):
                return False
            expected_proof = {**expected_proof, 'm07_gap_event_id': gap['event_id'],
                'm07_gap_sha256': sha256_json(gap), 'followup_sha256': sha256_json(follow)}
        return (proof == expected_proof and entry.get('state') == 'blocked'
                and entry.get('reason') == expected['reason']
                and entry.get('direction_id') == expected['direction_id']
                and entry.get('scenario_id') == expected['scenario_id']
                and entry.get('right_type') == expected['right_type']
                and set(entry.get('evidence_refs', [])) == set(expected['evidence_refs'])
                and (not request or entry.get('candidate_id') == expected['candidate_id']))
    except (ValueError, TypeError, KeyError, OSError):
        return False


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
        if row.get('kind') in {'requested', 'unavailable'}:
            if (row.get('request_id') in requests or not row.get('purpose')
                    or not row.get('minimum_information') or not row.get('question')
                    or not row.get('direction_id') or not row.get('fact_id')):
                raise ValueError('PRODUCT_FEEDBACK_REQUEST_INVALID')
            if row.get('kind') == 'unavailable':
                classification = row.get('structure_classification', {})
                basis = classification.get('basis')
                valid = (basis == 'explicit_information_category' and
                         classification.get('category') == row.get('information_category') in STRUCTURE_CATEGORIES)
                valid |= (basis == 'fact_information_category' and classification.get('category') in STRUCTURE_CATEGORIES
                          and isinstance(classification.get('source_path'), str))
                valid |= (basis == 'structural_fact_source_path' and
                          structural_fact({'source_path':classification.get('source_path')}))
                if basis == 'legacy_requested_technical_information':
                    pattern = classification.get('pattern')
                    value = row.get(classification.get('field'), '')
                    match = re.search(pattern, value) if pattern in LEGACY_STRUCTURE_PATTERNS and isinstance(value, str) else None
                    valid |= bool(match and match.group(0) == classification.get('matched_text'))
                if row.get('structure_policy') != STRUCTURE_POLICY or not valid:
                    raise ValueError('PRODUCT_FEEDBACK_UNAVAILABLE_POLICY_INVALID')
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
    return {row['candidate_id'] for row in outstanding(task) if row.get('candidate_id')}


def assessment_gate(task, assessments):
    affected = affected_candidate_ids(task)
    if any(row.get('candidate_id') in affected and row.get('risk') in {'极低','低','中','高','极高'}
           and not row.get('out_of_scope') for row in assessments):
        raise ValueError('PRODUCT_FEEDBACK_COMPARISON_PENDING')

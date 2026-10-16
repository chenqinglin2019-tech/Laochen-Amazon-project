"""r6 (report-always-v1): a module answer is repaired, never refused for one row.

Before r6 a module answer was all or nothing: one row against one rule (a miscopied scenario hash, a counter argument
citing the patent's own page, a missing implementation list, an out-of-scope row the task did not exclude) refused all
of it, the retry re-sent the same prompt, and the run stopped without a report. Seven products in the owner's runs hit
such a stop. Here the answer is kept as the model wrote it and an effective judgment is derived from it:

* ``derive(raw, packet, actions)`` is a pure function of the audited answer, the audited module packet and the host's
  recorded actions; ``module_review.validate_execution`` recomputes it, so nothing is hand-edited;
* fields the program owns are filled from the packet (scenario hash, module id, title, scope, statement, reading
  observations), malformed list fields and arguments are normalized or dropped, the evidence roll-up is completed;
* rows of foreign rights, foreign countries or non-selected candidates are dropped; duplicate units keep the first;
* a row that still cannot stand is demoted to pending with its code (``demoted_from`` keeps what the reviewer wrote);
* required scopes and selected candidates the answer left out get pending rows, so the review never lacks a unit;
* the host may only record ``drop_refs`` (evidence ids the frozen registry does not know), ``demote`` (unit -> code)
  and ``drop_signals``; none of them can create or raise a risk.
"""
from __future__ import annotations

from copy import deepcopy

REVISION = 'module-row-repair-v1'
# r7 (search-guard-v1 tasks): a comparison criterion written as plain text keeps its words. Run B0GFNWR8FW: the r6 prompt
# lacked the criteria format, every reviewer wrote strings, v1 dropped them and three rows rated 低 by both chains became
# 待定 while all eight graded designs read "已入选待比较". The recorded revision is the one a validation recomputes.
REVISION_V2 = 'module-row-repair-v2'
REVISIONS = (REVISION, REVISION_V2)
_FLAGS = ('out_of_scope', 'future_signal', 'signal_only', 'aggregation_included')
_LISTS = ('assumptions', 'raise_if', 'lower_if')
_RISKS = ('极低', '低', '中', '高', '极高')
_CONFIDENCES = ('低', '中', '高')
_RIGHT_STATES = ('active', 'pending', 'expired', 'abandoned', 'unknown')
_CONFIDENCE_FACTS = ('identity', 'scope', 'status', 'product', 'comparison')
_CRITERION_RESULTS = ('supports_risk', 'excludes_risk', 'unknown', 'not_applicable')
NO_SUPPORT = '本行没有记录支持风险的论据。'
NO_COUNTER = '本行没有记录降低风险的论据；检索失败、覆盖缺口和未发现候选均不作为排除事实。'
PENDING_TEXT = {
    'ASSESSMENT_REASONING_REQUIRED': '终审审阅没有写出这一行的判断理由，程序不代写结论，按待定处理。',
    'SPECIFIC_POSITIVE_CONFLICT_REQUIRED': '终审审阅给出了中及以上等级，但没有可核对的支持论据，按待定处理。',
    'DECISIVE_SCOPED_EXCLUSION_REQUIRED': '终审审阅给出了极低等级，但没有写明决定性排除依据，按待定处理。',
    'CANDIDATE_RATING_BINDING_REQUIRED': '终审审阅的论据没有引用该候选自身的记录或原文，等级无法与候选绑定，按待定处理。',
    'CANDIDATE_RATING_CRITERIA_REQUIRED': '终审审阅评为低风险，但没有写出比较依据，按待定处理。',
    'OUT_OF_SCOPE_NOT_BOUND_TO_TASK': '终审审阅把这一范围写成未纳入，但任务并未排除它，按待定处理。',
    'SCOPE_MISSING': '终审审阅没有输出这一范围的整体判断，按待定处理。',
    'CANDIDATE_MISSING': '终审审阅没有输出这一入选候选的判断，按待定处理。',
    'MODULE_UNAVAILABLE': '这一审阅链的该模块没有取得可用的终审结果，按待定处理，由主审结合另一审阅裁决。',
}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _unit(row):
    from final_review import unit_id
    return unit_id(row)


def _count(record, code):
    record['repairs'][code] = record['repairs'].get(code, 0) + 1


def _context(packet):
    from decision_workflow import scenario_index, scenario_sha256
    task = packet.get('task') or {}
    scope = packet.get('module_scope') or {}
    scenarios = scenario_index(task)
    return {'task': task, 'module': scope.get('module_id'), 'rights': set(scope.get('right_types') or []),
            'required': list(scope.get('required_scopes') or []),
            'targets': {str(value).upper() for value in task.get('target_jurisdictions') or []},
            'scenarios': scenarios, 'hashes': {key: scenario_sha256(value) for key, value in scenarios.items()},
            'primary': task.get('primary_scenario_id'),
            'index': packet.get('candidate_evidence') or {},
            'has_index': isinstance(packet.get('candidate_evidence'), dict),
            'reusable': set((packet.get('review_reuse') or {}).get('reusable_unit_ids') or [])}


def _string_list(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if _text(item)]


def _human_checks(value):
    result = []
    for item in value if isinstance(value, list) else [value] if value is not None else []:
        if _text(item):
            result.append(item.strip())
        elif isinstance(item, dict):
            if ((_text(item.get('action')) and _text(item.get('reviewer')))
                    or all(_text(item.get(key)) for key in ('owner', 'question', 'evidence_needed'))):
                result.append(item)
            else:
                words = [str(part).strip() for part in item.values() if _text(part)]
                if words:
                    result.append('；'.join(words))
    return result


def _ref_list(value):
    return isinstance(value, list) and all(isinstance(ref, str) and ref for ref in value)


def _arguments(value):
    if not isinstance(value, list):
        return [], value is not None
    kept = [item for item in value if isinstance(item, dict) and _text(item.get('reasoning'))
            and _ref_list(item.get('evidence_refs')) and item.get('evidence_refs')]
    return kept, len(kept) != len(value)


def _drop_refs(value, refs):
    """A copy of value without the given ids in any evidence-ref list."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if (key == 'evidence_refs' or key.endswith('_evidence_refs')) and isinstance(item, list):
                out[key] = [ref for ref in item if ref not in refs]
            else:
                out[key] = _drop_refs(item, refs)
        return out
    if isinstance(value, list):
        return [_drop_refs(item, refs) for item in value]
    return value


def _rollup(row):
    from module_review import row_evidence_ref_additions
    extra = row_evidence_ref_additions(row)
    if extra:
        row['evidence_refs'] = [*row['evidence_refs'], *extra]
    return bool(extra)


def _basis_refs(ctx, cid):
    info = ctx['index'].get(cid) or {}
    ordered = sorted(info.get('evidence', []), key=lambda item: ('discovery', 'detail_record', 'document', 'api_fact',
                     'drawing', 'record').index(item['role']) if item.get('role') in ('discovery', 'detail_record',
                     'document', 'api_fact', 'drawing', 'record') else 9)
    return [item['ref'] for item in ordered[:3]]


def pending_row(ctx, identity, code, *, reviewed=None, refs=None):
    """A complete, valid pending row for one unit; ``reviewed`` keeps what the reviewer wrote (demotions only)."""
    reason = PENDING_TEXT.get(code) or ('终审该行未通过程序校验（%s），按待定处理。' % code)
    cid = identity.get('candidate_id')
    refs = list(dict.fromkeys(refs if refs is not None else (_basis_refs(ctx, cid) if cid else [])))
    row = {key: deepcopy(identity[key]) for key in ('scenario_id', 'scenario_sha256', 'jurisdiction', 'right_type',
           'module_id', 'title', 'scope', 'candidate_id', 'assessment_object') if identity.get(key) not in (None, '')}
    row.update({'risk': None, 'assessment_status': 'pending', 'pending_reasoning': reason, 'reasoning': reason,
                'pending_basis': code, 'evidence_confidence': '低',
                'confidence_reasoning': '本行没有可采用的终审结论，置信度按低记录。',
                'evidence_refs': refs, 'supporting_evidence': [], 'counter_evidence': [],
                'no_supporting_evidence_reasoning': NO_SUPPORT, 'no_counter_evidence_reasoning': NO_COUNTER,
                'assumptions': [], 'raise_if': [], 'lower_if': [], 'human_checks': [],
                'right_state': 'unknown', 'confidence_basis': {}})
    if reviewed is not None:
        kept = {key: deepcopy(reviewed.get(key)) for key in ('risk', 'assessment_status', 'evidence_confidence',
                'reasoning', 'confidence_reasoning') if reviewed.get(key) not in (None, '', [])}
        row['demoted_from'] = {**kept, 'code': code}
        row['human_checks'] = _human_checks(reviewed.get('human_checks'))
        row['assumptions'] = _string_list(reviewed.get('assumptions'))
        row['raise_if'] = _string_list(reviewed.get('raise_if'))
        row['lower_if'] = _string_list(reviewed.get('lower_if'))
    return row


def _identity(row, ctx, record):
    """Fill the fields the program owns; None when the row cannot belong to this module."""
    from record_independent_review import MODULE_BY_RIGHT
    right = row.get('right_type')
    if right not in ctx['rights']:
        _count(record, 'foreign_right_row_dropped')
        return None
    country = str(row.get('jurisdiction') or '').upper()
    if country not in ctx['targets']:
        if len(ctx['targets']) == 1 and not row.get('jurisdiction'):
            country = next(iter(ctx['targets']))
            _count(record, 'jurisdiction_filled')
        else:
            _count(record, 'foreign_jurisdiction_row_dropped')
            return None
    row['jurisdiction'] = country
    scenario = row.get('scenario_id')
    if scenario not in ctx['scenarios']:
        from decision_workflow import scenario_right_types
        holders = [key for key, value in ctx['scenarios'].items() if right in scenario_right_types(value)]
        chosen = ctx['primary'] if ctx['primary'] in holders else holders[0] if len(holders) == 1 else None
        if chosen is None:
            _count(record, 'unknown_scenario_row_dropped')
            return None
        row['scenario_id'] = scenario = chosen
        _count(record, 'scenario_id_filled')
    if row.get('scenario_sha256') != ctx['hashes'][scenario]:
        row['scenario_sha256'] = ctx['hashes'][scenario]
        _count(record, 'scenario_sha256_filled')
    if row.get('module_id') != MODULE_BY_RIGHT.get(right) and not (
            row.get('module_id') == 'pending_application' and right in {'patent', 'utility_model', 'design'}):
        row['module_id'] = MODULE_BY_RIGHT.get(right)
        _count(record, 'module_id_filled')
    cid = row.get('candidate_id')
    if cid in (None, ''):
        row.pop('candidate_id', None)
    elif ctx['has_index'] and cid not in ctx['index']:
        if row.get('risk') in _RISKS and not (row.get('future_signal') is True or row.get('signal_only') is True):
            _count(record, 'unselected_candidate_row_dropped')
            return None
    info = ctx['index'].get(cid) or {}
    if not _text(row.get('title')):
        row['title'] = ' '.join(str(part) for part in (info.get('publication_number'), info.get('title')) if part) \
            or '%s %s 范围' % (country, right)
        _count(record, 'title_filled')
    if not _text(row.get('scope')):
        row['scope'] = row['title']
        _count(record, 'scope_filled')
    return row


def _text_criteria(value, record):
    """v2: criteria written as text become unknown-result criteria that keep the reviewer's words."""
    if isinstance(value, str):
        value = [value] if value.strip() else []
    if not isinstance(value, list):
        return value
    converted = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str) and item.strip():
            converted.append({'criterion': '比较依据%d' % index, 'result': 'unknown',
                              'reasoning': item.strip()[:1200], 'evidence_refs': []})
            _count(record, 'criterion_text_kept')
        else:
            converted.append(item)
    return converted


def _structure(row, ctx, record):
    for flag in _FLAGS:
        if flag in row and type(row[flag]) is not bool:
            value = str(row[flag]).strip().lower()
            if value in ('true', '1', 'yes'):
                row[flag] = True
            elif value in ('false', '0', 'no', '', 'none', 'null'):
                row[flag] = False
            else:
                row.pop(flag)
            _count(record, 'flag_normalized')
    for field in _LISTS:
        fixed = _string_list(row.get(field))
        if fixed != row.get(field):
            row[field] = fixed
            _count(record, 'list_normalized')
    checks = _human_checks(row.get('human_checks'))
    if checks != row.get('human_checks'):
        row['human_checks'] = checks
        _count(record, 'human_checks_normalized')
    for field, missing, text in (('supporting_evidence', 'no_supporting_evidence_reasoning', NO_SUPPORT),
                                 ('counter_evidence', 'no_counter_evidence_reasoning', NO_COUNTER)):
        kept, dropped = _arguments(row.get(field))
        if dropped or not isinstance(row.get(field), list):
            _count(record, 'argument_dropped')
        row[field] = kept
        if not kept and not _text(row.get(missing)):
            row[missing] = text
            _count(record, 'no_argument_reason_filled')
        elif missing not in row:
            row[missing] = ''
    basis = row.get('confidence_basis')
    if not isinstance(basis, dict):
        row['confidence_basis'] = {}
        if basis is not None:
            _count(record, 'confidence_basis_dropped')
    else:
        kept = {name: item for name, item in basis.items() if name in _CONFIDENCE_FACTS and isinstance(item, dict)
                and type(item.get('satisfied')) is bool and _text(item.get('reasoning'))
                and _ref_list(item.get('evidence_refs', [])) and (item.get('satisfied') is not True or item.get('evidence_refs'))}
        if len(kept) != len(basis):
            _count(record, 'confidence_basis_item_dropped')
        row['confidence_basis'] = kept
    comparison = row.get('comparison')
    if 'comparison' in row and not isinstance(comparison, dict):
        row.pop('comparison')
        _count(record, 'comparison_dropped')
    elif isinstance(comparison, dict):
        given = comparison.get('criteria', [])
        if ctx.get('revision') == REVISION_V2:
            given = _text_criteria(given, record)
        criteria = given if isinstance(given, list) else []
        kept, seen = [], set()
        for item in criteria:
            if (isinstance(item, dict) and _text(item.get('criterion')) and item['criterion'] not in seen
                    and item.get('result') in _CRITERION_RESULTS and _text(item.get('reasoning'))
                    and _ref_list(item.get('evidence_refs', []))
                    and (item.get('result') == 'unknown' or item.get('evidence_refs'))):
                kept.append(item)
                seen.add(item['criterion'])
        if len(kept) != len(criteria) or ('criteria' in comparison and not isinstance(given, list)):
            _count(record, 'criterion_dropped')
        if 'criteria' in comparison:
            comparison['criteria'] = kept
        if comparison.get('claims'):
            from assessment_estimate import _validate_implementation_claims
            try:
                _validate_implementation_claims(row)
                for claim in comparison['claims']:
                    if (not isinstance(claim, dict) or not claim.get('claim_id')
                            or not _ref_list(claim.get('claim_evidence_refs')) or not claim.get('claim_evidence_refs')
                            or not isinstance(claim.get('elements'), list)
                            or any(not isinstance(element, dict) or element.get('result') not in _CRITERION_RESULTS
                                   or not _ref_list(element.get('evidence_refs', []))
                                   or (element.get('result') != 'unknown' and not element.get('evidence_refs'))
                                   for element in claim['elements'])):
                        raise ValueError('CLAIM_ORIGINAL_EVIDENCE_REQUIRED')
            except ValueError:
                comparison.pop('claims', None)
                comparison.pop('implementations', None)
                _count(record, 'claims_dropped')
        visual = comparison.get('visual_coverage')
        if visual is not None and not (isinstance(visual, dict) and isinstance(visual.get('required_views'), list)
                and all(isinstance(visual.get(side), list) and all(isinstance(view, dict) and _text(view.get('view'))
                        and _ref_list(view.get('evidence_refs')) and view.get('evidence_refs') for view in visual[side])
                        for side in ('product_views', 'right_views'))):
            comparison.pop('visual_coverage')
            _count(record, 'visual_coverage_dropped')
    if 'search_comparison' in row:
        value = row['search_comparison']
        if not (isinstance(value, dict) and _text(value.get('reasoning')) and _ref_list(value.get('evidence_refs'))
                and value.get('evidence_refs')):
            row.pop('search_comparison')
            _count(record, 'search_comparison_dropped')
    applicability = row.get('scope_applicability')
    if 'scope_applicability' in row and not (isinstance(applicability, dict)
            and applicability.get('status') in ('applicable', 'not_applicable', 'unassessed')
            and _text(applicability.get('reasoning')) and _ref_list(applicability.get('evidence_refs', []))
            and (applicability.get('status') == 'unassessed' or applicability.get('evidence_refs'))):
        row.pop('scope_applicability')
        _count(record, 'scope_applicability_dropped')
    state = row.get('right_state', 'unknown')
    if state not in _RIGHT_STATES:
        state = row['right_state'] = 'unknown'
        _count(record, 'right_state_normalized')
    if state != 'unknown' and not (_ref_list(row.get('right_state_evidence_refs')) and row.get('right_state_evidence_refs')):
        refs = [item['ref'] for item in (ctx['index'].get(row.get('candidate_id')) or {}).get('evidence', [])
                if item.get('role') in ('detail_record', 'api_fact')]
        if refs:
            row['right_state_evidence_refs'] = refs[:1]
            _count(record, 'right_state_refs_filled')
        else:
            row['right_state'] = 'unknown'
            row.pop('right_state_evidence_refs', None)
            _count(record, 'right_state_unknown')
    if 'right_state' not in row:
        row['right_state'] = 'unknown'
    # risk, status and confidence (an out-of-scope row keeps its own contract)
    risk = row.get('risk')
    if isinstance(risk, str) and risk.strip() in _RISKS:
        risk = row['risk'] = risk.strip()
    elif risk is not None:
        row['risk'] = risk = None
        _count(record, 'risk_cleared')
    else:
        row['risk'] = None
    status = row.get('assessment_status')
    if row.get('out_of_scope') is True:
        pass
    elif status == 'pending' and risk is not None:
        row['risk'] = risk = None
        _count(record, 'risk_cleared_for_pending')
    elif status not in ('pending', 'assessed') or (status == 'assessed' and risk is None and not (
            row.get('future_signal') is True or row.get('signal_only') is True)):
        row['assessment_status'] = 'assessed' if risk is not None else 'pending'
        _count(record, 'status_normalized')
    if row.get('assessment_status') == 'pending' and row.get('out_of_scope') is not True:
        if not _text(row.get('pending_reasoning')):
            row['pending_reasoning'] = row.get('reasoning') if _text(row.get('reasoning')) else '终审审阅没有写明待定原因。'
            _count(record, 'pending_reasoning_filled')
        if not _text(row.get('reasoning')):
            row['reasoning'] = row['pending_reasoning']
    if row.get('evidence_confidence') not in _CONFIDENCES:
        row['evidence_confidence'] = '低'
        _count(record, 'confidence_defaulted')
    if not _text(row.get('confidence_reasoning')):
        row['confidence_reasoning'] = '终审审阅没有单独说明置信度理由。'
        _count(record, 'confidence_reasoning_filled')
    if not _ref_list(row.get('evidence_refs')):
        row['evidence_refs'] = [ref for ref in row.get('evidence_refs') or [] if isinstance(ref, str) and ref] \
            if isinstance(row.get('evidence_refs'), list) else []
        _count(record, 'evidence_refs_normalized')
    return row


def _semantic_problem(row, ctx):
    """Packet-decidable reasons a row cannot stand as written (it is demoted)."""
    from candidate_evidence import binding_refs, rating_binding
    if row.get('out_of_scope') is True:
        from assessment_estimate import _scope_excluded
        if row.get('risk') is not None or not _text(row.get('scope_reasoning')) or not _scope_excluded(row, ctx['task']):
            return 'OUT_OF_SCOPE_NOT_BOUND_TO_TASK'
        return None
    if row.get('future_signal') is True or row.get('signal_only') is True:
        return None
    risk = row.get('risk')
    if risk is not None and not _text(row.get('reasoning')):
        return 'ASSESSMENT_REASONING_REQUIRED'
    if risk in ('中', '高', '极高') and (not row.get('candidate_id') or not row.get('supporting_evidence')):
        return 'SPECIFIC_POSITIVE_CONFLICT_REQUIRED'
    if risk == '极低':
        decisive = row.get('decisive_exclusion')
        if (not row.get('candidate_id') or not isinstance(decisive, dict) or not _text(decisive.get('reasoning'))
                or not _ref_list(decisive.get('evidence_refs')) or not decisive.get('evidence_refs')):
            return 'DECISIVE_SCOPED_EXCLUSION_REQUIRED'
    if risk is not None and row.get('candidate_id') and ctx['index']:
        return rating_binding(row, binding_refs(ctx['index']))
    return None


def _statement(raw, ctx, record):
    statement = raw.get('final_review_statement')
    if not isinstance(statement, dict):
        statement = {}
    fixed = dict(statement)
    defaults = {'overall': '本模块审阅没有写总结语；本模块结论以各行判断为准。',
                'scope': '本模块范围：' + '、'.join(sorted(ctx['rights'])) + '（' + '、'.join(sorted(ctx['targets'])) + '）。',
                'limitations': '本模块审阅没有写明限制；未读取的原件和未完成事项见各行与报告限制。'}
    for key, text in defaults.items():
        if not _text(fixed.get(key)):
            fixed[key] = text
            _count(record, 'statement_filled')
    return fixed


def _observations(raw, packet, record):
    materials = (packet.get('retained_originals') or {}).get('materials') or []
    if (packet.get('retained_originals') or {}).get('revision') not in ('public-originals-v2', 'public-originals-v3') \
            or not materials:
        return raw.get('material_observations')
    given = raw.get('material_observations') if isinstance(raw.get('material_observations'), dict) else {}
    result = {}
    for material in materials:
        item = given.get(material['material_id'])
        if (isinstance(item, dict) and _text(item.get('observation')) and _text(item.get('limitations'))):
            result[material['material_id']] = item
        else:
            result[material['material_id']] = {'observation': '审阅没有单独记录对该材料的观察。',
                                               'limitations': '未单独记录观察，不推定其内容已被核对。',
                                               'source_refs': list(material.get('source_refs') or [])}
            _count(record, 'observation_filled')
    if set(given) - set(result):
        _count(record, 'observation_extra_dropped')
    return result


def _acknowledgements(raw, packet, statement, record):
    from review_material_policy import MANIFEST_REVISION
    originals = packet.get('retained_originals') or {}
    if originals.get('revision') != MANIFEST_REVISION:
        return raw.get('untransmitted_material_acknowledgements'), statement
    expected = sorted({row['sha256'] for row in originals.get('not_transmitted', [])})
    if not expected:
        return raw.get('untransmitted_material_acknowledgements'), statement
    given = raw.get('untransmitted_material_acknowledgements')
    given = given if isinstance(given, dict) else {}
    result = {}
    for sha in expected:
        item = given.get(sha)
        if isinstance(item, dict) and item.get('original_read') is False and _text(item.get('limitations')):
            result[sha] = item
        else:
            result[sha] = {'original_read': False, 'limitations': '有一份留存原件未随本次终审材料发送，未读取，不推定其内容。'}
            _count(record, 'acknowledgement_filled')
    limits = statement.get('limitations', '')
    for item in result.values():
        if item['limitations'] not in limits:
            limits = (limits + ' ' + item['limitations']).strip()
            _count(record, 'acknowledgement_limitation_appended')
    return result, {**statement, 'limitations': limits}


def _signal(row, ctx):
    """A signal row with the fields the program owns filled (scenario hash, country spelling)."""
    row = deepcopy(row)
    if row.get('scenario_id') in ctx['hashes'] and row.get('scenario_sha256') != ctx['hashes'][row['scenario_id']]:
        row['scenario_sha256'] = ctx['hashes'][row['scenario_id']]
    if isinstance(row.get('jurisdiction'), str):
        row['jurisdiction'] = row['jurisdiction'].upper()
    return row


def normalized_signals(raw, packet):
    """{field: [(index in the answer, normalized signal)]} - what the host checks one by one."""
    ctx = _context(packet)
    result = {}
    for field in ('future_applications', 'enforcement_signals'):
        value = raw.get(field) if isinstance(raw, dict) else None
        rows = value if isinstance(value, list) else []
        result[field] = [(index, _signal(row, ctx)) for index, row in enumerate(rows) if isinstance(row, dict)]
    return result


def _signals(raw, ctx, actions, record):
    result = {}
    drops = (actions or {}).get('drop_signals') or {}
    for field in ('future_applications', 'enforcement_signals'):
        value = raw.get(field)
        rows = value if isinstance(value, list) else []
        if value is not None and not isinstance(value, list):
            _count(record, 'signals_dropped')
        dropped = set(drops.get(field) or [])
        kept = [_signal(row, ctx) for index, row in enumerate(rows) if index not in dropped and isinstance(row, dict)]
        if len(kept) != len(rows):
            _count(record, 'signal_dropped')
        result[field] = kept
    return result


def derive(raw, packet, actions=None, revision=None):
    """(effective judgment, record) - a pure function of the answer, the packet and the recorded host actions.

    ``revision`` is the recorded row-derivation revision when a validation recomputes a record; a new derivation uses
    v2 on search-guard tasks and v1 otherwise."""
    from review_judgment import ModelJudgmentError
    if not isinstance(raw, dict):
        raise ModelJudgmentError('FINAL_REVIEW_MODULE_JUDGMENT_NOT_OBJECT')
    if revision is None:
        import search_guard
        revision = REVISION_V2 if search_guard.enabled((packet or {}).get('task')) else REVISION
    if revision not in REVISIONS:
        raise ModelJudgmentError('FINAL_REVIEW_MODULE_REPAIR_REVISION_UNKNOWN')
    rows = raw.get('assessments')
    ctx = {**_context(packet), 'revision': revision}
    reusing = isinstance(raw.get('reused_unit_ids'), list) and bool(raw.get('reused_unit_ids'))
    if not isinstance(rows, list) or (not rows and ctx['required'] and not reusing):
        # (an answer that only reuses its own earlier units has no new rows and is complete)
        raise ModelJudgmentError('FINAL_REVIEW_MODULE_ASSESSMENTS_INVALID')
    actions = actions or {}
    drop_refs = actions.get('drop_refs') or {}
    demote = actions.get('demote') or {}
    record = {'revision': revision, 'actions': deepcopy(actions), 'repairs': {}, 'demoted_units': {},
              'added_units': [], 'dropped_rows': 0}
    effective, seen = [], {}
    for original in rows:
        if not isinstance(original, dict):
            _count(record, 'row_not_object_dropped')
            record['dropped_rows'] += 1
            continue
        row = _identity(deepcopy(original), ctx, record)
        if row is None:
            record['dropped_rows'] += 1
            continue
        row = _structure(row, ctx, record)
        key = _unit(row)
        if drop_refs.get(key):
            row = _drop_refs(row, set(drop_refs[key]))
            row['evidence_refs'] = [ref for ref in row.get('evidence_refs', []) if ref not in set(drop_refs[key])]
            _count(record, 'unknown_refs_dropped')
            row = _structure(row, ctx, record)      # an argument left without ids is dropped again
        if _rollup(row):
            _count(record, 'evidence_refs_rolled_up')
        code = demote.get(key) or _semantic_problem(row, ctx)
        if code:
            identity = {**row, 'candidate_id': row.get('candidate_id')}
            row = pending_row(ctx, identity, code, reviewed=original)
            record['demoted_units'][key] = code
        if key in seen:
            _count(record, 'duplicate_unit_dropped')
            record['dropped_rows'] += 1
            continue
        seen[key] = row
        effective.append(row)
    reused = raw.get('reused_unit_ids') if isinstance(raw.get('reused_unit_ids'), list) else []
    reused = [key for key in dict.fromkeys(item for item in reused if isinstance(item, str))
              if key in ctx['reusable'] and key not in seen]
    if reused != raw.get('reused_unit_ids', []):
        _count(record, 'reuse_normalized')
    from assessment_estimate import missing_product_scopes
    for scope in missing_product_scopes(effective, ctx['task'], ctx['rights']):
        if any(key == _unit({**scope, 'assessment_object': 'product'}) for key in reused):
            continue
        from record_independent_review import MODULE_BY_RIGHT
        identity = {**scope, 'scenario_sha256': ctx['hashes'].get(scope['scenario_id']),
                    'module_id': MODULE_BY_RIGHT.get(scope['right_type']), 'assessment_object': 'product',
                    'title': '%s %s 整体范围' % (scope['jurisdiction'], scope['right_type']),
                    'scope': '%s / %s / %s' % (scope['scenario_id'], scope['jurisdiction'], scope['right_type'])}
        row = pending_row(ctx, identity, 'SCOPE_MISSING', refs=_scope_refs(packet, scope))
        effective.append(row)
        record['added_units'].append(_unit(row))
    from record_independent_review import MODULE_BY_RIGHT
    rated = {(row.get('candidate_id')) for row in effective if row.get('candidate_id')}
    reused_cids = set()
    for cid, info in ctx['index'].items():
        if cid in rated or info.get('right_type') not in ctx['rights'] or not ctx['has_index']:
            continue
        identity = {'scenario_id': ctx['primary'], 'scenario_sha256': ctx['hashes'].get(ctx['primary']),
                    'jurisdiction': info.get('jurisdiction'), 'right_type': info.get('right_type'),
                    'module_id': MODULE_BY_RIGHT.get(info.get('right_type')), 'candidate_id': cid,
                    'assessment_object': 'product',
                    'title': ' '.join(str(part) for part in (info.get('publication_number'), info.get('title')) if part) or cid,
                    'scope': '入选候选的当前风险'}
        if ctx['primary'] not in ctx['scenarios'] or _unit(identity) in reused:
            reused_cids.add(cid)
            continue
        row = pending_row(ctx, identity, 'CANDIDATE_MISSING')
        effective.append(row)
        record['added_units'].append(_unit(row))
    judgment = {key: deepcopy(value) for key, value in raw.items()
                if key not in ('assessments', 'reused_unit_ids', 'future_applications', 'enforcement_signals',
                               'final_review_statement', 'material_observations', 'untransmitted_material_acknowledgements')}
    judgment['assessments'] = effective
    judgment['reused_unit_ids'] = reused
    judgment.update(_signals(raw, ctx, actions, record))
    statement = _statement(raw, ctx, record)
    acknowledgements, statement = _acknowledgements(raw, packet, statement, record)
    judgment['final_review_statement'] = statement
    observations = _observations(raw, packet, record)
    if observations is not None:
        judgment['material_observations'] = observations
    if acknowledgements is not None:
        judgment['untransmitted_material_acknowledgements'] = acknowledgements
    record['repairs'] = dict(sorted(record['repairs'].items()))
    return judgment, record


def _scope_refs(packet, scope):
    """Search receipts of this country and right in the packet (they ground the disclosed limitation)."""
    refs = []
    for rows in ((packet.get('evidence') or {}).get('collections') or {}).values():
        for entry in rows if isinstance(rows, list) else []:
            if (isinstance(entry, dict) and entry.get('evidence_id') and not entry.get('review_packet_stub')
                    and entry.get('operation') == 'search'
                    and str(entry.get('jurisdiction') or '').upper() == scope['jurisdiction']
                    and entry.get('right_type') == scope['right_type']):
                refs.append(entry['evidence_id'])
    return sorted(refs)[:3]


def fallback_judgment(packet, reason_code):
    """The effective judgment of a module that produced no usable answer: every required scope and selected candidate
    is pending, citing what grounds the disclosed limitation (module-fallback-v1)."""
    ctx = _context(packet)
    record = {'revision': REVISION, 'actions': {}, 'repairs': {}, 'demoted_units': {}, 'added_units': [],
              'dropped_rows': 0}
    raw = {'assessments': [], 'reused_unit_ids': [], 'future_applications': [], 'enforcement_signals': []}
    rows = []
    from assessment_estimate import missing_product_scopes
    from record_independent_review import MODULE_BY_RIGHT
    for scope in missing_product_scopes([], ctx['task'], ctx['rights']):
        identity = {**scope, 'scenario_sha256': ctx['hashes'].get(scope['scenario_id']),
                    'module_id': MODULE_BY_RIGHT.get(scope['right_type']), 'assessment_object': 'product',
                    'title': '%s %s 整体范围' % (scope['jurisdiction'], scope['right_type']),
                    'scope': '%s / %s / %s' % (scope['scenario_id'], scope['jurisdiction'], scope['right_type'])}
        rows.append(pending_row(ctx, identity, 'MODULE_UNAVAILABLE', refs=_scope_refs(packet, scope)))
    for cid, info in ctx['index'].items():
        if info.get('right_type') not in ctx['rights'] or ctx['primary'] not in ctx['scenarios']:
            continue
        identity = {'scenario_id': ctx['primary'], 'scenario_sha256': ctx['hashes'].get(ctx['primary']),
                    'jurisdiction': info.get('jurisdiction'), 'right_type': info.get('right_type'),
                    'module_id': MODULE_BY_RIGHT.get(info.get('right_type')), 'candidate_id': cid,
                    'assessment_object': 'product',
                    'title': ' '.join(str(part) for part in (info.get('publication_number'), info.get('title')) if part) or cid,
                    'scope': '入选候选的当前风险'}
        rows.append(pending_row(ctx, identity, 'MODULE_UNAVAILABLE'))
    raw['assessments'] = rows
    raw['final_review_statement'] = {
        'overall': '这一审阅链的本模块没有取得可用的终审结果（%s），各行按待定处理。' % reason_code,
        'scope': '本模块范围：' + '、'.join(sorted(ctx['rights'])) + '（' + '、'.join(sorted(ctx['targets'])) + '）。',
        'limitations': '本模块终审未完成（%s）；结论由另一审阅链和主审裁决决定。' % reason_code}
    observations = _observations({}, packet, record)
    if observations is not None:
        raw['material_observations'] = observations
    acknowledgements, raw['final_review_statement'] = _acknowledgements({}, packet, raw['final_review_statement'], record)
    if acknowledgements is not None:
        raw['untransmitted_material_acknowledgements'] = acknowledgements
    return raw

"""One factual investigation-depth resolver for planning and work projection.

Absent/unknown facts never remove a legal scope or certify query completion.
"""
from copy import deepcopy
from common import sha256_json
from execution_efficiency import enabled, revised
from product_scope import RIGHTS, object_scenario


def validate_profile(task, rows):
    if not enabled(task):
        raise ValueError('INVESTIGATION_PROFILE_NEW_TASK_REQUIRED')
    if not isinstance(rows, list):
        raise ValueError('INVESTIGATION_PROFILE_ARRAY_REQUIRED')
    scope = task.get('product_scope') or {}
    objects = {r['object_id']: r for r in scope.get('objects', [])}
    facts = {r['fact_id']: r for r in scope.get('facts', [])}
    scenarios = {r['scenario_id'] for r in task.get('assessment_scenarios', [])}
    scenarios.add(task.get('primary_scenario_id', 'product_entry'))
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('INVESTIGATION_PROFILE_ROW_INVALID')
        key = tuple(row.get(k) for k in ('scenario_id', 'object_id', 'right_type'))
        if (key in seen or key[0] not in scenarios or key[1] not in objects or key[2] not in RIGHTS
                or (revised(task) and key[0] != 'genuine_resale' and key[1] in objects
                    and object_scenario(objects[key[1]]) != key[0])
                or row.get('intensity') not in {'baseline', 'focused'}):
            raise ValueError('INVESTIGATION_PROFILE_SCOPE_INVALID')
        seen.add(key)
        for name in ('fact_ids', 'evidence_refs', 'questions', 'escalation_conditions', 'limitations'):
            value = row.get(name)
            if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError('INVESTIGATION_PROFILE_' + name.upper() + '_INVALID')
        if (not row['questions'] or not row['escalation_conditions'] or not row['evidence_refs']
                or not isinstance(row.get('reason'), str) or not row['reason'].strip()
                or any(f not in facts for f in row['fact_ids'])):
            raise ValueError('INVESTIGATION_PROFILE_FACTUAL_BASIS_REQUIRED')
        known_refs = set(objects[key[1]].get('source_refs', []))
        for fid in row['fact_ids']:
            known_refs.update(facts[fid].get('source_refs', []))
        if not set(row['evidence_refs']) <= known_refs:
            raise ValueError('INVESTIGATION_PROFILE_EVIDENCE_NOT_BOUND')
    return deepcopy(rows)


def _basis(task, row):
    from final_review import semantic
    scope = task.get('product_scope') or {}
    objects = {r['object_id']: r for r in scope.get('objects', [])}
    facts = {r['fact_id']: r for r in scope.get('facts', [])}
    return semantic({'object': objects.get(row.get('object_id')),
        'facts': {fid: facts.get(fid) for fid in sorted(set(row.get('fact_ids', [])))}})


def bind_profile(task, rows):
    """Bind newly recorded judgments; never migrate a historical profile on read."""
    result = validate_profile(task, rows)
    for row in result:
        row['basis_sha256'] = sha256_json(_basis(task, row))
    return result


def _current_profiles(task):
    rows = task.get('investigation_profile', [])
    if not isinstance(rows, list):
        raise ValueError('INVESTIGATION_PROFILE_ARRAY_REQUIRED')
    current, stale = [], []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('INVESTIGATION_PROFILE_ROW_INVALID')
        key = tuple(row.get(k) for k in ('scenario_id', 'object_id', 'right_type'))
        if key in seen:
            raise ValueError('INVESTIGATION_PROFILE_SCOPE_INVALID')
        seen.add(key)
        reason = None
        try:
            validate_profile(task, [row])
        except ValueError as exc:
            if str(exc) not in {'INVESTIGATION_PROFILE_SCOPE_INVALID',
                    'INVESTIGATION_PROFILE_FACTUAL_BASIS_REQUIRED', 'INVESTIGATION_PROFILE_EVIDENCE_NOT_BOUND'}:
                raise
            reason = str(exc)
        basis = _basis(task, row)
        if row.get('basis_sha256') and row['basis_sha256'] != sha256_json(basis):
            reason = 'INVESTIGATION_PROFILE_BASIS_CHANGED'
        if reason:
            stale.append({**{k: row.get(k) for k in ('scenario_id', 'object_id', 'right_type')},
                'reason': reason, 'gap_id': 'INVESTIGATION-PROFILE-' + sha256_json([key, basis])[:20],
                'action': 'Revise only this investigation profile using current retained product facts.'})
        else:
            current.append(row)
    return current, stale


def resolve_discovery_work_policy(task, *, scenario_id=None, object_id=None, object_ids=None, right_type=None,
                                  positive_candidate=False, _profiles=None):
    if not enabled(task):
        return None
    scoped = revised(task)
    if scoped:
        scenario_id = scenario_id or task.get('primary_scenario_id', 'product_entry')
        selected_ids = set(object_ids) if object_ids else ({object_id} if object_id else None)
        relevant = {o['object_id'] for o in (task.get('product_scope') or {}).get('objects', [])
            if o.get('scope_status') in {'included', 'pending'}
            and (scenario_id == 'genuine_resale' or object_scenario(o) == scenario_id)
            and (selected_ids is None or o['object_id'] in selected_ids)}
    rows, stale = _profiles if _profiles is not None else _current_profiles(task)
    rows = [r for r in rows if (not scenario_id or r['scenario_id'] == scenario_id)
            and (not object_id or r['object_id'] == object_id)
            and (not right_type or r['right_type'] == right_type)
            and (not scoped or r['object_id'] in relevant)]
    stale = [r for r in stale if (not scenario_id or r['scenario_id'] == scenario_id)
             and (not object_id or r['object_id'] == object_id)
             and (not right_type or r['right_type'] == right_type)
            and (not scoped or r['object_id'] in relevant)]
    # An unprofiled included object cannot inherit another object's light check.
    if not scoped:
        relevant = {o['object_id'] for o in (task.get('product_scope') or {}).get('objects', [])
                    if o.get('scope_status') in {'included', 'pending'} and (not object_id or o['object_id'] == object_id)}
    intensity = ('baseline' if rows and relevant <= {r['object_id'] for r in rows}
                 and all(r['intensity'] == 'baseline' for r in rows) and not positive_candidate else 'focused')
    facts = {r['fact_id']: r for r in (task.get('product_scope') or {}).get('facts', [])}
    missing = sorted({fid for row in rows for fid in row['fact_ids'] if facts[fid].get('status') != 'confirmed'})
    from final_review import semantic
    return {'intensity': intensity, 'questions': list(dict.fromkeys(q for r in rows for q in r['questions'])),
            'basis': rows, 'escalated_by_candidate': bool(positive_candidate),
            'profile_revision_required': stale,
            'missing_facts': [{'fact_id': fid, 'question': facts[fid].get('question'),
                'gap_id': 'INVESTIGATION-GAP-' + sha256_json([scenario_id, object_id, right_type, fid, semantic(facts[fid])])[:20]}
                for fid in missing],
            'completion_rule': 'existing_coverage_only',
            'initial_material': 'title_abstract_representative_image',
            'detail_material': 'selected_or_concrete_missing_fact_only'}


def order_discovery_terms(task, terms, *, right_type):
    """Light recall starts with an actual category/product clue; no clue is dropped.

    All deeper facts remain available to the same bounded discovery/review rules.
    This order also applies when an append-only plan is expanded.
    """
    if revised(task):
        # Retained term bindings may cover more than one scenario or object.
        # Use their maximum intensity; a light profile never hides another scope.
        def priority(term):
            scopes = _term_scopes(task, term, right_type)
            light = all(resolve_discovery_work_policy(task, scenario_id=sid,
                object_ids=ids, right_type=right_type)['intensity'] == 'baseline' for sid, ids in scopes)
            return 1 if light and term.get('kind') not in {'product', 'category'} else 0
        return sorted(terms, key=priority)
    work = resolve_discovery_work_policy(task, right_type=right_type)
    if work is None or work['intensity'] != 'baseline':
        return terms
    return sorted(terms, key=lambda t: t.get('kind') not in {'product', 'category'})


def discovery_terms_intensity(task, terms, *, right_type):
    """Plan priority uses the same exact scopes as its available query terms."""
    if not revised(task):
        return resolve_discovery_work_policy(task, right_type=right_type)['intensity']
    scopes = set(scope for term in terms for scope in _term_scopes(task, term, right_type))
    if not scopes:
        scopes = {(task.get('primary_scenario_id', 'product_entry'), ())}
    profiles = _current_profiles(task)
    return ('focused' if any(resolve_discovery_work_policy(task, scenario_id=sid,
        object_ids=ids or None, right_type=right_type, _profiles=profiles)['intensity'] == 'focused'
        for sid, ids in scopes) else 'baseline')


def _term_scopes(task, term, right):
    from product_scope import matching, direction_state
    scope = task.get('product_scope') or {}
    found = matching(task, [term.get('derived_from')], right) if scope.get('directions') else []
    found = [d for d in found if direction_state(task, d) != 'out_of_scope'
             and (not term.get('scenario_id') or d['scenario_id'] == term['scenario_id'])]
    if found:
        return _group_scopes(found)
    return [(term.get('scenario_id') or task.get('primary_scenario_id', 'product_entry'),
             tuple(term.get('object_ids') or ()))]


def _group_scopes(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row['scenario_id'], set()).update(row.get('object_ids') or [])
    return [(sid, tuple(sorted(ids))) for sid, ids in sorted(grouped.items())]


def _work_scopes(task, entry, plan):
    sid = entry.get('scenario_id') or task.get('primary_scenario_id', 'product_entry')
    explicit = entry.get('object_ids') or ([entry['object_id']] if entry.get('object_id') else [])
    if explicit:
        return [(sid, tuple(sorted(set(explicit))))]
    query = next((r for rows in (plan or {}).get('queries', {}).values() for r in rows
        if entry.get('query_id') and r.get('query_id') == entry['query_id']
        and (not entry.get('plan_entry_sha256') or sha256_json(r) == entry['plan_entry_sha256'])), None)
    if query:
        from workflow_v24 import necessary_scenario_row_bindings
        bindings = necessary_scenario_row_bindings(task, query)
        if bindings:
            return [(b['scenario_id'], tuple(sorted({oid
                for d in query.get('product_dependencies', []) if d.get('scenario_id') == b['scenario_id']
                for oid in d.get('object_ids', [])}))) for b in bindings]
    deps = [d for d in entry.get('product_dependencies', []) if d.get('scenario_id') == sid]
    if deps:
        return _group_scopes(deps)
    cid = entry.get('candidate_id')
    links = [v for v in (task.get('product_scope') or {}).get('candidate_links', []) if cid and v.get('candidate_id') == cid]
    return [(sid, tuple(sorted({oid for link in links for oid in link.get('object_ids', [])})))]


def _combined_policy(policies):
    if len(policies) == 1:
        return policies[0]
    result = deepcopy(policies[0])
    result['intensity'] = 'focused' if any(p['intensity'] == 'focused' for p in policies) else 'baseline'
    for field in ('questions', 'basis', 'profile_revision_required', 'missing_facts'):
        values = {}
        for policy in policies:
            for value in policy[field]:
                values.setdefault(sha256_json(value), value)
        result[field] = list(values.values())
    return result


def project_work(task, view, plan=None):
    if not enabled(task):
        return view
    profiles = _current_profiles(task)
    cache = {}
    for entry in view.get('entries', []):
        right = entry.get('right_type')
        if right not in RIGHTS and not (right == 'unknown' and entry.get('kind') == 'triage'):
            continue
        positive = entry.get('decision') == 'selected' or (entry.get('candidate_id')
            and entry.get('kind') in {'candidate_verification', 'specialty_analysis', 'distinctive_rights'})
        scopes = _work_scopes(task, entry, plan) if revised(task) else [(entry.get('scenario_id'), ())]
        key = (tuple(scopes), right, bool(positive))
        if key not in cache:
            cache[key] = _combined_policy([resolve_discovery_work_policy(task, scenario_id=sid,
                object_ids=ids or None, right_type=right, positive_candidate=bool(positive),
                _profiles=profiles) for sid, ids in scopes])
        policy = cache[key]
        entry['investigation_policy'] = deepcopy(policy)
        if policy['profile_revision_required']:
            entry['investigation_profile_gaps'] = deepcopy(policy['profile_revision_required'])
        if entry.get('reason') == 'API_DISCOVERY_TERMS_MISSING' and policy['missing_facts']:
            entry['minimum_information'] = policy['missing_facts']
            # Preserve the existing work/completion state. This is a stable
            # factual repair hint, not a new limited-delivery exemption.
            entry['action_hint'] = 'Use available product facts for baseline recall; retain unknown facts. Do not invent structural keywords or repeatedly regenerate unchanged terms.'
    return view

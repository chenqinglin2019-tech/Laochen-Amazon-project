"""Program-written ledger entries that carry no judgment (new tasks only).

Every entry here is derivable from retained, hash-bound facts: which candidate
a result row was parsed into, which scopes a candidate belongs to by its own
source, which object a query was planned for. The reviewer identity is always
``program:<name>`` and each reason states the mechanical basis. Relevance,
applicability and risk are never decided here; they stay with triage and the
independent reviews. Rows or candidates that cannot be bound without
interpretation are left untouched for the ordinary Agent route.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json

SOURCE_BINDING_REVIEWER = 'program:source-binding-v1'
COLLECTIONS = ('patents', 'trademarks', 'copyright_assets', 'enforcement')


def _hashes(source):
    return {value for value in (source.get('source_record_sha256'), source.get('original_source_record_sha256')) if value}


def _bindings(candidates):
    """{run_id: [(candidate_id, source)]} from normalized candidate source references."""
    output = {}
    for name in COLLECTIONS:
        for candidate in candidates.get(name, []) if isinstance(candidates, dict) else []:
            if not isinstance(candidate, dict) or not candidate.get('candidate_id'):
                continue
            for source in candidate.get('sources', []):
                if isinstance(source, dict) and source.get('source_run_id'):
                    output.setdefault(source['source_run_id'], []).append((candidate['candidate_id'], source))
    return output


def _bound(source, position, row):
    """The same binding rule the result-position recorder enforces for a candidate outcome."""
    bound_position = source.get('source_position') or source.get('result_position')
    hashes = _hashes(source)
    if bound_position is None and not hashes:
        return False
    if bound_position is not None and bound_position != position:
        return False
    return not hashes or row['raw_sha256'] in hashes


def plan_dispositions(task_dir, task, evidence, candidates):
    """Decisions for result positions that bind, without interpretation, to normalized candidates."""
    from source_result_processing import _latest_decisions, _retained_run, WHOLE_RECORD
    bindings = _bindings(candidates)
    plans, skipped = {}, []
    for run in evidence.get('source_runs', []):
        if not isinstance(run, dict) or not isinstance(run.get('result_processing'), dict):
            continue
        run_id = run.get('run_id')
        if run_id not in bindings:
            continue
        try:
            index, _ = _retained_run(task_dir, run, evidence)
            existing = _latest_decisions(evidence, run_id, index)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            skipped.append({'source_run_id': run_id, 'reason': str(exc)[:120]})
            continue
        rows = index.get('rows') or []
        if not rows or rows[0].get('collection') == WHOLE_RECORD or index.get('count_contradiction'):
            continue
        decisions = []
        for row in rows:
            position = row['position']
            if position in existing or not row.get('raw_sha256'):
                continue
            ids = list(dict.fromkeys(cid for cid, source in bindings[run_id] if _bound(source, position, row)))
            if ids:
                decisions.append({'position': position, 'outcome': 'candidate', 'candidate_ids': ids,
                    'reviewer': SOURCE_BINDING_REVIEWER,
                    'reason': '原回执第%d行按保留行位置与行哈希唯一绑定到候选 %s；机械绑定，相关性由候选分流判断。'
                              % (position, '、'.join(ids))})
        if decisions:
            plans[run_id] = decisions
    return plans, skipped


def auto_bind_dispositions(task_dir):
    from source_result_processing import append_processing_batch, enabled as results_enabled
    from host_triage import enabled as host_enabled
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    if not host_enabled(task) or not results_enabled(task):
        return {'step': 'dispositions', 'status': 'not_applicable', 'bound_positions': 0}
    path = task_dir / 'normalized-candidates.json'
    if not path.is_file():
        return {'step': 'dispositions', 'status': 'no_candidates', 'bound_positions': 0}
    plans, skipped = plan_dispositions(task_dir, task, load_json(task_dir / 'evidence.json'), load_json(path))
    recorded, failed = 0, []
    if plans:
        events = [{'source_run_id': run_id, 'decisions': decisions} for run_id, decisions in plans.items()]
        try:
            append_processing_batch(task_dir, events)
            recorded = sum(len(d) for d in plans.values())
        except ValueError:
            # One run with an invalid binding must not block the others.
            for event in events:
                try:
                    append_processing_batch(task_dir, [event])
                    recorded += len(event['decisions'])
                except ValueError as exc:
                    failed.append({'source_run_id': event['source_run_id'], 'reason': str(exc)[:160]})
    return {'step': 'dispositions', 'status': 'done', 'bound_positions': recorded,
            'runs': len(plans), 'left_for_agent': skipped + failed}


def auto_link_candidates(task_dir):
    """Route unlinked candidates to the product objects they are compared with.

    The rule lives in ``candidate_scope_link`` (planned objects of the candidate's own
    query, else every compatible object when all are included). A link is a scope
    association, never a relevance decision; ambiguous candidates stay with the Agent.
    """
    import product_scope as ps
    import candidate_scope_link
    from host_triage import enabled as host_enabled
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    if not host_enabled(task) or not ps.enabled(task):
        return {'step': 'links', 'status': 'not_applicable', 'linked': 0}
    receipt = candidate_scope_link.auto_link(task_dir)
    if receipt.get('status') == 'no_candidates':
        return {'step': 'links', 'status': 'no_candidates', 'linked': 0}
    return {'step': 'links', 'status': 'done', 'linked': receipt['linked'],
            'left_for_agent': receipt.get('skipped', [])}


HANDOFF_REVIEWER = 'program:candidate-handoff-v1'


def plan_handoff(task, view, candidates):
    """Scope reviews for candidates whose sources are already reviewed and bound.

    With positioned triage every candidate has exactly its own origin country
    (or the unlocated scope) per scenario, so applicability follows from facts
    already retained: the candidate's own origin, and whether the reference-mark
    scenario was activated by an included object. Nothing is inferred beyond that.
    """
    from decision_workflow import UNLOCATED
    index = {row['candidate_id']: row for name in COLLECTIONS
             for row in (candidates.get(name, []) if isinstance(candidates, dict) else [])
             if isinstance(row, dict) and row.get('candidate_id')}
    scenarios = {row.get('scenario_id'): row for row in task.get('assessment_scenarios', []) if isinstance(row, dict)}
    active = set(task.get('execution_scenario_ids') or ['product_entry'])
    targets = {str(c).upper() for c in task.get('target_jurisdictions', [])}
    ids, reviews = [], []
    for row in view.get('rows', []):
        if row.get('handoff_state') != 'ready' or not row.get('remaining_scopes') or row['candidate_id'] not in index:
            continue
        refs = sorted({s['evidence_id'] for s in row.get('ready_sources', []) if s.get('evidence_id')})
        if not refs:
            continue
        candidate = index[row['candidate_id']]
        origin = str(candidate.get('jurisdiction') or candidate.get('office') or '').upper()
        for scope in row['remaining_scopes']:
            sid, country = scope['scenario_id'], scope['jurisdiction']
            if scenarios.get(sid, {}).get('type') == 'brand_reuse' and sid not in active:
                status, reason = 'not_applicable', '参考标识沿用情景未被任何已纳入的参考标识对象启用；本交接只登记该情景当前不适用，不是权利结论。'
            elif country == UNLOCATED or country not in targets or country != origin:
                status, reason = 'unknown', '候选来源国家（%s）未能定位到该目标国家范围；保持未定位交接，由候选分流与定位待办处理。' % (origin or '未知')
            else:
                status, reason = 'applicable', '候选来源国家 %s 即该目标范围国家，来源位置已有可追溯去向；相关性与适用细节由候选分流判断。' % origin
            reviews.append({'candidate_id': row['candidate_id'], 'scenario_id': sid, 'jurisdiction': country,
                            'applicability': status, 'reason': reason, 'evidence_refs': refs})
        ids.append(row['candidate_id'])
    return ids, reviews


def auto_candidate_handoff(task_dir):
    from candidate_handoff import enabled as handoff_enabled, project, record_batch
    from decision_workflow import triage_scope_enabled
    from host_triage import enabled as host_enabled
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    if not host_enabled(task) or not handoff_enabled(task) or not triage_scope_enabled(task):
        return {'step': 'handoff', 'status': 'not_applicable', 'handed_off': 0}
    path = task_dir / 'normalized-candidates.json'
    if not path.is_file():
        return {'step': 'handoff', 'status': 'no_candidates', 'handed_off': 0}
    candidates = load_json(path)
    ids, reviews = plan_handoff(task, project(task, load_json(task_dir / 'evidence.json'), candidates, task_dir), candidates)
    if not ids:
        return {'step': 'handoff', 'status': 'done', 'handed_off': 0}
    reason = '程序按已审来源位置与候选自身来源国家登记交接范围；不判断相关性、权利有效性或风险。'
    request = {'candidate_ids': ids, 'reviewer': HANDOFF_REVIEWER, 'reason': reason, 'scope_reviews': reviews}
    failed = []
    try:
        record_batch(task_dir, request)
        done = len(ids)
    except ValueError:
        done = 0
        for cid in ids:
            try:
                record_batch(task_dir, {**request, 'candidate_ids': [cid],
                                        'scope_reviews': [r for r in reviews if r['candidate_id'] == cid]})
                done += 1
            except ValueError as exc:
                failed.append({'candidate_id': cid, 'reason': str(exc)[:160]})
    return {'step': 'handoff', 'status': 'done', 'handed_off': done, 'left_for_agent': failed}


SELECTED_HANDOFF_REVIEWER = 'program:selected-handoff-v1'
_GAPS_BY_RIGHT = {
    'patent': ['完整权利要求与保护范围尚未读取', '当前法律状态与权利人尚未核验'],
    'utility_model': ['完整权利要求与保护范围尚未读取', '当前法律状态与权利人尚未核验'],
    'design': ['完整视图与保护范围尚未读取', '当前法律状态与权利人尚未核验'],
    'unregistered_design': ['公开事实、地域依据与权利主体尚未核验'],
    'trademark_word': ['商品服务范围与当前注册状态尚未核验', '权利人尚未核验'],
    'trademark_figurative': ['商品服务范围与当前注册状态尚未核验', '权利人尚未核验'],
    'copyright': ['作品来源、权利主体与授权关系尚未核验'],
    'trade_dress': ['来源识别、非功能性与地域依据尚未核验'],
    'enforcement': ['维权事件的原始主张、处置与来源层级尚未核验'],
}


def auto_selected_handoff(task_dir):
    """Hand every current selected decision to the specialty modules, listing what is still unverified."""
    import candidate_triage_stage as stage
    from host_triage import enabled as host_enabled
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    if not host_enabled(task) or not stage.enabled(task):
        return {'step': 'selected_handoff', 'status': 'not_applicable', 'handed_off': 0}
    from provider_utils import evidence_lock
    with evidence_lock(task_dir):
        task, evidence, candidates, _, ledger, supplement = stage._context(task_dir)
        view = stage.project(task, evidence, candidates, ledger, task_dir=task_dir, supplement=supplement)
    done, failed = 0, []
    for row in view.get('selected_pending_handoff', []):
        annotation = row['annotation']
        gaps = list(annotation.get('candidate_relation', {}).get('identity_gaps', []))
        gaps += _GAPS_BY_RIGHT.get(annotation.get('right_type'), ['来源原件与权利事实尚未核验'])
        request = {key: annotation[key] for key in stage.SCOPE}
        request.update(annotation_id=annotation['annotation_id'], evidence_refs=list(annotation['evidence_refs']),
                       reading_scope={'level': annotation['reading_level']},
                       verification_gaps=list(dict.fromkeys(gaps)), reviewer=SELECTED_HANDOFF_REVIEWER,
                       reason='入选相关性决定已登记；按该决定的已读范围交接专项核验，未完成核验事实列入 verification_gaps，不判断风险。')
        try:
            stage.record_selected_handoff(task_dir, request)
            done += 1
        except ValueError as exc:
            failed.append({'candidate_id': annotation['candidate_id'], 'reason': str(exc)[:160]})
    return {'step': 'selected_handoff', 'status': 'done', 'handed_off': done, 'left_for_agent': failed}


PROGRESS_REVIEWER = 'program:review-progress-v1'


def _progress_upstream(task, row, candidates):
    """A real, already registered event that gave rise to a planned row, or None.

    Pagination rows name the run they continue; reviewed follow-ups name the run
    they reviewed; candidate-bound actions name the candidate's own retained
    evidence. Anything else needs the Agent to cite its upstream.
    """
    basis = (row.get('discovery_scope') or {}).get('pagination_basis') or {}
    if isinstance(basis.get('source_run_id'), str) and basis['source_run_id']:
        return basis['source_run_id']
    for decision in task.get('discovery_followups', []):
        if (isinstance(decision, dict) and decision.get('query_id') == row.get('query_id')
                and isinstance(decision.get('source_run_id'), str) and decision['source_run_id']):
            return decision['source_run_id']
    cid = row.get('triage_candidate_id') or row.get('candidate_id')
    if cid:
        for name in COLLECTIONS:
            for candidate in candidates.get(name, []) if isinstance(candidates, dict) else []:
                if isinstance(candidate, dict) and candidate.get('candidate_id') == cid:
                    for source in candidate.get('sources', []):
                        if isinstance(source, dict) and source.get('evidence_id'):
                            return source['evidence_id']
    return None


def _initial_progress_entries(task, plan, evidence):
    submitted = {run.get('query_id') for run in evidence.get('source_runs', []) if isinstance(run, dict)
                 and (run.get('submission_state') == 'submitted' or run.get('source_environment') == 'local_agent_review')}
    scenarios = [row.get('scenario_id') for row in task.get('assessment_scenarios', []) if isinstance(row, dict)]
    entries = []
    for provider, rows in (plan.get('queries') or {}).items():
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or not row.get('query_id') or row['query_id'] in submitted:
                continue
            bound = [b.get('scenario_id') for b in row.get('scenario_bindings') or [] if isinstance(b, dict)]
            for scenario in bound or [row.get('scenario_id') or (scenarios[0] if len(scenarios) == 1 else None)]:
                if scenario:
                    entries.append({'query_id': row['query_id'], 'provider': provider, 'scenario_id': scenario})
    return entries


def auto_review_progress(task_dir):
    """Register planned query obligations (09A). Owners and acceptance text come from the right type."""
    import input_template as it
    import review_progress_stage_a as rp
    from host_triage import enabled as host_enabled
    from workflow_v24 import work_view_from_dir
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    if not host_enabled(task) or not rp.enabled(task):
        return {'step': 'progress', 'status': 'not_applicable', 'registered': 0}
    plan_path = task_dir / 'search-plan.json'
    if not plan_path.is_file():
        return {'step': 'progress', 'status': 'no_plan', 'registered': 0}
    plan = load_json(plan_path)
    evidence = load_json(task_dir / 'evidence.json')
    candidates_path = task_dir / 'normalized-candidates.json'
    candidates = load_json(candidates_path) if candidates_path.is_file() else {}
    rows = {row.get('query_id'): row for values in plan.get('queries', {}).values() if isinstance(values, list)
            for row in values if isinstance(row, dict)}
    first = not rp._events(evidence)
    if first:
        # While no plan is registered the dispatcher does not block (review_progress_stage_a.dispatch_block), so
        # REVIEW_PROGRESS_QUERY_NOT_PLANNED never appears and waiting for it would leave the ledger at
        # plan_required for the whole run. The initial registration therefore covers every generated plan row that
        # has not been submitted yet (an item cannot be registered retroactively), one per bound scenario.
        entries = _initial_progress_entries(task, plan, evidence)
    else:
        entries = [e for e in work_view_from_dir(task_dir).get('entries', []) if e.get('reason') == it.PROGRESS_REASON]
        from auto_refine import enabled as register_new_rows
        if register_new_rows(task):
            # A row appended later (a program refinement, a detail read) is registered as soon as it exists:
            # waiting for the runner to defer it first costs two no-progress rounds, after which the progress rule
            # cancels the query (r5d rehearsal: the second rewrites never ran).
            current = rp.ledger(task, evidence)
            known = {(item.get('provider'), item.get('query_id')) for item in current.get('items', [])
                     if item.get('kind') == 'query'}
            listed = {(e.get('provider'), e.get('query_id')) for e in entries}
            entries += [e for e in _initial_progress_entries(task, plan, evidence)
                        if (e['provider'], e['query_id']) not in known | listed]
    items, left = [], []
    for entry in entries:
        item, error = it.progress_item(task, plan, entry)
        if item is None:
            left.append({'query_id': entry.get('query_id'), 'reason': error})
            continue
        item = it.progress_defaults(item)
        if not item.get('module_ids'):
            left.append({'query_id': entry.get('query_id'), 'reason': 'NO_OWNING_MODULE_FOR_RIGHT_TYPE'})
            continue
        items.append((item, _progress_upstream(task, rows.get(entry.get('query_id')) or {}, candidates)))
    registered = 0
    if first:
        # The initial registration covers the whole generated plan; later rows need an upstream event.
        if not items:
            return {'step': 'progress', 'status': 'nothing_to_register', 'registered': 0, 'left_for_agent': left}
        request = {'kind': 'initialize', 'actor': PROGRESS_REVIEWER,
                   'reasoning': '按已生成的检索计划逐行登记唯一计划项（含适用专项与标准验收条件）；仅登记义务，不判断完成、风险或双审。',
                   'items': [item for item, _ in items]}
        rp.record_event(task_dir, request)
        registered = len(items)
        return {'step': 'progress', 'status': 'initialized', 'registered': registered, 'left_for_agent': left}
    groups = {}
    for item, upstream in items:
        if upstream is None:
            left.append({'query_id': item['query_id'], 'reason': 'UPSTREAM_EVENT_REQUIRED'})
        else:
            groups.setdefault(upstream, []).append(item)
    for upstream, group in groups.items():
        request = {'kind': 'add', 'actor': PROGRESS_REVIEWER, 'upstream_ref': upstream, 'items': group,
                   'reasoning': '新增计划行派生自已登记的上游事件 %s；仅补登唯一计划项，不判断完成、风险或双审。' % upstream}
        try:
            rp.record_event(task_dir, request)
            registered += len(group)
        except ValueError as exc:
            left.extend({'query_id': item['query_id'], 'reason': str(exc)[:160]} for item in group)
    return {'step': 'progress', 'status': 'added' if registered else 'nothing_added', 'registered': registered,
            'left_for_agent': left}


OPERATION_REVIEWER = 'program:operation_reviews'
BOUNDED_STOP_REVIEWER = 'program:bounded_stop'
# Public single-page routes whose bounded scope discovery_semantics can end without a coverage claim.
SINGLE_PAGE_ROUTES = {'serper_web': {'search'}, 'serper_images': {'images'},
                      'serpapi_google_patents': {'search'}, 'epo_ops': {'search'},
                      'serpapi_google_lens': {'image_search'}}


def _discovery_rows(plan):
    return [(provider, row) for provider, rows in plan.get('queries', {}).items() if isinstance(rows, list)
            for row in rows if isinstance(row, dict) and row.get('action_purpose') == 'discovery'
            and row.get('operation') in SINGLE_PAGE_ROUTES.get(provider, set())]


def _bounded_single_page(row):
    """The frozen plan row itself asks for exactly one page; nothing is inferred from the response."""
    scope = row.get('discovery_scope')
    return (isinstance(scope, dict) and scope.get('mode') == 'bounded' and scope.get('max_pages') == 1
            and scope.get('review_all_returned') is True and row.get('page', 1) in (None, 1))


def _request_echo(provider, row, run, task_dir):
    """Field effect as a retained fact: the request the adapter actually sent (or the response's echo of it)
    equals the plan row. Routes without a retained echo are not provable here."""
    from common import resolve_retained_path, sha256_json
    params = run.get('request_params') if isinstance(run.get('request_params'), dict) else {}
    if provider in {'serper_web', 'serper_images'}:
        keys = ('q', 'gl', 'hl', 'num')
        return (all(key in row and params.get(key) == row[key] for key in keys), 'request_params:' + ','.join(keys))
    if provider == 'epo_ops':
        coverage = (run.get('metadata') or {}).get('search_coverage') or {}
        ok = (params.get('q') == row.get('q') and params.get('range') == row.get('range')
              and (run.get('status') == 'no_result' or coverage.get('range_verified') is True))
        return ok, 'request_params:q,range+range_verified'
    if provider == 'serpapi_google_patents':
        try:
            raw = load_json(resolve_retained_path(task_dir, run['raw_paths'][0], expected_sha256=run.get('payload_digest', '')))
        except (ValueError, OSError, KeyError, IndexError, TypeError):
            return False, 'retained_response_unreadable'
        echo = raw.get('search_parameters') if isinstance(raw, dict) else None
        if not isinstance(echo, dict) or echo.get('engine') != 'google_patents' or echo.get('q') != row.get('q'):
            return False, 'search_parameters'
        ok = all(key not in row or str(echo.get(key)) == str(row[key]) for key in ('num', 'country', 'type'))
        # r5d20: the date floor of a recall task is checked when the response echoes it
        ok = ok and all(key not in row or key not in echo or str(echo.get(key)) == str(row[key]) for key in ('after', 'sort'))
        return ok, 'search_parameters:engine,q,num,country,type'
    return False, 'no_retained_request_echo_for_route'


def _exact_acceptance(task, evidence, provider, row, run, task_dir):
    """The 03C acceptance proof for this exact retained response: the persisted one when the response was the
    first of its operation, else the same acceptance function re-run on this response while the persisted
    acceptance of the operation is still current. Never HTTP success."""
    from common import sha256_json
    from source_operation import current_operation_acceptance, record_operation_acceptance
    run_sha, row_sha = sha256_json(run), sha256_json(row)
    exact = [item for item in evidence.get('operation_acceptances', []) if isinstance(item, dict)
             and isinstance(item.get('proof'), dict) and item['proof'].get('source_run_id') == run.get('run_id')
             and item['proof'].get('source_run_sha256') == run_sha and item['proof'].get('plan_entry_sha256') == row_sha]
    if exact:
        if current_operation_acceptance(task, {**evidence, 'operation_acceptances': exact}, provider, row, task_dir):
            return 'persisted', None
        return None, 'OPERATION_ACCEPTANCE_NOT_CURRENT'
    if not current_operation_acceptance(task, evidence, provider, row, task_dir):
        return None, 'OPERATION_ACCEPTANCE_MISSING'
    entries = [entry for group in evidence.get('collections', {}).values() if isinstance(group, list)
               for entry in group if isinstance(entry, dict) and entry.get('source_run_id') == run.get('run_id')
               and isinstance(entry.get('trusted_api_record'), dict)]
    if len(entries) != 1:
        return None, 'TRUSTED_RECEIPT_ENTRY_NOT_UNIQUE'
    try:
        proof = record_operation_acceptance(task_dir, task, {**evidence, 'operation_acceptances': []}, row, run, entries[0])
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return None, 'OPERATION_ACCEPTANCE_RECOMPUTE_FAILED:' + str(exc)[:80]
    if (not isinstance(proof, dict) or proof.get('state') != 'accepted'
            or (proof.get('proof') or {}).get('source_run_sha256') != run_sha):
        return None, 'OPERATION_ACCEPTANCE_RECOMPUTE_FAILED'
    return 'recomputed', None


def plan_operation_reviews(task_dir, task, plan, evidence):
    """Accepted 03C reviews the program can prove for single-page public runs; everything else is listed."""
    import source_operation as so
    from runtime_v24 import source_files_complete
    reviewed = {(item.get('provider'), item.get('query_id'), item.get('source_run_id'))
                for item in task.get('source_operation_reviews', []) if isinstance(item, dict)}
    requests, left = [], []
    for provider, row in _discovery_rows(plan):
        for run in so._runs(evidence, provider, row):
            unit = {'provider': provider, 'query_id': row.get('query_id'), 'source_run_id': run.get('run_id')}
            if (provider, row.get('query_id'), run.get('run_id')) in reviewed:
                continue
            if not _bounded_single_page(row):
                left.append({**unit, 'reason': 'NOT_A_FROZEN_SINGLE_PAGE_ROW'})
                continue
            if not source_files_complete(task_dir, evidence, run):
                left.append({**unit, 'reason': 'SOURCE_FILES_INCOMPLETE'})
                continue
            echoed, echo_basis = _request_echo(provider, row, run, task_dir)
            if not echoed:
                left.append({**unit, 'reason': 'REQUEST_ECHO_UNPROVEN:' + echo_basis})
                continue
            basis, error = _exact_acceptance(task, evidence, provider, row, run, task_dir)
            if basis is None:
                left.append({**unit, 'reason': error})
                continue
            basis_text = ('该回执的精确验收凭据已持久化于 operation_acceptances' if basis == 'persisted'
                          else '该操作的首次回执验收凭据仍然有效，且同一验收函数对本回执重算一致')
            requests.append({**unit, 'reviewer': OPERATION_REVIEWER, 'decision': 'accepted',
                'reason': ('程序验收：留存回执与计划行按 run／plan／响应哈希绑定（%s）；请求参数回显一致（%s）；'
                           '计划行为冻结的单页有界检索（max_pages=1），仅验收该页回执，不验证全集、分页能力或权利状态；'
                           '不作相关性或风险判断。' % (basis_text, echo_basis)),
                'checks': {'request_response_binding': True, 'field_effect': 'verified', 'pagination': 'single_page',
                           'known_number': 'not_applicable', 'original_content': 'not_applicable',
                           'current_status': 'not_applicable'}})
    return requests, left


def _record_operation_batch(task_dir, requests):
    """Write through the 03C recorder (its own validation, lock and receipts); one bad request must not block the rest."""
    import os
    import tempfile
    from record_source_operation import record

    def submit(payload):
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
        try:
            json.dump(payload, handle, ensure_ascii=False)
            handle.close()
            return record(task_dir, Path(handle.name))
        finally:
            handle.close()
            os.unlink(handle.name)
    failed = []
    try:
        return submit({'reviews': requests})['recorded_count'], failed
    except ValueError:
        recorded = 0
        for request in requests:
            try:
                submit(request)
                recorded += 1
            except ValueError as exc:
                failed.append({key: request[key] for key in ('provider', 'query_id', 'source_run_id')}
                              | {'reason': str(exc)[:160]})
        return recorded, failed


def auto_operation_reviews(task_dir):
    """Accept the retained single-page public responses whose exact 03C proof the program can show (no judgment)."""
    import source_operation as so
    from host_triage import enabled as host_enabled
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    if not host_enabled(task) or not so.enabled(task) or task.get('retrieval_workflow_revision') != 'api-first-v3':
        return {'step': 'operation_reviews', 'status': 'not_applicable', 'recorded': 0}
    plan_path = task_dir / 'search-plan.json'
    if not plan_path.is_file():
        return {'step': 'operation_reviews', 'status': 'no_plan', 'recorded': 0}
    plan = load_json(plan_path)
    evidence = load_json(task_dir / 'evidence.json')
    try:
        so.verify(task, plan, evidence, task_dir)
    except ValueError as exc:
        return {'step': 'operation_reviews', 'status': 'existing_reviews_invalid', 'recorded': 0,
                'left_for_agent': [{'reason': str(exc)[:160]}]}
    requests, left = plan_operation_reviews(task_dir, task, plan, evidence)
    recorded, failed = _record_operation_batch(task_dir, requests) if requests else (0, [])
    return {'step': 'operation_reviews', 'status': 'done', 'recorded': recorded, 'left_for_agent': left + failed}


def _bounded_stop_texts(provider, run):
    coverage = (run.get('metadata') or {}).get('search_coverage') or {}
    count = coverage.get('retrieved_hits')
    reason = ('程序默认收尾：该路线为冻结的单页有界公开检索（%s，max_pages=1），本页实际返回的 %s 条已全部登记并有当前分流去向；'
              '该页之外的排名结果在本任务内无法继续取得。本记录只结束该检索表达的有界范围，不是覆盖声明，也不判断相关性或风险；'
              'Agent 可事后改判。' % (provider, count))
    result_reason = ('已取回并处理单页 %s 条结果；来源未给出可核实的全集总量或已截断，方向线索在该页之外的覆盖情况未核实，'
                     'problem_covered 置为 false，next_action 为 awaiting_capability。' % count)
    followup = ('程序默认收尾：本回执全部位置已有当前分流去向，按有界单页路线停止本发现表达（stop_bounded_discovery）；'
                '不宣称完整覆盖、不排除风险；已入选候选的核验与其他检索表达不受影响。')
    return reason, result_reason, followup


def plan_bounded_stops(task_dir, task, plan, evidence, candidates, ledger, supplement):
    """Units whose after-result review the program can write: bounded single-page public runs with a current
    direction and before review and no after review yet. Nothing here is a proof; the proof is run per unit."""
    import discovery_semantics as ds
    import input_template as it
    from api_first_planning import current_followup_review, triage_digest
    from common import sha256_json
    units, left = [], []
    for provider, row in _discovery_rows(plan):
        if not _bounded_single_page(row):
            continue
        runs = [run for run in evidence.get('source_runs', []) if isinstance(run, dict)
                and run.get('provider') == provider and run.get('query_id') == row.get('query_id')
                and run.get('plan_entry_sha256') == sha256_json(row) and run.get('status') in {'success', 'no_result'}]
        if not runs:
            continue
        run = runs[-1]
        for country in sorted(ds.row_jurisdictions(provider, row)):
            for ref in row.get('product_dependencies', []):
                sid, direction_id = ref.get('scenario_id'), ref.get('direction_id')
                if sid not in task.get('execution_scenario_ids', []) or not direction_id:
                    continue
                unit = {'provider': provider, 'query_id': row['query_id'], 'source_run_id': run.get('run_id'),
                        'scenario_id': sid, 'jurisdiction': country, 'right_type': row.get('right_type'),
                        'direction_id': direction_id}
                direction = ds.current(task, plan, evidence, stage='direction', scenario_id=sid, jurisdiction=country,
                                       right_type=row.get('right_type'), task_dir=task_dir)
                if direction is None:
                    left.append({**unit, 'reason': 'DISCOVERY_DIRECTION_REVIEW_REQUIRED'})
                    continue
                before = ds.current(task, plan, evidence, stage='before', scenario_id=sid, jurisdiction=country,
                                    right_type=row.get('right_type'), direction_id=direction_id, provider=provider,
                                    row=row, task_dir=task_dir)
                if before is None or ds.bound_direction_sha256(task, plan, evidence, before, direction, task_dir) is None:
                    left.append({**unit, 'reason': 'DISCOVERY_EXPRESSION_REVIEW_REQUIRED'})
                    continue
                if before.get('semantic_fit') == 'mismatch':
                    left.append({**unit, 'reason': 'DISCOVERY_EXPRESSION_MISMATCH'})
                    continue
                if ds.current(task, plan, evidence, stage='after', scenario_id=sid, jurisdiction=country,
                              right_type=row.get('right_type'), direction_id=direction_id, provider=provider,
                              row=row, task_dir=task_dir) is not None:
                    continue  # already reviewed (by a person, the host or an earlier run of this step)
                basis = next((item for item in direction.get('directions', []) if item.get('direction_id') == direction_id), {})
                uncovered = sorted(set(before.get('uncovered_clues', [])) | set(basis.get('clue_ids', [])))
                if not uncovered:
                    left.append({**unit, 'reason': 'UNCOVERED_CLUES_NOT_COMPUTABLE'})
                    continue
                template, guide = it.after_template(task, plan, evidence, {**unit, 'source_run_id': run.get('run_id')})
                if template is None or not guide.get('evidence_ids_of_this_run'):
                    left.append({**unit, 'reason': 'RUN_EVIDENCE_MISSING' if template else str(guide)})
                    continue
                reason, result_reason, followup_reason = _bounded_stop_texts(provider, run)
                request = {**template, 'reviewer': BOUNDED_STOP_REVIEWER, 'reason': reason,
                           'evidence_refs': list(guide['evidence_ids_of_this_run']), 'original_problem_checked': True,
                           'problem_covered': False, 'result_reason': result_reason, 'uncovered_clues': uncovered,
                           'excluded_by_narrowing': [], 'next_action': 'awaiting_capability'}
                current = current_followup_review(task, row, run.get('run_id'))
                followup = None
                if current is None or current.get('outcome') != 'stop_bounded_discovery':
                    try:
                        digest = triage_digest(task, evidence, candidates, ledger, supplement, query_id=row['query_id'])
                    except (ValueError, KeyError, TypeError) as exc:
                        left.append({**unit, 'reason': 'TRIAGE_DIGEST_UNAVAILABLE:' + str(exc)[:80]})
                        continue
                    followup = {'query_id': row['query_id'], 'source_run_id': run.get('run_id'),
                                'reason': followup_reason, 'reviewer': BOUNDED_STOP_REVIEWER,
                                'evidence_ids': list(guide['evidence_ids_of_this_run']), 'triage_digest': digest,
                                'outcome': 'stop_bounded_discovery', 'blocker': None}
                units.append({**unit, 'row': row, 'run': run, 'request': request, 'followup': followup})
    return units, left


def _bounded_scope_proof(task, plan, evidence, candidates, ledger, supplement, task_dir, unit, after):
    """The same proof the work view uses to end a bounded public scope; None when it does not hold."""
    import discovery_semantics as ds
    if after is None:
        return None
    proof = ds._current_public_ranked_scope_wait(task, plan, evidence, candidates, ledger, supplement, task_dir,
                                                 unit['provider'], unit['row'], after, unit['run'])
    if not isinstance(proof, dict) or proof.get('missing_operation_review'):
        return None
    return proof


def _restore_bytes(path, data):
    import os
    temp = path.with_name(path.name + '.rollback')
    temp.write_bytes(data)
    os.replace(temp, path)


def auto_bounded_stop(task_dir):
    """Close the after-result stage of bounded single-page public runs with a program review that claims no
    coverage, then prove the scope limit exactly as the work view will; otherwise write nothing."""
    import discovery_semantics as ds
    import record_discovery_semantics as rds
    import record_discovery_review as rdr
    from api_first_planning import prepare_review
    from coverage_v3 import public_discovery_enabled
    from copy import deepcopy
    from host_triage import enabled as host_enabled
    from workflow_v24 import scenario_supplement
    task_dir = Path(task_dir).resolve()
    task = load_json(task_dir / 'task.json')
    if not host_enabled(task) or not ds.enabled(task) or not public_discovery_enabled(task):
        return {'step': 'bounded_stop', 'status': 'not_applicable', 'closed_count': 0}
    plan_path = task_dir / 'search-plan.json'
    if not plan_path.is_file():
        return {'step': 'bounded_stop', 'status': 'no_plan', 'closed_count': 0}
    plan = load_json(plan_path)
    evidence = load_json(task_dir / 'evidence.json')
    candidates_path = task_dir / 'normalized-candidates.json'
    candidates = load_json(candidates_path) if candidates_path.is_file() else {}
    ledger_path = task_dir / 'materiality-annotations.json'
    ledger = load_json(ledger_path) if ledger_path.is_file() else {}
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    units, left = plan_bounded_stops(task_dir, task, plan, evidence, candidates, ledger, supplement)
    closed = []
    local_errors = (ValueError, OSError, KeyError, TypeError)
    for unit in units:
        task = load_json(task_dir / 'task.json')
        evidence = load_json(task_dir / 'evidence.json')
        scope = {key: unit[key] for key in ('scenario_id', 'jurisdiction', 'right_type', 'direction_id')}
        summary = {key: unit[key] for key in ('provider', 'query_id', 'source_run_id', *scope)}
        # 1. the whole chain in memory first: event, follow-up review and the scope proof
        task_copy, evidence_copy = deepcopy(task), deepcopy(evidence)
        try:
            event, new = rds._prepare(task_copy, plan, evidence_copy, task_dir, unit['request'])
            if new:
                task_copy.setdefault('discovery_semantic_reviews', []).append(event)
            if unit['followup'] is not None:
                prepare_review(task_dir, task_copy, plan, evidence_copy, unit['row'],
                               {key: value for key, value in unit['followup'].items() if key != 'query_id'},
                               candidates=candidates, ledger=ledger, supplement=supplement)
            proof = _bounded_scope_proof(task_copy, plan, evidence_copy, candidates, ledger, supplement, task_dir, unit, event)
        except local_errors as exc:
            left.append({**summary, 'reason': str(exc)[:160]})
            continue
        if proof is None:
            left.append({**summary, 'reason': 'BOUNDED_SCOPE_PROOF_FAILED'})
            continue
        # 2. persist through the recorders, then prove again from disk; roll back when that fails
        snapshot = {name: (task_dir / name).read_bytes() for name in ('task.json', 'evidence.json')}
        receipt = task_dir / 'raw' / 'discovery_semantics' / (event['review_id'] + '.json')
        receipt_existed = receipt.exists()
        try:
            if new:
                rds.record_batch(task_dir, [unit['request']])
            if unit['followup'] is not None:
                rdr.record_batch(task_dir, [unit['followup']])
            task_now, evidence_now = load_json(task_dir / 'task.json'), load_json(task_dir / 'evidence.json')
            after_now = ds.current(task_now, plan, evidence_now, stage='after', provider=unit['provider'],
                                   row=unit['row'], task_dir=task_dir, **scope)
            proof_now = _bounded_scope_proof(task_now, plan, evidence_now, candidates, ledger, supplement, task_dir,
                                             unit, after_now)
            if proof_now is None or after_now.get('reviewer') != BOUNDED_STOP_REVIEWER:
                raise ValueError('PERSISTED_PROOF_FAILED')
        except local_errors as exc:
            for name, data in snapshot.items():
                _restore_bytes(task_dir / name, data)
            if new and not receipt_existed and receipt.exists():
                receipt.unlink()
            left.append({**summary, 'reason': 'ROLLED_BACK:' + str(exc)[:140]})
            continue
        capability = ds._current_bounded_capability_wait(task_now, plan, evidence_now, candidates, ledger, supplement,
                                                         task_dir, unit['provider'], unit['row'], after_now, unit['run'])
        closed.append({**summary, 'after_review_id': after_now.get('review_id'),
                       'followup_recorded': unit['followup'] is not None,
                       'retrieval_scope_kind': proof_now.get('retrieval_scope_kind'),
                       'bounded_capability_wait': capability is not None})
    return {'step': 'bounded_stop', 'status': 'done', 'closed_count': len(closed), 'closed': closed,
            'left_for_agent': left}


STEPS = {'progress': auto_review_progress, 'dispositions': auto_bind_dispositions, 'links': auto_link_candidates,
         'handoff': auto_candidate_handoff, 'selected_handoff': auto_selected_handoff,
         'operation_reviews': auto_operation_reviews, 'bounded_stop': auto_bounded_stop}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--steps', default=','.join(STEPS), help='comma separated: ' + ','.join(STEPS))
    args = parser.parse_args(argv)
    names = [name.strip() for name in args.steps.split(',') if name.strip()]
    unknown = [name for name in names if name not in STEPS]
    if unknown:
        parser.error('unknown step: ' + ','.join(unknown))
    results = [STEPS[name](args.task_dir) for name in names]
    print(json.dumps({'steps': results}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

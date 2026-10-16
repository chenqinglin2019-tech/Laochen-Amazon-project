#!/usr/bin/env python3
"""Carry out the result reviewer's "search again" verdict (new tasks with ``discovery_refinement_revision``).

A discovery query whose after-result review says the question is not answered (``refine`` / ``fallback`` /
``awaiting_capability`` without a provable page limit) used to wait for the Agent to type a follow-up by hand
(r5c real run: 8 open items, the core patent never searched with a usable expression). This step does it:

* refinement: the next unused query term of the same discovery purpose (the product understanding lists them
  in order of confidence; listing promotion words are already removed) through the ordinary
  ``api_first_planning.append_followup`` contract, reviewer ``program:auto-refine``. A patent refinement stays on
  the parent's engine for the first rewrite and moves to SerpApi Google Patents (full text, native country
  filter) for the second; a Serper patents parent always moves to SerpApi (its ``country:`` operator is ignored);
* when no rewrite is possible (``max_refinement_rounds`` reached, no unused applicable term, or no source
  budget) the query gets a bounded stop review (``stop_bounded_discovery``) and stays open as a disclosed
  limitation: remaining recall unverified, never a coverage claim.

The before-review, dispatch, triage and after-review of a new refinement row are the ordinary pipeline steps.
``discovery_semantics`` treats a reviewed row whose follow-up exists as carried by that follow-up, and a row
whose rewrites are exhausted and stopped as a bounded limitation (see ``refinement_exhausted_wait``).

usage: auto_refine.py --task-dir RUN [--dry-run]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json

REVISION = 'auto-refine-v1'
REVIEWER = 'program:auto-refine'
REPLAN_REASON = 'DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED'
FOLLOWUP_ROLES = ('refinement', 'fallback')
TERM_KINDS = {'patent': ('function', 'structural_feature', 'product', 'category'),
              'utility_model': ('function', 'structural_feature', 'product', 'category'),
              'design': ('design', 'product', 'category')}
GOOGLE_PATENTS = 'serpapi_google_patents'
# SerpApi also reads every selected candidate's exact record (status, owner, claims, drawings); a rewrite never
# spends the calls those reads need (r5d rehearsal: three rewrites left four selected patents without a record).
DETAIL_RESERVE = {'serpapi': 4}


def enabled(task) -> bool:
    return isinstance(task, dict) and task.get('discovery_refinement_revision') == REVISION


def cancelled_unsent(plan, evidence, other) -> bool:
    """True for a planned row that was cancelled and never submitted."""
    from common import sha256_json
    digest = sha256_json(other)
    cancelled = any(isinstance(item, dict) and item.get('query_id') == other.get('query_id')
                    and item.get('plan_entry_sha256') == digest and item.get('status') == 'cancelled'
                    for item in plan.get('execution_dispositions') or [])
    submitted = any(run.get('query_id') == other.get('query_id') and run.get('submission_state') != 'not_submitted'
                    for run in (evidence or {}).get('source_runs', []) if isinstance(run, dict))
    return cancelled and not submitted


def has_child(plan, row, evidence=None) -> bool:
    """A refinement or fallback of this exact query is already planned.

    With ``evidence`` (r5d7), a child cancelled before it was ever submitted does not count: it carries nothing, and
    counting it kept the parent open for good (B0GLNPC6K8: a triage change cancelled the planned rewrite, the parent
    then waited at checkpoint 2 with neither a stop nor a new rewrite)."""
    def counts(other):
        if evidence is None:
            return True
        from common import sha256_json
        digest = sha256_json(other)
        cancelled = any(isinstance(item, dict) and item.get('query_id') == other.get('query_id')
                        and item.get('plan_entry_sha256') == digest and item.get('status') == 'cancelled'
                        for item in plan.get('execution_dispositions') or [])
        submitted = any(run.get('query_id') == other.get('query_id') and run.get('submission_state') != 'not_submitted'
                        for run in evidence.get('source_runs', []) if isinstance(run, dict))
        return not cancelled or submitted
    return any(other.get('parent_query_id') == row.get('query_id') and other.get('discovery_role') in FOLLOWUP_ROLES
               and counts(other)
               for rows in (plan.get('queries') or {}).values() if isinstance(rows, list) for other in rows)


def _lineage(plan, row):
    purpose = row.get('discovery_intent_id')
    return [(provider, other) for provider, rows in (plan.get('queries') or {}).items() if isinstance(rows, list)
            for other in rows if purpose and other.get('discovery_intent_id') == purpose]


def _max_rounds(task) -> int:
    from api_first_planning import policy_limit
    import precision
    limit = policy_limit(task, 'max_refinement_rounds', 2, minimum=0)
    # r5d21 (precision-v1): one rewrite per purpose - the second generation of rewrites was the idle tail of every run
    return min(limit, 1) if precision.enabled(task) else limit


def _providers(task, provider, row):
    """Engines for the next rewrite, in order of preference."""
    from common import serpapi_free_enabled
    if row.get('right_type') in {'patent', 'utility_model'} and serpapi_free_enabled(task):
        if provider == 'serper_patents':
            return [GOOGLE_PATENTS]
        if row.get('refinement_round', 0) >= 1 and provider != GOOGLE_PATENTS:
            return [GOOGLE_PATENTS, provider]
    return [provider]


def _budget_left(task, plan, evidence, provider) -> bool:
    from api_first_planning import _account, _capacity_rows, _limits
    account, limits = _account(provider), _limits(task)
    if account not in limits:
        return True
    used = sum(_account(p) == account for p, _ in _capacity_rows(task, plan, evidence))
    return used + 1 + DETAIL_RESERVE.get(account, 0) <= limits[account]


def _clean_term(term):
    return {key: term[key] for key in ('value', 'kind', 'derived_from', 'language', 'strategy', 'recall_group')
            if term.get(key)}


def _reviewer_term(task, row):
    """r5d20 recall tasks: the latest result review's own refine_query as a term of the parent's purpose, or None."""
    import recall
    if not recall.enabled(task) or row.get('right_type') not in recall.GROUPS:
        return None
    rows = [event for event in task.get('discovery_semantic_reviews', []) if isinstance(event, dict)
            and event.get('stage') == 'after' and event.get('query_id') == row.get('query_id')]
    proposal = (rows[-1].get('refine_query') if rows and rows[-1].get('next_action') == 'refine' else None)
    parsed = recall.parse_refine_query(proposal)
    sources = row.get('derived_from') or []
    if not parsed or not sources:
        return None
    right = row['right_type']
    import precision
    if precision.enabled(task) and (right == 'design' or recall.phrases_enabled(task)):
        # r5d21: a category name the understanding marked broad floods a relevance-ranked design search (run B0GLNPC6K8:
        # the reviewer's "pet toy" returned 100 designs titled "Pet toy" and no teaser); only specific names remain.
        # r5d25 (title-phrases tasks): a utility rewrite never brings back an upper category name either
        broad = (precision.broad_names(task) if right == 'design'
                 else set((recall.recorded_levels(task) or {}).get('upper', [])))
        names = [name for name in parsed[0] if name.lower() not in broad]
        if not names:
            return None
        parsed = (names, parsed[1])
    return {'value': recall.refine_value(right, *parsed), 'kind': 'design' if right == 'design' else 'function',
            'derived_from': sources[0], 'language': 'en', 'strategy': 'boolean', 'recall_group': right}


def options(task, plan, evidence, provider, row) -> list:
    """[(provider, term)] rewrites still possible for this query, best first."""
    from api_first_planning import task_params
    from workflow_v24 import _applicable, _dimension, _target_language_compatible
    import product_scope as ps
    if row.get('refinement_round', 0) >= _max_rounds(task):
        return []
    right, country = row.get('right_type'), row.get('jurisdiction')
    kinds = TERM_KINDS.get(right)
    if not kinds or row.get('search_dimension') not in (None, 'text'):
        return []
    lineage = _lineage(plan, row)
    parent_sources = set(row.get('derived_from') or [])
    terms = []
    import recall
    group = row.get('right_type') if recall.enabled(task) and row.get('right_type') in recall.GROUPS else None
    proposal = _reviewer_term(task, row)
    if proposal is not None and (not ps.enabled(task) or ps.term_allowed(task, proposal, right)):
        terms.append(proposal)
    for term in plan.get('terms') or []:
        if group is not None and term.get('recall_group') != group:
            continue          # r5d20: a recall purpose is rewritten only with its own right's concept groups
        if (not isinstance(term, dict) or term.get('kind') not in kinds or term.get('_triage_decision')
                or not str(term.get('value') or '').strip() or not str(term.get('derived_from') or '').startswith('product')
                and not str(term.get('derived_from') or '').startswith('images[')):
            continue
        if _dimension(term) != 'text' or not _applicable(term, right, task=task):
            continue
        if not _target_language_compatible(term, country):
            continue
        if ps.enabled(task) and not ps.term_allowed(task, term, right):
            continue
        terms.append(_clean_term(term))
    # Rewrites from the same clue first, then the other confirmed clues, each in the listed order (the reviewer's
    # own proposal, when there is one, stays first).
    terms.sort(key=lambda term: (term is not proposal, term['derived_from'] not in parent_sources))
    # An expression that already ran on an engine for any purpose returns the same page again (r5d real run:
    # "lid retaining strap" was refined into the "lid securing strap" query that had already returned).
    ran = {(name, other.get('q')) for name, rows in (plan.get('queries') or {}).items() if isinstance(rows, list)
           for other in rows if isinstance(other, dict) and other.get('q')}
    result = []
    for engine in _providers(task, provider, row):
        if not _budget_left(task, plan, evidence, engine):
            continue
        for term in terms:
            try:
                compiled = {other_provider: task_params(task, other_provider, term, country, right,
                                                            epo_query_revision=task.get('epo_query_revision'))['q']
                            for other_provider in {engine, *(p for p, _ in lineage)}}
            except (ValueError, KeyError, TypeError):
                continue
            if any(compiled.get(p) == other.get('q') for p, other in lineage):
                continue          # this expression already ran for the purpose (on any engine)
            if (engine, compiled.get(engine)) in ran:
                continue
            if (engine, term) not in result:
                result.append((engine, term))
    return result


def exhausted(task, plan, evidence, provider, row) -> bool:
    return not has_child(plan, row, evidence) and not options(task, plan, evidence, provider, row)


def _linked_evidence(evidence, run_id):
    return [entry.get('evidence_id') for values in (evidence.get('collections') or {}).values() if isinstance(values, list)
            for entry in values if isinstance(entry, dict) and entry.get('source_run_id') == run_id and entry.get('evidence_id')]


def _after_reason(task, row):
    rows = [event for event in task.get('discovery_semantic_reviews', []) if isinstance(event, dict)
            and event.get('stage') == 'after' and event.get('query_id') == row.get('query_id')]
    return str(rows[-1].get('result_reason') or rows[-1].get('reason') or '')[:240] if rows else ''


ANSWERED = frozenset({'success', 'no_result'})


def _answered_run(evidence, provider, row):
    from common import sha256_json
    runs = [run for run in evidence.get('source_runs', []) if run.get('provider') == provider
            and run.get('query_id') == row.get('query_id') and run.get('plan_entry_sha256') == sha256_json(row)
            and run.get('status') in ANSWERED and run.get('submission_state') != 'not_submitted']
    return runs[-1] if runs else None


def close_carried_parents(root, summary):
    """A refined expression's bounded scope ends once its follow-up has returned: the coverage contract needs one
    review per returned response, and the purpose continues in the follow-up (which has its own review). Recording
    it earlier would end the purpose before the follow-up is sent (r5d rehearsal). Never a coverage claim."""
    from api_first_planning import append_followup, current_followup_review, triage_digest
    from workflow_v24 import scenario_supplement
    root = Path(root)
    task, plan, evidence = (load_json(root / name) for name in ('task.json', 'search-plan.json', 'evidence.json'))
    rows = [(provider, row) for provider, values in (plan.get('queries') or {}).items() if isinstance(values, list)
            for row in values if isinstance(row, dict) and row.get('action_purpose') == 'discovery']
    for provider, row in rows:
        children = [(p, child) for p, child in rows if child.get('parent_query_id') == row.get('query_id')
                    and child.get('discovery_role') in FOLLOWUP_ROLES]
        run = _answered_run(evidence, provider, row)
        if not children or run is None or not any(_answered_run(evidence, p, child) for p, child in children):
            continue
        current = current_followup_review(task, row, run['run_id'])
        if current is not None and current.get('outcome') == 'stop_bounded_discovery':
            continue
        candidates = load_json(root / 'normalized-candidates.json')
        ledger = load_json(root / 'materiality-annotations.json')
        supplement = scenario_supplement(root, task=task, evidence=evidence)
        request = {'role': 'review', 'outcome': 'stop_bounded_discovery', 'parent_query_id': row['query_id'],
                   'source_run_id': run['run_id'], 'evidence_ids': _linked_evidence(evidence, run['run_id']),
                   'triage_digest': triage_digest(task, evidence, candidates, ledger, supplement, query_id=row['query_id']),
                   'reviewer': REVIEWER,
                   'reason': ('结果审阅判定原问题未覆盖，已按审阅意见追加的细化查询 %s 已返回结果；本表达的有界检索到此结束，'
                              '同一调查目的由细化查询及其结果审阅继续。不是覆盖声明。'
                              % '、'.join(child['query_id'] for _, child in children))}
        try:
            append_followup(root, request)
            summary['parents_closed'].append(row['query_id'])
        except ValueError as exc:
            summary['skipped'].append({'query_id': row['query_id'], 'reason': 'PARENT_STOP:' + str(exc)[:160]})
        task, evidence = load_json(root / 'task.json'), load_json(root / 'evidence.json')


def pending(root):
    from workflow_v24 import work_view_from_dir
    seen, result = set(), []
    for entry in work_view_from_dir(Path(root)).get('entries', []):
        if (entry.get('reason') != REPLAN_REASON or not entry.get('source_run_id') or not entry.get('query_id')
                or entry.get('historical_expression_review_missing') or entry['query_id'] in seen):
            continue
        seen.add(entry['query_id'])
        result.append(entry)
    return result


def run(root, *, dry_run=False):
    from api_first_planning import append_followup, triage_digest
    from workflow_v24 import plan_row_index, scenario_supplement
    root = Path(root)
    task = load_json(root / 'task.json')
    if not enabled(task):
        return {'status': 'not_enabled', 'refined': [], 'stopped': [], 'skipped': []}
    summary = {'status': 'done', 'refined': [], 'stopped': [], 'skipped': [], 'parents_closed': []}
    if not dry_run:
        close_carried_parents(root, summary)
    for entry in pending(root):
        task, plan, evidence = (load_json(root / name) for name in ('task.json', 'search-plan.json', 'evidence.json'))
        candidates = load_json(root / 'normalized-candidates.json')
        ledger = load_json(root / 'materiality-annotations.json')
        rows = plan_row_index(plan).get(entry['query_id'], [])
        if len(rows) != 1 or has_child(plan, rows[0][1], evidence):
            continue
        provider, row = rows[0]
        refs = _linked_evidence(evidence, entry['source_run_id'])
        supplement = scenario_supplement(root, task=task, evidence=evidence)
        digest = triage_digest(task, evidence, candidates, ledger, supplement, query_id=row['query_id'])
        common = {'parent_query_id': row['query_id'], 'source_run_id': entry['source_run_id'], 'evidence_ids': refs,
                  'triage_digest': digest, 'reviewer': REVIEWER}
        reviewed = _after_reason(task, row)
        done, errors = False, []
        possible = options(task, plan, evidence, provider, row)
        for engine, term in possible:
            request = {**common, 'role': 'refinement', 'provider': engine, 'term': term, 'reason_code': 'refine_scope',
                       'reason': ('结果审阅判定原问题未覆盖（%s）。程序按审阅意见改用同一调查目的的下一表达"%s"再检索一次，'
                                  '原查询、结果与分流全部保留。' % (reviewed or '见结果审阅', term['value']))}
            if dry_run:
                summary['refined'].append({'query_id': row['query_id'], 'provider': engine, 'term': term['value'], 'dry_run': True})
                done = True
                break
            try:
                child = append_followup(root, request)
            except ValueError as exc:
                errors.append('%s:%s' % (engine, str(exc)[:160]))
                continue
            summary['refined'].append({'query_id': row['query_id'], 'refinement_query_id': child['query_id'],
                                       'provider': engine, 'term': term['value']})
            done = True
            break
        if done:
            continue
        if possible:
            # A rewrite exists but the follow-up contract refused it now (for example a card still untriaged):
            # never stop a purpose that can still be searched; the next round tries again.
            summary['skipped'].append({'query_id': row['query_id'], 'reason': 'REFINEMENT_NOT_ACCEPTED_YET',
                                       'refinement_errors': errors})
            continue
        request = {**common, 'role': 'review', 'outcome': 'stop_bounded_discovery',
                   'reason': ('结果审阅判定原问题未覆盖（%s）；本调查目的的细化轮次、可用表达或来源额度已用尽，按有界检索停止。'
                              '剩余召回未核实，作为证据限制披露，不表示无相关权利。' % (reviewed or '见结果审阅'))}
        if dry_run:
            summary['stopped'].append({'query_id': row['query_id'], 'dry_run': True})
            continue
        try:
            append_followup(root, request)
            summary['stopped'].append({'query_id': row['query_id'], 'after_refinement_errors': errors})
        except ValueError as exc:
            summary['skipped'].append({'query_id': row['query_id'], 'reason': str(exc)[:200], 'refinement_errors': errors})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    print(json.dumps(run(args.task_dir.resolve(), dry_run=args.dry_run), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Purpose/version discovery limits, derived from immutable plan rows and runs.

Reservations use live plan rows; consumption uses actual source receipts. A
cancelled, unsubmitted row can release its route, but an unknown submission
never does. No separate mutable counter can drift from retained evidence.
"""
from __future__ import annotations

from common import sha256_json

REVISION = 'discovery-purpose-budget-v1'


def enabled(task):
    value = task.get('discovery_budget_revision')
    if value is None:
        return False
    if value != REVISION:
        raise ValueError('DISCOVERY_BUDGET_REVISION_INVALID')
    return True


def purpose_id(country, right, axis, term, scenario_id=None):
    source = term.get('derived_from')
    if not isinstance(source, str) or not source.strip():
        raise ValueError('DISCOVERY_PURPOSE_SOURCE_REQUIRED')
    # A translation, field-syntax change or synonym does not mint a new
    # purpose. Distinct product clues have distinct stable source paths.
    problem = term.get('discovery_problem_id')
    if problem is not None and (not isinstance(problem, str) or not problem.strip()
            or not isinstance(term.get('discovery_problem_reason'), str)
            or not term['discovery_problem_reason'].strip()
            or not isinstance(term.get('different_from_purpose_id'), str)
            or not term['different_from_purpose_id'].strip()):
        raise ValueError('DISCOVERY_NEW_PURPOSE_REASON_REQUIRED')
    return 'INT-' + sha256_json({'scenario':scenario_id,'country':country,'right':right,
        'dimension':axis,'clue_source':source,'problem':problem})[:20]


def _scope(row):
    return row.get('discovery_intent_id'), row.get('refinement_round')


def _route(provider, row):
    return provider, row.get('operation'), 'browser' if provider.endswith('browser') else 'api'


def _run_pages(run, *, include_valid_failed=False):
    valid_failed_page = (include_valid_failed and run.get('status') == 'failed'
        and run.get('submission_state') == 'submitted'
        and isinstance(run.get('result_processing'), dict)
        and run['result_processing'].get('returned_count_basis') == 'retained_rows'
        and type(run['result_processing'].get('returned_count')) is int
        and run['result_processing']['returned_count'] > 0
        and run.get('metadata', {}).get('search_coverage', {}).get('schema_valid') is True)
    if run.get('status') not in {'success','no_result'} and not valid_failed_page:
        return 0
    coverage = run.get('metadata', {}).get('search_coverage', {})
    pages = coverage.get('pages_retrieved', 1)
    if type(pages) is not int or pages < 1 or pages > 8:
        raise ValueError('DISCOVERY_PAGE_RECEIPT_INVALID')
    return pages


def snapshot(task, plan, evidence, row, *, candidates=None):
    """One version's reserved routes, acquired pages and browser cards."""
    from api_first_planning import _capacity_rows
    if not enabled(task):
        return None
    matching = [(provider, item) for provider, item in _capacity_rows(task, plan, evidence)
                if item.get('action_purpose') == 'discovery' and _scope(item) == _scope(row)]
    routes = {_route(provider, item) for provider, item in matching}
    by_key = {(provider, item.get('query_id'), sha256_json(item)): item
              for provider, item in matching}
    pages = 0
    browser_cards = set()
    from candidate_acquisition import (enabled as acquisition_enabled, verified_receipt,
                                       current_candidate_stats, execution_state)
    acquisition_mode = acquisition_enabled(task)
    acquisition_keys = set()
    unknown_positions = []
    matching_run_ids = set()
    seen_runs = set()
    for run in evidence.get('source_runs', []):
        if not isinstance(run, dict) or run.get('run_id') in seen_runs:
            continue
        key = (run.get('provider'), run.get('query_id'), run.get('plan_entry_sha256'))
        source = by_key.get(key)
        if source is None:
            continue
        seen_runs.add(run.get('run_id'))
        matching_run_ids.add(run.get('run_id'))
        pages += _run_pages(run, include_valid_failed=acquisition_mode)
        if key[0].endswith('browser'):
            if acquisition_mode:
                receipt = verified_receipt(run)
                if receipt is None:
                    raise ValueError('CANDIDATE_ACQUISITION_RECEIPT_MISSING')
                if (receipt.get('purpose_id'), receipt.get('version')) != _scope(source):
                    raise ValueError('CANDIDATE_ACQUISITION_SCOPE_CHANGED')
                keys, unresolved = execution_state(evidence, run, receipt)
                acquisition_keys.update(keys)
                unknown_positions.extend({'source_run_id':run.get('run_id'),'position':position}
                    for position in unresolved)
                continue
            for group in evidence.get('collections', {}).values():
                if not isinstance(group, list):
                    continue
                for item in group:
                    if not isinstance(item, dict) or item.get('source_run_id') != run.get('run_id'):
                        continue
                    for card in (item.get('payload') or {}).get('candidates', []):
                        if isinstance(card, dict):
                            browser_cards.add(card.get('source_record_sha256') or sha256_json(card))
    consumed = len(acquisition_keys) if acquisition_mode else len(browser_cards)
    result = {'purpose_id':row.get('discovery_intent_id'),'version':row.get('refinement_round'),
            'routes':routes,'pages_acquired':pages,'browser_candidates_acquired':len(browser_cards),
            'remaining_pages':max(0,8-pages),'remaining_browser_candidates':max(0,50-consumed)}
    if acquisition_mode:
        result.update(browser_candidates_acquired=consumed,
                      execution_consumed_count=consumed,
                      execution_identity_keys=sorted(acquisition_keys),
                      unparsed_result_positions=unknown_positions,
                      count_basis='immutable_source_run_receipts')
        if candidates is not None:
            result.update(current_candidate_stats(candidates, matching_run_ids))
    return result


def dispatch_block(task, plan, evidence, provider, row):
    if not enabled(task) or row.get('action_purpose') != 'discovery':
        return None
    basis = row.get('discovery_scope', {}).get('purpose_basis')
    if not isinstance(basis, dict):
        return 'DISCOVERY_PURPOSE_BASIS_REQUIRED'
    try:
        expected = purpose_id(row.get('jurisdiction'),row.get('right_type'),
            row.get('search_dimension'),{'derived_from':basis.get('clue_source'),
                'discovery_problem_id':basis.get('problem_id'),
                'discovery_problem_reason':basis.get('problem_reason'),
                'different_from_purpose_id':basis.get('different_from_purpose_id')},
            basis.get('scenario_id'))
    except ValueError as exc:
        return str(exc)
    if row.get('discovery_intent_id') != expected:
        return 'DISCOVERY_PURPOSE_ID_MISMATCH'
    previous = basis.get('different_from_purpose_id')
    if previous and not any(item.get('discovery_intent_id') == previous
            and item.get('jurisdiction') == row.get('jurisdiction')
            and item.get('right_type') == row.get('right_type')
            and item.get('search_dimension') == row.get('search_dimension')
            and item.get('discovery_scope', {}).get('purpose_basis', {}).get('clue_source') == basis.get('clue_source')
            for values in plan.get('queries', {}).values() for item in values):
        return 'DISCOVERY_NEW_PURPOSE_PARENT_REQUIRED'
    state = snapshot(task, plan, evidence, row)
    if state.get('unparsed_result_positions'):
        return 'DISCOVERY_CANDIDATE_COUNT_PENDING_PARSE'
    if len(state['routes']) > 2:
        return 'DISCOVERY_ROUTE_LIMIT'
    if state['pages_acquired'] >= 8:
        return 'DISCOVERY_VERSION_PAGE_LIMIT'
    if provider.endswith('browser') and state['browser_candidates_acquired'] >= 50:
        return 'DISCOVERY_BROWSER_CANDIDATE_LIMIT'
    return None


def pagination_block(task, plan, evidence, provider, row):
    """A next page keeps its parent's purpose, version, route and page size."""
    if not enabled(task) or provider not in {'epo_ops','euipo_trademark','euipo_design','inpi_api'}:
        return 'DISCOVERY_PAGINATION_UNSUPPORTED'
    parents = [(p, item) for p, rows in plan.get('queries', {}).items() for item in rows
               if item.get('query_id') == row.get('parent_query_id')]
    if len(parents) != 1:
        return 'DISCOVERY_PAGINATION_PARENT_INVALID'
    old_provider, parent = parents[0]
    if (old_provider != provider or row.get('parent_plan_entry_sha256') != sha256_json(parent)
            or _scope(row) != _scope(parent) or row.get('q') != parent.get('q')
            or any(row.get(key) != parent.get(key) for key in
                   ('jurisdiction','right_type','requirement_ids','search_dimension','action_purpose','operation'))):
        return 'DISCOVERY_PAGINATION_PARENT_MISMATCH'
    basis = row.get('discovery_scope', {}).get('pagination_basis')
    runs = [run for run in evidence.get('source_runs', []) if run.get('run_id') == (basis or {}).get('source_run_id')]
    if (len(runs) != 1 or runs[0].get('provider') != provider
            or runs[0].get('query_id') != parent.get('query_id')
            or runs[0].get('plan_entry_sha256') != sha256_json(parent)
            or runs[0].get('status') != 'success'
            or runs[0].get('submission_state') != 'submitted'
            or (basis or {}).get('source_run_sha256') != sha256_json(runs[0])):
        return 'DISCOVERY_PAGINATION_SOURCE_REQUIRED'
    if provider == 'epo_ops':
        try:
            start, end = map(int, str(parent.get('range','')).split('-'))
        except ValueError:
            return 'DISCOVERY_PAGINATION_POSITION_INVALID'
        if start < 1 or end < start or row.get('range') != f'{end+1}-{end+(end-start+1)}':
            return 'DISCOVERY_PAGINATION_POSITION_INVALID'
    else:
        size = parent.get('size')
        if type(size) is not int or size < 1 or row.get('size') != size:
            return 'DISCOVERY_PAGINATION_SIZE_CHANGED'
        field = 'position' if provider == 'inpi_api' else 'page'
        old = parent.get(field, 0)
        if type(old) is not int or old < 0 or row.get(field) != old + (size if field == 'position' else 1):
            return 'DISCOVERY_PAGINATION_POSITION_INVALID'
    return None


def source_files_error(task_dir, task, plan, evidence, row):
    """Before another request, recheck every consumed page's retained source."""
    if not enabled(task) or row.get('action_purpose') != 'discovery':
        return None
    from api_first_planning import source_files_error as verify_source
    sources = {(provider,item.get('query_id'),sha256_json(item))
               for provider, rows in plan.get('queries', {}).items() for item in rows
               if item.get('action_purpose') == 'discovery' and _scope(item) == _scope(row)}
    for run in evidence.get('source_runs', []):
        if (run.get('provider'),run.get('query_id'),run.get('plan_entry_sha256')) not in sources:
            continue
        error = verify_source(task_dir,evidence,run)
        if error:
            return error
    return None

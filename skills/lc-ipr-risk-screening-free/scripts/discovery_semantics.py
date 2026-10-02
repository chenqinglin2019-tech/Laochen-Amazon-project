"""03B human semantic checks bound to current scope, actual query and result.

The reviewer judges meaning; this module checks coverage of the review itself,
immutable identities and whether a stated gap remains actionable. Historical
tasks without REVISION keep their earlier workflow.
"""
from __future__ import annotations

from pathlib import Path

from common import load_json, resolve_retained_path, sha256_json, stable_id

REVISION = 'discovery-semantics-v1'
STAGES = {'direction', 'before', 'after'}
CLUE_STATES = {'included', 'irrelevant', 'awaiting_information', 'awaiting_capability', 'covered_by_other'}


def enabled(task):
    value = task.get('discovery_semantics_revision')
    if value is None:
        return False
    if value != REVISION:
        raise ValueError('DISCOVERY_SEMANTICS_REVISION_INVALID')
    return True


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _text_list(value):
    return isinstance(value, list) and all(_text(item) for item in value)


def _events(task):
    if not enabled(task):
        return []
    rows = task.get('discovery_semantic_reviews', [])
    if not isinstance(rows, list):
        raise ValueError('DISCOVERY_SEMANTIC_REVIEWS_INVALID')
    return rows


def _digest(event):
    return sha256_json({key: value for key, value in event.items() if key not in {'review_id', 'review_sha256'}})


def _scope(task):
    import product_scope as ps
    if not ps.enabled(task):
        raise ValueError('DISCOVERY_DIRECTION_SCOPE_REQUIRED')
    return ps.scope(task)


def _directions(task, scenario_id, right_type):
    import product_scope as ps
    return ps.directions(task, scenario_id, right_type)


def _clues(task, scenario_id, right_type):
    directions = _directions(task, scenario_id, right_type)
    return ({'fact:' + fid for direction in directions for fid in direction['fact_ids']}
            | {'object:' + oid for direction in directions for oid in direction['object_ids']})


def _unmapped_facts(task):
    data = _scope(task)
    linked = {fid for direction in data['directions'] for fid in direction['fact_ids']}
    return {item['fact_id']:item for item in data['facts'] if item['fact_id'] not in linked}


def _direction_basis(task, scenario_id, right_type):
    import product_scope as ps
    return sha256_json({'directions':[{'direction_id':direction['direction_id'],
                        'sha256':ps.direction_digest(task,direction)}
                       for direction in _directions(task,scenario_id,right_type)],
        'unmapped_facts':_unmapped_facts(task)})


def _identity(task, event):
    from decision_workflow import scenario_index
    data = _scope(task)
    if (event.get('product_identity_sha256') != task.get('product_identity', {}).get('sha256')
            or event.get('scenario_id') not in scenario_index(task)
            or event.get('jurisdiction') not in task.get('target_jurisdictions', [])
            or not _text(event.get('right_type'))):
        raise ValueError('DISCOVERY_SEMANTIC_SCOPE_CHANGED')
    if (event.get('stage') == 'direction' and
            event.get('direction_basis_sha256') != _direction_basis(task,event['scenario_id'],event['right_type'])):
        raise ValueError('DISCOVERY_DIRECTION_BASIS_CHANGED')
    return data


def _row(plan, event):
    matches = [(provider, row) for provider, rows in plan.get('queries', {}).items() for row in rows
               if row.get('query_id') == event.get('query_id')]
    if (len(matches) != 1 or matches[0][0] != event.get('provider')
            or sha256_json(matches[0][1]) != event.get('plan_entry_sha256')):
        raise ValueError('DISCOVERY_SEMANTIC_QUERY_CHANGED')
    provider, row = matches[0]
    if (row.get('action_purpose') != 'discovery' or event.get('jurisdiction') not in row_jurisdictions(provider, row)
            or row.get('right_type') != event.get('right_type')
            or row.get('discovery_intent_id') != event.get('discovery_intent_id')
            or row.get('refinement_round') != event.get('refinement_round')
            or row.get('q') != event.get('actual_query')):
        raise ValueError('DISCOVERY_SEMANTIC_QUERY_CHANGED')
    refs = [ref for ref in row.get('product_dependencies', [])
            if ref.get('scenario_id') == event.get('scenario_id')]
    if event.get('direction_id') not in {ref.get('direction_id') for ref in refs}:
        raise ValueError('DISCOVERY_SEMANTIC_DIRECTION_UNBOUND')
    return provider, row


def _linked_evidence(evidence, run):
    return {item.get('evidence_id') for group in evidence.get('collections', {}).values()
            if isinstance(group, list) for item in group if isinstance(item, dict)
            and item.get('source_run_id') == run.get('run_id') and item.get('evidence_id')}


def row_jurisdictions(provider, row):
    """Only a native multi-office request may bind more than one country."""
    raw = row.get('jurisdiction')
    countries = raw.split(',') if isinstance(raw, str) else []
    if not countries or len(set(countries)) != len(countries) or any(not value or value != value.strip() for value in countries):
        return set()
    if len(countries) == 1:
        return {countries[0]}
    if provider != 'signa' or row.get('right_type') != 'trademark_word':
        return set()
    from common import load_skill_config
    offices = load_skill_config().get('providers', {}).get('signa', {}).get('office_map', {})
    expected = [offices.get(country) for country in countries]
    filters = row.get('filters')
    if any(not office for office in expected) or not isinstance(filters, dict) or filters.get('offices') != expected:
        return set()
    return set(countries)


def _direction_has_local_provenance_route(task, plan, direction, direction_basis, country):
    """True only when the current direction explicitly delegates to its local asset review.

    This route is valid for unregistered expression rights. It does not stand in
    for official discovery routes (including trademark or patent searches).
    """
    import product_scope as ps
    sid, right = direction['scenario_id'], direction['right_type']
    if (right not in {'copyright', 'trade_dress', 'unregistered_design'}
            or 'asset_provenance' not in direction_basis.get('proposed_sources', [])):
        return False
    digest = ps.direction_digest(task, direction)
    content_digest = ps.direction_content_digest(task, direction)
    return any(
        provider == 'asset_provenance'
        and row.get('action_purpose') == 'provenance'
        and row.get('operation') == 'provenance_review'
        and row.get('jurisdiction') == country
        and row.get('right_type') == right
        and any(ref.get('scenario_id') == sid
                and ref.get('direction_id') == direction['direction_id']
                and ref.get('right_type') == right
                and (ref.get('sha256') == digest or ref.get('content_sha256') == content_digest)
                for ref in row.get('product_dependencies', []))
        for provider, rows in plan.get('queries', {}).items()
        for row in rows if isinstance(row, dict)
    )


def _empty_figurative_inventory_closes_current_direction(task, sid, right, direction, review):
    """Close only current figurative-mark search when reviewed inventory is empty.

    A future word mark remains a separate user-information dependency; this
    predicate never waives text-mark or other trademark recall.
    """
    if right != 'trademark_figurative':
        return False
    from record_asset_provenance import asset_scope, specialty_enabled
    if not specialty_enabled(task):
        return False
    inventory = asset_scope(task, sid, right)
    if not inventory.get('inventory_reviewed') or inventory.get('asset_ids'):
        return False
    basis = next((item for item in review.get('directions', [])
                  if item.get('direction_id') == direction.get('direction_id')), None)
    if not basis:
        return False
    dispositions = {item.get('clue_id'): item.get('disposition')
                    for item in [*review.get('clues', []), *review.get('unmapped_clues', [])]}
    clue_ids = basis.get('clue_ids')
    return (isinstance(clue_ids, list) and bool(clue_ids)
            and all(dispositions.get(clue_id) == 'irrelevant' for clue_id in clue_ids))


def _empty_own_word_mark_waits_for_information(task, sid, right, direction, review):
    """Do not invent a word-mark query before the user has supplied a brand name."""
    if right != 'trademark_word' or direction.get('right_type') != right:
        return False
    from record_asset_provenance import asset_scope, specialty_enabled
    if not specialty_enabled(task):
        return False
    inventory = asset_scope(task, sid, 'trademark_figurative')
    if not inventory.get('inventory_reviewed') or inventory.get('asset_ids'):
        return False
    basis = next((item for item in review.get('directions', [])
                  if item.get('direction_id') == direction.get('direction_id')), None)
    if not basis:
        return False
    clue_ids = set(basis.get('clue_ids', []))
    dispositions = {item.get('clue_id'): item.get('disposition') for item in review.get('clues', [])}
    own_brand_clues = {clue_id for clue_id in clue_ids
                       if clue_id.endswith(':own-brand') or clue_id.endswith(':own-brand-use')}
    return bool(own_brand_clues and any(dispositions.get(clue_id) == 'awaiting_information'
                                        for clue_id in own_brand_clues))


def _has_discovery_obligation(task, country, right):
    """Whether canonical coverage makes an absent query actionable here."""
    return any(
        isinstance(item, dict)
        and item.get('jurisdiction') == country
        and item.get('right_type') == right
        and item.get('phase') in {'official_recall', 'provenance'}
        for item in task.get('coverage_requirements', [])
    )


def validate(task, plan, evidence, event, task_dir=None):
    if not enabled(task) or not isinstance(event, dict) or event.get('stage') not in STAGES:
        raise ValueError('DISCOVERY_SEMANTIC_REVIEW_INVALID')
    if event.get('review_sha256') and event['review_sha256'] != _digest(event):
        raise ValueError('DISCOVERY_SEMANTIC_RECEIPT_CHANGED')
    data = _identity(task, event)
    if not all(_text(event.get(key)) for key in ('reviewer', 'reason', 'reviewed_at')):
        raise ValueError('DISCOVERY_SEMANTIC_REASON_REQUIRED')
    stage = event['stage']
    if stage == 'direction':
        expected = {row['direction_id']: row for row in _directions(task, event['scenario_id'], event['right_type'])}
        supplied = event.get('directions')
        clues = event.get('clues')
        omitted = event.get('unmapped_clues',[])
        if (not isinstance(supplied, list) or {row.get('direction_id') for row in supplied if isinstance(row, dict)} != set(expected)
                or len(supplied) != len(expected) or not isinstance(clues, list)
                or {row.get('clue_id') for row in clues if isinstance(row, dict)} != _clues(task,event['scenario_id'], event['right_type'])
                or len(clues) != len(_clues(task,event['scenario_id'], event['right_type']))
                or not isinstance(omitted,list)
                or {row.get('clue_id') for row in omitted if isinstance(row,dict)} !=
                    {'fact:'+fid for fid in _unmapped_facts(task)}
                or len(omitted) != len(_unmapped_facts(task))):
            raise ValueError('DISCOVERY_DIRECTION_INVENTORY_INCOMPLETE')
        all_relevant = set()
        objects = {item['object_id']:item for item in data['objects']}
        known_evidence = {item.get('evidence_id') for group in evidence.get('collections', {}).values()
                          if isinstance(group, list) for item in group if isinstance(item, dict)}
        for item in clues:
            if (not isinstance(item, dict) or item.get('disposition') not in CLUE_STATES
                    or not _text(item.get('reason'))
                    or item.get('disposition') == 'covered_by_other' and
                       (not _text_list(item.get('evidence_refs')) or not item['evidence_refs']
                        or not set(item['evidence_refs']) <= known_evidence)):
                raise ValueError('DISCOVERY_CLUE_DISPOSITION_INVALID')
            if item['disposition'] == 'included':
                if item['clue_id'].startswith('object:') and objects[item['clue_id'][7:]]['scope_status'] != 'included':
                    raise ValueError('DISCOVERY_EXCLUDED_OBJECT_NOT_INCLUDED')
                all_relevant.add(item['clue_id'])
        for item in omitted:
            if (not isinstance(item, dict) or item.get('disposition') not in CLUE_STATES - {'included'}
                    or not _text(item.get('reason'))
                    or item['disposition'] == 'covered_by_other' and
                       (not _text_list(item.get('evidence_refs')) or not item['evidence_refs']
                        or not set(item['evidence_refs']) <= known_evidence)):
                raise ValueError('DISCOVERY_UNMAPPED_CLUE_REVIEW_REQUIRED')
        covered = set()
        for item in supplied:
            if not isinstance(item, dict):
                raise ValueError('DISCOVERY_DIRECTION_BASIS_INCOMPLETE')
            original = expected[item['direction_id']]
            required = {'fact:' + fid for fid in original['fact_ids']} | {'object:' + oid for oid in original['object_ids']}
            if (not _text_list(item.get('clue_ids')) or set(item['clue_ids']) != required
                    or len(item['clue_ids']) != len(required)
                    or not all(_text(item.get(key)) for key in ('question', 'method', 'evidence_needed', 'supplement_trigger'))
                    or not _text_list(item.get('proposed_sources'))):
                raise ValueError('DISCOVERY_DIRECTION_BASIS_INCOMPLETE')
            covered.update(required)
        if all_relevant - covered:
            raise ValueError('DISCOVERY_INCLUDED_CLUE_UNPLANNED')
    else:
        direction_reviews = [item for item in _events(task) if item.get('stage') == 'direction'
                             and item.get('review_sha256') == event.get('direction_review_sha256')]
        if len(direction_reviews) != 1:
            raise ValueError('DISCOVERY_DIRECTION_REVIEW_REQUIRED')
        direction = direction_reviews[0]
        validate(task, plan, evidence, direction, task_dir)
        if any(direction.get(key) != event.get(key) for key in ('scenario_id', 'jurisdiction', 'right_type')):
            raise ValueError('DISCOVERY_DIRECTION_REVIEW_CHANGED')
        _provider, row = _row(plan, event)
        if event['direction_id'] not in {item['direction_id'] for item in direction['directions']}:
            raise ValueError('DISCOVERY_DIRECTION_REVIEW_CHANGED')
        if stage == 'before':
            if (event.get('semantic_fit') not in {'full', 'partial', 'mismatch'}
                    or not _text(event.get('expression_reason'))
                    or not isinstance(event.get('concepts_in_query'), list)
                    or not event['concepts_in_query']
                    or any(not _text(value) for value in event['concepts_in_query'])
                    or not _text_list(event.get('uncovered_clues'))
                    or event['semantic_fit'] == 'full' and event['uncovered_clues']
                    or event['semantic_fit'] == 'partial' and not event['uncovered_clues']
                    or type(event.get('independent_structure')) is not bool
                    or type(event.get('whole_product_constraint')) is not bool
                    or event['independent_structure'] and event['whole_product_constraint']
                       and not _text(event.get('constraint_reason'))):
                raise ValueError('DISCOVERY_EXPRESSION_REVIEW_INCOMPLETE')
            kind = row.get('discovery_scope', {}).get('expression_basis', {}).get('kind')
            if kind in {'ipc', 'cpc', 'uspc', 'locarno', 'nice', 'similar_group', 'figurative_classification', 'jpo_figurative_classification', 'design_code'}:
                basis = event.get('classification_basis')
                if not isinstance(basis, dict) or not all(_text(basis.get(key)) for key in ('source', 'meaning', 'applicability')):
                    raise ValueError('DISCOVERY_CLASSIFICATION_REVIEW_REQUIRED')
            if kind in {'translation', 'original_japanese', 'english', 'romaji', 'reading'}:
                basis = event.get('language_basis')
                if not isinstance(basis, dict) or not all(_text(basis.get(key)) for key in ('original', 'submitted', 'source', 'relationship')):
                    raise ValueError('DISCOVERY_LANGUAGE_REVIEW_REQUIRED')
        else:
            pre = [item for item in _events(task) if item.get('stage') == 'before'
                   and item.get('review_sha256') == event.get('before_review_sha256')]
            if (len(pre) != 1 or pre[0].get('direction_review_sha256') != event.get('direction_review_sha256')
                    or any(pre[0].get(key) != event.get(key) for key in
                    ('query_id', 'direction_id', 'scenario_id', 'jurisdiction', 'right_type', 'plan_entry_sha256'))):
                raise ValueError('DISCOVERY_BEFORE_REVIEW_REQUIRED')
            validate(task, plan, evidence, pre[0], task_dir)
            runs = [run for run in evidence.get('source_runs', []) if run.get('run_id') == event.get('source_run_id')]
            if (len(runs) != 1 or runs[0].get('query_id') != row['query_id']
                    or runs[0].get('provider') != event['provider']
                    or runs[0].get('plan_entry_sha256') != sha256_json(row)
                    or sha256_json(runs[0]) != event.get('source_run_sha256')
                    or runs[0].get('status') not in {'success', 'no_result'}
                    or (runs[0].get('submission_state') != 'submitted'
                        and (task_dir is None or _physical_source(task_dir, evidence, runs[0]) is None))
                    or not _text_list(event.get('evidence_refs'))
                    or not event['evidence_refs'] or not set(event['evidence_refs']) <= _linked_evidence(evidence, runs[0])):
                raise ValueError('DISCOVERY_AFTER_SOURCE_REQUIRED')
            if (type(event.get('problem_covered')) is not bool
                    or event.get('original_problem_checked') is not True
                    or not _text(event.get('result_reason'))
                    or not _text_list(event.get('uncovered_clues'))
                    or not _text_list(event.get('excluded_by_narrowing'))
                    or event.get('next_action') not in {'none', 'refine', 'fallback', 'awaiting_information', 'awaiting_capability'}
                    or event['problem_covered'] and (pre[0]['semantic_fit'] != 'full'
                        or event['uncovered_clues'] or event['excluded_by_narrowing']
                        or event['next_action'] != 'none'
                        or (runs[0].get('metadata',{}).get('search_coverage') or {}).get('truncated') is True)
                    or not event['problem_covered'] and (event['next_action'] == 'none'
                        or not (event['uncovered_clues'] or event['excluded_by_narrowing']))):
                raise ValueError('DISCOVERY_RESULT_REVIEW_INCOMPLETE')
    return event


def _physical_source(task_dir, evidence, run):
    from runtime_v24 import physical_response_source
    return physical_response_source(Path(task_dir), evidence, run)


def current(task, plan, evidence, *, stage, scenario_id, jurisdiction, right_type, direction_id=None,
            provider=None, row=None, task_dir=None):
    for event in reversed(_events(task)):
        if (event.get('stage') != stage or event.get('scenario_id') != scenario_id
                or event.get('jurisdiction') != jurisdiction or event.get('right_type') != right_type
                or direction_id is not None and event.get('direction_id') != direction_id
                or row is not None and (event.get('query_id') != row.get('query_id')
                    or event.get('plan_entry_sha256') != sha256_json(row))
                or provider is not None and event.get('provider') != provider):
            continue
        try:
            validate(task, plan, evidence, event, task_dir)
        except ValueError:
            continue
        return event
    return None


def dispatch_error(task, plan, evidence, provider, row):
    if not enabled(task) or row.get('action_purpose') != 'discovery':
        return None
    import product_scope as ps
    if not ps.enabled(task):
        return 'DISCOVERY_DIRECTION_SCOPE_REQUIRED'
    countries = row_jurisdictions(provider, row)
    if not countries or not countries <= set(task.get('target_jurisdictions', [])):
        return 'DISCOVERY_QUERY_JURISDICTION_INVALID'
    for country in sorted(countries):
        for ref in row.get('product_dependencies', []):
            sid = ref.get('scenario_id')
            if ps.binding_state(task, row, sid) != 'ready':
                continue
            direction = current(task, plan, evidence, stage='direction', scenario_id=sid,
                jurisdiction=country, right_type=row['right_type'])
            if direction is None:
                return 'DISCOVERY_DIRECTION_REVIEW_REQUIRED'
            before = current(task, plan, evidence, stage='before', scenario_id=sid,
                jurisdiction=country, right_type=row['right_type'],
                direction_id=ref['direction_id'], provider=provider, row=row)
            if before is None or before.get('direction_review_sha256') != direction['review_sha256']:
                return 'DISCOVERY_EXPRESSION_REVIEW_REQUIRED'
            if before['semantic_fit'] == 'mismatch':
                return 'DISCOVERY_EXPRESSION_MISMATCH'
    return None


def _current_bounded_capability_wait(task, plan, evidence, candidates, ledger, supplement,
                                    task_dir, provider, row, after, run):
    """Prove a truncated search is genuinely waiting on an accepted route limit.

    The API review is the full-batch merge/triage gate. The exact retained run
    must also have a current accepted operation review that only demonstrated
    single-page retrieval. A prose `awaiting_capability` label alone is not a
    limitation.
    """
    if (after.get('next_action') != 'awaiting_capability' or task_dir is None
            or candidates is None or ledger is None):
        return None
    metadata = run.get('metadata')
    coverage = metadata.get('search_coverage') if isinstance(metadata, dict) else None
    if coverage is None and isinstance(metadata, dict):
        coverage = metadata  # EPO retains the verified native range at metadata root.
    if not isinstance(coverage, dict):
        return None
    remaining = coverage.get('unretrieved_result_row_count')
    remaining_count_proven = type(remaining) is int and remaining > 0
    start, end = coverage.get('range_start'), coverage.get('range_end')
    total, retrieved = coverage.get('total_hits'), coverage.get('retrieved_hits')
    range_count_proven = (coverage.get('range_verified') is True
        and coverage.get('schema_valid') is True and type(start) is int and start > 0
        and type(end) is int and end >= start and type(total) is int and total > end
        and type(retrieved) is int and retrieved == end - start + 1 and total > retrieved)
    if coverage.get('truncated') is not True or not (remaining_count_proven or range_count_proven):
        return None
    reviews = [item for item in task.get('discovery_followups', []) if isinstance(item, dict)
               if item.get('role') == 'review' and item.get('parent_query_id') == row.get('query_id')
               and item.get('source_run_id') == run.get('run_id')]
    if len(reviews) != 1 or reviews[0].get('outcome') != 'stop_bounded_discovery':
        return None
    from api_first_planning import review_validation
    if review_validation(task, plan, evidence, candidates, ledger, row, reviews[0], supplement):
        return None
    from api_first_planning import source_files_error
    if source_files_error(task_dir, evidence, run):
        return None
    from source_operation import (enabled as source_operation_enabled,
                                  validate as validate_operation,
                                  verify as verify_source_operations)
    if not source_operation_enabled(task):
        return None
    try:
        verify_source_operations(task, plan, evidence, task_dir)
    except (ValueError, OSError, KeyError, TypeError):
        return None
    ops = [item for item in task.get('source_operation_reviews', []) if isinstance(item, dict)
           if item.get('provider') == provider and item.get('query_id') == row.get('query_id')]
    if not ops:
        return None
    operation_review = ops[-1]
    if (operation_review.get('decision') != 'accepted'
            or operation_review.get('source_run_id') != run.get('run_id')):
        return None
    try:
        validate_operation(task, plan, evidence, operation_review, task_dir)
    except (ValueError, OSError, KeyError, TypeError):
        return None
    checks = operation_review.get('checks')
    if not isinstance(checks, dict) or checks.get('pagination') != 'single_page':
        return None
    return reviews[0]


def _current_source_fault_wait(task, plan, evidence, candidates, ledger, supplement,
                               task_dir, provider, row, after, run):
    """Wait on one hash-bound provider fault without converting it to zero hits.

    This is narrower than a bounded-result stop: the shared result processor
    must prove a non-result error, the API review must stop this exact query,
    and the source-operation review must retain its rejection for this exact
    receipt. Coverage remains unknown and any valid descendant query keeps
    its own work item.
    """
    if (after.get('next_action') != 'awaiting_capability' or task_dir is None
            or candidates is None or ledger is None):
        return None
    from api_first_planning import _receipt_classified_failure, review_validation, source_files_error
    if not _receipt_classified_failure(task_dir, task, evidence, run):
        return None
    reviews = [item for item in task.get('discovery_followups', []) if isinstance(item, dict)
        if item.get('role') == 'review' and item.get('parent_query_id') == row.get('query_id')
        and item.get('source_run_id') == run.get('run_id')]
    if (len(reviews) != 1 or reviews[0].get('outcome') != 'stop_bounded_discovery'
            or review_validation(task, plan, evidence, candidates, ledger, row, reviews[0], supplement)):
        return None
    if source_files_error(task_dir, evidence, run):
        return None
    from source_operation import enabled as source_operation_enabled, validate as validate_operation, verify as verify_operations
    if not source_operation_enabled(task):
        return None
    try:
        verify_operations(task, plan, evidence, task_dir)
    except (ValueError, OSError, KeyError, TypeError):
        return None
    operations = [item for item in task.get('source_operation_reviews', []) if isinstance(item, dict)
        if item.get('provider') == provider and item.get('query_id') == row.get('query_id')]
    if not operations:
        return None
    operation = operations[-1]
    checks = operation.get('checks')
    if (operation.get('decision') != 'rejected' or operation.get('source_run_id') != run.get('run_id')
            or not isinstance(checks, dict) or checks.get('pagination') != 'unknown'
            or checks.get('field_effect') != 'unknown'):
        return None
    try:
        validate_operation(task, plan, evidence, operation, task_dir)
    except (ValueError, OSError, KeyError, TypeError):
        return None
    return reviews[0]


def _retained_ranked_operation_review(task, plan, evidence, task_dir, provider, run):
    """Reuse the original accepted response review; adapter updates affect new calls."""
    from runtime_v24 import physical_response_source
    from source_operation import verify as verify_operation_reviews
    source = (physical_response_source(Path(task_dir), evidence, run)
        if run.get('metadata', {}).get('physical_response_reuse') else run)
    if not source or source.get('submission_state') != 'submitted':
        return None
    reviews = [item for item in task.get('source_operation_reviews', []) if isinstance(item, dict)
        and item.get('provider') == provider and item.get('source_run_id') == source.get('run_id')]
    if not reviews or reviews[-1].get('decision') != 'accepted':
        return None
    try:
        verify_operation_reviews({**task, 'source_operation_reviews':[reviews[-1]]}, plan, evidence, task_dir)
    except (ValueError, OSError, KeyError, TypeError):
        return None
    return reviews[-1]


def _current_public_ranked_scope_wait(task, plan, evidence, candidates, ledger, supplement,
                                    task_dir, provider, row, after, run):
    """End an exactly supported public API scope without claiming exhaustive recall."""
    from coverage_v3 import public_discovery_enabled
    if any(not isinstance(value, dict) for value in (row, after, run)):
        return None
    visual_route = provider == 'serpapi_google_lens' and row.get('operation') == 'image_search'
    design_route = (provider == 'serpapi_google_patents' and row.get('operation') == 'search'
        and row.get('right_type') == 'design' and row.get('type') == 'DESIGN'
        and row.get('jurisdiction') == 'US' and row.get('country') == 'US')
    native_route = (provider == 'epo_ops' and row.get('operation') == 'search'
        and row.get('right_type') in {'patent', 'design', 'utility_model'})
    zero_route = native_route and run.get('status') == 'no_result'
    web_route = (provider == 'serper_web' and row.get('operation') == 'search'
        and row.get('right_type') == 'enforcement' and row.get('jurisdiction') == 'US'
        and row.get('gl') == 'us')
    if (task.get('retrieval_workflow_revision') != 'api-first-v3' or not public_discovery_enabled(task)
            or not (visual_route or design_route or native_route or web_route)
            or task_dir is None or candidates is None or ledger is None
            or after.get('next_action') != 'awaiting_capability' or after.get('problem_covered') is not False
            or after.get('source_run_id') != run.get('run_id')
            or after.get('source_run_sha256') != sha256_json(run)
            or after.get('plan_entry_sha256') != sha256_json(row)
            or run.get('query_id') != row.get('query_id') or run.get('provider') != provider
            or run.get('plan_entry_sha256') != sha256_json(row) or run.get('status') not in ({'no_result'} if zero_route else {'success'})):
        return None
    scope = row.get('discovery_scope', {})
    metadata = run.get('metadata')
    coverage = metadata.get('search_coverage') if isinstance(metadata, dict) else None
    if not isinstance(scope, dict) or not isinstance(coverage, dict):
        return None
    retrieved = coverage.get('retrieved_hits')
    if (scope.get('mode') != 'bounded' or type(scope.get('max_pages')) is not int or scope.get('max_pages') != 1
            or scope.get('review_all_returned') is not True
            or coverage.get('schema_valid') is not True
            or coverage.get('truncated') is not (False if zero_route else True)
            or not native_route and coverage.get('total_hits') is not None
            or coverage.get('stop_reason') != ('query_exhausted' if zero_route
                else 'ranked_search_total_unknown' if visual_route
                else 'page_limit' if native_route else 'bounded_discovery_total_unknown')
            or type(retrieved) is not int or (retrieved != 0 if zero_route else retrieved <= 0)):
        return None
    if zero_route and (coverage.get('total_hits') != 0 or coverage.get('empty_fault_receipt') is not True):
        return None
    if web_route and (type(row.get('num')) is not int or not 1 <= row['num'] <= 10
            or scope.get('max_candidates') != row['num'] or type(scope.get('max_candidates')) is not int
            or retrieved > row['num'] or not isinstance(run.get('request_params'), dict)
            or any(run['request_params'].get(key) != row.get(key) for key in ('q','gl','hl','num'))):
        return None
    if design_route and (type(row.get('num')) is not int or not 1 <= row['num'] <= 25
            or type(scope.get('max_candidates')) is not int
            or row['num'] != scope.get('max_candidates') or retrieved > row['num']):
        return None
    if native_route and not zero_route:
        start, end, total = (coverage.get(key) for key in ('range_start', 'range_end', 'total_hits'))
        params = run.get('request_params')
        if (coverage.get('range_verified') is not True or type(start) is not int or start != 1
                or type(end) is not int or type(total) is not int or total <= end
                or type(scope.get('max_candidates')) is not int
                or end != scope.get('max_candidates') or retrieved != end - start + 1
                or row.get('range') != '%s-%s' % (start, end)
                or not isinstance(params, dict) or params.get('range') != row.get('range')):
            return None
        # An independently planned continuation remains its own executable or
        # material-processing obligation. Do not end its parent behind it.
        for values in plan.get('queries', {}).values():
            for child in values:
                if (child.get('parent_query_id') == row.get('query_id')
                        and child.get('discovery_role') == 'pagination'):
                    from api_first_planning import pagination_parent_stop_valid
                    if not pagination_parent_stop_valid(task, plan, evidence, candidates, ledger, child, supplement):
                        return None
    if zero_route:
        from api_first_planning import pagination_parent_stop_valid
        for values in plan.get('queries', {}).values():
            for child in values:
                if (child.get('parent_query_id') == row.get('query_id')
                        and child.get('discovery_role') == 'pagination'
                        and not pagination_parent_stop_valid(task, plan, evidence, candidates, ledger, child, supplement)):
                    return None
    reviews = [item for item in task.get('discovery_followups', []) if isinstance(item, dict)
        and item.get('role') == 'review' and item.get('parent_query_id') == row.get('query_id')
        and item.get('source_run_id') == run.get('run_id')]
    if len(reviews) != 1 or reviews[0].get('outcome') != 'stop_bounded_discovery':
        return None
    try:
        from api_first_planning import review_validation, source_files_error
        from source_result_processing import progress
        if (review_validation(task, plan, evidence, candidates, ledger, row, reviews[0], supplement)
                or source_files_error(task_dir, evidence, run)):
            return None
        if design_route:
            paths = run.get('raw_paths', [])
            if len(paths) != 1:
                return None
            raw = load_json(Path(paths[0]))
            params = raw.get('search_parameters') if isinstance(raw, dict) else None
            if (not isinstance(params, dict) or params.get('engine') != 'google_patents' or params.get('type') != 'DESIGN'
                    or params.get('country') != 'US' or params.get('q') != row.get('q')
                    or str(params.get('num')) != str(row['num'])):
                return None
        operation_review = _retained_ranked_operation_review(task, plan, evidence, task_dir, provider, run)
        if not operation_review:
            return None
        processed = progress(Path(task_dir), run, evidence)
        if (processed.get('material_processing_complete') is not True
                or processed.get('returned_count') != retrieved
                or zero_route and processed.get('zero_proven') is not True):
            return None
        if zero_route:
            shared = _same_direction_native_limit(task, plan, evidence, candidates, ledger,
                supplement, task_dir, provider, row, after)
            if shared is None:
                return None
    except (ValueError, OSError, KeyError, TypeError):
        return None
    return {'review_sha256':sha256_json(reviews[0]), 'after_review_sha256':after.get('review_sha256'),
        'original_operation_review_sha256':sha256_json(operation_review),
        'retrieval_scope_kind':'bounded_native_zero_with_shared_scope' if zero_route else 'public_visual_ranking' if visual_route else 'bounded_native_api_range' if native_route else 'bounded_public_enforcement_api' if web_route else 'bounded_us_design_api',
        **({'total_record_count':total, 'unretrieved_record_count':total - retrieved,
            'retained_range_start':start, 'retained_range_end':end} if native_route and not zero_route else {}),
        **({'shared_direction_scope':shared} if zero_route else {}),
        'processed_record_count':retrieved, 'processing_sha256':sha256_json(processed)}


def _same_direction_native_limit(task, plan, evidence, candidates, ledger, supplement,
                                 task_dir, provider, row, after):
    """Reuse a current bounded investigation, never substitute its search facts."""
    dependencies = row.get('product_dependencies')
    if not isinstance(dependencies, list) or not dependencies or not after.get('direction_id'):
        return None
    valid = []
    from assessment_v24 import bound_runs
    for other in plan.get('queries', {}).get(provider, []):
        if (other.get('query_id') == row.get('query_id') or other.get('operation') != 'search'
                or other.get('action_purpose') != 'discovery'
                or other.get('jurisdiction') != row.get('jurisdiction')
                or other.get('right_type') != row.get('right_type')
                or other.get('product_dependencies') != dependencies):
            continue
        runs = bound_runs(evidence, plan, provider, other)
        if not runs or runs[-1].get('status') != 'success':
            continue
        reviewed = current(task, plan, evidence, stage='after', scenario_id=after['scenario_id'],
            jurisdiction=after['jurisdiction'], right_type=after['right_type'],
            direction_id=after['direction_id'], provider=provider, row=other, task_dir=task_dir)
        proof = _current_public_ranked_scope_wait(task, plan, evidence, candidates, ledger,
            supplement, task_dir, provider, other, reviewed, runs[-1])
        if proof is None or proof.get('retrieval_scope_kind') != 'bounded_native_api_range':
            continue
        valid.append((other.get('refinement_round', 0), other['query_id'], {
            'relation':'same_current_direction_scope', 'query_id':other['query_id'],
            'plan_entry_sha256':sha256_json(other), 'source_run_id':runs[-1]['run_id'],
            'source_run_sha256':sha256_json(runs[-1]),
            'product_dependencies_sha256':sha256_json(dependencies), **proof}))
    return max(valid, key=lambda item:(item[0],item[1]))[2] if valid else None


def public_ranked_scope_entry(base, row, after, run, proof):
    """The limit concerns the returned public ranking, never rights or ownership."""
    native = proof.get('retrieval_scope_kind') == 'bounded_native_api_range'
    zero = proof.get('retrieval_scope_kind') == 'bounded_native_zero_with_shared_scope'
    shared = proof.get('shared_direction_scope', {})
    return {**base, 'kind':'plan_repair', 'state':'blocked',
        'reason':'BOUNDED_PUBLIC_DISCOVERY_SCOPE_LIMITED', 'source_run_id':run['run_id'],
        'coverage_status':'unknown', 'uncovered_clues':after.get('uncovered_clues', []),
        **({'unretrieved_result_row_count':proof['unretrieved_record_count']} if native else {}),
        'delivery_limit':{'kind':'bounded_public_ranked_scope', 'query_id':row['query_id'],
            'plan_entry_sha256':sha256_json(row), 'source_run_id':run['run_id'],
            'source_run_sha256':sha256_json(run), **proof},
        'resume_condition':'出现影响判断的新公开来源、原查询范围可用的新结果或作者／首发／授权链材料时，复核受影响范围。',
        'reasoning':('原准确表达已验证真实零结果，仍不覆盖未命中技术。另有同一当前产品方向的%s查询，其实际%s条/%s条已处理，%s条未访问；仅复用本轮有界调查的结束凭据，不替代原零结果，不声称父子检索或权利全集完成；已有独立补证与材料仍分别处理。' % (shared['query_id'],shared['processed_record_count'],shared['total_record_count'],shared['unretrieved_record_count']) if zero else '本轮已处理原冻结范围实际返回的%s条记录；来源声明共%s条，另%s条未访问，不能据此排除登记权利或技术保护范围。分页能力有效；本项结束仅对应原冻结范围，已有细化查询和候选补证仍分别处理。' %
            (proof['processed_record_count'],proof['total_record_count'],proof['unretrieved_record_count']) if native else
            '本轮已处理全部实际返回的有界公开API卡片；检索总量未知，未访问范围及未由准确记录支持的作者、首发、授权链仍未知。该范围结束不代表登记权利穷尽检索、无侵权或来源能力不足。')}


def _after_waiting_information(direction_review, after):
    """Only defer query repair when an exact direction clue awaits user input."""
    uncovered = set(after.get('uncovered_clues', []))
    return next((item.get('clue_id') for item in
        [*direction_review.get('clues', []), *direction_review.get('unmapped_clues', [])]
        if item.get('disposition') == 'awaiting_information'
        and item.get('clue_id') in uncovered), None)


def work_entries(task, plan, evidence, *, candidates=None, ledger=None, supplement=None, task_dir=None):
    if not enabled(task):
        return []
    import product_scope as ps
    if not ps.enabled(task):
        # The product handoff owns its own missing-scope work item. Repeating
        # it here would manufacture a second queue before any scope exists.
        return []
    entries = []
    for sid in task.get('execution_scenario_ids', []):
        for country in task.get('target_jurisdictions', []):
            for right in {d['right_type'] for d in ps.directions(task, sid)}:
                relevant = [d for d in ps.directions(task, sid, right) if ps.direction_state(task,d) != 'out_of_scope']
                if not relevant:
                    continue
                base = {'scenario_id':sid,'jurisdiction':country,'right_type':right}
                review = current(task, plan, evidence, stage='direction', scenario_id=sid,
                    jurisdiction=country, right_type=right)
                if review is None:
                    entries.append({**base,'kind':'agent_investigation','state':'awaiting_review',
                                    'reason':'DISCOVERY_DIRECTION_REVIEW_REQUIRED'})
                    continue
                for clue in [*review['clues'],*review.get('unmapped_clues',[])]:
                    if clue['disposition'] in {'awaiting_information','awaiting_capability'}:
                        entries.append({**base,'clue_id':clue['clue_id'],
                            'kind':'user_information' if clue['disposition']=='awaiting_information' else 'plan_repair',
                            'state':'awaiting_user' if clue['disposition']=='awaiting_information' else 'awaiting_access',
                            'reason':'DISCOVERY_CLUE_'+clue['disposition'].upper()})
                for d in relevant:
                    if ps.direction_state(task,d) != 'ready':
                        continue
                    direction_basis = next(item for item in review['directions'] if item['direction_id'] == d['direction_id'])
                    if not direction_basis['proposed_sources']:
                        entries.append({**base,'direction_id':d['direction_id'],'kind':'plan_repair',
                            'state':'awaiting_access','reason':'DISCOVERY_DIRECTION_SOURCE_UNAVAILABLE'})
                    rows = [(provider,row) for provider, values in plan.get('queries', {}).items() for row in values
                            if row.get('action_purpose') == 'discovery' and country in row_jurisdictions(provider,row)
                            and row.get('right_type') == right and any(ref.get('scenario_id') == sid
                                and ref.get('direction_id') == d['direction_id'] for ref in row.get('product_dependencies', []))]
                    if not rows:
                        # Direction review remains mandatory for applicability and
                        # scope, but an absent query is a work item only when the
                        # canonical coverage contract requires that axis here.
                        if not _has_discovery_obligation(task, country, right):
                            continue
                        if _direction_has_local_provenance_route(task, plan, d, direction_basis, country):
                            # The bound local investigation has its own result and
                            # completion lifecycle. It cannot satisfy official
                            # discovery axes, which remain governed by their own
                            # route/coverage obligations.
                            continue
                        if _empty_figurative_inventory_closes_current_direction(task, sid, right, d, review):
                            continue
                        if _empty_own_word_mark_waits_for_information(task, sid, right, d, review):
                            continue
                        entries.append({**base,'direction_id':d['direction_id'],'kind':'plan_repair',
                                        'state':'ready','reason':'DISCOVERY_DIRECTION_QUERY_MISSING'})
                        continue
                    complete = False
                    pending = []
                    for provider,row in rows:
                        from api_first_planning import pagination_parent_stop_valid
                        if pagination_parent_stop_valid(task, plan, evidence, candidates, ledger, row, supplement):
                            continue
                        from workflow_v24 import validated_query_cancellation
                        if (task.get('retrieval_workflow_revision') == 'api-first-v3'
                                and validated_query_cancellation(task, plan, row)):
                            from api_first_planning import retained_discovery_work
                            cancelled_runs = [run for run in evidence.get('source_runs', [])
                                if run.get('provider') == provider and run.get('query_id') == row.get('query_id')
                                and run.get('plan_entry_sha256') == sha256_json(row)]
                            # A withdrawn, never submitted query has no before
                            # obligation. Actual retained responses (including
                            # logical reuse) continue through their after gate.
                            if (not cancelled_runs
                                    and not retained_discovery_work(task, evidence, candidates, ledger,
                                        provider, row, supplement, task_dir=task_dir)):
                                continue
                        before = current(task,plan,evidence,stage='before',scenario_id=sid,jurisdiction=country,
                            right_type=right,direction_id=d['direction_id'],provider=provider,row=row,task_dir=task_dir)
                        row_base = {**base,'direction_id':d['direction_id'],'query_id':row['query_id'],
                                    'provider':provider,'discovery_intent_id':row.get('discovery_intent_id'),
                                    'plan_entry_sha256':sha256_json(row)}
                        if before is None or before.get('direction_review_sha256') != review['review_sha256']:
                            prior_attempts = [run for run in evidence.get('source_runs', [])
                                if run.get('query_id') == row['query_id'] and run.get('provider') == provider
                                and run.get('plan_entry_sha256') == sha256_json(row)
                                and run.get('submission_state') != 'not_submitted']
                            if prior_attempts:
                                # A current preflight review cannot be backfilled for an
                                # attempted or unknown-submission query. Reconcile its
                                # historical evidence through the plan-repair route.
                                pending.append({**row_base,'kind':'plan_repair','state':'ready',
                                    'reason':'DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED',
                                    'source_run_id':prior_attempts[-1]['run_id'],
                                    'historical_expression_review_missing':True})
                            else:
                                pending.append({**row_base,'kind':'agent_investigation','state':'awaiting_review',
                                                'reason':'DISCOVERY_EXPRESSION_REVIEW_REQUIRED'})
                            continue
                        if before['semantic_fit'] == 'mismatch':
                            pending.append({**row_base,'kind':'plan_repair','state':'ready',
                                            'reason':'DISCOVERY_EXPRESSION_MISMATCH'})
                            continue
                        after = current(task,plan,evidence,stage='after',scenario_id=sid,jurisdiction=country,
                            right_type=right,direction_id=d['direction_id'],provider=provider,row=row,task_dir=task_dir)
                        if after and after.get('before_review_sha256') == before['review_sha256'] and after['problem_covered']:
                            complete = True
                            continue
                        runs = [run for run in evidence.get('source_runs', []) if run.get('query_id') == row['query_id']
                                and run.get('provider') == provider and run.get('plan_entry_sha256') == sha256_json(row)
                                and run.get('status') in {'success','no_result'}]
                        if runs:
                            if after and after.get('before_review_sha256') == before['review_sha256']:
                                waiting_clue = (_after_waiting_information(review, after)
                                                if after.get('next_action') == 'awaiting_information' else None)
                                bounded_review = None
                                fault_review = None
                                if after.get('next_action') == 'awaiting_capability':
                                    public_scope = _current_public_ranked_scope_wait(task, plan, evidence,
                                        candidates, ledger, supplement, task_dir, provider, row, after, runs[-1])
                                    if public_scope:
                                        pending.append(public_ranked_scope_entry(row_base, row, after, runs[-1], public_scope))
                                        continue
                                    fault_review = _current_source_fault_wait(task, plan, evidence, candidates,
                                        ledger, supplement, task_dir, provider, row, after, runs[-1])
                                    bounded_review = _current_bounded_capability_wait(task, plan, evidence,
                                        candidates, ledger, supplement, task_dir, provider, row, after, runs[-1])
                                if waiting_clue:
                                    # The matching user-information entry was
                                    # emitted above from this same direction review.
                                    continue
                                if fault_review:
                                    pending.append({**row_base,'kind':'plan_repair','state':'awaiting_access',
                                        'reason':'SOURCE_FAULT_UNVERIFIED','source_run_id':runs[-1]['run_id'],
                                        'bounded_stop_review_id':fault_review.get('review_id'),
                                        'coverage_status':'unknown','uncovered_clues':after.get('uncovered_clues',[])})
                                    continue
                                if bounded_review:
                                    pending.append({**row_base,'kind':'plan_repair','state':'awaiting_access',
                                        'reason':'BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED',
                                        'source_run_id':runs[-1]['run_id'],
                                        'bounded_stop_review_id':bounded_review.get('review_id'),
                                        'uncovered_clues':after.get('uncovered_clues',[]),
                                        'unretrieved_result_row_count':(runs[-1].get('metadata',{})
                                            .get('search_coverage',{}).get('unretrieved_result_row_count'))})
                                    continue
                            pending.append({**row_base,'kind':'plan_repair' if after else 'agent_investigation',
                                'state':'ready' if after else 'awaiting_review',
                                'reason':'DISCOVERY_DIRECTION_GAP_REPLAN_REQUIRED' if after else 'DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED',
                                'source_run_id':runs[-1]['run_id']})
                    if complete:
                        # Coverage by one valid route does not waive review of
                        # other material that was already obtained.
                        entries.extend(item for item in pending
                            if item['reason'] == 'DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED')
                    else:
                        entries.extend(pending)
    return entries


def verify(task, plan, evidence, task_dir=None):
    if not enabled(task):
        return
    rows = _events(task)
    seen = set()
    for event in rows:
        if (not isinstance(event, dict) or event.get('review_id') in seen
                or event.get('review_sha256') != _digest(event)
                or event.get('review_id') != stable_id('SEM',task['task_id'],event['review_sha256'])):
            raise ValueError('DISCOVERY_SEMANTIC_RECEIPT_CHANGED')
        seen.add(event['review_id'])
        if task_dir is not None:
            path = resolve_retained_path(Path(task_dir),
                Path('raw')/'discovery_semantics'/(event['review_id']+'.json'))
            if load_json(path) != event:
                raise ValueError('DISCOVERY_SEMANTIC_RECEIPT_CHANGED')
        # An old review can be stale after a scope update; retain its history.
        # Current use always calls validate again against the new scope/plan.

#!/usr/bin/env python3
"""Record 03B direction, before-query and after-result human semantic reviews."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_json, stable_id
from execution_lock import execution_lock
import discovery_semantics as ds


def _prepare(task, plan, evidence, task_dir: Path, request):
    """Validate one review against in-memory state; return (event, is_new). Nothing is written here."""
    request_sha256 = sha256_json(request)
    existing_request = next((item for item in task.get('discovery_semantic_reviews', [])
                             if item.get('request_sha256') == request_sha256),None)
    if existing_request:
        try:
            ds.validate(task, plan, evidence, existing_request, task_dir)
        except ValueError as exc:
            raise ValueError('DISCOVERY_SEMANTIC_STALE_REQUEST') from exc
        return existing_request, False
    stage = request['stage']
    event = deepcopy(request)
    for key in ('review_id', 'review_sha256', 'reviewed_at', 'scope_sha256',
                'product_identity_sha256', 'plan_entry_sha256', 'actual_query',
                'discovery_intent_id', 'refinement_round', 'direction_review_sha256',
                'before_review_sha256', 'source_run_sha256', 'request_sha256',
                'direction_basis_sha256'):
        if key in event:
            raise ValueError('DISCOVERY_SEMANTIC_SYSTEM_FIELD_FORBIDDEN')
    event.update(request_sha256=request_sha256,scope_sha256=task['product_scope']['scope_sha256'],
        product_identity_sha256=task['product_identity']['sha256'], reviewed_at=now_iso())
    if stage == 'direction':
        event['direction_basis_sha256'] = ds._direction_basis(task,event.get('scenario_id'),event.get('right_type'))
        scoped = {(provider,row['query_id'],sha256_json(row)) for provider,values in plan.get('queries',{}).items()
                  for row in values if row.get('action_purpose') == 'discovery'
                  and event.get('jurisdiction') in ds.row_jurisdictions(provider,row)
                  and row.get('right_type') == event.get('right_type')
                  and any(ref.get('scenario_id') == event.get('scenario_id')
                          for ref in row.get('product_dependencies',[]))}
        had_direction_review = any(item.get('stage') == 'direction'
            and all(item.get(key) == event.get(key) for key in ('scenario_id','jurisdiction','right_type'))
            for item in task.get('discovery_semantic_reviews',[]))
        if not had_direction_review and any((run.get('provider'),run.get('query_id'),run.get('plan_entry_sha256')) in scoped
               and run.get('submission_state') != 'not_submitted'
               for run in evidence.get('source_runs',[])):
            raise ValueError('DISCOVERY_DIRECTION_REVIEW_TOO_LATE')
    if stage != 'direction':
        matches = [(provider,row) for provider, values in plan.get('queries', {}).items() for row in values
                   if row.get('query_id') == event.get('query_id')]
        if len(matches) != 1:
            raise ValueError('DISCOVERY_SEMANTIC_QUERY_REQUIRED')
        provider,row = matches[0]
        if event.get('provider') not in (None, provider):
            raise ValueError('DISCOVERY_SEMANTIC_PROVIDER_CHANGED')
        event.update(provider=provider, plan_entry_sha256=sha256_json(row),
            actual_query=row.get('q'),discovery_intent_id=row.get('discovery_intent_id'),
            refinement_round=row.get('refinement_round'))
        if stage == 'before' and any(run.get('provider') == provider
                and run.get('query_id') == row.get('query_id')
                and run.get('plan_entry_sha256') == sha256_json(row)
                and run.get('submission_state') != 'not_submitted'
                for run in evidence.get('source_runs',[])):
            raise ValueError('DISCOVERY_EXPRESSION_REVIEW_TOO_LATE')
        direction = ds.current(task,plan,evidence,stage='direction',scenario_id=event.get('scenario_id'),
            jurisdiction=event.get('jurisdiction'),right_type=event.get('right_type'),task_dir=task_dir)
        if direction is None:
            raise ValueError('DISCOVERY_DIRECTION_REVIEW_REQUIRED')
        event['direction_review_sha256'] = direction['review_sha256']
        if stage == 'after':
            before = ds.current(task,plan,evidence,stage='before',scenario_id=event.get('scenario_id'),
                jurisdiction=event.get('jurisdiction'),right_type=event.get('right_type'),
                direction_id=event.get('direction_id'),provider=provider,row=row,task_dir=task_dir)
            if before is None or before['direction_review_sha256'] != direction['review_sha256']:
                raise ValueError('DISCOVERY_BEFORE_REVIEW_REQUIRED')
            event['before_review_sha256'] = before['review_sha256']
            runs = [run for run in evidence.get('source_runs', []) if run.get('run_id') == event.get('source_run_id')]
            if len(runs) != 1:
                raise ValueError('DISCOVERY_AFTER_SOURCE_REQUIRED')
            event['source_run_sha256'] = sha256_json(runs[0])
    ds.validate(task,plan,evidence,event,task_dir)
    event['review_sha256'] = ds._digest(event)
    event['review_id'] = stable_id('SEM',task['task_id'],event['review_sha256'])
    existing = next((item for item in task.get('discovery_semantic_reviews', [])
                     if item.get('review_id') == event['review_id']),None)
    if existing:
        if existing != event:
            raise ValueError('DISCOVERY_SEMANTIC_REVIEW_ID_REUSED')
        return existing, False
    return event, True


def _open(task_dir: Path):
    task = load_json(task_dir/'task.json')
    plan = load_json(task_dir/'search-plan.json')
    evidence = load_json(task_dir/'evidence.json')
    if not ds.enabled(task):
        raise ValueError('DISCOVERY_SEMANTICS_TASK_REQUIRED')
    import product_scope as ps
    ps.verify(task, evidence, task_dir)
    ds.verify(task, plan, evidence, task_dir)
    return task, plan, evidence


def _persist(task, plan, evidence, task_dir: Path, events):
    """Write raw receipts, append the events and store task.json once, verifying the whole set."""
    for event in events:
        raw = task_dir/'raw'/'discovery_semantics'/(event['review_id']+'.json')
        if raw.exists() and load_json(raw) != event:
            raise ValueError('DISCOVERY_SEMANTIC_RECEIPT_CHANGED')
        atomic_write_json(raw, event)
        task.setdefault('discovery_semantic_reviews', []).append(event)
    ds.verify(task, plan, evidence, task_dir)
    atomic_write_json(task_dir/'task.json', task)


def record(task_dir: Path, input_path: Path):
    task_dir = task_dir.resolve()
    request = load_json(input_path.resolve())
    if not isinstance(request, dict) or request.get('stage') not in ds.STAGES:
        raise ValueError('DISCOVERY_SEMANTIC_REVIEW_INVALID')
    with execution_lock(task_dir, 'discovery-semantics'):
        task, plan, evidence = _open(task_dir)
        event, new = _prepare(task, plan, evidence, task_dir, request)
        if new:
            _persist(task, plan, evidence, task_dir, [event])
        return event


def record_batch(task_dir: Path, requests: list):
    """Record several reviews under one lock: one load, one full verification before, one after, one write.

    Each review is validated against the in-memory task that already holds the
    earlier reviews of the batch (direction before query before result), exactly
    as sequential calls would; nothing is written unless every review is accepted.
    """
    task_dir = task_dir.resolve()
    if (not isinstance(requests, list) or not requests
            or any(not isinstance(item, dict) or item.get('stage') not in ds.STAGES for item in requests)):
        raise ValueError('DISCOVERY_SEMANTIC_REVIEW_INVALID')
    with execution_lock(task_dir, 'discovery-semantics'):
        task, plan, evidence = _open(task_dir)
        results, new_events = [], []
        for request in requests:
            event, new = _prepare(task, plan, evidence, task_dir, request)
            if new:
                task.setdefault('discovery_semantic_reviews', []).append(event)
                new_events.append(event)
            results.append(event)
        # _prepare saw the batch's earlier events through the appended task; persist them for real now.
        task['discovery_semantic_reviews'] = task['discovery_semantic_reviews'][:len(task['discovery_semantic_reviews'])-len(new_events)]
        if new_events:
            _persist(task, plan, evidence, task_dir, new_events)
        return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir',type=Path,required=True)
    parser.add_argument('--input',type=Path,required=True)
    args = parser.parse_args()
    request = load_json(args.input.resolve())
    if isinstance(request, dict) and set(request) == {'events'}:
        print(' '.join(event['review_id'] for event in record_batch(args.task_dir, request['events'])))
        return
    print(record(args.task_dir,args.input)['review_id'])


if __name__ == '__main__':
    main()

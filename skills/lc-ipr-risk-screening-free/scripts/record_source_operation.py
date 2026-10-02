#!/usr/bin/env python3
"""Append a 03C source-operation review; never infer acceptance from HTTP success."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from common import atomic_write_json, load_json, sha256_json, stable_id
from execution_lock import execution_lock
import source_operation as so


def record(task_dir: Path, input_path: Path):
    """Validate a batch against one snapshot and persist task state once."""
    task_dir = task_dir.resolve()
    payload = load_json(input_path.resolve())
    batch = isinstance(payload, dict) and set(payload) == {'reviews'}
    requests = payload['reviews'] if batch else [payload]
    if not isinstance(requests, list) or not requests:
        raise ValueError('SOURCE_OPERATION_REVIEWS_REQUIRED')
    for request in requests:
        if not isinstance(request, dict) or any(key in request for key in
                ('review_id', 'review_sha256', 'reviewed_at', 'plan_entry_sha256', 'source_run_sha256')):
            raise ValueError('SOURCE_OPERATION_SYSTEM_FIELD_FORBIDDEN')
    with execution_lock(task_dir, 'source-operation'):
        task = load_json(task_dir / 'task.json')
        plan = load_json(task_dir / 'search-plan.json')
        evidence = load_json(task_dir / 'evidence.json')
        so.verify(task, plan, evidence, task_dir)
        events, additions = [], []
        retained = list(task.get('source_operation_reviews', []))
        for request in requests:
            provider = request.get('provider')
            matches = [row for row in plan.get('queries', {}).get(provider, [])
                       if row.get('query_id') == request.get('query_id')]
            if len(matches) != 1:
                raise ValueError('SOURCE_OPERATION_QUERY_REQUIRED')
            runs = [run for run in so._runs(evidence, provider, matches[0])
                    if run.get('run_id') == request.get('source_run_id')]
            if len(runs) != 1:
                raise ValueError('SOURCE_OPERATION_RUN_REQUIRED')
            body = {**deepcopy(request), 'plan_entry_sha256': sha256_json(matches[0]),
                    'source_run_sha256': sha256_json(runs[0])}
            latest = next((event for event in reversed(retained)
                if all(event.get(key) == body.get(key) for key in
                    ('provider', 'query_id', 'source_run_id', 'plan_entry_sha256', 'source_run_sha256'))), None)
            previous = latest if latest is not None and {key: value for key, value in latest.items()
                if key not in {'review_id', 'review_sha256', 'reviewed_at'}} == body else None
            if previous is not None:
                so.validate(task, plan, evidence, previous, task_dir)
                events.append(previous)
                continue
            event = {**body, 'reviewed_at': datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')}
            so.validate(task, plan, evidence, event, task_dir)
            event['review_sha256'] = sha256_json(event)
            event['review_id'] = stable_id('SOP', task['task_id'], event['review_sha256'])
            additions.append(event)
            retained.append(event)
            events.append(event)
        # No receipt or task mutation occurs before the entire batch validates.
        for event in additions:
            path = task_dir / 'raw' / 'source_operation' / (event['review_id'] + '.json')
            if path.is_file() and load_json(path) != event:
                raise ValueError('SOURCE_OPERATION_RECEIPT_CHANGED')
        for event in additions:
            atomic_write_json(task_dir / 'raw' / 'source_operation' / (event['review_id'] + '.json'), event)
        if additions:
            task['source_operation_reviews'] = retained
            atomic_write_json(task_dir / 'task.json', task)
        return {'reviews': events, 'recorded_count': len(additions)} if batch else events[0]


from runtime_timing import timed_cli


@timed_cli('source_operation_recording')
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    result = record(args.task_dir, args.input)
    if 'reviews' in result:
        import json
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(result['review_id'])


if __name__ == '__main__':
    main()

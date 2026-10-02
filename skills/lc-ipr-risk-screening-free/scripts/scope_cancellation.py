"""03C cancellation of a removed scope direction requires a confirmed change."""
from __future__ import annotations

from pathlib import Path
import argparse

from common import atomic_write_json, load_json, sha256_json
from execution_lock import execution_lock


def _dependencies(row):
    return [(ref.get('scenario_id'), ref.get('direction_id'))
            for ref in row.get('product_dependencies', []) if isinstance(ref, dict)
            and ref.get('scenario_id') and ref.get('direction_id')]


def _removed(task, row):
    import product_scope as ps
    if not ps.enabled(task):
        return False
    dependencies = _dependencies(row)
    if not dependencies:
        return False
    current = {(d['scenario_id'], d['direction_id']): d for d in ps.directions(task)}
    if all(pair not in current or ps.direction_state(task, current[pair]) == 'out_of_scope'
           for pair in dependencies):
        return True
    # A future brand direction may remain in scope while an older local mark
    # inventory has no current target. Only a reviewed empty mark inventory can
    # cancel those obsolete local actions; it cannot cancel official searches.
    if (row.get('operation') != 'provenance_review'
            or row.get('right_type') != 'trademark_figurative'
            or row.get('action_purpose') != 'provenance'
            or row.get('derived_from') != ['product.mark_inventory']
            or row.get('search_dimension') not in {'classification', 'visual_comparison'}
            or not row.get('asset_scope_sha256')):
        return False
    from record_asset_provenance import asset_scope
    for sid, direction_id in dependencies:
        direction = current.get((sid, direction_id))
        if not direction or direction.get('right_type') != 'trademark_figurative':
            return False
        scope = asset_scope(task, sid, 'trademark_figurative')
        if (not scope.get('inventory_reviewed') or scope.get('asset_ids')
                or scope.get('scope_sha256') == row['asset_scope_sha256']):
            return False
    return True


def scope_change_required(task, row):
    return _removed(task, row) and any(row.get('query_id') in event.get('affected_query_ids', [])
        for event in task.get('product_change_history', []))


def _business_scope_sha256(task):
    scope = task.get('product_scope', {})
    return sha256_json({key: scope.get(key, []) for key in ('objects', 'facts', 'directions')})


def _current_change_basis(task, event, item):
    if event.get('scope_sha256') == task.get('product_scope', {}).get('scope_sha256'):
        return True
    # Candidate links and delivery metadata do not revise product facts. A
    # separately retained cancellation can survive those updates only while
    # the confirmed business change and its full business scope stay current.
    version = event.get('version')
    return (isinstance(version, int) and not isinstance(version, bool) and version > 0
            and version == task.get('product_change_version')
            and event.get('target_sha256') == task.get('product_identity', {}).get('sha256')
            and bool(event.get('target_sha256'))
            and task.get('product_change_history', [])[-1].get('sha256') == event.get('sha256')
            and item.get('business_scope_sha256') == _business_scope_sha256(task))


def valid_scope_cancellation(task, row, item):
    if not scope_change_required(task, row) or task.get('product_change_pending'):
        return False
    if item.get('reason_code') != 'SCOPE_CHANGE':
        return False
    events = [event for event in task.get('product_change_history', [])
        if event.get('change_id') == item.get('scope_change_id')]
    if len(events) != 1:
        return False
    event = events[0]
    if (event.get('sha256') != sha256_json({key: value for key, value in event.items() if key != 'sha256'})
            or event.get('sha256') != item.get('scope_change_sha256')
            or not _current_change_basis(task, event, item)
            or row.get('query_id') not in event.get('affected_query_ids', [])):
        return False
    return all(direction_id in event.get('affected_direction_ids', [])
               for _, direction_id in _dependencies(row))


def record(task_dir: Path, query_id: str, change_id: str, reviewer: str, reason: str):
    task_dir = task_dir.resolve()
    if not reviewer.strip() or not reason.strip():
        raise ValueError('SCOPE_CANCELLATION_REASON_REQUIRED')
    with execution_lock(task_dir, 'scope-cancellation'):
        task = load_json(task_dir / 'task.json')
        plan = load_json(task_dir / 'search-plan.json')
        rows = [row for values in plan.get('queries', {}).values() for row in values
                if row.get('query_id') == query_id]
        if len(rows) != 1 or not scope_change_required(task, rows[0]):
            raise ValueError('SCOPE_CANCELLATION_DIRECTION_REQUIRED')
        event = next((event for event in task.get('product_change_history', [])
                      if event.get('change_id') == change_id), None)
        if event is None:
            raise ValueError('SCOPE_CANCELLATION_CHANGE_REQUIRED')
        item = {'query_id': query_id, 'plan_entry_sha256': sha256_json(rows[0]),
                'status': 'cancelled', 'reason_code': 'SCOPE_CHANGE',
                'scope_change_id': change_id, 'scope_change_sha256': event['sha256'],
                'business_scope_sha256': _business_scope_sha256(task),
                'reviewer': reviewer, 'reason': reason}
        if not valid_scope_cancellation(task, rows[0], item):
            raise ValueError('SCOPE_CANCELLATION_CHANGE_UNCONFIRMED')
        if item not in plan.setdefault('execution_dispositions', []):
            plan['execution_dispositions'].append(item)
            atomic_write_json(task_dir / 'search-plan.json', plan)
        return item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--query-id', required=True)
    parser.add_argument('--change-id', required=True)
    parser.add_argument('--reviewer', required=True)
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    print(record(args.task_dir, args.query_id, args.change_id,
                 args.reviewer, args.reason)['query_id'])


if __name__ == '__main__':
    main()

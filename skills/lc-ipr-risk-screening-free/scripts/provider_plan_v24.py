"""Minimal exact-plan adapter shared by the new 2.4 providers."""
from pathlib import Path
from common import assert_provider_execution_allowed, ensure_object, load_json
from provider_utils import PLAN_META_KEYS, ProviderError, authorize_exact_plan_execution


def load_action(task_dir: Path, provider: str, query_id: str, operations: set[str]) -> tuple[dict, dict, dict]:
    task = ensure_object(load_json(task_dir / 'task.json'), 'task.json')
    if task.get('schema_version') != '2.4-free':
        raise ProviderError('NEW_PROVIDER_SCHEMA_REQUIRED', 'failed', 'This provider requires a 2.4-free task')
    plan = ensure_object(load_json(task_dir / 'search-plan.json'), 'search-plan.json')
    matches = [(name, row) for name, rows in plan.get('queries', {}).items() if isinstance(rows, list)
               for row in rows if isinstance(row, dict) and row.get('query_id') == query_id]
    if len(matches) != 1 or matches[0][0] != provider:
        raise ProviderError('QUERY_ID_NOT_EXACTLY_PLANNED', 'failed', 'The query ID must select one globally unique provider action')
    item = dict(matches[0][1])
    if item.get('operation') not in operations:
        raise ProviderError('QUERY_PLAN_SCOPE_MISMATCH', 'failed', 'Unexpected provider operation')
    try:
        assert_provider_execution_allowed(task, provider, item['operation'], jurisdiction=item.get('jurisdiction', ''), right_type=item.get('right_type', ''))
    except ValueError as exc:
        raise ProviderError('PROVIDER_OPERATION_NOT_CONFIGURED', 'failed', str(exc)) from None
    params = {key: value for key, value in item.items() if key not in PLAN_META_KEYS}
    params['right_type'] = item.get('right_type', '')
    authorized = authorize_exact_plan_execution(task_dir, task, provider, item['operation'], query_id,
        jurisdiction=item.get('jurisdiction', ''), right_type=item.get('right_type', ''),
        query=item.get('q', ''), request_params=params)
    if not authorized:
        raise ProviderError('QUERY_PLAN_AUTHORIZATION_UNAVAILABLE', 'failed', 'Exact-plan authorization did not recognize this new provider operation')
    return task, item, params

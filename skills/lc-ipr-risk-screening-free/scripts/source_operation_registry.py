"""Maintainer-owned reusable operation acceptance; shipped empty without live evidence."""
from __future__ import annotations

from pathlib import Path

from common import atomic_write_json, load_json, sha256_json

REGISTRY_PATH = Path(__file__).resolve().parent.parent / 'references' / 'source-operation-registry.json'
KEYS = ('provider', 'jurisdiction', 'right_type', 'operation', 'query_compiler_revision',
        'search_dimension')


def read(path=None):
    value = load_json(Path(path or REGISTRY_PATH))
    if value.get('schema_version') != 'source-operation-registry-v1' or not isinstance(value.get('entries'), list):
        raise ValueError('SOURCE_OPERATION_REGISTRY_INVALID')
    seen = set()
    for entry in value['entries']:
        if (not isinstance(entry, dict) or entry.get('state') not in
                {'automatic', 'access_verification_only', 'unvalidated', 'unavailable'}
                or any(not isinstance(entry.get(key), str) for key in KEYS)
                or any(not isinstance(entry.get(key), str) or not entry[key].strip() for key in
                       ('input_mode', 'limitations', 'reviewer', 'acceptance_reason', 'checked_at',
                        'adapter_version', 'acceptance_review_sha256'))
                or entry.get('entry_sha256') != sha256_json({k: v for k, v in entry.items() if k != 'entry_sha256'})
                or entry['entry_sha256'] in seen):
            raise ValueError('SOURCE_OPERATION_REGISTRY_ENTRY_INVALID')
        seen.add(entry['entry_sha256'])
    return value


def latest_states(provider, path=None):
    latest = {}
    for entry in read(path)['entries']:
        if entry['provider'] == provider:
            latest[tuple(entry[key] for key in KEYS[1:])] = entry['state']
    return latest


def current_entries(provider, path=None):
    latest = {}
    for entry in read(path)['entries']:
        if entry['provider'] == provider:
            latest[tuple(entry[key] for key in KEYS)] = entry
    return [{**{key: value for key, value in entry.items() if key not in {'provider', 'entry_sha256'}},
             'registry_entry_sha256': entry['entry_sha256']}
            for entry in latest.values()]


def operations_for(provider, path=None):
    return [entry for entry in current_entries(provider, path) if entry['state'] == 'automatic']


def retained_operations(provider, snapshot, path=None):
    accepted = {sha256_json(operation): operation for operation in operations_for(provider, path)}
    return [accepted[sha256_json(operation)] for operation in snapshot if sha256_json(operation) in accepted]


def retained_states(provider, snapshot, path=None):
    current = {sha256_json(entry): entry for entry in current_entries(provider, path)}
    return [current[sha256_json(entry)] for entry in snapshot if sha256_json(entry) in current]


def promote(task_dir, review_id, *, maintainer, acceptance_reason, input_mode, limitations,
            adapter_version, state='automatic', path=None):
    """A maintainer explicitly promotes a reviewed retained run for future tasks."""
    import source_operation as so
    task_dir = Path(task_dir).resolve()
    task, plan, evidence = (load_json(task_dir / name) for name in
                            ('task.json', 'search-plan.json', 'evidence.json'))
    so.verify(task, plan, evidence, task_dir)
    reviews = [r for r in task.get('source_operation_reviews', []) if r.get('review_id') == review_id]
    if len(reviews) != 1 or state not in {
            'automatic', 'access_verification_only', 'unvalidated', 'unavailable'}:
        raise ValueError('SOURCE_OPERATION_REVIEW_STATE_INVALID')
    if (state == 'automatic') != (reviews[0].get('decision') == 'accepted'):
        raise ValueError('SOURCE_OPERATION_REVIEW_STATE_MISMATCH')
    if not all(isinstance(v, str) and v.strip() for v in
               (maintainer, acceptance_reason, input_mode, limitations, adapter_version)):
        raise ValueError('SOURCE_OPERATION_REGISTRY_DETAILS_REQUIRED')
    review = reviews[0]
    row, _ = so.validate(task, plan, evidence, review, task_dir)
    entry = {**{key: row.get(key, '') for key in KEYS if key != 'provider'},
             'provider': review['provider'], 'state': state,
             'input_mode': input_mode, 'limitations': limitations,
             'reviewer': maintainer, 'acceptance_reason': acceptance_reason,
             'checked_at': review['reviewed_at'],
             'adapter_version': adapter_version,
             'acceptance_review_sha256': review['review_sha256']}
    entry['entry_sha256'] = sha256_json(entry)
    destination = Path(path or REGISTRY_PATH)
    registry = read(destination)
    if entry not in registry['entries']:
        registry['entries'].append(entry)
        atomic_write_json(destination, registry)
    return entry


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--review-id', required=True)
    parser.add_argument('--maintainer', required=True)
    parser.add_argument('--acceptance-reason', required=True)
    parser.add_argument('--input-mode', required=True)
    parser.add_argument('--limitations', required=True)
    parser.add_argument('--adapter-version', required=True)
    parser.add_argument('--state', choices=('automatic', 'access_verification_only',
                                            'unvalidated', 'unavailable'), default='automatic')
    parser.add_argument('--registry', type=Path, default=REGISTRY_PATH)
    args = parser.parse_args()
    entry = promote(args.task_dir, args.review_id, maintainer=args.maintainer,
                    acceptance_reason=args.acceptance_reason, input_mode=args.input_mode,
                    limitations=args.limitations, adapter_version=args.adapter_version,
                    state=args.state, path=args.registry)
    print(entry['entry_sha256'])


if __name__ == '__main__':
    main()

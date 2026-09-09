"""Strict read-only projection for the first API-first pre-sanitization hashes."""
from pathlib import Path
import re
from common import API_FIRST_REVISION, load_json, path_within, sha256_file, sha256_json


def retained_records(evidence, run, task_dir, *, provider, normalize_records, invalid, projection_revision):
    """Verify retained bytes and every normalized field before a legacy projection.

    The pre-sanitization digest is unavailable and remains explicitly unverified.
    A staged record must match in full; it cannot enter the legacy conversion.
    """
    if run.get('provider') != provider or run.get('status') not in {'success', 'no_result'}:
        raise ValueError(invalid)
    paths = run.get('raw_paths')
    if not isinstance(paths, list) or len(paths) != 1 or not run.get('payload_digest'):
        raise ValueError(invalid)
    path = Path(paths[0])
    if not path.is_absolute():
        if task_dir is None:
            raise ValueError(invalid)
        path = Path(task_dir) / path
    if (task_dir is not None and not path_within(path.resolve(), Path(task_dir).resolve())) or sha256_file(path) != run['payload_digest']:
        raise ValueError(invalid)
    entries = [entry for group in evidence.get('collections', {}).values() if isinstance(group, list)
               for entry in group if isinstance(entry, dict) and entry.get('source_run_id') == run.get('run_id')]
    if len(entries) != 1:
        raise ValueError(invalid)
    entry = entries[0]
    if (entry.get('provider') != provider or not run.get('run_id') or not run.get('query_id')
            or entry.get('query_id') != run['query_id'] or entry.get('operation') != run.get('operation')
            or not run.get('plan_entry_sha256')
            or entry.get('plan_entry_sha256') != run['plan_entry_sha256']):
        raise ValueError(invalid)
    old = (entry.get('payload') or {}).get('candidates')
    fresh = normalize_records(load_json(path))
    if not isinstance(old, list) or len(old) != len(fresh) or (run['status'] == 'no_result') != (len(old) == 0):
        raise ValueError(invalid)
    projected = []
    for prior, current in zip(old, fresh):
        if not isinstance(prior, dict) or prior.get('retrieval_workflow_revision') != API_FIRST_REVISION:
            raise ValueError(invalid)
        if prior.get('source_record_hash_stage') == 'retained-v1':
            if prior != current:
                raise ValueError(invalid)
            projected.append(dict(current))
            continue
        if ('source_record_hash_stage' in prior or not re.fullmatch(r'[0-9a-f]{64}', str(prior.get('source_record_sha256') or ''))
                or {k: v for k, v in prior.items() if k != 'source_record_sha256'} !=
                   {k: v for k, v in current.items() if k not in {'source_record_sha256', 'source_record_hash_stage'}}):
            raise ValueError(invalid)
        projected.append({**current, 'original_source_record_sha256': prior['source_record_sha256'],
                          'normalization_provenance': {'revision': projection_revision,
                              'original_hash_verified': False, 'original_normalized_record_sha256': sha256_json(prior),
                              'source_run_id': run['run_id'], 'payload_digest': run['payload_digest'],
                              'plan_entry_sha256': run['plan_entry_sha256']}})
    return projected


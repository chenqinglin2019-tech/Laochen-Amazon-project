#!/usr/bin/env python3
"""Route unlinked candidates to the product objects they are compared with.

A link is a routing record, never a relevance finding: each linked candidate
still needs its own triage decision. Two unambiguous cases are automated:

* the candidate's own retained query was planned for specific product objects
  (its ``product_dependencies``) and at least one of them is an included object
  whose right types cover the candidate: link exactly those objects;
* otherwise link every included object whose right types cover the candidate's
  right. Excluded or pending objects are never linked here, so they cannot hide
  a candidate from assessment against the included objects.

A candidate with no included compatible object, no compatible object at all or
no retained source evidence stays with the existing Agent scope review, which
owns the report-visible scope reason. Nothing here changes a product fact,
object state or direction.
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from common import atomic_write_json, load_json, sha256_json

REVIEWER = 'program:candidate-scope-link-v1'
ROUTING_NOTE = '本关联只决定与哪些产品对象比较，候选相关性由随后的分流决定（程序规则，非相关性结论）。'
OUTPUT_DIR = 'host-ledger'


def _source_refs(candidate, registry=None):
    refs = []
    for value in candidate.get('evidence_refs') or []:
        if isinstance(value, str) and value.strip() and value not in refs:
            refs.append(value)
    for source in candidate.get('sources') or []:
        ref = source.get('evidence_id') if isinstance(source, dict) else None
        if isinstance(ref, str) and ref.strip() and ref not in refs:
            refs.append(ref)
    if registry is not None:
        refs = [ref for ref in refs if ref in registry]
    return refs


def _planned(candidate, runs, rows):
    """Objects and query ids the candidate's own retained source queries were planned for."""
    objects, queries = set(), []
    for source in candidate.get('sources') or []:
        if not isinstance(source, dict):
            continue
        row = rows.get((runs.get(source.get('source_run_id')) or {}).get('query_id'))
        if not row:
            continue
        if row['query_id'] not in queries:
            queries.append(row['query_id'])
        for dependency in row.get('product_dependencies') or []:
            if isinstance(dependency, dict):
                objects.update(oid for oid in dependency.get('object_ids') or [] if isinstance(oid, str))
    return objects, queries


def plan_links(task, candidates, evidence=None, plan=None):
    """Return ``(links, skipped)``; never writes and never guesses an object."""
    import product_scope as ps
    from annotate_materiality import iter_candidates
    if not ps.enabled(task):
        return [], [{'reason': 'PRODUCT_SCOPE_NOT_ENABLED'}]
    try:
        data = ps.scope(task)
    except ValueError as exc:
        return [], [{'reason': str(exc)}]
    linked = {row.get('candidate_id') for row in data.get('candidate_links', []) if isinstance(row, dict)}
    objects = [row for row in data.get('objects', []) if isinstance(row, dict)]
    runs = {run.get('run_id'): run for run in (evidence or {}).get('source_runs', []) if isinstance(run, dict)}
    rows = {row.get('query_id'): row for values in ((plan or {}).get('queries') or {}).values()
            if isinstance(values, list) for row in values if isinstance(row, dict) and row.get('query_id')}
    registry = None
    if evidence is not None:
        registry = {entry.get('evidence_id') for values in evidence.get('collections', {}).values()
                    if isinstance(values, list) for entry in values if isinstance(entry, dict)}
    links, skipped = [], []
    for _collection, candidate in iter_candidates(candidates):
        cid = candidate.get('candidate_id')
        if not isinstance(cid, str) or not cid or cid in linked:
            continue
        right = candidate.get('right_type')
        if right == 'unknown':
            compatible = [row for row in objects if row.get('scope_status') == 'included']
        else:
            compatible = [row for row in objects if right in (row.get('right_types') or [])]
        if not compatible:
            skipped.append({'candidate_id': cid, 'reason': 'NO_COMPATIBLE_OBJECT'})
            continue
        refs = _source_refs(candidate, registry)
        if not refs:
            skipped.append({'candidate_id': cid, 'reason': 'NO_RETAINED_SOURCE_EVIDENCE'})
            continue
        planned, queries = _planned(candidate, runs, rows)
        included = [row for row in compatible if row.get('scope_status') == 'included']
        if not included:
            skipped.append({'candidate_id': cid, 'reason': 'NO_INCLUDED_COMPATIBLE_OBJECT'})
            continue
        chosen = [row for row in included if row['object_id'] in planned]
        if chosen:
            basis = '按候选来源查询 ' + '、'.join(queries) + ' 的产品依赖对象确定比较范围；'
        else:
            chosen, basis = included, '按权利类型与已纳入产品对象确定比较范围；'
        links.append({'candidate_id': cid, 'object_ids': [row['object_id'] for row in chosen],
                      'reason': basis + ROUTING_NOTE, 'source_refs': refs})
    return links, skipped


def record_links(root, links):
    """Append the planned links through the existing scope recorder in one snapshot."""
    from record_product_scope import record
    import product_scope as ps
    root = Path(root).resolve()
    task = load_json(root / 'task.json')
    scope = deepcopy(ps.content(ps.scope(task)))
    known = {row['candidate_id'] for row in scope.get('candidate_links', [])}
    scope['candidate_links'] = [*scope.get('candidate_links', []),
                                *[deepcopy(row) for row in links if row['candidate_id'] not in known]]
    payload = {'schema_version': 'product-scope-input-v2' if scope.get('delivery_revision') else 'product-scope-input-v1',
               'expected_scope_sha256': task['product_scope']['scope_sha256'], 'sources': [], 'scope': scope}
    directory = root / OUTPUT_DIR
    directory.mkdir(exist_ok=True)
    path = directory / ('scope-links-' + sha256_json(payload)[:24] + '.json')
    atomic_write_json(path, payload)
    return record(root, path)


def auto_link(root, *, dry_run=False):
    """Link every unambiguous candidate; return a compact receipt."""
    root = Path(root).resolve()
    task = load_json(root / 'task.json')
    candidates_path = root / 'normalized-candidates.json'
    if not candidates_path.is_file():
        return {'linked': 0, 'candidate_ids': [], 'skipped': [], 'status': 'no_candidates'}
    plan_path = root / 'search-plan.json'
    links, skipped = plan_links(task, load_json(candidates_path), load_json(root / 'evidence.json'),
                                load_json(plan_path) if plan_path.is_file() else {})
    receipt = {'reviewer': REVIEWER, 'linked': len(links), 'candidate_ids': [row['candidate_id'] for row in links],
               'skipped': skipped}
    if not links or dry_run:
        receipt['status'] = 'planned' if links else 'nothing_to_link'
        return receipt
    receipt['status'] = record_links(root, links)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true', help='print the links that would be recorded')
    args = parser.parse_args()
    print(json.dumps(auto_link(args.task_dir, dry_run=args.dry_run), ensure_ascii=False))


if __name__ == '__main__':
    main()

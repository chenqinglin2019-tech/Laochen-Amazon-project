#!/usr/bin/env python3
"""Record evidence-bound reviews of executed API-first discovery rows.

One review: ``--query-id Q --input review.json``. Several reviews in one atomic write:
``--input {"reviews":[{"query_id": "...", ...review fields...}, ...]}`` (no ``--query-id``);
each review is validated against the in-memory task that already holds the earlier
ones, and nothing is written unless every review is accepted.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common import atomic_write_json, ensure_object, load_json
from api_first_planning import append_review, prepare_review


def _parent(plan, query_id):
    matches = [row for rows in plan.get("queries", {}).values() if isinstance(rows, list)
               for row in rows if isinstance(row, dict) and row.get("query_id") == query_id]
    if len(matches) != 1:
        raise ValueError("DISCOVERY_REVIEW_EXACT_PLAN_REQUIRED")
    return matches[0]


def record_batch(task_dir: Path, reviews: list) -> list[str]:
    task_dir = Path(task_dir).resolve()
    if not isinstance(reviews, list) or not reviews or any(not isinstance(item, dict) for item in reviews):
        raise ValueError("DISCOVERY_REVIEW_BATCH_INVALID")
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    candidates = load_json(task_dir / "normalized-candidates.json")
    ledger = load_json(task_dir / "materiality-annotations.json")
    from workflow_v24 import scenario_supplement
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    parents, changed = [], False
    seen = set()
    for item in reviews:
        query_id = item.get("query_id")
        if not isinstance(query_id, str) or not query_id or query_id in seen:
            raise ValueError("DISCOVERY_REVIEW_BATCH_QUERY_ID_INVALID_OR_DUPLICATE")
        seen.add(query_id)
        request = {key: value for key, value in item.items() if key != "query_id"}
        record, evidence_changed = prepare_review(task_dir, task, plan, evidence, _parent(plan, query_id), request,
                                                  candidates=candidates, ledger=ledger, supplement=supplement)
        parents.append(record["parent_query_id"])
        changed = changed or evidence_changed
    if changed:
        atomic_write_json(task_dir / "evidence.json", evidence)
    atomic_write_json(task_dir / "task.json", task)
    return parents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query-id")
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    payload = load_json(args.input)
    if isinstance(payload, dict) and set(payload) == {"reviews"}:
        if args.query_id:
            parser.error("--query-id is not used with a {\"reviews\": [...]} batch")
        for parent in record_batch(task_dir, payload["reviews"]):
            print(parent)
        return
    if not args.query_id:
        parser.error("--query-id is required for a single review")
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    record = append_review(task_dir, task, plan, evidence, _parent(plan, args.query_id),
                           ensure_object(payload, "review"))
    print(record["parent_query_id"])


if __name__ == "__main__":
    main()

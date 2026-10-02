#!/usr/bin/env python3
"""Record one evidence-bound review of an executed API-first discovery row."""
from __future__ import annotations

import argparse
from pathlib import Path

from common import ensure_object, load_json
from api_first_planning import append_review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    matches = [row for rows in plan.get("queries", {}).values() if isinstance(rows, list)
               for row in rows if isinstance(row, dict) and row.get("query_id") == args.query_id]
    if len(matches) != 1:
        raise ValueError("DISCOVERY_REVIEW_EXACT_PLAN_REQUIRED")
    record = append_review(task_dir, task, plan, evidence, matches[0], ensure_object(load_json(args.input), "review"))
    print(record["parent_query_id"])


if __name__ == "__main__":
    main()

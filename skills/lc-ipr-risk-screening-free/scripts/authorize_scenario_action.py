#!/usr/bin/env python3
"""Read-only dispatch guard shared by the direct CDP CLI and Python callers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import ensure_object, load_json


def authorize(task_dir: Path, provider: str, query_id: str) -> dict:
    task = ensure_object(load_json(task_dir / "task.json"), "task")
    if "decision_workflow_revision" not in task:
        return {"allowed": True, "legacy": True}
    if task.get("decision_workflow_revision") != "scenario-triage-v1":
        return {"allowed": False, "code": "DECISION_WORKFLOW_REVISION_UNSUPPORTED"}
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "plan")
    rows = [(name, row) for name, group in plan.get("queries", {}).items()
            for row in group if isinstance(row, dict) and row.get("query_id") == query_id]
    if len(rows) != 1 or rows[0][0] != provider:
        return {"allowed": False, "code": "SCENARIO_QUERY_ID_MISMATCH"}
    from workflow_v24 import scenario_dispatch_block_from_dir
    blocked = scenario_dispatch_block_from_dir(task_dir, provider, rows[0][1])
    if blocked:
        return {"allowed": False, "code": str(blocked.get("code") or "SCENARIO_ACTION_BLOCKED")}
    return {"allowed": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--query-id", required=True)
    args = parser.parse_args()
    try:
        result = authorize(args.task_dir.resolve(), args.provider, args.query_id)
    except (OSError, ValueError, KeyError, TypeError):
        result = {"allowed": False, "code": "SCENARIO_DISPATCH_INPUT_INVALID"}
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["allowed"] else 2)


if __name__ == "__main__":
    main()

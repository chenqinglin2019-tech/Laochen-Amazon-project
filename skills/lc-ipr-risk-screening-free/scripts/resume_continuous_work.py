#!/usr/bin/env python3
"""Explicitly opt an existing 2.4 task into the continuous-work-v2 behavior."""
from __future__ import annotations

import argparse
import shutil
import os
from pathlib import Path

from common import atomic_write_json, ensure_object, load_json, now_iso, sha256_file
from decision_workflow import scenario_index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--guard-session-id", help="Actual Codex session ID; bind the new recovery directory")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New recovery directory. The source task is never modified.")
    parser.add_argument("--execution-scenarios", default="", help="Comma-separated scenario IDs; default is the primary scenario only")
    args = parser.parse_args()
    source_dir = args.task_dir.resolve()
    task_dir = args.output_dir.resolve()
    if task_dir == source_dir or task_dir.exists():
        raise ValueError("CONTINUOUS_WORK_RESUME_REQUIRES_NEW_OUTPUT_DIRECTORY")
    if not source_dir.is_dir():
        raise ValueError("CONTINUOUS_WORK_RESUME_SOURCE_NOT_FOUND")
    source_task_path = source_dir / "task.json"
    source_plan_path = source_dir / "search-plan.json"
    task = ensure_object(load_json(source_task_path), "task.json")
    if task.get("schema_version") != "2.4-free" or task.get("execution_policy_revision") not in {None, "continuous-work-v1", "continuous-work-v2"}:
        raise ValueError("CONTINUOUS_WORK_RESUME_REQUIRES_2_4_TASK")
    scenarios = scenario_index(task)
    selected = [value.strip() for value in args.execution_scenarios.split(",") if value.strip()] or [task.get("primary_scenario_id")]
    if not selected or len(set(selected)) != len(selected) or any(value not in scenarios for value in selected):
        raise ValueError("EXECUTION_SCENARIOS_INVALID")
    if task.get("primary_scenario_id") not in selected:
        raise ValueError("PRIMARY_SCENARIO_EXECUTION_REQUIRED")
    # Validate all inputs before creating anything, so a rejected historical
    # task never leaves a confusing half-copied recovery directory behind.
    if source_plan_path.is_file():
        ensure_object(load_json(source_plan_path), "search-plan.json")
    shutil.copytree(source_dir, task_dir)
    # Preserve historical receipt strings, but bind every copied absolute file
    # to its byte-identical recovery copy.  Consumers must use this manifest;
    # it is deliberately not a permission to read outside the recovery task.
    mappings = []
    for path in task_dir.rglob("*"):
        if not path.is_file() or path.name == "recovery-manifest.json":
            continue
        relative = path.relative_to(task_dir)
        original = source_dir / relative
        if original.is_file():
            mappings.append({"source_path": str(original.resolve()), "copied_path": str(relative),
                             "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    task_path = task_dir / "task.json"
    plan_path = task_dir / "search-plan.json"
    before = sha256_file(task_path)
    plan = ensure_object(load_json(plan_path), "search-plan.json") if plan_path.is_file() else None
    plan_before = sha256_file(plan_path) if plan is not None else ""
    task["execution_policy_revision"] = "continuous-work-v2"
    task["execution_scenario_ids"] = selected
    # Earlier 2.4 captures stored one inventory review without the per-right
    # identity hashes introduced by asset-scope-v1.  Rebind that existing,
    # already evidenced review to the unchanged product inventory; do not
    # invent a new source or alter the original evidence reference.
    review = task.get("product", {}).get("asset_scope_review")
    if isinstance(review, dict) and review.get("status") == "reviewed" and review.get("evidence_refs"):
        from record_asset_provenance import inventory_identity_sha256
        right_hashes = dict(review.get("inventory_identity_sha256_by_right") or {})
        for right in ("copyright", "trade_dress", "unregistered_design"):
            right_hashes.setdefault(right, inventory_identity_sha256(task, right))
        review["inventory_identity_sha256_by_right"] = right_hashes
    task.setdefault("workflow_migrations", []).append({"at": now_iso(), "from_task_sha256": before,
        "kind": "continuous-work-v2-resume", "execution_scenario_ids": selected,
        "reason": "Explicit recovery in a new directory: execute the requested primary scenario and disclose conditional scenarios separately.",
        "search_plan_before_sha256": plan_before})
    atomic_write_json(task_path, task)
    # The plan is a task-bound snapshot.  Its execution-policy field is part
    # of the binding contract, so leaving it at v1 after an explicit v2 resume
    # makes candidate merge and assessment fail despite no query changing.
    if plan is not None:
        plan["execution_policy_revision"] = "continuous-work-v2"
        plan.setdefault("workflow_migrations", []).append({
            "at": now_iso(), "kind": "continuous-work-v2-resume",
            "from_plan_sha256": plan_before,
            "execution_scenario_ids": selected,
            "reason": "Align task-bound plan execution semantics after explicit resume; existing query rows remain unchanged.",
        })
        atomic_write_json(plan_path, plan)
    atomic_write_json(task_dir / "recovery-manifest.json", {
        "schema": "IPR-RECOVERY-MANIFEST/1.0", "source_task_dir": str(source_dir),
        "source_task_sha256": before, "created_at": now_iso(), "file_mappings": mappings,
    })
    from codex_guard import register_if_requested
    register_if_requested(args.guard_session_id, task_dir, resume=True)
    print(task_path)


if __name__ == "__main__":
    main()

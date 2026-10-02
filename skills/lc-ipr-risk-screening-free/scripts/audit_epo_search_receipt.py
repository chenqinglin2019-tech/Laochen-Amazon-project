#!/usr/bin/env python3
"""Append a hash-bound classification of one historical EPO OPS search receipt."""
from __future__ import annotations

import argparse
from pathlib import Path

from common import atomic_write_json, ensure_object, load_json, now_iso, resolve_retained_path, sha256_file, sha256_json
from epo_ops_client import ops_fault


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reasoning", required=True)
    args = parser.parse_args()
    root = args.task_dir.resolve()
    evidence = ensure_object(load_json(root / "evidence.json"), "evidence.json")
    plan = ensure_object(load_json(root / "search-plan.json"), "search-plan.json")
    runs = [item for item in evidence.get("source_runs", []) if isinstance(item, dict) and item.get("run_id") == args.run_id]
    if len(runs) != 1:
        raise ValueError("EPO_RECEIPT_RUN_REQUIRED")
    run = runs[0]
    if run.get("provider") != "epo_ops" or run.get("operation") != "search" or run.get("submission_state") in {"submitted", "not_submitted"}:
        raise ValueError("EPO_RECEIPT_AUDIT_NOT_APPLICABLE")
    matches = [(provider, row) for provider, rows in plan.get("queries", {}).items() if isinstance(rows, list)
               for row in rows if isinstance(row, dict) and row.get("query_id") == run.get("query_id")]
    if len(matches) != 1 or matches[0][0] != "epo_ops" or sha256_json(matches[0][1]) != run.get("plan_entry_sha256"):
        raise ValueError("EPO_RECEIPT_PLAN_BINDING_INVALID")
    paths = run.get("raw_paths", [])
    if len(paths) != 1 or not run.get("payload_digest"):
        raise ValueError("EPO_RECEIPT_RAW_REQUIRED")
    raw = resolve_retained_path(root, paths[0], expected_sha256=run["payload_digest"])
    body = raw.read_bytes()
    code, message = ops_fault(body)
    if run.get("error_code") != "PROVIDER_HTTP_ERROR" or "404" not in str(run.get("detail") or "") or code != "SERVER.EntityNotFound" or message.casefold() != "no results found":
        raise ValueError("EPO_RECEIPT_NOT_CONFIRMED_NO_RESULT")
    record = {"method": "epo_search_receipt_audit", "source_run_id": run["run_id"],
              "source_run_sha256": sha256_json(run), "query_id": run["query_id"],
              "plan_entry_sha256": sha256_json(matches[0][1]), "submission_state": "submitted", "result": "no_result",
              "raw_receipt": {"path": paths[0], "sha256": sha256_file(raw), "bytes": raw.stat().st_size},
              "http_status": 404, "fault_code": code, "fault_message": message,
              "reviewer": args.reviewer.strip(), "reasoning": args.reasoning.strip(), "reviewed_at": now_iso()}
    if not record["reviewer"] or not record["reasoning"]:
        raise ValueError("EPO_RECEIPT_AUDIT_REASONING_REQUIRED")
    prior = evidence.setdefault("submission_state_reviews", [])
    if any(isinstance(item, dict) and item.get("source_run_id") == run["run_id"] and item.get("method") == record["method"] for item in prior):
        raise ValueError("EPO_RECEIPT_ALREADY_AUDITED")
    prior.append(record)
    atomic_write_json(root / "evidence.json", evidence)
    print(record["source_run_id"])


if __name__ == "__main__":
    main()

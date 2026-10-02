#!/usr/bin/env python3
"""Bind an Agent's reviewed product asset inventory to existing evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import assert_active_free_policy, atomic_write_json, ensure_object, load_json, now_iso
from record_asset_provenance import inventory_identity_sha256, inventory_validation_errors


RIGHT_TYPES = ("copyright", "trade_dress", "unregistered_design")


def evidence_ids(evidence: dict) -> set[str]:
    result = set()
    for values in evidence.get("collections", {}).values():
        for item in values if isinstance(values, list) else []:
            if isinstance(item, dict) and isinstance(item.get("evidence_id"), str):
                result.add(item["evidence_id"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True,
                        help="JSON with reviewer, reasoning and evidence_refs for the actual inventory review")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    assert_active_free_policy(task)
    if task.get("schema_version") != "2.4-free":
        raise ValueError("ASSET_INVENTORY_REVIEW_REQUIRES_2_4")
    product = ensure_object(task.get("product"), "product")
    if not isinstance(product.get("analysis"), dict) or product["analysis"].get("status") != "confirmed":
        raise ValueError("ASSET_INVENTORY_REVIEW_REQUIRES_CONFIRMED_PRODUCT_ANALYSIS")
    errors = inventory_validation_errors(task)
    if errors:
        raise ValueError("ASSET_INVENTORY_INVALID: " + "; ".join(errors))
    payload = ensure_object(load_json(args.input), "inventory review")
    reviewer, reasoning, refs = payload.get("reviewer"), payload.get("reasoning"), payload.get("evidence_refs")
    if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(reasoning, str) or not reasoning.strip():
        raise ValueError("ASSET_INVENTORY_REVIEW_REASONING_REQUIRED")
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise ValueError("ASSET_INVENTORY_REVIEW_EVIDENCE_REQUIRED")
    if not set(refs) <= evidence_ids(ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")):
        raise ValueError("ASSET_INVENTORY_REVIEW_EVIDENCE_UNKNOWN")
    review = {"status": "reviewed", "reviewer": reviewer.strip(), "reasoning": reasoning.strip(),
              "evidence_refs": refs, "reviewed_at": now_iso(),
              "inventory_identity_sha256_by_right": {right: inventory_identity_sha256(task, right) for right in RIGHT_TYPES}}
    product["asset_scope_review"] = review
    task["updated_at"] = now_iso()
    atomic_write_json(task_dir / "task.json", task)
    print(json.dumps({"task_id": task["task_id"], "status": "reviewed", "rights": list(RIGHT_TYPES)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

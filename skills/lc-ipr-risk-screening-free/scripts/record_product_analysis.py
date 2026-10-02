#!/usr/bin/env python3
"""Validate and record an Agent's product analysis before search planning.

This recorder owns normalization of the product facts that drive scope and
query planning.  It does not discover facts, infer intended use, or modify an
already frozen search plan.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import assert_active_free_policy, atomic_write_json, ensure_object, load_json, now_iso, sha256_json
from record_asset_provenance import inventory_validation_errors
from workflow_v24 import product_analysis_readiness, product_identity_digest, term_records


ALLOWED_PRODUCT_FIELDS = {
    "structure", "assets", "mark_inventory", "asset_scope_review", "mark_inventory_review",
    "brand_use", "intended_use", "visible_ip_claims", "patent_claim_followup",
}


def validate_input(task: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    product = payload.get("product", {})
    if not isinstance(product, dict):
        raise ValueError("PRODUCT_ANALYSIS_PRODUCT_OBJECT_REQUIRED")
    unexpected = set(product) - ALLOWED_PRODUCT_FIELDS
    if unexpected:
        raise ValueError("PRODUCT_ANALYSIS_FIELD_UNSUPPORTED: " + ", ".join(sorted(unexpected)))
    if "query_terms" not in payload or not isinstance(payload["query_terms"], list):
        raise ValueError("PRODUCT_ANALYSIS_QUERY_TERMS_REQUIRED")
    from product_scope import enabled as scope_enabled
    if not scope_enabled(task) and (not isinstance(product.get("structure"), list) or not product["structure"]):
        raise ValueError("PRODUCT_ANALYSIS_STRUCTURE_REQUIRED")
    merged = {**task, "product": {**task.get("product", {}), **product}, "query_terms": payload["query_terms"]}
    errors = inventory_validation_errors(merged)
    if errors:
        raise ValueError("PRODUCT_INVENTORY_INVALID: " + "; ".join(errors))
    # Reuse the planner's exact language, source-path and observed-mark checks.
    term_records(merged)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True, help="Agent-authored analysis JSON")
    parser.add_argument("--revise", action="store_true", help="Append a bounded post-plan product-scope revision and expand the plan")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    assert_active_free_policy(task)
    if task.get("schema_version") != "2.4-free":
        raise ValueError("PRODUCT_ANALYSIS_REQUIRES_2_4")
    plan_path = task_dir / "search-plan.json"
    if plan_path.is_file() and not args.revise:
        raise ValueError("PRODUCT_ANALYSIS_AFTER_PLAN_FORBIDDEN: create a new task or record analysis before planning")
    payload = ensure_object(load_json(args.input), "product analysis input")
    merged = validate_input(task, payload)
    analysis = payload.get("analysis", {})
    if not isinstance(analysis, dict):
        raise ValueError("PRODUCT_ANALYSIS_CONFIRMATION_REQUIRED")
    merged["product"]["analysis"] = {
        "status": "confirmed",
        "reviewer": str(analysis.get("reviewer") or "agent").strip(),
        "reasoning": str(analysis.get("reasoning") or "").strip(),
        "clue_dispositions": analysis.get("clue_dispositions",
            (task.get("product", {}).get("analysis") or {}).get("clue_dispositions", [])),
        "confirmed_at": now_iso(),
        "identity_sha256": product_identity_digest(merged["product"], task=merged),
    }
    if not merged["product"]["analysis"]["reviewer"] or not merged["product"]["analysis"]["reasoning"]:
        raise ValueError("PRODUCT_ANALYSIS_REASONING_REQUIRED")
    readiness = product_analysis_readiness(merged)
    if not readiness["ready"]:
        raise ValueError("PRODUCT_ANALYSIS_NOT_READY: " + ", ".join(item["code"] for item in readiness["gaps"]))
    if args.revise:
        prior = task.get("product", {})
        merged.setdefault("product_analysis_revisions", []).append({
            "at": now_iso(), "prior_product_sha256": sha256_json(prior),
            "revised_product_sha256": sha256_json(merged.get("product", {})),
            "reason": str(analysis.get("reasoning") or "").strip(),
            "effect": "Existing query rows remain immutable; affected scope bindings are replanned by --expand.",
        })
        merged.pop("outputs", None)
    merged["updated_at"] = now_iso()
    atomic_write_json(task_dir / "task.json", merged)
    if args.revise:
        expanded = subprocess.run([sys.executable, str(Path(__file__).with_name("generate_search_plan.py")),
            "--task-dir", str(task_dir), "--expand"], check=False, text=True, capture_output=True)
        if expanded.returncode:
            raise ValueError("PRODUCT_ANALYSIS_REPLAN_FAILED: " + expanded.stderr[-800:])
    print(json.dumps({"task_id": merged["task_id"], "status": "confirmed", "identity_sha256": merged["product"]["analysis"]["identity_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

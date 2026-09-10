#!/usr/bin/env python3
"""Record an Agent's source/licence review of retained, hash-bound asset files.

This is a local recorder, not a search API and not a prompt for user legal work.
It never guesses authorship, registers a right, or claims zero database hits.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from completion_policy import supported as necessary_work_enabled

from common import assert_active_free_policy, ensure_object, load_json, now_iso, path_within, sha256_file
from provider_utils import record_result, sanitized_request_params

SPECIALTY_REVISION = "asset-scope-v1"
INVESTIGATION_STEPS = {
    "copyright": ("provenance", "visual_comparison"),
    "trade_dress": ("public_use", "source_identification", "functionality"),
    "unregistered_design": ("provenance", "visual_comparison"),
    "trademark_figurative": ("classification", "visual_comparison"),
}
ASSET_RIGHTS = {
    "reference_only": {"copyright", "trade_dress", "unregistered_design"},
    "intended_material": {"copyright"},
    "integrated_expression": {"copyright", "trade_dress", "unregistered_design"},
    "product_configuration": {"copyright", "trade_dress", "unregistered_design"},
    "intended_packaging": {"copyright", "trade_dress", "unregistered_design"},
}
EXTERNAL_INFORMATION_EVIDENCE = {
    "supply_chain_authorization", "independent_creation_records",
    "private_sales_and_marketing_records", "product_manufacturing_records",
}


def specialty_enabled(task: dict) -> bool:
    return task.get("specialty_workflow_revision") == SPECIALTY_REVISION


def inventory_identity_sha256(task: dict, right_type: str) -> str:
    from common import sha256_json
    from decision_workflow import correction_enabled, factual_content, product_identity_sha256
    product = task.get("product") or {}
    key = "mark_inventory" if right_type == "trademark_figurative" else "assets"
    if correction_enabled(task):
        inventory = product.get(key)
        if key == "assets" and isinstance(inventory, list):
            inventory = [item for item in inventory if isinstance(item, dict)
                         and right_type in (item.get("right_types") or [])]
        return sha256_json({"product_identity": product_identity_sha256(task, right_type=right_type),
                           "inventory": factual_content(inventory)})
    return sha256_json({"actual_asin": product.get("actual_asin"), "variant": product.get("variant"),
                       "structure": product.get("structure"), "images": task.get("images", []),
                       "inventory": product.get(key)})


def applicable_assets(task: dict, scenario_id: str, right_type: str) -> list[dict]:
    """Reference photography is evidence of a product, not intended creative use."""
    product = task.get("product") or {}
    inventory = product.get("mark_inventory" if right_type == "trademark_figurative" else "assets")
    if not isinstance(inventory, list):
        return []
    if right_type == "trademark_figurative":
        return [item for item in inventory if isinstance(item, dict)
                and isinstance(item.get("scenario_ids"), list) and scenario_id in item["scenario_ids"]
                and item.get("form") in {"stylized_text", "graphic", "composite"}]
    assets = []
    for item in inventory:
        if not isinstance(item, dict) or not isinstance(item.get("scenario_ids"), list) or scenario_id not in item["scenario_ids"]:
            continue
        if not isinstance(item.get("right_types"), list) or right_type not in item["right_types"]:
            continue
        usage = item.get("usage")
        if usage == "reference_only":
            continue
        if right_type not in ASSET_RIGHTS.get(usage, set()):
            continue
        assets.append(item)
    return assets


def asset_scope(task: dict, scenario_id: str, right_type: str) -> dict:
    from common import sha256_json
    from decision_workflow import scenario_index, correction_enabled, factual_content, product_identity_sha256
    product = task.get("product") or {}
    inventory_key = "mark_inventory" if right_type == "trademark_figurative" else "assets"
    inventory = product.get(inventory_key)
    review = product.get("mark_inventory_review" if right_type == "trademark_figurative" else "asset_scope_review", {})
    if not isinstance(review, dict):
        review = {}
    assets = applicable_assets(task, scenario_id, right_type)
    scenarios = scenario_index(task)
    scenario = scenarios.get(scenario_id, {})
    def strings(value, nonempty=True):
        return isinstance(value, list) and (bool(value) or not nonempty) and all(isinstance(v, str) and v.strip() for v in value)
    def valid_item(item):
        if (not isinstance(item, dict) or not strings(item.get("scenario_ids")) or not strings(item.get("evidence_refs"))
                or not set(item["scenario_ids"]) <= set(scenarios)):
            return False
        if right_type == "trademark_figurative":
            return (bool(item.get("mark_id")) and item.get("form") in {"plain_text", "stylized_text", "graphic", "composite"}
                    and bool(item.get("graphic_description")))
        allowed = ASSET_RIGHTS
        rights = item.get("right_types")
        return (bool(item.get("asset_id")) and item.get("usage") in allowed
                and strings(rights, nonempty=False) and set(rights) <= allowed[item["usage"]]
                and (bool(rights) or item["usage"] == "reference_only" or bool(item.get("inapplicability_reason")))
                and bool(item.get("scope_reasoning")))
    inventory_valid = isinstance(inventory, list) and all(valid_item(item) for item in inventory)
    inventory_hash = review.get("inventory_identity_sha256")
    if correction_enabled(task) and isinstance(review.get("inventory_identity_sha256_by_right"), dict):
        inventory_hash = review["inventory_identity_sha256_by_right"].get(right_type)
    reviewed = (bool(scenario) and inventory_valid and review.get("status") == "reviewed" and bool(review.get("reviewer"))
                and bool(review.get("reasoning")) and strings(review.get("evidence_refs"))
                and inventory_hash == inventory_identity_sha256(task, right_type))
    ids = [item.get("asset_id") or item.get("mark_id") for item in assets]
    valid = all(isinstance(identity, str) and identity for identity in ids) and len(ids) == len(set(ids))
    scope_content = {"revision": task.get("specialty_workflow_revision"),
                "scenario_id": scenario_id, "scenario_sha256": scenario.get("scenario_sha256"),
                "right_type": right_type, "assets": assets, "inventory_review": review}
    if correction_enabled(task):
        scope_content = {"revision": task["workflow_correction_revision"], "scenario_id": scenario_id,
            "scenario_sha256": scenario.get("scenario_sha256"), "right_type": right_type,
            "product_identity_sha256": product_identity_sha256(task, scenario_id=scenario_id, right_type=right_type),
            "assets": factual_content(assets)}
    return {"asset_ids": sorted(ids) if valid else [], "inventory_reviewed": reviewed and valid,
            "scope_sha256": sha256_json(scope_content),
            "review": review}


def investigation_complete(task: dict, payload: dict, query: dict, scenario_id: str, registry: dict | None = None) -> bool:
    """Investigated steps and unresolved legal facts have separate semantics."""
    scope = asset_scope(task, scenario_id, query.get("right_type", ""))
    if not isinstance(registry, dict) or not set(scope["review"].get("evidence_refs", [])) <= set(registry):
        return False
    attestation = payload.get("coverage_attestation", {})
    if (not scope["inventory_reviewed"] or payload.get("asset_scope_sha256") != scope["scope_sha256"]
            or query.get("asset_scope_sha256") != scope["scope_sha256"]
            or payload.get("scenario_id") != scenario_id
            or attestation.get("inventory_complete") is not True
            or set(attestation.get("asset_ids", [])) != set(scope["asset_ids"])
            or set(attestation.get("reviewed_asset_ids", [])) != set(scope["asset_ids"])):
        return False
    steps = payload.get("investigation_steps", [])
    requested = query.get("search_dimension")
    matches = [step for step in steps if isinstance(step, dict) and step.get("step") == requested]
    if len(matches) != 1 or not isinstance(payload.get("outstanding_actions"), list) or payload["outstanding_actions"]:
        return False
    step = matches[0]
    artifacts = {item.get("sha256") for item in payload.get("artifacts", []) if isinstance(item, dict)}
    refs = step.get("evidence_refs")
    if not isinstance(refs, list) or not refs or any(ref not in registry for ref in refs):
        return False
    def registered_hashes(value):
        hashes = set()
        if isinstance(value, dict):
            visual_extensions = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".pdf"}
            if value.get("path") and value.get("sha256") and (requested != "visual_comparison" or Path(str(value["path"])).suffix.lower() in visual_extensions):
                hashes.add(value["sha256"])
            if value.get("screenshot_path") and value.get("screenshot_sha256"):
                hashes.add(value["screenshot_sha256"])
            for key, nested in value.items():
                if key not in {"query_execution", "raw_response", "request", "log", "logs", "audit", "review", "retained_source_record"}:
                    hashes.update(registered_hashes(nested))
        elif isinstance(value, list):
            for nested in value:
                hashes.update(registered_hashes(nested))
        return hashes
    entries = [registry[ref] for ref in refs if registry[ref].get("kind") not in {"agent_review", "retained_source_record"}]
    registered = set().union(*(registered_hashes(entry) for entry in entries)) if entries else set()
    if not set(step.get("artifact_sha256", [])) <= registered:
        return False
    if requested in {"provenance", "public_use", "source_identification"} and scope["asset_ids"]:
        if not any(entry.get("kind") in {"provenance_document", "official_record", "rights_record", "patent_claim_followup", "license"}
                   and (entry.get("source_url") or entry.get("source_document")) for entry in entries):
            return False
    classification_na = False
    if query.get("right_type") == "trademark_figurative" and requested == "classification":
        reviews = [item.get("classification_review", {}) for item in applicable_assets(task, scenario_id, "trademark_figurative")]
        classification_na = bool(reviews) and all(
            review.get("status") == "not_applicable" and review.get("design_codes") == []
            and review.get("reasoning") and review.get("evidence_refs")
            and set(review["evidence_refs"]) <= set(refs) for review in reviews)
        # An Agent can document why no design-code axis applies, not claim to
        # have executed a code search through the local recorder.
        if scope["asset_ids"] and not (classification_na and step.get("status") == "not_applicable"):
            return False
    return (step.get("status") in {"completed", "not_applicable"}
            and bool(step.get("reasoning")) and bool(step.get("artifact_sha256"))
            and set(step["artifact_sha256"]) <= artifacts
            and (step["status"] != "not_applicable" or not scope["asset_ids"] or classification_na))


def external_information_actions(task: dict, payload: dict, query: dict, scenario_id: str,
                                 registry: dict | None = None) -> list[dict]:
    """Separate completed public research from specific private supply-chain facts.

    This is a projection of the current retained investigation, not another
    blocker ledger. Unknown facts alone never create a user dependency.
    """
    if (not necessary_work_enabled(task)
            or not specialty_enabled(task) or not isinstance(payload, dict)
            or not isinstance(registry, dict)):
        return []
    actions = payload.get("outstanding_actions")
    if not isinstance(actions, list) or not actions:
        return []
    public = {**payload, "outstanding_actions": []}
    if not investigation_complete(task, public, query, scenario_id, registry):
        return []
    scope = asset_scope(task, scenario_id, query.get("right_type", ""))
    if not scope["asset_ids"]:
        return []
    step = next(item for item in payload["investigation_steps"] if isinstance(item, dict)
                and item.get("step") == query.get("search_dimension"))
    if step.get("status") != "completed":
        return []
    from assessment_v24 import _retained_artifacts_complete
    if not _retained_artifacts_complete(payload):
        return []
    retained = {item.get("sha256") for item in payload["artifacts"]}
    step_refs = set(step["evidence_refs"])
    document_kinds = {"provenance_document", "official_record", "rights_record", "license"}
    media_extensions = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif"}
    ids = set()
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    for action in actions:
        if (not isinstance(action, dict) or action.get("kind") != "user_information"
                or any(not text(action.get(key)) for key in ("action_id", "purpose", "question", "reasoning"))
                or action["action_id"] in ids or not isinstance(action.get("owner"), str)
                or action["owner"] not in {"user", "supplier"}):
            return []
        ids.add(action["action_id"])
        needed, refs = action.get("evidence_needed"), action.get("evidence_refs")
        if (not isinstance(needed, list) or not needed or any(not text(value) for value in needed)
                or len(set(needed)) != len(needed) or not set(needed) <= EXTERNAL_INFORMATION_EVIDENCE
                or not isinstance(refs, list) or not refs or any(not text(ref) for ref in refs)
                or len(set(refs)) != len(refs) or not set(refs) <= step_refs):
            return []
        # Every request must cite retained original text and an actual compared
        # image from this step. A receipt or self-authored blocker is insufficient.
        sources = [registry[ref] for ref in refs if registry[ref].get("sha256") in retained
                   and (registry[ref].get("source_url") or registry[ref].get("source_document"))]
        if (not any(item.get("kind") in document_kinds and item.get("path") for item in sources)
                or not any(item.get("kind") not in {"agent_review", "retained_source_record"}
                    and Path(str(item.get("path") or "")).suffix.lower() in media_extensions for item in sources)):
            return []
    return deepcopy(actions)


def validate_payload(task_dir: Path, payload: dict[str, Any], query: dict[str, Any], candidates: dict[str, Any], task: dict | None = None) -> dict[str, Any]:
    from annotate_materiality import candidate_index
    from assessment_v24 import UNREGISTERED
    specialty = specialty_enabled(task or {})
    if query.get("operation") != "provenance_review" or query.get("right_type") not in (UNREGISTERED | ({"trademark_figurative"} if specialty else set())):
        raise ValueError("PROVENANCE_PLAN_OPERATION_INVALID")
    for field in ("jurisdiction", "right_type", "candidate_id"):
        if str(payload.get(field) or "") != str(query.get(field) or ""):
            raise ValueError("PROVENANCE_IDENTITY_MISMATCH: " + field)
    candidate_id = str(payload.get("candidate_id") or "")
    if candidate_id:
        index, _ = candidate_index(candidates)
        if candidate_id not in index or index[candidate_id][1].get("right_type") != query["right_type"]:
            raise ValueError("PROVENANCE_CANDIDATE_NOT_FOUND")
    if not str(payload.get("reviewer") or "").strip() or not str(payload.get("ownership_or_source_reasoning") or "").strip():
        raise ValueError("PROVENANCE_AGENT_REASONING_REQUIRED")
    source_url = str(payload.get("source_url") or "")
    if source_url:
        parsed = urlsplit(source_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("PROVENANCE_SOURCE_URL_INVALID")
    elif not str(payload.get("source_document") or "").strip():
        raise ValueError("PROVENANCE_SOURCE_REQUIRED")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("PROVENANCE_RETAINED_ARTIFACTS_REQUIRED")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("PROVENANCE_ARTIFACT_INVALID")
        path = Path(str(artifact.get("path") or "")).resolve()
        if not path.is_file() or not path_within(path, task_dir) or sha256_file(path) != artifact.get("sha256") or path.stat().st_size != artifact.get("bytes"):
            raise ValueError("PROVENANCE_ARTIFACT_HASH_OR_PATH_MISMATCH")
        if not str(artifact.get("role") or "").strip():
            raise ValueError("PROVENANCE_ARTIFACT_ROLE_REQUIRED")
    if not isinstance(payload.get("unresolved"), list):
        raise ValueError("PROVENANCE_UNRESOLVED_LIST_REQUIRED")
    attestation = payload.get("coverage_attestation")
    if attestation is not None:
        if not isinstance(attestation, dict) or not isinstance(attestation.get("asset_ids"), list) or (not specialty and not attestation["asset_ids"]) or not isinstance(attestation.get("reviewed_asset_ids"), list) or not isinstance(attestation.get("inventory_complete"), bool):
            raise ValueError("PROVENANCE_COVERAGE_ATTESTATION_INVALID")
    if specialty:
        from workflow_v24 import scenario_row_bindings
        bindings = scenario_row_bindings(task, query)
        if len(bindings) != 1 or payload.get("scenario_id") != bindings[0]["scenario_id"]:
            raise ValueError("PROVENANCE_SCENARIO_MISMATCH")
        scope = asset_scope(task, payload["scenario_id"], query["right_type"])
        if payload.get("asset_scope_sha256") != scope["scope_sha256"] or query.get("asset_scope_sha256") != scope["scope_sha256"]:
            raise ValueError("PROVENANCE_SCOPE_STALE")
        if not isinstance(payload.get("outstanding_actions"), list) or not isinstance(payload.get("investigation_steps"), list):
            raise ValueError("PROVENANCE_STEP_RECORDS_REQUIRED")
        if query.get("search_dimension") not in INVESTIGATION_STEPS.get(query["right_type"], ()):
            raise ValueError("PROVENANCE_STEP_NOT_APPLICABLE")
        from assessment_v24 import evidence_index
        from workflow_v24 import scenario_supplement
        known = set(evidence_index(load_json(task_dir / "evidence.json")))
        known.update(item.get("evidence_id") for item in (scenario_supplement(task_dir) or {}).get("evidence", []))
        if not set(scope["review"].get("evidence_refs", [])) <= known:
            raise ValueError("PROVENANCE_INVENTORY_EVIDENCE_UNKNOWN")
    return {**payload, "checked_at": now_iso()}


def agent_work_queue(task_dir: Path) -> dict:
    """Expose effective local investigations that API/browser runners cannot do."""
    from annotate_materiality import load_materiality_ledger
    from assessment_v24 import query_coverage
    from workflow_v24 import scenario_dispatch_block, scenario_row_bindings, scenario_supplement
    task, plan, evidence = (load_json(task_dir / name) for name in ("task.json", "search-plan.json", "evidence.json"))
    candidates = load_json(task_dir / "normalized-candidates.json") if (task_dir / "normalized-candidates.json").is_file() else {}
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    supplement = scenario_supplement(task_dir)
    work = []
    for row in plan.get("queries", {}).get("asset_provenance", []):
        blocked = scenario_dispatch_block(task, plan, "asset_provenance", row, candidates, ledger, evidence, supplement=supplement)
        if blocked:
            continue
        for binding in scenario_row_bindings(task, row):
            result = query_coverage(evidence, candidates, plan, "asset_provenance", row, task,
                ledger=ledger, supplement=supplement, scenario_id=binding["scenario_id"])
            scope = asset_scope(task, binding["scenario_id"], row["right_type"])
            work.append({"query_id": row["query_id"], **binding, "jurisdiction": row["jurisdiction"],
                "right_type": row["right_type"], "step": row["search_dimension"], **scope,
                "status": "completed" if result["complete"] else "public_investigation_pending",
                "assigned_to": "agent", "unresolved_facts": result.get("unresolved_facts", []),
                "next_action": "读取真实公开资料并保存来源文件，再用本记录器提交分步骤审阅；不是请用户代查。"})
    return {"schema": "IPR-AGENT-WORK/1.0", "task_id": task["task_id"], "work": work}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query-id")
    parser.add_argument("--input", type=Path, help="Agent-authored source/licence review JSON")
    parser.add_argument("--list-work", action="store_true", help="List effective investigations without executing or claiming source coverage")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task")
    assert_active_free_policy(task)
    if args.list_work:
        import json
        print(json.dumps(agent_work_queue(task_dir), ensure_ascii=False, indent=2))
        return
    if not args.query_id or not args.input:
        parser.error("--query-id and --input are required unless --list-work is used")
    if task.get("schema_version") != "2.4-free":
        raise ValueError("PROVENANCE_REQUIRES_2_4")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "plan")
    matches = [(provider, query) for provider, queries in plan.get("queries", {}).items() if isinstance(queries, list) for query in queries if isinstance(query, dict) and query.get("query_id") == args.query_id]
    if len(matches) != 1 or matches[0][0] != "asset_provenance":
        raise ValueError("PROVENANCE_EXACT_PLAN_REQUIRED")
    query = matches[0][1]
    if specialty_enabled(task):
        from workflow_v24 import scenario_dispatch_block, scenario_supplement
        from annotate_materiality import load_materiality_ledger
        blocked = scenario_dispatch_block(task, plan, "asset_provenance", query,
            load_json(task_dir / "normalized-candidates.json"), load_materiality_ledger(task_dir, task["task_id"], task=task),
            load_json(task_dir / "evidence.json"), supplement=scenario_supplement(task_dir))
        if blocked:
            raise ValueError(blocked["code"])
    payload = validate_payload(task_dir, ensure_object(load_json(args.input), "provenance"), query,
                               ensure_object(load_json(task_dir / "normalized-candidates.json"), "candidates"), task)
    run = record_result(task_dir, provider="asset_provenance", operation="provenance_review",
        query=str(query.get("q") or query.get("query") or ""), jurisdiction=query["jurisdiction"],
        evidence_type="asset_provenance", status="success", normalized=payload,
        request_params=sanitized_request_params(query), query_id=args.query_id,
        source_environment="local_agent_review", authoritative_for_final_rating=False)
    print(run["run_id"])


if __name__ == "__main__":
    main()

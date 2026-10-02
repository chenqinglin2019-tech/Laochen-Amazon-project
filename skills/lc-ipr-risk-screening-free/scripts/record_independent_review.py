#!/usr/bin/env python3
"""Expand a compact Agent judgment and bind host execution metadata automatically."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

from common import atomic_write_json, ensure_object, load_json, sha256_json
from annotate_materiality import candidate_index, load_materiality_ledger
from assessment_v24 import evidence_index
from assessment_estimate import (_validate_review, review_digest, validate_supplement, product_image_index)
from workflow_v24 import scenario_supplement


MODULE_BY_RIGHT = {
    "design": "appearance_patent", "unregistered_design": "appearance_patent",
    "patent": "utility_patent", "utility_model": "utility_patent",
    "trademark_word": "word_mark", "trademark_figurative": "figurative_trade_dress",
    "trade_dress": "figurative_trade_dress", "copyright": "copyright_ip",
    "enforcement": "enforcement",
}

FULL_ASSESSMENT_FIELDS = {
    "scenario_id", "jurisdiction", "right_type", "module_id", "title", "scope",
    "risk", "assessment_status", "reasoning", "confidence_reasoning",
    "evidence_confidence", "evidence_refs", "supporting_evidence", "counter_evidence",
    "no_supporting_evidence_reasoning", "no_counter_evidence_reasoning",
    "assumptions", "raise_if", "lower_if", "human_checks", "right_state",
    "confidence_basis",
}


def normalize_review_row(row: dict, task: dict) -> dict:
    """Preserve full agent judgments; expand only compact, explicitly pending rows."""
    if not isinstance(row, dict):
        raise ValueError("REVIEW_ASSESSMENT_OBJECT_REQUIRED")
    if FULL_ASSESSMENT_FIELDS <= set(row):
        return deepcopy(row)
    if row.get("risk") not in (None, "missing") or row.get("assessment_status") == "assessed":
        raise ValueError("COMPACT_REVIEW_CANNOT_CARRY_A_RISK_JUDGMENT")
    return expand_pending(row, task)


def expand_pending(row: dict, task: dict) -> dict:
    """Expand only an explicitly Agent-authored pending judgment."""
    if row.get("assessment_status") != "pending" and row.get("risk", "missing") is not None:
        return deepcopy(row)
    reason = str(row.get("pending_reasoning") or row.get("reasoning") or "").strip()
    if not reason:
        raise ValueError("COMPACT_PENDING_REASONING_REQUIRED")
    right = str(row.get("right_type") or "")
    jurisdiction = str(row.get("jurisdiction") or "").upper()
    scenario_id = str(row.get("scenario_id") or task.get("primary_scenario_id") or "")
    scenarios = {item.get("scenario_id"): item for item in task.get("assessment_scenarios", []) if isinstance(item, dict)}
    scenario = scenarios.get(scenario_id)
    if not scenario:
        raise ValueError("COMPACT_PENDING_SCENARIO_UNKNOWN")
    refs = list(dict.fromkeys(row.get("evidence_refs", [])))
    title = str(row.get("title") or f"{jurisdiction} {right}证据范围")
    scope = str(row.get("scope") or f"{scenario.get('title', scenario_id)} / {jurisdiction} / {right}")
    from decision_workflow import scenario_sha256
    result = {
        **deepcopy(row), "scenario_id": scenario_id, "scenario_sha256": scenario_sha256(scenario),
        "jurisdiction": jurisdiction, "right_type": right,
        "module_id": row.get("module_id") or MODULE_BY_RIGHT.get(right),
        "title": title, "scope": scope, "risk": None, "assessment_status": "pending",
        "pending_reasoning": reason, "reasoning": reason,
        "evidence_confidence": "低",
        "confidence_reasoning": str(row.get("confidence_reasoning") or "关键事实不足，当前范围保持暂不定级。"),
        "evidence_refs": refs, "supporting_evidence": [], "counter_evidence": [],
        "no_supporting_evidence_reasoning": str(row.get("no_supporting_evidence_reasoning") or "尚无足以支持具体风险等级的正面证据。"),
        "no_counter_evidence_reasoning": str(row.get("no_counter_evidence_reasoning") or "证据缺口不构成降低风险的反证。"),
        "assumptions": list(row.get("assumptions", [])), "raise_if": list(row.get("raise_if", [])),
        "lower_if": list(row.get("lower_if", [])), "human_checks": list(row.get("human_checks", [])),
        "right_state": row.get("right_state", "unknown"),
        "confidence_basis": row.get("confidence_basis", {}),
    }
    if result["module_id"] is None:
        raise ValueError("COMPACT_PENDING_RIGHT_TYPE_UNSUPPORTED")
    return result


def validate_host_input_digest(execution: dict, digest: str, task: dict) -> None:
    # The recorder must not replace the digest of inputs actually read by the host.
    supplied = execution.get("input_digest")
    if task.get("execution_policy_revision") == "continuous-work-v2" and supplied is None:
        raise ValueError("REVIEW_HOST_INPUT_DIGEST_REQUIRED")
    if supplied is not None and supplied != digest:
        raise ValueError("REVIEW_HOST_INPUT_DIGEST_MISMATCH")


def build_review(task_dir: Path, payload: dict, execution: dict, *, prepared_context=None) -> dict:
    task = ensure_object(load_json(task_dir / "task.json"), "task")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence")
    candidate_path = task_dir / "normalized-candidates.json"
    candidates = ensure_object(load_json(candidate_path), "candidates") if candidate_path.is_file() else {}
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "plan")
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    digest = review_digest(evidence, candidates, ledger, plan, task, supplement)
    validate_host_input_digest(execution, digest, task)
    if task.get("execution_policy_revision") == "continuous-work-v2":
        from review_readiness import readiness, PreparedReviewContext
        if prepared_context is not None and type(prepared_context) is not PreparedReviewContext:
            raise ValueError('REVIEW_PREPARED_CONTEXT_NOT_ISSUED')
        prepared = prepared_context.validate(task_dir, frozen=True) if prepared_context is not None else readiness(task_dir)
        if not prepared["ready"] or prepared["input_digest"] != digest:
            raise ValueError("REVIEW_INPUT_NOT_READY: complete preparation and freeze before dual review")
    assessments = [normalize_review_row(row, task) for row in payload.get("assessments", [])]
    from final_review import enabled as final_enabled, inputs as final_inputs, prepare_rows
    final_receipt = None
    if final_enabled(task):
        assessments, final_receipt = prepare_rows(payload, assessments,
            final_inputs(evidence, candidates, ledger, plan, task, supplement), execution.get("previous_review"))
    for field in ("session_id", "agent_id", "run_id"):
        if not str(execution.get(field) or "").strip():
            raise ValueError("REVIEW_EXECUTION_CONTEXT_REQUIRED:" + field)
    review = {
        "reviewer": payload.get("reviewer"),
        "review_context": {"session_id": execution["session_id"], "evidence_digest": digest,
            "first_review_visible": False,
            "execution": {"agent_id": execution["agent_id"], "run_id": execution["run_id"],
                          "input_digest": digest, "assessment_digest": sha256_json(assessments),
                          **({"host_audit": deepcopy(execution["host_audit"])}
                             if isinstance(execution.get("host_audit"), dict) else {}),
                          **({"module_execution": deepcopy(execution["module_execution"])}
                             if isinstance(execution.get("module_execution"), dict) else {})}},
        "coverage_confidence_cap": payload.get("coverage_confidence_cap"),
        "coverage_confidence_reasoning": payload.get("coverage_confidence_reasoning"),
        "assessments": assessments,
        "future_applications": deepcopy(payload.get("future_applications", [])),
        "enforcement_signals": deepcopy(payload.get("enforcement_signals", [])),
    }
    if final_receipt is not None:
        review["review_context"]["final_review"] = final_receipt
        review["review_context"]["execution"]["final_review_digest"] = sha256_json(final_receipt)
    supplemental = validate_supplement(supplement, task_dir, task=task, evidence=evidence)
    images = product_image_index(task, task_dir)
    if (set(evidence_index(evidence)) | set(supplemental)) & set(images):
        raise ValueError("PRODUCT_IMAGE_EVIDENCE_ID_COLLISION")
    known = set(evidence_index(evidence)) | set(supplemental) | set(images)
    index, errors = candidate_index(candidates)
    if errors:
        raise ValueError("INVALID_CANDIDATES:" + ";".join(errors))
    from module_review import enabled as modules_enabled
    if modules_enabled(task) and not isinstance(execution.get('module_execution'), dict):
        raise ValueError('FINAL_REVIEW_MODULE_EXECUTION_REQUIRED')
    _validate_review(review, digest, known, index,
                     {str(value).upper() for value in task.get("target_jurisdictions", [])},
                     task, {**evidence_index(evidence), **supplemental, **images})
    # Full registration is a completion boundary; staged manual reviews remain partial.
    if task.get("execution_policy_revision") == "continuous-work-v2" or final_enabled(task):
        from assessment_estimate import validate_product_scope_coverage
        validate_product_scope_coverage(review["assessments"], task)
    return review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True, help="Agent-authored full or compact review JSON")
    parser.add_argument("--execution-context", type=Path, required=True,
                        help="Host-created JSON containing session_id, agent_id, run_id and frozen input_digest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-review", type=Path,
        help="Same review slot's immutable prior receipt; reused_unit_ids explicitly select unchanged judgments")
    args = parser.parse_args()
    execution = ensure_object(load_json(args.execution_context), "execution context")
    if args.previous_review:
        execution["previous_review"] = ensure_object(load_json(args.previous_review), "previous review")
    review = build_review(args.task_dir.resolve(), ensure_object(load_json(args.input), "review input"), execution)
    atomic_write_json(args.output.resolve(), review)
    print(args.output.resolve())


if __name__ == "__main__":
    main()

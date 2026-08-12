#!/usr/bin/env python3
"""Validate independent reviews and deterministically finalize task state."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import (
    CONFIDENCE_LEVELS, MODULE_IDS, RISK_LEVELS, add_history, atomic_write_json,
    ensure_object, load_json, now_iso, sha256_json,
)


DISCOVERY_OPERATIONS_REQUIRED = {
    "epo_ops", "serpapi_google_patents", "serper_patents", "serper_web", "serper_images",
    "signa", "rapidapi_uspto_trademark", "uspto_tmsearch_browser", "euipo_trademark", "euipo_design",
}

LOW_RISK_GATE_OPERATIONS = {
    "wipo_patentscope_browser": "patent_recall",
    "epo_ops": "search",
    "uspto_patent_browser": "patent_recall",
}


def validate_review(review: dict[str, Any], known_evidence: set[str], input_digest: str) -> None:
    modules = review.get("modules")
    if not isinstance(modules, dict) or set(modules) != set(MODULE_IDS):
        raise ValueError("Review must contain exactly the seven required modules")
    for module_id, module in modules.items():
        if module.get("risk") not in RISK_LEVELS or module.get("confidence") not in CONFIDENCE_LEVELS:
            raise ValueError(f"Invalid risk/confidence in {module_id}")
        if not str(module.get("reasoning", "")).strip() or not isinstance(module.get("findings"), list):
            raise ValueError(f"Missing reasoning/findings in {module_id}")
        for finding in module["findings"]:
            refs = finding.get("evidence_refs", []) if isinstance(finding, dict) else []
            required_fields = ("finding_id", "title", "recommended_action")
            if not isinstance(finding, dict) or any(not str(finding.get(field) or "").strip() for field in required_fields):
                raise ValueError(f"Finding in {module_id} is missing required fields")
            if not refs or any(ref not in known_evidence for ref in refs):
                raise ValueError(f"Finding in {module_id} has missing or unknown evidence references")
    if not isinstance(review.get("review_triggers", {}), dict):
        raise ValueError("review_triggers must be an object")
    context = review.get("review_context")
    if not isinstance(context, dict):
        raise ValueError("review_context is required")
    if not str(context.get("session_id") or "").strip() or context.get("evidence_digest") != input_digest:
        raise ValueError("review_context session_id/evidence_digest is invalid")
    if context.get("first_review_visible") is not False:
        raise ValueError("review_context must state first_review_visible=false")


def reconcile_reviews(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Choose conservatively per module while retaining both sets of findings."""
    result = {**first, "modules": {}, "recommended_actions": []}
    confidence_rank = {value: index for index, value in enumerate(CONFIDENCE_LEVELS)}
    for module_id in MODULE_IDS:
        left, right = first["modules"][module_id], second["modules"][module_id]
        left_risk, right_risk = RISK_LEVELS.index(left["risk"]), RISK_LEVELS.index(right["risk"])
        if right_risk > left_risk or (right_risk == left_risk and confidence_rank[right["confidence"]] < confidence_rank[left["confidence"]]):
            chosen, other = right, left
        else:
            chosen, other = left, right
        findings = []
        seen: set[str] = set()
        for finding in [*chosen.get("findings", []), *other.get("findings", [])]:
            key = str(finding.get("finding_id") or sha256_json(finding))
            if key not in seen:
                seen.add(key)
                findings.append(finding)
        result["modules"][module_id] = {**chosen, "findings": findings}
    for action in [*first.get("recommended_actions", []), *second.get("recommended_actions", [])]:
        if action not in result["recommended_actions"]:
            result["recommended_actions"].append(action)
    result["summary_reasons"] = list(dict.fromkeys([*first.get("summary_reasons", []), *second.get("summary_reasons", [])]))
    return result


def review_risk(review: dict[str, Any]) -> str:
    level = max(RISK_LEVELS.index(module["risk"]) for module in review["modules"].values())
    escalation = review.get("compound_escalation", {})
    if escalation.get("enabled") and str(escalation.get("justification", "")).strip():
        level = min(level + 1, len(RISK_LEVELS) - 1)
    return RISK_LEVELS[level]


def review_confidence(review: dict[str, Any], image_count: int) -> str:
    values = {value: index for index, value in enumerate(CONFIDENCE_LEVELS)}
    if image_count == 1:
        for module_id in ("figurative_trade_dress", "copyright_ip"):
            review["modules"][module_id]["confidence"] = "中" if values[review["modules"][module_id]["confidence"]] > values["中"] else review["modules"][module_id]["confidence"]
    highest = max(RISK_LEVELS.index(module["risk"]) for module in review["modules"].values())
    drivers = [module for module in review["modules"].values() if RISK_LEVELS.index(module["risk"]) == highest]
    return min((module["confidence"] for module in drivers), key=values.get)


def material_unverified(candidates: dict[str, Any]) -> list[str]:
    missing = []
    for kind in ("patents", "trademarks"):
        for item in candidates.get(kind, []):
            if item.get("material") and item.get("official_verification", {}).get("status") != "verified":
                missing.append(str(item.get("normalization_key") or item.get("publication_number") or item.get("mark_text") or "candidate"))
    return missing


def tmsearch_expected_runs(search_plan: dict[str, Any]) -> set[str]:
    expected: set[str] = set()
    entries = search_plan.get("queries", {}).get("uspto_tmsearch_browser", [])
    if not isinstance(entries, list):
        return expected
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        query = str(entry.get("q") or "").strip()
        strategy = str(entry.get("strategy") or "").strip()
        if query and strategy:
            expected.add(str(entry.get("query_id") or f"{strategy}:{query}"))
    return expected


def low_risk_gate_expected_runs(search_plan: dict[str, Any], provider: str) -> set[str]:
    entries = search_plan.get("queries", {}).get(provider, [])
    if not isinstance(entries, list):
        return set()
    return {
        str(entry.get("query_id") or entry.get("q") or "").strip()
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("q") or "").strip()
    }


def low_risk_gate_gaps(task: dict[str, Any], evidence: dict[str, Any], search_plan: dict[str, Any]) -> list[str]:
    """Return US patent sources that make a negative clearance unsafe."""
    gaps: list[str] = []
    runs = evidence.get("source_runs", [])
    for provider in task.get("low_risk_gate_sources", []):
        operation = LOW_RISK_GATE_OPERATIONS.get(provider)
        if not operation:
            continue
        expected = low_risk_gate_expected_runs(search_plan, provider)
        completed = {
            str(run.get("query_id") or run.get("query") or "").strip()
            for run in runs
            if run.get("provider") == provider
            and run.get("operation") == operation
            and run.get("status") in {"success", "no_result"}
        }
        if not expected or not expected.issubset(completed):
            gaps.append(provider)
    return sorted(set(gaps))


def cap_negative_clearance(assessment: dict[str, Any], gate_gaps: list[str]) -> None:
    """A source outage can never be represented as a US low-risk clearance."""
    if not gate_gaps or assessment["overall"].get("risk") not in {"极低", "低"}:
        return
    assessment["overall"]["risk"] = "中"
    assessment["overall"]["confidence"] = "低"
    assessment["overall"].setdefault("reasons", []).append(
        "低风险结论门禁未完成：" + ", ".join(gate_gaps)
    )


def required_query_gaps(task: dict[str, Any], evidence: dict[str, Any], search_plan: dict[str, Any]) -> list[str]:
    terminal = {"success", "no_result", "not_applicable"}
    runs = evidence.get("source_runs", [])
    gaps: list[str] = []
    for provider in task.get("required_sources", []):
        entries = [
            entry for entry in search_plan.get("queries", {}).get(provider, [])
            if isinstance(entry, dict) and entry.get("required", True)
        ]
        for entry in entries:
            query_id = str(entry.get("query_id") or "")
            good = any(
                run.get("provider") == provider
                and run.get("status") in terminal
                and str(run.get("query_id") or "") == query_id
                for run in runs
            )
            if query_id and not good:
                gaps.append(f"{provider}:{query_id}")
    return sorted(set(gaps))


def source_gaps(task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any], search_plan: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    runs = evidence.get("source_runs", [])
    for provider in task.get("required_sources", []):
        provider_runs = [run for run in runs if run.get("provider") == provider]
        good = [run for run in provider_runs if run.get("status") in {"success", "no_result", "not_applicable"}]
        if provider in DISCOVERY_OPERATIONS_REQUIRED:
            good = [run for run in good if run.get("operation") != "preflight_probe"]
        if provider in {"euipo_trademark", "euipo_design"}:
            good = [
                run for run in good
                if (run.get("normalized") or {}).get("authoritative_for_final_rating", True) is True
            ]
        if provider == "amazon_browser":
            good = [run for run in good if run.get("operation") == "product_capture"]
        if provider == "uspto_tmsearch_browser":
            good = [run for run in good if run.get("operation") == "trademark_recall"]
            expected = tmsearch_expected_runs(search_plan)
            completed = {str(run.get("query_id") or run.get("query") or "") for run in good}
            if not expected or not expected.issubset(completed):
                good = []
        if provider == "uspto_tsdr":
            trademark_candidates = candidates.get("trademarks", [])
            if not trademark_candidates:
                good = [run for run in good if run.get("operation") in {
                    "api_preflight", "preflight_probe", "browser_capability", "candidate_verification",
                }]
            else:
                good = [run for run in good if run.get("operation") == "candidate_verification"]
        if provider in {"uspto_patent_browser", "official_registry_browser"}:
            material_exists = any(item.get("material") for kind in ("patents", "trademarks") for item in candidates.get(kind, []))
            good = [run for run in good if run.get("operation") not in {"preflight_probe", "browser_capability"}] if material_exists else good
        if not good:
            gaps.append(provider)
    return sorted(set(gaps))


def optional_source_losses(task: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    """Only attempted optional sources affect confidence; unselected enhancements do not."""
    terminal = {"success", "no_result", "not_applicable"}
    losses: list[str] = []
    for provider in task.get("optional_sources", []):
        runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider and run.get("operation") != "preflight_probe"]
        if runs and not any(run.get("status") in terminal for run in runs):
            losses.append(provider)
    return sorted(set(losses))


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize one IPR assessment.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--first-review", type=Path, required=True)
    parser.add_argument("--second-review", type=Path)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    candidates_path = task_dir / "normalized-candidates.json"
    candidates = ensure_object(load_json(candidates_path), "normalized-candidates.json") if candidates_path.exists() else {"patents": [], "trademarks": []}
    review_input_digest = sha256_json({"evidence": evidence, "candidates": candidates})
    known_evidence = {entry.get("evidence_id") for values in evidence.get("collections", {}).values() for entry in values if isinstance(entry, dict) and entry.get("evidence_id")}
    first = ensure_object(load_json(args.first_review), "first review")
    validate_review(first, known_evidence, review_input_digest)
    add_history(task, "assessing", "First independent review validated")
    search_plan_path = task_dir / "search-plan.json"
    search_plan = ensure_object(load_json(search_plan_path), "search-plan.json") if search_plan_path.exists() else {}
    missing_sources = source_gaps(task, evidence, candidates, search_plan)
    missing_queries = required_query_gaps(task, evidence, search_plan)
    gate_gaps = low_risk_gate_gaps(task, evidence, search_plan)
    optional_losses = optional_source_losses(task, evidence)
    unverified = material_unverified(candidates)
    assessment: dict[str, Any] = {
        "schema_version": task["schema_version"], "task_id": task["task_id"], "generated_at": now_iso(),
        "status": "", "overall": {"risk": "", "confidence": "", "provisional": True, "reasons": []},
        "modules": first["modules"], "review": {"required": False, "human_review_required": False, "first_reviewer": first.get("reviewer", "independent-review-1")},
        "coverage": {
            "missing_required_sources": missing_sources,
            "missing_required_queries": missing_queries,
            "missing_low_risk_gate_sources": gate_gaps,
            "optional_source_losses": optional_losses,
            "unverified_material_candidates": unverified,
        },
        "recommended_actions": first.get("recommended_actions", []),
    }
    if missing_sources or missing_queries or unverified:
        assessment["status"] = "incomplete"
        assessment["overall"]["reasons"] = (
            (["Required source incomplete: " + ", ".join(missing_sources)] if missing_sources else [])
            + (["Required queries incomplete: " + ", ".join(missing_queries)] if missing_queries else [])
            + (["Material candidate not officially verified: " + ", ".join(unverified)] if unverified else [])
        )
        add_history(task, "incomplete", "; ".join(assessment["overall"]["reasons"]))
    else:
        first_risk = review_risk(first)
        triggers = any(bool(value) for value in first.get("review_triggers", {}).values())
        second_required = first_risk in {"高", "极高"} or triggers
        assessment["review"]["required"] = second_required
        if second_required and not args.second_review:
            assessment["status"] = "needs_review"
            assessment["overall"].update({"risk": first_risk, "confidence": review_confidence(first, len(task.get("images", []))), "provisional": True, "reasons": first.get("summary_reasons", [])})
            add_history(task, "needs_review", "Second independent review required")
        else:
            chosen = first
            if args.second_review:
                second = ensure_object(load_json(args.second_review), "second review")
                validate_review(second, known_evidence, review_input_digest)
                if second.get("reviewer") == first.get("reviewer"):
                    raise ValueError("Second review must use a different reviewer identity")
                if second.get("review_context", {}).get("session_id") == first.get("review_context", {}).get("session_id"):
                    raise ValueError("Second review must use a different review session")
                second_risk = review_risk(second)
                assessment["review"]["second_reviewer"] = second.get("reviewer", "independent-review-2")
                if abs(RISK_LEVELS.index(first_risk) - RISK_LEVELS.index(second_risk)) >= 2:
                    assessment["status"] = "needs_review"
                    assessment["review"]["human_review_required"] = True
                    assessment["overall"].update({"risk": max((first_risk, second_risk), key=RISK_LEVELS.index), "confidence": "低", "provisional": True, "reasons": ["Independent reviews differ by at least two risk levels"]})
                    add_history(task, "needs_review", "Independent reviews diverged by at least two levels")
                else:
                    chosen = reconcile_reviews(first, second)
            if not assessment["status"]:
                assessment["status"] = "completed"
                assessment["modules"] = chosen["modules"]
                assessment["overall"].update({"risk": review_risk(chosen), "confidence": review_confidence(chosen, len(task.get("images", []))), "provisional": False, "reasons": chosen.get("summary_reasons", [])})
                cap_negative_clearance(assessment, gate_gaps)
                if optional_losses:
                    if assessment["overall"]["risk"] == "极低":
                        assessment["overall"]["risk"] = "低"
                    if CONFIDENCE_LEVELS.index(assessment["overall"]["confidence"]) > CONFIDENCE_LEVELS.index("中"):
                        assessment["overall"]["confidence"] = "中"
                    assessment["overall"].setdefault("reasons", []).append("可选来源不可用：" + ", ".join(optional_losses))
                assessment["recommended_actions"] = chosen.get("recommended_actions", [])
                add_history(task, "completed", "Assessment finalized")
    task.setdefault("outputs", {})["assessment_json"] = str(task_dir / "assessment.json")
    atomic_write_json(task_dir / "assessment.json", assessment)
    atomic_write_json(task_dir / "task.json", task)
    print(assessment["status"])


if __name__ == "__main__":
    main()

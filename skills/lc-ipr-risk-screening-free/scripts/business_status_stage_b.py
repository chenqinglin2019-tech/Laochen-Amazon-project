"""10B: read-only business closure and limitation audit over existing records."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from common import load_json, sha256_json

REVISION = "business-status-stage-b-v1"
SCOPE = ("scenario_id", "jurisdiction", "right_type", "candidate_id")
BATCH_SCOPE = ("scenario_id", "jurisdiction", "right_type", "product_version")
ACTIONABLE = {"ready", "awaiting_review", "submission_unknown"}
WAITING = {"awaiting_user", "awaiting_access"}


def enabled(task: dict) -> bool:
    value = task.get("business_status_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("BUSINESS_STATUS_REVISION_INVALID")
    return True


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _batch_for(entry: dict, stage: dict) -> dict | None:
    product_version = stage.get("product", {}).get("product_version")
    expected = {key: entry.get(key) for key in BATCH_SCOPE}
    expected["product_version"] = entry.get("product_version") or product_version
    batches = stage.get("stage_risk", {}).get("stage_review", {}).get("batches", [])
    for batch in batches:
        scope = batch.get("scope", {})
        if (batch.get("status") == "complete" and
                all(scope.get(key) == value for key, value in expected.items()) and
                any(note.get("subject") == "limitations" and
                    entry.get("work_id") in (note.get("work_ids") or [])
                    for note in batch.get("coverage_notes", []))):
            return batch
    return None


def _limitation(entry: dict, stage: dict, view: dict, *, proof_valid: bool, final_assessment=None) -> dict:
    work_id = entry.get("work_id")
    proof = entry.get("delivery_limit") if isinstance(entry.get("delivery_limit"), dict) else {}
    issue = next((row for row in view.get("continuous_work", {}).get("issues", [])
        if work_id in (row.get("work_ids") or [])), {})
    batch = _batch_for(entry, stage)
    review_note = next((note for note in (batch or {}).get("coverage_notes", [])
        if note.get("subject") == "limitations" and work_id in (note.get("work_ids") or [])), {})
    pending_positions = entry.get("pending_positions") or []
    returned, reviewed = entry.get("returned_count"), entry.get("reviewed_count")
    material_pending = (bool(pending_positions) or entry.get("kind") in {"agent_read", "source_result_processing"}
        or (type(returned) is int and type(reviewed) is int and reviewed < returned))
    scope = {key: entry[key] for key in SCOPE if entry.get(key) not in (None, "")}
    if issue.get("scope"):
        scope.update({key: value for key, value in issue["scope"].items() if value not in (None, "")})
    condition = (entry.get("resume_condition") or entry.get("completion_condition")
        or proof.get("recovery_condition") or issue.get("dependency"))
    impact = review_note.get("judgment_impact")
    from final_review import completed as final_completed
    final_valid = final_completed(final_assessment)
    if final_valid:
        matches = [row for row in final_assessment.get("assessments", []) if
            all(row.get(key) == scope.get(key) for key in SCOPE[:3]) and
            row.get("candidate_id") in (None, "", scope.get("candidate_id"))]
        impact = "；".join(dict.fromkeys(str(row.get("pending_reasoning") or row.get("reasoning") or "")
            for row in matches)).strip("；") or None
    gaps = []
    if not proof_valid:
        gaps.append("LIMITATION_PROOF_UNVERIFIED")
    if not all(scope.get(key) for key in SCOPE[:3]):
        gaps.append("ORIGINAL_OBLIGATION_SCOPE_MISSING")
    route_absence_valid = bool(proof_valid and proof.get("route_absence") and
        not proof.get("source_run_refs") and not proof.get("capability_refs"))
    if not route_absence_valid and not (final_valid and proof_valid):
        gaps.append("ALTERNATIVE_ROUTE_UNREVIEWED")
    if material_pending:
        gaps.append("RETAINED_MATERIAL_UNPROCESSED")
    if not _text(condition):
        gaps.append("RECOVERY_CONDITION_MISSING")
    if not _text(impact):
        gaps.append("JUDGMENT_IMPACT_UNREVIEWED")
    if not batch and not final_valid:
        gaps.append("LIMITATION_FINAL_REVIEW_MISSING" if final_assessment is not None else "LIMITATION_09C_REVIEW_MISSING")
    return {"work_id": work_id, "issue_id": entry.get("issue_id") or issue.get("issue_id"),
        "scope": scope, "product_version": entry.get("product_version") or stage.get("product", {}).get("product_version"),
        "obligation_refs": {key: deepcopy(entry[key]) for key in ("requirement_id", "query_id", "action_id", "source_run_id")
            if entry.get(key)}, "state": entry.get("state"), "reason": entry.get("reason"),
        "source_run_refs": deepcopy(proof.get("source_run_refs") or entry.get("source_run_refs") or []),
        "capability_refs": deepcopy(proof.get("capability_refs") or []),
        "route_absence": deepcopy(proof.get("route_absence")),
        "attempt_recorded": bool(proof.get("source_run_refs")),
        "material_processing": {"returned_count": returned, "reviewed_count": reviewed,
            "pending_positions": deepcopy(pending_positions)},
        "alternative_route": "no_qualified_route_proven" if route_absence_valid else "unreviewed",
        "judgment_impact": impact, "recovery_condition": condition,
        "review_batch_id": batch.get("batch_id") if batch else None,
        **({"final_review_digest": final_assessment["final_review"]["evidence_digest"]} if final_valid else {}),
        "affected_work_ids": sorted(set(issue.get("work_ids", []) or [work_id])),
        "affected_scopes": [scope],
        "gaps": gaps}


def classify(task: dict, stage: dict, view: dict, assessment: dict | None = None, *,
             limitation_validator=None) -> dict:
    """Never turn a tag, C/N or local file into business completion."""
    if not enabled(task):
        return {}
    from final_review import enabled as final_enabled, completed as final_completed
    final_policy = final_enabled(task)
    if stage.get("identity_errors"):
        return {"revision": REVISION, "business_status": "integrity_unavailable",
            "delivery_status": "not_verified", "limitations": [],
            "gaps": ["CURRENT_IDENTITY_OR_VIEW_INVALID"], "basis_sha256": sha256_json(stage)}
    entries = view.get("entries", [])
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise ValueError("BUSINESS_STATUS_WORK_VIEW_INVALID")
    risk = stage.get("stage_risk", {})
    overall = risk.get("overall", {})
    progress = stage.get("progress", {})
    pauses = view.get("active_pauses") or []
    stops = view.get("technical_stops") or []
    unresolved = view.get("unresolved_scopes") or []
    review_issues = stage.get("review_issues") or []
    quarantine = stage.get("quarantined_judgments") or []
    judgments = [row for row in risk.get("judgments", []) if row.get("applicability") == "current"]
    reviewed = (all(row.get("review_status") == "chief_reviewed" for row in judgments)
        and not review_issues and not quarantine)
    if final_policy:
        reviewed = final_completed(assessment)
    # The canonical publication decision has already validated bounded limits.
    # New operator tasks consume that decision instead of applying a second,
    # older stage-proof contract to the same accepted limitations. Independent
    # report validation recomputes this publication decision from frozen inputs.
    publication = (assessment or {}).get('publication', {})
    canonical_limits = publication.get('limitations', [])
    canonical_work = publication.get('remaining_work', [])
    binding_keys = ('work_id', 'kind', 'state', 'reason', 'scenario_id', 'jurisdiction',
                    'right_type', 'candidate_id', 'query_id', 'source_run_refs', 'delivery_limit')
    # failure-limits-v1: a technical stop that the canonical publication already disclosed as a
    # bounded limitation (by its stop event id) no longer vetoes the limited round; any other
    # stop, and every stop of a task without the revision, still does.
    from completion_policy import failure_limits_enabled
    disclosed_stops = {limit.get('technical_stop_id') for limit in canonical_limits
                       if isinstance(limit, dict) and limit.get('limitation_kind') == 'internal_technical_failure'}
    blocking_stops = ([stop for stop in stops if stop.get('event_id') not in disclosed_stops]
                      if failure_limits_enabled(task) else stops)
    canonical_round = (task.get('assessment_revision') == 'known-findings-risk-v1'
        and task.get('presentation_policy_revision') == 'operator-report-v1' and final_policy and reviewed
        and publication.get('mode') == 'evidence'
        and bool(publication.get('evidence_digest'))
        and publication.get('evidence_digest') == (assessment or {}).get('final_review', {}).get('evidence_digest')
        and isinstance(canonical_limits, list) and bool(canonical_limits)
        and isinstance(canonical_work, list)
        and not pauses and not blocking_stops and not any(row.get('state') in ACTIONABLE for row in entries)
        and all(any(all(row.get(key) == recorded.get(key) for key in binding_keys)
                    for recorded in canonical_work) for row in entries)
        and all(any(row.get('work_id') == limit.get('work_id') for limit in canonical_limits) for row in entries))
    total = progress.get("planned")
    completed = progress.get("completed")
    plan_done = type(total) is int and type(completed) is int and completed == total
    complete = (not entries and not unresolved and not pauses and not stops and reviewed and plan_done
        and overall.get("review_status") == "complete" and overall.get("applicability") == "current"
        and isinstance(assessment, dict) and assessment.get("status") == "completed")
    limitations = []
    for entry in entries:
        if entry.get("state") == "blocked":
            valid = True if canonical_round else limitation_validator(entry) if limitation_validator else False
            limitations.append(_limitation(entry, stage, view, proof_valid=valid,
                final_assessment=assessment if final_policy else None))
    unique = {}
    for item in limitations:
        key = item.get("work_id") or sha256_json(item)
        if key in unique:
            previous = unique[key]
            for field in ("reason", "source_run_refs", "capability_refs", "route_absence", "recovery_condition"):
                if previous[field] != item[field]:
                    raise ValueError("BUSINESS_STATUS_DUPLICATE_WORK_CONFLICT")
            previous["affected_scopes"].extend(scope for scope in item["affected_scopes"]
                if scope not in previous["affected_scopes"])
            previous["affected_work_ids"] = sorted(set(previous["affected_work_ids"] + item["affected_work_ids"]))
            previous["gaps"] = sorted(set(previous["gaps"] + item["gaps"]))
        else:
            unique[key] = item
    limitations = list(unique.values())
    covered_scopes = [scope for row in limitations for scope in row["affected_scopes"]]
    unresolved_unmatched = [scope for scope in unresolved if not any(all(
        scope.get(key) in (None, "", bound.get(key)) for key in SCOPE[:3]) for bound in covered_scopes)]
    limited = (not complete and bool(entries) and all(row.get("state") == "blocked" for row in entries) and
        all(not row["gaps"] for row in limitations) and not pauses and not stops and not unresolved_unmatched
        and (bool(judgments) or final_policy) and reviewed and isinstance(assessment, dict) and assessment.get("status") != "completed")
    if canonical_round and not complete:
        limited = True
    gaps = []
    if not reviewed:
        gaps.append("NECESSARY_FINAL_REVIEW_PENDING" if final_policy else "NECESSARY_09C_REVIEW_PENDING")
    if not plan_done:
        gaps.append("NECESSARY_PLAN_NOT_COMPLETE")
    if unresolved_unmatched:
        gaps.append("UNRESOLVED_SCOPE_REMAINS")
    if blocking_stops if canonical_round else stops:
        gaps.append("TECHNICAL_STOP_IS_NOT_LIMITATION_PROOF")
    if any(row.get("state") in ACTIONABLE for row in entries):
        gaps.append("EXECUTABLE_OR_REVIEW_WORK_REMAINS")
    gaps.extend(gap for row in limitations for gap in row["gaps"])
    if pauses:
        status = "user_paused" if not any(row.get("state") in ACTIONABLE for row in entries) else "continue"
    elif complete:
        status = "business_complete"
    elif limited:
        status = "limited_round_closed"
    elif any(row.get("state") in ACTIONABLE for row in entries):
        status = "continue"
    elif any(row.get("state") in WAITING for row in entries):
        status = "awaiting_dependency"
    elif not reviewed:
        status = "review_pending"
    else:
        status = "continue"
    return {"revision": REVISION, "business_status": status,
        "delivery_status": "not_verified", "delivery_meaning": "actual_accessible_entry_not_checked",
        "overall_business_complete": status == "business_complete",
        "round_limited_closed": status == "limited_round_closed",
        **({'closure_basis': 'canonical_final_publication',
            'publication_review_digest': publication['evidence_digest']} if canonical_round else {}),
        "limitations": limitations, "gaps": sorted(set(gaps)),
        "active_pauses": deepcopy(pauses), "technical_stops": deepcopy(stops),
        "remaining_work_ids": [row.get("work_id") for row in entries],
        "progress": {"completed": completed, "planned": total, "plan_version": progress.get("plan_version")},
        "source_cutoff": deepcopy(stage.get("progress_cutoff")),
        "review_cutoff": deepcopy(stage.get("grade_cutoff")),
        "basis_sha256": sha256_json({"stage": stage, "work_view": view,
            "assessment_status": assessment.get("status") if isinstance(assessment, dict) else None})}


def build(task_dir: Path, task: dict, stage: dict, assessment: dict | None = None) -> dict:
    if not enabled(task):
        return {}
    task_dir = Path(task_dir)
    required = ("task.json", "evidence.json", "search-plan.json", "normalized-candidates.json",
        "materiality-annotations.json")
    if not all((task_dir / name).is_file() for name in required):
        # A rendering-only fixture has no source work view. It cannot prove closure.
        view = {"entries": stage.get("work", {}).get("entries", []),
            "unresolved_scopes": stage.get("work", {}).get("unresolved_scopes", [])}
        return classify(task, stage, view, None)
    from workflow_v24 import work_view_from_dir
    from necessary_completion import _delivery_limit_valid, capability_map
    from final_review import enabled as final_enabled
    reviews = (assessment or {}).get("review", {}).get("input_reviews", {}) if final_enabled(task) else {}
    view = work_view_from_dir(task_dir, first_review=reviews.get("first"), second_review=reviews.get("second"))
    evidence = load_json(task_dir / "evidence.json")
    plan = load_json(task_dir / "search-plan.json")
    candidates = load_json(task_dir / "normalized-candidates.json")
    ledger = load_json(task_dir / "materiality-annotations.json")
    cap_path = task_dir / "source-capabilities.json"
    caps = capability_map(task, load_json(cap_path)) if cap_path.is_file() else {}
    from workflow_v24 import scenario_supplement
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    def validated(entry):
        return _delivery_limit_valid(entry, task, evidence, plan, caps,
            candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)
    return classify(task, stage, view, assessment, limitation_validator=validated)

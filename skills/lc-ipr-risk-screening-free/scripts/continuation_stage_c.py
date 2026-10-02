"""08C: durable user pause, access notices, and exact pre-resume reconciliation."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from common import RIGHT_TYPES, atomic_write_json, load_json, now_iso, sha256_json

REVISION = "continuous-continuation-stage-c-v1"
ACCESS_WORDS = ("LOGIN", "CAPTCHA", "MFA", "AUTH", "CREDENTIAL", "ACCESS", "CONSENT", "QR")


def enabled(task: dict) -> bool:
    value = task.get("continuous_continuation_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("CONTINUATION_REVISION_INVALID")
    return True


def _events(evidence: dict) -> list[dict]:
    return [row for row in evidence.get("continuation_events", []) if isinstance(row, dict)]


def _scope(scope: dict) -> dict:
    if not isinstance(scope, dict) or scope.get("level") not in {"task", "right_type"}:
        raise ValueError("CONTINUATION_SCOPE_INVALID")
    if scope["level"] == "task":
        return {"level": "task"}
    right_type = scope.get("right_type")
    if not isinstance(right_type, str) or right_type not in RIGHT_TYPES:
        raise ValueError("CONTINUATION_RIGHT_TYPE_REQUIRED")
    return {"level": "right_type", "right_type": right_type}


def active_pauses(evidence: dict) -> list[dict]:
    active = {}
    for event in _events(evidence):
        if event.get("kind") == "pause":
            active[sha256_json(event["scope"])] = event
        elif event.get("kind") == "resume":
            key = sha256_json(event["scope"])
            if active.get(key, {}).get("event_id") == event.get("pause_id"):
                active.pop(key)
    return list(active.values())


def pause_for(task: dict, evidence: dict, row: dict) -> dict | None:
    if not enabled(task):
        return None
    return next((pause for pause in active_pauses(evidence)
        if pause["scope"]["level"] == "task" or
        pause["scope"].get("right_type") == row.get("right_type")), None)


def dispatch_block(task: dict, evidence: dict, row: dict) -> str | None:
    return "USER_ACTIVE_PAUSE" if pause_for(task, evidence, row) else None


def _target(task: dict) -> str:
    return sha256_json({key: task.get(key) for key in
        ("task_id", "request", "target_jurisdictions", "coverage_requirements", "product_identity")})


def _snapshot(task: dict, evidence: dict, plan: dict | None, scope: dict,
              task_dir: Path | None = None) -> dict:
    from recovery_stage_b import effective_submission
    from common import resolve_retained_path, sha256_file
    material = {key: value for key, value in evidence.items() if key != "continuation_events"}
    runs = [{"run_id": row.get("run_id"), "submission_state": effective_submission(evidence, row),
             "original_submission_state": row.get("submission_state"),
             "status": row.get("status"), "sha256": sha256_json(row)}
            for row in evidence.get("source_runs", []) if isinstance(row, dict)]
    historical = [{"source_run_id": row.get("run_id"), "source_run_sha256": sha256_json(row)}
        for row in evidence.get("source_runs", []) if isinstance(row, dict) and
        (row.get("status") in {"success", "no_result"} or row.get("raw_paths"))]
    retained_material = []
    if task_dir is not None:
        for run in evidence.get("source_runs", []):
            if not isinstance(run, dict):
                continue
            for path in run.get("raw_paths", []):
                try:
                    actual = sha256_file(resolve_retained_path(task_dir, path))
                    expected = run.get("payload_digest") if len(run["raw_paths"]) == 1 else None
                    status = "valid" if not expected or expected == actual else "hash_mismatch"
                except (OSError, ValueError):
                    actual, status = None, "missing_or_invalid"
                retained_material.append({"source_run_id": run.get("run_id"), "path": path,
                    "status": status, "actual_sha256": actual})
    if scope["level"] == "task":
        scoped_plan = plan or {}
    else:
        scoped_plan = {}
        for provider, rows in (plan or {}).get("queries", {}).items():
            matched = [row for row in rows if row.get("right_type") == scope["right_type"]]
            if matched:
                scoped_plan[provider] = matched
    return {"target_sha256": _target(task),
            "product_sha256": sha256_json({"product": task.get("product"),
                "product_scope": task.get("product_scope")}),
            "plan_sha256": sha256_json(scoped_plan), "evidence_sha256": sha256_json(material),
            "product_change_ids": [row.get("change_id") for row in task.get("product_change_history", [])
                if isinstance(row, dict)],
            "source_runs": runs, "source_run_count": len(runs),
            "historical_evidence_to_review": historical,
            "retained_material": retained_material,
            "unknown_reserved_count": sum(row["submission_state"] == "unknown" for row in runs),
            "unknown_historical_count": sum(row["original_submission_state"] == "unknown" for row in runs),
            "source_attempt_count": sum(row["submission_state"] == "submitted" for row in runs)}


def _access_key(entry: dict) -> str | None:
    if entry.get("underlying_state", entry.get("state")) != "awaiting_access":
        return None
    reason = str(entry.get("underlying_reason", entry.get("reason")) or "").upper()
    if not any(word in reason for word in ACCESS_WORDS):
        return None
    return "ACCESS-" + sha256_json({"provider": entry.get("provider"), "reason": reason})[:24]


def access_requests(view: dict, evidence: dict) -> list[dict]:
    groups = {}
    for entry in view.get("entries", []):
        key = _access_key(entry)
        if key:
            group = groups.setdefault(key, {"dependency_key": key,
                "provider": entry.get("provider"), "reason": entry.get("underlying_reason", entry.get("reason")),
                "work_ids": [], "issue_ids": [], "capability_versions": [], "user_operation":
                "Complete only the required login, CAPTCHA, MFA, QR, or access consent; the Agent performs the query.",
                "verification": "Recheck the original route and query capability, then resume only unfinished work."})
            if entry.get("work_id"):
                group["work_ids"].append(entry["work_id"])
            if entry.get("issue_id"):
                group["issue_ids"].append(entry["issue_id"])
            if entry.get("capability_sha256"):
                group["capability_versions"].append(entry["capability_sha256"])
    notices = {row.get("dependency_key"): row for row in _events(evidence)
               if row.get("kind") == "access_notice"}
    for item in groups.values():
        item["work_ids"] = sorted(set(item["work_ids"]))
        item["issue_ids"] = sorted(set(item["issue_ids"]))
        item["capability_versions"] = sorted(set(item["capability_versions"]))
        previous = notices.get(item["dependency_key"])
        item["notification"] = ("notify_once" if previous is None else
            "already_notified" if previous.get("work_ids") == item["work_ids"] and
                previous.get("issue_ids") == item["issue_ids"] and
                previous.get("capability_versions") == item["capability_versions"] else "notify_update")
    return sorted(groups.values(), key=lambda row: row["dependency_key"])


def pending_rechecks(task: dict, evidence: dict | None) -> list[dict]:
    if not enabled(task) or evidence is None:
        return []
    latest = {}
    completed = {(row.get("reconciliation_id"), row.get("source_run_id")) for row in _events(evidence)
                 if row.get("kind") == "evidence_recheck_complete"}
    for event in _events(evidence):
        if event.get("kind") == "reconcile":
            for review in event.get("historical_evidence_reviews", []):
                latest[review["source_run_id"]] = (event, review)
    rows = []
    runs = {row.get("run_id"): row for row in evidence.get("source_runs", []) if isinstance(row, dict)}
    for run_id, (event, review) in latest.items():
        if review.get("disposition") != "recheck" or (event["event_id"], run_id) in completed:
            continue
        old = runs.get(run_id, {})
        rows.append({"work_id": "WORK-RECHECK-" + sha256_json({"review": event["event_id"], "run": run_id})[:24],
            "kind": "agent_investigation", "state": "awaiting_review",
            "reason": "HISTORICAL_DYNAMIC_FACT_RECHECK_REQUIRED", "provider": old.get("provider"),
            "right_type": old.get("right_type"), "jurisdiction": old.get("jurisdiction"),
            "source_run_id": run_id, "source_run_refs": [{"run_id": run_id, "sha256": review["source_run_sha256"]}],
            "reconciliation_id": event["event_id"], "fact_scope": review["scope"],
            "assessment_at": review["assessment_at"], "completion_condition":
                "Bind a newly reviewed source result for this dynamic fact; retain the original capture date."})
    return rows


def project(task: dict, view: dict, evidence: dict | None) -> dict:
    if not enabled(task) or evidence is None:
        return view
    result = deepcopy(view)
    # Group dependencies before applying active pauses so they retain their
    # original, independently verifiable access condition.
    result["access_requests"] = access_requests(result, evidence)
    pauses = active_pauses(evidence)
    for entry in [*result.get("entries", []), *result.get("review_work", {}).get("entries", [])]:
        pause = pause_for(task, evidence, entry)
        if pause:
            entry["underlying_state"] = entry.get("underlying_state", entry.get("state"))
            entry["underlying_reason"] = entry.get("underlying_reason", entry.get("reason"))
            entry["state"], entry["reason"] = "blocked", "USER_ACTIVE_PAUSE"
            entry["active_pause_id"] = pause["event_id"]
    for pause in pauses:
        pause_work_id = "WORK-PAUSE-" + pause["event_id"]
        if not any(entry.get("work_id") == pause_work_id for entry in result.get("entries", [])):
            result.setdefault("entries", []).append({"work_id": pause_work_id,
                "kind": "user_pause", "state": "blocked", "reason": "USER_ACTIVE_PAUSE",
                "scope": pause["scope"], "active_pause_id": pause["event_id"]})
    result["active_pauses"] = [{"pause_id": row["event_id"], "scope": row["scope"],
        "intent": row["intent"], "reason": row["reason"]} for row in pauses]
    if isinstance(result.get("continuous_work"), dict):
        by_issue = {}
        for entry in result.get("entries", []):
            if entry.get("issue_id"):
                by_issue.setdefault(entry["issue_id"], []).append(entry)
        for issue in result["continuous_work"].get("issues", []):
            current = by_issue.get(issue.get("issue_id"), [])
            if current:
                issue["states"] = sorted({row.get("state") for row in current})
                for requirement in issue.get("action_requirements", []):
                    match = next((row for row in current if row.get("work_id") == requirement.get("work_id")), None)
                    if match:
                        requirement["state"] = match.get("state")
                if any(row.get("reason") == "USER_ACTIVE_PAUSE" for row in current):
                    issue["user_pause_ids"] = sorted({row["active_pause_id"] for row in current
                        if row.get("active_pause_id")})
    result["counts"] = {state: sum(entry.get("state") == state for entry in result.get("entries", []))
        for state in ("ready", "awaiting_review", "awaiting_access", "awaiting_user", "submission_unknown", "blocked")}
    if pauses:
        result["status"] = "incomplete"
        if isinstance(result.get("continuous_work"), dict):
            result["continuous_work"]["status"] = "user_paused"
    if "work_view_sha256" in result:
        result["work_view_sha256"] = sha256_json({key: value for key, value in result.items()
            if key not in {"work_view_sha256", "review_work"}})
    return result


def record_event(task_dir: Path, request: dict) -> dict:
    """Append an audited control event; never execute or complete source work."""
    from provider_utils import evidence_lock
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        evidence = load_json(task_dir / "evidence.json")
        if not enabled(task) or evidence.get("task_id") != task.get("task_id"):
            raise ValueError("CONTINUATION_TASK_MISMATCH")
        kind = request.get("kind")
        if kind not in {"pause", "reconcile", "resume", "access_notice", "access_feedback",
                        "evidence_recheck_complete"}:
            raise ValueError("CONTINUATION_KIND_INVALID")
        if not all(isinstance(request.get(key), str) and request[key].strip()
                   for key in ("actor", "reasoning")):
            raise ValueError("CONTINUATION_ACTOR_AND_BASIS_REQUIRED")
        plan_path = task_dir / "search-plan.json"
        plan = load_json(plan_path) if plan_path.is_file() else {}
        event = {"kind": kind, "actor": request["actor"], "reasoning": request["reasoning"],
                 "recorded_at": now_iso()}
        if kind == "pause":
            scope = _scope(request.get("scope"))
            if request.get("intent") not in {"pause", "stop", "switch"} or any(
                    row["scope"] == scope for row in active_pauses(evidence)):
                raise ValueError("CONTINUATION_PAUSE_INTENT_OR_SCOPE_INVALID")
            event.update(scope=scope, intent=request["intent"], reason=request.get("reason") or request["reasoning"],
                original_snapshot=_snapshot(task, evidence, plan, scope, task_dir))
        elif kind in {"reconcile", "resume"}:
            pause = next((row for row in active_pauses(evidence)
                if row.get("event_id") == request.get("pause_id")), None)
            if not pause:
                raise ValueError("CONTINUATION_ACTIVE_PAUSE_REQUIRED")
            event.update(scope=pause["scope"], pause_id=pause["event_id"])
            if kind == "reconcile":
                snapshot = _snapshot(task, evidence, plan, pause["scope"], task_dir)
                original = pause["original_snapshot"]
                changed = [key for key in ("target_sha256", "product_sha256", "plan_sha256")
                    if snapshot[key] != original[key]]
                new_changes = task.get("product_change_history", [])[len(original["product_change_ids"]):]
                actual_change_ids = [row.get("change_id") for row in new_changes if isinstance(row, dict)]
                if changed and (not original["product_change_ids"] == snapshot["product_change_ids"][:
                        len(original["product_change_ids"])] or not actual_change_ids or
                        request.get("upstream_change_ids") != actual_change_ids or
                        any(row.get("sha256") != sha256_json({key: value for key, value in row.items()
                            if key != "sha256"}) for row in new_changes) or
                        ("target_sha256" in changed and not any(row.get("prior_target_sha256") and
                            row.get("target_sha256") for row in new_changes))):
                    raise ValueError("CONTINUATION_TARGET_OR_VERSION_CHANGED_USE_UPSTREAM_REVIEW")
                if request.get("original_target_sha256") != original["target_sha256"]:
                    raise ValueError("CONTINUATION_ORIGINAL_TARGET_NOT_REVIEWED")
                if not isinstance(request.get("remaining_work"), list) or not isinstance(request.get("dependency_checks"), list):
                    raise ValueError("CONTINUATION_REMAINING_WORK_AND_DEPENDENCIES_REQUIRED")
                if any(not isinstance(value, str) for value in request["remaining_work"]):
                    raise ValueError("CONTINUATION_REMAINING_WORK_INVALID")
                from workflow_v24 import work_view_from_dir
                view = work_view_from_dir(task_dir)
                scoped = [row for row in [*view.get("entries", []),
                    *view.get("review_work", {}).get("entries", [])]
                    if row.get("kind") != "user_pause" and
                    (pause["scope"]["level"] == "task" or
                     row.get("right_type") == pause["scope"].get("right_type"))]
                actual_work = sorted({row["work_id"] for row in scoped if row.get("work_id")})
                if sorted(request["remaining_work"]) != actual_work:
                    raise ValueError("CONTINUATION_REMAINING_WORK_MISMATCH")
                waiting = sorted({row["work_id"] for row in scoped if row.get("work_id") and
                    row.get("underlying_state", row.get("state")) in
                    {"awaiting_access", "awaiting_user", "submission_unknown", "blocked"}})
                if sorted(row.get("condition") for row in request["dependency_checks"]
                          if isinstance(row, dict)) != waiting:
                    raise ValueError("CONTINUATION_DEPENDENCY_INVENTORY_MISMATCH")
                if any(not isinstance(row, dict) or not row.get("condition") or not row.get("basis") or
                       type(row.get("verified")) is not bool for row in request["dependency_checks"]):
                    raise ValueError("CONTINUATION_DEPENDENCY_CHECK_INVALID")
                historical = request.get("historical_evidence_reviews")
                expected = snapshot["historical_evidence_to_review"]
                if not isinstance(historical, list) or any(not isinstance(row, dict) or
                        not isinstance(row.get("source_run_id"), str) or
                        not isinstance(row.get("source_run_sha256"), str) for row in historical) or sorted(
                        (row["source_run_id"], row["source_run_sha256"]) for row in historical) != sorted(
                        (row["source_run_id"], row["source_run_sha256"]) for row in expected):
                    raise ValueError("CONTINUATION_HISTORICAL_EVIDENCE_INVENTORY_MISMATCH")
                required = ("object", "scope", "version", "purpose", "captured_at", "assessment_at", "basis")
                old_runs = {row.get("run_id"): row for row in evidence.get("source_runs", [])
                    if isinstance(row, dict)}
                if any(not isinstance(row, dict) or not all(row.get(key) for key in required) or
                       row.get("fact_dynamics") not in {"stable_content", "dynamic_fact"} or
                       row.get("disposition") not in {"reuse", "recheck"} or
                       (old_runs.get(row.get("source_run_id"), {}).get("finished_at") or
                        old_runs.get(row.get("source_run_id"), {}).get("checked_at")) not in
                            {None, row.get("captured_at")} or
                       (row.get("fact_dynamics") == "dynamic_fact" and row.get("disposition") != "recheck"
                        and not row.get("current_fact_basis")) for row in historical):
                    raise ValueError("CONTINUATION_EVIDENCE_REUSE_REVIEW_INVALID")
                event.update(snapshot=snapshot, remaining_work=request["remaining_work"],
                    dependency_checks=request["dependency_checks"],
                    upstream_change_ids=actual_change_ids if changed else [],
                    material_review=request.get("material_review"),
                    evidence_reuse_review=request.get("evidence_reuse_review"),
                    historical_evidence_reviews=historical,
                    retry_and_budget_review=request.get("retry_and_budget_review"))
                if not all(event.get(key) for key in
                        ("material_review", "evidence_reuse_review", "retry_and_budget_review")):
                    raise ValueError("CONTINUATION_RECONCILIATION_INCOMPLETE")
            else:
                review = next((row for row in reversed(_events(evidence)) if
                    row.get("event_id") == request.get("reconciliation_id") and
                    row.get("kind") == "reconcile" and row.get("pause_id") == pause["event_id"]), None)
                if (not review or review.get("snapshot") != _snapshot(task, evidence, plan, pause["scope"], task_dir) or
                        not isinstance(request.get("explicit_resume_intent"), str) or
                        not request["explicit_resume_intent"].strip()):
                    raise ValueError("CONTINUATION_EXPLICIT_INTENT_AND_FRESH_RECONCILIATION_REQUIRED")
                event.update(reconciliation_id=review["event_id"], explicit_resume_intent=request["explicit_resume_intent"])
        elif kind == "evidence_recheck_complete":
            review = next((row for row in _events(evidence) if row.get("event_id") ==
                request.get("reconciliation_id") and row.get("kind") == "reconcile"), None)
            old_review = next((row for row in (review or {}).get("historical_evidence_reviews", [])
                if row.get("source_run_id") == request.get("source_run_id") and
                row.get("disposition") == "recheck"), None)
            replacement = next((row for row in evidence.get("source_runs", []) if
                row.get("run_id") == request.get("replacement_source_run_id")), None)
            if (not old_review or not replacement or replacement.get("run_id") == request.get("source_run_id")
                    or replacement.get("status") != "success" or not replacement.get("raw_paths")
                    or request.get("replacement_source_run_sha256") != sha256_json(replacement)
                    or not request.get("fact_review") or not request.get("material_review")
                    or not request.get("object_match_basis") or not request.get("scope_match_basis")):
                raise ValueError("CONTINUATION_DYNAMIC_RECHECK_NOT_PROVEN")
            from common import parse_iso
            try:
                if parse_iso(replacement.get("finished_at") or replacement.get("checked_at")) <= parse_iso(old_review["captured_at"]):
                    raise ValueError("CONTINUATION_REPLACEMENT_NOT_NEWER")
            except (TypeError, AttributeError) as exc:
                raise ValueError("CONTINUATION_REPLACEMENT_TIME_REQUIRED") from exc
            if any(row.get("kind") == "evidence_recheck_complete" and
                   row.get("reconciliation_id") == review["event_id"] and
                   row.get("source_run_id") == old_review["source_run_id"] for row in _events(evidence)):
                raise ValueError("CONTINUATION_DYNAMIC_RECHECK_ALREADY_CLOSED")
            from common import resolve_retained_path
            for retained in replacement["raw_paths"]:
                resolve_retained_path(task_dir, retained,
                    expected_sha256=replacement.get("payload_digest") if len(replacement["raw_paths"]) == 1 else "")
            if isinstance(replacement.get("result_processing"), dict):
                from source_result_processing import progress
                if not progress(task_dir, replacement, evidence)["material_processing_complete"]:
                    raise ValueError("CONTINUATION_REPLACEMENT_MATERIAL_PENDING")
            event.update(reconciliation_id=review["event_id"], source_run_id=old_review["source_run_id"],
                source_run_sha256=old_review["source_run_sha256"],
                replacement_source_run_id=replacement["run_id"],
                replacement_source_run_sha256=sha256_json(replacement),
                fact_review=request["fact_review"], material_review=request["material_review"],
                object_match_basis=request["object_match_basis"],
                scope_match_basis=request["scope_match_basis"])
        elif kind in {"access_notice", "access_feedback"}:
            from workflow_v24 import work_view_from_dir
            groups = {row["dependency_key"]: row for row in access_requests(work_view_from_dir(task_dir), evidence)}
            key = request.get("dependency_key")
            if key not in groups:
                raise ValueError("CONTINUATION_ACCESS_DEPENDENCY_NOT_CURRENT")
            if kind == "access_notice":
                if groups[key]["notification"] == "already_notified":
                    raise ValueError("CONTINUATION_ACCESS_NOTICE_ALREADY_SENT")
                event.update(dependency_key=key, work_ids=groups[key]["work_ids"],
                    issue_ids=groups[key]["issue_ids"],
                    capability_versions=groups[key]["capability_versions"],
                    user_operation=groups[key]["user_operation"],
                    verification=groups[key]["verification"])
            else:
                if type(request.get("query_capability_verified")) is not bool or not request.get("condition_basis"):
                    raise ValueError("CONTINUATION_ACCESS_FEEDBACK_NOT_VERIFIED")
                event.update(dependency_key=key, query_capability_verified=request["query_capability_verified"],
                    condition_basis=request["condition_basis"], user_feedback=request.get("user_feedback"))
        event["event_sequence"] = len(_events(evidence)) + 1
        event["event_id"] = "CONT-" + sha256_json(event)[:24]
        evidence.setdefault("continuation_events", []).append(event)
        atomic_write_json(task_dir / "evidence.json", evidence)
        return event

"""08A: one read-only, issue-oriented projection over the existing next_work view."""
from __future__ import annotations

from copy import deepcopy

from common import sha256_json

REVISION = "continuous-work-stage-a-v1"
ACTIONABLE = {"ready", "awaiting_review"}
WAITING = {"awaiting_user", "awaiting_access", "submission_unknown", "blocked"}
SCOPE = ("scenario_id", "jurisdiction", "right_type", "candidate_id", "object_id",
         "subject_id", "subject_version")
ISSUE_KEYS = ("obligation_id", "gap_event_id", "gap_id", "handoff_gap", "change_event_id",
              "impact_event_id", "fact_event_id", "fact_id", "material_event_id",
              "evidence_obligation_id", "requirement_id", "request_id", "source_run_id",
              "planning_gap", "query_id", "action_id", "work_id")


def enabled(task: dict) -> bool:
    revision = task.get("continuous_work_stage_revision")
    if revision is None:
        return False
    if revision != REVISION:
        raise ValueError("CONTINUOUS_WORK_STAGE_REVISION_INVALID")
    return True


def _issue(entry: dict, task: dict) -> tuple[str, str, str]:
    key = next((name for name in ISSUE_KEYS if entry.get(name) not in (None, "", [])), "")
    value = entry.get(key) if key else None
    scope = {name: entry.get(name) for name in SCOPE if entry.get(name) not in (None, "")}
    # Scope-only legacy entries remain visible, but cannot acquire a made-up
    # identity or be counted as a fully specified problem.
    quality = "exact" if key and key != "work_id" else "provisional"
    if not key:
        key, value = "legacy_entry", sha256_json(entry)
    issue_id = "ISSUE-" + sha256_json({"task_id": task.get("task_id"), "scope": scope,
        "key": key, "value": value})[:24]
    return issue_id, quality, key


def _action(entry: dict, task: dict) -> str:
    # A real source operation is shared across countries when the exact query
    # is shared. It is one action with several scoped issues, never a new run.
    if (entry.get("source_run_id") and entry.get("reason") in
            {"SOURCE_RESULTS_PENDING_PROCESSING", "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID"}):
        identity = {"task_id": task.get("task_id"), "kind": "process_retained_result",
            "source_run_id": entry["source_run_id"]}
    elif entry.get("query_id"):
        identity = {"task_id": task.get("task_id"), "provider": entry.get("provider"),
            "query_id": entry["query_id"], "kind": entry.get("kind")}
    elif entry.get("source_run_id"):
        identity = {"task_id": task.get("task_id"), "source_run_id": entry["source_run_id"]}
    elif entry.get("action_id"):
        identity = {"task_id": task.get("task_id"), "action_id": entry["action_id"]}
    elif entry.get("gap_event_id"):
        identity = {"task_id": task.get("task_id"), "gap_event_id": entry["gap_event_id"]}
    else:
        identity = {"task_id": task.get("task_id"), "work_id": entry.get("work_id")}
    return "ACTION-" + sha256_json(identity)[:24]


def _condition(entry: dict) -> str:
    if entry.get("completion_condition"):
        return str(entry["completion_condition"])
    if entry.get("reason") in {"SOURCE_RESULTS_PENDING_PROCESSING",
                                "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID"}:
        return "Review and assign a supported destination to every acquired result position"
    if entry.get("kind") == "source_lookup":
        return "Review the exact request receipt and its required evidence obligation"
    if entry.get("kind") == "agent_read":
        return "Review the retained original for the requested facts and reading scope"
    if entry.get("kind") == "triage":
        return "Record a scoped candidate decision supported by the retained evidence"
    return "Record evidence and re-project this specific open obligation"


def _priority(entry: dict, shared_count: int) -> tuple[int, int, str]:
    reason = str(entry.get("reason") or "")
    old = entry.get("triage_priority") if isinstance(entry.get("triage_priority"), dict) else {}
    age = old.get("received_order")
    age = age if type(age) is int and age >= 0 else 10**9
    if any(token in reason for token in ("CHANGE_REVIEW", "IMPACT_REVIEW", "CONFLICT",
                                          "REOPEN", "CORRECTION")):
        rank = 0
    elif reason in {"SOURCE_RESULTS_PENDING_PROCESSING", "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID",
                    "RETAINED_ORIGINAL_REQUIRES_READING"} or entry.get("kind") == "agent_read":
        rank = 1
    elif entry.get("kind") == "triage" or "TRIAGE" in reason:
        rank = 2
    elif shared_count > 1 and entry.get("state") in ACTIONABLE:
        rank = 3
    elif entry.get("state") in ACTIONABLE:
        rank = 4
    else:
        rank = 5
    return rank, age, str(entry.get("work_id") or "")


def project(task: dict, view: dict, evidence: dict | None = None, plan: dict | None = None) -> dict:
    """Decorate the existing queue; preserve every entry and every old work_id."""
    if not enabled(task):
        return view
    from recovery_stage_b import project as recovery_project
    result = recovery_project(task, deepcopy(view), evidence, plan)
    from continuation_stage_c import pending_rechecks
    result.setdefault("entries", []).extend(pending_rechecks(task, evidence))
    from stage_review_stage_c import supplement_entries
    result["entries"].extend(supplement_entries(task, evidence))
    entries = result.get("entries", [])
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise ValueError("CONTINUOUS_WORK_ENTRIES_INVALID")
    runs = {row.get("run_id"): row for row in (evidence or {}).get("source_runs", [])
            if isinstance(row, dict) and row.get("run_id")}
    actions: dict[str, set[str]] = {}
    issues: dict[str, dict] = {}
    for entry in entries:
        issue_id, quality, key = _issue(entry, task)
        action_id = _action(entry, task)
        entry["issue_id"] = issue_id
        entry["linked_action_id"] = action_id
        actions.setdefault(action_id, set()).add(issue_id)
        run = runs.get(entry.get("source_run_id")) or next((runs.get(ref.get("run_id"))
            for ref in reversed(entry.get("source_run_refs", [])) if isinstance(ref, dict)
            and ref.get("run_id") in runs), None)
        from recovery_stage_b import effective_result, effective_submission
        recorded_submission = (run or {}).get("submission_state", "not_recorded")
        effective = effective_submission(evidence or {}, run) if run else recorded_submission
        recorded_result = (run or {}).get("status", "not_recorded")
        execution = {"submission": effective,
                     "result": effective_result(evidence or {}, run) if run else recorded_result}
        if effective != recorded_submission:
            execution["original_submission_recorded"] = recorded_submission
        if execution["result"] != recorded_result:
            execution["original_result_recorded"] = recorded_result
        material = {"returned_count": entry.get("returned_count"),
                    "parsed_count": entry.get("parsed_count"),
                    "reviewed_count": entry.get("reviewed_count"),
                    "pending_positions": entry.get("pending_positions", [])}
        issue = issues.setdefault(issue_id, {"issue_id": issue_id, "identity_quality": quality,
            "identity_key": key, "scope": {name: entry.get(name) for name in SCOPE if entry.get(name) not in (None, "")},
            "version_refs": {name: entry[name] for name in ("subject_version", "candidate_version_sha256",
                "product_version_sha256", "plan_entry_sha256", "assessment_date") if entry.get(name)},
            "missing_fact_or_obligation": entry.get("question") or entry.get("reason") or entry.get("kind"),
            "completion_condition": _condition(entry),
            "dependency": entry.get("resume_condition") or entry.get("dependency") or
                entry.get("next_action_or_dependency"),
            "action_ids": [], "work_ids": [], "action_requirements": [],
            "observed_reasons": [],
            "states": [], "execution": [], "material_processing": [],
            "conclusion_usability": "needs_recheck" if any(token in str(entry.get("reason") or "")
                for token in ("CHANGE_REVIEW", "IMPACT_REVIEW", "RECHECK", "CONFLICT")) else "not_asserted"})
        issue["action_ids"].append(action_id)
        issue["work_ids"].append(entry.get("work_id"))
        issue["action_requirements"].append({"action_id": action_id,
            "work_id": entry.get("work_id"), "completion_condition": _condition(entry),
            "required_facts": entry.get("required_facts", []),
            "state": entry.get("state")})
        issue["observed_reasons"].append(entry.get("reason"))
        issue["states"].append(entry.get("state"))
        issue["execution"].append(execution)
        issue["material_processing"].append(material)
    for issue in issues.values():
        for key in ("action_ids", "work_ids", "states", "observed_reasons"):
            issue[key] = sorted(set(issue[key]), key=str)
        issue["obligation"] = "open"
    for entry in entries:
        rank, age, _ = _priority(entry, len(actions[entry["linked_action_id"]]))
        entry["continuous_priority"] = {"rank": rank, "received_order": age,
            "basis": ("affected_conclusion_recheck" if rank == 0 else
                      "retained_material" if rank == 1 else "light_triage" if rank == 2 else
                      "shared_action" if rank == 3 else "independent_work" if rank == 4 else "dependency_wait")}
    result["entries"] = sorted(entries, key=lambda row: (
        row["continuous_priority"]["rank"], row["continuous_priority"]["received_order"],
        str(row.get("work_id") or "")))
    result["continuous_work"] = {"revision": REVISION,
        "issues": sorted(issues.values(), key=lambda row: row["issue_id"]),
        "actions": [{"action_id": key, "issue_ids": sorted(value)} for key, value in sorted(actions.items())],
        "status": ("continue" if any(row.get("state") in ACTIONABLE for row in entries) else
                   "waiting" if any(row.get("state") in WAITING for row in entries) else
                   "stage_ready_for_downstream_review" if not entries and view.get("status") == "complete"
                   else "in_progress"),
        "completion_meaning": "current_obligations_only; risk_review_and_publication_separate"}
    if "work_view_sha256" in result:
        result["work_view_sha256"] = sha256_json({key: value for key, value in result.items()
            if key not in {"work_view_sha256", "review_work"}})
    return result

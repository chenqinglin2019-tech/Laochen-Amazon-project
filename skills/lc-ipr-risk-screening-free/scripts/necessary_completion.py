"""Opt-in completion checks over existing evidence and work projections.

This module owns no queue or mutable authority ledger. Publication retains the
non-secret status inputs used for its decision so validation never reads the
validating machine's credentials.
"""
from copy import deepcopy

from common import sha256_json

REVISION = "necessary-work-v1"
_ACCESS_REASONS = frozenset({"optional_credentials_missing", "OPTIONAL_CREDENTIALS_MISSING",
    "CREDENTIAL_MISSING", "AUTH_REQUIRED", "LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "MFA_REQUIRED",
    "CONSENT_REQUIRED", "QR_REQUIRED", "ACCESS_INTERACTION_REQUIRED", "QUOTA_EXHAUSTED",
    "FREE_QUOTA_EXHAUSTED", "RATE_LIMITED", "SOURCE_RETRY_CONDITION_REQUIRED",
    "BROWSER_RATE_LIMITED", "BROWSER_RATE_LIMIT_COOLDOWN", "BROWSER_RATE_LIMIT_RECOVERY_EXHAUSTED",
    "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED"})
_BLOCKED_REASONS = frozenset({"NO_SUPPORTED_ROUTE", "automation_policy_incompatible",
    "free_entitlement_unvalidated", "AUTOMATION_PROHIBITED", "CURRENT_STATUS_ROUTE_UNAVAILABLE",
    "BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED", "BROWSER_PARTIAL_RESUME_LIMIT"})


def enabled(task):
    revision = task.get("completion_policy_revision")
    if revision is None:
        return False
    if (revision != REVISION or task.get("schema_version") != "2.4-free"
            or task.get("assessment_policy") != "evidence-estimate-v1"
            or task.get("workflow_correction_revision") != "workflow-correction-v1"):
        raise ValueError("COMPLETION_POLICY_INVALID")
    return True


def capability_map(task, snapshot):
    if snapshot is None:
        return {}
    if not isinstance(snapshot, dict) or snapshot.get("task_id") != task["task_id"]:
        raise ValueError("COMPLETION_CAPABILITY_SNAPSHOT_INVALID")
    sources = snapshot.get("sources")
    if not isinstance(sources, list):
        raise ValueError("COMPLETION_CAPABILITY_SNAPSHOT_INVALID")
    result = {}
    for row in sources:
        if (not isinstance(row, dict) or not isinstance(row.get("provider"), str)
                or row["provider"] in result or type(row.get("executable")) is not bool):
            raise ValueError("COMPLETION_CAPABILITY_SNAPSHOT_INVALID")
        result[row["provider"]] = row
    return result


def sanitize_snapshots(task, snapshots):
    """Retain only fields consumed by work projection; never serialize opaque results."""
    if not isinstance(snapshots, dict) or set(snapshots) - {"source-capabilities.json", "browser-execution-status.json"}:
        raise ValueError("PUBLICATION_SNAPSHOT_INVALID")
    result = {}
    def fields(value, names):
        if not isinstance(value, dict):
            raise ValueError("PUBLICATION_SNAPSHOT_INVALID")
        kept = {key: value[key] for key in names if key in value}
        if any(item is not None and not isinstance(item, (str, bool, int, float)) for item in kept.values()):
            raise ValueError("PUBLICATION_SNAPSHOT_FIELD_INVALID")
        return kept
    for name, snapshot in snapshots.items():
        if not isinstance(snapshot, dict) or snapshot.get("task_id") != task["task_id"]:
            raise ValueError("PUBLICATION_SNAPSHOT_IDENTITY_INVALID")
        saved = fields(snapshot, ("schema_version", "task_id"))
        if name == "source-capabilities.json":
            capability_map(task, snapshot)
            saved["sources"] = [fields(row, ("provider", "state", "reason", "executable",
                "credentials_present", "checked_at", "cost_ceiling_usd")) for row in snapshot["sources"]]
        else:
            if not isinstance(snapshot.get("queries", []), list):
                raise ValueError("PUBLICATION_BROWSER_SNAPSHOT_INVALID")
            saved["queries"] = [fields(row, ("query_id", "plan_entry_sha256", "provider", "dispatch",
                "status", "error_code", "source_error_code", "phase", "submission_state",
                "partial_resume_attempts", "partial_resume_limit"))
                for row in snapshot.get("queries", [])]
            pauses = snapshot.get("provider_pauses", {})
            if not isinstance(pauses, dict):
                raise ValueError("PUBLICATION_BROWSER_SNAPSHOT_INVALID")
            saved["provider_pauses"] = {provider: fields(pause, ("error_code", "reason", "resume_after_epoch",
                "recovery_attempts", "paused_at", "query_id")) for provider, pause in pauses.items()}
        result[name] = saved
    return result


def _scope(value):
    return tuple(value.get(key) for key in ("scenario_id", "jurisdiction", "right_type"))


def _route_options(task, requirement, axis):
    """Ask the existing parameter compiler; do not invent an adapter per axis."""
    from workflow_v24 import _api_params, LANGUAGES
    right, country = requirement["right_type"], requirement["jurisdiction"]
    kinds = {"text": [("brand", "mark")] if right.startswith("trademark") else [("product", "toy")], "description": [("mark_description", "circle")],
        "phonetic": [("phonetic", "mark")], "owner": [("owner", "Example")],
        "classification": ([("ipc", "A63H33/00"), ("cpc", "A63H33/00"), ("uspc", "446/1")]
            if right in {"patent", "utility_model"} else [("locarno", "21-01"), ("uspc", "D21/398")]
            if right == "design" else [("design_code", "260101"), ("nice", "28")])}.get(axis, [])
    options = []
    for route in requirement.get("routes", []):
        provider = route.get("provider")
        if route.get("operation") in {"candidate_detail", "candidate_verification", "document_retrieval"}:
            continue
        if provider == "asset_provenance":
            from record_asset_provenance import INVESTIGATION_STEPS
            if axis in INVESTIGATION_STEPS.get(right, ()):
                options.append(route)
            continue
        for kind, value in kinds:
            term = {"kind": kind, "value": value, "language": LANGUAGES.get(country, ""),
                "strategy": "phrase" if axis == "owner" or (right.startswith("trademark") and axis == "text") else "boolean"}
            try:
                params = _api_params(provider, term, country, right)
                if params is not None and provider.endswith("browser"):
                    from record_browser_execution import planned_browser_query
                    row = {**params, "operation": route.get("operation"), "right_type": right}
                    if provider == "uspto_tmsearch_browser":
                        row["query_compiler_revision"] = "tm-figurative-fields-v1" if right == "trademark_figurative" else "tm-field-tags-v1"
                    planned_browser_query(provider, row, task)
            except (ValueError, TypeError):
                params = None
            if params is not None:
                options.append(route)
                break
    return options


def _route_state(options, capabilities):
    if not options:
        return "blocked", "NO_SUPPORTED_ROUTE"
    states = []
    for route in options:
        provider = route["provider"]
        cap = capabilities.get(provider, {})
        reason = cap.get("reason", "SOURCE_CAPABILITY_CHECK_REQUIRED")
        if provider == "asset_provenance" or cap.get("executable") is True:
            return "ready", "SUPPORTED_ROUTE_AVAILABLE"
        if reason in _ACCESS_REASONS:
            states.append(("awaiting_access", reason))
        elif reason in _BLOCKED_REASONS:
            states.append(("blocked", reason))
        else:
            # A missing preflight or local acceptance check is Agent work.
            return "ready", reason
    return next((s for s in states if s[0] == "awaiting_access"), states[0])


def refine_work_view(task, view, plan, capabilities):
    """Only marked tasks refine unsupported routes; investigation status stays separate."""
    if not enabled(task):
        return view
    view = deepcopy(view)
    from workflow_v24 import product_analysis_readiness
    for gap in product_analysis_readiness(task).get("gaps", []):
        entry = {"scenario_id": task.get("primary_scenario_id"), "kind": "product_analysis",
            "state": "ready", "reason": gap["code"]}
        entry["work_id"] = "WORK-" + sha256_json(entry)[:24]
        view["entries"].append(entry)
    requirements = {r["requirement_id"]: r for r in task.get("coverage_requirements", [])}
    rows = {r["query_id"]: r for values in plan.get("queries", {}).values()
        if isinstance(values, list) for r in values if isinstance(r, dict) and r.get("query_id")}
    original_entries = deepcopy(view["entries"])
    for entry in view["entries"]:
        reason = entry.get("reason", "")
        if reason in {"UNSUPPORTED_QUERY_SEMANTICS", "USPTO_QUERY_REJECTED"}:
            entry.update(state="ready", kind="plan_repair")
            row = rows.get(entry.get("query_id"), {})
            entry.update(query=row.get("q") or row.get("query"), derived_from=row.get("derived_from"),
                plan_entry_sha256=sha256_json(row) if row else None)
            continue
        axis = reason.split(":AXIS_MISSING:", 1)[1] if ":AXIS_MISSING:" in reason else None
        requirement = requirements.get(reason.split(":", 1)[0]) if axis else None
        if axis and requirement:
            options = _route_options(task, requirement, axis)
            entry["state"], entry["reason"] = _route_state(options, capabilities)
            entry["planning_gap"] = reason
            entry["route_options"] = [{k: route[k] for k in ("provider", "operation") if k in route} for route in options]
        elif entry.get("state") in {"awaiting_access", "blocked"} and entry.get("query_id"):
            row = rows.get(entry["query_id"], {})
            reqs = [requirements[r] for r in row.get("requirement_ids", []) if r in requirements]
            alternatives = [option for req in reqs for option in _route_options(task, req, row.get("search_dimension", "text"))
                if option.get("provider") != entry.get("provider")]
            from workflow_v24 import necessary_scenario_row_bindings
            # An already-planned alternative is represented by its own receipt
            # and work entry (including a provider cooldown). Never keep asking
            # for a duplicate plan merely because its static adapter is enabled.
            def unplanned(option):
                provider = option["provider"]
                for alternative in plan.get("queries", {}).get(provider, []):
                    if (alternative.get("search_dimension") == row.get("search_dimension")
                            and set(alternative.get("requirement_ids", [])) & set(row.get("requirement_ids", []))
                            and (alternative.get("triage_jurisdiction") or alternative.get("jurisdiction")) == entry.get("jurisdiction")
                            and alternative.get("right_type") == entry.get("right_type")
                            and any(binding["scenario_id"] == entry.get("scenario_id")
                                for binding in necessary_scenario_row_bindings(task, alternative))):
                        return False
                return not any(other.get("provider") == provider and other.get("state") == "awaiting_access"
                    and str(other.get("reason", "")).startswith("BROWSER_RATE_LIMIT") for other in original_entries)
            alternatives = [option for option in alternatives if unplanned(option)]
            if alternatives and _route_state(alternatives, capabilities)[0] == "ready":
                entry.update(state="ready", reason="AUTHORIZED_ALTERNATIVE_REQUIRES_PLANNING", kind="plan_repair")
    scope_keys = {_scope(entry) for entry in view.get("unresolved_scopes", [])}
    for gap in plan.get("planning_gaps", []):
        if gap.get("code") != "UNSUPPORTED_QUERY_SEMANTICS":
            continue
        for sid, country, right in scope_keys:
            if (country, right) != (gap.get("jurisdiction"), gap.get("right_type")):
                continue
            entry = {"scenario_id": sid, "jurisdiction": country, "right_type": right,
                "kind": "plan_repair", "state": "ready", "reason": gap["code"],
                "term_id": gap.get("term_id"), "provider": gap.get("provider"),
                "query": gap.get("query"), "derived_from": gap.get("derived_from"),
                "detail": gap.get("reason")}
            entry["work_id"] = "WORK-" + sha256_json(entry)[:24]
            view["entries"].append(entry)
    view["counts"] = {state: sum(item["state"] == state for item in view["entries"])
        for state in ("ready", "awaiting_review", "awaiting_access", "awaiting_user", "submission_unknown", "blocked")}
    view["status"] = "incomplete" if view["entries"] or view.get("unresolved_scopes") else "complete"
    return view


def review_work(task, evidence, candidates, plan, ledger, scopes, first=None, second=None,
                *, supplement=None, evidence_root=None):
    from assessment_estimate import (review_digest, _validate_review, missing_scope_reviews,
        evidence_index, candidate_index, validate_supplement)
    digest = review_digest(evidence, candidates, ledger, plan, task, supplement)
    registry = {**evidence_index(evidence), **validate_supplement(supplement, evidence_root, task=task, evidence=evidence)}
    index, errors = candidate_index(candidates)
    if errors:
        raise ValueError("; ".join(errors))
    for review in (first, second):
        if review is not None:
            _validate_review(review, digest, set(registry), index, set(task.get("target_jurisdictions", [])), task, registry)
    if first and second and (first["reviewer"] == second["reviewer"]
            or first["review_context"]["session_id"] == second["review_context"]["session_id"]):
        raise ValueError("SECOND_REVIEW_NOT_INDEPENDENT")
    missing = missing_scope_reviews(task, scopes, first, second, registry, index)
    entries = []
    for item in missing:
        for reviewer in item["missing_reviewers"]:
            role = "first" if reviewer == (first or {}).get("reviewer", "first") else "second"
            row = {key: item[key] for key in ("scenario_id", "jurisdiction", "right_type")}
            row.update(kind="scope_review", state="awaiting_review", action_id="review:" + role,
                reviewer=reviewer, reason="NECESSARY_SCOPE_REVIEW_REQUIRED")
            row["work_id"] = "WORK-" + sha256_json(row)[:24]
            entries.append(row)
    return {"status": "incomplete" if entries else "complete", "entries": entries, "evidence_digest": digest}


def publication_context(task, evidence, candidates, plan, ledger, assessment, *,
                        mode=None, stop_reason=None, snapshots=None, task_dir=None, evidence_root=None):
    """Recompute a publication decision using only frozen, non-secret inputs."""
    if not enabled(task):
        if mode is not None or stop_reason is not None:
            raise ValueError("COMPLETION_POLICY_REQUIRED_FOR_PUBLICATION_MODE")
        return None
    from workflow_v24 import derive_work_view
    mode = mode or "final"
    if mode not in {"final", "stage"}:
        raise ValueError("PUBLICATION_MODE_INVALID")
    raw_snapshots = snapshots if snapshots is not None else {}
    snapshots = sanitize_snapshots(task, raw_snapshots)
    source_digests = {name: sha256_json(value) for name, value in raw_snapshots.items()}
    caps = capability_map(task, snapshots.get("source-capabilities.json"))
    scopes = assessment["coverage"]["scopes"]
    supplement = assessment.get("supplement")
    reviews = assessment["review"]["input_reviews"]
    view = derive_work_view(task, evidence, candidates, plan, ledger, supplement=supplement,
        evidence_root=evidence_root, task_dir=task_dir, coverage=scopes,
        browser_status=snapshots.get("browser-execution-status.json"), source_capabilities=caps)
    view = refine_work_view(task, view, plan, caps)
    from workflow_v24 import plan_row_index
    plan_index = plan_row_index(plan)
    for entry in view["entries"]:
        matches = plan_index.get(entry.get("query_id"), [])
        if len(matches) == 1:
            provider, row = matches[0]
            entry["source_run_refs"] = [{"run_id": run["run_id"], "sha256": sha256_json(run)}
                for run in evidence.get("source_runs", []) if run.get("query_id") == row["query_id"]
                and run.get("provider") == provider and run.get("plan_entry_sha256") == sha256_json(row)]
        if entry.get("provider") in caps:
            entry["capability_sha256"] = sha256_json(caps[entry["provider"]])
    review = review_work(task, evidence, candidates, plan, ledger, scopes, reviews["first"], reviews.get("second"),
        supplement=supplement, evidence_root=evidence_root)
    if review["entries"]:
        raise ValueError("PUBLICATION_SCOPE_REVIEW_REQUIRED: " + ",".join(r["work_id"] for r in review["entries"]))
    if mode == "final":
        if assessment["status"] != "completed" or view["status"] != "complete" or view["entries"]:
            raise ValueError("PUBLICATION_NECESSARY_WORK_INCOMPLETE")
        if stop_reason:
            raise ValueError("FINAL_PUBLICATION_CANNOT_HAVE_STOP_REASON")
    else:
        if not isinstance(stop_reason, str) or not stop_reason.strip():
            raise ValueError("STAGE_STOP_REASON_REQUIRED")
        if assessment["status"] == "completed":
            raise ValueError("COMPLETED_ASSESSMENT_REQUIRES_FINAL_PUBLICATION")
        actionable = [r for r in view["entries"] if r["state"] in {"ready", "awaiting_review", "submission_unknown"}]
        if actionable:
            raise ValueError("STAGE_AGENT_WORK_REMAINS: " + ",".join(r["work_id"] for r in actionable))
        blockers = [r for r in view["entries"] if
            (r["state"] == "awaiting_access" and r["reason"] in _ACCESS_REASONS)
            or (r["state"] == "blocked" and r["reason"] in _BLOCKED_REASONS)
            or (r["state"] == "awaiting_user" and r.get("kind") in {"user_evidence", "user_information"})]
        if not blockers or len(blockers) != len(view["entries"]):
            raise ValueError("STAGE_EXTERNAL_BLOCKER_NOT_ESTABLISHED")
        blocked_scopes = {_scope(r) for r in blockers}
        if any(_scope(scope) not in blocked_scopes for scope in view.get("unresolved_scopes", [])):
            raise ValueError("STAGE_UNRESOLVED_SCOPE_WITHOUT_BLOCKER")
        for scenario in assessment.get("scenario_summaries", []):
            queues = scenario["completion"].get("queues", {})
            pending = {(*_scope(row), row.get("candidate_id")) for row in queues.get("pending_assessments", [])}
            if queues.get("scope_unassessed") or any((*_scope(row), row.get("candidate_id")) not in pending
                    for row in queues.get("selected_unassessed", [])):
                raise ValueError("STAGE_REVIEW_WORK_REMAINS")
            if any(_scope(row) not in blocked_scopes for row in queues.get("pending_assessments", [])):
                raise ValueError("STAGE_PENDING_ASSESSMENT_WITHOUT_BLOCKER")
    return {"revision": REVISION, "mode": mode, "stop_reason": stop_reason.strip() if stop_reason else None,
        "evidence_digest": review["evidence_digest"], "work_view_sha256": sha256_json(view),
        "remaining_work": view["entries"], "review_work_sha256": sha256_json(review),
        "snapshots": snapshots, "snapshot_digests": {name: sha256_json(value) for name, value in snapshots.items()},
        "snapshot_source_digests": source_digests}


def restore_publication(task, evidence, candidates, plan, ledger, expected, saved, *, task_dir, evidence_root=None):
    """Independent validation and standalone builds share the same frozen proof check."""
    if not enabled(task):
        return expected
    from pathlib import Path
    from common import load_json
    publication = saved.get("publication")
    if (not isinstance(publication, dict) or not isinstance(publication.get("snapshots"), dict)
            or not isinstance(publication.get("snapshot_source_digests"), dict)):
        raise ValueError("PUBLICATION_CONTEXT_REQUIRED")
    snapshots = {}
    for name in ("source-capabilities.json", "browser-execution-status.json"):
        path = Path(task_dir) / name
        if path.is_file():
            snapshots[name] = load_json(path)
        actual_digest = sha256_json(snapshots[name]) if name in snapshots else None
        if actual_digest != publication.get("snapshot_source_digests", {}).get(name):
            raise ValueError("PUBLICATION_SNAPSHOT_CHANGED: " + name)
    expected["publication"] = publication_context(task, evidence, candidates, plan, ledger, expected,
        mode=publication.get("mode"), stop_reason=publication.get("stop_reason"), snapshots=snapshots,
        task_dir=task_dir, evidence_root=evidence_root)
    expected["completion_policy_revision"] = task["completion_policy_revision"]
    return expected

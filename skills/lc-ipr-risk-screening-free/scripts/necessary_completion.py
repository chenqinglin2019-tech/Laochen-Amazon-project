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
    from completion_policy import supported
    if (not supported(task) or task.get("schema_version") != "2.4-free"
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
    from completion_policy import evidence_delivery_enabled
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
            if evidence_delivery_enabled(task):
                for source, retained in zip(snapshot["sources"], saved["sources"]):
                    operations = source.get("operations", [])
                    if not isinstance(operations, list):
                        raise ValueError("PUBLICATION_OPERATION_SNAPSHOT_INVALID")
                    retained["operations"] = [fields(operation, ("jurisdiction", "right_type", "operation",
                        "query_compiler_revision", "query_id", "plan_entry_sha256", "source_run_id",
                        "source_run_sha256")) for operation in operations]
        else:
            if not isinstance(snapshot.get("queries", []), list):
                raise ValueError("PUBLICATION_BROWSER_SNAPSHOT_INVALID")
            saved["queries"] = [fields(row, ("query_id", "plan_entry_sha256", "provider", "dispatch",
                "status", "error_code", "source_error_code", "phase", "submission_state",
                "partial_resume_attempts", "partial_resume_limit", *(('capture_path', 'capture_sha256', 'capture_status')
                    if evidence_delivery_enabled(task) else ())))
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


def _official_coverage_gap(entry):
    reason = str(entry.get("planning_gap") or entry.get("reason") or "")
    return ":AXIS_MISSING:" in reason or reason.endswith(":LOCAL_LANGUAGE_MISSING")


def _bounded_discovery_proofs(task, plan, evidence, candidates, ledger, *, supplement=None, task_dir=None):
    """Reuse exact, current source reviews; a free-form stop note proves nothing."""
    from api_first_planning import review_validation, source_files_error, reviewed_unknown_submission
    from workflow_v24 import necessary_scenario_row_bindings, validated_query_cancellation
    if task_dir is None:
        return {}
    result = {}
    for provider, rows in plan.get("queries", {}).items():
        for row in rows:
            if validated_query_cancellation(task, plan, row):
                continue
            runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
                and run.get("query_id") == row.get("query_id") and run.get("plan_entry_sha256") == sha256_json(row)]
            if not runs:
                continue
            run = runs[-1]
            if source_files_error(task_dir, evidence, run):
                continue
            reviews = [review for review in task.get("discovery_followups", []) if review.get("role") == "review"
                and review.get("parent_query_id") == row.get("query_id") and review.get("source_run_id") == run.get("run_id")]
            # The latest decision is authoritative for this input, not an older
            # bounded stop that was subsequently reopened.
            review = reviews[-1] if reviews else None
            unknown = reviewed_unknown_submission(task, plan, evidence, candidates, ledger, row, supplement, task_dir=task_dir)
            if row.get("action_purpose") != "discovery" and not unknown:
                continue
            expected_outcome = "stop_bounded_discovery" if run.get("status") in {"success", "no_result"} else "blocked"
            if (not review or review.get("outcome") != expected_outcome
                    or (run.get("submission_state") not in {"submitted", "not_submitted"} and not unknown)
                    or review_validation(task, plan, evidence, candidates, ledger, row, review, supplement)):
                continue
            proof = {"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                "review_sha256": sha256_json(review), "reasoning": review["reason"],
                "evidence_refs": list(review["evidence_ids"]),
                "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)}],
                **({"submission_review_refs": unknown} if unknown else {})}
            for scope in necessary_scenario_row_bindings(task, row):
                key = (scope["scenario_id"], row["jurisdiction"], row["right_type"])
                result.setdefault(key, []).append(proof)
    return result


def _figurative_na_proofs(task, plan, evidence, *, supplement=None, task_dir=None):
    """An empty, actually reviewed mark inventory can close a search-term todo."""
    from assessment_v24 import evidence_index, _entry_matches_run, _retained_artifacts_complete
    from record_asset_provenance import asset_scope, investigation_complete, INVESTIGATION_STEPS
    from runtime_v24 import source_files_complete
    from workflow_v24 import scenario_row_bindings
    from pathlib import Path
    if task_dir is None or task.get("specialty_workflow_revision") != "asset-scope-v1":
        return {}
    registry = evidence_index(evidence)
    registry.update({item["evidence_id"]: item for item in (supplement or {}).get("evidence", [])
        if isinstance(item, dict) and item.get("evidence_id")})
    result = {}
    runs = {run["run_id"]: run for run in evidence.get("source_runs", [])}
    for query in plan.get("queries", {}).get("asset_provenance", []):
        if query.get("right_type") != "trademark_figurative" or query.get("candidate_id"):
            continue
        bindings = scenario_row_bindings(task, query)
        if len(bindings) != 1:
            continue
        sid = bindings[0]["scenario_id"]
        inventory = asset_scope(task, sid, "trademark_figurative")
        if not inventory["inventory_reviewed"] or inventory["asset_ids"]:
            continue
        matches = [entry for entry in registry.values() if entry.get("query_id") == query.get("query_id")
            and entry.get("provider") == "asset_provenance" and entry.get("plan_entry_sha256") == sha256_json(query)]
        for entry in matches[-1:]:
            run = runs.get(entry.get("source_run_id"), {})
            payload = entry.get("payload", {})
            if (run.get("status") != "success" or not _entry_matches_run(entry, run)
                    or not source_files_complete(Path(task_dir), evidence, run)
                    or not _retained_artifacts_complete(payload)
                    or not investigation_complete(task, payload, query, sid, registry)):
                continue
            key = (sid, query["jurisdiction"], query["right_type"])
            result.setdefault(key, {})[query["search_dimension"]] = {
                "evidence_refs": [entry["evidence_id"], *inventory["review"]["evidence_refs"]],
                "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)}],
                "reasoning": inventory["review"]["reasoning"]}
    return {scope: list(steps.values()) for scope, steps in result.items()
        if set(INVESTIGATION_STEPS["trademark_figurative"]) <= set(steps)}


def _resolve_evidence_limits(task, view, plan, capabilities, evidence, candidates, ledger,
                             *, supplement=None, task_dir=None, coverage=None):
    """Resolve delivery only; never change official coverage or evidence authority."""
    bounded = _bounded_discovery_proofs(task, plan, evidence, candidates, ledger,
        supplement=supplement, task_dir=task_dir)
    absent_marks = _figurative_na_proofs(task, plan, evidence, supplement=supplement, task_dir=task_dir)
    from api_first_planning import reviewed_unknown_submission
    rows = {row["query_id"]: row for values in plan.get("queries", {}).values() for row in values}
    # Resolve the base workflow's duplicate unknown obligation using the same
    # exact review as the API projection. The underlying submission stays unknown.
    for entry in view["entries"]:
        if entry.get("state") != "submission_unknown" or entry.get("query_id") not in rows:
            continue
        audited = reviewed_unknown_submission(task, plan, evidence, candidates, ledger,
            rows[entry["query_id"]], supplement, task_dir=task_dir)
        if audited:
            reason = "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW"
            entry.update(state="blocked", kind="source_lookup", reason=reason, submission_state="unknown",
                delivery_limit={"kind": "source_constraint", "reason": reason, "official_verification": "not_verified",
                    "source_run_refs": [{"run_id": item["run_id"], "sha256": item["source_run_sha256"]} for item in audited],
                    "capability_refs": [], "submission_review_refs": audited})
    original = deepcopy(view["entries"])
    for entry in view["entries"]:
        proof = _route_absence_proof(task, entry, plan, capabilities, evidence, candidates, ledger, supplement=supplement)
        if proof:
            entry["delivery_limit"]["route_absence"] = proof
        # A reservation is unused capacity, not an exhausted source. It must be
        # allocated, legitimately cancelled, or replaced by a precise blocker.
        if entry.get("reason") == "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP":
            entry.update(state="ready", kind="plan_repair")
            continue
        if entry.get("reason") == "LANGUAGE_TERM_REPAIR_REQUIRED" and _scope(entry) not in absent_marks:
            continue
        scope = _scope(entry)
        no_mark = scope in absent_marks and (_official_coverage_gap(entry)
            or entry.get("reason") == "API_DISCOVERY_TERMS_MISSING")
        if not no_mark and not _official_coverage_gap(entry):
            continue
        proofs = absent_marks.get(scope) if no_mark else bounded.get(scope)
        if not proofs:
            continue
        # A reviewed web result is not permission to skip an authorized official
        # route. Resolve every compiled route for this exact axis against the
        # frozen capabilities or an actual retained attempt before stopping.
        routes_closed, route_proofs = _axis_route_limits(task, entry, plan, evidence, capabilities,
            original, task_dir=task_dir, candidates=candidates, ledger=ledger, supplement=supplement) if not no_mark else (True, [])
        if not routes_closed:
            entry.update(state="ready", kind="plan_repair", reason="AUTHORIZED_ALTERNATIVE_REQUIRES_PLANNING")
            continue
        # Ready investigations, missing terms, unreviewed cards, retained reads,
        # unknown submissions and reserved budgets cannot disappear behind an
        # official-coverage limitation. Their own exact obligations stay open.
        unfinished = [other for other in original if _scope(other) in {scope, (None, None, None)}
            and not _official_coverage_gap(other)
            and not (no_mark and other.get("reason") == "API_DISCOVERY_TERMS_MISSING")
            and (other.get("state") in {"ready", "awaiting_review", "submission_unknown"}
                 or other.get("reason") == "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP")]
        if unfinished:
            continue
        entry.setdefault("planning_gap", entry.get("reason"))
        entry.update(state="blocked", kind="scope_disposition" if no_mark else "retained_limitation",
            reason="REVIEWED_NO_APPLICABLE_FIGURATIVE_MARK" if no_mark else "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED",
            official_verification="not_applicable" if no_mark else "not_verified",
            reasoning=("已完成当前标识盘点及图像审阅；该范围没有已确认且适用的图形标。" if no_mark else
                "已审阅本范围留存的来源回执及已取得材料；所列官方检索维度仍未核验，失败或未知提交不代表无命中，保留为本轮证据报告的限制。"),
            evidence_refs=list(dict.fromkeys(ref for proof in proofs for ref in proof["evidence_refs"])),
            source_run_refs=list({proof["run_id"]: proof for item in proofs for proof in item["source_run_refs"]}.values()),
            resolution_refs=deepcopy(proofs), route_limit_refs=route_proofs)
    return view


def _axis_route_limits(task, entry, plan, evidence, capabilities, entries, *, task_dir=None,
                       candidates=None, ledger=None, supplement=None):
    """Bound alternatives by compiler, exact attempt and capability, never prose."""
    from pathlib import Path
    from runtime_v24 import source_files_complete
    from workflow_v24 import necessary_scenario_row_bindings
    gap = str(entry.get("planning_gap") or entry.get("reason") or "")
    requirement = next((row for row in task.get("coverage_requirements", [])
        if row.get("requirement_id") == gap.split(":", 1)[0]), None)
    if not requirement:
        return False, []
    axis = gap.split(":AXIS_MISSING:", 1)[1] if ":AXIS_MISSING:" in gap else "text"
    options = _route_options(task, requirement, axis)
    proofs = []
    scope_bound = _reviewed_browser_scope_limit(task, entry, plan, evidence, candidates, ledger,
        supplement=supplement, task_dir=task_dir)
    fields = ("provider", "state", "reason", "executable", "credentials_present", "checked_at", "cost_ceiling_usd")
    for option in options:
        provider = option["provider"]
        cap = capabilities.get(provider, {})
        attempts = []
        for row in plan.get("queries", {}).get(provider, []):
            if (row.get("search_dimension") != axis or requirement["requirement_id"] not in row.get("requirement_ids", [])
                    or (row.get("jurisdiction"), row.get("right_type")) != (entry.get("jurisdiction"), entry.get("right_type"))
                    or not any(binding["scenario_id"] == entry.get("scenario_id") for binding in necessary_scenario_row_bindings(task, row))):
                continue
            runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
                and run.get("query_id") == row["query_id"] and run.get("plan_entry_sha256") == sha256_json(row)]
            run = runs[-1] if runs else {}
            if (task_dir is not None and run.get("status") in {"success", "no_result"}
                    and source_files_complete(Path(task_dir), evidence, run)):
                attempts.append({"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                    "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)}]})
            elif any(other.get("query_id") == row["query_id"] and other.get("provider") == provider
                    and other.get("state") in {"awaiting_access", "blocked"}
                    and (other.get("reason") in _ACCESS_REASONS | _BLOCKED_REASONS
                         or _delivery_limit_valid(other, task, evidence, plan, capabilities,
                             candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)) for other in entries):
                attempts.append({"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                    "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)}] if run else []})
        if attempts:
            proofs.append({"provider": provider, "operation": option["operation"], "attempts": attempts})
        elif provider.endswith("browser") and scope_bound:
            proofs.append({"provider": provider, "operation": option["operation"], **deepcopy(scope_bound)})
        elif _route_state([option], capabilities)[0] != "ready":
            proofs.append({"provider": provider, "operation": option["operation"], "reason": cap.get("reason"),
                "capability_sha256": sha256_json({key: cap[key] for key in fields if key in cap})})
        else:
            return False, []
    return True, proofs


def _reviewed_browser_scope_limit(task, entry, plan, evidence, candidates, ledger, *, supplement=None, task_dir=None):
    """A scope budget is a delivery limit only after its real attempts are read.

    Use the planner's existing capacity and per-country/right policy. Planned
    reservations and duplicate/renamed rows do not prove performed work. An
    audited unknown submission may retain a slot, but is never a completed
    search or exhausted recovery; its reservation is disclosed separately.
    """
    from api_first_planning import _capacity_rows, policy_limit, dispatch_block, reviewed_unknown_submission
    from workflow_v24 import necessary_scenario_row_bindings, action_attempt_state, browser_submitted_failure_state
    from runtime_v24 import source_files_complete
    from pathlib import Path
    if task_dir is None or candidates is None or ledger is None:
        return None
    bound = policy_limit(task, "browser_fallback_queries_per_scope", 2)
    rows = [(provider, row) for provider, row in _capacity_rows(task, plan, evidence)
        if provider.endswith("browser") and row.get("discovery_role") == "browser_fallback"
        and (row.get("jurisdiction"), row.get("right_type")) == (entry.get("jurisdiction"), entry.get("right_type"))]
    if len(rows) != bound or len({row["query_id"] for _, row in rows}) != bound:
        return None
    reviewed = _bounded_discovery_proofs(task, plan, evidence, candidates, ledger,
        supplement=supplement, task_dir=task_dir).get(_scope(entry), [])
    attempts, unknown_slots = [], 0
    for provider, row in rows:
        if not any(scope["scenario_id"] == entry.get("scenario_id") for scope in necessary_scenario_row_bindings(task, row)):
            return None
        runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
            and run.get("query_id") == row["query_id"] and run.get("plan_entry_sha256") == sha256_json(row)]
        if not runs:
            return None
        proof = next((item for item in reviewed if item["query_id"] == row["query_id"]
            and item["plan_entry_sha256"] == sha256_json(row)), None)
        if not proof:
            return None
        block = dispatch_block(task, plan, evidence, candidates, ledger, provider, row, supplement)
        attempt = {"provider": provider, "discovery_intent_id": row.get("discovery_intent_id"), **deepcopy(proof)}
        if any(run.get("submission_state") not in {"submitted", "not_submitted"} for run in runs):
            audits = reviewed_unknown_submission(task, plan, evidence, candidates, ledger, row, supplement, task_dir=task_dir)
            if not audits or block not in {None, "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY"}:
                return None
            attempt["submission_reservation"] = {"reason": "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW",
                "submission_review_refs": audits, "completed_search": False,
                "reasoning": "原回执已核对但提交仍未知；原名额必须保留且禁止重发，不代表检索完成或实际调用耗尽。"}
            unknown_slots += 1
        else:
            if block or runs[-1].get("submission_state") != "submitted":
                return None
            if runs[-1].get("status") not in {"success", "no_result"}:
                recovery = browser_submitted_failure_state(task, evidence, provider, row)
                if (action_attempt_state(evidence, provider, row)["state"] != "submitted" or not recovery
                        or recovery.get("state") != "blocked" or recovery.get("reason") != "BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED"
                        or recovery.get("remaining_attempts") != 0):
                    return None
                recovered_ids = {ref["run_id"] for ref in recovery["source_run_refs"]}
                if any(not source_files_complete(Path(task_dir), evidence, run) for run in runs if run["run_id"] in recovered_ids):
                    return None
                attempt["recovery_limit"] = deepcopy(recovery)
        attempts.append(attempt)
    return {"reason": "API_DISCOVERY_BROWSER_SCOPE_RESERVED_FOR_UNKNOWN_SUBMISSION" if unknown_slots else "API_DISCOVERY_BROWSER_SCOPE_LIMIT", "limit": bound,
        **({"unknown_reserved_slots": unknown_slots, "known_attempt_slots": len(attempts) - unknown_slots} if unknown_slots else {}),
        "policy_sha256": sha256_json(task.get("retrieval_policy")), "attempts": attempts,
        "official_verification": "not_verified"}


def refine_work_view(task, view, plan, capabilities, *, evidence=None, candidates=None,
                     ledger=None, supplement=None, task_dir=None, coverage=None):
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
        from completion_policy import evidence_delivery_enabled
        if evidence_delivery_enabled(task) and reason.endswith(":LOCAL_LANGUAGE_MISSING"):
            from workflow_v24 import LANGUAGES
            language = LANGUAGES.get(entry.get("jurisdiction"), "")
            linked = _planned_language_queries(task, entry, plan, evidence or {}, candidates or {}, ledger or {}, supplement=supplement)
            entry.update(planning_gap=reason, required_language=language)
            if linked:
                entry.update(state="blocked", kind="coverage_information", reason="LOCAL_LANGUAGE_BOUND_TO_PLANNED_QUERY",
                    query_refs=linked, official_verification="not_verified",
                    reasoning="目标语言已绑定所列实际编译查询；查询执行与审阅由对应工作项跟踪，官方覆盖尚未核验。")
            else:
                entry.update(state="ready", kind="plan_repair", reason="LANGUAGE_TERM_REPAIR_REQUIRED",
                    source_terms=[{key: term.get(key) for key in ("kind", "value", "language", "derived_from")}
                        for term in plan.get("terms", []) if term.get("kind") not in {"nice", "cpc", "ipc", "locarno", "owner"}],
                    reasoning="缺少该范围的目标语言文本查询；使用现有目标语言词或补有来源的翻译/描述词重新编译，不能填写覆盖完成。")
            continue
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
    from completion_policy import evidence_delivery_enabled
    if evidence_delivery_enabled(task) and all(value is not None for value in (evidence, candidates, ledger)):
        view = _resolve_evidence_limits(task, view, plan, capabilities, evidence, candidates, ledger,
            supplement=supplement, task_dir=task_dir, coverage=coverage)
    view["counts"] = {state: sum(item["state"] == state for item in view["entries"])
        for state in ("ready", "awaiting_review", "awaiting_access", "awaiting_user", "submission_unknown", "blocked")}
    view["status"] = "incomplete" if view["entries"] or view.get("unresolved_scopes") else "complete"
    return view


def _planned_language_queries(task, entry, plan, evidence, candidates, ledger, *, supplement=None):
    """Language belongs to executable text/description rows, not coverage credit."""
    from workflow_v24 import LANGUAGES, necessary_scenario_row_bindings, validated_query_cancellation
    from api_first_planning import dispatch_block
    required = LANGUAGES.get(entry.get("jurisdiction"), "")
    requirement_id = str(entry.get("planning_gap") or entry.get("reason") or "").split(":", 1)[0]
    result = []
    for provider, rows in plan.get("queries", {}).items():
        for row in rows:
            if (validated_query_cancellation(task, plan, row) or row.get("search_dimension") not in {"text", "description", "phonetic"}
                    or not required or str(row.get("search_language") or "").casefold() != required
                    or (row.get("jurisdiction"), row.get("right_type")) != (entry.get("jurisdiction"), entry.get("right_type"))
                    or requirement_id not in row.get("requirement_ids", [])
                    or not any(scope["scenario_id"] == entry.get("scenario_id") for scope in necessary_scenario_row_bindings(task, row))):
                continue
            if dispatch_block(task, plan, evidence, candidates, ledger, provider, row, supplement) not in {
                    None, "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY", "API_DISCOVERY_BUDGET_EXHAUSTED",
                    "API_DISCOVERY_MERGE_REQUIRED", "API_DISCOVERY_TRIAGE_REQUIRED", "API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED"}:
                continue
            if provider.endswith("browser"):
                from record_browser_execution import planned_browser_query
                try:
                    planned_browser_query(provider, row, task)
                except (ValueError, TypeError, KeyError):
                    continue
            result.append({"provider": provider, "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                "search_language": required, "search_dimension": row["search_dimension"]})
    return result


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


def _delivery_limit_valid(entry, task, evidence, plan, capabilities, *, candidates=None, ledger=None,
                          supplement=None, task_dir=None):
    """Validate source constraints emitted by the shared planner, not stop prose."""
    proof = entry.get("delivery_limit")
    if (not isinstance(proof, dict) or proof.get("kind") != "source_constraint"
            or proof.get("reason") != entry.get("reason")
            or proof.get("official_verification") != "not_verified"):
        return False
    reason = str(entry.get("reason") or "")
    if (reason == "API_DISCOVERY_BUDGET_RESERVED_FOR_FOLLOWUP"
            or any(marker in reason for marker in ("INVALID", "MISMATCH", "STALE", "TAMPER", "SYNTAX",
                "UNSUPPORTED_QUERY", "CLOUD_AUTH", "AUTH_GATE", "GUARD", "TERMS_MISSING"))):
        return False
    run_refs, cap_refs = proof.get("source_run_refs", []), proof.get("capability_refs", [])
    if not isinstance(run_refs, list) or not isinstance(cap_refs, list):
        return False
    route_absence = _route_absence_proof(task, entry, plan, capabilities, evidence, candidates or {}, ledger or {}, supplement=supplement)
    if not (run_refs or cap_refs) and (not route_absence or proof.get("route_absence") != route_absence):
        return False
    runs = {run["run_id"]: run for run in evidence.get("source_runs", [])}
    unknown = None
    if reason == "SUBMISSION_UNKNOWN_AFTER_RECEIPT_REVIEW":
        from api_first_planning import reviewed_unknown_submission
        rows = [row for values in plan.get("queries", {}).values() for row in values if row.get("query_id") == entry.get("query_id")]
        if task_dir is None or candidates is None or ledger is None or len(rows) != 1:
            return False
        unknown = reviewed_unknown_submission(task, plan, evidence, candidates, ledger, rows[0], supplement, task_dir=task_dir)
        if not unknown or proof.get("submission_review_refs") != unknown:
            return False
        if run_refs != [{"run_id": item["run_id"], "sha256": item["source_run_sha256"]} for item in unknown]:
            return False
    from api_first_planning import account_stop_reason, _account
    stopped_providers = ({entry.get("provider")} | {ref.get("provider") for ref in cap_refs if isinstance(ref, dict)}
        | {ref.get("provider") for ref in entry.get("source_constraints", []) if isinstance(ref, dict)})
    stopped_accounts = {_account(provider) for provider in stopped_providers if provider
        and reason == "API_DISCOVERY_ACCOUNT_STOPPED" and account_stop_reason(provider, evidence)}
    for ref in run_refs:
        run = runs.get(ref.get("run_id"), {}) if isinstance(ref, dict) else {}
        if (not run or ref.get("sha256") != sha256_json(run)
                or ((run.get("jurisdiction"), run.get("right_type")) != (entry.get("jurisdiction"), entry.get("right_type"))
                    and _account(run.get("provider", "")) not in stopped_accounts)
                or (run.get("submission_state") not in {"submitted", "not_submitted"} and not unknown)):
            return False
    fields = ("provider", "state", "reason", "executable", "credentials_present", "checked_at", "cost_ceiling_usd")
    for ref in cap_refs:
        cap = capabilities.get(ref.get("provider"), {}) if isinstance(ref, dict) else {}
        if not cap or ref.get("sha256") != sha256_json({key: cap[key] for key in fields if key in cap}):
            return False
    gap_digest = proof.get("planning_gap_sha256")
    if gap_digest:
        from api_first_planning import gap_limit_still_current
        gaps = [gap for gap in plan.get("planning_gaps", []) if sha256_json(gap) == gap_digest
            and (gap.get("jurisdiction"), gap.get("right_type")) == (entry.get("jurisdiction"), entry.get("right_type"))]
        if len(gaps) != 1 or not gap_limit_still_current(task, plan, evidence, candidates or {}, ledger or {},
                gaps[0], capabilities, supplement):
            return False
    return bool(gap_digest or run_refs)


def _route_absence_proof(task, entry, plan, capabilities, evidence, candidates, ledger, *, supplement=None):
    """Prove an empty qualified route set from the frozen plan and real snapshot."""
    from api_first_planning import (_planning_gap_term, _gap_providers, gap_limit_still_current,
        intent_id, dimension)
    proof = entry.get("delivery_limit", {})
    if (entry.get("reason") != "API_DISCOVERY_ROUTE_UNAVAILABLE" or not capabilities
            or not isinstance(proof, dict) or proof.get("source_run_refs") or proof.get("capability_refs")):
        return None
    gaps = [gap for gap in plan.get("planning_gaps", []) if sha256_json(gap) == proof.get("planning_gap_sha256")]
    if len(gaps) != 1:
        return None
    gap = gaps[0]
    country, right = entry.get("jurisdiction"), entry.get("right_type")
    term = _planning_gap_term(task, plan, gap)
    requirements = [row for row in task.get("coverage_requirements", []) if
        (row.get("jurisdiction"), row.get("right_type")) == (country, right) and row.get("phase") in {"official_recall", "provenance"}]
    if (not term or not requirements or (gap.get("jurisdiction"), gap.get("right_type")) != (country, right)
            or gap.get("code") != entry["reason"]
            or set(gap.get("requirement_ids", [])) != {row["requirement_id"] for row in requirements}
            or gap.get("discovery_intent_id") != intent_id(country, right, dimension(term), term)
            or _gap_providers(task, gap, term, capabilities)
            or not gap_limit_still_current(task, plan, evidence, candidates, ledger, gap, capabilities, supplement)):
        return None
    policy = {key: task.get(key) for key in ("retrieval_policy", "serper_free_enhancement", "serpapi_free_enhancement", "signa_free_enhancement")}
    if any(plan.get(key) != value for key, value in policy.items()):
        return None
    return {"kind": "no_qualified_route", "planning_gap_sha256": sha256_json(gap), "term_sha256": sha256_json(term),
        "requirements_sha256": sha256_json(requirements), "policy_sha256": sha256_json(policy),
        "source_capabilities_sha256": sha256_json(capabilities), "qualified_providers": [], "official_verification": "not_verified"}


def _reviewed_fact_limitations(assessment, evidence, *, evidence_root=None, task=None):
    """Completed investigation may leave a reviewed fact unknown, without a retry."""
    from assessment_estimate import evidence_index, validate_supplement, _substantive_refs
    registry = {**evidence_index(evidence), **validate_supplement(assessment.get("supplement"),
        evidence_root, task=task, evidence=evidence)}
    runs = {run["run_id"]: run for run in evidence.get("source_runs", [])}
    result = []
    for row in assessment.get("assessments", []):
        if row.get("assessment_status") != "pending" or not row.get("pending_reasoning"):
            continue
        refs = _substantive_refs(row.get("evidence_refs", []), registry, runs, row=row)
        if not refs:
            continue
        identity = {key: row.get(key) for key in ("scenario_id", "jurisdiction", "right_type", "candidate_id")}
        result.append({**identity, "work_id": "LIMIT-" + sha256_json(identity)[:24],
            "kind": "reviewed_fact_limit", "reason": "REVIEWED_FACT_REMAINS_UNCONFIRMED", "state": "blocked",
            "official_verification": "not_verified", "reasoning": row["pending_reasoning"],
            "evidence_refs": sorted(refs), "source_run_refs": [{"run_id": rid, "sha256": sha256_json(runs[rid])}
                for rid in sorted({registry[ref].get("source_run_id") for ref in refs} - {None}) if rid in runs]})
    return result


def _partial_technical_limit(entry, evidence, plan, snapshots, *, task_dir=None):
    """Read-only report exception for a recorded query failure, never dispatch permission.

    Bare unexecuted plans, credential checks, unreviewed material and corrupt
    inputs cannot establish a technical limitation. Original work state and
    source submission facts are retained verbatim.
    """
    codes = {"INTERNAL_ROUTE_CONTRACT_ERROR", "NODE_UNAVAILABLE",
        "UNSUPPORTED_QUERY_SEMANTICS", "USPTO_QUERY_REJECTED",
        "API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED", "BROWSER_QUERY_CONTRACT_ERROR"}
    from assessment_v24 import NON_PRODUCTION
    def nonproduction(value):
        if isinstance(value, dict):
            return (any(str(value.get(key) or "").casefold() in
                        NON_PRODUCTION | {"offline", "unit_test_only"}
                        for key in ("source_environment", "environment", "kind"))
                    or any(value.get(key) for key in ("fixture", "fixture_only", "test_only", "mock"))
                    or any(nonproduction(item) for item in value.values()))
        return isinstance(value, list) and any(nonproduction(item) for item in value)
    def unread_material(value):
        if isinstance(value, dict):
            material = {"candidates", "records", "results", "documents", "artifacts", "attachments",
                "claims", "full_text", "text", "html", "body", "pages", "images", "items", "protected_views"}
            return (any(value.get(key) for key in material)
                    or any(unread_material(item) for item in value.values()))
        return isinstance(value, list) and any(unread_material(item) for item in value)
    if (entry.get("kind") not in {"source_lookup", "plan_repair"}
            or entry.get("state") not in {"ready", "blocked", "awaiting_access"}
            or entry.get("reason") not in codes or entry.get("integrity_failure")):
        return None
    provider, query_id = entry.get("provider"), entry.get("query_id")
    matches = [row for row in plan.get("queries", {}).get(provider, [])
        if query_id and row.get("query_id") == query_id]
    if len(matches) != 1:
        return None
    row = matches[0]
    digest = sha256_json(row)
    if any(entry.get(key) != row.get(key) for key in ("jurisdiction", "right_type")):
        return None
    runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
        and run.get("query_id") == query_id and run.get("plan_entry_sha256") == digest]
    from assessment_v24 import evidence_index
    linked = [item for item in evidence_index(evidence).values()
              if item.get("source_run_id") in {run.get("run_id") for run in runs}]
    # Failed returns may still carry usable material. Do not let an error-only
    # exception skip its existing merge/read/review path, even after a later failure.
    if any(nonproduction(value) for value in [*runs, *linked]):
        return None
    if any(unread_material(value) for value in [*runs, *linked]):
        return None
    facts = []
    if runs:
        latest = runs[-1]
        if (latest.get("status") in {"failed", "access_limited"}
                and latest.get("error_code") == entry["reason"]
                and latest.get("submission_state") in {"submitted", "not_submitted"}):
            facts.append({"kind": "source_run", "run_id": latest["run_id"], "sha256": sha256_json(latest)})
        else:
            return None
    current = [record for record in snapshots.get("browser-execution-status.json", {}).get("queries", [])
        if record.get("provider") == provider and record.get("query_id") == query_id
        and record.get("plan_entry_sha256") == digest]
    if current:
        latest = current[-1]
        if nonproduction(latest) or unread_material(latest):
            return None
        if (latest.get("status") in {"failed", "access_limited"}
                and latest.get("error_code") == entry["reason"]
                and latest.get("submission_state") == "not_submitted"
                and latest.get("capture_status") not in {"success", "no_result"}):
            # A scalar scheduler snapshot alone is not a retained failure receipt.
            # Read only the already captured local artifact; never create a capture.
            from pathlib import Path
            from common import load_json, path_within, sha256_file
            if not task_dir or not latest.get("capture_path") or not latest.get("capture_sha256"):
                return None
            root = Path(task_dir).resolve()
            capture_path = Path(latest["capture_path"])
            capture_path = (root / capture_path).resolve() if not capture_path.is_absolute() else capture_path.resolve()
            try:
                if (not path_within(capture_path, root) or not capture_path.is_file()
                        or sha256_file(capture_path) != latest["capture_sha256"]):
                    return None
                capture = load_json(capture_path)
            except (OSError, ValueError):
                return None
            if (not isinstance(capture, dict) or nonproduction(capture) or unread_material(capture)
                    or any(capture.get(key) != latest.get(key)
                           for key in ("status", "error_code", "submission_state"))
                    or any(key in capture and capture[key] != expected
                           for key, expected in (("query_id", query_id), ("provider", provider),
                                                 ("plan_entry_sha256", digest)))):
                return None
            facts.append({"kind": "browser_execution_record", "sha256": sha256_json(latest),
                          "capture_sha256": latest["capture_sha256"]})
        else:
            return None
    if not facts:
        return None
    return {**deepcopy(entry), "limitation_kind": "internal_technical_failure",
        "official_verification": "not_verified", "plan_entry_sha256": digest,
        "failure_records": facts,
        "reasoning": "本项已有绑定该查询的内部技术错误记录，查询未完成；仅允许交付不完整报告，"
                     "不改变原待办、恢复规则、提交状态或来源调用权限。"}


def publication_context(task, evidence, candidates, plan, ledger, assessment, *,
                        mode=None, stop_reason=None, snapshots=None, task_dir=None, evidence_root=None):
    """Recompute a publication decision using only frozen, non-secret inputs."""
    if not enabled(task):
        if mode is not None or stop_reason is not None:
            raise ValueError("COMPLETION_POLICY_REQUIRED_FOR_PUBLICATION_MODE")
        return None
    from workflow_v24 import derive_work_view
    from completion_policy import evidence_delivery_enabled
    delivery = evidence_delivery_enabled(task)
    mode = mode or ("auto" if delivery else "final")
    if mode not in ({"auto", "final", "evidence", "stage"} if delivery else {"final", "stage"}):
        raise ValueError("PUBLICATION_MODE_INVALID")
    raw_snapshots = snapshots if snapshots is not None else {}
    snapshots = sanitize_snapshots(task, raw_snapshots)
    source_digests = {name: sha256_json(value) for name, value in raw_snapshots.items()}
    caps = capability_map(task, snapshots.get("source-capabilities.json"))
    if delivery:
        from runtime_v24 import resolved_capabilities
        caps = resolved_capabilities(task, evidence, plan, caps, task_dir,
            browser_status=snapshots.get("browser-execution-status.json"))
        snapshots["source-capabilities.json"] = {"schema_version": task["schema_version"],
            "task_id": task["task_id"], "sources": list(caps.values())}
        snapshots = sanitize_snapshots(task, snapshots)
    scopes = assessment["coverage"]["scopes"]
    supplement = assessment.get("supplement")
    reviews = assessment["review"]["input_reviews"]
    if delivery:
        from workflow_v24 import resolved_work_view
        view = resolved_work_view(task, evidence, candidates, plan, ledger, supplement=supplement,
            evidence_root=evidence_root, task_dir=task_dir, coverage=scopes,
            browser_status=snapshots.get("browser-execution-status.json"), source_capabilities=caps)
    else:
        view = derive_work_view(task, evidence, candidates, plan, ledger, supplement=supplement,
            evidence_root=evidence_root, task_dir=task_dir, coverage=scopes,
            browser_status=snapshots.get("browser-execution-status.json"), source_capabilities=caps)
        view = refine_work_view(task, view, plan, caps)
    from workflow_v24 import plan_row_index
    plan_index = plan_row_index(plan)
    for entry in ([] if delivery else view["entries"]):
        matches = plan_index.get(entry.get("query_id"), [])
        if len(matches) == 1:
            provider, row = matches[0]
            linked = [{"run_id": run["run_id"], "sha256": sha256_json(run)}
                for run in evidence.get("source_runs", []) if run.get("query_id") == row["query_id"]
                and run.get("provider") == provider and run.get("plan_entry_sha256") == sha256_json(row)]
            entry["source_run_refs"] = list({item["run_id"]: item for item in
                [*entry.get("source_run_refs", []), *linked]}.values()) if delivery else linked
        if entry.get("provider") in caps:
            entry["capability_sha256"] = sha256_json(caps[entry["provider"]])
    review = review_work(task, evidence, candidates, plan, ledger, scopes, reviews["first"], reviews.get("second"),
        supplement=supplement, evidence_root=evidence_root)
    if review["entries"]:
        raise ValueError("PUBLICATION_SCOPE_REVIEW_REQUIRED: " + ",".join(r["work_id"] for r in review["entries"]))
    if mode == "auto":
        mode = "final" if (assessment["status"] == "completed" and view["status"] == "complete"
            and not view["entries"]) else "evidence"
    limitations = []
    if mode == "final":
        if assessment["status"] != "completed" or view["status"] != "complete" or view["entries"]:
            raise ValueError("PUBLICATION_NECESSARY_WORK_INCOMPLETE")
        if stop_reason:
            raise ValueError("FINAL_PUBLICATION_CANNOT_HAVE_STOP_REASON")
    elif mode == "evidence":
        if assessment["status"] == "completed":
            raise ValueError("COMPLETED_ASSESSMENT_REQUIRES_FINAL_PUBLICATION")
        from assessment_estimate import partial_evidence_enabled
        technical = {}
        if partial_evidence_enabled(task):
            for entry in view["entries"]:
                if entry.get("integrity_failure"):
                    raise ValueError("EVIDENCE_INPUT_INTEGRITY_FAILURE: " + entry["work_id"])
                limitation = _partial_technical_limit(entry, evidence, plan, snapshots, task_dir=task_dir)
                if limitation:
                    technical[entry["work_id"]] = limitation
        actionable = [r for r in view["entries"] if r["state"] in {"ready", "awaiting_review", "submission_unknown"}
                      and r["work_id"] not in technical]
        if actionable:
            raise ValueError("EVIDENCE_AGENT_WORK_REMAINS: " + ",".join(r["work_id"] for r in actionable))
        permitted = _ACCESS_REASONS | _BLOCKED_REASONS | {
            "BOUNDED_DISCOVERY_OFFICIAL_COVERAGE_UNVERIFIED", "REVIEWED_NO_APPLICABLE_FIGURATIVE_MARK", "LOCAL_LANGUAGE_BOUND_TO_PLANNED_QUERY"}
        for entry in view["entries"]:
            if entry["work_id"] in technical:
                limitations.append(technical[entry["work_id"]])
                continue
            external = entry["state"] == "awaiting_user" and entry.get("kind") in {"user_evidence", "user_information"}
            constrained = entry["state"] in {"awaiting_access", "blocked"} and entry.get("reason") in permitted
            structured = entry["state"] in {"awaiting_access", "blocked"} and _delivery_limit_valid(entry, task, evidence, plan, caps,
                candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)
            if not external and not constrained and not structured:
                raise ValueError("EVIDENCE_LIMITATION_NOT_ESTABLISHED: " + entry["work_id"])
            limitations.append({**deepcopy(entry), "official_verification": entry.get("official_verification", "not_verified"),
                "reasoning": entry.get("reasoning") or "本项受所列来源或资料条件限制，未经过官方核验；具体来源和剩余事实随本报告保留。"})
        # These are disclosed assessment facts, not a second execution queue.
        # All executable/review work has already been rejected above.
        limitations.extend(_reviewed_fact_limitations(assessment, evidence, evidence_root=evidence_root, task=task))
        limited_scopes = {_scope(entry) for entry in limitations}
        if any(_scope(scope) not in limited_scopes for scope in view.get("unresolved_scopes", [])):
            raise ValueError("EVIDENCE_UNRESOLVED_SCOPE_WITHOUT_LIMITATION")
        for scenario in assessment.get("scenario_summaries", []):
            queues = scenario["completion"].get("queues", {})
            pending = {(*_scope(row), row.get("candidate_id")) for row in queues.get("pending_assessments", [])}
            if queues.get("scope_unassessed") or any((*_scope(row), row.get("candidate_id")) not in pending
                    for row in queues.get("selected_unassessed", [])):
                raise ValueError("EVIDENCE_REVIEW_WORK_REMAINS")
            if any(_scope(row) not in limited_scopes for row in queues.get("pending_assessments", [])):
                raise ValueError("EVIDENCE_PENDING_ASSESSMENT_WITHOUT_LIMITATION")
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
    return {"revision": task["completion_policy_revision"], "mode": mode, "stop_reason": stop_reason.strip() if stop_reason else None,
        "evidence_digest": review["evidence_digest"], "work_view_sha256": sha256_json(view),
        "remaining_work": view["entries"], "review_work_sha256": sha256_json(review),
        "snapshots": snapshots, "snapshot_digests": {name: sha256_json(value) for name, value in snapshots.items()},
        "snapshot_source_digests": source_digests,
        **({"delivery_status": "partial" if mode == "stage" else "ready",
            "delivery_basis": "source_evidence" if mode == "evidence" else "interim" if mode == "stage" else "necessary_work_completed",
            "limitations": limitations} if delivery else {})}


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

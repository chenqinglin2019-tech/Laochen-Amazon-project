"""Read-only query completion from current obligations and retained/read receipts.

Administrative acceptance history, coverage and legal judgment stay separate.
Every projection revalidates source files; it never fabricates completion events.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from common import load_json, sha256_json

REVISION = "actual-query-execution-progress-v1"


def _scope_current(task, item, plan):
    from review_progress_stage_a import _version, _validate_rebind
    version = item["scope"]["product_version"]
    if version == _version(task):
        return True
    # Legacy first items used the target hash, while scope changes started at 2.
    # Only the first unchanged-target scope change can bridge that bootstrap.
    probe = deepcopy(item)
    history = task.get("product_change_history", [])
    if (len(history) == 1 and str(history[0].get("version")) == "2"
            and history[0].get("kind") == "scope_change"
            and version == task.get("product_identity", {}).get("sha256")
            and history[0].get("target_sha256") == version):
        probe["scope"]["product_version"] = "1"
    for change in history:
        try:
            _validate_rebind(task, {}, probe, plan, change.get("change_id"))
            return True
        except ValueError:
            continue
    return False


def _receipt(task, evidence, query, item, run, root, candidates, materiality):
    from recovery_stage_b import effective_result, effective_submission
    from review_progress_stage_a import _local_asset_review_complete
    from runtime_v24 import physical_response_source, source_files_complete
    from source_result_processing import progress, zero_result_proven
    if root is None:
        return False, "SOURCE_ROOT_UNAVAILABLE", None
    if run.get("provider") == "asset_provenance":
        complete = _local_asset_review_complete(task, evidence, query, item, run, root)
        return complete, "LOCAL_INVESTIGATION_REVALIDATED" if complete else "LOCAL_INVESTIGATION_INCOMPLETE", None
    status = effective_result(evidence, run)
    submitted = effective_submission(evidence, run)
    if status not in {"success", "no_result"}:
        return False, "SOURCE_RESULT_" + str(status).upper(), None
    if submitted != "submitted" and physical_response_source(root, evidence, run) is None:
        return False, "SOURCE_SUBMISSION_NOT_CONFIRMED", None
    if not source_files_complete(root, evidence, run):
        return False, "SOURCE_ORIGINAL_INVALID", None
    projected = {**run, "status": status, "submission_state": submitted}
    if status == "no_result" and not zero_result_proven(projected, evidence, root):
        return False, "ZERO_RESULT_UNVERIFIED", None
    if isinstance(run.get("result_processing"), dict):
        processing = progress(root, run, evidence)
        complete = (processing.get("material_processing_complete") is True
                    and not processing.get("receipt_disposition"))
        return complete, "RETAINED_RESPONSE_FULLY_READ" if complete else "RESULT_READING_INCOMPLETE", processing
    # Older discovery responses need current, source-bound card dispositions.
    if query.get("action_purpose") == "discovery":
        from api_first_planning import source_card_state, source_files_error
        from workflow_v24 import scenario_supplement
        error = source_files_error(root, evidence, run)
        if error:
            return False, error, None
        supplement = scenario_supplement(root, task=task, evidence=evidence)
        error, _ = source_card_state(task, evidence, candidates, materiality, query,
                                    projected, supplement)
        return error is None, error or "SOURCE_CARDS_REVIEWED", None
    return status == "no_result", "VERIFIED_ZERO_RESPONSE" if status == "no_result" else "RESULT_READING_PROOF_MISSING", None


def build(task, evidence, plan, *, task_dir=None, view=None, candidates=None, materiality=None):
    """Count each current unique query once, including failures and unread work."""
    from review_progress_stage_a import ledger, _plan_rows, _version
    administrative = ledger(task, evidence)
    root = Path(task_dir) if task_dir is not None else None
    if root is not None:
        if candidates is None and (root / "normalized-candidates.json").is_file():
            candidates = load_json(root / "normalized-candidates.json")
        if materiality is None:
            from annotate_materiality import load_materiality_ledger
            materiality = load_materiality_ledger(root, task["task_id"])
    rows = _plan_rows(plan)
    grouped, excluded = {}, []
    for item in administrative.get("items", []):
        if item.get("kind") != "query":
            continue
        provider, query = rows.get(item["query_id"], (None, None))
        if item["state"] not in {"planned", "completed"} or query is None or provider != item["provider"] or sha256_json(query) != item["plan_entry_sha256"]:
            excluded.append({"item_id": item["item_id"], "query_id": item["query_id"],
                             "reason": item["state"] if item["state"] in {"removed", "exempt"} else "historical_plan"})
            continue
        key = (provider, item["query_id"], item["plan_entry_sha256"])
        grouped.setdefault(key, []).append(item)
    # An executable current query awaiting plan registration remains unfinished.
    # Never silently turn missing registration into a smaller denominator.
    for entry in (view or {}).get("entries", []):
        provider, query = rows.get(entry.get("query_id"), (None, None))
        if query is None or entry.get("kind") not in {"source_lookup", "agent_investigation"}:
            continue
        if any(key[:3] == (provider, query["query_id"], sha256_json(query)) for key in grouped):
            continue
        bindings = query.get("scenario_bindings") or [{"scenario_id": query.get("scenario_id", "product_entry")}]
        for binding in bindings:
            scope = {"scenario_id": binding["scenario_id"], "jurisdiction": query["jurisdiction"],
                     "right_type": query["right_type"], "product_version": _version(task)}
            item = {"item_id": "unregistered:" + query["query_id"], "kind": "query", "query_id": query["query_id"],
                    "provider": provider, "plan_entry_sha256": sha256_json(query), "scope": scope,
                    "state": "planned", "unregistered": True}
            grouped.setdefault((provider, query["query_id"], sha256_json(query)), []).append(item)
    items = []
    for key, duplicates in sorted(grouped.items()):
        # Current version takes precedence; stale administrative copies do not
        # count again and cannot replace a reopened current obligation.
        duplicates.sort(key=lambda row: (row["scope"]["product_version"] == _version(task), row.get("created_in_version", 0)), reverse=True)
        scoped = {}
        for duplicate in duplicates:
            scope_key = tuple(duplicate["scope"][k] for k in ("scenario_id", "jurisdiction", "right_type"))
            if scope_key in scoped:
                excluded.append({"item_id": duplicate["item_id"], "query_id": duplicate["query_id"], "reason": "duplicate_obligation"})
            else:
                scoped[scope_key] = duplicate
        item = next(iter(scoped.values()))
        provider, query = rows[item["query_id"]]
        runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider
                and run.get("query_id") == item["query_id"] and run.get("plan_entry_sha256") == item["plan_entry_sha256"]]
        complete, basis, processing = False, "NO_BOUND_RUN", None
        run = runs[-1] if runs else None
        if item.get("unregistered"):
            basis = "QUERY_NOT_REGISTERED_BEFORE_EXECUTION"
        elif not all(_scope_current(task, scoped_item, plan) for scoped_item in scoped.values()):
            basis = "PRODUCT_SCOPE_REVIEW_REQUIRED"
        elif run and any(scoped_item.get("reopen_reason") and
                        any(completion.get("source_run_id") == run.get("run_id")
                            for completion in scoped_item.get("completion_history", []))
                        for scoped_item in scoped.values()):
            basis = "QUERY_REOPENED_REVALIDATION_REQUIRED"
        elif run:
            try:
                outcomes = [_receipt(task, evidence, query, scoped_item, run, root, candidates or {}, materiality or {})
                            for scoped_item in scoped.values()]
                complete = all(outcome[0] for outcome in outcomes)
                _, basis, processing = next((outcome for outcome in outcomes if not outcome[0]), outcomes[0])
            except (ValueError, OSError, KeyError, TypeError) as error:
                basis = "RECEIPT_VALIDATION_FAILED:" + str(error)
        items.append({"item_id": item["item_id"], "query_id": item["query_id"], "provider": provider,
            "scope": deepcopy(item["scope"]), "right_type": query["right_type"],
            "scopes": [deepcopy(scoped_item["scope"]) for scoped_item in scoped.values()],
            "plan_entry_sha256": item["plan_entry_sha256"], "query": query.get("q", ""),
            "search_dimension": query.get("search_dimension", ""), "completed": complete,
            "status": "completed" if complete else "incomplete", "basis": basis,
            "formal_accepted": item["state"] == "completed", "attempt_count": len(runs),
            "source_run_id": run.get("run_id") if run else None,
            "source_run_sha256": sha256_json(run) if run else None,
            "material_processing": processing,
            "coverage_boundary": "仅为冻结查询范围和已取得材料；未取得分页与法律事实缺口另列。"})
    total, completed = len(items), sum(item["completed"] for item in items)
    scopes = sorted({tuple(scope[k] for k in ("scenario_id", "jurisdiction", "right_type")) for item in items for scope in item["scopes"]})
    by_scope = []
    for scope in scopes:
        selected = [item for item in items if any(tuple(bound[k] for k in ("scenario_id", "jurisdiction", "right_type")) == scope for bound in item["scopes"])]
        by_scope.append({**dict(zip(("scenario_id", "jurisdiction", "right_type"), scope)),
                         "planned_total": len(selected), "completed_total": sum(item["completed"] for item in selected)})
    return {"revision": REVISION, "planned_total": total if administrative.get("status") != "plan_required" else None,
        "completed_total": completed, "completion_percent": round(100 * completed / total, 1) if total and administrative.get("status") != "plan_required" else None,
        "status": "plan_required" if administrative.get("status") == "plan_required" else "defined" if total else "no_active_queries",
        "items": items, "by_scope": by_scope, "excluded_items": excluded,
        "formal_acceptance_ledger": {key: administrative.get(key) for key in ("completed", "planned", "percentage")},
        "counting_basis": "current_unique_query_obligations_and_revalidated_retained_read_receipts",
        # Publication writes outputs/state/history; those are not query facts
        # and must not change canonical assessment on a second projection.
        "source_fingerprints": {"task": sha256_json({key: task.get(key) for key in
            ("task_id", "product", "product_identity", "product_scope", "product_change_version",
             "product_change_history", "product_feedback_history", "product_structure_policy",
             "target_jurisdictions", "assessment_scenarios", "primary_scenario_id")}),
            "evidence": sha256_json(evidence), "plan": sha256_json(plan)},
        "note": "查询完成率独立于覆盖、风险判定和报告双审；重试及历史重复不重复计数，失败与未读完继续计入未完成。"}

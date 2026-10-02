"""09A: versioned unique-work plan and evidence-bound C/N projection."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from common import atomic_write_json, load_json, now_iso, sha256_json

REVISION = "review-progress-stage-a-v1"
STATES = {"planned", "completed", "removed", "exempt"}
KINDS = {"query", "issue"}
SCOPE_KEYS = ("scenario_id", "jurisdiction", "right_type", "product_version")


def enabled(task: dict) -> bool:
    value = task.get("review_progress_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("REVIEW_PROGRESS_REVISION_INVALID")
    return True


def operating_progress_enabled(task: dict) -> bool:
    """Only explicit new operating tasks adopt audited outcome projection."""
    return (task.get("assessment_revision") == "known-findings-risk-v1"
            or task.get("presentation_policy_revision") == "operator-report-v1")


def _events(evidence: dict) -> list[dict]:
    value = evidence.get("review_progress_events", [])
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("REVIEW_PROGRESS_EVENTS_INVALID")
    return value


def _version(task: dict) -> str:
    value = task.get("product_change_version") or task.get("product_identity", {}).get("sha256")
    return str(value or sha256_json(task.get("product", {})))


def _fact_digest(evidence: dict) -> str:
    return sha256_json({key: value for key, value in evidence.items()
                        if key not in {"review_progress_events", "progress_events", "continuation_events",
                                       "stage_risk_events", "stage_review_events"}})


def _counts(items: dict[str, dict]) -> dict:
    active = [row for row in items.values() if row["state"] in {"planned", "completed"}]
    completed = sum(row["state"] == "completed" for row in active)
    total = len(active)
    return {"completed": completed, "planned": total,
            "percentage": round(100 * completed / total, 4) if total else None,
            "excluded": {state: sum(row["state"] == state for row in items.values())
                         for state in ("removed", "exempt")}}


def _apply(items: dict[str, dict], event: dict) -> None:
    kind = event["kind"]
    if kind in {"initialize", "add"}:
        for item in event["items"]:
            if item["item_id"] in items:
                raise ValueError("REVIEW_PROGRESS_ITEM_ID_REUSED")
            items[item["item_id"]] = {**deepcopy(item), "state": "planned",
                                      "created_in_version": event["version"]}
        return
    item = items.get(event.get("item_id"))
    if item is None:
        raise ValueError("REVIEW_PROGRESS_ITEM_UNKNOWN")
    if kind == "rebind":
        if item.get("kind") != "query":
            raise ValueError("REVIEW_PROGRESS_REBIND_QUERY_ONLY")
        if (event.get("from_product_version") != item.get("scope", {}).get("product_version") or
                event.get("to_product_version") in (None, "", event.get("from_product_version"))):
            raise ValueError("REVIEW_PROGRESS_REBIND_VERSION_CHAIN_INVALID")
        if event.get("plan_entry_sha256") != item.get("plan_entry_sha256"):
            raise ValueError("REVIEW_PROGRESS_REBIND_PLAN_HASH_CHANGED")
        if event.get("prior_item_sha256") != sha256_json(item):
            raise ValueError("REVIEW_PROGRESS_REBIND_ITEM_SNAPSHOT_MISMATCH")
        if not isinstance(event.get("upstream_ref"), str) or not event["upstream_ref"].strip():
            raise ValueError("REVIEW_PROGRESS_REBIND_UPSTREAM_REQUIRED")
        history = item.setdefault("rebind_history", [])
        history.append({key: deepcopy(event[key]) for key in
                        ("from_product_version", "to_product_version", "upstream_ref",
                         "plan_entry_sha256", "prior_item_sha256", "reasoning", "event_id")
                        if key in event})
        if "completion" in item:
            item.setdefault("completion_history", []).append(item.pop("completion"))
        item["scope"]["product_version"] = event["to_product_version"]
        item["state"] = "planned"
        item.pop("completion", None)
        item["rebind_reason"] = event["reasoning"]
        item["upstream_ref"] = event["upstream_ref"]
        return
    if kind == "complete":
        if item["state"] != "planned":
            raise ValueError("REVIEW_PROGRESS_COMPLETION_STATE_INVALID")
        item["state"] = "completed"
        item["completion"] = {key: deepcopy(event[key]) for key in
                              ("evidence_refs", "source_run_id", "reasoning", "event_id",
                               "source_run_sha256", "accepted_submission_state", "accepted_source_status") if key in event}
    elif kind in {"remove", "exempt"}:
        if item["state"] not in {"planned", "completed"}:
            raise ValueError("REVIEW_PROGRESS_CHANGE_STATE_INVALID")
        item["state"] = "removed" if kind == "remove" else "exempt"
        item["change_reason"] = event["reasoning"]
        item["upstream_ref"] = event["upstream_ref"]
    elif kind == "reopen":
        if item["state"] != "completed":
            raise ValueError("REVIEW_PROGRESS_REOPEN_REQUIRES_COMPLETED_ITEM")
        item.setdefault("completion_history", []).append(item.pop("completion"))
        item["state"] = "planned"
        item["reopen_reason"] = event["reasoning"]
        item["upstream_ref"] = event["upstream_ref"]
    else:
        raise ValueError("REVIEW_PROGRESS_EVENT_KIND_INVALID")


def ledger(task: dict, evidence: dict) -> dict:
    if not enabled(task):
        return {}
    items: dict[str, dict] = {}
    events = _events(evidence)
    if not events:
        return {"revision": REVISION, "status": "plan_required", "plan_version": None,
                "completed": 0, "planned": None, "percentage": None, "items": [], "history": []}
    history = []
    for number, event in enumerate(events, 1):
        if event.get("version") != number or event.get("prior_version") != number - 1:
            raise ValueError("REVIEW_PROGRESS_VERSION_CHAIN_INVALID")
        if (number == 1) != (event.get("kind") == "initialize"):
            raise ValueError("REVIEW_PROGRESS_INITIAL_EVENT_REQUIRED")
        before = _counts(items)
        if event.get("before") != before:
            raise ValueError("REVIEW_PROGRESS_BEFORE_COUNTS_INVALID")
        _apply(items, event)
        after = _counts(items)
        if event.get("after") != after:
            raise ValueError("REVIEW_PROGRESS_AFTER_COUNTS_INVALID")
        history.append({"event_id": event["event_id"], "kind": event["kind"],
                        "version": number, "before": before, "after": after,
                        "item_ids": [row["item_id"] for row in event["items"]] if "items" in event
                                   else [event["item_id"]], "reasoning": event["reasoning"]})
    counts = _counts(items)
    groups: dict[tuple, set[str]] = {}
    scope_groups: dict[tuple, set[str]] = {}
    for item in items.values():
        scope = item["scope"]
        scope_key = tuple(scope[key] for key in SCOPE_KEYS)
        scope_groups.setdefault(scope_key, set()).add(item["item_id"])
        for module_id in item["module_ids"]:
            key = (*scope_key, module_id)
            groups.setdefault(key, set()).add(item["item_id"])
    by_scope = [{**dict(zip(SCOPE_KEYS, key)), **_counts({item_id: items[item_id] for item_id in ids})}
                for key, ids in sorted(scope_groups.items())]
    scoped = []
    for (*scope_key, module_id), ids in sorted(groups.items()):
        group_counts = _counts({item_id: items[item_id] for item_id in ids})
        scoped.append({**dict(zip(SCOPE_KEYS, scope_key)), "module_id": module_id, **group_counts})
    return {"revision": REVISION, "status": "defined" if counts["planned"] else "no_active_items", "plan_version": len(events),
            **counts, "items": [items[key] for key in sorted(items)],
            "by_scope": by_scope, "by_scope_module": scoped, "history": history,
            "counting_basis": "unique_item_ids_in_current_plan; business_review_and_delivery_separate"}


def project(task: dict, view: dict, evidence: dict | None) -> dict:
    if not enabled(task) or evidence is None:
        return view
    result = deepcopy(view)
    result["review_progress"] = ledger(task, evidence)
    if "work_view_sha256" in result:
        result["work_view_sha256"] = sha256_json({key: value for key, value in result.items()
            if key not in {"work_view_sha256", "review_work"}})
    return result


def dispatch_block(task: dict, evidence: dict, provider: str, row: dict) -> str | None:
    """New tasks submit only a pre-registered, current query obligation."""
    if not enabled(task):
        return None
    current = ledger(task, evidence)
    if current["status"] == "plan_required":
        return None
    for item in current["items"]:
        if (item["kind"] == "query" and item["provider"] == provider and
                item["query_id"] == row.get("query_id") and
                item["plan_entry_sha256"] == sha256_json(row) and
                item["scope"]["product_version"] == _version(task) and
                item["state"] == "planned"):
            return None
    return "REVIEW_PROGRESS_QUERY_NOT_PLANNED"


def _plan_rows(plan: dict) -> dict[str, tuple[str, dict]]:
    rows = {}
    for provider, entries in plan.get("queries", {}).items():
        for row in entries if isinstance(entries, list) else []:
            if isinstance(row, dict) and row.get("query_id"):
                if row["query_id"] in rows:
                    raise ValueError("REVIEW_PROGRESS_DUPLICATE_PLAN_QUERY")
                rows[row["query_id"]] = provider, row
    return rows


def _item(task: dict, raw: dict, plan: dict, view: dict, evidence: dict) -> dict:
    if not isinstance(raw, dict) or raw.get("kind") not in KINDS:
        raise ValueError("REVIEW_PROGRESS_ITEM_KIND_INVALID")
    item_id = raw.get("item_id")
    scope = raw.get("scope")
    modules = raw.get("module_ids")
    condition = raw.get("acceptance_condition")
    if (not isinstance(item_id, str) or not item_id.startswith("ITEM-") or
            not isinstance(scope, dict) or not isinstance(modules, list) or not modules or
            any(not isinstance(value, str) or not value for value in modules) or
            not isinstance(condition, str) or not condition.strip()):
        raise ValueError("REVIEW_PROGRESS_ITEM_ID_SCOPE_AND_CONDITION_REQUIRED")
    if any(not isinstance(scope.get(key), str) or not scope[key] for key in SCOPE_KEYS):
        raise ValueError("REVIEW_PROGRESS_SCOPE_INVALID")
    if scope["product_version"] != _version(task):
        raise ValueError("REVIEW_PROGRESS_PRODUCT_VERSION_MISMATCH")
    requested_countries = set(task.get("target_jurisdictions", []))
    item_countries = set(scope["jurisdiction"].split(","))
    if not (item_countries <= requested_countries or
            (item_countries == {"EP"} and requested_countries & {"FR", "DE", "IT", "ES"})):
        raise ValueError("REVIEW_PROGRESS_COUNTRY_NOT_IN_TASK")
    scenarios = {row.get("scenario_id") for row in task.get("assessment_scenarios", []) if isinstance(row, dict)}
    if scenarios and scope["scenario_id"] not in scenarios:
        raise ValueError("REVIEW_PROGRESS_SCENARIO_NOT_IN_TASK")
    result = {"item_id": item_id, "kind": raw["kind"], "scope": {key: scope[key] for key in SCOPE_KEYS},
              "module_ids": sorted(set(modules)), "acceptance_condition": condition.strip()}
    if raw["kind"] == "query":
        query_id = raw.get("query_id")
        provider, row = _plan_rows(plan).get(query_id, (None, None))
        if row is None or row.get("jurisdiction") != scope["jurisdiction"] or row.get("right_type") != scope["right_type"]:
            raise ValueError("REVIEW_PROGRESS_QUERY_SCOPE_INVALID")
        bindings = row.get("scenario_bindings")
        if bindings and scope["scenario_id"] not in {item.get("scenario_id") for item in bindings if isinstance(item, dict)}:
            raise ValueError("REVIEW_PROGRESS_QUERY_SCENARIO_INVALID")
        if not bindings and row.get("scenario_id") != scope["scenario_id"]:
            raise ValueError("REVIEW_PROGRESS_QUERY_SCENARIO_INVALID")
        if any(isinstance(run, dict) and run.get("query_id") == query_id and
               run.get("provider") == provider and (run.get("submission_state") == "submitted"
                   or provider == "asset_provenance" and run.get("operation") == "provenance_review"
                   and run.get("source_environment") == "local_agent_review"
                   and run.get("status") == "success")
               for run in evidence.get("source_runs", [])):
            raise ValueError("REVIEW_PROGRESS_RETROACTIVE_QUERY_ITEM")
        result.update(query_id=query_id, provider=provider, plan_entry_sha256=sha256_json(row))
    else:
        issue_id = raw.get("issue_id")
        issue = next((row for row in view.get("continuous_work", {}).get("issues", [])
                      if row.get("issue_id") == issue_id), None)
        if not issue or issue.get("identity_quality") != "exact":
            raise ValueError("REVIEW_PROGRESS_EXACT_OPEN_ISSUE_REQUIRED")
        for key in ("scenario_id", "jurisdiction", "right_type"):
            if issue.get("scope", {}).get(key) != scope[key]:
                raise ValueError("REVIEW_PROGRESS_ISSUE_SCOPE_INVALID")
        result["issue_id"] = issue_id
        result["registered_fact_digest"] = _fact_digest(evidence)
    return result


def _upstream_exists(task: dict, evidence: dict, ref: str) -> bool:
    if not isinstance(ref, str) or not ref:
        return False
    for row in task.get("product_change_history", []):
        if isinstance(row, dict) and ref in {row.get("change_id"), row.get("event_id")}:
            return True
    if ref in _evidence_ids(evidence):
        return True
    for row in task.get("discovery_semantic_reviews", []):
        if isinstance(row, dict) and ref == row.get("review_id"):
            return True
    for key, rows in evidence.items():
        if key in {"review_progress_events", "progress_events", "continuation_events",
                   "stage_risk_events", "stage_review_events"}:
            continue
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and ref in {row.get("event_id"), row.get("review_id"),
                                                     row.get("source_run_id")}:
                    return True
    return False


def _validate_rebind(task: dict, evidence: dict, item: dict, plan: dict,
                     upstream_ref: str) -> dict:
    """Validate a query rebind against one real, current product-scope change."""
    if item.get("kind") != "query":
        raise ValueError("REVIEW_PROGRESS_REBIND_QUERY_ONLY")
    current_version = _version(task)
    prior_version = item.get("scope", {}).get("product_version")
    if prior_version == current_version:
        raise ValueError("REVIEW_PROGRESS_REBIND_NO_VERSION_CHANGE")
    prior_match = re.fullmatch(r"([Vv]?)([0-9]+)", str(prior_version or ""))
    current_match = re.fullmatch(r"([Vv]?)([0-9]+)", current_version)
    if (not prior_match or not current_match or prior_match.group(1) != current_match.group(1)
            or int(current_match.group(2)) != int(prior_match.group(2)) + 1):
        raise ValueError("REVIEW_PROGRESS_REBIND_VERSION_NOT_ADJACENT")
    change = next((row for row in task.get("product_change_history", [])
                  if isinstance(row, dict) and row.get("change_id") == upstream_ref), None)
    if (not change or str(change.get("version")) != current_version or
            not isinstance(change.get("sha256"), str) or
            change["sha256"] != sha256_json({key: value for key, value in change.items()
                                             if key != "sha256"})):
        raise ValueError("REVIEW_PROGRESS_REBIND_PRODUCT_CHANGE_REQUIRED")
    if (not isinstance(change.get("affected_query_ids"), list) or
            not isinstance(change.get("affected_direction_ids"), list) or
            not isinstance(change.get("affected_candidate_ids", []), list) or
            not isinstance(change.get("expanded_candidate_ids", []), list) or
            not isinstance(change.get("fact_changes", []), list) or
            not isinstance(change.get("object_changes", []), list)):
        raise ValueError("REVIEW_PROGRESS_REBIND_IMPACT_RECORD_INCOMPLETE")
    provider, row = _plan_rows(plan).get(item.get("query_id"), (None, None))
    if (row is None or provider != item.get("provider") or
            sha256_json(row) != item.get("plan_entry_sha256")):
        raise ValueError("REVIEW_PROGRESS_REBIND_PLAN_HASH_CHANGED")
    if item.get("scope", {}).get("jurisdiction") != row.get("jurisdiction") or \
            item.get("scope", {}).get("right_type") != row.get("right_type"):
        raise ValueError("REVIEW_PROGRESS_REBIND_SCOPE_CHANGED")
    if item.get("query_id") in set(change.get("affected_query_ids") or []):
        raise ValueError("REVIEW_PROGRESS_REBIND_QUERY_AFFECTED")
    dependencies = row.get("product_dependencies", [])
    dependency_directions = {ref.get("direction_id") for ref in dependencies if isinstance(ref, dict)}
    dependency_facts = {fact for ref in dependencies if isinstance(ref, dict)
                        for fact in ref.get("fact_ids", [])}
    dependency_objects = {obj for ref in dependencies if isinstance(ref, dict)
                          for obj in ref.get("object_ids", [])}
    changed_directions = set(change.get("affected_direction_ids") or [])
    changed_facts = ({entry.get("id") for entry in change.get("fact_changes", [])
                      if isinstance(entry, dict)} |
                     set(change.get("affected_fact_ids") or []))
    changed_objects = ({entry.get("id") for entry in change.get("object_changes", [])
                        if isinstance(entry, dict)} |
                       set(change.get("affected_object_ids") or []))
    if dependency_directions & changed_directions:
        raise ValueError("REVIEW_PROGRESS_REBIND_DIRECTION_AFFECTED")
    if dependency_facts & changed_facts:
        raise ValueError("REVIEW_PROGRESS_REBIND_FACT_AFFECTED")
    if dependency_objects & changed_objects:
        raise ValueError("REVIEW_PROGRESS_REBIND_OBJECT_AFFECTED")
    if change.get("affected_candidate_ids") or change.get("expanded_candidate_ids"):
        raise ValueError("REVIEW_PROGRESS_REBIND_CANDIDATE_SCOPE_AMBIGUOUS")
    return change


def _evidence_ids(evidence: dict) -> set[str]:
    ids = set()
    for key, rows in evidence.items():
        if key in {"review_progress_events", "progress_events", "continuation_events",
                   "stage_risk_events", "stage_review_events"}:
            continue
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    ids.update(value for key, value in row.items() if key in
                               {"evidence_id", "run_id", "event_id", "review_id", "record_id"}
                               and isinstance(value, str) and value)
    for rows in evidence.get("collections", {}).values():
        if isinstance(rows, list):
            ids.update(row["evidence_id"] for row in rows if isinstance(row, dict)
                       and isinstance(row.get("evidence_id"), str) and row["evidence_id"])
    return ids


def _local_asset_review_complete(task: dict, evidence: dict, row: dict,
                                 item: dict, run: dict, task_dir: Path | None = None) -> bool:
    if (run.get("provider") != "asset_provenance" or run.get("operation") != "provenance_review"
            or row.get("operation") != "provenance_review"
            or run.get("source_environment") != "local_agent_review"
            or run.get("submission_state") != "not_submitted" or run.get("status") != "success"):
        return False
    from assessment_v24 import evidence_index, _entry_matches_run, _retained_artifacts_complete
    from record_asset_provenance import investigation_complete
    registry = evidence_index(evidence)
    entries = [entry for entry in registry.values() if _entry_matches_run(entry, run)]
    if len(entries) != 1 or not isinstance(entries[0].get("payload"), dict):
        return False
    if task_dir is not None:
        from workflow_v24 import scenario_supplement
        try:
            supplement = scenario_supplement(Path(task_dir),task=task,evidence=evidence)
            registry.update({entry['evidence_id']:entry for entry in (supplement or {}).get('evidence',[])})
        except (ValueError,OSError,KeyError,TypeError):
            return False
    payload = entries[0]["payload"]
    if not _retained_artifacts_complete(payload):
        return False
    # A valid supplier/user request is a separate dependency after public
    # investigation. Validate it through the existing projection before
    # evaluating the public work with those private actions removed.
    actions = payload.get("outstanding_actions", [])
    if not isinstance(actions, list):
        return False
    if actions:
        from record_asset_provenance import external_information_actions
        if external_information_actions(task, payload, row, item["scope"]["scenario_id"], registry) != actions:
            return False
        payload = {**payload, "outstanding_actions": []}
    return investigation_complete(task, payload, row, item["scope"]["scenario_id"], registry)


def _completion(item: dict, request: dict, task: dict, evidence: dict, plan: dict, view: dict,
                task_dir: Path | None = None) -> dict:
    refs = request.get("evidence_refs")
    if not isinstance(refs, list) or not refs or any(ref not in _evidence_ids(evidence) for ref in refs):
        raise ValueError("REVIEW_PROGRESS_VERIFIED_EVIDENCE_REFS_REQUIRED")
    if item["scope"]["product_version"] != _version(task):
        raise ValueError("REVIEW_PROGRESS_CURRENT_PRODUCT_VERSION_CHANGED")
    if item["kind"] == "query":
        provider, row = _plan_rows(plan).get(item["query_id"], (None, None))
        if provider != item["provider"] or row is None or sha256_json(row) != item["plan_entry_sha256"]:
            raise ValueError("REVIEW_PROGRESS_QUERY_PLAN_CHANGED")
        from runtime_v24 import physical_response_source
        from recovery_stage_b import effective_submission, effective_result
        audited = operating_progress_enabled(task)
        def source_state(run):
            return effective_result(evidence, run) if audited else run.get("status")
        def submitted(run):
            return effective_submission(evidence, run) if audited else run.get("submission_state")
        runs = [run for run in evidence.get("source_runs", []) if isinstance(run, dict)
                and run.get("run_id") == request.get("source_run_id") and
                run.get("query_id") == item["query_id"] and run.get("provider") == provider and
                run.get("plan_entry_sha256") == item["plan_entry_sha256"] and
                ((submitted(run) == "submitted" and source_state(run) in {"success", "no_result"})
                 or task_dir is not None and run.get("status") in {"success", "no_result"}
                    and physical_response_source(Path(task_dir), evidence, run) is not None
                 or _local_asset_review_complete(task, evidence, row, item, run, task_dir))]
        if len(runs) != 1 or runs[0]["run_id"] not in refs:
            raise ValueError("REVIEW_PROGRESS_SUCCESSFUL_BOUND_RUN_REQUIRED")
        if source_state(runs[0]) == "no_result" and (audited or isinstance(runs[0].get("result_processing"), dict)):
            from source_result_processing import zero_result_proven
            # Only hash-bound submission audits may provide effective state.
            # Receipt/row/count verification still runs on retained original
            # bytes; this local projection never changes the archived source.
            projected = {**runs[0], "status": source_state(runs[0]), "submission_state": submitted(runs[0])}
            if not zero_result_proven(projected if audited else runs[0], evidence, task_dir):
                raise ValueError("REVIEW_PROGRESS_ZERO_RESULT_UNVERIFIED")
        if any(entry.get("query_id") == item["query_id"] and entry.get("kind") == "source_lookup"
               and entry.get("state") in {"ready", "awaiting_access", "submission_unknown", "blocked"}
               for entry in view.get("entries", [])):
            raise ValueError("REVIEW_PROGRESS_QUERY_WORK_REMAINS")
        return {"source_run_id": runs[0]["run_id"], "evidence_refs": refs,
                **({"source_run_sha256": sha256_json(runs[0]),
                    "accepted_submission_state": submitted(runs[0]),
                    "accepted_source_status": source_state(runs[0])} if audited else {})}
    if any(issue.get("issue_id") == item["issue_id"] for issue in
           view.get("continuous_work", {}).get("issues", [])):
        raise ValueError("REVIEW_PROGRESS_ORIGINAL_ISSUE_STILL_OPEN")
    if _fact_digest(evidence) == item["registered_fact_digest"]:
        raise ValueError("REVIEW_PROGRESS_NO_NEW_FACT_SINCE_REGISTRATION")
    return {"evidence_refs": refs}


def record_event(task_dir: Path, request: dict) -> dict:
    """Append a plan decision; never write task, source, candidate or review facts."""
    from provider_utils import evidence_lock
    from workflow_v24 import work_view_from_dir
    task_dir = Path(task_dir)
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        evidence = load_json(task_dir / "evidence.json")
        if not enabled(task) or evidence.get("task_id") != task.get("task_id"):
            raise ValueError("REVIEW_PROGRESS_TASK_MISMATCH")
        plan_path = task_dir / "search-plan.json"
        plan = load_json(plan_path) if plan_path.is_file() else {}
        kind = request.get("kind")
        if kind not in {"initialize", "add", "complete", "remove", "exempt", "reopen", "rebind"}:
            raise ValueError("REVIEW_PROGRESS_KIND_INVALID")
        if not all(isinstance(request.get(key), str) and request[key].strip()
                   for key in ("actor", "reasoning")):
            raise ValueError("REVIEW_PROGRESS_ACTOR_AND_REASON_REQUIRED")
        current = ledger(task, evidence)
        events = _events(evidence)
        if (kind == "initialize") != (not events):
            raise ValueError("REVIEW_PROGRESS_INITIALIZATION_ORDER_INVALID")
        items = {item["item_id"]: item for item in current.get("items", [])}
        before = _counts(items)
        view = work_view_from_dir(task_dir)
        event = {"kind": kind, "actor": request["actor"], "reasoning": request["reasoning"],
                 "recorded_at": now_iso(), "version": len(events) + 1,
                 "prior_version": len(events), "before": before}
        if kind in {"initialize", "add"}:
            raw_items = request.get("items")
            if not isinstance(raw_items, list) or (kind == "add" and not raw_items) or any(not isinstance(row, dict) for row in raw_items):
                raise ValueError("REVIEW_PROGRESS_ITEMS_REQUIRED")
            new = [_item(task, row, plan, view, evidence) for row in raw_items]
            if len({row["item_id"] for row in new}) != len(new):
                raise ValueError("REVIEW_PROGRESS_DUPLICATE_ITEM")
            if any(row["item_id"] in items for row in new):
                raise ValueError("REVIEW_PROGRESS_ITEM_ID_REUSED")
            identities = {(row["kind"], row.get("query_id") or row.get("issue_id"),
                           sha256_json(row["scope"]))
                          for row in [*items.values(), *new]}
            if len(identities) != len(items) + len(new):
                raise ValueError("REVIEW_PROGRESS_DUPLICATE_OBLIGATION")
            if kind == "add":
                ref = request.get("upstream_ref")
                if not _upstream_exists(task, evidence, ref):
                    raise ValueError("REVIEW_PROGRESS_NEW_OBLIGATION_UPSTREAM_REQUIRED")
                event["upstream_ref"] = ref
            event["items"] = new
        else:
            item = items.get(request.get("item_id"))
            if item is None:
                raise ValueError("REVIEW_PROGRESS_ITEM_UNKNOWN")
            event["item_id"] = item["item_id"]
            if kind == "complete":
                event.update(_completion(item, request, task, evidence, plan, view, task_dir))
            elif kind == "rebind":
                ref = request.get("upstream_ref")
                if not isinstance(ref, str) or not ref.strip():
                    raise ValueError("REVIEW_PROGRESS_REBIND_UPSTREAM_REQUIRED")
                _validate_rebind(task, evidence, item, plan, ref)
                event.update(from_product_version=item["scope"]["product_version"],
                             to_product_version=_version(task), upstream_ref=ref,
                             plan_entry_sha256=item["plan_entry_sha256"],
                             prior_item_sha256=sha256_json(item))
            else:
                ref = request.get("upstream_ref")
                if not _upstream_exists(task, evidence, ref):
                    raise ValueError("REVIEW_PROGRESS_CHANGE_UPSTREAM_REQUIRED")
                event["upstream_ref"] = ref
        event["event_id"] = "REVIEW-PLAN-" + sha256_json({"task_id": task["task_id"], "event": event})[:24]
        updated = deepcopy(items)
        _apply(updated, event)
        event["after"] = _counts(updated)
        evidence.setdefault("review_progress_events", []).append(event)
        atomic_write_json(task_dir / "evidence.json", evidence)
        return event


def _query_batch_snapshot(task_dir: Path) -> str:
    """Bind actual inputs and declared original bytes for this one locked call."""
    # Reuse the existing retained-byte scanner, including registered media,
    # documents and source receipts; do not introduce a separate path policy.
    from delivery_versions_stage_e import _retained_files, INPUTS
    values = {name: load_json(task_dir/name) if (task_dir/name).is_file() else None for name in INPUTS}
    return sha256_json({'inputs':values,'retained_files':_retained_files(task_dir,values)})


def record_query_completions(task_dir: Path, requests: list[dict]) -> list[dict]:
    """Atomically append query completions using one actual, unchanged work view."""
    from provider_utils import evidence_lock
    from workflow_v24 import work_view_from_dir
    task_dir = Path(task_dir)
    if (not isinstance(requests,list) or not requests
            or any(not isinstance(request,dict) or request.get('kind') != 'complete' for request in requests)):
        raise ValueError('REVIEW_PROGRESS_QUERY_COMPLETE_BATCH_REQUIRED')
    with evidence_lock(task_dir):
        before_inputs = _query_batch_snapshot(task_dir)
        task = load_json(task_dir/'task.json')
        evidence = load_json(task_dir/'evidence.json')
        plan_path = task_dir/'search-plan.json'
        plan = load_json(plan_path) if plan_path.is_file() else {}
        if not enabled(task) or evidence.get('task_id') != task.get('task_id'):
            raise ValueError('REVIEW_PROGRESS_TASK_MISMATCH')
        current = ledger(task,evidence)
        events = _events(evidence)
        if not events:
            raise ValueError('REVIEW_PROGRESS_INITIALIZATION_ORDER_INVALID')
        items = {item['item_id']:deepcopy(item) for item in current.get('items',[])}
        ids = [request.get('item_id') for request in requests]
        if any(not isinstance(item_id,str) or not item_id for item_id in ids) or len(set(ids)) != len(ids):
            raise ValueError('REVIEW_PROGRESS_BATCH_DUPLICATE_OR_INVALID_ITEM')
        for request in requests:
            item = items.get(request['item_id'])
            if item is None:
                raise ValueError('REVIEW_PROGRESS_ITEM_UNKNOWN')
            if item['kind'] != 'query':
                raise ValueError('REVIEW_PROGRESS_BATCH_QUERY_ONLY')
            if not all(isinstance(request.get(key),str) and request[key].strip() for key in ('actor','reasoning')):
                raise ValueError('REVIEW_PROGRESS_ACTOR_AND_REASON_REQUIRED')
        view = work_view_from_dir(task_dir)
        pending = []
        for request in requests:
            item = items[request['item_id']]
            event = {'kind':'complete','actor':request['actor'],'reasoning':request['reasoning'],
                'recorded_at':now_iso(),'version':len(events)+len(pending)+1,
                'prior_version':len(events)+len(pending),'before':_counts(items),'item_id':item['item_id']}
            # Every exact row/run/EV/zero-result/local investigation check is
            # the same function used by the original one-event recorder.
            event.update(_completion(item,request,task,evidence,plan,view,task_dir))
            event['event_id'] = 'REVIEW-PLAN-' + sha256_json({'task_id':task['task_id'],'event':event})[:24]
            _apply(items,event)
            event['after'] = _counts(items)
            pending.append(event)
        if _query_batch_snapshot(task_dir) != before_inputs:
            raise ValueError('REVIEW_PROGRESS_BATCH_INPUTS_CHANGED')
        evidence.setdefault('review_progress_events',[]).extend(pending)
        atomic_write_json(task_dir/'evidence.json',evidence)
        return pending

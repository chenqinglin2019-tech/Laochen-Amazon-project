"""09B: append-only, evidence-bound stage risk and current-usability projection."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path

from common import MODULE_IDS, RIGHT_TYPES, atomic_write_json, load_json, now_iso, sha256_json
from assessment_v24 import NON_PRODUCTION, evidence_index

REVISION = "stage-risk-stage-b-v1"
RISKS = ("极低", "低", "中", "高", "极高")
CONFIDENCES = ("低", "中", "高")
SCOPE = ("scenario_id", "jurisdiction", "right_type", "product_version", "module_id", "candidate_id")
OUTCOME_KINDS = {"comparison", "trademark_comparison", "copyright_relationship",
                 "trade_dress_comparison"}
CONTROL_COLLECTIONS = {"stage_risk_events", "stage_review_events", "review_progress_events", "progress_events",
                       "continuation_events"}


def enabled(task: dict) -> bool:
    value = task.get("stage_risk_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("STAGE_RISK_REVISION_INVALID")
    return True


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _version(task: dict) -> str:
    return str(task.get("product_change_version") or task.get("product_identity", {}).get("sha256")
               or sha256_json(task.get("product", {})))


def _registry(task: dict, evidence: dict, task_dir: Path | None = None) -> dict[str, dict]:
    registry = {}
    def add(ref, origin, row):
        value = {"origin": origin, "row": row}
        if ref in registry and registry[ref] != value:
            raise ValueError("STAGE_RISK_REFERENCE_COLLISION")
        registry[ref] = value
    for ref, row in evidence_index(evidence).items():
        add(ref, "evidence", row)
    if task_dir is not None:
        from workflow_v24 import scenario_supplement
        from assessment_estimate import validate_supplement
        supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
        root = task.get("evidence_root") or task.get("historical_evidence_root") or task_dir
        for ref, row in validate_supplement(supplement, root, task=task, evidence=evidence).items():
            add(ref, "evidence", row)
    for row in evidence.get("source_runs", []):
        if isinstance(row, dict) and _text(row.get("run_id")):
            add(row["run_id"], "run", row)
    for name in ("specialty_analysis_events", "distinctive_rights_events"):
        if name == "specialty_analysis_events" and task.get("specialty_analysis_revision"):
            from specialty_analysis import events
            events(task)
        if name == "distinctive_rights_events" and task.get("distinctive_rights_revision"):
            from distinctive_rights import events
            events(task)
        for row in task.get(name, []):
            if isinstance(row, dict) and _text(row.get("event_id")):
                add(row["event_id"], name, row)
    return registry


def _scope(task: dict, raw: dict) -> dict:
    if not isinstance(raw, dict) or any(not _text(raw.get(key)) for key in SCOPE[:-1]):
        raise ValueError("STAGE_RISK_SCOPE_REQUIRED")
    if raw["product_version"] != _version(task):
        raise ValueError("STAGE_RISK_PRODUCT_VERSION_MISMATCH")
    if raw["jurisdiction"] not in task.get("target_jurisdictions", []):
        raise ValueError("STAGE_RISK_COUNTRY_OUT_OF_SCOPE")
    scenarios = {row.get("scenario_id") for row in task.get("assessment_scenarios", [])
                 if isinstance(row, dict)}
    if scenarios and raw["scenario_id"] not in scenarios:
        raise ValueError("STAGE_RISK_SCENARIO_UNKNOWN")
    if raw["right_type"] in {"enforcement", "future_application"}:
        raise ValueError("STAGE_RISK_SIGNAL_NOT_CURRENT_RIGHT")
    if raw["right_type"] not in RIGHT_TYPES or raw["module_id"] not in MODULE_IDS:
        raise ValueError("STAGE_RISK_MODULE_OR_RIGHT_INVALID")
    from assessment_estimate import MODULE_RIGHTS
    if raw["right_type"] not in MODULE_RIGHTS[raw["module_id"]]:
        raise ValueError("STAGE_RISK_MODULE_RIGHT_MISMATCH")
    if raw.get("candidate_id") is not None and not isinstance(raw["candidate_id"], str):
        raise ValueError("STAGE_RISK_CANDIDATE_ID_INVALID")
    return {key: raw.get(key) or "" for key in SCOPE}


def _refs(registry: dict, refs, *, required=True) -> dict[str, str]:
    if (not isinstance(refs, list) or (required and not refs) or
            any(not _text(ref) or ref not in registry for ref in refs) or len(refs) != len(set(refs))):
        raise ValueError("STAGE_RISK_EXISTING_EVIDENCE_REFS_REQUIRED")
    def nonproduction(value):
        if isinstance(value, dict):
            return any(str(value.get(key) or "").casefold() in NON_PRODUCTION
                       for key in ("source_environment", "environment", "kind")) or any(
                           nonproduction(item) for item in value.values())
        return isinstance(value, list) and any(nonproduction(item) for item in value)
    if any(nonproduction(registry[ref]["row"]) for ref in refs):
        raise ValueError("STAGE_RISK_NONPRODUCTION_EVIDENCE")
    return {ref: sha256_json(registry[ref]) for ref in refs}


def _completed_outcome(task_dir: Path, task: dict, evidence: dict, registry: dict,
                       refs: list[str], scope: dict) -> None:
    for ref in refs:
        entry = registry[ref]
        row = entry["row"]
        if entry["origin"] in {"specialty_analysis_events", "distinctive_rights_events"}:
            if (row.get("kind") in OUTCOME_KINDS and all(
                    row.get(key) in (None, "", scope[key]) for key in
                    ("scenario_id", "jurisdiction", "right_type", "candidate_id"))):
                return
        if entry["origin"] == "run":
            if row.get("provider") == "asset_provenance" and scope.get("module_id") in {"copyright_ip", "figurative_trade_dress"}:
                from review_progress_stage_a import _local_asset_review_complete
                plan = load_json(task_dir / "search-plan.json")
                queries = [query for query in plan.get("queries", {}).get("asset_provenance", [])
                           if query.get("query_id") == row.get("query_id")
                           and query.get("right_type") == scope["right_type"]
                           and query.get("jurisdiction") == scope["jurisdiction"]
                           and str(query.get("candidate_id") or "") == str(scope.get("candidate_id") or "")
                           and sha256_json(query) == row.get("plan_entry_sha256")]
                if (len(queries) == 1 and scope["product_version"] == _version(task)
                        and _local_asset_review_complete(task, evidence, queries[0], {"scope": scope}, row, task_dir)):
                    return
            if any(row.get(key) not in (None, "", scope[key]) for key in
                   ("scenario_id", "jurisdiction", "right_type")):
                continue
            if not isinstance(row.get("result_processing"), dict):
                continue
            from source_result_processing import progress
            state = progress(task_dir, row, evidence)
            if (state["material_processing_complete"] and
                    (row.get("submission_state") == "submitted" and row.get("status") in {"success", "no_result"}
                     or isinstance(state.get("returned_count"), int) and state["returned_count"] > 0)):
                return
    raise ValueError("STAGE_RISK_REVIEWED_COMPLETED_OUTCOME_REQUIRED")


def _facts(registry: dict, rows, *, required=False) -> None:
    if not isinstance(rows, list) or (required and not rows):
        raise ValueError("STAGE_RISK_FACTS_REQUIRED")
    for row in rows:
        if not isinstance(row, dict) or not _text(row.get("reasoning")):
            raise ValueError("STAGE_RISK_FACT_REASONING_REQUIRED")
        _refs(registry, row.get("evidence_refs"))


def _review(task_dir: Path, task: dict, evidence: dict, request: dict, registry: dict,
            candidates: dict) -> dict:
    scope = _scope(task, request.get("scope"))
    risk = request.get("stage_risk")
    status = request.get("verification_status")
    basis = request.get("basis")
    if risk not in RISKS or status not in {"pending", "verified"}:
        raise ValueError("STAGE_RISK_GRADE_AND_VERIFICATION_REQUIRED")
    if basis not in {"no_specific_lead", "weak_leads", "credible_conflict", "verified_comparison", "decisive_exclusion"}:
        raise ValueError("STAGE_RISK_BASIS_INVALID")
    if not all(_text(request.get(key)) for key in ("assessment_date", "comparison", "adjacent_level_reasoning")):
        raise ValueError("STAGE_RISK_COMPARISON_AND_DATE_REQUIRED")
    try:
        date.fromisoformat(request["assessment_date"])
    except ValueError as exc:
        raise ValueError("STAGE_RISK_DATE_INVALID") from exc
    refs = request.get("evidence_refs")
    fingerprints = _refs(registry, refs)
    _refs(registry, request.get("outcome_refs"))
    _completed_outcome(task_dir, task, evidence, registry, request["outcome_refs"], scope)
    _facts(registry, request.get("supporting_facts", []), required=risk in {"中", "高", "极高"})
    _facts(registry, request.get("counter_facts", []))
    gaps = request.get("gaps")
    if not isinstance(gaps, list) or any(not isinstance(row, dict) or
            not all(_text(row.get(key)) for key in ("missing_fact", "impact", "minimal_action"))
            for row in gaps):
        raise ValueError("STAGE_RISK_SCOPED_GAPS_REQUIRED")
    if status == "pending":
        if not gaps or request.get("confidence") is not None or risk not in {"低", "中"}:
            raise ValueError("STAGE_RISK_PENDING_CONFIDENCE_OR_GAPS_INVALID")
        if risk == "低" and basis not in {"no_specific_lead", "weak_leads"}:
            raise ValueError("STAGE_RISK_PROVISIONAL_LOW_BASIS_INVALID")
        if risk == "中" and basis != "credible_conflict":
            raise ValueError("STAGE_RISK_CREDIBLE_CONFLICT_REQUIRED")
    else:
        if (gaps or basis not in {"verified_comparison", "decisive_exclusion"} or
                request.get("confidence") not in CONFIDENCES or not _text(request.get("confidence_reasoning"))):
            raise ValueError("STAGE_RISK_VERIFIED_BASIS_AND_CONFIDENCE_REQUIRED")
        if risk == "极低" and (basis != "decisive_exclusion" or
                request.get("scope_complete") is not True or not request.get("decisive_exclusion_refs")):
            raise ValueError("STAGE_RISK_DECISIVE_EXCLUSION_REQUIRED")
        if risk == "低" and request.get("necessary_work_reviewed") is not True:
            raise ValueError("STAGE_RISK_VERIFIED_LOW_COVERAGE_REQUIRED")
        if risk in {"高", "极高"} and (not _text(request.get("right_applicability_reasoning")) or
                not _text(request.get("counter_evidence_reasoning"))):
            raise ValueError("STAGE_RISK_HIGH_APPLICABILITY_REQUIRED")
        if risk == "极高" and request.get("important_exclusions_checked") is not True:
            raise ValueError("STAGE_RISK_VERY_HIGH_EXCLUSIONS_REQUIRED")
    weak = request.get("weak_leads", [])
    if (not isinstance(weak, list) or (basis == "weak_leads" and not weak) or
            any(not isinstance(row, dict) or not all(_text(row.get(key)) for key in
                ("lead", "why_not_credible_conflict", "minimal_check")) for row in weak)):
        raise ValueError("STAGE_RISK_WEAK_LEAD_EXPLANATION_REQUIRED")
    for row in weak:
        _refs(registry, row.get("evidence_refs"))
    fact_refs = {ref for name in ("supporting_facts", "counter_facts", "weak_leads")
                 for fact in request.get(name, []) for ref in fact.get("evidence_refs", [])}
    if not fact_refs <= set(refs):
        raise ValueError("STAGE_RISK_FACT_REF_NOT_IN_JUDGMENT")
    if basis == "credible_conflict" and (not scope["candidate_id"] or
            not _text(request.get("product_link")) or not _text(request.get("conflict_point"))):
        raise ValueError("STAGE_RISK_PRODUCT_CONFLICT_REQUIRED")
    if risk in {"中", "高", "极高"} and not scope["candidate_id"]:
        raise ValueError("STAGE_RISK_SPECIFIC_CANDIDATE_REQUIRED")
    if risk in {"中", "高", "极高"} and not any(
            registry[ref]["origin"] in {"evidence", "specialty_analysis_events", "distinctive_rights_events"}
            for fact in request.get("supporting_facts", []) for ref in fact["evidence_refs"]):
        raise ValueError("STAGE_RISK_POSITIVE_FACT_NOT_SOURCE_BOUND")
    if scope["candidate_id"]:
        from annotate_materiality import iter_candidates
        from assessment_v24 import candidate_applies
        matches = [row for _, row in iter_candidates(candidates)
                   if row.get("candidate_id") == scope["candidate_id"]]
        if len(matches) != 1 or matches[0].get("right_type") != scope["right_type"]:
            raise ValueError("STAGE_RISK_CANDIDATE_IDENTITY_INVALID")
        if risk in {"中", "高", "极高"} and not candidate_applies(
                matches[0], scope["jurisdiction"], scope["right_type"]):
            raise ValueError("STAGE_RISK_CANDIDATE_COUNTRY_EFFECT_UNSUPPORTED")
    if risk in {"高", "极高"} and (request.get("right_state") != "active" or
            not request.get("right_state_evidence_refs")):
        raise ValueError("STAGE_RISK_HIGH_CURRENT_RIGHT_REQUIRED")
    if request.get("right_state_evidence_refs"):
        _refs(registry, request["right_state_evidence_refs"])
        if not set(request["right_state_evidence_refs"]) <= set(refs):
            raise ValueError("STAGE_RISK_RIGHT_STATE_REF_NOT_IN_JUDGMENT")
    if basis == "no_specific_lead" and (weak or risk != "低"):
        raise ValueError("STAGE_RISK_NO_LEAD_CONTRADICTION")
    if basis == "weak_leads" and risk != "低":
        raise ValueError("STAGE_RISK_WEAK_LEAD_NOT_MEDIUM")
    if risk == "极低":
        _refs(registry, request.get("decisive_exclusion_refs"))
    prior = [row for row in evidence.get("stage_risk_events", []) if row.get("kind") == "review"
             and all(row.get("scope", {}).get(key) == scope[key] for key in SCOPE
                     if key != "product_version")]
    if prior and (request.get("prior_judgment_id") != prior[-1]["event_id"] or
                  not _text(request.get("change_reasoning"))):
        raise ValueError("STAGE_RISK_REVISION_EXPLANATION_REQUIRED")
    if not prior and request.get("prior_judgment_id"):
        raise ValueError("STAGE_RISK_PRIOR_JUDGMENT_UNKNOWN")
    from delivery_inspection_stage_d import enabled as inspection_enabled, dependency_refs
    if inspection_enabled(task):
        fingerprints.update(_refs(registry, dependency_refs(registry, refs + request["outcome_refs"])))
    return {"scope": scope, "stage_risk": risk, "verification_status": status,
            "basis": basis, "assessment_date": request["assessment_date"],
            "evidence_refs": deepcopy(refs), "outcome_refs": deepcopy(request["outcome_refs"]),
            "ref_fingerprints": {**fingerprints, **_refs(registry, request["outcome_refs"])},
            "supporting_facts": deepcopy(request.get("supporting_facts", [])),
            "counter_facts": deepcopy(request.get("counter_facts", [])),
            "comparison": request["comparison"], "adjacent_level_reasoning": request["adjacent_level_reasoning"],
            "gaps": deepcopy(gaps), "weak_leads": deepcopy(weak),
            "confidence": request.get("confidence"),
            "confidence_reasoning": request.get("confidence_reasoning") if status == "verified" else "核实置信度未形成",
            "right_state": request.get("right_state", "unknown"),
            "right_state_evidence_refs": deepcopy(request.get("right_state_evidence_refs", [])),
            "decisive_exclusion_refs": deepcopy(request.get("decisive_exclusion_refs", [])),
            "scope_complete": request.get("scope_complete"),
            "important_exclusions_checked": request.get("important_exclusions_checked"),
            "prior_judgment_id": request.get("prior_judgment_id"),
            "change_reasoning": request.get("change_reasoning"),
            "review_status": "single_review_pending_09C"}


def _upstream_exists(task: dict, evidence: dict, ref: str) -> bool:
    if not _text(ref):
        return False
    for row in task.get("product_change_history", []):
        if isinstance(row, dict) and ref in (row.get("event_id"), row.get("change_id")):
            return True
    for origin in (task, evidence):
        for key, rows in origin.items():
            if key in CONTROL_COLLECTIONS or not isinstance(rows, list):
                continue
            if any(isinstance(row, dict) and ref in (row.get("event_id"), row.get("review_id"),
                                                      row.get("evidence_id"), row.get("run_id")) for row in rows):
                return True
    return False


def record_event(task_dir: Path, request: dict) -> dict:
    from provider_utils import evidence_lock
    task_dir = Path(task_dir)
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        evidence = load_json(task_dir / "evidence.json")
        if not enabled(task) or evidence.get("task_id") != task.get("task_id"):
            raise ValueError("STAGE_RISK_TASK_MISMATCH")
        _events(evidence)
        event = _apply_event(task_dir, task, evidence, request, _registry(task, evidence, task_dir),
                             lambda: _load_candidates(task_dir))
        atomic_write_json(task_dir / "evidence.json", evidence)
        return event


def _apply_event(task_dir: Path, task: dict, evidence: dict, request: dict, registry: dict,
                 load_candidates) -> dict:
    """Validate one stage-risk event against in-memory state and append it (caller persists)."""
    if not isinstance(request, dict) or not _text(request.get("actor")) or not _text(request.get("reasoning")):
        raise ValueError("STAGE_RISK_ACTOR_AND_REASON_REQUIRED")
    kind = request.get("kind")
    if kind == "review":
        payload = _review(task_dir, task, evidence, request, registry, load_candidates())
    elif kind == "invalidate":
        prior_id = request.get("judgment_id")
        prior = next((row for row in evidence.get("stage_risk_events", []) if
                      row.get("event_id") == prior_id and row.get("kind") == "review"), None)
        if prior is None or not _upstream_exists(task, evidence, request.get("upstream_ref")):
            raise ValueError("STAGE_RISK_INVALIDATION_ORIGIN_REQUIRED")
        later = [row for row in evidence.get("stage_risk_events", []) if row.get("kind") == "review"
                 and row["version"] > prior["version"] and all(
                     row.get("scope", {}).get(key) == prior["scope"].get(key)
                     for key in SCOPE if key != "product_version")]
        if later:
            raise ValueError("STAGE_RISK_INVALIDATION_NOT_CURRENT_JUDGMENT")
        if any(row.get("kind") == "invalidate" and row.get("judgment_id") == prior_id
               for row in evidence.get("stage_risk_events", [])):
            raise ValueError("STAGE_RISK_ALREADY_INVALIDATED")
        payload = {"judgment_id": prior_id, "upstream_ref": request["upstream_ref"],
                   "scope": deepcopy(prior["scope"]), "impact": request.get("impact"),
                   "recovery_action": request.get("recovery_action")}
        if not _text(payload["impact"]) or not _text(payload["recovery_action"]):
            raise ValueError("STAGE_RISK_INVALIDATION_IMPACT_REQUIRED")
    elif kind == "signal_review":
        scope = request.get("scope")
        signal_type = request.get("signal_type")
        layers = ({"application", "publication", "grant", "amendment", "unknown"}
                  if signal_type == "future_application" else
                  {"party_claim", "platform_action", "proceeding", "formal_decision", "unknown"})
        if (not isinstance(scope, dict) or not _text(scope.get("scenario_id")) or
                scope["scenario_id"] not in {row.get("scenario_id") for row in task.get("assessment_scenarios", [])
                                             if isinstance(row, dict)} or
                scope.get("jurisdiction") not in task.get("target_jurisdictions", []) or
                scope.get("product_version") != _version(task) or
                signal_type not in {"future_application", "enforcement"} or
                request.get("event_layer") not in layers or
                not all(_text(request.get(key)) for key in
                        ("product_link", "source_status", "event_time", "signal_reasoning", "review_condition"))):
            raise ValueError("STAGE_RISK_SIGNAL_SCOPE_AND_CONTEXT_REQUIRED")
        try:
            date.fromisoformat(request["event_time"])
        except ValueError as exc:
            raise ValueError("STAGE_RISK_SIGNAL_TIME_INVALID") from exc
        refs = request.get("evidence_refs")
        payload = {"scope": deepcopy(scope), "signal_type": request["signal_type"],
                   "event_layer": request["event_layer"],
                   "evidence_refs": deepcopy(refs), "ref_fingerprints": _refs(registry, refs),
                   "product_link": request["product_link"], "source_status": request["source_status"],
                   "event_time": request["event_time"], "signal_reasoning": request["signal_reasoning"],
                   "review_condition": request["review_condition"], "current_risk_included": False}
    else:
        raise ValueError("STAGE_RISK_KIND_INVALID")
    events = evidence.setdefault("stage_risk_events", [])
    event = {"kind": kind, **payload, "actor": request["actor"],
             "reasoning": request["reasoning"], "recorded_at": now_iso(),
             "version": len(events) + 1,
             "previous_event_id": events[-1]["event_id"] if events else ""}
    event["event_id"] = "STAGE-RISK-" + sha256_json({"task_id": task["task_id"], "event": event})[:24]
    events.append(event)
    return event


def record_events(task_dir: Path, requests: list[dict]) -> list[dict]:
    """Record several events with one load, one evidence registry, one chain check and one write.

    Equivalent to sequential record_event calls: the reference registry is built
    from evidence collections, source runs, specialty/distinctive events and the
    supplement, none of which a stage-risk event changes. All requests are
    validated in memory first; nothing is written unless every one is accepted.
    """
    from provider_utils import evidence_lock
    task_dir = Path(task_dir)
    if not isinstance(requests, list) or not requests:
        raise ValueError("STAGE_RISK_BATCH_INVALID")
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        evidence = load_json(task_dir / "evidence.json")
        if not enabled(task) or evidence.get("task_id") != task.get("task_id"):
            raise ValueError("STAGE_RISK_TASK_MISMATCH")
        _events(evidence)
        registry = _registry(task, evidence, task_dir)
        cache = []
        def load_candidates():
            if not cache:
                cache.append(_load_candidates(task_dir))
            return cache[0]
        recorded = [_apply_event(task_dir, task, evidence, request, registry, load_candidates)
                    for request in requests]
        atomic_write_json(task_dir / "evidence.json", evidence)
        return recorded


def _load_candidates(task_dir: Path) -> dict:
    candidate_path = task_dir / "normalized-candidates.json"
    return load_json(candidate_path) if candidate_path.is_file() else {}


def _events(evidence: dict) -> list[dict]:
    events = evidence.get("stage_risk_events", [])
    if not isinstance(events, list):
        raise ValueError("STAGE_RISK_EVENTS_INVALID")
    prior = ""
    for number, row in enumerate(events, 1):
        if (not isinstance(row, dict) or row.get("version") != number or
                row.get("previous_event_id") != prior or
                row.get("event_id") != "STAGE-RISK-" + sha256_json({"task_id": evidence.get("task_id"),
                    "event": {key: value for key, value in row.items() if key != "event_id"}})[:24]):
            raise ValueError("STAGE_RISK_EVENT_CHAIN_INVALID")
        prior = row["event_id"]
    return events


def _risk_max(rows: list[dict]) -> str | None:
    return max((row["stage_risk"] for row in rows if row.get("stage_risk") in RISKS),
               key=RISKS.index, default=None)


def _summary(rows: list[dict], *, scope: dict) -> dict:
    valid = [row for row in rows if row["applicability"] == "current"]
    suspended = [row for row in rows if row["applicability"] == "suspended"]
    highest = _risk_max(valid)
    old_highest = _risk_max(suspended)
    affected = bool(old_highest and (highest is None or RISKS.index(old_highest) > RISKS.index(highest)))
    if highest == "极低" and any(row["applicability"] != "current" or
                              row["stage_risk"] != "极低" for row in rows):
        highest = "低"
    display = (f"当前待复核；上次等级：{old_highest}（已暂停适用）" if affected else
               "暂定低" if highest == "低" else f"阶段性{highest}" if highest else "尚无已审阶段等级")
    return {**scope, "stage_risk": None if affected else highest, "display_grade": display,
            "assessment_dates": sorted({row["assessment_date"] for row in rows}),
            "applicability": "pending_recheck" if affected else "current" if highest else "not_established",
            "previous_risk": old_highest if affected else None,
            "valid_partial_highest": highest if affected else None,
            "drivers": [row["event_id"] for row in valid if row["stage_risk"] == highest],
            "suspended_judgments": [row["event_id"] for row in suspended],
            "verification_status": "verified" if valid and all(row["verification_status"] == "verified" for row in valid)
                    and not suspended else "pending",
            "confidence": min((row["confidence"] for row in valid if row["stage_risk"] == highest
                               and row.get("confidence") in CONFIDENCES), key=CONFIDENCES.index, default=None)
                    if valid and all(row["verification_status"] == "verified" for row in valid) and not suspended else None}


def snapshot(task: dict, evidence: dict, review_progress: dict | None = None,
             task_dir: Path | None = None) -> dict:
    if not enabled(task):
        return {}
    events = _events(evidence)
    registry = _registry(task, evidence, task_dir)
    invalidations = {row["judgment_id"]: row for row in events if row["kind"] == "invalidate"}
    latest: dict[tuple, dict] = {}
    for row in events:
        if row["kind"] == "review":
            key = tuple(row["scope"].get(field, "") for field in SCOPE if field != "product_version")
            latest[key] = row
    judgments = []
    current_version = _version(task)
    for row in latest.values():
        reason = None
        if row["scope"]["product_version"] != current_version:
            reason = "PRODUCT_VERSION_CHANGED"
        elif row["event_id"] in invalidations:
            reason = "UPSTREAM_MATERIAL_INVALIDATION"
        elif any(ref not in registry or sha256_json(registry[ref]) != digest
                 for ref, digest in row["ref_fingerprints"].items()):
            reason = "EVIDENCE_CHANGED_OR_MISSING"
        judgments.append({key: deepcopy(row[key]) for key in ("event_id", "scope", "stage_risk",
            "verification_status", "basis", "assessment_date", "evidence_refs", "outcome_refs",
            "supporting_facts", "counter_facts", "comparison", "adjacent_level_reasoning",
            "gaps", "weak_leads", "confidence", "confidence_reasoning", "review_status")}
            | {"applicability": "suspended" if reason else "current", "suspension_reason": reason,
               "right_state": row.get("right_state"),
               "right_state_evidence_refs": deepcopy(row.get("right_state_evidence_refs", [])),
               "decisive_exclusion_refs": deepcopy(row.get("decisive_exclusion_refs", [])),
               "scope_complete": row.get("scope_complete"),
               "important_exclusions_checked": row.get("important_exclusions_checked"),
               "display_grade": f"上次等级：{row['stage_risk']}（已暂停适用）" if reason else
                   "暂定低" if row["verification_status"] == "pending" and row["stage_risk"] == "低" else
                   "阶段性中" if row["verification_status"] == "pending" else
                   f"单项核实{row['stage_risk']}（待双审）",
               "prior_judgment_id": row.get("prior_judgment_id")})
    by_country: dict[tuple, list[dict]] = {}
    for row in judgments:
        key = (row["scope"]["scenario_id"], row["scope"]["jurisdiction"], row["scope"]["product_version"])
        by_country.setdefault(key, []).append(row)
    country_summaries = [_summary(rows, scope={"scenario_id": key[0], "jurisdiction": key[1],
                                    "product_version": key[2]}) for key, rows in sorted(by_country.items())]
    planned_scopes = (review_progress or {}).get("by_scope", [])
    for summary in country_summaries:
        open_plan = any(row["scenario_id"] == summary["scenario_id"] and
            row["jurisdiction"] == summary["jurisdiction"] and
            row["product_version"] == summary["product_version"] and
            row["completed"] < row["planned"] for row in
            planned_scopes)
        country_scopes = [plan_scope for plan_scope in planned_scopes if
            plan_scope["scenario_id"] == summary["scenario_id"] and
            plan_scope["jurisdiction"] == summary["jurisdiction"] and
            plan_scope["product_version"] == summary["product_version"]]
        has_all_judgments = bool(country_scopes) and all(any(row["applicability"] == "current" and
            all(row["scope"].get(key) == plan_scope.get(key) for key in
                ("scenario_id", "jurisdiction", "right_type", "product_version"))
            for row in judgments) for plan_scope in country_scopes)
        summary.update(coverage_ready_for_09C=bool(review_progress is not None and
            not open_plan and has_all_judgments), verification_status="pending", confidence=None)
        if open_plan and summary["stage_risk"] == "极低":
            summary.update(stage_risk="低", verification_status="pending", confidence=None,
                           display_grade="暂定低",
                           qualification="local_decisive_exclusion_does_not_cover_unreviewed_scope")
    by_scenario: dict[str, list[dict]] = {}
    for row in judgments:
        if row["scope"]["product_version"] == current_version or row["applicability"] == "suspended":
            by_scenario.setdefault(row["scope"]["scenario_id"], []).append(row)
    scenario_summaries = [_summary(rows, scope={"scenario_id": sid, "product_version": current_version})
                          for sid, rows in sorted(by_scenario.items())]
    primary_id = task.get("primary_scenario_id") or "product_entry"
    overall = next((row for row in scenario_summaries if row["scenario_id"] == primary_id),
                   {"scenario_id": primary_id, "product_version": current_version,
                    "stage_risk": None, "applicability": "not_established", "verification_status": "pending",
                    "confidence": None, "display_grade": "尚无已审阶段等级"})
    if overall.get("stage_risk") == "极低" and isinstance(review_progress, dict) and (
            review_progress.get("planned") is None or
            review_progress.get("completed", 0) < review_progress.get("planned", 0)):
        overall = {**overall, "stage_risk": "低", "verification_status": "pending",
                   "confidence": None, "display_grade": "暂定低",
                   "qualification": "unreviewed_necessary_scope_prevents_overall_very_low"}
    overall_scopes = [scope for scope in planned_scopes if
                      scope["scenario_id"] == primary_id and
                      scope["product_version"] == current_version]
    overall_complete = (isinstance(review_progress, dict) and
        bool(overall_scopes) and overall.get("applicability") == "current" and
        review_progress.get("planned") is not None and
        review_progress.get("completed") == review_progress.get("planned") and
        all(any(row["applicability"] == "current" and
                all(row["scope"].get(key) == scope.get(key) for key in
                    ("scenario_id", "jurisdiction", "right_type", "product_version"))
                for row in judgments) for scope in overall_scopes))
    overall = {**overall, "coverage_ready_for_09C": bool(overall_complete),
               "verification_status": "pending", "confidence": None,
               "verification_reason": "necessary coverage and independent review await 09C"}
    signals = [deepcopy(row) for row in events if row["kind"] == "signal_review"]
    for row in signals:
        row["applicability"] = "current" if row["scope"].get("product_version") == current_version and all(
            ref in registry and sha256_json(registry[ref]) == digest
            for ref, digest in row["ref_fingerprints"].items()) else "suspended"
    return {"revision": REVISION, "status": "single_review_pending_09C" if judgments else "no_reviewed_outcome",
            "judgments": judgments, "by_country": country_summaries,
            "by_scenario": scenario_summaries, "overall": overall,
            "conditional_scenarios": [row for row in scenario_summaries if row["scenario_id"] != primary_id],
            "signals": signals, "review_progress": {key: review_progress.get(key) for key in
                ("plan_version", "completed", "planned", "percentage")}
                if isinstance(review_progress, dict) else None,
            "meaning": "stage risk, verification, work progress and review status are independent"}


def project(task: dict, view: dict, evidence: dict | None, task_dir: Path | None = None) -> dict:
    if not enabled(task) or evidence is None:
        return view
    result = deepcopy(view)
    result["stage_risk"] = snapshot(task, evidence, result.get("review_progress"), task_dir)
    reviewed = {(row["scope"]["scenario_id"], row["scope"]["jurisdiction"],
                 row["scope"]["product_version"], row["scope"]["right_type"])
                for row in result["stage_risk"]["judgments"]}
    unreviewed = []
    for scope in result.get("review_progress", {}).get("by_scope_module", []):
        key = (scope["scenario_id"], scope["jurisdiction"], scope["product_version"], scope["right_type"])
        if key in reviewed:
            continue
        entries = [row for row in result.get("entries", []) if
                   all(row.get(field) in (None, "", scope[field]) for field in
                       ("scenario_id", "jurisdiction", "right_type"))]
        states = {row.get("state") for row in entries}
        state = ("waiting" if states & {"awaiting_user", "awaiting_access", "submission_unknown"}
                 else "blocked" if "blocked" in states else "in_progress" if states else "not_started")
        unreviewed.append({key: scope[key] for key in ("scenario_id", "jurisdiction", "right_type",
                          "product_version", "module_id")} | {"stage_risk": None,
                          "investigation_status": state, "review_status": "not_reviewed"})
    result["stage_risk"]["scopes_without_any_judgment"] = unreviewed
    if "work_view_sha256" in result:
        result["work_view_sha256"] = sha256_json({key: value for key, value in result.items()
            if key not in {"work_view_sha256", "review_work"}})
    from stage_review_stage_c import project as stage_review_project
    from final_review import enabled as final_enabled
    if final_enabled(task):
        risk = result.get("stage_risk", {})
        if risk.get("status") == "single_review_pending_09C":
            risk["status"] = "final_review_pending"
        for row in risk.get("judgments", []):
            if row.get("review_status") == "single_review_pending_09C":
                row["review_status"] = "final_review_pending"
        if risk.get("overall"):
            risk["overall"]["verification_reason"] = "awaiting final report review"
        return result
    return stage_review_project(task, result, evidence, task_dir)

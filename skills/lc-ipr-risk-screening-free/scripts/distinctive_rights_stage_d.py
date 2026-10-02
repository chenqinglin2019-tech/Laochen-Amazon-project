"""Module-07D scoped gaps, result changes, batch accounting and closure."""
from __future__ import annotations

from copy import deepcopy

from common import sha256_json
from distinctive_rights import (_base, _refs, _scope, _strings, _text, events)

RESULT_KINDS = {"fact", "trademark_comparison", "copyright_source",
    "copyright_relationship", "copyright_license", "trade_dress_claim", "trade_dress_regime",
    "trade_dress_use", "trade_dress_functionality", "trade_dress_comparison",
    "enforcement_scope", "enforcement_signal", "enforcement_observation"}
FOLLOWUP_OUTCOMES = {"resolved", "continue", "waiting", "limited"}
ACTION_KINDS = {"read_existing", "verify_known", "discovery", "user_fact"}


def _payload(base, request):
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _related(task, intake_id):
    return [row for row in events(task) if row.get("intake_event_id") == intake_id]


def _gap(task, request, indexed):
    base = _base(task, request)
    if (not _text(request.get("gap_id")) or not _text(request.get("question"))
            or not _text(request.get("affected_judgment"))
            or not _strings(request.get("affected_reason_codes"))
            or not _strings(request.get("affected_event_ids"), required=False)
            or not _text(request.get("existing_material_check"))
            or not _text(request.get("minimum_action"))
            or not _text(request.get("completion_condition"))
            or request.get("action_kind") not in ACTION_KINDS):
        raise ValueError("M07_GAP_INVALID")
    if request.get("unavailable_comparison") is not None:
        from trusted_api import enabled as api_enabled
        dependency = request["unavailable_comparison"]
        if (not api_enabled(task) or request.get("right_type") not in {"trademark_word", "trademark_figurative"}
                or not isinstance(dependency, dict) or not _strings(dependency.get("required_facts"))
                or not set(dependency["required_facts"]) <= {"protection_content", "representative_figures"}
                or not _text(dependency.get("reasoning")) or not _text(dependency.get("readable_parts_review"))):
            raise ValueError("M07_API_COMPARISON_DEPENDENCY_REQUIRED")
    _refs(request.get("evidence_refs", []), indexed, required=False)
    rows = {row["event_id"] for row in _related(task, base["intake_event_id"])
            if row["kind"] in RESULT_KINDS}
    if not set(request["affected_event_ids"]) <= rows:
        raise ValueError("M07_GAP_AFFECTED_RESULT_INVALID")
    if request["action_kind"] == "user_fact":
        from product_feedback import pending
        if (not _text(request.get("product_feedback_request_id"))
                or request["product_feedback_request_id"] not in
                {row.get("request_id") for row in pending(task)}):
            raise ValueError("M07_USER_FACT_FEEDBACK_REQUIRED")
    prior = next((row for row in reversed(_related(task, base["intake_event_id"]))
                  if row["kind"] == "gap" and row["gap_id"] == request["gap_id"]), None)
    if prior and (request.get("prior_gap_event_id") != prior["event_id"]
                  or not _text(request.get("revision_reasoning"))):
        raise ValueError("M07_GAP_REVISION_LINK_REQUIRED")
    return _payload(base, request)


def _followup(task, evidence, request, indexed):
    base = _base(task, request)
    related = _related(task, base["intake_event_id"])
    gap = next((row for row in reversed(related) if row["kind"] == "gap"
                and row["gap_id"] == request.get("gap_id")), None)
    if gap is None or request.get("gap_event_id") != gap["event_id"]:
        raise ValueError("M07_GAP_LINK_REQUIRED")
    if (request.get("outcome") not in FOLLOWUP_OUTCOMES
            or not _text(request.get("action_id"))
            or not _text(request.get("result_review"))
            or not _text(request.get("remaining_impact"))):
        raise ValueError("M07_FOLLOWUP_INVALID")
    _refs(request.get("evidence_refs", []), indexed, required=request["outcome"] == "resolved")
    if request.get("source_run_id") and request["source_run_id"] not in {
            row.get("run_id") for row in evidence.get("source_runs", []) if isinstance(row, dict)}:
        raise ValueError("M07_FOLLOWUP_SOURCE_RUN_UNKNOWN")
    if request["outcome"] == "resolved":
        after = related[related.index(gap) + 1:]
        results = {row["event_id"] for row in after if row["kind"] in RESULT_KINDS}
        if (not _strings(request.get("resolved_event_ids"))
                or not set(request["resolved_event_ids"]) <= results):
            raise ValueError("M07_FOLLOWUP_RESOLUTION_REVIEW_REQUIRED")
    elif not _text(request.get("next_action_or_dependency")):
        raise ValueError("M07_FOLLOWUP_DEPENDENCY_REQUIRED")
    if request["outcome"] == "continue" and not _text(request.get("next_value_reasoning")):
        raise ValueError("M07_FOLLOWUP_NEXT_VALUE_REQUIRED")
    if request["outcome"] == "limited" and (
            request.get("limit_kind") not in {"no_lawful_route", "source_unavailable_with_no_recovery",
                                               "evidence_not_obtainable_within_scope"}
            or not _text(request.get("limit_evidence"))
            or not _text(request.get("restore_condition"))):
        raise ValueError("M07_FOLLOWUP_LIMIT_BASIS_REQUIRED")
    return _payload(base, request)


def _change(task, request, indexed):
    base = _base(task, request)
    if (not _text(request.get("change_id")) or not _text(request.get("impact_reasoning"))
            or not _strings(request.get("affected_event_ids"))):
        raise ValueError("M07_CHANGE_INVALID")
    _refs(request.get("evidence_refs"), indexed)
    results = {row["event_id"] for row in _related(task, base["intake_event_id"])
               if row["kind"] in RESULT_KINDS}
    if not set(request["affected_event_ids"]) <= results:
        raise ValueError("M07_CHANGE_AFFECTED_RESULT_INVALID")
    return _payload(base, request)


def _change_review(task, request, indexed):
    base = _base(task, request)
    related = _related(task, base["intake_event_id"])
    change = next((row for row in related if row["kind"] == "change"
                   and row["event_id"] == request.get("change_event_id")), None)
    if (change is None or request.get("outcome") not in {"continues", "changed", "unknown"}
            or request.get("reviewed_affected_event_ids") != change["affected_event_ids"]
            or not _text(request.get("recheck_reasoning"))):
        raise ValueError("M07_CHANGE_REVIEW_INVALID")
    _refs(request.get("evidence_refs"), indexed)
    if request["outcome"] == "changed":
        after = related[related.index(change) + 1:]
        replacements = {row["event_id"]: row for row in after if row["kind"] in RESULT_KINDS}
        old = {row["event_id"]: row for row in related if row["event_id"] in change["affected_event_ids"]}
        mapping = request.get("replacement_by_affected")
        if (not isinstance(mapping, dict) or set(mapping) != set(old)
                or any(not _strings(ids) or not set(ids) <= set(replacements)
                       or not any(replacements[mid]["kind"] == old[old_id]["kind"] for mid in ids)
                       for old_id, ids in mapping.items())):
            raise ValueError("M07_CHANGE_REPLACEMENT_REQUIRED")
    return _payload(base, request)


def _batch(task, evidence, request, indexed):
    base = _base(task, request)
    if (not _text(request.get("batch_id"))
            or not _strings(request.get("received_evidence_refs"), required=False)
            or not _strings(request.get("received_material_event_ids"), required=False)
            or not _strings(request.get("processed_material_event_ids"), required=False)
            or not _text(request.get("disposition_reasoning"))):
        raise ValueError("M07_BATCH_INVALID")
    _refs(request["received_evidence_refs"], indexed, required=False)
    valid = {row.get("run_id") for row in evidence.get("source_runs", []) if isinstance(row, dict)}
    valid.update("import:" + ref for ref in indexed)
    if request["batch_id"] not in valid:
        raise ValueError("M07_BATCH_SOURCE_UNKNOWN")
    if request["batch_id"].startswith("import:"):
        if request["batch_id"][7:] not in request["received_evidence_refs"]:
            raise ValueError("M07_BATCH_IMPORT_REF_MISSING")
    elif any(indexed[ref].get("source_run_id") != request["batch_id"]
             for ref in request["received_evidence_refs"]):
        raise ValueError("M07_BATCH_SOURCE_BINDING_INVALID")
    dispositions = request.get("disposition_by_evidence_ref")
    if (not isinstance(dispositions, dict)
            or set(dispositions) != set(request["received_evidence_refs"])
            or any(not _text(value) for value in dispositions.values())):
        raise ValueError("M07_BATCH_DISPOSITION_REQUIRED")
    materials = {row["event_id"]: row for row in _related(task, base["intake_event_id"])
                 if row["kind"] == "material"}
    received, processed = set(request["received_material_event_ids"]), set(request["processed_material_event_ids"])
    if not received <= set(materials) or not processed <= received:
        raise ValueError("M07_BATCH_MATERIAL_INVALID")
    if any(not set(materials[mid]["evidence_refs"]) <= set(request["received_evidence_refs"])
           for mid in received):
        raise ValueError("M07_BATCH_SOURCE_MATERIAL_MISMATCH")
    unread = request.get("unread_disposition_reasons", {})
    if (not isinstance(unread, dict) or any(
            not isinstance(reason, dict)
            or reason.get("kind") not in {"out_of_scope", "duplicate", "not_needed"}
            or not _text(reason.get("reasoning")) for reason in unread.values())
            or not set(unread) <= processed
            or any(materials[mid]["status"] == "acquired" and mid not in unread for mid in processed)):
        raise ValueError("M07_BATCH_UNREAD_MATERIAL_CANNOT_COMPLETE")
    return _payload(base, request)


def _handoff(task, request):
    base = _base(task, request)
    if (request.get("destination") not in {"08", "09", "10"}
            or not _strings(request.get("result_event_ids"))
            or not _text(request.get("handoff_reasoning"))):
        raise ValueError("M07_HANDOFF_INVALID")
    results = {row["event_id"] for row in _related(task, base["intake_event_id"])
               if row["kind"] in RESULT_KINDS | {"gap", "followup", "change_review"}}
    if not set(request["result_event_ids"]) <= results:
        raise ValueError("M07_HANDOFF_RESULT_INVALID")
    return _payload(base, request)


def _close(task, evidence, candidates, ledger, supplement, request):
    from distinctive_rights import project
    base = _base(task, request)
    if (request.get("status") not in {"normal_complete", "waiting", "limited"}
            or not _text(request.get("completion_reasoning"))):
        raise ValueError("M07_CLOSE_INVALID")
    view = project(task, evidence, candidates, ledger, supplement=supplement)
    scope = next((row for row in view["scopes"] if _scope(row) == _scope(request)), None)
    if scope is None or scope["intake_event_id"] != base["intake_event_id"]:
        raise ValueError("M07_CLOSE_CURRENT_SCOPE_REQUIRED")
    blocking = [row for row in scope["blockers"] if row["reason"] not in {
        "M07_SUBSTANTIVE_REVIEW_PENDING", "M07_CLOSE_PENDING"}]
    hard = [row for row in blocking if row["reason"] in {
        "M07_CANDIDATE_MATERIAL_UNACCOUNTED", "M07_MATERIAL_UNACCOUNTED",
        "M07_MATERIAL_UNREAD", "M07_BATCH_MATERIAL_UNREAD"}]
    if hard:
        raise ValueError("M07_CLOSE_BATCH_AND_READING_REQUIRED")
    if request["status"] == "normal_complete" and blocking:
        raise ValueError("M07_CLOSE_OBLIGATIONS_OPEN")
    related = _related(task, base["intake_event_id"])
    gaps = {row["event_id"]: row for row in related if row["kind"] == "gap"}
    covered = request.get("covered_gap_event_ids", [])
    if not _strings(covered, required=False) or not set(covered) <= set(gaps):
        raise ValueError("M07_CLOSE_GAP_COVERAGE_INVALID")
    if request["status"] != "normal_complete":
        if not blocking or not covered:
            raise ValueError("M07_CLOSE_DEPENDENCY_REQUIRED")
        outcome = "waiting" if request["status"] == "waiting" else "limited"
        reasons = set()
        for gap_id in covered:
            gap = gaps[gap_id]
            follow = next((row for row in reversed(related) if row["kind"] == "followup"
                           and row["gap_event_id"] == gap_id), None)
            if follow is None or follow["outcome"] != outcome:
                raise ValueError("M07_CLOSE_GAP_STATE_MISMATCH")
            reasons.update(gap["affected_reason_codes"])
            reasons.add("M07_GAP_OPEN")
        if not {row["reason"] for row in blocking} <= reasons:
            raise ValueError("M07_CLOSE_UNCOVERED_OBLIGATION")
        if request["status"] == "limited" and (
                not _text(request.get("limit_impact"))
                or not _text(request.get("restore_condition"))
                or type(request.get("no_pending_recovery")) is not bool
                or not request["no_pending_recovery"]):
            raise ValueError("M07_CLOSE_LIMIT_BASIS_REQUIRED")
    elif covered:
        raise ValueError("M07_CLOSE_UNNEEDED_GAP_COVERAGE")
    return {**base, "status": request["status"], "completion_reasoning": request["completion_reasoning"],
            "covered_gap_event_ids": covered, "blocker_sha256": sha256_json(blocking),
            "limit_impact": request.get("limit_impact"),
            "restore_condition": request.get("restore_condition"),
            "no_pending_recovery": request.get("no_pending_recovery")}


def record_stage_d(task, evidence, candidates, ledger, supplement, request, indexed):
    kind = request["kind"]
    if kind == "gap":
        return _gap(task, request, indexed)
    if kind == "followup":
        return _followup(task, evidence, request, indexed)
    if kind == "change":
        return _change(task, request, indexed)
    if kind == "change_review":
        return _change_review(task, request, indexed)
    if kind == "batch":
        return _batch(task, evidence, request, indexed)
    if kind == "handoff":
        return _handoff(task, request)
    return _close(task, evidence, candidates, ledger, supplement, request)


def project_stage_d(task, intake, related, candidate, blockers, *, unusable_facts=None,
                    substantive=None, handoff=None, api_limit=None):
    blockers = [row for row in blockers if row["reason"] != "M07_SUBSTANTIVE_REVIEW_PENDING"]
    batches = [row for row in related if row["kind"] == "batch"]
    materials = [row for row in related if row["kind"] == "material"]
    accounted = {ref for batch in batches for ref in batch["received_evidence_refs"]}
    processed = {mid for batch in batches for mid in batch["processed_material_event_ids"]}
    candidate_refs = {ref for ref in candidate.get("evidence_refs", []) if _text(ref)}
    candidate_refs.update(row.get("evidence_id") for row in candidate.get("sources", [])
                          if isinstance(row, dict) and _text(row.get("evidence_id")))
    if handoff:
        candidate_refs.update(ref for ref in handoff.get("evidence_refs", []) if _text(ref))
    for ref in sorted(candidate_refs - accounted):
        blockers.append({"reason": "M07_CANDIDATE_MATERIAL_UNACCOUNTED", "evidence_ref": ref})
    for material in materials:
        if material["event_id"] not in processed:
            blockers.append({"reason": "M07_MATERIAL_UNACCOUNTED", "material_event_id": material["event_id"]})
    gaps = [row for row in related if row["kind"] == "gap"]
    follows = [row for row in related if row["kind"] == "followup"]
    latest_gaps = {row["gap_id"]: row for row in gaps}
    for gap in latest_gaps.values():
        follow = next((row for row in reversed(follows) if row["gap_event_id"] == gap["event_id"]), None)
        if follow is None or follow["outcome"] != "resolved":
            state = (follow or {}).get("outcome", "open")
            blockers.append({"reason": "M07_GAP_OPEN", "gap_id": gap["gap_id"],
                             "gap_event_id": gap["event_id"], "state": state,
                             "action_kind": gap["action_kind"]})
    changed = set()
    suspended = set()
    for change in (row for row in related if row["kind"] == "change"):
        review = next((row for row in reversed(related) if row["kind"] == "change_review"
                       and row["change_event_id"] == change["event_id"]), None)
        if review is None or review["outcome"] == "unknown":
            suspended.update(change["affected_event_ids"])
            blockers.append({"reason": "M07_CHANGE_REVIEW_PENDING", "change_event_id": change["event_id"]})
        elif review["outcome"] == "changed":
            changed.update(change["affected_event_ids"])
    suspended.update(unusable_facts or set())
    available = {row["event_id"] for row in related if row["kind"] in RESULT_KINDS | {
        "gap", "followup", "change_review"} and row["event_id"] not in suspended | changed}
    substantive = substantive or {}
    for kind in ("trademark_comparison", "copyright_source", "copyright_relationship",
                 "copyright_license", "trade_dress_claim", "trade_dress_regime",
                 "trade_dress_use", "trade_dress_functionality", "trade_dress_comparison",
                 "enforcement_scope"):
        if substantive.get(kind + "_currently_usable") is False:
            available.difference_update(row["event_id"] for row in related if row["kind"] == kind)
    handoffs = [{"event_id": row["event_id"], "destination": row["destination"],
                 "currently_usable_event_ids": sorted(set(row["result_event_ids"]) & available),
                 "needs_recheck_event_ids": sorted(set(row["result_event_ids"]) - available)}
                for row in related if row["kind"] == "handoff"]
    close = next((row for row in reversed(related) if row["kind"] == "scope_close"), None)
    status = "in_progress"
    if close:
        blocking = [row for row in blockers if row["reason"] != "M07_CLOSE_PENDING"]
        current_tail = next((row for row in reversed(related) if row["kind"] != "handoff"), None)
        if current_tail and current_tail["event_id"] == close["event_id"] and sha256_json(blocking) == close["blocker_sha256"]:
            status = close["status"]
    if status == "in_progress":
        blockers.append({"reason": "M07_CLOSE_PENDING"})
    if status == "limited" and api_limit:
        # Only the closed gaps tied to these reviewed unknown API fields may
        # inherit the source limitation. Other substantive work stays open.
        basis = set(api_limit["delivery_limit"]["basis_event_ids"])
        bound_gaps = [gap for gap in latest_gaps.values()
            if gap["event_id"] in close.get("covered_gap_event_ids", [])
            and set(gap.get("affected_event_ids", [])) & basis]
        reason_codes = {code for gap in bound_gaps for code in gap.get("affected_reason_codes", [])}
        gap_ids = {gap["event_id"] for gap in bound_gaps}
        # A missing comparison, unread material or unresolved change is still
        # executable work. Only recorded unknown findings can be limited.
        permitted = {"M07_TRACK_FACT_PENDING", "M07_HANDOFF_GAP_OPEN",
            "M07_TRADEMARK_DIMENSION_OPEN", "M07_TRADEMARK_COMPONENT_OPEN",
            "M07_TRADEMARK_COMPOSITION_OPEN", "M07_COPYRIGHT_QUESTION_OPEN",
            "M07_COPYRIGHT_LICENSE_SCOPE_OPEN"}
        reason_codes &= permitted
        tracks = {row.get("track") for row in related if row["event_id"] in basis}
        blocked_comparison = next((gap for gap in bound_gaps if
            "M07_TRADEMARK_COMPARISON_PENDING" in gap.get("affected_reason_codes", [])
            and gap.get("unavailable_comparison")
            and set(gap["unavailable_comparison"]["required_facts"]) <= set(api_limit["required_facts"])
            and any(row["event_id"] in basis & set(gap.get("affected_event_ids", []))
                and row.get("api_fact") in gap["unavailable_comparison"]["required_facts"] for row in related)), None)
        can_compare = any(row.get("status") == "sufficient_for_listed_tracks"
            and "registration" in row.get("tracks", []) for row in materials)
        for blocker in blockers:
            if ((blocker["reason"] == "M07_GAP_OPEN" and blocker.get("gap_event_id") in gap_ids)
                    or (blocker["reason"] in reason_codes and
                        (not blocker.get("track") or blocker["track"] in tracks) and
                        (not blocker.get("fact_event_id") or blocker["fact_event_id"] in basis))):
                blocker.update(state="limited", source_dependency=api_limit)
            elif blocker["reason"] == "M07_TRADEMARK_COMPARISON_PENDING" and blocked_comparison and not can_compare:
                blocker.update(state="limited", source_dependency=api_limit,
                    comparison_limitation=deepcopy(blocked_comparison["unavailable_comparison"]))
    return {"status": status, "blockers": blockers, "batch_event_ids": [row["event_id"] for row in batches],
            "handoffs": handoffs, "currently_usable_event_ids": sorted(available),
            "close_event_id": close["event_id"] if close else None}

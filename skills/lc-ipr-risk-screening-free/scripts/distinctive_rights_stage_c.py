"""Module-07C trade-dress and public-enforcement evidence contracts.

These are bounded factual reviews. They neither select a risk level nor close
module 07; the parent ledger owns append-only storage and selected scope.
"""
from __future__ import annotations

from copy import deepcopy
import trusted_api

from distinctive_rights import (_base, _day, _intake, _judgment, _refs, _review_material,
                                _scope, _strings, _text, _timestamp, _unusable_facts, events)

FEATURE_KINDS = {"shape", "color", "layout", "decoration", "other_observed"}
REGIMES = {"us_trade_dress", "unregistered_mark", "unfair_competition", "other", "unknown"}
EVENT_LAYERS = {"claim", "platform_action", "procedure", "formal_decision"}
SIGNAL_KINDS = {"original", "repost", "summary"}


def _payload(base, request):
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _latest(task, intake_id, kind):
    return next((row for row in reversed(events(task)) if row["kind"] == kind
                 and row.get("intake_event_id") == intake_id), None)


def _claim(task, request, indexed):
    base = _base(task, request)
    if request["right_type"] != "trade_dress":
        raise ValueError("M07_TRADE_DRESS_SCOPE_REQUIRED")
    _refs(request.get("evidence_refs"), indexed)
    intake = _intake(task, _scope(request))
    if (request.get("appearance_version") != intake["subject_version"]
            or request.get("product_version_sha256") != intake["product_version_sha256"]
            or request.get("use_context") != intake["use_context"]
            or request.get("claimed_object_id") != intake["object_id"]
            or request.get("boundary_status") not in {"defined", "unknown"}
            or not _text(request.get("boundary_reasoning"))):
        raise ValueError("M07_TRADE_DRESS_CLAIM_SCOPE_INVALID")
    features = request.get("features")
    if not isinstance(features, list) or (request["boundary_status"] == "defined" and not features):
        raise ValueError("M07_TRADE_DRESS_FEATURES_REQUIRED")
    seen = set()
    for row in features:
        if (not isinstance(row, dict) or not _text(row.get("feature_id"))
                or row["feature_id"] in seen or row.get("kind") not in FEATURE_KINDS
                or row.get("appearance_version") != intake["subject_version"]
                or not _text(row.get("description"))):
            raise ValueError("M07_TRADE_DRESS_FEATURE_INVALID")
        _refs(row.get("evidence_refs"), indexed)
        if not set(row["evidence_refs"]) <= set(request["evidence_refs"]):
            raise ValueError("M07_TRADE_DRESS_FEATURE_SOURCE_INVALID")
        seen.add(row["feature_id"])
    if request["boundary_status"] == "defined" and not _text(request.get("combination_relation")):
        raise ValueError("M07_TRADE_DRESS_COMBINATION_REQUIRED")
    if request["boundary_status"] == "unknown" and not _text(request.get("boundary_gap")):
        raise ValueError("M07_TRADE_DRESS_BOUNDARY_GAP_REQUIRED")
    return _payload(base, request)


def _current_claim(task, base, request):
    claim = _latest(task, base["intake_event_id"], "trade_dress_claim")
    if claim is None or request.get("claim_event_id") != claim["event_id"]:
        raise ValueError("M07_TRADE_DRESS_CURRENT_CLAIM_REQUIRED")
    return claim


def _regime(task, request, indexed):
    base, materials = _review_material(task, request, indexed)
    claim = _current_claim(task, base, request)
    if request["right_type"] != "trade_dress":
        raise ValueError("M07_TRADE_DRESS_SCOPE_REQUIRED")
    if (request.get("regime") not in REGIMES
            or request.get("basis_status") not in {"reviewed", "unknown"}
            or not _text(request.get("legal_basis_or_gap"))
            or (request["regime"] == "us_trade_dress" and request["jurisdiction"] != "US")
            or (request["basis_status"] == "reviewed" and request["regime"] == "unknown")):
        raise ValueError("M07_TRADE_DRESS_REGIME_INVALID")
    conditions = request.get("conditions")
    if not isinstance(conditions, list) or (request["basis_status"] == "reviewed" and not conditions):
        raise ValueError("M07_TRADE_DRESS_CONDITIONS_REQUIRED")
    seen = set()
    for row in conditions:
        if (not isinstance(row, dict) or not _text(row.get("condition_id"))
                or row["condition_id"] in seen or not _text(row.get("question"))):
            raise ValueError("M07_TRADE_DRESS_CONDITION_INVALID")
        _judgment(row.get("review"), {"supported", "contradicted", "unknown", "not_applicable"},
                  set(request["evidence_refs"]))
        seen.add(row["condition_id"])
    if request["basis_status"] == "reviewed" and not any(
            (row["source_form"] in {"official_decision", "original_page"}
             or "original_content" in trusted_api.public_material_scope(task, row, indexed, require_full_text=True))
            and row["status"] == "sufficient_for_listed_tracks" for row in materials):
        raise ValueError("M07_TRADE_DRESS_RULE_SOURCE_REQUIRED")
    return _payload(base, request)


def _current_regime(task, base, request):
    regime = _latest(task, base["intake_event_id"], "trade_dress_regime")
    if regime is None or request.get("regime_event_id") != regime["event_id"]:
        raise ValueError("M07_TRADE_DRESS_CURRENT_REGIME_REQUIRED")
    return regime


def _use(task, request, indexed):
    base, _ = _review_material(task, request, indexed)
    claim = _current_claim(task, base, request)
    _current_regime(task, base, request)
    if request["right_type"] != "trade_dress":
        raise ValueError("M07_TRADE_DRESS_SCOPE_REQUIRED")
    public, identifying = request.get("public_use"), request.get("source_identification")
    available = set(request["evidence_refs"])
    _judgment(public, {"supported", "contradicted", "unknown"}, available)
    _judgment(identifying, {"supported", "contradicted", "unknown"}, available)
    if public["outcome"] == "supported" and (
            not _text(public.get("actor")) or not _day(public.get("use_date"))
            or public.get("appearance_version") != claim["appearance_version"]
            or public.get("jurisdiction") != request["jurisdiction"]):
        raise ValueError("M07_TRADE_DRESS_USE_TIME_SCOPE_REQUIRED")
    if identifying["outcome"] == "supported" and (
            identifying.get("basis_type") not in {"consumer_recognition", "source_indicating_presentation",
                                                  "specific_market_evidence"}
            or not _text(identifying.get("specific_indicator"))):
        raise ValueError("M07_TRADE_DRESS_SOURCE_IDENTIFICATION_REQUIRED")
    return _payload(base, request)


def _functionality(task, request, indexed):
    base, _ = _review_material(task, request, indexed)
    claim = _current_claim(task, base, request)
    _current_regime(task, base, request)
    if request["right_type"] != "trade_dress":
        raise ValueError("M07_TRADE_DRESS_SCOPE_REQUIRED")
    features = request.get("feature_reviews")
    ids = {row["feature_id"] for row in claim["features"]}
    if not isinstance(features, list) or {row.get("feature_id") for row in features if isinstance(row, dict)} != ids or len(features) != len(ids):
        raise ValueError("M07_TRADE_DRESS_FUNCTIONALITY_FEATURES_REQUIRED")
    available = set(request["evidence_refs"])
    for row in features:
        if not isinstance(row, dict) or row.get("source_nature") not in {
                "verified_fact", "technical_claim", "product_claim", "inference", "unknown"}:
            raise ValueError("M07_TRADE_DRESS_FUNCTIONALITY_SOURCE_INVALID")
        _judgment(row.get("review"), {"verified_functional", "nonfunctional", "claimed_functional", "unknown"}, available)
        if row["review"]["outcome"] == "verified_functional" and row["source_nature"] != "verified_fact":
            raise ValueError("M07_TRADE_DRESS_FUNCTIONALITY_OVERCLAIM")
    whole = request.get("combination_review")
    _judgment(whole, {"verified_functional", "nonfunctional", "unknown"}, available)
    if whole["outcome"] == "verified_functional" and any(
            row["review"]["outcome"] != "verified_functional" for row in features):
        raise ValueError("M07_TRADE_DRESS_COMBINATION_OVERCLAIM")
    return _payload(base, request)


def _comparison(task, request, indexed):
    base, _ = _review_material(task, request, indexed)
    claim = _current_claim(task, base, request)
    _current_regime(task, base, request)
    if request["right_type"] != "trade_dress" or request.get("use_context") != claim["use_context"]:
        raise ValueError("M07_TRADE_DRESS_COMPARISON_SCOPE_INVALID")
    visual, confusion = request.get("visual"), request.get("source_confusion")
    available = set(request["evidence_refs"])
    _judgment(visual, {"corresponds", "differs", "unknown"}, available)
    _judgment(confusion, {"supported", "contradicted", "unknown"}, available)
    if visual["outcome"] != "unknown" and (
            not _text(visual.get("similarities")) or not _text(visual.get("differences"))
            or not _text(visual.get("whole_relationship"))):
        raise ValueError("M07_TRADE_DRESS_VISUAL_BASIS_REQUIRED")
    if confusion["outcome"] != "unknown" and (
            not _text(confusion.get("use_basis")) or not _text(confusion.get("source_basis"))):
        raise ValueError("M07_TRADE_DRESS_CONFUSION_BASIS_REQUIRED")
    return _payload(base, request)


def _read_signal_materials(task, base, request, indexed):
    _refs(request.get("evidence_refs"), indexed)
    ids = request.get("material_event_ids")
    materials = {row["event_id"]: row for row in events(task) if row["kind"] == "material"
                 and row["intake_event_id"] == base["intake_event_id"]}
    if not _strings(ids) or not set(ids) <= set(materials):
        raise ValueError("M07_ENFORCEMENT_MATERIAL_REQUIRED")
    reviewed = [materials[mid] for mid in ids]
    if (any(not row["reading_locations"] for row in reviewed)
            or not set(request["evidence_refs"]) <= set().union(
                *(set(row["evidence_refs"]) for row in reviewed))):
        raise ValueError("M07_ENFORCEMENT_READING_REQUIRED")
    return reviewed


def _enforcement_scope(task, request, indexed):
    base = _base(task, request)
    _refs(request.get("evidence_refs"), indexed, required=False)
    if type(request.get("needed")) is not bool or not _text(request.get("reasoning")):
        raise ValueError("M07_ENFORCEMENT_SCOPE_INVALID")
    planned = request.get("planned_query_ids")
    if not _strings(planned, required=request["needed"]) or (not request["needed"] and planned):
        raise ValueError("M07_ENFORCEMENT_PLAN_INVALID")
    prior = _latest(task, base["intake_event_id"], "enforcement_scope")
    if prior and (request.get("prior_scope_event_id") != prior["event_id"]
                  or not _text(request.get("change_reasoning"))):
        raise ValueError("M07_ENFORCEMENT_SCOPE_CHANGE_LINK_REQUIRED")
    return _payload(base, request)


def _signal(task, request, indexed):
    base = _base(task, request)
    materials = _read_signal_materials(task, base, request, indexed)
    if (not _text(request.get("event_key")) or not _text(request.get("event_identity_basis"))
            or request.get("source_kind") not in SIGNAL_KINDS
            or not _text(request.get("source_document_id"))
            or not _text(request.get("party_identity"))
            or not _text(request.get("right_or_claim"))
            or not _text(request.get("affected_product"))
            or not _text(request.get("event_jurisdiction"))
            or request.get("association") not in {"verified", "unknown", "unrelated"}
            or not _text(request.get("association_reasoning"))):
        raise ValueError("M07_ENFORCEMENT_SIGNAL_INVALID")
    if request["association"] == "verified" and (
            request["source_kind"] != "original"
            or request["event_jurisdiction"] != request["jurisdiction"]
            or not _strings(request.get("association_evidence_refs"))
            or not set(request["association_evidence_refs"]) <= set(request["evidence_refs"])
            or not all(_text(request.get(key)) for key in (
                "party_match_basis", "product_match_basis", "right_match_basis"))
            or not _strings(request.get("fact_event_ids"))):
        raise ValueError("M07_ENFORCEMENT_ASSOCIATION_UNPROVEN")
    if request.get("fact_event_ids"):
        facts = {row["event_id"] for row in events(task) if row["kind"] == "fact"
                 and row["intake_event_id"] == base["intake_event_id"]}
        if (not _strings(request["fact_event_ids"])
                or not set(request["fact_event_ids"]) <= facts
                or set(request["fact_event_ids"]) & _unusable_facts(task, base["intake_event_id"])):
            raise ValueError("M07_ENFORCEMENT_FACT_BINDING_INVALID")
    layers = request.get("layers")
    if not isinstance(layers, dict) or set(layers) != EVENT_LAYERS:
        raise ValueError("M07_ENFORCEMENT_LAYERS_REQUIRED")
    for key, row in layers.items():
        _judgment(row, {"documented", "unknown", "not_applicable"}, set(request["evidence_refs"]))
        if row["outcome"] == "documented" and not _text(row.get("statement")):
            raise ValueError("M07_ENFORCEMENT_LAYER_STATEMENT_REQUIRED")
        if key == "formal_decision" and row["outcome"] == "documented" and (
                not _text(row.get("decision_level"))
                or not any(material["source_form"] == "official_decision"
                           and set(row["evidence_refs"]) <= set(material["evidence_refs"])
                           and material["status"] == "sufficient_for_listed_tracks"
                           for material in materials)):
            raise ValueError("M07_ENFORCEMENT_FORMAL_DECISION_SOURCE_REQUIRED")
    times = request.get("time_points")
    if not isinstance(times, list):
        raise ValueError("M07_ENFORCEMENT_TIMES_INVALID")
    for point in times:
        if (not isinstance(point, dict) or point.get("kind") not in {
                "event", "publication", "effective", "source_checked"}
                or not _day(point.get("date")) or not _text(point.get("meaning"))):
            raise ValueError("M07_ENFORCEMENT_TIME_INVALID")
        _refs(point.get("evidence_refs"), indexed)
        if not set(point["evidence_refs"]) <= set(request["evidence_refs"]):
            raise ValueError("M07_ENFORCEMENT_TIME_SOURCE_INVALID")
    if request.get("current_status") not in {"supported", "unknown"}:
        raise ValueError("M07_ENFORCEMENT_CURRENT_STATUS_INVALID")
    if request["current_status"] == "supported" and (
            request["source_kind"] != "original" or not _timestamp(request.get("source_checked_at"))
            or not _text(request.get("current_status_statement"))):
        raise ValueError("M07_ENFORCEMENT_CURRENT_SOURCE_REQUIRED")
    previous = next((row for row in reversed(events(task)) if row["kind"] == "enforcement_signal"
                     and row["intake_event_id"] == base["intake_event_id"]
                     and row["event_key"] == request["event_key"]), None)
    if previous and (request.get("prior_signal_event_id") != previous["event_id"]
                     or not _text(request.get("update_reasoning"))):
        raise ValueError("M07_ENFORCEMENT_UPDATE_LINK_REQUIRED")
    if request["source_kind"] != "original" and not _text(request.get("original_source_gap_or_ref")):
        raise ValueError("M07_ENFORCEMENT_ORIGINAL_SOURCE_GAP_REQUIRED")
    return _payload(base, request)


def _observation(task, evidence, request):
    base = _base(task, request)
    scope = _latest(task, base["intake_event_id"], "enforcement_scope")
    if (scope is None or not scope["needed"]
            or request.get("enforcement_scope_event_id") != scope["event_id"]
            or request.get("query_id") not in scope["planned_query_ids"]):
        raise ValueError("M07_ENFORCEMENT_CURRENT_SCOPE_REQUIRED")
    outcome = request.get("outcome")
    if (outcome not in {"no_result", "failed", "limited", "not_queried"}
            or not _text(request.get("query_id")) or not _text(request.get("query_scope"))
            or not _text(request.get("reasoning"))):
        raise ValueError("M07_ENFORCEMENT_OBSERVATION_INVALID")
    if outcome == "not_queried":
        if request.get("source_run_id"):
            raise ValueError("M07_ENFORCEMENT_NOT_QUERIED_HAS_RUN")
    else:
        run = next((row for row in evidence.get("source_runs", []) if isinstance(row, dict)
                    and row.get("run_id") == request.get("source_run_id")), None)
        statuses = {"no_result": {"no_result"}, "failed": {"failed", "error"},
                    "limited": {"access_limited", "blocked"}}
        if (run is None or run.get("query_id") != request["query_id"]
                or run.get("jurisdiction") != request["jurisdiction"]
                or run.get("status") not in statuses[outcome]
                or run.get("right_type") not in {request["right_type"], "enforcement"}):
            raise ValueError("M07_ENFORCEMENT_RECEIPT_REQUIRED")
    return _payload(base, request)


def record_stage_c(task, evidence, request, indexed):
    kind = request["kind"]
    if kind == "trade_dress_claim":
        return _claim(task, request, indexed)
    if kind == "trade_dress_regime":
        return _regime(task, request, indexed)
    if kind == "trade_dress_use":
        return _use(task, request, indexed)
    if kind == "trade_dress_functionality":
        return _functionality(task, request, indexed)
    if kind == "trade_dress_comparison":
        return _comparison(task, request, indexed)
    if kind == "enforcement_scope":
        return _enforcement_scope(task, request, indexed)
    if kind == "enforcement_signal":
        return _signal(task, request, indexed)
    return _observation(task, evidence, request)


def project_stage_c(task, intake, related, right_type, unusable_facts):
    reviews, blockers = {}, []
    if right_type == "trade_dress":
        latest = {kind: next((row for row in reversed(related) if row["kind"] == kind), None)
                  for kind in ("trade_dress_claim", "trade_dress_regime", "trade_dress_use",
                               "trade_dress_functionality", "trade_dress_comparison")}
        claim = latest["trade_dress_claim"]
        regime = latest["trade_dress_regime"]
        for kind, reason in (("trade_dress_claim", "M07_TRADE_DRESS_CLAIM_PENDING"),
                             ("trade_dress_regime", "M07_TRADE_DRESS_REGIME_PENDING"),
                             ("trade_dress_use", "M07_TRADE_DRESS_USE_PENDING"),
                             ("trade_dress_functionality", "M07_TRADE_DRESS_FUNCTIONALITY_PENDING"),
                             ("trade_dress_comparison", "M07_TRADE_DRESS_COMPARISON_PENDING")):
            row = latest[kind]
            reviews[kind + "_event_id"] = row["event_id"] if row else None
            stale = bool(row and set(row.get("fact_event_ids", [])) & unusable_facts)
            if kind not in {"trade_dress_claim"} and row:
                stale = stale or claim is None or row["claim_event_id"] != claim["event_id"]
            if kind in {"trade_dress_use", "trade_dress_functionality", "trade_dress_comparison"} and row:
                stale = stale or regime is None or row["regime_event_id"] != regime["event_id"]
                stale = stale or not reviews.get("trade_dress_regime_currently_usable", False)
            reviews[kind + "_currently_usable"] = bool(row and not stale)
            if row is None:
                blockers.append({"reason": reason})
            elif stale:
                blockers.append({"reason": "M07_TRADE_DRESS_RECHECK_PENDING", "review_kind": kind})
            elif kind == "trade_dress_claim" and row["boundary_status"] == "unknown":
                blockers.append({"reason": "M07_TRADE_DRESS_BOUNDARY_OPEN", "gap": row["boundary_gap"]})
            elif kind == "trade_dress_regime" and row["basis_status"] == "unknown":
                blockers.append({"reason": "M07_TRADE_DRESS_RULE_OPEN"})
            elif kind == "trade_dress_use":
                for axis in ("public_use", "source_identification"):
                    if row[axis]["outcome"] == "unknown":
                        blockers.append({"reason": "M07_TRADE_DRESS_USE_AXIS_OPEN", "axis": axis})
            elif kind == "trade_dress_functionality":
                if row["combination_review"]["outcome"] == "unknown":
                    blockers.append({"reason": "M07_TRADE_DRESS_FUNCTIONALITY_OPEN"})
            elif kind == "trade_dress_comparison":
                for axis in ("visual", "source_confusion"):
                    if row[axis]["outcome"] == "unknown":
                        blockers.append({"reason": "M07_TRADE_DRESS_COMPARISON_AXIS_OPEN", "axis": axis})
    signals = {}
    for row in (item for item in related if item["kind"] == "enforcement_signal"):
        signals.setdefault(row["event_key"], []).append(row)
    reviews["enforcement_signals"] = []
    for key, rows in signals.items():
        # A later repost expands the source chain, not the underlying event or
        # the reviewed status from an original record.
        authority = next((row for row in reversed(rows) if row["source_kind"] == "original"), rows[-1])
        usable = not bool(set(authority.get("fact_event_ids", [])) & unusable_facts)
        reviews["enforcement_signals"].append({"event_key": key,
            "latest_event_id": rows[-1]["event_id"], "reviewed_event_id": authority["event_id"],
            "source_event_ids": [row["event_id"] for row in rows],
            "association": authority["association"] if usable else "unknown",
            "current_status": authority["current_status"] if usable else "unknown",
            "currently_usable": usable, "event_count": 1})
    observations = [row for row in related if row["kind"] == "enforcement_observation"]
    scope = next((row for row in reversed(related) if row["kind"] == "enforcement_scope"), None)
    reviews["enforcement_scope_event_id"] = scope["event_id"] if scope else None
    reviews["enforcement_needed"] = scope["needed"] if scope else None
    reviews["enforcement_observations"] = [{"event_id": row["event_id"],
        "outcome": row["outcome"], "query_id": row["query_id"], "query_scope": row["query_scope"]}
        for row in observations]
    if scope is None:
        blockers.append({"reason": "M07_ENFORCEMENT_SCOPE_PENDING"})
    elif scope["needed"] and not signals and not observations:
        blockers.append({"reason": "M07_ENFORCEMENT_SEARCH_PENDING"})
    if scope and scope["needed"]:
        checked = {row["query_id"] for row in observations
                   if row.get("enforcement_scope_event_id") == scope["event_id"]}
        for query_id in scope["planned_query_ids"]:
            if query_id not in checked:
                blockers.append({"reason": "M07_ENFORCEMENT_SOURCE_OPEN",
                                 "query_id": query_id, "outcome": "not_queried"})
    for row in observations:
        if scope and row.get("enforcement_scope_event_id") == scope["event_id"] and row["outcome"] in {"failed", "limited", "not_queried"}:
            blockers.append({"reason": "M07_ENFORCEMENT_SOURCE_OPEN", "query_id": row["query_id"],
                             "outcome": row["outcome"]})
    for row in reviews["enforcement_signals"]:
        if row["association"] == "unknown" or row["current_status"] == "unknown":
            blockers.append({"reason": "M07_ENFORCEMENT_SIGNAL_OPEN", "event_key": row["event_key"]})
    return {"reviews": reviews, "blockers": blockers}

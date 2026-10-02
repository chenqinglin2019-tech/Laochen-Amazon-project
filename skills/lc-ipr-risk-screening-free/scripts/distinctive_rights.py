"""Versioned module-07A intake, material and parallel factual tracks.

This ledger records reviewed scope and evidence. It performs no lookup, legal
conclusion, risk grading or module-07 completion decision.
"""
from __future__ import annotations

import trusted_api
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_json, stable_id

REVISION = "distinctive-rights-v1"
EVENTS = "distinctive_rights_events"
KINDS = {"intake", "material", "fact", "observation", "impact", "impact_review",
         "trademark_comparison", "copyright_source", "copyright_relationship",
         "copyright_license", "trade_dress_claim", "trade_dress_regime",
         "trade_dress_use", "trade_dress_functionality", "trade_dress_comparison",
         "enforcement_scope", "enforcement_signal", "enforcement_observation"}
KINDS.update({"gap", "followup", "change", "change_review", "batch", "handoff", "scope_close"})
RIGHTS = {"trademark_word", "trademark_figurative", "copyright", "trade_dress"}
TRACKS = {"registration", "public_facts"}
SOURCE_FORMS = {"official_register", "official_decision", "original_page", "original_work",
                "product_original", "license", "summary", "ocr", "translation", "other"}
TIME_KINDS = {"page_label", "historical_publication", "event", "event_effective",
              "license_start", "license_end", "update"}
SCOPE = ("candidate_id", "scenario_id", "jurisdiction", "right_type")
MARK_DIMENSIONS = {"overall", "text", "pronunciation", "meaning", "graphic",
                   "goods_services", "actual_use", "specimen"}
COPYRIGHT_PARTIES = {"publisher", "author", "owner", "licensor"}
COPYRIGHT_QUESTIONS = {"protectable_expression", "expression_correspondence",
                       "access_or_copying", "independent_creation"}
LICENSE_DIMENSIONS = {"licensor_authority", "licensee", "asset_version", "use",
                      "jurisdiction", "term", "modification", "sublicense"}


def enabled(task: dict) -> bool:
    revision = task.get("distinctive_rights_revision")
    if revision is None:
        return False
    if revision != REVISION or task.get("triage_stage_revision") != "candidate-triage-stage-v1":
        raise ValueError("M07_REVISION_INVALID")
    return True


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value, *, required=True) -> bool:
    return (isinstance(value, list) and (bool(value) or not required)
            and all(_text(item) for item in value) and len(value) == len(set(value)))


def _day(value) -> bool:
    if not _text(value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _timestamp(value) -> bool:
    if not _text(value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _scope(row):
    return tuple(row.get(key) for key in SCOPE)


def events(task: dict) -> list[dict]:
    history = task.get(EVENTS, [])
    if not isinstance(history, list):
        raise ValueError("M07_EVENTS_INVALID")
    prior = ""
    for row in history:
        if (not isinstance(row, dict) or row.get("kind") not in KINDS
                or row.get("previous_event_id") != prior
                or row.get("event_id") != stable_id("M07", task["task_id"],
                    sha256_json({key: value for key, value in row.items() if key != "event_id"}))):
            raise ValueError("M07_EVENTS_CHANGED")
        prior = row["event_id"]
    return history


def _append(task, kind, payload):
    history = events(task)
    row = {"kind": kind, **deepcopy(payload), "recorded_at": now_iso(),
           "previous_event_id": history[-1]["event_id"] if history else ""}
    row["event_id"] = stable_id("M07", task["task_id"], sha256_json(row))
    task.setdefault(EVENTS, []).append(row)
    return row


def _context(task_dir):
    from annotate_materiality import load_materiality_ledger
    from decision_workflow import evidence_index
    from workflow_v24 import scenario_supplement
    task = load_json(task_dir / "task.json")
    evidence = load_json(task_dir / "evidence.json")
    candidates = load_json(task_dir / "normalized-candidates.json")
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    return task, evidence, candidates, ledger, supplement, evidence_index(evidence, supplement)


def _refs(value, indexed, *, required=True):
    if not _strings(value, required=required) or not set(value) <= set(indexed):
        raise ValueError("M07_EVIDENCE_REFS_INVALID")


def _intake(task, scope):
    return next((row for row in reversed(events(task)) if row["kind"] == "intake"
                 and _scope(row) == scope), None)


def _current(task, evidence, candidates, ledger, supplement, scope):
    from annotate_materiality import iter_candidates
    from decision_workflow import effective_decision
    matches = [(collection, item) for collection, item in iter_candidates(candidates)
               if item.get("candidate_id") == scope[0]]
    if len(matches) != 1:
        raise ValueError("M07_CANDIDATE_UNKNOWN")
    current = effective_decision(task, ledger, *matches[0], *scope[1:],
                                 evidence=evidence, supplement=supplement)
    if current.get("decision") != "selected" or not current.get("current"):
        raise ValueError("M07_CURRENT_SELECTED_REQUIRED")
    return current


def _validate_intake(task, evidence, candidates, ledger, supplement, indexed, request):
    from candidate_triage_stage import events as triage_events
    scope = _scope(request)
    annotation = _current(task, evidence, candidates, ledger, supplement, scope)["annotation"]
    handoff = next((row for row in reversed(triage_events(task)) if row["kind"] == "selected_handoff"
                    and row["event_id"] == request.get("selected_handoff_event_id")
                    and _scope(row) == scope), None)
    if (handoff is None or handoff["annotation_id"] != annotation["annotation_id"]
            or handoff["annotation_sha256"] != sha256_json(annotation)
            or not _day(request.get("assessment_date"))):
        raise ValueError("M07_CURRENT_HANDOFF_AND_DATE_REQUIRED")
    object_ids = handoff.get("candidate_relation", {}).get("product_object_ids", [])
    if request.get("object_id") not in object_ids:
        raise ValueError("M07_INCLUDED_OBJECT_REQUIRED")
    if (not _text(request.get("subject_id")) or not _text(request.get("subject_version"))
            or not _text(request.get("use_context"))):
        raise ValueError("M07_SUBJECT_AND_USE_REQUIRED")
    _refs(request.get("subject_evidence_refs"), indexed)
    product = task.get("product") or {}
    inventory = product.get("mark_inventory" if scope[3].startswith("trademark") else "assets")
    if isinstance(inventory, list) and inventory:
        identity = "mark_id" if scope[3].startswith("trademark") else "asset_id"
        matches = [item for item in inventory if isinstance(item, dict)
                   and item.get(identity) == request["subject_id"]
                   and scope[1] in item.get("scenario_ids", [])
                   and (identity == "mark_id" or scope[3] in item.get("right_types", []))]
        if (len(matches) != 1 or not set(request["subject_evidence_refs"])
                <= set(matches[0].get("evidence_refs", []))):
            raise ValueError("M07_SUBJECT_INVENTORY_BINDING_REQUIRED")
    tracks = request.get("tracks")
    if (not isinstance(tracks, dict) or set(tracks) != TRACKS
            or not all(isinstance(row, dict) and type(row.get("needed")) is bool
                       and _text(row.get("reasoning")) for row in tracks.values())
            or not any(row["needed"] for row in tracks.values())):
        raise ValueError("M07_TRACK_DECISIONS_REQUIRED")
    prior = _intake(task, scope)
    same = ("selected_handoff_event_id", "assessment_date", "object_id", "subject_id",
            "subject_version", "use_context", "subject_evidence_refs", "tracks")
    if prior and any(prior[key] != request[key] for key in same) and (
            request.get("prior_intake_event_id") != prior["event_id"]
            or not _text(request.get("new_round_reasoning"))):
        raise ValueError("M07_NEW_ROUND_REVIEW_REQUIRED")
    return {**{key: request[key] for key in SCOPE},
            **{key: deepcopy(request[key]) for key in same},
            "assessment_date_basis": request["assessment_date_basis"],
            "annotation_id": annotation["annotation_id"],
            "product_version_sha256": handoff["product_version_sha256"],
            "candidate_version_sha256": handoff["candidate_version_sha256"],
            "verification_gaps": handoff["verification_gaps"],
            **({"prior_intake_event_id": prior["event_id"],
                "new_round_reasoning": request["new_round_reasoning"]}
               if prior and request.get("prior_intake_event_id") else {})}


def _base(task, request):
    intake = _intake(task, _scope(request))
    if intake is None or request.get("intake_event_id") != intake["event_id"]:
        raise ValueError("M07_INTAKE_REQUIRED")
    if request.get("assessment_date") != intake["assessment_date"]:
        raise ValueError("M07_ASSESSMENT_DATE_CHANGED")
    return {**{key: request[key] for key in SCOPE},
            "intake_event_id": intake["event_id"], "assessment_date": intake["assessment_date"],
            "object_id": intake["object_id"], "subject_id": intake["subject_id"],
            "subject_version": intake["subject_version"],
            "product_version_sha256": intake["product_version_sha256"],
            "candidate_version_sha256": intake["candidate_version_sha256"]}


def _material(task, request, indexed):
    base = _base(task, request)
    _refs(request.get("evidence_refs"), indexed)
    if (not _text(request.get("document_id")) or not _text(request.get("document_version"))
            or request.get("source_form") not in (SOURCE_FORMS | ({"trusted_api_record"} if trusted_api.enabled(task) else set()))
            or request.get("status") not in {"acquired", "read", "sufficient_for_listed_tracks"}
            or not _timestamp(request.get("acquired_at"))
            or not _strings(request.get("tracks")) or set(request["tracks"]) - TRACKS
            or not _strings(request.get("reading_locations"), required=False)
            or not _text(request.get("support_reasoning"))):
        raise ValueError("M07_MATERIAL_INVALID")
    if request.get("source_form") == "trusted_api_record":
        from trusted_api import material_support
        if not material_support(task, request, indexed):
            raise ValueError("M07_API_RECORD_IDENTITY_OR_RECEIPT_INVALID")
        public_scope = trusted_api.public_material_scope(task, request, indexed)
        if public_scope:
            request = {**request, "api_public_content_scope": sorted(public_scope)}
    if request["status"] != "acquired" and not request["reading_locations"]:
        raise ValueError("M07_MATERIAL_READING_REQUIRED")
    if request["status"] == "acquired" and request["reading_locations"]:
        raise ValueError("M07_ACQUIRED_NOT_READ")
    if request.get("reuse_from_event_id"):
        from specialty_analysis import events as m06_events
        prior = next((row for row in m06_events(task) if row["kind"] == "material"
                      and row["event_id"] == request["reuse_from_event_id"]), None)
        if (prior is None or prior["scenario_id"] != request["scenario_id"]
                or prior["jurisdiction"] != request["jurisdiction"]
                or prior["document_id"] != request["document_id"]
                or prior["document_version"] != request["document_version"]
                or prior["acquired_at"] != request["acquired_at"]
                or not set(request["evidence_refs"]) <= set(prior["evidence_refs"])
                or not _text(request.get("reuse_applicability_reasoning"))):
            raise ValueError("M07_REUSE_BASIS_INVALID")
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _fact(task, request, indexed, *, evidence=None):
    base = _base(task, request)
    intake = _intake(task, _scope(request))
    if (request.get("track") not in TRACKS or request.get("outcome") not in {"supported", "unknown", "conflicted"}
            or not _text(request.get("fact_id")) or not _text(request.get("statement"))
            or not _text(request.get("as_of_reasoning")) or not _strings(request.get("material_event_ids"))):
        raise ValueError("M07_FACT_INVALID")
    _refs(request.get("evidence_refs"), indexed)
    materials = {row["event_id"]: row for row in events(task) if row["kind"] == "material"
                 and row["intake_event_id"] == base["intake_event_id"]}
    if not set(request["material_event_ids"]) <= set(materials):
        raise ValueError("M07_FACT_MATERIAL_REQUIRED")
    if not any(request["track"] in materials[mid]["tracks"]
               and set(request["evidence_refs"]) <= set(materials[mid]["evidence_refs"])
               and materials[mid]["reading_locations"] for mid in request["material_event_ids"]):
        raise ValueError("M07_PURPOSE_READING_REQUIRED")
    if request["outcome"] == "supported" and not any(
            materials[mid]["status"] == "sufficient_for_listed_tracks"
            and request["track"] in materials[mid]["tracks"]
            and set(request["evidence_refs"]) <= set(materials[mid]["evidence_refs"])
            for mid in request["material_event_ids"]):
        raise ValueError("M07_PURPOSE_SUFFICIENCY_REQUIRED")
    if (trusted_api.enabled(task) and request["track"] == "public_facts" and request["outcome"] == "supported"
            and all(materials[mid]["source_form"] == trusted_api.FORM for mid in request["material_event_ids"])):
        public_fact = request.get("api_fact")
        if public_fact not in {"public_identity", "source_excerpt", "original_content", "disclosure"} or not any(
                trusted_api.material_fact(task, materials[mid], indexed, public_fact,
                                          right_identity=request.get("right_identity"), evidence=evidence)
                for mid in request["material_event_ids"]):
            raise ValueError("M07_PUBLIC_API_FACT_NOT_RETURNED")
    if request["track"] == "registration" and request["outcome"] == "supported" and (
            not _text(request.get("right_identity")) or not _timestamp(request.get("source_checked_at"))
            or not any(materials[mid]["source_form"] in {"official_register", "official_decision"}
                       or (request.get("api_fact") in {"identity", "territory", "current_status", "rights_holder", "goods_services", "mark_text", "representative_figures"}
                           and trusted_api.material_fact(task, materials[mid], indexed, request["api_fact"],
                                                         right_identity=request.get("right_identity"), evidence=evidence))
                       for mid in request["material_event_ids"])):
        raise ValueError("M07_REGISTRATION_OFFICIAL_BASIS_REQUIRED")
    points = request.get("time_points", [])
    if not isinstance(points, list):
        raise ValueError("M07_TIME_POINTS_INVALID")
    for point in points:
        if (not isinstance(point, dict) or point.get("kind") not in TIME_KINDS
                or not _day(point.get("date")) or not _text(point.get("meaning"))):
            raise ValueError("M07_TIME_POINT_INVALID")
        _refs(point.get("evidence_refs"), indexed)
        if not set(point["evidence_refs"]) <= set(request["evidence_refs"]):
            raise ValueError("M07_TIME_POINT_SOURCE_INVALID")
    if request["outcome"] == "conflicted" and (
            not _text(request.get("conflict_explanation"))
            or not _strings(request.get("conflicting_evidence_refs"))):
        raise ValueError("M07_CONFLICT_BASIS_REQUIRED")
    if request.get("resolves_fact_event_ids"):
        prior = {row["event_id"]: row for row in events(task) if row["kind"] == "fact"
                 and row["intake_event_id"] == base["intake_event_id"]
                 and row["track"] == request["track"] and row["outcome"] == "conflicted"}
        if (request["outcome"] != "supported" or not _strings(request["resolves_fact_event_ids"])
                or not set(request["resolves_fact_event_ids"]) <= set(prior)
                or not _text(request.get("adoption_reasoning"))):
            raise ValueError("M07_CONFLICT_RESOLUTION_INVALID")
    if request.get("resolves_handoff_gaps") and (
            request["outcome"] != "supported" or not _strings(request["resolves_handoff_gaps"])
            or not set(request["resolves_handoff_gaps"]) <= set(intake["verification_gaps"])):
        raise ValueError("M07_HANDOFF_GAP_RESOLUTION_INVALID")
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _observation(task, request, evidence):
    base = _base(task, request)
    if (request.get("track") not in TRACKS or request.get("outcome") not in {"no_result", "failed", "unknown"}
            or not _text(request.get("reasoning")) or not _text(request.get("source_run_id"))):
        raise ValueError("M07_OBSERVATION_INVALID")
    run = next((row for row in evidence.get("source_runs", []) if isinstance(row, dict)
                and row.get("run_id") == request["source_run_id"]), None)
    if (run is None or run.get("jurisdiction") != request["jurisdiction"]
            or (request["outcome"] == "no_result" and run.get("status") != "no_result")
            or (request["outcome"] == "failed" and run.get("status") not in {"failed", "error", "blocked"})):
        raise ValueError("M07_OBSERVATION_RECEIPT_REQUIRED")
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _impact(task, request, indexed):
    base = _base(task, request)
    _refs(request.get("evidence_refs"), indexed)
    if (not _text(request.get("impact_reasoning")) or not _strings(request.get("affected_fact_event_ids"))):
        raise ValueError("M07_IMPACT_INVALID")
    facts = {row["event_id"] for row in events(task) if row["kind"] == "fact"
             and row["intake_event_id"] == base["intake_event_id"]}
    if not set(request["affected_fact_event_ids"]) <= facts:
        raise ValueError("M07_IMPACT_TARGET_INVALID")
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _impact_review(task, request, indexed):
    base = _base(task, request)
    _refs(request.get("evidence_refs"), indexed)
    impact = next((row for row in events(task) if row["kind"] == "impact"
                   and row["event_id"] == request.get("impact_event_id")
                   and row["intake_event_id"] == base["intake_event_id"]), None)
    if (impact is None or request.get("outcome") not in {"continues", "changed", "unknown"}
            or not _text(request.get("recheck_reasoning"))
            or request.get("reviewed_affected_fact_event_ids") != impact["affected_fact_event_ids"]):
        raise ValueError("M07_IMPACT_REVIEW_INVALID")
    if request["outcome"] == "changed":
        history = events(task)
        after = history[history.index(impact) + 1:]
        replacements = {row["event_id"]: row for row in after if row["kind"] == "fact"
                        and row["intake_event_id"] == base["intake_event_id"]}
        mapping = request.get("replacement_by_affected")
        originals = {row["event_id"]: row for row in history if row["event_id"] in impact["affected_fact_event_ids"]}
        if (not isinstance(mapping, dict) or set(mapping) != set(originals)
                or any(not _strings(ids) or not set(ids) <= set(replacements)
                       or any(replacements[mid]["track"] != originals[old_id]["track"] for mid in ids)
                       for old_id, ids in mapping.items())):
            raise ValueError("M07_IMPACT_REPLACEMENT_REQUIRED")
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _unusable_facts(task, intake_id):
    related = [row for row in events(task) if row.get("intake_event_id") == intake_id]
    unusable = set()
    for impact in (row for row in related if row["kind"] == "impact"):
        review = next((row for row in reversed(related) if row["kind"] == "impact_review"
                       and row["impact_event_id"] == impact["event_id"]), None)
        if review is None or review["outcome"] in {"unknown", "changed"}:
            unusable.update(impact["affected_fact_event_ids"])
    return unusable


def _review_material(task, request, indexed):
    """A comparison may cite only material actually read for this intake."""
    base = _base(task, request)
    _refs(request.get("evidence_refs"), indexed)
    if not _strings(request.get("material_event_ids")):
        raise ValueError("M07_REVIEW_MATERIAL_REQUIRED")
    materials = {row["event_id"]: row for row in events(task) if row["kind"] == "material"
                 and row["intake_event_id"] == base["intake_event_id"]}
    if not set(request["material_event_ids"]) <= set(materials):
        raise ValueError("M07_REVIEW_MATERIAL_REQUIRED")
    reviewed = [materials[mid] for mid in request["material_event_ids"]]
    if (any(not row["reading_locations"] for row in reviewed)
            or not set(request["evidence_refs"]) <= set().union(
                *(set(row["evidence_refs"]) for row in reviewed))):
        raise ValueError("M07_REVIEW_READING_REQUIRED")
    fact_ids = request.get("fact_event_ids")
    facts = {row["event_id"] for row in events(task) if row["kind"] == "fact"
             and row["intake_event_id"] == base["intake_event_id"]}
    if not _strings(fact_ids) or not set(fact_ids) <= facts:
        raise ValueError("M07_REVIEW_FACT_BINDING_REQUIRED")
    unusable = _unusable_facts(task, base["intake_event_id"])
    if set(fact_ids) & unusable:
        raise ValueError("M07_REVIEW_AFFECTED_FACT_UNUSABLE")
    return base, reviewed


def _judgment(row, allowed, available, *, require_known_refs=True):
    if (not isinstance(row, dict) or row.get("outcome") not in allowed
            or not _text(row.get("reasoning")) or not _strings(row.get("evidence_refs"), required=False)
            or not set(row["evidence_refs"]) <= available):
        raise ValueError("M07_REVIEW_JUDGMENT_INVALID")
    if row["outcome"] in {"unknown", "not_applicable"}:
        if not _text(row.get("dependency_or_basis")):
            raise ValueError("M07_REVIEW_DEPENDENCY_REQUIRED")
    elif require_known_refs and not row["evidence_refs"]:
        raise ValueError("M07_REVIEW_EVIDENCE_REQUIRED")


def _trademark_comparison(task, request, indexed):
    base, materials = _review_material(task, request, indexed)
    intake = _intake(task, _scope(request))
    if request["right_type"] not in {"trademark_word", "trademark_figurative"}:
        raise ValueError("M07_TRADEMARK_SCOPE_REQUIRED")
    if (request.get("mark_version") != intake["subject_version"]
            or request.get("use_context") != intake["use_context"]
            or request.get("mark_form") not in {"plain_text", "stylized_text", "graphic", "composite"}
            or not _text(request.get("candidate_sign_description"))):
        raise ValueError("M07_TRADEMARK_UNIT_INVALID")
    inventory = (task.get("product") or {}).get("mark_inventory")
    if isinstance(inventory, list) and inventory:
        mark = next((row for row in inventory if isinstance(row, dict)
                     and row.get("mark_id") == intake["subject_id"]), None)
        if mark is None or mark.get("form") != request["mark_form"]:
            raise ValueError("M07_TRADEMARK_FORM_MISMATCH")
    dimensions = request.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != MARK_DIMENSIONS:
        raise ValueError("M07_TRADEMARK_DIMENSIONS_REQUIRED")
    available = set(request["evidence_refs"])
    for row in dimensions.values():
        _judgment(row, {"corresponds", "differs", "unknown", "not_applicable"}, available)
    # A missing proposed image/use cannot be converted into a documented difference.
    if (any(dimensions[key]["outcome"] == "unknown" for key in
            ("actual_use", "goods_services", "graphic" if request["mark_form"] == "composite" else "actual_use"))
            and dimensions["overall"]["outcome"] != "unknown"):
        raise ValueError("M07_TRADEMARK_OVERALL_UNSUPPORTED")
    if (intake["tracks"]["registration"]["needed"] is False
            and dimensions["specimen"]["outcome"] != "not_applicable"):
        raise ValueError("M07_TRADEMARK_SPECIMEN_NOT_ESTABLISHED")
    if dimensions["specimen"]["outcome"] in {"corresponds", "differs"} and not any(
            (row["source_form"] in {"official_register", "official_decision"}
             or trusted_api.material_fact(task, row, indexed, "representative_figures"))
            and row["status"] == "sufficient_for_listed_tracks" for row in materials):
        raise ValueError("M07_TRADEMARK_SPECIMEN_OFFICIAL_REQUIRED")
    parts = request.get("components")
    if not isinstance(parts, list):
        raise ValueError("M07_TRADEMARK_COMPONENTS_INVALID")
    if request["mark_form"] == "composite":
        if (len(parts) < 2 or {row.get("kind") for row in parts if isinstance(row, dict)}
                != {"text", "graphic"} or not isinstance(request.get("composition_relation"), dict)):
            raise ValueError("M07_TRADEMARK_COMPOSITION_REQUIRED")
        _judgment(request["composition_relation"],
                  {"corresponds", "differs", "unknown"}, available)
    elif parts or request.get("composition_relation"):
        raise ValueError("M07_TRADEMARK_COMPONENTS_NOT_APPLICABLE")
    for part in parts:
        if not isinstance(part, dict) or not _text(part.get("component_id")) or part.get("kind") not in {"text", "graphic"}:
            raise ValueError("M07_TRADEMARK_COMPONENT_INVALID")
        _judgment(part.get("comparison"), {"corresponds", "differs", "unknown"}, available)
    if len({part["component_id"] for part in parts}) != len(parts):
        raise ValueError("M07_TRADEMARK_COMPONENT_DUPLICATE")
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _copyright_source(task, request, indexed):
    base, materials = _review_material(task, request, indexed)
    intake = _intake(task, _scope(request))
    if (request["right_type"] != "copyright"
            or request.get("intended_asset_version") != intake["subject_version"]
            or not _text(request.get("source_work_id"))
            or not _text(request.get("source_work_version"))
            or not _text(request.get("actually_reviewed_content"))
            or not _text(request.get("content_location"))
            or not _text(request.get("version_correspondence_reasoning"))):
        raise ValueError("M07_COPYRIGHT_SOURCE_INVALID")
    if not any(row["source_form"] in {"original_page", "original_work", "product_original"}
               or "original_content" in trusted_api.public_material_scope(task, row, indexed)
               for row in materials):
        raise ValueError("M07_COPYRIGHT_ORIGINAL_REQUIRED")
    points = request.get("time_points")
    if not isinstance(points, list):
        raise ValueError("M07_COPYRIGHT_TIME_INVALID")
    for point in points:
        if (not isinstance(point, dict) or point.get("kind") not in {"page_label", "historical_publication", "update"}
                or not _day(point.get("date")) or not _text(point.get("meaning"))):
            raise ValueError("M07_COPYRIGHT_TIME_INVALID")
        _refs(point.get("evidence_refs"), indexed)
        if not set(point["evidence_refs"]) <= set(request["evidence_refs"]):
            raise ValueError("M07_COPYRIGHT_TIME_SOURCE_INVALID")
        if point["kind"] == "historical_publication" and (
                point.get("content_version") != request["source_work_version"]
                or not _text(point.get("content_correspondence"))):
            raise ValueError("M07_COPYRIGHT_HISTORY_CONTENT_REQUIRED")
    earliest = request.get("earliest_found")
    if earliest is not None and (not isinstance(earliest, dict)
            or not _day(earliest.get("date")) or not _text(earliest.get("content_correspondence"))
            or earliest.get("claim") != "earliest_found_in_reviewed_sources"
            or not any(point["kind"] == "historical_publication" and point["date"] == earliest["date"]
                       for point in points)):
        raise ValueError("M07_COPYRIGHT_EARLIEST_OVERCLAIM")
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _copyright_relationship(task, request, indexed):
    base, materials = _review_material(task, request, indexed)
    if request["right_type"] != "copyright":
        raise ValueError("M07_COPYRIGHT_SCOPE_REQUIRED")
    source = next((row for row in reversed(events(task)) if row["kind"] == "copyright_source"
                   and row["intake_event_id"] == base["intake_event_id"]), None)
    if (source is None or source["event_id"] != request.get("source_event_id")
            or set(source["fact_event_ids"]) & _unusable_facts(task, base["intake_event_id"])):
        raise ValueError("M07_COPYRIGHT_SOURCE_REQUIRED")
    parties, questions = request.get("parties"), request.get("questions")
    if not isinstance(parties, dict) or set(parties) != COPYRIGHT_PARTIES:
        raise ValueError("M07_COPYRIGHT_PARTIES_REQUIRED")
    if not isinstance(questions, dict) or set(questions) != COPYRIGHT_QUESTIONS:
        raise ValueError("M07_COPYRIGHT_QUESTIONS_REQUIRED")
    available = set(request["evidence_refs"])
    for row in parties.values():
        _judgment(row, {"supported", "conflicted", "unknown"}, available)
        if row["outcome"] == "supported" and (not _text(row.get("identity"))
                or not _text(row.get("relationship_basis"))):
            raise ValueError("M07_COPYRIGHT_IDENTITY_BASIS_REQUIRED")
    for role in ("owner", "licensor"):
        if parties[role]["outcome"] == "supported" and not any(
                (material["source_form"] in {"license", "official_decision", "original_work"}
                 or "original_content" in trusted_api.public_material_scope(task, material, indexed))
                and material["status"] == "sufficient_for_listed_tracks"
                and set(parties[role]["evidence_refs"]) <= set(material["evidence_refs"])
                for material in materials):
            raise ValueError("M07_COPYRIGHT_RIGHTS_CHAIN_REQUIRED")
    for row in questions.values():
        _judgment(row, {"supported", "contradicted", "unknown", "not_applicable"}, available)
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def _copyright_license(task, request, indexed):
    base, materials = _review_material(task, request, indexed)
    intake = _intake(task, _scope(request))
    if (request["right_type"] != "copyright"
            or request.get("intended_asset_version") != intake["subject_version"]
            or request.get("requested_use") != intake["use_context"]
            or request.get("requested_jurisdiction") != request["jurisdiction"]
            or not _text(request.get("requested_licensee"))):
        raise ValueError("M07_COPYRIGHT_LICENSE_SCOPE_INVALID")
    source = next((row for row in reversed(events(task)) if row["kind"] == "copyright_source"
                   and row["intake_event_id"] == base["intake_event_id"]), None)
    if (source is None or request.get("source_event_id") != source["event_id"]
            or request.get("licensed_source_work_id") != source["source_work_id"]
            or request.get("licensed_source_work_version") != source["source_work_version"]
            or set(source["fact_event_ids"]) & _unusable_facts(task, base["intake_event_id"])):
        raise ValueError("M07_COPYRIGHT_LICENSE_WORK_BINDING_REQUIRED")
    dimensions = request.get("coverage")
    if not isinstance(dimensions, dict) or set(dimensions) != LICENSE_DIMENSIONS:
        raise ValueError("M07_COPYRIGHT_LICENSE_COVERAGE_REQUIRED")
    available = set(request["evidence_refs"])
    for row in dimensions.values():
        _judgment(row, {"covered", "not_covered", "unknown", "not_applicable"}, available)
    license_materials = [row for row in materials if row["source_form"] == "license"
                         and row["status"] == "sufficient_for_listed_tracks"]
    if (any(row["outcome"] == "covered" for row in dimensions.values())
            and not license_materials):
        raise ValueError("M07_COPYRIGHT_LICENSE_INSTRUMENT_REQUIRED")
    for row in dimensions.values():
        if row["outcome"] == "covered" and not any(
                set(row["evidence_refs"]) <= set(material["evidence_refs"])
                for material in license_materials):
            raise ValueError("M07_COPYRIGHT_LICENSE_INSTRUMENT_REQUIRED")
    if dimensions["term"]["outcome"] == "covered":
        start, end = request.get("license_start"), request.get("license_end")
        if not _day(start) or (end is not None and not _day(end)) or not (
                start <= intake["assessment_date"] and (end is None or intake["assessment_date"] <= end)):
            raise ValueError("M07_COPYRIGHT_LICENSE_TERM_INVALID")
    if request.get("overall_coverage") == "covered":
        if any(row["outcome"] not in {"covered", "not_applicable"} for row in dimensions.values()):
            raise ValueError("M07_COPYRIGHT_LICENSE_OVERCLAIM")
        if any(dimensions[key]["outcome"] != "covered" for key in (
                "licensor_authority", "licensee", "asset_version", "use", "jurisdiction", "term")):
            raise ValueError("M07_COPYRIGHT_LICENSE_OVERCLAIM")
        relation = next((row for row in reversed(events(task)) if row["kind"] == "copyright_relationship"
                         and row["intake_event_id"] == base["intake_event_id"]), None)
        unusable = _unusable_facts(task, base["intake_event_id"])
        if (relation is None or source is None or relation["event_id"] != request.get("relationship_event_id")
                or relation["source_event_id"] != source["event_id"]
                or set(relation["fact_event_ids"] + source["fact_event_ids"]) & unusable
                or relation["parties"]["licensor"]["outcome"] != "supported"):
            raise ValueError("M07_COPYRIGHT_LICENSOR_UNVERIFIED")
    elif request.get("overall_coverage") not in {"partial", "unknown", "not_covered"}:
        raise ValueError("M07_COPYRIGHT_LICENSE_OUTCOME_INVALID")
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base}}


def record(task_dir: Path, request: dict) -> dict:
    from provider_utils import evidence_lock
    task_dir = task_dir.resolve()
    with evidence_lock(task_dir):
        task, evidence, candidates, ledger, supplement, indexed = _context(task_dir)
        if not enabled(task) or task.get("state") == "completed":
            raise ValueError("M07_NOT_WRITABLE")
        kind = request.get("kind")
        if kind == "intake" and not request.get("assessment_date"):
            request = {**request, "assessment_date": datetime.now().astimezone().date().isoformat(),
                       "assessment_date_basis": "module_07_start_local_date"}
        elif kind == "intake":
            request = {**request, "assessment_date_basis": request.get("assessment_date_basis")
                       or "recorded_module_07_input_date"}
        if (kind not in KINDS or not _text(request.get("reviewer"))
                or not _text(request.get("reason")) or _scope(request)[3] not in RIGHTS
                or any(not _text(value) for value in _scope(request))):
            raise ValueError("M07_INPUT_INVALID")
        if kind == "intake":
            payload = _validate_intake(task, evidence, candidates, ledger, supplement, indexed, request)
            prior = _intake(task, _scope(request))
            if prior and all(prior[key] == payload[key] for key in (
                    "selected_handoff_event_id", "assessment_date", "object_id", "subject_id",
                    "subject_version", "use_context", "subject_evidence_refs", "tracks")):
                return prior
        else:
            _current(task, evidence, candidates, ledger, supplement, _scope(request))
            if kind == "material":
                request = trusted_api.bind_material_candidate(task, request, candidates)
                payload = _material(task, request, indexed)
            elif kind == "fact":
                payload = _fact(task, request, indexed, evidence=evidence)
            elif kind == "observation":
                payload = _observation(task, request, evidence)
            elif kind == "impact":
                payload = _impact(task, request, indexed)
            elif kind == "impact_review":
                payload = _impact_review(task, request, indexed)
            elif kind == "trademark_comparison":
                payload = _trademark_comparison(task, request, indexed)
            elif kind == "copyright_source":
                payload = _copyright_source(task, request, indexed)
            elif kind == "copyright_relationship":
                payload = _copyright_relationship(task, request, indexed)
            elif kind == "copyright_license":
                payload = _copyright_license(task, request, indexed)
            elif kind in {"trade_dress_claim", "trade_dress_regime", "trade_dress_use",
                          "trade_dress_functionality", "trade_dress_comparison", "enforcement_scope",
                          "enforcement_signal", "enforcement_observation"}:
                from distinctive_rights_stage_c import record_stage_c
                payload = record_stage_c(task, evidence, request, indexed)
            else:
                from distinctive_rights_stage_d import record_stage_d
                payload = record_stage_d(task, evidence, candidates, ledger, supplement, request, indexed)
        event = _append(task, kind, {**payload, "reviewer": request["reviewer"], "reason": request["reason"]})
        atomic_write_json(task_dir / "task.json", task)
        return event


def project(task, evidence, candidates, ledger, *, supplement=None, source_work=None,
            plan=None, capabilities=None, task_dir=None):
    """Project current 07A factual work; 07D owns module completion."""
    if not enabled(task):
        return {"revision": None}
    from candidate_triage_stage import events as triage_events
    from decision_workflow import triage_summary
    history = events(task)
    handoffs = [row for row in triage_events(task) if row["kind"] == "selected_handoff"]
    selected = [row for row in triage_summary(task, candidates, ledger, evidence=evidence,
                supplement=supplement)["records"] if row.get("current")
                and row.get("decision") == "selected" and row.get("right_type") in RIGHTS]
    scopes = []
    for current in selected:
        scope = _scope(current)
        relevant = [row for row in history if _scope(row) == scope]
        handoff = next((row for row in reversed(handoffs) if _scope(row) == scope
                        and row["annotation_id"] == current["annotation"]["annotation_id"]
                        and row["annotation_sha256"] == sha256_json(current["annotation"])), None)
        intake = next((row for row in reversed(relevant) if row["kind"] == "intake"
                       and handoff and row["selected_handoff_event_id"] == handoff["event_id"]), None)
        blockers = []
        if handoff is None:
            blockers.append({"reason": "M07_SELECTED_HANDOFF_PENDING"})
        if intake is None:
            blockers.append({"reason": "M07_INTAKE_PENDING"})
        facts, materials, observations = [], [], []
        substantive = {}
        if intake:
            related = [row for row in relevant if row.get("intake_event_id") == intake["event_id"]]
            materials = [row for row in related if row["kind"] == "material"]
            observations = [row for row in related if row["kind"] == "observation"]
            changed = {ref for row in related if row["kind"] == "impact_review" and row["outcome"] == "changed"
                       for ref in row["reviewed_affected_fact_event_ids"]}
            pending = set()
            for impact in (row for row in related if row["kind"] == "impact"):
                review = next((row for row in reversed(related) if row["kind"] == "impact_review"
                               and row["impact_event_id"] == impact["event_id"]), None)
                if review is None or review["outcome"] == "unknown":
                    pending.update(impact["affected_fact_event_ids"])
                    blockers.append({"reason": "M07_IMPACT_REVIEW_PENDING", "impact_event_id": impact["event_id"]})
            facts = [row for row in related if row["kind"] == "fact" and row["event_id"] not in changed]
            unusable_facts = changed | pending
            resolved = {ref for row in facts if row["outcome"] == "supported"
                        and row["event_id"] not in pending
                        for ref in row.get("resolves_fact_event_ids", [])}
            for fact in facts:
                if fact["outcome"] == "conflicted" and fact["event_id"] not in resolved:
                    blockers.append({"reason": "M07_FACT_CONFLICT", "fact_event_id": fact["event_id"]})
            irrelevant_unread = {mid for row in related if row["kind"] == "batch"
                for mid in row.get("unread_disposition_reasons", {})}
            for material in materials:
                later_read = any(row["kind"] == "material" and row["status"] != "acquired"
                    and row["document_id"] == material["document_id"]
                    and row["document_version"] == material["document_version"]
                    and set(material["tracks"]) <= set(row["tracks"])
                    and set(material["evidence_refs"]) <= set(row["evidence_refs"])
                    for row in related[related.index(material) + 1:])
                if material["status"] == "acquired" and not later_read and material["event_id"] not in irrelevant_unread:
                    blockers.append({"reason": "M07_MATERIAL_UNREAD", "material_event_id": material["event_id"]})
            for gap in intake["verification_gaps"]:
                if not any(gap in row.get("resolves_handoff_gaps", []) for row in facts
                           if row["outcome"] == "supported" and row["event_id"] not in pending):
                    blockers.append({"reason": "M07_HANDOFF_GAP_OPEN", "handoff_gap": gap})
            for track, decision in intake["tracks"].items():
                if decision["needed"] and not any(row["track"] == track and row["outcome"] == "supported"
                                                  and row["event_id"] not in pending for row in facts):
                    blockers.append({"reason": "M07_TRACK_FACT_PENDING", "track": track})
            if current["right_type"] in {"trademark_word", "trademark_figurative"}:
                comparison = next((row for row in reversed(related)
                                   if row["kind"] == "trademark_comparison"), None)
                stale = bool(comparison and set(comparison["fact_event_ids"]) & unusable_facts)
                substantive["trademark_comparison_event_id"] = comparison["event_id"] if comparison else None
                substantive["trademark_comparison_currently_usable"] = bool(comparison and not stale)
                if comparison is None:
                    blockers.append({"reason": "M07_TRADEMARK_COMPARISON_PENDING"})
                elif stale:
                    blockers.append({"reason": "M07_TRADEMARK_COMPARISON_RECHECK_PENDING"})
                else:
                    for dimension, detail in comparison["dimensions"].items():
                        if detail["outcome"] == "unknown":
                            blockers.append({"reason": "M07_TRADEMARK_DIMENSION_OPEN",
                                             "dimension": dimension, "dependency": detail["dependency_or_basis"]})
                    for part in comparison["components"]:
                        if part["comparison"]["outcome"] == "unknown":
                            blockers.append({"reason": "M07_TRADEMARK_COMPONENT_OPEN",
                                             "component_id": part["component_id"]})
                    if (comparison.get("composition_relation") or {}).get("outcome") == "unknown":
                        blockers.append({"reason": "M07_TRADEMARK_COMPOSITION_OPEN"})
            elif current["right_type"] == "copyright":
                latest_copyright = {kind: next((item for item in reversed(related)
                    if item["kind"] == kind), None) for kind in (
                    "copyright_source", "copyright_relationship", "copyright_license")}
                for kind, reason in (("copyright_source", "M07_COPYRIGHT_SOURCE_PENDING"),
                                     ("copyright_relationship", "M07_COPYRIGHT_RELATIONSHIP_PENDING"),
                                     ("copyright_license", "M07_COPYRIGHT_LICENSE_PENDING")):
                    row = latest_copyright[kind]
                    substantive[kind + "_event_id"] = row["event_id"] if row else None
                    stale = bool(row and set(row["fact_event_ids"]) & unusable_facts)
                    if kind == "copyright_relationship" and row and latest_copyright["copyright_source"]:
                        stale = stale or row["source_event_id"] != latest_copyright["copyright_source"]["event_id"]
                        stale = stale or not substantive.get("copyright_source_currently_usable", False)
                    if kind == "copyright_license" and row and row.get("relationship_event_id"):
                        relation = latest_copyright["copyright_relationship"]
                        stale = stale or relation is None or row["relationship_event_id"] != relation["event_id"]
                        stale = stale or not substantive.get("copyright_relationship_currently_usable", False)
                    if kind == "copyright_license" and row and latest_copyright["copyright_source"]:
                        stale = stale or row["source_event_id"] != latest_copyright["copyright_source"]["event_id"]
                        stale = stale or not substantive.get("copyright_source_currently_usable", False)
                    substantive[kind + "_currently_usable"] = bool(row and not stale)
                    if row is None:
                        blockers.append({"reason": reason})
                    elif stale:
                        blockers.append({"reason": "M07_COPYRIGHT_RECHECK_PENDING", "review_kind": kind})
                    elif kind == "copyright_relationship":
                        for role, detail in row["parties"].items():
                            if detail["outcome"] != "supported":
                                blockers.append({"reason": "M07_COPYRIGHT_PARTY_OPEN", "role": role})
                        for question, detail in row["questions"].items():
                            if detail["outcome"] == "unknown":
                                blockers.append({"reason": "M07_COPYRIGHT_QUESTION_OPEN", "question": question})
                    elif kind == "copyright_license" and row["overall_coverage"] != "covered":
                        blockers.append({"reason": "M07_COPYRIGHT_LICENSE_SCOPE_OPEN",
                                         "overall_coverage": row["overall_coverage"]})
            from distinctive_rights_stage_c import project_stage_c
            stage_c = project_stage_c(task, intake, related, current["right_type"], unusable_facts)
            substantive.update(stage_c["reviews"])
            blockers.extend(stage_c["blockers"])
            candidate = next((item for rows in candidates.values() if isinstance(rows, list)
                              for item in rows if isinstance(item, dict)
                              and item.get("candidate_id") == scope[0]), {})
            from distinctive_rights_stage_d import project_stage_d
            api_limit = None
            if source_work and plan is not None and capabilities is not None:
                from necessary_completion import _delivery_limit_valid
                api_limit = next((row for row in source_work
                    if _scope(row) == scope and row.get("delivery_limit", {}).get("kind") == "api_record_fact_gap"
                    and _delivery_limit_valid(row, task, evidence, plan, capabilities,
                        candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)), None)
            stage_d = project_stage_d(task, intake, related, candidate, blockers,
                unusable_facts=unusable_facts, substantive=substantive, handoff=handoff,
                api_limit=api_limit)
            blockers = stage_d["blockers"]
            substantive["batch_event_ids"] = stage_d["batch_event_ids"]
            substantive["handoffs"] = stage_d["handoffs"]
            substantive["currently_usable_event_ids"] = stage_d["currently_usable_event_ids"]
            substantive["close_event_id"] = stage_d["close_event_id"]
        else:
            stage_d = {"status": "in_progress"}
        scopes.append({**{key: current[key] for key in SCOPE},
                       "status": stage_d["status"], "intake_event_id": intake["event_id"] if intake else None,
                       "assessment_date": intake["assessment_date"] if intake else None,
                       "tracks": deepcopy(intake["tracks"]) if intake else None,
                       "substantive_reviews": substantive,
                       "blockers": blockers, "facts": [{"event_id": row["event_id"], "track": row["track"],
                           "outcome": row["outcome"], "currently_usable": row["event_id"] not in pending}
                           for row in facts],
                       "material_event_ids": [row["event_id"] for row in materials],
                       "observations": [{"event_id": row["event_id"], "track": row["track"],
                                         "outcome": row["outcome"], "source_run_id": row["source_run_id"]}
                                        for row in observations]})
    status = ("normal_complete" if scopes and all(row["status"] == "normal_complete" for row in scopes)
              else "waiting" if scopes and all(row["status"] in {"normal_complete", "waiting"} for row in scopes)
              else "limited" if scopes and all(row["status"] in {"normal_complete", "limited"} for row in scopes)
              else "in_progress")
    return {"revision": REVISION, "status": status, "scopes": scopes,
            "completion_meaning": "module_07_scoped_review_only; downstream_risk_and_publication_separate"}


def work_entries(view):
    entries = []
    for scope in view.get("scopes", []):
        for blocker in scope["blockers"]:
            state = (("awaiting_user" if blocker.get("action_kind") == "user_fact" else "awaiting_access")
                if blocker.get("state") == "waiting" else (
                "blocked" if blocker.get("state") == "limited" else "awaiting_review"))
            projected = {**{key: scope[key] for key in SCOPE},
                **{key: value for key, value in blocker.items() if key != "source_dependency"},
                "kind": "agent_investigation", "state": state}
            if blocker.get("source_dependency"):
                projected.update({key: deepcopy(value) for key, value in blocker["source_dependency"].items()
                    if key not in {"work_id", "kind", "state", "obligation_id"}})
                projected["distinctive_reason"] = blocker["reason"]
            entries.append(projected)
    return entries

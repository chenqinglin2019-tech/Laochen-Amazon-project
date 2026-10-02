"""Versioned patent/design specialty facts, comparisons and work projection.

This is a review ledger. It never asserts that a cited document is an official
register, performs a source request, or assigns a legal risk level.
"""
from __future__ import annotations

import trusted_api
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_json, stable_id

REVISION = "specialty-analysis-v1"
EVENTS = "specialty_analysis_events"
KINDS = {"intake", "material", "fact", "exemption", "inventory", "comparison",
         "gap", "followup", "change", "change_review", "batch", "handoff", "handoff_classification", "handoff_discovery_scope"}
RIGHTS = {"patent", "utility_model", "design", "unregistered_design"}
FACT_KINDS = {"identity", "territory", "status", "protection", "product", "rights_holder", "legal_conditions"}
PURPOSES = {"identity", "territory", "status", "protection", "product", "rights_holder", "comparison", "legal_conditions"}
SOURCE_FORMS = {"official_register", "official_event", "official_decision", "original_document",
                "product_original", "legal_rule", "summary", "ocr", "translation", "other"}
OUTCOMES = {"supported", "unknown", "conflicted"}
UNIT_OUTCOMES = {"corresponds", "differs", "unknown"}
GAP_OUTCOMES = {"resolved", "continue", "waiting", "limited"}
SCOPE = ("candidate_id", "scenario_id", "jurisdiction", "right_type")


def enabled(task: dict) -> bool:
    value = task.get("specialty_analysis_revision")
    if value is None:
        return False
    if value != REVISION or task.get("triage_stage_revision") != "candidate-triage-stage-v1":
        raise ValueError("SPECIALTY_REVISION_INVALID")
    return True


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(value, *, nonempty=True) -> bool:
    return (isinstance(value, list) and (bool(value) or not nonempty)
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
        raise ValueError("SPECIALTY_EVENTS_INVALID")
    previous = ""
    for row in history:
        if (not isinstance(row, dict) or row.get("kind") not in KINDS
                or row.get("previous_event_id") != previous
                or row.get("event_id") != stable_id("SPECIALTY", task["task_id"],
                    sha256_json({k: v for k, v in row.items() if k != "event_id"}))):
            raise ValueError("SPECIALTY_EVENTS_CHANGED")
        previous = row["event_id"]
    return history


def _append(task, kind, payload):
    history = events(task)
    row = {"kind": kind, **deepcopy(payload), "recorded_at": now_iso(),
           "previous_event_id": history[-1]["event_id"] if history else ""}
    row["event_id"] = stable_id("SPECIALTY", task["task_id"], sha256_json(row))
    task.setdefault(EVENTS, []).append(row)
    return row


def _context(task_dir: Path):
    from annotate_materiality import load_materiality_ledger
    from decision_workflow import evidence_index
    from workflow_v24 import scenario_supplement
    task = load_json(task_dir / "task.json")
    evidence = load_json(task_dir / "evidence.json")
    candidates = load_json(task_dir / "normalized-candidates.json")
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    return task, evidence, candidates, ledger, supplement, evidence_index(evidence, supplement)


def _refs(refs, indexed, *, required=True):
    if not _list(refs, nonempty=required) or not set(refs) <= set(indexed):
        raise ValueError("SPECIALTY_EVIDENCE_REFS_INVALID")


def _intake(task, scope):
    return next((row for row in reversed(events(task)) if row["kind"] == "intake"
                 and _scope(row) == scope), None)


def _current(task, evidence, candidates, ledger, supplement, scope):
    from annotate_materiality import iter_candidates
    from decision_workflow import effective_decision
    matches = [(collection, candidate) for collection, candidate in iter_candidates(candidates)
               if candidate.get("candidate_id") == scope[0]]
    if len(matches) != 1:
        raise ValueError("SPECIALTY_CANDIDATE_UNKNOWN")
    current = effective_decision(task, ledger, *matches[0], *scope[1:],
                                 evidence=evidence, supplement=supplement)
    if current.get("decision") != "selected" or not current.get("current"):
        raise ValueError("SPECIALTY_CURRENT_SELECTED_REQUIRED")
    return current


def _validate_intake(task, evidence, candidates, ledger, supplement, request, *, current=None):
    from candidate_triage_stage import events as triage_events
    scope = _scope(request)
    current = current if current is not None else _current(task, evidence, candidates, ledger, supplement, scope)
    annotation = current["annotation"]
    handoff = next((row for row in reversed(triage_events(task)) if row["kind"] == "selected_handoff"
                    and row["event_id"] == request.get("selected_handoff_event_id")
                    and _scope(row) == scope), None)
    if (handoff is None or handoff["annotation_id"] != annotation["annotation_id"]
            or handoff["annotation_sha256"] != sha256_json(annotation)
            or not _day(request.get("assessment_date"))):
        raise ValueError("SPECIALTY_CURRENT_HANDOFF_AND_DATE_REQUIRED")
    prior = _intake(task, scope)
    if (prior and (prior["selected_handoff_event_id"] != request["selected_handoff_event_id"]
                   or prior["assessment_date"] != request["assessment_date"])
            and (request.get("prior_intake_event_id") != prior["event_id"]
                 or not _text(request.get("new_round_reasoning")))):
        raise ValueError("SPECIALTY_INTAKE_CHANGE_REQUIRES_REVIEW")
    return {**{key: request[key] for key in SCOPE},
            "selected_handoff_event_id": handoff["event_id"],
            "annotation_id": annotation["annotation_id"],
            "product_version_sha256": handoff["product_version_sha256"],
            "candidate_version_sha256": handoff["candidate_version_sha256"],
            "assessment_date": request["assessment_date"],
            "assessment_date_basis": request["assessment_date_basis"],
            "verification_gaps": handoff["verification_gaps"],
            **({"prior_intake_event_id": prior["event_id"],
                "new_round_reasoning": request["new_round_reasoning"]}
               if prior and request.get("prior_intake_event_id") else {})}


def _base(task, request):
    scope = _scope(request)
    intake = _intake(task, scope)
    if intake is None or request.get("intake_event_id") != intake["event_id"]:
        raise ValueError("SPECIALTY_INTAKE_REQUIRED")
    if request.get("assessment_date") != intake["assessment_date"]:
        raise ValueError("SPECIALTY_ASSESSMENT_DATE_CHANGED")
    return {**{key: request[key] for key in SCOPE},
            "intake_event_id": intake["event_id"], "assessment_date": intake["assessment_date"],
            "product_version_sha256": intake["product_version_sha256"],
            "candidate_version_sha256": intake["candidate_version_sha256"]}


def _material(task, request, indexed):
    base = _base(task, request)
    _refs(request.get("evidence_refs"), indexed)
    if (not _text(request.get("document_id")) or not _text(request.get("document_version"))
            or not _list(request.get("purposes")) or set(request["purposes"]) - PURPOSES
            or not _timestamp(request.get("acquired_at"))
            or not _list(request.get("reading_locations"), nonempty=False)
            or not _text(request.get("support_reasoning"))
            or request.get("source_form") not in (SOURCE_FORMS | ({"trusted_api_record"} if trusted_api.enabled(task) else set()))
            or request.get("status") not in {"acquired", "read", "sufficient_for_listed_purposes"}):
        raise ValueError("SPECIALTY_MATERIAL_INVALID")
    if request.get("source_form") == "trusted_api_record":
        from trusted_api import material_support
        if not material_support(task, request, indexed):
            raise ValueError("SPECIALTY_API_RECORD_IDENTITY_OR_RECEIPT_INVALID")
        public_scope = trusted_api.public_material_scope(task, request, indexed)
        if public_scope:
            request = {**request, "api_public_content_scope": sorted(public_scope)}
            if (request.get("status") == "sufficient_for_listed_purposes"
                    and "protection" in request.get("supported_facts", [])
                    and "original_content" not in public_scope):
                raise ValueError("SPECIALTY_PUBLIC_ORIGINAL_CONTENT_REQUIRED")
    if request["status"] != "acquired" and not request["reading_locations"]:
        raise ValueError("SPECIALTY_ACTUAL_READING_REQUIRED")
    if request["status"] == "sufficient_for_listed_purposes" and not _list(request.get("supported_facts")):
        raise ValueError("SPECIALTY_SUPPORT_SCOPE_REQUIRED")
    if request["source_form"] in {"ocr", "translation", "summary"}:
        _refs(request.get("original_evidence_refs"), indexed)
        if not _list(request.get("original_locations")):
            raise ValueError("SPECIALTY_ORIGINAL_LOCATION_REQUIRED")
        if request["status"] == "sufficient_for_listed_purposes" and not request.get("original_verified"):
            raise ValueError("SPECIALTY_DERIVED_ORIGINAL_CHECK_REQUIRED")
    if request.get("reuse_from_event_id"):
        prior = next((row for row in events(task) if row["kind"] == "material"
                      and row["event_id"] == request["reuse_from_event_id"]
                      and _scope(row) == _scope(request)), None)
        rank = {"acquired": 0, "read": 1, "sufficient_for_listed_purposes": 2}
        if (prior is None or not _text(request.get("reuse_applicability_reasoning"))
                or prior["document_id"] != request["document_id"]
                or prior["document_version"] != request["document_version"]
                or set(request["evidence_refs"]) != set(prior["evidence_refs"])
                or not set(request["purposes"]) <= set(prior["purposes"])
                or rank[request["status"]] > rank[prior["status"]]
                or request["acquired_at"] != prior["acquired_at"]):
            raise ValueError("SPECIALTY_MATERIAL_REUSE_INVALID")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _handoff_classification(task, request, indexed):
    """Review the exact legacy obligation's kinds without resolving any of it."""
    base = _base(task, request)
    intake = _intake(task, _scope(request))
    if (request.get("handoff_gap") not in intake["verification_gaps"]
            or not _list(request.get("fact_kinds")) or set(request["fact_kinds"]) - FACT_KINDS
            or not _text(request.get("classification_reasoning"))
            or not _list(request.get("reading_locations"))):
        raise ValueError("SPECIALTY_HANDOFF_CLASSIFICATION_INVALID")
    _refs(request.get("evidence_refs"), indexed)
    materials = {row["event_id"]: row for row in events(task) if row["kind"] == "material"
                 and _scope(row) == _scope(request) and row["intake_event_id"] == base["intake_event_id"]}
    if (not _list(request.get("material_event_ids")) or not set(request["material_event_ids"]) <= set(materials)
            or not any(row["reading_locations"] and row["status"] != "acquired"
                       and set(request["evidence_refs"]) <= set(row["evidence_refs"])
                       for mid, row in materials.items() if mid in request["material_event_ids"])):
        raise ValueError("SPECIALTY_HANDOFF_CLASSIFICATION_READING_REQUIRED")
    prior = next((row for row in reversed(events(task)) if row["kind"] == "handoff_classification"
                  and _scope(row) == _scope(request) and row["intake_event_id"] == base["intake_event_id"]
                  and row["handoff_gap"] == request["handoff_gap"]), None)
    if prior and (request.get("supersedes_event_id") != prior["event_id"]
                  or not _text(request.get("revision_reasoning"))):
        raise ValueError("SPECIALTY_HANDOFF_CLASSIFICATION_REVISION_REQUIRED")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _plan_handoff_binding_valid(gap, binding, usable):
    if binding.get("reason") != "SPECIALTY_HANDOFF_GAP_OPEN":
        return True
    ref = binding.get("handoff_classification_event_id")
    if not ref:
        return (binding.get("fact_kind") == "status" and binding.get("handoff_gap") in {"status", "current_status"}
                and binding.get("handoff_gap") in gap.get("status_handoff_gaps", []))
    current = next((row for row in reversed(usable) if row["kind"] == "handoff_classification"
                    and row.get("handoff_gap") == binding.get("handoff_gap")), {})
    materials = {row["event_id"]: row for row in usable if row["kind"] == "material"}
    return (current.get("event_id") == ref and binding.get("fact_kind") in current.get("fact_kinds", [])
            and binding.get("handoff_classification_sha256") == sha256_json(current)
            and set(current.get("material_event_ids", [])) <= set(materials)
            and any(materials[mid].get("reading_locations") and materials[mid].get("status") != "acquired"
                    and set(current.get("evidence_refs", [])) <= set(materials[mid].get("evidence_refs", []))
                    for mid in current.get("material_event_ids", []) if mid in materials))


def _discovery_scope_basis(task, scope):
    from product_scope import directions, direction_digest, enabled as scope_enabled
    if scope[2:] != ("US", "patent") or not scope_enabled(task):
        raise ValueError("SPECIALTY_DISCOVERY_DELEGATION_SCOPE_REQUIRED")
    requirements = [row for row in task.get("coverage_requirements", []) if row.get("jurisdiction") == "US"
                    and row.get("right_type") in {"patent", "design"} and row.get("phase") == "official_recall"]
    if (len(requirements) != 2 or {row["right_type"] for row in requirements} != {"patent", "design"}
            or len({row["requirement_id"] for row in requirements}) != 2):
        raise ValueError("SPECIALTY_DISCOVERY_DELEGATION_COVERAGE_REQUIRED")
    refs = [{"direction_id": row["direction_id"], "right_type": right, "sha256": direction_digest(task, row)}
            for right in ("patent", "design") for row in directions(task, scope[1], right)]
    if {row["right_type"] for row in refs} != {"patent", "design"}:
        raise ValueError("SPECIALTY_DISCOVERY_DELEGATION_DIRECTIONS_REQUIRED")
    return {"coverage_requirements": {row["requirement_id"]: sha256_json(row) for row in requirements},
            "direction_refs": refs}


def _handoff_discovery_scope(task, request, indexed):
    base = _base(task, request)
    intake = _intake(task, _scope(request))
    history = [row for row in events(task) if _scope(row) == _scope(request)
               and row.get("intake_event_id") == base["intake_event_id"]]
    raw = request.get("handoff_gap")
    if (raw not in intake["verification_gaps"] or request.get("classification") != "residual_discovery"
            or request.get("excluded_fact_kinds") != sorted(FACT_KINDS)
            or not _text(request.get("scope_reasoning")) or not _text(request.get("remaining_impact"))
            or not _list(request.get("reading_locations"))):
        raise ValueError("SPECIALTY_DISCOVERY_DELEGATION_REVIEW_REQUIRED")
    if any(row["kind"] == "handoff_classification" and row["handoff_gap"] == raw or
           row["kind"] == "gap" and any(binding.get("handoff_gap") == raw
              for binding in row.get("obligation_bindings", [])) for row in history):
        raise ValueError("SPECIALTY_DISCOVERY_DELEGATION_KNOWN_OBLIGATION_FORBIDDEN")
    _refs(request.get("evidence_refs"), indexed)
    materials = {row["event_id"]: row for row in history if row["kind"] == "material"}
    if (not _list(request.get("material_event_ids")) or not set(request["material_event_ids"]) <= set(materials)
            or not any(row.get("reading_locations") and row["status"] != "acquired"
                       and set(request["evidence_refs"]) <= set(row["evidence_refs"])
                       for mid, row in materials.items() if mid in request["material_event_ids"])):
        raise ValueError("SPECIALTY_DISCOVERY_DELEGATION_READING_REQUIRED")
    basis = _discovery_scope_basis(task, _scope(request))
    if (not _list(request.get("coverage_requirement_ids"))
            or set(request["coverage_requirement_ids"]) != set(basis["coverage_requirements"])
            or request.get("direction_refs") != basis["direction_refs"]):
        raise ValueError("SPECIALTY_DISCOVERY_DELEGATION_MAPPING_REQUIRED")
    retained = {row["event_id"]: sha256_json(row) for row in history
                if row["kind"] in {"fact", "inventory", "comparison", "exemption"}}
    if not _list(request.get("nondelegated_event_ids"), nonempty=False) or set(request["nondelegated_event_ids"]) != set(retained):
        raise ValueError("SPECIALTY_DISCOVERY_DELEGATION_JUDGMENTS_REQUIRED")
    prior = next((row for row in reversed(history) if row["kind"] == "handoff_discovery_scope"
                  and row["handoff_gap"] == raw), None)
    if prior and (request.get("supersedes_event_id") != prior["event_id"] or not _text(request.get("revision_reasoning"))):
        raise ValueError("SPECIALTY_DISCOVERY_DELEGATION_REVISION_REQUIRED")
    return {**base, **{key: deepcopy(value) for key, value in request.items() if key not in base},
            "discovery_scope_basis": basis, "nondelegated_judgments": retained}


def discovery_delegation_entry(task, evidence, candidates, ledger, plan, scope, raw_gap, *, supplement=None):
    """Delegate duplicate residual discovery to its existing canonical queue; never close it."""
    try:
        current = _current(task, evidence, candidates, ledger, supplement, _scope(scope))
        intake = _intake(task, _scope(scope))
        if not intake or intake["annotation_id"] != current["annotation"]["annotation_id"]:
            return None
        from candidate_triage_stage import events as triage_events
        handoff = next((row for row in reversed(triage_events(task)) if row["kind"] == "selected_handoff"
                        and _scope(row) == _scope(scope) and row["annotation_id"] == current["annotation"]["annotation_id"]), {})
        if intake["selected_handoff_event_id"] != handoff.get("event_id"):
            return None
        rows = [row for row in events(task) if _scope(row) == _scope(scope)
                and row.get("intake_event_id") == intake["event_id"]]
        review = next((row for row in reversed(rows) if row["kind"] == "handoff_discovery_scope"
                       and row["handoff_gap"] == raw_gap), None)
        if not review or review["discovery_scope_basis"] != _discovery_scope_basis(task, _scope(scope)):
            return None
        retained = {row["event_id"]: sha256_json(row) for row in rows
                    if row["kind"] in {"fact", "inventory", "comparison", "exemption"}}
        if review["nondelegated_judgments"] != retained:
            return None
        if (any(row["kind"] == "handoff_classification" and row["handoff_gap"] == raw_gap or
                row["kind"] == "gap" and any(binding.get("handoff_gap") == raw_gap
                   for binding in row.get("obligation_bindings", [])) for row in rows)
                or any(row["kind"] == "change" and row["substantive"]
                       and ({review["event_id"], *review["material_event_ids"]} & set(row["affected_event_ids"]))
                       and not any(r["kind"] == "change_review" and r["change_event_id"] == row["event_id"]
                                   and r["outcome"] == "continues" for r in rows) for row in rows)):
            return None
        if not isinstance(plan, dict) or plan.get("task_id") != task["task_id"]:
            return None
    except ValueError:
        return None
    proof = {"kind": "specialty_discovery_delegation", "review_event_id": review["event_id"],
             "review_sha256": sha256_json(review), "intake_sha256": sha256_json(intake),
             "annotation_sha256": sha256_json(current["annotation"]), "plan_sha256": sha256_json(plan),
             "discovery_scope_basis": deepcopy(review["discovery_scope_basis"]), "official_verification": "not_verified"}
    return {**{key: scope[key] for key in SCOPE}, "state": "blocked", "reason": "SPECIALTY_DISCOVERY_SCOPE_DELEGATED",
            "handoff_gap": raw_gap, "limitation_kind": "residual_discovery_pending", "official_verification": "not_verified",
            "delivery_limit": proof, "reasoning": review["remaining_impact"] + "；剩余发现仍由规范检索队列处理，不宣称全面检索或正常完成。"}


def _unregistered_public_analysis(task, request, materials, indexed):
    """Link a legal inference to the actual public work and a read applicable rule."""
    if (not trusted_api.enabled(task) or request.get("right_type") != "unregistered_design"
            or request.get("outcome") != "supported" or request.get("fact_kind") not in
            {"legal_conditions", "status", "territory", "rights_holder"}):
        return False
    selected = [materials[mid] for mid in request["material_event_ids"]]
    public = [row for row in selected if trusted_api.public_material_scope(task, row, indexed)]
    if not public:
        return False
    rules = [row for row in selected if row.get("source_form") == "legal_rule"
             and "legal_conditions" in row.get("purposes", [])
             and "legal_conditions" in row.get("supported_facts", [])]
    if (not rules or any(row.get("status") != "sufficient_for_listed_purposes"
            or not row.get("reading_locations") for row in selected)
            or not set(request["evidence_refs"]) <= set().union(*(set(row["evidence_refs"]) for row in selected))
            or not set().union(*(set(row["evidence_refs"]) for row in rules)) <= set(request["evidence_refs"])
            or not any(set(row["evidence_refs"]) & set(request["evidence_refs"]) for row in public)):
        raise ValueError("SPECIALTY_UNREGISTERED_PUBLIC_RULE_BASIS_REQUIRED")
    if request["fact_kind"] == "legal_conditions":
        if not _text(request.get("rules_basis")) or not isinstance(request.get("conditions"), list):
            raise ValueError("SPECIALTY_UNREGISTERED_RULES_REQUIRED")
        for condition in request.get("conditions", []):
            if isinstance(condition, dict) and condition.get("condition_id") == "disclosure" and condition.get("outcome") == "supported":
                if not any("original_content" in trusted_api.public_material_scope(task, row, indexed)
                           and set(condition.get("evidence_refs", [])) & set(row["evidence_refs"]) for row in public):
                    raise ValueError("SPECIALTY_DISCLOSURE_ORIGINAL_CONTENT_REQUIRED")
        return True
    prior = next((row for row in reversed(events(task)) if row.get("kind") == "fact" and row.get("fact_kind") == "legal_conditions"
                  and row.get("intake_event_id") == request.get("intake_event_id") and _scope(row) == _scope(request)), None)
    if (prior is None or prior.get("event_id") != request.get("legal_conditions_event_id")
            or prior.get("outcome") != "supported" or not prior.get("conditions")
            or any(row.get("outcome") != "supported" for row in prior["conditions"])
            or not set(prior.get("material_event_ids", [])) <= set(request["material_event_ids"])
            or not any(str(request.get("right_identity") or "").strip() in
                       trusted_api._public_urls(row.get("api_candidate_identity", {})) for row in public)
            or not _text(request.get("inference_reasoning"))):
        raise ValueError("SPECIALTY_UNREGISTERED_INFERENCE_BASIS_REQUIRED")
    return True


def _fact(task, request, indexed, *, evidence=None):
    base = _base(task, request)
    intake = _intake(task, _scope(request))
    if (request.get("fact_kind") not in FACT_KINDS or request.get("outcome") not in OUTCOMES
            or not _text(request.get("fact_id")) or not _text(request.get("raw_statement"))
            or not _text(request.get("reasoning")) or not _text(request.get("document_version"))
            or not _list(request.get("reading_locations"))):
        raise ValueError("SPECIALTY_FACT_INVALID")
    _refs(request.get("evidence_refs"), indexed)
    if request["fact_kind"] in {"territory", "status"}:
        if not _text(request.get("right_identity")) or not _text(request.get("territory_basis")):
            raise ValueError("SPECIALTY_TERRITORY_BASIS_REQUIRED")
        if request["fact_kind"] == "status" and not _day(request.get("source_checked_date")):
            raise ValueError("SPECIALTY_QUERY_DATE_REQUIRED")
    if request["outcome"] == "conflicted":
        _refs(request.get("conflicting_evidence_refs"), indexed)
        if not _text(request.get("conflict_explanation")):
            raise ValueError("SPECIALTY_CONFLICT_EXPLANATION_REQUIRED")
    if request.get("resolves_fact_event_ids"):
        prior = {row["event_id"]: row for row in events(task) if row["kind"] == "fact"
                 and _scope(row) == _scope(request)
                 and row["intake_event_id"] == base["intake_event_id"]
                 and row["fact_kind"] == request["fact_kind"]}
        if (request["outcome"] != "supported" or not _list(request["resolves_fact_event_ids"])
                or not set(request["resolves_fact_event_ids"]) <= set(prior)
                or not _text(request.get("adoption_reasoning"))):
            raise ValueError("SPECIALTY_CONFLICT_RESOLUTION_INVALID")
    if request.get("resolves_handoff_gaps"):
        if (request["outcome"] != "supported" or not _list(request["resolves_handoff_gaps"])
                or not set(request["resolves_handoff_gaps"]) <= set(intake["verification_gaps"])):
            raise ValueError("SPECIALTY_HANDOFF_GAP_RESOLUTION_INVALID")
    if request.get("excludes_action_ids"):
        if (request["outcome"] != "supported" or request["fact_kind"] not in {"territory", "status"}
                or not _list(request["excludes_action_ids"])
                or not _text(request.get("exclusion_reasoning"))
                or not _text(request.get("assessment_applicability_reasoning"))):
            raise ValueError("SPECIALTY_DECISIVE_FACT_INVALID")
    if request.get("derived_kind") in {"ocr", "translation", "summary"}:
        _refs(request.get("original_evidence_refs"), indexed)
        if request["outcome"] == "supported" and not request.get("original_verified"):
            raise ValueError("SPECIALTY_DERIVED_ORIGINAL_CHECK_REQUIRED")
    material_refs = {row["event_id"]: row for row in events(task)
                     if row["kind"] == "material" and _scope(row) == _scope(request)
                     and row["intake_event_id"] == base["intake_event_id"]}
    if not _list(request.get("material_event_ids")) or not set(request["material_event_ids"]) <= set(material_refs):
        raise ValueError("SPECIALTY_MATERIAL_LINK_REQUIRED")
    public_analysis = _unregistered_public_analysis(task, request, material_refs, indexed)
    purpose = "legal_conditions" if request["fact_kind"] == "legal_conditions" else request["fact_kind"]
    if not public_analysis and not any(purpose in material_refs[mid]["purposes"] and material_refs[mid]["reading_locations"]
               and material_refs[mid]["document_version"] == request["document_version"]
               and set(request["evidence_refs"]) <= set(material_refs[mid]["evidence_refs"])
               for mid in request["material_event_ids"]):
        raise ValueError("SPECIALTY_PURPOSE_READING_REQUIRED")
    if request["outcome"] == "supported" and not public_analysis and not any(
            material_refs[mid]["status"] == "sufficient_for_listed_purposes"
            and purpose in material_refs[mid]["purposes"]
            and request["fact_kind"] in material_refs[mid].get("supported_facts", [])
            and material_refs[mid]["document_version"] == request["document_version"]
            and set(request["evidence_refs"]) <= set(material_refs[mid]["evidence_refs"])
            for mid in request["material_event_ids"]):
        raise ValueError("SPECIALTY_PURPOSE_SUFFICIENCY_REQUIRED")
    if request["outcome"] == "supported" and not public_analysis and all(
            material_refs[mid]["source_form"] == "trusted_api_record" for mid in request["material_event_ids"]):
        if not any(trusted_api.material_fact(task, material_refs[mid], indexed, request["fact_kind"],
                                            right_identity=request.get("right_identity"), evidence=evidence)
                   for mid in request["material_event_ids"]):
            raise ValueError("SPECIALTY_API_FACT_NOT_RETURNED")
    if request["outcome"] == "supported" and not public_analysis and request["fact_kind"] in {"territory", "status"}:
        from trusted_api import material_fact
        if not any(material_refs[mid]["source_form"] in
                   {"official_register", "official_event", "official_decision"}
                   or material_fact(task, material_refs[mid], indexed, request["fact_kind"],
                                    right_identity=request.get("right_identity"), evidence=evidence)
                   for mid in request["material_event_ids"]):
            raise ValueError("SPECIALTY_OFFICIAL_STATUS_OR_TERRITORY_REQUIRED")
    if request["outcome"] == "supported" and request["fact_kind"] == "product":
        if not any(material_refs[mid]["source_form"] == "product_original"
                   for mid in request["material_event_ids"]):
            raise ValueError("SPECIALTY_PRODUCT_ORIGINAL_REQUIRED")
    if request["fact_kind"] == "rights_holder" and request["right_type"] == "design":
        if (not _text(request.get("holder_identity"))
                or not _text(request.get("assessment_applicability_reasoning"))):
            raise ValueError("SPECIALTY_CURRENT_HOLDER_BASIS_REQUIRED")
        if request["outcome"] == "supported" and not any(
                material_refs[mid]["source_form"] in
                {"official_register", "official_event", "official_decision"}
                or trusted_api.material_fact(task, material_refs[mid], indexed, "rights_holder",
                                             right_identity=request.get("right_identity"), evidence=evidence)
                for mid in request["material_event_ids"]):
            raise ValueError("SPECIALTY_HOLDER_OFFICIAL_BASIS_REQUIRED")
    if request["fact_kind"] == "legal_conditions" and request["right_type"] == "unregistered_design":
        conditions = request.get("conditions")
        if not _text(request.get("rules_basis")) or not isinstance(conditions, list) or not conditions:
            raise ValueError("SPECIALTY_UNREGISTERED_RULES_REQUIRED")
        for item in conditions:
            if (not isinstance(item, dict) or not _text(item.get("condition_id"))
                    or not _text(item.get("applicability_reasoning"))
                    or item.get("outcome") not in OUTCOMES):
                raise ValueError("SPECIALTY_UNREGISTERED_CONDITION_INVALID")
            _refs(item.get("evidence_refs", []), indexed, required=item["outcome"] == "supported")
            if item.get("condition_id") == "disclosure" and (not _text(item.get("design_version"))
                    or not _text(item.get("disclosed_content"))
                    or not _text(item.get("date_basis"))
                    or not _text(item.get("geographic_basis"))):
                raise ValueError("SPECIALTY_DISCLOSURE_CONTENT_AND_DATE_REQUIRED")
    result = {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}
    if public_analysis:
        result["analysis_basis"] = "public_facts_with_applicable_rule"
    return result


def _exemption(task, request):
    base = _base(task, request)
    if (not _text(request.get("action_id")) or not _text(request.get("reasoning"))
            or not _text(request.get("scenario_basis")) or not _text(request.get("right_identity"))
            or not _text(request.get("territory_basis")) or not _list(request.get("remaining_obligations"), nonempty=False)
            or not _list(request.get("fact_event_ids"))):
        raise ValueError("SPECIALTY_EXEMPTION_INVALID")
    facts = {row["event_id"]: row for row in events(task)
             if row["kind"] == "fact" and _scope(row) == _scope(request)
             and row["intake_event_id"] == base["intake_event_id"]
             and row["outcome"] == "supported"}
    if not set(request["fact_event_ids"]) <= set(facts):
        raise ValueError("SPECIALTY_EXEMPTION_FACTS_UNSUPPORTED")
    kinds = {facts[ref]["fact_kind"] for ref in request["fact_event_ids"]}
    decisive = [facts[ref] for ref in request["fact_event_ids"]
                if request["action_id"] in facts[ref].get("excludes_action_ids", [])]
    if "identity" not in kinds or not decisive:
        raise ValueError("SPECIALTY_EXEMPTION_BASIS_INCOMPLETE")
    if any(fact.get("right_identity") != request["right_identity"] for fact in decisive):
        raise ValueError("SPECIALTY_EXEMPTION_RIGHT_IDENTITY_MISMATCH")
    materials = {row["event_id"]: row for row in events(task) if row["kind"] == "material"
                 and _scope(row) == _scope(request)
                 and row["intake_event_id"] == base["intake_event_id"]}
    if not any(any(materials.get(mid, {}).get("source_form") in
                   ({"official_register", "official_event", "official_decision"} | ({"trusted_api_record"} if trusted_api.enabled(task) else set()))
                   for mid in fact["material_event_ids"]) for fact in decisive):
        raise ValueError("SPECIALTY_EXEMPTION_OFFICIAL_BASIS_REQUIRED")
    resolved = {ref for row in events(task) if row["kind"] == "fact" and _scope(row) == _scope(request)
                and row["intake_event_id"] == base["intake_event_id"]
                for ref in row.get("resolves_fact_event_ids", [])}
    if any(row["kind"] == "fact" and _scope(row) == _scope(request)
           and row["intake_event_id"] == base["intake_event_id"]
           and row["outcome"] == "conflicted" and row["fact_kind"] in kinds
           and row["event_id"] not in resolved for row in events(task)):
        raise ValueError("SPECIALTY_EXEMPTION_CONFLICT_OPEN")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _inventory(task, request, indexed):
    base = _base(task, request)
    _refs(request.get("evidence_refs"), indexed)
    if (not _text(request.get("document_id")) or not _text(request.get("document_version"))
            or not _list(request.get("reading_locations"))
            or not _text(request.get("completeness_reasoning"))
            or not isinstance(request.get("units"), list) or not request["units"]):
        raise ValueError("SPECIALTY_INVENTORY_INVALID")
    materials = {row["event_id"]: row for row in events(task) if row["kind"] == "material"
                 and _scope(row) == _scope(request)
                 and row["intake_event_id"] == base["intake_event_id"]}
    if (not _list(request.get("material_event_ids"))
            or not any(mid in materials and materials[mid]["document_version"] == request["document_version"]
                       and materials[mid]["status"] == "sufficient_for_listed_purposes"
                       and "protection" in materials[mid]["purposes"]
                       and set(request["evidence_refs"]) <= set(materials[mid]["evidence_refs"])
                       for mid in request["material_event_ids"])):
        raise ValueError("SPECIALTY_INVENTORY_ORIGINAL_READING_REQUIRED")
    seen = set()
    for unit in request["units"]:
        if (not isinstance(unit, dict) or not _text(unit.get("unit_id"))
                or unit["unit_id"] in seen or not _text(unit.get("product_configuration"))
                or not _text(unit.get("original_location"))):
            raise ValueError("SPECIALTY_UNIT_INVALID")
        seen.add(unit["unit_id"])
        if request["right_type"] in {"patent", "utility_model"}:
            if (unit.get("kind") not in {"independent_claim", "dependent_claim"}
                    or not _text(unit.get("implementation_id"))
                    or not _list(unit.get("necessary_elements"))):
                raise ValueError("SPECIALTY_CLAIM_INVENTORY_INVALID")
        elif (unit.get("kind") != "design" or not _text(unit.get("design_id"))
              or not _text(unit.get("product_state")) or not _list(unit.get("necessary_views"))):
            raise ValueError("SPECIALTY_DESIGN_INVENTORY_INVALID")
    if request["right_type"] in {"patent", "utility_model"} and not any(
            unit["kind"] == "independent_claim" for unit in request["units"]):
        raise ValueError("SPECIALTY_INDEPENDENT_CLAIM_MISSING")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _unit(task, request):
    inventory = next((row for row in events(task) if row["kind"] == "inventory"
                      and row["event_id"] == request.get("inventory_event_id")
                      and _scope(row) == _scope(request)
                      and row["intake_event_id"] == request.get("intake_event_id")), None)
    if inventory is None:
        raise ValueError("SPECIALTY_INVENTORY_REQUIRED")
    unit = next((item for item in inventory["units"] if item["unit_id"] == request.get("unit_id")), None)
    if unit is None:
        raise ValueError("SPECIALTY_UNIT_UNKNOWN")
    return inventory, unit


def _comparison(task, request, indexed):
    base = _base(task, request)
    inventory, unit = _unit(task, request)
    if request.get("disposition") not in {"compared", "exempt", "pending"}:
        raise ValueError("SPECIALTY_COMPARISON_DISPOSITION_INVALID")
    if request["disposition"] == "exempt":
        exemption = next((row for row in events(task) if row["kind"] == "exemption"
                          and row["event_id"] == request.get("exemption_event_id")
                          and _scope(row) == _scope(request)
                          and row["intake_event_id"] == base["intake_event_id"]
                          and row["action_id"] == request["unit_id"]), None)
        if exemption is None:
            raise ValueError("SPECIALTY_UNIT_EXEMPTION_REQUIRED")
    elif request["disposition"] == "pending":
        if not _text(request.get("gap_reasoning")):
            raise ValueError("SPECIALTY_PENDING_GAP_REQUIRED")
    else:
        _refs(request.get("evidence_refs"), indexed)
        if not _text(request.get("reasoning")):
            raise ValueError("SPECIALTY_COMPARISON_REASONING_REQUIRED")
        if request["right_type"] in {"patent", "utility_model"}:
            items = request.get("elements")
            if not isinstance(items, list) or {row.get("element_id") for row in items if isinstance(row, dict)} != set(unit["necessary_elements"]) or len(items) != len(unit["necessary_elements"]):
                raise ValueError("SPECIALTY_ALL_NECESSARY_ELEMENTS_REQUIRED")
            for item in items:
                if (item.get("result") not in UNIT_OUTCOMES
                        or not _text(item.get("claim_quote"))
                        or not _text(item.get("original_location"))
                        or not _text(item.get("product_fact"))
                        or not _text(item.get("reasoning"))):
                    raise ValueError("SPECIALTY_ELEMENT_INVALID")
                _refs(item.get("claim_evidence_refs"), indexed)
                _refs(item.get("product_evidence_refs"), indexed, required=item["result"] != "unknown")
        else:
            views = request.get("views")
            if not isinstance(views, list) or {row.get("view_id") for row in views if isinstance(row, dict)} != set(unit["necessary_views"]) or len(views) != len(unit["necessary_views"]):
                raise ValueError("SPECIALTY_ALL_NECESSARY_VIEWS_REQUIRED")
            for view in views:
                if view.get("result") not in UNIT_OUTCOMES or not _text(view.get("reasoning")):
                    raise ValueError("SPECIALTY_VIEW_INVALID")
                _refs(view.get("right_evidence_refs"), indexed, required=view["result"] != "unknown")
                _refs(view.get("product_evidence_refs"), indexed, required=view["result"] != "unknown")
                if view["result"] != "unknown" and (not _text(view.get("right_location"))
                                                    or not _text(view.get("product_location"))):
                    raise ValueError("SPECIALTY_VIEW_LOCATIONS_REQUIRED")
            parts = request.get("design_scope_parts")
            if not isinstance(parts, list) or not parts:
                raise ValueError("SPECIALTY_DESIGN_SCOPE_PARTS_REQUIRED")
            for part in parts:
                if (not isinstance(part, dict) or not _text(part.get("part_id"))
                        or part.get("treatment") not in {"claimed", "excluded", "unknown"}
                        or not _text(part.get("interpretation_basis"))):
                    raise ValueError("SPECIALTY_DESIGN_MARKING_INVALID")
                _refs(part.get("evidence_refs"), indexed)
            if (not _text(request.get("overall_visual_relationship"))
                    or not _text(request.get("design_scope_basis"))
                    or request.get("registered_basis") != ("registered" if request["right_type"] == "design"
                                                           else "unregistered")
                    or not _list(request.get("similarities"), nonempty=False)
                    or not _list(request.get("differences"), nonempty=False)
                    or not _list(request.get("unknowns"), nonempty=False)
                    or not _text(request.get("perspective_limitations"))):
                raise ValueError("SPECIALTY_DESIGN_CONTEXT_REQUIRED")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _dependency_matches(gap, binding, basis):
    if gap.get("action_kind") == "professional_review":
        return (binding.get("reason") == "SPECIALTY_DESIGN_SCOPE_UNKNOWN"
                and basis.get("kind") == "comparison" and basis.get("right_type") == "design")
    if gap.get("action_kind") == "user_fact":
        return binding.get("reason") == "SPECIALTY_COMPARISON_UNKNOWN" or basis.get("fact_kind") == "product"
    if gap.get("action_kind") not in {"verify_known_right", "discovery"}:
        return False
    if binding.get("reason") == "SPECIALTY_COMPARISON_UNKNOWN":
        return (gap.get("source_plan_gap_proof", {}).get("kind") == "api_record_fact_gap"
            and bool(gap.get("unavailable_comparison"))
            and binding.get("unit_id") in gap["unavailable_comparison"].get("unit_ids", []))
    if basis.get("fact_kind") == "product":
        return False
    proof = gap.get("source_plan_gap_proof", {})
    if (basis.get("fact_kind") == "territory" and proof.get("kind") == "territory_current_effect_plan_gap"
            and proof.get("fact_kind") == "territory" and gap.get("jurisdiction") == "US"
            and gap.get("right_type") in {"patent", "design"}):
        return gap.get("source_required_facts") == ["current_status"]
    aliases = {"identity": {"identity", "right_identity"}, "territory": {"territory", "territory_basis"},
        "status": {"status", "current_status"}, "protection": {"protection", "protection_content"},
        "rights_holder": {"rights_holder", "owner", "assignment"}, "legal_conditions": {"legal_conditions"}}
    if proof.get('kind') == 'api_record_fact_gap':
        aliases['protection'].add('representative_figures')
    return bool(set(gap.get("source_required_facts", [])) & aliases.get(basis.get("fact_kind"), set()))


def _handoff_facet_matches(blocker, binding):
    return (not blocker.get("handoff_classification_event_id")
            or blocker.get("fact_kind") == binding.get("fact_kind"))


def _unknown_bindings(task, gap, history):
    """Find exact current, reviewed unknowns for an explicit dependency binding.

    This never establishes a fact, closes a comparison, or certifies a source limit.
    A changed/suspended basis must be reviewed again rather than silently deferred.
    """
    relevant = [row for row in history if _scope(row) == _scope(gap)
                and row.get("intake_event_id") == gap.get("intake_event_id")]
    superseded = {ref for row in relevant if row["kind"] == "change_review"
                  and row["outcome"] == "changed" for ref in row["reviewed_affected_event_ids"]}
    suspended = {ref for change in relevant if change["kind"] == "change" and change["substantive"]
                 if not any(review["kind"] == "change_review" and
                            review["change_event_id"] == change["event_id"] and
                            review["outcome"] in {"continues", "changed"} for review in relevant)
                 for ref in change["affected_event_ids"]}
    usable = [row for row in relevant if row["event_id"] not in superseded | suspended]
    indexed = {row["event_id"]: row for row in usable}
    result = []
    for binding in gap.get("obligation_bindings", []):
        classification_ref = binding.get("handoff_classification_event_id")
        if classification_ref:
            latest = next((row for row in reversed(relevant) if row["kind"] == "handoff_classification"
                           and row.get("handoff_gap") == binding.get("handoff_gap")), {})
            if latest.get("event_id") != classification_ref or classification_ref not in indexed:
                continue  # A suspended latest classification must never revive an older mapping.
        basis = indexed.get(binding.get("basis_event_id"), {})
        reason = binding.get("reason")
        valid = False
        if reason in {"SPECIALTY_FACT_REQUIRED", "SPECIALTY_HANDOFF_GAP_OPEN"}:
            current = next((row for row in reversed(usable) if row["kind"] == "fact"
                            and row["fact_kind"] == basis.get("fact_kind")), {})
            valid = (basis.get("kind") == "fact" and basis.get("outcome") == "unknown"
                     and current.get("event_id") == basis.get("event_id")
                     and (not binding.get("fact_kind") or binding["fact_kind"] == basis.get("fact_kind"))
                     and (reason != "SPECIALTY_FACT_REQUIRED" or
                          binding.get("fact_kind") == basis.get("fact_kind")))
        elif reason in {"SPECIALTY_COMPARISON_UNKNOWN", "SPECIALTY_DESIGN_SCOPE_UNKNOWN"}:
            inventory = next((row for row in reversed(usable) if row["kind"] == "inventory"), {})
            current = next((row for row in reversed(usable) if row["kind"] == "comparison"
                            and row.get("inventory_event_id") == inventory.get("event_id")
                            and row.get("unit_id") == binding.get("unit_id")), {})
            valid = (basis.get("kind") == "comparison" and basis.get("disposition") == "compared"
                     and current.get("event_id") == basis.get("event_id")
                     and (any(part.get("treatment") == "unknown" for part in basis.get("design_scope_parts", []))
                          if reason == "SPECIALTY_DESIGN_SCOPE_UNKNOWN" else
                          any(item.get("result") == "unknown" for item in basis.get("elements", basis.get("views", [])))))
        if (valid and _dependency_matches(gap, binding, basis)
                and (not (gap.get("source_plan_gap_proof") or classification_ref)
                     or _plan_handoff_binding_valid(gap, binding, usable))):
            result.append(binding)
    return result


def professional_scope_packet(task, request, indexed):
    """Exact already-read design scope packet; this contains no expert conclusion."""
    base = _base(task, request)
    if request.get("right_type") != "design":
        raise ValueError("SPECIALTY_PROFESSIONAL_DESIGN_ONLY")
    history = [row for row in events(task) if _scope(row) == _scope(request)
               and row.get("intake_event_id") == base["intake_event_id"]]
    affected = {ref for row in history if row["kind"] == "change" and row["substantive"]
                for ref in row["affected_event_ids"]}
    inventory, unit = _unit(task, request)
    latest = next((row for row in reversed(history) if row["kind"] == "inventory"), {})
    comparison = next((row for row in reversed(history) if row["kind"] == "comparison"
                       and row.get("inventory_event_id") == inventory["event_id"]
                       and row.get("unit_id") == unit["unit_id"]), {})
    bindings = request.get("obligation_bindings", [])
    if (latest.get("event_id") != inventory["event_id"] or unit.get("kind") != "design"
            or comparison.get("disposition") != "compared"
            or not any(part.get("treatment") == "unknown" for part in comparison.get("design_scope_parts", []))
            or len(comparison.get("views", [])) != len(unit["necessary_views"])
            or {row.get("view_id") for row in comparison.get("views", [])} != set(unit["necessary_views"])
            or len(bindings) != 1 or bindings[0].get("reason") != "SPECIALTY_DESIGN_SCOPE_UNKNOWN"
            or bindings[0].get("unit_id") != unit["unit_id"]
            or bindings[0].get("basis_event_id") != comparison.get("event_id")):
        raise ValueError("SPECIALTY_PROFESSIONAL_CURRENT_SCOPE_REQUIRED")
    materials = {row["event_id"]: row for row in history if row["kind"] == "material"}
    mids = inventory.get("material_event_ids", [])
    if (not mids or not set(mids) <= set(materials) or any(mid in affected for mid in mids)
            or {inventory["event_id"], comparison["event_id"]} & affected
            or not any((materials[mid].get("source_form") == "original_document"
                       or trusted_api.material_fact(task, materials[mid], indexed, "representative_figures"))
                       and materials[mid].get("status") == "sufficient_for_listed_purposes"
                       and "protection" in materials[mid].get("purposes", [])
                       and materials[mid].get("reading_locations")
                       and set(inventory["evidence_refs"]) <= set(materials[mid]["evidence_refs"])
                       for mid in mids)):
        raise ValueError("SPECIALTY_PROFESSIONAL_ORIGINAL_READING_REQUIRED")
    refs = sorted(set(inventory["evidence_refs"]) | set(comparison["evidence_refs"]))
    _refs(refs, indexed)
    from common import sha256_file
    for ref in refs:
        source = indexed[ref]
        if source.get("path") and (not Path(source["path"]).is_file()
                or not source.get("sha256") or sha256_file(Path(source["path"])) != source["sha256"]):
            raise ValueError("SPECIALTY_PROFESSIONAL_SOURCE_CHANGED")
    intake = _intake(task, _scope(request))
    return {"schema": "IPR-DESIGN-SCOPE-PACKET/1.0", **{key: request[key] for key in SCOPE},
            "intake_event_id": intake["event_id"], "intake_sha256": sha256_json(intake),
            "inventory_event_id": inventory["event_id"], "inventory_sha256": sha256_json(inventory),
            "comparison_event_id": comparison["event_id"], "comparison_sha256": sha256_json(comparison),
            "unit_id": unit["unit_id"], "necessary_views": deepcopy(unit["necessary_views"]),
            "material_sha256": {mid: sha256_json(materials[mid]) for mid in mids},
            "reading_locations": {mid: deepcopy(materials[mid]["reading_locations"]) for mid in mids},
            "evidence_sha256": {ref: sha256_json(indexed[ref]) for ref in refs}}


def professional_wait_entry(task, evidence, candidates, ledger, scope, unit_id, *, supplement=None, gap_event_id=None):
    """Revalidate external professional scope waiting against current selected material."""
    from decision_workflow import evidence_index
    try:
        current = _current(task, evidence, candidates, ledger, supplement, _scope(scope))
        intake = _intake(task, _scope(scope))
        if not intake or intake["annotation_id"] != current["annotation"]["annotation_id"]:
            return None
        from candidate_triage_stage import events as triage_events
        handoff = next((row for row in reversed(triage_events(task)) if row["kind"] == "selected_handoff"
                        and _scope(row) == _scope(scope) and row.get("annotation_id") == intake["annotation_id"]), {})
        if handoff.get("event_id") != intake.get("selected_handoff_event_id"):
            return None
        history = [row for row in events(task) if _scope(row) == _scope(scope)
                   and row.get("intake_event_id") == intake["event_id"]]
        gap = next((row for row in reversed(history) if row["kind"] == "gap"
                    and row.get("action_kind") == "professional_review" and row.get("unit_id") == unit_id
                    and (gap_event_id is None or row["event_id"] == gap_event_id)), {})
        follow = next((row for row in reversed(history) if row["kind"] == "followup"
                       and row.get("gap_event_id") == gap.get("event_id")), {})
        latest_gap = next((row for row in reversed(history) if row["kind"] == "gap"
                          and row.get("action_kind") == "professional_review" and row.get("unit_id") == unit_id), {})
        if (gap.get("event_id") != latest_gap.get("event_id") or any(
                row["kind"] == "change" and row["substantive"]
                and {gap.get("event_id"), follow.get("event_id")} & set(row["affected_event_ids"])
                for row in history)):
            return None
        packet = professional_scope_packet(task, gap, evidence_index(evidence, supplement))
        if (gap.get("professional_packet") != packet or follow.get("outcome") != "waiting"
                or follow.get("professional_dependency") != "qualified_design_scope_interpretation"
                or follow.get("professional_packet_sha256") != sha256_json(packet)
                or not _text(follow.get("resume_condition")) or not _text(follow.get("next_action_or_dependency"))
                or set(follow.get("evidence_refs", [])) != set(packet["evidence_sha256"])
                or len(_unknown_bindings(task, gap, history)) != 1):
            return None
    except (ValueError, KeyError, OSError, TypeError):
        return None
    proof = {"kind": "professional_wait", "packet": packet, "packet_sha256": sha256_json(packet),
             "gap_event_id": gap["event_id"], "gap_sha256": sha256_json(gap),
             "followup_event_id": follow["event_id"], "followup_sha256": sha256_json(follow),
             "annotation_sha256": sha256_json(current["annotation"]), "official_verification": "not_verified"}
    return {**{key: scope[key] for key in SCOPE}, "unit_id": unit_id, "kind": "professional_review",
            "state": "awaiting_access", "reason": "SPECIALTY_PROFESSIONAL_SCOPE_WAIT",
            "dependency_gap_event_id": gap["event_id"], "basis_event_id": packet["comparison_event_id"],
            "delivery_limit": proof, "official_verification": "not_verified",
            "reasoning": follow["remaining_impact"], "resume_condition": follow["resume_condition"]}


def _gap(task, request, indexed, plan=None, *, evidence=None, candidates=None, ledger=None,
         supplement=None, task_dir=None):
    base = _base(task, request)
    if (not _text(request.get("gap_id")) or not _text(request.get("question"))
            or not _text(request.get("affected_judgment"))
            or request.get("action_kind") not in {"read_existing", "verify_known_right", "discovery", "user_fact", "professional_review"}
            or not _text(request.get("minimum_action"))
            or not _text(request.get("completion_condition"))
            or not _text(request.get("existing_material_check"))
            or not _text(request.get("next_value"))):
        raise ValueError("SPECIALTY_GAP_INVALID")
    _refs(request.get("evidence_refs", []), indexed, required=False)
    if request["action_kind"] == "user_fact":
        from product_feedback import pending
        if (not _text(request.get("product_feedback_request_id"))
                or request["product_feedback_request_id"] not in
                {row.get("request_id") for row in pending(task)}):
            raise ValueError("SPECIALTY_USER_FACT_FEEDBACK_REQUIRED")
    if request.get("unit_id"):
        _unit(task, request)
    if request["action_kind"] == "professional_review":
        if (not request.get("obligation_bindings") or any(key in request for key in
                ("source_query_id", "source_plan_gap_sha256", "product_feedback_request_id"))
                or request.get("professional_packet") != professional_scope_packet(task, request, indexed)):
            raise ValueError("SPECIALTY_PROFESSIONAL_PACKET_REQUIRED")
    if "obligation_bindings" in request:
        if not isinstance(request["obligation_bindings"], list) or not request["obligation_bindings"]:
            raise ValueError("SPECIALTY_WAITING_BINDINGS_REQUIRED")
        if request.get("action_kind") not in {"user_fact", "professional_review"}:
            if request.get("action_kind") not in {"verify_known_right", "discovery"}:
                raise ValueError("SPECIALTY_BOUND_DEPENDENCY_REQUIRED")
            if request.get("source_plan_gap_sha256"):
                if request.get("source_query_id") or request.get("action_kind") != "verify_known_right" or task_dir is None:
                    raise ValueError("SPECIALTY_STATUS_PLAN_GAP_BOUNDARY_REQUIRED")
                from necessary_completion import capability_map, status_route_gap_entry, api_record_gap_entry
                from runtime_v24 import resolved_capabilities
                cap_path = Path(task_dir) / "source-capabilities.json"
                if not cap_path.is_file():
                    raise ValueError("SPECIALTY_STATUS_PLAN_GAP_CAPABILITIES_REQUIRED")
                caps = capability_map(task, load_json(cap_path))
                browser_path = Path(task_dir) / "browser-execution-status.json"
                caps = resolved_capabilities(task, evidence, plan, caps, task_dir,
                    browser_status=load_json(browser_path) if browser_path.is_file() else None)
                fact_kinds = {binding.get("fact_kind") for binding in request.get("obligation_bindings", []) if isinstance(binding, dict)}
                source = api_record_gap_entry(task, evidence, candidates, ledger, plan, caps, request,
                    supplement=supplement, require_review=False, task_dir=task_dir) if trusted_api.enabled(task) else None
                if source is None:
                    if len(fact_kinds) != 1 or not fact_kinds <= {"status", "rights_holder", "territory"}:
                        raise ValueError("SPECIALTY_STATUS_PLAN_GAP_FACT_BOUNDARY_REQUIRED")
                    source = status_route_gap_entry(task, evidence, candidates, ledger, plan, caps, request,
                        supplement=supplement, fact_kind=next(iter(fact_kinds)))
                if (not source or request["source_plan_gap_sha256"] != source["delivery_limit"]["planning_gap_sha256"]
                        or request.get("source_capabilities_sha256") != source["delivery_limit"]["capabilities_sha256"]):
                    raise ValueError("SPECIALTY_STATUS_PLAN_GAP_PROOF_REQUIRED")
                base["source_plan_gap_proof"] = deepcopy(source["delivery_limit"])
                base["source_required_facts"] = (deepcopy(source["required_facts"])
                    if source["delivery_limit"]["kind"] == "api_record_fact_gap" else
                    ["current_status" if source["fact_kind"] in {"status", "territory"} else "rights_holder"])
            else:
                matches = [row for rows in (plan or {}).get("queries", {}).values() for row in rows
                           if row.get("query_id") == request.get("source_query_id")]
                if (len(matches) != 1 or matches[0].get("jurisdiction") != request["jurisdiction"]
                        or matches[0].get("right_type") != request["right_type"]
                        or matches[0].get("candidate_id") != request["candidate_id"]):
                    raise ValueError("SPECIALTY_SOURCE_DEPENDENCY_QUERY_REQUIRED")
                base["source_plan_entry_sha256"] = sha256_json(matches[0])
                base["source_required_facts"] = deepcopy(matches[0].get("required_facts", []))
        bindings = request["obligation_bindings"]
        if not isinstance(bindings, list) or not bindings:
            raise ValueError("SPECIALTY_WAITING_BINDINGS_REQUIRED")
        keys = []
        intake = next(row for row in events(task) if row["event_id"] == base["intake_event_id"])
        for binding in bindings:
            if not isinstance(binding, dict) or not _text(binding.get("reasoning")):
                raise ValueError("SPECIALTY_WAITING_BINDING_INVALID")
            reason = binding.get("reason")
            field = {"SPECIALTY_FACT_REQUIRED": "fact_kind", "SPECIALTY_HANDOFF_GAP_OPEN": "handoff_gap",
                     "SPECIALTY_COMPARISON_UNKNOWN": "unit_id", "SPECIALTY_DESIGN_SCOPE_UNKNOWN": "unit_id"}.get(reason)
            if not field or not _text(binding.get(field)) or not _text(binding.get("basis_event_id")):
                raise ValueError("SPECIALTY_WAITING_BINDING_INVALID")
            if base.get("source_plan_gap_proof"):
                proof = base['source_plan_gap_proof']
                api_basis = proof.get('kind') == 'api_record_fact_gap'
                allowed = {"SPECIALTY_FACT_REQUIRED", "SPECIALTY_HANDOFF_GAP_OPEN"}
                if api_basis and request.get("unavailable_comparison"):
                    allowed.add("SPECIALTY_COMPARISON_UNKNOWN")
                proof_basis = binding.get("protection_fact_event_id") if reason == "SPECIALTY_COMPARISON_UNKNOWN" else binding["basis_event_id"]
                if (reason not in allowed
                        or (proof_basis not in proof['basis_event_ids'] if api_basis else
                            binding.get("fact_kind") != proof["fact_kind"] or binding["basis_event_id"] != proof["basis_event_id"])
                        or not _plan_handoff_binding_valid({**request, **base}, binding,
                            [row for row in events(task) if _scope(row) == _scope(request)
                             and row.get("intake_event_id") == base["intake_event_id"]])):
                    raise ValueError("SPECIALTY_STATUS_PLAN_GAP_FACT_BOUNDARY_REQUIRED")
            if field == "handoff_gap" and binding[field] not in intake["verification_gaps"]:
                raise ValueError("SPECIALTY_WAITING_BINDING_INVALID")
            basis = next((row for row in events(task) if row["event_id"] == binding["basis_event_id"]), {})
            if not _dependency_matches({**request, **base}, binding, basis):
                raise ValueError("SPECIALTY_DEPENDENCY_FACT_MISMATCH")
            keys.append((reason, binding[field]))
        if len(keys) != len(set(keys)) or len(_unknown_bindings(task, {**request, **base}, events(task))) != len(bindings):
            raise ValueError("SPECIALTY_WAITING_BASIS_NOT_CURRENT_UNKNOWN")
    if request.get("unavailable_comparison") is not None:
        dependency = request["unavailable_comparison"]
        proof = base.get("source_plan_gap_proof", {})
        if (proof.get("kind") != "api_record_fact_gap" or not isinstance(dependency, dict)
                or not _list(dependency.get("required_facts"))
                or not set(dependency["required_facts"]) <= set(proof.get("required_facts", []))
                or not set(dependency["required_facts"]) <= {"protection_content", "representative_figures"}
                or not _text(dependency.get("reasoning")) or not _text(dependency.get("readable_parts_review"))
                or not _list(dependency.get("unit_ids", []), nonempty=False)
                or not any(binding.get("fact_kind") == "protection" for binding in request.get("obligation_bindings", []))):
            raise ValueError("SPECIALTY_API_COMPARISON_DEPENDENCY_REQUIRED")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _followup(task, request, indexed):
    base = _base(task, request)
    gap = next((row for row in reversed(events(task)) if row["kind"] == "gap"
                and row["gap_id"] == request.get("gap_id") and _scope(row) == _scope(request)
                and row["intake_event_id"] == base["intake_event_id"]), None)
    if gap is None or request.get("gap_event_id") != gap["event_id"]:
        raise ValueError("SPECIALTY_GAP_LINK_REQUIRED")
    if (request.get("outcome") not in GAP_OUTCOMES or not _text(request.get("result_review"))
            or not _text(request.get("remaining_impact"))):
        raise ValueError("SPECIALTY_FOLLOWUP_INVALID")
    _refs(request.get("evidence_refs", []), indexed, required=request["outcome"] == "resolved")
    if request["outcome"] == "resolved":
        history = events(task)
        after_gap = history[history.index(gap) + 1:]
        decisions = {row["event_id"]: row for row in after_gap if _scope(row) == _scope(request)
                     and row["intake_event_id"] == base["intake_event_id"]
                     and row["kind"] in {"fact", "comparison", "exemption"}}
        if (not _list(request.get("resolved_event_ids"))
                or not set(request["resolved_event_ids"]) <= set(decisions)):
            raise ValueError("SPECIALTY_RESOLVED_JUDGMENT_REQUIRED")
    if request["outcome"] in {"continue", "waiting", "limited"}:
        if not _text(request.get("next_action_or_dependency")):
            raise ValueError("SPECIALTY_FOLLOWUP_DEPENDENCY_REQUIRED")
    if gap.get("action_kind") == "professional_review" and request["outcome"] != "resolved":
        if (request["outcome"] != "waiting" or not _text(request.get("resume_condition"))
                or request.get("professional_dependency") != "qualified_design_scope_interpretation"
                or request.get("professional_packet_sha256") != sha256_json(gap["professional_packet"])
                or gap["professional_packet"] != professional_scope_packet(task, gap, indexed)
                or set(request.get("evidence_refs", [])) != set(gap["professional_packet"]["evidence_sha256"])):
            raise ValueError("SPECIALTY_PROFESSIONAL_WAIT_REQUIRED")
    if request["outcome"] == "continue" and not _text(request.get("next_value_reasoning")):
        raise ValueError("SPECIALTY_FOLLOWUP_NEXT_VALUE_REQUIRED")
    if request["outcome"] == "limited" and (not _text(request.get("limit_evidence"))
                                             or not _text(request.get("restore_condition"))
                                             or request.get("limit_kind") not in
                                             {"no_lawful_route", "source_unavailable_with_no_recovery",
                                              "evidence_not_obtainable_within_scope"}):
        raise ValueError("SPECIALTY_LIMIT_BASIS_REQUIRED")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _change(task, request, indexed):
    base = _base(task, request)
    if (not _text(request.get("change_id")) or not _text(request.get("change_kind"))
            or not _text(request.get("impact_reasoning"))
            or not _list(request.get("affected_event_ids"), nonempty=False)
            or type(request.get("substantive")) is not bool):
        raise ValueError("SPECIALTY_CHANGE_INVALID")
    _refs(request.get("evidence_refs", []), indexed, required=request["substantive"])
    history = {row["event_id"]: row for row in events(task) if _scope(row) == _scope(request)
               and row.get("intake_event_id") == base["intake_event_id"]}
    if not set(request["affected_event_ids"]) <= set(history):
        raise ValueError("SPECIALTY_CHANGE_TARGET_INVALID")
    if request["substantive"] and not request["affected_event_ids"]:
        raise ValueError("SPECIALTY_CHANGE_IMPACT_REQUIRED")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _change_review(task, request, indexed):
    base = _base(task, request)
    change = next((row for row in events(task) if row["kind"] == "change"
                   and row["event_id"] == request.get("change_event_id")
                   and _scope(row) == _scope(request)
                   and row["intake_event_id"] == base["intake_event_id"]), None)
    if change is None or not change["substantive"] or not _text(request.get("recheck_reasoning")):
        raise ValueError("SPECIALTY_CHANGE_REVIEW_INVALID")
    _refs(request.get("evidence_refs"), indexed)
    if request.get("outcome") not in {"continues", "changed", "unknown"}:
        raise ValueError("SPECIALTY_CHANGE_OUTCOME_INVALID")
    if (not _list(request.get("reviewed_affected_event_ids"))
            or set(request["reviewed_affected_event_ids"]) != set(change["affected_event_ids"])):
        raise ValueError("SPECIALTY_CHANGE_IMPACT_REVIEW_INCOMPLETE")
    if request["outcome"] == "changed":
        history = events(task)
        after_change = history[history.index(change) + 1:]
        replacements = {row["event_id"]: row for row in after_change if _scope(row) == _scope(request)
                        and row["intake_event_id"] == base["intake_event_id"]
                        and row["kind"] in {"material", "fact", "inventory", "comparison", "exemption", "handoff_classification", "handoff_discovery_scope"}}
        originals = {row["event_id"]: row for row in history if row["event_id"] in change["affected_event_ids"]}
        mapping = request.get("replacement_by_affected")
        if (not isinstance(mapping, dict) or set(mapping) != set(originals)
                or any(not _list(value) or not set(value) <= set(replacements) for value in mapping.values())):
            raise ValueError("SPECIALTY_CHANGE_REPLACEMENT_REQUIRED")
        for old_id, new_ids in mapping.items():
            old = originals[old_id]
            if not any(replacements[new_id]["kind"] == old["kind"]
                       and (old["kind"] != "fact" or replacements[new_id]["fact_kind"] == old["fact_kind"])
                       and (old["kind"] != "comparison" or replacements[new_id]["unit_id"] == old["unit_id"])
                       and (old["kind"] != "exemption" or replacements[new_id]["action_id"] == old["action_id"])
                       and (old["kind"] not in {"handoff_classification", "handoff_discovery_scope"} or
                            replacements[new_id]["handoff_gap"] == old["handoff_gap"])
                       for new_id in new_ids):
                raise ValueError("SPECIALTY_CHANGE_REPLACEMENT_KIND_MISMATCH")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _batch(task, request, evidence, indexed):
    base = _base(task, request)
    if (not _text(request.get("batch_id")) or not _list(request.get("received_material_event_ids"), nonempty=False)
            or not _list(request.get("processed_material_event_ids"), nonempty=False)
            or not _list(request.get("received_evidence_refs"), nonempty=False)
            or not _text(request.get("disposition_reasoning"))):
        raise ValueError("SPECIALTY_BATCH_INVALID")
    _refs(request["received_evidence_refs"], indexed, required=False)
    valid_batches = {run.get("run_id") for run in evidence.get("source_runs", []) if isinstance(run, dict)}
    valid_batches.update("import:" + ref for ref in indexed)
    if request["batch_id"] not in valid_batches:
        raise ValueError("SPECIALTY_BATCH_SOURCE_UNKNOWN")
    if request["batch_id"].startswith("import:"):
        if request["batch_id"][7:] not in request["received_evidence_refs"]:
            raise ValueError("SPECIALTY_BATCH_IMPORT_REF_MISSING")
    elif any(indexed[ref].get("source_run_id") != request["batch_id"]
             for ref in request["received_evidence_refs"]):
        raise ValueError("SPECIALTY_BATCH_SOURCE_BINDING_INVALID")
    dispositions = request.get("disposition_by_evidence_ref")
    if (not isinstance(dispositions, dict) or set(dispositions) != set(request["received_evidence_refs"])
            or any(not _text(reason) for reason in dispositions.values())):
        raise ValueError("SPECIALTY_BATCH_EVIDENCE_DISPOSITION_REQUIRED")
    materials = {row["event_id"]: row for row in events(task) if row["kind"] == "material"
                 and _scope(row) == _scope(request)
                 and row["intake_event_id"] == base["intake_event_id"]}
    if (not set(request["received_material_event_ids"]) <= set(materials)
            or not set(request["processed_material_event_ids"]) <= set(request["received_material_event_ids"])):
        raise ValueError("SPECIALTY_BATCH_MATERIAL_INVALID")
    if any(not set(materials[mid]["evidence_refs"]) <= set(request["received_evidence_refs"])
           for mid in request["received_material_event_ids"]):
        raise ValueError("SPECIALTY_BATCH_SOURCE_MATERIAL_MISMATCH")
    skipped = request.get("unread_disposition_reasons", {})
    if (not isinstance(skipped, dict) or any(not _text(reason) for reason in skipped.values())
            or any(mid not in request["processed_material_event_ids"] for mid in skipped)
            or any(materials[mid]["status"] == "acquired" and mid not in skipped
                   for mid in request["processed_material_event_ids"])):
        raise ValueError("SPECIALTY_BATCH_UNREAD_MATERIAL_CANNOT_COMPLETE")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _handoff(task, request):
    base = _base(task, request)
    if (request.get("destination") not in {"07", "08", "09", "10"}
            or not _list(request.get("result_event_ids"))
            or not _text(request.get("handoff_reasoning"))):
        raise ValueError("SPECIALTY_HANDOFF_INVALID")
    rows = {row["event_id"]: row for row in events(task) if _scope(row) == _scope(request)
            and row.get("intake_event_id") == base["intake_event_id"]
            and row["kind"] in {"fact", "exemption", "comparison", "gap", "followup", "change_review"}}
    if not set(request["result_event_ids"]) <= set(rows):
        raise ValueError("SPECIALTY_HANDOFF_RESULT_INVALID")
    return {**base, **{key: deepcopy(request[key]) for key in request if key not in base}}


def _record_into(task_dir, task, evidence, candidates, ledger, supplement, indexed, request, *,
                 plan=None, triage_task=None, transaction=None):
    """Validate and append only to a caller-owned detached task; no file writes."""
    triage_task = triage_task if triage_task is not None else task
    request = deepcopy(request)
    kind = request.get("kind")
    if kind == "intake" and not request.get("assessment_date"):
        request = {**request, "assessment_date": datetime.now().astimezone().date().isoformat(),
                   "assessment_date_basis": "specialty_start_local_date"}
    elif kind == "intake":
        request = {**request, "assessment_date_basis": request.get("assessment_date_basis")
                   or "recorded_specialty_input_date"}
    if kind not in KINDS or not _text(request.get("reviewer")) or not _text(request.get("reason")):
        raise ValueError("SPECIALTY_INPUT_INVALID")
    scope = _scope(request)
    if scope[3] not in RIGHTS or any(not _text(value) for value in scope):
        raise ValueError("SPECIALTY_SCOPE_INVALID")
    if kind == "intake":
        payload = _validate_intake(task, evidence, candidates, ledger, supplement, request,
            current=_current(triage_task, evidence, candidates, ledger, supplement, scope))
        prior = _intake(task, scope)
        if (prior and prior["selected_handoff_event_id"] == payload["selected_handoff_event_id"]
                and prior["assessment_date"] == payload["assessment_date"]):
            return prior, False
    else:
        _current(triage_task, evidence, candidates, ledger, supplement, scope)
        if kind == "material":
            request = trusted_api.bind_material_candidate(task, request, candidates)
            payload = _material(task, request, indexed)
        elif kind == "handoff_classification":
            payload = _handoff_classification(task, request, indexed)
        elif kind == "handoff_discovery_scope":
            payload = _handoff_discovery_scope(task, request, indexed)
        elif kind == "fact":
            payload = _fact(task, request, indexed, evidence=evidence)
        elif kind == "exemption":
            payload = _exemption(task, request)
        elif kind == "inventory":
            payload = _inventory(task, request, indexed)
        elif kind == "comparison":
            payload = _comparison(task, request, indexed)
        elif kind == "gap":
            payload = _gap(task, request, indexed, plan if plan is not None else load_json(task_dir / "search-plan.json"),
                evidence=evidence, candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)
        elif kind == "followup":
            payload = _followup(task, request, indexed)
        elif kind == "change":
            payload = _change(task, request, indexed)
        elif kind == "change_review":
            payload = _change_review(task, request, indexed)
        elif kind == "batch":
            payload = _batch(task, request, evidence, indexed)
        elif kind == "handoff":
            payload = _handoff(task, request)
        else:
            raise ValueError("SPECIALTY_KIND_INVALID")
    payload.update(reviewer=request["reviewer"], reason=request["reason"])
    if transaction is not None:
        payload.update(transaction)
    return _append(task, kind, payload), True


def comparison_blockers(review):
    """The same factual unknowns used by work projection and atomic closure."""
    if review.get('disposition') == 'pending':
        return [{'reason': 'SPECIALTY_UNIT_PENDING', 'unit_id': review['unit_id']}]
    if review.get('disposition') != 'compared':
        return []
    result = []
    if any(row.get('result') == 'unknown' for row in review.get('elements', review.get('views', []))):
        result.append({'reason': 'SPECIALTY_COMPARISON_UNKNOWN', 'unit_id': review['unit_id']})
    if any(row.get('treatment') == 'unknown' for row in review.get('design_scope_parts', [])):
        result.append({'reason': 'SPECIALTY_DESIGN_SCOPE_UNKNOWN', 'unit_id': review['unit_id']})
    return result


TRANSACTIONS = 'specialty_transaction_receipts'


def _transaction_enabled(task):
    return (task.get('assessment_revision') == 'known-findings-risk-v1'
            or task.get('presentation_policy_revision') == 'operator-report-v1')


def _transaction_basis(task, evidence, candidates, ledger, supplement, plan, scopes, source_fingerprints=None):
    from final_review import inputs
    frame = {key: value for key, value in task.items() if key not in {EVENTS, TRANSACTIONS}}
    material = inputs(evidence, candidates, ledger, plan, frame, supplement)
    material['current_specialty_intakes'] = {
        str(scope): sha256_json(_intake(task, scope)) for scope in sorted(scopes)}
    material['retained_source_fingerprints'] = source_fingerprints or {}
    return sha256_json(material)


def _transaction_source_fingerprints(task_dir, context):
    """Reuse retained-file scanning; never reuse a passed flag across calls."""
    from common import resolve_retained_path, sha256_file
    from delivery_versions_stage_e import _retained_files
    task, evidence, candidates, ledger, supplement, indexed = context
    def check_originals(value):
        if isinstance(value, dict):
            path, fingerprint = value.get('path'), value.get('sha256')
            if _text(path) and '://' not in path and _text(fingerprint):
                resolve_retained_path(task_dir, path, expected_sha256=fingerprint, expected_bytes=value.get('bytes'))
            for child in value.values():
                check_originals(child)
        elif isinstance(value, list):
            for child in value:
                check_originals(child)
    # Static originals retain their declared byte identity even on a fresh
    # request. A changed file cannot be accepted under an unchanged source ref.
    check_originals(indexed)
    fingerprints = _retained_files(task_dir, {'task': task, 'evidence': evidence,
        'candidates': candidates, 'ledger': ledger, 'supplement': supplement})
    manifest_path = task_dir / 'recovery-manifest.json'
    if manifest_path.is_file():
        manifest = load_json(manifest_path)
        mappings = {row.get('source_path'): row for row in manifest.get('file_mappings', [])}
        fingerprints[str(manifest_path)] = sha256_file(manifest_path)
        for source in list(fingerprints):
            mapping = mappings.get(source)
            if mapping:
                actual = resolve_retained_path(task_dir, source, expected_sha256=mapping['sha256'],
                                               expected_bytes=mapping.get('bytes'))
                del fingerprints[source]
                fingerprints[str(actual)] = sha256_file(actual)
    for name in ('source-capabilities.json', 'browser-execution-status.json'):
        path = task_dir / name
        fingerprints[str(path)] = sha256_file(path) if path.is_file() else None
    return fingerprints


def _transaction_receipts(task):
    rows = task.get(TRANSACTIONS, [])
    if not isinstance(rows, list):
        raise ValueError('SPECIALTY_TRANSACTION_RECEIPTS_INVALID')
    by_id = {}
    for row in rows:
        if (not isinstance(row, dict) or not _text(row.get('transaction_id'))
                or row.get('transaction_id') in by_id
                or row.get('receipt_sha256') != sha256_json({key: value for key, value in row.items() if key != 'receipt_sha256'})):
            raise ValueError('SPECIALTY_TRANSACTION_RECEIPT_CHANGED')
        if (row.get('schema') != 'IPR-SPECIALTY-TRANSACTION/1.0'
                or not _text(row.get('request_sha256')) or not _text(row.get('input_sha256'))
                or not isinstance(row.get('event_ids'), list) or not row['event_ids']
                or not all(_text(key) for key in row['event_ids'])
                or not isinstance(row.get('event_sha256s'), dict)
                or set(row['event_ids']) != set(row['event_sha256s'])
                or not isinstance(row.get('aliases'), dict)
                or not isinstance(row.get('derived_gaps'), list)
                or not isinstance(row.get('scopes'), list) or not row['scopes']
                or any(not isinstance(scope, list) or len(scope) != len(SCOPE)
                       or any(not _text(value) for value in scope) for scope in row['scopes'])):
            raise ValueError('SPECIALTY_TRANSACTION_RECEIPT_INVALID')
        by_id[row['transaction_id']] = row
    return by_id


def _resolve_event_aliases(value, aliases):
    if isinstance(value, dict):
        if set(value) == {'$event'}:
            alias = value['$event']
            if not _text(alias) or alias not in aliases:
                raise ValueError('SPECIALTY_EVENT_ALIAS_NOT_PREVIOUS')
            return aliases[alias]
        return {key: _resolve_event_aliases(child, aliases) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolve_event_aliases(child, aliases) for child in value]
    return deepcopy(value)


def _comparison_close_requests(task, comparison, closure, indexed, common):
    """Build dependent IDs only; caller supplies the actual disposition/proof."""
    blockers = comparison_blockers(comparison)
    if not blockers:
        if closure.get('gap') is not None or closure.get('followup') is not None:
            raise ValueError('SPECIALTY_CLOSE_NO_DERIVED_GAP')
        return None, None, blockers
    if (comparison['disposition'] != 'compared' or not isinstance(closure.get('gap'), dict)
            or not isinstance(closure.get('followup'), dict)):
        raise ValueError('SPECIALTY_CLOSE_DISPOSITION_AND_RECOVERY_REQUIRED')
    gap = {**common, **deepcopy(closure['gap']), 'kind': 'gap'}
    reasons = gap.pop('blocker_reasons', [row['reason'] for row in blockers])
    if not _list(reasons) or not set(reasons) <= {row['reason'] for row in blockers}:
        raise ValueError('SPECIALTY_CLOSE_DERIVED_BINDING_INVALID')
    # Only asserted facts and exact component IDs are copied. No reading,
    # status, missing-fact reason, availability or recovery proof is invented.
    gap.setdefault('evidence_refs', deepcopy(comparison.get('evidence_refs', [])))
    gap.update(inventory_event_id=comparison['inventory_event_id'], unit_id=comparison['unit_id'],
        basis_event_id=comparison['event_id'], comparison_event_id=comparison['event_id'],
        affected_judgment=' / '.join(row['reason'] + ':' + row['unit_id'] for row in blockers if row['reason'] in reasons))
    gap.setdefault('gap_id', stable_id('SPECIALTY-GAP', task['task_id'], comparison['event_id'], sha256_json(reasons)))
    binding_reason = gap.pop('binding_reasoning', common['reason'])
    bindings = [{'reason': row['reason'], 'unit_id': row['unit_id'], 'basis_event_id': comparison['event_id'],
        'reasoning': binding_reason,
        **({'protection_fact_event_id': gap['protection_fact_event_id']} if gap.get('protection_fact_event_id') else {})}
        for row in blockers if row['reason'] in reasons]
    gap.pop('protection_fact_event_id', None)
    additional = gap.pop('additional_bindings', [])
    if not isinstance(additional, list):
        raise ValueError('SPECIALTY_CLOSE_ADDITIONAL_BINDINGS_INVALID')
    if 'obligation_bindings' in gap:
        raise ValueError('SPECIALTY_CLOSE_BINDINGS_ARE_DERIVED')
    gap['obligation_bindings'] = bindings + additional
    if gap.get('action_kind') == 'professional_review':
        gap['professional_packet'] = professional_scope_packet(task, gap, indexed)
    follow = {**common, **deepcopy(closure['followup']), 'kind': 'followup', 'gap_id': gap['gap_id']}
    if gap.get('professional_packet'):
        follow['professional_packet_sha256'] = sha256_json(gap['professional_packet'])
    return gap, follow, blockers


def _record_transaction(task_dir, request, context):
    from decision_workflow import decision_snapshot
    task, evidence, candidates, ledger, supplement, indexed = context
    if not _transaction_enabled(task):
        raise ValueError('SPECIALTY_TRANSACTION_POLICY_REQUIRED')
    if request.get('kind') == 'comparison_close':
        submissions = [request]
    else:
        submissions = request.get('events')
        if not isinstance(submissions, list) or not submissions:
            raise ValueError('SPECIALTY_TRANSACTION_EVENTS_REQUIRED')
    if not _text(request.get('reviewer')) or not _text(request.get('reason')):
        raise ValueError('SPECIALTY_TRANSACTION_REVIEW_REQUIRED')
    if 'scope' in request and not isinstance(request['scope'], dict):
        raise ValueError('SPECIALTY_SCOPE_INVALID')
    if any(key in request and request[key] != value for key, value in request.get('scope', {}).items()):
        raise ValueError('SPECIALTY_SCOPE_CONFLICT')
    shared = {key: deepcopy(request[key]) for key in (*SCOPE, 'intake_event_id', 'assessment_date', 'reviewer', 'reason') if key in request}
    shared.update(request.get('scope', {}))
    if set(request.get('scope', {})) - set(SCOPE):
        raise ValueError('SPECIALTY_SCOPE_INVALID')
    plan = load_json(task_dir / 'search-plan.json')
    source_fingerprints = _transaction_source_fingerprints(task_dir, context)
    request_hash = sha256_json(request)
    if 'transaction_id' in request and not _text(request['transaction_id']):
        raise ValueError('SPECIALTY_TRANSACTION_ID_INVALID')
    transaction_id = request.get('transaction_id') or stable_id('SPECIALTY-TX', task['task_id'], request_hash)
    if not _text(transaction_id):
        raise ValueError('SPECIALTY_TRANSACTION_ID_INVALID')
    existing = _transaction_receipts(task).get(transaction_id)
    if existing:
        if existing['request_sha256'] != request_hash:
            raise ValueError('SPECIALTY_TRANSACTION_ID_REUSED')
        original_rows = {row['event_id']: row for row in events(task)}
        if any(key not in original_rows or sha256_json(original_rows[key]) != fingerprint
               for key, fingerprint in existing['event_sha256s'].items()):
            raise ValueError('SPECIALTY_TRANSACTION_EVENT_CHANGED')
        scopes = {tuple(row) for row in existing['scopes']}
        with decision_snapshot(task, evidence, candidates, plan, ledger, supplement):
            for scope in scopes:
                _current(task, evidence, candidates, ledger, supplement, scope)
            if _transaction_basis(task, evidence, candidates, ledger, supplement, plan, scopes,
                                  source_fingerprints) != existing['input_sha256']:
                raise ValueError('SPECIALTY_TRANSACTION_INPUT_CHANGED')
            view = project(task, evidence, candidates, ledger, supplement=supplement, plan=plan, task_dir=task_dir)
        if _transaction_source_fingerprints(task_dir, context) != source_fingerprints:
            raise ValueError('SPECIALTY_TRANSACTION_SOURCE_CHANGED_DURING_RECORD')
        return {'status': 'reused', 'transaction_id': transaction_id,
            'events': [deepcopy(original_rows[key]) for key in existing['event_ids']],
            'aliases': deepcopy(existing['aliases']), 'derived_gaps': deepcopy(existing['derived_gaps']), 'projection': view}
    pending = deepcopy(task)
    aliases, rows, derived, scopes = {}, [], [], set()
    appended = 0
    reserved = {'event_id', 'recorded_at', 'previous_event_id', 'transaction_id',
                'transaction_request_sha256', 'transaction_ordinal'}
    def append_one(child, alias=None):
        nonlocal appended
        if not isinstance(child, dict) or set(child).intersection(reserved):
            raise ValueError('SPECIALTY_TRANSACTION_EVENT_INVALID')
        if alias is not None and (not _text(alias) or alias in aliases):
            raise ValueError('SPECIALTY_EVENT_ALIAS_DUPLICATE')
        child_scope = child.get('scope', {})
        if (not isinstance(child_scope, dict) or set(child_scope) - set(SCOPE)
                or any(key in child and child[key] != value for key, value in child_scope.items())):
            raise ValueError('SPECIALTY_SCOPE_CONFLICT')
        actual = _resolve_event_aliases({**shared, **child_scope, **child}, aliases)
        actual.pop('alias', None)
        actual.pop('scope', None)
        scope = _scope(actual)
        if actual.get('kind') != 'intake':
            intake = _intake(pending, scope)
            if intake:
                actual.setdefault('intake_event_id', intake['event_id'])
                actual.setdefault('assessment_date', intake['assessment_date'])
        row, written = _record_into(task_dir, pending, evidence, candidates, ledger, supplement, indexed, actual,
            plan=plan, triage_task=task, transaction={'transaction_id': transaction_id,
                'transaction_request_sha256': request_hash, 'transaction_ordinal': len(rows) + 1})
        rows.append(row)
        scopes.add(scope)
        appended += int(written)
        if alias is not None:
            aliases[alias] = row['event_id']
        return row
    # Inputs of the memo remain unchanged; only the detached specialty journal
    # is appended. Current selected checks therefore reuse the original indexes.
    with decision_snapshot(task, evidence, candidates, plan, ledger, supplement):
        for submission in submissions:
            if not isinstance(submission, dict):
                raise ValueError('SPECIALTY_TRANSACTION_EVENT_INVALID')
            if submission.get('kind') != 'comparison_close':
                append_one(submission, submission.get('alias'))
                continue
            closure = _resolve_event_aliases(submission, aliases)
            if not isinstance(closure.get('comparison'), dict):
                raise ValueError('SPECIALTY_CLOSE_COMPARISON_REQUIRED')
            alias = closure.get('alias')
            comparison = append_one({**{key: closure[key] for key in shared if key in closure},
                **({'scope': closure['scope']} if 'scope' in closure else {}),
                **closure['comparison'], 'kind': 'comparison'}, alias)
            common = {key: comparison[key] for key in (*SCOPE, 'intake_event_id', 'assessment_date', 'reviewer', 'reason')}
            gap, follow, blockers = _comparison_close_requests(pending, comparison, closure, indexed, common)
            derived.extend({**row, 'basis_event_id': comparison['event_id']} for row in blockers)
            if gap is not None:
                gap = append_one(gap, alias + '.gap' if alias else None)
                follow['gap_event_id'] = gap['event_id']
                append_one(follow, alias + '.followup' if alias else None)
    # Refresh only once against the final draft, after every child validated.
    # An exception here also leaves the original task byte-for-byte unchanged.
    with decision_snapshot(pending, evidence, candidates, plan, ledger, supplement):
        view = project(pending, evidence, candidates, ledger, supplement=supplement, plan=plan, task_dir=task_dir)
        basis = _transaction_basis(pending, evidence, candidates, ledger, supplement, plan, scopes, source_fingerprints)
    if _transaction_source_fingerprints(task_dir, context) != source_fingerprints:
        raise ValueError('SPECIALTY_TRANSACTION_SOURCE_CHANGED_DURING_RECORD')
    receipt = {'schema': 'IPR-SPECIALTY-TRANSACTION/1.0', 'transaction_id': transaction_id,
        'request_sha256': request_hash, 'input_sha256': basis, 'scopes': [list(scope) for scope in sorted(scopes)],
        'event_ids': [row['event_id'] for row in rows], 'event_sha256s': {row['event_id']: sha256_json(row) for row in rows},
        'aliases': deepcopy(aliases), 'derived_gaps': deepcopy(derived), 'recorded_at': now_iso()}
    receipt['receipt_sha256'] = sha256_json(receipt)
    pending.setdefault(TRANSACTIONS, []).append(receipt)
    atomic_write_json(task_dir / 'task.json', pending)
    return {'status': 'recorded', 'transaction_id': transaction_id, 'appended_event_count': appended,
        'events': rows, 'aliases': aliases, 'derived_gaps': derived, 'projection': view}


def record(task_dir: Path, request: dict) -> dict:
    """Single legacy event, or one gated atomic transaction on a local draft."""
    from provider_utils import evidence_lock
    if not isinstance(request, dict):
        raise ValueError('SPECIALTY_INPUT_OBJECT_REQUIRED')
    task_dir = task_dir.resolve()
    with evidence_lock(task_dir):
        context = _context(task_dir)
        task = context[0]
        if not enabled(task) or task.get('state') == 'completed':
            raise ValueError('SPECIALTY_NOT_WRITABLE')
        if request.get('kind') in {'transaction', 'comparison_close'} or request.get('kind') is None and 'events' in request:
            return _record_transaction(task_dir, request, context)
        event, appended = _record_into(task_dir, *context, request)
        if appended:
            atomic_write_json(task_dir / 'task.json', task)
        return event

def _source_gap_proof_matches(task, fresh, saved):
    """Compare reviewed judgment inputs after the caller revalidates the fresh source.

    A v3 API gap hash includes quota advisory bookkeeping. Its judgment is
    already bound by the current planner, exact candidate and M06 event hashes.
    Keep the saved receipt immutable; only compare the fresh proof here.
    """
    if not isinstance(fresh, dict) or not isinstance(saved, dict):
        return False
    ignored = {'plan_sha256', 'candidate_sha256', 'capabilities_sha256',
        'followup_sha256', 'recovery_condition'}
    if (task.get('retrieval_workflow_revision') == 'api-first-v3'
            and fresh.get('kind') == saved.get('kind') == 'api_record_fact_gap'):
        ignored.add('planning_gap_sha256')
        if not all(fresh.get(key) and saved.get(key) for key in
                ('candidate_id','scenario_id','jurisdiction','right_type',
                 'annotation_sha256','required_facts','basis_event_ids','event_sha256')):
            return False
    return ({key:value for key,value in fresh.items() if key not in ignored}
        == {key:value for key,value in saved.items() if key not in ignored})


def project(task: dict, evidence: dict, candidates: dict, ledger: dict, *, supplement=None,
            source_work=None, plan=None, capabilities=None, task_dir=None) -> dict:
    """Project module-06 progress without changing triage or risk decisions."""
    if not enabled(task):
        return {"revision": None}
    from candidate_triage_stage import events as triage_events
    from decision_workflow import triage_summary
    history = events(task)
    handoffs = [row for row in triage_events(task) if row["kind"] == "selected_handoff"
                and row["right_type"] in RIGHTS]
    triage = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)
    records = [row for row in triage["records"] if row.get("current")
               and row.get("decision") == "selected" and row.get("right_type") in RIGHTS]
    scopes = []
    for selected in records:
        scope = _scope(selected)
        relevant = [row for row in history if _scope(row) == scope]
        current_handoff = next((row for row in reversed(handoffs) if _scope(row) == scope
                                and row["annotation_id"] == selected["annotation"]["annotation_id"]), None)
        intake = next((row for row in reversed(relevant) if row["kind"] == "intake"
                       and current_handoff and row["selected_handoff_event_id"] == current_handoff["event_id"]), None)
        blockers = []
        current_results = []
        handoff_results = []
        handoff_classifications = []
        def block(reason, **extra):
            blockers.append({"reason": reason, **extra})
        if current_handoff is None:
            block("SPECIALTY_SELECTED_HANDOFF_PENDING")
        if intake is None:
            block("SPECIALTY_INTAKE_PENDING")
        if intake:
            superseded = {old_id for review in relevant if review["kind"] == "change_review"
                          and review["outcome"] == "changed"
                          for old_id in review["reviewed_affected_event_ids"]}
            facts = [row for row in relevant if row["kind"] == "fact"
                     and row["intake_event_id"] == intake["event_id"]
                     and row["event_id"] not in superseded]
            resolved_conflicts = {ref for row in facts for ref in row.get("resolves_fact_event_ids", [])}
            for row in facts:
                if row["outcome"] == "conflicted" and row["event_id"] not in resolved_conflicts:
                    block("SPECIALTY_FACT_CONFLICT", fact_event_id=row["event_id"])
            supported = {row["fact_kind"] for row in facts if row["outcome"] == "supported"}
            resolved_handoff = {gap for row in facts if row["outcome"] == "supported"
                                for gap in row.get("resolves_handoff_gaps", [])}
            for gap in intake["verification_gaps"]:
                classified = next((row for row in reversed(relevant) if row["kind"] == "handoff_classification"
                                   and row["intake_event_id"] == intake["event_id"] and row["handoff_gap"] == gap
                                   and row["event_id"] not in superseded), None)
                if classified and len(classified["fact_kinds"]) > 1:
                    for fact_kind in classified["fact_kinds"]:
                        if not any(row["outcome"] == "supported" and row["fact_kind"] == fact_kind
                                   and gap in row.get("resolves_handoff_gaps", []) for row in facts):
                            block("SPECIALTY_HANDOFF_GAP_OPEN", handoff_gap=gap, fact_kind=fact_kind,
                                  handoff_classification_event_id=classified["event_id"])
                elif gap not in resolved_handoff:
                    block("SPECIALTY_HANDOFF_GAP_OPEN", handoff_gap=gap)
            materials = [row for row in relevant if row["kind"] == "material"
                         and row["intake_event_id"] == intake["event_id"]
                         and row["event_id"] not in superseded]
            batches = [row for row in relevant if row["kind"] == "batch"
                       and row["intake_event_id"] == intake["event_id"]]
            processed = {ref for row in batches for ref in row["processed_material_event_ids"]}
            accounted_refs = {ref for row in batches for ref in row["received_evidence_refs"]}
            candidate = next((candidate for rows in candidates.values() if isinstance(rows, list)
                              for candidate in rows if isinstance(candidate, dict)
                              and candidate.get("candidate_id") == scope[0]), {})
            candidate_refs = {ref for ref in candidate.get("evidence_refs", []) if isinstance(ref, str)}
            candidate_refs.update(source.get("evidence_id") for source in candidate.get("sources", [])
                                  if isinstance(source, dict) and _text(source.get("evidence_id")))
            for ref in sorted(candidate_refs - accounted_refs):
                block("SPECIALTY_CANDIDATE_MATERIAL_UNACCOUNTED", evidence_ref=ref)
            for material in materials:
                if material["event_id"] not in processed:
                    block("SPECIALTY_MATERIAL_UNACCOUNTED", material_event_id=material["event_id"])
            exemptions = [row for row in relevant if row["kind"] == "exemption"
                          and row["intake_event_id"] == intake["event_id"]
                          and row["event_id"] not in superseded]
            all_exempt = any(row["action_id"] == "all_comparisons" for row in exemptions)
            if "identity" not in supported:
                block("SPECIALTY_FACT_REQUIRED", fact_kind="identity")
            if all_exempt:
                if not any(row["outcome"] == "supported" and "all_comparisons" in row.get("excludes_action_ids", [])
                           for row in facts):
                    block("SPECIALTY_EXEMPTION_DECISIVE_FACT_REQUIRED")
            else:
                for kind in ("territory", "status"):
                    if kind not in supported:
                        block("SPECIALTY_FACT_REQUIRED", fact_kind=kind)
            inventories = [row for row in relevant if row["kind"] == "inventory"
                           and row["intake_event_id"] == intake["event_id"]
                           and row["event_id"] not in superseded]
            if not all_exempt:
                for kind in ("protection", "product"):
                    if kind not in supported:
                        block("SPECIALTY_FACT_REQUIRED", fact_kind=kind)
                if selected["right_type"] == "unregistered_design" and "legal_conditions" not in supported:
                    block("SPECIALTY_FACT_REQUIRED", fact_kind="legal_conditions")
                if selected["right_type"] == "unregistered_design":
                    for row in facts:
                        if row["fact_kind"] == "legal_conditions" and any(
                                item["outcome"] != "supported" for item in row.get("conditions", [])):
                            block("SPECIALTY_UNREGISTERED_CONDITION_PENDING", fact_event_id=row["event_id"])
                if selected["right_type"] == "design" and "rights_holder" not in supported:
                    block("SPECIALTY_FACT_REQUIRED", fact_kind="rights_holder")
                if not inventories:
                    block("SPECIALTY_INVENTORY_PENDING")
                else:
                    latest = inventories[-1]
                    comparisons = [row for row in relevant if row["kind"] == "comparison"
                                   and row.get("inventory_event_id") == latest["event_id"]
                                   and row["event_id"] not in superseded]
                    for unit in latest["units"]:
                        review = next((row for row in reversed(comparisons)
                                       if row["unit_id"] == unit["unit_id"]), None)
                        if review is None:
                            block("SPECIALTY_UNIT_PENDING", unit_id=unit["unit_id"])
                        elif review["disposition"] in {"pending", "compared"}:
                            for derived in comparison_blockers(review):
                                block(derived['reason'], unit_id=derived['unit_id'])
                        elif not any(row["event_id"] == review["exemption_event_id"]
                                     and row["action_id"] == unit["unit_id"] for row in exemptions):
                            block("SPECIALTY_UNIT_EXEMPTION_STALE", unit_id=unit["unit_id"])
            gaps = [row for row in relevant if row["kind"] == "gap"
                    and row["intake_event_id"] == intake["event_id"]]
            follows = [row for row in relevant if row["kind"] == "followup"
                       and row["intake_event_id"] == intake["event_id"]]
            for gap in gaps:
                latest = next((row for row in reversed(follows)
                               if row["gap_event_id"] == gap["event_id"]), None)
                if latest is None or latest["outcome"] != "resolved":
                    block("SPECIALTY_GAP_OPEN", gap_id=gap["gap_id"],
                          state=(latest or {}).get("outcome", "open"))
            suspended = set()
            for change in (row for row in relevant if row["kind"] == "change" and row["substantive"]):
                review = next((row for row in reversed(relevant) if row["kind"] == "change_review"
                               and row["change_event_id"] == change["event_id"]), None)
                if review is None or review["outcome"] == "unknown":
                    block("SPECIALTY_CHANGE_REVIEW_PENDING", change_event_id=change["event_id"])
                    suspended.update(change["affected_event_ids"])
            for raw_gap in intake["verification_gaps"]:
                classified = next((row for row in reversed(relevant) if row["kind"] == "handoff_classification"
                                   and row["intake_event_id"] == intake["event_id"] and row["handoff_gap"] == raw_gap), None)
                if classified:
                    handoff_classifications.append({"event_id": classified["event_id"], "handoff_gap": raw_gap,
                        "fact_kinds": deepcopy(classified["fact_kinds"]),
                        "currently_usable": not ({classified["event_id"], *classified["material_event_ids"]}
                                                 & (superseded | suspended)),
                        "classification_reasoning": classified["classification_reasoning"]})
            current_results = [{"event_id": row["event_id"], "kind": row["kind"],
                                "fact_kind": row.get("fact_kind"), "unit_id": row.get("unit_id"),
                                "action_id": row.get("action_id"), "outcome": row.get("outcome", row.get("disposition")),
                                "currently_usable": row["event_id"] not in suspended}
                               for row in relevant if row.get("intake_event_id") == intake["event_id"]
                               and row["kind"] in {"fact", "comparison", "exemption"}
                               and row["event_id"] not in superseded]
            available = {row["event_id"] for row in relevant
                         if row.get("intake_event_id") == intake["event_id"]
                         and row["kind"] in {"fact", "comparison", "exemption", "gap", "followup", "change_review"}
                         and row["event_id"] not in superseded and row["event_id"] not in suspended}
            for handoff in (row for row in relevant if row["kind"] == "handoff"
                            and row["intake_event_id"] == intake["event_id"]):
                handoff_results.append({"event_id": handoff["event_id"],
                    "destination": handoff["destination"],
                    "currently_usable_event_ids": sorted(set(handoff["result_event_ids"]) & available),
                    "needs_recheck_event_ids": sorted(set(handoff["result_event_ids"]) - available)})
        # A prose "waiting" label cannot hide unprocessed work. Only exact,
        # already-reviewed unknowns linked to an active product feedback request
        # become external dependencies; all other obligations remain actionable.
        if intake:
            from product_feedback import pending
            feedback = {row.get("request_id") for row in pending(task)}
            for gap in gaps:
                if gap.get("action_kind") != "professional_review":
                    continue
                professional = professional_wait_entry(task, evidence, candidates, ledger, selected,
                    gap.get("unit_id"), supplement=supplement, gap_event_id=gap["event_id"])
                if professional:
                    for blocker in blockers:
                        if (blocker["reason"] == "SPECIALTY_DESIGN_SCOPE_UNKNOWN" and blocker.get("unit_id") == gap.get("unit_id")
                                or blocker["reason"] == "SPECIALTY_GAP_OPEN" and blocker.get("gap_id") == gap["gap_id"]):
                            blocker.update(state="awaiting_access", source_dependency=deepcopy(professional))
            for gap in gaps:
                follow = next((row for row in reversed(follows) if row["gap_event_id"] == gap["event_id"]), {})
                if (follow.get("outcome") != "waiting" or gap.get("action_kind") != "user_fact"
                        or gap.get("product_feedback_request_id") not in feedback):
                    continue
                dependency = {"state": "waiting", "product_feedback_request_id": gap["product_feedback_request_id"],
                              "dependency_gap_event_id": gap["event_id"]}
                for blocker in blockers:
                    if blocker["reason"] == "SPECIALTY_GAP_OPEN" and blocker.get("gap_id") == gap["gap_id"]:
                        blocker.update(dependency)
                    for binding in _unknown_bindings(task, gap, relevant):
                        field = {"SPECIALTY_FACT_REQUIRED": "fact_kind", "SPECIALTY_HANDOFF_GAP_OPEN": "handoff_gap",
                                 "SPECIALTY_COMPARISON_UNKNOWN": "unit_id"}[binding["reason"]]
                        if blocker["reason"] == binding["reason"] and blocker.get(field) == binding[field] and _handoff_facet_matches(blocker, binding):
                            blocker.update(dependency, basis_event_id=binding["basis_event_id"])
            from necessary_completion import _delivery_limit_valid
            for gap in gaps:
                follow = next((row for row in reversed(follows) if row["gap_event_id"] == gap["event_id"]), {})
                if follow.get("outcome") != "limited" or gap.get("action_kind") not in {"verify_known_right", "discovery"}:
                    continue
                if gap.get("source_plan_gap_proof"):
                    source = next((row for row in source_work or [] if
                        all(row.get(key) == gap.get(key) for key in SCOPE)
                        # Current selected/annotation validation already checks canonical candidate content.
                        # Planning bookkeeping, materiality projections and unrelated operation acceptance
                        # are not new facts. The fresh proof still rejects any restored status/owner route.
                        and _source_gap_proof_matches(task, row.get("delivery_limit"), gap["source_plan_gap_proof"])
                        and _delivery_limit_valid(row, task, evidence, plan, capabilities or {},
                            candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)), None)
                    if source is None:
                        continue
                    bindings = _unknown_bindings(task, gap, relevant)
                    for blocker in blockers:
                        matched = blocker["reason"] == "SPECIALTY_GAP_OPEN" and blocker.get("gap_id") == gap["gap_id"]
                        for binding in bindings:
                            field = {"SPECIALTY_FACT_REQUIRED": "fact_kind", "SPECIALTY_HANDOFF_GAP_OPEN": "handoff_gap",
                                "SPECIALTY_COMPARISON_UNKNOWN": "unit_id"}.get(binding["reason"])
                            matched |= bool(field and blocker["reason"] == binding["reason"] and blocker.get(field) == binding[field] and _handoff_facet_matches(blocker, binding))
                        if matched:
                            blocker.update(state="limited", source_dependency=deepcopy(source), dependency_gap_event_id=gap["event_id"])
                    dependency = gap.get("unavailable_comparison")
                    if (source["delivery_limit"].get("kind") == "api_record_fact_gap" and dependency
                            and any(binding.get("fact_kind") == "protection" for binding in bindings)):
                        # A complete inventory cannot be invented from missing
                        # claims/views. Explicitly reviewed partial material is
                        # a limitation; available readable inventories stay work.
                        can_inventory = any(row.get("status") == "sufficient_for_listed_purposes"
                            and "protection" in row.get("purposes", []) for row in materials)
                        for blocker in blockers:
                            if blocker["reason"] == "SPECIALTY_INVENTORY_PENDING" and not can_inventory:
                                blocker.update(state="limited", source_dependency=deepcopy(source),
                                    dependency_gap_event_id=gap["event_id"],
                                    comparison_limitation=deepcopy(dependency))
                    continue
                queries = [row for rows in (plan or {}).get("queries", {}).values() for row in rows
                           if row.get("query_id") == gap.get("source_query_id")]
                if len(queries) != 1 or sha256_json(queries[0]) != gap.get("source_plan_entry_sha256"):
                    continue
                source = next((row for row in source_work or []
                    if row.get("query_id") == gap["source_query_id"] and row.get("candidate_id") == scope[0]
                    and row.get("scenario_id") == scope[1] and row.get("jurisdiction") == scope[2]
                    and row.get("right_type") == scope[3] and row.get("state") in {"blocked", "awaiting_access"}
                    and _delivery_limit_valid(row, task, evidence, plan, capabilities or {},
                        candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir)), None)
                if source is None:
                    continue
                bindings = _unknown_bindings(task, gap, relevant)
                for blocker in blockers:
                    matched = blocker["reason"] == "SPECIALTY_GAP_OPEN" and blocker.get("gap_id") == gap["gap_id"]
                    for binding in bindings:
                        field = {"SPECIALTY_FACT_REQUIRED": "fact_kind", "SPECIALTY_HANDOFF_GAP_OPEN": "handoff_gap",
                                 "SPECIALTY_COMPARISON_UNKNOWN": "unit_id"}[binding["reason"]]
                        matched |= blocker["reason"] == binding["reason"] and blocker.get(field) == binding[field] and _handoff_facet_matches(blocker, binding)
                    if matched:
                        blocker.update(state="limited" if source["state"] == "blocked" else "awaiting_access",
                                       source_dependency=deepcopy(source), dependency_gap_event_id=gap["event_id"])
            for blocker in blockers:
                if blocker.get("state") == "waiting" and not blocker.get("product_feedback_request_id"):
                    blocker["state"] = "open"
            from completion_policy import evidence_delivery_enabled
            if evidence_delivery_enabled(task):
                for blocker in blockers:
                    if blocker["reason"] != "SPECIALTY_HANDOFF_GAP_OPEN" or blocker.get("fact_kind"):
                        continue
                    delegated = discovery_delegation_entry(task, evidence, candidates, ledger, plan,
                        selected, blocker["handoff_gap"], supplement=supplement)
                    if delegated:
                        blocker.update(state="residual_discovery_pending", source_dependency=delegated)
        for source in source_work or []:
            if (source.get("candidate_id") == scope[0] and source.get("scenario_id") == scope[1]
                    and source.get("jurisdiction") == scope[2] and source.get("right_type") == scope[3]
                    and source.get("kind") in {"source_lookup", "agent_read"}
                    and source.get("state") in {"ready", "awaiting_review", "awaiting_access", "submission_unknown"}):
                block("SPECIALTY_SOURCE_PENDING", query_id=source.get("query_id"),
                      state=source.get("state"))
            elif (source.get("reason") in {"SOURCE_RESULTS_PENDING_PROCESSING",
                                           "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID"}
                  and source.get("jurisdiction") == scope[2]
                  and source.get("right_type") == scope[3]
                  and (not source.get("candidate_id") or source.get("candidate_id") == scope[0])
                  and (not source.get("scenario_id") or source.get("scenario_id") == scope[1])):
                block("SPECIALTY_POTENTIAL_MATERIAL_PENDING", source_run_id=source.get("source_run_id"))
        waiting = bool(blockers) and all(
            (row.get("state") == "waiting" and row.get("product_feedback_request_id"))
            or (row.get("state") == "awaiting_access" and
                row.get("source_dependency", {}).get("delivery_limit", {}).get("kind") == "professional_wait")
            or (row["reason"] == "SPECIALTY_SOURCE_PENDING" and row.get("state") == "awaiting_access")
            for row in blockers)
        limited = bool(blockers) and all(row.get("state") == "limited" and
            (row.get("source_dependency") or row["reason"] == "SPECIALTY_GAP_OPEN") for row in blockers)
        waiting_discovery = (any(row.get("state") == "residual_discovery_pending" for row in blockers)
                             and all(row.get("state") in {"limited", "residual_discovery_pending"} for row in blockers))
        status = ("normal_complete" if not blockers else "waiting_discovery" if waiting_discovery else
                  "waiting" if waiting else "limited" if limited else "in_progress")
        scopes.append({**{key: selected[key] for key in SCOPE}, "status": status,
                       "intake_event_id": intake["event_id"] if intake else None,
                       "assessment_date": intake["assessment_date"] if intake else None,
                       "blockers": blockers, "results": current_results,
                       "handoffs": handoff_results, "handoff_classifications": handoff_classifications})
    overall = ("normal_complete" if scopes and all(row["status"] == "normal_complete" for row in scopes)
               else "waiting" if scopes and all(row["status"] == "waiting" for row in scopes)
               else "limited" if scopes and all(row["status"] == "limited" for row in scopes)
               else "waiting_discovery" if scopes and any(row["status"] == "waiting_discovery" for row in scopes)
                    and all(row["status"] in {"waiting_discovery", "limited"} for row in scopes)
               else "in_progress")
    return {"revision": REVISION, "status": overall, "scopes": scopes,
            "completion_meaning": "module_06_only; risk_review_and_publication_separate"}


def work_entries(view: dict) -> list[dict]:
    result = []
    for scope in view.get("scopes", []):
        for blocker in scope["blockers"]:
            state = ("awaiting_user" if blocker.get("state") == "waiting" else
                     "awaiting_access" if blocker.get("state") == "awaiting_access" else
                     "blocked" if blocker.get("state") in {"limited", "residual_discovery_pending"} else "awaiting_review")
            identity = {**{key: scope[key] for key in SCOPE}, "intake_event_id": scope.get("intake_event_id"),
                        "reason": blocker["reason"], **{key: blocker[key] for key in
                        ("fact_kind", "handoff_gap", "unit_id", "material_event_id", "evidence_ref",
                         "change_event_id", "source_run_id", "query_id", "gap_id", "fact_event_id") if key in blocker}}
            projected = {**{key: scope[key] for key in SCOPE},
                           "obligation_id": "SPECIALTY-OBLIGATION-" + sha256_json(identity)[:24], "kind": "user_evidence" if state == "awaiting_user" and blocker.get("product_feedback_request_id") else "agent_investigation",
                           "state": state, "reason": blocker["reason"],
                           **{key: value for key, value in blocker.items() if key not in {"reason", "state", "source_dependency"}}}
            if blocker.get("source_dependency"):
                projected.update({key: deepcopy(value) for key, value in blocker["source_dependency"].items()
                                  if key not in {"work_id", "kind", "state", "obligation_id"}})
                if blocker["source_dependency"].get("delivery_limit", {}).get("kind") == "professional_wait":
                    projected["kind"] = "professional_review"
                projected["specialty_reason"] = blocker["reason"]
            result.append(projected)
    return result

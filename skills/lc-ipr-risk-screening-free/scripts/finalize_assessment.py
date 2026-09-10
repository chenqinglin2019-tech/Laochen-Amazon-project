#!/usr/bin/env python3
"""Validate independent reviews and deterministically finalize task state."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import (
    CONFIDENCE_LEVELS, MODULE_IDS, RISK_LEVELS, add_history, assert_active_free_policy,
    assert_default_discovery_plan_contract,
    atomic_write_json, ensure_object, is_active_schema, load_json, load_skill_config,
    now_iso, optional_discovery_incomplete_queries,
    optional_discovery_provider_groups, parse_iso, plan_free_policy_matches_task,
    sha256_json, validate_checked_at,
)
from annotate_materiality import CANDIDATE_COLLECTIONS, materiality_annotation_complete
from runtime_timing import timed_cli


DISCOVERY_OPERATIONS_REQUIRED = {
    "epo_ops", "serpapi_google_patents", "serper_patents", "serper_web", "serper_images",
    "signa", "rapidapi_uspto_trademark", "uspto_tmsearch_browser", "euipo_trademark", "euipo_design",
}

LOW_RISK_GATE_OPERATIONS = {
    "wipo_patentscope_browser": "patent_recall",
    "espacenet_browser": "patent_recall",
    "epo_ops": "search",
    "uspto_patent_browser": "patent_recall",
}


def validate_review(
    review: dict[str, Any], known_evidence: set[str], input_digest: str,
    *, formal_risk_evidence: set[str] | dict[str, set[str]] | None = None,
) -> None:
    modules = review.get("modules")
    if not isinstance(modules, dict) or set(modules) != set(MODULE_IDS):
        raise ValueError("Review must contain exactly the seven required modules")
    formal_evidence_backed_finding_count = 0
    for module_id, module in modules.items():
        if module.get("risk") not in RISK_LEVELS or module.get("confidence") not in CONFIDENCE_LEVELS:
            raise ValueError(f"Invalid risk/confidence in {module_id}")
        if not str(module.get("reasoning", "")).strip() or not isinstance(module.get("findings"), list):
            raise ValueError(f"Missing reasoning/findings in {module_id}")
        module_has_formal_evidence = False
        for finding in module["findings"]:
            refs = finding.get("evidence_refs", []) if isinstance(finding, dict) else []
            required_fields = ("finding_id", "title", "recommended_action")
            if not isinstance(finding, dict) or any(not str(finding.get(field) or "").strip() for field in required_fields):
                raise ValueError(f"Finding in {module_id} is missing required fields")
            if (
                not isinstance(refs, list) or not refs
                or any(not isinstance(ref, str) or ref not in known_evidence for ref in refs)
            ):
                raise ValueError(f"Finding in {module_id} has missing or unknown evidence references")
            eligible_for_module = (
                formal_risk_evidence.get(module_id, set())
                if isinstance(formal_risk_evidence, dict)
                else formal_risk_evidence
            )
            if eligible_for_module is None or bool(set(refs) & eligible_for_module):
                module_has_formal_evidence = True
                formal_evidence_backed_finding_count += 1
        if (
            RISK_LEVELS.index(module["risk"]) >= RISK_LEVELS.index("中")
            and not module_has_formal_evidence
        ):
            raise ValueError(
                f"Risk-bearing module {module_id} requires at least one finding backed by "
                "an exact planned official candidate verification"
            )
    escalation = review.get("compound_escalation", {})
    if isinstance(escalation, dict) and escalation.get("enabled"):
        escalation_refs = escalation.get("evidence_refs")
        if (
            not str(escalation.get("justification") or "").strip()
            or not isinstance(escalation_refs, list)
            or not escalation_refs
            or any(
                not isinstance(ref, str) or ref not in known_evidence
                for ref in escalation_refs
            )
            or formal_evidence_backed_finding_count == 0
            or (
                formal_risk_evidence is not None
                and not bool(
                    set(escalation_refs or [])
                    & (
                        set().union(*formal_risk_evidence.values())
                        if isinstance(formal_risk_evidence, dict)
                        else formal_risk_evidence
                    )
                )
            )
        ):
            raise ValueError(
                "Enabled compound escalation requires justification, known evidence references, "
                "and at least one evidence-backed module finding"
            )
    if not isinstance(review.get("review_triggers", {}), dict):
        raise ValueError("review_triggers must be an object")
    context = review.get("review_context")
    if not isinstance(context, dict):
        raise ValueError("review_context is required")
    if not str(context.get("session_id") or "").strip() or context.get("evidence_digest") != input_digest:
        raise ValueError("review_context session_id/evidence_digest is invalid")
    if context.get("first_review_visible") is not False:
        raise ValueError("review_context must state first_review_visible=false")


def reconcile_reviews(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Choose conservatively per module while retaining both sets of findings."""
    result = {**first, "modules": {}, "recommended_actions": []}
    confidence_rank = {value: index for index, value in enumerate(CONFIDENCE_LEVELS)}
    for module_id in MODULE_IDS:
        left, right = first["modules"][module_id], second["modules"][module_id]
        left_risk, right_risk = RISK_LEVELS.index(left["risk"]), RISK_LEVELS.index(right["risk"])
        if right_risk > left_risk or (right_risk == left_risk and confidence_rank[right["confidence"]] < confidence_rank[left["confidence"]]):
            chosen, other = right, left
        else:
            chosen, other = left, right
        findings = []
        seen: set[str] = set()
        for finding in [*chosen.get("findings", []), *other.get("findings", [])]:
            key = str(finding.get("finding_id") or sha256_json(finding))
            if key not in seen:
                seen.add(key)
                findings.append(finding)
        result["modules"][module_id] = {**chosen, "findings": findings}
    for action in [*first.get("recommended_actions", []), *second.get("recommended_actions", [])]:
        if action not in result["recommended_actions"]:
            result["recommended_actions"].append(action)
    result["summary_reasons"] = list(dict.fromkeys([*first.get("summary_reasons", []), *second.get("summary_reasons", [])]))
    return result


def review_risk(review: dict[str, Any]) -> str:
    level = max(RISK_LEVELS.index(module["risk"]) for module in review["modules"].values())
    escalation = review.get("compound_escalation", {})
    if escalation.get("enabled") and str(escalation.get("justification", "")).strip():
        level = min(level + 1, len(RISK_LEVELS) - 1)
    return RISK_LEVELS[level]


def review_confidence(review: dict[str, Any], image_count: int) -> str:
    values = {value: index for index, value in enumerate(CONFIDENCE_LEVELS)}
    if image_count == 1:
        for module_id in ("figurative_trade_dress", "copyright_ip"):
            review["modules"][module_id]["confidence"] = "中" if values[review["modules"][module_id]["confidence"]] > values["中"] else review["modules"][module_id]["confidence"]
    highest = max(RISK_LEVELS.index(module["risk"]) for module in review["modules"].values())
    drivers = [module for module in review["modules"].values() if RISK_LEVELS.index(module["risk"]) == highest]
    return min((module["confidence"] for module in drivers), key=values.get)


def _verification_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        return [row for row in candidates if isinstance(row, dict)]
    return [payload]


def _identifier_tokens(item: dict[str, Any]) -> set[str]:
    return {
        re.sub(r"[^A-Za-z0-9]", "", str(item.get(field) or "")).upper()
        for field in (
            "application_number", "publication_number", "grant_number", "registration_number",
            "serial_number", "record_number", "page_application_number", "case_number",
            "docket_number",
        )
        if str(item.get(field) or "").strip()
    }


def _request_identifier_tokens(request_params: dict[str, Any]) -> set[str]:
    tokens = _identifier_tokens(request_params)
    for field in ("number", "identifier", "document", "q"):
        value = str(request_params.get(field) or "").strip()
        if value:
            tokens.add(re.sub(r"[^A-Za-z0-9]", "", value).upper())
    return {value for value in tokens if value}


def _run_candidate_binding_matches(
    item: dict[str, Any], run: dict[str, Any],
) -> bool:
    request_params = run.get("request_params")
    if not isinstance(request_params, dict):
        return False
    candidate_id = str(item.get("candidate_id") or "").strip()
    request_candidate_id = str(request_params.get("candidate_id") or "").strip()
    if candidate_id:
        return request_candidate_id == candidate_id
    return bool(_identifier_tokens(item) & _request_identifier_tokens(request_params))


def _same_candidate(candidate: dict[str, Any], official_row: dict[str, Any]) -> bool:
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    official_id = str(official_row.get("candidate_id") or "").strip()
    if candidate_id and official_id:
        return candidate_id == official_id
    return bool(_identifier_tokens(candidate) & _identifier_tokens(official_row))


def _identity_mismatch_scopes(
    item: dict[str, Any], evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return independently-clearable mismatch scopes for one candidate."""
    scopes: list[dict[str, Any]] = []
    bound_payloads: set[str] = set()
    runs = {
        str(run.get("run_id") or ""): run
        for run in (evidence or {}).get("source_runs", []) if isinstance(run, dict)
    }

    def parsed_time(official: dict[str, Any]) -> Any:
        try:
            value = parse_iso(str(official.get("checked_at") or ""))
            return value if value.tzinfo is not None else None
        except (TypeError, ValueError):
            return None

    for entry in (evidence or {}).get("collections", {}).get("official_verifications", []):
        if not isinstance(entry, dict):
            continue
        run = runs.get(str(entry.get("source_run_id") or ""), {})
        provider = str(entry.get("provider") or "")
        operation = str(entry.get("operation") or "")
        jurisdiction = str(entry.get("jurisdiction") or "").upper()
        right_type = str(entry.get("right_type") or "")
        run_requirements = {
            str(value) for value in run.get("requirement_ids", []) if str(value).strip()
        }
        entry_requirements = {
            str(value) for value in entry.get("requirement_ids", []) if str(value).strip()
        }
        requirements = sorted(run_requirements & entry_requirements)
        run_binding_matches = bool(
            provider and operation == "candidate_verification" and jurisdiction and right_type
            and str(run.get("query_id") or "").strip()
            and str(entry.get("query_id") or "").strip()
            == str(run.get("query_id") or "").strip()
            and run.get("provider") == provider
            and run.get("operation") == operation
            and str(run.get("jurisdiction") or "").upper() == jurisdiction
            and str(run.get("right_type") or "") == right_type
            and _run_candidate_binding_matches(item, run)
        )
        for row in _verification_rows(entry.get("payload")):
            official = row.get("official_verification")
            if (
                not _same_candidate(item, row)
                or not isinstance(official, dict)
                or official.get("identity_match") is not False
            ):
                continue
            bound_payloads.add(sha256_json(official))
            checked_at = parsed_time(official)
            if run_binding_matches and requirements:
                scopes.extend({
                    "scoped": True, "provider": provider, "operation": operation,
                    "jurisdiction": jurisdiction, "right_type": right_type,
                    "requirement_id": requirement_id, "checked_at": checked_at,
                } for requirement_id in requirements)
            else:
                scopes.append({"scoped": False, "checked_at": checked_at})

    top_level = item.get("official_verification")
    if (
        isinstance(top_level, dict)
        and top_level.get("identity_match") is False
        and sha256_json(top_level) not in bound_payloads
    ):
        scopes.append({"scoped": False, "checked_at": parsed_time(top_level)})
    unique: dict[str, dict[str, Any]] = {}
    for scope in scopes:
        unique[sha256_json({
            **scope,
            "checked_at": scope["checked_at"].isoformat()
            if scope.get("checked_at") is not None else "",
        })] = scope
    return list(unique.values())


def _identity_mismatch_resolved_after(
    item: dict[str, Any], evidence: dict[str, Any] | None,
    allowed_routes: list[dict[str, Any]], *, jurisdiction: str, right_type: str,
    requirement_ids: set[str], mismatch_at: Any,
    search_plan: dict[str, Any] | None = None,
) -> bool:
    if evidence is None or mismatch_at is None:
        return False
    return bool(allowed_routes) and any(
        _official_payload_complete(official, right_type)
        and parse_iso(str(official.get("checked_at") or "")) > mismatch_at
        for official in _verification_evidence_records(
            item, evidence, allowed_routes, jurisdiction=jurisdiction,
            right_type=right_type, requirement_ids=requirement_ids,
            search_plan=search_plan,
        )
    )


def _allowed_verification_hosts(provider: str, jurisdiction: str) -> set[str]:
    config = load_skill_config().get("providers", {})
    direct_key = {
        "uspto_tsdr": "tsdr",
        "uspto_patent_browser": "uspto_patent_browser",
        "jplatpat_browser": "jplatpat_browser",
        "epo_register_browser": "epo_register_browser",
    }.get(provider, provider)
    direct = config.get(direct_key, {}) if isinstance(config.get(direct_key), dict) else {}
    hosts = {str(value).casefold() for value in direct.get("browser_allowed_hosts", [])}
    if provider in {"euipo_trademark", "euipo_design"}:
        hosts |= {"euipo.europa.eu", "www.euipo.europa.eu", "api.euipo.europa.eu"}
    elif provider == "jpo_api":
        hosts |= {"ip-data.jpo.go.jp", "j-platpat.inpit.go.jp", "www.j-platpat.inpit.go.jp"}
    elif provider == "inpi_api":
        hosts |= {"api-gateway.inpi.fr", "data.inpi.fr"}
    elif provider == "public_web_browser":
        by_jurisdiction = direct.get("jurisdiction_allowed_hosts", {})
        if isinstance(by_jurisdiction, dict):
            hosts |= {
                str(value).casefold()
                for value in by_jurisdiction.get(jurisdiction.upper(), [])
            }
    elif provider == "official_registry_browser":
        registries = config.get("official_registry_browser", {}).get("registries", {})
        registry = registries.get(jurisdiction.upper(), {}) if isinstance(registries, dict) else {}
        hosts |= {str(value).casefold() for value in registry.get("browser_allowed_hosts", [])}
    return hosts


def _verification_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, list) or isinstance(right, list):
        left_values = left if isinstance(left, list) else [left]
        right_values = right if isinstance(right, list) else [right]
        return sorted(sha256_json(value) for value in left_values) == sorted(
            sha256_json(value) for value in right_values
        )
    return left == right


def _official_payload_complete(verification: dict[str, Any], right_type: str) -> bool:
    if (
        verification.get("status") != "verified"
        or verification.get("identity_match") is not True
        or any(
            not str(verification.get(field) or "").strip()
            for field in ("authority", "method", "checked_at")
        )
    ):
        return False
    owner = verification.get("owner") or verification.get("owners")
    legal_status = str(verification.get("legal_status") or "").strip()
    classes = verification.get("classes")
    media = verification.get("media")
    if right_type in {"patent", "utility_model"}:
        return bool(owner and legal_status)
    if right_type == "design":
        return bool(owner and legal_status and classes and media)
    if right_type == "trademark_figurative":
        return bool(owner and legal_status and classes and media)
    if right_type == "trademark_word":
        return bool(owner and legal_status and classes)
    if right_type in {"copyright", "enforcement"}:
        return bool(owner and legal_status)
    return bool(legal_status)


_VERIFICATION_PLAN_META_FIELDS = {
    "query_id", "operation", "jurisdiction", "right_type", "required",
    "required_for", "requirement_id", "requirement_ids", "wave", "derived_from",
    "execute_by_default", "execute_when", "fallback_provider",
}


def _exact_verification_plan_entry(
    search_plan: dict[str, Any], provider: str, query_id: str,
) -> dict[str, Any] | None:
    """Resolve a query id globally; provider-local lookup alone is not sufficient."""
    matches = [
        (str(bucket), row)
        for bucket, rows in search_plan.get("queries", {}).items()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, dict) and str(row.get("query_id") or "") == query_id
    ]
    if len(matches) != 1 or matches[0][0] != provider:
        return None
    return matches[0][1]


def _verification_plan_binding_matches(
    search_plan: dict[str, Any], item: dict[str, Any], run: dict[str, Any],
    entry: dict[str, Any], *, provider: str, query_id: str,
    jurisdiction: str, right_type: str, requirement_ids: set[str] | None,
) -> bool:
    """Reverse-check imported evidence against its one immutable execution plan row."""
    planned = _exact_verification_plan_entry(search_plan, provider, query_id)
    if not isinstance(planned, dict):
        return False
    if (
        str(planned.get("operation") or "") != "candidate_verification"
        or str(planned.get("jurisdiction") or "").upper() != jurisdiction.upper()
        or str(planned.get("right_type") or "") != right_type
    ):
        return False

    candidate_id = str(item.get("candidate_id") or "").strip()
    if not candidate_id or str(planned.get("candidate_id") or "").strip() != candidate_id:
        return False
    request = run.get("request_params")
    if not isinstance(request, dict) or str(request.get("candidate_id") or "").strip() != candidate_id:
        return False

    planned_requirements = {
        str(value) for value in planned.get("requirement_ids", []) if str(value).strip()
    }
    run_requirements = {
        str(value) for value in run.get("requirement_ids", []) if str(value).strip()
    }
    entry_requirements = {
        str(value) for value in entry.get("requirement_ids", []) if str(value).strip()
    }
    if (
        not planned_requirements
        or run_requirements != planned_requirements
        or entry_requirements != planned_requirements
        or (requirement_ids is not None and not requirement_ids <= planned_requirements)
    ):
        return False

    planned_digest = sha256_json(planned)
    if (
        str(run.get("plan_entry_sha256") or "") != planned_digest
        or str(entry.get("plan_entry_sha256") or "") != planned_digest
    ):
        return False

    planned_query = str(planned.get("q") or planned.get("query") or "").strip()
    if not planned_query or str(run.get("query") or "").strip() != planned_query:
        return False
    plan_meta_fields = _VERIFICATION_PLAN_META_FIELDS
    if search_plan.get("schema_version") == "2.4-free":
        plan_meta_fields = plan_meta_fields | {"search_dimension", "search_language", "execution_phase", "publication_scope", "pagination_parent_id"}
        if search_plan.get("decision_workflow_revision") == "scenario-triage-v1":
            from common import DECISION_PLAN_META_KEYS
            # Internal scenario authority is bound by the complete plan hash,
            # not transmitted as a provider request parameter.
            plan_meta_fields = plan_meta_fields | DECISION_PLAN_META_KEYS
    for key, expected in planned.items():
        if key in plan_meta_fields or key in {"q", "query", "candidate_id"}:
            continue
        if key not in request or not _verification_values_equal(request.get(key), expected):
            return False
    return True


def _verification_evidence_records(
    item: dict[str, Any], evidence: dict[str, Any], allowed_routes: list[dict[str, Any]],
    *, jurisdiction: str, right_type: str,
    requirement_ids: set[str] | None = None,
    search_plan: dict[str, Any] | None = None,
    include_entries: bool = False,
) -> list[Any]:
    refs = {
        str(value) for value in item.get("verification_refs", [])
        if str(value).strip()
    }
    if not refs or not allowed_routes:
        return []
    routes = {
        (str(route.get("provider") or ""), str(route.get("operation") or ""))
        for route in allowed_routes if isinstance(route, dict)
    }
    runs = {
        str(run.get("run_id") or ""): run
        for run in evidence.get("source_runs", []) if isinstance(run, dict)
    }
    matches: list[dict[str, Any]] = []
    for entry in evidence.get("collections", {}).get("official_verifications", []):
        if not isinstance(entry, dict) or str(entry.get("evidence_id") or "") not in refs:
            continue
        provider = str(entry.get("provider") or "")
        operation = str(entry.get("operation") or "")
        if (provider, operation) not in routes or operation != "candidate_verification":
            continue
        if str(entry.get("jurisdiction") or "").upper() != jurisdiction.upper():
            continue
        if str(entry.get("right_type") or "") != right_type:
            continue
        run = runs.get(str(entry.get("source_run_id") or ""), {})
        run_query_id = str(run.get("query_id") or "").strip()
        entry_query_id = str(entry.get("query_id") or "").strip()
        if (
            run.get("status") != "success"
            or not run_query_id
            or entry_query_id != run_query_id
            or run.get("provider") != provider
            or run.get("operation") != operation
            or str(run.get("jurisdiction") or "").upper() != jurisdiction.upper()
            or str(run.get("right_type") or "") != right_type
            or not _authoritative_run(evidence, run)
        ):
            continue
        if not _run_candidate_binding_matches(item, run):
            continue
        if requirement_ids:
            run_requirements = {
                str(value) for value in run.get("requirement_ids", []) if str(value).strip()
            }
            entry_requirements = {
                str(value) for value in entry.get("requirement_ids", []) if str(value).strip()
            }
            if not (requirement_ids & run_requirements & entry_requirements):
                continue
        if search_plan is not None and not _verification_plan_binding_matches(
            search_plan, item, run, entry, provider=provider,
            query_id=run_query_id, jurisdiction=jurisdiction,
            right_type=right_type, requirement_ids=requirement_ids,
        ):
            continue
        for row in _verification_rows(entry.get("payload")):
            if not _same_candidate(item, row):
                continue
            row_right_type = str(row.get("right_type") or "")
            if row_right_type != right_type:
                continue
            official = row.get("official_verification", {})
            if not isinstance(official, dict) or official.get("status") != "verified":
                continue
            url = str(official.get("url") or "").strip()
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or (parsed.hostname or "").casefold() not in _allowed_verification_hosts(provider, jurisdiction)
            ):
                continue
            try:
                validate_checked_at(str(official.get("checked_at") or ""))
            except (TypeError, ValueError):
                continue
            matches.append((entry, official) if include_entries else official)
    return matches


def _verification_evidence_complete(
    item: dict[str, Any], evidence: dict[str, Any], allowed_routes: list[dict[str, Any]],
    *, jurisdiction: str, right_type: str,
    requirement_ids: set[str] | None = None,
    search_plan: dict[str, Any] | None = None,
) -> bool:
    return any(
        _official_payload_complete(official, right_type)
        for official in _verification_evidence_records(
            item, evidence, allowed_routes, jurisdiction=jurisdiction,
            right_type=right_type, requirement_ids=requirement_ids,
            search_plan=search_plan,
        )
    )


def official_verification_complete(
    item: dict[str, Any], *, strict: bool, evidence: dict[str, Any] | None = None,
    allowed_routes: list[dict[str, Any]] | None = None, jurisdiction: str = "",
    right_type: str = "",
    requirement_ids: set[str] | None = None,
    search_plan: dict[str, Any] | None = None,
) -> bool:
    verification = item.get("official_verification", {})
    if not isinstance(verification, dict):
        return False
    if not strict:
        return verification.get("status") == "verified" and verification.get("identity_match") is not False
    right_type = right_type or str(item.get("right_type") or "patent")
    if evidence is None or not jurisdiction:
        return False
    return _verification_evidence_complete(
        item, evidence, allowed_routes or [], jurisdiction=jurisdiction,
        right_type=right_type, requirement_ids=requirement_ids,
        search_plan=search_plan,
    )


def material_unverified(
    candidates: dict[str, Any], strict: bool = False,
    *, evidence: dict[str, Any] | None = None, task: dict[str, Any] | None = None,
    search_plan: dict[str, Any] | None = None,
) -> list[str]:
    missing = []
    for kind in CANDIDATE_COLLECTIONS:
        for item in candidates.get(kind, []):
            candidate_label = str(
                item.get("candidate_id") or item.get("normalization_key")
                or item.get("publication_number") or item.get("mark_text") or "candidate"
            )
            if strict and not materiality_annotation_complete(item):
                missing.append(candidate_label)
                continue
            right_type = _candidate_right_type(kind, item)
            matching_requirements = _candidate_verification_requirements(
                task or {}, kind, item,
            )
            if strict:
                requirements_by_id = {
                    str(requirement.get("requirement_id") or ""): requirement
                    for requirement in matching_requirements
                }
                mismatch_scopes = _identity_mismatch_scopes(item, evidence)
                unresolved_mismatch = False
                for scope in mismatch_scopes:
                    requirement = requirements_by_id.get(str(scope.get("requirement_id") or ""))
                    if (
                        not scope.get("scoped")
                        or scope.get("checked_at") is None
                        or requirement is None
                        or str(requirement.get("jurisdiction") or "").upper()
                        != str(scope.get("jurisdiction") or "").upper()
                        or str(requirement.get("right_type") or "")
                        != str(scope.get("right_type") or "")
                        or not _identity_mismatch_resolved_after(
                            item, evidence,
                            [
                                route for route in requirement.get("routes", [])
                                if isinstance(route, dict)
                            ],
                            jurisdiction=str(scope.get("jurisdiction") or ""),
                            right_type=str(scope.get("right_type") or ""),
                            requirement_ids={str(scope.get("requirement_id") or "")},
                            mismatch_at=scope.get("checked_at"),
                            search_plan=search_plan,
                        )
                    ):
                        unresolved_mismatch = True
                        break
                if unresolved_mismatch:
                    missing.append(candidate_label)
                    continue
            if item.get("material"):
                if not matching_requirements or any(
                    not official_verification_complete(
                        item, strict=strict, evidence=evidence,
                        allowed_routes=[
                            route for route in requirement.get("routes", [])
                            if isinstance(route, dict)
                        ],
                        jurisdiction=str(requirement.get("jurisdiction") or ""),
                        right_type=right_type,
                        requirement_ids={str(requirement.get("requirement_id") or "")},
                        search_plan=search_plan,
                    )
                    for requirement in matching_requirements
                ):
                    missing.append(candidate_label)
    return list(dict.fromkeys(missing))


def _candidate_right_type(kind: str, item: dict[str, Any]) -> str:
    explicit = str(item.get("right_type") or "")
    if explicit:
        return explicit
    if kind == "copyright_assets":
        return "copyright"
    if kind == "enforcement":
        return "enforcement"
    if kind == "trademarks":
        return "trademark_figurative" if any(
            item.get(field) for field in ("figurative_id", "image_url", "image", "vienna_classes")
        ) else "trademark_word"
    if item.get("locarno") or item.get("views") or "design" in str(item.get("source") or ""):
        return "design"
    kind_code = str(item.get("kind_code") or "").upper()
    if kind_code.startswith("S"):
        return "design"
    return "utility_model" if kind_code.startswith("U") else "patent"


def _candidate_jurisdiction(item: dict[str, Any]) -> str:
    jurisdiction = str(item.get("jurisdiction") or item.get("office") or "").upper()
    if jurisdiction in {"EP", "EUIPO"}:
        return "EU"
    if jurisdiction == "USPTO":
        return "US"
    return jurisdiction


def _candidate_effect_jurisdictions(item: dict[str, Any], right_type: str) -> set[str]:
    jurisdiction = _candidate_jurisdiction(item)
    effects = {jurisdiction} if jurisdiction else set()
    if jurisdiction != "WO" or right_type != "patent":
        return effects
    sources = item.get("sources")
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict) or source.get("provider") != "epo_ops":
            continue
        source_jurisdiction = str(source.get("jurisdiction") or "").upper()
        if source_jurisdiction:
            effects.add("EU" if source_jurisdiction == "EP" else source_jurisdiction)
    family_values: list[Any] = []
    for field in ("family_members", "publication_numbers"):
        value = item.get(field)
        if isinstance(value, list):
            family_values.extend(value)
        elif value not in (None, ""):
            family_values.append(value)
    for value in family_values:
        normalized = str(value or "").upper()
        prefix_match = re.match(r"^([A-Z]{2})", normalized)
        prefix = prefix_match.group(1) if prefix_match else ""
        if prefix == "EP":
            effects.add("EU")
        elif prefix:
            effects.add(prefix)
    return effects


def _candidate_verification_requirements(
    task: dict[str, Any], kind: str, item: dict[str, Any],
) -> list[dict[str, Any]]:
    right_type = _candidate_right_type(kind, item)
    jurisdiction = _candidate_jurisdiction(item)
    effects = _candidate_effect_jurisdictions(item, right_type)
    targets = {
        str(value).upper() for value in task.get("target_jurisdictions", [])
        if str(value).strip()
    }
    if right_type == "patent" and (jurisdiction == "EU" or "EU" in effects):
        effects |= targets - {"US", "JP"}
    return [
        requirement
        for requirement in task.get("coverage_requirements", [])
        if isinstance(requirement, dict)
        and requirement.get("phase") == "candidate_verification"
        and str(requirement.get("right_type") or "") == right_type
        and str(requirement.get("jurisdiction") or "").upper() in effects
    ]


def _candidate_module_id(kind: str, item: dict[str, Any]) -> str:
    right_type = _candidate_right_type(kind, item)
    if right_type == "patent" and str(item.get("kind_code") or "").upper().startswith("A"):
        return "pending_application"
    return {
        "design": "appearance_patent",
        "patent": "utility_patent",
        "utility_model": "utility_patent",
        "trademark_word": "word_mark",
        "trademark_figurative": "figurative_trade_dress",
        "copyright": "copyright_ip",
        "enforcement": "enforcement",
    }.get(right_type, "")


def formal_rating_evidence_by_module(
    task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any],
    search_plan: dict[str, Any],
) -> dict[str, set[str]]:
    """Return only exact planned official verifications eligible for formal ratings."""
    result = {module_id: set() for module_id in MODULE_IDS}
    if (
        str(search_plan.get("schema_version") or "") != str(task.get("schema_version") or "")
        or str(search_plan.get("task_id") or "") != str(task.get("task_id") or "")
        or not plan_free_policy_matches_task(task, search_plan)
    ):
        return result
    for kind in CANDIDATE_COLLECTIONS:
        for item in candidates.get(kind, []):
            if not isinstance(item, dict) or item.get("material") is not True:
                continue
            right_type = _candidate_right_type(kind, item)
            module_id = _candidate_module_id(kind, item)
            if module_id not in result:
                continue
            for requirement in _candidate_verification_requirements(task, kind, item):
                requirement_id = str(requirement.get("requirement_id") or "").strip()
                if not requirement_id:
                    continue
                matches = _verification_evidence_records(
                    item, evidence,
                    [route for route in requirement.get("routes", []) if isinstance(route, dict)],
                    jurisdiction=str(requirement.get("jurisdiction") or ""),
                    right_type=right_type, requirement_ids={requirement_id},
                    search_plan=search_plan, include_entries=True,
                )
                for entry, official in matches:
                    evidence_id = str(entry.get("evidence_id") or "").strip()
                    if evidence_id and _official_payload_complete(official, right_type):
                        result[module_id].add(evidence_id)
    return result


def verification_plan_binding_errors(
    task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any],
    search_plan: dict[str, Any],
) -> list[str]:
    """Audit every active-schema official-verification row, not only material ones."""
    if not is_active_schema(task):
        return []
    errors: list[str] = []
    runs = {
        str(run.get("run_id") or ""): run
        for run in evidence.get("source_runs", []) if isinstance(run, dict)
    }
    all_candidates = [
        item
        for kind in CANDIDATE_COLLECTIONS
        for item in candidates.get(kind, [])
        if isinstance(item, dict)
    ]
    backed_verifications: dict[int, set[str]] = {}
    requirements = {
        str(requirement.get("requirement_id") or ""): requirement
        for requirement in task.get("coverage_requirements", [])
        if isinstance(requirement, dict) and requirement.get("requirement_id")
    }
    for entry in evidence.get("collections", {}).get("official_verifications", []):
        if not isinstance(entry, dict):
            errors.append("official verification entry is not an object")
            continue
        evidence_id = str(entry.get("evidence_id") or "").strip()
        run = runs.get(str(entry.get("source_run_id") or ""))
        provider = str(entry.get("provider") or "")
        operation = str(entry.get("operation") or "")
        jurisdiction = str(entry.get("jurisdiction") or "").upper()
        right_type = str(entry.get("right_type") or "")
        query_id = str(entry.get("query_id") or "").strip()
        label = evidence_id or query_id or "unnamed"
        if not isinstance(run, dict) or (
            operation != "candidate_verification"
            or not query_id
            or str(run.get("query_id") or "").strip() != query_id
            or str(run.get("provider") or "") != provider
            or str(run.get("operation") or "") != operation
            or str(run.get("jurisdiction") or "").upper() != jurisdiction
            or str(run.get("right_type") or "") != right_type
        ):
            errors.append(f"{label}: run/evidence scope is not an exact candidate verification")
            continue
        rows = _verification_rows(entry.get("payload"))
        if not rows:
            errors.append(f"{label}: official verification payload has no candidate row")
            continue
        entry_requirements = {
            str(value) for value in entry.get("requirement_ids", []) if str(value).strip()
        }
        route_bound = bool(entry_requirements) and all(
            isinstance(requirements.get(requirement_id), dict)
            and str(requirements[requirement_id].get("phase") or "") == "candidate_verification"
            and str(requirements[requirement_id].get("jurisdiction") or "").upper() == jurisdiction
            and str(requirements[requirement_id].get("right_type") or "") == right_type
            and any(
                isinstance(route, dict)
                and str(route.get("provider") or "") == provider
                and str(route.get("operation") or "") == operation
                for route in requirements[requirement_id].get("routes", [])
            )
            for requirement_id in entry_requirements
        )
        if not route_bound:
            errors.append(f"{label}: requirement/provider route binding is invalid")
            continue
        for row in rows:
            if provider == "uspto_patent_browser":
                from provider_utils import validate_text_evidence
                try:
                    validate_text_evidence(row, expected_stage="retained")
                except (ValueError, TypeError) as exc:
                    errors.append(f"{label}: {exc}")
                    continue
            matching = [
                item for item in all_candidates
                if evidence_id in {
                    str(value) for value in item.get("verification_refs", [])
                    if str(value).strip()
                }
                and _same_candidate(item, row)
            ]
            binding_matches = len(matching) == 1 and _verification_plan_binding_matches(
                search_plan, matching[0], run, entry,
                provider=provider, query_id=query_id, jurisdiction=jurisdiction,
                right_type=right_type, requirement_ids=entry_requirements,
            )
            if not binding_matches:
                errors.append(f"{label}: query/candidate/parameters/requirements/plan hash mismatch")
                continue
            official = row.get("official_verification")
            if isinstance(official, dict):
                backed_verifications.setdefault(id(matching[0]), set()).add(
                    sha256_json(official)
                )
    for item in all_candidates:
        official = item.get("official_verification")
        if not isinstance(official, dict):
            continue
        status = str(official.get("status") or "").strip()
        backed = backed_verifications.get(id(item), set())
        if not backed and status in {"", "not_checked"}:
            continue
        if sha256_json(official) not in backed:
            candidate_id = str(
                item.get("candidate_id") or item.get("normalization_key")
                or next(iter(_identifier_tokens(item)), "candidate")
            )
            errors.append(
                f"{candidate_id}: top-level official_verification does not match "
                "an exact-plan referenced verification payload"
            )
    return list(dict.fromkeys(errors))


def _material_candidates_for(
    candidates: dict[str, Any], jurisdiction: str, right_type: str,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for kind in CANDIDATE_COLLECTIONS:
        for item in candidates.get(kind, []):
            if not isinstance(item, dict) or not item.get("material"):
                continue
            item_jurisdiction = _candidate_jurisdiction(item)
            type_match = _candidate_right_type(kind, item) == right_type
            effects = _candidate_effect_jurisdictions(item, right_type)
            european_effect = (
                right_type == "patent"
                and "EU" in effects
                and jurisdiction not in {"US", "JP"}
            )
            if type_match and (
                not item_jurisdiction or jurisdiction in effects or european_effect
            ):
                matches.append(item)
    return matches


def _jurisdiction_matches(run_value: object, requirement_value: str) -> bool:
    values = {part.strip().upper() for part in str(run_value or "").split(",") if part.strip()}
    return requirement_value.upper() in values


def _authoritative_run(evidence: dict[str, Any], run: dict[str, Any]) -> bool:
    provider = str(run.get("provider") or "")
    if provider not in {
        "epo_ops", "euipo_trademark", "euipo_design", "jpo_api",
        "inpi_api", "prv_open_data",
    }:
        return True
    return (
        run.get("authoritative_for_final_rating") is True
        and str(run.get("source_environment") or "") == "production"
    )


def _route_complete(
    evidence: dict[str, Any], provider: str, operation: str, jurisdiction: str,
    *, requirement_id: str = "", right_type: str = "",
    search_plan: dict[str, Any] | None = None,
) -> bool:
    planned_query_ids = {
        str(entry.get("query_id") or "")
        for entry in (search_plan or {}).get("queries", {}).get(provider, [])
        if isinstance(entry, dict)
        and entry.get("required", True) is not False
        and str(entry.get("query_id") or "")
        and str(entry.get("operation") or "") == operation
        and _jurisdiction_matches(entry.get("jurisdiction"), jurisdiction)
        and (not right_type or str(entry.get("right_type") or "") == right_type)
        and requirement_id in {
            str(value) for value in entry.get("requirement_ids", []) if str(value).strip()
        }
    }
    if not planned_query_ids:
        return False
    completed_query_ids = {
        str(run.get("query_id") or "")
        for run in evidence.get("source_runs", [])
        if isinstance(run, dict)
        and run.get("provider") == provider
        and run.get("operation") == operation
        and run.get("status") in {"success", "no_result"}
        and str(run.get("query_id") or "") in planned_query_ids
        and _jurisdiction_matches(run.get("jurisdiction"), jurisdiction)
        and (not right_type or str(run.get("right_type") or "") == right_type)
        and _authoritative_run(evidence, run)
    }
    return planned_query_ids <= completed_query_ids


def coverage_requirement_gaps(
    task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any],
    search_plan: dict[str, Any],
) -> list[str]:
    """Return unsatisfied 2.3 requirement IDs; legacy uses its v1 gates."""
    if not is_active_schema(task):
        return []
    gaps: set[str] = set()
    requirements = {
        str(item.get("requirement_id") or ""): item
        for item in task.get("coverage_requirements", [])
        if isinstance(item, dict) and item.get("requirement_id")
    }
    for requirement_id, requirement in requirements.items():
        jurisdiction = str(requirement.get("jurisdiction") or "").upper()
        right_type = str(requirement.get("right_type") or "")
        if requirement.get("phase") == "candidate_verification":
            material = _material_candidates_for(candidates, jurisdiction, right_type)
            routes = [route for route in requirement.get("routes", []) if isinstance(route, dict)]
            if material and any(not official_verification_complete(
                item, strict=True, evidence=evidence, allowed_routes=routes,
                jurisdiction=jurisdiction, right_type=right_type,
                requirement_ids={requirement_id},
                search_plan=search_plan,
            ) for item in material):
                gaps.add(requirement_id)
            continue
        routes = [
            route for route in requirement.get("routes", [])
            if isinstance(route, dict) and route.get("required", True) is not False
        ]
        completed = [
            _route_complete(
                evidence, str(route.get("provider") or ""),
                str(route.get("operation") or ""), jurisdiction,
                requirement_id=requirement_id, right_type=right_type,
                search_plan=search_plan,
            )
            for route in routes
        ]
        policy = str(requirement.get("completion_policy") or "all")
        satisfied = bool(completed) and (any(completed) if policy == "any" else all(completed))
        if not satisfied:
            gaps.add(requirement_id)

    terminal = {"success", "no_result"}
    runs = evidence.get("source_runs", [])
    for provider, entries in search_plan.get("queries", {}).items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("required", True):
                continue
            query_id = str(entry.get("query_id") or "")
            if query_id and not any(
                run.get("provider") == provider
                and run.get("status") in terminal
                and str(run.get("query_id") or "") == query_id
                for run in runs
            ):
                for value in entry.get("requirement_ids", []):
                    requirement_id = str(value)
                    requirement = requirements.get(requirement_id)
                    if not requirement:
                        continue
                    if requirement.get("completion_policy") == "any":
                        jurisdiction = str(requirement.get("jurisdiction") or "")
                        if any(
                            _route_complete(
                                evidence, str(route.get("provider") or ""),
                                str(route.get("operation") or ""), jurisdiction,
                                requirement_id=requirement_id,
                                right_type=str(requirement.get("right_type") or ""),
                                search_plan=search_plan,
                            )
                            for route in requirement.get("routes", [])
                            if isinstance(route, dict)
                        ):
                            continue
                    gaps.add(requirement_id)
    for gap in task.get("coverage_gaps", []):
        if isinstance(gap, dict) and gap.get("error_code") == "UNSUPPORTED_JURISDICTION_ROUTE":
            gaps.add(f"UNSUPPORTED_JURISDICTION_ROUTE:{str(gap.get('jurisdiction') or '')}")
    return sorted(gaps)


def _requirements_by_purpose(task: dict[str, Any], purpose: str) -> set[str]:
    return {
        str(item.get("requirement_id") or "")
        for item in task.get("coverage_requirements", [])
        if isinstance(item, dict) and item.get("required_for") == purpose
    }


def tmsearch_expected_runs(search_plan: dict[str, Any]) -> set[str]:
    expected: set[str] = set()
    entries = search_plan.get("queries", {}).get("uspto_tmsearch_browser", [])
    if not isinstance(entries, list):
        return expected
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        query = str(entry.get("q") or "").strip()
        strategy = str(entry.get("strategy") or "").strip()
        if query and strategy:
            expected.add(str(entry.get("query_id") or f"{strategy}:{query}"))
    return expected


def low_risk_gate_expected_runs(search_plan: dict[str, Any], provider: str) -> set[str]:
    entries = search_plan.get("queries", {}).get(provider, [])
    if not isinstance(entries, list):
        return set()
    return {
        str(entry.get("query_id") or entry.get("q") or "").strip()
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("q") or "").strip()
    }


def low_risk_gate_gaps(task: dict[str, Any], evidence: dict[str, Any], search_plan: dict[str, Any]) -> list[str]:
    """Return US patent sources that make a negative clearance unsafe."""
    if is_active_schema(task):
        candidates: dict[str, Any] = {"patents": [], "trademarks": []}
        all_gaps = coverage_requirement_gaps(task, evidence, candidates, search_plan)
        expected = _requirements_by_purpose(task, "low_risk")
        return sorted(gap for gap in all_gaps if gap in expected or gap.startswith("UNSUPPORTED_JURISDICTION_ROUTE:"))
    gaps: list[str] = []
    runs = evidence.get("source_runs", [])
    for provider in task.get("low_risk_gate_sources", []):
        operation = LOW_RISK_GATE_OPERATIONS.get(provider)
        if not operation:
            continue
        expected = low_risk_gate_expected_runs(search_plan, provider)
        completed = {
            str(run.get("query_id") or run.get("query") or "").strip()
            for run in runs
            if run.get("provider") == provider
            and run.get("operation") == operation
            and run.get("status") in {"success", "no_result"}
        }
        if not expected or not expected.issubset(completed):
            gaps.append(provider)
    return sorted(set(gaps))


def cap_negative_clearance(assessment: dict[str, Any], gate_gaps: list[str]) -> None:
    """A source outage can never be represented as a US low-risk clearance."""
    if not gate_gaps or assessment["overall"].get("risk") not in {"极低", "低"}:
        return
    assessment["overall"]["risk"] = "中"
    assessment["overall"]["confidence"] = "低"
    assessment["overall"].setdefault("reasons", []).append(
        "低风险结论门禁未完成：" + ", ".join(gate_gaps)
    )


def required_query_gaps(task: dict[str, Any], evidence: dict[str, Any], search_plan: dict[str, Any]) -> list[str]:
    terminal = {"success", "no_result", "not_applicable"}
    runs = evidence.get("source_runs", [])
    gaps: list[str] = []
    if is_active_schema(task):
        for provider, entries in search_plan.get("queries", {}).items():
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict) or not entry.get("required", True) or entry.get("required_for") != "formal":
                    continue
                query_id = str(entry.get("query_id") or "")
                if query_id and not any(
                    run.get("provider") == provider
                    and run.get("status") in terminal
                    and str(run.get("query_id") or "") == query_id
                    for run in runs
                ):
                    gaps.append(f"{provider}:{query_id}")
        return sorted(set(gaps))
    for provider in task.get("required_sources", []):
        entries = [
            entry for entry in search_plan.get("queries", {}).get(provider, [])
            if isinstance(entry, dict) and entry.get("required", True)
        ]
        for entry in entries:
            query_id = str(entry.get("query_id") or "")
            good = any(
                run.get("provider") == provider
                and run.get("status") in terminal
                and str(run.get("query_id") or "") == query_id
                for run in runs
            )
            if query_id and not good:
                gaps.append(f"{provider}:{query_id}")
    return sorted(set(gaps))


def source_gaps(task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any], search_plan: dict[str, Any]) -> list[str]:
    if is_active_schema(task):
        all_gaps = coverage_requirement_gaps(task, evidence, candidates, search_plan)
        expected = _requirements_by_purpose(task, "formal")
        return sorted(
            gap for gap in all_gaps
            if gap in expected or gap.startswith("UNSUPPORTED_JURISDICTION_ROUTE:")
        )
    gaps: list[str] = []
    runs = evidence.get("source_runs", [])
    for provider in task.get("required_sources", []):
        provider_runs = [run for run in runs if run.get("provider") == provider]
        good = [run for run in provider_runs if run.get("status") in {"success", "no_result", "not_applicable"}]
        if provider in DISCOVERY_OPERATIONS_REQUIRED:
            good = [run for run in good if run.get("operation") != "preflight_probe"]
        if provider in {"euipo_trademark", "euipo_design"}:
            good = [
                run for run in good
                if (run.get("normalized") or {}).get("authoritative_for_final_rating", True) is True
            ]
        if provider == "amazon_browser":
            good = [run for run in good if run.get("operation") == "product_capture"]
        if provider == "uspto_tmsearch_browser":
            good = [run for run in good if run.get("operation") == "trademark_recall"]
            expected = tmsearch_expected_runs(search_plan)
            completed = {str(run.get("query_id") or run.get("query") or "") for run in good}
            if not expected or not expected.issubset(completed):
                good = []
        if provider == "uspto_tsdr":
            trademark_candidates = candidates.get("trademarks", [])
            if not trademark_candidates:
                good = [run for run in good if run.get("operation") in {
                    "api_preflight", "preflight_probe", "browser_capability", "candidate_verification",
                }]
            else:
                good = [run for run in good if run.get("operation") == "candidate_verification"]
        if provider in {"uspto_patent_browser", "official_registry_browser"}:
            material_exists = any(
                item.get("material")
                for kind in CANDIDATE_COLLECTIONS
                for item in candidates.get(kind, [])
                if isinstance(item, dict)
            )
            good = [run for run in good if run.get("operation") not in {"preflight_probe", "browser_capability"}] if material_exists else good
        if not good:
            gaps.append(provider)
    return sorted(set(gaps))


def optional_source_losses(
    task: dict[str, Any], evidence: dict[str, Any],
    search_plan: dict[str, Any] | None = None,
) -> list[str]:
    """Expose non-gating discovery losses; unselected legacy sources stay neutral."""
    if is_active_schema(task):
        groups = optional_discovery_provider_groups(task)
        selected_providers = set().union(*groups.values()) if groups else set()
        failures = {
            str(gap.get("provider") or "")
            for gap in task.get("coverage_gaps", [])
            if isinstance(gap, dict)
            and gap.get("provider") in selected_providers
            and gap.get("mandatory") is False
            and gap.get("status") in {"needs_user_action", "access_limited", "failed"}
        }
        for provider in selected_providers:
            runs = [
                run for run in evidence.get("source_runs", [])
                if isinstance(run, dict) and run.get("provider") == provider
            ]
            if runs and not any(
                run.get("status") in {"success", "no_result", "not_applicable"}
                for run in runs
            ):
                failures.add(provider)
        represented_groups = {
            logical_provider
            for logical_provider, providers in groups.items()
            if failures & providers
        }
        if search_plan is not None:
            failures.update(
                logical_provider
                for logical_provider in optional_discovery_incomplete_queries(
                    task, evidence, search_plan,
                )
                if logical_provider not in represented_groups
            )
        return sorted(value for value in failures if value)
    terminal = {"success", "no_result", "not_applicable"}
    losses: list[str] = []
    for provider in task.get("optional_sources", []):
        runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == provider and run.get("operation") != "preflight_probe"]
        if runs and not any(run.get("status") in terminal for run in runs):
            losses.append(provider)
    return sorted(set(losses))


PAID_FALLBACK_TRIGGER_CODES = {
    "FREE_QUOTA_EXHAUSTED", "FREE_QUOTA_STOP_THRESHOLD",
    "PAID_QUOTA_USAGE_DETECTED", "EPO_RECORDED_FREE_QUOTA_STOP",
    "EPO_REPORTED_FREE_QUOTA_NEAR_LIMIT", "EPO_TASK_FREE_QUOTA_NEAR_LIMIT",
    "OFFICIAL_VERIFICATION_INCOMPLETE", "OFFICIAL_VERIFICATION_NOT_FOUND",
    "OFFICIAL_REGISTRY_ACCESS_LIMITED", "OFFICIAL_REGISTRY_CAPTURE_FAILED",
    "RESPONSE_SCHEMA_CHANGED", "SOURCE_DATA_STALE",
}


def _unsupported_discovery_routes_completed(
    task: dict[str, Any], jurisdiction: str,
    search_plan: dict[str, Any], evidence: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Require every planned zero-cash discovery route before suggesting paid coverage.

    An unsupported national *formal* route is known when the task is created, but
    that alone does not mean the free discovery routes were exhausted.  This gate
    prevents a paid recommendation from appearing before TMview/DesignView (or a
    future free discovery route) was actually attempted for the country.
    """
    target = jurisdiction.upper()
    if target not in {
        str(value).upper() for value in task.get("target_jurisdictions", [])
        if str(value).strip()
    }:
        return False, []
    requirements = [
        item for item in task.get("coverage_requirements", [])
        if isinstance(item, dict)
        and str(item.get("jurisdiction") or "").upper() == target
        and str(item.get("phase") or "") in {"discovery", "official_recall"}
        and str(item.get("required_for") or "") == "low_risk"
    ]
    if not requirements:
        return False, []

    runs = [item for item in evidence.get("source_runs", []) if isinstance(item, dict)]
    observed_triggers: set[str] = set()
    for requirement in requirements:
        requirement_id = str(requirement.get("requirement_id") or "")
        right_type = str(requirement.get("right_type") or "")
        routes = [
            route for route in requirement.get("routes", [])
            if isinstance(route, dict)
            and route.get("required", True) is not False
            and route.get("operation") != "candidate_detail"
        ]
        if not routes:
            return False, []
        for route in routes:
            provider = str(route.get("provider") or "")
            operation = str(route.get("operation") or "")
            planned = [
                item for item in search_plan.get("queries", {}).get(provider, [])
                if isinstance(item, dict)
                and item.get("required", True) is not False
                and str(item.get("operation") or "") == operation
                and _jurisdiction_matches(item.get("jurisdiction"), target)
                and str(item.get("right_type") or "") == right_type
                and requirement_id in {
                    str(value) for value in item.get("requirement_ids", [])
                    if str(value).strip()
                }
            ]
            if not planned:
                return False, []
            for query in planned:
                query_id = str(query.get("query_id") or "")
                matching = [
                    run for run in runs
                    if run.get("provider") == provider
                    and run.get("operation") == operation
                    and str(run.get("query_id") or "") == query_id
                    and _jurisdiction_matches(run.get("jurisdiction"), target)
                    and str(run.get("right_type") or "") == right_type
                    and requirement_id in {
                        str(value) for value in run.get("requirement_ids", [])
                        if str(value).strip()
                    }
                ]
                completed = any(
                    run.get("status") in {"success", "no_result", "not_applicable"}
                    and _authoritative_run(evidence, run)
                    for run in matching
                )
                triggers = {
                    str(run.get("error_code") or "") for run in matching
                    if str(run.get("error_code") or "") in PAID_FALLBACK_TRIGGER_CODES
                }
                if not completed and not triggers:
                    return False, []
                observed_triggers.update(triggers)
    return True, ["UNSUPPORTED_JURISDICTION_ROUTE", *sorted(observed_triggers)]


def _free_routes_exhausted_for_requirement(
    task: dict[str, Any], requirement_id: str, requirement: dict[str, Any],
    search_plan: dict[str, Any], evidence: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Return true only after every planned free route was actually attempted.

    Missing credentials, approval/setup work, CAPTCHA and other user-action
    states are intentionally not paid-fallback triggers: they still have a
    zero-cash remediation path.
    """
    if requirement_id.startswith("UNSUPPORTED_JURISDICTION_ROUTE:"):
        jurisdiction = requirement_id.rsplit(":", 1)[-1]
        return _unsupported_discovery_routes_completed(
            task, jurisdiction, search_plan, evidence,
        )
    jurisdiction = str(requirement.get("jurisdiction") or "").upper()
    right_type = str(requirement.get("right_type") or "")
    phase = str(requirement.get("phase") or "")
    routes = [
        route for route in requirement.get("routes", [])
        if isinstance(route, dict)
        and route.get("required", True) is not False
        and route.get("operation") != "candidate_detail"
    ]
    linked: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for route in routes:
        provider = str(route.get("provider") or "")
        operation = str(route.get("operation") or "")
        rows = [
            item for item in search_plan.get("queries", {}).get(provider, [])
            if isinstance(item, dict)
            and str(item.get("operation") or "") == operation
            and _jurisdiction_matches(item.get("jurisdiction"), jurisdiction)
            and str(item.get("right_type") or "") == right_type
            and requirement_id in {
                str(value) for value in item.get("requirement_ids", [])
                if str(value).strip()
            }
            # Candidate-verification actions are deliberately marked
            # required=false so a zero-candidate task does not invent work.
            and (phase == "candidate_verification" or item.get("required", True) is not False)
        ]
        if not rows:
            return False, []
        linked[(provider, operation)] = rows

    runs = [run for run in evidence.get("source_runs", []) if isinstance(run, dict)]
    trigger_codes: list[str] = []
    for (provider, operation), rows in linked.items():
        for item in rows:
            query_id = str(item.get("query_id") or "")
            matching = [
                run for run in runs
                if run.get("provider") == provider
                and run.get("operation") == operation
                and str(run.get("query_id") or "") == query_id
                and _jurisdiction_matches(run.get("jurisdiction"), jurisdiction)
                and str(run.get("right_type") or "") == right_type
                and requirement_id in {
                    str(value) for value in run.get("requirement_ids", [])
                    if str(value).strip()
                }
            ]
            if not matching:
                return False, []
            row_triggers = sorted({
                str(run.get("error_code") or "") for run in matching
                if str(run.get("error_code") or "") in PAID_FALLBACK_TRIGGER_CODES
            })
            row_completed = any(
                run.get("status") in {"success", "no_result", "not_applicable"}
                for run in matching
            )
            # An authentication/setup/CAPTCHA/user-action failure still has a
            # zero-cash remediation path.  It cannot be hidden by a genuine
            # exhaustion signal from a different route in the same requirement.
            if not row_completed and not row_triggers:
                return False, []
            trigger_codes.extend(row_triggers)
    return bool(trigger_codes), sorted(set(trigger_codes))


def paid_recommendations(
    task: dict[str, Any], missing_requirements: list[str], search_plan: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Describe paid fallbacks only after the free routes are demonstrably spent."""
    if not is_active_schema(task) or not missing_requirements:
        return []
    requirements = {
        str(item.get("requirement_id") or ""): item
        for item in task.get("coverage_requirements", [])
        if isinstance(item, dict)
    }
    recommendations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    module_by_right_type = {
        "patent": "utility_patent",
        "utility_model": "utility_patent",
        "design": "appearance_patent",
        "trademark_word": "word_mark",
        "trademark_figurative": "figurative_trade_dress",
        "copyright": "copyright_ip",
        "enforcement": "enforcement",
    }
    for gap in missing_requirements:
        requirement = requirements.get(gap, {})
        exhausted, trigger_codes = _free_routes_exhausted_for_requirement(
            task, gap, requirement, search_plan, evidence or {},
        )
        if not exhausted:
            continue
        jurisdiction = str(requirement.get("jurisdiction") or gap.rsplit(":", 1)[-1] or "GLOBAL")
        right_type = str(requirement.get("right_type") or "coverage")
        provider = "professional_ip_database"
        missing_fields = ["multi-source candidate recall", "official record linkage"]
        if jurisdiction == "DE" and right_type in {
            "patent", "utility_model", "design", "trademark_word", "trademark_figurative",
        }:
            provider = "DPMAconnectPlus"
            missing_fields = ["machine-readable German register recall"]
        elif jurisdiction == "US" and right_type == "enforcement":
            provider = "PACER"
            missing_fields = ["complete federal docket and filing documents"]
        elif right_type == "copyright":
            provider = "paid_image_rights_search"
            missing_fields = ["image provenance", "registered or licensed copyright ownership"]
        elif right_type in {"trademark_word", "trademark_figurative"}:
            provider = "Signa_or_professional_ip_database"
            missing_fields = ["phonetic, semantic, or figurative multi-jurisdiction recall"]
        elif right_type == "design":
            provider = "professional_design_database"
            missing_fields = ["cross-jurisdiction design-image recall", "official record linkage"]
        key = (provider, jurisdiction, right_type)
        if key in seen:
            continue
        seen.add(key)
        linked_requirement_ids = {gap}
        if gap.startswith("UNSUPPORTED_JURISDICTION_ROUTE:"):
            linked_requirement_ids = {
                str(item.get("requirement_id") or "")
                for item in task.get("coverage_requirements", [])
                if isinstance(item, dict)
                and str(item.get("jurisdiction") or "").upper() == jurisdiction.upper()
                and str(item.get("phase") or "") in {"discovery", "official_recall"}
            }
        estimated_calls = sum(
            1
            for entries in search_plan.get("queries", {}).values()
            if isinstance(entries, list)
            for item in entries
            if isinstance(item, dict)
            and linked_requirement_ids.intersection({
                str(value) for value in item.get("requirement_ids", [])
                if str(value).strip()
            })
        ) or 1
        recommendations.append({
            "recommendation_id": f"PAID-{len(recommendations) + 1:03d}",
            "provider": provider,
            "jurisdiction": jurisdiction,
            "module": module_by_right_type.get(right_type, right_type),
            "missing_fields": missing_fields,
            "estimated_calls": estimated_calls,
            "free_exhaustion_evidence": trigger_codes,
            "cost_cap": {
                "amount": 0,
                "currency": "USD",
                "status": "not_authorized",
                "basis": "current executable cap; obtain a current quote and explicit numeric approval before changing it",
            },
            "authorized_spend_cap": {
                "amount": 0,
                "currency": "USD",
                "basis": "no paid execution has been authorized",
            },
            "approval_required": True,
            "automatic_execution": False,
        })
    return recommendations


@timed_cli("assessment_finalize")
def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize one IPR assessment.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--first-review", type=Path, required=True)
    parser.add_argument("--second-review", type=Path)
    parser.add_argument("--assessment-policy", choices=("evidence-estimate-v1",))
    parser.add_argument("--assessment-revision", choices=("partial-evidence-v1",))
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--supplement", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--mode", choices=("auto", "final", "evidence", "stage"))
    parser.add_argument("--stop-reason")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if task.get("assessment_policy") not in (None, "evidence-estimate-v1"):
        raise SystemExit("Unsupported existing assessment_policy: " + str(task["assessment_policy"]))
    policy = args.assessment_policy or task.get("assessment_policy")
    if policy:
        if policy != "evidence-estimate-v1":
            raise SystemExit("Unsupported assessment_policy: " + str(policy))
        if not task.get("assessment_policy") and (
            args.output_dir is None or args.output_dir.resolve() == task_dir
        ):
            parser.error("Historical reassessment requires a separate --output-dir; original inputs are read-only")
        task = {**task, "assessment_policy": policy}
        from assessment_estimate import finalize as finalize_estimate
        result = finalize_estimate(
            task_dir, task, args.first_review, args.second_review,
            adjudication_path=args.adjudication, supplement_path=args.supplement,
            evidence_root=args.evidence_root, output_dir=args.output_dir,
            publication_mode=args.mode, stop_reason=args.stop_reason,
            assessment_revision=args.assessment_revision,
        )
        print(result["status"])
        return
    if any((args.adjudication, args.supplement, args.evidence_root, args.output_dir, args.mode, args.stop_reason, args.assessment_revision)):
        parser.error("Supplement/adjudication/output options require evidence-estimate-v1")
    if task.get("schema_version") == "2.4-free":
        from assessment_v24 import finalize
        print(finalize(task_dir, task, args.first_review, args.second_review)["status"])
        return
    if not is_active_schema(task):
        raise SystemExit("LEGACY_TASK_READ_ONLY: 2.1/2.2 assessments cannot be regenerated")
    assert_active_free_policy(task)
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    candidates_path = task_dir / "normalized-candidates.json"
    candidates = ensure_object(load_json(candidates_path), "normalized-candidates.json") if candidates_path.exists() else {
        collection: [] for collection in CANDIDATE_COLLECTIONS
    }
    review_input_digest = sha256_json({"evidence": evidence, "candidates": candidates})
    known_evidence = {entry.get("evidence_id") for values in evidence.get("collections", {}).values() for entry in values if isinstance(entry, dict) and entry.get("evidence_id")}
    search_plan_path = task_dir / "search-plan.json"
    search_plan = ensure_object(load_json(search_plan_path), "search-plan.json") if search_plan_path.exists() else {}
    if (
        str(search_plan.get("schema_version") or "") != str(task.get("schema_version") or "")
        or str(search_plan.get("task_id") or "") != str(task.get("task_id") or "")
        or not plan_free_policy_matches_task(task, search_plan)
    ):
        raise ValueError("SEARCH_PLAN_IDENTITY_MISMATCH: plan does not belong to this task/free policy")
    assert_default_discovery_plan_contract(task, search_plan)
    verification_binding_errors = verification_plan_binding_errors(
        task, evidence, candidates, search_plan,
    )
    if verification_binding_errors:
        raise ValueError(
            "OFFICIAL_VERIFICATION_PLAN_BINDING_INVALID: "
            + "; ".join(verification_binding_errors)
        )
    formal_risk_evidence = formal_rating_evidence_by_module(
        task, evidence, candidates, search_plan,
    )
    first = ensure_object(load_json(args.first_review), "first review")
    validate_review(
        first, known_evidence, review_input_digest,
        formal_risk_evidence=formal_risk_evidence,
    )
    add_history(task, "assessing", "First independent review validated")
    missing_sources = source_gaps(task, evidence, candidates, search_plan)
    missing_queries = required_query_gaps(task, evidence, search_plan)
    gate_gaps = low_risk_gate_gaps(task, evidence, search_plan)
    optional_losses = optional_source_losses(task, evidence, search_plan)
    unverified = material_unverified(
        candidates, strict=is_active_schema(task), evidence=evidence, task=task,
        search_plan=search_plan,
    )
    all_coverage_gaps = (
        coverage_requirement_gaps(task, evidence, candidates, search_plan)
        if is_active_schema(task) else sorted(set([*missing_sources, *gate_gaps]))
    )
    first_risk = review_risk(first)
    paid = paid_recommendations(task, all_coverage_gaps, search_plan, evidence)
    assessment: dict[str, Any] = {
        "schema_version": task["schema_version"], "task_id": task["task_id"], "generated_at": now_iso(),
        "status": "", "overall": {
            "risk": "", "confidence": "", "discovery_signal": first_risk,
            "provisional": True, "reasons": [],
        },
        "modules": first["modules"], "review": {"required": False, "human_review_required": False, "first_reviewer": first.get("reviewer", "independent-review-1")},
        "coverage": {
            "missing_coverage_requirements": all_coverage_gaps,
            "missing_formal_requirements": missing_sources if is_active_schema(task) else [],
            "missing_low_risk_requirements": gate_gaps if is_active_schema(task) else [],
            "missing_required_sources": [] if is_active_schema(task) else missing_sources,
            "missing_required_queries": missing_queries,
            "missing_low_risk_gate_sources": [] if is_active_schema(task) else gate_gaps,
            "optional_source_losses": optional_losses,
            "unverified_material_candidates": unverified,
        },
        "recommended_actions": first.get("recommended_actions", []),
        "paid_recommendations": paid,
    }
    if missing_sources or missing_queries or unverified:
        assessment["status"] = "incomplete"
        assessment["overall"]["reasons"] = (
            (["Required source incomplete: " + ", ".join(missing_sources)] if missing_sources else [])
            + (["Required queries incomplete: " + ", ".join(missing_queries)] if missing_queries else [])
            + (["Candidate materiality review or official verification incomplete: " + ", ".join(unverified)] if unverified else [])
        )
        add_history(task, "incomplete", "; ".join(assessment["overall"]["reasons"]))
    else:
        triggers = any(bool(value) for value in first.get("review_triggers", {}).values())
        second_required = first_risk in {"高", "极高"} or triggers
        assessment["review"]["required"] = second_required
        if second_required and not args.second_review:
            assessment["status"] = "needs_review"
            assessment["overall"].update({"risk": first_risk, "confidence": review_confidence(first, len(task.get("images", []))), "provisional": True, "reasons": first.get("summary_reasons", [])})
            add_history(task, "needs_review", "Second independent review required")
        else:
            chosen = first
            if args.second_review:
                second = ensure_object(load_json(args.second_review), "second review")
                validate_review(
                    second, known_evidence, review_input_digest,
                    formal_risk_evidence=formal_risk_evidence,
                )
                if second.get("reviewer") == first.get("reviewer"):
                    raise ValueError("Second review must use a different reviewer identity")
                if second.get("review_context", {}).get("session_id") == first.get("review_context", {}).get("session_id"):
                    raise ValueError("Second review must use a different review session")
                second_risk = review_risk(second)
                assessment["review"]["second_reviewer"] = second.get("reviewer", "independent-review-2")
                if abs(RISK_LEVELS.index(first_risk) - RISK_LEVELS.index(second_risk)) >= 2:
                    assessment["status"] = "needs_review"
                    assessment["review"]["human_review_required"] = True
                    assessment["overall"].update({"risk": max((first_risk, second_risk), key=RISK_LEVELS.index), "confidence": "低", "provisional": True, "reasons": ["Independent reviews differ by at least two risk levels"]})
                    add_history(task, "needs_review", "Independent reviews diverged by at least two levels")
                else:
                    chosen = reconcile_reviews(first, second)
            if not assessment["status"]:
                assessment["modules"] = chosen["modules"]
                chosen_risk = review_risk(chosen)
                assessment["overall"]["discovery_signal"] = chosen_risk
                assessment["overall"].update({"risk": chosen_risk, "confidence": review_confidence(chosen, len(task.get("images", []))), "provisional": False, "reasons": chosen.get("summary_reasons", [])})
                if is_active_schema(task) and gate_gaps and chosen_risk in {"极低", "低"}:
                    assessment["status"] = "incomplete"
                    assessment["overall"]["risk"] = ""
                    assessment["overall"]["confidence"] = "低"
                    assessment["overall"]["provisional"] = True
                    assessment["overall"].setdefault("reasons", []).append(
                        "低风险结论门禁未完成：" + ", ".join(gate_gaps)
                    )
                    add_history(task, "incomplete", assessment["overall"]["reasons"][-1])
                else:
                    assessment["status"] = "completed"
                    if is_active_schema(task) and gate_gaps:
                        assessment["overall"].setdefault("reasons", []).append(
                            "以下低风险召回门禁未完成，但已核验的中高风险发现仍可正式报告："
                            + ", ".join(gate_gaps)
                        )
                    else:
                        cap_negative_clearance(assessment, gate_gaps)
                if optional_losses:
                    if CONFIDENCE_LEVELS.index(assessment["overall"]["confidence"]) > CONFIDENCE_LEVELS.index("中"):
                        assessment["overall"]["confidence"] = "中"
                    assessment["overall"].setdefault("reasons", []).append(
                        "已选可选发现来源不可用：" + ", ".join(optional_losses)
                    )
                assessment["recommended_actions"] = chosen.get("recommended_actions", [])
                if assessment["status"] == "completed":
                    add_history(task, "completed", "Assessment finalized")
    task["paid_recommendations"] = paid
    task.setdefault("outputs", {})["assessment_json"] = str(task_dir / "assessment.json")
    atomic_write_json(task_dir / "assessment.json", assessment)
    atomic_write_json(task_dir / "task.json", task)
    print(assessment["status"])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Evidence-gated, jurisdiction-scoped assessment; legacy 2.3 stays unchanged.

Risk is a review conclusion, not a score computed from missing sources.  This
module verifies its prerequisites and publication scope without asserting that
an office record, successful search, or model confidence proves infringement.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree

from common import (add_history, assert_active_free_policy,
                    assert_default_discovery_plan_contract, atomic_write_json,
                    ensure_object, load_json, now_iso, plan_free_policy_matches_task,
                    sha256_json, sha256_file)
from annotate_materiality import (candidate_index, iter_candidates,
                                 load_materiality_ledger, materiality_annotation_complete,
                                 materiality_ledger_errors)

SCHEMA = "2.4-free"
RISKS = ("无法判断", "低", "中", "高")
CONFIDENCES = ("低", "中", "高")
UNREGISTERED = {"copyright", "trade_dress", "unregistered_design"}
REGISTERED = {"patent", "utility_model", "design", "trademark_word", "trademark_figurative"}
RESULTS = {"supports_risk", "excludes_risk", "unknown", "not_applicable"}
CRITERIA = {
    "patent": {"current_claims", "element_mapping", "territorial_effect", "current_status", "authorization"},
    "utility_model": {"current_claims", "element_mapping", "territorial_effect", "current_status", "authorization"},
    "design": {"protected_views", "product_views", "protected_features", "overall_impression", "exclusions", "territorial_effect", "current_status", "authorization"},
    "trademark_word": {"signs", "goods_services", "use_context", "overall_impression", "territorial_effect", "current_status", "authorization"},
    "trademark_figurative": {"signs", "goods_services", "use_context", "overall_impression", "territorial_effect", "current_status", "authorization"},
    "copyright": {"source_provenance", "protectable_expression", "product_expression", "access_or_copying", "territorial_effect", "authorization"},
    "trade_dress": {"source_provenance", "market_recognition", "non_functionality", "overall_impression", "use_context", "territorial_effect", "authorization"},
    "unregistered_design": {"first_disclosure", "protected_features", "product_views", "overall_impression", "copying", "territorial_effect", "authorization"},
}
CONFIDENCE_FACTS = {"identity", "scope", "status", "product", "comparison"}
LANGUAGES = {"US": "en", "GB": "en", "FR": "fr", "DE": "de", "IT": "it", "ES": "es", "JP": "ja", "EU": "en"}
NON_PRODUCTION = {"sandbox", "fixture", "test", "test_fixture", "mock", "simulation"}


def evidence_index(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for values in evidence.get("collections", {}).values():
        if not isinstance(values, list):
            continue
        for entry in values:
            if isinstance(entry, dict) and entry.get("evidence_id"):
                if entry["evidence_id"] in result and result[entry["evidence_id"]] != entry:
                    raise ValueError("DUPLICATE_EVIDENCE_ID: " + str(entry["evidence_id"]))
                result[entry["evidence_id"]] = entry
    return result


def review_digest(evidence: dict[str, Any], candidates: dict[str, Any], ledger: dict[str, Any], plan: dict[str, Any], task: dict[str, Any]) -> str:
    from workflow_v24 import scenario_workflow_enabled
    fields = ["product", "images", "target_jurisdictions", "coverage_requirements"]
    if scenario_workflow_enabled(task):
        fields += ["decision_workflow_revision", "assessment_scenarios", "primary_scenario_id"]
    if "workflow_correction_revision" in task:
        from decision_workflow import correction_enabled
        correction_enabled(task)
        fields.append("workflow_correction_revision")
    return sha256_json({"evidence": evidence, "candidates": candidates,
                        "materiality_ledger": ledger, "search_plan": plan,
                        "product_context": {key: task.get(key) for key in fields}})


def scope_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("jurisdiction") or "").upper(),
            str(row.get("right_type") or ""), str(row.get("candidate_id") or ""))


def _refs(value: Any, known: set[str], *, required: bool = True) -> bool:
    return isinstance(value, list) and (bool(value) or not required) and all(isinstance(ref, str) and ref in known for ref in value)


def _plan_rows(plan: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(str(provider), row) for provider, rows in plan.get("queries", {}).items()
            if isinstance(rows, list) for row in rows if isinstance(row, dict)]


def _entry_matches_run(entry: dict[str, Any], run: dict[str, Any]) -> bool:
    return (entry.get("source_run_id") == run.get("run_id")
            and bool(run.get("plan_entry_sha256"))
            and all(entry.get(key) == run.get(key) for key in ("provider", "query_id", "operation", "jurisdiction", "right_type", "plan_entry_sha256"))
            and set(entry.get("requirement_ids", [])) == set(run.get("requirement_ids", [])))


def bound_runs(evidence: dict[str, Any], plan: dict[str, Any], provider: str, query: dict[str, Any]) -> list[dict[str, Any]]:
    """Recall needs the same immutable plan/run/evidence identity as verification."""
    query_id = str(query.get("query_id") or "")
    if not query_id or sum(row.get("query_id") == query_id for _, row in _plan_rows(plan)) != 1:
        return []
    digest = sha256_json(query)
    entries = evidence_index(evidence).values()
    valid = []
    for run in evidence.get("source_runs", []):
        if not isinstance(run, dict) or run.get("provider") != provider or run.get("query_id") != query_id:
            continue
        if run.get("plan_entry_sha256") != digest:
            continue
        if any(str(run.get(key) or "") != str(query.get(key) or "") for key in ("operation", "jurisdiction", "right_type")):
            continue
        if set(run.get("requirement_ids", [])) != set(query.get("requirement_ids", [])):
            continue
        if not any(_entry_matches_run(entry, run) for entry in entries):
            continue
        valid.append(run)
    return valid


def _query_candidates(candidates: dict[str, Any], evidence: dict[str, Any], query_id: str) -> list[dict[str, Any]]:
    index = evidence_index(evidence)
    found = []
    for _, item in iter_candidates(candidates):
        sources = item.get("sources", [])
        refs = [*item.get("evidence_refs", []), *item.get("source_evidence_ids", [])]
        if item.get("query_id") == query_id or any(isinstance(source, dict) and source.get("query_id") == query_id for source in sources) or any(index.get(ref, {}).get("query_id") == query_id for ref in refs):
            found.append(item)
    return found


def _source_records(evidence: dict[str, Any], run_id: str) -> list[dict[str, Any]] | None:
    records = []
    envelopes = 0
    run = next((run for run in evidence.get("source_runs", []) if run.get("run_id") == run_id), {})
    for entry in evidence_index(evidence).values():
        if not _entry_matches_run(entry, run):
            continue
        payload = entry.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
            values = payload["candidates"]
        elif isinstance(payload, list):
            values = payload
        else:
            continue
        if any(not isinstance(value, dict) for value in values):
            return None
        envelopes += 1
        records.extend(values)
    return records if envelopes else None


def _retained_artifacts_complete(payload: dict[str, Any]) -> bool:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False
    try:
        return all(isinstance(artifact, dict) and bool(artifact.get("role"))
                   and Path(str(artifact.get("path") or "")).is_file()
                   and sha256_file(Path(artifact["path"])) == artifact.get("sha256")
                   and Path(artifact["path"]).stat().st_size == artifact.get("bytes") for artifact in artifacts)
    except (OSError, KeyError, TypeError):
        return False


def _records_accounted_for(records, candidates, review_check=None) -> bool:
    """Match original identities, not copied hit counts or query membership.

    A publication/registration is the identity when supplied by the source;
    sharing an application or family cannot stand in for that document.
    """
    identifiers = ("publication_number", "registration_number", "application_number", "serial_number", "record_number", "candidate_id")
    def normalized(value):
        return re.sub(r"\W", "", str(value or "")).upper()
    for record in records:
        field = next((key for key in identifiers if record.get(key)), None)
        if field is None or not any((review_check or materiality_annotation_complete)(item)
                and normalized(item.get(field)) == normalized(record[field])
                and (not record.get("right_type") or item.get("right_type") == record["right_type"])
                for item in candidates):
            return False
    return True


def _triage_review_check(task, candidates, ledger, evidence, supplement, scenario_id, jurisdiction):
    from decision_workflow import effective_decision
    index = {item.get("candidate_id"): (collection, item) for collection, item in iter_candidates(candidates)}
    def reviewed(item):
        found = index.get(item.get("candidate_id"))
        if not found or ledger is None:
            return False
        decision = effective_decision(task, ledger, found[0], found[1], scenario_id, jurisdiction,
                                      item.get("right_type"), evidence=evidence, supplement=supplement)
        return decision.get("current") is True and decision.get("decision") in {"selected", "not_selected", "needs_info"}
    return reviewed


def query_coverage(evidence: dict[str, Any], candidates: dict[str, Any], plan: dict[str, Any], provider: str, query: dict[str, Any], task: dict[str, Any] | None = None, *, strict_lineage: bool = False,
                   ledger: dict | None = None, supplement: dict | None = None, scenario_id: str | None = None) -> dict[str, Any]:
    from workflow_v24 import scenario_workflow_enabled
    scenario_mode = scenario_workflow_enabled(task or {})
    review_check = _triage_review_check(task, candidates, ledger, evidence, supplement, scenario_id, query.get("jurisdiction")) if scenario_mode else materiality_annotation_complete
    candidates_for_query = _query_candidates(candidates, evidence, str(query.get("query_id") or ""))
    reviewed = sum(review_check(item) for item in candidates_for_query)
    output = {"query_id": query.get("query_id"), "provider": provider,
              "search_dimension": query.get("search_dimension"), "search_language": query.get("search_language"),
              "execution_phase": query.get("execution_phase"), "complete": False,
              "reviewed_candidates": reviewed, "bound_candidates": len(candidates_for_query), "gap": "QUERY_NOT_COMPLETED"}
    if scenario_mode:
        output.update(retrieval_complete=False, triage_complete=reviewed == len(candidates_for_query))
    for run in reversed(bound_runs(evidence, plan, provider, query)):
        output["source_status"] = run.get("status")
        if run.get("status") not in {"success", "no_result"}:
            continue
        if provider == "asset_provenance":
            from record_asset_provenance import specialty_enabled, investigation_complete
            if specialty_enabled(task or {}):
                entries = [entry for entry in evidence_index(evidence).values() if _entry_matches_run(entry, run)]
                for entry in entries:
                    payload = entry.get("payload", {})
                    if isinstance(payload, dict):
                        output.update(outstanding_actions=payload.get("outstanding_actions", []), unresolved_facts=payload.get("unresolved", []))
                    if (isinstance(payload, dict) and _retained_artifacts_complete(payload)
                            and investigation_complete(task, payload, query, scenario_id,
                                {**evidence_index(evidence), **{item["evidence_id"]: item for item in (supplement or {}).get("evidence", [])}})):
                        output.update(complete=True, retrieval_complete=True, gap="",
                            investigation_status="completed", unresolved_facts=payload.get("unresolved", []),
                            evidence_refs=[entry["evidence_id"]],
                            reviewed_assets=len(payload["coverage_attestation"]["reviewed_asset_ids"]))
                        return output
                output.update(gap="INVESTIGATION_STEPS_OR_SCOPE_INCOMPLETE", investigation_status="incomplete")
                continue
            inventories = (task or {}).get("product", {}).get("assets", [])
            expected_assets = {item.get("asset_id") for item in inventories if isinstance(item, dict) and item.get("asset_id")}
            entries = [entry for entry in evidence_index(evidence).values() if _entry_matches_run(entry, run)]
            for entry in entries:
                payload = entry.get("payload", {})
                attestation = payload.get("coverage_attestation", {})
                if (expected_assets and attestation.get("inventory_complete") is True
                        and set(attestation.get("asset_ids", [])) == expected_assets
                        and set(attestation.get("reviewed_asset_ids", [])) == expected_assets
                        and payload.get("unresolved") == [] and _retained_artifacts_complete(payload)):
                    output.update(complete=True, gap="", reviewed_assets=len(expected_assets))
                    return output
            output["gap"] = "ASSET_INVENTORY_OR_PROVENANCE_INCOMPLETE"
            continue
        from finalize_assessment import _authoritative_run
        if (not _authoritative_run(evidence, run)
                or str(run.get("source_environment") or "").casefold() in NON_PRODUCTION
                or run.get("authoritative_for_final_rating") is False):
            output["gap"] = "NON_AUTHORITATIVE_RECALL_SOURCE"
            continue
        metadata = run.get("metadata", {}).get("search_coverage", {})
        if not isinstance(metadata, dict):
            metadata = {}
        output["search_coverage"] = metadata
        total, retrieved = metadata.get("total_hits"), metadata.get("retrieved_hits")
        if (metadata.get("schema_valid") is not True or isinstance(total, bool) or not isinstance(total, int)
                or isinstance(retrieved, bool) or not isinstance(retrieved, int) or total < 0 or retrieved < 0):
            output["gap"] = "SEARCH_SCHEMA_OR_TOTAL_UNKNOWN"
            continue
        if run.get("status") == "no_result" and (total != 0 or retrieved != 0 or candidates_for_query):
            output["gap"] = "ZERO_RESULT_CONTRADICTION"
            continue
        if metadata.get("truncated") is not False or retrieved < total:
            output["gap"] = "SEARCH_TRUNCATED"
            continue
        if not str(metadata.get("stop_reason") or "").strip():
            output["gap"] = "STOP_REASON_MISSING"
            continue
        actual_records = _source_records(evidence, str(run.get("run_id") or ""))
        if actual_records is None or len(actual_records) != retrieved:
            output["gap"] = "SOURCE_RECORD_COUNT_MISMATCH"
            continue
        if scenario_mode:
            if not _records_accounted_for(actual_records, candidates_for_query, lambda item: True):
                output["gap"] = "SOURCE_RECORD_IDENTITY_NOT_ACCOUNTED_FOR"
                continue
            output["retrieval_complete"] = True
        if retrieved and (not candidates_for_query or reviewed != len(candidates_for_query)):
            output["gap"] = "CANDIDATES_NOT_BOUND_OR_REVIEWED"
            continue
        # A count copied into candidate metadata cannot account for vanished
        # source records; missing normalization lineage remains incomplete.
        if not strict_lineage and retrieved > len(candidates_for_query):
            output["gap"] = "RETRIEVED_RESULTS_NOT_ACCOUNTED_FOR"
            continue
        if strict_lineage and not _records_accounted_for(actual_records, candidates_for_query, review_check):
            output["gap"] = "SOURCE_RECORD_IDENTITY_NOT_ACCOUNTED_FOR"
            continue
        output.update(complete=True, gap="")
        return output
    return output


def _complete_paginated_series(checked: list[dict[str, Any]], rows: list[tuple[str, dict[str, Any]]], evidence: dict[str, Any], candidates: dict[str, Any], plan: dict[str, Any], *, strict_lineage: bool = False,
                               task: dict | None = None, ledger: dict | None = None, supplement: dict | None = None, scenario_id: str | None = None) -> None:
    """A complete set of actual distinct records can satisfy a paginated query.

    Counts alone never establish completeness. Repeated pages and conflicting
    totals remain gaps, and fetched records must survive normalization/review.
    """
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    from workflow_v24 import scenario_workflow_enabled
    scenario_mode = scenario_workflow_enabled(task or {})
    by_id = {row["query_id"]: row for row in checked}
    meta_keys = {"query_id", "range", "page", "page_size", "size", "start", "offset", "position", "pagination_parent_id", "derived_from", "wave"}
    for provider, query in rows:
        if provider == "asset_provenance":
            continue
        key = sha256_json({"provider": provider, **{field: value for field, value in query.items() if field not in meta_keys}})
        groups.setdefault(key, []).append((provider, query))
    entries = evidence_index(evidence)
    for series in groups.values():
        if len(series) < 2:
            continue
        totals, actual_records, reviewed_candidates, attempted_ids = set(), set(), set(), []
        valid = True
        triaged = True
        for provider, query in series:
            runs = [run for run in bound_runs(evidence, plan, provider, query) if run.get("status") in {"success", "no_result"}]
            if not runs:
                valid = False
                break
            run = runs[-1]
            from finalize_assessment import _authoritative_run
            if (not _authoritative_run(evidence, run)
                    or run.get("authoritative_for_final_rating") is False
                    or str(run.get("source_environment") or "").casefold() in NON_PRODUCTION):
                valid = False
                break
            meta = run.get("metadata", {}).get("search_coverage", {})
            total = meta.get("total_hits")
            if meta.get("schema_valid") is not True or isinstance(total, bool) or not isinstance(total, int) or total < 0:
                valid = False
                break
            totals.add(total)
            payloads = [entry.get("payload") for entry in entries.values() if _entry_matches_run(entry, run)]
            page_records = []
            for payload in payloads:
                if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
                    page_records.extend(payload["candidates"])
                elif isinstance(payload, list):
                    page_records.extend(payload)
            if len(page_records) != meta.get("retrieved_hits"):
                valid = False
                break
            for record in page_records:
                if not isinstance(record, dict):
                    valid = False
                    break
                identifier = next((str(record.get(field)) for field in ("publication_number", "registration_number", "application_number", "serial_number", "record_number", "candidate_id") if record.get(field)), "")
                if not identifier:
                    valid = False
                    break
                actual_records.add((query.get("right_type"), re.sub(r"\W", "", identifier).upper()))
            bound_candidates = _query_candidates(candidates, evidence, query["query_id"])
            review_check = _triage_review_check(task, candidates, ledger, evidence, supplement, scenario_id, query.get("jurisdiction")) if scenario_mode else materiality_annotation_complete
            if strict_lineage and not _records_accounted_for(page_records, bound_candidates, (lambda item: True) if scenario_mode else review_check):
                valid = False
                by_id[query["query_id"]]["gap"] = "SOURCE_RECORD_IDENTITY_NOT_ACCOUNTED_FOR"
                break
            if any(not review_check(item) for item in bound_candidates):
                if not scenario_mode:
                    valid = False
                    break
                triaged = False
            reviewed_candidates.update(str(item.get("candidate_id") or "") for item in bound_candidates)
            attempted_ids.append(query["query_id"])
        if valid and len(totals) == 1 and len(actual_records) == next(iter(totals)) and len(reviewed_candidates) >= len(actual_records):
            for query_id in attempted_ids:
                by_id[query_id].update(complete=triaged, gap="" if triaged else "CANDIDATES_NOT_BOUND_OR_REVIEWED", pagination_complete=True,
                    series_distinct_records=len(actual_records), series_reviewed_candidates=len(reviewed_candidates))
                if scenario_mode:
                    by_id[query_id].update(retrieval_complete=True, triage_complete=triaged)


def coverage_by_scope(task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any], plan: dict[str, Any], *, strict_lineage: bool = False,
                      ledger: dict | None = None, supplement: dict | None = None, evidence_root=None) -> list[dict[str, Any]]:
    from workflow_v24 import scenario_workflow_enabled
    if scenario_workflow_enabled(task):
        return scenario_coverage_by_scope(task, evidence, candidates, plan, ledger=ledger, supplement=supplement, evidence_root=evidence_root)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for requirement in task.get("coverage_requirements", []):
        if not isinstance(requirement, dict) or requirement.get("right_type") == "enforcement":
            continue
        key = (str(requirement.get("jurisdiction") or "").upper(), str(requirement.get("right_type") or ""))
        group = groups.setdefault(key, {"jurisdiction": key[0], "right_type": key[1], "status": "满足已定义要求",
                                       "requirement_ids": [], "gaps": [], "queries": []})
        requirement_id = str(requirement.get("requirement_id") or "")
        group["requirement_ids"].append(requirement_id)
        if requirement.get("phase") in {"candidate_verification", "verification"}:
            continue  # Candidate and geographic verification is checked per assessment.
        axes = set(requirement.get("required_axes", []))
        routes = {(route.get("provider"), route.get("operation")) for route in requirement.get("routes", []) if isinstance(route, dict)}
        rows = [(provider, row) for provider, row in _plan_rows(plan)
                if requirement_id in row.get("requirement_ids", []) and (provider, row.get("operation")) in routes
                and str(row.get("jurisdiction") or "").upper() == key[0] and row.get("right_type") == key[1]]
        checked = [query_coverage(evidence, candidates, plan, provider, query, task, strict_lineage=strict_lineage) for provider, query in rows]
        _complete_paginated_series(checked, rows, evidence, candidates, plan, strict_lineage=strict_lineage)
        group["queries"].extend(checked)
        # A convenient zero-result keyword must not hide another incomplete
        # query on the same axis. Providers are alternative whole routes.
        axis_routes: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        planned_by_id = {query["query_id"]: query for _, query in rows}
        for row in checked:
            route_key = (row["provider"], str(planned_by_id[row["query_id"]].get("operation") or ""), str(row.get("search_dimension") or ""))
            axis_routes.setdefault(route_key, []).append(row)
        completed_axis_routes = {key: values for key, values in axis_routes.items() if values and all(row["complete"] for row in values)}
        completed_axes = {key[2] for key in completed_axis_routes}
        if not axes:
            group["gaps"].append(requirement_id + ":SEARCH_AXES_UNDEFINED")
        for axis in sorted(axes - completed_axes):
            group["gaps"].append(requirement_id + ":AXIS_MISSING:" + axis)
        local_language = LANGUAGES.get(key[0])
        if "text" in axes and local_language and not any(key[2] == "text" and any(row.get("search_language") == local_language for row in values) for key, values in completed_axis_routes.items()):
            group["gaps"].append(requirement_id + ":LOCAL_LANGUAGE_MISSING:" + local_language)
        # Expansion is required only where a related material candidate exists.
        material = [item for _, item in iter_candidates(candidates) if item.get("material") is True and candidate_applies(item, key[0], key[1])]
        if material and requirement.get("expansion_required", key[1] in {"patent", "utility_model"}) and not any(row["complete"] and row.get("execution_phase") == "expansion" for row in checked):
            group["gaps"].append(requirement_id + ":CANDIDATE_EXPANSION_MISSING")
    for group in groups.values():
        group["gaps"] = sorted(set(group["gaps"]))
        if group["gaps"]:
            group["status"] = "部分完成" if any(row["complete"] for row in group["queries"]) else "受阻"
    return sorted(groups.values(), key=lambda row: (row["jurisdiction"], row["right_type"]))


def _scenario_action_complete(evidence: dict, plan: dict, provider: str, row: dict) -> bool:
    """A response is not current-effect proof unless its bound payload says so."""
    from finalize_assessment import _authoritative_run
    for run in reversed(bound_runs(evidence, plan, provider, row)):
        if (run.get("status") != "success" or str(run.get("source_environment") or "").casefold() in NON_PRODUCTION
                or (row.get("action_purpose") == "official_verification"
                    and (run.get("authoritative_for_final_rating") is False or not _authoritative_run(evidence, run)))):
            continue
        payloads = [entry.get("payload") for entry in evidence_index(evidence).values() if _entry_matches_run(entry, run)]
        for payload in payloads:
            records = payload if isinstance(payload, list) else payload.get("candidates", [payload]) if isinstance(payload, dict) else []
            for record in records:
                if not isinstance(record, dict):
                    continue
                if row.get("workflow_correction_revision") == "workflow-correction-v1" and row.get("execution_phase") == "needs_info":
                    from workflow_v24 import requested_facts_satisfied
                    if requested_facts_satisfied(row, record):
                        return True
                    continue
                if row.get("action_purpose") == "official_verification":
                    verification = record.get("official_verification") or {}
                    if (verification.get("status") == "verified" and verification.get("identity_match") is True
                            and str(verification.get("legal_status") or "").strip()
                            and record.get("candidate_id") == row.get("candidate_id")):
                        return True
                elif row.get("action_purpose") == "document_content":
                    if (record.get("authority_scope") == "published_document_only"
                            and record.get("candidate_id") == row.get("candidate_id")
                            and record.get("document_identity_match") is True
                            and _document_number(record.get("publication_number")) == _document_number(row.get("document") or row.get("q"))
                            and any(record.get(key) for key in ("claims", "claim_text", "document_text", "description", "descriptions"))):
                        return True
                elif row.get("execution_phase") == "needs_info" and record:
                    return True
    return False


def scenario_coverage_by_scope(task: dict, evidence: dict, candidates: dict, plan: dict, *,
                               ledger: dict | None = None, supplement: dict | None = None, evidence_root=None) -> list[dict]:
    from decision_workflow import scenario_index, triage_summary, necessary_scenario_right_types
    from workflow_v24 import (necessary_scenario_row_bindings, scenario_dispatch_block, validated_query_substitution,
                             scenario_historical_reuse, scenario_fact_reuse)
    scenarios = scenario_index(task)
    ledger = ledger or {"schema_version": "2.0", "task_id": task.get("task_id"), "annotations": []}
    triage = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)
    rows = _plan_rows(plan)
    outputs = []
    for sid, scenario in scenarios.items():
        groups = {}
        for requirement in task.get("coverage_requirements", []):
            if (not isinstance(requirement, dict) or requirement.get("right_type") == "enforcement"
                    or requirement.get("right_type") not in necessary_scenario_right_types(task, scenario)):
                continue
            key = (requirement["jurisdiction"], requirement["right_type"])
            group = groups.setdefault(key, {"scenario_id": sid, "scenario_sha256": scenario["scenario_sha256"],
                "jurisdiction": key[0], "right_type": key[1], "status": "满足已定义要求", "requirement_ids": [],
                "gaps": [], "queries": [], "obligations": [], "queues": {"unreviewed": [], "needs_info": [], "selected": []}})
            group["requirement_ids"].append(requirement["requirement_id"])
        for key, group in groups.items():
            scope_rows = [(provider, row) for provider, row in rows
                          if {"scenario_id": sid, "scenario_sha256": scenario["scenario_sha256"]} in necessary_scenario_row_bindings(task, row)
                          and (row.get("triage_jurisdiction") or row.get("jurisdiction"), row.get("right_type")) == key
                          and row.get("required_for") not in {"discovery_only", "optional_enrichment"}
                          and not scenario_dispatch_block(task, plan, provider, row, candidates, ledger, evidence, supplement=supplement, for_dispatch=False)]
            recall_rows = [(provider, row) for provider, row in scope_rows if row.get("action_purpose") in {"recall", "provenance"}]
            checked = [query_coverage(evidence, candidates, plan, provider, row, task, strict_lineage=True,
                                     ledger=ledger, supplement=supplement, scenario_id=sid) for provider, row in recall_rows]
            _complete_paginated_series(checked, recall_rows, evidence, candidates, plan, strict_lineage=True,
                                       task=task, ledger=ledger, supplement=supplement, scenario_id=sid)
            by_id = {item["query_id"]: item for item in checked}
            for provider, row in scope_rows:
                if row["query_id"] not in by_id:
                    complete = _scenario_action_complete(evidence, plan, provider, row)
                    by_id[row["query_id"]] = {"query_id": row["query_id"], "provider": provider,
                        "complete": complete, "gap": "" if complete else "NECESSARY_CANDIDATE_EVIDENCE_MISSING",
                        "execution_phase": row.get("execution_phase"), "search_dimension": row.get("search_dimension"),
                        "search_language": row.get("search_language")}
                result = by_id[row["query_id"]]
                if result.get("complete"):
                    continue
                reused_fact = scenario_fact_reuse(task, plan, evidence, candidates, ledger, provider, row,
                                                  supplement=supplement, evidence_root=evidence_root)
                if reused_fact is not None:
                    result.update(complete=True, gap="", fact_reuse=reused_fact,
                                  evidence_refs=reused_fact["evidence_refs"],
                                  authority_scope=reused_fact["authority_scope"], dispatch="fact_reused",
                                  submission_state="not_submitted", source_query_performed=False)
                    continue
                retained = scenario_historical_reuse(task, provider, row, candidates, supplement,
                                                      evidence_root=evidence_root, scenario_id=sid)
                if retained is None:
                    continue
                result["historical_reuse"] = retained
                result["evidence_refs"] = retained["evidence_refs"]
                if row.get("action_purpose") == "recall":
                    # Original retrieval may be reused, never the old review.
                    current = {item.get("candidate_id"): item for _, item in iter_candidates(candidates)}
                    ids = retained["retained_candidate_ids"]
                    reviewed = _triage_review_check(task, candidates, ledger, evidence, supplement, sid, key[0])
                    all_reviewed = all(identity in current and reviewed(current[identity]) for identity in ids)
                    result.update(retrieval_complete=True, triage_complete=all_reviewed,
                                  complete=all_reviewed, candidate_count=len(ids),
                                  reviewed_count=sum(reviewed(current[identity]) for identity in ids if identity in current),
                                  gap="" if all_reviewed else "RETAINED_RESULTS_REQUIRE_CURRENT_TRIAGE")
                else:
                    result.update(complete=True, gap="", authority_scope=retained["authority_scope"])
            obligations = {}
            for provider, row in scope_rows:
                oid = row.get("evidence_obligation_id")
                if not oid:
                    group["gaps"].append("ACTION_OBLIGATION_BINDING_MISSING:" + row["query_id"])
                    continue
                obligation = obligations.setdefault(oid, {"evidence_obligation_id": oid, "action_purpose": row.get("action_purpose"),
                    "scenario_id": sid, "jurisdiction": key[0], "right_type": key[1], "complete": False,
                    "query_ids": [], "completed_query_ids": [], "retrieval_complete": False, "gap": "NECESSARY_EVIDENCE_MISSING"})
                obligation["query_ids"].append(row["query_id"])
                result = by_id[row["query_id"]]
                substitution = validated_query_substitution(task, plan, row, scenario_id=sid)
                if substitution and substitution["scenario_id"] == sid:
                    target = by_id.get(substitution["new_query_id"])
                    if target and target["complete"]:
                        result = target
                if result["complete"]:
                    obligation["complete"] = True
                    obligation["gap"] = ""
                    obligation["completed_query_ids"].append(result["query_id"])
                obligation["retrieval_complete"] |= bool(result.get("retrieval_complete", result["complete"]))
            group["queries"] = list(by_id.values())
            group["obligations"] = list(obligations.values())
            for obligation in obligations.values():
                if not obligation["complete"]:
                    group["gaps"].append("OBLIGATION_INCOMPLETE:" + obligation["evidence_obligation_id"])
            for requirement in task.get("coverage_requirements", []):
                if (requirement.get("jurisdiction"), requirement.get("right_type")) != key or requirement.get("phase") not in {"official_recall", "provenance"}:
                    continue
                relevant = [row for _, row in scope_rows if requirement["requirement_id"] in row.get("requirement_ids", [])]
                # A reviewed empty figurative inventory may close this scope;
                # missing pictures or an unexecuted inventory never can.
                from record_asset_provenance import specialty_enabled, asset_scope
                if specialty_enabled(task) and key[1] == "trademark_figurative":
                    inventory = asset_scope(task, sid, key[1])
                    if (inventory["inventory_reviewed"] and not inventory["asset_ids"]
                            and any(result.get("complete") and result.get("investigation_status") == "completed"
                                    for result in by_id.values())):
                        continue
                for axis in requirement.get("required_axes", []):
                    matching = [row for row in relevant if row.get("search_dimension") == axis]
                    if not matching:
                        group["gaps"].append(requirement["requirement_id"] + ":AXIS_MISSING:" + axis)
                language_axis = "description" if specialty_enabled(task) and key == ("US", "trademark_figurative") else "text"
                if requirement.get("required_language") and language_axis in requirement.get("required_axes", []):
                    if not any(row.get("search_dimension") == language_axis and row.get("search_language") == requirement["required_language"] for row in relevant):
                        group["gaps"].append(requirement["requirement_id"] + ":LOCAL_LANGUAGE_MISSING")
            records = [record for record in triage["records"] if record["scenario_id"] == sid
                       and (record["jurisdiction"], record["right_type"]) == key]
            for record in records:
                decision = record["decision"] if record.get("current") else "unreviewed"
                if decision in group["queues"]:
                    group["queues"][decision].append(record)
                if decision in {"unreviewed", "needs_info"}:
                    group["gaps"].append("TRIAGE_" + decision.upper() + ":" + record["candidate_id"])
                elif decision == "selected" and key[1] in REGISTERED:
                    candidate_rows = [row for _, row in scope_rows if row.get("triage_candidate_id") == record["candidate_id"] and row.get("action_purpose") == "official_verification"]
                    if not candidate_rows:
                        group["gaps"].append("SELECTED_VERIFICATION_UNPLANNED:" + record["candidate_id"])
                    if any(req.get("expansion_required") for req in task.get("coverage_requirements", []) if (req.get("jurisdiction"), req.get("right_type")) == key):
                        if not any(row.get("triage_candidate_id") == record["candidate_id"] and row.get("execution_phase") == "expansion" for _, row in scope_rows):
                            group["gaps"].append("SELECTED_EXPANSION_UNPLANNED:" + record["candidate_id"])
            # Initial asset investigations belong to retrieval; selected-right
            # investigations are necessary verification even though both use the
            # same local provenance recorder. Preserve the historical split.
            candidate_provenance = {row.get("evidence_obligation_id") for _, row in scope_rows
                if specialty_enabled(task) and row.get("action_purpose") == "provenance"
                and row.get("execution_phase") == "verification" and row.get("triage_candidate_id")}
            retrieval_obligations = [item for item in obligations.values()
                if item["action_purpose"] in {"recall", "provenance"}
                and item["evidence_obligation_id"] not in candidate_provenance]
            verification_obligations = [item for item in obligations.values()
                if item["action_purpose"] not in {"recall", "provenance"}
                or item["evidence_obligation_id"] in candidate_provenance]
            group["retrieval_status"] = "complete" if retrieval_obligations and all(item["retrieval_complete"] for item in retrieval_obligations) and not any(":AXIS_MISSING:" in gap or ":LOCAL_LANGUAGE_MISSING" in gap for gap in group["gaps"]) else "incomplete"
            group["triage_status"] = "incomplete" if group["queues"]["unreviewed"] else "complete"
            group["verification_status"] = "complete" if all(item["complete"] for item in verification_obligations) and not group["queues"]["needs_info"] and not any(gap.startswith("SELECTED_") for gap in group["gaps"]) else "incomplete"
            group["gaps"] = sorted(set(group["gaps"]))
            if group["gaps"]:
                group["status"] = "部分完成" if any(item["complete"] for item in obligations.values()) else "受阻"
            if specialty_enabled(task):
                group["unresolved_facts"] = [fact for result in by_id.values() for fact in result.get("unresolved_facts", [])]
                reasons = []
                runs = {run.get("query_id"): run for run in evidence.get("source_runs", [])}
                for provider, row in scope_rows:
                    result = by_id[row["query_id"]]
                    if result.get("complete"):
                        continue
                    run = runs.get(row["query_id"], {})
                    code = run.get("error_code") or result.get("gap")
                    if "TRUNCAT" in str(code) or result.get("search_coverage", {}).get("truncated"):
                        kind = "truncated"
                    elif run.get("status") in {"access_limited", "needs_user_action"}:
                        kind = "access_limited"
                    elif any(token in str(code) for token in ("UNSUPPORTED", "UNIMPLEMENTED", "ADAPTER", "INTERNAL_ROUTE")):
                        kind = "adapter_missing"
                    elif any(isinstance(action, dict) and action.get("kind") == "user_information" for action in result.get("outstanding_actions", [])):
                        kind = "user_information_required"
                    elif provider == "asset_provenance":
                        kind = "public_investigation_pending"
                    else:
                        kind = "execution_failed" if run else "not_executed"
                    reasons.append({"query_id": row["query_id"], "kind": kind, "code": code,
                                    "next_step": row.get("search_dimension"), "assigned_to": "user" if kind == "user_information_required" else "agent"})
                group["work_reasons"] = reasons
                if group["gaps"] and not any(item["complete"] for item in obligations.values()):
                    group["status"] = "访问受限" if reasons and all(item["kind"] == "access_limited" for item in reasons) else "待执行"
            outputs.append(group)
    return sorted(outputs, key=lambda row: (row["scenario_id"], row["jurisdiction"], row["right_type"]))


def candidate_applies(item: dict[str, Any], jurisdiction: str, right_type: str) -> bool:
    from finalize_assessment import _candidate_effect_jurisdictions
    if item.get("right_type") != right_type:
        return False
    if right_type in UNREGISTERED:
        # The location of a source/author is not a territorial exclusion.
        return True
    effects = _candidate_effect_jurisdictions(item, right_type)
    european = jurisdiction in {"GB", "FR", "DE", "IT", "ES"}
    return jurisdiction in effects or (right_type == "patent" and "EU" in effects and european)


def validate_review(review: dict[str, Any], digest: str, evidence: dict[str, Any], candidates: dict[str, Any], scopes: set[tuple[str, str]]) -> None:
    known = set(evidence_index(evidence))
    context = review.get("review_context", {})
    if not str(review.get("reviewer") or "").strip() or not str(context.get("session_id") or "").strip() or context.get("evidence_digest") != digest or context.get("first_review_visible") is not False:
        raise ValueError("REVIEW_CONTEXT_INVALID: independent reviewer/session and identical evidence/ledger/plan digest required")
    rows = review.get("assessments")
    if not isinstance(rows, list):
        raise ValueError("review.assessments must be an array")
    index, errors = candidate_index(candidates)
    if errors:
        raise ValueError("; ".join(errors))
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Assessment must be an object")
        key = scope_key(row)
        if key in seen or key[:2] not in scopes or key[1] not in CRITERIA:
            raise ValueError("DUPLICATE_OR_UNSUPPORTED_ASSESSMENT_SCOPE: " + str(key))
        seen.add(key)
        if key[2] and (key[2] not in index or index[key[2]][1].get("right_type") != key[1]):
            raise ValueError("ASSESSMENT_CANDIDATE_IDENTITY_MISMATCH: " + str(key))
        if row.get("risk") not in RISKS or row.get("evidence_confidence") not in CONFIDENCES or not str(row.get("reasoning") or "").strip():
            raise ValueError("Invalid risk/confidence/reasoning")
        if not _refs(row.get("evidence_refs", []), known, required=row["risk"] != "无法判断"):
            raise ValueError("Missing or unknown assessment evidence refs")
        if row.get("right_state", "unknown") not in {"active", "pending", "expired", "unknown"} or not _refs(row.get("right_state_evidence_refs", []), known, required=row.get("right_state", "unknown") != "unknown"):
            raise ValueError("Invalid current right state/evidence")
        if row["risk"] in {"中", "高"} and not key[2]:
            raise ValueError("Risk-bearing finding needs a candidate; missing access is not medium risk")
        findings = row.get("findings", [])
        if not isinstance(findings, list) or (row["risk"] in {"中", "高"} and not findings):
            raise ValueError("Risk-bearing assessment needs findings")
        for finding in findings:
            if not isinstance(finding, dict) or any(not str(finding.get(field) or "").strip() for field in ("finding_id", "title", "recommended_action")) or not _refs(finding.get("evidence_refs"), known):
                raise ValueError("Invalid finding evidence or required fields")
        comparison = row.get("comparison", {})
        if not isinstance(comparison, dict) or not isinstance(comparison.get("criteria", []), list) or not isinstance(comparison.get("unresolved", []), list):
            raise ValueError("Invalid comparison contract")
        criteria_seen = set()
        for criterion in comparison.get("criteria", []):
            if not isinstance(criterion, dict) or not criterion.get("criterion") or criterion["criterion"] in criteria_seen:
                raise ValueError("Missing/duplicate comparison criterion")
            criteria_seen.add(criterion["criterion"])
            if criterion.get("result") not in RESULTS or not str(criterion.get("reasoning") or "").strip() or not _refs(criterion.get("evidence_refs", []), known, required=criterion.get("result") != "unknown"):
                raise ValueError("Comparison criterion lacks result/reason/evidence")
        if not isinstance(comparison.get("claims", []), list):
            raise ValueError("comparison.claims must be an array")
        for claim in comparison.get("claims", []):
            if not isinstance(claim, dict) or not claim.get("claim_id") or not _refs(claim.get("claim_evidence_refs"), known) or not isinstance(claim.get("elements"), list):
                raise ValueError("Invalid claim text/evidence binding")
            for element in claim["elements"]:
                if not isinstance(element, dict) or not _refs(element.get("evidence_refs", []), known, required=element.get("result") != "unknown") or element.get("result") not in RESULTS:
                    raise ValueError("Invalid claim element evidence/result")
                if not _refs(element.get("product_evidence_refs", []), known, required=False) or not isinstance(element.get("claim_quote", ""), str):
                    raise ValueError("Invalid claim element product/original binding")
        visual = comparison.get("visual_coverage", {})
        if visual:
            if not isinstance(visual, dict) or not isinstance(visual.get("required_views"), list):
                raise ValueError("Invalid required visual views")
            for side in ("product_views", "right_views"):
                if not isinstance(visual.get(side), list) or any(not isinstance(view, dict) or not view.get("view") or not _refs(view.get("evidence_refs"), known) for view in visual[side]):
                    raise ValueError("Invalid evidence-bound visual view")
        basis = row.get("confidence_basis", {})
        if not isinstance(basis, dict):
            raise ValueError("confidence_basis must be an object")
        for value in basis.values():
            if not isinstance(value, dict) or not isinstance(value.get("satisfied"), bool) or not str(value.get("reasoning") or "").strip() or not _refs(value.get("evidence_refs", []), known, required=value.get("satisfied") is True):
                raise ValueError("Confidence prerequisite lacks reason or evidence")
    for name in ("future_applications", "enforcement_signals"):
        if not isinstance(review.get(name, []), list):
            raise ValueError(name + " must be an array")
        for row in review.get(name, []):
            if not isinstance(row, dict) or not str(row.get("reasoning") or "").strip() or not _refs(row.get("evidence_refs"), known):
                raise ValueError("Invalid supplemental signal: " + name)


def official_refs(task: dict[str, Any], evidence: dict[str, Any], plan: dict[str, Any], candidate: dict[str, Any], jurisdiction: str, right_type: str) -> set[str]:
    from finalize_assessment import _verification_evidence_records, _official_payload_complete
    found = set()
    for requirement in task.get("coverage_requirements", []):
        if (requirement.get("phase") not in {"candidate_verification", "verification"}
                or requirement.get("jurisdiction") != jurisdiction or requirement.get("right_type") != right_type):
            continue
        for entry, official in _verification_evidence_records(candidate, evidence, requirement.get("routes", []),
                jurisdiction=jurisdiction, right_type=right_type, requirement_ids={requirement["requirement_id"]},
                search_plan=plan, include_entries=True):
            run = next((run for run in evidence.get("source_runs", []) if run.get("run_id") == entry.get("source_run_id")), {})
            if _official_payload_complete(official, right_type) and str(run.get("source_environment") or "").casefold() not in NON_PRODUCTION:
                found.add(str(entry["evidence_id"]))
    return found


def _provenance_refs(evidence: dict[str, Any], plan: dict[str, Any], row: dict[str, Any]) -> set[str]:
    found = set()
    for provider, query in _plan_rows(plan):
        if provider != "asset_provenance" or query.get("operation") != "provenance_review" or query.get("jurisdiction") != row["jurisdiction"] or query.get("right_type") != row["right_type"]:
            continue
        runs = [run for run in bound_runs(evidence, plan, provider, query) if run.get("status") == "success"]
        for entry in evidence_index(evidence).values():
            payload = entry.get("payload", {})
            if any(_entry_matches_run(entry, run) for run in runs) and isinstance(payload, dict) and payload.get("candidate_id") == row.get("candidate_id") and _retained_artifacts_complete(payload) and payload.get("ownership_or_source_reasoning") and payload.get("unresolved") == []:
                found.add(entry["evidence_id"])
    return found


def _valid_media_hashes(items: Any) -> set[str]:
    from common import image_info
    found = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            path = Path(str(item.get("path") or ""))
            if path.is_file() and path.stat().st_size == item.get("bytes") and sha256_file(path) == item.get("sha256"):
                mime, width, height = image_info(path)
                if mime.startswith("image/") and width > 0 and height > 0:
                    found.add(item["sha256"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found


def _product_evidence(task: dict[str, Any], evidence: dict[str, Any]) -> dict[str, set[str]]:
    """A browser collection also contains registry pages; it is not a product type."""
    found = {}
    expected = str(task.get("product", {}).get("actual_asin") or "")
    product_images = _valid_media_hashes(task.get("images", []))
    for entry in evidence.get("collections", {}).get("product", []):
        payload = entry.get("payload", entry)
        product = payload.get("product", payload)
        actual = str(product.get("actual_asin") or product.get("asin") or "")
        hashes = _valid_media_hashes(payload.get("images", [])) & product_images
        if expected and actual == expected and hashes and entry.get("evidence_id"):
            found[entry["evidence_id"]] = hashes
    return found


def _payload_records(payload: Any) -> list[dict[str, Any]]:
    values = payload.get("candidates", [payload]) if isinstance(payload, dict) else payload
    return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []


def _document_number(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _claim_documents(evidence: dict[str, Any], plan: dict[str, Any], candidate: dict[str, Any], official: set[str]) -> dict[str, dict[str, str]]:
    """Return claim number/text only from same-document retained original content.

    EPS XML is supported now. Official record adapters can also retain typed
    claims in their raw JSON capture and normalized record; a status page or
    arbitrary extracted page text cannot substitute for that contract.
    """
    identifiers = {_document_number(candidate.get(key)) for key in ("publication_number", "grant_number", "record_number") if candidate.get(key)}
    found = {}
    for provider, query in _plan_rows(plan):
        if query.get("candidate_id") != candidate.get("candidate_id"):
            continue
        for run in bound_runs(evidence, plan, provider, query):
            if run.get("status") != "success" or str(run.get("source_environment") or "").casefold() in NON_PRODUCTION:
                continue
            for entry in evidence_index(evidence).values():
                if not _entry_matches_run(entry, run) or not (entry.get("evidence_id") in official or (provider == "epo_publication_server" and query.get("operation") == "document_retrieval")):
                    continue
                for record in _payload_records(entry.get("payload")):
                    document = _document_number(record.get("publication_number") or record.get("record_number"))
                    if record.get("candidate_id") != candidate.get("candidate_id") or document not in identifiers:
                        continue
                    if not (record.get("document_identity_match") is True or record.get("official_verification", {}).get("identity_match") is True):
                        continue
                    normalized_claims = record.get("claims", [])
                    for raw in run.get("raw_paths", []):
                        try:
                            path = Path(raw)
                            if not path.is_file() or sha256_file(path) != run.get("payload_digest"):
                                continue
                            if provider == "epo_publication_server":
                                from eps_client import normalize_document
                                source = normalize_document(document, path.read_bytes(), str(candidate["candidate_id"]))["candidates"][0]
                                if source.get("document_sha256") != record.get("document_sha256"):
                                    continue
                                originals = source["claims"]
                            else:
                                # JSON is the current browser/API capture artifact;
                                # PDF/OCR adapters must first implement equivalent
                                # typed original-content extraction and binding.
                                raw_records = _payload_records(json.loads(path.read_text(encoding="utf-8")))
                                originals = [claim for source in raw_records if _document_number(source.get("publication_number") or source.get("record_number")) == document for claim in source.get("claims", [])]
                            original_set = {(str(claim.get("number") or "").lstrip("0") or "0", " ".join(str(claim.get("text") or "").split())) for claim in originals if isinstance(claim, dict) and claim.get("number") and claim.get("text")}
                            for claim in normalized_claims if isinstance(normalized_claims, list) else []:
                                if not isinstance(claim, dict):
                                    continue
                                number, content = str(claim.get("number") or "").lstrip("0") or "0", " ".join(str(claim.get("text") or "").split())
                                if content and (number, content) in original_set:
                                    found.setdefault(entry["evidence_id"], {})[number] = content
                        except (OSError, ValueError, TypeError, KeyError, RuntimeError, ElementTree.ParseError):
                            continue
    return found


def _typed_comparison_gaps(row: dict[str, Any], task: dict[str, Any], evidence: dict[str, Any], plan: dict[str, Any], candidate: dict[str, Any], authoritative: set[str], products: dict[str, set[str]]) -> list[str]:
    comparison = row.get("comparison", {})
    criteria = {item["criterion"]: item for item in comparison.get("criteria", [])}
    gaps = []
    product_refs = set(products)
    right_keys = {"current_status", "territorial_effect"} if row["right_type"] in REGISTERED else {"source_provenance", "first_disclosure", "protectable_expression"}
    for key in right_keys & set(criteria):
        if not set(criteria[key].get("evidence_refs", [])) & authoritative:
            gaps.append("RIGHT_SIDE_EVIDENCE_REQUIRED:" + key)
    for key in {"product_expression", "product_views", "use_context"} & set(criteria):
        if not set(criteria[key].get("evidence_refs", [])) & product_refs:
            gaps.append("PRODUCT_SIDE_EVIDENCE_REQUIRED:" + key)
    if row["right_type"] in {"patent", "utility_model"}:
        documents = _claim_documents(evidence, plan, candidate, authoritative)
        for key in {"current_claims", "element_mapping"}:
            if not set(criteria.get(key, {}).get("evidence_refs", [])) & set(documents):
                gaps.append("CLAIM_ORIGINAL_EVIDENCE_REQUIRED:" + key)
        if not set(criteria.get("element_mapping", {}).get("evidence_refs", [])) & product_refs:
            gaps.append("PRODUCT_SIDE_EVIDENCE_REQUIRED:element_mapping")
        complete_claim = False
        for claim in comparison.get("claims", []):
            number = str(claim.get("claim_id") or "").lstrip("0") or "0"
            texts = [documents[ref][number] for ref in claim.get("claim_evidence_refs", []) if ref in documents and number in documents[ref]]
            if not texts:
                gaps.append("CLAIM_DOCUMENT_IDENTITY_OR_TEXT_MISSING:" + number)
            for element in claim.get("elements", []):
                quote = " ".join(str(element.get("claim_quote") or "").split())
                if not quote or not any(quote in content for content in texts) or not set(element.get("evidence_refs", [])) & set(documents):
                    gaps.append("CLAIM_ELEMENT_ORIGINAL_QUOTE_REQUIRED:" + number)
                if not set(element.get("product_evidence_refs", [])) & product_refs:
                    gaps.append("CLAIM_ELEMENT_PRODUCT_EVIDENCE_REQUIRED:" + number)
            # This catches omitted source text, not legal completeness. Two
            # independent Agents must still construe limiting language and
            # dependencies and compare the relevant product features.
            for content in texts:
                compact = re.sub(r"[\W_]+", "", content).casefold()
                covered = set()
                for element in claim.get("elements", []):
                    quote = re.sub(r"[\W_]+", "", str(element.get("claim_quote") or "")).casefold()
                    if quote:
                        for match in re.finditer(re.escape(quote), compact):
                            covered.update(range(match.start(), match.end()))
                if compact and len(covered) == len(compact) and claim.get("elements") and all(element.get("result") == "supports_risk" for element in claim["elements"]):
                    complete_claim = True
        if row.get("risk") == "高" and not complete_claim:
            gaps.append("CLAIM_FULL_TEXT_MAPPING_INCOMPLETE")
    if row["right_type"] in {"design", "trademark_figurative", "unregistered_design"}:
        rights = {}
        for ref in authoritative:
            entry = evidence_index(evidence)[ref]
            for record in _payload_records(entry.get("payload")):
                if record.get("candidate_id") != candidate.get("candidate_id"):
                    continue
                media = record.get("official_verification", {}).get("media", []) if row["right_type"] in REGISTERED else [artifact for artifact in record.get("artifacts", []) if artifact.get("role") in {"source_image", "protected_view", "original_work", "source_artwork", "right_view"}]
                rights.setdefault(ref, set()).update(_valid_media_hashes(media))
        visual = comparison.get("visual_coverage", {})
        for side, valid in (("product_views", products), ("right_views", rights)):
            for view in visual.get(side, []):
                if not view.get("artifact_sha256") or not any(view["artifact_sha256"] in valid.get(ref, set()) for ref in view.get("evidence_refs", [])):
                    gaps.append("VISUAL_ARTIFACT_BINDING_INVALID:" + side + ":" + str(view.get("view")))
    return gaps


def _comparison_gaps(row: dict[str, Any]) -> list[str]:
    comparison = row.get("comparison", {})
    by_key = {item["criterion"]: item for item in comparison.get("criteria", [])}
    gaps = ["COMPARISON_MISSING:" + key for key in sorted(CRITERIA[row["right_type"]] - set(by_key))]
    gaps += ["COMPARISON_UNKNOWN:" + key for key, item in by_key.items() if item["result"] == "unknown"]
    if comparison.get("unresolved"):
        gaps.append("COMPARISON_UNRESOLVED")
    if row.get("risk") == "高":
        essential = CRITERIA[row["right_type"]] - {"authorization", "exclusions"}
        gaps += ["ESSENTIAL_COMPARISON_NOT_APPLICABLE:" + key for key in sorted(essential) if by_key.get(key, {}).get("result") == "not_applicable"]
    if row["right_type"] in {"design", "trademark_figurative", "unregistered_design"}:
        visual = comparison.get("visual_coverage", {})
        required = set(visual.get("required_views", []))
        if not required or any(not required <= {view["view"] for view in visual.get(side, [])} for side in ("product_views", "right_views")):
            gaps.append("REQUIRED_VISUAL_VIEWS_INCOMPLETE")
    if row["right_type"] in {"patent", "utility_model"} and row.get("risk") == "高":
        claims = comparison.get("claims", [])
        if not isinstance(claims, list) or not any(isinstance(claim, dict) and claim.get("claim_id") and claim.get("claim_evidence_refs") and isinstance(claim.get("elements"), list) and claim["elements"] and all(isinstance(element, dict) and element.get("claim_element") and element.get("product_feature") and element.get("evidence_refs") and element.get("result") == "supports_risk" for element in claim["elements"]) for claim in claims):
            gaps.append("CLAIM_ELEMENT_MAPPING_INCOMPLETE")
    return gaps


def _conflicts(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    conflicts = []
    if left["risk"] != right["risk"]:
        conflicts.append("risk")
    if left.get("right_state", "unknown") != right.get("right_state", "unknown"):
        conflicts.append("right_state")
    if left.get("exclusion_basis") != right.get("exclusion_basis"):
        conflicts.append("exclusion_basis")
    a = {item["criterion"]: item["result"] for item in left.get("comparison", {}).get("criteria", [])}
    b = {item["criterion"]: item["result"] for item in right.get("comparison", {}).get("criteria", [])}
    conflicts += ["comparison:" + key for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key)]
    def claims(row: dict[str, Any]) -> dict[str, Any]:
        return {str(claim.get("claim_id")): {str(element.get("claim_element")): {key: element.get(key) for key in ("result", "claim_quote", "product_feature")} for element in claim.get("elements", [])} for claim in row.get("comparison", {}).get("claims", [])}
    if claims(left) != claims(right):
        conflicts.append("claim_elements")
    def visual_views(row: dict[str, Any]) -> dict[str, Any]:
        value = row.get("comparison", {}).get("visual_coverage", {})
        return {"required": sorted(value.get("required_views", [])), **{side: sorted((view.get("view", ""), view.get("artifact_sha256", "")) for view in value.get(side, [])) for side in ("product_views", "right_views")}}
    if visual_views(left) != visual_views(right):
        conflicts.append("visual_views")
    return conflicts


def evaluate_row(row: dict[str, Any], second: dict[str, Any] | None, task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any], plan: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(row)
    result["coverage"] = deepcopy(coverage)
    result["requested_risk"] = row["risk"]
    result["publication"] = "discovery_only"
    gaps = []
    if task.get("product", {}).get("input_role") != "actual_product":
        gaps.append("ACTUAL_PRODUCT_IDENTITY_NOT_ESTABLISHED")
    index, _ = candidate_index(candidates)
    candidate = index.get(row.get("candidate_id", ""), ("", {}))[1]
    if second is None:
        gaps.append("INDEPENDENT_AGENT_REVIEW_REQUIRED")
    else:
        conflicts = _conflicts(row, second)
        if conflicts:
            gaps += ["INDEPENDENT_REVIEW_CONFLICT:" + key for key in conflicts]
            result["review_proposals"] = [{"risk": value["risk"], "reasoning": value["reasoning"], "evidence_confidence": value["evidence_confidence"]} for value in (row, second)]
            result["risk"] = "无法判断"
        result["evidence_confidence"] = min((row["evidence_confidence"], second["evidence_confidence"]), key=CONFIDENCES.index)
    refs = set(row.get("evidence_refs", []))
    if row["right_type"] in REGISTERED:
        authoritative = official_refs(task, evidence, plan, candidate, row["jurisdiction"], row["right_type"]) if candidate else set()
    else:
        authoritative = _provenance_refs(evidence, plan, row)
    supported = bool(refs & authoritative)
    if row["right_type"] in REGISTERED and row["risk"] in {"中", "高"}:
        if row.get("right_state") != "active" or not set(row.get("right_state_evidence_refs", [])) & authoritative:
            gaps.append("CURRENT_EFFECTIVE_RIGHT_NOT_ESTABLISHED")
        if row.get("right_state") == "pending":
            result["future_application_signal"] = row["risk"]
            result["risk"] = "无法判断"
            gaps.append("PENDING_APPLICATION_SEPARATE_FROM_CURRENT_RISK")
    if candidate and not materiality_annotation_complete(candidate):
        gaps.append("CANDIDATE_MATERIALITY_UNREVIEWED")
    # Retain exact identity checks, but an unrelated country's gap cannot erase
    # an independently supported local finding.
    from finalize_assessment import _identity_mismatch_scopes, _identity_mismatch_resolved_after
    for mismatch in _identity_mismatch_scopes(candidate, evidence):
        if mismatch.get("jurisdiction") != row["jurisdiction"] or mismatch.get("right_type") != row["right_type"]:
            continue
        requirement = next((req for req in task.get("coverage_requirements", []) if req.get("requirement_id") == mismatch.get("requirement_id")), {})
        if mismatch.get("checked_at") is None or not _identity_mismatch_resolved_after(candidate, evidence, requirement.get("routes", []), jurisdiction=row["jurisdiction"], right_type=row["right_type"], requirement_ids={str(mismatch.get("requirement_id") or "")}, mismatch_at=mismatch.get("checked_at"), search_plan=plan):
            gaps.append("CANDIDATE_IDENTITY_MISMATCH")
    products = _product_evidence(task, evidence)
    comparison_gaps = []
    if candidate:
        for value in (row, second) if second else (row,):
            comparison_gaps.extend(_comparison_gaps(value))
            comparison_gaps.extend(_typed_comparison_gaps(value, task, evidence, plan, candidate, authoritative, products))
    if candidate:
        gaps += comparison_gaps
        if not supported:
            gaps.append("OFFICIAL_VERIFICATION_REQUIRED" if row["right_type"] in REGISTERED else "SOURCE_PROVENANCE_REQUIRED")
    if row["risk"] == "高" and any(item["result"] == "excludes_risk" for item in row.get("comparison", {}).get("criteria", [])):
        gaps.append("HIGH_RISK_CONTRADICTS_EXCLUSION")
    if row["risk"] == "低":
        if candidate and not any(item["result"] == "excludes_risk" for item in row.get("comparison", {}).get("criteria", [])):
            gaps.append("CANDIDATE_EXCLUSION_NOT_SUPPORTED")
        if coverage["status"] != "满足已定义要求":
            gaps.append("LOW_RISK_COVERAGE_INCOMPLETE")
        if gaps:
            result["risk"] = "无法判断"
    facts = row.get("confidence_basis", {})
    if second:
        second_facts = second.get("confidence_basis", {})
    else:
        second_facts = {}
    complete_facts = all(facts.get(key, {}).get("satisfied") is True and second_facts.get(key, {}).get("satisfied") is True for key in CONFIDENCE_FACTS)
    product_bound = all(bool(set(basis.get("product", {}).get("evidence_refs", [])) & set(products)) for basis in (facts, second_facts))
    if candidate:
        comparison_sources = set(_claim_documents(evidence, plan, candidate, authoritative)) if row["right_type"] in {"patent", "utility_model"} else authoritative
        for basis in (facts, second_facts):
            if any(not set(basis.get(key, {}).get("evidence_refs", [])) & authoritative for key in ("identity", "scope", "status")):
                complete_facts = False
            comparison_refs = set(basis.get("comparison", {}).get("evidence_refs", []))
            if not comparison_refs & comparison_sources or not comparison_refs & set(products):
                complete_facts = False
    if not product_bound:
        complete_facts = False
        gaps.append("ACTUAL_PRODUCT_EVIDENCE_REQUIRED")
    confidence_gaps = ["CONFIDENCE_BASIS_INCOMPLETE"] if not complete_facts else []
    if result["evidence_confidence"] == "高" and (not complete_facts or comparison_gaps or (candidate and not supported)):
        result["evidence_confidence"] = "中"
    if not facts.get("identity", {}).get("satisfied") or not facts.get("product", {}).get("satisfied") or any("CONFLICT" in gap or "IDENTITY_MISMATCH" in gap for gap in gaps):
        result["evidence_confidence"] = "低"
    if not candidate and row["risk"] == "低" and not complete_facts:
        gaps.append("NEGATIVE_CLEARANCE_FACTS_INCOMPLETE")
        result["risk"] = "无法判断"
    result["publication_gaps"] = sorted(set(gaps))
    result["confidence_gaps"] = confidence_gaps
    result["authoritative_evidence_refs"] = sorted(authoritative & refs)
    if result["risk"] == "无法判断":
        result["evidence_confidence"] = "低"
    if not gaps and result["risk"] != "无法判断":
        result["publication"] = "confirmed_scoped"
    return result


def compute_assessment(task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any], plan: dict[str, Any], ledger: dict[str, Any], first: dict[str, Any], second: dict[str, Any] | None, *, generated_at: str | None = None) -> dict[str, Any]:
    assert_active_free_policy(task)
    from common import canonical_coverage_requirements_match
    if not canonical_coverage_requirements_match(task):
        raise ValueError("COVERAGE_REQUIREMENTS_INVALID")
    if task.get("schema_version") != SCHEMA or plan.get("schema_version") != SCHEMA or plan.get("task_id") != task.get("task_id") or not plan_free_policy_matches_task(task, plan):
        raise ValueError("SEARCH_PLAN_IDENTITY_MISMATCH")
    assert_default_discovery_plan_contract(task, plan)
    from finalize_assessment import verification_plan_binding_errors
    binding_errors = verification_plan_binding_errors(task, evidence, candidates, plan)
    if binding_errors:
        raise ValueError("OFFICIAL_VERIFICATION_PLAN_BINDING_INVALID: " + "; ".join(binding_errors))
    ledger_errors = materiality_ledger_errors(ledger, task["task_id"], candidates)
    # Unreviewed candidates remain actionable incomplete work; corrupt/stale
    # ledger entries are invalid input, not a way to clear review obligations.
    fatal_ledger_errors = [error for error in ledger_errors if "candidate has no materiality ledger decision:" not in error]
    if fatal_ledger_errors:
        raise ValueError("INVALID_MATERIALITY_LEDGER: " + "; ".join(fatal_ledger_errors))
    coverage = coverage_by_scope(task, evidence, candidates, plan)
    scope_map = {(row["jurisdiction"], row["right_type"]): row for row in coverage}
    digest = review_digest(evidence, candidates, ledger, plan, task)
    validate_review(first, digest, evidence, candidates, set(scope_map))
    if second is not None:
        validate_review(second, digest, evidence, candidates, set(scope_map))
        if first["reviewer"] == second["reviewer"] or first["review_context"]["session_id"] == second["review_context"]["session_id"]:
            raise ValueError("SECOND_REVIEW_NOT_INDEPENDENT")
    left = {scope_key(row): row for row in first["assessments"]}
    right = {scope_key(row): row for row in (second or {}).get("assessments", [])}
    rows = []
    for key in sorted(set(left) | set(right)):
        row = left.get(key) or right[key]
        rows.append(evaluate_row(row, right.get(key) if key in left else None, task, evidence, candidates, plan, scope_map[key[:2]]))
    # Each covered right needs a scope statement, and every candidate needs a
    # scoped disposition; omission is never a negative-clearance shortcut.
    for scope in coverage:
        scope_rows = [row for row in rows if scope_key(row)[:2] == (scope["jurisdiction"], scope["right_type"])]
        if not scope_rows:
            scope["gaps"].append("SCOPE_ASSESSMENT_MISSING")
        relevant = [item for _, item in iter_candidates(candidates) if candidate_applies(item, scope["jurisdiction"], scope["right_type"])]
        for item in relevant:
            if not any(row.get("candidate_id") == item.get("candidate_id") for row in scope_rows):
                scope["gaps"].append("CANDIDATE_ASSESSMENT_MISSING:" + str(item.get("candidate_id")))
        if any(gap.startswith("CANDIDATE_ASSESSMENT_MISSING:") for gap in scope["gaps"]):
            for row in scope_rows:
                if not row.get("candidate_id") and row["risk"] == "低":
                    row.update(risk="无法判断", publication="discovery_only")
                    row["publication_gaps"].append("SCOPE_CANDIDATES_NOT_ALL_ASSESSED")
        if any(row["publication"] != "confirmed_scoped" for row in scope_rows):
            scope["gaps"].append("SCOPED_ASSESSMENT_UNRESOLVED")
        scope["gaps"] = sorted(set(scope["gaps"]))
        if scope["gaps"] and scope["status"] == "满足已定义要求":
            scope["status"] = "部分完成"
    confirmed = [row for row in rows if row["publication"] == "confirmed_scoped"]
    all_complete = bool(coverage) and all(not scope["gaps"] for scope in coverage) and not ledger_errors
    overall_risk = max((row["risk"] for row in confirmed), key=RISKS.index, default="无法判断") if all_complete else ""
    known_risk = max((row["risk"] for row in confirmed), key=RISKS.index, default="无法判断")
    drivers = [row for row in confirmed if row["risk"] == known_risk]
    overall = {"risk": overall_risk, "confidence": min((row["evidence_confidence"] for row in drivers), key=CONFIDENCES.index, default="低"),
               "provisional": not all_complete, "known_scoped_risk": known_risk,
               "discovery_signal": max((row["risk"] for row in rows if row["publication"] != "confirmed_scoped"), key=RISKS.index, default="无法判断"),
               "reasons": ["按国家和具体权利分别发布；已确认发现不会覆盖尚未完成的国家或权利。", "检索覆盖不足不代表中风险，也不支持全范围低风险。"]}
    supplemental = {}
    for field in ("future_applications", "enforcement_signals"):
        supplemental[field] = list({sha256_json(row): row for review in (first, second or {}) for row in review.get(field, [])}.values())
    supplemental["future_applications"].extend({"jurisdiction": row["jurisdiction"], "right_type": row["right_type"],
        "candidate_id": row.get("candidate_id"), "title": "待审申请观察", "reasoning": row["reasoning"],
        "evidence_refs": row.get("evidence_refs", []), "future_signal": row["future_application_signal"]}
        for row in rows if row.get("future_application_signal"))
    return {"schema_version": SCHEMA, "assessment_contract": "SCOPED-IPR/1.0", "task_id": task["task_id"], "generated_at": generated_at or now_iso(),
            "status": "completed" if all_complete else "incomplete", "overall": overall, "assessments": rows, "coverage": {"scopes": coverage},
            "review": {"required": True, "human_review_required": False, "evidence_digest": digest,
                       "first_reviewer": first["reviewer"], "second_reviewer": (second or {}).get("reviewer", ""),
                       "input_reviews": {"first": deepcopy(first), "second": deepcopy(second)}},
            "recommended_actions": sorted({finding["recommended_action"] for row in rows for finding in row.get("findings", [])}),
            "paid_recommendations": [], **supplemental}


def finalize(task_dir: Path, task: dict[str, Any], first_path: Path, second_path: Path | None) -> dict[str, Any]:
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    candidates = ensure_object(load_json(task_dir / "normalized-candidates.json"), "normalized-candidates.json")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    ledger = load_materiality_ledger(task_dir, task["task_id"])
    first = ensure_object(load_json(first_path), "first review")
    second = ensure_object(load_json(second_path), "second review") if second_path else None
    assessment = compute_assessment(task, evidence, candidates, plan, ledger, first, second)
    add_history(task, assessment["status"], "2.4 scoped risk/confidence/coverage finalized; Agent review only")
    task.setdefault("outputs", {})["assessment_json"] = str(task_dir / "assessment.json")
    atomic_write_json(task_dir / "assessment.json", assessment)
    atomic_write_json(task_dir / "task.json", task)
    return assessment

#!/usr/bin/env python3
"""Evidence-bound five-level estimates, without changing historical policies.

This is a validator and deterministic aggregator of reasoned review judgments,
not a similarity score or an automatic legal conclusion. Strict recall-integrity
tasks retain unsupported scopes as pending and incomplete; historical policies
keep their original grading behavior. Corrupt review contracts are input errors.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from common import (MODULE_IDS, RIGHT_TYPES, SOURCE_STATUSES, add_history,
                    assert_active_free_policy, assert_default_discovery_plan_contract,
                    atomic_write_json, canonical_coverage_requirements_match,
                    ensure_object, load_json, now_iso, parse_iso,
                    plan_free_policy_matches_task, recall_integrity_enabled,
                    sha256_file, sha256_json)
from annotate_materiality import (candidate_index, iter_candidates,
                                 load_materiality_ledger, materiality_ledger_errors)
from assessment_v24 import (candidate_applies, coverage_by_scope, evidence_index,
                           review_digest as legacy_review_digest, scope_key, _conflicts,
                           NON_PRODUCTION, RESULTS, CONFIDENCE_FACTS)

POLICY = "evidence-estimate-v1"
SCHEMA = "2.4-free"
CONTRACT = "EVIDENCE-ESTIMATE/1.0"
RISKS = ("极低", "低", "中", "高", "极高")
CONFIDENCES = ("低", "中", "高")
MODULE_RIGHTS = {
    "appearance_patent": {"design", "unregistered_design"},
    "utility_patent": {"patent", "utility_model"},
    "pending_application": {"patent", "utility_model", "design"},
    "word_mark": {"trademark_word"},
    "figurative_trade_dress": {"trademark_figurative", "trade_dress"},
    "copyright_ip": {"copyright"}, "enforcement": {"enforcement"},
}


def _decision_enabled(task):
    return task.get("decision_workflow_revision") == "scenario-triage-v1"


def _correction_enabled(task):
    if "workflow_correction_revision" not in task:
        return False
    from decision_workflow import correction_enabled
    return correction_enabled(task)


def review_digest(evidence, candidates, ledger, plan, task, supplement=None) -> str:
    """Bind independent judgments to the exact policy and all original inputs."""
    payload = {"assessment_policy": POLICY,
                        "base_evidence_digest": legacy_review_digest(evidence, candidates, ledger, plan, task),
                        "supplement": supplement}
    if "assessment_scope_exclusions" in task:
        payload["assessment_scope_exclusions"] = task["assessment_scope_exclusions"]
    if "screening_revision" in task:
        payload["screening_revision"] = task["screening_revision"]
    if "recall_planning_revision" in task:
        payload["recall_planning_revision"] = task["recall_planning_revision"]
        payload["query_terms"] = task.get("query_terms", [])
        payload["discovery_followups"] = task.get("discovery_followups", [])
    if "decision_workflow_revision" in task:
        payload["decision_workflow_revision"] = task["decision_workflow_revision"]
        payload["assessment_scenarios"] = task.get("assessment_scenarios")
        payload["primary_scenario_id"] = task.get("primary_scenario_id")
        if "historical_evidence_root" in task:
            payload["historical_evidence_root"] = task["historical_evidence_root"]
    if "specialty_workflow_revision" in task:
        payload["specialty_workflow_revision"] = task["specialty_workflow_revision"]
    if "workflow_correction_revision" in task:
        _correction_enabled(task)
        payload["workflow_correction_revision"] = task["workflow_correction_revision"]
    if "completion_policy_revision" in task:
        from necessary_completion import enabled
        enabled(task)
        payload["completion_policy_revision"] = task["completion_policy_revision"]
    return sha256_json(payload)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _refs(value: Any, known: set[str], *, required: bool = True) -> bool:
    return (isinstance(value, list) and (bool(value) or not required)
            and all(isinstance(ref, str) and ref in known for ref in value))


def _resolve(path: str, root: Path | None) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        if root is None:
            raise ValueError("EVIDENCE_ROOT_REQUIRED: " + path)
        value = root / value
    return value.resolve()


def _verify_file(path: Path, digest: Any, size: Any = None) -> None:
    if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not path.is_file() or (size is not None and (type(size) is not int or size < 0))):
        raise ValueError("EVIDENCE_ARTIFACT_INVALID: " + str(path))
    if sha256_file(path) != digest or (size is not None and path.stat().st_size != size):
        raise ValueError("EVIDENCE_ARTIFACT_HASH_OR_SIZE_MISMATCH: " + str(path))


def validate_supplement(supplement, evidence_root=None, *, task=None, evidence=None) -> dict[str, dict[str, Any]]:
    """A retained-file index is never converted into an accepted adapter receipt."""
    if supplement is None:
        return {}
    if (not isinstance(supplement, dict) or not _text(supplement.get("schema"))
            or not isinstance(supplement.get("evidence"), list)
            or not isinstance(supplement.get("coverage_notes", []), list)):
        raise ValueError("SUPPLEMENT_CONTRACT_INVALID")
    if evidence_root is None:
        raise ValueError("SUPPLEMENT_EVIDENCE_ROOT_REQUIRED")
    root = Path(evidence_root).resolve()
    result = {}
    for item in supplement["evidence"]:
        if (not isinstance(item, dict) or any(not _text(item.get(key)) for key in
                ("evidence_id", "path", "sha256", "kind", "checked_at"))
                or isinstance(item.get("bytes"), bool) or not isinstance(item.get("bytes"), int)
                or item["bytes"] < 0):
            raise ValueError("SUPPLEMENT_EVIDENCE_INVALID")
        if item["evidence_id"] in result:
            raise ValueError("DUPLICATE_EVIDENCE_ID: " + item["evidence_id"])
        path = _resolve(item["path"], root)
        if not path.is_relative_to(root):
            raise ValueError("SUPPLEMENT_PATH_OUTSIDE_EVIDENCE_ROOT: " + str(path))
        _verify_file(path, item["sha256"], item["bytes"])
        if not _text(item.get("source_url")) and not _text(item.get("source_document")):
            raise ValueError("SUPPLEMENT_SOURCE_URL_OR_DOCUMENT_REQUIRED")
        if item.get("source_url"):
            parsed = urlparse(item["source_url"])
            if parsed.scheme not in {"https", "http"} or not parsed.netloc:
                raise ValueError("SUPPLEMENT_SOURCE_URL_INVALID")
        if item.get("source_document"):
            document = _resolve(item["source_document"], root)
            if not document.is_file() or not document.is_relative_to(root):
                raise ValueError("SUPPLEMENT_SOURCE_DOCUMENT_INVALID")
        try:
            if parse_iso(item["checked_at"]).tzinfo is None:
                raise ValueError("timezone missing")
        except (ValueError, TypeError) as exc:
            raise ValueError("SUPPLEMENT_CHECKED_AT_INVALID") from exc
        result[item["evidence_id"]] = deepcopy(item)
    if any(not _text(note) for note in supplement.get("coverage_notes", [])):
        raise ValueError("SUPPLEMENT_COVERAGE_NOTES_INVALID")
    if task is not None and _correction_enabled(task):
        from pdf_page_evidence import validate_page_binding
        parents = {**evidence_index(evidence or {}), **result}
        page_cache = {}
        for item in result.values():
            if "page_verification" not in item:
                # Original unlocated page bytes may be retained alongside a
                # later verified alias. They cannot enter a v2 visual board;
                # the selector records the missing locator, not this loader.
                continue
            if not item.get("source_document") or Path(item["source_document"]).suffix.lower() != ".pdf":
                continue
            if ("page_number" not in item and Path(item["path"]).suffix.lower() not in
                    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp", ".svg"}):
                continue  # A retained PDF/text extract is not a rendered page image.
            matches = [parent for parent in parents.values()
                if parent.get("path") and _resolve(parent["path"], root) == _resolve(item["source_document"], root)
                and parent.get("sha256") == item.get("source_document_sha256")]
            if not matches:
                continue  # The report records an unbound-parent visual gap.
            try:
                validate_page_binding(item, matches[0], root, cache=page_cache)
            except ValueError as exc:
                if str(exc) != "PDF_PAGE_PROVENANCE_MISSING_OR_STALE":
                    raise
                # Old retained page bytes remain usable as documentary evidence;
                # missing verified locators exclude the image from a v2 board.
    return result


def _verify_declared_artifacts(value: Any, root: Path | None, checked: set, *, image_context=False) -> None:
    if isinstance(value, dict):
        bindings = []
        for name, raw in value.items():
            if isinstance(raw, str) and (name == "path" or name.endswith("_path")):
                stem = name[:-5] if name.endswith("_path") else ""
                hashes = ([stem + "_sha256", stem + "_hash"] if stem else []) + ["sha256"]
                sizes = ([stem + suffix for suffix in ("_bytes", "_byte_count", "_size_bytes")] if stem else []) + ["bytes", "byte_count", "size_bytes", "file_bytes"]
                digest = next((value[key] for key in hashes if key in value), None)
                size = next((value[key] for key in sizes if key in value), None)
                image_path = Path(raw).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
                if digest is not None or image_path or image_context or name.endswith(("image_path", "screenshot_path")):
                    bindings.append((raw, digest, size))
        for name in ("screenshots", "screenshot_paths"):
            paths = value.get(name)
            hashes, sizes = value.get("screenshot_hashes", {}), value.get("screenshot_bytes", {})
            if isinstance(paths, (dict, list)):
                for key, raw in (paths.items() if isinstance(paths, dict) else enumerate(paths)):
                    if not isinstance(raw, str):
                        continue  # Structured entries are visited recursively below.
                    def lookup(values):
                        if isinstance(values, dict):
                            return values.get(key, values.get(str(key), values.get(raw)))
                        return values[key] if isinstance(values, list) and isinstance(key, int) and key < len(values) else None
                    bindings.append((raw, lookup(hashes), lookup(sizes)))
        for raw, digest, size in bindings:
            path = _resolve(raw, root)
            key = (str(path), str(digest), str(size))
            if key not in checked:
                _verify_file(path, digest, size)
                checked.add(key)
        for name, item in value.items():
            _verify_declared_artifacts(item, root, checked, image_context=image_context or name in {"images", "screenshots", "screenshot_paths"})
    elif isinstance(value, list):
        for item in value:
            _verify_declared_artifacts(item, root, checked, image_context=image_context)


def task_artifact_root(task, evidence_root=None, task_dir=None):
    """Task-relative declarations are distinct from the supplement boundary.

    In-memory callers without source-directory context and legacy tasks retain
    their existing resolution. Never infer a directory from a file's basename.
    """
    root = task_dir if _correction_enabled(task) and task_dir is not None else evidence_root
    return Path(root).resolve() if root else None


def validate_inputs(task, evidence, candidates, plan, ledger, *, evidence_root=None, supplement=None, task_dir=None) -> list[str]:
    assert_active_free_policy(task)
    if task.get("assessment_policy") != POLICY:
        raise ValueError("RATING_POLICY_NOT_SELECTED")
    if _correction_enabled(task) and plan.get("workflow_correction_revision") != task["workflow_correction_revision"]:
        raise ValueError("SEARCH_PLAN_WORKFLOW_CORRECTION_REVISION_MISMATCH")
    if task.get("decision_workflow_revision") not in (None, "scenario-triage-v1"):
        raise ValueError("UNSUPPORTED_DECISION_WORKFLOW_REVISION")
    if _decision_enabled(task):
        from decision_workflow import validate_decision_workflow
        scenario_errors = validate_decision_workflow(task)
        if scenario_errors:
            raise ValueError("DECISION_WORKFLOW_INVALID: " + "; ".join(scenario_errors))
        if plan.get("decision_workflow_revision") != task["decision_workflow_revision"]:
            raise ValueError("SEARCH_PLAN_DECISION_REVISION_MISMATCH")
    if not canonical_coverage_requirements_match(task):
        raise ValueError("COVERAGE_REQUIREMENTS_INVALID")
    if (task.get("schema_version") != SCHEMA or plan.get("schema_version") != SCHEMA
            or plan.get("task_id") != task.get("task_id")
            or not plan_free_policy_matches_task(task, plan)
            or plan.get("assessment_policy", POLICY) != POLICY):
        raise ValueError("SEARCH_PLAN_IDENTITY_MISMATCH")
    for label, document in (("EVIDENCE", evidence), ("CANDIDATES", candidates)):
        if document.get("task_id") != task["task_id"] or document.get("schema_version") != SCHEMA:
            raise ValueError(label + "_IDENTITY_MISMATCH")
    assert_default_discovery_plan_contract(task, plan)
    from finalize_assessment import verification_plan_binding_errors
    errors = verification_plan_binding_errors(task, evidence, candidates, plan)
    if errors:
        raise ValueError("OFFICIAL_VERIFICATION_PLAN_BINDING_INVALID: " + "; ".join(errors))
    ledger_errors = materiality_ledger_errors(ledger, task["task_id"], candidates,
        **({"task": task, "evidence": evidence, "supplement": supplement} if _decision_enabled(task) else {}))
    fatal = [item for item in ledger_errors if "candidate has no materiality ledger decision:" not in item]
    if fatal:
        raise ValueError("INVALID_MATERIALITY_LEDGER: " + "; ".join(fatal))
    root = task_artifact_root(task, evidence_root, task_dir)
    if recall_integrity_enabled(task) and "candidate_leads" in evidence.get("collections", {}):
        if root is None:
            raise ValueError("CANDIDATE_LEAD_EVIDENCE_ROOT_REQUIRED")
        from record_candidate_lead import validated_candidate_lead_entries
        validated_candidate_lead_entries(task, evidence, root)
    checked = set()
    for value in (evidence, candidates):
        _verify_declared_artifacts(value, root, checked)
    _verify_declared_artifacts(task.get("images", []), root, checked, image_context=True)
    seen = set()
    for run in evidence.get("source_runs", []):
        if (not isinstance(run, dict) or not _text(run.get("run_id"))
                or run["run_id"] in seen or run.get("status") not in SOURCE_STATUSES):
            raise ValueError("SOURCE_RUN_IDENTITY_OR_STATUS_INVALID")
        seen.add(run["run_id"])
        if run["status"] == "no_result" and run.get("error_code"):
            raise ValueError("ZERO_RESULT_CONTRADICTION")
        for path in run.get("raw_paths", []):
            _verify_file(_resolve(str(path), root), run.get("payload_digest"))
    exclusions = task.get("assessment_scope_exclusions", [])
    if not isinstance(exclusions, list):
        raise ValueError("TASK_SCOPE_EXCLUSIONS_INVALID")
    seen_exclusions = set()
    for item in exclusions:
        if (not isinstance(item, dict) or scope_key(item)[0] not in task.get("target_jurisdictions", [])
                or scope_key(item)[1] not in RIGHT_TYPES or not _text(item.get("reasoning"))):
            raise ValueError("TASK_SCOPE_EXCLUSIONS_INVALID")
        _validate_assessment_object(item)
        if _decision_enabled(task):
            _validate_scenario_binding(item, task)
        if _review_scope_key(item, task) in seen_exclusions:
            raise ValueError("TASK_SCOPE_EXCLUSIONS_INVALID")
        seen_exclusions.add(_review_scope_key(item, task))
    evidence_index(evidence)  # Duplicate IDs must not silently replace evidence.
    return ledger_errors


def _validate_nested_refs(value, known):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence_refs" or key.endswith("_evidence_refs"):
                if not _refs(item, known, required=False):
                    raise ValueError("UNKNOWN_OR_INVALID_EVIDENCE_REFS: " + key)
            else:
                _validate_nested_refs(item, known)
    elif isinstance(value, list):
        for item in value:
            _validate_nested_refs(item, known)


def _validate_comparison(row, known):
    """Retain original comparison/reference integrity when richer rows provide it."""
    if "comparison" not in row:
        return
    comparison = row["comparison"]
    if not isinstance(comparison, dict):
        raise ValueError("COMPARISON_CONTRACT_INVALID")
    seen = set()
    criteria = comparison.get("criteria", [])
    if not isinstance(criteria, list):
        raise ValueError("COMPARISON_CRITERIA_INVALID")
    for item in criteria:
        if (not isinstance(item, dict) or not _text(item.get("criterion"))
                or item["criterion"] in seen or item.get("result") not in RESULTS
                or not _text(item.get("reasoning"))
                or not _refs(item.get("evidence_refs", []), known, required=item.get("result") != "unknown")):
            raise ValueError("COMPARISON_CRITERION_EVIDENCE_INVALID")
        seen.add(item["criterion"])
    claims = comparison.get("claims", [])
    if not isinstance(claims, list):
        raise ValueError("COMPARISON_CLAIMS_INVALID")
    for claim in claims:
        if (not isinstance(claim, dict) or not claim.get("claim_id")
                or not _refs(claim.get("claim_evidence_refs"), known)
                or not isinstance(claim.get("elements"), list)):
            raise ValueError("CLAIM_ORIGINAL_EVIDENCE_REQUIRED")
        for element in claim["elements"]:
            if (not isinstance(element, dict) or element.get("result") not in RESULTS
                    or not _refs(element.get("evidence_refs", []), known, required=element.get("result") != "unknown")):
                raise ValueError("CLAIM_ELEMENT_EVIDENCE_REQUIRED")
    visual = comparison.get("visual_coverage")
    if visual is not None:
        if not isinstance(visual, dict) or not isinstance(visual.get("required_views"), list):
            raise ValueError("VISUAL_COVERAGE_INVALID")
        for side in ("product_views", "right_views"):
            if not isinstance(visual.get(side), list) or any(not isinstance(view, dict)
                    or not _text(view.get("view")) or not _refs(view.get("evidence_refs"), known)
                    for view in visual[side]):
                raise ValueError("VISUAL_VIEW_EVIDENCE_REQUIRED")


def _assessment_object(row):
    return row.get("assessment_object", "own_brand" if row.get("scope_exclusion_basis") == "unknown_own_brand" else "product")


def _review_scope_key(row, task=None):
    """Brand names not yet supplied are a distinct object, not product clearance."""
    key = (*scope_key(row), _assessment_object(row))
    return (*key, row.get("scenario_id", "")) if _decision_enabled(task or {}) else key


def _validate_scenario_binding(row, task):
    from decision_workflow import scenario_index, scenario_sha256, scenario_right_types
    scenarios = scenario_index(task)
    scenario = scenarios.get(row.get("scenario_id"))
    if not scenario or row.get("scenario_sha256") != scenario_sha256(scenario):
        raise ValueError("ASSESSMENT_SCENARIO_BINDING_INVALID")
    if row.get("right_type") is not None and row["right_type"] not in scenario_right_types(scenario):
        raise ValueError("ASSESSMENT_RIGHT_OUTSIDE_SCENARIO")


def _validate_implementation_claims(row):
    """Keep each embodiment and claim's element reasoning self-contained."""
    comparison = row.get("comparison", {})
    claims = comparison.get("claims", [])
    if not claims:
        return
    implementations = comparison.get("implementations")
    if not isinstance(implementations, list) or not implementations:
        raise ValueError("CLAIM_IMPLEMENTATIONS_REQUIRED")
    identifiers = set()
    for item in implementations:
        if (not isinstance(item, dict) or any(not _text(item.get(key)) for key in
                ("implementation_id", "title", "description"))
                or item["implementation_id"] in identifiers
                or not item.get("product_evidence_refs")):
            raise ValueError("CLAIM_IMPLEMENTATION_INVALID")
        identifiers.add(item["implementation_id"])
    seen = set()
    for claim in claims:
        key = (claim.get("implementation_id"), str(claim.get("claim_id")))
        if (key[0] not in identifiers or key in seen
                or claim.get("claim_type") not in {"independent", "dependent"}
                or claim.get("conclusion") not in {"supports_risk", "excludes_risk", "unknown"}
                or not claim.get("elements")):
            raise ValueError("CLAIM_IMPLEMENTATION_SCOPE_INVALID")
        seen.add(key)
        for element in claim["elements"]:
            if (element.get("implementation_id", key[0]) != key[0]
                    or str(element.get("claim_id", key[1])) != key[1]):
                raise ValueError("CLAIM_ELEMENT_CROSS_SCOPE_MIXING")
            if (any(not _text(element.get(field)) for field in ("claim_element", "claim_quote", "product_feature"))
                    or not element.get("product_evidence_refs")):
                raise ValueError("CLAIM_ELEMENT_ORIGINAL_AND_PRODUCT_COMPARISON_REQUIRED")
        if (claim["conclusion"] == "excludes_risk"
                and not any(element.get("result") == "excludes_risk"
                            and element.get("evidence_refs") for element in claim["elements"])):
            raise ValueError("CLAIM_EXCLUSION_REQUIRES_OWN_MISSING_ELEMENT")


def _validate_assessment_object(row):
    if (_assessment_object(row) not in ("product", "own_brand")
            or (_assessment_object(row) == "own_brand" and scope_key(row)[1] not in {"trademark_word", "trademark_figurative"})
            or (row.get("scope_exclusion_basis") == "unknown_own_brand" and _assessment_object(row) != "own_brand")):
        raise ValueError("ASSESSMENT_OBJECT_INVALID")


def _scope_excluded(row, task):
    key = scope_key(row)
    if any(_review_scope_key(item, task) == _review_scope_key(row, task) for item in task.get("assessment_scope_exclusions", [])):
        return True
    product = task.get("product", {})
    supplied_own_brand = any(product.get(field) for field in ("own_brand", "own_brand_name", "own_brand_logo", "own_logo"))
    supplied_own_brand = supplied_own_brand or (product.get("brand_role") == "own" and any(product.get(field) for field in ("brand", "logo")))
    return (not key[2] and key[1] in {"trademark_word", "trademark_figurative"}
            and row.get("scope_exclusion_basis") == "unknown_own_brand"
            and not supplied_own_brand)


def _validate_applicability(row, known, candidates):
    key = scope_key(row)
    exception = row.get("applicability_exception")
    if exception is not None and (not isinstance(exception, dict)
            or exception.get("kind") not in {"territorial_effect", "current_enforceability", "territorial_and_current_effect"}
            or not _text(exception.get("reasoning")) or not _refs(exception.get("evidence_refs"), known)):
        raise ValueError("APPLICABILITY_EXCEPTION_EVIDENCE_REQUIRED")
    if row.get("out_of_scope") is True:
        return
    current = not (row.get("future_signal") is True or row.get("signal_only") is True)
    if (current and key[1] in {"patent", "utility_model", "design", "trademark_word", "trademark_figurative"}
            and row.get("right_state") in {"pending", "expired", "abandoned"}
            and row.get("risk") in {"中", "高", "极高"}
            and (exception or {}).get("kind") not in {"current_enforceability", "territorial_and_current_effect"}):
        raise ValueError("CURRENT_RISK_CONTRADICTS_KNOWN_RIGHT_STATE")
    if key[2]:
        item = candidates[key[2]][1]
        from finalize_assessment import _candidate_effect_jurisdictions, _candidate_jurisdiction
        effects = _candidate_effect_jurisdictions(item, key[1])
        direct_jurisdiction = _candidate_jurisdiction(item)
        needs_local_effect = (key[1] in {"patent", "utility_model"} and direct_jurisdiction
                              and direct_jurisdiction != key[0])
        if (effects and (not candidate_applies(item, key[0], key[1]) or needs_local_effect)
                and row.get("risk") in {"中", "高", "极高"}
                and (exception or {}).get("kind") not in {"territorial_effect", "territorial_and_current_effect"}):
            raise ValueError("CANDIDATE_TERRITORIAL_EFFECT_CONFLICT")


def _future_labeled(row):
    return (row.get("right_type") != "enforcement" and
            (row.get("future_signal") is True or row.get("signal_only") is True
             or row.get("module_id") == "pending_application"))


def _future_review_qualified(row, known, candidates, task, registry=None):
    """Validate future-signal identity; only evidenced applications close review work.

    An unknown status may be reported as a signal without acquiring completion
    credit. A published grant/registration cannot become an ungranted right by
    moving its row to a different review array.
    """
    if not _correction_enabled(task):
        return True
    _validate_scenario_binding(row, task)
    jurisdiction, right, cid = scope_key(row)
    if (not cid or cid not in candidates or jurisdiction not in task.get("target_jurisdictions", [])
            or right not in {"patent", "utility_model", "design", "trademark_word", "trademark_figurative"}
            or candidates[cid][1].get("right_type") != right):
        raise ValueError("FUTURE_SIGNAL_CANDIDATE_SCOPE_INVALID")
    candidate = candidates[cid][1]
    if not _refs(row.get("evidence_refs"), known):
        raise ValueError("FUTURE_SIGNAL_EVIDENCE_REQUIRED")
    def number(value):
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    publication = number(candidate.get("publication_number"))
    granted_publication = bool(re.search(r"(?:B[0-9]?|S[0-9]?)$", publication))
    if (candidate.get("right_state") == "active" or row.get("right_state") == "active"
            or candidate.get("registration_number") or granted_publication):
        raise ValueError("FUTURE_SIGNAL_CURRENT_OR_GRANTED_RIGHT_CONFLICT")
    basis = row.get("future_signal_basis")
    if basis is None:
        return False
    if (not isinstance(basis, dict) or basis.get("status") not in {"ungranted", "pending"}
            or not _text(basis.get("application_identity")) or not _text(basis.get("reasoning"))
            or not _refs(basis.get("evidence_refs"), known)
            or not set(basis["evidence_refs"]) <= set(row["evidence_refs"])):
        raise ValueError("FUTURE_SIGNAL_BASIS_INVALID")
    identities = {number(candidate.get(field)) for field in
                  ("application_number", "serial_number", "publication_number") if candidate.get(field)}
    if number(basis["application_identity"]) not in identities:
        raise ValueError("FUTURE_SIGNAL_APPLICATION_IDENTITY_MISMATCH")
    if candidate.get("right_state") in {"expired", "abandoned"} or row.get("right_state") in {"expired", "abandoned"}:
        return False
    if str(candidate.get("jurisdiction") or candidate.get("office") or "").upper() != jurisdiction:
        return False  # A foreign application can remain a lead, not a reviewed local right.
    refs = set(candidate.get("evidence_refs", [])) | set(candidate.get("verification_refs", []))
    for ref, entry in (registry or {}).items():
        if (entry.get("candidate_id") == cid and entry.get("jurisdiction") == jurisdiction
                and entry.get("right_type") == right):
            refs.add(ref)
        elif _published_supplement_binds_candidate(entry, candidate):
            refs.add(ref)
    if not set(basis["evidence_refs"]) & refs:
        raise ValueError("FUTURE_SIGNAL_UNBOUND_APPLICATION_EVIDENCE")
    # A publication kind identifies an application document, not its present
    # pendency. Unknown present state keeps a signal without closing review work.
    if row.get("right_state") != "pending":
        return False
    state_refs = row.get("right_state_evidence_refs", []) or basis["evidence_refs"]
    if not _refs(state_refs, known) or not set(state_refs) & refs:
        raise ValueError("FUTURE_SIGNAL_PENDING_STATE_EVIDENCE_REQUIRED")
    return True


def _validate_row(row, known, candidates, jurisdictions, task, registry=None):
    if not isinstance(row, dict):
        raise ValueError("ASSESSMENT_MUST_BE_OBJECT")
    for flag in ("out_of_scope", "future_signal", "signal_only", "aggregation_included"):
        if flag in row and type(row[flag]) is not bool:
            raise ValueError("ASSESSMENT_FLAG_MUST_BE_BOOLEAN: " + flag)
    key = scope_key(row)
    if _decision_enabled(task):
        _validate_scenario_binding(row, task)
    _validate_assessment_object(row)
    if (key[0] not in jurisdictions or key[1] not in RIGHT_TYPES
            or row.get("module_id") not in MODULE_IDS
            or key[1] not in MODULE_RIGHTS[row["module_id"]]):
        raise ValueError("UNSUPPORTED_ASSESSMENT_SCOPE: " + str(key))
    if key[2] and (key[2] not in candidates or candidates[key[2]][1].get("right_type") != key[1]):
        raise ValueError("ASSESSMENT_CANDIDATE_IDENTITY_MISMATCH: " + str(key))
    if _correction_enabled(task) and _future_labeled(row):
        if row.get("risk") is not None:
            raise ValueError("FUTURE_SIGNAL_CANNOT_CARRY_CURRENT_RISK")
        _future_review_qualified(row, known, candidates, task, registry)
    if row.get("out_of_scope") is True:
        if row.get("risk") is not None or not _text(row.get("scope_reasoning")) or not _text(row.get("title")):
            raise ValueError("OUT_OF_SCOPE_CONTRACT_INVALID")
        if not _scope_excluded(row, task):
            raise ValueError("OUT_OF_SCOPE_NOT_BOUND_TO_TASK")
        _validate_nested_refs(row, known)
        return
    pending = (recall_integrity_enabled(task) and row.get("risk") is None
               and row.get("assessment_status") == "pending"
               and _text(row.get("pending_reasoning")))
    reviewed_signal = (_decision_enabled(task) and row.get("risk") is None
                       and row.get("assessment_status") == "assessed"
                       and (row.get("future_signal") is True or row.get("signal_only") is True))
    if (row.get("risk") not in RISKS and not pending and not reviewed_signal) or row.get("evidence_confidence") not in CONFIDENCES:
        raise ValueError("FIVE_LEVEL_RISK_AND_CONFIDENCE_REQUIRED")
    if recall_integrity_enabled(task) and row.get("assessment_status") not in (None, "pending", "assessed"):
        raise ValueError("ASSESSMENT_STATUS_INVALID")
    if row.get("assessment_status") == "pending" and not pending:
        raise ValueError("PENDING_ASSESSMENT_MUST_HAVE_NULL_RISK")
    for field in ("title", "scope", "reasoning", "confidence_reasoning"):
        if not _text(row.get(field)):
            raise ValueError("ASSESSMENT_REASONING_REQUIRED: " + field)
    if not _refs(row.get("evidence_refs"), known, required=not pending):
        raise ValueError("ASSESSMENT_EVIDENCE_REQUIRED")
    for field in ("supporting_evidence", "counter_evidence"):
        items = row.get(field)
        if not isinstance(items, list):
            raise ValueError("EVIDENCE_ARGUMENT_ARRAY_REQUIRED: " + field)
        missing_reason = "no_supporting_evidence_reasoning" if field == "supporting_evidence" else "no_counter_evidence_reasoning"
        if not items and not _text(row.get(missing_reason)):
            raise ValueError("EMPTY_EVIDENCE_ARGUMENT_NEEDS_EXPLANATION: " + field)
        if any(not isinstance(item, dict) or not _text(item.get("reasoning"))
               or not _refs(item.get("evidence_refs"), known) for item in items):
            raise ValueError("EVIDENCE_ARGUMENT_INVALID: " + field)
    if row["risk"] in {"中", "高", "极高"} and (not key[2] or not row["supporting_evidence"]):
        raise ValueError("SPECIFIC_POSITIVE_CONFLICT_REQUIRED")
    if row["risk"] == "极低":
        decisive = row.get("decisive_exclusion", {})
        if (not key[2] or not isinstance(decisive, dict) or not _text(decisive.get("reasoning"))
                or not _refs(decisive.get("evidence_refs"), known)):
            raise ValueError("DECISIVE_SCOPED_EXCLUSION_REQUIRED")
    for field in ("assumptions", "raise_if", "lower_if"):
        if not isinstance(row.get(field), list) or any(not _text(item) for item in row[field]):
            raise ValueError("ASSUMPTIONS_OR_ADJUSTMENT_CONDITIONS_INVALID: " + field)
    if not isinstance(row.get("human_checks"), list):
        raise ValueError("HUMAN_CHECKS_REQUIRED")
    for check in row["human_checks"]:
        if _text(check):
            continue
        if not isinstance(check, dict) or not (
                (_text(check.get("action")) and _text(check.get("reviewer")))
                or all(_text(check.get(field)) for field in ("owner", "question", "evidence_needed"))):
            raise ValueError("HUMAN_CHECK_OWNER_AND_ACTION_REQUIRED")
    if row.get("right_state", "unknown") not in {"active", "pending", "expired", "abandoned", "unknown"}:
        raise ValueError("RIGHT_STATE_INVALID")
    if row.get("right_state", "unknown") != "unknown" and not _refs(row.get("right_state_evidence_refs"), known):
        raise ValueError("RIGHT_STATE_EVIDENCE_REQUIRED")
    _validate_applicability(row, known, candidates)
    basis = row.get("confidence_basis", {})
    if not isinstance(basis, dict):
        raise ValueError("CONFIDENCE_BASIS_INVALID")
    for name, item in basis.items():
        if (name not in CONFIDENCE_FACTS or not isinstance(item, dict) or type(item.get("satisfied")) is not bool
                or not _text(item.get("reasoning"))
                or not _refs(item.get("evidence_refs", []), known, required=item.get("satisfied") is True)):
            raise ValueError("CONFIDENCE_BASIS_FACT_INVALID")
    _validate_comparison(row, known)
    if _decision_enabled(task):
        _validate_implementation_claims(row)
    if "search_comparison" in row:
        comparison = row["search_comparison"]
        if (not isinstance(comparison, dict) or not _text(comparison.get("reasoning"))
                or not _refs(comparison.get("evidence_refs"), known)):
            raise ValueError("SEARCH_COMPARISON_EVIDENCE_REQUIRED")
    _validate_nested_refs(row, known)
    gathered = set()
    def gather(value):
        if isinstance(value, dict):
            for name, item in value.items():
                if name == "evidence_refs" or name.endswith("_evidence_refs"):
                    gathered.update(item)
                else:
                    gather(item)
        elif isinstance(value, list):
            for item in value:
                gather(item)
    gather(row)
    if not gathered.issubset(set(row["evidence_refs"])):
        raise ValueError("ROW_EVIDENCE_REFS_MUST_INCLUDE_ARGUMENT_REFS")


def _validate_review(review, digest, known, candidates, jurisdictions, task, registry=None):
    if not isinstance(review, dict):
        raise ValueError("REVIEW_REQUIRED")
    context = review.get("review_context", {})
    if (not _text(review.get("reviewer")) or not _text(context.get("session_id"))
            or context.get("evidence_digest") != digest or context.get("first_review_visible") is not False):
        raise ValueError("REVIEW_CONTEXT_INVALID")
    if (review.get("coverage_confidence_cap") not in CONFIDENCES
            or not _text(review.get("coverage_confidence_reasoning"))):
        raise ValueError("COVERAGE_CONFIDENCE_CAP_REQUIRED")
    if not isinstance(review.get("assessments"), list):
        raise ValueError("REVIEW_ASSESSMENTS_REQUIRED")
    seen = set()
    for row in review["assessments"]:
        _validate_row(row, known, candidates, jurisdictions, task, registry)
        key = _review_scope_key(row, task)
        if key in seen:
            raise ValueError("DUPLICATE_ASSESSMENT_SCOPE: " + str(key))
        seen.add(key)
    for name in ("future_applications", "enforcement_signals"):
        if not isinstance(review.get(name, []), list):
            raise ValueError("SUPPLEMENTAL_SIGNAL_ARRAY_REQUIRED")
        for row in review.get(name, []):
            if not isinstance(row, dict) or not _text(row.get("reasoning")) or not _refs(row.get("evidence_refs"), known):
                raise ValueError("SUPPLEMENTAL_SIGNAL_EVIDENCE_REQUIRED")
            if _decision_enabled(task):
                _validate_scenario_binding(row, task)
            if name == "future_applications" and _correction_enabled(task):
                _future_review_qualified(row, known, candidates, task, registry)


def _row_conflicts(left, right, task=None):
    result = _conflicts(left, right)
    for field in ("evidence_confidence", "out_of_scope", "module_id", "future_signal", "signal_only", "decisive_exclusion", "applicability_exception", "scope_exclusion_basis"):
        if left.get(field) != right.get(field):
            result.append(field)
    # The conflict list is persisted in assessment.json and then recomputed by
    # the report validator. Set iteration varies between Python processes, so
    # its order must be stable for canonical recomputation to be meaningful.
    for name in sorted(set(left.get("confidence_basis", {})) | set(right.get("confidence_basis", {}))):
        if left.get("confidence_basis", {}).get(name, {}).get("satisfied") != right.get("confidence_basis", {}).get(name, {}).get("satisfied"):
            result.append("confidence_basis:" + name)
    if _decision_enabled(task or {}):
        for field in ("implementations", "claims"):
            if left.get("comparison", {}).get(field) != right.get("comparison", {}).get(field):
                result.append("comparison:" + field)
    return result


def _substantive_refs(refs, registry, runs, *, row=None):
    """A product snapshot or failed request cannot exclude a third-party right.

    Retained supplements remain documentary evidence, not accepted query runs.
    Their explicit scope/record metadata must support the cited candidate.
    """
    result = set()
    for ref in refs:
        entry = registry.get(ref, {})
        run = runs.get(entry.get("source_run_id"), {})
        if entry.get("provider") in {"amazon_browser", "product", "seller_sprite"}:
            continue
        if run and run.get("status") != "success":
            continue
        if entry.get("source_run_id") and not run:
            continue
        if row is not None:
            if str(entry.get("jurisdiction") or run.get("jurisdiction") or "").upper() != row["jurisdiction"]:
                continue
            if (entry.get("right_type") or run.get("right_type")) != row["right_type"]:
                continue
        if run:
            from assessment_v24 import _entry_matches_run
            if not _entry_matches_run(entry, run):
                continue
            # A successful retrieval needs original records or a retained
            # source/provenance document; a bare success status is not enough.
            payload = entry.get("payload", {})
            if not ((isinstance(payload, list) and bool(payload)) or
                    (isinstance(payload, dict) and any(payload.get(key) for key in
                     ("candidates", "records", "results", "artifacts", "official_verification", "record")))):
                continue
        elif entry.get("provider") == "external_document_lead":
            # validate_inputs revalidates the original registration and retained
            # bytes. This admits the document for comparison, never a query
            # receipt or current legal-status verification.
            document = entry.get("document", {})
            if not (entry.get("kind") == "candidate_lead"
                    and entry.get("authority_scope") == "published_document_only"
                    and document.get("path") and document.get("sha256") and document.get("source_url")):
                continue
        elif not (entry.get("kind") in {"official_record", "patent_document", "design_drawings",
                      "rights_record", "provenance_document", "license", "patent_claim_followup"}
                  and entry.get("path") and entry.get("sha256")
                  and (entry.get("source_url") or entry.get("source_document"))):
            continue
        result.add(ref)
    return result


def _recall_refs(row, coverage, registry, runs, task, plan):
    from assessment_v24 import _entry_matches_run
    scope = next((scope for scope in coverage if (scope["jurisdiction"], scope["right_type"])
                  == scope_key(row)[:2] and (not _decision_enabled(task)
                  or scope.get("scenario_id") == row.get("scenario_id"))), {})
    completed_ids = {query["query_id"] for query in scope.get("queries", []) if query.get("complete")}
    ppubs_semantics = {}
    for provider, queries in plan.get("queries", {}).items():
        for query in queries:
            if query.get("query_id") not in completed_ids or provider != "uspto_patent_browser":
                continue
            from record_browser_execution import planned_browser_query
            try:
                compiled = planned_browser_query(provider, query, task)
            except ValueError:
                compiled = {}
            if compiled.get("semantics") not in {"lexical_phrase", "boolean_terms"}:
                completed_ids.discard(query["query_id"])
            else:
                ppubs_semantics[query["query_id"]] = compiled
    def current_semantics(entry):
        if entry.get("provider") != "uspto_patent_browser":
            return True
        provenance = entry.get("payload", {}).get("browser_evidence", {}).get("capture_provenance", {})
        expected = ppubs_semantics.get(entry.get("query_id"), {})
        actual = provenance.get("query_semantics", {})
        receipt = provenance.get("query_execution", {})
        return bool(expected and receipt.get("path") and receipt.get("sha256")
                    and all(actual.get(key) == value for key, value in expected.items()))
    qualified = {ref for ref, entry in registry.items() if entry.get("query_id") in completed_ids
            and (entry.get("jurisdiction"), entry.get("right_type")) == scope_key(row)[:2]
            and current_semantics(entry)
            and (run := runs.get(entry.get("source_run_id"), {})).get("status") in {"success", "no_result"}
            and _entry_matches_run(entry, run)
            and run.get("metadata", {}).get("search_coverage", {}).get("schema_valid") is True
            and run.get("metadata", {}).get("search_coverage", {}).get("truncated") is False}
    # A completed asset investigation is not a database search and therefore
    # has no search_coverage receipt. Admit its actual comparison only through
    # the existing scenario/asset/step and retained-file validators. This does
    # not make an empty asset inventory, one completed step, or unknown legal
    # facts a negative-clearance result.
    from record_asset_provenance import specialty_enabled, asset_scope, investigation_complete, INVESTIGATION_STEPS
    if (not specialty_enabled(task) or not _decision_enabled(task) or row.get("candidate_id")
            or row.get("right_type") not in {"copyright", "trade_dress", "unregistered_design"}
            or scope.get("scenario_sha256") != row.get("scenario_sha256")):
        return qualified
    from assessment_v24 import _retained_artifacts_complete
    from workflow_v24 import scenario_row_bindings
    inventory = asset_scope(task, row.get("scenario_id"), row["right_type"])
    if not inventory["inventory_reviewed"] or not inventory["asset_ids"]:
        return qualified
    checked = {item["query_id"]: item for item in scope.get("queries", [])
               if item.get("complete") and item.get("investigation_status") == "completed"}
    steps = {}
    binding = {"scenario_id": row["scenario_id"], "scenario_sha256": row["scenario_sha256"]}
    for query in plan.get("queries", {}).get("asset_provenance", []):
        proof = checked.get(query.get("query_id"), {})
        if (not proof or query.get("operation") != "provenance_review"
                or query.get("action_purpose") != "provenance" or query.get("execution_phase") != "initial"
                or query.get("candidate_id") or query.get("triage_candidate_id")
                or (query.get("jurisdiction"), query.get("right_type")) != scope_key(row)[:2]
                or scenario_row_bindings(task, query) != [binding]
                or query.get("asset_scope_sha256") != inventory["scope_sha256"]):
            continue
        for ref in proof.get("evidence_refs", []):
            entry = registry.get(ref, {})
            run = runs.get(entry.get("source_run_id"), {})
            payload = entry.get("payload", {})
            if (entry.get("query_id") == query["query_id"] and entry.get("provider") == "asset_provenance"
                    and run.get("status") == "success" and not run.get("error_code")
                    and entry.get("plan_entry_sha256") == sha256_json(query)
                    and _entry_matches_run(entry, run) and isinstance(payload, dict)
                    and _retained_artifacts_complete(payload)
                    and investigation_complete(task, payload, query, row["scenario_id"], registry)):
                steps.setdefault(query.get("search_dimension"), set()).add(ref)
    if set(INVESTIGATION_STEPS[row["right_type"]]) <= set(steps):
        # The row must cite an actual comparison, not just a provenance note.
        for step in ("visual_comparison", "functionality"):
            qualified.update(steps.get(step, set()))
    return qualified


def _published_supplement_binds_candidate(entry, candidate):
    """Exact US publication identity, only after retained-file validation.

    This binds comparison content, not a query receipt, current legal status,
    or other members of the publication's application/family.
    """
    from record_candidate_lead import publication_number
    right = candidate.get("right_type")
    if (entry.get("kind") not in {"patent_document", "design_drawings"}
            or entry.get("authority_scope") != "published_document_only"
            or right not in {"patent", "design"}
            or entry.get("right_type") != right
            or entry.get("jurisdiction") != "US" or candidate.get("jurisdiction") != "US"
            or (entry.get("kind") == "design_drawings" and right != "design")
            or not _text(entry.get("path"))
            or not isinstance(entry.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
        return False
    try:
        actual = publication_number(entry.get("publication_number"))
        expected = publication_number(candidate.get("publication_number"))
    except ValueError:
        return False
    return (actual == expected
            and right == ("design" if actual.startswith("USD") else "patent"))


def _historical_review_refs(row, coverage, registry, validated_supplements):
    """Admit exact original EVs only through internally validated reuse proof.

    A retained wrapper alone proves no official facts. Coverage has already
    revalidated the old plan, run, receipt, files, date and current scope; bind
    the cited wrapper back to those exact original bytes and accepted payload.
    """
    refs = set()
    for scope in coverage:
        if any(scope.get(key) != row.get(key) for key in ('scenario_id', 'scenario_sha256', 'jurisdiction', 'right_type')):
            continue
        for query in scope.get('queries', []):
            proof = query.get('historical_reuse', {})
            if (not query.get('complete') or proof.get('complete') is not True
                    or proof.get('authority_scope') != 'original_official_verification'
                    or proof.get('action_purpose') != 'official_verification'
                    or any(proof.get(key) != row.get(key) for key in ('scenario_id', 'scenario_sha256', 'jurisdiction', 'right_type'))):
                continue
            descriptor = (validated_supplements or {}).get(proof.get('reuse_evidence_id'), {})
            if descriptor.get('kind') != 'historical_source_reuse':
                continue
            for ref in set(row.get('evidence_refs', [])) & set(proof.get('evidence_ids', [])):
                item = (validated_supplements or {}).get(ref, {})
                payload = item.get('payload', {})
                if (item.get('kind') != 'retained_source_record' or registry.get(ref) != item
                        or item.get('original_task_id') != proof.get('source_task_id')
                        or not item.get('original_entry_sha256')
                        or item['original_entry_sha256'] != proof.get('source_evidence_sha256', {}).get(ref)
                        or any(item.get(key) != descriptor.get(key) for key in ('path', 'sha256', 'bytes'))
                        or item.get('source_checked_at') != proof.get('source_checked_at')
                        or not isinstance(payload, dict)
                        or any(payload.get(key) != row.get(key) for key in ('candidate_id', 'jurisdiction', 'right_type'))
                        or payload not in proof.get('payload', [])):
                    continue
                refs.add(ref)
    return refs


def _apply_recall_integrity(rows, task, evidence, candidates, plan, coverage, registry,
                            *, validated_supplements=None, sufficiency_only=False):
    """Business sufficiency is separate from file and reviewer integrity."""
    from workflow_v24 import product_analysis_readiness, planned_execution_gaps
    runs = {run["run_id"]: run for run in evidence.get("source_runs", [])}
    readiness = product_analysis_readiness(task)
    completion_gaps = [str(gap["code"]) for gap in readiness.get("gaps", [])]
    execution = [] if sufficiency_only else planned_execution_gaps(task, plan, evidence)
    completion_gaps.extend(str(gap["code"]) + ":" + str(gap["query_id"]) for gap in execution)
    document_supplement = {"evidence": list((validated_supplements or {}).values())}
    for row in rows:
        row["screening_revision"] = task["screening_revision"]
        if row.get("out_of_scope") or row.get("future_signal") or row.get("signal_only") or row["right_type"] == "enforcement":
            continue
        row.setdefault("assessment_status", "assessed" if row.get("risk") in RISKS else "pending")
        retained_refs = (_historical_review_refs(row, coverage, registry, validated_supplements)
                         if _decision_enabled(task) else set())
        actual = _substantive_refs(row.get("evidence_refs", []), registry, runs, row=row) | retained_refs
        candidate = next((item for _, item in iter_candidates(candidates) if item.get("candidate_id") == row.get("candidate_id")), {})
        candidate_refs = set(candidate.get("evidence_refs", [])) | set(candidate.get("verification_refs", []))
        exact_document_ids = set()
        if _correction_enabled(task):
            from decision_workflow import candidate_document_entries
            exact_document_ids = {entry["evidence_id"] for entry in candidate_document_entries(candidate, evidence,
                document_supplement, task=task)}
        bound_actual = {ref for ref in actual if ref in retained_refs or ref in candidate_refs
                        or registry[ref].get("candidate_id") == row.get("candidate_id")
                        or (ref in (validated_supplements or {})
                            and registry[ref] == validated_supplements[ref]
                            and (ref in exact_document_ids if _correction_enabled(task)
                                 else _published_supplement_binds_candidate(registry[ref], candidate)))}
        sufficient = True
        if row["risk"] in {"低", "极低"}:
            decisive_refs = set(row.get("decisive_exclusion", {}).get("evidence_refs", []))
            comparison = row.get("search_comparison", {})
            recall_refs = _recall_refs(row, coverage, registry, runs, task, plan)
            compared = bool(comparison.get("reasoning") and set(comparison.get("evidence_refs", [])) & recall_refs)
            decisive = bool(row.get("candidate_id") and decisive_refs & bound_actual)
            counter_refs = {ref for argument in row.get("counter_evidence", []) for ref in argument.get("evidence_refs", [])}
            specific = bool(row.get("candidate_id") and counter_refs & bound_actual
                            and row.get("comparison", {}).get("criteria"))
            sufficient = decisive or specific or (not row.get("candidate_id") and compared)
        elif row["risk"] in {"中", "高", "极高"}:
            positive_refs = {ref for argument in row.get("supporting_evidence", []) for ref in argument.get("evidence_refs", [])}
            sufficient = bool(positive_refs & bound_actual)
        if not sufficient:
            row["reviewed_risk"] = row["risk"]
            row.update(risk=None, assessment_status="pending", evidence_confidence="低",
                       pending_reasoning="未取得对应国家和权利类型的合格检索比较或具体权利证据；保留阶段性记录，不输出最终风险结论。")
            row["reviewed_reasoning"] = row["reasoning"]
            row["reasoning"] = row["pending_reasoning"]
        # A failed query is a gap, never counter-evidence even if an input
        # reviewer has mislabeled its narrative as an exclusion.
        retained, rejected = [], []
        allowed = (_substantive_refs(row.get("evidence_refs", []), registry, runs, row=row)
                   | retained_refs | _recall_refs(row, coverage, registry, runs, task, plan))
        for argument in row.get("counter_evidence", []):
            (retained if set(argument.get("evidence_refs", [])) & allowed else rejected).append(argument)
        if rejected:
            row["unsubstantiated_counter_evidence"] = rejected
            row["counter_evidence"] = retained
        if not row.get("counter_evidence"):
            row["no_counter_evidence_reasoning"] = "未取得降低风险的证据；检索失败、覆盖缺口和未发现候选均不作为排除事实。"
        if row["assessment_status"] == "pending":
            row.update(risk=None, publication="pending", aggregation_included=False)
            completion_gaps.append("ASSESSMENT_PENDING:" + ":".join(scope_key(row)))
    followup = task.get("product", {}).get("patent_claim_followup") or {}
    if isinstance(followup, dict) and readiness["patent_claim_followup"].get("required") and followup.get("status") == "completed":
        refs = followup.get("evidence_ids", [])
        valid_refs = isinstance(refs, list) and all(isinstance(ref, str) for ref in refs)
        valid = _substantive_refs(refs, registry, runs) if valid_refs else set()
        if not valid or not set(refs).issubset(registry):
            completion_gaps.append("PATENT_CLAIM_FOLLOWUP_EVIDENCE_INVALID")
    return sorted(set(completion_gaps)), execution


def _scenario_caps(review, scenarios, known):
    values = (review or {}).get("scenario_confidence_caps", {})
    if not isinstance(values, dict):
        raise ValueError("SCENARIO_CONFIDENCE_CAP_INVALID")
    for sid, item in values.items():
        if (sid not in scenarios or not isinstance(item, dict)
                or item.get("confidence") not in CONFIDENCES or not _text(item.get("reasoning"))
                or item.get("scenario_sha256") != scenarios[sid]["scenario_sha256"]
                or not _refs(item.get("evidence_refs", []), known, required=False)):
            raise ValueError("SCENARIO_CONFIDENCE_CAP_INVALID")
    return values


def missing_scope_reviews(task, scopes, first, second, registry, index):
    """The same necessary-scope obligation serves planning and final review."""
    missing = []
    def qualified(row):
        return _future_review_qualified(row, set(registry), index, task, registry)
    for scope in scopes:
        sid, country, right_type = (scope[key] for key in ("scenario_id", "jurisdiction", "right_type"))
        absent = []
        for role, review in (("first", first), ("second", second)):
            review = review or {}
            relevant = [row for row in review.get("assessments", [])
                if row.get("scenario_id") == sid and scope_key(row)[:2] == (country, right_type)
                and (not _future_labeled(row) or qualified(row))]
            signals = [row for row in review.get("future_applications", [])
                if row.get("scenario_id") == sid and scope_key(row)[:2] == (country, right_type) and qualified(row)]
            if not relevant and not signals:
                absent.append(review.get("reviewer") or role)
        if absent:
            missing.append({"scenario_id": sid, "jurisdiction": country, "right_type": right_type,
                "candidate_id": "", "assessment_status": "pending",
                "pending_reasoning": "必要范围缺少独立审阅记录；调查完成不代替风险或适用性审阅。",
                "missing_reviewers": absent})
    return missing


def _compute_scenario_assessment(task, evidence, candidates, plan, ledger, first, second,
        adjudication, rows, digest, registry, supplemental_index, supplement, evidence_root, generated_at):
    """Opt-in decision contract: current risk and required-work completion differ."""
    from decision_workflow import effective_decision, scenario_index, triage_summary, necessary_scenario_right_types
    from workflow_v24 import scenario_execution_gaps
    scenarios = scenario_index(task)
    primary_id = task["primary_scenario_id"]
    index, _ = candidate_index(candidates)
    triage = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)
    coverage = coverage_by_scope(task, evidence, candidates, plan, strict_lineage=True,
                                 ledger=ledger, supplement=supplement, evidence_root=evidence_root)
    for row in rows:
        row["decision_workflow_revision"] = task["decision_workflow_revision"]
        row["scenario_title"] = scenarios[row["scenario_id"]]["title"]
        row["primary_scenario"] = row["scenario_id"] == primary_id
        if not row.get("candidate_id") or row.get("out_of_scope"):
            continue
        collection, candidate = index[row["candidate_id"]]
        decision = effective_decision(task, ledger, collection, candidate, row["scenario_id"],
            row["jurisdiction"], row["right_type"], evidence=evidence, supplement=supplement)
        row["triage_decision"] = decision["decision"]
        if decision["decision"] != "selected":
            # A stale or merely prioritized candidate is not a reviewed finding.
            if row.get("risk") in RISKS and row.get("assessment_status") != "pending":
                raise ValueError("ASSESSMENT_REQUIRES_CURRENT_SELECTED_TRIAGE: " + row["candidate_id"])
            row["aggregation_included"] = False
        elif (row["right_type"] in {"patent", "utility_model"} and row.get("risk") in RISKS
                and not row.get("future_signal") and not row.get("signal_only")):
            claims = row.get("comparison", {}).get("claims", [])
            legal = row.get("decisive_exclusion", {})
            legal_refs = [registry.get(ref, {}) for ref in legal.get("evidence_refs", [])]
            legal_only = (legal.get("basis") == "legal_status_or_scope"
                          and _text(legal.get("comparison_not_required_reasoning"))
                          and any(entry.get("kind") in {"official_record", "rights_record", "license"}
                                  and entry.get("authority_scope") != "published_document_only" for entry in legal_refs))
            if not legal_only and not any(claim.get("claim_type") == "independent" for claim in claims):
                raise ValueError("SELECTED_PATENT_INDEPENDENT_CLAIM_COMPARISON_REQUIRED")
    basic_gaps, _ = _apply_recall_integrity(rows, task, evidence, candidates, plan, coverage,
        registry, validated_supplements=supplemental_index, sufficiency_only=True)
    execution = scenario_execution_gaps(task, plan, evidence, candidates=candidates, ledger=ledger,
                                       supplement=supplement, evidence_root=evidence_root, coverage=coverage)
    caps = [_scenario_caps(review, scenarios, set(registry)) for review in (first, second, adjudication)]
    if (adjudication or {}).get("module_confidence_caps"):
        raise ValueError("UNSCOPED_MODULE_CAP_NOT_ALLOWED_IN_SCENARIO_WORKFLOW")
    summaries = []
    for sid, scenario in scenarios.items():
        current_rows = [row for row in rows if row["scenario_id"] == sid]
        current = [row for row in current_rows if row.get("aggregation_included") and row.get("risk") in RISKS]
        local_highest = max((row["risk"] for row in current), key=RISKS.index, default=None)
        drivers = [row for row in current if row["risk"] == local_highest]
        scopes = [scope for scope in coverage if scope.get("scenario_id") == sid]
        necessary_rights = necessary_scenario_right_types(task, scenario)
        decisions = [r for r in triage["records"] if r["scenario_id"] == sid and r["right_type"] in necessary_rights]
        selected = [r for r in decisions if r["decision"] == "selected"]
        corrected = _correction_enabled(task)
        def qualified_future(row):
            return _future_review_qualified(row, set(registry), index, task, registry)
        reviewed_keys = {scope_key(row) for row in current_rows if not row.get("out_of_scope")
            and row.get("assessment_status") != "pending" and (row.get("risk") in RISKS
                or ((row.get("future_signal") or row.get("signal_only"))
                    and (not corrected or row.get("right_type") == "enforcement" or qualified_future(row))))}
        # Future applications are reviewed, but never converted to current rights.
        future_keys = [{scope_key(row) for row in review.get("future_applications", [])
                       if row.get("scenario_id") == sid and row.get("candidate_id")
                       and (not corrected or qualified_future(row))} for review in (first, second)]
        reviewed_keys.update(future_keys[0] & future_keys[1])
        missing = [r for r in selected if (r["jurisdiction"], r["right_type"], r["candidate_id"]) not in reviewed_keys]
        queues = {name: [r for r in decisions if r["decision"] == name] for name in ("needs_info", "unreviewed")}
        queues["selected_unassessed"] = missing
        queues["pending_assessments"] = [{key: row.get(key) for key in
             ("scenario_id", "jurisdiction", "right_type", "candidate_id", "pending_reasoning")}
             for row in current_rows if row.get("assessment_status") == "pending" and row["right_type"] in necessary_rights]
        missing_scopes = []
        if corrected:
            missing_scopes = missing_scope_reviews(task, scopes, first, second, registry, index)
            queues["scope_unassessed"] = missing_scopes
        scenario_execution = [gap for gap in execution if gap.get("scenario_id") in (None, sid)]
        gaps = [gap for gap in basic_gaps if not gap.startswith("ASSESSMENT_PENDING:")] if sid == primary_id else []
        gaps.extend(str(gap.get("code", "REQUIRED_ACTION_INCOMPLETE"))
                    + (":" + str(gap["query_id"]) if gap.get("query_id") else "") for gap in scenario_execution)
        gaps.extend("SELECTED_ASSESSMENT_MISSING:" + r["candidate_id"] for r in missing)
        gaps.extend("TRIAGE_" + name.upper() + ":" + r["candidate_id"] for name in ("needs_info", "unreviewed") for r in queues[name])
        gaps.extend("ASSESSMENT_PENDING:" + str(row["right_type"]) + ":" + str(row.get("candidate_id", "")) for row in queues["pending_assessments"])
        gaps.extend("SCOPE_ASSESSMENT_MISSING:" + row["jurisdiction"] + ":" + row["right_type"] for row in missing_scopes)
        retrieval_complete = bool(scopes) and all(scope.get("retrieval_status") == "complete" for scope in scopes)
        triage_complete = not queues["needs_info"] and not queues["unreviewed"]
        verification_complete = bool(scopes) and all(scope.get("verification_status") == "complete" for scope in scopes)
        for scope in scopes:
            gaps.extend(str(gap) for gap in scope.get("gaps", []))
        if not scopes:
            gaps.append("SCENARIO_COVERAGE_MISSING")
        risk = local_highest
        reasons = ["同一销售情景内，取有具体依据的最高适用当前风险；条件情景与未来申请分别列示。",
                   "完成度记录必要证据义务是否满足，不清空已有依据的当前风险，也不把失败查询当成排除事实。"]
        if risk in {"低", "极低"} and not (retrieval_complete and triage_complete and verification_complete and not gaps):
            risk = None
            reasons.append("目前只有局部低风险或排除结论，必要负面检索或入选比较仍不足，不能外推该情景总体低风险。")
        if risk == "极低":
            decisive = (adjudication or {}).get("overall_decisive_exclusion") or {}
            if decisive.get("scenario_id") != sid or decisive.get("scenario_sha256") != scenario["scenario_sha256"]:
                risk = "低"
                reasons.append("单件的决定性排除不足以支持整个情景极低风险。")
        if risk is None:
            gaps.append("SCENARIO_RISK_BASIS_PENDING")
        completed = retrieval_complete and triage_complete and verification_complete and not gaps
        chosen_caps = [caps[2][sid]] if sid in caps[2] else [cap[sid] for cap in caps[:2] if sid in cap]
        cap = min((item["confidence"] for item in chosen_caps), key=CONFIDENCES.index, default="高")
        confidence = min([cap, *[row["evidence_confidence"] for row in drivers]], key=CONFIDENCES.index) if drivers else "低"
        completion = {"status": "complete" if completed else "incomplete",
            "retrieval": "complete" if retrieval_complete else "incomplete",
            "triage": "complete" if triage_complete else "incomplete",
            "verification": "complete" if verification_complete else "incomplete",
            "assessment": "complete" if risk in RISKS and not missing and not missing_scopes and not queues["pending_assessments"] else "incomplete",
            "triage_counts": {name: sum(record["decision"] == name for record in decisions)
                              for name in triage["by_scenario"][sid]["counts"]},
            "all_triage_counts": triage["by_scenario"][sid]["counts"], "queues": queues,
            "gaps": sorted(set(gaps))}
        summaries.append({"scenario_id": sid, "scenario_sha256": scenario["scenario_sha256"],
            "title": scenario["title"], "conditional": scenario["conditional"],
            "necessary_right_types": sorted(necessary_rights),
            "assumptions": deepcopy(scenario["assumptions"]), "primary": sid == primary_id,
            "risk": risk, "assessment_status": "assessed" if risk in RISKS else "pending",
            "confidence": confidence, "known_scoped_risk": local_highest,
            "known_scoped_confidence": confidence if drivers else None,
            "coverage_confidence_cap": cap, "coverage_confidence_reasoning": [item["reasoning"] for item in chosen_caps],
            "drivers": [{key: row.get(key) for key in ("scenario_id", "scenario_sha256", "jurisdiction", "right_type", "candidate_id", "module_id", "title", "risk", "evidence_confidence")} for row in drivers],
            "reasons": reasons, "completion": completion})
    primary = next(item for item in summaries if item["scenario_id"] == primary_id)
    complete = all(item["completion"]["status"] == "complete" for item in summaries)
    overall = {key: deepcopy(primary[key]) for key in ("scenario_id", "scenario_sha256", "risk", "confidence", "known_scoped_risk", "known_scoped_confidence", "drivers", "reasons", "coverage_confidence_cap", "coverage_confidence_reasoning")}
    overall.update(provisional=True, all_scope_clearance=False, business_completion="complete" if complete else "incomplete",
        primary_completion=primary["completion"]["status"], assessment_status=primary["assessment_status"],
        report_lead=primary["title"] + "：" + (f"{primary['risk']}风险／{primary['confidence']}置信度" if primary["risk"] else "当前风险尚未定级")
                    + ("；必要排查已完成" if complete else "；排查仍有未完成义务"),
        report_summary=" ".join(primary["reasons"]))
    supplemental = {name: list({sha256_json(row): deepcopy(row) for review in (first, second)
        for row in review.get(name, [])}.values()) for name in ("future_applications", "enforcement_signals")}
    return {"schema_version": SCHEMA, "assessment_contract": CONTRACT, "assessment_policy": POLICY,
        **({"workflow_correction_revision": task["workflow_correction_revision"]} if _correction_enabled(task) else {}),
        "screening_revision": task.get("screening_revision"), "decision_workflow_revision": task["decision_workflow_revision"],
        "task_id": task["task_id"], "generated_at": generated_at or now_iso(), "status": "completed" if complete else "incomplete",
        "overall": overall, "scenario_summaries": summaries, "assessments": rows,
        "coverage": {"scopes": coverage, "triage": triage, "execution_gaps": execution,
            "completion_gaps": [{"scenario_id": item["scenario_id"], "gaps": item["completion"]["gaps"]} for item in summaries],
            "notes": [*(supplement or {}).get("coverage_notes", []), "候选未入选仅表示未进入深度核验，不是权利要求或法律排除；needs_info 与未审队列保持可追溯。"]},
        "review": {"required": True, "human_review_required": False, "evidence_digest": digest,
            "evidence_root": str(Path(evidence_root).resolve()) if evidence_root else None,
            "first_reviewer": first["reviewer"], "second_reviewer": second["reviewer"],
            "input_reviews": {"first": deepcopy(first), "second": deepcopy(second), "adjudication": deepcopy(adjudication)}},
        "input_binding": {"evidence_root": str(Path(evidence_root).resolve()) if evidence_root else None, "evidence_digest": digest},
        "supplement": deepcopy(supplement), "supplement_provenance": {"validation": "retained_file_hashes_verified",
            "adapter_acceptance_claimed": False, "evidence_count": len(supplemental_index)},
        "legacy_coverage_confidence_disclosure": [{"reviewer": review["reviewer"], "cap": review["coverage_confidence_cap"],
            "reasoning": review["coverage_confidence_reasoning"]} for review in (first, second)],
        "paid_recommendations": [], **supplemental}


def compute_assessment(task, evidence, candidates, plan, ledger, first, second=None,
                       adjudication=None, *, supplement=None, evidence_root=None,
                       generated_at=None, task_dir=None) -> dict[str, Any]:
    from decision_workflow import decision_snapshot
    with decision_snapshot(task, evidence, candidates, plan, ledger, supplement):
        return _compute_assessment(task, evidence, candidates, plan, ledger, first, second,
            adjudication, supplement=supplement, evidence_root=evidence_root, generated_at=generated_at,
            task_dir=task_dir)


def _compute_assessment(task, evidence, candidates, plan, ledger, first, second=None,
                        adjudication=None, *, supplement=None, evidence_root=None,
                        generated_at=None, task_dir=None) -> dict[str, Any]:
    ledger_gaps = validate_inputs(task, evidence, candidates, plan, ledger, evidence_root=evidence_root,
                                  supplement=supplement, task_dir=task_dir)
    supplemental_index = validate_supplement(supplement, evidence_root, task=task, evidence=evidence)
    canonical = evidence_index(evidence)
    if set(canonical) & set(supplemental_index):
        raise ValueError("SUPPLEMENT_CANONICAL_EVIDENCE_ID_COLLISION")
    known = set(canonical) | set(supplemental_index)
    runs_by_id = {run["run_id"]: run for run in evidence.get("source_runs", [])}
    def nonproduction(value):
        if isinstance(value, dict):
            return any(str(value.get(key) or "").casefold() in NON_PRODUCTION
                       for key in ("source_environment", "environment", "kind")) or any(nonproduction(item) for item in value.values())
        return isinstance(value, list) and any(nonproduction(item) for item in value)
    non_production_refs = {ref for ref, entry in {**canonical, **supplemental_index}.items()
        if nonproduction(entry) or nonproduction(runs_by_id.get(entry.get("source_run_id"), {}))}
    def referenced_ids(value):
        refs = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if (key == "evidence_refs" or key.endswith("_evidence_refs")) and isinstance(item, list):
                    refs.update(ref for ref in item if isinstance(ref, str))
                else:
                    refs.update(referenced_ids(item))
        elif isinstance(value, list):
            for item in value:
                refs.update(referenced_ids(item))
        return refs
    for review in (first, second, adjudication):
        if not isinstance(review, dict):
            continue
        if referenced_ids(review) & non_production_refs:
            raise ValueError("NON_PRODUCTION_EVIDENCE_CANNOT_SUPPORT_REAL_ESTIMATE")
    index, errors = candidate_index(candidates)
    if errors:
        raise ValueError("; ".join(errors))
    digest = review_digest(evidence, candidates, ledger, plan, task, supplement)
    jurisdictions = {str(value).upper() for value in task.get("target_jurisdictions", [])}
    registry = {**canonical, **supplemental_index}
    _validate_review(first, digest, known, index, jurisdictions, task, registry)
    if second is None:
        raise ValueError("SECOND_REVIEW_REQUIRED: complete independent work before publishing")
    _validate_review(second, digest, known, index, jurisdictions, task, registry)
    if (first["reviewer"] == second["reviewer"]
            or first["review_context"]["session_id"] == second["review_context"]["session_id"]):
        raise ValueError("SECOND_REVIEW_NOT_INDEPENDENT")
    left = {_review_scope_key(row, task): row for row in first["assessments"]}
    right = {_review_scope_key(row, task): row for row in second["assessments"]}
    decisions = {}
    overall_decisive = None
    module_caps = None
    if adjudication is not None:
        context = adjudication.get("review_context", {})
        if (not _text(adjudication.get("reviewer")) or not _text(context.get("session_id"))
                or context.get("evidence_digest") != digest or not isinstance(adjudication.get("decisions"), list)):
            raise ValueError("ADJUDICATION_CONTEXT_INVALID")
        expected_refs = {"first": sha256_json(first), "second": sha256_json(second)}
        for decision in adjudication["decisions"]:
            _validate_row(decision, known, index, jurisdictions, task, registry)
            key = _review_scope_key(decision, task)
            if key in decisions or key not in set(left) | set(right):
                raise ValueError("DUPLICATE_OR_UNREVIEWED_ADJUDICATION")
            if not _text(decision.get("adjudication_reasoning")) or decision.get("review_refs") != expected_refs:
                raise ValueError("ADJUDICATION_REASONING_OR_REVIEW_BINDING_INVALID")
            decisions[key] = decision
        if any(field in adjudication for field in ("coverage_confidence_cap", "overall_decisive_exclusion", "module_confidence_caps", "scenario_confidence_caps")):
            if not decisions and adjudication.get("review_refs") != expected_refs:
                raise ValueError("GLOBAL_ADJUDICATION_REVIEW_BINDING_REQUIRED")
        module_caps = adjudication.get("module_confidence_caps")
        if module_caps is not None and (not isinstance(module_caps, dict) or any(
                module not in MODULE_IDS or module == "enforcement" or not isinstance(value, dict)
                or value.get("confidence") not in CONFIDENCES or not _text(value.get("reasoning"))
                for module, value in module_caps.items())):
            raise ValueError("MODULE_CONFIDENCE_CAP_INVALID")
        _validate_nested_refs(adjudication, known)
        overall_decisive = adjudication.get("overall_decisive_exclusion")
        if overall_decisive is not None and (not isinstance(overall_decisive, dict)
                or not _text(overall_decisive.get("scope")) or not _text(overall_decisive.get("reasoning"))
                or not _refs(overall_decisive.get("evidence_refs"), known)):
            raise ValueError("OVERALL_DECISIVE_EXCLUSION_INVALID")
        if overall_decisive is not None and _decision_enabled(task):
            _validate_scenario_binding(overall_decisive, task)
    rows = []
    for key in sorted(set(left) | set(right)):
        conflicts = _row_conflicts(left[key], right[key], task) if key in left and key in right else ["review_scope_missing"]
        if conflicts and key not in decisions:
            raise ValueError("ADJUDICATION_REQUIRED: " + str(key) + ":" + ",".join(conflicts))
        row = deepcopy(decisions.get(key) or left.get(key) or right[key])
        row["assessment_object"] = _assessment_object(row)
        if row.get("applicability_exception") and key not in decisions:
            raise ValueError("APPLICABILITY_EXCEPTION_REQUIRES_CHIEF_ADJUDICATION")
        row["publication"] = "out_of_scope" if row.get("out_of_scope") is True else "evidence_estimate"
        row["aggregation_included"] = not (row.get("out_of_scope") is True or row["right_type"] == "enforcement"
                                               or row.get("signal_only") is True or row.get("future_signal") is True)
        uncertainty = []
        basis = row.get("confidence_basis", {})
        # A decisive expiry/licence can dispense with a product comparison;
        # uncertainty about the right's identity cannot be dispensed with.
        relevant = {"identity", "status"} if row.get("decisive_exclusion") else {"identity", "scope", "status", "product", "comparison"}
        uncertainty.extend("未核实的置信度基础：" + name for name in sorted(relevant)
                           if basis.get(name, {}).get("satisfied") is False)
        if (row["aggregation_included"] and key[2] and key[1] in {"patent", "utility_model", "design", "trademark_word", "trademark_figurative"}
                and row.get("right_state", "unknown") == "unknown"):
            uncertainty.append("当前状态尚未核实；对风险及置信度的具体影响见主审理由。" if _decision_enabled(task)
                               else "适用权利的当前状态未知，保留当前预判并降低置信度。")
        if row["aggregation_included"] and key[2] and key[1] in {"patent", "utility_model", "design", "trademark_word", "trademark_figurative"}:
            from finalize_assessment import _candidate_effect_jurisdictions
            if not _candidate_effect_jurisdictions(index[key[2]][1], key[1]) and not row.get("applicability_exception"):
                uncertainty.append("候选的地域适用事实未知，当前预判依赖低置信假设。")
        if uncertainty and _decision_enabled(task):
            row["confidence_gaps"] = uncertainty
        elif uncertainty and row.get("evidence_confidence") in CONFIDENCES:
            row["reviewed_evidence_confidence"] = row["evidence_confidence"]
            row["evidence_confidence"] = "低"
            row["confidence_reasoning"] += " " + " ".join(uncertainty)
        row["review_resolution"] = {"method": "chief_adjudication" if key in decisions else "independent_agreement",
                                    "conflicts": conflicts, "first_risk": left.get(key, {}).get("risk"),
                                    "second_risk": right.get(key, {}).get("risk")}
        rows.append(row)
    if _decision_enabled(task):
        return _compute_scenario_assessment(task, evidence, candidates, plan, ledger, first, second,
                    adjudication, rows, digest, {**canonical, **supplemental_index},
                    supplemental_index, supplement, evidence_root, generated_at)
    strict = recall_integrity_enabled(task)
    coverage = coverage_by_scope(task, evidence, candidates, plan, strict_lineage=True)
    completion_gaps, execution_gaps = (_apply_recall_integrity(rows, task, evidence, candidates, plan, coverage,
                       {**canonical, **supplemental_index},
                       validated_supplements=supplemental_index) if strict else ([], []))
    included = [row for row in rows if row["aggregation_included"] and row.get("risk") in RISKS]
    if not included and not (strict and any(row.get("assessment_status") == "pending" for row in rows)):
        raise ValueError("NO_CURRENT_IN_SCOPE_ASSESSMENT: do not invent an overall grade")
    highest = max((row["risk"] for row in included), key=RISKS.index, default=None)
    drivers = [row for row in included if row["risk"] == highest]
    cap_source = adjudication if adjudication and "coverage_confidence_cap" in adjudication else None
    if cap_source:
        if (cap_source["coverage_confidence_cap"] not in CONFIDENCES
                or not _text(cap_source.get("coverage_confidence_reasoning"))):
            raise ValueError("ADJUDICATION_COVERAGE_CONFIDENCE_INVALID")
        cap = cap_source["coverage_confidence_cap"]
        cap_reasons = [cap_source["coverage_confidence_reasoning"]]
    else:
        cap = min((first["coverage_confidence_cap"], second["coverage_confidence_cap"]), key=CONFIDENCES.index)
        cap_reasons = list(dict.fromkeys([first["coverage_confidence_reasoning"], second["coverage_confidence_reasoning"]]))
    for scope in coverage:
        current = [row for row in rows if scope_key(row)[:2] == (scope["jurisdiction"], scope["right_type"])]
        evaluated = [row for row in current if row["aggregation_included"] and _assessment_object(row) == "product"]
        fully_excluded = any(scope_key(item) == (scope["jurisdiction"], scope["right_type"], "")
                             and _assessment_object(item) == "product"
                             for item in task.get("assessment_scope_exclusions", []))
        if not evaluated and not fully_excluded:
            scope["gaps"].append("SCOPE_ASSESSMENT_MISSING")
        for _, item in iter_candidates(candidates):
            candidate_excluded = any(_review_scope_key(exclusion) == (scope["jurisdiction"], scope["right_type"], item.get("candidate_id"), "product")
                                     for exclusion in task.get("assessment_scope_exclusions", []))
            if candidate_applies(item, scope["jurisdiction"], scope["right_type"]) and not candidate_excluded and not any(row.get("candidate_id") == item.get("candidate_id") for row in evaluated):
                scope["gaps"].append("CANDIDATE_ASSESSMENT_MISSING:" + item["candidate_id"])
        if scope["gaps"]:
            for row in evaluated:
                if not row.get("candidate_id") and row["risk"] == "低" and row["evidence_confidence"] != "低":
                    row["reviewed_evidence_confidence"] = row["evidence_confidence"]
                    row["evidence_confidence"] = "低"
                    row["confidence_reasoning"] += " 该范围检索覆盖仍不完整；未发现具体威胁仅支持低置信预判。"
        scope["gaps"] = sorted(set(scope["gaps"]))
        if scope["gaps"] and scope["status"] == "满足已定义要求":
            scope["status"] = "部分完成"
    overall_reasons = ["采用经审阅或主审裁决的最高适用风险；不按候选数量、相似图片数量或重复文献加权。",
                       "当前评级是现有证据范围内的预判；证据缺口单独影响置信度和人工核查事项。"]
    if highest == "极低" and overall_decisive is None:
        highest = "低"
        overall_reasons.append("决定性排除仅针对已评具体候选，不能外推整个产品极低；总体按低风险预判。")
    missing_assessments = bool(ledger_gaps) or any(
        gap == "SCOPE_ASSESSMENT_MISSING" or gap.startswith("CANDIDATE_ASSESSMENT_MISSING:")
        for scope in coverage for gap in scope["gaps"])
    negative_search_gaps = any(scope["gaps"] and any(row["aggregation_included"] and not row.get("candidate_id")
        and scope_key(row)[:2] == (scope["jurisdiction"], scope["right_type"]) for row in rows) for scope in coverage)
    if highest in {"低", "极低"} and (missing_assessments or negative_search_gaps):
        cap = "低"
        cap_reasons.append("存在尚未评价的适用范围、候选或负面检索覆盖缺口；具体候选的高置信排除不能外推为整个产品的高置信低风险。")
    driver_module_caps = [(module_caps or {}).get(row["module_id"], {}).get("confidence", "高") for row in drivers]
    for module in sorted({row["module_id"] for row in drivers} & set(module_caps or {})):
        module_cap = module_caps[module]
        if CONFIDENCES.index(module_cap["confidence"]) < CONFIDENCES.index(cap):
            cap_reasons.append("主导风险模块的置信度限制：" + module_cap["reasoning"])
    cap = min([cap, *driver_module_caps], key=CONFIDENCES.index)
    confidence = min([cap, *[row["evidence_confidence"] for row in drivers], *driver_module_caps], key=CONFIDENCES.index)
    supplemental = {}
    for name in ("future_applications", "enforcement_signals"):
        supplemental[name] = list({sha256_json(row): deepcopy(row) for review in (first, second) for row in review.get(name, [])}.values())
    complete = not strict or (bool(coverage) and bool(included) and not completion_gaps
                             and not ledger_gaps and all(not scope["gaps"] for scope in coverage))
    if strict and not complete:
        overall_reasons = ["本阶段尚未完成必要检索或证据比较，不对整个任务给出最终风险等级。",
                           "已取得具体证据的局部风险单独保留；未执行、失败和截断不是零结果，也不是降低风险的证据。"]
    scoped_highest = max((row["risk"] for row in included), key=RISKS.index, default=None)
    result = {
        "schema_version": SCHEMA, "assessment_contract": CONTRACT, "assessment_policy": POLICY,
        "task_id": task["task_id"], "generated_at": generated_at or now_iso(), "status": "completed" if complete else "incomplete",
        "overall": {"risk": highest if complete else None, "confidence": confidence, "coverage_confidence_cap": cap,
                    "coverage_confidence_reasoning": cap_reasons,
                    "drivers": [{field: row.get(field) for field in ("jurisdiction", "right_type", "candidate_id", "module_id", "title", "risk", "evidence_confidence")} for row in drivers],
                    "provisional": True, "all_scope_clearance": False,
                    "overall_decisive_exclusion": deepcopy(overall_decisive),
                    "reasons": overall_reasons,
                    "report_lead": f"{highest}风险／{confidence}置信度" if complete else "阶段性报告：整项排查尚未完成" + (f"；已评范围最高为{scoped_highest}风险" if scoped_highest else "；尚无具备评级依据的当前结论"),
                    "report_summary": " ".join(overall_reasons)},
        "assessments": rows, "coverage": {"scopes": coverage,
            "notes": [*(supplement or {}).get("coverage_notes", []), *ledger_gaps]},
        "review": {"required": True, "human_review_required": False, "evidence_digest": digest,
                   "evidence_root": str(Path(evidence_root).resolve()) if evidence_root else None,
                   "first_reviewer": first["reviewer"], "second_reviewer": second["reviewer"],
                   "input_reviews": {"first": deepcopy(first), "second": deepcopy(second), "adjudication": deepcopy(adjudication)}},
        "input_binding": {"evidence_root": str(Path(evidence_root).resolve()) if evidence_root else None, "evidence_digest": digest},
        "supplement": deepcopy(supplement),
        "supplement_provenance": {"validation": "retained_file_hashes_verified", "adapter_acceptance_claimed": False,
                                  "evidence_count": len(supplemental_index)},
        "paid_recommendations": [], **supplemental,
        **({"module_confidence_caps": deepcopy(module_caps)} if module_caps is not None else {}),
    }
    if strict:
        result["screening_revision"] = task["screening_revision"]
        result["overall"]["known_scoped_risk"] = scoped_highest
        result["overall"]["known_scoped_confidence"] = confidence if included else None
        result["overall"]["business_completion"] = "complete" if complete else "incomplete"
        result["coverage"]["completion_gaps"] = completion_gaps
        result["coverage"]["execution_gaps"] = execution_gaps
        result["coverage"]["notes"].extend(completion_gaps)
    return result


def report_input_context(task_dir, task, output_dir):
    """Use the finalized output task and its frozen source for both report CLIs."""
    task_dir, output_dir = Path(task_dir).resolve(), Path(output_dir).resolve()
    if task.get("assessment_policy") not in (None, POLICY):
        raise ValueError("REPORT_TASK_POLICY_CONFLICT")
    saved_path = output_dir / "task.json"
    effective = ensure_object(load_json(saved_path), "output task") if saved_path.is_file() else task
    if (effective.get("task_id") != task.get("task_id")
            or effective.get("assessment_policy") not in (None, POLICY)):
        raise ValueError("REPORT_OUTPUT_TASK_IDENTITY_CONFLICT")
    effective = {**effective, "assessment_policy": POLICY}
    source = Path(effective.get("outputs", {}).get("assessment_input_dir") or task_dir).resolve()
    if task_dir not in (source, output_dir):
        raise ValueError("REPORT_SOURCE_DIRECTORY_CONFLICT")
    return source, effective


def resolve_estimate_supplement(task_dir, task, explicit_path=None):
    """Explicit input wins; a present default is never silently discarded."""
    if explicit_path is not None:
        return Path(explicit_path).expanduser().resolve()
    default = Path(task_dir).resolve() / "supplemental-evidence.json"
    return default if _correction_enabled(task) and (default.exists() or default.is_symlink()) else None


_VERIFIED_CONTEXT_TOKEN = object()


class VerifiedAssessmentContext:
    """Single-use, in-process result of a real assessment computation.

    It cannot be loaded from a saved report. Mutable Python values are sealed
    and checked immediately before consumption, as are the source file bytes.
    """
    __slots__ = ("inputs", "assessment", "output_task", "_source", "_destination",
                 "_source_hashes", "_digest", "_consumed")

    def __init__(self, token, inputs, assessment, output_task, source, destination, source_hashes):
        if token is not _VERIFIED_CONTEXT_TOKEN:
            raise ValueError("VERIFIED_ASSESSMENT_CONTEXT_REQUIRED")
        self.inputs, self.assessment, self.output_task = inputs, assessment, output_task
        self._source, self._destination = Path(source).resolve(), Path(destination).resolve()
        self._source_hashes = dict(source_hashes)
        self._digest = sha256_json((inputs, assessment, output_task))
        self._consumed = False

    def validate(self, *, task_dir=None, output_dir=None):
        if ((task_dir is not None and Path(task_dir).resolve() != self._source)
                or (output_dir is not None and Path(output_dir).resolve() != self._destination)):
            raise ValueError("VERIFIED_ASSESSMENT_CONTEXT_DIRECTORY_MISMATCH")
        if sha256_json((self.inputs, self.assessment, self.output_task)) != self._digest:
            raise ValueError("VERIFIED_ASSESSMENT_CONTEXT_MUTATED")
        for path, expected in self._source_hashes.items():
            actual = sha256_file(path) if path.is_file() else None
            if actual != expected:
                raise ValueError("VERIFIED_ASSESSMENT_SOURCE_CHANGED: " + str(path))
        return self

    def consume(self, *, task_dir=None, output_dir=None):
        if self._consumed:
            raise ValueError("VERIFIED_ASSESSMENT_CONTEXT_ALREADY_CONSUMED")
        self.validate(task_dir=task_dir, output_dir=output_dir)
        self._consumed = True
        return self


def finalize(task_dir, task, first_path, second_path=None, *, adjudication_path=None,
             supplement_path=None, output_dir=None, evidence_root=None,
             return_context=False, publication_mode=None, stop_reason=None) -> dict[str, Any] | VerifiedAssessmentContext:
    task_dir = Path(task_dir).resolve()
    destination = Path(output_dir) if output_dir else task_dir
    source_hashes = {}
    def read_object(path, label):
        path = Path(path).expanduser().resolve()
        raw = path.read_bytes()
        source_hashes[path] = hashlib.sha256(raw).hexdigest()
        return ensure_object(json.loads(raw), label)
    source_task_path = task_dir / "task.json"
    if return_context:
        saved_task = read_object(source_task_path, "task.json")
        allowed_task = {**saved_task, "assessment_policy": POLICY} if saved_task.get("assessment_policy") is None else saved_task
        if allowed_task != task:
            raise ValueError("VERIFIED_ASSESSMENT_TASK_NOT_LOADED_FROM_SOURCE")
    evidence = read_object(task_dir / "evidence.json", "evidence.json")
    candidates = read_object(task_dir / "normalized-candidates.json", "normalized-candidates.json")
    plan = read_object(task_dir / "search-plan.json", "search-plan.json")
    ledger_path = task_dir / "materiality-annotations.json"
    if return_context:
        source_hashes[ledger_path] = sha256_file(ledger_path) if ledger_path.is_file() else None
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    first = read_object(first_path, "first review")
    second = read_object(second_path, "second review") if second_path else None
    adjudication = read_object(adjudication_path, "adjudication") if adjudication_path else None
    supplement_file = resolve_estimate_supplement(task_dir, task, supplement_path)
    supplement = read_object(supplement_file, "supplement") if supplement_file is not None else None
    if return_context and supplement_path is None and supplement_file is None and _correction_enabled(task):
        source_hashes[task_dir / "supplemental-evidence.json"] = None
    root = evidence_root or task.get("evidence_root") or (task.get("historical_evidence_root") if _correction_enabled(task) else None) or task_dir
    journal = None
    if return_context:
        journal_path = task_dir / "browser-candidate-journal.json"
        if journal_path.is_file():
            journal = read_object(journal_path, "browser candidate journal")
        else:
            source_hashes[journal_path] = None
            journal = {"schema_version": "1.0", "task_id": task["task_id"], "entries": []}
    assessment = compute_assessment(task, evidence, candidates, plan, ledger, first, second, adjudication,
                                    supplement=supplement, evidence_root=root, task_dir=task_dir)
    from necessary_completion import enabled as completion_enabled, publication_context
    snapshots = {}
    if completion_enabled(task):
        for name in ("source-capabilities.json", "browser-execution-status.json"):
            path = task_dir / name
            if path.is_file():
                snapshots[name] = read_object(path, name)
            elif return_context:
                source_hashes[path] = None
    publication = publication_context(task, evidence, candidates, plan, ledger, assessment,
        mode=publication_mode, stop_reason=stop_reason, snapshots=snapshots,
        task_dir=task_dir, evidence_root=root)
    if publication is not None:
        assessment["completion_policy_revision"] = task["completion_policy_revision"]
        assessment["publication"] = publication
    if return_context:
        for path, expected in source_hashes.items():
            if (sha256_file(path) if path.is_file() else None) != expected:
                raise ValueError("VERIFIED_ASSESSMENT_SOURCE_CHANGED: " + str(path))
    output_task = deepcopy(task)
    add_history(output_task, assessment["status"],
                "evidence-estimate-v1: stage report retained; business screening incomplete"
                if assessment["status"] == "incomplete" else
                "evidence-estimate-v1: five-level estimate finalized; source and review integrity verified")
    output_task.setdefault("outputs", {})["assessment_json"] = str(destination / "assessment.json")
    output_task["outputs"]["assessment_input_dir"] = str(task_dir.resolve())
    atomic_write_json(destination / "assessment.json", assessment)
    atomic_write_json(destination / "task.json", output_task)
    if destination.resolve() == task_dir.resolve():
        task.clear()
        task.update(output_task)
    if return_context:
        source_hashes[destination.resolve() / "task.json"] = sha256_file(destination / "task.json")
        source_hashes[destination.resolve() / "assessment.json"] = sha256_file(destination / "assessment.json")
        return VerifiedAssessmentContext(_VERIFIED_CONTEXT_TOKEN,
            {"task": task, "evidence": evidence, "candidates": candidates, "plan": plan, "ledger": ledger, "journal": journal},
            assessment, output_task, task_dir, destination, source_hashes)
    return assessment


def validate_assessment(task_dir, task, assessment, *, evidence_root=None) -> list[str]:
    """Recompute with stored original reviewer inputs; never trust edited grades."""
    try:
        source = Path(task.get("outputs", {}).get("assessment_input_dir") or task_dir)
        reviews = assessment["review"]["input_reviews"]
        evidence = load_json(source / "evidence.json")
        candidates = load_json(source / "normalized-candidates.json")
        plan = load_json(source / "search-plan.json")
        ledger = load_materiality_ledger(source, task["task_id"], task=task)
        root = evidence_root or assessment["review"].get("evidence_root")
        expected = compute_assessment(task, evidence, candidates, plan, ledger, reviews["first"], reviews.get("second"),
            reviews.get("adjudication"), supplement=assessment.get("supplement"),
            evidence_root=root,
            generated_at=assessment["generated_at"], task_dir=source)
        from necessary_completion import restore_publication
        restore_publication(task, evidence, candidates, plan, ledger, expected, assessment,
            task_dir=source, evidence_root=root)
        return [] if expected == assessment else ["ASSESSMENT_CANONICAL_RECOMPUTATION_MISMATCH"]
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return ["ASSESSMENT_RECOMPUTATION_FAILED: " + str(exc)]

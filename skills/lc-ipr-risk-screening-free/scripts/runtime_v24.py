"""Capability-aware execution: missing optional accounts never block other work."""
from __future__ import annotations

import subprocess
import os
import time
import math
import threading
from datetime import datetime, timezone
from execution_lock import execution_lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from copy import deepcopy
from typing import Any

from common import (add_gap, add_history, assert_active_free_policy,
                    assert_default_discovery_plan_contract, atomic_write_json,
                    credential, coverage_routes, load_json, load_skill_config,
                    now_iso, plan_free_policy_matches_task, resolve_retained_path, sha256_file, sha256_json, stable_id,
                    serper_free_enabled, signa_free_enabled, serpapi_free_enabled)
from provider_utils import PLAN_META_KEYS, ProviderError, evidence_lock, record_error

API_CLIENTS = {"epo_ops", "euipo_trademark", "euipo_design", "jpo_api", "inpi_api",
               "epo_publication_server", "serper_patents", "serper_web", "serper_images",
               "signa", "serpapi_google_patents", "serpapi_google_lens"}
CREDENTIALS = {
    "epo_ops": ("epo_consumer_key", "epo_consumer_secret"),
    "euipo_trademark": ("euipo_client_id", "euipo_client_secret"),
    "euipo_design": ("euipo_client_id", "euipo_client_secret"),
    "jpo_api": ("jpo_api_username", "jpo_api_password"),
    "inpi_api": ("inpi_username", "inpi_password"),
    "serper_patents": ("serper_api_key",), "serper_web": ("serper_api_key",), "serper_images": ("serper_api_key",),
    "signa": ("signa_api_key",), "serpapi_google_patents": ("serpapi_api_key",), "serpapi_google_lens": ("serpapi_api_key",),
}


def capabilities(task: dict, config: dict) -> list[dict]:
    providers = {r["provider"] for r in coverage_routes(task)} | {"epo_publication_server", "asset_provenance"}
    for enabled, names in ((serper_free_enabled(task), ("serper_patents", "serper_web", "serper_images")),
                           (signa_free_enabled(task), ("signa",)),
                           (serpapi_free_enabled(task), ("serpapi_google_patents", "serpapi_google_lens"))):
        if enabled:
            providers.update(names)
    resolved = {key: bool(credential(config, key)) for key in set(k for p in providers for k in CREDENTIALS.get(p, ()))}
    results = []
    for provider in sorted(providers):
        present = all(resolved[k] for k in CREDENTIALS.get(provider, ()))
        if provider == "asset_provenance" and task.get("specialty_workflow_revision") == "asset-scope-v1":
            state, reason, executable = "unvalidated", "agent_investigation_queue_required_not_an_api", False
        elif provider in {"epo_publication_server", "asset_provenance"}:
            state, reason, executable = "automatic", "free_public_document_or_agent_evidence", True
        elif provider in API_CLIENTS:
            state, reason, executable = ("unvalidated", "first_real_query_checks_free_account_and_contract", True) if present else ("unavailable", "optional_credentials_missing", False)
            from common import api_first_revision_enabled
            if provider.startswith("serper_") and present and not api_first_revision_enabled(task.get("retrieval_workflow_revision")):
                state, reason, executable = "unvalidated", "free_entitlement_unvalidated", False
        elif provider in {"epo_register_browser", "jplatpat_browser", "euipo_esearch_browser", "tmview_browser", "designview_browser"} or provider.startswith("wipo"):
            state, reason, executable = "unavailable", "automation_policy_incompatible", False
        else:
            state, reason, executable = "unvalidated", "browser_adapter_requires_real_route_acceptance", False
        results.append({"provider": provider, "state": state, "reason": reason, "executable": executable,
                        "credentials_present": present if provider in CREDENTIALS else None,
                        "checked_at": now_iso(), "cost_ceiling_usd": 0,
                        "human_actions": ["login", "captcha", "mfa", "consent", "qr"], "manual_business_work": False})
    from source_operation import enabled as operation_review_enabled
    if operation_review_enabled(task):
        from source_operation_registry import operations_for, current_entries
        for capability in results:
            states = current_entries(capability['provider'])
            if states:
                capability['operation_states'] = states
            accepted = operations_for(capability['provider'])
            if accepted:
                capability['operations'] = accepted
    return results


def operation_accepted(capability, row):
    """Acceptance is exact to the operation and compiler, not provider-wide."""
    keys = ("jurisdiction", "right_type", "operation", "query_compiler_revision", "search_dimension")
    return any(all(operation.get(key, "") == row.get(key, "") for key in keys)
               for operation in (capability or {}).get("operations", []))


def resolved_capabilities(task, evidence, plan, source_capabilities, task_dir, *, browser_status=None):
    """Derive exact, receipt-backed operation acceptance without upgrading a site.

    Frozen callers supply all status inputs. This does not read credentials,
    mutate preflight snapshots, or claim official coverage/current legal status.
    """
    from completion_policy import evidence_delivery_enabled
    result = deepcopy(source_capabilities or {})
    if not evidence_delivery_enabled(task):
        return result
    registry_snapshots = {provider: cap.get('operations', []) for provider, cap in result.items()}
    state_snapshots = {provider: cap.get('operation_states', []) for provider, cap in result.items()}
    for cap in result.values():
        cap.pop("operations", None)  # Revalidate, never trust a saved derived assertion.
        cap.pop("operation_states", None)
    from source_operation import enabled as operation_review_enabled, accepted_operations, rejected_operation_keys
    if operation_review_enabled(task):
        from source_operation_registry import retained_operations, retained_states, latest_states
        for provider, cap in result.items():
            states = retained_states(provider, state_snapshots.get(provider, []))
            if states:
                cap['operation_states'] = states
            accepted = retained_operations(provider, registry_snapshots.get(provider, []))
            if accepted:
                cap['operations'] = accepted
        if task_dir is not None and evidence.get('task_id') == task.get('task_id') \
                and plan.get('task_id') == task.get('task_id'):
            rejected = rejected_operation_keys(task, plan, evidence, task_dir)
            for provider, cap in result.items():
                cap['operations'] = [operation for operation in cap.get('operations', [])
                    if (provider, *(operation.get(key, '') for key in
                        ('jurisdiction', 'right_type', 'operation', 'query_compiler_revision', 'search_dimension'))) not in rejected]
            for provider, operations in accepted_operations(task, plan, evidence, task_dir).items():
                if provider in result:
                    combined = [*result[provider].get('operations', []), *operations]
                    result[provider]['operations'] = sorted(combined, key=sha256_json)
        for provider, cap in result.items():
            states = latest_states(provider)
            cap['operations'] = [operation for operation in cap.get('operations', [])
                if states.get(tuple(operation.get(key, '') for key in
                    ('jurisdiction', 'right_type', 'operation', 'query_compiler_revision', 'search_dimension')),
                    'automatic') == 'automatic']
        return result
    if task_dir is None or not isinstance(browser_status, dict):
        return result
    if any(value.get("task_id") != task.get("task_id") for value in (evidence, plan, browser_status)):
        return result
    from run_browser_plan import completed_capture
    from assessment_v24 import NON_PRODUCTION
    root = Path(task_dir).resolve()
    indexes = {}
    for provider, rows in plan.get("queries", {}).items():
        for row in rows:
            indexes.setdefault(row.get("query_id"), []).append((provider, row))
    for saved in browser_status.get("queries", []):
        matches = indexes.get(saved.get("query_id"), [])
        if len(matches) != 1:
            continue
        provider, row = matches[0]
        if provider not in result or not completed_capture(root, task, provider, row, saved):
            continue
        runs = [run for run in evidence.get("source_runs", [])
            if run.get("provider") == provider and run.get("query_id") == row.get("query_id")
            and run.get("plan_entry_sha256") == sha256_json(row)
            and run.get("operation") == row.get("operation")
            and run.get("jurisdiction") == row.get("jurisdiction")
            and run.get("right_type") == row.get("right_type")
            and run.get("status") in {"success", "no_result"}
            and run.get("submission_state") == "submitted"
            and not run.get("fixture") and not run.get("test_only")
            and str(run.get("source_environment") or "").casefold() not in
                NON_PRODUCTION | {"unit_test_only", "non_production", "synthetic", "offline"}
            and source_files_complete(root, evidence, run)]
        if not runs:
            continue
        run = runs[-1]
        operation = {key: row.get(key, "") for key in (
            "jurisdiction", "right_type", "operation", "query_compiler_revision", "query_id")}
        operation.update(plan_entry_sha256=sha256_json(row), source_run_id=run["run_id"],
                         source_run_sha256=sha256_json(run))
        accepted = result[provider].setdefault("operations", [])
        if operation not in accepted:
            accepted.append(operation)
    for cap in result.values():
        if "operations" in cap:
            cap["operations"].sort(key=sha256_json)
    return result


def preflight_credentials(task_dir: Path) -> str:
    from auth_gate import require_auth, safe_failure_message
    from preflight import credential_storage_checkpoint
    task = load_json(task_dir / "task.json")
    assert_active_free_policy(task)
    if task.get("state") not in {"pending", "preflight_credentials", "incomplete", "needs_user_action"}:
        raise ValueError("Credential preflight is not available in this task state")
    task.setdefault("checkpoints", {})["credential_storage"] = credential_storage_checkpoint()
    atomic_write_json(task_dir / "task.json", task)
    try:
        require_auth()  # Existing skill licence; independent from IP data accounts.
    except SystemExit as exc:
        auth_detail = safe_failure_message(exc)
        add_gap(task, "cloud_auth", "GLOBAL", "access_limited", "AUTH_FAILED", auth_detail)
        add_history(task, "incomplete", auth_detail)
        atomic_write_json(task_dir / "task.json", task)
        raise SystemExit(auth_detail) from None
    source_capabilities = capabilities(task, load_skill_config())
    atomic_write_json(task_dir / "source-capabilities.json", {"schema_version": "2.4-free", "task_id": task["task_id"], "sources": source_capabilities})
    task["checkpoints"]["credential_preflight"] = {"status": "success", "at": now_iso(), "source_capabilities": "source-capabilities.json", "note": "Optional provider accounts are capabilities, not startup prerequisites"}
    from product_entry import enabled as entry_enabled
    user_entry = entry_enabled(task) and task["request"]["entry_type"] == "user_materials"
    add_history(task, "awaiting_browser", "Licence checked; retain supplied product materials" if user_entry else "Licence checked; agent may collect product and use available free routes")
    atomic_write_json(task_dir / "task.json", task)
    return "awaiting_browser"


def preflight_evidence(task_dir: Path) -> str:
    task, evidence = load_json(task_dir / "task.json"), load_json(task_dir / "evidence.json")
    assert_active_free_policy(task)
    product = task.get("product", {})
    errors = []
    if task.get("checkpoints", {}).get("credential_preflight", {}).get("status") != "success":
        errors.append("Credential preflight is missing")
    from product_entry import enabled as entry_enabled, evidence_errors
    new_entry = entry_enabled(task)
    if new_entry:
        errors.extend(evidence_errors(task, evidence, task_dir))
    elif not product.get("actual_asin") or product.get("actual_asin") != product.get("requested_asin") or product.get("variant", {}).get("confirmed") is not True:
        errors.append("Product ASIN and current variant are not confirmed")
    images = task.get("images", [])
    if not images and (not new_entry or task["request"]["entry_type"] == "amazon_url"):
        errors.append("Product image evidence is missing")
    for image in images:
        try:
            path = (resolve_retained_path(task_dir, str(image.get("path") or ""),
                    expected_sha256=image.get("sha256", ""), expected_bytes=image.get("bytes"))
                    if new_entry else Path(str(image.get("path") or "")))
            if not path.is_file() or image.get("sha256") != sha256_file(path):
                errors.append("Product image is absent or changed")
        except (ValueError, OSError):
            errors.append("Product image is absent or changed")
    if not new_entry and not any(r.get("provider") == "amazon_browser" and r.get("status") == "success" for r in evidence.get("source_runs", [])):
        errors.append("Accepted Amazon capture is missing")
    if errors:
        task.setdefault("errors", []).extend({"at": now_iso(), "code": "PRODUCT_EVIDENCE_INCOMPLETE", "detail": message} for message in errors)
        add_history(task, "incomplete", "; ".join(errors))
    else:
        task.setdefault("checkpoints", {})["evidence_preflight"] = {"status": "success", "at": now_iso()}
        add_history(task, "collecting", "Product identity accepted; view sufficiency and intended-product match remain separate assessment criteria")
    atomic_write_json(task_dir / "task.json", task)
    return task["state"]


def record_gap(task_dir: Path, provider: str, row: dict, code: str, detail: str, *, submission_state: str = "unknown") -> dict:
    evidence_type = "official_verification" if row["operation"] == "candidate_verification" else "trademark" if row.get("right_type", "").startswith("trademark") else "copyright" if row.get("right_type") == "copyright" else "patent"
    return record_error(task_dir, provider=provider, operation=row["operation"], query=row.get("q", ""),
                        jurisdiction=row.get("jurisdiction", ""), evidence_type=evidence_type,
                        error_value=ProviderError(code, "access_limited", detail), mandatory=False,
                        submission_state=submission_state,
                        request_params={**{k: v for k, v in row.items() if k not in PLAN_META_KEYS}, "right_type": row.get("right_type", "")}, query_id=row["query_id"])


def api_execution_lock(task_dir: Path):
    return execution_lock(task_dir, "api")


def source_files_complete(task_dir: Path, evidence: dict, run: dict) -> bool:
    """Resume only an actual retained response plus every declared payload file."""
    try:
        paths = run.get("raw_paths", [])
        if len(paths) != 1 or not run.get("payload_digest"):
            return False
        for raw in paths:
            path = resolve_retained_path(task_dir, raw, expected_sha256=run["payload_digest"])
            if sha256_file(path) != run["payload_digest"]:
                return False
        def intact(value):
            if isinstance(value, dict):
                if value.get("path") and value.get("sha256"):
                    path = resolve_retained_path(task_dir, value["path"], expected_sha256=value["sha256"], expected_bytes=value.get("bytes"))
                    if sha256_file(path) != value["sha256"] or (value.get("bytes") is not None and path.stat().st_size != value["bytes"]):
                        return False
                return all(intact(item) for item in value.values())
            return all(intact(item) for item in value) if isinstance(value, list) else True
        linked = [entry for collection in evidence.get("collections", {}).values()
                  if isinstance(collection, list) for entry in collection
                  if isinstance(entry, dict) and entry.get("source_run_id") == run.get("run_id")]
        # Product capture is bound through task.product and its retained raw
        # capture rather than a discovery collection row.
        if run.get("status") == "success" and not linked and run.get("operation") != "product_capture":
            return False
        return all(intact(entry) for entry in linked)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def source_fresh(run: dict, max_age_hours: float = 48) -> bool:
    # Only immutable publication documents may outlive a task's 48-hour recall window.
    if run.get("provider") == "epo_publication_server" and run.get("operation") == "document_retrieval":
        return True
    try:
        checked = datetime.fromisoformat(str(run.get("finished_at", "")).replace("Z", "+00:00"))
        if checked.tzinfo is None:
            return False
        age = (datetime.now(timezone.utc) - checked).total_seconds()
        return 0 <= age <= max_age_hours * 3600
    except (TypeError, ValueError):
        return False


def _lane(provider: str) -> str:
    # Fallback must run after Serper in the same lane, and shared accounts must
    # never race their own endpoints. Account reservation lives in each client.
    # Keep Serper and SerpApi in one dependency lane: patent fallback must see
    # the completed upstream response, and endpoints sharing either account
    # must not race quota reservations.  Independent official providers still
    # run in their own lanes.
    if provider.startswith(("serper_", "serpapi_")):
        return "discovery"
    return "euipo" if provider.startswith("euipo_") else provider


def _physical_request_identity(provider: str, row: dict[str, Any]) -> dict[str, Any] | None:
    """Return actual wire identity only for audited request shapes.

    Logical right/scenario metadata is intentionally absent.  Reuse remains
    country-bound and creates a separate, explicitly linked logical record.
    """
    if provider == "serpapi_google_lens":
        keys = ("q", "image_url", "type", "hl", "country")
        return {"provider": provider, "operation": row.get("operation"),
                "jurisdiction": row.get("jurisdiction"),
                "params": {key: row.get(key) for key in keys}}
    return None


def physical_response_source(task_dir: Path, evidence: dict, run: dict) -> dict | None:
    """Verify one logical Lens reuse against its unchanged physical receipt.

    Consumers may use the original request/acceptance through this proof;
    the logical run itself remains explicitly not submitted.
    """
    proof = run.get('metadata', {}).get('physical_response_reuse')
    if not isinstance(proof, dict) or run.get('provider') != 'serpapi_google_lens':
        return None
    originals = [source for source in evidence.get('source_runs', [])
                 if source.get('run_id') == proof.get('source_run_id')]
    if len(originals) != 1:
        return None
    source = originals[0]
    if (source.get('provider') != run.get('provider')
            or source.get('status') not in {'success','no_result'}
            or source.get('submission_state') != 'submitted'
            or (source.get('quota') or {}).get('network_request_attempted') is not True
            or source.get('metadata', {}).get('physical_response_reuse')
            or proof.get('source_run_sha256') != sha256_json(source)
            or proof.get('independent_source_count') != 1
            or proof.get('network_request_attempted') is not False
            or run.get('submission_state') != 'not_submitted'
            or run.get('source_query_performed') is not False
            or (run.get('quota') or {}).get('network_request_attempted') is not False):
        return None
    provider = run['provider']
    original_identity = _physical_request_identity(provider, {
        **(source.get('request_params') or {}), 'operation':source.get('operation'),
        'jurisdiction':source.get('jurisdiction')})
    reuse_identity = _physical_request_identity(provider, {
        **(run.get('request_params') or {}), 'operation':run.get('operation'),
        'jurisdiction':run.get('jurisdiction')})
    if (original_identity != reuse_identity or proof.get('request_identity_sha256') != sha256_json(original_identity)
            or proof.get('source_finished_at') != source.get('finished_at')
            or any(run.get(key) != source.get(key) for key in
                   ('started_at','finished_at','raw_paths','payload_digest','status','data_date'))):
        return None
    try:
        plan = load_json(task_dir / 'search-plan.json')
        rows = [row for row in plan.get('queries', {}).get(provider, [])
                if row.get('query_id') == run.get('query_id')]
        if len(rows) != 1 or run.get('plan_entry_sha256') != sha256_json(rows[0]):
            return None
        if any(run.get(key) != rows[0].get(key) for key in ('operation','jurisdiction','right_type')):
            return None
        current_params = {key:value for key,value in rows[0].items() if key not in PLAN_META_KEYS}
        current_params['right_type'] = rows[0].get('right_type', '')
        if run.get('request_params') != current_params:
            return None
        if not source_files_complete(task_dir,evidence,source) or not source_files_complete(task_dir,evidence,run):
            return None
    except (OSError, ValueError, TypeError, KeyError):
        return None
    return source


def _reuse_physical_response(task_dir: Path, provider: str, row: dict[str, Any], max_age_hours: float,
                             *, authorized_task=None, authorized_params=None) -> dict[str, Any] | None:
    identity = _physical_request_identity(provider, row)
    if identity is None or not math.isfinite(max_age_hours) or max_age_hours <= 0:
        return None
    # Reuse is still a current, authorized action. It neither authorizes a
    # missing image permission nor consumes another provider request.
    if authorized_task is None:
        from provider_plan_v24 import load_action
        authorized_task, planned, authorized_params = load_action(task_dir, provider, row['query_id'], {'image_search'})
        if planned != row:
            raise ProviderError('SCENARIO_PLAN_ROW_CHANGED', 'failed', 'Reuse requires the current exact plan row')
    from serpapi_lens_client import public_product_image, retained_source_records, normalize
    from product_delivery import validate_image_query
    public_product_image(authorized_task, row)
    image_reason = validate_image_query(authorized_task, provider, row)
    if image_reason:
        raise ProviderError(image_reason, 'failed', 'Reuse requires the current permitted product image')
    with evidence_lock(task_dir):
        evidence_path = task_dir / "evidence.json"
        evidence = load_json(evidence_path)
        source = None
        for run in reversed(evidence.get("source_runs", [])):
            if (run.get('provider') != provider or run.get("status") not in {"success", "no_result"}
                    or run.get("query_id") == row.get("query_id")
                    or run.get('submission_state') != 'submitted'
                    or (run.get('quota') or {}).get('network_request_attempted') is not True
                    or run.get('metadata', {}).get('physical_response_reuse')):
                continue
            run_row = {**(run.get("request_params") or {}), "operation": run.get("operation"),
                       "jurisdiction": run.get("jurisdiction")}
            if (_physical_request_identity(provider, run_row) == identity
                    and source_files_complete(task_dir, evidence, run)
                    and source_fresh(run, max_age_hours)):
                try:
                    retained_source_records(evidence, run, task_dir)
                except (OSError, ValueError, TypeError, KeyError):
                    continue
                source = run
                break
        if source is None:
            return None
        checked_at = now_iso()
        digest = sha256_json(row)
        run_id = stable_id("ATT-REUSE", row["query_id"], source["run_id"], digest)
        already = next((run for run in evidence.get('source_runs', []) if run.get('run_id') == run_id), None)
        if already is not None:
            return already if physical_response_source(task_dir, evidence, already) is not None else None
        raw_path = resolve_retained_path(task_dir, source['raw_paths'][0], expected_sha256=source['payload_digest'])
        normalized = normalize(load_json(raw_path), retrieval_workflow_revision=authorized_task.get('retrieval_workflow_revision'),
                               investigation_right_type=str(row.get('right_type') or ''))
        reused = deepcopy(source)
        reused.update(run_id=run_id, attempt_id=run_id, query_id=row["query_id"],
                      jurisdiction=row["jurisdiction"], right_type=row.get("right_type"),
                      requirement_ids=deepcopy(row.get("requirement_ids", [])),
                      query=row.get('q', ''), request_params=deepcopy(authorized_params),
                      plan_entry_sha256=digest,
                      submission_state="not_submitted", source_query_performed=False)
        # Keep original collection/request dates. A new logical binding is not
        # a fresh query and cannot extend the dynamic material's lifetime.
        reused['quota'] = {'network_request_attempted': False, 'physical_response_reused': True}
        from common import DECISION_PLAN_META_KEYS
        current_meta = DECISION_PLAN_META_KEYS | {'search_dimension','search_language','execution_phase','publication_scope'}
        for key in current_meta:
            reused.setdefault('metadata', {}).pop(key, None)
        reused['metadata'].update({key:deepcopy(row[key]) for key in current_meta if key in row})
        reused.setdefault("metadata", {})["physical_response_reuse"] = {
            "source_run_id": source["run_id"], "source_run_sha256": sha256_json(source),
            "request_identity_sha256": sha256_json(identity),
            "source_finished_at": source.get('finished_at'), 'bound_at': checked_at,
            "independent_source_count": 1, 'network_request_attempted': False,
        }
        evidence.setdefault("source_runs", []).append(reused)
        for collection in evidence.get("collections", {}).values():
            if not isinstance(collection, list):
                continue
            originals = [item for item in collection if isinstance(item, dict)
                         and item.get("source_run_id") == source["run_id"]]
            for item in originals:
                copied = deepcopy(item)
                copied.update(evidence_id=stable_id("EV-REUSE", row["query_id"], item["evidence_id"]),
                              source_run_id=run_id, query_id=row["query_id"],
                              jurisdiction=row["jurisdiction"], right_type=row.get("right_type"),
                              requirement_ids=deepcopy(row.get("requirement_ids", [])),
                              query=row.get('q', ''), payload=deepcopy(normalized),
                              plan_entry_sha256=digest,
                              physical_response_reuse={"source_evidence_id": item["evidence_id"],
                                                       'source_run_id':source['run_id'],
                                                       'source_run_sha256':sha256_json(source),
                                                       'source_collected_at':item.get('collected_at'),
                                                       'bound_at':checked_at,
                                                       "independent_source_count": 1})
                from trusted_api import annotate_entry
                annotate_entry(authorized_task, copied, reused)
                collection.append(copied)
        atomic_write_json(evidence_path, evidence)
        return reused


def execute_api_plan(task_dir: Path, *, wave: str = "all", include_optional: bool = False, max_workers: int = 0,
                     query_ids_filter: list[str] | None = None, phase: str = "",
                     skip_final_view: bool = False) -> dict:
    task_dir = task_dir.resolve()
    from execution_budget import execution_budget
    with execution_budget(task_dir, 'sources', inherit=True) as execution_deadline:
        with api_execution_lock(task_dir):
            return _execute_api_plan(task_dir, wave=wave, include_optional=include_optional, max_workers=max_workers,
                query_ids_filter=query_ids_filter, phase=phase, skip_final_view=skip_final_view,
                execution_deadline=execution_deadline)


def _operation_stop_key(task, provider, row):
    """A pass-local circuit key; raw credentials are never saved or returned."""
    from source_operation import operation_acceptance_context
    return (provider, row.get('operation'), row.get('query_compiler_revision', ''),
            sha256_json(operation_acceptance_context(task, provider)))


def _deterministic_operation_fault(task_dir, provider, result, recorded):
    """Stop protocol failures, while an absent individual record stays local."""
    code = str(result.get('error_code') or '').upper()
    if any(marker in code for marker in ('CONTRACT', 'SCHEMA', 'NOT_ACCEPTABLE',
            'NOTACCEPTABLE', 'METHOD_NOT_ALLOWED', 'UNSUPPORTED_MEDIA_TYPE',
            'PROTOCOL', 'API_VERSION')) or code in {'HTTP_405', 'HTTP_406', 'HTTP_415'}:
        return code
    if provider != 'epo_ops':
        return ''
    # OPS often reports only HTTP_ERROR at the client boundary. Read the
    # original fault envelope instead of treating every 404/empty record as a
    # provider failure. This cannot replace the source run or refund its cost.
    from xml.etree import ElementTree
    for run in recorded:
        if run.get('status') in {'success', 'no_result'}:
            continue
        for value in run.get('raw_paths', []):
            try:
                path = resolve_retained_path(task_dir, value,
                    expected_sha256=run.get('payload_digest'))
                root = ElementTree.fromstring(path.read_bytes())
            except (OSError, ValueError, ElementTree.ParseError, TypeError):
                continue
            if root.tag != '{http://ops.epo.org}fault':
                continue
            fault = ' '.join((root.findtext('{http://ops.epo.org}code') or '').split())
            if fault in {'CLIENT.NotAcceptable', 'CLIENT.MethodNotAllowed',
                    'CLIENT.UnsupportedMediaType'}:
                return fault
    return ''


def _retained_operation_stop(task_dir, evidence, result, operation_key):
    """Resume the same circuit only while its original failure proof is intact."""
    proof = result.get('operation_circuit_failure') or result.get('operation_stop')
    if not isinstance(proof, dict) or (proof.get('provider'), proof.get('operation'),
            proof.get('query_compiler_revision', ''), proof.get('context_sha256')) != operation_key:
        return None
    runs = [run for run in evidence.get('source_runs', [])
        if run.get('run_id') == proof.get('source_run_id')]
    if len(runs) != 1 or sha256_json(runs[0]) != proof.get('source_run_sha256'):
        return None
    if _deterministic_operation_fault(task_dir, operation_key[0], runs[0], runs) != proof.get('reason'):
        return None
    return proof


def _execute_api_plan(task_dir: Path, *, wave: str, include_optional: bool, max_workers: int,
                      query_ids_filter: list[str] | None = None, phase: str = "",
                      skip_final_view: bool = False, execution_deadline=None) -> dict:
    from run_api_plan import command_for, completed_result
    from workflow_v24 import (validated_query_cancellation, assert_recall_planning_contract, validated_discovery_followup,
                             scenario_workflow_enabled, reconcile_scenario_actions, scenario_dispatch_block_from_dir,
                             scenario_historical_reuse_from_dir, scenario_fact_reuse_from_dir)
    from workflow_v24 import correction_enabled, TEMPORARY_DISPATCH_CODES, record_action_recovery, work_view_from_dir
    from run_browser_plan import _BatchInputs
    from serpapi_patents_client import fallback_satisfied
    task, plan = load_json(task_dir / "task.json"), load_json(task_dir / "search-plan.json")
    from retrieval_execution import selected_phase, in_phase
    phase = selected_phase(task, phase, "api")
    assert_active_free_policy(task)
    if plan.get("task_id") != task["task_id"] or plan.get("schema_version") != "2.4-free" or not plan_free_policy_matches_task(task, plan):
        raise ValueError("Search plan identity or immutable policy mismatch")
    assert_default_discovery_plan_contract(task, plan, task_dir=task_dir)
    assert_recall_planning_contract(task, plan)
    if scenario_workflow_enabled(task):
        reconcile_scenario_actions(task_dir, task, plan)
        atomic_write_json(task_dir / "search-plan.json", plan)
    def read_evidence():
        value = load_json(task_dir / "evidence.json")
        if value.get("task_id") != task["task_id"] or value.get("schema_version") != task["schema_version"]:
            raise ValueError("API_EVIDENCE_TASK_MISMATCH")
        return value
    read_evidence()
    previous_execution = load_json(task_dir / 'execution-status.json') if (task_dir / 'execution-status.json').is_file() else {}
    prior_results = previous_execution.get('results', []) if previous_execution.get('task_id') == task['task_id'] else []
    config = load_skill_config()
    caps = {r["provider"]: r for r in capabilities(task, config)}
    max_age_hours = float(config.get("performance", {}).get("dynamic_evidence_max_age_hours", 48))
    if not math.isfinite(max_age_hours) or max_age_hours <= 0:
        raise ValueError("dynamic_evidence_max_age_hours must be finite and positive")
    rows = [(p, r) for p, values in plan.get("queries", {}).items() for r in values]
    identifiers = [r["query_id"] for _, r in rows]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate query ID in search plan")
    if query_ids_filter is not None and (not isinstance(query_ids_filter, (list, tuple)) or not query_ids_filter
            or any(not isinstance(q, str) or not q for q in query_ids_filter)
            or len(set(query_ids_filter)) != len(query_ids_filter)
            or not set(query_ids_filter) <= {row["query_id"] for provider, row in rows if provider in API_CLIENTS}):
        raise ValueError("SEARCH_PLAN_INVALID: query-ids must be distinct exact API rows")
    selected_ids = set(query_ids_filter or [])
    if selected_ids and any(row["query_id"] in selected_ids and not in_phase(row, phase) for _, row in rows):
        raise ValueError("SELECTED_QUERY_PHASE_MISMATCH")
    if selected_ids and not include_optional and any(row["query_id"] in selected_ids and not row.get("execute_by_default", False) for _, row in rows):
        raise ValueError("SELECTED_QUERY_NOT_EXECUTABLE: optional API rows require --include-optional")
    results, browser_queue, lanes = [], [], {}
    maximum = max(1, min(int(config.get("performance", {}).get("max_api_concurrency", 3)), 3))
    if max_workers < 0:
        raise ValueError("max_workers must be nonnegative")
    workers = min(max_workers or maximum, maximum)
    started_at, started = now_iso(), time.monotonic()
    write_lock = threading.Lock()
    output = {"schema_version": "2.4-free", "task_id": task["task_id"], "started_at": started_at,
              "status": "running", "workers": workers, "cost_ceiling_usd": 0, "results": results,
              "agent_browser_queue": browser_queue}
    if correction_enabled(task):
        output["selected_query_ids"] = sorted(selected_ids)
    def checkpoint(result):
        with write_lock:
            output.get('pending_submissions', {}).pop(result.get('query_id'), None)
            results.append(result)
            output["updated_at"] = now_iso()
            atomic_write_json(task_dir / "execution-status.json", output)
            with (task_dir / "api-attempts.jsonl").open("a", encoding="utf-8") as log:
                import json
                log.write(json.dumps({"task_id": task["task_id"], **result}, ensure_ascii=False) + "\n")
    for provider, row in rows:
        if selected_ids and row["query_id"] not in selected_ids:
            continue
        if not in_phase(row, phase):
            continue
        if not phase and wave != "all" and not selected_ids and int(row.get("wave", 1)) != int(wave):
            continue
        if not row.get("execute_by_default", False) and not include_optional:
            continue
        if provider not in API_CLIENTS:
            browser_queue.append({"provider": provider, "query_id": row["query_id"], "assigned_to": "agent", "state": "unvalidated", "manual_business_work": False})
            continue
        cancellation = validated_query_cancellation(task, plan, row)
        if cancellation is not None:
            # This is a scheduler disposition, not a response from a source.
            # In particular do not reserve credits, repair/reuse old evidence,
            # append a source_run, or dispatch a provider subprocess.
            checkpoint({"provider": provider, "query_id": row["query_id"],
                        "status": "cancelled", "dispatch": "cancelled",
                        "reason": cancellation["reason"], "plan_entry_sha256": sha256_json(row),
                        "started_at": now_iso(), "finished_at": now_iso(), "elapsed_ms": 0})
            continue
        lanes.setdefault(_lane(provider), []).append((provider, row))
    def run_lane(entries):
        stopped = set()
        stopped_operations = {}
        batch = _BatchInputs(task_dir) if correction_enabled(task) else None
        entries.sort(key=lambda value: value[0].startswith("serpapi_"))
        for provider, row in entries:
            row_started, tick = now_iso(), time.monotonic()
            if execution_deadline is not None and time.time() >= execution_deadline:
                checkpoint({'provider': provider, 'query_id': row['query_id'], 'status': 'incomplete',
                    'dispatch': 'budget_stopped', 'error_code': 'EXECUTION_TIME_BUDGET_EXHAUSTED',
                    'submission_state': 'not_submitted', 'source_query_performed': False})
                continue
            if batch is not None:
                blocked, reused_fact, historical = batch.disposition(provider, row)
            else:
                blocked, reused_fact, historical = scenario_dispatch_block_from_dir(task_dir, provider, row), None, None
            if blocked:
                temporary = correction_enabled(task) and blocked.get("reason") in TEMPORARY_DISPATCH_CODES
                checkpoint({"provider": provider, "query_id": row["query_id"], "status": "awaiting_user" if blocked.get("reason")=="PRODUCT_SCOPE_WAITING" else "awaiting_review" if temporary else "cancelled",
                            "dispatch": "deferred" if temporary else "cancelled", "reason": blocked["reason"], "plan_entry_sha256": sha256_json(row),
                            "submission_state": "not_submitted", "started_at": row_started, "finished_at": now_iso(), "elapsed_ms": 0})
                continue
            if batch is not None and batch.reading_material is not None:
                checkpoint({"provider": provider, "query_id": row["query_id"], "status": "awaiting_review", "dispatch": "agent_read_required",
                    "plan_entry_sha256": sha256_json(row), "submission_state": "not_submitted", "source_query_performed": False,
                    "reading_material": batch.reading_material, "started_at": row_started, "finished_at": now_iso(), "elapsed_ms": 0})
                continue
            if batch is None:
                reused_fact = scenario_fact_reuse_from_dir(task_dir, provider, row)
            if reused_fact is not None:
                checkpoint({"provider": provider, "query_id": row["query_id"], "status": "fact_reused",
                            "dispatch": "fact_reused", "plan_entry_sha256": sha256_json(row),
                            "submission_state": "not_submitted", "source_query_performed": False,
                            "fact_reuse": reused_fact, "started_at": row_started, "finished_at": now_iso(), "elapsed_ms": 0})
                continue
            if batch is None:
                historical = scenario_historical_reuse_from_dir(task_dir, provider, row)
            if historical is not None:
                checkpoint({"provider": provider, "query_id": row["query_id"], "status": "success",
                            "dispatch": "historical_reused", "plan_entry_sha256": sha256_json(row),
                            "submission_state": "not_submitted", "source_query_performed": False,
                            "historical_reuse": historical, "started_at": row_started, "finished_at": now_iso(), "elapsed_ms": 0})
                continue
            evidence = read_evidence()
            digest = sha256_json(row)
            previous = [r for r in evidence.get("source_runs", []) if r.get("query_id") == row["query_id"]
                        and r.get("provider") == provider and r.get("plan_entry_sha256") == digest]
            completed = next((r for r in reversed(previous) if r.get("status") in {"success", "no_result"}
                              and source_files_complete(task_dir, evidence, r) and source_fresh(r, max_age_hours)), None)
            if completed:
                checkpoint({"provider": provider, "query_id": row["query_id"], "status": completed["status"],
                            "source_run_id": completed.get("run_id"), "dispatch": "reused", "elapsed_ms": 0,
                            "started_at": row_started, "finished_at": now_iso(), "plan_entry_sha256": digest})
                continue
            physical = _reuse_physical_response(task_dir, provider, row, max_age_hours)
            if physical is not None:
                checkpoint({"provider": provider, "query_id": row["query_id"], "status": physical["status"],
                            "source_run_id": physical["run_id"], "dispatch": "physical_response_reused",
                            "source_query_performed": False, "submission_state": "not_submitted", "elapsed_ms": 0,
                            "started_at": row_started, "finished_at": now_iso(), "plan_entry_sha256": digest})
                continue
            planned_reuse = row.get('discovery_scope', {}).get('physical_response_plan_reuse')
            if isinstance(planned_reuse, dict):
                parents = [item for item in plan.get('queries', {}).get(provider, [])
                    if item.get('query_id') == planned_reuse.get('query_id')]
                valid_reuse = (provider == 'serpapi_google_lens' and len(parents) == 1
                    and planned_reuse.get('provider') == provider
                    and planned_reuse.get('plan_entry_sha256') == sha256_json(parents[0])
                    and _physical_request_identity(provider, parents[0]) == _physical_request_identity(provider, row)
                    and planned_reuse.get('request_identity_sha256') == sha256_json(_physical_request_identity(provider, row)))
                checkpoint({'provider': provider, 'query_id': row['query_id'],
                    'status': 'awaiting_review', 'dispatch': 'deferred',
                    'reason': 'SOURCE_RESPONSE_REUSE_PENDING' if valid_reuse else 'SOURCE_RESPONSE_REUSE_BINDING_INVALID',
                    'physical_response_plan_reuse': planned_reuse,
                    'plan_entry_sha256': digest, 'submission_state': 'not_submitted',
                    'source_query_performed': False, 'started_at': row_started,
                    'finished_at': now_iso(), 'elapsed_ms': round((time.monotonic() - tick) * 1000)})
                continue
            cap = caps.get(provider, {})
            result = None
            operation_key = _operation_stop_key(task, provider, row)
            operation_stop = stopped_operations.get(operation_key) or next((stop for previous in prior_results
                if isinstance(previous, dict) for stop in [_retained_operation_stop(task_dir, evidence, previous, operation_key)]
                if stop is not None), None)
            if operation_stop and cap.get('executable') and provider not in stopped:
                prior_block = next((run for run in reversed(previous)
                    if run.get('error_code') == 'PROVIDER_OPERATION_STOPPED_THIS_PASS'
                    and run.get('submission_state') == 'not_submitted'), None)
                result = {**(prior_block or record_gap(task_dir, provider, row, 'PROVIDER_OPERATION_STOPPED_THIS_PASS',
                    'A retained deterministic protocol failure stopped this operation; no request was submitted',
                    submission_state='not_submitted')), 'dispatch': 'blocked_reused' if prior_block else 'blocked',
                    'operation_stop': operation_stop}
            elif not cap.get("executable") or provider in stopped:
                code = "FREE_ACCOUNT_UNVERIFIED" if cap.get("reason") == "free_entitlement_unvalidated" else "OPTIONAL_CREDENTIALS_MISSING" if not cap.get("executable") else "PROVIDER_STOPPED_THIS_PASS"
                prior = next((r for r in reversed(previous) if r.get("error_code") == code), None)
                result = ({"provider": provider, "query_id": row["query_id"], "status": "access_limited",
                           "error_code": code, "source_run_id": prior.get("run_id"), "dispatch": "blocked_reused"} if prior else
                          {**record_gap(task_dir, provider, row, code, "Continue other routes; no business work is delegated to the user", submission_state="not_submitted"), "dispatch": "blocked"})
            fallback = row.get("fallback_query_id")
            followup = (validated_discovery_followup(task_dir, task, plan, evidence, row, max_age_hours)
                        if provider == "serpapi_google_patents" and row.get("operation") == "search" else None)
            if result is None and fallback and fallback_satisfied(evidence, row, task_dir=task_dir, task=task, plan=plan):
                result = {"provider": provider, "query_id": row["query_id"], "status": "not_applicable", "dispatch": "fallback_reused"}
            if result is None:
                recorded = []
                client_started = False
                budget = max(1, min(int(config.get("performance", {}).get("api_operation_timeout_seconds", 180)), 180))
                try:
                    inherited_deadline = float(os.environ.get("LC_IPR_OPERATION_DEADLINE_EPOCH", time.time() + budget))
                    if not math.isfinite(inherited_deadline):
                        raise ValueError("OPERATION_DEADLINE_EXCEEDED: invalid inherited deadline")
                    deadline = min(time.time() + budget, inherited_deadline)
                    if execution_deadline is not None:
                        deadline = min(deadline, execution_deadline)
                    if not (0 < deadline - time.time() <= budget):
                        raise ValueError("OPERATION_DEADLINE_EXCEEDED: invalid or expired inherited deadline")
                    environment = {**os.environ, "LC_IPR_OPERATION_DEADLINE_EPOCH": str(deadline),
                                   "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
                    command = command_for(Path(__file__).parent, task_dir, provider, row)
                    old_success = next((r for r in reversed(previous) if r.get("status") in {"success", "no_result"}), None)
                    if provider in {"serpapi_google_patents", "serpapi_google_lens", "signa"} and old_success:
                        reason = "retained_evidence_missing_or_changed" if not source_files_complete(task_dir, evidence, old_success) else "dynamic_evidence_expired"
                        identity = {"provider": provider, "query_id": row["query_id"], "plan_entry_sha256": digest,
                                    "prior_source_run_id": old_success.get("run_id"), "retry_reason": reason}
                        attempt_id = "repair-" + sha256_json(identity)[:24]
                        with write_lock:
                            claim_path = task_dir / "api-retry-claims.json"
                            claims = load_json(claim_path) if claim_path.exists() else {"task_id": task["task_id"], "attempts": {}}
                            if claims.get("task_id") != task["task_id"]:
                                raise ValueError("API_RETRY_CLAIM_TASK_MISMATCH")
                            claims["attempts"].setdefault(attempt_id, {**identity, "created_at": now_iso()})
                            atomic_write_json(claim_path, claims)
                        command += ["--attempt-id", attempt_id, "--retry-reason", reason]
                    with write_lock:
                        recovery = record_action_recovery(task_dir, provider, row)
                    if execution_deadline is not None:
                        with write_lock:
                            output.setdefault('pending_submissions', {})[row['query_id']] = {
                                'provider': provider, 'query_id': row['query_id'],
                                'plan_entry_sha256': digest, 'submission_state': 'unknown'}
                            atomic_write_json(task_dir / 'execution-status.json', output)
                    client_started = True
                    process = subprocess.run(command, capture_output=True,
                                             text=True, encoding="utf-8", check=False,
                                             timeout=max(0.01, deadline - time.time()), env=environment)
                    result = {**completed_result(provider, row, process), "dispatch": "executed"}
                    if recovery:
                        result["recovery_id"] = recovery["recovery_id"]
                    current = read_evidence()
                    recorded = [run for run in current.get("source_runs", []) if run.get("query_id") == row["query_id"]
                                and run.get("provider") == provider and run.get("plan_entry_sha256") == digest
                                and run.get("run_id") not in {old.get("run_id") for old in previous}]
                    if recorded:
                        result.update({key: recorded[-1].get(key) for key in ("status", "error_code")})
                        result['source_run_id'] = recorded[-1].get('run_id')
                    elif result.get("status") not in {"success", "no_result"}:
                        result = {**record_gap(task_dir, provider, row, str(result.get("error_code") or "API_EXECUTION_FAILED"),
                                              str(result.get("stderr") or "Client failed before retaining a plan-bound source run")[:500]), "dispatch": "failed"}
                    if process.returncode and result.get("status") in {"success", "no_result"}:
                        result = {**record_gap(task_dir, provider, row, "API_EXIT_STATUS_MISMATCH", "Client exited unsuccessfully after reporting a successful response"), "dispatch": "failed"}
                    if result.get("status") in {"success", "no_result"} and not any(
                            run.get("status") == result["status"] and source_files_complete(task_dir, current, run) for run in recorded):
                        result = {**record_gap(task_dir, provider, row, "API_COMPLETION_EVIDENCE_MISSING", "Client did not retain a complete plan-bound response"), "dispatch": "failed"}
                except subprocess.TimeoutExpired:
                    result = {**record_gap(task_dir, provider, row, "OPERATION_DEADLINE_EXCEEDED", "Client exhausted the shared operation deadline; uncertain reserved consumption is not refunded"), "dispatch": "failed"}
                except (OSError, ValueError) as exc:
                    from provider_utils import redact_sensitive_text
                    code = "OPERATION_DEADLINE_EXCEEDED" if str(exc).startswith("OPERATION_DEADLINE_EXCEEDED") else "API_EXECUTION_FAILED"
                    options = ({'submission_state': 'not_submitted'}
                               if execution_deadline is not None and not client_started else {})
                    result = {**record_gap(task_dir, provider, row, code, redact_sensitive_text(exc)[:500], **options), "dispatch": "failed"}
                fault = _deterministic_operation_fault(task_dir, provider, result, recorded)
                if fault:
                    source_run = recorded[-1] if recorded else None
                    stopped_operations[operation_key] = {
                        'reason': fault, 'source_run_id': result.get('source_run_id'),
                        'source_run_sha256': sha256_json(source_run) if source_run else '',
                        'provider': provider, 'query_compiler_revision': row.get('query_compiler_revision', ''),
                        'operation': row.get('operation'), 'context_sha256': operation_key[-1]}
                    result['operation_circuit_failure'] = stopped_operations[operation_key]
            result.update(started_at=row_started, finished_at=now_iso(), elapsed_ms=round((time.monotonic() - tick) * 1000), plan_entry_sha256=digest)
            if followup:
                result.update(discovery_followup=followup, discovery_followup_sha256=sha256_json(followup))
            checkpoint(result)
            code = str(result.get("error_code") or "")
            if any(marker in code for marker in ("QUOTA", "LIMIT", "AUTH", "PAID", "CREDIT")):
                stopped.add(provider)
                if provider.startswith("serpapi"):
                    stopped.update({"serpapi_google_patents", "serpapi_google_lens"})
    output["workers"] = min(workers, len(lanes) or 1)
    with ThreadPoolExecutor(max_workers=output["workers"]) as pool:
        for future in as_completed([pool.submit(run_lane, entries) for entries in lanes.values()]):
            future.result()
    cancelled = sum(r.get("dispatch") == "cancelled" for r in results)
    output.update(updated_at=now_iso(), finished_at=now_iso(), elapsed_ms=round((time.monotonic() - started) * 1000),
                  status="access_limited" if any(r.get("status") not in {"success", "no_result", "not_applicable", "cancelled", "fact_reused"} for r in results)
                  else "incomplete" if cancelled else "success")
    output["counts"] = {key: sum(r.get("dispatch") == key for r in results) for key in ("executed", "reused", "blocked", "blocked_reused", "fallback_reused", "failed")}
    if cancelled:
        output["counts"]["cancelled"] = cancelled
    if correction_enabled(task):
        from completion_policy import evidence_delivery_enabled
        output["batch_status"] = output["status"]
        if skip_final_view:
            # The dispatcher derives its own fresh work view right after the batch; deriving
            # and serializing a full one here only to discard it is pure overhead.
            atomic_write_json(task_dir / "execution-status.json", output)
            return output
        # Live credentials still guard each submission. Delivery and next-work
        # use the same task-bound snapshot as CLI/freeze/independent validation;
        # a transient config read must not silently replace that evidence.
        output["work_view"] = (work_view_from_dir(task_dir) if evidence_delivery_enabled(task)
            else work_view_from_dir(task_dir, source_capabilities=caps))
        output["work_status"] = output["work_view"]["status"]
    atomic_write_json(task_dir / "execution-status.json", output)
    return output

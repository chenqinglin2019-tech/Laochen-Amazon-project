#!/usr/bin/env python3
"""Execute one exact, task-opted-in, zero-payment Signa discovery entry."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from common import (
    SIGNA_FREE_MAX_QUERIES_PER_TASK,
    SIGNA_OPERATION,
    SIGNA_PROVIDER,
    active_free_policy,
    authorize_signa_free_plan_entry,
    credential,
    ensure_object,
    load_json,
    load_skill_config,
    parse_iso,
    sha256_json,
    api_first_enabled, API_FIRST_PLAN_META_KEYS, DECISION_PLAN_META_KEYS,
)
from provider_utils import (
    ProviderError,
    authorize_current_scenario_action,
    file_lock,
    http_json,
    json_body,
    quota_summary,
    record_result,
)
from free_search_budget import attempt_context, reserve_search


OFFICIAL_BASE_URL = "https://api.signa.so"
TEST_CREDENTIAL = "lc-ipr-signa-loopback-fixture"
ALLOWED_PLANS = {"beta", "free"}
REQUIRED_SCOPES = {"trademarks:read", "billing:read"}
SEARCH_STRATEGIES = ("exact", "phonetic", "fuzzy", "prefix")
RESULTS_PER_QUERY = 25
LOCAL_LIMIT_CODE = "SIGNA_TASK_QUERY_LIMIT_REACHED"
QUERY_ALREADY_ATTEMPTED_CODE = "SIGNA_QUERY_ALREADY_ATTEMPTED"
PERSISTENT_STOP_CODES = {
    "AUTH_FAILED",
    "COVERAGE_UNVERIFIED",
    "FREE_QUOTA_EXHAUSTED",
    "PAID_PLAN_REQUIRED",
    "PAID_QUOTA_USAGE_DETECTED",
    "PROVIDER_HTTP_ERROR",
    "PROVIDER_NETWORK_ERROR",
    "PROVIDER_UNAVAILABLE",
    "RESPONSE_SCHEMA_CHANGED",
    "SIGNA_ENDPOINT_INVALID",
    "SIGNA_BILLING_STATE_UNSAFE",
    "SIGNA_OFFICE_SCOPE_VIOLATION",
    "SIGNA_POSTCHECK_UNVERIFIED",
    "SIGNA_QUOTA_STATE_UNVERIFIED",
    "SIGNA_SCOPE_INSUFFICIENT",
    "SOURCE_DATA_STALE",
}
PLAN_META_KEYS = {
    "query_id",
    "operation",
    "jurisdiction",
    "right_type",
    "required",
    "required_for",
    "requirement_ids",
    "wave",
    "derived_from",
    "role",
    "execute_by_default",
    "authoritative_for_final_rating",
}
POST_BODY_KEYS = {
    "q",
    "strategies",
    "filters",
    "options",
    "limit",
}


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value))
    )


def _nonnegative_integer(value: Any) -> int | None:
    if not _is_number(value):
        return None
    number = int(value)
    return number if number == value and number >= 0 else None


def _normalized_plan(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _resolved_base(config: dict[str, Any]) -> str:
    configured = str(
        config.get("providers", {}).get(SIGNA_PROVIDER, {}).get("base_url") or ""
    ).rstrip("/")
    override = os.environ.get("SIGNA_BASE_URL", "").rstrip("/")
    test_mode = os.environ.get("LC_IPR_TEST_MODE") == "1"
    if not test_mode:
        if override or configured != OFFICIAL_BASE_URL:
            raise ProviderError(
                "SIGNA_ENDPOINT_INVALID",
                "access_limited",
                "Signa must use the exact official HTTPS endpoint",
            )
        return OFFICIAL_BASE_URL

    candidate = override or configured
    parsed = urlparse(candidate)
    loopback = (
        parsed.scheme == "http"
        and (parsed.hostname or "").casefold() in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )
    if not loopback:
        raise ProviderError(
            "SIGNA_ENDPOINT_INVALID",
            "access_limited",
            "Signa test mode requires an explicit HTTP loopback origin",
        )
    return candidate


def settings() -> tuple[dict[str, Any], str, str]:
    config = load_skill_config()
    cfg = config.get("providers", {}).get(SIGNA_PROVIDER, {})
    limits = config.get("limits", {})
    configured_maximum = limits.get("signa_free_max_queries_per_task")
    configured_result_limit = limits.get("signa_results_per_query")
    if (
        config.get("free_policy") != active_free_policy()
        or cfg.get("commercial_freemium") is not True
        or cfg.get("default_enabled") is not False
        or cfg.get("network_enabled_when_opted_in") is not True
        or cfg.get("supported_operations") != [SIGNA_OPERATION]
        or cfg.get("role") != "discovery_only"
        or cfg.get("authoritative_for_final_rating") is not False
        or cfg.get("free_plan_only") is not True
        or cfg.get("allow_paid") is not False
        or cfg.get("allow_overage") is not False
        or cfg.get("allow_automatic_recharge") is not False
        or cfg.get("offices_path") != "/v1/offices"
        or cfg.get("trademarks_path") != "/v1/trademarks"
        or cfg.get("excluded_offices") != ["WO"]
        or isinstance(configured_maximum, bool)
        or not isinstance(configured_maximum, int)
        or configured_maximum != SIGNA_FREE_MAX_QUERIES_PER_TASK
        or isinstance(configured_result_limit, bool)
        or not isinstance(configured_result_limit, int)
        or configured_result_limit != RESULTS_PER_QUERY
    ):
        raise ProviderError(
            "SIGNA_FREE_POLICY_INVALID",
            "access_limited",
            "Signa configuration violates the explicit task opt-in, bounded zero-payment discovery contract",
        )
    base = _resolved_base(config)
    key = (
        TEST_CREDENTIAL if os.environ.get("LC_IPR_TEST_MODE") == "1"
        else credential(config, "signa_api_key")
    )
    return config, base, key


def auth_headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _get_json(base: str, key: str, path: str, timeout: int) -> tuple[dict[str, Any], dict[str, str]]:
    payload, headers, _ = http_json(
        f"{base}{path}",
        headers=auth_headers(key),
        timeout=timeout,
        retries=0,
    )
    return payload, headers


def _usage_state(
    payload: dict[str, Any], *, allow_exhausted: bool = False,
) -> dict[str, int]:
    pools = payload.get("by_endpoint_type")
    search = pools.get("search") if isinstance(pools, dict) else None
    if not isinstance(search, dict):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED",
            "failed",
            "Signa usage response has no search quota pool",
        )
    used = _nonnegative_integer(search.get("used"))
    limit = _nonnegative_integer(search.get("limit"))
    if used is None or limit is None or limit <= 0 or used > limit:
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED",
            "failed",
            "Signa search usage counters are missing or invalid",
        )
    result = {"used": used, "limit": limit, "remaining": limit - used}
    if not allow_exhausted and result["remaining"] <= 0:
        raise ProviderError(
            "FREE_QUOTA_EXHAUSTED",
            "access_limited",
            "Signa search quota is exhausted",
        )
    return result


def _credit_state(payload: dict[str, Any]) -> dict[str, int]:
    grants = payload.get("grants")
    if not isinstance(grants, dict):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED",
            "failed",
            "Signa credit response has no grant breakdown",
        )
    fields = {
        "balance": payload.get("balance"),
        "reserved": payload.get("reserved"),
        "pending": payload.get("pending"),
        "grant_plan": grants.get("plan"),
        "grant_addon": grants.get("addon"),
        "grant_promo": grants.get("promo"),
    }
    if any(not _is_number(value) for value in fields.values()):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED",
            "failed",
            "Signa credit counters are missing or invalid",
        )
    if any(value != 0 for value in fields.values()):
        raise ProviderError(
            "SIGNA_BILLING_STATE_UNSAFE",
            "access_limited",
            "Signa credit, reservation, pending-spend, or grant balance is non-zero",
        )
    return {name: 0 for name in fields}


def _identity_state(payload: dict[str, Any]) -> dict[str, Any]:
    plan = _normalized_plan(payload.get("plan"))
    if plan not in ALLOWED_PLANS:
        raise ProviderError(
            "PAID_PLAN_REQUIRED",
            "access_limited",
            "Signa account is not on an accepted zero-payment beta/free plan",
        )
    if payload.get("billing_preview") is not False:
        raise ProviderError(
            "SIGNA_BILLING_STATE_UNSAFE",
            "access_limited",
            "Signa billing state is enabled or cannot be proved disabled",
        )
    api_key = payload.get("api_key")
    scopes = api_key.get("scopes") if isinstance(api_key, dict) else None
    if not isinstance(scopes, list) or not REQUIRED_SCOPES <= {
        str(value) for value in scopes
    }:
        raise ProviderError(
            "SIGNA_SCOPE_INSUFFICIENT",
            "access_limited",
            "Signa key must have trademarks:read and billing:read scopes",
        )
    return {"plan": plan, "required_scopes_present": True, "billing_preview": False}


def _target_offices(request_payload: dict[str, Any]) -> list[str]:
    filters = request_payload.get("filters")
    offices = filters.get("offices") if isinstance(filters, dict) else None
    if not isinstance(offices, list) or not offices:
        raise ProviderError(
            "SIGNA_PLAN_PARAMETERS_INVALID",
            "failed",
            "A Signa discovery request must contain an explicit non-empty offices filter",
        )
    normalized: list[str] = []
    for value in offices:
        if not isinstance(value, str) or value != value.strip().upper():
            raise ProviderError(
                "SIGNA_OFFICE_NOT_ALLOWED",
                "access_limited",
                "Signa office filters must use canonical uppercase office codes",
            )
        office = value
        if not re.fullmatch(r"[A-Z]{2}", office) or office == "WO":
            raise ProviderError(
                "SIGNA_OFFICE_NOT_ALLOWED",
                "access_limited",
                "Signa office filters must be two-letter non-WO office codes",
            )
        if office in normalized:
            raise ProviderError(
                "SIGNA_PLAN_PARAMETERS_INVALID",
                "failed",
                "Signa office filters must not contain duplicates",
            )
        normalized.append(office)
    return normalized


def _office_state(
    payload: dict[str, Any], targets: list[str], max_age_days: int,
) -> dict[str, dict[str, Any]]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED",
            "failed",
            "Signa offices response has no data list",
        )
    by_code = {
        str(row.get("code") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and row.get("code")
    }
    result: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for target in targets:
        row = by_code.get(target)
        if not isinstance(row, dict) or str(row.get("status") or "").casefold() != "live":
            raise ProviderError(
                "COVERAGE_UNVERIFIED",
                "access_limited",
                f"Signa office {target} is absent or not live",
            )
        synced = str(row.get("last_synced_at") or "").strip()
        try:
            checked = parse_iso(synced)
            if checked.tzinfo is None:
                raise ValueError("timezone missing")
            age_days = (now - checked.astimezone(timezone.utc)).total_seconds() / 86400
        except (TypeError, ValueError):
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED",
                "failed",
                f"Signa office {target} has no valid synchronization timestamp",
            ) from None
        if age_days < -1 or age_days > max_age_days:
            raise ProviderError(
                "SOURCE_DATA_STALE",
                "access_limited",
                f"Signa office {target} freshness is outside the accepted window",
            )
        result[target] = {
            "status": "live",
            "last_synced_at": synced,
            "total_marks": row.get("total_marks"),
        }
    return result


def _precheck(
    config: dict[str, Any], base: str, key: str, request_payload: dict[str, Any],
    *, attempt_state: dict[str, bool] | None = None,
) -> dict[str, Any]:
    if not key:
        raise ProviderError("AUTH_FAILED", "access_limited", "SIGNA_API_KEY is missing")
    timeout = int(config.get("http", {}).get("timeout_seconds", 30))
    if attempt_state is not None:
        attempt_state["network_request_attempted"] = True
    identity, _ = _get_json(base, key, "/v1/organization/me", timeout)
    usage, _ = _get_json(base, key, "/v1/organization/usage", timeout)
    credits, _ = _get_json(base, key, "/v1/organization/credits", timeout)
    offices, _ = _get_json(base, key, "/v1/offices", timeout)
    identity_state = _identity_state(identity)
    usage_state = _usage_state(usage)
    credit_state = _credit_state(credits)
    targets = _target_offices(request_payload)
    office_state = _office_state(
        offices,
        targets,
        int(config.get("freshness", {}).get("signa_max_age_days", 14)),
    )
    return {
        "plan": identity_state["plan"],
        "billing_safe": True,
        "usage": usage_state,
        "credits": credit_state,
        "offices": office_state,
    }


def _postcheck(config: dict[str, Any], base: str, key: str) -> dict[str, Any]:
    timeout = int(config.get("http", {}).get("timeout_seconds", 30))
    usage, _ = _get_json(base, key, "/v1/organization/usage", timeout)
    credits, _ = _get_json(base, key, "/v1/organization/credits", timeout)
    return {
        "billing_safe": True,
        "usage": _usage_state(usage, allow_exhausted=True),
        "credits": _credit_state(credits),
    }


def probe(offices: list[str]) -> dict[str, Any]:
    """Verify an opted-in bounded-free Signa account and offices without searching."""
    config, base, key = settings()
    state = _precheck(config, base, key, {"filters": {"offices": offices}})
    usage = state["usage"]
    return {
        "ready": True,
        "status": "success",
        "environment": (
            "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1"
            else "commercial_freemium_beta_free"
        ),
        "authoritative_for_final_rating": False,
        "quota": {
            "network_request_attempted": True,
            "search_request_attempted": False,
            "plan": state["plan"],
            "used": usage["used"],
            "limit": usage["limit"],
            "monthly_remaining": usage["remaining"],
            "billing_safe": True,
        },
        "offices": state["offices"],
    }


def _request_from_plan(item: dict[str, Any], max_results: int, *, task: dict | None = None) -> dict[str, Any]:
    metadata = set(PLAN_META_KEYS)
    if task is not None and api_first_enabled(task):
        metadata |= API_FIRST_PLAN_META_KEYS | DECISION_PLAN_META_KEYS | {
            'search_dimension', 'search_language', 'execution_phase', 'publication_scope'}
    unexpected = sorted(set(item) - metadata - POST_BODY_KEYS)
    if unexpected:
        raise ProviderError(
            "SIGNA_PLAN_PARAMETERS_INVALID",
            "failed",
            "Signa plan contains unsupported request fields: " + ", ".join(unexpected),
        )
    request_payload = {
        key: value for key, value in item.items()
        if key in POST_BODY_KEYS
    }
    raw_query = request_payload.pop("q", None)
    query = raw_query.strip() if isinstance(raw_query, str) else ""
    if not query:
        raise ProviderError(
            "SIGNA_PLAN_PARAMETERS_INVALID",
            "failed",
            "Signa plan must contain exactly one non-empty query value",
        )
    request_payload["query"] = query
    strategies = request_payload.get("strategies")
    if strategies != list(SEARCH_STRATEGIES):
        raise ProviderError(
            "SIGNA_PLAN_PARAMETERS_INVALID",
            "failed",
            "Opted-in Signa discovery must use exact, phonetic, fuzzy, and prefix strategies",
        )
    limit = request_payload.get("limit")
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or max_results != RESULTS_PER_QUERY
        or limit != max_results
    ):
        raise ProviderError(
            "SIGNA_PLAN_PARAMETERS_INVALID",
            "failed",
            "Signa result limit must equal the fixed local per-query maximum",
        )
    options = request_payload.get("options")
    if options != {"include_total": False}:
        raise ProviderError(
            "SIGNA_PLAN_PARAMETERS_INVALID",
            "failed",
            "Signa include_total must be false under the nested options object",
        )
    filters = request_payload.get("filters")
    if not isinstance(filters, dict):
        raise ProviderError(
            "SIGNA_PLAN_PARAMETERS_INVALID", "failed", "Signa filters must be an object",
        )
    if set(filters) != {"offices"}:
        raise ProviderError(
            "SIGNA_PLAN_PARAMETERS_INVALID",
            "failed",
            "Opted-in Signa discovery permits only the explicit offices filter",
        )
    nice_classes = filters.get("nice_classes", [])
    if (
        not isinstance(nice_classes, list)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 45
            for value in nice_classes
        )
    ):
        raise ProviderError(
            "SIGNA_PLAN_PARAMETERS_INVALID",
            "failed",
            "Signa Nice classes must be integers from 1 through 45",
        )
    _target_offices(request_payload)
    return request_payload


@contextmanager
def signa_budget_lock(task_dir: Path) -> Iterator[None]:
    with file_lock(task_dir / ".signa-free.lock"):
        yield


def _search_was_attempted(run: dict[str, Any]) -> bool:
    quota = run.get("quota") if isinstance(run.get("quota"), dict) else {}
    return (
        quota.get("search_request_attempted") is True
        or (
            quota.get("search_request_attempted") is None
            and quota.get("network_request_attempted") is True
        )
    )


def consumed_queries(evidence: dict[str, Any]) -> int:
    return sum(
        1
        for run in evidence.get("source_runs", [])
        if isinstance(run, dict)
        and run.get("provider") == SIGNA_PROVIDER
        and run.get("operation") == SIGNA_OPERATION
        and _search_was_attempted(run)
    )


def query_was_attempted(evidence: dict[str, Any], query_id: str, attempt_id: str = 'initial') -> bool:
    return any(
        isinstance(run, dict)
        and run.get("provider") == SIGNA_PROVIDER
        and run.get("operation") == SIGNA_OPERATION
        and str(run.get("query_id") or "") == query_id
        and _search_was_attempted(run)
        and (run.get('quota') or {}).get('attempt_id', 'initial') == attempt_id
        for run in evidence.get("source_runs", [])
    )


def persisted_stop_reason(evidence: dict[str, Any]) -> str:
    for run in evidence.get("source_runs", []):
        if run.get("provider") != SIGNA_PROVIDER:
            continue
        if run.get("operation") != SIGNA_OPERATION:
            # Credential preflight is non-metered and must be recoverable when
            # the user later configures or replaces the optional credential.
            continue
        code = str(run.get("error_code") or "")
        if code == "AUTH_FAILED" and not _search_was_attempted(run):
            continue
        if code in PERSISTENT_STOP_CODES:
            return f"recorded_{code.casefold()}"
        quota = run.get("quota") if isinstance(run.get("quota"), dict) else {}
        if quota.get("billing_safe") is False:
            return "recorded_unproven_billing_state"
        for key in ("monthly_remaining", "daily_remaining"):
            value = quota.get(key)
            if _is_number(value) and int(value) <= 0:
                return f"recorded_zero_{key}"
    return ""


def _status_parts(value: Any) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed", "Signa trademark status is not an object",
        )
    primary, stage = value.get("primary"), value.get("stage")
    if not isinstance(primary, str) or not isinstance(stage, str):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED",
            "failed",
            "Signa trademark status.primary/status.stage are missing",
        )
    return primary, stage


def _owners(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed", "Signa trademark owners is not a list",
        )
    names: list[str] = []
    for owner in value:
        if not isinstance(owner, dict) or not isinstance(owner.get("name"), str):
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED", "failed", "Signa trademark owner schema changed",
            )
        name = owner["name"].strip()
        if name and name not in names:
            names.append(name)
    return names


def _classifications(value: Any) -> tuple[list[int], list[dict[str, Any]]]:
    if not isinstance(value, list):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED",
            "failed",
            "Signa trademark classifications is not a list",
        )
    nice: list[int] = []
    goods: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED",
                "failed",
                "Signa trademark classification schema changed",
            )
        number = row.get("nice_class")
        text = row.get("goods_services_text")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 45:
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED",
                "failed",
                "Signa trademark classification has an invalid Nice class",
            )
        if text is not None and not isinstance(text, str):
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED",
                "failed",
                "Signa goods/services text schema changed",
            )
        if number not in nice:
            nice.append(number)
        goods.append({
            "nice_class": number,
            "text": text or "",
            "truncated": row.get("goods_services_text_truncated") is True,
        })
    return nice, goods


def normalize(
    payload: dict[str, Any], expected_offices: list[str] | None = None,
) -> tuple[list[dict[str, Any]], bool, list[dict[str, Any]]]:
    rows = payload.get("data")
    has_more = payload.get("has_more")
    pagination = payload.get("pagination")
    if (
        payload.get("object") != "list"
        or not isinstance(rows, list)
        or not isinstance(has_more, bool)
        or not isinstance(pagination, dict)
        or "cursor" not in pagination
    ):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed", "Signa search response schema changed",
        )
    meta = payload.get("search_meta")
    if meta is not None and not isinstance(meta, dict):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed", "Signa search_meta schema changed",
        )
    warnings = (meta or {}).get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, dict) for item in warnings):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed", "Signa search warnings schema changed",
        )
    search_id = str((meta or {}).get("search_id") or "")
    request_id = str(payload.get("request_id") or "")
    permitted_offices = {
        str(value).strip().upper() for value in (expected_offices or [])
        if str(value).strip()
    }
    candidates: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED", "failed", "Signa trademark result is not an object",
            )
        record_id = str(item.get("id") or "").strip()
        office = str(item.get("office_code") or "").strip().upper()
        if not record_id or not office or office == "WO":
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED",
                "failed",
                "Signa trademark result lacks a permitted record or office identity",
            )
        if permitted_offices and office not in permitted_offices:
            raise ProviderError(
                "SIGNA_OFFICE_SCOPE_VIOLATION",
                "failed",
                f"Signa returned office {office} outside the task-authorized office filter",
            )
        primary, stage = _status_parts(item.get("status"))
        owners = _owners(item.get("owners"))
        nice, goods = _classifications(item.get("classifications"))
        image_url = item.get("primary_image_url")
        if image_url is not None and not isinstance(image_url, str):
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED", "failed", "Signa primary image URL schema changed",
            )
        design_codes = item.get("design_codes")
        if not isinstance(design_codes, list):
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED", "failed", "Signa design_codes schema changed",
            )
        match_explanation = item.get("match_explanation")
        matched_strategies = (
            match_explanation.get("strategies_matched", [])
            if isinstance(match_explanation, dict) else []
        )
        if not isinstance(matched_strategies, list) or any(
            not isinstance(value, str) for value in matched_strategies
        ):
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED",
                "failed",
                "Signa match provenance schema changed",
            )
        feature = str(item.get("mark_feature_type") or "")
        jurisdiction = str(item.get("jurisdiction_code") or office).upper()
        if jurisdiction == "EM":
            jurisdiction = "EU"
        candidate = {
            "provider_record_id": record_id,
            "office": office,
            "jurisdiction": jurisdiction,
            "serial_number": str(item.get("application_number") or ""),
            "application_number": str(item.get("application_number") or ""),
            "registration_number": str(item.get("registration_number") or ""),
            "mark_text": str(item.get("mark_text") or ""),
            "mark_feature_type": feature,
            # Signa is authorized only for text-query discovery.  A combined
            # mark returned by that query is not evidence of image similarity.
            "right_type": "trademark_word",
            "owner": owners[0] if owners else "",
            "owners": owners,
            "status": stage,
            "status_primary": primary,
            "status_stage": stage,
            "status_detail": {
                "primary": primary,
                "stage": stage,
                "reason": item["status"].get("reason"),
                "challenges": item["status"].get("challenges", []),
                "effective_date": item["status"].get("effective_date"),
            },
            "nice_classes": nice,
            "classifications": goods,
            "goods_services": goods,
            "design_codes": design_codes,
            "image_url": image_url or "",
            "primary_image_url": image_url or "",
            "source_data_date": str(item.get("office_updated_at") or item.get("updated_at") or ""),
            "relevance_score": item.get("relevance_score"),
            "source": SIGNA_PROVIDER,
            "role": "discovery_only",
            "material": False,
            "material_reason": "",
            "disposition": "unreviewed",
            "evidence_refs": [],
            "verification_refs": [],
            "authoritative_for_final_rating": False,
            "discovery_provenance": {
                "provider": SIGNA_PROVIDER,
                "record_id": record_id,
                "search_id": search_id,
                "request_id": request_id,
                "office_updated_at": str(item.get("office_updated_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
                "scope_kind": str(item.get("scope_kind") or ""),
                "filing_route": str(item.get("filing_route") or ""),
                "origin_office_code": str(item.get("origin_office_code") or ""),
                "international_registration_number": str(item.get("ir_number") or ""),
                "strategies_matched": matched_strategies,
            },
            "official_verification": {
                "status": "not_checked",
                "authority": "",
                "source": "",
                "method": "",
                "identity_match": None,
                "legal_status": "",
                "owner": [],
                "classes": [],
                "media": [],
                "url": "",
                "checked_at": "",
            },
        }
        candidates.append(candidate)
    if has_more and not candidates:
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED",
            "failed",
            "Signa reported additional pages without returning a result row",
        )
    return candidates, has_more, warnings


def _quota_record(
    headers: dict[str, str] | None = None,
    *, network_attempted: bool, precheck: dict[str, Any] | None = None,
    postcheck: dict[str, Any] | None = None, billing_safe: bool | None = None,
) -> dict[str, Any]:
    result = quota_summary(headers or {}, {})
    result["network_request_attempted"] = network_attempted
    result["search_request_attempted"] = network_attempted
    lowered_headers = {
        str(key).casefold(): str(value).strip()
        for key, value in (headers or {}).items()
    }
    header_fields = {
        "response_monthly_limit": "x-quota-limit",
        "response_monthly_remaining": "x-quota-remaining",
        "daily_limit": "x-quota-daily-limit",
        "daily_remaining": "x-quota-daily-remaining",
    }
    header_values: dict[str, int] = {}
    quota_headers_valid = True
    for output_name, header_name in header_fields.items():
        raw_value = lowered_headers.get(header_name)
        if raw_value is None:
            continue
        if not re.fullmatch(r"\d+", raw_value):
            quota_headers_valid = False
            continue
        header_values[output_name] = int(raw_value)
    if (
        header_values.get("response_monthly_remaining", 0)
        > header_values.get("response_monthly_limit", float("inf"))
        or header_values.get("daily_remaining", 0)
        > header_values.get("daily_limit", float("inf"))
    ):
        quota_headers_valid = False
    result.update(header_values)
    result["quota_headers_valid"] = quota_headers_valid
    if precheck:
        result.update(precheck.get("local_reservation", {}))
        result.update({
            "plan": precheck.get("plan"),
            "used_before": precheck.get("usage", {}).get("used"),
            "monthly_limit": precheck.get("usage", {}).get("limit"),
            "monthly_remaining_before": precheck.get("usage", {}).get("remaining"),
        })
    if postcheck:
        used = postcheck.get("usage", {}).get("used")
        limit = postcheck.get("usage", {}).get("limit")
        result.update({
            "used_after": used,
            "monthly_remaining": (
                int(limit) - int(used) if _is_number(limit) and _is_number(used) else None
            ),
        })
    if billing_safe is not None:
        result["billing_safe"] = billing_safe
    return result


def _record_failure(
    task_dir: Path,
    item: dict[str, Any],
    error: ProviderError,
    *,
    network_attempted: bool,
    search_attempted: bool = False,
    candidates: list[dict[str, Any]] | None = None,
    raw_body: bytes = b"",
    quota: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query = str(item.get("q") or item.get("query") or "")
    normalized = None
    if candidates:
        normalized = {
            "candidates": candidates,
            "role": "discovery_only",
            "authoritative_for_final_rating": False,
        }
    return record_result(
        task_dir,
        provider=SIGNA_PROVIDER,
        operation=SIGNA_OPERATION,
        query=query,
        jurisdiction=str(item.get("jurisdiction") or ""),
        evidence_type="trademark",
        status=error.source_status,
        normalized=normalized,
        raw_body=raw_body,
        raw_suffix="json",
        error_code=error.code,
        detail=error.detail,
        mandatory=False,
        request_params={
            key: value for key, value in item.items()
            if key in POST_BODY_KEYS or key == "right_type"
        },
        query_id=str(item.get("query_id") or ""),
        quota=quota or {
            "network_request_attempted": network_attempted,
            "search_request_attempted": search_attempted,
        },
        source_environment=(
            "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1"
            else "commercial_freemium_beta_free"
        ),
        authoritative_for_final_rating=False,
    )


def execute(task_dir: Path, query_id: str, *, attempt_id: str = 'initial', retry_reason: str = '') -> dict[str, Any]:
    attempt = attempt_context(attempt_id, retry_reason)
    task_dir = task_dir.resolve()
    with signa_budget_lock(task_dir):
        task = ensure_object(load_json(task_dir / "task.json"), "task.json")
        plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
        item = authorize_signa_free_plan_entry(task, plan, query_id)
        authorize_current_scenario_action(task_dir, task, SIGNA_PROVIDER, item)
        evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
        used = consumed_queries(evidence)
        stop = persisted_stop_reason(evidence)
        if query_was_attempted(evidence, query_id, attempt_id):
            return _record_failure(
                task_dir,
                item,
                ProviderError(
                    QUERY_ALREADY_ATTEMPTED_CODE,
                    "access_limited",
                    "This exact Signa plan query already attempted its single allowed search; no network request sent",
                ),
                network_attempted=False,
                search_attempted=False,
            )
        if used >= SIGNA_FREE_MAX_QUERIES_PER_TASK:
            return _record_failure(
                task_dir,
                item,
                ProviderError(
                    LOCAL_LIMIT_CODE,
                    "access_limited",
                    f"Local Signa query cap reached: {used}/{SIGNA_FREE_MAX_QUERIES_PER_TASK}; no network request sent",
                ),
                network_attempted=False,
            )
        if stop and attempt_id == 'initial':
            return _record_failure(
                task_dir,
                item,
                ProviderError(
                    "SIGNA_PERSISTED_STOP",
                    "access_limited",
                    f"Signa zero-payment stop is already recorded ({stop}); no network request sent",
                ),
                network_attempted=False,
            )

        precheck_attempt = {"network_request_attempted": False}
        try:
            config, base, key = settings()
            max_results = config["limits"]["signa_results_per_query"]
            request_payload = _request_from_plan(item, max_results, task=task)
            precheck = _precheck(
                config, base, key, request_payload, attempt_state=precheck_attempt,
            )
            precheck["local_reservation"] = reserve_search(
                "signa", key, base, remaining=precheck["usage"]["remaining"],
                task_dir=task_dir, query_id=query_id,
                plan_entry_sha256=sha256_json(item), **attempt,
                max_queries_per_task=SIGNA_FREE_MAX_QUERIES_PER_TASK,
            )
        except ProviderError as exc:
            return _record_failure(
                task_dir,
                item,
                exc,
                network_attempted=precheck_attempt["network_request_attempted"],
                search_attempted=False,
            )

        body = b""
        headers: dict[str, str] = {}
        try:
            payload, headers, body = http_json(
                f"{base}/v1/trademarks",
                method="POST",
                headers=auth_headers(key),
                data=json_body(request_payload),
                timeout=int(config.get("http", {}).get("timeout_seconds", 30)),
                retries=0,
            )
            candidates, has_more, warnings = normalize(
                payload, _target_offices(request_payload),
            )
        except ProviderError as exc:
            if exc.http_status == 400:
                exc = ProviderError(
                    "RESPONSE_SCHEMA_CHANGED",
                    "failed",
                    "Signa rejected the generated current-schema request",
                    exc.http_status,
                )
            try:
                failed_postcheck = _postcheck(config, base, key)
            except ProviderError as post_exc:
                original_code = exc.code
                exc = ProviderError(
                    "SIGNA_POSTCHECK_UNVERIFIED",
                    "access_limited",
                    "Signa search failed and its post-search zero-payment state "
                    f"could not be proved ({original_code}; {post_exc.code})",
                )
                quota = _quota_record(
                    headers,
                    network_attempted=True,
                    precheck=precheck,
                    billing_safe=False,
                )
            else:
                quota = _quota_record(
                    headers,
                    network_attempted=True,
                    precheck=precheck,
                    postcheck=failed_postcheck,
                    billing_safe=True,
                )
            return _record_failure(
                task_dir,
                item,
                exc,
                network_attempted=True,
                raw_body=body,
                quota=quota,
            )

        try:
            postcheck = _postcheck(config, base, key)
        except ProviderError as exc:
            error = ProviderError(
                "SIGNA_POSTCHECK_UNVERIFIED",
                "access_limited",
                f"Signa returned discovery data but post-search zero-payment state could not be proved: {exc.code}",
            )
            return _record_failure(
                task_dir,
                item,
                error,
                network_attempted=True,
                candidates=candidates,
                raw_body=body,
                quota=_quota_record(
                    headers,
                    network_attempted=True,
                    precheck=precheck,
                    billing_safe=False,
                ),
            )

        quota = _quota_record(
            headers,
            network_attempted=True,
            precheck=precheck,
            postcheck=postcheck,
            billing_safe=True,
        )
        if quota.get("quota_headers_valid") is not True:
            return _record_failure(
                task_dir,
                item,
                ProviderError(
                    "SIGNA_QUOTA_STATE_UNVERIFIED",
                    "access_limited",
                    "Signa returned malformed search quota headers; discovery data was retained but further Signa searches are stopped",
                ),
                network_attempted=True,
                candidates=candidates,
                raw_body=body,
                quota=quota,
            )
        exhausted_dimensions = [
            name for name in ("monthly_remaining", "daily_remaining")
            if _nonnegative_integer(quota.get(name)) == 0
        ]
        if exhausted_dimensions:
            return _record_failure(
                task_dir,
                item,
                ProviderError(
                    "FREE_QUOTA_EXHAUSTED",
                    "access_limited",
                    "Signa returned discovery data but exhausted its free "
                    + "/".join(name.replace("_remaining", "") for name in exhausted_dimensions)
                    + " search quota",
                ),
                network_attempted=True,
                candidates=candidates,
                raw_body=body,
                quota=quota,
            )
        incomplete_reasons: list[str] = []
        if has_more:
            incomplete_reasons.append("additional result pages were not fetched")
        if warnings:
            warning_codes = [str(value.get("code") or "warning") for value in warnings]
            incomplete_reasons.append("provider warnings: " + ", ".join(warning_codes))
        if incomplete_reasons:
            return _record_failure(
                task_dir,
                item,
                ProviderError(
                    "SIGNA_DISCOVERY_INCOMPLETE",
                    "access_limited",
                    "; ".join(incomplete_reasons),
                ),
                network_attempted=True,
                candidates=candidates,
                raw_body=body,
                quota=quota,
            )

        normalized = {
            "candidates": candidates,
            "role": "discovery_only",
            "authoritative_for_final_rating": False,
        }
        return record_result(
            task_dir,
            provider=SIGNA_PROVIDER,
            operation=SIGNA_OPERATION,
            query=str(item.get("q") or item.get("query") or ""),
            jurisdiction=str(item.get("jurisdiction") or ""),
            evidence_type="trademark",
            status="success" if candidates else "no_result",
            normalized=normalized if candidates else None,
            raw_body=body,
            raw_suffix="json",
            quota=quota,
            mandatory=False,
            request_params={
                key: value for key, value in item.items()
                if key in POST_BODY_KEYS or key == "right_type"
            },
            query_id=query_id,
            source_environment=(
                "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1"
                else "commercial_freemium_beta_free"
            ),
            authoritative_for_final_rating=False,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute one exact task-opted-in Signa query from search-plan.json.",
        allow_abbrev=False,
    )
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--attempt-id", default="initial")
    parser.add_argument("--retry-reason", default="")
    args = parser.parse_args()
    try:
        run = execute(args.task_dir, args.query_id, attempt_id=args.attempt_id, retry_reason=args.retry_reason)
    except (ProviderError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps({
        "status": run.get("status", "failed"),
        "error_code": run.get("error_code", ""),
        "query_id": run.get("query_id", ""),
    }, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

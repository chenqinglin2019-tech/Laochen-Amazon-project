#!/usr/bin/env python3
"""Execute one exact opt-in SerpApi Free-plan Google Patents query."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlencode, urlparse

from common import (
    SERPAPI_FREE_MAX_QUERIES_PER_TASK, SERPAPI_OPERATION, SERPAPI_PROVIDER,
    active_free_policy, authorize_serpapi_free_plan_entry, credential,
    ensure_object, load_json, load_skill_config, provider_execution_error,
    sha256_json,
)
from provider_utils import ProviderError, authorize_current_scenario_action, file_lock, http_json, quota_summary, record_result
from free_search_budget import attempt_context, reserve_search


OFFICIAL_BASE_URL = "https://serpapi.com"
TEST_CREDENTIAL = "lc-ipr-serpapi-loopback-fixture"
ZERO_RESULT_MESSAGE = "Google hasn't returned any results for this query."
FREE_PLAN_NAMES = frozenset({"free", "free plan"})
LOCAL_LIMIT_CODE = "SERPAPI_TASK_QUERY_LIMIT_REACHED"
RECORDED_STOP_CODES = {
    "FREE_QUOTA_EXHAUSTED", "PAID_PLAN_REQUIRED", "PAID_QUOTA_USAGE_DETECTED",
}


def _resolved_base(config: dict[str, Any]) -> str:
    configured = str(config.get("providers", {}).get("serpapi", {}).get("base_url") or "")
    candidate = (
        os.environ.get("SERPAPI_BASE_URL", configured)
        if os.environ.get("LC_IPR_TEST_MODE") == "1" else configured
    ).rstrip("/")
    parsed = urlparse(candidate)
    loopback_test = (
        os.environ.get("LC_IPR_TEST_MODE") == "1"
        and parsed.scheme == "http"
        and (parsed.hostname or "").casefold() in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )
    test_mode = os.environ.get("LC_IPR_TEST_MODE") == "1"
    if (test_mode and not loopback_test) or (not test_mode and candidate != OFFICIAL_BASE_URL):
        raise ProviderError(
            "SERPAPI_ENDPOINT_INVALID", "access_limited",
            "SerpApi requires the official HTTPS endpoint in production and an explicit HTTP loopback endpoint in test mode",
        )
    return candidate


def settings() -> tuple[dict[str, Any], str, str]:
    config = load_skill_config()
    cfg = config.get("providers", {}).get("serpapi", {})
    limits = config.get("limits", {})
    if (
        config.get("free_policy") != active_free_policy()
        or cfg.get("default_enabled") is not False
        or cfg.get("network_enabled_when_opted_in") is not True
        or cfg.get("engine") != "google_patents"
        or cfg.get("role") != "discovery_only"
        or cfg.get("authoritative_for_final_rating") is not False
        or cfg.get("free_plan_only") is not True
        or cfg.get("account_api_unmetered") is not True
        or cfg.get("allow_automatic_early_renewal") is not False
        or cfg.get("allow_extra_credits") is not False
        or cfg.get("allow_paid") is not False
        or cfg.get("allow_overage") is not False
        or int(limits.get("serpapi_google_patents_queries_per_task", 0))
        != SERPAPI_FREE_MAX_QUERIES_PER_TASK
    ):
        raise ProviderError(
            "SERPAPI_FREE_POLICY_INVALID", "access_limited",
            "SerpApi configuration violates the explicit opt-in Free-plan-only contract",
        )
    base = _resolved_base(config)
    key = TEST_CREDENTIAL if os.environ.get("LC_IPR_TEST_MODE") == "1" else credential(config, "serpapi_api_key")
    return config, base, key


@contextmanager
def budget_lock(task_dir: Path) -> Iterator[None]:
    with file_lock(task_dir / ".serpapi-free.lock"):
        yield


def _decimal_number(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    raw = str(value).strip().replace(",", "") if value is not None else ""
    if not raw:
        return None
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _number(value: Any) -> int | None:
    number = _decimal_number(value)
    if number is None or number != number.to_integral_value():
        return None
    return int(number)


def consumed_queries(evidence: dict[str, Any]) -> int:
    return sum(
        1 for run in evidence.get("source_runs", [])
        if run.get("provider") in {SERPAPI_PROVIDER, "serpapi_google_lens"}
        and run.get("operation") in {SERPAPI_OPERATION, "image_search"}
        and (run.get("quota") or {}).get("network_request_attempted") is True
    )


def persisted_quota_block_reason(evidence: dict[str, Any]) -> str:
    for run in evidence.get("source_runs", []):
        if run.get("provider") not in {SERPAPI_PROVIDER, "serpapi_google_lens"}:
            continue
        code = str(run.get("error_code") or "")
        if code in RECORDED_STOP_CODES:
            return f"recorded_{code.casefold()}"
        quota = run.get("quota") if isinstance(run.get("quota"), dict) else {}
        remaining = _number(quota.get("plan_searches_left"))
        if remaining is not None and remaining <= 0:
            return "recorded_zero_free_plan_searches"
    return ""


def free_account_snapshot(base: str, key: str, timeout: int) -> dict[str, Any]:
    """Use the unmetered Account API and retain only non-sensitive quota fields."""
    payload, _, _ = http_json(
        f"{base}/account.json?{urlencode({'api_key': key})}",
        timeout=timeout, retries=0,
    )
    if payload.get("error"):
        raise ProviderError(
            "AUTH_FAILED", "access_limited",
            "SerpApi Account API rejected the credential or account request",
        )
    plan_name = str(payload.get("plan_name") or "").strip()
    price = _decimal_number(payload.get("plan_monthly_price"))
    plan_left = _number(payload.get("plan_searches_left"))
    extra_credits = _number(payload.get("extra_credits"))
    account_status = str(payload.get("account_status") or "").strip()
    if not plan_name or price is None:
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed",
            "SerpApi Account API did not expose an unambiguous plan name and monthly price",
        )
    normalized_plan_name = " ".join(plan_name.casefold().split())
    if normalized_plan_name not in FREE_PLAN_NAMES or price != Decimal("0"):
        raise ProviderError(
            "PAID_PLAN_REQUIRED", "access_limited",
            "SerpApi execution is restricted to an allowlisted $0 Free plan",
        )
    if extra_credits is None:
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed",
            "SerpApi Account API did not expose an unambiguous extra_credits balance",
        )
    if extra_credits != 0:
        raise ProviderError(
            "PAID_QUOTA_USAGE_DETECTED", "access_limited",
            "SerpApi extra credits are present; this skill will not spend them",
        )
    if plan_left is None:
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed",
            "SerpApi Account API did not expose plan_searches_left",
        )
    if plan_left <= 0:
        raise ProviderError(
            "FREE_QUOTA_EXHAUSTED", "access_limited",
            "SerpApi Free-plan monthly searches are exhausted",
        )
    if not account_status:
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed",
            "SerpApi Account API did not expose account_status",
        )
    if account_status.casefold() != "active":
        raise ProviderError("AUTH_FAILED", "access_limited", "SerpApi account is not active")
    return {
        "plan_name": plan_name,
        "plan_monthly_price": 0,
        "searches_per_month": _number(payload.get("searches_per_month")),
        "plan_searches_left": plan_left,
        "this_month_usage": _number(payload.get("this_month_usage")),
        "plan_renewal_date": str(payload.get("plan_renewal_date") or ""),
        "extra_credits": extra_credits,
    }


def fallback_satisfied(evidence: dict[str, Any], item: dict[str, Any], *,
                       task_dir: Path | None = None, task: dict | None = None, plan: dict | None = None) -> bool:
    """Skip a bound SerpApi query after the matching Serper lane completed normally."""
    fallback_query_id = str(item.get("fallback_query_id") or "")
    if not fallback_query_id:
        return False
    if task and task.get("schema_version") == "2.4-free":
        if task_dir is None or not isinstance(plan, dict):
            return False
        # Share the scheduler's retained-evidence contract without introducing
        # a top-level client/runtime import cycle. Legacy 2.3 keeps its rule.
        from runtime_v24 import source_files_complete, source_fresh
        from workflow_v24 import validated_discovery_followup
        matching = [row for row in plan.get("queries", {}).get("serper_patents", [])
                    if row.get("query_id") == fallback_query_id]
        if len(matching) != 1:
            return False
        try:
            maximum_age = float(load_skill_config().get("performance", {}).get("dynamic_evidence_max_age_hours", 48))
            if not math.isfinite(maximum_age) or maximum_age <= 0:
                raise ValueError("invalid freshness window")
        except (TypeError, ValueError):
            raise ProviderError("SOURCE_FRESHNESS_POLICY_INVALID", "failed", "Dynamic evidence reuse requires a positive finite age limit") from None
        if validated_discovery_followup(task_dir, task, plan, evidence, item, maximum_age):
            return False
        return any(
            isinstance(run, dict) and run.get("provider") == "serper_patents"
            and run.get("query_id") == fallback_query_id and run.get("status") in {"success", "no_result"}
            and run.get("plan_entry_sha256") == sha256_json(matching[0])
            and source_fresh(run, maximum_age) and source_files_complete(task_dir, evidence, run)
            for run in evidence.get("source_runs", [])
        )
    return any(
        isinstance(run, dict)
        and run.get("provider") == "serper_patents"
        and str(run.get("query_id") or "") == fallback_query_id
        and run.get("status") in {"success", "no_result", "not_applicable"}
        for run in evidence.get("source_runs", [])
    )


def search(
    base: str, key: str, timeout: int, item: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str], bytes]:
    params = {
        "engine": "google_patents", "api_key": key, "output": "json",
        "q": item["q"], "num": item["num"], "country": item["country"],
    }
    payload, headers, body = http_json(
        f"{base}/search.json?{urlencode(params)}", timeout=timeout, retries=0,
    )
    error = str(payload.get("error") or "")
    if error:
        lowered = error.casefold()
        metadata = payload.get("search_metadata")
        if (error == ZERO_RESULT_MESSAGE and isinstance(metadata, dict)
                and metadata.get("status") == "Success"
                and payload.get("organic_results", []) == []):
            normalized = {**payload, "organic_results": []}
            normalized.pop("error", None)
            return normalized, headers, body
        if any(word in lowered for word in ("quota", "limit", "searches left")):
            raise ProviderError("FREE_QUOTA_EXHAUSTED", "access_limited", error)
        raise ProviderError("PROVIDER_HTTP_ERROR", "failed", error)
    metadata = payload.get("search_metadata")
    results = payload.get("organic_results")
    if not isinstance(metadata, dict) or metadata.get("status") != "Success" or not isinstance(results, list):
        raise ProviderError(
            "RESPONSE_SCHEMA_CHANGED", "failed",
            "SerpApi Google Patents response is missing successful metadata or organic_results",
        )
    return payload, headers, body


def normalize(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in payload.get("organic_results", []):
        if not isinstance(item, dict):
            continue
        publication = re.sub(
            r"[^A-Za-z0-9]", "", str(item.get("publication_number") or ""),
        ).upper()
        if not publication:
            link = str(item.get("patent_link") or item.get("link") or "")
            match = re.search(r"/patent/([A-Za-z]{2}[A-Za-z0-9-]+)", link)
            publication = re.sub(r"[^A-Za-z0-9]", "", match.group(1)).upper() if match else ""
        candidates.append({
            "publication_number": publication,
            "title": str(item.get("title") or ""),
            "snippet": str(item.get("snippet") or ""),
            "inventor": item.get("inventor") or "",
            "assignee": item.get("assignee") or "",
            "filing_date": item.get("filing_date") or "",
            "grant_date": item.get("grant_date") or "",
            "url": str(item.get("patent_link") or item.get("link") or ""),
            "figures": item.get("figures") if isinstance(item.get("figures"), list) else [],
            "jurisdiction": publication[:2],
            "source": SERPAPI_PROVIDER,
            "role": "discovery_only",
            "material": False,
            "authoritative_for_final_rating": False,
            "official_verification": {
                "status": "not_checked", "source": "", "url": "", "checked_at": "",
            },
        })
    return candidates


def _record_failure(
    task_dir: Path, item: dict[str, Any], error: ProviderError,
    *, network_attempted: bool, quota: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return record_result(
        task_dir, provider=SERPAPI_PROVIDER, operation=SERPAPI_OPERATION,
        query=str(item.get("q") or ""),
        jurisdiction=str(item.get("jurisdiction") or ""), evidence_type="patent",
        status=error.source_status, normalized=None,
        error_code=error.code, detail=error.detail, mandatory=False,
        request_params={
            "q": item.get("q"), "num": item.get("num"),
            "country": item.get("country"), "right_type": item.get("right_type"),
        },
        query_id=str(item.get("query_id") or ""),
        quota={**(quota or {}), "network_request_attempted": network_attempted},
        source_environment=(
            "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1"
            else "commercial_freemium_free_plan"
        ),
        authoritative_for_final_rating=False,
    )


def execute(task_dir: Path, query_id: str, *, attempt_id: str = 'initial', retry_reason: str = '') -> dict[str, Any]:
    attempt = attempt_context(attempt_id, retry_reason)
    task_dir = task_dir.resolve()
    with budget_lock(task_dir):
        task = ensure_object(load_json(task_dir / "task.json"), "task.json")
        execution_error = provider_execution_error(task, SERPAPI_PROVIDER, SERPAPI_OPERATION)
        if execution_error:
            raise ValueError(f"{execution_error}: {SERPAPI_PROVIDER}/{SERPAPI_OPERATION}")
        plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
        item = authorize_serpapi_free_plan_entry(task, plan, SERPAPI_OPERATION, query_id)
        authorize_current_scenario_action(task_dir, task, SERPAPI_PROVIDER, item)
        evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
        from workflow_v24 import assert_recall_planning_contract, validated_discovery_followup
        if task.get("recall_planning_revision") is not None:
            assert_recall_planning_contract(task, plan)
        maximum_age = float(load_skill_config().get("performance", {}).get("dynamic_evidence_max_age_hours", 48))
        followup = validated_discovery_followup(task_dir, task, plan, evidence, item, maximum_age)
        if fallback_satisfied(evidence, item, task_dir=task_dir, task=task, plan=plan):
            return {
                "status": "not_applicable", "error_code": "",
                "query_id": query_id, "fallback_provider": "serper_patents",
            }
        maximum = int(task["serpapi_free_enhancement"]["max_queries_per_task"])
        used = consumed_queries(evidence)
        if used >= maximum:
            return _record_failure(
                task_dir, item,
                ProviderError(
                    LOCAL_LIMIT_CODE, "access_limited",
                    f"Local SerpApi free-query cap reached: {used}/{maximum}; no network request sent",
                ),
                network_attempted=False,
            )
        if any(run.get("provider") == SERPAPI_PROVIDER and run.get("query_id") == query_id
               and (run.get("quota") or {}).get("network_request_attempted") is True
               and (run.get("quota") or {}).get("attempt_id", "initial") == attempt_id
               and run.get("plan_entry_sha256") == sha256_json(item)
               for run in evidence.get("source_runs", [])):
            return _record_failure(
                task_dir, item, ProviderError("FREE_SEARCH_ALREADY_RESERVED", "access_limited",
                "This exact SerpApi query already attempted its search; no network request sent"),
                network_attempted=False,
            )
        recorded_stop = persisted_quota_block_reason(evidence)
        if recorded_stop and attempt_id == 'initial':
            return _record_failure(
                task_dir, item,
                ProviderError(
                    "FREE_QUOTA_EXHAUSTED", "access_limited",
                    f"SerpApi Free-plan stop is already recorded ({recorded_stop}); no network request sent",
                ),
                network_attempted=False,
            )

        metered_attempted = False
        account = dict(attempt)
        if followup:
            account["discovery_followup"] = followup
            account["discovery_followup_sha256"] = sha256_json(followup)
        try:
            config, base, key = settings()
            if not key:
                raise ProviderError("AUTH_FAILED", "access_limited", "SERPAPI_API_KEY is missing")
            timeout = int(config.get("http", {}).get("timeout_seconds", 30))
            account.update(free_account_snapshot(base, key, timeout))
            account.update(reserve_search(
                "serpapi", key, base, remaining=account["plan_searches_left"],
                task_dir=task_dir, query_id=query_id,
                renewal_date=account.get("plan_renewal_date", ""),
                plan_entry_sha256=sha256_json(item), **attempt,
                max_queries_per_task=maximum,
            ))
            metered_attempted = True
            payload, headers, body = search(base, key, timeout, item)
            candidates = normalize(payload)
            quota = {**account, **quota_summary(headers, payload)}
            quota["network_request_attempted"] = True
            return record_result(
                task_dir, provider=SERPAPI_PROVIDER, operation=SERPAPI_OPERATION,
                query=str(item["q"]), jurisdiction=str(item.get("jurisdiction") or ""),
                evidence_type="patent", status="success" if candidates else "no_result",
                normalized={
                    "candidates": candidates, "role": "discovery_only",
                    "authoritative_for_final_rating": False,
                },
                raw_body=body, raw_suffix="json", quota=quota, mandatory=False,
                request_params={
                    "q": item["q"], "num": item["num"],
                    "country": item["country"], "right_type": item["right_type"],
                },
                query_id=query_id,
                source_environment=(
                    "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1"
                    else "commercial_freemium_free_plan"
                ),
                authoritative_for_final_rating=False,
            )
        except ProviderError as exc:
            # Account API calls are unmetered; only Google Patents search counts.
            return _record_failure(
                task_dir, item, exc, network_attempted=metered_attempted, quota=account,
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute one exact opt-in SerpApi Free-plan patent query.",
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

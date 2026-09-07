#!/usr/bin/env python3
"""Execute one exact explicitly opted-in Serper discovery entry from search-plan.json."""

from __future__ import annotations

import argparse
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows runner remains sequential.
    fcntl = None

from common import (
    SERPER_FREE_MAX_QUERIES_PER_TASK, SERPER_PROVIDER_OPERATIONS,
    SERPER_PROVIDER_QUERY_CAPS, SERPER_PROVIDERS, active_free_policy,
    authorize_serper_free_plan_entry,
    credential, ensure_object, load_json, load_skill_config,
)
from provider_utils import (
    ProviderError, authorize_current_scenario_action, http_json, json_body, quota_summary, record_result,
)


OFFICIAL_BASE_URL = "https://google.serper.dev"
LOCAL_LIMIT_CODE = "SERPER_TASK_QUERY_LIMIT_REACHED"
PERSISTENT_STOP_CODES = {
    "AUTH_FAILED", "FREE_QUOTA_EXHAUSTED", "FREE_QUOTA_STOP_THRESHOLD",
    "PAID_PLAN_REQUIRED", "PAID_QUOTA_USAGE_DETECTED", "RESPONSE_SCHEMA_CHANGED",
    "SERPER_ENDPOINT_INVALID", "SERPER_FREE_POLICY_INVALID",
    "SERPER_TASK_QUERY_LIMIT_REACHED", "FREE_ACCOUNT_UNVERIFIED",
}
FAILED_STOP_CODES = {"RESPONSE_SCHEMA_CHANGED"}
AUTH_ERROR_PHRASES = (
    "invalid api key", "api key is invalid", "unauthorized", "authentication failed",
    "invalid authentication", "missing api key",
)
QUOTA_ERROR_PHRASES = (
    "insufficient credit", "insufficient credits", "not enough credit",
    "no credit remaining", "no credits remaining", "credits exhausted",
    "no credits left", "out of credits", "credits depleted",
    "credit limit reached", "credit balance is zero", "zero credit balance",
    "free quota reached",
    "quota reached", "quota exhausted", "usage limit reached", "rate limit reached",
)
PAYMENT_ERROR_PHRASES = (
    "paid plan", "payment required", "upgrade your plan", "upgrade plan",
    "purchase credits", "buy credits", "billing required", "overage",
)


def _resolved_base(config: dict[str, Any]) -> str:
    configured = str(config.get("providers", {}).get("serper", {}).get("base_url") or "")
    candidate = (
        os.environ.get("SERPER_BASE_URL", configured)
        if os.environ.get("LC_IPR_TEST_MODE") == "1" else configured
    ).rstrip("/")
    parsed = urlparse(candidate)
    official = candidate == OFFICIAL_BASE_URL
    loopback_test = (
        os.environ.get("LC_IPR_TEST_MODE") == "1"
        and parsed.scheme == "http"
        and (parsed.hostname or "").casefold() in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )
    if not official and not loopback_test:
        raise ProviderError(
            "SERPER_ENDPOINT_INVALID", "access_limited",
            "Serper must use the exact official HTTPS endpoint outside loopback test mode",
        )
    return candidate


def settings() -> tuple[dict[str, Any], str, str]:
    config = load_skill_config()
    policy = config.get("free_policy", {})
    cfg = config.get("providers", {}).get("serper", {})
    limits = config.get("limits", {})
    maximum = limits.get("serper_free_max_queries_per_task")
    per_operation = [
        limits.get("serper_patents_queries_per_task"),
        limits.get("serper_search_queries_per_task"),
        limits.get("serper_images_queries_per_task"),
    ]
    if (
        policy != active_free_policy()
        or cfg.get("default_enabled") is not False
        or cfg.get("network_enabled_when_opted_in") is not True
        or cfg.get("role") != "discovery_only"
        or cfg.get("authoritative_for_final_rating") is not False
        or cfg.get("allow_automatic_recharge") is not False
        or cfg.get("allow_paid") is not False
        or cfg.get("allow_overage") is not False
        or cfg.get("supported_operations") != ["patents", "search", "images"]
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or maximum != SERPER_FREE_MAX_QUERIES_PER_TASK
        or any(isinstance(value, bool) or not isinstance(value, int) for value in per_operation)
        or per_operation != [
            SERPER_PROVIDER_QUERY_CAPS["serper_patents"],
            SERPER_PROVIDER_QUERY_CAPS["serper_web"],
            SERPER_PROVIDER_QUERY_CAPS["serper_images"],
        ]
        or sum(per_operation) > SERPER_FREE_MAX_QUERIES_PER_TASK
    ):
        raise ProviderError(
            "SERPER_FREE_POLICY_INVALID", "access_limited",
            "Serper free-balance configuration violates the explicit task opt-in bounded discovery contract",
        )
    return config, _resolved_base(config), credential(config, "serper_api_key")


@contextmanager
def serper_budget_lock(task_dir: Path) -> Iterator[None]:
    """Serialize the pre-network budget check across concurrent plan runners."""
    lock_path = task_dir / ".serper-free.lock"
    with lock_path.open("a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def consumed_queries(evidence: dict[str, Any]) -> int:
    return sum(
        1
        for run in evidence.get("source_runs", [])
        if run.get("provider") in SERPER_PROVIDERS
        and run.get("operation") in set(SERPER_PROVIDER_OPERATIONS.values())
        and (run.get("quota") or {}).get("network_request_attempted") is True
    )


def _numeric(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"-?\d+", str(value or "").replace(",", ""))
    return int(match.group()) if match else None


def _persistent_stop_status(code: str, recorded_status: str = "") -> str:
    if recorded_status in {"access_limited", "failed"}:
        return recorded_status
    if code in FAILED_STOP_CODES or code.startswith("PROVIDER_"):
        return "failed"
    return "access_limited"


def persisted_provider_block(evidence: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return the first recorded condition that permanently stops this task's Serper lane."""
    for run in evidence.get("source_runs", []):
        if run.get("provider") not in SERPER_PROVIDERS:
            continue
        code = str(run.get("error_code") or "")
        quota = run.get("quota") if isinstance(run.get("quota"), dict) else {}
        if code == "AUTH_FAILED" and quota.get("network_request_attempted") is not True:
            # A missing local credential consumed no free query and may be
            # repaired after the task's non-blocking reminder.
            continue
        if code in PERSISTENT_STOP_CODES or code.startswith("PROVIDER_"):
            return (
                code,
                _persistent_stop_status(code, str(run.get("status") or "")),
                f"recorded_{code.casefold()}",
            )
        if run.get("status") == "failed":
            return (
                "PROVIDER_UNAVAILABLE", "failed", "recorded_provider_failure",
            )
        for key, value in quota.items():
            lowered = str(key).casefold()
            remaining = _numeric(value)
            if remaining is not None and remaining <= 0 and any(
                marker in lowered for marker in ("credit", "quota", "balance", "remaining")
            ):
                return (
                    "FREE_QUOTA_EXHAUSTED", "access_limited",
                    "recorded_zero_remaining_balance",
                )
    return None


def persisted_quota_block_reason(evidence: dict[str, Any]) -> str:
    """Compatibility helper returning the persisted Serper stop reason, if any."""
    blocked = persisted_provider_block(evidence)
    return blocked[2] if blocked else ""


def _error_envelope_text(payload: dict[str, Any]) -> str:
    """Inspect provider error metadata without scanning ordinary search-result text."""
    envelope = {
        key: payload[key]
        for key in ("error", "errors", "message", "detail", "reason", "code", "status")
        if key in payload
    }
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True).casefold()


def _reports_zero_balance(payload: dict[str, Any]) -> bool:
    for key, value in payload.items():
        lowered = str(key).casefold().replace("-", "_")
        if not (
            "remaining" in lowered
            or "balance" in lowered
            or lowered in {"credit", "credits", "quota"}
        ):
            continue
        number = _numeric(value)
        if number is not None and number <= 0:
            return True
    return False


def call(
    operation: str, request_payload: dict[str, Any], *,
    attempt_state: dict[str, bool] | None = None,
) -> tuple[dict[str, Any], dict[str, str], bytes]:
    config, base, key = settings()
    if not key:
        raise ProviderError("AUTH_FAILED", "access_limited", "SERPER_API_KEY is missing")
    if attempt_state is not None:
        attempt_state["network_request_attempted"] = True
    payload, headers, body = http_json(
        f"{base}/{operation}", method="POST",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        data=json_body(request_payload),
        timeout=int(config.get("http", {}).get("timeout_seconds", 30)),
        # One planned query is one network attempt.  Never spend extra free
        # balance through an implicit retry.
        retries=0,
    )
    expected = "images" if operation == "images" else "organic"
    if expected in payload and isinstance(payload.get(expected), list):
        return payload, headers, body

    response_text = _error_envelope_text(payload)
    if _reports_zero_balance(payload) or any(
        phrase in response_text for phrase in QUOTA_ERROR_PHRASES
    ):
        raise ProviderError(
            "FREE_QUOTA_EXHAUSTED", "access_limited",
            "Serper free query balance is exhausted",
        )
    if any(phrase in response_text for phrase in PAYMENT_ERROR_PHRASES):
        raise ProviderError(
            "PAID_PLAN_REQUIRED", "access_limited",
            "Serper requires paid capacity; this task will not continue",
        )
    if any(phrase in response_text for phrase in AUTH_ERROR_PHRASES):
        raise ProviderError(
            "AUTH_FAILED", "access_limited", "Serper authentication failed",
        )
    raise ProviderError(
        "RESPONSE_SCHEMA_CHANGED", "failed",
        f"Serper {operation} response is missing the expected {expected} list",
    )


def normalize(
    provider: str, operation: str, payload: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_items = payload.get("images" if operation == "images" else "organic", [])
    candidates: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        source_url = str(item.get("link") or item.get("url") or "")
        publication = ""
        if operation == "patents":
            match = re.search(r"/patent/([A-Za-z]{2}[A-Za-z0-9-]+)", source_url)
            publication = (
                re.sub(r"[^A-Za-z0-9]", "", match.group(1)).upper()
                if match else ""
            )
        candidate = {
            "publication_number": publication,
            "jurisdiction": publication[:2] if publication else "",
            "title": str(item.get("title") or ""),
            "snippet": str(item.get("snippet") or ""),
            "url": source_url,
            "image_url": str(item.get("imageUrl") or item.get("image") or ""),
            "source": provider,
            "role": "discovery_only",
            "material": False,
            "authoritative_for_final_rating": False,
            "official_verification": {
                "status": "not_checked", "source": "", "url": "", "checked_at": "",
            },
        }
        candidates.append(candidate)
    return candidates


def _find_entry(plan: dict[str, Any], query_id: str) -> tuple[str, str]:
    matches = [
        (provider, SERPER_PROVIDER_OPERATIONS[provider])
        for provider in SERPER_PROVIDERS
        for item in plan.get("queries", {}).get(provider, [])
        if isinstance(item, dict) and str(item.get("query_id") or "") == query_id
    ]
    if len(matches) != 1:
        raise ValueError("SERPER_QUERY_ID_NOT_EXACTLY_PLANNED")
    return matches[0]


def _record_failure(
    task_dir: Path, provider: str, operation: str, item: dict[str, Any],
    error: ProviderError, *, network_attempted: bool,
) -> dict[str, Any]:
    return record_result(
        task_dir, provider=provider, operation=operation,
        query=str(item.get("q") or ""),
        jurisdiction=str(item.get("jurisdiction") or ""),
        evidence_type=(
            "patent" if operation == "patents" else
            "enforcement" if operation == "search" else "copyright"
        ),
        status=error.source_status, normalized=None,
        error_code=error.code, detail=error.detail, mandatory=False,
        request_params={"q": item.get("q"), "num": item.get("num")},
        query_id=str(item.get("query_id") or ""),
        quota={"network_request_attempted": network_attempted},
        source_environment=(
            "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1"
            else "free_entitlement_unvalidated" if error.code == "FREE_ACCOUNT_UNVERIFIED"
            else "commercial_freemium_free_balance"
        ),
        authoritative_for_final_rating=False,
    )


def execute(task_dir: Path, query_id: str) -> dict[str, Any]:
    task_dir = task_dir.resolve()
    with serper_budget_lock(task_dir):
        task = ensure_object(load_json(task_dir / "task.json"), "task.json")
        plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
        provider, operation = _find_entry(plan, query_id)
        item = authorize_serper_free_plan_entry(task, plan, provider, operation, query_id)
        authorize_current_scenario_action(task_dir, task, provider, item)
        if task.get("schema_version") == "2.4-free":
            # A local allow_paid=False flag or the presence of a Key does not
            # reveal the account's actual credit type or automatic recharge.
            # No accepted account-page proof collector exists in this version.
            # Keep the source planned so its precise discovery gap and the
            # SerpApi fallback remain visible; never spend a query to test cost.
            return _record_failure(
                task_dir, provider, operation, item,
                ProviderError(
                    "FREE_ACCOUNT_UNVERIFIED", "access_limited",
                    "Serper free entitlement, absence of paid credits, and disabled automatic recharge cannot yet be independently verified; no metered request sent",
                ),
                network_attempted=False,
            )
        evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
        maximum = int(task["serper_free_enhancement"]["max_queries_per_task"])
        used = consumed_queries(evidence)
        provider_stop = persisted_provider_block(evidence)
        if used >= maximum:
            return _record_failure(
                task_dir, provider, operation, item,
                ProviderError(
                    LOCAL_LIMIT_CODE, "access_limited",
                    f"Local Serper free-query cap reached: {used}/{maximum}; no network request sent",
                ),
                network_attempted=False,
            )
        if provider_stop:
            stop_code, stop_status, stop_reason = provider_stop
            return _record_failure(
                task_dir, provider, operation, item,
                ProviderError(
                    stop_code, stop_status,
                    f"Serper task stop is already recorded ({stop_reason}); no network request sent",
                ),
                network_attempted=False,
            )

        request_payload = {"q": item["q"], "num": item["num"]}
        attempt_state = {"network_request_attempted": False}
        try:
            payload, headers, body = call(
                operation, request_payload, attempt_state=attempt_state,
            )
            candidates = normalize(provider, operation, payload)
            quota = quota_summary(headers, payload)
            quota["network_request_attempted"] = True
            return record_result(
                task_dir, provider=provider, operation=operation,
                query=str(item["q"]), jurisdiction=str(item.get("jurisdiction") or ""),
                evidence_type=(
                    "patent" if operation == "patents" else
                    "enforcement" if operation == "search" else "copyright"
                ),
                status="success" if candidates else "no_result",
                normalized={
                    "candidates": candidates,
                    "role": "discovery_only",
                    "authoritative_for_final_rating": False,
                },
                raw_body=body, raw_suffix="json", quota=quota,
                mandatory=False, request_params=request_payload,
                query_id=query_id,
                source_environment=(
                    "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1"
                    else "commercial_freemium_free_balance"
                ),
                authoritative_for_final_rating=False,
            )
        except ProviderError as exc:
            return _record_failure(
                task_dir, provider, operation, item, exc,
                network_attempted=attempt_state["network_request_attempted"],
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute one exact explicitly opted-in Serper discovery query from search-plan.json.",
        allow_abbrev=False,
    )
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query-id", required=True)
    args = parser.parse_args()
    try:
        run = execute(args.task_dir, args.query_id)
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps({
        "status": run.get("status", "failed"),
        "error_code": run.get("error_code", ""),
        "query_id": run.get("query_id", ""),
    }, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

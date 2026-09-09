#!/usr/bin/env python3
"""Execute one exact explicitly opted-in Serper discovery entry from search-plan.json."""

from __future__ import annotations

import argparse
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from common import (
    SERPER_FREE_MAX_QUERIES_PER_TASK, SERPER_PROVIDER_OPERATIONS,
    SERPER_PROVIDER_QUERY_CAPS, SERPER_PROVIDERS, active_free_policy,
    authorize_serper_free_plan_entry,
    credential, ensure_object, load_json, load_skill_config,
    api_first_enabled, API_FIRST_REVISION, sha256_json, api_discovery_patent_right_type,
)
from free_search_budget import attempt_context, reserve_search
from serper_entitlement import load_entitlement
from provider_utils import (
    ProviderError, authorize_current_scenario_action, file_lock, http_json, json_body, quota_summary, record_result, sanitize_for_evidence,
)


OFFICIAL_BASE_URL = "https://google.serper.dev"
TEST_CREDENTIAL = "offline-serper-test-credential"
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
    key = TEST_CREDENTIAL if os.environ.get("LC_IPR_TEST_MODE") == "1" else credential(config, "serper_api_key")
    return config, _resolved_base(config), key


@contextmanager
def serper_budget_lock(task_dir: Path) -> Iterator[None]:
    """Serialize the pre-network budget check across concurrent plan runners."""
    lock_path = task_dir / ".serper-free.lock"
    with file_lock(lock_path):
        yield


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


def persisted_provider_block(evidence: dict[str, Any], *, entitlement_recheck: bool = False) -> tuple[str, str, str] | None:
    """Return the first recorded condition that permanently stops this task's Serper lane."""
    for run in evidence.get("source_runs", []):
        if run.get("provider") not in SERPER_PROVIDERS:
            continue
        code = str(run.get("error_code") or "")
        quota = run.get("quota") if isinstance(run.get("quota"), dict) else {}
        if entitlement_recheck and code in {'FREE_ACCOUNT_UNVERIFIED', 'AUTH_FAILED'} and quota.get('network_request_attempted') is not True:
            continue
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
            if lowered.endswith('sha256') or isinstance(value, (dict, list)):
                continue  # Provenance hashes and authorization snapshots are not balances.
            remaining = _numeric(value)
            if remaining is not None and remaining <= 0 and not lowered.startswith(('paid_', 'reserved_')) and any(
                marker in lowered for marker in ("balance", "remaining", "_left")
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
    connection: tuple | None = None,
) -> tuple[dict[str, Any], dict[str, str], bytes]:
    config, base, key = connection if connection is not None else settings()
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
    *, retrieval_workflow_revision: str | None = None,
) -> list[dict[str, Any]]:
    raw_items = payload.get("images" if operation == "images" else "organic", [])
    candidates: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            if retrieval_workflow_revision == API_FIRST_REVISION:
                raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'A returned discovery card is not an object; all original cards must be retained for review')
            continue
        if retrieval_workflow_revision == API_FIRST_REVISION and not any(item.get(k) for k in ('title', 'link', 'url', 'imageUrl', 'image', 'publicationNumber', 'publication_number')):
            raise ProviderError('RESPONSE_SCHEMA_CHANGED', 'failed', 'A returned discovery card has no readable identity fields')
        if retrieval_workflow_revision == API_FIRST_REVISION:
            item = sanitize_for_evidence(item)
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
        if retrieval_workflow_revision == API_FIRST_REVISION:
            candidate['retrieval_workflow_revision'] = API_FIRST_REVISION
            candidate.update(google_patent_fields(item) if operation == 'patents' else {
                'thumbnail_url': str(item.get('thumbnailUrl') or ''),
                'source_index': 'google_images' if operation == 'images' else 'google_search',
            })
            candidate.update(source_record_sha256=sha256_json(item), source_position=item.get('position'), source_record_hash_stage='retained-v1')
        candidates.append(candidate)
    return candidates


def retained_source_records(evidence: dict, run: dict, task_dir: Path | None = None) -> list[dict]:
    """Verify retained Images cards, including the legacy pre-sanitization shape."""
    from retained_discovery import retained_records
    if run.get('operation') != 'images':
        raise ValueError('SERPER_IMAGES_RETAINED_NORMALIZATION_INVALID')
    return retained_records(evidence, run, task_dir, provider='serper_images',
        normalize_records=lambda raw: normalize('serper_images', 'images', raw,
            retrieval_workflow_revision=API_FIRST_REVISION),
        invalid='SERPER_IMAGES_RETAINED_NORMALIZATION_INVALID',
        projection_revision='serper-images-retained-projection-v1')


def google_patent_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Keep declared publication identity and source bibliographic facts distinct."""
    item = sanitize_for_evidence(item)
    url = str(item.get('patent_link') or item.get('link') or item.get('url') or '')
    declared = str(item.get('publicationNumber') or item.get('publication_number') or '')
    match = re.search(r'/patent/([A-Za-z]{2}[A-Za-z0-9-]+)', url)
    from_url = re.sub(r'[^A-Za-z0-9]', '', match.group(1)).upper() if match else ''
    publication = re.sub(r'[^A-Za-z0-9]', '', declared).upper() or from_url
    result = {'publication_number': publication, 'jurisdiction': publication[:2], 'url': url,
              'retrieval_workflow_revision': API_FIRST_REVISION,
              'source_index': 'google_patents', 'source_record_sha256': sha256_json(item),
              'source_record_hash_stage': 'retained-v1',
              'source_position': item.get('position'), 'inventor': item.get('inventor') or '',
              'assignee': item.get('assignee') or '', 'language': item.get('language') or '',
              'figures': item.get('figures') if isinstance(item.get('figures'), list) else []}
    for snake, camel in [('priority_date', 'priorityDate'), ('filing_date', 'filingDate'),
                         ('grant_date', 'grantDate'), ('publication_date', 'publicationDate'),
                         ('thumbnail_url', 'thumbnailUrl'), ('pdf_url', 'pdfUrl')]:
        result[snake] = item.get(camel) or item.get(snake) or ''
    if declared and from_url and publication != from_url:
        result['source_identity_conflict'] = {'declared_publication': publication, 'url_publication': from_url}
    actual_type = api_discovery_patent_right_type(publication, item.get('kind_code'))
    result.update(right_type=actual_type or 'unknown',
                  right_type_status='intrinsic_document_identifier' if actual_type else 'unresolved')
    return result


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
    error: ProviderError, *, network_attempted: bool, quota: dict | None = None, raw_body: bytes | None = None,
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
        raw_body=raw_body, raw_suffix='json',
        error_code=error.code, detail=error.detail, mandatory=False,
        request_params={"q": item.get("q"), "num": item.get("num")},
        query_id=str(item.get("query_id") or ""),
        quota={**(quota or {}), "network_request_attempted": network_attempted},
        source_environment=(
            "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1"
            else "user_authorized_existing_balance" if (quota or {}).get('balance_authorization')
            else "free_entitlement_unvalidated" if error.code == "FREE_ACCOUNT_UNVERIFIED"
            else "commercial_freemium_free_balance"
        ),
        authoritative_for_final_rating=False,
    )


def existing_balance_authorization(task: dict[str, Any]) -> dict | None:
    """A task-scoped user override does not claim any verified free balance."""
    value = task.get('serper_existing_balance_authorization')
    if value is None:
        return None
    fields = {'authorized', 'source', 'authorized_at', 'max_requests', 'allow_recharge', 'allow_new_purchase'}
    valid = (api_first_enabled(task) and isinstance(value, dict) and set(value) == fields
             and value.get('authorized') is True and value.get('source') == 'explicit_user_instruction'
             and value.get('allow_recharge') is False and value.get('allow_new_purchase') is False
             and type(value.get('max_requests')) is int and 1 <= value['max_requests'] <= 30
             and value['max_requests'] == task.get('serper_free_enhancement', {}).get('max_queries_per_task'))
    try:
        timestamp = datetime.fromisoformat(str(value.get('authorized_at')).replace('Z', '+00:00')) if isinstance(value, dict) else None
        valid = valid and timestamp is not None and timestamp.tzinfo is not None and timestamp <= datetime.now(timezone.utc) + timedelta(seconds=60)
    except ValueError:
        valid = False
    if not valid:
        raise ProviderError('SERPER_BALANCE_AUTHORIZATION_INVALID', 'access_limited', 'Existing-balance use requires a bounded explicit user authorization on this new task')
    return dict(value)


def execute(task_dir: Path, query_id: str, *, attempt_id: str = 'initial', retry_reason: str = '') -> dict[str, Any]:
    task_dir = task_dir.resolve()
    with serper_budget_lock(task_dir):
        task = ensure_object(load_json(task_dir / "task.json"), "task.json")
        plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
        provider, operation = _find_entry(plan, query_id)
        item = authorize_serper_free_plan_entry(task, plan, provider, operation, query_id)
        authorize_current_scenario_action(task_dir, task, provider, item)
        api_first = api_first_enabled(task)
        authorization = existing_balance_authorization(task) if api_first else None
        authorization_quota = {'balance_authorization': authorization, 'balance_authorization_sha256': sha256_json(authorization),
                               'balance_verified': False} if authorization else {}
        if task.get("schema_version") == "2.4-free" and not api_first:
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
                network_attempted=False, quota=authorization_quota,
            )
        evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
        maximum = int(task["serper_free_enhancement"]["max_queries_per_task"])
        used = consumed_queries(evidence)
        provider_stop = persisted_provider_block(evidence, entitlement_recheck=api_first)
        if used >= maximum:
            return _record_failure(
                task_dir, provider, operation, item,
                ProviderError(
                    LOCAL_LIMIT_CODE, "access_limited",
                    f"Local Serper free-query cap reached: {used}/{maximum}; no network request sent",
                ),
                network_attempted=False, quota=authorization_quota,
            )
        if provider_stop:
            stop_code, stop_status, stop_reason = provider_stop
            return _record_failure(
                task_dir, provider, operation, item,
                ProviderError(
                    stop_code, stop_status,
                    f"Serper task stop is already recorded ({stop_reason}); no network request sent",
                ),
                network_attempted=False, quota=authorization_quota,
            )

        request_payload = {"q": item["q"], "num": item["num"]}
        if api_first:
            request_payload.update({k: item[k] for k in ('gl', 'hl', 'page') if k in item})
        attempt_state = {"network_request_attempted": False}
        account = dict(authorization_quota)
        connection = None
        body = b''
        try:
            if api_first:
                attempt = attempt_context(attempt_id, retry_reason)
                connection = settings()
                _, base, key = connection
                if not key:
                    raise ProviderError('AUTH_FAILED', 'access_limited', 'SERPER_API_KEY is missing')
                account.update(attempt)
                if authorization:
                    account.update(reserve_search('serper', key, base, remaining=None, credit_units=None,
                        balance_verified=False, task_dir=task_dir, query_id=query_id,
                        plan_entry_sha256=sha256_json(item), max_queries_per_task=maximum, **attempt))
                else:
                    proof = load_entitlement(key, operation)
                    account.update(entitlement_sha256=proof['proof_sha256'],
                                   entitlement_capture_sha256=proof['capture_sha256'],
                                   entitlement_expires_at=proof['expires_at'])
                    account.update(reserve_search('serper', key, base, remaining=proof['free_credit_units'],
                        credit_units=proof['operation_credit_units'][operation], account_identity=proof['account_fingerprint'],
                        task_dir=task_dir, query_id=query_id, plan_entry_sha256=sha256_json(item),
                        max_queries_per_task=maximum, **attempt))
            payload, headers, body = call(
                operation, request_payload, attempt_state=attempt_state,
                **({'connection': connection} if api_first else {}),
            )
            candidates = normalize(provider, operation, payload, retrieval_workflow_revision=task.get('retrieval_workflow_revision'))
            quota = {**account, **quota_summary(headers, payload)}
            if api_first:
                units = payload.get('credits')
                quota['reported_credit_units'] = units if type(units) in (int, float) and units >= 0 else None
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
                    **({'source_index': candidates[0]['source_index'] if candidates else {
                        'patents': 'google_patents', 'search': 'google_search', 'images': 'google_images'}[operation],
                        'search_metadata': bounded_search_metadata(candidates)} if api_first else {}),
                },
                raw_body=body, raw_suffix="json", quota=quota,
                mandatory=False, request_params=request_payload,
                query_id=query_id,
                source_environment=(
                    "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1"
                    else "user_authorized_existing_balance" if authorization
                    else "commercial_freemium_free_balance"
                ),
                authoritative_for_final_rating=False,
            )
        except ProviderError as exc:
            return _record_failure(
                task_dir, provider, operation, item, exc,
                network_attempted=attempt_state["network_request_attempted"], quota=account, raw_body=body or None,
            )


def bounded_search_metadata(candidates: list) -> dict:
    return {'total_hits': None, 'retrieved_hits': len(candidates), 'reviewed_hits': None,
            'truncated': True, 'stop_reason': 'bounded_discovery_total_unknown',
            'source_updated_at': None, 'schema_valid': True}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute one exact explicitly opted-in Serper discovery query from search-plan.json.",
        allow_abbrev=False,
    )
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query-id", required=True)
    parser.add_argument('--attempt-id', default='initial')
    parser.add_argument('--retry-reason', default='')
    args = parser.parse_args()
    try:
        run = execute(args.task_dir, args.query_id, attempt_id=args.attempt_id, retry_reason=args.retry_reason)
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps({
        "status": run.get("status", "failed"),
        "error_code": run.get("error_code", ""),
        "query_id": run.get("query_id", ""),
    }, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

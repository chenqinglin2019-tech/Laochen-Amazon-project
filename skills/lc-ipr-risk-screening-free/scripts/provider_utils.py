#!/usr/bin/env python3
"""HTTP, raw-evidence, and provider-result helpers."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from http.client import RemoteDisconnected
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback remains serial.
    fcntl = None

from common import (
    add_gap, add_history, atomic_write_bytes, atomic_write_json, clear_gaps, ensure_object, load_json,
    load_skill_config, now_iso, sha256_bytes, stable_id, upsert_source_run,
)


@dataclass
class ProviderError(RuntimeError):
    code: str
    source_status: str
    detail: str
    http_status: int = 0

    def __str__(self) -> str:
        return self.detail


def classify_http(status: int, body: bytes) -> ProviderError:
    detail = body.decode("utf-8", errors="replace")[:500]
    lowered = detail.casefold()
    if status == 402 or "paid plan" in lowered or "upgrade" in lowered:
        return ProviderError("PAID_PLAN_REQUIRED", "access_limited", "Provider requires a paid plan", status)
    if status == 429:
        return ProviderError("FREE_QUOTA_EXHAUSTED", "access_limited", "Provider quota or rate limit reached", status)
    if status in {401, 403}:
        return ProviderError("AUTH_FAILED", "access_limited", "Provider authentication or subscription failed", status)
    if status >= 500:
        return ProviderError("PROVIDER_UNAVAILABLE", "failed", f"Provider HTTP {status}", status)
    return ProviderError("PROVIDER_HTTP_ERROR", "failed", f"Provider HTTP {status}: {detail}", status)


def http_request(
    url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
    data: bytes | None = None, timeout: int = 30, retries: int = 2,
) -> tuple[int, dict[str, str], bytes]:
    safe_headers = {**(headers or {})}
    if not any(key.casefold() == "user-agent" for key in safe_headers):
        safe_headers["User-Agent"] = str(load_skill_config().get("http", {}).get("user_agent", "lc-ipr-risk-screening-free/2.1"))
    for attempt in range(retries + 1):
        req = request.Request(url, data=data, headers=safe_headers, method=method)
        try:
            with request.urlopen(req, timeout=timeout) as response:
                return response.status, dict(response.headers.items()), response.read()
        except error.HTTPError as exc:
            body = exc.read()
            problem = classify_http(exc.code, body)
            retryable = exc.code == 429 or exc.code >= 500
            if not retryable or attempt >= retries:
                raise problem from None
        except (error.URLError, TimeoutError, RemoteDisconnected) as exc:
            if attempt >= retries:
                raise ProviderError("PROVIDER_NETWORK_ERROR", "failed", "Provider network request failed") from exc
        time.sleep(min(2 ** attempt, 8))
    raise ProviderError("PROVIDER_NETWORK_ERROR", "failed", "Provider request failed")


def http_json(*args: Any, **kwargs: Any) -> tuple[dict[str, Any], dict[str, str], bytes]:
    _, headers, body = http_request(*args, **kwargs)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "Provider response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "Provider JSON response must be an object")
    return payload, headers, body


def json_body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def quota_summary(headers: dict[str, str], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in headers.items():
        lowered = key.casefold()
        if any(word in lowered for word in ("rate", "quota", "limit", "remaining", "usage")):
            result[key] = value
    if isinstance(payload, dict):
        for key in ("plan", "searches_per_month", "this_month_usage", "total_searches_left", "remaining", "usage"):
            if key in payload:
                result[key] = payload[key]
    return result


def enforce_task_limit(task_dir: Path, provider: str, operation: str, maximum: int) -> None:
    evidence_path = task_dir / "evidence.json"
    evidence = ensure_object(load_json(evidence_path), "evidence.json")
    count = sum(
        1 for run in evidence.get("source_runs", [])
        if run.get("provider") == provider and run.get("operation") == operation
        and run.get("status") in {"success", "no_result", "access_limited", "failed"}
    )
    if count >= maximum:
        raise ProviderError("FREE_QUOTA_EXHAUSTED", "access_limited", f"Per-task free query cap reached for {provider}/{operation}: {maximum}")


SENSITIVE_REQUEST_KEYS = {
    "api_key", "apikey", "key", "token", "access_token", "authorization",
    "client_secret", "consumer_secret", "x-api-key", "x-rapidapi-key",
}


def sanitized_request_params(value: Any) -> Any:
    """Return canonical non-secret request data suitable for evidence and hashing."""
    if isinstance(value, dict):
        return {
            str(key): sanitized_request_params(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).casefold() not in SENSITIVE_REQUEST_KEYS
        }
    if isinstance(value, list):
        return [sanitized_request_params(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def query_identity(
    provider: str, operation: str, jurisdiction: str, query: str,
    request_params: dict[str, Any] | None = None,
) -> str:
    canonical = sanitized_request_params(request_params or {"q": query})
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return stable_id("QRY", provider, operation, jurisdiction.upper(), encoded)


PLAN_META_KEYS = {"query_id", "operation", "jurisdiction", "required", "wave", "derived_from"}


def planned_query_id(
    task_dir: Path, provider: str, operation: str, query: str,
    request_params: dict[str, Any],
) -> str:
    """Resolve a generated plan entry without making client defaults part of identity."""
    plan_path = task_dir / "search-plan.json"
    if not plan_path.is_file():
        return ""
    try:
        plan = ensure_object(load_json(plan_path), "search-plan.json")
    except (OSError, ValueError):
        return ""
    matches: list[str] = []
    for item in plan.get("queries", {}).get(provider, []):
        if not isinstance(item, dict):
            continue
        if str(item.get("operation") or operation) != operation:
            continue
        if str(item.get("q") or item.get("query") or "") != query:
            continue
        comparable = {key: value for key, value in item.items() if key not in PLAN_META_KEYS}
        if all(sanitized_request_params(request_params.get(key)) == sanitized_request_params(value) for key, value in comparable.items()):
            if item.get("query_id"):
                matches.append(str(item["query_id"]))
    return matches[0] if len(set(matches)) == 1 else ""


def raw_path(task_dir: Path, provider: str, query_id: str, digest: str, suffix: str = "json") -> Path:
    return task_dir / "raw" / provider / f"{query_id}_{digest[:16]}.{suffix}"


@contextmanager
def evidence_lock(task_dir: Path):
    lock_path = task_dir / ".evidence.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _record_result(
    task_dir: Path, *, provider: str, operation: str, query: str, jurisdiction: str,
    evidence_type: str, status: str, normalized: Any, raw_body: bytes = b"",
    raw_suffix: str = "json", error_code: str = "", detail: str = "",
    quota: dict[str, Any] | None = None, data_date: str = "", retry_count: int = 0,
    mandatory: bool = True, request_params: dict[str, Any] | None = None,
    query_id: str = "",
) -> dict[str, Any]:
    task_path, evidence_path = task_dir / "task.json", task_dir / "evidence.json"
    task = ensure_object(load_json(task_path), "task.json")
    evidence = ensure_object(load_json(evidence_path), "evidence.json")
    raw_paths: list[str] = []
    safe_request = sanitized_request_params(request_params or {"q": query})
    logical_query_id = (
        query_id
        or planned_query_id(task_dir, provider, operation, query, safe_request)
        or query_identity(provider, operation, jurisdiction, query, safe_request)
    )
    if raw_body:
        digest = sha256_bytes(raw_body)
        path = raw_path(task_dir, provider, logical_query_id, digest, raw_suffix)
        atomic_write_bytes(path, raw_body)
        raw_paths.append(str(path))
    else:
        digest = sha256_bytes(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode())
    recorded_at = now_iso()
    run_id = stable_id("ATT", logical_query_id, digest, recorded_at, str(time.time_ns()))
    run = {
        "run_id": run_id, "attempt_id": run_id, "query_id": logical_query_id,
        "provider": provider, "operation": operation, "query": query,
        "request_params": safe_request,
        "jurisdiction": jurisdiction.upper(), "started_at": recorded_at, "finished_at": recorded_at,
        "status": status, "evidence_type": evidence_type, "raw_paths": raw_paths,
        "payload_digest": digest, "error_code": error_code, "detail": detail,
        "retry_count": retry_count, "quota": quota or {}, "data_date": data_date,
    }
    upsert_source_run(evidence, run)
    if status in {"success", "no_result", "not_applicable"}:
        clear_gaps(task, provider, logical_query_id)
    elif provider in task.get("required_sources", []):
        add_gap(
            task, provider, jurisdiction, status, error_code or "PROVIDER_FAILED",
            detail, mandatory, query_id=logical_query_id,
        )
        if mandatory:
            add_history(task, "incomplete", f"Required provider {provider} failed: {detail}")
    collection_name = {
        "patent": "patents", "trademark": "trademarks", "copyright": "copyright_assets",
        "enforcement": "enforcement", "official_verification": "official_verifications",
        "blacklist": "blacklist", "product": "product",
    }.get(evidence_type)
    if collection_name and normalized not in (None, [], {}):
        entry = {
            "evidence_id": stable_id("EV", logical_query_id, digest), "source_run_id": run_id,
            "query_id": logical_query_id,
            "provider": provider, "operation": operation, "query": query,
            "jurisdiction": jurisdiction.upper(), "collected_at": now_iso(), "payload": normalized,
        }
        collection = evidence.setdefault("collections", {}).setdefault(collection_name, [])
        collection[:] = [item for item in collection if item.get("evidence_id") != entry["evidence_id"]]
        collection.append(entry)
    task["updated_at"] = now_iso()
    atomic_write_json(task_path, task)
    atomic_write_json(evidence_path, evidence)
    return run


def record_result(task_dir: Path, **kwargs: Any) -> dict[str, Any]:
    """Serialize evidence mutations so independent API calls may run concurrently."""
    with evidence_lock(task_dir):
        return _record_result(task_dir, **kwargs)


def record_error(
    task_dir: Path, *, provider: str, operation: str, query: str, jurisdiction: str,
    evidence_type: str, error_value: ProviderError, mandatory: bool = True,
    request_params: dict[str, Any] | None = None, query_id: str = "",
) -> dict[str, Any]:
    return record_result(
        task_dir, provider=provider, operation=operation, query=query, jurisdiction=jurisdiction,
        evidence_type=evidence_type, status=error_value.source_status, normalized=None,
        error_code=error_value.code, detail=error_value.detail,
        mandatory=mandatory, request_params=request_params, query_id=query_id,
    )

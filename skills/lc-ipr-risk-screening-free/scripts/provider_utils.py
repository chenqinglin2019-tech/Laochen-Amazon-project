#!/usr/bin/env python3
"""HTTP, raw-evidence, and provider-result helpers."""

from __future__ import annotations

import base64
import binascii
import json
import errno
import math
import os
import re
import time
from contextlib import contextmanager
from http.client import RemoteDisconnected
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses msvcrt.
    fcntl = None
try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX uses fcntl.
    msvcrt = None

from common import (
    COMMERCIAL_PROVIDERS, DECISION_PLAN_META_KEYS, SERPAPI_PROVIDER, SERPER_PROVIDERS, SIGNA_OPERATION,
    SIGNA_PROVIDER,
    add_gap, add_history, atomic_write_bytes, atomic_write_json,
    authorize_serpapi_free_plan_entry, authorize_serper_free_plan_entry,
    authorize_signa_free_plan_entry,
    canonical_coverage_requirements_match, clear_gaps,
    clear_optional_discovery_access_gaps, ensure_object, load_json,
    load_skill_config, now_iso, plan_free_policy_matches_task,
    provider_execution_error, sha256_bytes, sha256_json, signa_free_enabled, stable_id,
    task_free_policy_valid,
    upsert_source_run,
)


@dataclass
class ProviderError(RuntimeError):
    code: str
    source_status: str
    detail: str
    http_status: int = 0

    def __str__(self) -> str:
        return self.detail


def classify_http(status: int, body: bytes, headers: dict[str, str] | None = None) -> ProviderError:
    detail = redact_sensitive_text(body.decode("utf-8", errors="replace"))[:500]
    lowered = detail.casefold()
    rejection_reason = " ".join(
        str(value) for key, value in (headers or {}).items()
        if key.casefold() in {"x-rejection-reason", "x-rate-limit-reason"}
    ).casefold()
    if status == 402 or "paid plan" in lowered or "upgrade" in lowered:
        return ProviderError("PAID_PLAN_REQUIRED", "access_limited", "Provider requires a paid plan", status)
    exhausted_credit = any(phrase in lowered for phrase in (
        "insufficient credit", "not enough credit", "no credit remaining",
        "credits exhausted", "credit balance is zero", "zero credit balance",
    ))
    if status == 429 or exhausted_credit or "quota" in rejection_reason or "limit" in rejection_reason:
        return ProviderError("FREE_QUOTA_EXHAUSTED", "access_limited", "Provider quota or rate limit reached", status)
    if status in {401, 403}:
        return ProviderError("AUTH_FAILED", "access_limited", "Provider authentication or subscription failed", status)
    if status >= 500:
        return ProviderError("PROVIDER_UNAVAILABLE", "failed", f"Provider HTTP {status}", status)
    return ProviderError("PROVIDER_HTTP_ERROR", "failed", f"Provider HTTP {status}: {detail}", status)


MAX_HTTP_RESPONSE_BYTES = 32 * 1024 * 1024


def _http_origin(url: str) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("invalid HTTP URL")
        return parsed.scheme, parsed.hostname.casefold(), parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise ProviderError("PROVIDER_ENDPOINT_INVALID", "failed", "Provider URL is not an HTTP(S) endpoint without user information") from None


class SameOriginRedirectHandler(request.HTTPRedirectHandler):
    """Keep every hop inside the validated origin, including POST credentials."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _http_origin(req.full_url) != _http_origin(newurl):
            raise ProviderError("PROVIDER_REDIRECT_BLOCKED", "access_limited", "Cross-origin or HTTPS-downgrade provider redirect was blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request_timeout(timeout: float) -> float:
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ProviderError("PROVIDER_TIMEOUT_INVALID", "failed", "Provider timeout must be a positive finite number")
    deadline = os.environ.get("LC_IPR_OPERATION_DEADLINE_EPOCH")
    if deadline:
        try:
            remaining = float(deadline) - time.time()
            if not math.isfinite(remaining) or remaining <= 0:
                raise ValueError("expired deadline")
        except ValueError:
            raise ProviderError("OPERATION_DEADLINE_EXCEEDED", "access_limited", "Provider operation deadline is invalid or expired") from None
        return min(timeout, remaining)
    return timeout


def assert_test_endpoint(url: str) -> None:
    origin = _http_origin(url)
    offline = os.environ.get("LC_IPR_TEST_MODE") == "1" or os.environ.get("LC_IPR_OFFLINE_TESTS") == "1"
    if offline and (origin[0] != "http" or origin[1] not in {"127.0.0.1", "localhost", "::1"}):
        raise ProviderError("TEST_NETWORK_BLOCKED", "access_limited", "Provider offline tests permit only loopback HTTP transport")


def _bounded_response(response, maximum: int) -> bytes:
    body = response.read(maximum + 1)
    if len(body) > maximum:
        raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE", "failed", "Provider response exceeded the configured in-memory limit")
    return body


def http_request(
    url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
    data: bytes | None = None, timeout: int = 30, retries: int = 2,
    max_response_bytes: int = MAX_HTTP_RESPONSE_BYTES,
) -> tuple[int, dict[str, str], bytes]:
    origin = _http_origin(url)
    assert_test_endpoint(url)
    if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or not 0 < max_response_bytes <= MAX_HTTP_RESPONSE_BYTES:
        raise ProviderError("PROVIDER_RESPONSE_LIMIT_INVALID", "failed", "Provider response limit must be within the bounded transport maximum")
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 3:
        raise ProviderError("PROVIDER_RETRY_LIMIT_INVALID", "failed", "Provider retries must be between zero and three")
    safe_headers = {**(headers or {})}
    if not any(key.casefold() == "user-agent" for key in safe_headers):
        safe_headers["User-Agent"] = str(load_skill_config().get("http", {}).get("user_agent", "lc-ipr-risk-screening-free/2.1"))
    opener = request.build_opener(SameOriginRedirectHandler())
    for attempt in range(retries + 1):
        attempt_timeout = request_timeout(timeout)
        req = request.Request(url, data=data, headers=safe_headers, method=method)
        try:
            with opener.open(req, timeout=attempt_timeout) as response:
                if _http_origin(response.geturl()) != origin:
                    raise ProviderError("PROVIDER_REDIRECT_BLOCKED", "access_limited", "Provider response origin differs from the validated endpoint")
                return response.status, dict(response.headers.items()), _bounded_response(response, max_response_bytes)
        except error.HTTPError as exc:
            try:
                body = _bounded_response(exc, min(max_response_bytes, 65536))
            finally:
                exc.close()
            problem = classify_http(exc.code, body, dict(exc.headers.items()) if exc.headers else {})
            # 429 is a hard free-tier stop, not a transient transport error.
            # Retrying it can consume additional quota or cross an allowance.
            retryable = exc.code >= 500
            if not retryable or attempt >= retries:
                raise problem from None
        except (error.URLError, TimeoutError, RemoteDisconnected) as exc:
            if attempt >= retries:
                raise ProviderError("PROVIDER_NETWORK_ERROR", "failed", "Provider network request failed") from exc
        wait_seconds = min(2 ** attempt, 8)
        if os.environ.get("LC_IPR_OPERATION_DEADLINE_EPOCH") and request_timeout(timeout) <= wait_seconds:
            raise ProviderError("OPERATION_DEADLINE_EXCEEDED", "access_limited", "Provider operation has no time for another bounded retry")
        time.sleep(wait_seconds)
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
    for key, value in sanitize_headers(headers).items():
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


REDACTED = "[redacted]"
SENSITIVE_REQUEST_KEYS = {
    "api_key", "apikey", "key", "token", "access_token", "refresh_token",
    "id_token", "request_token", "requesttoken", "authorization", "proxy-authorization",
    "password", "passwd", "pwd", "username", "user_name", "user", "user_id",
    "client_secret", "consumer_secret", "client_id", "consumer_key", "x-api-key",
    "x-rapidapi-key", "x-ibm-client-id", "cookie", "set-cookie", "credential",
    "credentials", "session_id", "session_token", "websocket", "websocket_url",
    "cdp_endpoint", "endpoint", "remote_debugging_port", "profile_dir", "user_data_dir",
    "local_storage", "localstorage",
}
_SENSITIVE_NORMALIZED_KEYS = {
    re.sub(r"[^a-z0-9]", "", key.casefold()) for key in SENSITIVE_REQUEST_KEYS
} | {
    "accesstoken", "authtoken", "bearertoken", "clientid", "clientsecret",
    "consumerkey", "consumersecret", "privatekey", "publickey", "secretkey",
    "setcookie", "xapikey", "xibmclientid", "xrapidapikey",
}
_SENSITIVE_KEY_MARKERS = ("token", "secret", "password", "passwd", "credential")
_URL_RE = re.compile(r"(?i)https?://[^\s<>\"']+")
_HEADER_LINE_RE = re.compile(
    r"(?im)^(?P<indent>[ \t]*)(?P<key>[a-z][a-z0-9_.-]{0,80})"
    r"(?P<separator>[ \t]*:[ \t]*)(?P<value>[^\r\n]*)"
)
_XML_SECRET_ELEMENT_RE = re.compile(
    r"(?is)(?P<open><(?P<key>[a-z_][\w:.-]*)\b[^>]*>)"
    r"(?P<value>[^<]*)(?P<close></(?P=key)\s*>)"
)
_KEY_VALUE_RE = re.compile(
    r'''(?ix)
    (?P<prefix>
        (?P<quote>["']?)(?P<key>[a-z][a-z0-9_.-]{0,80})(?P=quote)
        \s*[:=]\s*
    )
    (?P<value>
        "(?:\\.|[^"\\])*"
        | '(?:\\.|[^'\\])*'
        | (?:bearer|basic)\s+[^\s,;&}\]\r\n]+
        | [^"',;&}\]\r\n]+
    )
    ''',
)
_CLI_VALUE_RE = re.compile(
    r"(?i)(?P<prefix>--(?P<key>[a-z][a-z0-9_.-]{0,80})(?:=|\s+))"
    r"(?P<value>[^\s,;]+)"
)
_AUTH_SCHEME_RE = re.compile(r"(?i)\b(?P<scheme>bearer|basic)\s+[^\s,;]+")
TEXT_EVIDENCE_REVISION = "retained-text-v1"
TEXT_HASH_ALGORITHM = "sha256-canonical-json-utf8"
# The legacy patterns are frozen: historical capture -> raw proofs use them.
_RETAINED_KEY_VALUE_RE = re.compile(
    _KEY_VALUE_RE.pattern.replace("(?P<value>", r"(?P<value>\[redacted\] |", 1), _KEY_VALUE_RE.flags,
)


def normalized_sensitive_key(value: Any) -> str:
    """Normalize case and separators before checking a key for credential semantics."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def is_sensitive_key(value: Any) -> bool:
    """Recognize credential keys across case, hyphen, underscore, and camel-case variants."""
    normalized = normalized_sensitive_key(value)
    if not normalized or normalized == "useragent":
        return False
    if normalized in _SENSITIVE_NORMALIZED_KEYS:
        return True
    if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
        return True
    if normalized == "user" or normalized.startswith("user") or normalized.endswith("user"):
        return True
    return normalized.endswith((
        "apikey", "keyid", "clientid", "consumerkey", "sessionid",
        "username", "userid", "cookie", "accesskey", "privatekey", "publickey",
        "signingkey", "subscriptionkey", "encryptionkey",
    ))


def _redacted_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return f"{value[0]}{REDACTED}{value[0]}"
    return REDACTED


def _redact_key_values(text: str, pattern: re.Pattern[str]) -> str:
    """Replace sensitive pairs without letting an outer safe pair hide nested credentials."""
    chunks: list[str] = []
    copied_through = 0
    search_from = 0
    while True:
        match = pattern.search(text, search_from)
        if match is None:
            break
        if not is_sensitive_key(match.group("key")):
            search_from = match.start() + 1
            continue
        chunks.append(text[copied_through:match.start()])
        chunks.append(f"{match.group('prefix')}{_redacted_value(match.group('value'))}")
        copied_through = match.end()
        search_from = match.end()
    if not chunks:
        return text
    chunks.append(text[copied_through:])
    return "".join(chunks)


def _redact_header_line(match: re.Match[str]) -> str:
    if not is_sensitive_key(match.group("key")):
        return match.group(0)
    return f"{match.group('indent')}{match.group('key')}{match.group('separator')}{REDACTED}"


def _redact_xml_element(match: re.Match[str]) -> str:
    local_name = match.group("key").rsplit(":", 1)[-1]
    if not is_sensitive_key(local_name):
        return match.group(0)
    return f"{match.group('open')}{REDACTED}{match.group('close')}"


def _redact_auth_scheme(match: re.Match[str], revision: str | None) -> str:
    if revision == TEXT_EVIDENCE_REVISION and match.group("scheme").casefold() == "basic":
        token = match.group(0).split(None, 1)[1].strip("\"'()[]{}<>.!?:")
        # A free prose word after 'basic' is not an HTTP credential. Explicit
        # sensitive headers/keys have already been redacted regardless of form.
        if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", token):
            return match.group(0)
        try:
            decoded = base64.b64decode(token + "=" * (-len(token) % 4), validate=True)
        except (ValueError, binascii.Error):
            return match.group(0)
        if b":" not in decoded:
            return match.group(0)
    return f"{match.group('scheme')} {REDACTED}"


def _redact_non_url_text(text: str, revision: str | None = None) -> str:
    text = _XML_SECRET_ELEMENT_RE.sub(_redact_xml_element, text)
    text = _HEADER_LINE_RE.sub(_redact_header_line, text)
    text = _redact_key_values(text, _CLI_VALUE_RE)
    text = _redact_key_values(text, _RETAINED_KEY_VALUE_RE if revision == TEXT_EVIDENCE_REVISION else _KEY_VALUE_RE)
    return _AUTH_SCHEME_RE.sub(
        lambda match: _redact_auth_scheme(match, revision), text,
    )


def _redact_url_match(match: re.Match[str], revision: str | None = None) -> str:
    candidate = match.group(0)
    trailing = ""
    while candidate and candidate[-1] in ".,;!?)]}":
        trailing = candidate[-1] + trailing
        candidate = candidate[:-1]
    sanitized = sanitize_evidence_url(candidate, text_evidence_revision=revision)
    return f"{sanitized or _redact_non_url_text(candidate, revision)}{trailing}"


def redact_sensitive_text(value: Any, *, text_evidence_revision: str | None = None) -> str:
    """Remove credentials from free-form text, embedded URLs, headers, and bodies."""
    text = "" if value is None else str(value)
    if text_evidence_revision not in {None, TEXT_EVIDENCE_REVISION}:
        raise ValueError("TEXT_EVIDENCE_REVISION_UNSUPPORTED")
    return _redact_non_url_text(_URL_RE.sub(lambda match: _redact_url_match(match, text_evidence_revision), text), text_evidence_revision)


def sanitize_evidence_url(value: Any, *, text_evidence_revision: str | None = None) -> str:
    """Return an HTTPS/HTTP URL without credential-bearing query parameters."""
    try:
        parts = urlsplit(str(value or ""))
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    safe_query = [
        (key, redact_sensitive_text(item, text_evidence_revision=text_evidence_revision))
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not is_sensitive_key(key)
    ]
    hostname = parts.hostname
    try:
        port = parts.port
    except ValueError:
        return ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if port:
        hostname = f"{hostname}:{port}"
    return urlunsplit((
        parts.scheme, hostname, _redact_non_url_text(parts.path, text_evidence_revision),
        urlencode(safe_query, doseq=True), "",
    ))


def sanitize_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    """Return response/request headers with all credential-bearing values redacted."""
    return {
        str(key): REDACTED if is_sensitive_key(key) else redact_sensitive_text(item)
        for key, item in (headers or {}).items()
    }


def validate_text_evidence(value: dict, *, expected_stage: str | None = None) -> str | None:
    """Validate only explicitly versioned PPS text; never repair legacy hashes."""
    names = [name for name in ("document_retrieval", "published_document") if name in value]
    if "text_evidence_revision" not in value and not any(
            isinstance(value[name], dict) and "text_evidence_revision" in value[name] for name in names):
        return None
    if len(names) != 1 or not isinstance(value[names[0]], dict):
        raise ValueError("TEXT_EVIDENCE_DOCUMENT_SHAPE_INVALID")
    document = value[names[0]]
    revision, document_revision = value.get("text_evidence_revision"), document.get("text_evidence_revision")
    if revision != TEXT_EVIDENCE_REVISION or document_revision != revision:
        raise ValueError("TEXT_EVIDENCE_REVISION_UNSUPPORTED_OR_MISMATCH")
    text = value.get("rendered_text") if "document_retrieval" in value else document.get("rendered_text")
    stage = document.get("rendered_text_stage")
    if (not isinstance(text, str) or not text.strip() or stage not in {"source", "retained"}
            or expected_stage is not None and stage != expected_stage
            or document.get("text_hash_algorithm") != TEXT_HASH_ALGORITHM
            or document.get("source_rendered_text_stage") != "source"):
        raise ValueError("TEXT_EVIDENCE_STAGE_OR_ALGORITHM_INVALID")
    source_hash = document.get("source_rendered_text_sha256")
    if (not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash)
            or document.get("rendered_text_sha256") != sha256_json(text)
            or stage == "source" and source_hash != document["rendered_text_sha256"]):
        raise ValueError("TEXT_EVIDENCE_HASH_MISMATCH")
    if "document_text" in value and value["document_text"] != text:
        raise ValueError("TEXT_EVIDENCE_DOCUMENT_TEXT_MISMATCH")
    abstract = value.get("abstract", "")
    facts = value.get("satisfied_facts", [])
    if (not isinstance(facts, list) or any(not isinstance(fact, str) for fact in facts)
            or not isinstance(abstract, str) or abstract and abstract not in text
            or "abstract" in facts and not abstract.strip()):
        raise ValueError("TEXT_EVIDENCE_ABSTRACT_MISMATCH")
    return stage


def _sanitize_value(value: Any, key: str = "", revision: str | None = None) -> Any:
    if is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        if revision is None and ("text_evidence_revision" in value
                or any(isinstance(value.get(name), dict) and "text_evidence_revision" in value[name]
                       for name in ("document_retrieval", "published_document"))):
            validate_text_evidence(value)
            retained = _sanitize_value(value, revision=TEXT_EVIDENCE_REVISION)
            document = retained.get("document_retrieval") if "document_retrieval" in retained else retained["published_document"]
            text = retained["rendered_text"] if "document_retrieval" in retained else document["rendered_text"]
            document.update(rendered_text_stage="retained", rendered_text_sha256=sha256_json(text))
            validate_text_evidence(retained, expected_stage="retained")
            return retained
        return {
            str(item_key): _sanitize_value(item, str(item_key), revision)
            for item_key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item, revision=revision) for item in value]
    if isinstance(value, set):
        return [_sanitize_value(item, revision=revision) for item in sorted(value, key=str)]
    if isinstance(value, str):
        return redact_sensitive_text(value, text_evidence_revision=revision)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return redact_sensitive_text(value, text_evidence_revision=revision)


def sanitize_for_evidence(value: Any, key: str = "") -> Any:
    """Remove secrets; explicit PPS revisions additionally bind retained text."""
    return _sanitize_value(value, key)


def sanitize_raw_evidence(raw_body: bytes, suffix: str) -> bytes:
    """Redact text evidence while leaving binary media untouched."""
    if not raw_body:
        return raw_body
    normalized_suffix = suffix.casefold().lstrip(".")
    text_suffixes = {"json", "txt", "xml", "html", "htm", "csv", "log", "yaml", "yml"}
    if normalized_suffix not in text_suffixes:
        try:
            decoded = raw_body.decode("utf-8")
        except UnicodeDecodeError:
            return raw_body
        if "\x00" in decoded:
            return raw_body
    else:
        decoded = raw_body.decode("utf-8", errors="replace")
    if normalized_suffix == "json" or decoded.lstrip().startswith(("{", "[")):
        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError:
            pass
        else:
            return json.dumps(
                sanitize_for_evidence(payload), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
    if normalized_suffix not in text_suffixes and not all(
        character.isprintable() or character in "\r\n\t" for character in decoded
    ):
        return raw_body
    return redact_sensitive_text(decoded).encode("utf-8")


def sanitized_request_params(value: Any) -> Any:
    """Return canonical non-secret request data suitable for evidence and hashing."""
    if isinstance(value, dict):
        return {
            str(key): sanitized_request_params(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not is_sensitive_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [sanitized_request_params(item) for item in value]
    if isinstance(value, set):
        return [sanitized_request_params(item) for item in sorted(value, key=str)]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return redact_sensitive_text(value)


def query_identity(
    provider: str, operation: str, jurisdiction: str, query: str,
    request_params: dict[str, Any] | None = None,
) -> str:
    canonical = sanitized_request_params(request_params or {"q": query})
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return stable_id("QRY", provider, operation, jurisdiction.upper(), encoded)


PLAN_META_KEYS = DECISION_PLAN_META_KEYS | {
    "query_id", "operation", "jurisdiction", "required", "wave", "derived_from",
    "requirement_id", "requirement_ids", "required_for", "right_type",
    "execute_by_default", "execute_when", "fallback_provider", "fallback_query_id",
    "role", "authoritative_for_final_rating",
    "search_dimension", "search_language", "execution_phase", "publication_scope",
}


def planned_query_metadata(task_dir: Path, provider: str, query_id: str) -> dict[str, Any]:
    """Return the exact generated plan entry bound to a source run, if any."""
    plan_path = task_dir / "search-plan.json"
    if not query_id or not plan_path.is_file():
        return {}
    try:
        plan = ensure_object(load_json(plan_path), "search-plan.json")
    except (OSError, ValueError):
        return {}
    matches = [
        item for item in plan.get("queries", {}).get(provider, [])
        if isinstance(item, dict) and str(item.get("query_id") or "") == query_id
    ]
    return dict(matches[0]) if len(matches) == 1 else {}


PLANNED_EXECUTION_OPERATIONS = {
    "search", "candidate_detail", "candidate_verification",
    "patent_recall", "utility_model_recall", "trademark_recall", "design_recall",
    "copyright_recall", "enforcement_recall", "document_retrieval", "image_search", "provenance_review",
}
EXACT_PLAN_API_PROVIDERS = {
    "epo_ops", "euipo_trademark", "euipo_design", "jpo_api",
    "inpi_api", "prv_open_data", "epo_publication_server", "serpapi_google_lens",
}


def authorize_current_scenario_action(task_dir: Path, task: dict[str, Any],
                                      provider: str, planned: dict[str, Any]) -> None:
    """Recheck current decision before any direct or scheduled provider request."""
    revision = task.get("decision_workflow_revision")
    if "decision_workflow_revision" not in task:
        return
    if revision != "scenario-triage-v1":
        raise ProviderError("DECISION_WORKFLOW_REVISION_UNSUPPORTED", "failed",
                            "Unsupported explicit decision workflow revision")
    from workflow_v24 import scenario_dispatch_block_from_dir
    blocked = scenario_dispatch_block_from_dir(task_dir, provider, planned)
    if blocked:
        raise ProviderError(str(blocked.get("code") or "SCENARIO_ACTION_BLOCKED"),
                            "failed", str(blocked.get("detail") or blocked.get("reason")
                                                  or "Action is not authorized by the current scenario and triage decision"))


def authorize_exact_plan_execution(
    task_dir: Path, task: dict[str, Any], provider: str, operation: str,
    query_id: str, *, jurisdiction: str = "", right_type: str = "",
    query: str = "", request_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind a network/data action to exactly one immutable generated plan row."""
    if str(task.get("schema_version") or "") not in {"2.3-free", "2.4-free"} or operation not in PLANNED_EXECUTION_OPERATIONS:
        return {}
    selected_id = str(query_id or "").strip()
    if not selected_id:
        raise ProviderError(
            "QUERY_ID_REQUIRED", "failed",
            f"{provider}/{operation} must select one generated search-plan query_id",
        )
    plan_path = task_dir / "search-plan.json"
    if not plan_path.is_file():
        raise ProviderError("SEARCH_PLAN_MISSING", "failed", "Generated search-plan.json is missing")
    try:
        plan = ensure_object(load_json(plan_path), "search-plan.json")
    except (OSError, ValueError):
        raise ProviderError("SEARCH_PLAN_INVALID", "failed", "Generated search-plan.json is invalid") from None
    if (
        str(plan.get("schema_version") or "") != str(task.get("schema_version") or "")
        or str(plan.get("task_id") or "") != str(task.get("task_id") or "")
        or not plan_free_policy_matches_task(task, plan)
    ):
        raise ProviderError(
            "SEARCH_PLAN_IDENTITY_MISMATCH", "failed",
            "Generated search plan does not belong to this task or free policy",
        )
    queries = plan.get("queries", {})
    if not isinstance(queries, dict):
        raise ProviderError("SEARCH_PLAN_INVALID", "failed", "search-plan queries must be an object")
    matches = [
        (str(name), item) for name, rows in queries.items()
        if isinstance(rows, list)
        for item in rows
        if isinstance(item, dict) and str(item.get("query_id") or "") == selected_id
    ]
    if len(matches) != 1 or matches[0][0] != provider:
        code = (
            "QUERY_ID_NOT_PLANNED" if not matches else
            "QUERY_ID_PROVIDER_MISMATCH" if len(matches) == 1 else
            "QUERY_ID_AMBIGUOUS"
        )
        raise ProviderError(
            code,
            "failed", f"query_id must identify exactly one {provider} plan entry",
        )
    planned = dict(matches[0][1])
    actual_scope = {
        "operation": str(operation or ""),
        "jurisdiction": str(jurisdiction or "").upper(),
        "right_type": str(right_type or ""),
    }
    planned_scope = {
        "operation": str(planned.get("operation") or ""),
        "jurisdiction": str(planned.get("jurisdiction") or "").upper(),
        "right_type": str(planned.get("right_type") or ""),
    }
    if actual_scope != planned_scope:
        raise ProviderError(
            "QUERY_PLAN_SCOPE_MISMATCH", "failed",
            "Provider operation, jurisdiction, or right type differs from the selected plan entry",
        )

    supplied = sanitized_request_params(request_params or {})
    if not isinstance(supplied, dict):
        supplied = {}
    comparable = {
        key: sanitized_request_params(value)
        for key, value in planned.items()
        if key not in PLAN_META_KEYS
    }
    actual = {**supplied}
    actual.setdefault("q", redact_sensitive_text(query))
    for key, expected in comparable.items():
        if actual.get(key) != expected:
            raise ProviderError(
                "QUERY_PLAN_PARAMETERS_MISMATCH", "failed",
                f"Request parameter {key!r} differs from the selected plan entry",
            )
    allowed_call_keys = set(comparable) | {"right_type"}
    unexpected = sorted(
        key for key, value in actual.items()
        if key not in allowed_call_keys and value not in (None, "", [], {})
    )
    if unexpected:
        raise ProviderError(
            "QUERY_PLAN_PARAMETERS_MISMATCH", "failed",
            f"Request contains parameters absent from the selected plan entry: {', '.join(unexpected)}",
        )
    expected_requirements = {
        str(value) for value in planned.get("requirement_ids", []) if str(value).strip()
    }
    if operation == "candidate_verification" and not expected_requirements:
        raise ProviderError(
            "CANDIDATE_PLAN_REQUIREMENT_MISSING", "failed",
            "Candidate verification plan entry has no operation-level requirement binding",
        )
    authorize_current_scenario_action(task_dir, task, provider, planned)
    return planned


def coverage_route_policy(
    task: dict[str, Any], provider: str, operation: str,
    *, jurisdiction: str = "", right_type: str = "",
) -> tuple[bool, bool]:
    """Resolve provider allowance and mandatory status for legacy and 2.3 tasks."""
    schema_version = str(task.get("schema_version") or "")
    if schema_version not in {"2.3-free", "2.4-free"}:
        allowed = (
            set(task.get("required_sources", []))
            | set(task.get("optional_sources", []))
            | set(task.get("low_risk_gate_sources", []))
            | {"local_high_risk_ip"}
        )
        mandatory = provider in set(task.get("required_sources", [])) | set(task.get("low_risk_gate_sources", []))
        return provider in allowed, mandatory

    if not task_free_policy_valid(task):
        return False, False
    if not canonical_coverage_requirements_match(task):
        return False, False

    if "wipo" in provider.casefold() or "patentscope" in provider.casefold():
        return False, False
    if schema_version == "2.4-free" and provider == "epo_publication_server":
        return not provider_execution_error(task, provider, operation, jurisdiction=jurisdiction, right_type=right_type), False
    if provider in SERPER_PROVIDERS:
        return not provider_execution_error(
            task, provider, operation,
            jurisdiction=jurisdiction, right_type=right_type,
        ), False
    if provider in {SERPAPI_PROVIDER, "serpapi_google_lens"}:
        return not provider_execution_error(
            task, provider, operation,
            jurisdiction=jurisdiction, right_type=right_type,
        ), False
    if provider == SIGNA_PROVIDER:
        if operation == SIGNA_OPERATION:
            return not provider_execution_error(
                task, provider, operation,
                jurisdiction=jurisdiction, right_type=right_type,
            ), False
        if operation in {"credential_check", "quota_check"} and signa_free_enabled(task):
            return True, False
        return False, False
    if provider in COMMERCIAL_PROVIDERS:
        return False, False
    matching_routes: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for requirement in task.get("coverage_requirements", []):
        if not isinstance(requirement, dict):
            continue
        if jurisdiction and str(requirement.get("jurisdiction") or "").upper() != jurisdiction.upper():
            continue
        if right_type and str(requirement.get("right_type") or "") != right_type:
            continue
        routes = requirement.get("routes", [])
        if not isinstance(routes, list):
            continue
        matching_routes.extend(
            (requirement, route)
            for route in routes
            if isinstance(route, dict)
            and str(route.get("provider") or "") == provider
            and str(route.get("operation") or "") == operation
        )
    if matching_routes:
        mandatory = any(
            route.get("required", True) is not False
            and str(requirement.get("required_for") or "") in {"formal", "low_risk"}
            and str(requirement.get("completion_policy") or "all") == "all"
            for requirement, route in matching_routes
        )
        return True, mandatory

    # Infrastructure evidence is not a coverage route, but is required to prove
    # that a configured route was usable without spending money.
    administrative_operations = {
        "api_preflight", "browser_capability", "credential_check", "free_policy_check",
        "product_capture", "blacklist_check", "quota_check",
    }
    routed_providers = {
        str(route.get("provider") or "")
        for requirement in task.get("coverage_requirements", [])
        if isinstance(requirement, dict)
        for route in requirement.get("routes", [])
        if isinstance(route, dict)
    }
    allowed = operation in administrative_operations and (
        provider in routed_providers or provider in {"amazon_browser", "local_high_risk_ip"}
    )
    return allowed, False


def require_provider_operation(
    task: dict[str, Any], provider: str, operation: str,
    *, jurisdiction: str = "", right_type: str = "",
) -> bool:
    """Raise before evidence mutation when a task did not configure the route."""
    if str(task.get("schema_version") or "") in {"2.3-free", "2.4-free"} and not task_free_policy_valid(task):
        raise ProviderError(
            "FREE_POLICY_INVALID", "failed",
            "2.3-free tasks must use the immutable official_free_only policy",
        )
    if (
        str(task.get("schema_version") or "") in {"2.3-free", "2.4-free"}
        and not canonical_coverage_requirements_match(task)
    ):
        raise ProviderError(
            "COVERAGE_REQUIREMENTS_INVALID", "failed",
            "2.3-free coverage requirements must match the canonical jurisdiction routes",
        )
    allowed, mandatory = coverage_route_policy(
        task, provider, operation, jurisdiction=jurisdiction, right_type=right_type,
    )
    if not allowed:
        if str(task.get("schema_version") or "") in {"2.3-free", "2.4-free"} and (
            "wipo" in provider.casefold() or "patentscope" in provider.casefold()
        ):
            raise ProviderError(
                "WIPO_REMOVED_FROM_2_3", "failed",
                "WIPO PATENTSCOPE is disabled for 2.3-free tasks",
            )
        if str(task.get("schema_version") or "") in {"2.3-free", "2.4-free"} and provider in COMMERCIAL_PROVIDERS:
            code = provider_execution_error(
                task, provider, operation,
                jurisdiction=jurisdiction, right_type=right_type,
            )
            raise ProviderError(
                code or "COMMERCIAL_PROVIDER_DISABLED", "failed",
                f"Commercial or freemium provider is not authorized for this task: {provider}",
            )
        raise ProviderError(
            "PROVIDER_OPERATION_NOT_CONFIGURED", "failed",
            f"Provider operation is not configured for this task: {provider}/{operation}",
        )
    return mandatory


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
    requested_right_type = str(request_params.get("right_type") or "")
    for item in plan.get("queries", {}).get(provider, []):
        if not isinstance(item, dict):
            continue
        if str(item.get("operation") or operation) != operation:
            continue
        if str(item.get("q") or item.get("query") or "") != query:
            continue
        if requested_right_type and str(item.get("right_type") or "") != requested_right_type:
            continue
        comparable = {key: value for key, value in item.items() if key not in PLAN_META_KEYS}
        if all(sanitized_request_params(request_params.get(key)) == sanitized_request_params(value) for key, value in comparable.items()):
            if item.get("query_id"):
                matches.append(str(item["query_id"]))
    return matches[0] if len(set(matches)) == 1 else ""


def raw_path(task_dir: Path, provider: str, query_id: str, digest: str, suffix: str = "json") -> Path:
    return task_dir / "raw" / provider / f"{query_id}_{digest[:16]}.{suffix}"


@contextmanager
def file_lock(lock_path: Path, timeout: float = 30):
    """Bounded cross-process locking for evidence and pre-request budgets."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + request_timeout(timeout)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(lock_path, flags, 0o600), "a+b") as handle:
        if fcntl is None and msvcrt is None:
            raise ProviderError("PROVIDER_LOCK_UNAVAILABLE", "access_limited", "Cross-process locking is required for provider state")
        if fcntl is None:
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0"); handle.flush()
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:  # pragma: no cover - native Windows call, mocked in offline tests
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                remaining = min(deadline - time.monotonic(), request_timeout(timeout))
                if remaining <= 0:
                    raise ProviderError("PROVIDER_LOCK_BUSY", "access_limited", "Provider state is busy; no parallel write or duplicate request was permitted") from None
                time.sleep(min(.05, remaining))
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            else:  # pragma: no cover - native Windows call, mocked in offline tests
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def evidence_lock(task_dir: Path):
    with file_lock(task_dir / ".evidence.lock"):
        yield


def _record_result(
    task_dir: Path, *, provider: str, operation: str, query: str, jurisdiction: str,
    evidence_type: str, status: str, normalized: Any, raw_body: bytes = b"",
    raw_suffix: str = "json", error_code: str = "", detail: str = "",
    quota: dict[str, Any] | None = None, data_date: str = "", retry_count: int = 0,
    mandatory: bool = True, request_params: dict[str, Any] | None = None,
    query_id: str = "", source_environment: str = "",
    authoritative_for_final_rating: bool | None = None,
    submission_state: str = "", execution_phase: str = "",
) -> dict[str, Any]:
    task_path, evidence_path = task_dir / "task.json", task_dir / "evidence.json"
    task = ensure_object(load_json(task_path), "task.json")
    if str(task.get("schema_version") or "") not in {"2.3-free", "2.4-free"}:
        raise ProviderError(
            "LEGACY_TASK_READ_ONLY", "failed",
            "2.1/2.2 tasks are read-only and may only rebuild or validate existing reports",
        )
    evidence = ensure_object(load_json(evidence_path), "evidence.json")
    discovery_providers = {*SERPER_PROVIDERS, SERPAPI_PROVIDER, SIGNA_PROVIDER, "serpapi_google_lens"}
    if provider in discovery_providers and evidence_type == "official_verification":
        raise ProviderError(
            "DISCOVERY_PROVIDER_NOT_AUTHORITATIVE", "failed",
            f"{provider} cannot record official-verification evidence",
        )
    if provider in SERPER_PROVIDERS:
        try:
            plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
            authorize_serper_free_plan_entry(task, plan, provider, operation, query_id)
        except (OSError, ValueError) as exc:
            code = str(exc).split(":", 1)[0] or "SERPER_QUERY_NOT_AUTHORIZED"
            raise ProviderError(
                code, "failed",
                "Serper evidence requires the exact task-authorized search-plan query_id",
            ) from None
    elif provider == SERPAPI_PROVIDER:
        try:
            plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
            authorize_serpapi_free_plan_entry(task, plan, operation, query_id)
        except (OSError, ValueError) as exc:
            code = str(exc).split(":", 1)[0] or "SERPAPI_QUERY_NOT_AUTHORIZED"
            raise ProviderError(
                code, "failed",
                "SerpApi evidence requires the exact task-authorized search-plan query_id",
            ) from None
    elif provider == SIGNA_PROVIDER and operation == SIGNA_OPERATION:
        try:
            plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
            authorize_signa_free_plan_entry(task, plan, query_id)
        except (OSError, ValueError) as exc:
            code = str(exc).split(":", 1)[0] or "SIGNA_QUERY_NOT_AUTHORIZED"
            raise ProviderError(
                code, "failed",
                "Signa evidence requires the exact task-authorized search-plan query_id",
            ) from None
    requested_right_type = str(
        (request_params or {}).get("right_type")
        or (normalized.get("right_type") if isinstance(normalized, dict) else "")
        or ""
    )
    derived_mandatory = require_provider_operation(
        task, provider, operation,
        jurisdiction=jurisdiction, right_type=requested_right_type,
    )
    if str(task.get("schema_version") or "") in {"2.3-free", "2.4-free"}:
        mandatory = derived_mandatory
    raw_paths: list[str] = []
    safe_query = redact_sensitive_text(query)
    safe_request = sanitized_request_params(request_params or {"q": query})
    normalized = sanitize_for_evidence(normalized)
    quota = sanitize_for_evidence(quota or {})
    detail = redact_sensitive_text(detail)
    raw_body = sanitize_raw_evidence(raw_body, raw_suffix)
    logical_query_id = (
        query_id
        or planned_query_id(task_dir, provider, operation, query, safe_request)
        or query_identity(provider, operation, jurisdiction, query, safe_request)
    )
    if provider in EXACT_PLAN_API_PROVIDERS:
        authorize_exact_plan_execution(
            task_dir, task, provider, operation, logical_query_id,
            jurisdiction=jurisdiction, right_type=requested_right_type,
            query=safe_query, request_params=safe_request,
        )
    plan_metadata = planned_query_metadata(task_dir, provider, logical_query_id)
    right_type = str(
        safe_request.get("right_type")
        or plan_metadata.get("right_type")
        or (normalized.get("right_type") if isinstance(normalized, dict) else "")
        or ""
    )
    requirement_ids = [
        str(value) for value in plan_metadata.get("requirement_ids", [])
        if str(value).strip()
    ]
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
        "provider": provider, "operation": operation, "query": safe_query,
        "request_params": safe_request,
        "jurisdiction": jurisdiction.upper(), "started_at": recorded_at, "finished_at": recorded_at,
        "status": status, "evidence_type": evidence_type, "raw_paths": raw_paths,
        "payload_digest": digest, "error_code": error_code, "detail": detail,
        "retry_count": retry_count, "quota": quota, "data_date": data_date,
        "right_type": right_type, "requirement_ids": list(dict.fromkeys(requirement_ids)),
    }
    if plan_metadata:
        run["plan_entry_sha256"] = sha256_bytes(json.dumps(
            plan_metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8"))
    if source_environment:
        run["source_environment"] = redact_sensitive_text(source_environment)
    if task.get("workflow_correction_revision") == "workflow-correction-v1":
        # A source failure may precede submission. Missing state is explicitly
        # unknown, never evidence that a bounded lookup consumed its attempt.
        captured = {}
        if raw_body and raw_suffix == "json":
            try:
                value = json.loads(raw_body)
                captured = value if isinstance(value, dict) else {}
            except (ValueError, UnicodeError):
                pass
        metadata = normalized.get("search_metadata", {}) if isinstance(normalized, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        observed = submission_state or captured.get("submission_state") or metadata.get("submission_state")
        if not observed and "network_request_attempted" in quota:
            observed = "submitted" if quota["network_request_attempted"] is True else "not_submitted" if quota["network_request_attempted"] is False else "unknown"
        if not observed and status in {"success", "no_result"}:
            observed = "not_submitted" if provider == "asset_provenance" else "submitted"
        if observed not in {None, "", "submitted", "not_submitted", "unknown"}:
            raise ValueError("SUBMISSION_STATE_INVALID")
        run["submission_state"] = observed or "unknown"
        run["execution_phase"] = str(execution_phase or captured.get("phase") or metadata.get("phase") or "")
    if provider in discovery_providers:
        run["authoritative_for_final_rating"] = False
    elif authoritative_for_final_rating is not None:
        run["authoritative_for_final_rating"] = authoritative_for_final_rating is True
    if isinstance(normalized, dict) and isinstance(normalized.get("search_metadata"), dict):
        run.setdefault("metadata", {})["search_coverage"] = normalized["search_metadata"]
    if plan_metadata:
        run.setdefault("metadata", {}).update({key: plan_metadata[key] for key in (
            "search_dimension", "search_language", "execution_phase", "publication_scope",
        ) if key in plan_metadata})
        run["metadata"].update({key: plan_metadata[key] for key in DECISION_PLAN_META_KEYS if key in plan_metadata})
    upsert_source_run(evidence, run)
    if status in {"success", "no_result", "not_applicable"}:
        clear_gaps(task, provider, logical_query_id)
        if provider in discovery_providers and status in {"success", "no_result"}:
            clear_optional_discovery_access_gaps(task, provider)
    elif str(task.get("schema_version") or "") in {"2.3-free", "2.4-free"} or mandatory:
        add_gap(
            task, provider, jurisdiction, status, error_code or "PROVIDER_FAILED",
            detail, mandatory, query_id=logical_query_id,
        )
        if mandatory:
            add_history(task, "incomplete", f"Required provider operation {provider}/{operation} failed: {detail}")
    collection_name = {
        "patent": "patents", "trademark": "trademarks", "copyright": "copyright_assets",
        "enforcement": "enforcement", "official_verification": "official_verifications",
        "blacklist": "blacklist", "product": "product",
        "asset_provenance": "asset_provenance",
    }.get(evidence_type)
    if collection_name and normalized not in (None, [], {}):
        entry = {
            "evidence_id": stable_id("EV", logical_query_id, digest), "source_run_id": run_id,
            "query_id": logical_query_id,
            "provider": provider, "operation": operation, "query": safe_query,
            "jurisdiction": jurisdiction.upper(), "collected_at": now_iso(), "payload": normalized,
            "right_type": right_type,
            "requirement_ids": list(dict.fromkeys(requirement_ids)),
        }
        if plan_metadata:
            entry["plan_entry_sha256"] = run["plan_entry_sha256"]
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
    source_environment: str = "",
    authoritative_for_final_rating: bool | None = None,
    submission_state: str = "", execution_phase: str = "",
) -> dict[str, Any]:
    return record_result(
        task_dir, provider=provider, operation=operation, query=query, jurisdiction=jurisdiction,
        evidence_type=evidence_type, status=error_value.source_status, normalized=None,
        error_code=error_value.code, detail=error_value.detail,
        mandatory=mandatory, request_params=request_params, query_id=query_id,
        source_environment=source_environment,
        authoritative_for_final_rating=authoritative_for_final_rating,
        submission_state=submission_state, execution_phase=execution_phase,
    )

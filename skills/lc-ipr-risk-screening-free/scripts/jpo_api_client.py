#!/usr/bin/env python3
"""Verify one Japanese patent, design, or trademark through the free JPO API.

The JPO service is identifier-based.  This client deliberately does not expose
keyword discovery and never writes OAuth-style access or refresh tokens to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlparse

from common import (
    assert_provider_execution_allowed, credential, ensure_object, load_json,
    load_skill_config, now_iso,
)
from provider_utils import (
    ProviderError, authorize_exact_plan_execution, http_json, record_error,
    record_result, sanitize_evidence_url,
)


PROVIDER = "jpo_api"
OPERATION = "candidate_verification"
DEFAULT_BASE_URL = "https://ip-data.jpo.go.jp/api"
DEFAULT_AUTH_URL = "https://ip-data.jpo.go.jp/auth/token"
SUPPORTED_RIGHT_TYPES = {
    "patent": "patent",
    "design": "design",
    "trademark_word": "trademark",
    "trademark_figurative": "trademark",
}
CASE_NUMBER_KINDS = {
    "patent": {"application", "publication", "registration"},
    "design": {"application", "registration"},
    "trademark": {"application", "registration"},
}
ENDPOINT_LIMIT_KEYS = {
    "case_number_reference": "number_reference",
    "app_progress": "progress",
    "registration_info": "registered_information",
    "jpp_fixed_address": "jplatpat_fixed_address",
}


@dataclass
class _TokenState:
    credential_fingerprint: str
    access_token: str
    refresh_token: str
    expires_at: float


_TOKEN_CACHE: _TokenState | None = None
_EXHAUSTED_ENDPOINTS: dict[str, str] = {}
JPO_TIMEZONE = timezone(timedelta(hours=9))


def _jpo_today() -> str:
    return datetime.now(JPO_TIMEZONE).date().isoformat()


def _jpo_date_for_timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=JPO_TIMEZONE)
    return parsed.astimezone(JPO_TIMEZONE).date().isoformat()


def _endpoint_exhausted(endpoint_key: str) -> bool:
    exhausted_on = _EXHAUSTED_ENDPOINTS.get(endpoint_key)
    today = _jpo_today()
    if exhausted_on and exhausted_on != today:
        _EXHAUSTED_ENDPOINTS.pop(endpoint_key, None)
        return False
    return exhausted_on == today


def _mark_endpoint_exhausted(endpoint_key: str) -> None:
    _EXHAUSTED_ENDPOINTS[endpoint_key] = _jpo_today()


def normalize_application_number(value: object) -> str:
    """Normalize a Gregorian-year JPO application number to exactly ten digits."""
    number = re.sub(r"\D", "", str(value or ""))
    if len(number) != 10:
        raise ProviderError(
            "JPO_APPLICATION_NUMBER_REQUIRED", "access_limited",
            "JPO verification requires a ten-digit Gregorian application number",
        )
    return number


def normalize_case_number(value: object, number_kind: str) -> str:
    """Normalize a supported JPO case number without accepting ambiguous lengths."""
    raw = unicodedata.normalize("NFKC", str(value or "")).strip().upper()
    # Published/registered document labels commonly include an A1/B2 kind suffix.
    raw = re.sub(r"[A-Z]\d?\s*$", "", raw)
    number = re.sub(r"\D", "", raw)
    expected_length = 7 if number_kind == "registration" else 10
    if len(number) != expected_length:
        raise ProviderError(
            "JPO_CASE_NUMBER_INVALID", "needs_user_action",
            f"JPO {number_kind} number must normalize to exactly {expected_length} digits",
        )
    return number


def _normalized_reference_values(data: dict[str, Any], number_kind: str) -> set[str]:
    """Normalize API reference fields before comparing them with the request."""
    keys = {
        "application": ("applicationNumber",),
        "publication": ("publicationNumber", "nationalPublicationNumber"),
        "registration": ("registrationNumber",),
    }[number_kind]
    values: set[str] = set()
    for key in keys:
        raw = data.get(key)
        if raw in (None, ""):
            continue
        try:
            values.add(normalize_case_number(raw, number_kind))
        except ProviderError:
            # A malformed alternate field must not hide a valid value from the
            # other official reference field, but it also cannot prove identity.
            continue
    return values


def _normalized_case_number_or_blank(value: object, number_kind: str) -> str:
    if value in (None, ""):
        return ""
    try:
        return normalize_case_number(value, number_kind)
    except ProviderError:
        return ""


def _credential_fingerprint(username: str, password: str, auth_url: str) -> str:
    """Bind the in-memory token to the exact credential pair without retaining it."""
    return hashlib.sha256(f"{username}\x1f{password}\x1f{auth_url}".encode("utf-8")).hexdigest()


def _date_text(value: object) -> str:
    raw = str(value or "").strip()
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if re.fullmatch(r"\d{8}", raw) else raw


def _strings(values: object, *keys: str) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        for key in keys:
            text = str(item.get(key) or "").strip()
            if text and text not in result:
                result.append(text)
                break
    return result


def _applicant_owners(values: object) -> list[str]:
    """Return applicants only; class 2 is an attorney and must never become owner."""
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for item in values:
        if not isinstance(item, dict) or str(item.get("applicantAttorneyClass") or "").strip() != "1":
            continue
        name = str(item.get("name") or "").strip()
        if name and name not in result:
            result.append(name)
    return result


def _first_value(*values: object) -> object:
    return next((value for value in values if value not in (None, "", [], {})), "")


def _legal_status(progress: dict[str, Any], registration: dict[str, Any]) -> str:
    disappearance = _date_text(_first_value(
        registration.get("disappearanceDate"), progress.get("disappearanceDate"),
    ))
    erasure = str(_first_value(
        registration.get("erasureIdentifier"), progress.get("erasureIdentifier"),
    )).strip()
    expiry = _date_text(_first_value(registration.get("expireDate"), progress.get("expireDate")))
    if disappearance:
        return f"right_terminated:{disappearance}"
    if erasure and erasure not in {"0", "00"}:
        return f"right_erased:{erasure}"
    if expiry and expiry < _jpo_today():
        return f"term_expired:{expiry}"
    if str(_first_value(
        registration.get("registrationNumber"), progress.get("registrationNumber"),
    )).strip():
        return "registered"
    # A progress record alone does not establish a pending/active legal status.
    return ""


def _classification(right_type: str, progress: dict[str, Any], registration: dict[str, Any]) -> list[str]:
    values: list[str] = []
    design_class = _first_value(registration.get("designClass"), progress.get("designClass"))
    if right_type == "design" and design_class:
        values.append(f"design:{design_class}")
    if right_type.startswith("trademark"):
        goods_services = [
            *(
                progress.get("goodsServiceInformation")
                if isinstance(progress.get("goodsServiceInformation"), list) else []
            ),
            *(
                registration.get("goodsServiceInformation")
                if isinstance(registration.get("goodsServiceInformation"), list) else []
            ),
        ]
        for item in goods_services:
            if not isinstance(item, dict):
                continue
            class_number = str(item.get("goodsServiceClass") or "").strip()
            similar_code = str(item.get("similarCode") or "").strip()
            if class_number:
                values.append(f"nice:{class_number}")
            if similar_code:
                values.append(f"similar_group:{similar_code}")
        vienna = _first_value(registration.get("viennaClass"), progress.get("viennaClass"))
        if vienna not in (None, "", {}, []):
            values.append(f"vienna:{json.dumps(vienna, ensure_ascii=False, sort_keys=True)}")
    return list(dict.fromkeys(values))


def normalize_verification(
    requested_right_type: str, application_number: str,
    progress: dict[str, Any], registration: dict[str, Any], fixed_address: dict[str, Any],
    candidate_id: str = "", checked_at: str = "", *, requested_number: str = "",
    requested_number_kind: str = "application", number_reference: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool, str]:
    """Return normalized evidence, whether it is complete, and any fallback reason."""
    api_right_type = SUPPORTED_RIGHT_TYPES[requested_right_type]
    page_number = str(_first_value(
        progress.get("applicationNumber"), registration.get("applicationNumber"),
    )).strip()
    try:
        normalized_page_number = normalize_application_number(page_number)
    except ProviderError:
        normalized_page_number = ""
    identity_match = normalized_page_number == application_number
    title_key = {
        "patent": "inventionTitle",
        "design": "designArticle",
        "trademark": "trademarkForDisplay",
    }[api_right_type]
    title = str(_first_value(progress.get(title_key), registration.get(title_key))).strip()
    owners = _strings(registration.get("rightPersonInformation"), "rightPersonName")
    owner_basis = "registered_right_person"
    if not owners:
        owners = _applicant_owners(progress.get("applicantAttorney"))
        owner_basis = "application_party"
    legal_status = _legal_status(progress, registration)
    updated_date = _date_text(_first_value(registration.get("updateDate"), progress.get("updateDate")))
    official_url = sanitize_evidence_url(fixed_address.get("URL"))
    parsed_official_url = urlparse(official_url)
    if official_url and (
        parsed_official_url.scheme != "https"
        or (parsed_official_url.hostname or "").casefold() != "www.j-platpat.inpit.go.jp"
    ):
        official_url = ""
    classes = _classification(requested_right_type, progress, registration)
    needs_media = requested_right_type in {"design", "trademark_figurative"}
    missing = []
    if not identity_match:
        missing.append("identity")
    if not title:
        missing.append("title")
    if not owners:
        missing.append("owner_or_applicant")
    if legal_status and owner_basis != "registered_right_person":
        missing.append("registered_right_person")
    if not legal_status:
        missing.append("legal_status")
    if not updated_date:
        missing.append("updated_date")
    if not official_url:
        missing.append("jplatpat_fixed_url")
    if requested_right_type == "design" and not classes:
        missing.append("design_class")
    if requested_right_type.startswith("trademark") and not any(
        value.startswith("nice:") for value in classes
    ):
        missing.append("goods_service_class")
    if needs_media:
        missing.append("official_media")
    complete = not missing
    fallback_reason = ",".join(missing)
    verified_at = checked_at or now_iso()
    media: list[dict[str, str]] = []
    verification_status = "verified" if complete else "partial"
    payload: dict[str, Any] = {
        "candidate_id": candidate_id,
        "right_type": requested_right_type,
        "jurisdiction": "JP",
        "requested_number": requested_number or application_number,
        "requested_number_kind": requested_number_kind,
        "number_reference": number_reference or {},
        "application_number": application_number,
        "page_application_number": page_number,
        "publication_number": _normalized_case_number_or_blank(_first_value(
            registration.get("ADPublicationNumber"), progress.get("ADPublicationNumber"),
            registration.get("publicationNumber"), progress.get("publicationNumber"),
            registration.get("ADNationalPublicationNumber"), progress.get("ADNationalPublicationNumber"),
            registration.get("nationalPublicationNumber"), progress.get("nationalPublicationNumber"),
            (number_reference or {}).get("publicationNumber"),
            (number_reference or {}).get("nationalPublicationNumber"),
            requested_number if requested_number_kind == "publication" else "",
        ), "publication"),
        "registration_number": _normalized_case_number_or_blank(_first_value(
            registration.get("registrationNumber"), progress.get("registrationNumber"),
            (number_reference or {}).get("registrationNumber"),
            requested_number if requested_number_kind == "registration" else "",
        ), "registration"),
        "title": title,
        "owners": owners,
        "classes": classes,
        "legal_status": legal_status,
        "filing_date": _date_text(_first_value(registration.get("filingDate"), progress.get("filingDate"))),
        "registration_date": _date_text(_first_value(
            registration.get("registrationDate"), progress.get("registrationDate"),
        )),
        "expiry_date": _date_text(_first_value(registration.get("expireDate"), progress.get("expireDate"))),
        "updated_date": updated_date,
        "official_verification": {
            "status": verification_status,
            "authority": "Japan Patent Office (JPO)",
            "source": "JPO Patent Information Retrieval API",
            "method": "official_free_api",
            "identity_match": identity_match,
            "legal_status": legal_status,
            "owner": owners,
            "owner_basis": owner_basis,
            "classes": classes,
            "media": media,
            "url": official_url,
            "updated_date": updated_date,
            "checked_at": verified_at,
            "fallback_required": not complete,
            "fallback_provider": "jplatpat_browser" if not complete else "",
            "missing_fields": missing,
        },
    }
    if requested_right_type.startswith("trademark"):
        payload["mark_text"] = title
        payload["goods_services"] = [
            str(item.get("goodsServiceName") or "").strip()
            for item in [
                *(
                    progress.get("goodsServiceInformation")
                    if isinstance(progress.get("goodsServiceInformation"), list) else []
                ),
                *(
                    registration.get("goodsServiceInformation")
                    if isinstance(registration.get("goodsServiceInformation"), list) else []
                ),
            ]
            if isinstance(item, dict) and str(item.get("goodsServiceName") or "").strip()
        ]
    return payload, complete, fallback_reason


def _quota_number(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    return int(text) if re.fullmatch(r"\d+", text) else None


def _endpoint_pool(endpoint: str) -> str:
    base = str(endpoint).split("/", 1)[0]
    return ENDPOINT_LIMIT_KEYS.get(base, base)


def required_endpoint_pools(number_kind: str) -> set[str]:
    pools = {
        ENDPOINT_LIMIT_KEYS["app_progress"],
        ENDPOINT_LIMIT_KEYS["registration_info"],
        ENDPOINT_LIMIT_KEYS["jpp_fixed_address"],
    }
    if number_kind != "application":
        pools.add(ENDPOINT_LIMIT_KEYS["case_number_reference"])
    return pools


def persisted_quota_block_reason(
    task_dir: Path, endpoint_pools: set[str], daily_limits: dict[str, Any],
) -> str:
    """Read prior evidence so a fresh process cannot cross a known daily limit."""
    evidence_path = task_dir / "evidence.json"
    if not evidence_path.is_file():
        return ""
    evidence = ensure_object(load_json(evidence_path), "evidence.json")
    today = _jpo_today()
    attempts = {pool: 0 for pool in endpoint_pools}
    for run in evidence.get("source_runs", []):
        if not isinstance(run, dict) or run.get("provider") != PROVIDER:
            continue
        finished_at = str(run.get("finished_at") or run.get("started_at") or "")
        if _jpo_date_for_timestamp(finished_at) != today:
            continue
        if run.get("error_code") == "FREE_QUOTA_EXHAUSTED":
            detail = str(run.get("detail") or "").casefold()
            matching = {
                pool for pool in endpoint_pools
                if pool.casefold() in detail
                or any(
                    endpoint.casefold() in detail
                    for endpoint, mapped_pool in ENDPOINT_LIMIT_KEYS.items()
                    if mapped_pool == pool
                )
            }
            if matching or not any(
                token in detail
                for token in (*ENDPOINT_LIMIT_KEYS, *ENDPOINT_LIMIT_KEYS.values())
            ):
                return "prior evidence records exhausted JPO free quota"
        quota = run.get("quota")
        if not isinstance(quota, dict):
            continue
        for endpoint, value in quota.items():
            pool = _endpoint_pool(str(endpoint))
            if pool not in endpoint_pools or not isinstance(value, dict):
                continue
            attempts[pool] += 1
            remaining = _quota_number(value.get("remaining"))
            status_code = str(value.get("status_code") if value.get("status_code") is not None else "")
            if remaining == 0 or status_code == "203":
                return f"prior evidence records exhausted JPO {pool} free quota"
    for pool, count in attempts.items():
        limit = _quota_number(daily_limits.get(pool))
        if limit is not None and count >= limit:
            return f"recorded JPO {pool} attempts reached the documented daily limit {limit}"
    return ""


class JpoApiClient:
    """Small authenticated client with process-memory-only token caching."""

    def __init__(
        self, config: dict[str, Any] | None = None,
        transport: Callable[..., tuple[dict[str, Any], dict[str, str], bytes]] = http_json,
    ) -> None:
        self.config = config or load_skill_config()
        provider_config = self.config.get("providers", {}).get(PROVIDER, {})
        test_mode = os.environ.get("LC_IPR_TEST_MODE", "") == "1"
        test_base_url = os.environ.get("JPO_API_BASE_URL", "") if test_mode else ""
        test_auth_url = os.environ.get("JPO_AUTH_URL", "") if test_mode else ""
        self.base_url = str(
            test_base_url or provider_config.get("base_url") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.auth_url = str(
            test_auth_url or provider_config.get("auth_url") or DEFAULT_AUTH_URL
        )
        self.timeout = int(provider_config.get("timeout_seconds") or 30)
        self.daily_limits = provider_config.get("daily_limits", {})
        self.transport = transport
        self._refresh_used = False
        allowed_test_hosts = {"127.0.0.1", "localhost", "::1"}
        base_host = (urlparse(self.base_url).hostname or "").casefold()
        auth_host = (urlparse(self.auth_url).hostname or "").casefold()
        official = self.base_url == DEFAULT_BASE_URL and self.auth_url == DEFAULT_AUTH_URL
        safe_test_override = test_mode and base_host in allowed_test_hosts and auth_host in allowed_test_hosts
        if not official and not safe_test_override:
            raise ProviderError(
                "JPO_ENDPOINT_NOT_OFFICIAL", "failed",
                "JPO API endpoints must use the official ip-data.jpo.go.jp service",
            )
        self.source_environment = "production" if official and not test_mode else "test_fixture"
        self.authoritative_for_final_rating = official and not test_mode

    def _credentials(self) -> tuple[str, str]:
        username = credential(self.config, "jpo_api_username").strip()
        password = credential(self.config, "jpo_api_password")
        if not username or not password:
            raise ProviderError(
                "JPO_CREDENTIALS_MISSING", "access_limited",
                "JPO_API_USERNAME and JPO_API_PASSWORD are required for the free JPO API",
            )
        return username, password

    def _authenticate(self, *, refresh: bool = False) -> str:
        global _TOKEN_CACHE
        username, password = self._credentials()
        fingerprint = _credential_fingerprint(username, password, self.auth_url)
        if (
            not refresh and _TOKEN_CACHE
            and _TOKEN_CACHE.credential_fingerprint == fingerprint
            and _TOKEN_CACHE.expires_at > time.monotonic() + 60
        ):
            return _TOKEN_CACHE.access_token
        if refresh and _TOKEN_CACHE and _TOKEN_CACHE.refresh_token:
            form = {
                "grant_type": "refresh_token",
                "refresh_token": _TOKEN_CACHE.refresh_token,
            }
        else:
            form = {
                "grant_type": "password",
                "username": username,
                "password": password,
            }
        payload, _, _ = self.transport(
            self.auth_url,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=urlencode(form).encode("utf-8"),
            timeout=self.timeout,
            retries=0,
        )
        access_token = str(payload.get("access_token") or payload.get("accessToken") or "")
        if not access_token:
            raise ProviderError(
                "JPO_AUTH_RESPONSE_INVALID", "access_limited",
                "JPO authentication did not return an access token",
            )
        refresh_token = str(payload.get("refresh_token") or payload.get("refreshToken") or "")
        try:
            expires_in = max(60, int(payload.get("expires_in") or payload.get("expiresIn") or 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        _TOKEN_CACHE = _TokenState(
            credential_fingerprint=fingerprint,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.monotonic() + expires_in,
        )
        return access_token

    def access_token(self, *, force_refresh: bool = False) -> str:
        """Return a token to an in-process caller without exposing it in evidence."""
        return self._authenticate(refresh=force_refresh)

    def _get(self, api_right_type: str, endpoint: str, case_number: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
        endpoint_pool = _endpoint_pool(endpoint)
        endpoint_key = f"{api_right_type}:{endpoint_pool}"
        if _endpoint_exhausted(endpoint_key):
            raise ProviderError(
                "FREE_QUOTA_EXHAUSTED", "access_limited",
                f"JPO daily free access limit is already exhausted for {endpoint_pool}",
            )
        token = self._authenticate()
        while True:
            try:
                payload, _, body = self.transport(
                    f"{self.base_url}/{api_right_type}/v1/{endpoint}/{quote(case_number, safe='')}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=self.timeout,
                    retries=1,
                )
                break
            except ProviderError as exc:
                if exc.code == "AUTH_FAILED" and not self._refresh_used:
                    self._refresh_used = True
                    token = self._authenticate(refresh=True)
                    continue
                raise
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED", "failed",
                f"JPO {endpoint} response is missing result",
            )
        status_value = result.get("statusCode")
        status_code = "" if status_value is None else str(status_value)
        remaining_value = result.get("remainAccessCount")
        quota = {
            "status_code": status_code,
            "remaining": "" if remaining_value is None else str(remaining_value),
            "documented_daily_limit": self.daily_limits.get(endpoint_pool, ""),
        }
        if quota["remaining"].isdigit() and int(quota["remaining"]) <= 0:
            _mark_endpoint_exhausted(endpoint_key)
        if status_code == "100":
            data = result.get("data")
            if not isinstance(data, dict):
                raise ProviderError(
                    "RESPONSE_SCHEMA_CHANGED", "failed",
                    f"JPO {endpoint} success response is missing data",
                )
            return data, quota, body
        if status_code in {"107", "111"}:
            return {}, quota, body
        if status_code == "203":
            _mark_endpoint_exhausted(endpoint_key)
            raise ProviderError(
                "FREE_QUOTA_EXHAUSTED", "access_limited",
                f"JPO daily free access limit reached for {endpoint}",
            )
        if status_code in {"204", "208"}:
            raise ProviderError(
                "JPO_PARAMETER_REJECTED", "failed",
                f"JPO rejected the case number for {endpoint}",
            )
        raise ProviderError(
            "JPO_API_ERROR", "failed",
            f"JPO {endpoint} returned status {status_code or 'unknown'}",
        )

    def verify(
        self, right_type: str, case_number: str, candidate_id: str = "", *,
        number_kind: str = "application", task_dir: Path | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any], bytes, bool, str]:
        if right_type == "utility_model":
            raise ProviderError(
                "JPO_API_UNSUPPORTED_RIGHT_TYPE", "needs_user_action",
                "The JPO retrieval API does not cover utility models; use J-PlatPat browser verification",
            )
        if right_type not in SUPPORTED_RIGHT_TYPES:
            raise ProviderError(
                "JPO_RIGHT_TYPE_INVALID", "failed",
                f"Unsupported JPO right type: {right_type}",
            )
        api_right_type = SUPPORTED_RIGHT_TYPES[right_type]
        if number_kind not in CASE_NUMBER_KINDS[api_right_type]:
            raise ProviderError(
                "JPO_NUMBER_KIND_INVALID", "needs_user_action",
                f"JPO {right_type} does not support {number_kind} number conversion",
            )
        requested_number = normalize_case_number(case_number, number_kind)
        endpoint_pools = required_endpoint_pools(number_kind)
        if task_dir is not None:
            quota_reason = persisted_quota_block_reason(task_dir, endpoint_pools, self.daily_limits)
            if quota_reason:
                raise ProviderError(
                    "FREE_QUOTA_EXHAUSTED", "access_limited",
                    f"{quota_reason}; request stopped before authentication or retrieval",
                )
        self._refresh_used = False
        endpoint_data: dict[str, dict[str, Any]] = {}
        quota: dict[str, Any] = {}
        raw_payload: dict[str, Any] = {"endpoints": {}}
        number_reference: dict[str, Any] = {}
        if number_kind == "application":
            application_number = normalize_application_number(requested_number)
        else:
            endpoint = f"case_number_reference/{number_kind}"
            data, endpoint_quota, raw_body = self._get(
                api_right_type, endpoint, requested_number,
            )
            quota["case_number_reference"] = endpoint_quota
            try:
                raw_payload["endpoints"]["case_number_reference"] = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raw_payload["endpoints"]["case_number_reference"] = {"response_schema": "unparseable"}
            if not data:
                return (
                    None, quota, json.dumps(raw_payload, ensure_ascii=False).encode("utf-8"),
                    False, "number_reference_not_found",
                )
            reference_values = _normalized_reference_values(data, number_kind)
            if requested_number not in reference_values:
                raise ProviderError(
                    "JPO_NUMBER_REFERENCE_IDENTITY_MISMATCH", "failed",
                    "JPO number-reference response does not match the requested case number",
                )
            application_number = str(data.get("applicationNumber") or "").strip()
            try:
                application_number = normalize_application_number(application_number)
            except ProviderError as exc:
                raise ProviderError(
                    "JPO_NUMBER_REFERENCE_INCOMPLETE", "access_limited",
                    "JPO number-reference response did not provide a valid application number",
                ) from exc
            number_reference = data
        for endpoint in ("app_progress",):
            data, endpoint_quota, raw_body = self._get(api_right_type, endpoint, application_number)
            endpoint_data[endpoint] = data
            quota[endpoint] = endpoint_quota
            try:
                raw_payload["endpoints"][endpoint] = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raw_payload["endpoints"][endpoint] = {"response_schema": "unparseable"}
        if not endpoint_data["app_progress"]:
            return None, quota, json.dumps(raw_payload, ensure_ascii=False).encode("utf-8"), False, "no_applicable_data"
        for endpoint in ("registration_info", "jpp_fixed_address"):
            data, endpoint_quota, raw_body = self._get(api_right_type, endpoint, application_number)
            endpoint_data[endpoint] = data
            quota[endpoint] = endpoint_quota
            try:
                raw_payload["endpoints"][endpoint] = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raw_payload["endpoints"][endpoint] = {"response_schema": "unparseable"}
        normalized, complete, detail = normalize_verification(
            right_type,
            application_number,
            endpoint_data["app_progress"],
            endpoint_data["registration_info"],
            endpoint_data["jpp_fixed_address"],
            candidate_id,
            requested_number=requested_number,
            requested_number_kind=number_kind,
            number_reference=number_reference,
        )
        return normalized, quota, json.dumps(raw_payload, ensure_ascii=False).encode("utf-8"), complete, detail


def probe(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Authenticate once for preflight without consuming a retrieval endpoint quota."""
    client = JpoApiClient(config=config)
    client.access_token()
    return {
        "status": "success",
        "ready": True,
        "provider": PROVIDER,
        "environment": client.source_environment,
        "authoritative_for_final_rating": client.authoritative_for_final_rating,
        "authentication": "password_grant_to_in_memory_bearer",
        "base_url": DEFAULT_BASE_URL,
        "checked_at": now_iso(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify one record through the free JPO API.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument(
        "--right-type",
        choices=["patent", "design", "trademark_word", "trademark_figurative", "utility_model"],
        required=True,
    )
    numbers = parser.add_mutually_exclusive_group(required=True)
    numbers.add_argument("--number")
    numbers.add_argument(
        "--application-number",
        help="Legacy alias for --number with --number-kind=application",
    )
    parser.add_argument(
        "--number-kind", choices=["application", "publication", "registration"],
        default="application",
    )
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--mandatory", action="store_true")
    args = parser.parse_args()
    if args.application_number and args.number_kind != "application":
        parser.error("--application-number can only be used with --number-kind=application")
    case_number = str(args.number or args.application_number or "").strip()
    task_dir = args.task_dir.expanduser().resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if "JP" not in {str(item).upper() for item in task.get("target_jurisdictions", [])}:
        raise SystemExit("JPO verification is only valid for a JP task")
    if args.right_type == "utility_model":
        print(json.dumps({
            "status": "needs_user_action",
            "provider": PROVIDER,
            "operation": OPERATION,
            "error_code": "JPO_API_UNSUPPORTED_RIGHT_TYPE",
            "detail": "The JPO retrieval API does not cover utility models; use one J-PlatPat browser verification.",
            "fallback_provider": "jplatpat_browser",
        }, ensure_ascii=False))
        raise SystemExit(2)
    try:
        assert_provider_execution_allowed(
            task, PROVIDER, OPERATION, jurisdiction="JP", right_type=args.right_type,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    request_params = {
        "number": case_number,
        "number_kind": args.number_kind,
        "right_type": args.right_type,
        "candidate_id": args.candidate_id,
    }
    try:
        authorize_exact_plan_execution(
            task_dir, task, PROVIDER, OPERATION, args.query_id,
            jurisdiction="JP", right_type=args.right_type, query=case_number,
            request_params=request_params,
        )
    except ProviderError as exc:
        raise SystemExit(f"{exc.code}: {exc.detail}") from None
    try:
        client = JpoApiClient()
        normalized, quota, raw_body, complete, fallback_reason = client.verify(
            args.right_type, case_number, args.candidate_id,
            number_kind=args.number_kind, task_dir=task_dir,
        )
        if isinstance(normalized, dict):
            normalized["source_environment"] = client.source_environment
            normalized["authoritative_for_final_rating"] = client.authoritative_for_final_rating
            if not client.authoritative_for_final_rating:
                verification = normalized.get("official_verification")
                if isinstance(verification, dict):
                    verification["status"] = "not_checked"
                    verification["reason"] = "non_authoritative_test_fixture"
                complete = False
                fallback_reason = "non_authoritative_test_fixture"
        if normalized is None:
            status = "access_limited"
            error_code = "OFFICIAL_VERIFICATION_NOT_FOUND"
            detail = "JPO returned no applicable application data; verify the identifier in J-PlatPat"
        elif complete:
            status = "success"
            error_code = ""
            detail = ""
        else:
            status = "access_limited"
            error_code = "OFFICIAL_VERIFICATION_INCOMPLETE"
            detail = f"JPO record requires J-PlatPat fallback for: {fallback_reason}"
        run = record_result(
            task_dir,
            provider=PROVIDER,
            operation=OPERATION,
            query=case_number,
            jurisdiction="JP",
            evidence_type="official_verification",
            status=status,
            normalized=normalized,
            raw_body=raw_body,
            raw_suffix="json",
            error_code=error_code,
            detail=detail,
            quota=quota,
            mandatory=args.mandatory,
            request_params=request_params,
            query_id=args.query_id,
            source_environment=client.source_environment,
            authoritative_for_final_rating=client.authoritative_for_final_rating,
        )
    except ProviderError as exc:
        source_environment = (
            client.source_environment if "client" in locals() else
            ("test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1" else "production")
        )
        authoritative = client.authoritative_for_final_rating if "client" in locals() else False
        run = record_error(
            task_dir,
            provider=PROVIDER,
            operation=OPERATION,
            query=case_number,
            jurisdiction="JP",
            evidence_type="official_verification",
            error_value=exc,
            mandatory=args.mandatory,
            request_params=request_params,
            query_id=args.query_id,
            source_environment=source_environment,
            authoritative_for_final_rating=authoritative,
        )
    print(json.dumps({
        "status": run["status"],
        "provider": PROVIDER,
        "operation": OPERATION,
        "run_id": run["run_id"],
        "error_code": run.get("error_code", ""),
        "detail": run.get("detail", ""),
        "fallback_provider": "jplatpat_browser" if run["status"] not in {"success", "no_result"} else "",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

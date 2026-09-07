#!/usr/bin/env python3
"""EUIPO Trademark Search and Design Search OAuth client."""

from __future__ import annotations

import argparse
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlencode, urlparse

from common import (
    assert_provider_execution_allowed, atomic_write_bytes, credential, ensure_object,
    image_info, load_json, load_skill_config, now_iso, sha256_bytes,
)
from provider_utils import (
    ProviderError, authorize_exact_plan_execution, http_json, http_request,
    quota_summary, record_error, record_result,
)


_TOKEN_CACHE: dict[str, object] = {"access_token": "", "expires_at": 0.0}
PRODUCTION_ENDPOINTS = {
    "token": "https://euipo.europa.eu/cas-server-webapp/oidc/accessToken",
    "trademark": "https://api.euipo.europa.eu/trademark-search",
    "design": "https://api.euipo.europa.eu/design-search",
}
SANDBOX_ENDPOINTS = {
    "token": "https://auth-sandbox.euipo.europa.eu/oidc/accessToken",
    "trademark": "https://api-sandbox.euipo.europa.eu/trademark-search",
    "design": "https://api-sandbox.euipo.europa.eu/design-search",
}


def _resolved_endpoints(cfg: dict, environment: str) -> dict[str, str]:
    """Bind Production/Sandbox identity to exact official endpoint families."""
    if environment not in {"production", "sandbox"}:
        raise ProviderError(
            "EUIPO_ENVIRONMENT_INVALID", "access_limited",
            f"Unsupported EUIPO environment: {environment or '(missing)'}",
        )
    expected = PRODUCTION_ENDPOINTS if environment == "production" else SANDBOX_ENDPOINTS
    values = {
        "token": os.environ.get("EUIPO_TOKEN_URL", str(cfg.get("token_url") or expected["token"])),
        "trademark": os.environ.get(
            "EUIPO_TRADEMARK_BASE_URL", str(cfg.get("trademark_base_url") or expected["trademark"]),
        ),
        "design": os.environ.get(
            "EUIPO_DESIGN_BASE_URL", str(cfg.get("design_base_url") or expected["design"]),
        ),
    }
    if os.environ.get("LC_IPR_TEST_MODE") == "1":
        for key, value in values.items():
            parsed = urlparse(value)
            host = (parsed.hostname or "").casefold()
            expected_host = (urlparse(expected[key]).hostname or "").casefold()
            if (
                parsed.scheme not in {"http", "https"}
                or host not in {"127.0.0.1", "localhost", "::1", expected_host}
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
            ):
                raise ProviderError(
                    "EUIPO_TEST_ENDPOINT_NOT_LOCAL", "access_limited",
                    "EUIPO test overrides must be loopback or the matching official host",
                )
        return {key: value.rstrip("/") for key, value in values.items()}
    for key, value in values.items():
        parsed = urlparse(value)
        expected_parsed = urlparse(expected[key])
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (parsed.hostname or "").casefold() != (expected_parsed.hostname or "").casefold()
            or parsed.path.rstrip("/") != expected_parsed.path.rstrip("/")
        ):
            raise ProviderError(
                "EUIPO_ENVIRONMENT_ENDPOINT_MISMATCH", "access_limited",
                f"EUIPO {environment} {key} endpoint does not match the official environment",
            )
    return {key: value.rstrip("/") for key, value in values.items()}


def settings() -> tuple[dict, dict, str, str]:
    config = load_skill_config()
    return config, config["providers"]["euipo"], credential(config, "euipo_client_id"), credential(config, "euipo_client_secret")


def source_profile() -> tuple[str, bool]:
    """Return the active EUIPO environment and whether it is legally authoritative."""
    _, cfg, _, _ = settings()
    environment = os.environ.get("EUIPO_ENVIRONMENT", str(cfg.get("environment", "production"))).strip().lower()
    authoritative_override = os.environ.get("EUIPO_AUTHORITATIVE_FOR_FINAL_RATING")
    configured_authoritative = (
        authoritative_override.strip().lower() in {"1", "true", "yes"}
        if authoritative_override is not None
        else bool(cfg.get("authoritative_for_final_rating", True))
    )
    _resolved_endpoints(cfg, environment)
    # Test endpoint overrides exist only for deterministic fixtures.  Evidence
    # created while that escape hatch is active must never satisfy a formal
    # Production coverage gate, even when the configured environment is named
    # ``production``.
    if os.environ.get("LC_IPR_TEST_MODE") == "1":
        return "test_fixture", False
    authoritative = environment == "production" and configured_authoritative
    return environment, authoritative


def token() -> str:
    cached = str(_TOKEN_CACHE.get("access_token") or "")
    if cached and float(_TOKEN_CACHE.get("expires_at") or 0) > time.time():
        return cached
    config, cfg, client_id, secret = settings()
    if not client_id or not secret:
        raise ProviderError("AUTH_FAILED", "access_limited", "EUIPO client credentials are missing")
    environment = os.environ.get("EUIPO_ENVIRONMENT", str(cfg.get("environment", "production"))).strip().lower()
    token_url = _resolved_endpoints(cfg, environment)["token"]
    payload, _, _ = http_json(token_url, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=urlencode({
            "grant_type": "client_credentials", "client_id": client_id, "client_secret": secret,
            "scope": str(cfg.get("client_credentials_scope", "uid")),
        }).encode(),
        timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]))
    value = payload.get("access_token")
    if not value:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO token response has no access_token")
    expires_in = max(int(payload.get("expires_in", 300)), 1)
    _TOKEN_CACHE.update({"access_token": str(value), "expires_at": time.time() + max(expires_in - 30, 1)})
    return str(value)


def api_get(product: str, path: str, params: dict | None = None) -> tuple[dict, dict[str, str], bytes]:
    config, cfg, client_id, _ = settings()
    environment = os.environ.get("EUIPO_ENVIRONMENT", str(cfg.get("environment", "production"))).strip().lower()
    base = _resolved_endpoints(cfg, environment)[product]
    url = f"{base}/{path.lstrip('/')}"
    if params:
        url += "?" + urlencode(params, doseq=True)
    headers = {"Authorization": f"Bearer {token()}", "X-IBM-Client-Id": client_id, "Accept": "application/json"}
    try:
        return http_json(url, headers=headers, timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]))
    except ProviderError as exc:
        if exc.code != "AUTH_FAILED":
            raise
        _TOKEN_CACHE.update({"access_token": "", "expires_at": 0.0})
        headers["Authorization"] = f"Bearer {token()}"
        return http_json(url, headers=headers, timeout=int(config["http"]["timeout_seconds"]), retries=0)


def api_bytes(product: str, path: str) -> tuple[bytes, dict[str, str]]:
    config, cfg, client_id, _ = settings()
    environment = os.environ.get("EUIPO_ENVIRONMENT", str(cfg.get("environment", "production"))).strip().lower()
    base = _resolved_endpoints(cfg, environment)[product]
    url = f"{base}/{path.lstrip('/')}"
    request_headers = {"Authorization": f"Bearer {token()}", "X-IBM-Client-Id": client_id, "Accept": "*/*"}
    try:
        _, headers, body = http_request(url, headers=request_headers, timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]))
    except ProviderError as exc:
        if exc.code != "AUTH_FAILED":
            raise
        _TOKEN_CACHE.update({"access_token": "", "expires_at": 0.0})
        request_headers["Authorization"] = f"Bearer {token()}"
        _, headers, body = http_request(url, headers=request_headers, timeout=int(config["http"]["timeout_seconds"]), retries=0)
    return body, headers


def _content_type(headers: dict[str, str]) -> str:
    return next((value for key, value in headers.items() if key.casefold() == "content-type"), "")


def _probe_sandbox_design_fixture(cfg: dict) -> dict:
    identifier = str(cfg.get("sandbox_fixture_design_number") or "").strip()
    if not re.fullmatch(r"\d{9}-\d{4}", identifier):
        raise ProviderError(
            "COVERAGE_UNVERIFIED", "access_limited",
            "EUIPO Sandbox fixture design number is missing or invalid",
        )
    try:
        detail, detail_headers, _ = api_get("design", f"designs/{identifier}")
        actual = str(detail.get("designNumber") or "")
        if actual != identifier:
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED", "failed",
                "EUIPO Sandbox fixture detail identifier mismatch",
            )
        views = detail.get("views")
        if not isinstance(views, list) or not views:
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED", "failed",
                "EUIPO Sandbox fixture detail has no views",
            )
        first_order = next(
            (int(view.get("order")) for view in views if isinstance(view, dict) and str(view.get("order", "")).isdigit()),
            None,
        )
        if first_order is None:
            raise ProviderError(
                "RESPONSE_SCHEMA_CHANGED", "failed",
                "EUIPO Sandbox fixture has no valid view order",
            )
        view_body, view_headers = api_bytes("design", f"designs/{identifier}/views/{first_order}")
        thumb_body, thumb_headers = api_bytes("design", f"designs/{identifier}/views/{first_order}/thumbnail")
        if not view_body or not _content_type(view_headers).casefold().startswith("image/"):
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO Sandbox fixture view is not an image")
        if not thumb_body or not _content_type(thumb_headers).casefold().startswith("image/"):
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO Sandbox fixture thumbnail is not an image")
    except ProviderError as exc:
        if exc.http_status in {400, 404}:
            raise ProviderError(
                "COVERAGE_UNVERIFIED", "access_limited",
                f"EUIPO Sandbox fixture {identifier} is unavailable in Design Detail/Views",
                exc.http_status,
            ) from exc
        raise
    return {
        "fixture_design_number": identifier,
        "detail_ready": True,
        "views_ready": True,
        "thumbnail_ready": True,
        "view_count": len(views),
        "checked_view_order": first_order,
        "detail_quota": quota_summary(detail_headers, detail),
    }


def probe(product: str | None = None) -> dict:
    products = (product,) if product else ("trademark", "design")
    if any(value not in {"trademark", "design"} for value in products):
        raise ValueError(f"Unsupported EUIPO product: {product}")
    _, cfg, _, _ = settings()
    configured_environment = os.environ.get(
        "EUIPO_ENVIRONMENT", str(cfg.get("environment", "production")),
    ).strip().lower()
    _resolved_endpoints(cfg, configured_environment)
    if configured_environment == "production" and str(cfg.get("access_tier") or "") != "registered_free":
        raise ProviderError(
            "EUIPO_PRODUCTION_PROFILE_INVALID", "access_limited",
            "EUIPO Production must use the registered_free access profile",
        )
    versions = cfg.get("api_versions")
    expected_versions = {
        "trademark": ("trademark_search", "1.1.0"),
        "design": ("design_search", "1.1.0"),
    }
    if not isinstance(versions, dict) or any(
        str(versions.get(expected_versions[current_product][0]) or "")
        != expected_versions[current_product][1]
        for current_product in products
    ):
        raise ProviderError(
            "EUIPO_API_PROFILE_INVALID", "access_limited",
            "EUIPO Search API profile must match the configured 1.1.0 client contract",
        )

    environment, authoritative = source_profile()
    token()
    coverage = {
        current_product: {
            "oauth_ready": True,
            "endpoint_profile_valid": True,
            "api_version": expected_versions[current_product][1],
            "search_probe_performed": False,
            "subscription_status": "deferred_to_exact_planned_query",
        }
        for current_product in products
    }
    return {
        "ready": True,
        "oauth_ready": True,
        "environment": environment,
        "configured_environment": configured_environment,
        "authoritative_for_final_rating": authoritative,
        "coverage": coverage,
    }


def mark_text(item: dict) -> str:
    value = item.get("wordMark") or item.get("markText") or item.get("wordMarkSpecification") or ""
    if isinstance(value, dict):
        return str(value.get("verbalElement") or value.get("value") or "")
    return str(value) if value is not None else ""


def applicant_names(item: dict) -> list[str]:
    applicants = item.get("applicants") or item.get("owners") or []
    if not isinstance(applicants, list):
        return []
    return [
        str(value.get("name") or "").strip()
        for value in applicants
        if isinstance(value, dict) and str(value.get("name") or "").strip()
    ]


def _rsql_contains_value(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not normalized:
        raise ProviderError("INVALID_QUERY", "failed", "EUIPO search term is empty")
    wildcard = f"*{normalized}*"
    # Follow the official examples for URI-safe tokens.  Phrases and values
    # containing RSQL-reserved characters use the grammar's quoted form.
    if not re.search(r'''[\s"'(),;=!~<>\\]''', normalized):
        return wildcard
    escaped = normalized.replace("\\", "\\\\").replace('"', '\\"')
    return f'"*{escaped}*"'


def search_rsql(product: str, value: str, right_type: str) -> str:
    """Build only selectors documented by the official EUIPO 1.1.0 specs."""
    if product == "trademark":
        if right_type != "trademark_word":
            raise ProviderError(
                "EUIPO_FIGURATIVE_CLASS_SEARCH_UNSUPPORTED", "access_limited",
                "Trademark Search 1.1.0 cannot query Vienna classes; retain a coverage gap until a compatible automatic route is accepted",
            )
        return "wordMarkSpecification.verbalElement==" + _rsql_contains_value(value)
    if product == "design":
        if right_type != "design":
            raise ProviderError("INVALID_QUERY", "failed", "EUIPO design search requires right_type=design")
        normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
        if re.fullmatch(r"\d{1,2}\.\d{2}", normalized):
            return f"locarnoClasses=={normalized}"
        return "productIndications==" + _rsql_contains_value(normalized)
    raise ProviderError("INVALID_QUERY", "failed", f"Unsupported EUIPO product: {product}")


def search_parameters(
    product: str, value: str, right_type: str, page: int, size: int,
) -> tuple[dict[str, object], dict[str, object]]:
    """Return the official HTTP parameters and the richer evidence parameters.

    EUIPO Search 1.1.0 accepts ``query/page/size`` for this call.  The raw term
    and right type remain evidence metadata and must not leak into the request.
    """
    rsql = search_rsql(product, value, right_type)
    return (
        {"query": rsql, "page": page, "size": size},
        {
            "q": value, "query": rsql, "page": page,
            "size": size, "right_type": right_type,
        },
    )


def _class_numbers_from_goods(item: dict) -> list[str]:
    values = item.get("goodsAndServices")
    if not isinstance(values, list):
        return []
    return list(dict.fromkeys(
        str(row.get("classNumber")).strip()
        for row in values
        if isinstance(row, dict) and str(row.get("classNumber") or "").strip()
    ))


def _locarno_classes(item: dict) -> list[str]:
    direct = item.get("locarnoClasses")
    output = [str(value).strip() for value in direct if str(value).strip()] if isinstance(direct, list) else []
    details = item.get("locarnoClassification")
    if isinstance(details, list):
        output.extend(
            str(row.get("classNumber")).strip()
            for row in details
            if isinstance(row, dict) and str(row.get("classNumber") or "").strip()
        )
    return list(dict.fromkeys(output))


def _product_indications(item: dict) -> list[str]:
    values = item.get("productIndications")
    if not isinstance(values, list):
        return []
    output: list[str] = []
    for row in values:
        if not isinstance(row, dict) or not isinstance(row.get("terms"), list):
            continue
        output.extend(str(value).strip() for value in row["terms"] if str(value).strip())
    return list(dict.fromkeys(output))


def normalize(product: str, payload: dict, right_type: str = "") -> list[dict]:
    environment, authoritative = source_profile()
    if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO response is not a successful search envelope")
    keys = [key for key in ("trademarks" if product == "trademark" else "designs", "content", "data", "results") if key in payload]
    if len(keys) != 1:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO search must contain one explicit result collection")
    rows = payload[keys[0]]
    if not isinstance(rows, list):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", f"EUIPO {product} response schema changed")
    candidates = []
    for item in rows:
        if not isinstance(item, dict):
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO result is not an object")
        identifier = (item.get("applicationNumber") or item.get("application_number")) if product == "trademark" else (item.get("designNumber") or item.get("applicationNumber"))
        if not isinstance(identifier, str) or not identifier.strip():
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO search result has no stable identifier")
        if product == "trademark":
            candidates.append({
                "jurisdiction": "EU", "right_type": right_type or "trademark_word",
                "office": "euipo", "application_number": item.get("applicationNumber") or item.get("application_number") or "",
                "registration_number": item.get("registrationNumber") or "", "mark_text": mark_text(item),
                "owner": item.get("ownerName") or "; ".join(applicant_names(item)), "status": item.get("status") or "", "nice_classes": item.get("niceClasses") or [],
                "source": "euipo_trademark", "material": False,
                "source_environment": environment,
                "authoritative_for_final_rating": authoritative,
                "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
            })
        else:
            candidates.append({
                "right_type": "design",
                "publication_number": item.get("designNumber") or item.get("applicationNumber") or "", "jurisdiction": "EU",
                "locarno": _locarno_classes(item), "title": "; ".join(_product_indications(item)),
                "views": item.get("views") or [], "source": "euipo_design", "material": False,
                "source_environment": environment,
                "authoritative_for_final_rating": authoritative,
                "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
            })
    return candidates


def search_metadata(payload: dict, candidates: list, page: int, size: int) -> dict:
    pagination = payload.get("page") if isinstance(payload.get("page"), dict) else {}
    raw = next((value for value in (payload.get("totalElements"), payload.get("totalResults"), payload.get("total"), pagination.get("totalElements")) if value is not None), None)
    total = int(raw) if not isinstance(raw, bool) and str(raw).isdigit() else None
    if raw is not None and total is None:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO result total is invalid")
    if total is not None and (total < len(candidates) or total == 0 and candidates):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO result total contradicts the returned records")
    if not candidates and total is not None and total > page * size:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO returned an empty page before the stated result total")
    truncated = total is None or page > 0 or total > len(candidates)
    return {"total_hits": total, "retrieved_hits": len(candidates), "reviewed_hits": None,
            "truncated": truncated, "stop_reason": "total_unknown" if total is None else "page_limit" if truncated else "query_exhausted",
            "source_updated_at": None, "schema_valid": True, "page": page, "page_size": size}


def verified_detail(
    product: str, identifier: str, payload: dict, media: list[dict], right_type: str = "",
) -> dict:
    environment, authoritative = source_profile()
    if product == "trademark":
        actual = str(payload.get("applicationNumber") or payload.get("application_number") or "")
        if not actual or actual.casefold() != identifier.casefold():
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO trademark detail identifier mismatch")
        owners = [str(payload.get("ownerName") or "").strip(), *applicant_names(payload)]
        owners = list(dict.fromkeys(value for value in owners if value))
        legal_status = str(payload.get("status") or "").strip()
        candidate = {
            "office": "euipo", "application_number": actual,
            "registration_number": payload.get("registrationNumber") or "",
            "mark_text": mark_text(payload),
            "owner": "; ".join(owners), "owners": owners, "status": legal_status,
            "nice_classes": _class_numbers_from_goods(payload),
            "goods_services": payload.get("goodsAndServices") if isinstance(payload.get("goodsAndServices"), list) else [],
            "media": media,
        }
    else:
        actual = str(payload.get("designNumber") or payload.get("applicationNumber") or "")
        if not actual or actual.casefold() != identifier.casefold():
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO design detail identifier mismatch")
        owners = applicant_names(payload)
        legal_status = str(payload.get("status") or "").strip()
        candidate = {
            "publication_number": actual, "jurisdiction": "EU",
            "title": "; ".join(_product_indications(payload)), "legal_status": legal_status,
            "owners": owners, "locarno": _locarno_classes(payload),
            "views": media,
        }
    verification_owner = candidate.get("owners") or ([candidate.get("owner")] if candidate.get("owner") else [])
    verification_classes = candidate.get("nice_classes") or candidate.get("locarno") or []
    verification_legal_status = str(candidate.get("status") or candidate.get("legal_status") or "")
    effective_right_type = right_type or (
        "trademark_figurative" if product == "trademark" and media else
        "trademark_word" if product == "trademark" else "design"
    )
    missing = []
    if not verification_owner:
        missing.append("owner")
    if not verification_legal_status:
        missing.append("legal_status")
    if not verification_classes:
        missing.append("classes")
    if effective_right_type in {"design", "trademark_figurative"} and not media:
        missing.append("official_media")
    if product == "design":
        raw_views = payload.get("views") if isinstance(payload.get("views"), list) else []
        expected_orders = {
            int(view.get("order"))
            for view in raw_views if isinstance(view, dict) and str(view.get("order", "")).isdigit()
        }
        media_roles = {str(item.get("role") or "") for item in media if isinstance(item, dict)}
        if not expected_orders:
            missing.append("official_media_manifest")
        elif any(f"view-{order}" not in media_roles for order in expected_orders):
            missing.append("official_media_incomplete")
    verification_status = (
        "verified" if authoritative and not missing else
        "partial" if authoritative else "not_checked"
    )
    candidate.update({
        "jurisdiction": "EU",
        "right_type": effective_right_type,
        "source": f"euipo_{product}",
        "source_environment": environment,
        "authoritative_for_final_rating": authoritative,
        "material": False,
        "material_reason": "",
        "disposition": (
            "verified" if verification_status == "verified" else
            "verification_incomplete" if authoritative else "non_authoritative_fixture_only"
        ),
        "official_verification": {
            "status": verification_status,
            "authority": "European Union Intellectual Property Office (EUIPO)",
            "source": "EUIPO API detail" if authoritative else "EUIPO non-authoritative API fixture",
            "url": f"https://euipo.europa.eu/eSearch/#{'details/trademarks' if product == 'trademark' else 'details/designs'}/{identifier}",
            "checked_at": now_iso(),
            "method": "official_free_api" if authoritative else "fixture_api_detail",
            "identity_match": True,
            "legal_status": verification_legal_status,
            "owner": verification_owner,
            "classes": verification_classes,
            "media": media,
            "reason": (
                ",".join(missing) if missing else
                "" if authoritative else "non_authoritative_environment_or_fixture"
            ),
        },
    })
    return candidate


def fetch_media(task_dir: Path, product: str, identifier: str, detail: dict) -> list[dict]:
    media: list[dict] = []
    if product == "trademark":
        if not isinstance(detail.get("markImage"), dict):
            return media
        paths = [(f"trademarks/{identifier}/image", "image")]
    else:
        raw_views = detail.get("views") if isinstance(detail.get("views"), list) else []
        orders = []
        for index, view in enumerate(raw_views, 1):
            order = view.get("order") if isinstance(view, dict) else index
            if str(order).isdigit():
                orders.append(int(order))
        if not orders:
            orders = [1]
        paths = [(f"designs/{identifier}/views/{order}", f"view-{order}") for order in sorted(set(orders))]
    for path, role in paths:
        body, headers = api_bytes(product, path)
        if not body:
            continue
        content_type = next((value for key, value in headers.items() if key.casefold() == "content-type"), "application/octet-stream")
        normalized_type = content_type.split(";", 1)[0].strip().casefold()
        suffix = {
            "image/png": ".png", "image/jpeg": ".jpg",
            "image/gif": ".gif", "image/webp": ".webp",
        }.get(normalized_type, "")
        if not suffix:
            continue
        target = task_dir / "raw" / f"euipo_{product}" / f"{identifier}-{role}{suffix}"
        atomic_write_bytes(target, body)
        try:
            detected_type, _, _ = image_info(target)
        except ValueError:
            target.unlink(missing_ok=True)
            continue
        if detected_type != normalized_type:
            target.unlink(missing_ok=True)
            continue
        media.append({
            "role": role, "path": str(target), "sha256": sha256_bytes(body),
            "bytes": len(body), "mime_type": normalized_type,
            "content_type": content_type,
        })
    return media


def main() -> None:
    parser = argparse.ArgumentParser(description="Search EUIPO trademarks or designs.")
    parser.add_argument("product", choices=["trademark", "design"])
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--identifier", default="")
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--rsql", default="")
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--size", type=int, default=25)
    parser.add_argument(
        "--right-type", choices=("design", "trademark_word", "trademark_figurative"),
        default="",
    )
    args = parser.parse_args()
    provider = "euipo_trademark" if args.product == "trademark" else "euipo_design"
    operation = "candidate_verification" if args.verify else "search"
    right_type = args.right_type or ("trademark_word" if args.product == "trademark" else "design")
    if args.product == "design" and right_type != "design":
        raise SystemExit("EUIPO design operations require right_type=design")
    if args.product == "trademark" and right_type not in {"trademark_word", "trademark_figurative"}:
        raise SystemExit("EUIPO trademark operations require a trademark right_type")
    task = ensure_object(load_json(args.task_dir.resolve() / "task.json"), "task.json")
    try:
        assert_provider_execution_allowed(
            task, provider, operation, jurisdiction="EU", right_type=right_type,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    evidence_type = "trademark" if args.product == "trademark" else "patent"
    path = "trademarks" if args.product == "trademark" else "designs"
    search_request_params = {
        "q": args.query, "query": args.rsql, "page": args.page,
        "size": args.size, "right_type": right_type,
    }
    selected_query = args.identifier.strip() or args.query.strip() if args.verify else args.query
    selected_request_params = (
        {
            "identifier": selected_query, "candidate_id": args.candidate_id.strip(),
            "detail": True, "right_type": right_type,
        }
        if args.verify else search_request_params
    )
    try:
        authorize_exact_plan_execution(
            args.task_dir.resolve(), task, provider, operation, args.query_id,
            jurisdiction="EU", right_type=right_type, query=selected_query,
            request_params=selected_request_params,
        )
    except ProviderError as exc:
        raise SystemExit(f"{exc.code}: {exc.detail}") from None
    try:
        source_environment, authoritative_for_final_rating = source_profile()
        if source_environment != "production" and os.environ.get("LC_IPR_TEST_MODE") != "1":
            raise ProviderError(
                "EUIPO_PRODUCTION_REQUIRED", "access_limited",
                "EUIPO Sandbox is fixture-only for 2.3 task execution",
            )
        if args.verify:
            identifier = args.identifier.strip() or args.query.strip()
            if not identifier:
                raise ProviderError("INVALID_QUERY", "failed", "EUIPO verification requires an identifier")
            payload, headers, body = api_get(args.product, f"{path}/{identifier}")
            media = fetch_media(args.task_dir.resolve(), args.product, identifier, payload)
            candidate = verified_detail(args.product, identifier, payload, media, right_type)
            candidate["right_type"] = right_type
            if args.candidate_id.strip():
                candidate["candidate_id"] = args.candidate_id.strip()
            verified = candidate["official_verification"]["status"] == "verified"
            run = record_result(
                args.task_dir.resolve(), provider=provider, operation="candidate_verification", query=identifier,
                jurisdiction="EU", evidence_type="official_verification",
                status="success" if verified else "access_limited",
                normalized=candidate, raw_body=body, quota=quota_summary(headers, payload),
                error_code="" if verified else "OFFICIAL_VERIFICATION_INCOMPLETE",
                detail="" if verified else str(candidate["official_verification"].get("reason") or "EUIPO detail is incomplete"),
                request_params={
                    "identifier": identifier, "candidate_id": args.candidate_id.strip(),
                    "detail": True, "right_type": right_type,
                },
                query_id=args.query_id,
                source_environment=source_environment,
                authoritative_for_final_rating=authoritative_for_final_rating,
            )
        else:
            api_params, request_params = search_parameters(
                args.product, args.query, right_type, args.page, args.size,
            )
            rsql = str(api_params["query"])
            if args.rsql and args.rsql != rsql:
                raise ProviderError(
                    "EUIPO_QUERY_PLAN_MISMATCH", "failed",
                    "Planned EUIPO RSQL does not match the deterministic official 1.1.0 query",
                )
            search_request_params = request_params
            payload, headers, body = api_get(args.product, path, api_params)
            candidates = normalize(args.product, payload, right_type)
            run = record_result(args.task_dir.resolve(), provider=provider, operation="search", query=args.query,
                jurisdiction="EU", evidence_type=evidence_type, status="success" if candidates else "no_result",
            normalized={
                "candidates": candidates,
                "search_metadata": search_metadata(payload, candidates, args.page, args.size),
                "source_environment": source_environment,
                "authoritative_for_final_rating": authoritative_for_final_rating,
            }, raw_body=body, quota=quota_summary(headers, payload), request_params=request_params,
                query_id=args.query_id, source_environment=source_environment,
                authoritative_for_final_rating=authoritative_for_final_rating)
    except ProviderError as exc:
        query = args.identifier.strip() or args.query
        run = record_error(args.task_dir.resolve(), provider=provider, operation=operation, query=query,
            jurisdiction="EU", evidence_type="official_verification" if args.verify else evidence_type, error_value=exc,
            request_params=(
                {
                    "identifier": query, "candidate_id": args.candidate_id.strip(),
                    "detail": True, "right_type": right_type,
                }
                if args.verify else search_request_params
            ), query_id=args.query_id,
            source_environment=(
                source_environment if "source_environment" in locals() else
                ("test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1" else "production")
            ),
            authoritative_for_final_rating=(
                authoritative_for_final_rating
                if "authoritative_for_final_rating" in locals() else False
            ))
    print(run["status"])


if __name__ == "__main__":
    main()

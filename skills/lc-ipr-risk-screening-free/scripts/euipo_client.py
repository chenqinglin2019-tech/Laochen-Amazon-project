#!/usr/bin/env python3
"""EUIPO Trademark Search and Design Search OAuth client."""

from __future__ import annotations

import argparse
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode

from common import atomic_write_bytes, credential, load_skill_config, now_iso, sha256_bytes
from provider_utils import ProviderError, http_json, http_request, quota_summary, record_error, record_result


_TOKEN_CACHE: dict[str, object] = {"access_token": "", "expires_at": 0.0}


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
    authoritative = environment == "production" and configured_authoritative
    return environment, authoritative


def token() -> str:
    cached = str(_TOKEN_CACHE.get("access_token") or "")
    if cached and float(_TOKEN_CACHE.get("expires_at") or 0) > time.time():
        return cached
    config, cfg, client_id, secret = settings()
    if not client_id or not secret:
        raise ProviderError("AUTH_FAILED", "access_limited", "EUIPO client credentials are missing")
    token_url = os.environ.get("EUIPO_TOKEN_URL", str(cfg["token_url"]))
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
    base_key = "trademark_base_url" if product == "trademark" else "design_base_url"
    env_key = "EUIPO_TRADEMARK_BASE_URL" if product == "trademark" else "EUIPO_DESIGN_BASE_URL"
    base = os.environ.get(env_key, str(cfg[base_key])).rstrip("/")
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
    base_key = "trademark_base_url" if product == "trademark" else "design_base_url"
    env_key = "EUIPO_TRADEMARK_BASE_URL" if product == "trademark" else "EUIPO_DESIGN_BASE_URL"
    base = os.environ.get(env_key, str(cfg[base_key])).rstrip("/")
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
    environment, authoritative = source_profile()
    coverage = {}
    products = (product,) if product else ("trademark", "design")
    if any(value not in {"trademark", "design"} for value in products):
        raise ValueError(f"Unsupported EUIPO product: {product}")
    for current_product in products:
        try:
            payload, headers, _ = api_get(
                current_product,
                "trademarks" if current_product == "trademark" else "designs",
                {"page": 0, "size": 10},
            )
            product_coverage = {
                "subscribed": True,
                "search_ready": True,
                "quota": quota_summary(headers, payload),
            }
            if current_product == "design" and environment == "sandbox":
                product_coverage.update(_probe_sandbox_design_fixture(settings()[1]))
            coverage[current_product] = product_coverage
        except ProviderError as exc:
            if exc.code in {"AUTH_FAILED", "PAID_PLAN_REQUIRED"}:
                raise ProviderError("PAID_PLAN_REQUIRED" if exc.code == "PAID_PLAN_REQUIRED" else "AUTH_FAILED", "access_limited", f"EUIPO {current_product} subscription unavailable") from exc
            raise
    return {
        "ready": True,
        "environment": environment,
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


def normalize(product: str, payload: dict) -> list[dict]:
    environment, authoritative = source_profile()
    product_rows = payload.get("trademarks" if product == "trademark" else "designs")
    rows = product_rows if product_rows is not None else payload.get("content", payload.get("data", payload.get("results", [])))
    if not isinstance(rows, list):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", f"EUIPO {product} response schema changed")
    candidates = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if product == "trademark":
            candidates.append({
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
                "publication_number": item.get("designNumber") or item.get("applicationNumber") or "", "jurisdiction": "EU",
                "locarno": item.get("locarnoClassification") or [], "title": item.get("productIndication") or "",
                "views": item.get("views") or [], "source": "euipo_design", "material": False,
                "source_environment": environment,
                "authoritative_for_final_rating": authoritative,
                "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
            })
    return candidates


def verified_detail(product: str, identifier: str, payload: dict, media: list[dict]) -> dict:
    environment, authoritative = source_profile()
    if product == "trademark":
        actual = str(payload.get("applicationNumber") or payload.get("application_number") or "")
        if not actual or actual.casefold() != identifier.casefold():
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO trademark detail identifier mismatch")
        candidate = {
            "office": "euipo", "application_number": actual,
            "registration_number": payload.get("registrationNumber") or "",
            "mark_text": mark_text(payload),
            "owner": payload.get("ownerName") or "; ".join(applicant_names(payload)), "status": payload.get("status") or "",
            "nice_classes": payload.get("niceClasses") or [], "media": media,
        }
    else:
        actual = str(payload.get("designNumber") or payload.get("applicationNumber") or "")
        if not actual or actual.casefold() != identifier.casefold():
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EUIPO design detail identifier mismatch")
        if not media:
            raise ProviderError("OFFICIAL_VERIFICATION_REQUIRED", "failed", "EUIPO design verification requires at least one official view")
        candidate = {
            "publication_number": actual, "jurisdiction": "EU",
            "title": payload.get("productIndication") or "", "legal_status": payload.get("status") or "",
            "owners": payload.get("owners") or payload.get("applicants") or [], "locarno": payload.get("locarnoClassification") or [],
            "views": media,
        }
    candidate.update({
        "source": f"euipo_{product}",
        "source_environment": environment,
        "authoritative_for_final_rating": authoritative,
        "material": authoritative,
        "official_verification": {
            "status": "verified" if authoritative else "not_checked",
            "source": "EUIPO API detail" if authoritative else "EUIPO Sandbox API detail",
            "url": f"https://euipo.europa.eu/eSearch/#{'details/trademarks' if product == 'trademark' else 'details/designs'}/{identifier}",
            "checked_at": now_iso(),
            "method": "official_api_detail" if authoritative else "sandbox_api_detail",
            "reason": "" if authoritative else "sandbox_not_authoritative_for_final_rating",
        },
    })
    return candidate


def fetch_media(task_dir: Path, product: str, identifier: str, detail: dict) -> list[dict]:
    media: list[dict] = []
    if product == "trademark":
        if not any(detail.get(key) for key in ("image", "imageUrl", "figurativeElements")):
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
        suffix = ".png" if "png" in content_type else ".jpg" if "jpeg" in content_type or "jpg" in content_type else ".bin"
        target = task_dir / "raw" / f"euipo_{product}" / f"{identifier}-{role}{suffix}"
        atomic_write_bytes(target, body)
        media.append({"role": role, "path": str(target), "sha256": sha256_bytes(body), "content_type": content_type})
    return media


def main() -> None:
    parser = argparse.ArgumentParser(description="Search EUIPO trademarks or designs.")
    parser.add_argument("product", choices=["trademark", "design"])
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--identifier", default="")
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--size", type=int, default=25)
    args = parser.parse_args()
    provider = "euipo_trademark" if args.product == "trademark" else "euipo_design"
    evidence_type = "trademark" if args.product == "trademark" else "patent"
    path = "trademarks" if args.product == "trademark" else "designs"
    try:
        source_environment, authoritative_for_final_rating = source_profile()
        if args.verify:
            identifier = args.identifier.strip() or args.query.strip()
            if not identifier:
                raise ProviderError("INVALID_QUERY", "failed", "EUIPO verification requires an identifier")
            payload, headers, body = api_get(args.product, f"{path}/{identifier}")
            media = fetch_media(args.task_dir.resolve(), args.product, identifier, payload)
            candidate = verified_detail(args.product, identifier, payload, media)
            run = record_result(
                args.task_dir.resolve(), provider=provider, operation="candidate_verification", query=identifier,
                jurisdiction="EU", evidence_type="official_verification", status="success",
                normalized=candidate, raw_body=body, quota=quota_summary(headers, payload),
                request_params={"identifier": identifier, "detail": True},
            )
        else:
            request_params = {"q": args.query, "page": args.page, "size": args.size}
            payload, headers, body = api_get(args.product, path, request_params)
            candidates = normalize(args.product, payload)
            run = record_result(args.task_dir.resolve(), provider=provider, operation="search", query=args.query,
                jurisdiction="EU", evidence_type=evidence_type, status="success" if candidates else "no_result",
            normalized={
                "candidates": candidates,
                "source_environment": source_environment,
                "authoritative_for_final_rating": authoritative_for_final_rating,
            }, raw_body=body, quota=quota_summary(headers, payload), request_params=request_params)
    except ProviderError as exc:
        operation = "candidate_verification" if args.verify else "search"
        query = args.identifier.strip() or args.query
        run = record_error(args.task_dir.resolve(), provider=provider, operation=operation, query=query,
            jurisdiction="EU", evidence_type="official_verification" if args.verify else evidence_type, error_value=exc,
            request_params={"identifier": query, "detail": True} if args.verify else {"q": args.query, "page": args.page, "size": args.size})
    print(run["status"])


if __name__ == "__main__":
    main()

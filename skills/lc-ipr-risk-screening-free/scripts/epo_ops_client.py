#!/usr/bin/env python3
"""EPO OPS OAuth, discovery, and candidate-detail client."""

from __future__ import annotations

import argparse
import base64
import os
import time
from pathlib import Path
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

from common import credential, load_skill_config
from provider_utils import ProviderError, enforce_task_limit, http_request, quota_summary, record_error, record_result


_TOKEN_CACHE: dict[str, object] = {"access_token": "", "expires_at": 0.0}


def settings() -> tuple[dict, str, str, str, str]:
    config = load_skill_config()
    cfg = config["providers"]["epo_ops"]
    base = os.environ.get("EPO_OPS_BASE_URL", str(cfg["base_url"])).rstrip("/")
    auth = os.environ.get("EPO_OPS_AUTH_URL", str(cfg["auth_url"]))
    return config, base, auth, credential(config, "epo_consumer_key"), credential(config, "epo_consumer_secret")


def access_token(force_refresh: bool = False) -> tuple[str, dict[str, str]]:
    cached = str(_TOKEN_CACHE.get("access_token") or "")
    if not force_refresh and cached and float(_TOKEN_CACHE.get("expires_at") or 0) > time.time():
        return cached, {}
    config, _, auth_url, key, secret = settings()
    if not key or not secret:
        raise ProviderError("AUTH_FAILED", "access_limited", "EPO OPS credentials are missing")
    basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
    status, headers, body = http_request(
        auth_url, method="POST", headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data=urlencode({"grant_type": "client_credentials"}).encode(),
        timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]),
    )
    del status
    import json
    try:
        payload = json.loads(body.decode())
        token = payload["access_token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO OAuth response has no access_token") from exc
    expires_in = max(int(payload.get("expires_in", 300)), 1)
    _TOKEN_CACHE.update({"access_token": str(token), "expires_at": time.time() + max(expires_in - 30, 1)})
    return str(token), headers


def ops_get(path: str, range_header: str = "") -> tuple[bytes, dict[str, str]]:
    config, base, _, _, _ = settings()
    token, _ = access_token()
    request_headers = {"Authorization": f"Bearer {token}", "Accept": "application/exchange+xml"}
    if range_header:
        request_headers["Range"] = range_header
    url = f"{base}/{path.lstrip('/')}"
    try:
        _, headers, body = http_request(url, headers=request_headers, timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]))
    except ProviderError as exc:
        if exc.code != "AUTH_FAILED":
            raise
        fresh, _ = access_token(force_refresh=True)
        request_headers["Authorization"] = f"Bearer {fresh}"
        _, headers, body = http_request(url, headers=request_headers, timeout=int(config["http"]["timeout_seconds"]), retries=0)
    return body, headers


def normalize_search(xml_bytes: bytes) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO OPS response is invalid XML") from exc
    candidates: list[dict[str, str]] = []
    for doc in root.findall(".//{*}exchange-document"):
        country = doc.attrib.get("country", "")
        number = doc.attrib.get("doc-number", "")
        kind = doc.attrib.get("kind", "")
        if number:
            candidates.append({
                "publication_number": f"{country}{number}{kind}", "jurisdiction": country,
                "kind_code": kind, "source": "epo_ops", "material": False,
                "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
            })
    if not candidates:
        for doc_id in root.findall(".//{*}document-id"):
            country = (doc_id.findtext("{*}country") or "").strip()
            number = (doc_id.findtext("{*}doc-number") or "").strip()
            kind = (doc_id.findtext("{*}kind") or "").strip()
            if number:
                candidates.append({"publication_number": f"{country}{number}{kind}", "jurisdiction": country, "kind_code": kind, "source": "epo_ops", "material": False, "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""}})
    unique: dict[str, dict[str, str]] = {}
    for item in candidates:
        unique[item["publication_number"]] = item
    return list(unique.values())


def normalize_detail(operation: str, document: str, body: bytes) -> dict:
    """Retain usable EPO detail fields instead of recording only an operation label."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", f"EPO {operation} response is invalid XML") from exc
    identifiers: list[str] = []
    for node in root.findall(".//{*}document-id"):
        country = (node.findtext("{*}country") or "").strip()
        number = (node.findtext("{*}doc-number") or "").strip()
        kind = (node.findtext("{*}kind") or "").strip()
        value = f"{country}{number}{kind}"
        if number and value not in identifiers:
            identifiers.append(value)
    titles = [str(node.text or "").strip() for node in root.findall(".//{*}invention-title") if str(node.text or "").strip()]
    applicants = [str(node.text or "").strip() for node in root.findall(".//{*}applicant-name/{*}name") if str(node.text or "").strip()]
    legal_events = []
    for event in root.findall(".//{*}legal-event")[:50]:
        legal_events.append({
            "code": event.attrib.get("code", ""),
            "date": event.attrib.get("date", ""),
            "description": " ".join(str(text).strip() for text in event.itertext() if str(text).strip())[:500],
        })
    return {
        "document": document,
        "operation": operation,
        "identifiers": identifiers,
        "titles": list(dict.fromkeys(titles)),
        "applicants": list(dict.fromkeys(applicants)),
        "legal_events": legal_events,
    }


def probe() -> dict:
    token, headers = access_token(force_refresh=True)
    return {"ready": bool(token), "quota": quota_summary(headers), "mode": "oauth_client_credentials"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Query EPO OPS.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--operation", choices=["search", "biblio", "family", "fulltext", "images", "legal"], default="search")
    parser.add_argument("--query", required=True)
    parser.add_argument("--jurisdiction", default="")
    parser.add_argument("--range", default="1-25")
    args = parser.parse_args()
    operation_paths = {
        "search": f"published-data/search?{urlencode({'q': args.query})}",
        "biblio": f"published-data/publication/epodoc/{quote(args.query)}/biblio",
        "family": f"family/publication/epodoc/{quote(args.query)}/biblio",
        "fulltext": f"published-data/publication/epodoc/{quote(args.query)}/fulltext",
        "images": f"published-data/images/epodoc/{quote(args.query)}/fullimage",
        "legal": f"published-data/publication/epodoc/{quote(args.query)}/legal",
    }
    try:
        config, _, _, _, _ = settings()
        if args.operation == "search":
            enforce_task_limit(args.task_dir.resolve(), "epo_ops", "search", int(config["limits"].get("epo_search_queries_per_task", 6)))
        else:
            enforce_task_limit(args.task_dir.resolve(), "epo_ops", "candidate_detail", int(config["limits"]["epo_candidate_detail_limit"]))
        body, headers = ops_get(operation_paths[args.operation], args.range if args.operation == "search" else "")
        normalized = normalize_search(body) if args.operation == "search" else normalize_detail(args.operation, args.query, body)
        status = "success" if normalized else "no_result"
        recorded_operation = args.operation if args.operation == "search" else "candidate_detail"
        run = record_result(args.task_dir.resolve(), provider="epo_ops", operation=recorded_operation, query=args.query,
            jurisdiction=args.jurisdiction, evidence_type="patent", status=status, normalized=normalized,
            raw_body=body, raw_suffix="xml", quota=quota_summary(headers),
            request_params={"q": args.query, "range": args.range} if args.operation == "search" else {"document": args.query, "detail_operation": args.operation})
        print(run["status"])
    except ProviderError as exc:
        recorded_operation = args.operation if args.operation == "search" else "candidate_detail"
        run = record_error(args.task_dir.resolve(), provider="epo_ops", operation=recorded_operation, query=args.query,
            jurisdiction=args.jurisdiction, evidence_type="patent", error_value=exc,
            request_params={"q": args.query, "range": args.range} if args.operation == "search" else {"document": args.query, "detail_operation": args.operation})
        print(run["status"])


if __name__ == "__main__":
    main()

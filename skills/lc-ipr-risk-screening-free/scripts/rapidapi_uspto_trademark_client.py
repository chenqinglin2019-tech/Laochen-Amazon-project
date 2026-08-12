#!/usr/bin/env python3
"""RapidAPI USPTO Trademark second-recall client."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import quote

from common import credential, load_skill_config
from provider_utils import ProviderError, enforce_task_limit, http_json, quota_summary, record_error, record_result


def settings() -> tuple[dict, dict, str]:
    config = load_skill_config()
    cfg = config["providers"]["rapidapi_uspto_trademark"]
    return config, cfg, credential(config, "rapidapi_key")


def call(path: str) -> tuple[dict, dict[str, str], bytes]:
    config, cfg, key = settings()
    if not key:
        raise ProviderError("AUTH_FAILED", "access_limited", "RapidAPI key is missing")
    base = os.environ.get("RAPIDAPI_USPTO_BASE_URL", str(cfg["base_url"])).rstrip("/")
    url = f"{base}{path}"
    return http_json(url, headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": str(cfg["host"]), "Accept": "application/json"},
        timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]))


def probe() -> dict:
    config, cfg, _ = settings()
    payload, headers, _ = call(str(cfg["database_status_path"]))
    if not payload:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "RapidAPI database status is empty")
    return {"ready": True, "quota": quota_summary(headers, payload), "database": payload}


def normalize(payload: dict) -> list[dict]:
    rows = payload.get("items", payload.get("results", payload.get("data", payload.get("trademarks", []))))
    if not isinstance(rows, list):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "RapidAPI trademark response schema changed")
    candidates: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        owners = item.get("owners") if isinstance(item.get("owners"), list) else []
        owner_names = [str(owner.get("name") or "").strip() for owner in owners if isinstance(owner, dict) and owner.get("name")]
        classifications = item.get("classification") if isinstance(item.get("classification"), list) else []
        nice_classes = [
            str(classification.get("international_code") or "").strip()
            for classification in classifications
            if isinstance(classification, dict) and classification.get("international_code")
        ]
        candidates.append({
            "office": "uspto", "serial_number": item.get("serialNumber") or item.get("serial_number") or "",
            "registration_number": item.get("registrationNumber") or item.get("registration_number") or "",
            "mark_text": item.get("markText") or item.get("wordMark") or item.get("mark_text") or item.get("keyword") or "",
            "owner": item.get("ownerName") or item.get("owner") or "; ".join(owner_names),
            "owners": owners,
            "status": item.get("status") or item.get("status_label") or item.get("status_definition") or "",
            "nice_classes": item.get("internationalClasses") or item.get("nice_classes") or nice_classes,
            "source": "rapidapi_uspto_trademark", "material": False,
            "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
        })
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Search USPTO Trademark through RapidAPI.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--jurisdiction", default="US")
    parser.add_argument("--search-type", choices=("active", "all"), default="active")
    args = parser.parse_args()
    try:
        config, _, _ = settings()
        enforce_task_limit(args.task_dir.resolve(), "rapidapi_uspto_trademark", "trademark_search", int(config["limits"]["trademark_queries_per_strategy"]))
        keyword = quote(args.query.strip(), safe="")
        if not keyword:
            raise ProviderError("INVALID_QUERY", "failed", "RapidAPI trademark keyword is empty")
        payload, headers, body = call(f"/v1/trademarkSearch/{keyword}/{args.search_type}")
        candidates = normalize(payload)
        run = record_result(args.task_dir.resolve(), provider="rapidapi_uspto_trademark", operation="trademark_search",
            query=args.query, jurisdiction="US", evidence_type="trademark", status="success" if candidates else "no_result",
            normalized={"candidates": candidates}, raw_body=body, quota=quota_summary(headers, payload), mandatory=False,
            request_params={"q": args.query, "search_type": args.search_type})
    except ProviderError as exc:
        run = record_error(args.task_dir.resolve(), provider="rapidapi_uspto_trademark", operation="trademark_search",
            query=args.query, jurisdiction="US", evidence_type="trademark", error_value=exc, mandatory=False,
            request_params={"q": args.query, "search_type": args.search_type})
    print(run["status"])


if __name__ == "__main__":
    main()

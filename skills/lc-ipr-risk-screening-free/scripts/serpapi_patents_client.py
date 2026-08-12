#!/usr/bin/env python3
"""SerpApi Google Patents free-tier client."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlencode

from common import credential, load_skill_config
from provider_utils import ProviderError, enforce_task_limit, http_json, quota_summary, record_error, record_result


def settings() -> tuple[dict, str, str]:
    config = load_skill_config()
    base = os.environ.get("SERPAPI_BASE_URL", str(config["providers"]["serpapi"]["base_url"])).rstrip("/")
    return config, base, credential(config, "serpapi_api_key")


def probe() -> dict:
    config, base, key = settings()
    if not key:
        raise ProviderError("AUTH_FAILED", "access_limited", "SerpApi key is missing")
    payload, headers, _ = http_json(f"{base}/account.json?{urlencode({'api_key': key})}", timeout=int(config["http"]["timeout_seconds"]), retries=0)
    quota = quota_summary(headers, payload)
    plan = str(payload.get("plan_name") or payload.get("plan") or "")
    left = payload.get("total_searches_left")
    if left is not None and int(left) <= 0:
        raise ProviderError("FREE_QUOTA_EXHAUSTED", "access_limited", "SerpApi has no searches remaining")
    if plan and "free" not in plan.casefold() and payload.get("overage_enabled"):
        raise ProviderError("PAID_PLAN_REQUIRED", "access_limited", "SerpApi account may use paid overage")
    return {"ready": True, "plan": plan, "quota": quota}


def search(params: dict[str, str]) -> tuple[dict, dict[str, str], bytes]:
    config, base, key = settings()
    if not key:
        raise ProviderError("AUTH_FAILED", "access_limited", "SerpApi key is missing")
    query = {"engine": "google_patents", "api_key": key, "output": "json", **{k: v for k, v in params.items() if v}}
    payload, headers, body = http_json(f"{base}/search?{urlencode(query)}", timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]))
    metadata = payload.get("search_metadata")
    results = payload.get("organic_results")
    if not isinstance(metadata, dict) or metadata.get("status") != "Success" or not isinstance(results, list):
        if payload.get("error"):
            message = str(payload["error"])
            if "hasn't returned any results" in message.casefold():
                return {"candidates": [], "search_information": payload.get("search_information", {})}, headers, body
            raise ProviderError("PROVIDER_HTTP_ERROR", "failed", message)
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "SerpApi patent response schema changed")
    candidates = []
    for item in results:
        if not isinstance(item, dict):
            continue
        publication = str(item.get("publication_number") or "")
        candidates.append({
            "publication_number": publication, "title": item.get("title", ""), "snippet": item.get("snippet", ""),
            "inventor": item.get("inventor", ""), "assignee": item.get("assignee", ""),
            "filing_date": item.get("filing_date", ""), "grant_date": item.get("grant_date", ""),
            "url": item.get("patent_link", ""), "figures": item.get("figures", []),
            "jurisdiction": publication[:2], "source": "serpapi_google_patents", "material": False,
            "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
        })
    return {"candidates": candidates, "search_information": payload.get("search_information", {})}, headers, body


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Google Patents through SerpApi.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--jurisdiction", default="")
    parser.add_argument("--country", default="")
    parser.add_argument("--status", choices=["", "GRANT", "APPLICATION"], default="")
    parser.add_argument("--type", choices=["", "PATENT", "DESIGN"], default="")
    parser.add_argument("--assignee", default="")
    parser.add_argument("--inventor", default="")
    parser.add_argument("--before", default="")
    parser.add_argument("--after", default="")
    args = parser.parse_args()
    params = {key: str(value) for key, value in vars(args).items() if key in {"country", "status", "type", "assignee", "inventor", "before", "after"}}
    params["q"] = args.query
    try:
        config, _, _ = settings()
        enforce_task_limit(args.task_dir.resolve(), "serpapi_google_patents", "search", int(config["limits"]["serpapi_google_patents_queries_per_task"]))
        normalized, headers, body = search(params)
        status = "success" if normalized["candidates"] else "no_result"
        run = record_result(args.task_dir.resolve(), provider="serpapi_google_patents", operation="search", query=args.query,
            jurisdiction=args.jurisdiction or args.country, evidence_type="patent", status=status, normalized=normalized,
            raw_body=body, quota=quota_summary(headers), request_params=params)
    except ProviderError as exc:
        run = record_error(args.task_dir.resolve(), provider="serpapi_google_patents", operation="search", query=args.query,
            jurisdiction=args.jurisdiction or args.country, evidence_type="patent", error_value=exc,
            request_params=params)
    print(run["status"])


if __name__ == "__main__":
    main()

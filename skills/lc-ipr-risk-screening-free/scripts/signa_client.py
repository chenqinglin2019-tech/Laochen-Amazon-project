#!/usr/bin/env python3
"""Signa office-coverage validation and trademark recall client."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from common import credential, ensure_object, load_json, load_skill_config, parse_iso
from provider_utils import ProviderError, enforce_task_limit, http_json, json_body, quota_summary, record_error, record_result


# Signa's `/v1/offices` uses its own office codes, not registry acronyms.
# Current production records identify the United States as `US` and EUIPO as
# `EM`; preserve that casing when sending the offices filter back to Signa.
OFFICE_MAP = {"US": "US", "EU": "EM"}


def settings() -> tuple[dict, str, str]:
    config = load_skill_config()
    cfg = config["providers"]["signa"]
    base = os.environ.get("SIGNA_BASE_URL", str(cfg["base_url"])).rstrip("/")
    return config, base, credential(config, "signa_api_key")


def auth_headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Accept": "application/json", "Content-Type": "application/json"}


def office_rows(payload: dict) -> list[dict]:
    rows = payload.get("data", payload.get("offices", []))
    if not isinstance(rows, list):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "Signa offices response schema changed")
    return [item for item in rows if isinstance(item, dict)]


def search_request(body_payload: dict) -> tuple[dict, dict[str, str], bytes]:
    config, base, key = settings()
    if not key:
        raise ProviderError("AUTH_FAILED", "access_limited", "Signa key is missing")
    return http_json(f"{base}/v1/trademarks", method="POST", headers=auth_headers(key), data=json_body(body_payload),
        timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]))


def probe(jurisdictions: list[str]) -> dict:
    config, base, key = settings()
    if not key:
        raise ProviderError("AUTH_FAILED", "access_limited", "Signa key is missing")
    identity, _, _ = http_json(f"{base}/v1/organization/me", headers=auth_headers(key),
        timeout=int(config["http"]["timeout_seconds"]), retries=0)
    plan = str(identity.get("plan") or "").casefold()
    if plan not in {"free", "beta"}:
        raise ProviderError("PAID_PLAN_REQUIRED", "access_limited", f"Signa account plan is not free-tier: {plan or 'unknown'}")
    usage, usage_headers, _ = http_json(f"{base}/v1/organization/usage", headers=auth_headers(key),
        timeout=int(config["http"]["timeout_seconds"]), retries=0)
    search_usage = usage.get("by_endpoint_type", {}).get("search", {}) if isinstance(usage.get("by_endpoint_type"), dict) else {}
    used, limit = search_usage.get("used"), search_usage.get("limit")
    if limit == 0:
        raise ProviderError("PAID_PLAN_REQUIRED", "access_limited", "Signa search is unavailable on the current plan")
    if isinstance(used, int) and isinstance(limit, int) and used >= limit:
        raise ProviderError("FREE_QUOTA_EXHAUSTED", "access_limited", "Signa monthly search quota is exhausted")
    offices_payload, headers, _ = http_json(f"{base}/v1/offices", headers=auth_headers(key),
        timeout=int(config["http"]["timeout_seconds"]), retries=0)
    rows = office_rows(offices_payload)
    by_code = {str(row.get("code") or row.get("office_code") or row.get("id") or "").casefold(): row for row in rows}
    targets = sorted({OFFICE_MAP.get(value.upper(), value.upper()) for value in jurisdictions})
    coverage = {}
    max_age = int(config["freshness"]["signa_max_age_days"])
    known = str(config["providers"]["signa"].get("known_mark_probe", "NIKE"))
    for target in targets:
        row = by_code.get(target.casefold(), {})
        stage = str(row.get("status") or row.get("stage") or "").casefold()
        last_sync = str(row.get("last_synced_at") or row.get("last_sync_at") or "")
        total = row.get("total_marks", row.get("record_count", 0))
        if not row or stage not in {"production", "live"} or not total:
            raise ProviderError("COVERAGE_UNVERIFIED", "access_limited", f"Signa office {target} is not verified production coverage")
        if last_sync:
            age = (datetime.now(timezone.utc) - parse_iso(last_sync)).total_seconds() / 86400
            if age > max_age:
                raise ProviderError("SOURCE_DATA_STALE", "access_limited", f"Signa office {target} is {age:.1f} days stale")
        sample, _, _ = search_request({"query": known, "strategies": ["exact"], "filters": {"offices": [target]}, "limit": 1})
        sample_rows = sample.get("data", sample.get("results", []))
        if not isinstance(sample_rows, list) or not sample_rows:
            raise ProviderError("COVERAGE_UNVERIFIED", "access_limited", f"Signa known-mark sample failed for {target}")
        source_date = str(sample_rows[0].get("source_data_date") or sample_rows[0].get("updated_at") or "")
        coverage[target] = {"production": True, "provider_status": stage, "last_synced_at": last_sync, "total_marks": total, "known_mark_result": True, "source_data_date": source_date, "has_image": bool(sample_rows[0].get("image") or sample_rows[0].get("image_url"))}
    quota = quota_summary({**usage_headers, **headers}, usage)
    quota.update({"plan": plan, "search": search_usage})
    return {"ready": True, "coverage": coverage, "quota": quota}


def normalize(payload: dict) -> list[dict]:
    rows = payload.get("data", payload.get("results", []))
    if not isinstance(rows, list):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "Signa trademark response schema changed")
    candidates = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        candidates.append({
            "office": item.get("office_code") or item.get("office") or "", "serial_number": item.get("serial_number") or item.get("application_number") or "",
            "registration_number": item.get("registration_number") or "", "mark_text": item.get("mark_text") or item.get("word_mark") or "",
            "owner": item.get("owner_name") or item.get("owner") or "", "status": item.get("status_stage") or item.get("status") or "",
            "nice_classes": item.get("nice_classes", []), "goods_services": item.get("goods_services", []),
            "image_url": item.get("image_url") or item.get("image") or "", "source_data_date": item.get("source_data_date") or "",
            "source": "signa", "material": False, "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
        })
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Signa trademarks.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--office", default="")
    parser.add_argument("--nice-class", action="append", default=[])
    parser.add_argument("--owner", default="")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    office = args.office or OFFICE_MAP.get(args.jurisdiction.upper(), args.jurisdiction.upper())
    filters: dict = {"offices": [office], "status_stage": ["registered", "examining"]}
    if args.nice_class:
        filters["nice_classes"] = args.nice_class
    if args.owner:
        filters["owner"] = args.owner
    request_payload = {"query": args.query, "strategies": ["exact", "phonetic", "fuzzy", "prefix"], "filters": filters, "limit": args.limit}
    request_identity = {"q": args.query, "office": office, "strategies": ["exact", "phonetic", "fuzzy", "prefix"]}
    task = ensure_object(load_json(args.task_dir.resolve() / "task.json"), "task.json")
    mandatory = "signa" in task.get("required_sources", [])
    try:
        config, _, _ = settings()
        enforce_task_limit(args.task_dir.resolve(), "signa", "trademark_search", int(config["limits"]["trademark_queries_per_strategy"]))
        payload, headers, body = search_request(request_payload)
        candidates = normalize(payload)
        run = record_result(args.task_dir.resolve(), provider="signa", operation="trademark_search", query=args.query,
            jurisdiction=args.jurisdiction, evidence_type="trademark", status="success" if candidates else "no_result",
            normalized={"candidates": candidates}, raw_body=body, quota=quota_summary(headers, payload),
            data_date=max((item.get("source_data_date", "") for item in candidates), default=""),
            mandatory=mandatory, request_params=request_identity)
    except ProviderError as exc:
        run = record_error(args.task_dir.resolve(), provider="signa", operation="trademark_search", query=args.query,
            jurisdiction=args.jurisdiction, evidence_type="trademark", error_value=exc,
            mandatory=mandatory, request_params=request_identity)
    print(run["status"])


if __name__ == "__main__":
    main()

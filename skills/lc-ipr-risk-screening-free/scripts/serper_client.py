#!/usr/bin/env python3
"""Serper Search, Patents, Images, and runtime-probed Lens client."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from common import credential, load_skill_config
from provider_utils import ProviderError, enforce_task_limit, http_json, json_body, quota_summary, record_error, record_result


OPERATIONS = {"search", "patents", "images", "lens"}


def settings() -> tuple[dict, str, str]:
    config = load_skill_config()
    base = os.environ.get("SERPER_BASE_URL", str(config["providers"]["serper"]["base_url"])).rstrip("/")
    return config, base, credential(config, "serper_api_key")


def call(operation: str, payload: dict) -> tuple[dict, dict[str, str], bytes]:
    config, base, key = settings()
    if not key:
        raise ProviderError("AUTH_FAILED", "access_limited", "Serper key is missing")
    result, headers, body = http_json(f"{base}/{operation}", method="POST",
        headers={"X-API-KEY": key, "Content-Type": "application/json"}, data=json_body(payload),
        timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]))
    expected = {"patents": "organic", "search": "organic", "images": "images", "lens": "organic"}[operation]
    if expected not in result and not any(key in result for key in ("knowledgeGraph", "visual_matches")):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", f"Serper {operation} response schema changed")
    return result, headers, body


def probe() -> dict:
    payload, headers, _ = call("search", {"q": "site:uspto.gov trademark", "num": 1})
    return {"ready": True, "quota": quota_summary(headers, payload)}


def normalize(operation: str, payload: dict) -> list[dict]:
    raw_items = payload.get("images" if operation == "images" else "organic", [])
    if not isinstance(raw_items, list) or (not raw_items and isinstance(payload.get("visual_matches"), list)):
        raw_items = payload.get("visual_matches", []) if isinstance(payload.get("visual_matches"), list) else []
    candidates = []
    for item in raw_items:
        if isinstance(item, dict):
            url = item.get("link") or item.get("url") or ""
            publication = ""
            if operation == "patents":
                import re
                match = re.search(r"/patent/([A-Za-z]{2}[A-Za-z0-9-]+)", str(url))
                publication = re.sub(r"[^A-Za-z0-9]", "", match.group(1)).upper() if match else ""
            candidates.append({
                "publication_number": publication,
                "jurisdiction": publication[:2] if publication else "",
                "title": item.get("title", ""), "url": url,
                "snippet": item.get("snippet", ""),
                "image_url": item.get("imageUrl") or item.get("image") or "",
                "source": f"serper_{operation}", "material": False,
                "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
            })
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Call a Serper discovery endpoint.")
    parser.add_argument("operation", choices=sorted(OPERATIONS))
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query", default="")
    parser.add_argument("--image-url", default="")
    parser.add_argument("--jurisdiction", default="")
    parser.add_argument("--num", type=int, default=10)
    args = parser.parse_args()
    if args.operation == "lens":
        if not args.image_url.startswith("https://"):
            raise SystemExit("Lens requires a public HTTPS image URL")
        request_payload, query = {"url": args.image_url}, args.image_url
    else:
        if not args.query:
            raise SystemExit("--query is required")
        request_payload, query = {"q": args.query, "num": args.num}, args.query
    provider = f"serper_{args.operation}" if args.operation != "search" else "serper_web"
    evidence_type = "patent" if args.operation == "patents" else ("enforcement" if args.operation == "search" else "copyright")
    mandatory = args.operation != "lens"
    try:
        config, _, _ = settings()
        limit_key = {"patents": "serper_patents_queries_per_task", "search": "serper_web_queries_per_task", "images": "serper_images_queries_per_task"}.get(args.operation)
        if limit_key:
            enforce_task_limit(args.task_dir.resolve(), provider, args.operation, int(config["limits"][limit_key]))
        payload, headers, body = call(args.operation, request_payload)
        normalized = normalize(args.operation, payload)
        run = record_result(args.task_dir.resolve(), provider=provider, operation=args.operation, query=query,
            jurisdiction=args.jurisdiction, evidence_type=evidence_type, status="success" if normalized else "no_result",
            normalized={"candidates": normalized}, raw_body=body, quota=quota_summary(headers, payload), mandatory=mandatory,
            request_params=request_payload)
    except ProviderError as exc:
        if args.operation == "lens":
            exc = ProviderError(exc.code, exc.source_status, exc.detail)
        run = record_error(args.task_dir.resolve(), provider=provider, operation=args.operation, query=query,
            jurisdiction=args.jurisdiction, evidence_type=evidence_type, error_value=exc,
            mandatory=mandatory, request_params=request_payload)
    print(run["status"])


if __name__ == "__main__":
    main()

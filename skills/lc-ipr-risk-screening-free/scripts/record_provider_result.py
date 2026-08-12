#!/usr/bin/env python3
"""Ingest manual browser, MCP-like, or official-registry evidence deterministically."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlparse

from common import SOURCE_STATUSES, ensure_object, load_json, path_within, sha256_file
from provider_utils import record_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a normalized provider result.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--evidence-type", choices=["patent", "trademark", "copyright", "enforcement", "official_verification", "blacklist", "product"], required=True)
    parser.add_argument("--status", choices=sorted(SOURCE_STATUSES), required=True)
    parser.add_argument("--normalized-json", type=Path)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--error-code", default="")
    parser.add_argument("--detail", default="")
    parser.add_argument("--data-date", default="")
    parser.add_argument("--optional", action="store_true")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    allowed = set(task.get("required_sources", [])) | set(task.get("optional_sources", [])) | set(task.get("low_risk_gate_sources", [])) | {"local_high_risk_ip"}
    if args.provider not in allowed:
        raise SystemExit(f"Provider is not configured for this task: {args.provider}")
    normalized = None
    if args.normalized_json:
        normalized = ensure_object(load_json(args.normalized_json), "normalized JSON")
    raw_body = args.raw.read_bytes() if args.raw else b""
    if args.status == "no_result" and normalized not in (None, {}, {"candidates": []}):
        raise SystemExit("no_result requires an empty normalized result")
    if args.status in {"success", "no_result"} and args.error_code:
        raise SystemExit("Successful statuses cannot include an error code")
    request_params = {"q": args.query}
    if args.evidence_type == "official_verification":
        parsed = urlparse(args.source_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise SystemExit("Official verification requires an HTTPS --source-url")
        if not args.screenshot:
            raise SystemExit("Official verification requires --screenshot")
        screenshot = args.screenshot.expanduser().resolve()
        if not screenshot.is_file() or not path_within(screenshot, task_dir / "screenshots"):
            raise SystemExit("Official verification screenshot must exist inside task screenshots/")
        request_params.update({"source_url": args.source_url, "screenshot_sha256": sha256_file(screenshot)})
        if isinstance(normalized, dict):
            normalized.setdefault("browser_evidence", {}).update({"screenshot_path": str(screenshot), "screenshot_sha256": sha256_file(screenshot)})
    run = record_result(task_dir, provider=args.provider, operation=args.operation, query=args.query,
        jurisdiction=args.jurisdiction, evidence_type=args.evidence_type, status=args.status,
        normalized=normalized, raw_body=raw_body, raw_suffix=args.raw.suffix.lstrip(".") if args.raw else "json",
        error_code=args.error_code, detail=args.detail, data_date=args.data_date, mandatory=not args.optional,
        request_params=request_params)
    print(run["run_id"])


if __name__ == "__main__":
    main()

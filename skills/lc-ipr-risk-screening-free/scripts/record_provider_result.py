#!/usr/bin/env python3
"""Ingest manual browser, MCP-like, or official-registry evidence deterministically."""

from __future__ import annotations

import argparse
from pathlib import Path

from common import SOURCE_STATUSES, ensure_object, is_active_schema, load_json
from provider_utils import ProviderError, require_provider_operation, record_result


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
    if not is_active_schema(task):
        raise SystemExit("LEGACY_TASK_READ_ONLY: 2.1/2.2 provider evidence cannot be changed")
    try:
        derived_mandatory = require_provider_operation(
            task, args.provider, args.operation, jurisdiction=args.jurisdiction,
        )
    except ProviderError as exc:
        raise SystemExit(f"{exc.code}: {exc.detail}") from None
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
        raise SystemExit(
            "TYPED_OFFICIAL_RECORDER_REQUIRED: use the provider-specific API or official-registry recorder"
        )
    run = record_result(task_dir, provider=args.provider, operation=args.operation, query=args.query,
        jurisdiction=args.jurisdiction, evidence_type=args.evidence_type, status=args.status,
        normalized=normalized, raw_body=raw_body, raw_suffix=args.raw.suffix.lstrip(".") if args.raw else "json",
        error_code=args.error_code, detail=args.detail, data_date=args.data_date,
        mandatory=derived_mandatory if task.get("schema_version") == "2.3-free" else not args.optional,
        request_params=request_params)
    print(run["run_id"])


if __name__ == "__main__":
    main()

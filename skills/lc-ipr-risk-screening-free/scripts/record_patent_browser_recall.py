#!/usr/bin/env python3
"""Validate manual WIPO, legacy Espacenet, or USPTO CDP patent-recall evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from common import (
    capture_provenance, ensure_object, load_json, load_skill_config,
    path_within, sha256_file, validate_checked_at,
)
from provider_utils import record_result


PROVIDERS = {"wipo_patentscope_browser", "espacenet_browser", "uspto_patent_browser"}
ALLOWED_CAPTURE_STATUSES = {"success", "no_result", "needs_user_action", "access_limited", "failed"}


def number(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def screenshot(value: object, task_dir: Path) -> tuple[str, str]:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file() or not path_within(path, task_dir / "screenshots"):
        raise ValueError(f"screenshot_path must exist inside task screenshots/: {path}")
    return str(path), sha256_file(path)


def strings(value: object) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [str(item).strip() for item in values if str(item).strip()]


def normalize_candidate(item: object, provider: str, final_url: str, checked_at: str, image_path: str, image_hash: str) -> dict:
    if not isinstance(item, dict):
        raise ValueError("every candidate must be an object")
    identifiers = {
        "publication_number": number(item.get("publication_number")),
        "application_number": number(item.get("application_number")),
        "grant_number": number(item.get("grant_number")),
        "record_number": number(item.get("record_number")),
    }
    if not any(identifiers.values()):
        raise ValueError("every candidate must include a publication, application, grant, or record number")
    title = str(item.get("title") or "").strip()
    if not title:
        raise ValueError("every candidate must include title")
    return {
        **identifiers,
        "title": title,
        "owners": strings(item.get("owners") or item.get("owner") or item.get("assignee")),
        "legal_status": str(item.get("legal_status") or item.get("status") or "").strip(),
        "jurisdiction": str(item.get("jurisdiction") or "").upper(),
        "kind_code": str(item.get("kind_code") or "").upper(),
        "family_id": str(item.get("family_id") or "").strip(),
        "source": provider,
        "material": bool(item.get("material", False)),
        "official_verification": {"status": "not_checked", "source": provider, "url": final_url, "checked_at": checked_at},
        "browser_evidence": {"screenshot_path": image_path, "screenshot_sha256": image_hash, "checked_at": checked_at},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Record manual WIPO, legacy Espacenet, or USPTO CDP patent recall evidence.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.expanduser().resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if args.provider not in task.get("low_risk_gate_sources", []):
        raise SystemExit(f"{args.provider} is not a configured patent browser gate for this task")
    capture = ensure_object(load_json(args.capture.expanduser().resolve()), "browser patent recall capture")
    status = str(capture.get("status") or "")
    if status not in ALLOWED_CAPTURE_STATUSES:
        raise SystemExit(f"Unsupported browser patent recall status: {status!r}")
    try:
        if args.provider == "espacenet_browser" and task.get("schema_version") != "2.1-free":
            raise ValueError("Espacenet browser automation is legacy-only; use EPO OPS")
        allowed_transports = {"manual"} if args.provider == "wipo_patentscope_browser" else {"cdp"}
        provenance = capture_provenance(capture, task, allowed_transports=allowed_transports)
        query = str(capture.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        final_url = str(capture.get("final_url") or "").strip()
        cfg = load_skill_config()["providers"][args.provider]
        allowed_hosts = {str(host).casefold() for host in cfg["browser_allowed_hosts"]}
        parsed = urlparse(final_url)
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in allowed_hosts:
            raise ValueError("final_url must be an allowed official HTTPS registry URL")
        checked_at = str(capture.get("checked_at") or "").strip()
        validate_checked_at(checked_at)
        image_path, image_hash = screenshot(capture.get("screenshot_path"), task_dir)
        mode = str(capture.get("mode") or "").strip()
        if not mode:
            raise ValueError("mode is required and must match search-plan.json")
        raw_candidates = capture.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raise ValueError("candidates must be an array")
        if status == "success" and not raw_candidates:
            raise ValueError("success requires at least one candidate")
        if status == "no_result" and (raw_candidates or not str(capture.get("result_message") or "").strip()):
            raise ValueError("no_result requires an empty candidates array and result_message")
        normalized = (
            {"candidates": [normalize_candidate(item, args.provider, final_url, checked_at, image_path, image_hash) for item in raw_candidates], "browser_evidence": {"screenshot_path": image_path, "screenshot_sha256": image_hash, "checked_at": checked_at}}
            if status == "success" else
            {"candidates": [], "browser_evidence": {"screenshot_path": image_path, "screenshot_sha256": image_hash, "checked_at": checked_at}}
            if status == "no_result" else None
        )
        if normalized is not None:
            normalized["browser_evidence"]["capture_provenance"] = provenance
            for candidate in normalized.get("candidates", []):
                candidate["browser_evidence"]["capture_provenance"] = provenance
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid browser patent recall capture: {exc}") from None
    detail = str(capture.get("detail") or capture.get("result_message") or "").strip()
    error_code = ""
    if status == "needs_user_action":
        error_code, detail = "BROWSER_USER_ACTION_REQUIRED", detail or "Official patent registry requires user action in Chrome desktop"
    elif status in {"access_limited", "failed"}:
        error_code, detail = "OFFICIAL_VERIFICATION_REQUIRED", detail or "Official browser patent recall could not be completed"
    run = record_result(
        task_dir, provider=args.provider, operation="patent_recall", query=query,
        jurisdiction="US", evidence_type="patent", status=status, normalized=normalized,
        raw_body=json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8"), raw_suffix="json",
        error_code=error_code, detail=detail, mandatory=False,
        request_params={"q": query, "mode": mode},
    )
    print(run["status"])


if __name__ == "__main__":
    main()

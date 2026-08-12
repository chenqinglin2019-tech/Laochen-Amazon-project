#!/usr/bin/env python3
"""Validate and record a USPTO TM Search Chrome desktop trademark-recall result."""

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


ALLOWED_CAPTURE_STATUSES = {"success", "no_result", "needs_user_action", "access_limited", "failed"}
ALLOWED_STRATEGIES = {"exact", "phrase", "prefix"}


def clean_serial(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def string_list(value: object) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [str(item).strip() for item in values if str(item).strip()]


def validate_file(value: object, task_dir: Path) -> tuple[str, str]:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file() or not path_within(path, task_dir / "screenshots"):
        raise ValueError(f"screenshot_path must exist inside task screenshots/: {path}")
    return str(path), sha256_file(path)


def normalize_candidate(
    item: object, screenshot_path: str, screenshot_sha256: str,
    checked_at: str, provenance: dict,
) -> dict:
    if not isinstance(item, dict):
        raise ValueError("every candidate must be an object")
    serial = clean_serial(item.get("serial_number") or item.get("application_number"))
    if len(serial) != 8:
        raise ValueError("every successful TM Search candidate must contain an eight-digit serial_number")
    mark_text = str(item.get("mark_text") or item.get("word_mark") or "").strip()
    if not mark_text:
        raise ValueError("every successful TM Search candidate must contain mark_text")
    return {
        "office": "uspto",
        "serial_number": serial,
        "registration_number": clean_serial(item.get("registration_number")),
        "mark_text": mark_text,
        "owner": str(item.get("owner") or item.get("owner_name") or "").strip(),
        "status": str(item.get("status") or item.get("status_label") or "").strip(),
        "nice_classes": string_list(item.get("nice_classes") or item.get("international_classes")),
        "goods_services": string_list(item.get("goods_services")),
        "source": "uspto_tmsearch_browser",
        "material": False,
        "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
        "browser_evidence": {
            "screenshot_path": screenshot_path,
            "screenshot_sha256": screenshot_sha256,
            "checked_at": checked_at,
            "capture_provenance": provenance,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Record USPTO TM Search Chrome desktop trademark-recall evidence.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.expanduser().resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if "US" not in {str(value).upper() for value in task.get("target_jurisdictions", [])}:
        raise SystemExit("USPTO TM Search Chrome desktop recall is only valid for US tasks")
    capture = ensure_object(load_json(args.capture.expanduser().resolve()), "USPTO TM Search Chrome desktop capture")
    status = str(capture.get("status") or "")
    if status not in ALLOWED_CAPTURE_STATUSES:
        raise SystemExit(f"Unsupported USPTO TM Search Chrome desktop capture status: {status!r}")
    try:
        provenance = capture_provenance(capture, task, allowed_transports={"cdp"})
        query = str(capture.get("query") or "").strip()
        strategy = str(capture.get("strategy") or "").strip()
        if not query or strategy not in ALLOWED_STRATEGIES:
            raise ValueError("query and strategy are required")
        rendered_query = str(capture.get("rendered_query") or "").strip()
        if not rendered_query:
            raise ValueError("rendered_query is required to bind the strategy to the rendered page")
        final_url = str(capture.get("final_url") or "").strip()
        parsed = urlparse(final_url)
        cfg = load_skill_config()["providers"]["uspto_tmsearch_browser"]
        allowed_hosts = {str(host).casefold() for host in cfg["browser_allowed_hosts"]}
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in allowed_hosts:
            raise ValueError("final_url must be an allowed official HTTPS USPTO TM Search URL")
        checked_at = str(capture.get("checked_at") or "").strip()
        validate_checked_at(checked_at)
        screenshot_path, screenshot_sha256 = validate_file(capture.get("screenshot_path"), task_dir)
        evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
        for existing in evidence.get("collections", {}).get("trademarks", []):
            browser_evidence = existing.get("payload", {}).get("browser_evidence", {}) if isinstance(existing, dict) else {}
            if browser_evidence.get("screenshot_path") == screenshot_path and existing.get("query") != f"{strategy}:{query}":
                raise ValueError("each TM Search strategy/query must use its own rendered screenshot path")
        raw_candidates = capture.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raise ValueError("candidates must be an array")
        if status == "success" and not raw_candidates:
            raise ValueError("successful TM Search capture must contain at least one candidate")
        if status == "no_result":
            if raw_candidates or not str(capture.get("result_message") or "").strip():
                raise ValueError("no_result requires an empty candidates array and result_message")
            normalized = {"candidates": [], "browser_evidence": {"screenshot_path": screenshot_path, "screenshot_sha256": screenshot_sha256, "checked_at": checked_at, "rendered_query": rendered_query, "capture_provenance": provenance}}
        elif status == "success":
            normalized = {
                "candidates": [normalize_candidate(item, screenshot_path, screenshot_sha256, checked_at, provenance) for item in raw_candidates],
                "browser_evidence": {"screenshot_path": screenshot_path, "screenshot_sha256": screenshot_sha256, "checked_at": checked_at, "rendered_query": rendered_query, "capture_provenance": provenance},
            }
        else:
            normalized = None
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid USPTO TM Search Chrome desktop capture: {exc}") from None

    error_code = ""
    detail = str(capture.get("detail") or capture.get("result_message") or "").strip()
    if status == "needs_user_action":
        error_code = "USPTO_ROBOT_CHECK"
        detail = detail or "USPTO TM Search requires user action in Chrome desktop"
    elif status in {"access_limited", "failed"}:
        error_code = "OFFICIAL_VERIFICATION_REQUIRED"
        detail = detail or "USPTO TM Search Chrome desktop recall could not be completed"
    raw_body = json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8")
    run = record_result(
        task_dir, provider="uspto_tmsearch_browser", operation="trademark_recall", query=f"{strategy}:{query}",
        jurisdiction="US", evidence_type="trademark", status=status, normalized=normalized,
        raw_body=raw_body, raw_suffix="json", error_code=error_code, detail=detail, mandatory=True,
        request_params={"q": query, "strategy": strategy},
    )
    print(run["status"])


if __name__ == "__main__":
    main()

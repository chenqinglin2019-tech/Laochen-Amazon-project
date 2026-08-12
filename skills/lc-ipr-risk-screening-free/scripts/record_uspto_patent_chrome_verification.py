#!/usr/bin/env python3
"""Validate and record a USPTO Patent Public Search Chrome desktop verification."""

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


def clean_number(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def nonempty_strings(value: object, field: str) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    result = [str(item).strip() for item in values if str(item).strip()]
    if not result:
        raise ValueError(f"{field} must contain at least one value")
    return result


def validate_file(value: object, field: str, task_dir: Path) -> tuple[str, str]:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file() or not path_within(path, task_dir / "screenshots"):
        raise ValueError(f"{field} must exist inside task screenshots/: {path}")
    return str(path), sha256_file(path)


def validate_common(
    capture: dict, task: dict, allowed_hosts: set[str], task_dir: Path,
) -> tuple[str, str, str, str, str, dict]:
    provenance = capture_provenance(capture, task, allowed_transports={"cdp"})
    record_number = clean_number(capture.get("record_number"))
    page_record_number = clean_number(capture.get("page_record_number"))
    if not record_number or page_record_number != record_number:
        raise ValueError("record_number and page_record_number must be the same non-empty identifier")
    final_url = str(capture.get("final_url") or "").strip()
    parsed = urlparse(final_url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in allowed_hosts:
        raise ValueError("final_url must be an allowed official HTTPS USPTO Patent Public Search URL")
    if record_number not in clean_number(final_url):
        raise ValueError("final_url must contain the verified record number")
    checked_at = str(capture.get("checked_at") or "").strip()
    validate_checked_at(checked_at)
    screenshot_path, screenshot_sha256 = validate_file(capture.get("screenshot_path"), "screenshot_path", task_dir)
    return record_number, final_url, checked_at, screenshot_path, screenshot_sha256, provenance


def normalize_success(capture: dict, common: tuple[str, str, str, str, str, dict]) -> dict:
    record_number, final_url, checked_at, screenshot_path, screenshot_sha256, provenance = common
    title = str(capture.get("title") or "").strip()
    legal_status = str(capture.get("legal_status") or "").strip()
    if not title or not legal_status:
        raise ValueError("title and legal_status are required for a successful verification")
    normalized = {
        "record_number": record_number,
        "publication_number": str(capture.get("publication_number") or record_number).strip(),
        "application_number": str(capture.get("application_number") or "").strip(),
        "grant_number": str(capture.get("grant_number") or "").strip(),
        "title": title,
        "legal_status": legal_status,
        "owners": nonempty_strings(capture.get("owners", capture.get("owner")), "owners"),
        "official_verification": {
            "status": "verified", "source": "USPTO Patent Public Search Chrome Desktop",
            "url": final_url, "checked_at": checked_at, "method": "chrome_desktop",
        },
        "browser_evidence": {
            "screenshot_path": screenshot_path, "screenshot_sha256": screenshot_sha256,
            "capture_provenance": provenance,
        },
        "capture_transport": provenance["capture_transport"],
    }
    views = capture.get("views")
    if views is not None:
        normalized["views"] = nonempty_strings(views, "views")
    evidence_images = capture.get("evidence_images", [])
    if evidence_images:
        if not isinstance(evidence_images, list):
            raise ValueError("evidence_images must be an array")
        task_dir = Path(screenshot_path).parents[1]
        normalized["browser_evidence"]["evidence_images"] = []
        for index, item in enumerate(evidence_images, 1):
            if isinstance(item, str):
                item = {"path": item, "label": f"USPTO evidence image {index}"}
            if not isinstance(item, dict):
                raise ValueError("each evidence image must be a path string or object")
            path, digest = validate_file(item.get("path"), "evidence_image.path", task_dir)
            normalized["browser_evidence"]["evidence_images"].append({
                "path": path, "sha256": digest,
                "label": str(item.get("label") or f"USPTO evidence image {index}").strip(),
                "role": str(item.get("role") or "official_drawing").strip(),
            })
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Record USPTO Patent Public Search Chrome desktop evidence.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.expanduser().resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if "US" not in {str(value).upper() for value in task.get("target_jurisdictions", [])}:
        raise SystemExit("USPTO Patent Public Search Chrome desktop verification is only valid for US tasks")
    capture = ensure_object(load_json(args.capture.expanduser().resolve()), "USPTO Patent Public Search Chrome desktop capture")
    status = str(capture.get("status") or "")
    if status not in ALLOWED_CAPTURE_STATUSES:
        raise SystemExit(f"Unsupported USPTO Patent Public Search Chrome desktop capture status: {status!r}")
    cfg = load_skill_config()["providers"]["uspto_patent_browser"]
    allowed_hosts = {str(host).casefold() for host in cfg["browser_allowed_hosts"]}
    try:
        common = validate_common(capture, task, allowed_hosts, task_dir)
        record_number, _, _, _, _, _ = common
        normalized = normalize_success(capture, common) if status == "success" else None
        if status == "no_result" and not str(capture.get("result_message") or "").strip():
            raise ValueError("result_message is required for a confirmed no_result")
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid USPTO Patent Public Search Chrome desktop capture: {exc}") from None

    error_code = ""
    detail = str(capture.get("detail") or capture.get("result_message") or "").strip()
    if status == "needs_user_action":
        error_code = "USPTO_ROBOT_CHECK"
        detail = detail or "USPTO Patent Public Search requires user action in Chrome desktop"
    elif status in {"access_limited", "failed"}:
        error_code = "OFFICIAL_VERIFICATION_REQUIRED"
        detail = detail or "USPTO Patent Public Search Chrome desktop verification could not be completed"

    raw_body = json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8")
    run = record_result(
        task_dir, provider="uspto_patent_browser", operation="candidate_verification", query=record_number,
        jurisdiction="US", evidence_type="official_verification", status=status,
        normalized=normalized, raw_body=raw_body, raw_suffix="json",
        error_code=error_code, detail=detail, mandatory=True,
    )
    print(run["status"])


if __name__ == "__main__":
    main()

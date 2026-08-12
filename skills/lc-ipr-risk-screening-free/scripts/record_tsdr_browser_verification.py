#!/usr/bin/env python3
"""Validate and record an official USPTO TSDR Chrome desktop verification."""

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


def clean_serial(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def nonempty_strings(value: object, field: str) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        raise ValueError(f"{field} must be a string or array")
    result = [str(item).strip() for item in values if str(item).strip()]
    if not result:
        raise ValueError(f"{field} must contain at least one value")
    return result


def validate_file(value: object, field: str, task_dir: Path, root_name: str = "screenshots") -> tuple[str, str]:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file() or not path_within(path, task_dir / root_name):
        raise ValueError(f"{field} must exist inside task {root_name}/: {path}")
    return str(path), sha256_file(path)


def validate_common(
    capture: dict, task: dict, allowed_hosts: set[str], task_dir: Path,
) -> tuple[str, str, str, str, str, dict]:
    provenance = capture_provenance(capture, task, allowed_transports={"cdp"})
    serial = clean_serial(capture.get("serial_number"))
    page_serial = clean_serial(capture.get("page_case_number"))
    if len(serial) != 8 or page_serial != serial:
        raise ValueError("serial_number and page_case_number must be the same eight-digit serial")
    final_url = str(capture.get("final_url") or "").strip()
    parsed = urlparse(final_url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in allowed_hosts:
        raise ValueError("final_url must be an allowed official HTTPS TSDR URL")
    if serial not in final_url:
        raise ValueError("final_url must contain the verified serial number")
    checked_at = str(capture.get("checked_at") or "").strip()
    validate_checked_at(checked_at)
    screenshot_path, screenshot_sha256 = validate_file(capture.get("screenshot_path"), "screenshot_path", task_dir)
    return serial, final_url, checked_at, screenshot_path, screenshot_sha256, provenance


def normalize_success(capture: dict, common: tuple[str, str, str, str, str, dict]) -> dict:
    serial, final_url, checked_at, screenshot_path, screenshot_sha256, provenance = common
    case_status = str(capture.get("case_status") or "").strip()
    if not case_status:
        raise ValueError("case_status is required for a successful verification")
    owners = nonempty_strings(capture.get("owners", capture.get("owner")), "owners")
    goods_services = nonempty_strings(capture.get("goods_services"), "goods_services")
    normalized = {
        "serial_number": serial,
        "registration_number": clean_serial(capture.get("registration_number")),
        "mark_text": str(capture.get("mark_text") or "").strip(),
        "case_status": case_status,
        "owners": owners,
        "goods_services": goods_services,
        "official_verification": {
            "status": "verified", "source": "USPTO TSDR Chrome Desktop", "url": final_url,
            "checked_at": checked_at, "method": "chrome_desktop",
        },
        "browser_evidence": {
            "screenshot_path": screenshot_path, "screenshot_sha256": screenshot_sha256,
            "capture_provenance": provenance,
        },
        "capture_transport": provenance["capture_transport"],
    }
    if capture.get("mark_image_path"):
        image_path, image_sha256 = validate_file(capture["mark_image_path"], "mark_image_path", Path(screenshot_path).parents[1], "images")
        normalized["browser_evidence"].update({"mark_image_path": image_path, "mark_image_sha256": image_sha256})
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Record official USPTO TSDR Chrome desktop evidence.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.expanduser().resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if "US" not in {str(value).upper() for value in task.get("target_jurisdictions", [])}:
        raise SystemExit("TSDR Chrome desktop verification is only valid for US tasks")
    capture = ensure_object(load_json(args.capture.expanduser().resolve()), "TSDR Chrome desktop capture")
    status = str(capture.get("status") or "")
    if status not in ALLOWED_CAPTURE_STATUSES:
        raise SystemExit(f"Unsupported TSDR Chrome desktop capture status: {status!r}")
    cfg = load_skill_config()["providers"]["tsdr"]
    allowed_hosts = {str(host).casefold() for host in cfg.get("browser_allowed_hosts", ["tsdr.uspto.gov"])}
    try:
        common = validate_common(capture, task, allowed_hosts, task_dir)
        serial, _, _, _, _, _ = common
        normalized = normalize_success(capture, common) if status == "success" else None
        if status == "no_result" and not str(capture.get("result_message") or "").strip():
            raise ValueError("result_message is required for a confirmed no_result")
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid TSDR Chrome desktop capture: {exc}") from None

    error_code = ""
    detail = str(capture.get("detail") or capture.get("result_message") or "").strip()
    if status == "needs_user_action":
        error_code = "USPTO_ROBOT_CHECK"
        detail = detail or "USPTO TSDR requires user action in Chrome desktop"
    elif status in {"access_limited", "failed"}:
        error_code = "OFFICIAL_VERIFICATION_REQUIRED"
        detail = detail or "USPTO TSDR Chrome desktop verification could not be completed"

    raw_body = json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8")
    run = record_result(
        task_dir, provider="uspto_tsdr", operation="candidate_verification", query=serial,
        jurisdiction="US", evidence_type="official_verification", status=status,
        normalized=normalized, raw_body=raw_body, raw_suffix="json",
        error_code=error_code, detail=detail, mandatory=True,
    )
    print(run["status"])


if __name__ == "__main__":
    main()

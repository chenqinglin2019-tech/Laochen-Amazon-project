#!/usr/bin/env python3
"""Validate and record an official USPTO TSDR Chrome desktop verification."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from record_browser_execution import validate_browser_execution

from common import (
    capture_provenance, ensure_object, image_info, is_active_schema, load_json, load_skill_config,
    path_within, sha256_file, validate_checked_at, recall_integrity_enabled,
)
from provider_utils import PLAN_META_KEYS, planned_query_metadata, record_result


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
    capture: dict, task: dict, allowed_hosts: set[str], task_dir: Path, status: str,
) -> tuple[str, str, str, str, str, dict]:
    provenance = capture_provenance(capture, task, allowed_transports={"cdp"})
    provenance.update(validate_browser_execution(capture, task, task_dir, "uspto_tsdr"))
    serial = clean_serial(capture.get("serial_number"))
    page_serial = clean_serial(capture.get("page_case_number"))
    if len(serial) != 8:
        raise ValueError("serial_number must be an eight-digit serial")
    if page_serial and page_serial != serial:
        raise ValueError("page_case_number does not match serial_number")
    if status == "success" and page_serial != serial:
        raise ValueError("successful verification requires an exact page_case_number match")
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


def bind_candidate_plan(
    task_dir: Path, capture: dict, serial: str, right_type: str,
) -> tuple[str, str]:
    query_id = str(capture.get("query_id") or "").strip()
    candidate_id = str(capture.get("candidate_id") or "").strip()
    if not query_id or not candidate_id:
        raise ValueError("capture requires query_id and candidate_id from the generated plan")
    planned = planned_query_metadata(task_dir, "uspto_tsdr", query_id)
    if not planned:
        raise ValueError("query_id is not an exact TSDR plan entry")
    expected = {
        "operation": "candidate_verification", "jurisdiction": "US",
        "right_type": right_type, "candidate_id": candidate_id,
    }
    actual = {
        "operation": str(planned.get("operation") or ""),
        "jurisdiction": str(planned.get("jurisdiction") or "").upper(),
        "right_type": str(planned.get("right_type") or ""),
        "candidate_id": str(planned.get("candidate_id") or ""),
    }
    if actual != expected:
        raise ValueError("query_id/candidate_id/jurisdiction/right_type does not match the plan")
    if clean_serial(planned.get("q")) != serial or clean_serial(planned.get("serial_number")) != serial:
        raise ValueError("planned q/serial_number does not match the captured serial")
    if not any(str(value).strip() for value in planned.get("requirement_ids", [])):
        raise ValueError("planned candidate action has no requirement_ids")
    return query_id, candidate_id


def normalize_success(
    capture: dict, common: tuple[str, str, str, str, str, dict], candidate_id: str,
) -> dict:
    serial, final_url, checked_at, screenshot_path, screenshot_sha256, provenance = common
    case_status = str(capture.get("case_status") or "").strip()
    if not case_status:
        raise ValueError("case_status is required for a successful verification")
    owners = nonempty_strings(capture.get("owners", capture.get("owner")), "owners")
    goods_services = nonempty_strings(capture.get("goods_services"), "goods_services")
    declared_right_type = str(capture.get("right_type") or "").strip()
    right_type = declared_right_type or ("trademark_figurative" if capture.get("mark_image_path") else "trademark_word")
    if right_type not in {"trademark_word", "trademark_figurative"}:
        raise ValueError("right_type must be trademark_word or trademark_figurative")
    if right_type == "trademark_figurative" and not capture.get("mark_image_path"):
        raise ValueError("figurative trademark verification requires official mark_image_path")
    class_value = capture.get("classes") or capture.get("nice_classes") or goods_services
    classes = nonempty_strings(class_value, "classes")
    normalized = {
        "jurisdiction": "US", "right_type": right_type,
        "candidate_id": candidate_id,
        "serial_number": serial,
        "registration_number": clean_serial(capture.get("registration_number")),
        "mark_text": str(capture.get("mark_text") or "").strip(),
        **({"mark_description": str(capture["mark_description"])} if capture.get("mark_description") else {}),
        **({"mark_drawing_type": str(capture["mark_drawing_type"])} if capture.get("mark_drawing_type") else {}),
        **({"mark_information": deepcopy(capture["mark_information"])} if capture.get("mark_information") else {}),
        "case_status": case_status,
        "owners": owners,
        "goods_services": goods_services,
        "classes": classes,
        "design_codes": nonempty_strings(capture.get("design_codes"), "design_codes") if capture.get("design_codes") else [],
        "official_verification": {
            "status": "verified", "authority": "United States Patent and Trademark Office (USPTO)",
            "source": "USPTO TSDR Chrome Desktop", "url": final_url,
            "checked_at": checked_at, "method": "cdp_assisted", "identity_match": True,
            "legal_status": case_status, "owner": owners, "classes": classes, "media": [],
        },
        "browser_evidence": {
            "screenshot_path": screenshot_path, "screenshot_sha256": screenshot_sha256,
            "screenshot_bytes": Path(screenshot_path).stat().st_size,
            "capture_provenance": provenance,
        },
        "capture_transport": provenance["capture_transport"],
    }
    if capture.get("mark_image_path"):
        image_path, image_sha256 = validate_file(capture["mark_image_path"], "mark_image_path", Path(screenshot_path).parents[1], "images")
        image_mime, _, _ = image_info(Path(image_path))
        media = [{
            "role": "official_mark", "path": image_path, "sha256": image_sha256,
            "bytes": Path(image_path).stat().st_size, "mime_type": image_mime,
        }]
        normalized["browser_evidence"].update({
            "mark_image_path": image_path, "mark_image_sha256": image_sha256,
            "mark_image_bytes": Path(image_path).stat().st_size, "mark_image_mime_type": image_mime,
        })
        normalized["official_verification"]["media"] = media
    return normalized


def candidate_request_params(task_dir: Path, task: dict, capture: dict, serial: str, right_type: str) -> dict:
    query_id, candidate_id = bind_candidate_plan(task_dir, capture, serial, right_type)
    if recall_integrity_enabled(task):
        planned = planned_query_metadata(task_dir, "uspto_tsdr", query_id)
        return {**{key: deepcopy(value) for key, value in planned.items() if key not in PLAN_META_KEYS},
                "right_type": right_type}
    return {"q": serial, "candidate_id": candidate_id, "right_type": right_type,
            "serial_number": serial, "mode": "user_assisted"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Record official USPTO TSDR Chrome desktop evidence.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.expanduser().resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if not is_active_schema(task):
        raise SystemExit("LEGACY_TASK_READ_ONLY: 2.1/2.2 TSDR evidence cannot be changed")
    if "US" not in {str(value).upper() for value in task.get("target_jurisdictions", [])}:
        raise SystemExit("TSDR Chrome desktop verification is only valid for US tasks")
    capture = ensure_object(load_json(args.capture.expanduser().resolve()), "TSDR Chrome desktop capture")
    status = str(capture.get("status") or "")
    if status not in ALLOWED_CAPTURE_STATUSES:
        raise SystemExit(f"Unsupported TSDR Chrome desktop capture status: {status!r}")
    cfg = load_skill_config()["providers"]["tsdr"]
    allowed_hosts = {str(host).casefold() for host in cfg.get("browser_allowed_hosts", ["tsdr.uspto.gov"])}
    try:
        common = validate_common(capture, task, allowed_hosts, task_dir, status)
        serial, _, _, _, _, _ = common
        declared_right_type = str(capture.get("right_type") or "").strip()
        right_type = declared_right_type or (
            "trademark_figurative" if capture.get("mark_image_path") else "trademark_word"
        )
        query_id, candidate_id = bind_candidate_plan(task_dir, capture, serial, right_type)
        request_params = candidate_request_params(task_dir, task, capture, serial, right_type)
        normalized = normalize_success(capture, common, candidate_id) if status == "success" else None
        if task.get("workflow_correction_revision") == "workflow-correction-v1":
            planned = planned_query_metadata(task_dir, "uspto_tsdr", query_id)
            if planned.get("execution_phase") == "needs_info":
                from workflow_v24 import reading_contract_valid
                if (not reading_contract_valid(planned)
                        or not set(planned["required_facts"]) <= {"goods_services", "current_status"}):
                    raise ValueError("TSDR needs_info requires an exact goods/status reading contract")
                if normalized is not None:
                    # These facts come from the same full official record already
                    # validated above. A changed use does not require recapture.
                    normalized.update(required_facts=deepcopy(planned["required_facts"]),
                        reading_scope=deepcopy(planned["reading_scope"]),
                        satisfied_facts=["goods_services", "current_status"],
                        authority_scope="official_record", content_retrieval_status="complete")
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
        error_code = str(capture.get("error_code") or "OFFICIAL_VERIFICATION_REQUIRED") if recall_integrity_enabled(task) else "OFFICIAL_VERIFICATION_REQUIRED"
        detail = detail or "USPTO TSDR Chrome desktop verification could not be completed"

    raw_body = json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8")
    run = record_result(
        task_dir, provider="uspto_tsdr", operation="candidate_verification", query=serial,
        jurisdiction="US", evidence_type="official_verification", status=status,
        normalized=normalized, raw_body=raw_body, raw_suffix="json",
        error_code=error_code, detail=detail, mandatory=True,
        request_params=request_params,
        query_id=query_id,
    )
    print(run["status"])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate and ingest product facts collected through visible Chrome CDP."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import (
    add_gap, add_history, atomic_write_json, capture_provenance, ensure_object, image_info, load_json,
    now_iso, path_within, sha256_file, sha256_json, stable_id, upsert_source_run,
    validate_checked_at,
)


def fail_task(task: dict[str, Any], evidence: dict[str, Any], task_dir: Path, capture: dict[str, Any], code: str, detail: str, user_action: bool = False) -> None:
    task.setdefault("errors", []).append({"at": now_iso(), "code": code, "detail": detail})
    add_gap(task, "amazon_browser", task["request"]["marketplace"],
            "needs_user_action" if user_action else "failed", code, detail)
    add_history(task, "needs_user_action" if user_action else "incomplete", detail)
    raw_capture = task_dir / "raw" / "amazon_browser" / "capture-error.json"
    atomic_write_json(raw_capture, capture)
    digest = sha256_json(capture)
    upsert_source_run(evidence, {
        "run_id": stable_id("SRC", "amazon_browser", "product_capture", digest), "provider": "amazon_browser",
        "attempt_id": stable_id("SRC", "amazon_browser", "product_capture", digest),
        "query_id": stable_id("QRY", "amazon_browser", "product_capture", str(capture.get("requested_url") or task.get("request", {}).get("url", ""))),
        "operation": "product_capture", "query": str(capture.get("requested_url") or task.get("request", {}).get("url", "")),
        "jurisdiction": task.get("request", {}).get("marketplace", ""), "started_at": now_iso(), "finished_at": now_iso(),
        "status": "needs_user_action" if user_action else "failed", "evidence_type": "product",
        "raw_paths": [str(raw_capture)], "payload_digest": digest, "error_code": code, "detail": detail,
        "retry_count": 0, "quota": {}, "data_date": "",
    })
    atomic_write_json(task_dir / "evidence.json", evidence)


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a visible Chrome CDP Amazon capture.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.expanduser().resolve()
    task_path, evidence_path = task_dir / "task.json", task_dir / "evidence.json"
    task = ensure_object(load_json(task_path), "task.json")
    evidence = ensure_object(load_json(evidence_path), "evidence.json")
    if task.get("state") not in {"awaiting_browser", "needs_user_action", "incomplete"}:
        raise SystemExit("Credential preflight must pass before browser product ingestion")
    capture = ensure_object(load_json(args.capture), "browser capture")
    try:
        provenance = capture_provenance(capture, task, allowed_transports={"cdp"})
    except ValueError as exc:
        fail_task(task, evidence, task_dir, capture, "RESPONSE_SCHEMA_CHANGED", str(exc))
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    status = str(capture.get("status", ""))
    if status == "robot_check":
        fail_task(task, evidence, task_dir, capture, "AMAZON_ROBOT_CHECK", "Amazon robot check requires user action", True)
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    if status != "success":
        fail_task(task, evidence, task_dir, capture, "RESPONSE_SCHEMA_CHANGED", "Browser capture status is not success")
        atomic_write_json(task_path, task)
        print(task["state"])
        return

    requested = str(task.get("product", {}).get("requested_asin", "")).upper()
    actual = str(capture.get("actual_asin", "")).upper()
    if not actual or (requested and actual != requested):
        fail_task(task, evidence, task_dir, capture, "AMAZON_ASIN_MISMATCH", f"requested={requested or 'unknown'}, actual={actual or 'missing'}")
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    variant = capture.get("variant")
    if not isinstance(variant, dict) or variant.get("confirmed") is not True:
        fail_task(task, evidence, task_dir, capture, "AMAZON_ASIN_MISMATCH", "Current variant was not explicitly confirmed")
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    requested_url = str(capture.get("requested_url") or "").strip()
    final_url = str(capture.get("final_url") or "").strip()
    expected_host = str(task.get("request", {}).get("amazon_host") or "").casefold()
    final_host = (urlparse(final_url).hostname or "").casefold().removeprefix("www.")
    if not requested_url or final_host != expected_host or actual not in final_url.upper():
        fail_task(task, evidence, task_dir, capture, "AMAZON_ASIN_MISMATCH", "Final Amazon URL must match the requested host and actual ASIN")
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    collected_at = str(capture.get("collected_at") or "").strip()
    try:
        validate_checked_at(collected_at)
    except ValueError:
        fail_task(task, evidence, task_dir, capture, "SOURCE_DATA_STALE", "Amazon capture time is missing, stale, or in the future")
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    main_image = capture.get("main_image")
    screenshots = capture.get("screenshots")
    if not isinstance(main_image, dict) or not isinstance(screenshots, dict):
        fail_task(task, evidence, task_dir, capture, "MAIN_IMAGE_UNAVAILABLE", "Main image or screenshots are absent")
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    image_path = Path(str(main_image.get("path", ""))).expanduser().resolve()
    if not image_path.is_file() or not path_within(image_path, task_dir / "images"):
        fail_task(task, evidence, task_dir, capture, "MAIN_IMAGE_UNAVAILABLE", "Main image must exist inside task images/")
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    source_url = str(main_image.get("source_url", ""))
    image_host = (urlparse(source_url).hostname or "").casefold()
    actual_hash = sha256_file(image_path)
    if not source_url.startswith("https://") or not image_host.endswith("media-amazon.com") or actual_hash != str(main_image.get("sha256", "")):
        fail_task(task, evidence, task_dir, capture, "MAIN_IMAGE_UNAVAILABLE", "Main image URL or SHA-256 validation failed")
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    mime, width, height = image_info(image_path)
    stated_width, stated_height = int(main_image.get("width", 0)), int(main_image.get("height", 0))
    if width and stated_width != width or height and stated_height != height or min(stated_width, stated_height) <= 0:
        fail_task(task, evidence, task_dir, capture, "MAIN_IMAGE_UNAVAILABLE", "Main image dimensions do not match the file")
        atomic_write_json(task_path, task)
        print(task["state"])
        return
    screenshot_paths: dict[str, str] = {}
    screenshot_hashes: dict[str, str] = {}
    for role in ("product_core", "product_details"):
        path = Path(str(screenshots.get(role, ""))).expanduser().resolve()
        if not path.is_file() or not path_within(path, task_dir / "screenshots"):
            fail_task(task, evidence, task_dir, capture, "RESPONSE_SCHEMA_CHANGED", f"Missing required screenshot: {role}")
            atomic_write_json(task_path, task)
            print(task["state"])
            return
        screenshot_paths[role] = str(path)
        screenshot_hashes[role] = sha256_file(path)

    if not str(capture.get("title") or "").strip() or not str(capture.get("category") or "").strip():
        fail_task(task, evidence, task_dir, capture, "RESPONSE_SCHEMA_CHANGED", "Amazon title and category are required")
        atomic_write_json(task_path, task)
        print(task["state"])
        return

    fields = ["title", "brand", "manufacturer", "category", "bullets", "specifications", "structure", "visible_ip_claims"]
    product = task["product"]
    product["actual_asin"] = actual
    product["variant"] = variant
    for field in fields:
        product[field] = capture.get(field, [] if field in {"bullets", "structure", "visible_ip_claims"} else ({} if field == "specifications" else ""))
    task["images"] = [{
        "image_id": "IMG-001", "role": "main", "path": str(image_path), "source_url": source_url,
        "sha256": actual_hash, "mime_type": mime, "width": stated_width, "height": stated_height,
        "format": str(main_image.get("format", "")), "collected_at": collected_at,
    }]
    browser_ev = {
        "evidence_id": stable_id("EV", "amazon_browser", actual, actual_hash),
        "source": "amazon_browser", "product": product, "requested_url": capture.get("requested_url"),
        "final_url": final_url, "screenshots": screenshot_paths, "screenshot_hashes": screenshot_hashes,
        "ocr_text": capture.get("ocr_text", []), "visual_features": capture.get("visual_features", []),
        "collected_at": collected_at, "capture_provenance": provenance,
    }
    evidence["collections"]["browser"] = [browser_ev]
    evidence["collections"]["product"] = [browser_ev]
    raw_capture = task_dir / "raw" / "amazon_browser" / "capture.json"
    atomic_write_json(raw_capture, capture)
    raw_digest = sha256_file(raw_capture)
    query_id = stable_id("QRY", "amazon_browser", "product_capture", task["request"]["url"])
    run = {
        "run_id": stable_id("SRC", "amazon_browser", actual, actual_hash), "provider": "amazon_browser",
        "attempt_id": stable_id("SRC", "amazon_browser", actual, actual_hash), "query_id": query_id,
        "operation": "product_capture", "query": task["request"]["url"],
        "jurisdiction": task["request"]["marketplace"], "started_at": browser_ev["collected_at"],
        "finished_at": now_iso(), "status": "success", "evidence_type": "product",
        "raw_paths": [str(raw_capture)], "payload_digest": raw_digest, "error_code": "",
        "retry_count": 0, "quota": {}, "data_date": browser_ev["collected_at"],
    }
    upsert_source_run(evidence, run)
    task["checkpoints"]["browser_product"] = {"status": "success", "at": now_iso(), "evidence_id": browser_ev["evidence_id"]}
    task["updated_at"] = now_iso()
    atomic_write_json(task_path, task)
    atomic_write_json(evidence_path, evidence)
    print("success")


if __name__ == "__main__":
    main()

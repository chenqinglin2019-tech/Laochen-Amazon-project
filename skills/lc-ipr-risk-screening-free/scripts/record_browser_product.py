#!/usr/bin/env python3
"""Validate and ingest product facts collected through visible Chrome CDP."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import (
    add_gap, add_history, atomic_write_json, capture_provenance, ensure_object, image_info, load_json,
    is_active_schema, now_iso, path_within, sha256_file, sha256_json, stable_id, upsert_source_run,
    validate_checked_at, recall_integrity_enabled,
)


def merge_captured_product(task: dict, capture: dict, media_hashes: list[str]) -> None:
    """Keep observed listing facts separate from the agent's confirmed analysis."""
    from workflow_v24 import product_identity_digest
    product = task["product"]
    strict = recall_integrity_enabled(task)
    old_identity = product_identity_digest(product, task=task)
    fields = ["title", "brand", "manufacturer", "category", "bullets", "specifications", "visible_ip_claims"]
    if not strict:
        fields.append("structure")
    product["actual_asin"] = str(capture.get("actual_asin") or "").upper()
    product["variant"] = capture["variant"]
    for field in fields:
        product[field] = capture.get(field, [] if field in {"bullets", "structure", "visible_ip_claims"} else {} if field == "specifications" else "")
    if not strict:
        return
    product["raw_capture"] = {key: capture[key] for key in [*fields, "structure", "visual_features", "ocr_text"] if key in capture}
    product["media_identity"] = sorted(set(media_hashes))
    analysis = product.get("analysis")
    if isinstance(analysis, dict) and analysis.get("status") == "confirmed":
        if old_identity != product_identity_digest(product, task=task) or analysis.get("identity_sha256") != old_identity:
            analysis.update(status="stale", stale_reason="captured_product_identity_or_content_changed")
    else:
        product.setdefault("analysis", {"status": "pending"})


def validated_product_views(capture: dict, task_dir: Path, asin: str, collected_at: str,
                            main_hash: str) -> list[dict]:
    views = capture.get("product_images", [])
    if not isinstance(views, list):
        raise ValueError("product_images must be an array")
    normalized, hashes = [], {main_hash}
    for item in views:
        if not isinstance(item, dict) or str(item.get("asin") or "").upper() != asin:
            raise ValueError("Product view is not bound to the current ASIN")
        file = Path(str(item.get("path") or "")).resolve()
        if not file.is_file() or not path_within(file, task_dir / "images"):
            raise ValueError("Product views must exist inside task images/")
        url = urlparse(str(item.get("source_url") or ""))
        host = (url.hostname or "").lower()
        if url.scheme != "https" or not (host == "media-amazon.com" or host.endswith(".media-amazon.com")):
            raise ValueError("Product view must come from Amazon media")
        digest = sha256_file(file)
        if digest != item.get("sha256"):
            raise ValueError("Product view SHA-256 does not match")
        mime, width, height = image_info(file)
        if min(width, height) <= 0 or width != item.get("width") or height != item.get("height"):
            raise ValueError("Product view dimensions do not match the image")
        if digest in hashes:
            continue
        hashes.add(digest)
        normalized.append({"image_id": f"IMG-{len(normalized) + 2:03d}", "role": "product_view",
                           "path": str(file), "source_url": item["source_url"], "asin": asin,
                           "sha256": digest, "bytes": file.stat().st_size,
                           "mime_type": mime, "width": width, "height": height,
                           "format": item.get("format", ""), "collected_at": collected_at})
    return normalized


def fail_task(task: dict[str, Any], evidence: dict[str, Any], task_dir: Path, capture: dict[str, Any], code: str, detail: str, user_action: bool = False, access_limited: bool = False) -> None:
    source_status = "needs_user_action" if user_action else "access_limited" if access_limited else "failed"
    task.setdefault("errors", []).append({"at": now_iso(), "code": code, "detail": detail})
    add_gap(task, "amazon_browser", task["request"]["marketplace"],
            source_status, code, detail)
    add_history(task, "needs_user_action" if user_action else "incomplete", detail)
    digest = sha256_json(capture)
    raw_capture = task_dir / "raw" / "amazon_browser" / (
        f"capture-error-{digest}.json" if recall_integrity_enabled(task) else "capture-error.json")
    atomic_write_json(raw_capture, capture)
    upsert_source_run(evidence, {
        "run_id": stable_id("SRC", "amazon_browser", "product_capture", digest), "provider": "amazon_browser",
        "attempt_id": stable_id("SRC", "amazon_browser", "product_capture", digest),
        "query_id": stable_id("QRY", "amazon_browser", "product_capture", str(capture.get("requested_url") or task.get("request", {}).get("url", ""))),
        "operation": "product_capture", "query": str(capture.get("requested_url") or task.get("request", {}).get("url", "")),
        "jurisdiction": task.get("request", {}).get("marketplace", ""), "started_at": now_iso(), "finished_at": now_iso(),
        "status": source_status, "evidence_type": "product",
        "raw_paths": [str(raw_capture)], "payload_digest": sha256_file(raw_capture) if recall_integrity_enabled(task) else digest,
        "error_code": code, "detail": detail,
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
    if not is_active_schema(task):
        raise SystemExit("LEGACY_TASK_READ_ONLY: 2.1/2.2 product evidence cannot be changed")
    evidence = ensure_object(load_json(evidence_path), "evidence.json")
    allowed_states = {"awaiting_browser", "needs_user_action", "incomplete"}
    if recall_integrity_enabled(task):
        allowed_states.update({"collecting", "ready_for_assessment", "assessing", "needs_review"})
    if task.get("state") not in allowed_states:
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
    if status == "access_limited" and task.get("schema_version") == "2.4-free":
        fail_task(task, evidence, task_dir, capture, "AMAZON_ACCESS_LIMITED",
                  str(capture.get("detail") or "Amazon access is blocked"), access_limited=True)
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
    screenshot_bytes: dict[str, int] = {}
    for role in ("product_core", "product_details"):
        path = Path(str(screenshots.get(role, ""))).expanduser().resolve()
        if not path.is_file() or not path_within(path, task_dir / "screenshots"):
            fail_task(task, evidence, task_dir, capture, "RESPONSE_SCHEMA_CHANGED", f"Missing required screenshot: {role}")
            atomic_write_json(task_path, task)
            print(task["state"])
            return
        screenshot_paths[role] = str(path)
        screenshot_hashes[role] = sha256_file(path)
        screenshot_bytes[role] = path.stat().st_size

    if not str(capture.get("title") or "").strip() or not str(capture.get("category") or "").strip():
        fail_task(task, evidence, task_dir, capture, "RESPONSE_SCHEMA_CHANGED", "Amazon title and category are required")
        atomic_write_json(task_path, task)
        print(task["state"])
        return

    product = task["product"]
    task["images"] = [{
        "image_id": "IMG-001", "role": "main", "path": str(image_path), "source_url": source_url,
        "sha256": actual_hash, "bytes": image_path.stat().st_size, "mime_type": mime,
        "width": stated_width, "height": stated_height,
        "format": str(main_image.get("format", "")), "collected_at": collected_at,
    }]
    if task.get("schema_version") == "2.4-free":
        try:
            task["images"].extend(validated_product_views(capture, task_dir, actual, collected_at, actual_hash))
        except (TypeError, ValueError) as exc:
            fail_task(task, evidence, task_dir, capture, "PRODUCT_VIEW_INVALID", str(exc))
            atomic_write_json(task_path, task)
            print(task["state"])
            return
        coverage = capture.get("image_coverage") or {}
        product["image_coverage"] = {
            "retrieved_count": len(task["images"]),
            "available_thumbnail_count": coverage.get("available_thumbnail_count") if isinstance(coverage, dict) else None,
            "truncated": coverage.get("truncated") if isinstance(coverage, dict) else None,
            "completeness": "unknown",
            "reason": "Collected gallery views do not establish coverage of internal structure, all relevant faces, or packaging.",
        }
    merge_captured_product(task, capture, [item["sha256"] for item in task["images"]])
    strict = recall_integrity_enabled(task)
    capture_identity = sha256_json(capture) if strict else actual_hash
    browser_ev = {
        "evidence_id": stable_id("EV", "amazon_browser", actual, capture_identity),
        "source": "amazon_browser", "product": product, "requested_url": capture.get("requested_url"),
        "final_url": final_url, "screenshots": screenshot_paths, "screenshot_hashes": screenshot_hashes,
        "screenshot_bytes": screenshot_bytes,
        "ocr_text": capture.get("ocr_text", []), "visual_features": capture.get("visual_features", []),
        "collected_at": collected_at, "capture_provenance": provenance,
        **({"images": list(task["images"]), "image_coverage": product["image_coverage"]}
           if task.get("schema_version") == "2.4-free" else {}),
    }
    for collection in ("browser", "product"):
        if strict:
            entries = evidence["collections"].setdefault(collection, [])
            existing = next((item for item in entries if item.get("evidence_id") == browser_ev["evidence_id"]), None)
            if existing is None:
                entries.append(browser_ev)
            # Re-ingestion of the identical capture preserves its original
            # product snapshot, including the analysis as it existed then.
        else:
            evidence["collections"][collection] = [browser_ev]
    raw_capture = task_dir / "raw" / "amazon_browser" / (
        f"capture-{capture_identity}.json" if strict else "capture.json")
    atomic_write_json(raw_capture, capture)
    raw_digest = sha256_file(raw_capture)
    query_id = stable_id("QRY", "amazon_browser", "product_capture", task["request"]["url"])
    run = {
        "run_id": stable_id("SRC", "amazon_browser", actual, capture_identity), "provider": "amazon_browser",
        "attempt_id": stable_id("SRC", "amazon_browser", actual, capture_identity), "query_id": query_id,
        "operation": "product_capture", "query": task["request"]["url"],
        "jurisdiction": task["request"]["marketplace"], "started_at": browser_ev["collected_at"],
        "finished_at": now_iso(), "status": "success", "evidence_type": "product",
        "raw_paths": [str(raw_capture)], "payload_digest": raw_digest, "error_code": "",
        "retry_count": 0, "quota": {}, "data_date": browser_ev["collected_at"],
    }
    if not strict or not any(item.get("run_id") == run["run_id"] for item in evidence.get("source_runs", [])):
        upsert_source_run(evidence, run)
    task["checkpoints"]["browser_product"] = {"status": "success", "at": now_iso(), "evidence_id": browser_ev["evidence_id"]}
    task["updated_at"] = now_iso()
    if strict and task.get("state") in {"ready_for_assessment", "assessing", "needs_review"}:
        add_history(task, "collecting", "Product recapture invalidates prior review digests; recheck analysis before assessment")
    atomic_write_json(task_path, task)
    atomic_write_json(evidence_path, evidence)
    print("success")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Record USPTO recall for 2.3; reject all writes to legacy/WIPO routes."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from record_browser_execution import validate_browser_execution

from common import (
    capture_provenance, coverage_route_configured, ensure_object, is_active_schema,
    load_json, load_skill_config, path_within, sha256_file, validate_checked_at,
    recall_integrity_enabled,
)
from provider_utils import record_result


PROVIDERS = {"wipo_patentscope_browser", "espacenet_browser", "uspto_patent_browser"}
ALLOWED_CAPTURE_STATUSES = {"success", "no_result", "needs_user_action", "access_limited", "failed"}


def capture_diagnostics(capture: dict) -> dict:
    """Retain execution failure identity without converting missing work to zero."""
    return {key: capture[key] for key in ("error_code", "phase", "submission_state") if capture.get(key)}


def number(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def screenshot(value: object, task_dir: Path) -> tuple[str, str, int]:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file() or not path_within(path, task_dir / "screenshots"):
        raise ValueError(f"screenshot_path must exist inside task screenshots/: {path}")
    return str(path), sha256_file(path), path.stat().st_size


def strings(value: object) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [str(item).strip() for item in values if str(item).strip()]


def normalize_candidate(
    item: object, provider: str, final_url: str, checked_at: str,
    image_path: str, image_hash: str, image_bytes: int,
) -> dict:
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
    right_type = str(item.get("right_type") or "").strip() or (
        "design" if str(item.get("kind_code") or "").upper().startswith("S") else "patent"
    )
    material = bool(item.get("material", False))
    return {
        **identifiers,
        "title": title,
        "owners": strings(item.get("owners") or item.get("owner") or item.get("assignee")),
        "inventors": strings(item.get("inventors") or item.get("inventor")),
        "publication_date": str(item.get("publication_date") or "").strip(),
        "result_ordinal": item.get("result_ordinal") if isinstance(item.get("result_ordinal"), int) and not isinstance(item.get("result_ordinal"), bool) and item["result_ordinal"] > 0 else None,
        "family_members": [number(value) for value in strings(item.get("family_members"))],
        "family_member_count": item.get("family_member_count") if isinstance(item.get("family_member_count"), int) and not isinstance(item.get("family_member_count"), bool) and item["family_member_count"] >= 0 else None,
        "legal_status": str(item.get("legal_status") or item.get("status") or "").strip(),
        "jurisdiction": str(item.get("jurisdiction") or "").upper(),
        "kind_code": str(item.get("kind_code") or "").upper(),
        "family_id": str(item.get("family_id") or "").strip(),
        "source": provider,
        "right_type": right_type,
        "material": material,
        "material_reason": str(item.get("material_reason") or ("source_marked_material" if material else "")),
        "official_verification": {
            "status": "not_checked", "source": provider, "authority": provider,
            "method": "", "identity_match": None, "legal_status": "",
            "owner": [], "classes": [], "media": [],
            "url": final_url, "checked_at": checked_at,
        },
        "browser_evidence": {
            "screenshot_path": image_path,
            "screenshot_sha256": image_hash,
            "screenshot_bytes": image_bytes,
            "checked_at": checked_at,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a planned USPTO CDP patent-recall result for a 2.3 task.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--capture", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.expanduser().resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if not is_active_schema(task):
        raise SystemExit("LEGACY_TASK_READ_ONLY: 2.1/2.2 browser evidence cannot be changed")
    if args.provider != "uspto_patent_browser":
        code = "WIPO_PROVIDER_DISABLED" if args.provider == "wipo_patentscope_browser" else "LEGACY_PROVIDER_DISABLED"
        raise SystemExit(f"{code}: {args.provider} cannot record new 2.3 evidence")
    capture = ensure_object(load_json(args.capture.expanduser().resolve()), "browser patent recall capture")
    operation = "design_recall" if task.get("schema_version") == "2.4-free" and capture.get("right_type") == "design" else "patent_recall"
    if not coverage_route_configured(task, args.provider, operation):
        raise SystemExit(f"{args.provider} is not a configured patent browser gate for this task")
    status = str(capture.get("status") or "")
    if status not in ALLOWED_CAPTURE_STATUSES:
        raise SystemExit(f"Unsupported browser patent recall status: {status!r}")
    try:
        if args.provider == "espacenet_browser" and task.get("schema_version") != "2.1-free":
            raise ValueError("Espacenet browser automation is legacy-only; use EPO OPS")
        allowed_transports = {"manual"} if args.provider == "wipo_patentscope_browser" else {"cdp"}
        provenance = capture_provenance(capture, task, allowed_transports=allowed_transports)
        provenance.update(validate_browser_execution(capture, task, task_dir, args.provider))
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
        image_path, image_hash, image_bytes = screenshot(capture.get("screenshot_path"), task_dir)
        mode = str(capture.get("mode") or "").strip()
        right_type = str(capture.get("right_type") or capture.get("search_focus") or "").strip()
        search_focus = str(capture.get("search_focus") or right_type).strip()
        capture_query_id = str(capture.get("query_id") or "").strip()
        if not mode:
            raise ValueError("mode is required and must match search-plan.json")
        if right_type not in {"patent", "design"}:
            raise ValueError("right_type must be patent or design")
        planned_query_id = ""
        if is_active_schema(task):
            plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
            matches = [
                item for item in plan.get("queries", {}).get(args.provider, [])
                if isinstance(item, dict)
                and str(item.get("q") or "") == query
                and str(item.get("mode") or ("basic_search" if task.get("schema_version") == "2.4-free" else "")) == mode
                and str(item.get("search_focus") or item.get("right_type") or "") == search_focus
                and str(item.get("right_type") or "") == right_type
                and item.get("operation") == operation
                and (not capture_query_id or str(item.get("query_id") or "") == capture_query_id)
            ]
            if len(matches) != 1 or not matches[0].get("query_id"):
                raise ValueError("query/mode must match exactly one generated search-plan entry")
            planned_query_id = str(matches[0]["query_id"])
        raw_candidates = capture.get("candidates", [])
        if not isinstance(raw_candidates, list):
            raise ValueError("candidates must be an array")
        if status == "success" and not raw_candidates:
            raise ValueError("success requires at least one candidate")
        if status == "no_result" and (raw_candidates or not str(capture.get("result_message") or "").strip()):
            raise ValueError("no_result requires an empty candidates array and result_message")
        normalized = (
            {
                "candidates": [
                    normalize_candidate(
                        item, args.provider, final_url, checked_at,
                        image_path, image_hash, image_bytes,
                    )
                    for item in raw_candidates
                ],
                "browser_evidence": {
                    "screenshot_path": image_path,
                    "screenshot_sha256": image_hash,
                    "screenshot_bytes": image_bytes,
                    "checked_at": checked_at,
                },
            }
            if status == "success" else
            {
                "candidates": [],
                "browser_evidence": {
                    "screenshot_path": image_path,
                    "screenshot_sha256": image_hash,
                    "screenshot_bytes": image_bytes,
                    "checked_at": checked_at,
                },
            }
            if status == "no_result" else None
        )
        if normalized is not None:
            normalized["browser_evidence"]["capture_provenance"] = provenance
            for candidate in normalized.get("candidates", []):
                candidate["browser_evidence"]["capture_provenance"] = provenance
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid browser patent recall capture: {exc}") from None
    detail = str(capture.get("detail") or capture.get("result_message") or "").strip()
    if recall_integrity_enabled(task) and normalized is None:
        normalized = {"candidates": [], "search_metadata": {**capture.get("result_coverage", {}),
                       "schema_valid": False, **capture_diagnostics(capture)}}
    if task.get("schema_version") == "2.4-free" and isinstance(normalized, dict):
        normalized["search_metadata"] = {**normalized.get("search_metadata", {}), **capture.get("result_coverage", {}),
                                         "query_semantics": provenance.get("query_semantics", {}),
                                         **(capture_diagnostics(capture) if recall_integrity_enabled(task) else {})}
    error_code = ""
    if status == "needs_user_action":
        error_code, detail = "BROWSER_USER_ACTION_REQUIRED", detail or "Official patent registry requires user action in Chrome desktop"
    elif status in {"access_limited", "failed"}:
        error_code, detail = "OFFICIAL_VERIFICATION_REQUIRED", detail or "Official browser patent recall could not be completed"
    if recall_integrity_enabled(task) and capture.get("error_code"):
        error_code = str(capture["error_code"])
    run = record_result(
        task_dir, provider=args.provider, operation=operation, query=query,
        jurisdiction="US", evidence_type="patent", status=status, normalized=normalized,
        raw_body=json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8"), raw_suffix="json",
        error_code=error_code, detail=detail, mandatory=False,
        request_params={
            "q": query, "mode": mode, "search_focus": search_focus,
            "right_type": right_type,
        },
        query_id=planned_query_id,
    )
    print(run["status"])


if __name__ == "__main__":
    main()

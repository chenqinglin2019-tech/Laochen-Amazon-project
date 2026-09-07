#!/usr/bin/env python3
"""Validate and record a USPTO Patent Public Search Chrome desktop verification."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import re
from pathlib import Path
from urllib.parse import urlparse
import uuid

from record_browser_execution import canonical_digest, validate_browser_execution

from common import (
    capture_provenance, ensure_object, image_info, is_active_schema, load_json, load_skill_config,
    intrinsic_patent_right_type, path_within, sha256_file, validate_checked_at, recall_integrity_enabled,
    atomic_write_bytes, atomic_write_json, now_iso,
)
from provider_utils import (PLAN_META_KEYS, evidence_lock, planned_query_metadata, record_result,
                            sanitize_for_evidence, sanitize_raw_evidence, validate_text_evidence)


ALLOWED_CAPTURE_STATUSES = {"success", "no_result", "needs_user_action", "access_limited", "failed"}


def clean_number(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def nonempty_strings(value: object, field: str) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    result = [str(item).strip() for item in values if str(item).strip()]
    if not result:
        raise ValueError(f"{field} must contain at least one value")
    return result


def resolved_right_type(capture: dict, record_number: str) -> str:
    declared = str(capture.get("right_type") or "").strip()
    intrinsic_values = {
        intrinsic_patent_right_type("US", value)
        for value in (
            record_number, capture.get("publication_number"),
            capture.get("grant_number"),
        )
        if str(value or "").strip()
    } - {""}
    if len(intrinsic_values) > 1:
        raise ValueError("official US identifiers encode conflicting right types")
    intrinsic = next(iter(intrinsic_values), "")
    if declared and intrinsic and declared != intrinsic:
        raise ValueError(
            f"right_type {declared!r} conflicts with the official US identifier type {intrinsic!r}"
        )
    right_type = intrinsic or declared or "patent"
    if right_type not in {"patent", "design"}:
        raise ValueError("right_type must be patent or design")
    return right_type


def validate_file(value: object, field: str, task_dir: Path) -> tuple[str, str]:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file() or not path_within(path, task_dir / "screenshots"):
        raise ValueError(f"{field} must exist inside task screenshots/: {path}")
    return str(path), sha256_file(path)


def validate_common(
    capture: dict, task: dict, allowed_hosts: set[str], task_dir: Path, status: str,
) -> tuple[str, str, str, str, str, dict]:
    provenance = capture_provenance(capture, task, allowed_transports={"cdp"})
    provenance.update(validate_browser_execution(capture, task, task_dir, "uspto_patent_browser"))
    record_number = clean_number(capture.get("record_number"))
    page_record_number = clean_number(capture.get("page_record_number"))
    if not record_number:
        raise ValueError("record_number must be a non-empty identifier")
    if page_record_number and page_record_number != record_number:
        raise ValueError("page_record_number does not match record_number")
    if status == "success" and page_record_number != record_number:
        raise ValueError("successful verification requires an exact page_record_number match")
    final_url = str(capture.get("final_url") or "").strip()
    parsed = urlparse(final_url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in allowed_hosts:
        raise ValueError("final_url must be an allowed official HTTPS USPTO Patent Public Search URL")
    # PPS Advanced uses one stable workspace URL. Strict evidence instead binds
    # the submitted number, Search History and Document Viewer identity in its
    # validated execution receipt; never invent a record number in the URL.
    if not recall_integrity_enabled(task) and record_number not in clean_number(final_url):
        raise ValueError("final_url must contain the verified record number")
    checked_at = str(capture.get("checked_at") or "").strip()
    validate_checked_at(checked_at)
    screenshot_path, screenshot_sha256 = validate_file(capture.get("screenshot_path"), "screenshot_path", task_dir)
    return record_number, final_url, checked_at, screenshot_path, screenshot_sha256, provenance


def bind_candidate_plan(
    task_dir: Path, capture: dict, record_number: str, right_type: str,
) -> tuple[str, str]:
    query_id = str(capture.get("query_id") or "").strip()
    candidate_id = str(capture.get("candidate_id") or "").strip()
    if not query_id or not candidate_id:
        raise ValueError("capture requires query_id and candidate_id from the generated plan")
    planned = planned_query_metadata(task_dir, "uspto_patent_browser", query_id)
    if not planned:
        raise ValueError("query_id is not an exact USPTO patent plan entry")
    planned_record = str(planned.get("record_number") or planned.get("q") or "").strip()
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
    if clean_number(planned.get("q")) != clean_number(planned_record):
        raise ValueError("planned q and record_number differ")
    if clean_number(planned_record) != record_number:
        raise ValueError("capture record_number does not match the selected plan entry")
    if not any(str(value).strip() for value in planned.get("requirement_ids", [])):
        raise ValueError("planned candidate action has no requirement_ids")
    return query_id, candidate_id


def candidate_request_params(task_dir: Path, task: dict, capture: dict, record_number: str, right_type: str) -> dict:
    query_id, candidate_id = bind_candidate_plan(task_dir, capture, record_number, right_type)
    if recall_integrity_enabled(task):
        planned = planned_query_metadata(task_dir, "uspto_patent_browser", query_id)
        # Preserve the entire validated input contract, including strategy and
        # future supported filters. Routing metadata is kept out of the request.
        return {**{key: deepcopy(value) for key, value in planned.items() if key not in PLAN_META_KEYS},
                "right_type": right_type}
    return {"q": record_number, "candidate_id": candidate_id, "right_type": right_type,
            "record_number": str(capture.get("record_number") or "").strip()}


def repair_derived_request_params(task_dir: Path, evidence_ids: list[str]) -> dict:
    """Repair only missing derived fields proven by intact strict capture receipts.

    This is a local metadata migration, not a new official query or source run.
    The original evidence snapshot and a separate repair audit remain available.
    """
    task_dir = task_dir.resolve()
    if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("repair requires explicit unique evidence IDs")
    with evidence_lock(task_dir):
        task = ensure_object(load_json(task_dir / "task.json"), "task.json")
        if not recall_integrity_enabled(task):
            raise ValueError("LEGACY_TASK_READ_ONLY: metadata repair requires recall-integrity revision")
        evidence_path = task_dir / "evidence.json"
        evidence = ensure_object(load_json(evidence_path), "evidence.json")
        if evidence.get("task_id") != task.get("task_id") or evidence.get("schema_version") != task.get("schema_version"):
            raise ValueError("EVIDENCE_TASK_MISMATCH")
        updated = deepcopy(evidence)
        changes, protected = [], {}
        cfg = load_skill_config()["providers"]["uspto_patent_browser"]
        hosts = {str(host).casefold() for host in cfg["browser_allowed_hosts"]}
        for evidence_id in evidence_ids:
            entries = [row for row in updated.get("collections", {}).get("official_verifications", []) if row.get("evidence_id") == evidence_id]
            if len(entries) != 1:
                raise ValueError("repair evidence ID must identify one official verification")
            entry = entries[0]
            runs = [row for row in updated.get("source_runs", []) if row.get("run_id") == entry.get("source_run_id")]
            if len(runs) != 1:
                raise ValueError("repair evidence requires one source run")
            run = runs[0]
            if run.get("provider") != "uspto_patent_browser" or run.get("operation") != "candidate_verification" or len(run.get("raw_paths", [])) != 1:
                raise ValueError("repair only supports one raw PPS candidate-verification capture")
            raw_path = Path(run["raw_paths"][0]).resolve()
            if not path_within(raw_path, task_dir / "raw") or sha256_file(raw_path) != run.get("payload_digest"):
                raise ValueError("repair raw capture is missing, outside the task, or changed")
            # The generic raw-evidence sanitizer redacts even the already
            # sanitized CDP session correlation ID. Validate the original
            # immutable capture, after proving that it produced this exact raw
            # document through the recorder's existing sanitization pipeline.
            raw_bytes = raw_path.read_bytes()
            originals = []
            for candidate_path in task_dir.glob("*capture.json"):
                candidate = ensure_object(load_json(candidate_path), "candidate capture")
                if candidate.get("query_id") != run.get("query_id"):
                    continue
                encoded = json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode("utf-8")
                if sanitize_raw_evidence(encoded, "json") == raw_bytes:
                    originals.append((candidate_path, candidate))
            if len(originals) != 1:
                raise ValueError("repair requires one original capture matching the sanitized raw evidence")
            capture_path, capture = originals[0]
            common = validate_common(capture, task, hosts, task_dir, str(capture.get("status") or ""))
            record_number = common[0]
            right_type = resolved_right_type(capture, record_number)
            params = candidate_request_params(task_dir, task, capture, record_number, right_type)
            planned = planned_query_metadata(task_dir, "uspto_patent_browser", capture["query_id"])
            if (entry.get("query_id") != capture.get("query_id") or run.get("query_id") != capture.get("query_id")
                    or run.get("status") != capture.get("status")
                    or any(entry.get(key) != run.get(key) for key in ("provider", "operation", "jurisdiction", "right_type"))
                    or run.get("query") != planned.get("q")
                    or run.get("plan_entry_sha256") != canonical_digest(planned)
                    or entry.get("plan_entry_sha256") != canonical_digest(planned)):
                raise ValueError("repair source, evidence and receipt plan bindings differ")
            original_params = run.get("request_params")
            if not isinstance(original_params, dict) or any(key not in params or params[key] != value for key, value in original_params.items()):
                raise ValueError("repair cannot overwrite conflicting recorded request parameters")
            if original_params == params:
                raise ValueError("repair is unnecessary: request parameters already match the plan")
            paths = [raw_path, capture_path, Path(capture["query_execution"]["path"]), Path(capture["screenshot_path"])]
            paths.extend(Path(row["path"]) for row in capture.get("evidence_images", []))
            if capture.get("history_binding", {}).get("screenshot_path"):
                paths.append(Path(capture["history_binding"]["screenshot_path"]))
            for file in paths:
                if not path_within(file.resolve(), task_dir):
                    raise ValueError("repair protected artifact is outside the task")
                protected[str(file.resolve())] = sha256_file(file)
            changes.append({"evidence_id": evidence_id, "source_run_id": run["run_id"], "query_id": run["query_id"],
                            "plan_entry_sha256": run["plan_entry_sha256"], "before": deepcopy(original_params), "after": deepcopy(params),
                            "added_keys": sorted(set(params) - set(original_params))})
            run["request_params"] = params
        repair_dir = task_dir / "repairs" / ("request-params-" + uuid.uuid4().hex)
        repair_dir.mkdir(parents=True, exist_ok=False)
        snapshot = repair_dir / "evidence-before.json"
        atomic_write_bytes(snapshot, evidence_path.read_bytes())
        audit = {"schema_version": "1.0", "task_id": task["task_id"], "repair_type": "derived_request_params",
                 "repaired_at": now_iso(), "external_execution_performed": False,
                 "reason": "Restore omitted non-metadata parameters from the exact plan after validating the original raw capture and execution receipt.",
                 "snapshot_path": str(snapshot), "evidence_before_sha256": sha256_file(snapshot),
                 "changes": changes, "protected_artifact_sha256": protected}
        audit_path = repair_dir / "repair-audit.json"
        atomic_write_json(audit_path, {**audit, "status": "prepared"})
        atomic_write_json(evidence_path, updated)
        if any(sha256_file(Path(file)) != digest for file, digest in protected.items()):
            raise ValueError("repair detected a concurrent protected-artifact change")
        audit.update(status="completed", evidence_after_sha256=sha256_file(evidence_path))
        atomic_write_json(audit_path, audit)
        return {"status": "repaired", "audit_path": str(audit_path), "changes": len(changes)}


def normalize_success(capture: dict, common: tuple[str, str, str, str, str, dict], *, published_only: bool = False) -> dict:
    if validate_text_evidence(capture) is not None:
        capture = sanitize_for_evidence(capture)
    record_number, final_url, checked_at, screenshot_path, screenshot_sha256, provenance = common
    title = str(capture.get("title") or "").strip()
    legal_status = str(capture.get("legal_status") or "").strip()
    if not title or not legal_status and not published_only:
        raise ValueError("title and legal_status are required for a successful verification")
    if published_only and (legal_status or capture.get("owners") or capture.get("owner")):
        raise ValueError("a published document does not establish current legal status or owner")
    right_type = resolved_right_type(capture, record_number)
    normalized = {
        "jurisdiction": "US", "right_type": right_type,
        "candidate_id": str(capture.get("candidate_id") or "").strip(),
        "record_number": record_number,
        "publication_number": str(capture.get("publication_number") or record_number).strip(),
        "application_number": str(capture.get("application_number") or "").strip(),
        "grant_number": str(capture.get("grant_number") or "").strip(),
        "title": title,
        "legal_status": legal_status,
        "owners": [] if published_only else nonempty_strings(capture.get("owners", capture.get("owner")), "owners"),
        "official_verification": {
            "status": "incomplete" if published_only else "verified", "authority": "United States Patent and Trademark Office (USPTO)",
            "source": "USPTO Patent Public Search Chrome Desktop",
            "url": final_url, "checked_at": checked_at, "method": "cdp_assisted",
            "identity_match": True, "legal_status": legal_status,
            "owner": [] if published_only else nonempty_strings(capture.get("owners", capture.get("owner")), "owners"),
            "classes": nonempty_strings(capture.get("classifications"), "classifications") if capture.get("classifications") else [],
            "media": [],
        },
        "browser_evidence": {
            "screenshot_path": screenshot_path, "screenshot_sha256": screenshot_sha256,
            "screenshot_bytes": Path(screenshot_path).stat().st_size,
            "capture_provenance": provenance,
        },
        "capture_transport": provenance["capture_transport"],
    }
    if published_only:
        if "text_evidence_revision" in capture:
            normalized["text_evidence_revision"] = capture["text_evidence_revision"]
        normalized["published_document"] = {
            **capture["document_retrieval"],
            "rendered_text": capture["rendered_text"],
            "inventor_information": str(capture.get("inventor_information") or ""),
            "published_at": str(capture.get("published_at") or ""),
            "filed_at": str(capture.get("filed_at") or ""),
        }
        normalized["official_verification"].update({
            "authority_scope": "published_document_only", "document_retrieval_status": "success",
            "missing_official_current_status": True, "missing_official_current_owner": True,
            "reason": "Official published document identity and available media were retrieved; current legal status and ownership remain unverified.",
        })
        if capture.get("workflow_correction_revision") == "workflow-correction-v1":
            normalized.update(authority_scope="published_document_only", document_identity_match=True,
                              document_text=capture["rendered_text"], abstract=str(capture.get("abstract") or ""),
                              required_facts=capture.get("required_facts", []), reading_scope=capture.get("reading_scope", {}),
                              satisfied_facts=capture.get("satisfied_facts", []),
                              content_retrieval_status=capture.get("content_retrieval_status", "incomplete"))
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
            mime_type, _, _ = image_info(Path(path))
            media_item = {
                "path": path, "sha256": digest,
                "bytes": Path(path).stat().st_size, "mime_type": mime_type,
                "label": str(item.get("label") or f"USPTO evidence image {index}").strip(),
                "role": str(item.get("role") or "official_drawing").strip(),
            }
            normalized["browser_evidence"]["evidence_images"].append(media_item)
            normalized["official_verification"]["media"].append(media_item)
    if right_type == "design" and not published_only:
        if not normalized["official_verification"]["classes"]:
            raise ValueError("successful US design verification requires official classification")
        if not normalized["official_verification"]["media"]:
            raise ValueError("successful US design verification requires official drawing media")
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Record USPTO Patent Public Search Chrome desktop evidence.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--repair-evidence-id", action="append", default=[], help="Explicit strict evidence ID whose missing derived request parameters should be repaired without querying")
    args = parser.parse_args()
    task_dir = args.task_dir.expanduser().resolve()
    if args.repair_evidence_id:
        if args.capture:
            parser.error("--capture cannot be combined with --repair-evidence-id")
        print(json.dumps(repair_derived_request_params(task_dir, args.repair_evidence_id), ensure_ascii=False))
        return
    if not args.capture:
        parser.error("--capture is required unless repairing explicit evidence IDs")
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if not is_active_schema(task):
        raise SystemExit("LEGACY_TASK_READ_ONLY: 2.1/2.2 patent evidence cannot be changed")
    if "US" not in {str(value).upper() for value in task.get("target_jurisdictions", [])}:
        raise SystemExit("USPTO Patent Public Search Chrome desktop verification is only valid for US tasks")
    capture = ensure_object(load_json(args.capture.expanduser().resolve()), "USPTO Patent Public Search Chrome desktop capture")
    status = str(capture.get("status") or "")
    if status not in ALLOWED_CAPTURE_STATUSES:
        raise SystemExit(f"Unsupported USPTO Patent Public Search Chrome desktop capture status: {status!r}")
    cfg = load_skill_config()["providers"]["uspto_patent_browser"]
    allowed_hosts = {str(host).casefold() for host in cfg["browser_allowed_hosts"]}
    try:
        common = validate_common(capture, task, allowed_hosts, task_dir, status)
        record_number, _, _, _, _, _ = common
        right_type = resolved_right_type(capture, record_number)
        query_id, candidate_id = bind_candidate_plan(task_dir, capture, record_number, right_type)
        request_params = candidate_request_params(task_dir, task, capture, record_number, right_type)
        published_only = (recall_integrity_enabled(task)
                          and capture.get("document_retrieval", {}).get("status") == "success")
        if task.get("workflow_correction_revision") == "workflow-correction-v1":
            from workflow_v24 import reading_contract_valid
            planned = planned_query_metadata(task_dir, "uspto_patent_browser", query_id)
            if (capture.get("workflow_correction_revision") != task["workflow_correction_revision"]
                    or not reading_contract_valid(planned)
                    or capture.get("required_facts") != planned["required_facts"]
                    or capture.get("reading_scope", {}).get("level") != planned["reading_scope"]["level"]
                    or capture.get("reading_scope", {}).get("page_numbers", []) != planned["reading_scope"].get("page_numbers", [])):
                raise ValueError("Requested content scope differs from the exact plan")
            if "current_status" in planned["required_facts"] and published_only:
                raise ValueError("Published content cannot satisfy current status")
            obtained = capture.get("satisfied_facts", [])
            if not isinstance(obtained, list) or any(fact not in {"abstract", "representative_figures", "protection_content"} for fact in obtained):
                raise ValueError("Published content facts are invalid")
            if "abstract" in obtained and (not str(capture.get("abstract") or "").strip()
                    or capture["abstract"] not in str(capture.get("rendered_text") or "")):
                raise ValueError("Abstract is not bound to the retained document text")
            pages = capture.get("document_pages", [])
            for page in pages:
                if (not isinstance(page, dict) or clean_number(page.get("record_number")) != record_number
                        or type(page.get("page")) is not int or page["page"] < 1):
                    raise ValueError("Requested page identity is invalid")
                page_path, page_hash = validate_file(page.get("path"), "document_page.path", task_dir)
                if page_hash != page.get("sha256"):
                    raise ValueError("Requested page bytes changed")
            if "representative_figures" in obtained and (not planned["reading_scope"].get("page_numbers")
                    or not set(planned["reading_scope"]["page_numbers"]) <= {page["page"] for page in pages}):
                raise ValueError("Requested representative pages are incomplete")
            if "protection_content" in obtained and (not capture.get("rendered_text")
                    or len(capture["rendered_text"]) >= 200000
                    or capture.get("media_coverage", {}).get("completeness") != "complete"):
                raise ValueError("Protection-content document coverage is incomplete")
            if status == "success" and not set(planned["required_facts"]) <= set(obtained):
                raise ValueError("Successful content retrieval lacks requested facts")
        normalized = normalize_success(capture, common, published_only=published_only) if status == "success" or published_only else None
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
        error_code = str(capture.get("error_code") or "OFFICIAL_VERIFICATION_REQUIRED") if recall_integrity_enabled(task) else "OFFICIAL_VERIFICATION_REQUIRED"
        detail = detail or "USPTO Patent Public Search Chrome desktop verification could not be completed"

    raw_body = json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if normalized is not None and recall_integrity_enabled(task):
        normalized["search_metadata"] = {"phase": capture.get("phase"), "submission_state": capture.get("submission_state"),
                                         "error_code": error_code, "document_retrieval_status": "success" if published_only else "unconfirmed"}
    run = record_result(
        task_dir, provider="uspto_patent_browser", operation="candidate_verification", query=str(request_params.get("q") or record_number),
        jurisdiction="US", evidence_type="official_verification", status=status,
        normalized=normalized, raw_body=raw_body, raw_suffix="json",
        error_code=error_code, detail=detail, mandatory=True,
        request_params=request_params,
        query_id=query_id,
    )
    print(run["status"])


if __name__ == "__main__":
    main()

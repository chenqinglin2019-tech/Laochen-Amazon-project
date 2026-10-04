#!/usr/bin/env python3
"""Retrieve one selected Google Patents record through SerpApi Details.

This is a bounded content reader, not an official status route.  It shares the
existing SerpApi account, account-capacity reservation ledger and task request cap.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

from common import (SERPAPI_DETAILS_OPERATION, SERPAPI_PROVIDER, ensure_object,
                    load_json, provider_execution_error, sha256_json, atomic_write_bytes, path_within, sha256_file)
from free_search_budget import attempt_context, reserve_search
from source_policy import enabled as account_capacity_enabled, dynamic_max_age_hours
from provider_utils import (ProviderError, authorize_exact_plan_execution, http_json, http_request,
                            record_result, sanitize_for_evidence, MAX_HTTP_RESPONSE_BYTES)
from serpapi_patents_client import (budget_lock, consumed_queries, free_account_snapshot,
                                    persisted_quota_block_reason, settings)


def _request_params(item: dict) -> dict:
    params = {"patent_id": item["patent_id"], "candidate_id": item["candidate_id"],
              "right_type": item.get("right_type")}
    if "missing_facts" in item:
        params["missing_facts"] = item["missing_facts"]
    if "publication_number" in item:
        params["publication_number"] = item["publication_number"]
    return params


def _item(task_dir: Path, query_id: str) -> tuple[dict, dict]:
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    matches = [row for row in plan.get("queries", {}).get(SERPAPI_PROVIDER, [])
               if isinstance(row, dict) and row.get("query_id") == query_id]
    if len(matches) != 1:
        raise ProviderError("QUERY_ID_NOT_EXACTLY_PLANNED", "failed", "SerpApi detail query must be exactly planned")
    item = dict(matches[0])
    if item.get("operation") != SERPAPI_DETAILS_OPERATION or not item.get("candidate_id"):
        raise ProviderError("QUERY_PLAN_SCOPE_MISMATCH", "failed", "SerpApi details requires a selected candidate and candidate_detail operation")
    patent_id = str(item.get("patent_id") or "").strip()
    if not re.fullmatch(r"patent/[A-Za-z]{2}[A-Za-z0-9]+/[a-z]{2}", patent_id):
        raise ProviderError("SERPAPI_PATENT_ID_INVALID", "failed", "patent_id must be an exact Google Patents document identifier")
    if "publication_number" in item:
        normalize = lambda value: re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
        if (not normalize(item["publication_number"])
                or normalize(item["publication_number"]) != normalize(item.get("q"))
                or normalize(patent_id.split("/")[1]) != normalize(item["publication_number"])):
            raise ProviderError("RESPONSE_IDENTITY_MISMATCH", "failed", "Exact follow-up locator, query and patent_id must identify one publication")
    error = provider_execution_error(task, SERPAPI_PROVIDER, SERPAPI_DETAILS_OPERATION,
                                     jurisdiction=str(item.get("jurisdiction") or ""), right_type=str(item.get("right_type") or ""))
    if error:
        raise ProviderError(error, "access_limited", "SerpApi patent detail is not enabled for this task")
    authorize_exact_plan_execution(task_dir, task, SERPAPI_PROVIDER, SERPAPI_DETAILS_OPERATION,
        query_id, jurisdiction=str(item.get("jurisdiction") or ""), right_type=str(item.get("right_type") or ""),
        query=str(item.get("q") or ""), request_params=_request_params(item))
    return task, item


def _normalize(payload: dict, item: dict, *, retrieval_workflow_revision: str | None = None) -> dict:
    publication = re.sub(r"[^A-Za-z0-9]", "", str(payload.get("publication_number") or "")).upper()
    requested = re.sub(r"[^A-Za-z0-9]", "", str(item.get("q") or "")).upper()
    if not publication or publication != requested:
        raise ProviderError("RESPONSE_IDENTITY_MISMATCH", "failed", "SerpApi detail publication number does not match the selected candidate")
    if retrieval_workflow_revision == "api-first-v3":
        expected_country = str(item.get("jurisdiction") or publication[:2]).upper()
        patent_id = str(item.get("patent_id") or "patent/" + publication + "/en")
        if publication[:2] != expected_country or patent_id.split("/")[1].upper() != publication:
            raise ProviderError("RESPONSE_IDENTITY_MISMATCH", "failed", "SerpApi detail identity or country differs from the planned document")
    claims = payload.get("claims")
    if claims is not None and (not isinstance(claims, list) or any(not isinstance(value, str) for value in claims)):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "SerpApi detail claims are not a string array")
    images = payload.get("images")
    if images is not None and not isinstance(images, list):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "SerpApi detail images are not an array")
    result = {"candidate_id": item["candidate_id"], "publication_number": publication,
            "jurisdiction": publication[:2], "right_type": item.get("right_type"),
            "title": str(payload.get("title") or ""), "abstract": str(payload.get("abstract") or ""),
            "claims": claims or [], "claims_translated": payload.get("claims_translated") if isinstance(payload.get("claims_translated"), list) else [],
            "description_link": str(payload.get("description_link") or ""),
            "description_link_translated": str(payload.get("description_link_translated") or ""),
            "pdf": str(payload.get("pdf") or ""), "images": images or [],
            "legal_events": payload.get("legal_events") if isinstance(payload.get("legal_events"), list) else [],
            "source_role": "published_document_content_only", "authoritative_for_final_rating": False,
            "satisfied_facts": [fact for fact, present in (("protection_content", bool(claims)), ("representative_figures", bool(images))) if present]}
    if retrieval_workflow_revision != "api-first-v3":
        return result
    payload = sanitize_for_evidence(payload)
    result.update(retrieval_workflow_revision=retrieval_workflow_revision,
                  source_role="api_record", source_index="google_patents",
                  source_upstream="google_patents", source_record_sha256=sha256_json(payload),
                  source_record_hash_stage="retained-v1", record_identity=publication,
                  source_updated_at=payload.get("source_updated_at") or payload.get("updated_at") or None)
    # Keep every relationship and event separate from the target document's status.
    for name in ("application_number", "country", "inventors", "assignees", "current_assignee", "current_owner", "current_status", "assignees_are_current", "priority_date",
                 "filing_date", "publication_date", "grant_date", "expiration_date", "family_id",
                 "events", "worldwide_applications", "parent_applications", "child_applications",
                 "priority_applications", "applications_claiming_priority", "description",
                 "description_translated", "claims_truncated", "images_truncated", "truncated",
                 "protection_content_truncated", "external_links"):
        if name in payload:
            result[name] = payload[name]
    status_rows = []
    worldwide = payload.get("worldwide_applications")
    for year, rows in (worldwide.items() if isinstance(worldwide, dict) else []):
        if not isinstance(rows, list):
            continue
        for position, row in enumerate(rows):
            if (isinstance(row, dict) and row.get("this_app") is True
                    and str(row.get("document_id") or "").split("/")[1:2] == [publication]
                    and str(row.get("country_code") or "").upper() == publication[:2]
                    and isinstance(row.get("legal_status"), str) and row["legal_status"].strip()):
                status_rows.append((row, "worldwide_applications." + str(year) + "." + str(position)))
    statuses = {row["legal_status"].strip() for row, _ in status_rows}
    if len(statuses) == 1:
        row, path = status_rows[0]
        result.update(legal_status=row["legal_status"], status=row["legal_status"],
                      status_detail={"status": row["legal_status"], "category": row.get("legal_status_cat"),
                                     "publication_number": publication, "jurisdiction": publication[:2],
                                     "source_field": path, "record_scope": "target_document"})
        result["satisfied_facts"].append("legal_status")
    elif len(statuses) > 1:
        result["source_status_conflict"] = sorted(statuses)
    result["field_provenance"] = {name: name for name in payload if name in result}
    if status_rows and len(statuses) == 1:
        result["field_provenance"]["legal_status"] = status_rows[0][1] + ".legal_status"
    if claims and payload.get("claims_truncated") is True:
        result["satisfied_facts"] = [fact for fact in result["satisfied_facts"] if fact != "protection_content"]
    # URLs describe available figures; only retained decoded bytes satisfy reading.
    result["satisfied_facts"] = [fact for fact in result["satisfied_facts"] if fact != "representative_figures"]
    return result


def _retained_media(evidence: dict, publication: str, task_dir: Path) -> dict:
    cached = {}
    for entry in evidence.get("collections", {}).get("patents", []):
        payload = entry.get("payload") if isinstance(entry, dict) else None
        if not isinstance(payload, dict) or payload.get("publication_number") != publication:
            continue
        for media in payload.get("media") if isinstance(payload.get("media"), list) else []:
            if not isinstance(media, dict) or not media.get("path") or not media.get("sha256") or not media.get("url"):
                continue
            path = Path(media["path"])
            try:
                if path_within(path.resolve(), task_dir.resolve()) and path.is_file() and sha256_file(path) == media["sha256"]:
                    cached[media["url"]] = dict(media)
            except (OSError, ValueError):
                continue
    return cached


def retain_figures(task_dir: Path, result: dict, item: dict, evidence: dict, config: dict) -> dict:
    """Fetch missing figures from the record's public Google storage links once."""
    if not isinstance(item.get("missing_facts"), list) or "representative_figures" not in item["missing_facts"]:
        return result
    images = result.get("images") if isinstance(result.get("images"), list) else []
    cache = _retained_media(evidence, result["publication_number"], task_dir)
    deadline = time.monotonic() + int(config.get("performance", {}).get("api_operation_timeout_seconds", 180))
    remaining = MAX_HTTP_RESPONSE_BYTES
    retained, gaps, seen = [], [], set()
    for position, image in enumerate(images):
        url = image if isinstance(image, str) else image.get("url") if isinstance(image, dict) else ""
        url = url if isinstance(url, str) else ""
        if url in seen:
            continue
        seen.add(url)
        try:
            parsed = urlparse(url or "")
            if (parsed.scheme != "https" or parsed.hostname != "patentimages.storage.googleapis.com"
                    or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or not re.search(r"\.(?:png|jpe?g|gif|webp|tiff?)$", parsed.path, re.I)):
                raise ProviderError("PATENT_FIGURE_URL_UNSUPPORTED", "access_limited", "Figure URL is outside the public Google Patents image store")
            if url in cache:
                retained.append({**cache[url], "reused": True})
                continue
            available = deadline - time.monotonic()
            if available <= 0 or remaining <= 0:
                raise ProviderError("PATENT_FIGURE_DOWNLOAD_BOUND", "access_limited", "Figure acquisition reached the existing operation or byte bound")
            _, headers, body = http_request(url, headers={"Accept": "image/*"}, timeout=max(1, min(30, int(available))), retries=0,
                                           max_response_bytes=remaining)
            remaining -= len(body)
            from PIL import Image
            try:
                with Image.open(io.BytesIO(body)) as picture:
                    width, height = picture.size
                    fmt = str(picture.format or "").upper()
                    picture.verify()
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
                raise ProviderError("PATENT_FIGURE_UNREADABLE", "failed", "Figure response is not a readable image") from exc
            extensions = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp", "TIFF": "tiff"}
            if fmt not in extensions or width <= 0 or height <= 0:
                raise ProviderError("PATENT_FIGURE_UNREADABLE", "failed", "Figure response has an unsupported image format")
            digest = hashlib.sha256(body).hexdigest()
            path = task_dir / "raw" / SERPAPI_PROVIDER / "media" / (digest + "." + extensions[fmt])
            atomic_write_bytes(path, body)
            retained.append({"url": url, "path": str(path), "sha256": digest, "bytes": len(body),
                             "width": width, "height": height, "mime_type": Image.MIME[fmt],
                             "publication_number": result["publication_number"], "source_field": "images[" + str(position) + "]", "reused": False})
        except (ProviderError, OSError, ValueError, ImportError) as exc:
            gaps.append({"source_field": "images[" + str(position) + "]", "url": str(url or ""),
                         "error_code": exc.code if isinstance(exc, ProviderError) else "PATENT_FIGURE_STORAGE_FAILED"})
    result["media"] = retained
    result["media_acquisition"] = {"requested": len(seen), "retained": len(retained), "gaps": gaps,
                                   "complete": bool(images) and not gaps and result.get("images_truncated") is not True}
    if retained:
        result["satisfied_facts"].append("representative_figures")
    return result


def authorize_detail_retry(task_dir, task, item, evidence, attempt_id, retry_reason):
    if attempt_id == "initial":
        return
    from recovery_stage_b import recovery_state
    state = recovery_state(task, evidence, SERPAPI_PROVIDER, item)
    if state and state.get("state") == "ready":
        return  # Exact original receipt and the bounded failure/repair review are current.
    if not state or state.get("state") != "result_available":
        raise ProviderError("API_RETRY_REVIEW_REQUIRED", "access_limited", "Review the original receipt and recovery conditions before retrying")
    # Scheduler claims may restore missing/changed raw evidence or an expired response.
    path = task_dir / "api-retry-claims.json"
    claims = load_json(path) if path.is_file() else {}
    claim = claims.get("attempts", {}).get(attempt_id, {})
    identity = {"provider": SERPAPI_PROVIDER, "query_id": item["query_id"],
                "plan_entry_sha256": sha256_json(item),
                "prior_source_run_id": claim.get("prior_source_run_id"), "retry_reason": retry_reason}
    previous = [run for run in evidence.get("source_runs", [])
                if run.get("provider") == SERPAPI_PROVIDER and run.get("query_id") == item["query_id"]
                and run.get("plan_entry_sha256") == sha256_json(item)]
    from recovery_stage_b import effective_submission
    if (claims.get("task_id") != task.get("task_id")
            or attempt_id != "repair-" + sha256_json(identity)[:24]
            or any(claim.get(key) != value for key, value in identity.items())
            or not previous or previous[-1].get("run_id") != identity["prior_source_run_id"]
            or any(effective_submission(evidence, run) == "unknown" for run in previous)):
        raise ProviderError("API_RETRY_REVIEW_REQUIRED", "access_limited", "No current exact receipt-repair claim is bound to this retry")
    from runtime_v24 import source_files_complete, source_fresh
    prior = previous[-1]
    justified = (retry_reason == "retained_evidence_missing_or_changed" and not source_files_complete(task_dir, evidence, prior)
                 or retry_reason == "dynamic_evidence_expired" and source_files_complete(task_dir, evidence, prior)
                 and not source_fresh(prior, dynamic_max_age_hours(task)))
    if not justified:
        raise ProviderError("API_RETRY_REVIEW_REQUIRED", "access_limited", "The claimed receipt-repair condition no longer applies")


def execute(task_dir: Path, query_id: str, *, attempt_id="initial", retry_reason="") -> dict:
    task_dir = task_dir.resolve()
    with budget_lock(task_dir):
        task, item = _item(task_dir, query_id)
        evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
        attempt = attempt_context(attempt_id, retry_reason)
        authorize_detail_retry(task_dir, task, item, evidence, attempt_id, retry_reason)
        maximum = int(task["serpapi_free_enhancement"]["max_queries_per_task"])
        if consumed_queries(evidence) >= maximum:
            raise ProviderError("SERPAPI_TASK_QUERY_LIMIT_REACHED", "access_limited", "Shared SerpApi task limit is exhausted")
        stop = persisted_quota_block_reason(evidence)
        if stop and attempt_id == "initial":
            raise ProviderError("FREE_QUOTA_EXHAUSTED", "access_limited", "A prior SerpApi quota stop is recorded: " + stop)
        config, base, key = settings()
        if not key:
            raise ProviderError("AUTH_FAILED", "access_limited", "SERPAPI_API_KEY is missing")
        timeout = int(config.get("http", {}).get("timeout_seconds", 30))
        account = {**attempt, **free_account_snapshot(base, key, timeout, **({"task": task} if account_capacity_enabled(task) else {}))}
        account.update(reserve_search("serpapi", key, base, remaining=account.get("searches_available", account["plan_searches_left"]), task_dir=task_dir,
                                      query_id=query_id, renewal_date=account.get("plan_renewal_date", ""),
                                      plan_entry_sha256=sha256_json(item), max_queries_per_task=maximum, **attempt))
        params = {"engine": "google_patents_details", "api_key": key, "output": "json", "patent_id": item["patent_id"]}
        request_params = _request_params(item)
        body = b""
        attempted = False
        try:
            attempted = True
            payload, headers, body = http_json(base + "/search.json?" + urlencode(params), timeout=timeout, retries=0)
            if payload.get("error"):
                raise ProviderError("PROVIDER_HTTP_ERROR", "failed", str(payload["error"]))
            normalized = _normalize(payload, item, retrieval_workflow_revision=task.get("retrieval_workflow_revision"))
            if task.get("retrieval_workflow_revision") == "api-first-v3":
                normalized = retain_figures(task_dir, normalized, item, evidence, config)
            return record_result(task_dir, provider=SERPAPI_PROVIDER, operation=SERPAPI_DETAILS_OPERATION,
                                 query=item["q"], jurisdiction=str(item.get("jurisdiction") or ""), evidence_type="patent",
                                 status="success", normalized=normalized, raw_body=body, raw_suffix="json", query_id=query_id,
                                 request_params=request_params,
                                 quota={**account, "network_request_attempted": True}, source_environment=("test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1" else "commercial_account_capacity" if account_capacity_enabled(task) else "commercial_freemium_free_plan"), authoritative_for_final_rating=False)
        except ProviderError as exc:
            return record_result(task_dir, provider=SERPAPI_PROVIDER, operation=SERPAPI_DETAILS_OPERATION,
                                 query=str(item.get("q") or ""), jurisdiction=str(item.get("jurisdiction") or ""), evidence_type="patent",
                                 status=exc.source_status, normalized=None, raw_body=body or None, raw_suffix="json", error_code=exc.code,
                                 detail=exc.detail, query_id=query_id, request_params=request_params,
                                 quota={**account, "network_request_attempted": attempted}, source_environment=("test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1" else "commercial_account_capacity" if account_capacity_enabled(task) else "commercial_freemium_free_plan"), authoritative_for_final_rating=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--attempt-id", default="initial")
    parser.add_argument("--retry-reason", default="")
    args = parser.parse_args()
    try:
        run = execute(args.task_dir, args.query_id, attempt_id=args.attempt_id, retry_reason=args.retry_reason)
        print(json.dumps({key: run.get(key) for key in ("status", "error_code", "query_id")}, ensure_ascii=False))
    except (ProviderError, OSError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()

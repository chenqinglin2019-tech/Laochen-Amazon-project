#!/usr/bin/env python3
"""EPO OPS OAuth, discovery, and candidate-detail client."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import os
import re
import time
import secrets
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from xml.etree import ElementTree

from common import (
    assert_provider_execution_allowed, credential, ensure_object, load_json,
    intrinsic_patent_right_type, load_skill_config,
    atomic_write_bytes, atomic_write_json, now_iso,
)
from epo_quota_ledger import EpoQuotaLedger
from provider_utils import (
    ProviderError, authorize_exact_plan_execution, enforce_task_limit, http_request,
    quota_summary, record_error, record_result,
    evidence_lock, MAX_HTTP_RESPONSE_BYTES,
)


_TOKEN_CACHE: dict[str, object] = {"access_token": "", "expires_at": 0.0}


def settings() -> tuple[dict, str, str, str, str]:
    config = load_skill_config()
    cfg = config["providers"]["epo_ops"]
    base = os.environ.get("EPO_OPS_BASE_URL", str(cfg["base_url"])).rstrip("/")
    auth = os.environ.get("EPO_OPS_AUTH_URL", str(cfg["auth_url"]))
    test_mode = os.environ.get("LC_IPR_TEST_MODE") == "1"
    if test_mode:
        for value, label in ((base, "EPO OPS base URL"), (auth, "EPO OPS auth URL")):
            parsed = urlparse(value)
            host = (parsed.hostname or "").casefold()
            if (
                parsed.scheme not in {"http", "https"}
                or host not in {"127.0.0.1", "localhost", "::1", "ops.epo.org"}
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
            ):
                raise ProviderError(
                    "EPO_TEST_ENDPOINT_NOT_LOCAL", "failed",
                    f"{label} test override must be loopback or the official OPS host",
                )
    else:
        for value, label in ((base, "EPO OPS base URL"), (auth, "EPO OPS auth URL")):
            parsed = urlparse(value)
            if parsed.scheme != "https" or (parsed.hostname or "").casefold() != "ops.epo.org":
                raise ProviderError(
                    "EPO_ENDPOINT_NOT_OFFICIAL", "failed",
                    f"{label} must use the official ops.epo.org HTTPS service",
                )
    return config, base, auth, credential(config, "epo_consumer_key"), credential(config, "epo_consumer_secret")


def source_profile() -> tuple[str, bool]:
    """Classify official Production traffic separately from local fixtures."""
    settings()  # also enforces official endpoints outside explicit test mode
    if os.environ.get("LC_IPR_TEST_MODE") == "1":
        return "test_fixture", False
    return "production", True


def classify_ops_failure(exc: ProviderError, operation: str) -> tuple[ProviderError, str]:
    """Classify OPS errors from the actual request stage and fault envelope.

    A received data-endpoint fault establishes delivery, but does not establish
    a successful search.  OAuth errors occur before a search request and stay
    ``not_submitted``.  This intentionally avoids treating generic HTTP 404s
    (detail lookups, gateways, and bad pagination) as search zeroes.
    """
    if exc.code == "AUTH_FAILED" and exc.request_stage != "data":
        return exc, "not_submitted"
    if operation == "search" and exc.http_status and exc.response_body:
        code, message = ops_fault(exc.response_body)
        if code == "SERVER.EntityNotFound" and message.casefold() == "no results found" and exc.http_status == 404:
            return ProviderError("EPO_SEARCH_NO_RESULTS", "no_result", "EPO OPS search explicitly returned no results",
                                 exc.http_status, exc.response_body, exc.response_headers, exc.request_stage), "submitted"
        if code.startswith("CLIENT.") and re.fullmatch(
                r"CLIENT\.(?:MinimumCharsBeforeTruncation|InvalidQuery|QuerySyntax)[A-Za-z0-9_.-]*", code, re.I):
            return ProviderError("EPO_QUERY_SYNTAX_REJECTED", "failed", exc.detail,
                                 exc.http_status, exc.response_body, exc.response_headers, exc.request_stage), "submitted"
    if exc.request_stage == "oauth":
        return exc, "not_submitted"
    if exc.code in {"FREE_QUOTA_EXHAUSTED", "EPO_TASK_HTTP_LEDGER_INVALID"}:
        return exc, "not_submitted"
    if exc.http_status and (exc.request_stage == "data" or exc.response_body):
        return exc, "submitted"
    return exc, "unknown"


def ops_fault(xml_bytes: bytes) -> tuple[str, str]:
    """Return a namespaced OPS fault code/message without accepting lookalikes."""
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return "", ""
    fault = root if root.tag.rsplit("}", 1)[-1] == "fault" else root.find(".//{*}fault")
    if fault is None:
        return "", ""
    code = " ".join((fault.findtext("{*}code") or "").split())
    message = " ".join((fault.findtext("{*}message") or "").split())
    return code, message


def _with_stage(exc: ProviderError, stage: str) -> ProviderError:
    return ProviderError(exc.code, exc.source_status, exc.detail, exc.http_status,
                         exc.response_body, exc.response_headers, stage)


def response_receipt(exc: ProviderError, stage: str) -> dict:
    """Persist only non-secret transport facts alongside the raw, hashed body."""
    return {
        "request_stage": stage,
        "http_status": exc.http_status or None,
        "response_received": bool(exc.http_status or exc.response_body),
        "headers": exc.response_headers or {},
    }


def access_token(force_refresh: bool = False) -> tuple[str, dict[str, str]]:
    cached = str(_TOKEN_CACHE.get("access_token") or "")
    if not force_refresh and cached and float(_TOKEN_CACHE.get("expires_at") or 0) > time.time():
        return cached, {}
    config, _, auth_url, key, secret = settings()
    if not key or not secret:
        raise ProviderError("AUTH_FAILED", "access_limited", "EPO OPS credentials are missing")
    basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
    status, headers, body = http_request(
        auth_url, method="POST", headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data=urlencode({"grant_type": "client_credentials"}).encode(),
        timeout=int(config["http"]["timeout_seconds"]), retries=int(config["http"]["retries"]),
    )
    del status
    import json
    try:
        payload = json.loads(body.decode())
        token = payload["access_token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO OAuth response has no access_token") from exc
    expires_in = max(int(payload.get("expires_in", 300)), 1)
    _TOKEN_CACHE.update({"access_token": str(token), "expires_at": time.time() + max(expires_in - 30, 1)})
    return str(token), headers


def ops_get(path: str, range_header: str = "", *, accept: str = "application/exchange+xml",
            task_request: dict | None = None) -> tuple[bytes, dict[str, str]]:
    config, base, _, consumer_key, _ = settings()
    try:
        token, _ = access_token()
    except ProviderError as exc:
        raise _with_stage(exc, "oauth") from None
    url = f"{base}/{path.lstrip('/')}"
    ledger = EpoQuotaLedger(config, consumer_key)

    def request_once(access_value: str) -> tuple[bytes, dict[str, str]]:
        request_headers = {
            "Authorization": f"Bearer {access_value}",
            "Accept": accept,
        }
        if range_header:
            request_headers["X-OPS-Range"] = range_header
        if task_request is not None:
            enforce_task_limit(task_request["task_dir"], "epo_ops", "candidate_detail", task_request["maximum"])
        reservation = ledger.reserve(path)
        if task_request is not None:
            # Reserve each data request atomically before HTTP. An interrupted
            # metadata/page request stays counted even without a final run.
            try:
                with evidence_lock(task_request["task_dir"]):
                    enforce_task_limit(task_request["task_dir"], "epo_ops", "candidate_detail", task_request["maximum"])
                    trace_path = task_request["task_dir"] / "epo-data-http-attempts.json"
                    trace = load_json(trace_path) if trace_path.is_file() else {"task_id":task_request["task_id"], "attempts":[]}
                    request_id = "OPS-HTTP-" + secrets.token_hex(16)
                    trace["attempts"].append({"request_id":request_id, "query_id":task_request["query_id"],
                        "path":path, "accept":accept, "range":range_header, "reserved_at":now_iso(),
                        "submission_state":"unknown"})
                    atomic_write_json(trace_path, trace)
                    task_request["trace_ids"].append(request_id)
            except (ProviderError, OSError, ValueError):
                ledger.settle(reservation, error_code="PRE_NETWORK_TASK_RESERVATION_FAILED")
                raise
        try:
            _, response_headers, response_body = http_request(
                url,
                headers=request_headers,
                timeout=int(config["http"]["timeout_seconds"]),
                # Each quota-bearing HTTP attempt needs its own persisted
                # reservation. Do not hide retries inside http_request.
                retries=0,
                max_response_bytes=(min(MAX_HTTP_RESPONSE_BYTES, int(config["providers"]["epo_ops"]["estimated_max_response_bytes_per_query"]))
                                    if task_request is not None else MAX_HTTP_RESPONSE_BYTES),
            )
        except ProviderError as exc:
            try:
                ledger.settle(reservation, error_code=exc.code)
            except ProviderError as quota_error:
                raise quota_error from None
            raise _with_stage(exc, "data") from None
        ledger.settle(
            reservation,
            headers=response_headers,
            response_bytes=len(response_body),
        )
        if task_request is not None:
            task_request["received_count"] = task_request.get("received_count", 0) + 1
        return response_body, response_headers

    try:
        return request_once(token)
    except ProviderError as exc:
        if exc.code != "AUTH_FAILED":
            raise
    try:
        fresh, _ = access_token(force_refresh=True)
    except ProviderError as exc:
        raise _with_stage(exc, "oauth") from None
    return request_once(fresh)


def normalize_search(xml_bytes: bytes, *, include_biblio: bool = False, retrieval_workflow_revision: str | None = None) -> list[dict]:
    """Accept only a documented search envelope or the exact OPS empty fault."""
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO OPS response is invalid XML") from exc
    code, message = ops_fault(xml_bytes)
    if code == "SERVER.EntityNotFound" and message.casefold() == "no results found":
        return []
    search = next(iter(root.findall(".//{*}biblio-search") + root.findall(".//{*}bibliographic-search")), None)
    if search is None and root.tag.rsplit("}", 1)[-1] in {"biblio-search", "bibliographic-search"}:
        search = root
    scope = search if search is not None else root
    candidates = []
    docs = scope.findall(".//{*}exchange-document")
    if docs:
        identities = [(d.attrib.get("country", ""), d.attrib.get("doc-number", ""), d.attrib.get("kind", "")) for d in docs]
    else:
        identities = [((d.findtext("{*}country") or "").strip(), (d.findtext("{*}doc-number") or "").strip(), (d.findtext("{*}kind") or "").strip()) for d in scope.findall(".//{*}publication-reference/{*}document-id") if d.attrib.get("document-id-type", "docdb") == "docdb"]
    for index, (country, number, kind) in enumerate(identities):
        if not re.fullmatch(r"[A-Z]{2}", country) or not number or not kind:
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO search result has an incomplete publication identity")
        candidate = {
            "publication_number": f"{country}{number}{kind}", "jurisdiction": country,
            "kind_code": kind, "source": "epo_ops", "material": False,
            "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
        }
        if include_biblio and docs:
            candidate.update(_bibliographic_fields(docs[index]))
        if retrieval_workflow_revision == "api-first-v3":
            candidate.pop("owners", None)
            candidate.update(retrieval_workflow_revision=retrieval_workflow_revision,
                             field_provenance={"applicants": "applicant-name/name"},
                             api_fact_exclusions=["rights_holder", "current_status", "territory"])
        candidates.append(candidate)
    if not candidates:
        total = str(search.attrib.get("total-result-count", "")) if search is not None else ""
        result = scope.find("{*}search-result")
        if total != "0" or result is None or len(result):
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO response does not prove an explicit, schema-valid zero-result search")
    return list({item["publication_number"]: item for item in candidates}.values())


def search_response(xml_bytes: bytes, requested_range: str = "1-25", *, include_biblio: bool = False, require_range: bool = False, retrieval_workflow_revision: str | None = None) -> dict:
    candidates = normalize_search(xml_bytes, include_biblio=include_biblio, retrieval_workflow_revision=retrieval_workflow_revision)
    root = ElementTree.fromstring(xml_bytes)
    code, message = ops_fault(xml_bytes)
    if code == "SERVER.EntityNotFound" and message.casefold() == "no results found":
        match = re.fullmatch(r"(\d+)-(\d+)", requested_range)
        if not match or int(match[1]) < 1 or int(match[2]) < int(match[1]) or int(match[2]) - int(match[1]) >= 100:
            raise ProviderError("INVALID_SEARCH_RANGE", "failed", "EPO search range must identify 1 to 100 ordered records")
        return {"candidates": candidates, "search_metadata": {
            "total_hits": 0, "retrieved_hits": 0, "reviewed_hits": None,
            "truncated": False, "stop_reason": "query_exhausted", "source_updated_at": None,
            "schema_valid": True, "range_start": int(match[1]), "range_end": int(match[2]),
            "range_verified": False, "empty_fault_receipt": True,
        }}
    search = next(iter(root.findall(".//{*}biblio-search") + root.findall(".//{*}bibliographic-search")), None)
    if root.tag.rsplit("}", 1)[-1] in {"biblio-search", "bibliographic-search"}:
        search = root
    raw_total = search.attrib.get("total-result-count", "") if search is not None else ""
    if search is None or not str(raw_total).isdigit():
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO search response lacks the documented search envelope and total-result-count")
    total = int(raw_total)
    if total < len(candidates):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO total-result-count contradicts the retrieved records")
    match = re.fullmatch(r"(\d+)-(\d+)", requested_range)
    if not match or int(match[1]) < 1 or int(match[2]) < int(match[1]) or int(match[2]) - int(match[1]) >= 100:
        raise ProviderError("INVALID_SEARCH_RANGE", "failed", "EPO search range must identify 1 to 100 ordered records")
    start, end = int(match[1]), int(match[2])
    returned_range = search.find("{*}range")
    range_verified = False
    if returned_range is not None and total:
        begin_value, end_value = returned_range.attrib.get("begin", ""), returned_range.attrib.get("end", "")
        if not begin_value.isdigit() or not end_value.isdigit() or int(begin_value) != start or int(end_value) not in {end, min(end, total)}:
            raise ProviderError("RESPONSE_RANGE_MISMATCH", "failed", "EPO search response range does not match the requested page")
        range_verified = True
    if total and require_range and not range_verified:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO search response lacks the documented range needed to verify pagination")
    truncated = total is None or start > 1 or total > len(candidates)
    return {"candidates": candidates, "search_metadata": {
        "total_hits": total, "retrieved_hits": len(candidates), "reviewed_hits": None,
        "truncated": truncated, "stop_reason": "total_unknown" if total is None else "page_limit" if truncated else "query_exhausted",
        "source_updated_at": None, "schema_valid": True, "range_start": start, "range_end": end, "range_verified": range_verified,
    }}


def _unique_text(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _node_text(node: ElementTree.Element) -> str:
    return re.sub(r"\s+", " ", " ".join(
        str(value).strip() for value in node.itertext() if str(value).strip()
    )).strip()


def _document_value(node: ElementTree.Element) -> str:
    country = (node.findtext("{*}country") or "").strip()
    number = (node.findtext("{*}doc-number") or "").strip()
    kind = (node.findtext("{*}kind") or "").strip()
    return re.sub(r"[^A-Za-z0-9]", "", f"{country}{number}{kind}").upper() if number else ""


def _document_stem(value: str) -> tuple[str, str]:
    normalized = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    match = re.fullmatch(r"([A-Z]{2})((?:D|RE|PP)?\d+)(?:[A-Z]\d?)?", normalized)
    return (match.group(1), match.group(2)) if match else ("", normalized)


def _reference_values(root: ElementTree.Element, reference: str) -> list[str]:
    return _unique_text([
        _document_value(node)
        for node in root.findall(f".//{{*}}{reference}/{{*}}document-id")
    ])


def _classification_symbol(node: ElementTree.Element) -> str:
    """Extract only the symbol, excluding IPC version and classification metadata."""
    parts = [str(node.findtext("{*}" + key) or "").strip() for key in ("section", "class", "subclass", "main-group", "subgroup")]
    if all(parts):
        return "".join(parts[:4]) + "/" + parts[4]
    raw = _node_text(node)
    match = re.match(r"([A-HY]\s*\d{2}\s*[A-Z]\s*\d+\s*/\s*\d+)", raw.upper())
    return re.sub(r"\s+", "", match[1]) if match else ""


def _bibliographic_fields(root: ElementTree.Element) -> dict:
    """Keep one publication's discovery fields together; none proves present effect."""
    result: dict[str, object] = {}
    titles = _unique_text([_node_text(node) for node in root.findall(".//{*}invention-title")])
    abstracts = _unique_text([_node_text(node) for node in root.findall(".//{*}abstract")])
    applicants = _unique_text([_node_text(node) for node in root.findall(".//{*}applicant-name/{*}name")])
    ipc = _unique_text([_classification_symbol(node) for node in root.findall(".//{*}classification-ipcr") + root.findall(".//{*}classification-ipc/{*}main-classification") + root.findall(".//{*}classification-ipc/{*}further-classification")])
    cpc = []
    for node in root.findall(".//{*}patent-classification"):
        scheme = node.find("{*}classification-scheme")
        values = [node.attrib.get("scheme", "")]
        if scheme is not None:
            values.extend([scheme.attrib.get("scheme", ""), scheme.attrib.get("scheme-type", ""), _node_text(scheme)])
        if "CPC" in " ".join(values).upper():
            cpc.append(_classification_symbol(node))
    cpc = _unique_text(cpc)
    if titles:
        result.update(title=titles[0], titles=titles)
    if abstracts:
        result.update(abstract=abstracts[0], abstracts=abstracts)
    if applicants:
        result.update(owners=applicants, applicants=applicants)
    if ipc or cpc:
        result.update(ipc_classes=ipc, cpc_classes=cpc, classifications=_unique_text([*ipc, *cpc]))
    for tag, key in (("publication-reference", "publication_numbers"), ("application-reference", "application_numbers"), ("priority-claim", "priority_numbers")):
        values = _reference_values(root, tag)
        if values:
            result[key] = values
    if result.get("application_numbers"):
        result["application_number"] = result["application_numbers"][0]
    if root.attrib.get("family-id"):
        result["family_id"] = root.attrib["family-id"]
    return result


def search_path(query: str, schema_version: str) -> str:
    # OPS v3.2 Reference Guide, table 19: constituents may be comma separated.
    constituent = "/biblio,abstract" if schema_version == "2.4-free" else ""
    return f"published-data/search{constituent}?{urlencode({'q': query})}"


def normalize_detail(
    operation: str, document: str, body: bytes, *, right_type: str = "patent",
    candidate_id: str = "", retrieval_workflow_revision: str | None = None,
) -> dict:
    """Normalize one bounded EPO detail endpoint into a mergeable candidate."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", f"EPO {operation} response is invalid XML") from exc
    identifiers = _unique_text([
        _document_value(node) for node in root.findall(".//{*}document-id")
    ])
    if retrieval_workflow_revision == "api-first-v3":
        for node in root.iter():
            if all(node.attrib.get(key) for key in ("country", "doc-number", "kind")):
                identifiers.append(re.sub(r"[^A-Za-z0-9]", "", node.attrib["country"] + node.attrib["doc-number"] + node.attrib["kind"]).upper())
        identifiers = _unique_text(identifiers)
        if not identifiers:
            raise ProviderError("RESPONSE_IDENTITY_MISMATCH", "failed", "EPO API detail did not return a document identity")
    publication_numbers = _reference_values(root, "publication-reference")
    application_numbers = _reference_values(root, "application-reference")
    priority_numbers = _reference_values(root, "priority-claim")
    titles = _unique_text([
        _node_text(node) for node in root.findall(".//{*}invention-title")
    ])
    applicants = _unique_text([
        _node_text(node) for node in root.findall(".//{*}applicant-name/{*}name")
    ])
    ipc_classes = _unique_text([
        _node_text(node) for node in root.findall(".//{*}classification-ipcr")
    ])
    cpc_classes: list[str] = []
    for node in root.findall(".//{*}patent-classification"):
        scheme = node.find("{*}classification-scheme")
        scheme_name = " ".join((scheme.attrib.get("office", ""), _node_text(scheme))).upper() if scheme is not None else ""
        if "CPC" in scheme_name:
            cpc_classes.append(_node_text(node))
    cpc_classes = _unique_text(cpc_classes)
    family_ids = _unique_text([
        str(node.attrib.get("family-id") or "").strip()
        for node in root.findall(".//{*}family-member")
    ])
    legal_events: list[dict[str, str]] = []
    for event in root.findall(".//{*}legal-event")[:50]:
        legal_events.append({
            "code": event.attrib.get("code", ""),
            "date": event.attrib.get("date", ""),
            "description": str(event.attrib.get("desc") or _node_text(event))[:500],
        })
    if not any((identifiers, titles, applicants, ipc_classes, cpc_classes, family_ids, legal_events)):
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", f"EPO {operation} detail contains no interpretable patent record")

    requested_stem = _document_stem(document)
    returned_stems = {_document_stem(value) for value in identifiers}
    if identifiers and requested_stem not in returned_stems:
        raise ProviderError(
            "RESPONSE_IDENTITY_MISMATCH", "failed",
            f"EPO {operation} response identifiers do not match the requested document",
        )

    publication_number = re.sub(r"[^A-Za-z0-9]", "", document).upper()
    document_country = _document_stem(publication_number)[0]
    candidate: dict[str, object] = {
        "publication_number": publication_number,
        "jurisdiction": document_country,
        "right_type": intrinsic_patent_right_type(
            document_country, publication_number,
        ) or right_type,
        "source": "epo_ops",
        "material": False,
        "detail_operations": [operation],
        "identifiers": identifiers,
    }
    if candidate_id:
        candidate["candidate_id"] = candidate_id
    if titles:
        candidate.update({"title": titles[0], "titles": titles})
    if applicants:
        candidate.update({"owners": applicants, "applicants": applicants})
    if publication_numbers:
        candidate["publication_numbers"] = publication_numbers
    if application_numbers:
        candidate.update({
            "application_number": application_numbers[0],
            "application_numbers": application_numbers,
        })
    if priority_numbers:
        candidate["priority_numbers"] = priority_numbers
    if ipc_classes or cpc_classes:
        candidate.update({
            "classifications": _unique_text([*ipc_classes, *cpc_classes]),
            "ipc_classes": ipc_classes,
            "cpc_classes": cpc_classes,
        })
    if family_ids:
        candidate["family_id"] = family_ids[0]
    if operation == "family":
        candidate["family_members"] = publication_numbers or identifiers
    if legal_events:
        candidate["legal_events"] = legal_events
    if retrieval_workflow_revision == "api-first-v3":
        candidate.pop("owners", None)
        candidate.update(retrieval_workflow_revision=retrieval_workflow_revision,
                         field_provenance={"applicants": "applicant-name/name", "legal_events": "legal-event"},
                         api_fact_exclusions=["rights_holder", "current_status", "territory"],
                         record_scope="family" if operation == "family" else "target_record",
                         source_updated_at=None)
        if operation == "family":
            candidate["family_applicants"] = candidate.pop("applicants", [])
            candidate["api_fact_exclusions"].extend(["protection_content", "representative_figures"])
        elif publication_number in identifiers:
            scopes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"exchange-document", "fulltext-document"}
                      and re.sub(r"[^A-Za-z0-9]", "", str(node.attrib.get("country", "")) + str(node.attrib.get("doc-number", "")) + str(node.attrib.get("kind", ""))).upper() == publication_number]
            claim_scope = scopes[0] if len(scopes) == 1 else root if set(identifiers) == {publication_number} else None
            claims = _unique_text([_node_text(node) for node in claim_scope.findall(".//{*}claim")]) if claim_scope is not None else []
            if claims:
                candidate["claims"] = claims
                candidate["field_provenance"]["claims"] = "claim"
    return {"detail_operation": operation, "candidates": [candidate]}


def retrieve_images(task_dir: Path, document: str, *, right_type: str, candidate_id: str,
                    task_request: dict) -> tuple[bytes, dict, dict]:
    """Read availability, then one full-resolution drawing page from its link.

    OPS v3.2 section 3.1.3: availability is XML; the media Accept and single
    page range are declared by that response. No guessed kind or image URL.
    """
    body, headers = ops_get("published-data/publication/epodoc/" + quote(document) + "/images",
                            accept="application/ops+xml", task_request=task_request)
    digest = hashlib.sha256(body).hexdigest()
    inquiry_path = task_dir / "raw" / "epo_ops" / "images" / (digest + ".xml")
    atomic_write_bytes(inquiry_path, body)
    task_request["image_inquiry"] = {"path":str(inquiry_path), "sha256":digest, "bytes":len(body)}
    normalized = normalize_detail("images", document, body, right_type=right_type,
        candidate_id=candidate_id, retrieval_workflow_revision="api-first-v3")
    root = ElementTree.fromstring(body)
    target = re.sub(r"[^A-Za-z0-9]", "", document).upper()
    aliases = {target}
    if re.fullmatch(r"USD\d+S", target):
        aliases.add(target + "1")
    returned = set(normalized["candidates"][0]["identifiers"])
    if not aliases & returned:
        raise ProviderError("RESPONSE_IDENTITY_MISMATCH", "failed", "OPS image inquiry did not identify the exact publication")
    choices = []
    for instance in root.findall(".//{*}document-instance"):
        link = str(instance.attrib.get("link") or "")
        match = re.fullmatch(r"(?:published-data/images/)?([A-Z]{2})/([A-Z0-9]+)/([A-Z]\d?)/fullimage", link)
        if not match or "".join(match.groups()).upper() not in aliases:
            continue
        pages = str(instance.attrib.get("number-of-pages") or "")
        if not pages.isdigit() or int(pages) < 1:
            continue
        starts = [int(section.attrib["start-page"]) for section in instance.findall(".//{*}document-section")
                  if section.attrib.get("name", "").upper() == "DRAWINGS"
                  and str(section.attrib.get("start-page") or "").isdigit()]
        page = min(starts) if starts else 1
        if page < 1 or page > int(pages):
            continue
        formats = [(node.text or "").strip().lower() for node in instance.findall(".//{*}document-format")]
        media_format = next((value for value in ("application/tiff", "image/tiff", "image/png", "image/jpeg", "application/pdf") if value in formats), None)
        if media_format:
            path = "published-data/images/" + link.removeprefix("published-data/images/")
            choices.append((not bool(starts), path, page, media_format, int(pages)))
    record = normalized["candidates"][0]
    record.update(images=[], media=[], documents=[], media_acquisition={"requested":1, "retained":0, "complete":False, "gaps":[]})
    if not choices:
        record["media_acquisition"]["gaps"].append({"error_code":"EPO_IMAGE_FULL_PAGE_UNAVAILABLE",
            "reason":"No same-record fullimage resource with a supported declared format"})
        return body, headers, normalized
    _, path, page, media_format, total_pages = sorted(choices)[0]
    page_body, page_headers = ops_get(path, str(page), accept=media_format, task_request=task_request)
    page_digest = hashlib.sha256(page_body).hexdigest()
    artifact = {"sha256":page_digest, "bytes":len(page_body), "publication_number":target,
                "page_number":page, "source_path":path, "source_field":"document-instance/fullimage",
                "mime_type":media_format, "is_thumbnail":False}
    if media_format == "application/pdf":
        if not page_body.startswith(b"%PDF-"):
            raise ProviderError("EPO_IMAGE_RESPONSE_UNREADABLE", "failed", "OPS PDF page response is not PDF")
        artifact_path = inquiry_path.parent / (page_digest + ".pdf")
        artifact["path"] = str(artifact_path)
        atomic_write_bytes(artifact_path, page_body)
        record["documents"].append(artifact)
        record["media_acquisition"]["gaps"].append({"error_code":"EPO_PDF_PAGE_REQUIRES_READING",
            "reason":"PDF page retained; no raster drawing comparison is claimed"})
    else:
        from PIL import Image
        try:
            with Image.open(io.BytesIO(page_body)) as picture:
                width, height = picture.size
                picture_format = str(picture.format or "").upper()
                picture.verify()
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            raise ProviderError("EPO_IMAGE_RESPONSE_UNREADABLE", "failed", "OPS media is not a readable image") from exc
        extensions = {"TIFF":"tiff", "PNG":"png", "JPEG":"jpg"}
        if picture_format not in extensions or width <= 0 or height <= 0:
            raise ProviderError("EPO_IMAGE_RESPONSE_UNREADABLE", "failed", "OPS media format or dimensions are invalid")
        artifact_path = inquiry_path.parent / (page_digest + "." + extensions[picture_format])
        artifact.update(path=str(artifact_path), width=width, height=height, mime_type=Image.MIME[picture_format])
        atomic_write_bytes(artifact_path, page_body)
        record["images"].append(artifact)
        record["media"].append(artifact)
        record["media_acquisition"]["retained"] = 1
    record["media_acquisition"].update(available_document_pages=total_pages, acquired_page_numbers=[page],
        limitation="Only this full-resolution page was retrieved; all design views/claimed contours still require comparison.")
    record.setdefault("field_provenance", {})["media"] = "document-instance/fullimage; X-OPS-Range=" + str(page)
    return body, {**headers, **page_headers}, normalized


def probe() -> dict:
    token, headers = access_token(force_refresh=True)
    environment, authoritative = source_profile()
    return {
        "ready": bool(token), "quota": quota_summary(headers),
        "mode": "oauth_client_credentials", "environment": environment,
        "authoritative_for_final_rating": authoritative,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Query EPO OPS.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--operation", choices=["search", "biblio", "family", "fulltext", "images", "legal"], default="search")
    parser.add_argument("--query", required=True)
    parser.add_argument("--jurisdiction", default="")
    parser.add_argument("--right-type", choices=("patent", "utility_model", "design"), default="patent")
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--range", default="1-25")
    args = parser.parse_args()
    task = ensure_object(load_json(args.task_dir.resolve() / "task.json"), "task.json")
    revision = task.get("epo_query_revision")
    if revision and args.operation == "search":
        try:
            from epo_query import REVISION, validate_compiled_query
            if revision != REVISION:
                raise ValueError("EPO_QUERY_REVISION_INVALID")
            validate_compiled_query(args.query)
        except ValueError as exc:
            error_value = ProviderError(str(exc), "failed", str(exc))
            request_params = {"q": args.query, "range": args.range, "right_type": args.right_type,
                              "query_compiler_revision": revision}
            run = record_error(args.task_dir.resolve(), provider="epo_ops", operation="search",
                query=args.query, jurisdiction=args.jurisdiction, evidence_type="patent",
                error_value=error_value, request_params=request_params,
                query_id=args.query_id, submission_state="not_submitted")
            print(run["status"])
            return
    recorded_operation = "search" if args.operation == "search" else "candidate_detail"
    try:
        assert_provider_execution_allowed(
            task, "epo_ops", recorded_operation, jurisdiction=args.jurisdiction,
            right_type=args.right_type,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    operation_paths = {
        "search": search_path(args.query, str(task.get("schema_version") or "")),
        "biblio": f"published-data/publication/epodoc/{quote(args.query)}/biblio",
        "family": f"family/publication/epodoc/{quote(args.query)}/biblio",
        "fulltext": f"published-data/publication/epodoc/{quote(args.query)}/fulltext",
        "images": f"published-data/images/epodoc/{quote(args.query)}/fullimage",
        "legal": f"published-data/publication/epodoc/{quote(args.query)}/legal",
    }
    request_params = (
        {"q": args.query, "range": args.range, "right_type": args.right_type,
         **({"query_compiler_revision": revision} if revision else {})}
        if args.operation == "search" else {
            "q": args.query, "document": args.query, "detail_operation": args.operation,
            "candidate_id": args.candidate_id, "right_type": args.right_type,
        }
    )
    try:
        authorize_exact_plan_execution(
            args.task_dir.resolve(), task, "epo_ops", recorded_operation, args.query_id,
            jurisdiction=args.jurisdiction, right_type=args.right_type,
            query=args.query, request_params=request_params,
        )
    except ProviderError as exc:
        # The request has not reached OPS when immutable-plan validation fails.
        # Record that fact instead of letting the generic runner classify it as
        # an indeterminate external submission.
        run = record_error(
            args.task_dir.resolve(), provider="epo_ops", operation=recorded_operation,
            query=args.query, jurisdiction=args.jurisdiction, evidence_type="patent",
            error_value=exc, request_params=request_params, query_id=args.query_id,
            submission_state="not_submitted",
        )
        print(run["status"])
        return
    source_environment = "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1" else "production"
    authoritative_for_final_rating = False
    task_request = None
    try:
        source_environment, authoritative_for_final_rating = source_profile()
        config, _, _, _, _ = settings()
        if args.operation == "search":
            current_task = load_json(args.task_dir.resolve() / "task.json")
            limit_key = "epo_search_queries_per_task_v24" if current_task.get("schema_version") == "2.4-free" else "epo_search_queries_per_task"
            enforce_task_limit(args.task_dir.resolve(), "epo_ops", "search", int(config["limits"].get(limit_key, 96 if limit_key.endswith("v24") else 6)))
        else:
            enforce_task_limit(args.task_dir.resolve(), "epo_ops", "candidate_detail", int(config["limits"]["epo_candidate_detail_limit"]))
            if task.get("retrieval_workflow_revision") == "api-first-v3":
                task_request = {"task_dir":args.task_dir.resolve(), "task_id":task["task_id"],
                    "query_id":args.query_id, "maximum":int(config["limits"]["epo_candidate_detail_limit"]),
                    "trace_ids":[], "received_count":0}
        if args.operation == "images" and task_request is not None:
            body, headers, normalized = retrieve_images(args.task_dir.resolve(), args.query,
                right_type=args.right_type, candidate_id=args.candidate_id, task_request=task_request)
        else:
            kwargs = {"task_request":task_request} if task_request is not None else {}
            body, headers = ops_get(operation_paths[args.operation], args.range if args.operation == "search" else "", **kwargs)
            normalized = search_response(body, args.range, include_biblio=task.get("schema_version") == "2.4-free", require_range=task.get("schema_version") == "2.4-free", retrieval_workflow_revision=task.get("retrieval_workflow_revision")) if args.operation == "search" else normalize_detail(
                args.operation, args.query, body,
                right_type=args.right_type, candidate_id=args.candidate_id, retrieval_workflow_revision=task.get("retrieval_workflow_revision"),
            )
        if isinstance(normalized, list):
            for item in normalized:
                if isinstance(item, dict):
                    item["source_environment"] = source_environment
                    item["authoritative_for_final_rating"] = authoritative_for_final_rating
        elif isinstance(normalized, dict):
            normalized["source_environment"] = source_environment
            normalized["authoritative_for_final_rating"] = authoritative_for_final_rating
            for item in normalized.get("candidates", []):
                if isinstance(item, dict):
                    item["source_environment"] = source_environment
                    item["authoritative_for_final_rating"] = authoritative_for_final_rating
        status = "success" if (
            normalized if isinstance(normalized, list) else normalized.get("candidates")
        ) else "no_result"
        run = record_result(args.task_dir.resolve(), provider="epo_ops", operation=recorded_operation, query=args.query,
            jurisdiction=args.jurisdiction, evidence_type="patent", status=status, normalized=normalized,
            raw_body=body, raw_suffix="xml", quota=quota_summary(headers),
            request_params=request_params, query_id=args.query_id, source_environment=source_environment,
            authoritative_for_final_rating=authoritative_for_final_rating,
            response_receipt=({"request_stage":"data", "response_received":True,
                "ops_http_trace_ids":task_request["trace_ids"], "data_http_requests":len(task_request["trace_ids"]),
                "data_response_count":task_request["received_count"]} if task_request is not None else None))
        print(run["status"])
    except ProviderError as exc:
        exc, submission_state = classify_ops_failure(exc, args.operation)
        if (task_request is not None and task_request["received_count"]
                and exc.code != "PROVIDER_TIMEOUT" and exc.request_stage != "oauth"):
            submission_state = "submitted"
        receipt = response_receipt(exc, exc.request_stage or ("data" if submission_state == "submitted" else ""))
        if task_request is not None:
            receipt.update(ops_http_trace_ids=task_request["trace_ids"], data_http_requests=len(task_request["trace_ids"]),
                data_response_count=task_request["received_count"])
            receipt["response_received"] = receipt["response_received"] or bool(task_request["received_count"])
            if task_request.get("image_inquiry"):
                receipt["image_inquiry"] = task_request["image_inquiry"]
        if args.operation == "search" and exc.code == "EPO_SEARCH_NO_RESULTS":
            # OPS uses a fault envelope rather than a biblio-search envelope
            # for some genuine zero-result searches.  Preserve the raw XML and
            # normalize it through the same search-response schema as a 200.
            normalized = search_response(exc.response_body, args.range,
                include_biblio=task.get("schema_version") == "2.4-free",
                require_range=task.get("schema_version") == "2.4-free")
            run = record_result(args.task_dir.resolve(), provider="epo_ops", operation=recorded_operation,
                query=args.query, jurisdiction=args.jurisdiction, evidence_type="patent", status="no_result",
                normalized=normalized, raw_body=exc.response_body, raw_suffix="xml", quota={},
                request_params=request_params, query_id=args.query_id, source_environment=source_environment,
                authoritative_for_final_rating=authoritative_for_final_rating,
                submission_state=submission_state, execution_phase="data", response_receipt=receipt)
            print(run["status"])
            return
        run = record_error(args.task_dir.resolve(), provider="epo_ops", operation=recorded_operation, query=args.query,
            jurisdiction=args.jurisdiction, evidence_type="patent", error_value=exc,
            request_params=request_params, query_id=args.query_id, source_environment=source_environment,
            authoritative_for_final_rating=authoritative_for_final_rating,
            submission_state=submission_state, execution_phase=exc.request_stage,
            raw_body=exc.response_body, raw_suffix="xml", response_receipt=receipt)
        print(run["status"])


if __name__ == "__main__":
    main()

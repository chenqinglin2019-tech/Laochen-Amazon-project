#!/usr/bin/env python3
"""EPO OPS OAuth, discovery, and candidate-detail client."""

from __future__ import annotations

import argparse
import base64
import os
import re
import time
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from xml.etree import ElementTree

from common import (
    assert_provider_execution_allowed, credential, ensure_object, load_json,
    intrinsic_patent_right_type, load_skill_config,
)
from epo_quota_ledger import EpoQuotaLedger
from provider_utils import (
    ProviderError, authorize_exact_plan_execution, enforce_task_limit, http_request,
    quota_summary, record_error, record_result,
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


def ops_get(path: str, range_header: str = "") -> tuple[bytes, dict[str, str]]:
    config, base, _, consumer_key, _ = settings()
    token, _ = access_token()
    url = f"{base}/{path.lstrip('/')}"
    ledger = EpoQuotaLedger(config, consumer_key)

    def request_once(access_value: str) -> tuple[bytes, dict[str, str]]:
        request_headers = {
            "Authorization": f"Bearer {access_value}",
            "Accept": "application/exchange+xml",
        }
        if range_header:
            request_headers["X-OPS-Range"] = range_header
        reservation = ledger.reserve(path)
        try:
            _, response_headers, response_body = http_request(
                url,
                headers=request_headers,
                timeout=int(config["http"]["timeout_seconds"]),
                # Each quota-bearing HTTP attempt needs its own persisted
                # reservation. Do not hide retries inside http_request.
                retries=0,
            )
        except ProviderError as exc:
            try:
                ledger.settle(reservation, error_code=exc.code)
            except ProviderError as quota_error:
                raise quota_error from None
            raise
        ledger.settle(
            reservation,
            headers=response_headers,
            response_bytes=len(response_body),
        )
        return response_body, response_headers

    try:
        return request_once(token)
    except ProviderError as exc:
        if exc.code != "AUTH_FAILED":
            raise
    fresh, _ = access_token(force_refresh=True)
    return request_once(fresh)


def normalize_search(xml_bytes: bytes, *, include_biblio: bool = False) -> list[dict]:
    """Never interpret an unrelated/error XML document as a successful empty search."""
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO OPS response is invalid XML") from exc
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
        candidates.append(candidate)
    if not candidates:
        total = str(search.attrib.get("total-result-count", "")) if search is not None else ""
        result = scope.find("{*}search-result")
        if total != "0" or result is None or len(result):
            raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", "EPO response does not prove an explicit, schema-valid zero-result search")
    return list({item["publication_number"]: item for item in candidates}.values())


def search_response(xml_bytes: bytes, requested_range: str = "1-25", *, include_biblio: bool = False, require_range: bool = False) -> dict:
    candidates = normalize_search(xml_bytes, include_biblio=include_biblio)
    root = ElementTree.fromstring(xml_bytes)
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
    match = re.fullmatch(r"([A-Z]{2})(\d+)(?:[A-Z]\d?)?", normalized)
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
    candidate_id: str = "",
) -> dict:
    """Normalize one bounded EPO detail endpoint into a mergeable candidate."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ProviderError("RESPONSE_SCHEMA_CHANGED", "failed", f"EPO {operation} response is invalid XML") from exc
    identifiers = _unique_text([
        _document_value(node) for node in root.findall(".//{*}document-id")
    ])
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
    return {"detail_operation": operation, "candidates": [candidate]}


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
        {"q": args.query, "range": args.range, "right_type": args.right_type}
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
        raise SystemExit(f"{exc.code}: {exc.detail}") from None
    source_environment = "test_fixture" if os.environ.get("LC_IPR_TEST_MODE") == "1" else "production"
    authoritative_for_final_rating = False
    try:
        source_environment, authoritative_for_final_rating = source_profile()
        config, _, _, _, _ = settings()
        if args.operation == "search":
            current_task = load_json(args.task_dir.resolve() / "task.json")
            limit_key = "epo_search_queries_per_task_v24" if current_task.get("schema_version") == "2.4-free" else "epo_search_queries_per_task"
            enforce_task_limit(args.task_dir.resolve(), "epo_ops", "search", int(config["limits"].get(limit_key, 96 if limit_key.endswith("v24") else 6)))
        else:
            enforce_task_limit(args.task_dir.resolve(), "epo_ops", "candidate_detail", int(config["limits"]["epo_candidate_detail_limit"]))
        body, headers = ops_get(operation_paths[args.operation], args.range if args.operation == "search" else "")
        normalized = search_response(body, args.range, include_biblio=task.get("schema_version") == "2.4-free", require_range=task.get("schema_version") == "2.4-free") if args.operation == "search" else normalize_detail(
            args.operation, args.query, body,
            right_type=args.right_type, candidate_id=args.candidate_id,
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
            authoritative_for_final_rating=authoritative_for_final_rating)
        print(run["status"])
    except ProviderError as exc:
        run = record_error(args.task_dir.resolve(), provider="epo_ops", operation=recorded_operation, query=args.query,
            jurisdiction=args.jurisdiction, evidence_type="patent", error_value=exc,
            request_params=request_params, query_id=args.query_id, source_environment=source_environment,
            authoritative_for_final_rating=authoritative_for_final_rating)
        print(run["status"])


if __name__ == "__main__":
    main()

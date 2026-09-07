#!/usr/bin/env python3
"""Validate and record one assisted official-registry browser capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import (
    capture_provenance, ensure_object, load_json, load_skill_config, path_within, sha256_file,
    validate_checked_at,
)
from provider_utils import (
    ProviderError, planned_query_id, planned_query_metadata, record_result,
    require_provider_operation, sanitize_evidence_url,
)


ALLOWED_STATUSES = {
    "success", "no_result", "needs_user_action", "access_limited", "failed",
}
RECALL_OPERATIONS = {
    "patent_recall", "utility_model_recall", "trademark_recall", "design_recall",
    "copyright_recall", "enforcement_recall",
}
RIGHT_TYPES = {
    "patent", "utility_model", "design", "trademark_word", "trademark_figurative",
    "copyright", "enforcement",
}

PROVIDER_RULES: dict[str, dict[str, Any]] = {
    "jplatpat_browser": {
        "authority": "Japan Patent Office / INPIT",
        "hosts": {"www.j-platpat.inpit.go.jp", "j-platpat.inpit.go.jp"},
        "jurisdictions": {"JP"},
        "right_types": RIGHT_TYPES - {"copyright", "enforcement"},
        "operations": {"patent_recall", "utility_model_recall", "trademark_recall", "design_recall", "candidate_verification"},
    },
    "tmview_browser": {
        "authority": "European Union Intellectual Property Network (TMview)",
        "hosts": {"www.tmdn.org", "tmdn.org"},
        "jurisdictions": {
            "EU", "AT", "BE", "BG", "HR", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
            "FR", "GR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT",
            "RO", "SE", "SI", "SK", "GB",
        },
        "right_types": {"trademark_word", "trademark_figurative"},
        "operations": {"trademark_recall"},
    },
    "designview_browser": {
        "authority": "European Union Intellectual Property Network (DesignView)",
        "hosts": {"www.tmdn.org", "tmdn.org"},
        "jurisdictions": {
            "EU", "AT", "BE", "BG", "HR", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
            "FR", "GR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT",
            "RO", "SE", "SI", "SK", "GB",
        },
        "right_types": {"design"},
        "operations": {"design_recall"},
    },
    "epo_register_browser": {
        "authority": "European Patent Office",
        "hosts": {"register.epo.org"},
        "terms_hosts": {"epo.org", "www.epo.org"},
        "jurisdictions": {"EP", "EU", "DE", "FR", "IT", "ES", "GB", "NL", "BE", "SE", "PL"},
        "right_types": {"patent"},
        "operations": {"patent_recall", "candidate_verification"},
    },
    "euipo_esearch_browser": {
        "authority": "European Union Intellectual Property Office (EUIPO)",
        "hosts": {"euipo.europa.eu", "www.euipo.europa.eu"},
        "jurisdictions": {"EU"},
        "right_types": {"trademark_figurative"},
        "operations": {"trademark_recall"},
    },
}

NATIONAL_RULES: dict[str, dict[str, Any]] = {
    "DE": {"authority": "German Patent and Trade Mark Office (DPMA)", "hosts": {"register.dpma.de", "dpma.de", "www.dpma.de"}},
    "FR": {"authority": "Institut national de la propriété industrielle (INPI)", "hosts": {"data.inpi.fr", "inpi.fr", "www.inpi.fr"}},
    "IT": {"authority": "Ufficio Italiano Brevetti e Marchi (UIBM)", "hosts": {"uibm.mise.gov.it", "uibm.mimit.gov.it", "uibm.gov.it", "www.uibm.gov.it"}},
    "ES": {"authority": "Oficina Española de Patentes y Marcas (OEPM)", "hosts": {"consultas2.oepm.es", "sede.oepm.gob.es", "oepm.es", "www.oepm.es"}},
    "GB": {"authority": "UK Intellectual Property Office (UKIPO)", "hosts": {"www.gov.uk", "gov.uk", "www.ipo.gov.uk", "ipo.gov.uk", "trademarks.ipo.gov.uk", "www.registered-design.service.gov.uk", "registered-design.service.gov.uk", "patents.service.gov.uk"}},
    "NL": {"authority": "Netherlands Patent Office / BOIP", "hosts": {"mijnoctrooi.rvo.nl", "rvo.nl", "www.rvo.nl", "boip.int", "www.boip.int"}},
    "BE": {"authority": "Belgian Office for Intellectual Property / BOIP", "hosts": {"economie.fgov.be", "bpp.economie.fgov.be", "fgov.be", "boip.int", "www.boip.int"}},
    "SE": {"authority": "Swedish Intellectual Property Office (PRV)", "hosts": {"search.prv.se", "tc.prv.se", "was.prv.se", "prv.se", "www.prv.se"}},
    "PL": {"authority": "Patent Office of the Republic of Poland (UPRP)", "hosts": {"ewyszukiwarka.pue.uprp.gov.pl", "pue.uprp.gov.pl", "uprp.gov.pl", "www.uprp.gov.pl"}},
}

PUBLIC_RULES: dict[str, dict[str, Any]] = {
    "US": {
        "authority": "United States public IP records",
        "hosts": {"publicrecords.copyright.gov", "cocatalog.loc.gov", "copyright.gov", "www.copyright.gov", "ttabvue.uspto.gov", "ptab.uspto.gov", "ccb.gov", "www.ccb.gov", "dockets.ccb.gov"},
        "source_hosts": {
            "copyright_records": {"publicrecords.copyright.gov", "cocatalog.loc.gov", "copyright.gov", "www.copyright.gov"},
            "ttabvue": {"ttabvue.uspto.gov"},
            "ptab": {"ptab.uspto.gov"},
            "copyright_claims_board": {"ccb.gov", "www.ccb.gov", "dockets.ccb.gov"},
        },
    },
    "JP": {"authority": "Japanese official copyright and IP court sources", "hosts": {"www.bunka.go.jp", "bunka.go.jp", "www.courts.go.jp", "courts.go.jp", "www.ip.courts.go.jp", "ip.courts.go.jp"}},
    "EU": {"authority": "European Union official IP and court sources", "hosts": {"europa.eu", "curia.europa.eu", "euipo.europa.eu", "www.euipo.europa.eu"}},
    "DE": {"authority": "German official court sources", "hosts": {"rechtsprechung-im-internet.de", "www.rechtsprechung-im-internet.de", "bundesgerichtshof.de", "www.bundesgerichtshof.de", "dpma.de", "www.dpma.de"}},
    "FR": {"authority": "French official court and INPI sources", "hosts": {"courdecassation.fr", "www.courdecassation.fr", "data.inpi.fr", "inpi.fr", "www.inpi.fr"}},
    "IT": {"authority": "Italian official justice and UIBM sources", "hosts": {"giustizia.it", "www.giustizia.it", "uibm.mimit.gov.it", "uibm.mise.gov.it"}},
    "ES": {"authority": "Spanish official judiciary and OEPM sources", "hosts": {"poderjudicial.es", "www.poderjudicial.es", "oepm.es", "www.oepm.es"}},
    "GB": {"authority": "UK official judiciary and UKIPO sources", "hosts": {"gov.uk", "www.gov.uk", "judiciary.uk", "www.judiciary.uk", "ipo.gov.uk", "www.ipo.gov.uk", "caselaw.nationalarchives.gov.uk", "nationalarchives.gov.uk"}},
    "NL": {"authority": "Dutch official court sources", "hosts": {"rechtspraak.nl", "www.rechtspraak.nl", "uitspraken.rechtspraak.nl", "overheid.nl", "www.overheid.nl", "rvo.nl", "www.rvo.nl"}},
    "BE": {"authority": "Belgian official legal sources", "hosts": {"economie.fgov.be", "justel.fgov.be", "fgov.be", "juportal.be", "www.juportal.be"}},
    "SE": {"authority": "Swedish official court sources", "hosts": {"domstol.se", "www.domstol.se", "prv.se", "www.prv.se"}},
    "PL": {"authority": "Polish official IP and government sources", "hosts": {"gov.pl", "www.gov.pl", "uprp.gov.pl", "www.uprp.gov.pl", "orzeczenia.ms.gov.pl", "ms.gov.pl"}},
}

FORBIDDEN_CAPTURE_KEYS = {
    "cdp_endpoint", "endpoint", "websocket", "websocket_url", "remote_debugging_port",
    "profile_dir", "user_data_dir", "cookies", "cookie", "set-cookie", "local_storage",
    "localstorage", "authorization", "proxy-authorization", "password", "passwd",
    "username", "api_key", "apikey", "access_token", "refresh_token", "requesttoken",
    "client_id", "client_secret", "consumer_key", "consumer_secret",
}
RECALL_PLAN_META_FIELDS = {
    "query_id", "operation", "jurisdiction", "right_type", "required", "required_for",
    "requirement_id", "requirement_ids", "wave", "derived_from", "execute_by_default",
    "execute_when", "fallback_provider", "mode",
}


def clean_number(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def jpo_verification_already_complete(
    task_dir: Path, right_type: str, candidate_id: str, record: str,
) -> bool:
    """Avoid a redundant J-PlatPat session after complete JPO API verification."""
    path = task_dir / "normalized-candidates.json"
    evidence_path = task_dir / "evidence.json"
    if not path.is_file() or not evidence_path.is_file():
        return False
    try:
        payload = ensure_object(load_json(path), "normalized-candidates.json")
        evidence = ensure_object(load_json(evidence_path), "evidence.json")
        task = ensure_object(load_json(task_dir / "task.json"), "task.json")
        search_plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    except (OSError, ValueError):
        return False
    from finalize_assessment import official_verification_complete

    expected_id = str(candidate_id or "").strip()
    expected_number = clean_number(record)
    requirement_ids = {
        str(requirement.get("requirement_id") or "")
        for requirement in task.get("coverage_requirements", [])
        if isinstance(requirement, dict)
        and requirement.get("phase") == "candidate_verification"
        and str(requirement.get("jurisdiction") or "").upper() == "JP"
        and str(requirement.get("right_type") or "") == right_type
        and any(
            isinstance(route, dict)
            and route.get("provider") == "jpo_api"
            and route.get("operation") == "candidate_verification"
            for route in requirement.get("routes", [])
        )
    }
    for item in [*payload.get("patents", []), *payload.get("trademarks", [])]:
        if not isinstance(item, dict) or str(item.get("right_type") or "") != right_type:
            continue
        identifiers = {
            clean_number(item.get(field))
            for field in (
                "record_number", "application_number", "publication_number", "registration_number",
                "grant_number", "serial_number",
            )
            if clean_number(item.get(field))
        }
        matches = (
            bool(expected_id and str(item.get("candidate_id") or "") == expected_id)
            or bool(expected_number and expected_number in identifiers)
        )
        if not matches:
            continue
        if official_verification_complete(
            item, strict=True, evidence=evidence,
            allowed_routes=[{
                "provider": "jpo_api", "operation": "candidate_verification",
            }],
            jurisdiction="JP", right_type=right_type,
            requirement_ids=requirement_ids,
            search_plan=search_plan,
        ):
            return True
    return False


def _host_allowed(hostname: str, allowed: set[str]) -> bool:
    host = hostname.casefold().strip(".")
    return any(host == item.casefold() or host.endswith(f".{item.casefold()}") for item in allowed)


def _rules(provider: str, jurisdiction: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if provider == "official_registry_browser":
        national = NATIONAL_RULES.get(jurisdiction)
        if not national:
            raise ValueError(f"unsupported national official registry jurisdiction: {jurisdiction}")
        return {
            **national,
            "jurisdictions": {jurisdiction},
            "right_types": RIGHT_TYPES - {"copyright", "enforcement"},
            "operations": {"patent_recall", "utility_model_recall", "trademark_recall", "design_recall", "candidate_verification"},
        }
    if provider == "public_web_browser":
        public = PUBLIC_RULES.get(jurisdiction)
        if not public:
            raise ValueError(f"no official public-web sources configured for jurisdiction: {jurisdiction}")
        configured_hosts = (
            (config or {}).get("providers", {}).get("public_web_browser", {})
            .get("jurisdiction_allowed_hosts", {}).get(jurisdiction)
        )
        if not isinstance(configured_hosts, list) or not configured_hosts:
            raise ValueError(f"no public-web host allowlist configured for jurisdiction: {jurisdiction}")
        for host in configured_hosts:
            if not _host_allowed(str(host), public["hosts"]):
                raise ValueError(f"configured public-web host is outside the built-in official allowlist: {host}")
        return {
            **public,
            "hosts": {str(host).casefold() for host in configured_hosts},
            "jurisdictions": {jurisdiction},
            "right_types": {"copyright", "enforcement"},
            "operations": {"copyright_recall", "enforcement_recall", "candidate_verification"},
        }
    if provider not in PROVIDER_RULES:
        raise ValueError(f"unsupported registry provider: {provider}")
    return PROVIDER_RULES[provider]


def _reject_sensitive_fields(value: Any, prefix: str = "capture") -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_fields(item, f"{prefix}[{index}]")
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if str(key).casefold() in FORBIDDEN_CAPTURE_KEYS:
            raise ValueError(f"capture contains forbidden sensitive field: {prefix}.{key}")
        _reject_sensitive_fields(item, f"{prefix}.{key}")


def _strings(value: object, field: str, required: bool = False) -> list[str]:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    result = [str(item).strip() for item in values if str(item).strip()]
    if required and not result:
        raise ValueError(f"{field} must contain at least one value")
    return list(dict.fromkeys(result))


def _evidence_file(value: object, field: str, task_dir: Path) -> tuple[str, str, int, str]:
    path = Path(str(value or "")).expanduser().resolve()
    if not path.is_file() or not (
        path_within(path, task_dir / "screenshots") or path_within(path, task_dir / "images")
    ):
        raise ValueError(f"{field} must exist inside task screenshots/ or images/: {path}")
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    byte_count = path.stat().st_size
    if byte_count <= 0 or not mime_type.startswith("image/"):
        raise ValueError(f"{field} must be a non-empty image file")
    return str(path), sha256_file(path), byte_count, mime_type


def _common_capture(
    capture: dict[str, Any], task: dict[str, Any], task_dir: Path, allowed_hosts: set[str],
    allowed_transports: set[str],
) -> tuple[str, str, str, dict[str, Any]]:
    _reject_sensitive_fields(capture)
    provenance = capture_provenance(capture, task, allowed_transports=allowed_transports)
    raw_url = str(capture.get("final_url") or "").strip()
    final_url = sanitize_evidence_url(raw_url)
    parsed = urlparse(final_url)
    if parsed.scheme != "https" or not parsed.hostname or not _host_allowed(parsed.hostname, allowed_hosts):
        raise ValueError("final_url must use an allowlisted official HTTPS registry host")
    checked_at = str(capture.get("checked_at") or "").strip()
    validate_checked_at(checked_at)
    screenshot_path, screenshot_sha256, screenshot_bytes, screenshot_mime_type = _evidence_file(
        capture.get("screenshot_path"), "screenshot_path", task_dir,
    )
    browser_evidence = {
        "screenshot_path": screenshot_path,
        "screenshot_sha256": screenshot_sha256,
        "screenshot_bytes": screenshot_bytes,
        "screenshot_mime_type": screenshot_mime_type,
        "capture_provenance": provenance,
    }
    return final_url, checked_at, provenance["capture_transport"], browser_evidence


def _terms_review(capture: dict[str, Any], allowed_hosts: set[str]) -> dict[str, Any]:
    review = capture.get("terms_review")
    if not isinstance(review, dict) or review.get("schema_version") != "1.0":
        raise ValueError("REGISTRY_TERMS_REVIEW_REQUIRED: terms_review schema 1.0 is missing")
    if (
        review.get("operator_confirmed") is not True
        or review.get("decision") != "cdp_assisted_single_action_confirmed"
    ):
        raise ValueError("REGISTRY_TERMS_REVIEW_REQUIRED: current assisted-use decision was not confirmed")
    terms_url = sanitize_evidence_url(str(review.get("terms_url") or ""))
    parsed = urlparse(terms_url)
    if parsed.scheme != "https" or not parsed.hostname or not _host_allowed(parsed.hostname, allowed_hosts):
        raise ValueError("terms_review.terms_url must use an allowlisted official HTTPS host")
    checked_at = str(review.get("checked_at") or "").strip()
    validate_checked_at(checked_at, max_age_hours=24)
    return {
        "schema_version": "1.0",
        "terms_url": terms_url,
        "checked_at": checked_at,
        "decision": "cdp_assisted_single_action_confirmed",
        "operator_confirmed": True,
    }


def _normalize_media(capture: dict[str, Any], task_dir: Path) -> list[dict[str, Any]]:
    values = capture.get("evidence_images", [])
    if not isinstance(values, list):
        raise ValueError("evidence_images must be an array")
    media: list[dict[str, Any]] = []
    for index, item in enumerate(values, 1):
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict):
            raise ValueError("each evidence image must be a path or object")
        path, digest, byte_count, mime_type = _evidence_file(
            item.get("path"), "evidence_image.path", task_dir,
        )
        media.append({
            "path": path,
            "sha256": digest,
            "bytes": byte_count,
            "mime_type": mime_type,
            "label": str(item.get("label") or f"Official registry media {index}").strip(),
            "role": str(item.get("role") or "official_media").strip(),
        })
    return media


def _normalize_recall_candidate(
    item: dict[str, Any], right_type: str, jurisdiction: str, provider: str,
) -> dict[str, Any]:
    record = str(
        item.get("record_number") or item.get("application_number")
        or item.get("publication_number") or item.get("registration_number")
        or item.get("case_number") or item.get("docket_number") or ""
    ).strip()
    if not clean_number(record):
        raise ValueError("each recalled candidate requires an official record identifier")
    item_jurisdiction = str(item.get("jurisdiction") or jurisdiction).upper()
    item_right_type = str(item.get("right_type") or right_type)
    if item_jurisdiction != jurisdiction or item_right_type != right_type:
        raise ValueError("candidate jurisdiction/right_type must match the recorded query")
    return {
        "candidate_id": str(item.get("candidate_id") or ""),
        "right_type": right_type,
        "jurisdiction": jurisdiction,
        "record_number": record,
        "application_number": str(item.get("application_number") or "").strip(),
        "publication_number": str(item.get("publication_number") or "").strip(),
        "registration_number": str(item.get("registration_number") or "").strip(),
        "title": str(item.get("title") or "").strip(),
        "owner": str(item.get("owner") or "").strip(),
        "legal_status": str(item.get("legal_status") or "").strip(),
        "classes": _strings(item.get("classes"), "classes"),
        "material": bool(item.get("material", False)),
        "source": provider,
        "official_verification": {
            "status": "not_checked", "source": provider, "url": "", "checked_at": "",
        },
    }


def _normalize_success_recall(
    capture: dict[str, Any], common: tuple[str, str, str, dict[str, Any]],
    provider: str, operation: str, right_type: str, jurisdiction: str,
) -> dict[str, Any]:
    final_url, checked_at, transport, browser_evidence = common
    candidates_value = capture.get("candidates")
    if not isinstance(candidates_value, list) or not candidates_value:
        raise ValueError("successful recall requires at least one candidate")
    candidates = [
        _normalize_recall_candidate(item, right_type, jurisdiction, provider)
        for item in candidates_value if isinstance(item, dict)
    ]
    if len(candidates) != len(candidates_value):
        raise ValueError("every recalled candidate must be an object")
    return {
        "right_type": right_type,
        "jurisdiction": jurisdiction,
        "operation": operation,
        "query": str(capture.get("query") or "").strip(),
        "source_url": final_url,
        "checked_at": checked_at,
        "candidates": candidates,
        "browser_evidence": browser_evidence,
        "capture_transport": transport,
    }


def _normalize_success_verification(
    capture: dict[str, Any], common: tuple[str, str, str, dict[str, Any]],
    rules: dict[str, Any], right_type: str, jurisdiction: str,
    expected_record: str, candidate_id: str, task_dir: Path,
) -> dict[str, Any]:
    final_url, checked_at, transport, browser_evidence = common
    record_number = clean_number(capture.get("record_number") or expected_record)
    page_record_number = clean_number(capture.get("page_record_number"))
    if not record_number or clean_number(expected_record) != record_number or page_record_number != record_number:
        raise ValueError("record_number and page_record_number must match the requested record")
    title = str(capture.get("title") or "").strip()
    legal_status = str(capture.get("legal_status") or "").strip()
    owners = _strings(capture.get("owners", capture.get("owner")), "owners", required=True)
    if not title or not legal_status:
        raise ValueError("successful verification requires title and legal_status")
    media = _normalize_media(capture, task_dir)
    if right_type in {"design", "trademark_figurative"} and not media:
        raise ValueError("design and figurative-mark verification requires official media")
    if media:
        browser_evidence["evidence_images"] = media
    classes = _strings(capture.get("classes"), "classes")
    if right_type in {"patent", "utility_model", "design", "trademark_word", "trademark_figurative"} and not classes:
        raise ValueError("official verification requires at least one official classification")
    return {
        "candidate_id": candidate_id or str(capture.get("candidate_id") or ""),
        "right_type": right_type,
        "jurisdiction": jurisdiction,
        "record_number": record_number,
        "application_number": str(capture.get("application_number") or "").strip(),
        "publication_number": str(capture.get("publication_number") or "").strip(),
        "registration_number": str(capture.get("registration_number") or "").strip(),
        "title": title,
        "legal_status": legal_status,
        "owners": owners,
        "classes": classes,
        "official_verification": {
            "status": "verified",
            "authority": rules["authority"],
            "source": rules["authority"],
            "method": (
                "chrome_desktop_cdp_assisted" if transport == "cdp"
                else "official_manual_capture"
            ),
            "identity_match": True,
            "legal_status": legal_status,
            "owner": owners,
            "classes": classes,
            "media": media,
            "url": final_url,
            "checked_at": checked_at,
        },
        "browser_evidence": browser_evidence,
        "capture_transport": transport,
    }


def _recall_plan_binding(
    task_dir: Path, provider: str, operation: str, jurisdiction: str,
    right_type: str, query: str, capture: dict[str, Any],
    request_params: dict[str, Any], explicit_query_id: str,
) -> tuple[str, dict[str, Any]]:
    captured_query_id = str(capture.get("query_id") or "").strip()
    query_id = str(explicit_query_id or captured_query_id).strip()
    if explicit_query_id and captured_query_id and explicit_query_id != captured_query_id:
        raise ValueError("capture query_id does not match the explicitly selected query_id")
    if not query_id:
        query_id = planned_query_id(task_dir, provider, operation, query, request_params)
    planned = planned_query_metadata(task_dir, provider, query_id)
    if not query_id or not planned:
        raise ValueError("recall capture must bind exactly one generated query_id")
    expected = {
        "operation": operation,
        "jurisdiction": jurisdiction,
        "right_type": right_type,
        "query": query,
    }
    actual = {
        "operation": str(planned.get("operation") or ""),
        "jurisdiction": str(planned.get("jurisdiction") or "").upper(),
        "right_type": str(planned.get("right_type") or ""),
        "query": str(planned.get("q") or planned.get("query") or ""),
    }
    if actual != expected:
        raise ValueError("capture operation/jurisdiction/right_type/query does not match query_id")
    planned_source = str(planned.get("source_key") or "").strip()
    captured_source = str(capture.get("source_key") or "").strip()
    if planned_source != captured_source:
        raise ValueError("capture source_key does not match the planned official source")
    return query_id, planned


def _verification_plan_binding(
    task_dir: Path, provider: str, jurisdiction: str, right_type: str,
    expected_record: str, explicit_candidate_id: str, capture: dict[str, Any],
    explicit_query_id: str, *, require_capture_binding: bool = True,
) -> tuple[str, dict[str, Any], str]:
    """Bind one verification to its exact generated candidate action."""
    captured_query_id = str(capture.get("query_id") or "").strip()
    query_id = str(explicit_query_id or captured_query_id).strip()
    if explicit_query_id and captured_query_id and explicit_query_id != captured_query_id:
        raise ValueError("capture query_id does not match the explicitly selected query_id")
    if not query_id:
        raise ValueError("candidate_verification requires an exact generated query_id")
    planned = planned_query_metadata(task_dir, provider, query_id)
    if not planned:
        raise ValueError("candidate_verification query_id is not an exact generated plan entry")

    planned_record = str(
        planned.get("record_number") or planned.get("serial_number")
        or planned.get("number") or planned.get("identifier")
        or planned.get("q") or planned.get("query") or ""
    ).strip()
    planned_query = str(planned.get("q") or planned.get("query") or "").strip()
    planned_candidate_id = str(planned.get("candidate_id") or "").strip()
    expected = {
        "operation": "candidate_verification",
        "jurisdiction": jurisdiction,
        "right_type": right_type,
    }
    actual = {
        "operation": str(planned.get("operation") or ""),
        "jurisdiction": str(planned.get("jurisdiction") or "").upper(),
        "right_type": str(planned.get("right_type") or ""),
    }
    if actual != expected:
        raise ValueError("query_id operation/jurisdiction/right_type does not match this verification")
    if provider == "public_web_browser" and (
        not planned_record or planned_query != planned_record
    ):
        raise ValueError("planned public candidate q and exact record identifier do not match")
    if provider != "public_web_browser" and (
        not clean_number(planned_record) or clean_number(planned_query) != clean_number(planned_record)
    ):
        raise ValueError("planned candidate q and record identifier do not match")
    if provider == "public_web_browser":
        if expected_record.strip() != planned_record:
            raise ValueError("--record does not exactly match the selected public candidate plan entry")
    elif clean_number(expected_record) != clean_number(planned_record):
        raise ValueError("--record does not match the selected candidate plan entry")
    if not planned_candidate_id:
        raise ValueError("planned candidate action has no candidate_id")
    selected_candidate_id = str(
        explicit_candidate_id or capture.get("candidate_id") or ""
    ).strip()
    if selected_candidate_id != planned_candidate_id:
        raise ValueError("candidate_id does not match the selected candidate plan entry")
    captured_candidate_id = str(capture.get("candidate_id") or "").strip()
    if explicit_candidate_id and captured_candidate_id and explicit_candidate_id != captured_candidate_id:
        raise ValueError("capture candidate_id does not match --candidate-id")
    if require_capture_binding:
        if captured_query_id != query_id or captured_candidate_id != planned_candidate_id:
            raise ValueError("capture must contain the exact planned query_id and candidate_id")
        planned_source = str(planned.get("source_key") or "").strip()
        captured_source = str(capture.get("source_key") or "").strip()
        if provider == "public_web_browser" and planned_source != captured_source:
            raise ValueError("capture source_key does not match the planned official source")
        if provider == "public_web_browser" and jurisdiction == "US" and not planned_source:
            raise ValueError("US public candidate verification requires a planned source_key")
        captured_record = clean_number(capture.get("record_number"))
        if captured_record and captured_record != clean_number(planned_record):
            raise ValueError("capture record_number does not match the selected plan entry")
        page_record = clean_number(capture.get("page_record_number"))
        if page_record and page_record != clean_number(planned_record):
            raise ValueError("capture page_record_number does not match the selected plan entry")
        page_query_record = clean_number(capture.get("page_query_record"))
        if page_query_record and page_query_record != clean_number(planned_record):
            raise ValueError("capture page_query_record does not match the selected plan entry")
        if str(capture.get("status") or "") == "no_result" and page_query_record != clean_number(planned_record):
            raise ValueError("no_result verification requires an exact rendered record-query binding")
    requirement_ids = [
        str(value).strip() for value in planned.get("requirement_ids", [])
        if str(value).strip()
    ]
    if not requirement_ids:
        raise ValueError("planned candidate action has no requirement_ids")
    return query_id, planned, planned_candidate_id


def _planned_request_params(planned: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in planned.items()
        if key not in (RECALL_PLAN_META_FIELDS - {"mode"}) and value not in (None, "")
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _planned_recall_filters(planned: dict[str, Any]) -> dict[str, Any]:
    return {
        key: planned[key]
        for key in sorted(planned)
        if key not in RECALL_PLAN_META_FIELDS
        and key not in {"q", "query"}
        and planned[key] not in (None, "")
    }


def _normalized_binding_value(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def _equivalent_binding_value(expected: Any, actual: Any) -> bool:
    left = _normalized_binding_value(expected)
    right = _normalized_binding_value(actual)
    if left == right:
        return True
    aliases = {
        "vienna_classification": {"vienna", "vienna classification"},
        "locarno_classification": {"locarno", "locarno classification"},
        "nice_classification": {"nice", "nice classification"},
        "jpo_figurative_classification": {
            "jpo figurative", "figurative classification", "図形分類",
        },
    }
    return right in aliases.get(left, set())


def _recall_page_binding_digest(
    capture: dict[str, Any], browser_evidence: dict[str, Any], query_id: str,
) -> str:
    bound = {
        "query_id": query_id,
        "final_url": str(capture.get("final_url") or ""),
        "page_title": str(capture.get("page_title") or ""),
        "screenshot_sha256": str(capture.get("screenshot_sha256") or ""),
        "checked_at": str(capture.get("checked_at") or ""),
        "rendered_search": capture.get("rendered_search"),
        "capture_provenance": browser_evidence.get("capture_provenance"),
    }
    return hashlib.sha256(_canonical_json(bound).encode("utf-8")).hexdigest()


def _validate_recall_attestation(
    capture: dict[str, Any], planned: dict[str, Any],
    browser_evidence: dict[str, Any], query_id: str,
) -> dict[str, Any]:
    """Bind an operator-confirmed planned lookup to the actual captured page."""
    attestation = capture.get("operator_attestation")
    if not isinstance(attestation, dict):
        raise ValueError("REGISTRY_OPERATOR_ATTESTATION_REQUIRED: recall capture has no operator attestation")
    if attestation.get("schema_version") != "1.0":
        raise ValueError("registry operator attestation schema_version must be 1.0")
    if attestation.get("operator_confirmed") is not True or attestation.get("confirmed_current_page") is not True:
        raise ValueError("REGISTRY_OPERATOR_ATTESTATION_REQUIRED: current page was not explicitly confirmed")

    planned_query = str(planned.get("q") or planned.get("query") or "").strip()
    planned_right_type = str(planned.get("right_type") or "").strip()
    planned_filters = _planned_recall_filters(planned)
    if str(attestation.get("query") or "") != planned_query:
        raise ValueError("REGISTRY_ATTESTED_QUERY_MISMATCH: attested query does not match the plan")
    if str(attestation.get("right_type") or "") != planned_right_type:
        raise ValueError("REGISTRY_ATTESTED_RIGHT_TYPE_MISMATCH: attested right type does not match the plan")
    if attestation.get("filters") != planned_filters:
        raise ValueError("REGISTRY_ATTESTED_FILTER_MISMATCH: attested filters do not match the plan")

    checked_at = str(capture.get("checked_at") or "").strip()
    invoked_at = str(attestation.get("invoked_at") or "").strip()
    attested_at = str(attestation.get("attested_at") or "").strip()
    if attested_at != checked_at:
        raise ValueError("operator attestation time is not bound to capture checked_at")
    invoked_time = validate_checked_at(invoked_at)
    checked_time = validate_checked_at(checked_at)
    if invoked_time > checked_time:
        raise ValueError("operator attestation invocation cannot be later than page capture")

    page_title = str(capture.get("page_title") or "").strip()
    if not page_title:
        raise ValueError("recall capture requires the current official page title")
    screenshot_digest = str(capture.get("screenshot_sha256") or "").strip()
    if screenshot_digest != str(browser_evidence.get("screenshot_sha256") or ""):
        raise ValueError("attested screenshot_sha256 does not match the captured image")

    rendered = capture.get("rendered_search")
    if not isinstance(rendered, dict) or rendered.get("schema_version") != "1.0":
        raise ValueError("REGISTRY_RENDERED_BINDING_MISSING: rendered_search schema is missing")
    if rendered.get("extraction_attempted") is not True:
        raise ValueError("REGISTRY_RENDERED_BINDING_MISSING: DOM/URL extraction was not attempted")
    query_values = rendered.get("query_values")
    if not isinstance(query_values, list) or not all(isinstance(value, str) for value in query_values):
        raise ValueError("rendered_search.query_values must be an array of strings")
    query_values = [value for value in query_values if value.strip()]
    if query_values and not any(
        _equivalent_binding_value(planned_query, value) for value in query_values
    ):
        raise ValueError("REGISTRY_RENDERED_QUERY_MISMATCH: visible page belongs to another query")

    rendered_filters = rendered.get("filters")
    if not isinstance(rendered_filters, dict):
        raise ValueError("rendered_search.filters must be an object")
    for key, values in rendered_filters.items():
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"rendered_search.filters.{key} must be an array of strings")
        observed = [value for value in values if value.strip()]
        if observed and (
            key not in planned_filters
            or not any(_equivalent_binding_value(planned_filters[key], value) for value in observed)
        ):
            raise ValueError(f"REGISTRY_RENDERED_FILTER_MISMATCH: visible {key} does not match the plan")

    expected_binding = _recall_page_binding_digest(capture, browser_evidence, query_id)
    if str(attestation.get("page_binding_sha256") or "") != expected_binding:
        raise ValueError("operator attestation is not bound to this URL/title/screenshot/time/provenance")
    audit = {
        "page_title": page_title,
        "rendered_search": rendered,
        "operator_attestation": attestation,
        "page_binding_sha256": expected_binding,
    }
    browser_evidence.update(audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Record an assisted official-registry browser capture.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument(
        "--operation", choices=sorted(RECALL_OPERATIONS | {"candidate_verification"}), required=True,
    )
    parser.add_argument("--right-type", choices=sorted(RIGHT_TYPES), required=True)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--record", default="")
    parser.add_argument("--candidate-id", default="")
    parser.add_argument("--query-id", default="")
    parser.add_argument("--mandatory", action="store_true")
    args = parser.parse_args()

    task_dir = args.task_dir.expanduser().resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if task.get("schema_version") == "2.4-free":
        raise SystemExit("AUTOMATION_NOT_VALIDATED: 2.4 registry capture cannot rely on manual business actions or operator attestation; record the unavailable route as access_limited")
    if str(task.get("schema_version") or "") != "2.3-free":
        raise SystemExit("The unified registry recorder requires task schema 2.3-free")
    provider = args.provider.strip()
    jurisdiction = args.jurisdiction.upper().strip()
    try:
        targets = {str(value).upper() for value in task.get("target_jurisdictions", [])}
        if jurisdiction not in targets and not (jurisdiction == "EP" and "EU" in targets):
            raise ValueError(f"jurisdiction {jurisdiction} is not targeted by this task")
        require_provider_operation(
            task, provider, args.operation,
            jurisdiction=jurisdiction, right_type=args.right_type,
        )
    except (ValueError, ProviderError) as exc:
        raise SystemExit(f"Invalid official registry capture: {exc}") from None
    effective_query_id = str(args.query_id or "").strip()
    planned_verification: dict[str, Any] = {}
    planned_candidate_id = ""
    if args.operation == "candidate_verification":
        try:
            if not clean_number(args.record):
                raise ValueError("candidate_verification requires --record")
            effective_query_id, planned_verification, planned_candidate_id = _verification_plan_binding(
                task_dir, provider, jurisdiction, args.right_type, args.record,
                args.candidate_id, {}, effective_query_id, require_capture_binding=False,
            )
        except ValueError as exc:
            raise SystemExit(f"Invalid official registry capture: {exc}") from None
    if (
        provider == "jplatpat_browser"
        and args.operation == "candidate_verification"
        and jpo_verification_already_complete(
            task_dir, args.right_type, planned_candidate_id, args.record,
        )
    ):
        print(json.dumps({
            "status": "not_applicable",
            "skipped": True,
            "provider": provider,
            "operation": args.operation,
            "reason": "complete_jpo_api_verification_already_present",
        }, ensure_ascii=False))
        return
    try:
        rules = _rules(provider, jurisdiction, load_skill_config())
        if jurisdiction not in rules["jurisdictions"]:
            raise ValueError(f"{provider} is not configured for jurisdiction {jurisdiction}")
        if args.right_type not in rules["right_types"] or args.operation not in rules["operations"]:
            raise ValueError(f"unsupported provider/right_type/operation combination: {provider}/{args.right_type}/{args.operation}")
        capture = ensure_object(load_json(args.capture.expanduser().resolve()), "registry browser capture")
        if str(capture.get("provider") or provider) != provider:
            raise ValueError("capture provider does not match --provider")
        if str(capture.get("operation") or args.operation) != args.operation:
            raise ValueError("capture operation does not match --operation")
        if str(capture.get("right_type") or args.right_type) != args.right_type:
            raise ValueError("capture right_type does not match --right-type")
        if str(capture.get("jurisdiction") or jurisdiction).upper() != jurisdiction:
            raise ValueError("capture jurisdiction does not match --jurisdiction")
        status = str(capture.get("status") or "")
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"unsupported registry capture status: {status!r}")
        common = _common_capture(
            capture, task, task_dir, rules["hosts"],
            {"cdp", "manual", "manual_capture"} if provider == "public_web_browser" else {"cdp"},
        )
        common[3]["terms_review"] = _terms_review(
            capture, rules.get("terms_hosts", rules["hosts"]),
        )
        query = str(capture.get("query") or "").strip()
        request_params: dict[str, Any]
        effective_query_id = str(effective_query_id or capture.get("query_id") or "").strip()
        if args.operation in RECALL_OPERATIONS:
            if not query:
                raise ValueError("recall capture requires the exact operator-submitted query")
            request_params = {
                "q": query,
                "mode": "manual_capture" if provider == "public_web_browser" else "user_assisted",
                "right_type": args.right_type,
            }
            source_key = str(capture.get("source_key") or "").strip()
            if source_key:
                request_params["source_key"] = source_key
            effective_query_id, planned = _recall_plan_binding(
                task_dir, provider, args.operation, jurisdiction, args.right_type,
                query, capture, request_params, effective_query_id,
            )
            _validate_recall_attestation(
                capture, planned, common[3], effective_query_id,
            )
            if provider == "public_web_browser" and source_key:
                source_hosts = rules.get("source_hosts", {}).get(source_key)
                final_host = (urlparse(common[0]).hostname or "").casefold()
                if not source_hosts or not _host_allowed(final_host, source_hosts):
                    raise ValueError("final_url is not bound to the planned official source_key")
            normalized = _normalize_success_recall(
                capture, common, provider, args.operation, args.right_type, jurisdiction,
            ) if status == "success" else None
            if status == "no_result":
                if capture.get("candidates") not in (None, []):
                    raise ValueError("no_result recall requires an empty candidates array")
                if not str(capture.get("result_message") or "").strip():
                    raise ValueError("no_result recall requires an explicit result_message")
        else:
            query = args.record.strip()
            if not clean_number(query):
                raise ValueError("candidate_verification requires --record")
            effective_query_id, planned_verification, planned_candidate_id = _verification_plan_binding(
                task_dir, provider, jurisdiction, args.right_type, query,
                args.candidate_id, capture, effective_query_id,
            )
            query = str(
                planned_verification.get("q")
                or planned_verification.get("query")
                or ""
            ).strip()
            request_params = _planned_request_params(planned_verification)
            normalized = _normalize_success_verification(
                capture, common, rules, args.right_type, jurisdiction, query,
                planned_candidate_id, task_dir,
            ) if status == "success" else None
            source_key = str(planned_verification.get("source_key") or "").strip()
            if provider == "public_web_browser" and source_key:
                source_hosts = rules.get("source_hosts", {}).get(source_key)
                final_host = (urlparse(common[0]).hostname or "").casefold()
                if not source_hosts or not _host_allowed(final_host, source_hosts):
                    raise ValueError("final_url is not bound to the planned official source_key")
                if normalized is not None:
                    normalized["source_key"] = source_key
            if status == "no_result" and not str(capture.get("result_message") or "").strip():
                raise ValueError("no_result verification requires an explicit result_message")
    except (KeyError, TypeError, ValueError, ProviderError) as exc:
        raise SystemExit(f"Invalid official registry capture: {exc}") from None

    error_code = ""
    detail = str(capture.get("detail") or capture.get("result_message") or "").strip()
    if status == "needs_user_action":
        error_code = "REGISTRY_USER_ACTION_REQUIRED"
        detail = detail or "The official registry requires user action in visible Chrome"
    elif status == "access_limited":
        error_code = "OFFICIAL_REGISTRY_ACCESS_LIMITED"
        detail = detail or "The official registry result could not be confirmed"
    elif status == "failed":
        error_code = "OFFICIAL_REGISTRY_CAPTURE_FAILED"
        detail = detail or "The official registry capture failed"

    evidence_type = (
        "official_verification" if args.operation == "candidate_verification"
        else "copyright" if args.right_type == "copyright"
        else "enforcement" if args.right_type == "enforcement"
        else "trademark" if args.right_type.startswith("trademark")
        else "patent"
    )
    raw_body = json.dumps(capture, ensure_ascii=False, sort_keys=True).encode("utf-8")
    run = record_result(
        task_dir,
        provider=provider,
        operation=args.operation,
        query=query,
        jurisdiction=jurisdiction,
        evidence_type=evidence_type,
        status=status,
        normalized=normalized,
        raw_body=raw_body,
        raw_suffix="json",
        error_code=error_code,
        detail=detail,
        mandatory=args.mandatory,
        request_params=request_params,
        query_id=effective_query_id,
    )
    print(json.dumps({
        "status": run["status"], "provider": provider,
        "operation": args.operation, "run_id": run["run_id"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

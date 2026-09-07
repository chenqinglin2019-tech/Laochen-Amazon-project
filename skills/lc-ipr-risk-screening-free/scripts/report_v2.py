#!/usr/bin/env python3
"""Build the schema-2.3 static report bundle from one canonical report data object."""

from __future__ import annotations

import base64
import csv
import html
import io
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from common import (
    CONFIDENCE_LEVELS, MODULE_IDS, RISK_LEVELS,
    assert_active_free_policy, assert_default_discovery_plan_contract, atomic_write_bytes,
    atomic_write_json, canonical_coverage_requirements_match, image_info, now_iso, path_within,
    optional_discovery_incomplete_queries, optional_discovery_provider_groups,
    sha256_bytes, sha256_json, stable_id, task_free_policy_valid,
)
from annotate_materiality import load_materiality_ledger, materiality_ledger_errors
from finalize_assessment import (
    coverage_requirement_gaps, formal_rating_evidence_by_module,
    material_unverified, required_query_gaps, verification_plan_binding_errors,
)
from provider_utils import SENSITIVE_REQUEST_KEYS as PROVIDER_SENSITIVE_REQUEST_KEYS


TASK_SCHEMA_VERSION = "2.3-free"
REPORT_SCHEMA_VERSION = "2.0"
REPORT_SCHEMA_NAME = f"IPR-EVIDENCE-DOSSIER/{REPORT_SCHEMA_VERSION}"
SECTION_ORDER = ["product", "decision", "coverage", "gaps", "modules", "visual", "candidates", "trace"]
VISUAL_LIMIT = 12
TERMINAL_SOURCE_STATUSES = {"success", "no_result", "not_applicable"}
IMAGE_MIME_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
OPTIONAL_DISCOVERY_PROVIDERS = {
    "serper_patents", "serper_web", "serper_images", "signa",
    "serpapi_google_patents",
}
MODULE_LABELS = {
    "appearance_patent": "外观设计 / 外观专利",
    "utility_patent": "实用 / 发明专利",
    "pending_application": "申请中专利",
    "word_mark": "文字商标",
    "figurative_trade_dress": "图形商标与商业外观",
    "figurative_mark": "图形商标",
    "trade_dress": "商业外观",
    "copyright_ip": "版权与创意资产",
    "enforcement": "公开维权信号",
    "enforcement_public_signals": "公开维权信号",
}
RISK_CSS = {"极低": "very-low", "低": "low", "中": "medium", "高": "high", "极高": "critical"}
SENSITIVE_QUERY_KEYS = {
    *(re.sub(r"[^a-z0-9]", "", key.casefold()) for key in PROVIDER_SENSITIVE_REQUEST_KEYS),
    "requesttoken", "token", "apikey", "key", "accesstoken", "clientsecret",
    "password", "passwd", "authorization", "auth", "session", "sessionid",
    "cookie", "setcookie", "refreshtoken", "idtoken", "bearer", "oauthcode",
}
AUTHORITY_BOUND_API_PROVIDERS = {
    "epo_ops", "euipo_trademark", "euipo_design", "jpo_api",
    "inpi_api", "prv_open_data",
}
# Report links are evidence links, not general web links. Keep this list aligned
# with the official registries accepted by the API/CDP recorders. A hostname may
# be the listed host itself or one of its subdomains; lookalike suffixes fail.
OFFICIAL_RECORD_HOSTS = frozenset({
    # United States
    "ppubs.uspto.gov", "patents.uspto.gov", "patentcenter.uspto.gov",
    "tsdr.uspto.gov", "tsdrsec.uspto.gov", "tmsearch.uspto.gov",
    # US public copyright and administrative-enforcement records. Keep the
    # concrete hosts aligned with public_web_browser's per-source bindings.
    "publicrecords.copyright.gov", "cocatalog.loc.gov", "copyright.gov", "www.copyright.gov",
    "ttabvue.uspto.gov", "ptab.uspto.gov",
    "ccb.gov", "www.ccb.gov", "dockets.ccb.gov",
    # Official public copyright/court sources for JP/EU/target countries
    "bunka.go.jp", "www.bunka.go.jp", "courts.go.jp", "www.courts.go.jp",
    "ip.courts.go.jp", "www.ip.courts.go.jp", "europa.eu", "curia.europa.eu",
    "rechtsprechung-im-internet.de", "www.rechtsprechung-im-internet.de",
    "bundesgerichtshof.de", "www.bundesgerichtshof.de",
    "courdecassation.fr", "www.courdecassation.fr",
    "giustizia.it", "www.giustizia.it", "poderjudicial.es", "www.poderjudicial.es",
    "judiciary.uk", "www.judiciary.uk", "caselaw.nationalarchives.gov.uk",
    "nationalarchives.gov.uk", "rechtspraak.nl", "www.rechtspraak.nl",
    "uitspraken.rechtspraak.nl", "overheid.nl", "www.overheid.nl",
    "justel.fgov.be", "juportal.be", "www.juportal.be",
    "domstol.se", "www.domstol.se", "gov.pl", "www.gov.pl",
    "orzeczenia.ms.gov.pl", "ms.gov.pl",
    # EPO / EUIPO
    "register.epo.org", "ops.epo.org", "euipo.europa.eu", "www.euipo.europa.eu",
    "api.euipo.europa.eu",
    # Japan
    "j-platpat.inpit.go.jp", "www.j-platpat.inpit.go.jp", "ip-data.jpo.go.jp",
    # National European registers used by the schema-2.3 routes
    "register.dpma.de", "dpma.de", "www.dpma.de",
    "data.inpi.fr", "inpi.fr", "www.inpi.fr", "api-gateway.inpi.fr",
    "uibm.mise.gov.it", "uibm.mimit.gov.it", "uibm.gov.it", "www.uibm.gov.it",
    "consultas2.oepm.es", "sede.oepm.gob.es", "oepm.es", "www.oepm.es",
    "gov.uk", "www.gov.uk", "ipo.gov.uk", "www.ipo.gov.uk",
    "trademarks.ipo.gov.uk", "registered-design.service.gov.uk",
    "www.registered-design.service.gov.uk", "patents.service.gov.uk",
    "mijnoctrooi.rvo.nl", "rvo.nl", "www.rvo.nl", "boip.int", "www.boip.int",
    "economie.fgov.be", "bpp.economie.fgov.be", "fgov.be",
    "tc.prv.se", "was.prv.se", "prv.se", "www.prv.se",
    "ewyszukiwarka.pue.uprp.gov.pl", "pue.uprp.gov.pl", "uprp.gov.pl", "www.uprp.gov.pl",
    # Cross-office official discovery views. Material candidates still require
    # the competent-office verification gate before a Formal report.
    "tmdn.org", "www.tmdn.org",
})
CSV_FIELDS = [
    "report_mode", "module_id", "module_name", "module_risk", "module_confidence",
    "finding_id", "title", "recommended_action", "evidence_refs",
]
DISCLAIMER = "本报告是面向 Amazon 卖家运营的知识产权风险初筛，不构成律师出具的法律意见、FTO 法律结论或不侵权保证。未检出记录不等于不存在权利。"
COVERAGE_BOUNDARIES = [
    "仅覆盖公开、已公布或已注册的权利。",
    "未公开申请、未登记版权及完整诉讼记录无法仅凭本免费流程排除。",
    "PCT 国际阶段特有程序信息不在本流程的专门覆盖内；已公开 WO 文献仅通过 EPO OPS 召回。",
]


def text(value: Any) -> str:
    return str(value if value is not None else "")


def esc(value: Any) -> str:
    return html.escape(text(value), quote=True)


def md_escape(value: Any) -> str:
    return text(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text(item).strip() for item in value if text(item).strip()]


def unique_strings(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(text(value).strip() for value in values if text(value).strip()))


def _sensitive_url_key(value: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", text(value).casefold())
    return normalized in SENSITIVE_QUERY_KEYS


def is_official_record_url(value: Any) -> bool:
    """Return whether value is an allowlisted, credential-free official HTTPS URL."""
    raw = text(value).strip()
    if not raw:
        return False
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").casefold().strip(".")
    if (
        parts.scheme.casefold() != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
    ):
        return False
    if any(_sensitive_url_key(key) for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        return False
    fragment_query = parts.fragment.lstrip("?")
    if any(_sensitive_url_key(key) for key, _ in parse_qsl(fragment_query, keep_blank_values=True)):
        return False
    if re.search(
        r"(?:^|[?&#;/])(?:request[-_]?token|access[-_]?token|refresh[-_]?token|id[-_]?token|"
        r"token|api[-_]?key|client[-_]?secret|password|passwd|authorization|session[-_]?id|cookie)=",
        parts.fragment,
        re.I,
    ):
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in OFFICIAL_RECORD_HOSTS)


def sanitize_url(value: Any) -> str:
    raw = text(value).strip()
    if not is_official_record_url(raw):
        return ""
    parts = urlsplit(raw)
    query = urlencode([
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not _sensitive_url_key(key)
    ])
    # Keep safe registry routing fragments (EUIPO eSearch uses them for record
    # details); is_official_record_url has already rejected credential-bearing
    # query strings and fragments.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def input_digests(
    task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any],
    candidates: dict[str, Any], journal: dict[str, Any], search_plan: dict[str, Any],
    materiality_ledger: dict[str, Any] | None = None,
) -> dict[str, str]:
    task_for_digest = {**task, "outputs": {}}
    return {
        "task": sha256_json(task_for_digest),
        "evidence": sha256_json(evidence),
        "assessment": sha256_json(assessment),
        "candidates": sha256_json(candidates),
        "candidate_journal": sha256_json(journal),
        "search_plan": sha256_json(search_plan),
        "materiality_annotations": sha256_json(
            materiality_ledger if materiality_ledger is not None else {
                "schema_version": "1.0", "task_id": task.get("task_id"), "annotations": [],
            }
        ),
    }


def _wipo_marker(value: Any) -> bool:
    normalized = text(value).casefold()
    return bool(
        "wipo_patentscope" in normalized
        or "patentscope.wipo.int" in normalized
        or re.search(r"(^|[^a-z])wipo([^a-z]|$)", normalized)
    )


def _scan_source_fields(value: Any, prefix: str, found: list[str]) -> None:
    source_fields = {
        "provider", "source", "registry", "url", "final_url", "raw_path", "raw_paths",
        "capture_path", "screenshot_path", "recorder", "recorded_by",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else text(key)
            if _wipo_marker(key):
                found.append(path)
            if text(key).casefold() in source_fields:
                values = item if isinstance(item, list) else [item]
                for candidate in values:
                    if _wipo_marker(candidate):
                        found.append(f"{path}={text(candidate)[:120]}")
            if isinstance(item, (dict, list)):
                _scan_source_fields(item, path, found)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_source_fields(item, f"{prefix}[{index}]", found)


def wipo_traces(
    task_dir: Path, task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any],
    journal: dict[str, Any], search_plan: dict[str, Any],
) -> list[str]:
    """Locate forbidden PATENTSCOPE provider/query/recorder traces in a 2.3 task."""
    found: list[str] = []
    for field in ("required_sources", "optional_sources", "low_risk_gate_sources"):
        for provider in task.get(field, []) if isinstance(task.get(field), list) else []:
            if _wipo_marker(provider):
                found.append(f"task.{field}={text(provider)}")
    _scan_source_fields(task.get("coverage_requirements", []), "task.coverage_requirements", found)
    queries = search_plan.get("queries", {})
    if isinstance(queries, dict):
        for provider, entries in queries.items():
            if _wipo_marker(provider):
                found.append(f"search_plan.queries.{provider}")
            _scan_source_fields(entries, f"search_plan.queries.{provider}", found)
    _scan_source_fields(evidence.get("source_runs", []), "evidence.source_runs", found)
    collections = evidence.get("collections", {})
    if isinstance(collections, dict):
        for name, records in collections.items():
            if _wipo_marker(name):
                found.append(f"evidence.collections.{name}")
            _scan_source_fields(records, f"evidence.collections.{name}", found)
    _scan_source_fields(journal, "candidate_journal", found)
    _scan_source_fields(candidates, "normalized_candidates", found)
    if task_dir.is_dir():
        for path in task_dir.rglob("*"):
            if path.is_file() and _wipo_marker(path.relative_to(task_dir).as_posix()):
                found.append(f"artifact:{path.relative_to(task_dir).as_posix()}")
    return sorted(set(found))


def assert_no_wipo_traces(
    task_dir: Path, task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any],
    journal: dict[str, Any], search_plan: dict[str, Any],
) -> None:
    traces = wipo_traces(task_dir, task, evidence, candidates, journal, search_plan)
    if traces:
        preview = "; ".join(traces[:8])
        suffix = f"; +{len(traces) - 8} more" if len(traces) > 8 else ""
        raise ValueError(f"2.3-free tasks prohibit WIPO source/query/recorder traces: {preview}{suffix}")


def _candidate_identifier(item: dict[str, Any]) -> str:
    keys = (
        "publication_number", "grant_number", "application_number", "serial_number",
        "registration_number", "record_number", "design_number", "case_number",
        "docket_number",
    )
    return next((text(item.get(key)).strip() for key in keys if text(item.get(key)).strip()), "")


def _owner_text(item: dict[str, Any]) -> str:
    direct = text(
        item.get("owner") or item.get("claimant") or item.get("plaintiff")
        or item.get("assignee") or item.get("applicant")
    ).strip()
    if direct:
        return direct
    owners = item.get("owners")
    if not isinstance(owners, list):
        return ""
    values: list[str] = []
    for owner in owners:
        if isinstance(owner, dict):
            name = text(owner.get("name") or owner.get("owner") or owner.get("applicant")).strip()
        else:
            name = text(owner).strip()
        if name:
            values.append(name)
    return ", ".join(unique_strings(values))


def _candidate_module(collection: str, item: dict[str, Any]) -> str:
    right_type = text(item.get("right_type") or item.get("type")).casefold().replace("-", "_").replace(" ", "_")
    mapping = {
        "appearance_patent": "appearance_patent", "design": "appearance_patent",
        "design_patent": "appearance_patent", "industrial_design": "appearance_patent",
        "utility_model": "utility_patent", "utility_patent": "utility_patent",
        "invention_patent": "utility_patent", "patent": "utility_patent",
        "pending_application": "pending_application", "application": "pending_application",
        "word_mark": "word_mark", "word_trademark": "word_mark", "trademark_word": "word_mark", "trademark": "word_mark",
        "figurative_mark": "figurative_trade_dress", "figurative_trademark": "figurative_trade_dress",
        "trademark_figurative": "figurative_trade_dress",
        "trade_dress": "figurative_trade_dress", "copyright": "copyright_ip",
        "enforcement": "enforcement",
    }
    if right_type == "patent" and text(item.get("kind_code")).upper().startswith("A"):
        return "pending_application"
    if right_type in mapping:
        return mapping[right_type]
    if collection == "trademarks":
        return "word_mark"
    if collection == "patents":
        identifier = _candidate_identifier(item).upper()
        return "appearance_patent" if re.match(r"^(US)?D\d", identifier) else "utility_patent"
    return ""


def _candidate_evidence_refs(item: dict[str, Any]) -> list[str]:
    refs: list[Any] = []
    for key in ("evidence_refs", "verification_refs"):
        if isinstance(item.get(key), list):
            refs.extend(item[key])
    for source in item.get("sources", []) if isinstance(item.get("sources"), list) else []:
        if isinstance(source, dict) and source.get("evidence_id"):
            refs.append(source["evidence_id"])
    verification = item.get("official_verification")
    if isinstance(verification, dict):
        for key in ("evidence_ref", "verification_id"):
            if verification.get(key):
                refs.append(verification[key])
        if isinstance(verification.get("evidence_refs"), list):
            refs.extend(verification["evidence_refs"])
    return unique_strings(refs)


def _candidate_collections(candidates: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    collections: list[tuple[str, list[Any]]] = []
    for name in ("patents", "trademarks", "copyright_assets", "enforcement"):
        value = candidates.get(name)
        if isinstance(value, list):
            collections.append((name, value))
    known = {name for name, _ in collections}
    candidate_keys = {
        "candidate_id", "publication_number", "serial_number", "registration_number",
        "record_number", "title", "mark_text", "right_type", "module", "module_id",
    }
    for name, value in candidates.items():
        if name in known or not isinstance(value, list) or not value:
            continue
        if all(isinstance(item, dict) and candidate_keys.intersection(item) for item in value):
            collections.append((text(name), value))
    return collections


def candidate_rows(candidates: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one compact reporting row for every normalized candidate."""
    collections = _candidate_collections(candidates)

    rows: list[dict[str, Any]] = []
    used_ids: dict[str, int] = {}
    for collection, values in collections:
        for index, raw in enumerate(values):
            item = raw if isinstance(raw, dict) else {"title": text(raw)}
            source_id = text(item.get("candidate_id") or item.get("normalization_key")).strip()
            base_id = source_id or stable_id("C", collection, sha256_json(item), length=20)
            used_ids[base_id] = used_ids.get(base_id, 0) + 1
            report_id = base_id if used_ids[base_id] == 1 else f"{base_id}~{used_ids[base_id]}"
            verification = item.get("official_verification") if isinstance(item.get("official_verification"), dict) else {}
            source_names = unique_strings(
                source.get("provider") or source.get("source")
                for source in item.get("sources", []) if isinstance(item.get("sources"), list) and isinstance(source, dict)
            )
            material = bool(item.get("material")) or text(item.get("disposition")).casefold() in {"material", "risk_bearing"}
            disposition = text(item.get("disposition")).strip() or ("material" if material else "not_material")
            score = next((item.get(key) for key in ("similarity", "similarity_score", "visual_similarity", "score") if item.get(key) is not None), "")
            rows.append({
                "candidate_id": report_id,
                "source_candidate_id": source_id,
                "source_collection": collection,
                "source_index": index,
                "module_id": _candidate_module(collection, item),
                "module_name": MODULE_LABELS.get(_candidate_module(collection, item), _candidate_module(collection, item) or "未映射"),
                "right_type": text(item.get("right_type") or {
                    "patents": "patent", "trademarks": "trademark_word",
                    "copyright_assets": "copyright", "enforcement": "enforcement",
                }.get(collection, "")),
                "jurisdiction": text(item.get("jurisdiction") or item.get("office")),
                "record_number": _candidate_identifier(item),
                "title": text(item.get("title") or item.get("mark_text") or "未命名候选"),
                "owner": _owner_text(item),
                "status": text(item.get("status") or item.get("legal_status")),
                "material": material,
                "material_reason": text(item.get("material_reason") or item.get("relevance")),
                "disposition": disposition,
                "similarity": text(score),
                "evidence_refs": _candidate_evidence_refs(item),
                "sources": source_names,
                "official_verification": {
                    "status": text(verification.get("status") or "not_checked"),
                    "authority": text(verification.get("authority")),
                    "source": text(verification.get("source")),
                    "method": text(verification.get("method")),
                    "identity_match": verification.get("identity_match"),
                    "legal_status": text(verification.get("legal_status")),
                    "owner": verification.get("owner") or verification.get("owners") or [],
                    "classes": verification.get("classes") or [],
                    "media": verification.get("media") or [],
                    "url": sanitize_url(verification.get("url")),
                    "checked_at": text(verification.get("checked_at")),
                },
                "url": sanitize_url(verification.get("url") or item.get("url")),
            })
    return rows


def _image_label(path: Path, role: str) -> str:
    if role == "main":
        return "Amazon 当前变体主图"
    name = path.stem.casefold()
    labels = (
        ("figure", "专利或外观图样"), ("drawing", "专利或外观图样"),
        ("patent", "专利登记核验证据"), ("tsdr", "商标官方核验证据"),
        ("tmsearch", "商标检索证据"), ("trademark", "商标图样证据"),
        ("design", "外观登记图样"), ("product", "商品页面冻结证据"),
    )
    for needle, label in labels:
        if needle in name:
            return label
    return role.replace("_", " ").strip().title() or path.stem.replace("-", " ").title()


def _declared_bytes(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _bound_visual_paths(value: Any, prefix: str = "") -> Iterable[dict[str, Any]]:
    """Yield only paths carrying an adjacent declared SHA-256 and byte count."""
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _bound_visual_paths(item, f"{prefix}[{index}]")
        return
    if not isinstance(value, dict):
        return

    screenshot_paths = value.get("screenshots")
    screenshot_hashes = value.get("screenshot_hashes")
    screenshot_bytes = value.get("screenshot_bytes") or value.get("screenshot_byte_counts")
    if isinstance(screenshot_paths, dict) and isinstance(screenshot_hashes, dict) and isinstance(screenshot_bytes, dict):
        for role, path_value in screenshot_paths.items():
            yield {
                "binding_path": f"{prefix}.screenshots.{role}" if prefix else f"screenshots.{role}",
                "path": path_value,
                "sha256": screenshot_hashes.get(role),
                "bytes": screenshot_bytes.get(role),
                "role": text(role),
                "label": "",
                "mime_type": "",
            }

    for key, path_value in value.items():
        normalized = text(key).casefold()
        if not isinstance(path_value, str) or not (normalized == "path" or normalized.endswith("_path")):
            continue
        stem = normalized[:-5] if normalized.endswith("_path") else ""
        hash_keys = ([f"{stem}_sha256"] if stem else []) + ([f"{stem}_hash"] if stem else []) + ["sha256"]
        byte_keys = (
            ([f"{stem}_bytes", f"{stem}_byte_count", f"{stem}_size_bytes"] if stem else [])
            + ["bytes", "byte_count", "size_bytes", "file_bytes"]
        )
        declared_hash = next((value.get(name) for name in hash_keys if value.get(name) is not None), None)
        declared_size = next((value.get(name) for name in byte_keys if value.get(name) is not None), None)
        yield {
            "binding_path": f"{prefix}.{key}" if prefix else text(key),
            "path": path_value,
            "sha256": declared_hash,
            "bytes": declared_size,
            "role": text(value.get("role") or stem or key),
            "label": text(value.get("label")),
            "mime_type": text(value.get("mime_type") or value.get("content_type")).split(";", 1)[0].strip().casefold(),
        }

    for key, item in value.items():
        if isinstance(item, (dict, list)):
            current = f"{prefix}.{key}" if prefix else text(key)
            yield from _bound_visual_paths(item, current)


def _credible_similarity(item: dict[str, Any]) -> float | None:
    """Accept only explicitly sourced, reliable similarity with a declared scale."""
    metadata = item.get("similarity_metadata") if isinstance(item.get("similarity_metadata"), dict) else {}
    reliable = item.get("similarity_reliable") is True or metadata.get("reliable") is True
    source = text(
        item.get("similarity_source") or item.get("similarity_method")
        or metadata.get("source") or metadata.get("method")
    ).strip()
    if not reliable or not source:
        return None
    field = next(
        (key for key in ("similarity_percent", "similarity", "similarity_score", "visual_similarity") if item.get(key) is not None),
        "",
    )
    raw = item.get(field) if field else None
    if raw is None or isinstance(raw, bool):
        return None
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score) or score < 0:
        return None
    scale = text(item.get("similarity_scale") or metadata.get("scale")).strip().casefold()
    if field == "similarity_percent":
        scale = scale or "0-100"
    if scale in {"0-1", "ratio", "fraction"}:
        if score > 1:
            return None
        score *= 100
    elif scale not in {"0-100", "percent", "percentage"}:
        return None
    return round(score, 6) if score <= 100 else None


def _validated_visual_record(
    task_dir: Path, binding: dict[str, Any], *, source: str,
    candidate_id: str = "", material: bool = False, risk: str = "",
    similarity: float | None = None, role_override: str = "",
) -> dict[str, Any] | None:
    """Validate one declared local image before it can be omitted or embedded."""
    raw = text(binding.get("path")).strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    path = path.resolve() if path.is_absolute() else (task_dir / path).resolve()
    suffix_mime = IMAGE_MIME_TYPES.get(path.suffix.casefold(), "")
    declared_mime = text(binding.get("mime_type")).split(";", 1)[0].strip().casefold()
    mime_type = declared_mime or suffix_mime
    if mime_type not in set(IMAGE_MIME_TYPES.values()):
        return None
    binding_path = text(binding.get("binding_path") or raw)
    if not path.is_file() or not path_within(path, task_dir):
        raise ValueError(f"Declared visual is missing or outside the task: {binding_path}")
    declared_hash = text(binding.get("sha256")).casefold().strip()
    declared_size = _declared_bytes(binding.get("bytes"))
    if not re.fullmatch(r"[0-9a-f]{64}", declared_hash) or declared_size is None:
        raise ValueError(f"Declared visual has no valid SHA-256/byte binding: {binding_path}")
    blob = path.read_bytes()
    digest = sha256_bytes(blob)
    if not blob or digest != declared_hash or len(blob) != declared_size:
        raise ValueError(f"Declared visual hash/byte mismatch: {binding_path}")
    try:
        detected_mime, _, _ = image_info(path)
    except ValueError as exc:
        raise ValueError(f"Declared visual is not a supported image: {binding_path}") from exc
    if detected_mime != mime_type or (suffix_mime and suffix_mime != detected_mime):
        raise ValueError(f"Declared visual MIME/extension mismatch: {binding_path}")
    relative = Path(os.path.relpath(path, task_dir)).as_posix()
    role = role_override or text(binding.get("role") or "evidence")
    similarity_display = "未评分" if similarity is None else f"{similarity:g}%"
    return {
        "evidence_id": stable_id("VIS", digest, length=16),
        "label": text(binding.get("label")) or _image_label(path, role),
        "role": role,
        "source": source,
        "candidate_id": candidate_id,
        "material": material,
        "risk": risk if risk in RISK_LEVELS else "",
        "similarity": similarity,
        "similarity_display": similarity_display,
        "binding_path": binding_path,
        "relative_path": relative,
        "mime_type": mime_type,
        "sha256": declared_hash,
        "bytes": declared_size,
        "data_uri": f"data:{mime_type};base64,{base64.b64encode(blob).decode('ascii')}",
    }


def main_visual_evidence(task_dir: Path, task: dict[str, Any]) -> dict[str, Any] | None:
    """Return the validated product hero independently of the 12 evidence cards."""
    records: list[dict[str, Any]] = []
    for index, image in enumerate(task.get("images", []) if isinstance(task.get("images"), list) else []):
        if not isinstance(image, dict):
            continue
        for binding in _bound_visual_paths(image, f"task.images[{index}]"):
            record = _validated_visual_record(
                task_dir, binding, source="amazon_browser", role_override="main",
            )
            if record:
                records.append(record)
    if not records:
        return None
    if len({record["sha256"] for record in records}) != 1:
        raise ValueError("Task declares more than one distinct product main visual")
    return records[0]


def visual_evidence(
    task_dir: Path, task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any],
    assessment: dict[str, Any],
) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    module_risks = {
        text(module_id): text(module.get("risk"))
        for module_id, module in assessment.get("modules", {}).items()
        if isinstance(assessment.get("modules"), dict) and isinstance(module, dict)
    }
    report_rows = {
        (row["source_collection"], row["source_index"]): row for row in candidate_rows(candidates)
    }

    def add(
        binding: dict[str, Any], *, source: str, candidate_id: str = "", material: bool = False,
        risk: str = "", similarity: float | None = None,
    ) -> None:
        record = _validated_visual_record(
            task_dir, binding, source=source, candidate_id=candidate_id,
            material=material, risk=risk, similarity=similarity,
        )
        if record:
            pending.append(record)

    for collection, values in _candidate_collections(candidates):
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            row = report_rows.get((collection, index), {})
            material = bool(row.get("material"))
            risk = text(item.get("risk") or item.get("risk_level") or module_risks.get(text(row.get("module_id"))))
            similarity = _credible_similarity(item)
            for binding in _bound_visual_paths(item, f"candidates.{collection}[{index}]"):
                add(
                    binding, source=collection, candidate_id=text(row.get("candidate_id")),
                    material=material, risk=risk, similarity=similarity,
                )

    collections = evidence.get("collections", {})
    if isinstance(collections, dict):
        for collection_name, collection in collections.items():
            for binding in _bound_visual_paths(collection, f"evidence.collections.{collection_name}"):
                add(binding, source=text(collection_name))

    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        risk_rank = RISK_LEVELS.index(item["risk"]) if item.get("risk") in RISK_LEVELS else -1
        similarity = item.get("similarity")
        return (
            0 if item.get("material") else 1,
            -risk_rank,
            0 if similarity is not None else 1,
            -(similarity or 0),
            text(item.get("candidate_id")).casefold(),
            text(item.get("relative_path")).casefold(),
            text(item.get("source")).casefold(),
            text(item.get("binding_path")).casefold(),
        )

    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for item in sorted(pending, key=sort_key):
        if item["sha256"] in seen_hashes:
            continue
        seen_hashes.add(item["sha256"])
        records.append(item)
        if len(records) == VISUAL_LIMIT:
            break
    return records


def _unresolved_journal(journal: dict[str, Any]) -> list[str]:
    unresolved: list[str] = []
    for entry in journal.get("entries", []) if isinstance(journal.get("entries"), list) else []:
        if not isinstance(entry, dict):
            continue
        if text(entry.get("status")) in {"pending", "needs_user_action", "access_limited", "failed"}:
            unresolved.append(text(entry.get("record_number") or entry.get("candidate_id") or "unknown"))
    return sorted(set(unresolved))


def coverage_gap_groups(task: dict[str, Any], requirement_gaps: Iterable[Any]) -> dict[str, list[str]]:
    """Split active coverage gaps into absolute, formal and low-risk-only gates."""
    gaps = unique_strings(requirement_gaps)
    requirements_by_id = {
        text(item.get("requirement_id")): item
        for item in task.get("coverage_requirements", [])
        if isinstance(item, dict) and text(item.get("requirement_id"))
    }
    unsupported = [gap for gap in gaps if gap.startswith("UNSUPPORTED_JURISDICTION_ROUTE:")]
    low_risk = [
        gap for gap in gaps
        if gap not in unsupported
        and isinstance(requirements_by_id.get(gap), dict)
        and requirements_by_id[gap].get("required_for") == "low_risk"
    ]
    formal = [gap for gap in gaps if gap not in {*unsupported, *low_risk}]
    return {"all": gaps, "formal": formal, "low_risk": low_risk, "unsupported": unsupported}


def release_gate(
    task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any],
    candidates: dict[str, Any], journal: dict[str, Any], search_plan: dict[str, Any],
) -> dict[str, Any]:
    requirement_gaps = coverage_requirement_gaps(task, evidence, candidates, search_plan)
    query_gaps = required_query_gaps(task, evidence, search_plan)
    unverified = material_unverified(
        candidates, strict=True, evidence=evidence, task=task,
        search_plan=search_plan,
    )
    unresolved = _unresolved_journal(journal)
    coverage = assessment.get("coverage", {}) if isinstance(assessment.get("coverage"), dict) else {}
    blockers: list[dict[str, Any]] = []
    grouped_gaps = coverage_gap_groups(task, requirement_gaps)
    unsupported_gaps = grouped_gaps["unsupported"]
    low_risk_gaps = grouped_gaps["low_risk"]
    formal_gaps = grouped_gaps["formal"]

    def block(code: str, scope: str, detail: str, items: Iterable[Any] = ()) -> None:
        blockers.append({"code": code, "scope": scope, "detail": detail, "items": unique_strings(items)})

    if not task_free_policy_valid(task):
        block("FREE_POLICY_INVALID", "task.free_policy", "2.3 任务的免费执行策略已被修改。")
    verification_binding_errors = verification_plan_binding_errors(
        task, evidence, candidates, search_plan,
    )
    if verification_binding_errors:
        block(
            "OFFICIAL_VERIFICATION_PLAN_BINDING_INVALID", "official_verifications",
            "官方核验证据无法反查到唯一、参数一致的计划动作。",
            verification_binding_errors,
        )
    if assessment.get("status") != "completed":
        block("ASSESSMENT_NOT_FINALIZED", "assessment", "评估尚未完成，报告只能作为 Draft。")
    known_evidence = {
        text(entry.get("evidence_id")).strip()
        for values in evidence.get("collections", {}).values()
        if isinstance(values, list)
        for entry in values
        if isinstance(entry, dict) and text(entry.get("evidence_id")).strip()
    }
    module_contract_errors = assessment_module_errors(
        assessment, known_evidence=known_evidence,
        formal_risk_evidence=formal_rating_evidence_by_module(
            task, evidence, candidates, search_plan,
        ),
    )
    if module_contract_errors:
        block(
            "ASSESSMENT_MODULES_INVALID", "assessment.modules",
            "评估必须包含字段完整且合法的固定七模块。", module_contract_errors,
        )
    requirements = task.get("coverage_requirements")
    if not isinstance(requirements, list) or not requirements:
        block("COVERAGE_REQUIREMENTS_MISSING", "task.coverage_requirements", "2.3 任务没有可验证的覆盖要求。")
    elif not canonical_coverage_requirements_match(task):
        block(
            "COVERAGE_REQUIREMENTS_INVALID", "task.coverage_requirements",
            "2.3 任务的覆盖要求与目标法域的规范路由不一致。",
        )
    if task.get("state") != "completed":
        block("TASK_NOT_COMPLETED", "task", f"任务状态为 {text(task.get('state') or 'unknown')}。")
    overall = assessment.get("overall", {}) if isinstance(assessment.get("overall"), dict) else {}
    if overall.get("risk") not in RISK_LEVELS:
        block("FINAL_RISK_MISSING", "assessment.overall", "没有有效的正式总风险等级。")
    if overall.get("provisional") is not False:
        block("ASSESSMENT_PROVISIONAL", "assessment.overall", "评估仍标记为 provisional。")
    review = assessment.get("review", {}) if isinstance(assessment.get("review"), dict) else {}
    if review.get("human_review_required") is True:
        block("HUMAN_REVIEW_REQUIRED", "assessment.review", "仍需人工复核。")
    if unsupported_gaps:
        block(
            "UNSUPPORTED_JURISDICTION_ROUTE", "coverage",
            "存在没有受支持官方核验路径的目标法域，不能发布正式报告。", unsupported_gaps,
        )
    if formal_gaps:
        block("FORMAL_COVERAGE_INCOMPLETE", "coverage", "正式报告必需的覆盖要求尚未满足。", formal_gaps)
    if low_risk_gaps and overall.get("risk") in {"极低", "低"}:
        block(
            "LOW_RISK_COVERAGE_INCOMPLETE", "coverage",
            "低风险结论所需的召回覆盖尚未满足。", low_risk_gaps,
        )
    if query_gaps:
        block("QUERY_COVERAGE_INCOMPLETE", "coverage", "仍有未完成的必需查询。", query_gaps)
    if unverified:
        block(
            "CANDIDATE_REVIEW_OR_VERIFICATION_INCOMPLETE", "candidates",
            "仍有候选未完成实质性审阅、存在未解除的身份不匹配，或重大候选未完成官方核验。",
            unverified,
        )
    if unresolved:
        block("BROWSER_CANDIDATE_UNRESOLVED", "candidate_journal", "浏览器候选日志仍有未解决项。", unresolved)

    comparisons = (
        ("missing_coverage_requirements", requirement_gaps),
        ("missing_formal_requirements", formal_gaps),
        ("missing_low_risk_requirements", [*low_risk_gaps, *unsupported_gaps]),
        ("missing_required_queries", query_gaps),
        ("unverified_material_candidates", unverified),
        ("missing_low_risk_gate_sources", []),
    )
    stale_fields = [
        key for key, recomputed in comparisons
        if sorted(string_list(coverage.get(key))) != sorted(unique_strings(recomputed))
    ]
    if stale_fields:
        block("COVERAGE_BINDING_STALE", "assessment.coverage", "评估中的覆盖绑定与当前证据不一致。", stale_fields)
    discovery_risk = overall.get("discovery_signal") if overall.get("discovery_signal") in RISK_LEVELS else "无法判断"
    formal_allowed = not blockers
    return {
        "report_mode": "Formal" if formal_allowed else "Draft",
        "formal_allowed": formal_allowed,
        "final_risk": overall.get("risk") if formal_allowed else None,
        "display_risk": overall.get("risk") if formal_allowed else discovery_risk,
        "confidence": overall.get("confidence") if formal_allowed else "无法判断",
        "risk_basis": "formal_assessment" if formal_allowed else "discovery_only",
        "blockers": blockers,
        "computed": {
            "missing_coverage_requirements": unique_strings(requirement_gaps),
            "missing_formal_requirements": unique_strings(formal_gaps),
            "missing_low_risk_requirements": unique_strings([*low_risk_gaps, *unsupported_gaps]),
            "unsupported_jurisdiction_routes": unique_strings(unsupported_gaps),
            "missing_required_queries": unique_strings(query_gaps),
            "unverified_material_candidates": unique_strings(unverified),
            "unresolved_browser_candidates": unique_strings(unresolved),
            "optional_source_losses": unique_strings(coverage.get("optional_source_losses", [])),
        },
    }


def _query_rows(search_plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    queries = search_plan.get("queries", {})
    if not isinstance(queries, dict):
        return rows
    for provider, entries in queries.items():
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            rows.append({
                "provider": text(provider),
                "query_id": text(entry.get("query_id") or f"{provider}:{index + 1}"),
                "operation": text(entry.get("operation")),
                "jurisdiction": text(entry.get("jurisdiction")),
                "right_type": text(entry.get("right_type")),
                "requirement_ids": unique_strings(entry.get("requirement_ids", [])),
                "required": entry.get("required", True) is not False,
                "module_id": text(entry.get("module_id") or entry.get("module")),
            })
    return rows


def _jurisdiction_tokens(value: Any) -> set[str]:
    return {
        part.strip().upper() for part in text(value).split(",") if part.strip()
    }


def planned_query_completed(query: dict[str, Any], evidence: dict[str, Any]) -> bool:
    """Require a fully bound authoritative terminal run for one planned query."""
    provider = text(query.get("provider"))
    query_id = text(query.get("query_id"))
    if not provider or not query_id:
        return False
    expected_requirements = set(unique_strings(query.get("requirement_ids", [])))
    for run in evidence.get("source_runs", []) if isinstance(evidence.get("source_runs"), list) else []:
        if not isinstance(run, dict) or run.get("status") not in {"success", "no_result"}:
            continue
        if text(run.get("provider")) != provider or text(run.get("query_id")) != query_id:
            continue
        if text(run.get("operation")) != text(query.get("operation")):
            continue
        if _jurisdiction_tokens(run.get("jurisdiction")) != _jurisdiction_tokens(query.get("jurisdiction")):
            continue
        if text(run.get("right_type")) != text(query.get("right_type")):
            continue
        if set(unique_strings(run.get("requirement_ids", []))) != expected_requirements:
            continue
        if provider in AUTHORITY_BOUND_API_PROVIDERS and not (
            run.get("authoritative_for_final_rating") is True
            and text(run.get("source_environment")) == "production"
        ):
            continue
        return True
    return False


def required_query_completion(
    search_plan: dict[str, Any], evidence: dict[str, Any],
) -> tuple[int, int]:
    required = [row for row in _query_rows(search_plan) if row["required"]]
    completed = sum(1 for row in required if planned_query_completed(row, evidence))
    return len(required), completed


def _source_runs(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in evidence.get("source_runs", []) if isinstance(evidence.get("source_runs"), list) else []:
        if not isinstance(run, dict):
            continue
        rows.append({
            "run_id": text(run.get("run_id")),
            "query_id": text(run.get("query_id")),
            "provider": text(run.get("provider")),
            "operation": text(run.get("operation")),
            "jurisdiction": text(run.get("jurisdiction")),
            "status": text(run.get("status")),
            "error_code": text(run.get("error_code")),
            "started_at": text(run.get("started_at")),
            "finished_at": text(run.get("finished_at")),
        })
    return rows


def _source_summary(source_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in source_runs:
        grouped.setdefault(run["provider"] or "unknown", []).append(run)
    summary: list[dict[str, Any]] = []
    for provider in sorted(grouped):
        runs = grouped[provider]
        terminal = sum(1 for run in runs if run["status"] in TERMINAL_SOURCE_STATUSES)
        statuses = unique_strings(run["status"] for run in runs)
        summary.append({
            "provider": provider,
            "attempted": len(runs),
            "terminal": terminal,
            "statuses": statuses,
            "complete": terminal == len(runs),
        })
    return summary


def default_discovery_degradations(
    task: dict[str, Any], evidence: dict[str, Any], search_plan: dict[str, Any],
) -> list[dict[str, str]]:
    """Expose selected optional-source failures separately from release blockers."""
    groups = optional_discovery_provider_groups(task)
    selected = set().union(*groups.values()) if groups else set()
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for gap in task.get("coverage_gaps", []):
        if (
            not isinstance(gap, dict)
            or gap.get("provider") not in OPTIONAL_DISCOVERY_PROVIDERS
            or gap.get("provider") not in selected
        ):
            continue
        if gap.get("mandatory") is not False or gap.get("status") not in {
            "access_limited", "needs_user_action", "failed",
        }:
            continue
        key = (
            text(gap.get("provider")), text(gap.get("query_id")),
            text(gap.get("error_code")), text(gap.get("jurisdiction")),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "provider": key[0], "query_id": key[1], "error_code": key[2],
            "jurisdiction": key[3], "status": text(gap.get("status")),
            "detail": text(gap.get("detail")), "at": text(gap.get("at")),
        })
    represented_groups = {
        logical_provider
        for logical_provider, providers in groups.items()
        if any(row["provider"] in providers for row in rows)
    }
    for logical_provider, query_ids in optional_discovery_incomplete_queries(
        task, evidence, search_plan,
    ).items():
        if logical_provider in represented_groups:
            continue
        detail = (
            "已选择该可选来源，但未生成可执行的计划查询"
            if query_ids == ["not_planned"] else
            "已选择的可选发现查询尚未完成："
            + ", ".join(query_ids)
        )
        rows.append({
            "provider": logical_provider,
            "query_id": "",
            "error_code": "OPTIONAL_DISCOVERY_NOT_COMPLETED",
            "jurisdiction": "",
            "status": "needs_user_action",
            "detail": detail,
            "at": "",
        })
    return sorted(rows, key=lambda row: (
        row["provider"], row["jurisdiction"], row["error_code"], row["query_id"],
    ))


def paid_recommendation_rows(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize advisory-only paid upgrades; execution and spend remain disabled."""
    rows: list[dict[str, Any]] = []
    for item in assessment.get("paid_recommendations", []) if isinstance(assessment.get("paid_recommendations"), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            estimated_calls = max(0, int(item.get("estimated_calls") or 0))
        except (TypeError, ValueError):
            estimated_calls = 0
        cost_cap = item.get("cost_cap") if isinstance(item.get("cost_cap"), dict) else {}
        raw_cap = cost_cap.get("amount")
        proposed_amount: int | float | None
        if isinstance(raw_cap, bool) or raw_cap in (None, ""):
            proposed_amount = None
        else:
            try:
                proposed_amount = float(raw_cap)
                if proposed_amount < 0 or not math.isfinite(proposed_amount):
                    proposed_amount = None
                elif proposed_amount.is_integer():
                    proposed_amount = int(proposed_amount)
            except (TypeError, ValueError):
                proposed_amount = None
        rows.append({
            "recommendation_id": text(item.get("recommendation_id")),
            "provider": text(item.get("provider")),
            "jurisdiction": text(item.get("jurisdiction")),
            "module": text(item.get("module")),
            "missing_fields": string_list(item.get("missing_fields")),
            "estimated_calls": estimated_calls,
            "free_exhaustion_evidence": string_list(item.get("free_exhaustion_evidence")),
            "cost_cap": {
                "amount": proposed_amount,
                "currency": text(cost_cap.get("currency") or "USD"),
                "status": text(cost_cap.get("status") or (
                    "set" if proposed_amount is not None else "quote_required"
                )),
                "basis": text(cost_cap.get("basis") or "需核验供应商报价并由用户设定数值上限。"),
            },
            "authorized_spend_cap": {
                "amount": 0,
                "currency": "USD",
                "basis": "未获用户明确批准，不允许执行付费请求。",
            },
            "approval_required": True,
            "automatic_execution": False,
        })
    return rows


def assessment_module_errors(
    assessment: dict[str, Any], *, known_evidence: set[str] | None = None,
    formal_risk_evidence: dict[str, set[str]] | None = None,
) -> list[str]:
    """Validate the fixed seven-module assessment contract used by reports."""
    modules = assessment.get("modules")
    if not isinstance(modules, dict):
        return ["assessment.modules must be an object containing exactly the seven required modules"]
    actual_ids = set(modules)
    expected_ids = set(MODULE_IDS)
    errors: list[str] = []
    formal_backed_modules: set[str] = set()
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        unexpected = sorted(actual_ids - expected_ids)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        errors.append(
            "assessment.modules must contain exactly the seven required modules: "
            + "; ".join(detail)
        )
    for module_id in MODULE_IDS:
        module = modules.get(module_id)
        if not isinstance(module, dict):
            if module_id in modules:
                errors.append(f"assessment.modules.{module_id} must be an object")
            continue
        if module.get("risk") not in RISK_LEVELS:
            errors.append(f"assessment.modules.{module_id}.risk is invalid")
        if module.get("confidence") not in CONFIDENCE_LEVELS:
            errors.append(f"assessment.modules.{module_id}.confidence is invalid")
        if not text(module.get("reasoning")).strip():
            errors.append(f"assessment.modules.{module_id}.reasoning is required")
        findings = module.get("findings")
        if not isinstance(findings, list):
            errors.append(f"assessment.modules.{module_id}.findings must be an array")
            continue
        if (
            module.get("risk") in RISK_LEVELS
            and RISK_LEVELS.index(module["risk"]) >= RISK_LEVELS.index("中")
            and not findings
        ):
            errors.append(
                f"assessment.modules.{module_id} risk-bearing conclusion requires an evidence-backed finding"
            )
        for index, finding in enumerate(findings):
            prefix = f"assessment.modules.{module_id}.findings[{index}]"
            if not isinstance(finding, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for field in ("finding_id", "title", "recommended_action"):
                if not text(finding.get(field)).strip():
                    errors.append(f"{prefix}.{field} is required")
            refs = finding.get("evidence_refs")
            if (
                not isinstance(refs, list) or not refs
                or any(not text(ref).strip() for ref in refs)
            ):
                errors.append(f"{prefix}.evidence_refs must be a non-empty string array")
            elif known_evidence is not None:
                unknown = sorted({
                    text(ref).strip() for ref in refs
                    if text(ref).strip() not in known_evidence
                })
                if unknown:
                    errors.append(f"{prefix}.evidence_refs contains unknown evidence: {','.join(unknown)}")
            if (
                isinstance(refs, list)
                and formal_risk_evidence is not None
                and set(unique_strings(refs)) & formal_risk_evidence.get(module_id, set())
            ):
                formal_backed_modules.add(module_id)
        if (
            module.get("risk") in RISK_LEVELS
            and RISK_LEVELS.index(module["risk"]) >= RISK_LEVELS.index("中")
            and formal_risk_evidence is not None
            and module_id not in formal_backed_modules
        ):
            errors.append(
                f"assessment.modules.{module_id} risk-bearing conclusion requires an exact planned "
                "official verification for a material candidate in the same module"
            )
    overall_risk = assessment.get("overall", {}).get("risk")
    if (
        assessment.get("status") == "completed"
        and overall_risk in RISK_LEVELS
        and RISK_LEVELS.index(overall_risk) >= RISK_LEVELS.index("中")
        and not (
            bool(formal_backed_modules)
            if formal_risk_evidence is not None
            else any(
                isinstance(module, dict) and bool(module.get("findings"))
                for module in modules.values()
            )
        )
    ):
        errors.append("completed medium/high overall risk requires formally eligible evidence-backed findings")
    return errors


def _module_rows(assessment: dict[str, Any], rows: list[dict[str, Any]], report_mode: str) -> list[dict[str, Any]]:
    modules = assessment["modules"]
    result: list[dict[str, Any]] = []
    for module_id in MODULE_IDS:
        module = modules[module_id]
        module_candidates = [row for row in rows if row["module_id"] == module_id]
        findings: list[dict[str, Any]] = []
        for index, finding in enumerate(module.get("findings", []) if isinstance(module.get("findings"), list) else []):
            if not isinstance(finding, dict):
                continue
            findings.append({
                "finding_id": text(finding.get("finding_id") or stable_id("F", module_id, str(index), sha256_json(finding), length=16)),
                "title": text(finding.get("title") or "未命名发现"),
                "recommended_action": text(finding.get("recommended_action")),
                "evidence_refs": unique_strings(finding.get("evidence_refs", [])),
            })
        result.append({
            "module_id": module_id,
            "module_name": MODULE_LABELS.get(module_id, module_id),
            "risk": text(module.get("risk")) if report_mode == "Formal" else "无法判断",
            "confidence": text(module.get("confidence")) if report_mode == "Formal" else "无法判断",
            "risk_basis": "formal_assessment" if report_mode == "Formal" else "discovery_only",
            "reasoning": text(module.get("reasoning")),
            "candidate_count": len(module_candidates),
            "material_candidate_count": sum(1 for row in module_candidates if row["material"]),
            "findings": findings,
        })
    return result


def build_report_data(
    task_dir: Path, task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any],
    candidates: dict[str, Any], journal: dict[str, Any], search_plan: dict[str, Any],
    *, generated_at: str | None = None,
) -> dict[str, Any]:
    assert_active_free_policy(task)
    assert_default_discovery_plan_contract(task, search_plan)
    assert_no_wipo_traces(task_dir, task, evidence, candidates, journal, search_plan)
    binding_errors = verification_plan_binding_errors(
        task, evidence, candidates, search_plan,
    )
    if binding_errors:
        raise ValueError(
            "OFFICIAL_VERIFICATION_PLAN_BINDING_INVALID: " + "; ".join(binding_errors)
        )
    evidence_collections = (
        evidence.get("collections", {})
        if isinstance(evidence.get("collections"), dict) else {}
    )
    known_evidence = {
        text(entry.get("evidence_id")).strip()
        for values in evidence_collections.values()
        if isinstance(values, list)
        for entry in values
        if isinstance(entry, dict) and text(entry.get("evidence_id")).strip()
    }
    module_errors = assessment_module_errors(
        assessment, known_evidence=known_evidence,
        formal_risk_evidence=formal_rating_evidence_by_module(
            task, evidence, candidates, search_plan,
        ),
    )
    if module_errors:
        raise ValueError("INVALID_ASSESSMENT_MODULES: " + "; ".join(module_errors))
    materiality_ledger = load_materiality_ledger(
        task_dir, text(task.get("task_id")),
    )
    materiality_errors = materiality_ledger_errors(
        materiality_ledger, text(task.get("task_id")), candidates,
    )
    if materiality_errors:
        raise ValueError("INVALID_MATERIALITY_LEDGER: " + "; ".join(materiality_errors))
    rows = candidate_rows(candidates)
    main_visual = main_visual_evidence(task_dir, task)
    visuals = visual_evidence(task_dir, task, evidence, candidates, assessment)
    gate = release_gate(task, evidence, assessment, candidates, journal, search_plan)
    runs = _source_runs(evidence)
    discovery_degradations = default_discovery_degradations(
        task, evidence, search_plan,
    )
    required_query_count, completed_required = required_query_completion(search_plan, evidence)
    completion = round(100 * completed_required / required_query_count) if required_query_count else 100
    product = task.get("product", {}) if isinstance(task.get("product"), dict) else {}
    request = task.get("request", {}) if isinstance(task.get("request"), dict) else {}
    overall = assessment.get("overall", {}) if isinstance(assessment.get("overall"), dict) else {}
    digests = input_digests(
        task, evidence, assessment, candidates, journal, search_plan,
        materiality_ledger,
    )
    report_data: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_schema": REPORT_SCHEMA_NAME,
        "task_schema_version": text(task.get("schema_version")),
        "task_id": text(task.get("task_id")),
        "generated_at": generated_at or now_iso(),
        "report_mode": gate["report_mode"],
        "formal_allowed": gate["formal_allowed"],
        "section_order": SECTION_ORDER,
        "product": {
            "title": text(product.get("title")),
            "brand": text(product.get("brand")),
            "manufacturer": text(product.get("manufacturer")),
            "category": text(product.get("category")),
            "asin": text(product.get("actual_asin") or product.get("requested_asin")),
            "marketplace": text(request.get("marketplace")),
            "jurisdictions": unique_strings(task.get("target_jurisdictions", [])),
            "variant": product.get("variant") if isinstance(product.get("variant"), dict) else {},
            "bullets": string_list(product.get("bullets")),
            "specifications": product.get("specifications") if isinstance(product.get("specifications"), dict) else {},
            "structure": string_list(product.get("structure")),
            "main_visual_id": main_visual["evidence_id"] if main_visual else "",
            "main_visual": main_visual,
        },
        "decision": {
            "report_mode": gate["report_mode"],
            "formal_allowed": gate["formal_allowed"],
            "final_risk": gate["final_risk"],
            "display_risk": gate["display_risk"],
            "confidence": gate["confidence"],
            "risk_basis": gate["risk_basis"],
            "assessment_status": text(assessment.get("status")),
            "reasons": string_list(overall.get("reasons")),
        },
        "coverage": {
            "requirement_count": len(task.get("coverage_requirements", [])) if isinstance(task.get("coverage_requirements"), list) else 0,
            "completed_requirement_count": max(
                0,
                (len(task.get("coverage_requirements", [])) if isinstance(task.get("coverage_requirements"), list) else 0)
                - len(gate["computed"]["missing_coverage_requirements"]),
            ),
            "required_query_count": required_query_count,
            "completed_required_query_count": completed_required,
            "completion_percent": completion,
            "candidate_count": len(rows),
            "material_candidate_count": sum(1 for row in rows if row["material"]),
            **gate["computed"],
            "source_summary": _source_summary(runs),
        },
        "blockers": gate["blockers"],
        "discovery_degradations": discovery_degradations,
        "modules": _module_rows(assessment, rows, gate["report_mode"]),
        "visual_evidence": visuals,
        "candidates": rows,
        "source_runs": runs,
        "recommended_actions": string_list(assessment.get("recommended_actions")),
        "paid_recommendations": paid_recommendation_rows(assessment),
        "disclaimer": DISCLAIMER,
        "coverage_boundaries": COVERAGE_BOUNDARIES,
        "trace": {
            "input_digests": digests,
            "materiality_ledger": {
                "path": "materiality-annotations.json",
                "annotation_count": len(materiality_ledger.get("annotations", [])),
            },
        },
        "offline_policy": {
            "images_embedded_as_data_uri": True,
            "remote_resources": False,
            "scripts": False,
            "visual_limit": VISUAL_LIMIT,
        },
    }
    return report_data


def _section_head(index: int, english: str, chinese: str) -> str:
    return f'<div class="section-head"><h2>{esc(chinese)}</h2><span>{index:02d} / {esc(english)}</span></div>'


def _risk_css(value: Any) -> str:
    return RISK_CSS.get(text(value), "not-assessable")


def _fact(label: str, value: Any, *, code: bool = False) -> str:
    content = f"<code>{esc(value or '—')}</code>" if code else f"<strong>{esc(value or '—')}</strong>"
    return f'<div class="fact"><span>{esc(label)}</span>{content}</div>'


def _candidate_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<p class="empty">没有候选记录；这不代表不存在相关权利。</p>'
    rendered: list[str] = []
    for row in rows:
        link = row.get("url")
        record = esc(row.get("record_number") or "—")
        record_html = f'<a href="{esc(link)}" target="_blank" rel="noopener">{record}</a>' if link else record
        verification = row.get("official_verification", {})
        verification_meta = " · ".join(unique_strings([
            verification.get("authority"), verification.get("method"),
            verification.get("legal_status"),
            ", ".join(string_list(verification.get("classes"))),
        ])) or "—"
        evidence_refs = ", ".join(row.get("evidence_refs", [])) or "—"
        owner = row.get("owner") or "—"
        title_owner = f"{esc(row.get('title'))}<br><span class=\"meta\">{esc(owner)}</span>"
        disposition = esc(row.get("disposition") or "—")
        if row.get("material_reason"):
            disposition += f'<br><span class="meta">{esc(row.get("material_reason"))}</span>'
        rendered.append(
            "<tr>"
            f"<td><code>{esc(row['candidate_id'])}</code></td>"
            f"<td>{esc(row.get('module_name'))}<br><span class=\"meta\">{esc(row.get('jurisdiction') or '—')}</span></td>"
            f"<td>{record_html}<br><span class=\"meta\">{esc(row.get('status') or '—')}</span></td>"
            f"<td>{title_owner}</td><td>{disposition}</td>"
            f"<td>{esc(verification.get('status') or 'not_checked')}<br><span class=\"meta\">{esc(verification_meta)}</span></td>"
            f"<td><code>{esc(evidence_refs)}</code></td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>候选</th><th>模块 / 法域</th>'
        '<th>编号 / 状态</th><th>标题 / 权利人</th><th>处置</th><th>官方核验</th><th>证据引用</th>'
        f"</tr></thead><tbody>{''.join(rendered)}</tbody></table></div>"
    )


def render_html(report_data: dict[str, Any], report_data_digest: str, report_data_bytes: int) -> str:
    template_path = Path(__file__).resolve().parents[1] / "assets" / "report-v2-template.html"
    template = template_path.read_text(encoding="utf-8")
    product = report_data["product"]
    visuals = report_data["visual_evidence"]
    main_visual = product.get("main_visual") if isinstance(product.get("main_visual"), dict) else None
    image_html = (
        f'<figure class="product-image"><img src="{esc(main_visual["data_uri"])}" alt="{esc(main_visual["label"])}">'
        f'<figcaption><span>{esc(main_visual["label"])}</span><code>SHA {esc(main_visual["sha256"][:12])}</code></figcaption></figure>'
        if main_visual else '<div class="product-image empty">主图不可用</div>'
    )
    variant = product.get("variant", {})
    variant_text = " / ".join(unique_strings([variant.get("label"), variant.get("value")])) if isinstance(variant, dict) else ""
    facts = "".join([
        _fact("品牌", product.get("brand")),
        _fact("类目", product.get("category")),
        _fact("市场 / 法域", f"{product.get('marketplace') or '—'} / {', '.join(product.get('jurisdictions', [])) or '—'}"),
        _fact("ASIN", product.get("asin"), code=True),
        _fact("当前变体", variant_text or "—"),
    ])
    product_html = (
        _section_head(1, "Product", "产品快照")
        + f'<div class="product-layout">{image_html}<div class="product-copy"><span class="frozen">冻结商品事实</span>'
        + f'<h3>{esc(product.get("title") or "未命名商品")}</h3><p class="meta">图片来自任务内冻结副本，并在报告构建时重新计算 SHA-256；HTML 可离线查看。</p>'
        + f'<div class="facts">{facts}</div></div></div>'
    )

    decision = report_data["decision"]
    coverage = report_data["coverage"]
    display_risk = decision.get("display_risk") or "无法判断"
    mode_copy = "正式结论" if report_data["report_mode"] == "Formal" else "发现层风险（非正式）"
    decision_reasons = "".join(f"<li>{esc(reason)}</li>" for reason in decision.get("reasons", [])) or "<li>未记录补充理由。</li>"
    decision_actions = "".join(f"<li>{esc(action)}</li>" for action in report_data.get("recommended_actions", []))
    coverage_boundaries = "".join(
        f"<li>{esc(item)}</li>" for item in report_data.get("coverage_boundaries", [])
    )
    decision_html = (
        _section_head(2, "Decision", "筛查结论")
        + '<div class="decision-layout">'
        + f'<div class="risk-seal {_risk_css(display_risk)}"><small>{esc(mode_copy)}</small><strong>{esc(display_risk)}</strong><small>置信度 {esc(decision.get("confidence"))}</small></div>'
        + '<div><div class="metrics">'
        + f'<div class="metric"><span>报告状态</span><strong>{esc(report_data["report_mode"])}</strong></div>'
        + f'<div class="metric"><span>正式结论门禁</span><strong>{"允许" if report_data["formal_allowed"] else "不允许"}</strong></div>'
        + f'<div class="metric"><span>查询覆盖</span><strong>{coverage["completed_required_query_count"]}/{coverage["required_query_count"]}</strong></div>'
        + f'<div class="metric"><span>候选 / 重大</span><strong>{coverage["candidate_count"]} / {coverage["material_candidate_count"]}</strong></div>'
        + f'</div><div class="decision-copy"><ul>{decision_reasons}</ul>'
        + (f'<h3>建议动作</h3><ol>{decision_actions}</ol>' if decision_actions else "")
        + '</div></div></div>'
        + f'<div class="legal-note"><strong>法律边界</strong><br>{esc(report_data["disclaimer"])}'
        + (f'<ul>{coverage_boundaries}</ul>' if coverage_boundaries else "")
        + '</div>'
    )

    source_cards = "".join(
        f'<div class="source-card"><strong>{esc(item["provider"])}</strong><span>{item["terminal"]}/{item["attempted"]} 终态 · {esc(", ".join(item["statuses"]) or "未运行")}</span></div>'
        for item in coverage.get("source_summary", [])
    ) or '<p class="empty">没有来源执行记录。</p>'
    coverage_html = (
        _section_head(3, "Coverage", "查询与候选覆盖")
        + '<div class="metrics">'
        + f'<div class="metric"><span>覆盖要求</span><strong>{coverage["completed_requirement_count"]}/{coverage["requirement_count"]}</strong></div>'
        + f'<div class="metric"><span>必需查询</span><strong>{coverage["completed_required_query_count"]}/{coverage["required_query_count"]}</strong></div>'
        + f'<div class="metric"><span>未核验重大候选</span><strong>{len(coverage["unverified_material_candidates"])}</strong></div>'
        + f'<div class="metric"><span>候选总数</span><strong>{coverage["candidate_count"]}</strong></div></div>'
        + f'<p class="meta">必需查询完成度 {coverage["completion_percent"]}%</p><div class="progress"><i style="width:{coverage["completion_percent"]}%"></i></div>'
        + f'<div class="source-grid">{source_cards}</div>'
    )

    if report_data["blockers"]:
        gaps = "".join(
            f'<div class="gap"><code>{esc(item["code"])}</code> · {esc(item["scope"])}<br>{esc(item["detail"])}'
            + (f'<br><span class="meta">{esc(", ".join(item["items"]))}</span>' if item.get("items") else "")
            + "</div>"
            for item in report_data["blockers"]
        )
    else:
        gaps = '<div class="gap clear"><strong>正式发布门禁已通过</strong><br>当前输入与证据绑定未发现报告级阻断项。</div>'
    paid_cards_parts: list[str] = []
    for item in report_data.get("paid_recommendations", []):
        cap = item.get("cost_cap", {})
        cap_display = (
            f'{esc(cap.get("currency", "USD"))} {cap.get("amount")}'
            if cap.get("amount") is not None else "待报价并由用户设定"
        )
        exhaustion = esc(", ".join(item.get("free_exhaustion_evidence", [])) or "已记录免费路径穷尽证据")
        paid_cards_parts.append(
            '<div class="gap paid">'
            f'<code>{esc(item.get("recommendation_id") or "PAID")}</code> · {esc(item.get("jurisdiction") or "—")} / {esc(item.get("module") or "—")}<br>'
            f'<strong>{esc(item.get("provider") or "待选择服务商")}</strong>：{esc(", ".join(item.get("missing_fields", [])) or "补充缺失数据")}<br>'
            f'<span class="meta">预计 {item.get("estimated_calls", 0)} 次调用 · 免费路径依据 {exhaustion} · '
            f'当前可执行费用上限 {cap_display} · {esc(cap.get("basis", ""))} · 必须另行批准，当前不执行</span>'
            '</div>'
        )
    paid_cards = "".join(paid_cards_parts)
    paid_html = (
        '<h3>付费升级建议（仅建议，不执行）</h3>'
        f'<div class="gap-list">{paid_cards}</div>'
        if paid_cards else ""
    )
    discovery_cards = "".join(
        '<div class="gap">'
        f'<code>{esc(item["error_code"] or "DISCOVERY_DEGRADED")}</code> · '
        f'{esc(item["provider"])} / {esc(item["jurisdiction"] or "—")}<br>'
        f'{esc(item["detail"] or item["status"])}'
        + (f'<br><span class="meta">query {esc(item["query_id"])}</span>' if item["query_id"] else "")
        + '</div>'
        for item in report_data.get("discovery_degradations", [])
    )
    discovery_html = (
        '<h3>可选发现源降级（非阻断）</h3>'
        f'<div class="gap-list">{discovery_cards}</div>'
        if discovery_cards else ""
    )
    gaps_html = (
        _section_head(
            4, "Release gaps",
            f'发布阻断项（{len(report_data["blockers"])}） · 发现降级（{len(report_data.get("discovery_degradations", []))}）',
        )
        + f'<div class="gap-list">{gaps}</div>{discovery_html}{paid_html}'
    )

    module_cards: list[str] = []
    for module in report_data["modules"]:
        findings = "".join(
            f'<li><strong>{esc(item["title"])}</strong>：{esc(item["recommended_action"] or "待确认动作")}<br><code>{esc(", ".join(item["evidence_refs"]) or "无证据引用")}</code></li>'
            for item in module["findings"]
        ) or '<li class="empty">未记录具体发现。</li>'
        basis = "正式评级" if module["risk_basis"] == "formal_assessment" else "发现层 / 非正式"
        module_cards.append(
            '<article class="module-card"><div class="module-head">'
            f'<h3>{esc(module["module_name"])}</h3><span class="risk-pill {_risk_css(module["risk"])}">{esc(module["risk"])}</span></div>'
            f'<p class="meta">{esc(basis)} · 置信度 {esc(module["confidence"])} · 候选 {module["candidate_count"]} / 重大 {module["material_candidate_count"]}</p>'
            f'<p>{esc(module["reasoning"] or "尚无模块说明。")}</p><ul>{findings}</ul></article>'
        )
    modules_html = _section_head(5, "Modules", f'{len(report_data["modules"])}项知识产权模块') + f'<div class="module-grid">{"".join(module_cards)}</div>'

    visual_cards = "".join(
        '<figure class="visual-card">'
        f'<img src="{esc(item["data_uri"])}" alt="{esc(item["label"])}">'
        f'<figcaption><strong>{esc(item["label"])}</strong><span class="meta">{esc(item["source"])} · 相似度 {esc(item["similarity_display"])} · {item["bytes"]} bytes</span>'
        f'<code>{esc(item["evidence_id"])} · SHA {esc(item["sha256"][:16])}…</code></figcaption></figure>'
        for item in visuals
    ) or '<p class="empty">没有可展示的任务内视觉证据。</p>'
    visual_html = (
        _section_head(6, "Visual evidence", f'重点视觉证据（{len(visuals)}/{VISUAL_LIMIT}）')
        + '<p class="meta">仅展示任务内已校验文件；相似度或图像接近仅是发现线索，不等于侵权结论。</p>'
        + f'<div class="visual-grid">{visual_cards}</div>'
    )

    # Only a reviewer-explicit exclusion may be folded. Draft/unreviewed rows
    # stay visible even when their materiality boolean is still false.
    visible = [
        row for row in report_data["candidates"]
        if text(row.get("disposition")).casefold() != "excluded"
    ]
    excluded = [
        row for row in report_data["candidates"]
        if text(row.get("disposition")).casefold() == "excluded"
    ]
    candidates_html = _section_head(7, "Candidates", f'候选追溯（完整 {len(report_data["candidates"])} 条）')
    candidates_html += '<h3>待处置或重大候选</h3>' + _candidate_table(visible)
    if excluded:
        excluded_table = _candidate_table(excluded)
        candidates_html += (
            f'<details class="fold print-hidden"><summary>已排除候选（{len(excluded)} 条，点击展开）</summary>'
            f'{excluded_table}</details>'
            f'<div class="print-only excluded-print" data-print-excluded-count="{len(excluded)}">'
            f'<h3>已排除候选（{len(excluded)} 条）</h3>{excluded_table}</div>'
        )
    elif visible:
        candidates_html += '<p class="empty">没有已排除候选。</p>'

    trace_rows = "".join(
        f'<div class="trace-row"><span>{esc(label.replace("_", " ").title())}</span><code>{esc(digest)}</code><small>SHA-256</small></div>'
        for label, digest in report_data["trace"]["input_digests"].items()
    )
    trace_rows += f'<div class="trace-row"><span>Report data</span><code>{esc(report_data_digest)}</code><small>{report_data_bytes} bytes</small></div>'
    trace_html = _section_head(8, "Trace", "可复现数据绑定") + f'<div class="trace-list">{trace_rows}</div>'

    replacements = {
        "REPORT_MODE": report_data["report_mode"],
        "MODE_CLASS": report_data["report_mode"].casefold(),
        "DOCUMENT_TITLE": esc(f'{text(product.get("asin"))} · 知识产权风险筛查报告'),
        "TASK_ID": esc(report_data["task_id"]),
        "HEADER_META": esc(" · ".join(unique_strings([
            product.get("title"), product.get("brand"), product.get("marketplace"),
            ", ".join(product.get("jurisdictions", [])),
        ]))),
        "QUERY_COUNT": str(coverage["required_query_count"]),
        "CANDIDATE_COUNT": str(coverage["candidate_count"]),
        "GAP_COUNT": str(
            len(report_data["blockers"])
            + len(report_data.get("discovery_degradations", []))
        ),
        "MODULE_COUNT": str(len(report_data["modules"])),
        "VISUAL_COUNT": str(len(visuals)),
        "PRODUCT_HTML": product_html,
        "DECISION_HTML": decision_html,
        "COVERAGE_HTML": coverage_html,
        "GAPS_HTML": gaps_html,
        "MODULES_HTML": modules_html,
        "VISUAL_HTML": visual_html,
        "CANDIDATES_HTML": candidates_html,
        "TRACE_HTML": trace_html,
    }
    rendered = template
    for name, value in replacements.items():
        rendered = rendered.replace(f"@@{name}@@", text(value))
    leftovers = re.findall(r"@@[A-Z_]+@@", rendered)
    if leftovers:
        raise ValueError("Unresolved v2 report template markers: " + ", ".join(sorted(set(leftovers))))
    return rendered


def render_markdown(report_data: dict[str, Any], report_data_digest: str, report_data_bytes: int) -> str:
    product = report_data["product"]
    decision = report_data["decision"]
    coverage = report_data["coverage"]
    lines = [
        "# 知识产权风险筛查报告", "",
        f"- 报告格式：`{REPORT_SCHEMA_NAME}`",
        f"- 发布模式：`{report_data['report_mode']}`",
        f"- 任务：`{md_escape(report_data['task_id'])}`", "",
        "## 1. 产品快照", "",
        f"- 商品：{md_escape(product.get('title'))}",
        f"- 品牌：{md_escape(product.get('brand') or '—')}",
        f"- ASIN：`{md_escape(product.get('asin') or '—')}`",
        f"- 市场 / 法域：{md_escape(product.get('marketplace') or '—')} / {md_escape(', '.join(product.get('jurisdictions', [])) or '—')}",
    ]
    main_visual = product.get("main_visual") if isinstance(product.get("main_visual"), dict) else None
    if main_visual:
        lines += [
            "", f"![{md_escape(main_visual['label'])}]({main_visual['data_uri']})", "",
            f"- 主图 SHA-256：`{main_visual['sha256']}`",
        ]
    lines += [
        "", "## 2. 筛查结论", "",
        f"- 状态：**{report_data['report_mode']}**",
        f"- {'正式总风险' if report_data['formal_allowed'] else '发现层风险（非正式）'}：**{md_escape(decision.get('display_risk'))}**",
        f"- 正式结论门禁：{'允许' if report_data['formal_allowed'] else '不允许'}",
    ]
    lines.extend(f"- {md_escape(reason)}" for reason in decision.get("reasons", []))
    if report_data.get("recommended_actions"):
        lines += ["", "### 建议动作", ""]
        lines.extend(f"- {md_escape(action)}" for action in report_data["recommended_actions"])
    lines += ["", f"> {md_escape(report_data['disclaimer'])}"]
    lines.extend(f"> - {md_escape(item)}" for item in report_data.get("coverage_boundaries", []))
    lines += ["", "## 3. 查询与候选覆盖", "",
              f"- 必需查询：{coverage['completed_required_query_count']}/{coverage['required_query_count']}（{coverage['completion_percent']}%）",
              f"- 覆盖要求：{coverage['completed_requirement_count']}/{coverage['requirement_count']}",
              f"- 未满足覆盖要求：{md_escape(', '.join(coverage['missing_coverage_requirements']) or '无')}",
              f"- 未完成查询：{md_escape(', '.join(coverage['missing_required_queries']) or '无')}",
              f"- 候选 / 重大候选：{coverage['candidate_count']} / {coverage['material_candidate_count']}", ""]
    lines += ["## 4. 发布阻断项", ""]
    if report_data["blockers"]:
        for blocker in report_data["blockers"]:
            suffix = f"；{', '.join(blocker['items'])}" if blocker.get("items") else ""
            lines.append(f"- `{md_escape(blocker['code'])}`：{md_escape(blocker['detail'])}{md_escape(suffix)}")
    else:
        lines.append("- 无；正式发布门禁已通过。")
    if report_data.get("discovery_degradations"):
        lines += ["", "### 可选发现源降级（非阻断）", ""]
        for item in report_data["discovery_degradations"]:
            query = f"；查询 `{md_escape(item['query_id'])}`" if item.get("query_id") else ""
            lines.append(
                f"- `{md_escape(item.get('error_code') or 'DISCOVERY_DEGRADED')}` "
                f"{md_escape(item.get('provider'))} / {md_escape(item.get('jurisdiction') or '—')}："
                f"{md_escape(item.get('detail') or item.get('status'))}{query}"
            )
    if report_data.get("paid_recommendations"):
        lines += ["", "### 付费升级建议（仅建议，不执行）", ""]
        for item in report_data["paid_recommendations"]:
            cap = item.get("cost_cap", {})
            cap_display = (
                f"{cap.get('currency', 'USD')} {cap.get('amount')}"
                if cap.get("amount") is not None else "待报价并由用户设定"
            )
            lines.append(
                f"- `{md_escape(item.get('recommendation_id') or 'PAID')}` "
                f"{md_escape(item.get('jurisdiction') or '—')} / {md_escape(item.get('module') or '—')}："
                f"{md_escape(item.get('provider') or '待选择服务商')}；缺失字段 "
                f"{md_escape(', '.join(item.get('missing_fields', [])) or '未说明')}；预计 "
                f"{item.get('estimated_calls', 0)} 次调用；免费路径依据 "
                f"{md_escape(', '.join(item.get('free_exhaustion_evidence', [])) or '已记录免费路径穷尽证据')}；"
                f"当前可执行费用上限 {md_escape(cap_display)}；{md_escape(cap.get('basis', ''))}；"
                "必须另行批准，当前不执行。"
            )
    lines += ["", "## 5. 知识产权模块", "", "| 模块 | 风险 | 置信度 | 候选 / 重大 | 说明 |", "|---|---|---|---:|---|"]
    findings: list[dict[str, Any]] = []
    for module in report_data["modules"]:
        lines.append(
            f"| {md_escape(module['module_name'])} | {md_escape(module['risk'])} | {md_escape(module['confidence'])} | "
            f"{module['candidate_count']} / {module['material_candidate_count']} | {md_escape(module['reasoning'])} |"
        )
        findings.extend({**finding, "module_name": module["module_name"]} for finding in module["findings"])
    if findings:
        lines += ["", "### 模块发现", ""]
        for finding in findings:
            lines.append(
                f"- **{md_escape(finding['module_name'])} · {md_escape(finding['title'])}**："
                f"{md_escape(finding['recommended_action'])}；证据 `{md_escape(', '.join(finding['evidence_refs']))}`"
            )
    lines += ["", "## 6. 重点视觉证据", ""]
    for item in report_data["visual_evidence"]:
        lines += [
            f"### {md_escape(item['label'])}", "",
            f"![{md_escape(item['label'])}]({item['data_uri']})", "",
            f"- `{item['evidence_id']}` · `{item['mime_type']}` · `{item['bytes']} bytes`",
            f"- 相似度：{md_escape(item['similarity_display'])}",
            f"- SHA-256：`{item['sha256']}`", "",
        ]
    if not report_data["visual_evidence"]:
        lines += ["- 没有可展示的任务内视觉证据。", ""]
    lines += ["## 7. 候选追溯", "", "| 候选 | 模块 / 法域 | 编号 | 标题 / 权利人 | 处置 | 官方核验 | 证据引用 |", "|---|---|---|---|---|---|---|"]
    for row in report_data["candidates"]:
        lines.append(
            f"| `{md_escape(row['candidate_id'])}` | {md_escape(row['module_name'])} / {md_escape(row['jurisdiction'] or '—')} | "
            f"{md_escape(row['record_number'] or '—')} | {md_escape(row['title'])} / {md_escape(row['owner'] or '—')} | "
            f"{md_escape(row['disposition'])} | {md_escape(row['official_verification']['status'])} / "
            f"{md_escape(row['official_verification'].get('authority') or '—')} / "
            f"{md_escape(row['official_verification'].get('method') or '—')} | "
            f"`{md_escape(', '.join(row['evidence_refs']) or '—')}` |"
        )
    if not report_data["candidates"]:
        lines.append("| — | — | — | 没有候选记录；这不代表不存在相关权利 | — | — | — |")
    lines += ["", "## 8. 可复现数据绑定", ""]
    lines.extend(f"- {key}：`{value}`" for key, value in report_data["trace"]["input_digests"].items())
    lines += [f"- report-data.json：`{report_data_digest}`（{report_data_bytes} bytes）", ""]
    return "\n".join(lines)


def _csv_safe(value: Any) -> str:
    raw = text(value).replace("\x00", "")
    if raw.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + raw
    return raw


def render_findings_csv(report_data: dict[str, Any]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for module in report_data["modules"]:
        for finding in module["findings"]:
            writer.writerow({
                "report_mode": _csv_safe(report_data["report_mode"]),
                "module_id": _csv_safe(module["module_id"]),
                "module_name": _csv_safe(module["module_name"]),
                "module_risk": _csv_safe(module["risk"]),
                "module_confidence": _csv_safe(module["confidence"]),
                "finding_id": _csv_safe(finding["finding_id"]),
                "title": _csv_safe(finding["title"]),
                "recommended_action": _csv_safe(finding["recommended_action"]),
                "evidence_refs": _csv_safe(";".join(finding["evidence_refs"])),
            })
    return stream.getvalue()


def compute_manifest_content_digest(manifest: dict[str, Any]) -> str:
    """Hash canonical manifest content while excluding this digest field itself."""
    return sha256_json({key: value for key, value in manifest.items() if key != "content_digest"})


def build_v2_bundle(
    task_dir: Path, task: dict[str, Any], evidence: dict[str, Any], assessment: dict[str, Any],
    candidates: dict[str, Any], journal: dict[str, Any], search_plan: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    report_data = build_report_data(task_dir, task, evidence, assessment, candidates, journal, search_plan)
    report_data_bytes = (json.dumps(report_data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    report_data_path = task_dir / "report-data.json"
    atomic_write_bytes(report_data_path, report_data_bytes)
    report_data_digest = sha256_bytes(report_data_bytes)

    rendered = {
        "report.html": render_html(report_data, report_data_digest, len(report_data_bytes)).encode("utf-8"),
        "report.md": render_markdown(report_data, report_data_digest, len(report_data_bytes)).encode("utf-8"),
        "report-findings.csv": render_findings_csv(report_data).encode("utf-8-sig"),
    }
    for name, payload in rendered.items():
        atomic_write_bytes(task_dir / name, payload)

    artifacts: dict[str, dict[str, Any]] = {
        "report-data.json": {"path": "report-data.json", "sha256": report_data_digest, "bytes": len(report_data_bytes)},
    }
    for name, payload in rendered.items():
        artifacts[name] = {"path": name, "sha256": sha256_bytes(payload), "bytes": len(payload)}
    overall = assessment.get("overall", {}) if isinstance(assessment.get("overall"), dict) else {}
    manifest = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "report_schema": REPORT_SCHEMA_NAME,
        "task_schema_version": text(task.get("schema_version")),
        "task_id": text(task.get("task_id")),
        "generated_at": report_data["generated_at"],
        "report_mode": report_data["report_mode"],
        "formal_allowed": report_data["formal_allowed"],
        "formal_status": {
            "task_state": text(task.get("state")),
            "assessment_status": text(assessment.get("status")),
            "assessment_risk": text(overall.get("risk")),
            "assessment_provisional": overall.get("provisional"),
            "formal_allowed": report_data["formal_allowed"],
        },
        "section_order": SECTION_ORDER,
        "input_digests": report_data["trace"]["input_digests"],
        "artifacts": artifacts,
        "visual_evidence": [
            {key: item[key] for key in ("evidence_id", "relative_path", "mime_type", "sha256", "bytes")}
            for item in report_data["visual_evidence"]
        ],
        "main_visual": (
            {key: report_data["product"]["main_visual"][key] for key in (
                "evidence_id", "relative_path", "mime_type", "sha256", "bytes",
            )}
            if isinstance(report_data["product"].get("main_visual"), dict) else {}
        ),
        "offline_policy": report_data["offline_policy"],
    }
    manifest["content_digest"] = compute_manifest_content_digest(manifest)
    atomic_write_json(task_dir / "report-manifest.json", manifest)
    return report_data, manifest

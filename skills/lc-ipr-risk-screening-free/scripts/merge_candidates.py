#!/usr/bin/env python3
"""Normalize and deduplicate patent/design and trademark candidates across sources."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import re
import shlex
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import (
    AMAZON_EU_COUNTRIES, add_history, assert_active_free_policy, atomic_write_json,
    ensure_object, intrinsic_patent_right_type, is_active_schema, load_json,
    normalize_text, load_skill_config, now_iso, parse_iso, SERPAPI_PROVIDER,
    SERPER_PROVIDERS,
    stable_id,
)
from annotate_materiality import apply_materiality_annotations, load_materiality_ledger
from provider_utils import query_identity
from runtime_timing import timed_cli


US_PUBLIC_SOURCE_KEYS = {
    "copyright": ("copyright_records",),
    "enforcement": ("ttabvue", "ptab", "copyright_claims_board"),
}
US_PUBLIC_SOURCE_HOSTS = {
    "publicrecords.copyright.gov": "copyright_records",
    "cocatalog.loc.gov": "copyright_records",
    "copyright.gov": "copyright_records",
    "www.copyright.gov": "copyright_records",
    "ttabvue.uspto.gov": "ttabvue",
    "ptab.uspto.gov": "ptab",
    "ccb.gov": "copyright_claims_board",
    "www.ccb.gov": "copyright_claims_board",
    "dockets.ccb.gov": "copyright_claims_board",
}

PUBLIC_RECORD_IDENTIFIER_REQUIRED = "PUBLIC_RECORD_IDENTIFIER_REQUIRED"
PUBLIC_RECORD_IDENTIFIER_FIELDS = {
    "copyright": ("record_number", "registration_number", "application_number"),
    "enforcement": (
        "case_number", "docket_number", "record_number",
        "application_number", "registration_number",
    ),
}
PUBLIC_RECORD_IDENTIFIER_PLACEHOLDERS = {
    "", "na", "none", "null", "pending", "tbd", "unknown", "unavailable",
    "notavailable", "notfound", "missing", "未提供", "未知", "待定", "暂无", "无",
}


def patent_key(item: dict[str, Any]) -> str:
    publication = str(item.get("publication_number") or "")
    number = str(publication or item.get("application_number") or item.get("grant_number") or item.get("record_number") or "")
    number = re.sub(r"[^A-Za-z0-9]", "", number).upper()
    jurisdiction = str(item.get("jurisdiction") or number[:2]).upper()
    kind = str(item.get("kind_code") or "").upper()
    right_type = intrinsic_patent_right_type(jurisdiction, number, kind) or str(
        item.get("right_type") or "patent"
    )
    family = str(item.get("family_id") or "")
    if (publication or re.match(r"^[A-Z]{2}(?:D|RE|PP)?\d", number)) and number:
        return f"{jurisdiction}:{right_type}:{number}"
    return f"{jurisdiction}:{right_type}:{number}:{kind}" if number else f"{right_type}:family:{family}" if family else ""


def trademark_key(item: dict[str, Any]) -> str:
    office = str(item.get("office") or item.get("jurisdiction") or "").casefold()
    right_type = candidate_right_type("trademark", item)
    number = str(item.get("application_number") or item.get("serial_number") or item.get("registration_number") or "")
    number = re.sub(r"\W", "", number).upper()
    if number:
        return f"{office}:{right_type}:{number}"
    mark = normalize_text(str(item.get("mark_text") or item.get("word_mark") or ""))
    figurative = str(item.get("figurative_id") or item.get("image_url") or "")
    return f"{office}:{right_type}:text:{mark}:figure:{figurative}" if mark or figurative else ""


def public_record_key(kind: str, item: dict[str, Any]) -> str:
    """Keep copyright/enforcement discovery rows even without patent-style IDs."""
    right_type = candidate_right_type(kind, item)
    jurisdiction = str(item.get("jurisdiction") or item.get("office") or "").upper()
    candidate_id = normalize_text(str(item.get("candidate_id") or ""))
    if candidate_id:
        return f"{jurisdiction}:{right_type}:candidate:{candidate_id}"
    record = next((
        normalize_text(str(item.get(field) or ""))
        for field in (
            "record_number", "registration_number", "case_number",
            "docket_number", "application_number",
        )
        if str(item.get(field) or "").strip()
    ), "")
    if record:
        return f"{jurisdiction}:{right_type}:record:{record}"
    url = str(item.get("url") or item.get("source_url") or item.get("image_url") or "").strip()
    if url:
        return f"{jurisdiction}:{right_type}:url:{url}"
    title = normalize_text(str(item.get("title") or item.get("name") or item.get("snippet") or ""))
    owner = normalize_text(str(item.get("owner") or item.get("claimant") or ""))
    return f"{jurisdiction}:{right_type}:text:{title}:owner:{owner}" if title or owner else ""


def better_verification(left: Any, right: Any) -> Any:
    rank = {
        "verified": 7, "identity_mismatch": 6, "partial": 5, "no_result": 4, "incomplete": 3,
        "needs_user_action": 3, "access_limited": 2, "failed": 1,
        "not_checked": 0,
    }
    if not isinstance(left, dict):
        return right
    if not isinstance(right, dict):
        return left

    # A newer recall row only says it did not check this right. It must not
    # erase an earlier, plan-bound published-document inspection. Preserve the
    # inspection's original date and incomplete status (never infer currency).
    if left.get("authority_scope") == "published_document_only" and right.get("status") == "not_checked":
        return left
    if right.get("authority_scope") == "published_document_only" and left.get("status") == "not_checked":
        return right

    def checked_at(value: dict[str, Any]) -> Any:
        raw = str(value.get("checked_at") or "").strip()
        if not raw:
            return None
        try:
            parsed = parse_iso(raw)
            return parsed if parsed.tzinfo is not None else None
        except (TypeError, ValueError):
            return None

    left_time = checked_at(left)
    right_time = checked_at(right)
    if left_time is not None or right_time is not None:
        if left_time is None:
            return right
        if right_time is None:
            return left
        if right_time != left_time:
            return right if right_time > left_time else left
        left_mismatch = str(left.get("status") or "") == "identity_mismatch"
        right_mismatch = str(right.get("status") or "") == "identity_mismatch"
        if left_mismatch != right_mismatch:
            return right if right_mismatch else left
    return right if rank.get(str(right.get("status")), -1) > rank.get(str(left.get("status")), -1) else left


def unique_list(values: list[Any]) -> list[Any]:
    """Deduplicate scalars and structured provider fields without losing order."""
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def merge_browser_evidence(left: Any, right: Any) -> Any:
    if not isinstance(left, dict):
        return right
    if not isinstance(right, dict):
        return left
    merged = {**left, **right}
    merged["evidence_images"] = unique_list([
        *left.get("evidence_images", []),
        *right.get("evidence_images", []),
    ])
    if not merged["evidence_images"]:
        merged.pop("evidence_images")
    return merged


def merge(kind: str, entries: list[dict[str, Any]], runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if kind == "patent":
        key_fn = patent_key
    elif kind == "trademark":
        key_fn = trademark_key
    else:
        key_fn = lambda item: public_record_key(kind, item)
    for entry in entries:
        payload = entry.get("payload", {})
        candidates = payload if isinstance(payload, list) else payload.get("candidates", []) if isinstance(payload, dict) else []
        if isinstance(candidates, dict):
            candidates = [candidates]
        if not isinstance(candidates, list):
            continue
        for item in candidates:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            source_run = runs.get(str(entry.get("source_run_id")), {})
            if str(entry.get("provider") or "") in {*SERPER_PROVIDERS, SERPAPI_PROVIDER}:
                item["role"] = "discovery_only"
                item["authoritative_for_final_rating"] = False
                item["official_verification"] = {
                    "status": "not_checked", "authority": "", "source": "",
                    "method": "", "identity_match": None, "legal_status": "",
                    "owner": [], "classes": [], "media": [], "url": "",
                    "checked_at": "",
                }
            source_right_type = str(
                entry.get("right_type") or source_run.get("right_type") or ""
            ).strip()
            source_jurisdiction = str(
                entry.get("jurisdiction") or source_run.get("jurisdiction") or ""
            ).upper().strip()
            if source_jurisdiction and not item.get("jurisdiction") and not item.get("office"):
                item["jurisdiction"] = source_jurisdiction
            if kind == "patent":
                document_number = next((
                    str(item.get(field) or "")
                    for field in (
                        "publication_number", "record_number", "grant_number",
                        "application_number",
                    ) if str(item.get(field) or "").strip()
                ), "")
                intrinsic_type = intrinsic_patent_right_type(
                    item.get("jurisdiction") or item.get("office"),
                    document_number, item.get("kind_code"),
                )
                declared_type = str(item.get("right_type") or source_right_type or "")
                if intrinsic_type:
                    item["right_type"] = intrinsic_type
                    if declared_type and declared_type != intrinsic_type:
                        item.setdefault("type_conflicts", []).append({
                            "declared": declared_type,
                            "resolved": intrinsic_type,
                            "basis": "intrinsic_document_identifier",
                        })
                elif source_right_type and not item.get("right_type"):
                    item["right_type"] = source_right_type
            elif source_right_type and not item.get("right_type"):
                item["right_type"] = source_right_type
            key = key_fn(item)
            if not key:
                continue
            source_key = str(
                item.get("source_key") or entry.get("source_key")
                or (
                    source_run.get("request_params", {}).get("source_key")
                    if isinstance(source_run.get("request_params"), dict) else ""
                )
                or ""
            ).strip()
            source_ref = {
                "provider": entry.get("provider"), "evidence_id": entry.get("evidence_id"),
                "source_run_id": entry.get("source_run_id"), "query": entry.get("query"),
                "operation": entry.get("operation") or source_run.get("operation"),
                "jurisdiction": entry.get("jurisdiction") or source_run.get("jurisdiction"),
                "right_type": source_right_type,
                "collected_at": entry.get("collected_at"),
                "status": runs.get(str(entry.get("source_run_id")), {}).get("status", ""),
                "raw_paths": runs.get(str(entry.get("source_run_id")), {}).get("raw_paths", []),
                "data_date": runs.get(str(entry.get("source_run_id")), {}).get("data_date", ""),
                "relevance": item.get("relevance_score", item.get("relevance", "")),
            }
            if source_key:
                source_ref["source_key"] = source_key
            if key not in result:
                result[key] = {**item, "normalization_key": key, "sources": [source_ref], "conflicts": {}}
                continue
            current = result[key]
            current["sources"].append(source_ref)
            current["material"] = bool(current.get("material") or item.get("material"))
            current["official_verification"] = better_verification(current.get("official_verification"), item.get("official_verification"))
            for field, value in item.items():
                if field == "browser_evidence":
                    current[field] = merge_browser_evidence(current.get(field), value)
                    continue
                if field not in current or current[field] in (None, "", [], {}):
                    current[field] = value
                elif field in {
                    "owners", "nice_classes", "views", "figures", "titles",
                    "applicants", "classifications", "ipc_classes", "cpc_classes",
                    "publication_numbers", "application_numbers", "priority_numbers",
                    "family_members", "legal_events", "detail_operations",
                    "publication_documents", "publication_relations", "evidence_refs", "verification_refs",
                } and isinstance(value, list):
                    # Retain every source reference across same-record recall
                    # and historical fact rows. References do not grant official
                    # verification, which remains independently ranked above.
                    current[field] = unique_list([*current.get(field, []), *value])
                elif field not in {"sources", "conflicts", "official_verification", "material"} and current.get(field) != value:
                    claims = current.setdefault("conflicts", {}).setdefault(field, [])
                    current_value = current.get(field)
                    for claim in (current_value, value):
                        if claim not in claims:
                            claims.append(claim)
    return list(result.values())


def official_entries_for_kind(
    entries: list[dict[str, Any]], kind: str, providers: set[str],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for entry in entries:
        if str(entry.get("provider") or "") not in providers:
            continue
        payload = entry.get("payload", {})
        rows = payload.get("candidates", []) if isinstance(payload, dict) and isinstance(payload.get("candidates"), list) else [payload]
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("official_verification"), dict):
                continue
            row_kind = candidate_kind(row)
            if row_kind != kind:
                continue
            prepared.append({**entry, "payload": {"candidates": [row]}})
    return prepared


def candidate_kind(item: dict[str, Any]) -> str:
    right_type = str(item.get("right_type") or "")
    if right_type == "copyright":
        return "copyright"
    if right_type == "enforcement":
        return "enforcement"
    if right_type in {"patent", "utility_model", "design"}:
        return "patent"
    if right_type.startswith("trademark") or bool(
        item.get("serial_number") or item.get("registration_number") or item.get("mark_text")
    ):
        return "trademark"
    return "patent"


def verification_identifier_fields(kind: str) -> tuple[str, ...]:
    if kind == "trademark":
        return "serial_number", "application_number", "registration_number"
    if kind in {"copyright", "enforcement"}:
        return (
            "record_number", "registration_number", "case_number",
            "docket_number", "application_number",
        )
    return "application_number", "publication_number", "grant_number", "record_number"


def verification_index(
    entries: list[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

    def bind(key: tuple[str, str, str], verification: dict[str, Any], evidence_ref: str) -> None:
        value = {**verification, "_evidence_ref": evidence_ref}
        bucket = index.setdefault(key, [])
        identity = (evidence_ref, json.dumps(verification, ensure_ascii=False, sort_keys=True))
        if not any(
            (str(row.get("_evidence_ref") or ""), json.dumps(
                {name: item for name, item in row.items() if name != "_evidence_ref"},
                ensure_ascii=False, sort_keys=True,
            )) == identity
            for row in bucket
        ):
            bucket.append(value)

    for entry in entries:
        payload = entry.get("payload", {})
        rows = payload.get("candidates", []) if isinstance(payload, dict) and isinstance(payload.get("candidates"), list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            verification = row.get("official_verification")
            if not isinstance(verification, dict):
                continue
            right_type = str(row.get("right_type") or "")
            kind = candidate_kind(row)
            if not right_type:
                right_type = candidate_right_type(kind, row)
            fields = verification_identifier_fields(kind)
            for field in fields:
                value = re.sub(r"[^A-Za-z0-9]", "", str(row.get(field) or "")).upper()
                if value:
                    bind(
                        (kind, right_type, value), verification,
                        str(entry.get("evidence_id") or ""),
                    )
            candidate_id = str(row.get("candidate_id") or "").strip()
            if candidate_id:
                bind(
                    (kind, right_type, f"candidate:{candidate_id}"), verification,
                    str(entry.get("evidence_id") or ""),
                )
    return index


def apply_verifications(
    kind: str, candidates: list[dict[str, Any]],
    index: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> None:
    for item in candidates:
        matches: list[dict[str, Any]] = []
        right_type = candidate_right_type(kind, item)
        candidate_id = str(item.get("candidate_id") or "").strip()
        if candidate_id and (kind, right_type, f"candidate:{candidate_id}") in index:
            matches.extend(index[(kind, right_type, f"candidate:{candidate_id}")])
        fields = verification_identifier_fields(kind)
        for field in fields:
            value = re.sub(r"[^A-Za-z0-9]", "", str(item.get(field) or "")).upper()
            if value and (kind, right_type, value) in index:
                matches.extend(index[(kind, right_type, value)])
        seen: set[tuple[str, str]] = set()
        for verification in matches:
            evidence_ref = str(verification.get("_evidence_ref") or "")
            clean = {key: value for key, value in verification.items() if key != "_evidence_ref"}
            identity = (evidence_ref, json.dumps(clean, ensure_ascii=False, sort_keys=True))
            if identity in seen:
                continue
            seen.add(identity)
            item["official_verification"] = better_verification(item.get("official_verification"), clean)
            if evidence_ref:
                item.setdefault("verification_refs", []).append(evidence_ref)
        item["verification_refs"] = unique_list(item.get("verification_refs", []))


def hydrate_tsdr_candidate_facts(
    task: dict[str, Any], candidates: list[dict[str, Any]],
    entries: list[dict[str, Any]], runs: dict[str, dict[str, Any]],
) -> None:
    """Retain exact-record TSDR facts before scenario triage hashes are evaluated.

    This does not grant a triage decision or change official-verification status.
    Historical observations without a new run remain ordinary retained facts.
    """
    from decision_workflow import decision_workflow_enabled
    from assessment_v24 import _entry_matches_run
    if not decision_workflow_enabled(task):
        return
    details = []
    for entry in entries:
        run = runs.get(str(entry.get("source_run_id") or ""), {})
        if (not str(entry.get("evidence_id") or "").strip()
                or entry.get("provider") != "uspto_tsdr" or run.get("status") != "success"
                or run.get("error_code") or run.get("authoritative_for_final_rating") is False
                or run.get("operation") != "candidate_verification"
                or not _entry_matches_run(entry, run)):
            continue
        payload = entry.get("payload", {})
        rows = payload.get("candidates", []) if isinstance(payload, dict) and isinstance(payload.get("candidates"), list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            verification = row.get("official_verification") or {}
            if (not isinstance(verification, dict) or verification.get("status") != "verified"
                    or verification.get("identity_match") is not True
                    or row.get("jurisdiction") != "US" or run.get("jurisdiction") != "US"
                    or row.get("right_type") != run.get("right_type")
                    or row.get("right_type") not in {"trademark_word", "trademark_figurative"}
                    or not re.fullmatch(r"\d{8}", str(row.get("serial_number") or ""))):
                continue
            try:
                checked_at = parse_iso(str(verification.get("checked_at") or ""))
                if checked_at.tzinfo is None:
                    continue
            except (TypeError, ValueError):
                continue
            details.append((checked_at, str(entry.get("evidence_id") or ""), row, run))
    # Source arrival order is not evidence freshness; deterministic tie-breaking
    # also makes applying this hydration repeatedly idempotent.
    for _, evidence_ref, row, run in sorted(details, key=lambda value: (value[0], value[1])):
        matching = [item for item in candidates if item.get("candidate_id")
                    and item.get("candidate_id") == row.get("candidate_id")
                    and item.get("serial_number") == row["serial_number"]
                    and item.get("jurisdiction") == row["jurisdiction"]
                    and item.get("right_type") == row["right_type"]]
        if len(matching) != 1:
            continue
        item = matching[0]
        facts = {}
        registration = row.get("registration_number")
        if isinstance(registration, str) and re.fullmatch(r"\d+", registration):
            facts["registration_number"] = registration
        goods = row.get("goods_services")
        if ((isinstance(goods, str) and goods.strip())
                or (isinstance(goods, list) and goods and all(isinstance(value, str) and value.strip() for value in goods))):
            facts["goods_services"] = goods
            # Missing legacy metadata is unknown, never a claim of full capture.
            flag = row.get("goods_services_truncated")
            facts["goods_services_truncated"] = flag if isinstance(flag, bool) else None
        for field, value in facts.items():
            previous = item.get(field)
            if field in item and previous != value:
                conflicts = item.setdefault("conflicts", {}).setdefault(field, [])
                item["conflicts"][field] = unique_list([*conflicts, deepcopy(previous), deepcopy(value)])
            item[field] = deepcopy(value)
        if facts and evidence_ref:
            item["evidence_refs"] = unique_list([*item.get("evidence_refs", []), evidence_ref])
            item["verification_refs"] = unique_list([*item.get("verification_refs", []), evidence_ref])


def candidate_verification_view(task: dict, collection: str, candidate: dict,
                                evidence: dict, official: dict) -> dict:
    """Pure refresh of one existing candidate, without merge CLI side effects.

    Triage uses this to reject a stale derived view, not to silently bind unread
    evidence. Reuse the merge's exact enrichment rules; do not acquire sources,
    append plans, read artifacts, take locks, or mutate the supplied candidate.
    """
    item = deepcopy(candidate)
    entries = evidence.get("collections", {}).get("official_verifications", [])
    kind = {"patents": "patent", "trademarks": "trademark",
            "copyright_assets": "copyright", "enforcement": "enforcement"}[collection]
    apply_verifications(kind, [item], official)
    # No related official evidence means no new derived defaults to require.
    if set(item.get("verification_refs", [])) & {entry.get("evidence_id") for entry in entries}:
        apply_candidate_contract(kind, [item])
    if kind == "trademark":
        runs = {str(run.get("run_id") or ""): run for run in evidence.get("source_runs", [])}
        hydrate_tsdr_candidate_facts(task, [item], entries, runs)
    return item


def _verification_match_tokens(kind: str, item: dict[str, Any]) -> set[tuple[str, str]]:
    right_type = candidate_right_type(kind, item)
    fields = verification_identifier_fields(kind)
    return {
        (right_type, re.sub(r"[^A-Za-z0-9]", "", str(item.get(field) or "")).upper())
        for field in fields if str(item.get(field) or "").strip()
    }


def append_orphan_official_candidates(
    kind: str, candidates: list[dict[str, Any]], entries: list[dict[str, Any]],
    runs: dict[str, dict[str, Any]], providers: set[str],
) -> None:
    """Keep only verification rows that cannot attach to an existing recall."""
    existing_ids = {
        str(item.get("candidate_id") or "").strip() for item in candidates
        if str(item.get("candidate_id") or "").strip()
    }
    existing_tokens = {
        token for item in candidates for token in _verification_match_tokens(kind, item)
    }
    orphan_entries: list[dict[str, Any]] = []
    for entry in official_entries_for_kind(entries, kind, providers):
        row = entry.get("payload", {}).get("candidates", [])[0]
        candidate_id = str(row.get("candidate_id") or "").strip()
        if (candidate_id and candidate_id in existing_ids) or (
            _verification_match_tokens(kind, row) & existing_tokens
        ):
            continue
        orphan_entries.append(entry)
    if not orphan_entries:
        return
    orphans = merge(kind, orphan_entries, runs)
    apply_candidate_contract(kind, orphans)
    for item in orphans:
        # Registry/API detail status is verification state, not a reviewer
        # materiality disposition.
        item["disposition"] = "unreviewed"
        item.pop("materiality_annotation", None)
    candidates.extend(orphans)


def ensure_global_candidate_ids(
    *collections: tuple[str, list[dict[str, Any]]],
) -> None:
    """Reject ambiguous identities; official details must attach, not duplicate."""
    seen: dict[str, str] = {}
    for collection, rows in collections:
        for item in rows:
            candidate_id = str(item.get("candidate_id") or "").strip()
            if not candidate_id:
                raise ValueError(f"{collection} candidate has no candidate_id")
            if candidate_id in seen:
                raise ValueError(
                    f"duplicate candidate_id across normalized candidates: {candidate_id} "
                    f"({seen[candidate_id]}, {collection})"
                )
            seen[candidate_id] = collection


def coalesce_candidate_ids(items: list[dict[str, Any]]) -> None:
    """Merge same-ID orphan detail rows without creating a second candidate."""
    by_id: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    list_fields = {
        "sources", "owners", "classes", "nice_classes", "views", "figures",
        "titles", "applicants", "classifications", "ipc_classes", "cpc_classes",
        "publication_numbers", "application_numbers", "priority_numbers",
        "family_members", "legal_events", "detail_operations", "evidence_refs",
        "verification_refs", "publication_documents", "publication_relations",
    }
    for item in items:
        candidate_id = str(item.get("candidate_id") or "").strip()
        current = by_id.get(candidate_id)
        if current is None or not candidate_id:
            if candidate_id:
                by_id[candidate_id] = item
            ordered.append(item)
            continue
        current["official_verification"] = better_verification(
            current.get("official_verification"), item.get("official_verification"),
        )
        for field, value in item.items():
            if field == "conflicts":
                # A conflict map is bookkeeping, never an alternative value of
                # itself. Treating it like an ordinary field appends this map
                # into its own list after any preceding field conflict.
                target = current.setdefault("conflicts", {})
                if not isinstance(value, dict) or not isinstance(target, dict):
                    raise ValueError("CANDIDATE_CONFLICTS_INVALID: expected an alternatives map")
                for name, alternatives in value.items():
                    existing = target.get(name, [])
                    if not isinstance(existing, list) or not isinstance(alternatives, list):
                        raise ValueError("CANDIDATE_CONFLICTS_INVALID: alternatives must be lists")
                    target[name] = unique_list([*existing, *alternatives])
            elif field in list_fields and isinstance(value, list):
                current[field] = unique_list([*current.get(field, []), *value])
            elif field not in current or current[field] in (None, "", [], {}):
                current[field] = value
            elif field not in {
                "candidate_id", "material", "material_reason", "disposition",
                "official_verification", *list_fields,
            } and current[field] != value:
                claims = current.setdefault("conflicts", {}).setdefault(field, [])
                for claim in (current[field], value):
                    if claim not in claims:
                        claims.append(claim)
    items[:] = ordered


def expand_family_candidates(patents: list[dict[str, Any]]) -> None:
    """Known family publications become independent, initially unreviewed rights."""
    known = {patent_key(item) for item in patents}
    derived = []
    for parent in list(patents):
        values = [*(parent.get("family_members", []) if isinstance(parent.get("family_members"), list) else []),
                  *(parent.get("publication_numbers", []) if isinstance(parent.get("publication_numbers"), list) else [])]
        for value in values:
            number = re.sub(r"[\s./-]", "", str(value)).upper()
            if not re.fullmatch(r"(?:US|GB|FR|DE|IT|ES|JP|EP|WO)(?:D|RE|PP)?\d+[A-CUSY]\d?", number):
                continue
            country = number[:2]
            right = intrinsic_patent_right_type(country, number) or "patent"
            child = {"publication_number": number, "jurisdiction": country, "right_type": right}
            key = patent_key(child)
            if key in known:
                continue
            known.add(key)
            family_sources = [source for source in parent.get("sources", []) if source.get("operation") == "candidate_detail"]
            child.update(normalization_key=key, candidate_id=stable_id("CAND", "patent", key),
                         family_id=parent.get("family_id", ""), family_members=values,
                         family_parent_publication=parent.get("publication_number", ""),
                         sources=family_sources or list(parent.get("sources", [])),
                         material=False, disposition="unreviewed", conflicts={}, right_state="unknown",
                         role="discovery_only", authoritative_for_final_rating=False,
                         official_verification={"status": "not_checked"})
            derived.append(child)
    patents.extend(derived)


def add_family_groups(patents: list[dict[str, Any]], *, preserve_identifiers: bool = False) -> None:
    families: dict[str, list[str]] = {}
    for item in patents:
        family = str(item.get("family_id") or "").strip()
        if family:
            families.setdefault(family, []).append(str(item.get("normalization_key") or ""))
    for item in patents:
        family = str(item.get("family_id") or "").strip()
        if family:
            item["family_group_key"] = f"family:{family}"
            keys = [value for value in families.get(family, []) if value]
            if preserve_identifiers:
                item["family_candidate_keys"] = keys
                actual = [p.get("publication_number") for p in patents if p.get("family_id") == family and p.get("publication_number")]
                previous = item.get("family_members", [])
                item["family_members"] = unique_list([*(previous if isinstance(previous, list) else []), *actual])
            else:
                item["family_members"] = keys


def candidate_right_type(kind: str, item: dict[str, Any]) -> str:
    explicit = str(item.get("right_type") or "").strip()
    if explicit:
        return explicit
    if kind in {"copyright", "copyright_assets"}:
        return "copyright"
    if kind == "enforcement":
        return "enforcement"
    source = str(item.get("source") or "")
    if kind == "trademark":
        return "trademark_figurative" if any(
            item.get(field) for field in ("figurative_id", "image_url", "image", "vienna_classes")
        ) else "trademark_word"
    if "design" in source or item.get("locarno") or item.get("views"):
        return "design"
    kind_code = str(item.get("kind_code") or "").upper()
    if kind_code.startswith("S"):
        return "design"
    if "utility_model" in source or kind_code.startswith("U"):
        return "utility_model"
    return "patent"


def module_for(right_type: str) -> str:
    return {
        "design": "appearance_patent",
        "patent": "utility_patent",
        "utility_model": "utility_patent",
        "trademark_word": "word_mark",
        "trademark_figurative": "figurative_trade_dress",
        "copyright": "copyright_ip",
        "enforcement": "enforcement",
    }.get(right_type, "utility_patent")


def normalize_verification(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("official_verification")
    verification = dict(raw) if isinstance(raw, dict) else {}
    status = str(verification.get("status") or "not_checked")
    authority = str(
        verification.get("authority")
        or verification.get("source")
        or item.get("verification_authority")
        or ""
    )
    owners = verification.get("owner") or verification.get("owners") or item.get("owner") or item.get("owners") or []
    classes = (
        verification.get("classes") or item.get("nice_classes") or item.get("locarno")
        or item.get("goods_services") or []
    )
    browser_evidence = item.get("browser_evidence") if isinstance(item.get("browser_evidence"), dict) else {}
    media = (
        verification.get("media") or item.get("media") or item.get("views")
        or browser_evidence.get("evidence_images")
        or ([browser_evidence.get("mark_image_path")] if browser_evidence.get("mark_image_path") else [])
        or []
    )
    verification.update({
        "status": status,
        "authority": authority,
        "method": str(verification.get("method") or ""),
        # Identity must be affirmatively established by the official adapter.
        # A generic ``verified`` status cannot silently manufacture this field.
        "identity_match": verification.get("identity_match"),
        "legal_status": str(
            verification.get("legal_status") or item.get("legal_status")
            or item.get("case_status") or item.get("status") or ""
        ),
        "owner": owners,
        "classes": classes,
        "media": media,
        "checked_at": str(verification.get("checked_at") or ""),
    })
    return verification


def apply_candidate_contract(kind: str, items: list[dict[str, Any]]) -> None:
    for item in items:
        key = str(item.get("normalization_key") or "")
        right_type = candidate_right_type(kind, item)
        inferred_module = module_for(right_type)
        if right_type == "patent" and str(item.get("kind_code") or "").upper().startswith("A"):
            inferred_module = "pending_application"
        item["candidate_id"] = str(item.get("candidate_id") or stable_id("CAND", kind, key))
        item["right_type"] = right_type
        # Module assignment is derived from the normalized right type.  Source
        # payloads cannot promote a candidate into a different formal module.
        item["module"] = inferred_module
        item["module_id"] = inferred_module
        item["material"] = bool(item.get("material", False))
        item["material_reason"] = str(item.get("material_reason") or ("source_marked_material" if item["material"] else ""))
        item["disposition"] = str(item.get("disposition") or "unreviewed")
        source_refs = [
            str(source.get("evidence_id") or "")
            for source in item.get("sources", [])
            if isinstance(source, dict) and source.get("evidence_id")
        ]
        item["evidence_refs"] = unique_list([*item.get("evidence_refs", []), *source_refs])
        item["verification_refs"] = unique_list(item.get("verification_refs", []))
        item["official_verification"] = normalize_verification(item)


def mark_material(task: dict[str, Any], patents: list[dict[str, Any]], trademarks: list[dict[str, Any]]) -> None:
    brand = normalize_text(str(task.get("product", {}).get("brand") or ""))
    for item in trademarks:
        mark = normalize_text(str(item.get("mark_text") or ""))
        if brand and mark == brand:
            item["material"] = True
            item["material_reason"] = "exact_product_brand_match"
    for item in patents:
        item["material"] = bool(item.get("material", False))
        if item["material"] and not item.get("material_reason"):
            item["material_reason"] = "source_marked_material"


EPO_DETAIL_OPERATIONS = ("biblio", "family", "legal")


def _epo_candidate_document(item: dict[str, Any]) -> str:
    for field in ("publication_number", "record_number", "grant_number", "application_number"):
        value = re.sub(r"[^A-Za-z0-9]", "", str(item.get(field) or "")).upper()
        if value:
            return value
    return ""


def _epo_detail_requirement_ids(
    task: dict[str, Any], jurisdiction: str, right_type: str,
) -> list[str]:
    return [
        str(requirement.get("requirement_id") or "")
        for requirement in task.get("coverage_requirements", [])
        if isinstance(requirement, dict)
        and str(requirement.get("jurisdiction") or "").upper() == jurisdiction
        and str(requirement.get("right_type") or "") == right_type
        and any(
            isinstance(route, dict)
            and route.get("provider") == "epo_ops"
            and route.get("operation") == "candidate_detail"
            for route in requirement.get("routes", [])
        )
    ]


def _epo_detail_jurisdiction(
    task: dict[str, Any], item: dict[str, Any], right_type: str,
) -> str:
    configured = {
        str(requirement.get("jurisdiction") or "").upper()
        for requirement in task.get("coverage_requirements", [])
        if isinstance(requirement, dict)
        and str(requirement.get("right_type") or "") == right_type
        and any(
            isinstance(route, dict)
            and route.get("provider") == "epo_ops"
            and route.get("operation") == "candidate_detail"
            for route in requirement.get("routes", [])
        )
    }
    source_jurisdictions = [
        str(source.get("jurisdiction") or "").upper()
        for source in item.get("sources", [])
        if isinstance(source, dict) and source.get("provider") == "epo_ops"
    ]
    candidate_jurisdiction = str(item.get("jurisdiction") or "").upper()
    candidates = [*source_jurisdictions, "EU" if candidate_jurisdiction == "EP" else candidate_jurisdiction]
    return next((value for value in candidates if value in configured), "")


def append_epo_candidate_detail_actions(
    task_dir: Path, task: dict[str, Any], patents: list[dict[str, Any]],
) -> None:
    """Append bounded, optional EPO enrichment for recalled material candidates."""
    plan_path = task_dir / "search-plan.json"
    if not plan_path.is_file():
        return
    plan = ensure_object(load_json(plan_path), "search-plan.json")
    queries = plan.setdefault("queries", {})
    bucket = queries.setdefault("epo_ops", [])
    limit = max(int(load_skill_config().get("limits", {}).get("epo_candidate_detail_limit", 0)), 0)
    existing_count = sum(
        1 for row in bucket
        if isinstance(row, dict) and row.get("operation") == "candidate_detail"
    )
    remaining = max(limit - existing_count, 0)
    if remaining < len(EPO_DETAIL_OPERATIONS):
        return

    recalled_material = []
    for item in patents:
        if not isinstance(item, dict) or not item.get("material"):
            continue
        if not any(
            isinstance(source, dict)
            and source.get("provider") == "epo_ops"
            and source.get("operation") != "candidate_detail"
            for source in item.get("sources", [])
        ):
            continue
        right_type = str(item.get("right_type") or "")
        document = _epo_candidate_document(item)
        jurisdiction = _epo_detail_jurisdiction(task, item, right_type)
        if document and jurisdiction and right_type in {"patent", "utility_model", "design"}:
            recalled_material.append((str(item.get("candidate_id") or ""), document, jurisdiction, right_type))

    known_ids = {
        str(row.get("query_id") or "") for row in bucket if isinstance(row, dict)
    }
    for candidate_id, document, jurisdiction, right_type in sorted(set(recalled_material)):
        if remaining < len(EPO_DETAIL_OPERATIONS):
            break
        actions: list[dict[str, Any]] = []
        requirement_ids = _epo_detail_requirement_ids(task, jurisdiction, right_type)
        if not candidate_id or not requirement_ids:
            continue
        for detail_operation in EPO_DETAIL_OPERATIONS:
            params = {
                "q": document,
                "document": document,
                "detail_operation": detail_operation,
                "candidate_id": candidate_id,
                "right_type": right_type,
            }
            action = {
                **params,
                "query_id": query_identity(
                    "epo_ops", "candidate_detail", jurisdiction, document, params,
                ),
                "operation": "candidate_detail",
                "jurisdiction": jurisdiction,
                "required": False,
                "required_for": "low_risk",
                "requirement_ids": requirement_ids,
                "wave": 2,
                "derived_from": [f"normalized-candidates:{candidate_id}"],
                "execute_by_default": True,
            }
            if action["query_id"] not in known_ids:
                actions.append(action)
        if len(actions) > remaining:
            break
        for action in actions:
            known_ids.add(str(action["query_id"]))
            bucket.append(action)
        remaining -= len(actions)
    plan["queries"] = {provider: rows for provider, rows in queries.items() if rows}
    atomic_write_json(plan_path, plan)


def _jp_candidate_number(item: dict[str, Any], right_type: str) -> tuple[str, str]:
    """Choose a traceable known identifier for JPO number-reference/detail APIs."""
    for field, kind in (
        ("application_number", "application"),
        ("registration_number", "registration"),
        ("grant_number", "registration"),
    ):
        value = str(item.get(field) or "").strip()
        if value:
            return value, kind
    publication = str(item.get("publication_number") or item.get("record_number") or "").strip()
    if publication:
        return publication, "publication" if right_type == "patent" else "registration"
    return "", ""


def _candidate_verification_requirement_ids(
    task: dict[str, Any], provider: str, right_type: str,
) -> list[str]:
    return [
        str(requirement.get("requirement_id"))
        for requirement in task.get("coverage_requirements", [])
        if isinstance(requirement, dict)
        and requirement.get("phase") == "candidate_verification"
        and str(requirement.get("jurisdiction") or "").upper() == "JP"
        and str(requirement.get("right_type") or "") == right_type
        and any(
            isinstance(route, dict)
            and route.get("provider") == provider
            and route.get("operation") == "candidate_verification"
            for route in requirement.get("routes", [])
        )
    ]


def _eu_candidate_verification_requirement_ids(
    task: dict[str, Any], provider: str, right_type: str,
    jurisdiction: str = "EU",
) -> list[str]:
    return [
        str(requirement.get("requirement_id"))
        for requirement in task.get("coverage_requirements", [])
        if isinstance(requirement, dict)
        and requirement.get("phase") == "candidate_verification"
        and str(requirement.get("jurisdiction") or "").upper() == jurisdiction.upper()
        and str(requirement.get("right_type") or "") == right_type
        and any(
            isinstance(route, dict)
            and route.get("provider") == provider
            and route.get("operation") == "candidate_verification"
            for route in requirement.get("routes", [])
        )
    ]


def _public_candidate_verification_requirement_ids(
    task: dict[str, Any], jurisdiction: str, right_type: str,
) -> list[str]:
    return [
        str(requirement.get("requirement_id") or "")
        for requirement in task.get("coverage_requirements", [])
        if isinstance(requirement, dict)
        and requirement.get("phase") == "candidate_verification"
        and str(requirement.get("jurisdiction") or "").upper() == jurisdiction.upper()
        and str(requirement.get("right_type") or "") == right_type
        and any(
            isinstance(route, dict)
            and route.get("provider") == "public_web_browser"
            and route.get("operation") == "candidate_verification"
            for route in requirement.get("routes", [])
        )
    ]


def _usable_public_record_identifier(item: dict[str, Any], right_type: str) -> tuple[str, str]:
    """Return only an explicit, plausibly usable official identifier.

    Public-record verification must never manufacture a number from a candidate
    ID, title, snippet, or URL.  The syntax check is deliberately conservative:
    a public registration/proceeding identifier must contain a digit and cannot
    be a placeholder or URL.  Authority-specific validation still happens in
    the browser recorder against the rendered official record.
    """
    for field in PUBLIC_RECORD_IDENTIFIER_FIELDS.get(right_type, ()):
        value = str(item.get(field) or "").strip()
        placeholder = re.sub(r"[^\w]+", "", value, flags=re.UNICODE).casefold()
        if (
            not value
            or len(value) > 160
            or placeholder in PUBLIC_RECORD_IDENTIFIER_PLACEHOLDERS
            or "://" in value
            or value.casefold().startswith("www.")
            or any(ord(character) < 32 for character in value)
            or not any(character.isdigit() for character in value)
        ):
            continue
        return field, value
    return "", ""


def _public_identifier_action(
    task_dir: Path, item: dict[str, Any], *, jurisdiction: str,
    right_type: str, requirement_ids: list[str], source_keys: list[str],
) -> dict[str, Any]:
    candidate_id = str(item.get("candidate_id") or "").strip()
    recall_operation = "copyright_recall" if right_type == "copyright" else "enforcement_recall"
    accepted_fields = list(PUBLIC_RECORD_IDENTIFIER_FIELDS[right_type])
    resume_argv = [
        "python3", str(Path(__file__).resolve()), "--task-dir", str(task_dir),
    ]
    return {
        "action_id": stable_id(
            "ACTION", PUBLIC_RECORD_IDENTIFIER_REQUIRED, candidate_id,
            jurisdiction, right_type,
        ),
        "status": "needs_user_action",
        "error_code": PUBLIC_RECORD_IDENTIFIER_REQUIRED,
        "provider": "public_web_browser",
        "operation": "candidate_verification",
        "next_operation": recall_operation,
        "candidate_id": candidate_id,
        "jurisdiction": jurisdiction,
        "right_type": right_type,
        "requirement_ids": requirement_ids,
        "source_keys": [value for value in source_keys if value],
        "accepted_identifier_fields": accepted_fields,
        "instruction": (
            "在适用的官方公共登记库中完成已计划的可见浏览器召回，"
            "从具体记录页面抄录页面实际显示的精确登记号/案号，"
            f"并以当前 candidate_id={candidate_id} 随召回证据入库；"
            "不得从 candidate_id、标题、摘要或 URL 推断编号。完成后重新运行候选合并。"
        ),
        "required_capture_binding": {"candidate_id": candidate_id},
        "resume_argv": resume_argv,
        "resume_command": " ".join(shlex.quote(value) for value in resume_argv),
        "do_not_infer_from": ["candidate_id", "title", "name", "snippet", "url", "source_url"],
    }


def _sync_public_identifier_actions(
    task: dict[str, Any], actions: list[dict[str, Any]],
) -> None:
    """Replace only this merge-owned gap family, clearing resolved candidates."""
    task.setdefault("coverage_gaps", [])[:] = [
        gap for gap in task.get("coverage_gaps", [])
        if not (
            isinstance(gap, dict)
            and gap.get("error_code") == PUBLIC_RECORD_IDENTIFIER_REQUIRED
        )
    ]
    ordered = sorted(actions, key=lambda item: str(item.get("candidate_id") or ""))
    for action in ordered:
        requirement_ids = [
            str(value) for value in action.get("requirement_ids", []) if str(value).strip()
        ]
        task["coverage_gaps"].append({
            "provider": "public_web_browser",
            "operation": "candidate_verification",
            "jurisdiction": action["jurisdiction"],
            "right_type": action["right_type"],
            "status": "needs_user_action",
            "error_code": PUBLIC_RECORD_IDENTIFIER_REQUIRED,
            "affected_modules": [module_for(str(action["right_type"]))],
            "detail": action["instruction"],
            "mandatory": True,
            "query_id": "",
            "candidate_id": action["candidate_id"],
            "requirement_id": requirement_ids[0] if requirement_ids else "",
            "requirement_ids": requirement_ids,
            "user_action": action,
            "at": now_iso(),
        })
    task.setdefault("checkpoints", {})["public_record_identifier_resolution"] = {
        "status": "needs_user_action" if ordered else "success",
        "at": now_iso(),
        "error_code": PUBLIC_RECORD_IDENTIFIER_REQUIRED if ordered else "",
        "pending": len(ordered),
        "actions": ordered,
    }


def _public_candidate_source_keys(
    item: dict[str, Any], jurisdiction: str, right_type: str,
) -> list[str]:
    """Resolve the exact US public source; fan out only when discovery was ambiguous."""
    if jurisdiction != "US":
        return [""]
    allowed = US_PUBLIC_SOURCE_KEYS.get(right_type, ())
    observed: list[str] = []
    direct = str(item.get("source_key") or "").strip()
    if direct:
        observed.append(direct)
    for source in item.get("sources", []):
        if not isinstance(source, dict) or source.get("provider") != "public_web_browser":
            continue
        source_key = str(source.get("source_key") or "").strip()
        if source_key:
            observed.append(source_key)
    for field in ("url", "source_url"):
        try:
            host = (urlparse(str(item.get(field) or "")).hostname or "").casefold()
        except ValueError:
            host = ""
        mapped = US_PUBLIC_SOURCE_HOSTS.get(host, "")
        if mapped:
            observed.append(mapped)
    selected = list(dict.fromkeys(value for value in observed if value in allowed))
    return selected or list(allowed)


def _candidate_document_for_jurisdiction(
    item: dict[str, Any], jurisdiction: str,
) -> str:
    """Choose an own/family publication that the target authority can resolve."""
    def list_value(name: str) -> list[Any]:
        value = item.get(name)
        if isinstance(value, list):
            return value
        return [value] if value not in (None, "") else []

    values = unique_list([
        item.get("publication_number"), item.get("record_number"),
        item.get("grant_number"), item.get("application_number"),
        *list_value("family_members"), *list_value("publication_numbers"),
        *list_value("identifiers"),
    ])
    normalized = [
        re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()
        for value in values if str(value or "").strip()
    ]
    target = jurisdiction.upper()
    prefixes = {"EU": ("EP",), "US": ("US",), "JP": ("JP",)}.get(
        target,
        (target, "EP") if target in AMAZON_EU_COUNTRIES | {"GB"} else (target,),
    )
    return next((
        value for prefix in prefixes for value in normalized
        if value.startswith(prefix)
    ), "")


def _append_browser_candidate_action(
    queries: dict[str, list[dict[str, Any]]], *, provider: str,
    jurisdiction: str, right_type: str, identifier: str, candidate_id: str,
    requirement_ids: list[str], mode: str = "user_assisted",
    record_field: str = "record_number", source_key: str = "",
) -> None:
    if not identifier or not candidate_id or not requirement_ids:
        return
    params = {
        "q": identifier, "candidate_id": candidate_id,
        "right_type": right_type, record_field: identifier,
    }
    if provider != "uspto_patent_browser":
        params["mode"] = mode
    if source_key:
        params["source_key"] = source_key
    action = {
        **params,
        "query_id": query_identity(
            provider, "candidate_verification", jurisdiction, identifier, params,
        ),
        "operation": "candidate_verification",
        "jurisdiction": jurisdiction,
        "required": False,
        "required_for": "formal",
        "requirement_ids": requirement_ids,
        "wave": 2,
        "derived_from": [f"normalized-candidates:{candidate_id}"],
        "execute_by_default": True,
    }
    bucket = queries.setdefault(provider, [])
    if not any(
        isinstance(row, dict) and row.get("query_id") == action["query_id"]
        for row in bucket
    ):
        bucket.append(action)


def append_public_web_candidate_verification_actions(
    task_dir: Path, task: dict[str, Any], copyright_assets: list[dict[str, Any]],
    enforcement: list[dict[str, Any]],
) -> None:
    """Append exact, source-bound public-record checks after candidate IDs exist."""
    plan_path = task_dir / "search-plan.json"
    targets = {
        str(value).upper() for value in task.get("target_jurisdictions", [])
        if str(value).strip()
    }
    plan = (
        ensure_object(load_json(plan_path), "search-plan.json")
        if plan_path.is_file() else None
    )
    queries = plan.setdefault("queries", {}) if plan is not None else {}
    identifier_actions: list[dict[str, Any]] = []
    for item in [*copyright_assets, *enforcement]:
        if not isinstance(item, dict) or not item.get("material"):
            continue
        right_type = str(item.get("right_type") or "")
        if right_type not in {"copyright", "enforcement"}:
            continue
        jurisdiction = str(item.get("jurisdiction") or item.get("office") or "").upper()
        if jurisdiction == "EUIPO":
            jurisdiction = "EU"
        if jurisdiction not in targets:
            continue
        candidate_id = str(item.get("candidate_id") or "").strip()
        requirement_ids = _public_candidate_verification_requirement_ids(
            task, jurisdiction, right_type,
        )
        source_keys = _public_candidate_source_keys(item, jurisdiction, right_type)
        _record_field, identifier = _usable_public_record_identifier(item, right_type)
        if not identifier:
            identifier_actions.append(_public_identifier_action(
                task_dir, item, jurisdiction=jurisdiction, right_type=right_type,
                requirement_ids=requirement_ids, source_keys=source_keys,
            ))
            continue
        if plan is None:
            continue
        for source_key in source_keys:
            _append_browser_candidate_action(
                queries, provider="public_web_browser", jurisdiction=jurisdiction,
                right_type=right_type, identifier=identifier,
                candidate_id=candidate_id, requirement_ids=requirement_ids,
                mode="manual_capture", source_key=source_key,
            )
    _sync_public_identifier_actions(task, identifier_actions)
    if plan is None:
        return
    plan["queries"] = {provider: rows for provider, rows in queries.items() if rows}
    atomic_write_json(plan_path, plan)


def append_us_candidate_verification_actions(
    task_dir: Path, task: dict[str, Any], patents: list[dict[str, Any]],
    trademarks: list[dict[str, Any]],
) -> None:
    """Route material US and WO-family candidates to official USPTO detail."""
    plan_path = task_dir / "search-plan.json"
    if not plan_path.is_file() or "US" not in {
        str(value).upper() for value in task.get("target_jurisdictions", [])
    }:
        return
    plan = ensure_object(load_json(plan_path), "search-plan.json")
    queries = plan.setdefault("queries", {})
    for item in patents:
        if not isinstance(item, dict) or not item.get("material"):
            continue
        right_type = str(item.get("right_type") or "")
        if right_type not in {"patent", "design"}:
            continue
        identifier = _candidate_document_for_jurisdiction(item, "US")
        requirement_ids = _eu_candidate_verification_requirement_ids(
            task, "uspto_patent_browser", right_type, "US",
        )
        _append_browser_candidate_action(
            queries, provider="uspto_patent_browser", jurisdiction="US",
            right_type=right_type, identifier=identifier,
            candidate_id=str(item.get("candidate_id") or "").strip(),
            requirement_ids=requirement_ids,
        )
    for item in trademarks:
        if not isinstance(item, dict) or not item.get("material"):
            continue
        jurisdiction = str(item.get("jurisdiction") or item.get("office") or "").upper()
        right_type = str(item.get("right_type") or "")
        if jurisdiction not in {"US", "USPTO"} or right_type not in {
            "trademark_word", "trademark_figurative",
        }:
            continue
        identifier = str(
            item.get("serial_number") or item.get("application_number") or ""
        ).strip()
        _append_browser_candidate_action(
            queries, provider="uspto_tsdr", jurisdiction="US",
            right_type=right_type, identifier=identifier,
            candidate_id=str(item.get("candidate_id") or "").strip(),
            requirement_ids=_eu_candidate_verification_requirement_ids(
                task, "uspto_tsdr", right_type, "US",
            ),
            record_field="serial_number",
        )
    plan["queries"] = {provider: rows for provider, rows in queries.items() if rows}
    atomic_write_json(plan_path, plan)


def append_eu_candidate_verification_actions(
    task_dir: Path, task: dict[str, Any], patents: list[dict[str, Any]],
    trademarks: list[dict[str, Any]],
) -> None:
    """Append EUIPO, EPO Register, and target-country verification actions."""
    plan_path = task_dir / "search-plan.json"
    targets = {
        str(value).upper() for value in task.get("target_jurisdictions", [])
    }
    national_targets = sorted(targets & (AMAZON_EU_COUNTRIES | {"GB"}))
    if not plan_path.is_file() or not ({"EU"} & targets or national_targets):
        return
    plan = ensure_object(load_json(plan_path), "search-plan.json")
    queries = plan.setdefault("queries", {})
    for item in [*patents, *trademarks]:
        if not isinstance(item, dict) or not item.get("material"):
            continue
        item_jurisdiction = str(item.get("jurisdiction") or item.get("office") or "").upper()
        source_jurisdictions = {
            str(source.get("jurisdiction") or "").upper()
            for source in item.get("sources", []) if isinstance(source, dict)
        }
        candidate_jurisdictions = {item_jurisdiction, *source_jurisdictions} - {""}
        right_type = str(item.get("right_type") or "")
        candidate_id = str(item.get("candidate_id") or "").strip()
        if right_type == "patent" and item_jurisdiction in {"EU", "EP", "WO"} and "EU" in targets:
            identifier = _candidate_document_for_jurisdiction(item, "EU")
            _append_browser_candidate_action(
                queries, provider="epo_register_browser", jurisdiction="EU",
                right_type="patent", identifier=identifier,
                candidate_id=candidate_id,
                requirement_ids=_eu_candidate_verification_requirement_ids(
                    task, "epo_register_browser", "patent", "EU",
                ),
            )
        # Every material target-country candidate discovered through TMview,
        # DesignView, EPO family data, or a national recall must return to the
        # competent national register.  This also covers a GB-only task.
        applicable_countries = [
            country for country in national_targets
            if country in candidate_jurisdictions
            or (
                right_type in {"patent", "utility_model"}
                and bool(candidate_jurisdictions & {"EU", "EP", "WO"})
            )
        ]
        for country in applicable_countries:
            if right_type not in {
                "patent", "utility_model", "design",
                "trademark_word", "trademark_figurative",
            }:
                continue
            if right_type in {"patent", "utility_model"}:
                identifier = _candidate_document_for_jurisdiction(item, country)
            elif right_type == "design":
                identifier = str(
                    item.get("registration_number") or item.get("application_number")
                    or item.get("publication_number") or item.get("record_number") or ""
                ).strip()
            else:
                identifier = str(
                    item.get("registration_number") or item.get("application_number")
                    or item.get("serial_number") or item.get("record_number") or ""
                ).strip()
            _append_browser_candidate_action(
                queries, provider="official_registry_browser",
                jurisdiction=country, right_type=right_type,
                identifier=identifier, candidate_id=candidate_id,
                requirement_ids=_eu_candidate_verification_requirement_ids(
                    task, "official_registry_browser", right_type, country,
                ),
            )
        if item_jurisdiction not in {"EU", "EUIPO"}:
            continue
        if right_type == "design":
            provider = "euipo_design"
            identifier = str(
                item.get("publication_number") or item.get("application_number") or ""
            ).strip()
        elif right_type in {"trademark_word", "trademark_figurative"}:
            provider = "euipo_trademark"
            # The 1.1.0 detail resource is keyed by applicationNumber.  A bare
            # registration number is deliberately not guessed into that slot.
            identifier = str(item.get("application_number") or "").strip()
        else:
            continue
        requirement_ids = _eu_candidate_verification_requirement_ids(
            task, provider, right_type,
        )
        if not candidate_id or not identifier or not requirement_ids:
            continue
        params = {
            "q": identifier,
            "identifier": identifier,
            "candidate_id": candidate_id,
            "right_type": right_type,
            "detail": True,
        }
        action = {
            **params,
            "query_id": query_identity(
                provider, "candidate_verification", "EU", identifier, params,
            ),
            "operation": "candidate_verification",
            "jurisdiction": "EU",
            "required": False,
            "required_for": "formal",
            "requirement_ids": requirement_ids,
            "wave": 1,
            "derived_from": [f"normalized-candidates:{candidate_id}"],
            "execute_by_default": True,
        }
        bucket = queries.setdefault(provider, [])
        if not any(
            isinstance(row, dict) and row.get("query_id") == action["query_id"]
            for row in bucket
        ):
            bucket.append(action)
    plan["queries"] = {provider: rows for provider, rows in queries.items() if rows}
    atomic_write_json(plan_path, plan)


def append_jp_candidate_verification_actions(
    task_dir: Path, task: dict[str, Any], patents: list[dict[str, Any]],
    trademarks: list[dict[str, Any]],
) -> None:
    """Append API-first/J-PlatPat-fallback actions after candidate IDs exist."""
    plan_path = task_dir / "search-plan.json"
    if not plan_path.is_file() or "JP" not in {
        str(value).upper() for value in task.get("target_jurisdictions", [])
    }:
        return
    plan = ensure_object(load_json(plan_path), "search-plan.json")
    queries = plan.setdefault("queries", {})
    for item in [*patents, *trademarks]:
        if not isinstance(item, dict) or not item.get("material"):
            continue
        jurisdiction = str(item.get("jurisdiction") or item.get("office") or "").upper()
        right_type = str(item.get("right_type") or "")
        if jurisdiction not in {"JP", "JPO", "WO"} or right_type not in {
            "patent", "utility_model", "design", "trademark_word", "trademark_figurative",
        }:
            continue
        if jurisdiction == "WO":
            number = _candidate_document_for_jurisdiction(item, "JP")
            number_kind = "publication"
        else:
            number, number_kind = _jp_candidate_number(item, right_type)
        if not number:
            continue
        candidate_id = str(item.get("candidate_id") or "").strip()
        common = {
            "q": number,
            "number": number,
            "number_kind": number_kind,
            "candidate_id": candidate_id,
            "operation": "candidate_verification",
            "jurisdiction": "JP",
            "right_type": right_type,
            "required": False,
            "required_for": "formal",
            "wave": 1,
            "derived_from": [f"normalized-candidates:{candidate_id}"],
        }
        if right_type != "utility_model":
            params = {
                "number": number, "number_kind": number_kind,
                "candidate_id": candidate_id, "right_type": right_type,
            }
            api_entry = {
                **common,
                "query_id": query_identity(
                    "jpo_api", "candidate_verification", "JP", number, params,
                ),
                "requirement_ids": _candidate_verification_requirement_ids(
                    task, "jpo_api", right_type,
                ),
                "execute_by_default": True,
                "fallback_provider": "jplatpat_browser",
            }
            bucket = queries.setdefault("jpo_api", [])
            if not any(row.get("query_id") == api_entry["query_id"] for row in bucket if isinstance(row, dict)):
                bucket.append(api_entry)
        fallback_params = {
            "q": number, "candidate_id": candidate_id,
            "mode": "user_assisted", "right_type": right_type,
        }
        fallback_entry = {
            **fallback_params,
            "operation": "candidate_verification",
            "jurisdiction": "JP",
            "required": False,
            "required_for": "formal",
            "wave": 1,
            "derived_from": [f"normalized-candidates:{candidate_id}"],
            "query_id": query_identity(
                "jplatpat_browser", "candidate_verification", "JP", number,
                fallback_params,
            ),
            "requirement_ids": _candidate_verification_requirement_ids(
                task, "jplatpat_browser", right_type,
            ),
            "execute_when": "jpo_api_incomplete" if right_type != "utility_model" else "always",
        }
        bucket = queries.setdefault("jplatpat_browser", [])
        if not any(row.get("query_id") == fallback_entry["query_id"] for row in bucket if isinstance(row, dict)):
            bucket.append(fallback_entry)
    plan["queries"] = {provider: rows for provider, rows in queries.items() if rows}
    atomic_write_json(plan_path, plan)


def dynamic_candidate_action_ids(
    task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any],
) -> set[str]:
    """Return material candidates plus excluded candidates needing mismatch repair."""
    from finalize_assessment import material_unverified

    all_candidates = [
        item
        for collection in ("patents", "trademarks", "copyright_assets", "enforcement")
        for item in candidates.get(collection, [])
        if isinstance(item, dict)
    ]
    material_ids = {
        str(item.get("candidate_id") or "").strip()
        for item in all_candidates if item.get("material")
    }
    repair_ids = set(material_unverified(
        candidates, strict=True, evidence=evidence, task=task,
    ))
    excluded_repair_ids = {
        str(item.get("candidate_id") or "").strip()
        for item in all_candidates
        if str(item.get("disposition") or "") == "excluded"
        and str(item.get("candidate_id") or "").strip() in repair_ids
    }
    return material_ids | excluded_repair_ids


def prune_dynamic_candidate_actions(
    task_dir: Path, task: dict[str, Any], evidence: dict[str, Any],
    candidates: dict[str, Any],
) -> None:
    """Remove stale actions while preserving executed verification provenance."""
    plan_path = task_dir / "search-plan.json"
    if not plan_path.is_file():
        return
    retained_ids = dynamic_candidate_action_ids(task, evidence, candidates)
    recorded_verification_query_ids = {
        str(item.get("query_id") or "").strip()
        for item in [
            *evidence.get("source_runs", []),
            *evidence.get("collections", {}).get("official_verifications", []),
        ]
        if isinstance(item, dict)
        and item.get("operation") == "candidate_verification"
        and str(item.get("query_id") or "").strip()
    }
    plan = ensure_object(load_json(plan_path), "search-plan.json")
    queries = plan.get("queries", {})
    if not isinstance(queries, dict):
        return
    for provider, entries in list(queries.items()):
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            candidate_id = str(entry.get("candidate_id") or "").strip() if isinstance(entry, dict) else ""
            derived = entry.get("derived_from", []) if isinstance(entry, dict) else []
            dynamic = bool(
                candidate_id
                and entry.get("operation") in {"candidate_detail", "candidate_verification"}
                and f"normalized-candidates:{candidate_id}" in derived
            )
            executed_verification = bool(
                isinstance(entry, dict)
                and entry.get("operation") == "candidate_verification"
                and str(entry.get("query_id") or "").strip()
                in recorded_verification_query_ids
            )
            if not dynamic or candidate_id in retained_ids or executed_verification:
                kept.append(entry)
        queries[provider] = kept
    plan["queries"] = {provider: rows for provider, rows in queries.items() if rows}
    atomic_write_json(plan_path, plan)


@timed_cli("candidate_merge")
def main() -> None:
    parser = argparse.ArgumentParser(description="Merge cross-source IPR candidates.")
    parser.add_argument("--task-dir", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if not is_active_schema(task):
        raise SystemExit("LEGACY_TASK_READ_ONLY: 2.1/2.2 candidates cannot be regenerated")
    assert_active_free_policy(task)
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    collections = evidence.get("collections", {})
    runs = {str(run.get("run_id")): run for run in evidence.get("source_runs", [])}
    official_entries = collections.get("official_verifications", [])
    official_providers = {
        "uspto_patent_browser", "uspto_tsdr", "euipo_trademark", "euipo_design",
        "jpo_api", "jplatpat_browser", "epo_register_browser", "official_registry_browser",
        "public_web_browser",
    }
    if task.get("schema_version") == "2.4-free":
        official_providers.add("inpi_api")
    from record_candidate_lead import validated_candidate_lead_entries
    lead_entries = validated_candidate_lead_entries(task, evidence, task_dir)
    patents = merge("patent", [*collections.get("patents", []), *lead_entries], runs)
    if task.get("schema_version") == "2.4-free":
        expand_family_candidates(patents)
    trademarks = merge("trademark", collections.get("trademarks", []), runs)
    copyright_assets = merge("copyright", collections.get("copyright_assets", []), runs)
    enforcement = merge("enforcement", collections.get("enforcement", []), runs)
    apply_candidate_contract("patent", patents)
    apply_candidate_contract("trademark", trademarks)
    apply_candidate_contract("copyright", copyright_assets)
    apply_candidate_contract("enforcement", enforcement)
    official = verification_index(collections.get("official_verifications", []))
    apply_verifications("patent", patents, official)
    apply_verifications("trademark", trademarks, official)
    apply_verifications("copyright", copyright_assets, official)
    apply_verifications("enforcement", enforcement, official)
    append_orphan_official_candidates(
        "patent", patents, official_entries, runs, official_providers,
    )
    append_orphan_official_candidates(
        "trademark", trademarks, official_entries, runs, official_providers,
    )
    append_orphan_official_candidates(
        "copyright", copyright_assets, official_entries, runs, official_providers,
    )
    append_orphan_official_candidates(
        "enforcement", enforcement, official_entries, runs, official_providers,
    )
    apply_verifications("patent", patents, official)
    apply_verifications("trademark", trademarks, official)
    apply_verifications("copyright", copyright_assets, official)
    apply_verifications("enforcement", enforcement, official)
    add_family_groups(patents, preserve_identifiers=task.get("schema_version") == "2.4-free")
    apply_candidate_contract("patent", patents)
    apply_candidate_contract("trademark", trademarks)
    apply_candidate_contract("copyright", copyright_assets)
    apply_candidate_contract("enforcement", enforcement)
    from workflow_v24 import scenario_workflow_enabled, scenario_supplement
    if not scenario_workflow_enabled(task):
        mark_material(task, patents, trademarks)
    else:
        # Preserve source assertions as priority signals only. Actual authority
        # comes from the country/scenario decision ledger applied below.
        for item in (*patents, *trademarks, *copyright_assets, *enforcement):
            if item.get("material") is True:
                item.setdefault("priority_signals", []).append("source_marked_material")
            item.update(material=False, material_reason="", disposition="unreviewed")
            item.pop("materiality_annotation", None)
    coalesce_candidate_ids(patents)
    coalesce_candidate_ids(trademarks)
    coalesce_candidate_ids(copyright_assets)
    coalesce_candidate_ids(enforcement)
    hydrate_tsdr_candidate_facts(task, trademarks, official_entries, runs)
    candidates_payload = {
        "patents": patents, "trademarks": trademarks,
        "copyright_assets": copyright_assets, "enforcement": enforcement,
    }
    materiality_ledger = load_materiality_ledger(
        task_dir, str(task.get("task_id") or ""),
        **({"task": task} if scenario_workflow_enabled(task) else {}),
    )
    apply_materiality_annotations(
        materiality_ledger, str(task.get("task_id") or ""), candidates_payload,
        **({"task": task, "evidence": evidence, "supplement": scenario_supplement(task_dir)} if scenario_workflow_enabled(task) else {}),
    )
    ensure_global_candidate_ids(
        ("patents", patents), ("trademarks", trademarks),
        ("copyright_assets", copyright_assets), ("enforcement", enforcement),
    )
    output = {
        "schema_version": evidence["schema_version"], "task_id": evidence["task_id"], "created_at": now_iso(),
        "patents": patents, "trademarks": trademarks,
        "copyright_assets": copyright_assets, "enforcement": enforcement,
    }
    if task.get("schema_version") == "2.4-free":
        for values in candidates_payload.values():
            for item in values:
                item.setdefault("territorial_effects", [])
                item.setdefault("right_state", "unknown")
                item.setdefault("comparison_elements", [])
                item.setdefault("unresolved_issues", [])
                item.setdefault("exclusion_basis", [])
    atomic_write_json(task_dir / "normalized-candidates.json", output)
    if task.get("schema_version") == "2.4-free":
        from workflow_v24 import append_candidate_actions
        append_candidate_actions(task_dir, task, candidates_payload)
        task.setdefault("checkpoints", {})["candidate_merge"] = {"status": "success", "at": now_iso(), **{key: len(value) for key, value in candidates_payload.items()}}
        if task.get("state") == "collecting":
            add_history(task, "ready_for_assessment", "Candidates normalized; comparison, coverage, and independent review remain separate")
        atomic_write_json(task_dir / "task.json", task)
        print(task_dir / "normalized-candidates.json")
        return
    prune_dynamic_candidate_actions(task_dir, task, evidence, candidates_payload)
    action_ids = dynamic_candidate_action_ids(task, evidence, candidates_payload)
    action_patents = [
        item if item.get("material") else {**item, "material": True}
        for item in patents if str(item.get("candidate_id") or "") in action_ids
    ]
    action_trademarks = [
        item if item.get("material") else {**item, "material": True}
        for item in trademarks if str(item.get("candidate_id") or "") in action_ids
    ]
    action_copyright_assets = [
        item if item.get("material") else {**item, "material": True}
        for item in copyright_assets if str(item.get("candidate_id") or "") in action_ids
    ]
    action_enforcement = [
        item if item.get("material") else {**item, "material": True}
        for item in enforcement if str(item.get("candidate_id") or "") in action_ids
    ]
    append_epo_candidate_detail_actions(task_dir, task, patents)
    append_us_candidate_verification_actions(
        task_dir, task, action_patents, action_trademarks,
    )
    append_eu_candidate_verification_actions(
        task_dir, task, action_patents, action_trademarks,
    )
    append_jp_candidate_verification_actions(
        task_dir, task, action_patents, action_trademarks,
    )
    append_public_web_candidate_verification_actions(
        task_dir, task, action_copyright_assets, action_enforcement,
    )
    task.setdefault("checkpoints", {})["candidate_merge"] = {
        "status": "success", "at": now_iso(),
        "patents": len(patents), "trademarks": len(trademarks),
        "copyright_assets": len(copyright_assets), "enforcement": len(enforcement),
    }
    if task.get("state") == "collecting":
        add_history(task, "ready_for_assessment", "Candidates normalized; finalizer will enforce source coverage")
    atomic_write_json(task_dir / "task.json", task)
    print(task_dir / "normalized-candidates.json")


if __name__ == "__main__":
    main()

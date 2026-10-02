"""04B candidate identity: exact records, provisional leads and sourced relations."""
from __future__ import annotations

import re
from typing import Any

from common import sha256_json, stable_id

REVISION = "candidate-identity-v1"
NUMBER_FIELDS = ("publication_number", "registration_number", "serial_number",
                 "application_number", "record_number", "case_number", "docket_number")
CLAIM_FIELDS = (*NUMBER_FIELDS, "title", "mark_text", "owner", "right_type",
                "jurisdiction", "legal_status", "family_id", "family_members",
                "publication_numbers", "territorial_effects")
SUBSTANTIVE_FIELDS = {"publication_number", "application_number", "registration_number",
    "serial_number", "record_number", "title", "mark_text", "owner", "owners",
    "applicant", "applicants", "assignee", "abstract", "claims", "description",
    "goods_services", "classes", "nice_classes", "legal_status", "right_state",
    "territorial_effects", "family_members", "publication_numbers", "views", "figures"}
TRANSPORT_FIELDS = {"url", "source", "source_record_sha256", "source_position",
    "source_collection", "source_index", "source_record_hash_stage",
    "retrieval_workflow_revision", "normalization_provenance",
    "source_position_basis", "query_id", "source_run_id", "snippet",
    "thumbnail_url", "payload_digest"}
DOCUMENT_NUMBER = re.compile(r"^[A-Z]{2}(?:[A-Z0-9-]*\d)[A-CUSY]\d?$", re.I)


def enabled(task: dict) -> bool:
    value = task.get("candidate_identity_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("CANDIDATE_IDENTITY_REVISION_INVALID")
    return True


def source_anchor(kind: str, entry: dict, ordinal: int) -> str:
    return stable_id("SRC", kind, str(entry.get("evidence_id") or ""),
                     str(entry.get("source_run_id") or ""), str(ordinal))


def normalized_number(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def identity_key(kind: str, item: dict, anchor: str) -> tuple[str, str]:
    """Only exact, typed identifiers merge automatically; all other rows survive."""
    country = str(item.get("jurisdiction") or item.get("office") or "").upper().strip()
    right = str(item.get("right_type") or "unknown").strip() or "unknown"
    if kind == "patent":
        raw = str(item.get("publication_number") or "").strip()
        number = normalized_number(raw)
        if raw and DOCUMENT_NUMBER.fullmatch(number) and country and country == number[:2]:
            return f"{country}:{right}:publication:{number}", "exact_document_number"
    elif kind == "trademark":
        for field in ("serial_number", "registration_number"):
            number = normalized_number(item.get(field))
            if country and number and any(ch.isdigit() for ch in number):
                return f"{country}:{right}:{field}:{number}", "exact_record_number"
    else:
        fields = (("record_number", "registration_number", "application_number") if kind == "copyright"
                  else ("case_number", "docket_number", "record_number", "registration_number"))
        for field in fields:
            number = normalized_number(item.get(field))
            if country and number and any(ch.isdigit() for ch in number):
                return f"{country}:{right}:{field}:{number}", "exact_record_number"
    return f"{kind}:provisional:{anchor}", "identity_pending"


def identifier_snapshot(item: dict) -> dict:
    return {field: {"raw": str(item[field]), "normalized": normalized_number(item[field])}
            for field in NUMBER_FIELDS if item.get(field) not in (None, "")}


def field_claims(item: dict, source_ref: dict) -> dict[str, list[dict]]:
    result = {}
    for field in CLAIM_FIELDS:
        value = item.get(field)
        if value in (None, "", [], {}):
            continue
        result[field] = [{"value": value, "evidence_id": source_ref.get("evidence_id"),
                          "source_run_id": source_ref.get("source_run_id"),
                          "source_anchor": source_ref.get("source_anchor"),
                          "collected_at": source_ref.get("collected_at")}]
    return result


def append_field_claims(target: dict, incoming: dict) -> None:
    claims = target.setdefault("field_claims", {})
    for field, values in incoming.items():
        bucket = claims.setdefault(field, [])
        seen = {sha256_json(row) for row in bucket}
        for value in values:
            digest = sha256_json(value)
            if digest not in seen:
                bucket.append(value)
                seen.add(digest)


def duplicate_discovery_facts(current: dict, incoming: dict, source_ref: dict) -> bool:
    """A new discovery wrapper with no new factual field is provenance only."""
    if source_ref.get("operation") == "candidate_verification":
        return False
    verification = incoming.get("official_verification")
    if isinstance(verification, dict) and verification.get("status") not in (None, "", "not_checked"):
        return False
    return all(value in (None, "", [], {}) or current.get(field) == value
               for field, value in incoming.items() if field in SUBSTANTIVE_FIELDS)


def relation_view(candidates: dict[str, list[dict]]) -> dict:
    """Relations are observations, not extra candidates or inherited rights."""
    patent_rows = candidates.get("patents", [])
    relations: list[dict] = []
    member_leads: list[dict] = []
    territorial_claims: list[dict] = []
    by_application: dict[tuple[str, str], list[dict]] = {}
    by_family: dict[str, list[dict]] = {}
    by_title: dict[str, list[dict]] = {}
    for item in patent_rows:
        cid = item.get("candidate_id")
        title = " ".join(str(item.get("title") or "").casefold().split())
        if title:
            by_title.setdefault(title, []).append(item)
        app = normalized_number(item.get("application_number"))
        if app:
            by_application.setdefault((str(item.get("jurisdiction") or "").upper(), app), []).append(item)
        family = str(item.get("family_id") or "").strip()
        if family:
            by_family.setdefault(family, []).append(item)
        effects = item.get("territorial_effects")
        if isinstance(effects, list):
            refs = [claim["evidence_id"] for claim in item.get("field_claims", {}).get("territorial_effects", [])
                    if claim.get("evidence_id")]
            for effect in effects:
                if isinstance(effect, (str, dict)) and effect:
                    territorial_claims.append({"candidate_id": cid, "claimed_territory": effect,
                        "status": "source_claim_unverified", "evidence_refs": sorted(set(refs)),
                        "transfers_status_or_risk": False})
        for field in ("family_members", "publication_numbers"):
            values = item.get(field)
            if not isinstance(values, list):
                continue
            for value in values:
                number = normalized_number(value)
                if not number or number == normalized_number(item.get("publication_number")):
                    continue
                refs = [claim["evidence_id"] for claim in item.get("field_claims", {}).get(field, [])
                        if claim.get("evidence_id")]
                if not refs:
                    refs = [ref.get("evidence_id") for ref in item.get("sources", []) if ref.get("evidence_id")]
                member_leads.append({"parent_candidate_id": cid, "publication_number": number,
                    "relation": "family_member_lead" if field == "family_members" else "publication_lead",
                    "status": "lead_only", "source_refs": sorted(set(refs)),
                    "full_record_acquired": False, "legal_status": "unknown"})
    for relation_type, groups in (("same_application", by_application), ("same_family", by_family)):
        for key, rows in groups.items():
            if len(rows) < 2:
                continue
            for position, left in enumerate(rows):
                for right in rows[position + 1:]:
                    if left["candidate_id"] == right["candidate_id"]:
                        continue
                    field = "application_number" if relation_type == "same_application" else "family_id"
                    refs = sorted({claim["evidence_id"] for row in (left, right)
                        for claim in row.get("field_claims", {}).get(field, []) if claim.get("evidence_id")})
                    relations.append({"relation": relation_type,
                        "candidate_ids": sorted([left["candidate_id"], right["candidate_id"]]),
                        "basis_value": key, "evidence_refs": refs,
                        "transfers_status_or_risk": False})
    for title, rows in by_title.items():
        for position, left in enumerate(rows):
            for right in rows[position + 1:]:
                if left["candidate_id"] == right["candidate_id"]:
                    continue
                refs = sorted({ref["evidence_id"] for row in (left, right)
                    for ref in row.get("sources", []) if ref.get("evidence_id")})
                relations.append({"relation": "suspected_duplicate",
                    "candidate_ids": sorted([left["candidate_id"], right["candidate_id"]]),
                    "basis_field": "title", "basis_value": title, "evidence_refs": refs,
                    "status": "review_required", "transfers_status_or_risk": False})
    return {"relations": sorted({sha256_json(row): row for row in relations}.values(),
                                  key=lambda row: sha256_json(row)),
            "member_leads": sorted({sha256_json(row): row for row in member_leads}.values(),
                                   key=lambda row: sha256_json(row)),
            "territorial_claims": sorted({sha256_json(row): row for row in territorial_claims}.values(),
                                         key=lambda row: sha256_json(row))}

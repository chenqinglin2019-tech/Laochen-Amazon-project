#!/usr/bin/env python3
"""Import an explicitly reviewed, retained US publication as an unreviewed lead.

This is not a retrieval adapter. Quotes are the Agent's source-reading record,
not machine proof of PDF contents, a legal-status finding, or blind recall.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from common import (assert_active_free_policy, atomic_write_json, ensure_object,
                    load_json, parse_iso, recall_integrity_enabled, sha256_file,
                    sha256_json, stable_id)
from provider_utils import evidence_lock
from workflow_v24 import product_identity_digest
from assessment_v24 import NON_PRODUCTION

SCHEMA = "IPR-CANDIDATE-LEAD/1.0"
PROVIDER = "external_document_lead"
COLLECTION = "candidate_leads"
DOCUMENT_KINDS = {"patent_document", "patent_publication", "design_document",
                  "design_drawings", "official_publication", "published_document",
                  "original_patent_document"}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonproduction(value: Any) -> bool:
    """Share project labels; inspect provenance flags, never prose keywords."""
    if isinstance(value, dict):
        return (any(str(value.get(key) or "").strip().casefold() in NON_PRODUCTION | {"non_production", "synthetic", "offline"}
                    for key in ("source_environment", "environment", "kind"))
                or any(value.get(key) is True for key in ("test_only", "fixture", "synthetic", "simulation", "mock", "non_production"))
                or any(_nonproduction(item) for item in value.values()))
    return isinstance(value, list) and any(_nonproduction(item) for item in value)


def publication_number(value: Any) -> str:
    """Require a US publication with kind code; never invent missing digits/kinds."""
    if not isinstance(value, str) or re.search(r"[^A-Za-z0-9\s,./-]", value):
        raise ValueError("CANDIDATE_LEAD_PUBLICATION_INVALID")
    number = re.sub(r"[\s,./-]", "", value).upper()
    if not re.fullmatch(r"US(?:D\d{4,9}S\d?|(?:RE|PP)?\d{4,11}[AB]\d)", number):
        raise ValueError("CANDIDATE_LEAD_PUBLICATION_INVALID")
    return number


def _quote_has_number(quote: str, number: str) -> bool:
    pattern = r"(?<![A-Za-z0-9])" + r"[\s,./-]*".join(map(re.escape, number)) + r"(?![A-Za-z0-9])"
    return re.search(pattern, quote, re.I) is not None


def _inside(root: Path, raw: Any) -> Path:
    if not _text(raw):
        raise ValueError("CANDIDATE_LEAD_DOCUMENT_PATH_INVALID")
    path = (root / raw).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("CANDIDATE_LEAD_DOCUMENT_OUTSIDE_OR_MISSING")
    return path


def _source(task: dict, evidence: dict, root: Path, registration: dict) -> dict:
    if not isinstance(registration, dict) or not _text(registration.get("evidence_id")):
        raise ValueError("CANDIDATE_LEAD_SOURCE_REGISTRATION_INVALID")
    provenance = [registration]
    if registration.get("kind") == "supplement":
        manifest = _inside(root, registration.get("manifest"))
        supplement = ensure_object(load_json(manifest), "supplement")
        # Reuse the established retained-file contract, without converting it to
        # an adapter receipt. The import is lazy to avoid an assessment cycle.
        from assessment_estimate import validate_supplement
        entries = list(validate_supplement(supplement, root).values())
        if supplement.get("task_id", task["task_id"]) != task["task_id"]:
            raise ValueError("CANDIDATE_LEAD_SOURCE_TASK_MISMATCH")
        # Container-level flags apply to its entries, not unrelated documents.
        provenance.append({key: value for key, value in supplement.items() if key != "evidence"})
    elif registration.get("kind") == "evidence":
        if registration.get("manifest"):
            raise ValueError("CANDIDATE_LEAD_SOURCE_REGISTRATION_INVALID")
        entries = [entry for name, values in evidence.get("collections", {}).items()
                   if name != COLLECTION and isinstance(values, list)
                   for entry in values if isinstance(entry, dict)]
        provenance.append({key: value for key, value in evidence.items()
                           if key not in {"collections", "source_runs"}})
    else:
        raise ValueError("CANDIDATE_LEAD_SOURCE_REGISTRATION_INVALID")
    matches = [entry for entry in entries if entry.get("evidence_id") == registration["evidence_id"]]
    if len(matches) != 1:
        raise ValueError("CANDIDATE_LEAD_REGISTERED_SOURCE_NOT_UNIQUE")
    source = matches[0]
    if source.get("kind") not in DOCUMENT_KINDS or source.get("source_document"):
        raise ValueError("CANDIDATE_LEAD_ORIGINAL_PUBLICATION_REQUIRED")
    provenance.append(source)
    if source.get("source_run_id"):
        runs = [run for run in evidence.get("source_runs", []) if isinstance(run, dict)
                and run.get("run_id") == source["source_run_id"]]
        if len(runs) != 1 or runs[0].get("status") != "success":
            raise ValueError("CANDIDATE_LEAD_SOURCE_RUN_NOT_SUCCESSFUL")
        provenance.extend(runs)
    if any(_nonproduction(item) for item in provenance):
        raise ValueError("CANDIDATE_LEAD_NONPRODUCTION_SOURCE")
    return source


def build_record(task: dict, evidence: dict, root: Path, payload: dict) -> dict:
    root = root.resolve()
    if not recall_integrity_enabled(task):
        raise ValueError("CANDIDATE_LEAD_REQUIRES_RECALL_INTEGRITY")
    if _nonproduction({key: task[key] for key in (
            "source_environment", "environment", "kind", "test_only", "fixture", "synthetic",
            "simulation", "mock", "non_production", "provenance", "capture_provenance",
            "source_provenance") if key in task}):
        raise ValueError("CANDIDATE_LEAD_NONPRODUCTION_SOURCE")
    assert_active_free_policy(task)
    if (evidence.get("task_id") != task.get("task_id")
            or evidence.get("schema_version") != task.get("schema_version")):
        raise ValueError("CANDIDATE_LEAD_EVIDENCE_TASK_MISMATCH")
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("CANDIDATE_LEAD_SCHEMA_INVALID")
    if _nonproduction(payload):
        raise ValueError("CANDIDATE_LEAD_NONPRODUCTION_SOURCE")
    number = publication_number(payload.get("publication_number"))
    right_type = "design" if number.startswith("USD") else "patent"
    if (payload.get("jurisdiction") != "US" or "US" not in task.get("target_jurisdictions", [])
            or payload.get("right_type") != right_type):
        raise ValueError("CANDIDATE_LEAD_SCOPE_OR_TYPE_MISMATCH")
    identity = product_identity_digest(task.get("product", {}), task=task)
    if payload.get("product_identity_sha256") != identity:
        raise ValueError("CANDIDATE_LEAD_PRODUCT_IDENTITY_MISMATCH")
    if not _text(payload.get("title")):
        raise ValueError("CANDIDATE_LEAD_TITLE_REQUIRED")
    registration = payload.get("source_registration")
    source = _source(task, evidence, root, registration)
    if publication_number(source.get("publication_number")) != number:
        raise ValueError("CANDIDATE_LEAD_REGISTERED_PUBLICATION_MISMATCH")
    if (source.get("jurisdiction", "US") != "US"
            or source.get("right_type", right_type) != right_type):
        raise ValueError("CANDIDATE_LEAD_REGISTERED_SCOPE_MISMATCH")
    document = payload.get("document")
    if not isinstance(document, dict):
        raise ValueError("CANDIDATE_LEAD_DOCUMENT_BINDING_REQUIRED")
    path = _inside(root, document.get("path"))
    registered_path = _inside(root, source.get("path"))
    url = document.get("source_url")
    parsed = urlparse(url) if isinstance(url, str) else None
    if (not parsed or parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username or parsed.password or url != source.get("source_url")):
        raise ValueError("CANDIDATE_LEAD_SOURCE_URL_MISMATCH")
    digest, size = document.get("sha256"), document.get("bytes")
    if (path != registered_path or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest) or type(size) is not int or size < 1
            or digest != source.get("sha256") or size != source.get("bytes")
            or sha256_file(path) != digest or path.stat().st_size != size):
        raise ValueError("CANDIDATE_LEAD_DOCUMENT_HASH_OR_BINDING_MISMATCH")
    review = payload.get("review")
    if (not isinstance(review, dict) or any(not _text(review.get(key)) for key in
            ("reviewer", "reviewed_at", "number_location", "number_quote", "reasoning"))
            or review.get("content_verification") != "agent_read_original"):
        raise ValueError("CANDIDATE_LEAD_SOURCE_REVIEW_REQUIRED")
    try:
        if parse_iso(review["reviewed_at"]).tzinfo is None:
            raise ValueError("timezone missing")
    except (ValueError, TypeError) as exc:
        raise ValueError("CANDIDATE_LEAD_REVIEW_TIMESTAMP_INVALID") from exc
    if not _quote_has_number(review["number_quote"], number):
        raise ValueError("CANDIDATE_LEAD_NUMBER_QUOTE_MISMATCH")
    relations = payload.get("publication_relations", [])
    if not isinstance(relations, list):
        raise ValueError("CANDIDATE_LEAD_RELATIONS_INVALID")
    confirmed_relations = []
    registered_relations = source.get("publication_relations", [])
    for relation in relations:
        if not isinstance(relation, dict):
            raise ValueError("CANDIDATE_LEAD_RELATIONS_INVALID")
        related = publication_number(relation.get("publication_number"))
        relation_type = relation.get("relation")
        if (related == number or right_type != "patent" or related.startswith("USD")
                or relation_type not in {"prior_publication", "same_application"}
                or not _text(relation.get("location")) or not _text(relation.get("quote"))
                or not _quote_has_number(relation["quote"], related)
                or not isinstance(registered_relations, list)
                or not any(isinstance(item, dict) and item.get("relation") == relation_type
                           and item.get("publication_number") == related for item in registered_relations)):
            raise ValueError("CANDIDATE_LEAD_RELATION_NOT_DOCUMENT_BACKED")
        confirmed_relations.append({key: relation[key] for key in
                                   ("relation", "location", "quote")} | {"publication_number": related})
    registration_binding = {"kind": registration["kind"], "evidence_id": registration["evidence_id"],
                            "entry_sha256": sha256_json(source)}
    if registration["kind"] == "supplement":
        registration_binding["manifest"] = str(_inside(root, registration["manifest"]).relative_to(root))
    record = {
        "schema": SCHEMA, "task_id": task["task_id"],
        "evidence_id": stable_id("EV-LEAD", task["task_id"], number, digest, registration["evidence_id"]),
        "provider": PROVIDER, "operation": "candidate_lead", "kind": "candidate_lead",
        "source_environment": "agent_document_review", "authority_scope": "published_document_only",
        "jurisdiction": "US", "right_type": right_type, "collected_at": review["reviewed_at"],
        "product_identity_sha256": identity, "source_registration": registration_binding,
        "document": {"path": str(path.relative_to(root)), "sha256": digest, "bytes": size, "source_url": url},
        "lead": {"publication_number": number, "title": payload["title"].strip(),
                 "review": {key: review[key] for key in ("reviewer", "reviewed_at", "number_location",
                           "number_quote", "reasoning", "content_verification")},
                 "publication_relations": confirmed_relations},
    }
    return record


def validated_candidate_lead_entries(task: dict, evidence: dict, task_dir: Path) -> list[dict]:
    """Revalidate original registrations and bytes on every merge/assessment."""
    if not recall_integrity_enabled(task):
        return []  # Frozen pre-integrity and 2.3 behavior is unchanged.
    rows = evidence.get("collections", {}).get(COLLECTION, [])
    if not isinstance(rows, list):
        raise ValueError("CANDIDATE_LEAD_COLLECTION_INVALID")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("lead"), dict):
            raise ValueError("CANDIDATE_LEAD_RECORD_INVALID")
        payload = {key: row.get(key) for key in ("schema", "jurisdiction", "right_type",
                   "product_identity_sha256", "source_registration", "document")}
        payload.update(row["lead"])
        current = build_record(task, evidence, task_dir, payload)
        if row != current or row["evidence_id"] in seen:
            raise ValueError("CANDIDATE_LEAD_RECORD_OR_REGISTRATION_CHANGED")
        seen.add(row["evidence_id"])
        lead = current["lead"]
        candidate = {
            "publication_number": lead["publication_number"], "title": lead["title"],
            "kind_code": re.search(r"[ABS]\d?$", lead["publication_number"]).group(),
            "jurisdiction": "US", "right_type": current["right_type"],
            "material": False, "material_reason": "", "disposition": "unreviewed",
            "right_state": "unknown", "role": "discovery_only", "authoritative_for_final_rating": False,
            "authority_scope": "published_document_only", "recall_origin": "known_document_lead",
            "official_verification": {"status": "not_checked", "identity_match": None},
            "publication_documents": [{**current["document"], "evidence_refs": [current["evidence_id"]],
                                       "authority_scope": "published_document_only"}],
            "publication_relations": [{**relation, "evidence_refs": [current["evidence_id"]]}
                                      for relation in lead["publication_relations"]],
            "unresolved_issues": ["Known publication lead: materiality, territorial effect and current legal status remain unverified."],
        }
        result.append({**current, "payload": {"candidates": [candidate]}})
    return result


def record_candidate_lead(task_dir: Path, payload: dict) -> tuple[dict, bool]:
    task_dir = task_dir.resolve()
    with evidence_lock(task_dir):
        task = ensure_object(load_json(task_dir / "task.json"), "task.json")
        if task.get("state") == "completed":
            raise ValueError("CANDIDATE_LEAD_COMPLETED_RUN_READ_ONLY")
        evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
        record = build_record(task, evidence, task_dir, payload)
        validated_candidate_lead_entries(task, evidence, task_dir)
        entries = evidence.setdefault("collections", {}).setdefault(COLLECTION, [])
        existing = next((entry for entry in entries if entry["evidence_id"] == record["evidence_id"]), None)
        if existing is not None:
            if existing != record:
                raise ValueError("CANDIDATE_LEAD_IDENTITY_CONFLICT")
            return deepcopy(existing), False
        entries.append(record)
        atomic_write_json(task_dir / "evidence.json", evidence)
        return record, True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    record, created = record_candidate_lead(args.task_dir, ensure_object(load_json(args.input), "candidate lead"))
    import json
    print(json.dumps({"evidence_id": record["evidence_id"], "created": created,
                      "authority_scope": "published_document_only", "material": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()

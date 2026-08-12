#!/usr/bin/env python3
"""Normalize and deduplicate patent/design and trademark candidates across sources."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import add_history, atomic_write_json, ensure_object, load_json, normalize_text, now_iso


def patent_key(item: dict[str, Any]) -> str:
    publication = str(item.get("publication_number") or "")
    number = str(publication or item.get("application_number") or item.get("grant_number") or item.get("record_number") or "")
    number = re.sub(r"[^A-Za-z0-9]", "", number).upper()
    jurisdiction = str(item.get("jurisdiction") or number[:2]).upper()
    kind = str(item.get("kind_code") or "").upper()
    family = str(item.get("family_id") or "")
    if (publication or re.match(r"^[A-Z]{2}(?:D|RE|PP)?\d", number)) and number:
        return f"{jurisdiction}:{number}"
    return f"{jurisdiction}:{number}:{kind}" if number else f"family:{family}" if family else ""


def trademark_key(item: dict[str, Any]) -> str:
    office = str(item.get("office") or item.get("jurisdiction") or "").casefold()
    number = str(item.get("application_number") or item.get("serial_number") or item.get("registration_number") or "")
    number = re.sub(r"\W", "", number).upper()
    if number:
        return f"{office}:{number}"
    mark = normalize_text(str(item.get("mark_text") or item.get("word_mark") or ""))
    figurative = str(item.get("figurative_id") or item.get("image_url") or "")
    return f"{office}:text:{mark}:figure:{figurative}" if mark or figurative else ""


def better_verification(left: Any, right: Any) -> Any:
    rank = {"verified": 3, "no_result": 2, "access_limited": 1, "not_checked": 0}
    if not isinstance(left, dict):
        return right
    if not isinstance(right, dict):
        return left
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
    key_fn = patent_key if kind == "patent" else trademark_key
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
            key = key_fn(item)
            if not key:
                continue
            source_ref = {
                "provider": entry.get("provider"), "evidence_id": entry.get("evidence_id"),
                "source_run_id": entry.get("source_run_id"), "query": entry.get("query"),
                "collected_at": entry.get("collected_at"),
                "status": runs.get(str(entry.get("source_run_id")), {}).get("status", ""),
                "raw_paths": runs.get(str(entry.get("source_run_id")), {}).get("raw_paths", []),
                "data_date": runs.get(str(entry.get("source_run_id")), {}).get("data_date", ""),
                "relevance": item.get("relevance_score", item.get("relevance", "")),
            }
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
                elif field in {"owners", "nice_classes", "views", "figures"} and isinstance(value, list):
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
            trademark_like = bool(row.get("serial_number") or row.get("registration_number") or row.get("mark_text"))
            row_kind = "trademark" if trademark_like else "patent"
            if row_kind != kind:
                continue
            prepared.append({**entry, "payload": {"candidates": [row]}})
    return prepared


def verification_index(entries: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        payload = entry.get("payload", {})
        rows = payload.get("candidates", []) if isinstance(payload, dict) and isinstance(payload.get("candidates"), list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            verification = row.get("official_verification")
            if not isinstance(verification, dict):
                continue
            trademark_like = bool(row.get("serial_number") or row.get("registration_number") or row.get("mark_text"))
            kind = "trademark" if trademark_like else "patent"
            fields = ("serial_number", "application_number", "registration_number") if kind == "trademark" else ("application_number", "publication_number", "grant_number", "record_number")
            for field in fields:
                value = re.sub(r"[^A-Za-z0-9]", "", str(row.get(field) or "")).upper()
                if value:
                    index[(kind, value)] = verification
    return index


def apply_verifications(kind: str, candidates: list[dict[str, Any]], index: dict[tuple[str, str], dict[str, Any]]) -> None:
    for item in candidates:
        fields = ("serial_number", "application_number", "registration_number") if kind == "trademark" else ("application_number", "publication_number", "grant_number", "record_number")
        for field in fields:
            value = re.sub(r"[^A-Za-z0-9]", "", str(item.get(field) or "")).upper()
            if (kind, value) in index:
                item["official_verification"] = better_verification(item.get("official_verification"), index[(kind, value)])


def add_family_groups(patents: list[dict[str, Any]]) -> None:
    families: dict[str, list[str]] = {}
    for item in patents:
        family = str(item.get("family_id") or "").strip()
        if family:
            families.setdefault(family, []).append(str(item.get("normalization_key") or ""))
    for item in patents:
        family = str(item.get("family_id") or "").strip()
        if family:
            item["family_group_key"] = f"family:{family}"
            item["family_members"] = [value for value in families.get(family, []) if value]


def mark_material(task: dict[str, Any], patents: list[dict[str, Any]], trademarks: list[dict[str, Any]]) -> None:
    brand = normalize_text(str(task.get("product", {}).get("brand") or ""))
    for item in trademarks:
        mark = normalize_text(str(item.get("mark_text") or ""))
        verified = item.get("official_verification", {}).get("status") == "verified"
        if verified or (brand and mark == brand):
            item["material"] = True
            item["material_reason"] = "officially_verified" if verified else "exact_product_brand_match"
    for item in patents:
        if item.get("official_verification", {}).get("status") == "verified":
            item["material"] = True
            item["material_reason"] = "officially_verified_candidate"


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge cross-source IPR candidates.")
    parser.add_argument("--task-dir", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    collections = evidence.get("collections", {})
    runs = {str(run.get("run_id")): run for run in evidence.get("source_runs", [])}
    official_entries = collections.get("official_verifications", [])
    patents = merge("patent", [
        *collections.get("patents", []),
        *official_entries_for_kind(
            official_entries, "patent", {"uspto_patent_browser"},
        ),
    ], runs)
    trademarks = merge("trademark", collections.get("trademarks", []), runs)
    official = verification_index(collections.get("official_verifications", []))
    apply_verifications("patent", patents, official)
    apply_verifications("trademark", trademarks, official)
    add_family_groups(patents)
    mark_material(task, patents, trademarks)
    output = {
        "schema_version": evidence["schema_version"], "task_id": evidence["task_id"], "created_at": now_iso(),
        "patents": patents, "trademarks": trademarks,
    }
    atomic_write_json(task_dir / "normalized-candidates.json", output)
    task.setdefault("checkpoints", {})["candidate_merge"] = {"status": "success", "at": now_iso(), "patents": len(patents), "trademarks": len(trademarks)}
    if task.get("state") == "collecting":
        add_history(task, "ready_for_assessment", "Candidates normalized; finalizer will enforce source coverage")
    atomic_write_json(task_dir / "task.json", task)
    print(task_dir / "normalized-candidates.json")


if __name__ == "__main__":
    main()

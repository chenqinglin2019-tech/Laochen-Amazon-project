"""Append-only reviewed identity corrections over stable source-row anchors."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from common import atomic_write_json, load_json, now_iso, sha256_json, stable_id
from candidate_identity import REVISION

FILENAME = "candidate-identity-corrections.json"
COLLECTIONS = {"patents", "trademarks", "copyright_assets", "enforcement"}
RELATIONS = {"same_application", "same_family", "territorial_applicability", "suspected_duplicate"}
SELECTABLE_FIELDS = {"title", "owner", "legal_status", "jurisdiction", "right_type",
                     "publication_number", "registration_number", "serial_number",
                     "application_number", "record_number", "family_id"}


def load_ledger(task_dir: Path, task: dict) -> dict:
    path = task_dir / FILENAME
    ledger = load_json(path) if path.is_file() else {
        "revision": REVISION, "task_id": task["task_id"], "events": []}
    if (not isinstance(ledger, dict) or ledger.get("revision") != REVISION
            or ledger.get("task_id") != task["task_id"]
            or not isinstance(ledger.get("events"), list)):
        raise ValueError("CANDIDATE_CORRECTION_LEDGER_INVALID")
    ids = [row.get("event_id") for row in ledger["events"] if isinstance(row, dict)]
    if len(ids) != len(ledger["events"]) or len(ids) != len(set(ids)):
        raise ValueError("CANDIDATE_CORRECTION_LEDGER_DUPLICATE")
    previous = ""
    for row in ledger["events"]:
        unsigned = {key: value for key, value in row.items()
                    if key != "event_id"}
        if (row.get("previous_event_id") != previous
                or row.get("event_id") != stable_id("IDCOR", task["task_id"], sha256_json(unsigned))):
            raise ValueError("CANDIDATE_CORRECTION_LEDGER_CHANGED")
        previous = row["event_id"]
    return ledger


def projection_policy(ledger: dict) -> tuple[dict[str, str], dict[str, str], set[str]]:
    assignments: dict[str, str] = {}
    redirects: dict[str, str] = {}
    retired: set[str] = set()
    for event in ledger["events"]:
        kind = event.get("kind")
        if kind == "merge":
            key = f"reviewed-merge:{event['event_id']}"
            for anchor in event["source_anchors"]:
                assignments[anchor] = key
            for old in event["before_keys"]:
                redirects[old] = key
                retired.discard(old)
        elif kind == "split":
            for position, anchors in enumerate(event["partitions"], 1):
                for anchor in anchors:
                    assignments[anchor] = f"reviewed-split:{event['event_id']}:{position}"
            invalidated = set(event["before_keys"])
            while True:
                parents = {old for old, target in redirects.items() if target in invalidated}
                if parents <= invalidated:
                    break
                invalidated.update(parents)
            retired.update(invalidated)
            for old in invalidated:
                redirects.pop(old, None)
    return assignments, redirects, retired


def _candidate_index(payload: dict) -> dict[str, tuple[str, dict]]:
    return {row["candidate_id"]: (collection, row)
            for collection in COLLECTIONS for row in payload.get(collection, [])
            if isinstance(row, dict) and row.get("candidate_id")}


def _source_refs(rows: list[dict]) -> list[dict]:
    return [ref for row in rows for ref in row.get("sources", [])
            if isinstance(ref, dict) and ref.get("source_anchor")]


def record_correction(task_dir: Path, request: dict) -> dict:
    from provider_utils import evidence_lock
    task_dir = task_dir.resolve()
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        if task.get("candidate_identity_revision") != REVISION:
            raise ValueError("CANDIDATE_IDENTITY_NOT_ENABLED")
        if task.get("state") == "completed":
            raise ValueError("CANDIDATE_CORRECTION_COMPLETED_READ_ONLY")
        ledger = load_ledger(task_dir, task)
        if (isinstance(request, dict) and request.get("kind") in
                {"merge", "split", "field_selection", "relation"}
                and all(isinstance(request.get(field), str) and request[field].strip()
                        for field in ("reviewer", "reason", "quote"))
                and isinstance(request.get("candidate_ids"), list)
                and isinstance(request.get("evidence_refs"), list)):
            comparable = {key: request.get(key) for key in ("kind", "candidate_ids",
                "reviewer", "reason", "quote", "field", "selected_value", "relation", "partitions")}
            comparable["evidence_refs"] = sorted(set(request.get("evidence_refs", []))) if isinstance(request.get("evidence_refs"), list) else None
            for prior in ledger["events"]:
                if all(prior.get(key) == value for key, value in comparable.items()):
                    return prior
        current = load_json(task_dir / "normalized-candidates.json")
        head = ledger["events"][-1]["event_id"] if ledger["events"] else ""
        if current.get("identity_correction_head", "") != head:
            raise ValueError("CANDIDATE_CORRECTION_MERGE_REFRESH_REQUIRED")
        if not isinstance(request, dict) or request.get("kind") not in {
                "merge", "split", "field_selection", "relation"}:
            raise ValueError("CANDIDATE_CORRECTION_KIND_INVALID")
        kind = request["kind"]
        if not all(isinstance(request.get(field), str) and request[field].strip()
                   for field in ("reviewer", "reason", "quote")):
            raise ValueError("CANDIDATE_CORRECTION_REVIEW_REQUIRED")
        index = _candidate_index(current)
        ids = request.get("candidate_ids")
        if not isinstance(ids, list) or any(not isinstance(cid, str) or cid not in index for cid in ids):
            raise ValueError("CANDIDATE_CORRECTION_CANDIDATES_INVALID")
        if len(ids) != len(set(ids)):
            raise ValueError("CANDIDATE_CORRECTION_CANDIDATES_DUPLICATE")
        refs = request.get("evidence_refs")
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or not ref for ref in refs):
            raise ValueError("CANDIDATE_CORRECTION_EVIDENCE_REQUIRED")
        evidence = load_json(task_dir / "evidence.json")
        known_evidence = {entry.get("evidence_id") for values in evidence.get("collections", {}).values()
                          if isinstance(values, list) for entry in values if isinstance(entry, dict)}
        if not set(refs) <= known_evidence:
            raise ValueError("CANDIDATE_CORRECTION_EVIDENCE_UNKNOWN")
        rows = [index[cid][1] for cid in ids]
        if any(not set(refs) & {ref.get("evidence_id") for ref in _source_refs([row])}
               for row in rows):
            raise ValueError("CANDIDATE_CORRECTION_EVIDENCE_UNRELATED")
        event: dict[str, Any] = {"kind": kind, "candidate_ids": ids,
            "evidence_refs": sorted(set(refs)), "reviewer": request["reviewer"].strip(),
            "reason": request["reason"].strip(), "quote": request["quote"].strip()}
        if kind in {"merge", "split"}:
            if kind == "merge" and (len(ids) < 2 or len({index[cid][0] for cid in ids}) != 1):
                raise ValueError("CANDIDATE_CORRECTION_MERGE_SCOPE_INVALID")
            if kind == "split" and len(ids) != 1:
                raise ValueError("CANDIDATE_CORRECTION_SPLIT_SCOPE_INVALID")
            anchors = {ref["source_anchor"] for ref in _source_refs(rows)}
            if kind == "merge":
                event["source_anchors"] = sorted(anchors)
            else:
                partitions = request.get("partitions")
                if (not isinstance(partitions, list) or len(partitions) < 2
                        or any(not isinstance(group, list) or not group for group in partitions)):
                    raise ValueError("CANDIDATE_CORRECTION_PARTITIONS_INVALID")
                flattened = [anchor for group in partitions for anchor in group]
                if set(flattened) != anchors or len(flattened) != len(set(flattened)):
                    raise ValueError("CANDIDATE_CORRECTION_PARTITIONS_NOT_EXACT")
                event["partitions"] = [sorted(group) for group in partitions]
            event["collection"] = index[ids[0]][0]
            event["before_keys"] = sorted({row["normalization_key"] for row in rows})
        elif kind == "field_selection":
            field = request.get("field")
            if len(ids) != 1 or field not in SELECTABLE_FIELDS:
                raise ValueError("CANDIDATE_CORRECTION_FIELD_INVALID")
            selected = request.get("selected_value")
            claims = rows[0].get("field_claims", {}).get(field, [])
            supported = [claim for claim in claims if claim.get("value") == selected
                         and claim.get("evidence_id") in refs and claim.get("source_anchor")]
            if not supported:
                raise ValueError("CANDIDATE_CORRECTION_SELECTED_CLAIM_UNSUPPORTED")
            event.update(field=field, selected_value=selected,
                         selected_source_anchors=sorted({claim["source_anchor"] for claim in supported}))
        else:
            if (len(ids) != 2 or request.get("relation") not in RELATIONS):
                raise ValueError("CANDIDATE_CORRECTION_RELATION_INVALID")
            event["relation"] = request["relation"]
        event["previous_event_id"] = head
        event["recorded_at"] = now_iso()
        event["event_id"] = stable_id("IDCOR", task["task_id"], sha256_json(event))
        ledger["events"].append(event)
        atomic_write_json(task_dir / FILENAME, ledger)
        return event


def apply_reviewed_fields(candidates: dict, ledger: dict) -> None:
    index = _candidate_index(candidates)
    for event in ledger["events"]:
        if event["kind"] != "field_selection":
            continue
        field = event["field"]
        anchors = set(event.get("selected_source_anchors", []))
        rows = [row for _, row in index.values()
                if anchors & {ref.get("source_anchor") for ref in row.get("sources", [])}]
        if not rows:
            raise ValueError("CANDIDATE_CORRECTION_FIELD_CLAIM_CHANGED")
        for candidate in rows:
            if not any(claim.get("value") == event["selected_value"]
                       and claim.get("evidence_id") in event["evidence_refs"]
                       and claim.get("source_anchor") in anchors
                       for claim in candidate.get("field_claims", {}).get(field, [])):
                raise ValueError("CANDIDATE_CORRECTION_FIELD_CLAIM_CHANGED")
            candidate[field] = event["selected_value"]
            candidate.setdefault("field_resolutions", {})[field] = {
                "event_id": event["event_id"], "evidence_refs": event["evidence_refs"],
                "reviewer": event["reviewer"], "reason": event["reason"],
                "selected_value": event["selected_value"]}


def correction_view(candidates: dict, ledger: dict) -> dict:
    active = _candidate_index(candidates)
    aliases = []
    relations = []
    for event in ledger["events"]:
        if event["kind"] in {"merge", "split"}:
            anchors = set(event.get("source_anchors", [])) | {
                anchor for group in event.get("partitions", []) for anchor in group}
            current_ids = sorted({cid for cid, (_, row) in active.items()
                if anchors & {ref.get("source_anchor") for ref in row.get("sources", [])}})
            aliases.append({"event_id": event["event_id"], "kind": event["kind"],
                "old_candidate_ids": event["candidate_ids"], "current_candidate_ids": current_ids,
                "evidence_refs": event["evidence_refs"]})
        elif event["kind"] == "relation":
            relations.append({"relation": event["relation"], "candidate_ids": event["candidate_ids"],
                "evidence_refs": event["evidence_refs"], "quote": event["quote"],
                "event_id": event["event_id"], "transfers_status_or_risk": False})
    return {"aliases": aliases, "relations": relations,
            "head": ledger["events"][-1]["event_id"] if ledger["events"] else ""}

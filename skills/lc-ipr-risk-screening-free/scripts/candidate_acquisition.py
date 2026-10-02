"""04C immutable browser-acquisition counts and live candidate projection."""
from __future__ import annotations

from typing import Any

from common import sha256_json
from candidate_identity import DOCUMENT_NUMBER, normalized_number

REVISION = "candidate-acquisition-v1"
COLLECTIONS = {"patent": "patents", "trademark": "trademarks",
               "copyright": "copyright_assets", "enforcement": "enforcement"}


def enabled(task: dict) -> bool:
    value = task.get("candidate_acquisition_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("CANDIDATE_ACQUISITION_REVISION_INVALID")
    return True


def _cards(normalized: Any) -> list[dict]:
    value = normalized.get("candidates", []) if isinstance(normalized, dict) else normalized
    return [card for card in value if isinstance(card, dict)] if isinstance(value, list) else []


def _identity(evidence_type: str, card: dict, country: str, run_id: str, ordinal: int) -> tuple[str, str]:
    office = str(card.get("jurisdiction") or card.get("office") or country or "").upper().strip()
    if evidence_type == "patent":
        number = normalized_number(card.get("publication_number"))
        if office and number.startswith(office) and DOCUMENT_NUMBER.fullmatch(number):
            return f"patent:document:{office}:{number}", "exact_document"
    else:
        fields = (("serial_number", "registration_number") if evidence_type == "trademark"
                  else ("record_number", "registration_number", "application_number") if evidence_type == "copyright"
                  else ("case_number", "docket_number", "record_number", "registration_number"))
        for field in fields:
            number = normalized_number(card.get(field))
            if office and number and any(char.isdigit() for char in number):
                return f"{evidence_type}:{office}:{field}:{number}", "exact_record"
    # Different incomplete source rows remain different acquisitions. Neither
    # title nor provider URL supplies a stable right identity.
    return f"pending:{run_id}:{ordinal}", "identity_pending"


def parsed_identity(run: dict, card: dict, position: int) -> tuple[str, str]:
    if type(position) is not int or position < 1:
        raise ValueError("CANDIDATE_ACQUISITION_POSITION_INVALID")
    return _identity(run.get("evidence_type", ""), card,
                     str(run.get("jurisdiction") or ""), str(run["run_id"]), position)


def execution_state(evidence: dict, run: dict, receipt: dict) -> tuple[set[str], list[int]]:
    """Original receipt plus append-only local parsing; never rewrite the run."""
    keys = {row["identity_key"] for row in receipt["rows"]}
    resolved = set()
    for event in evidence.get("result_parses", []):
        if not isinstance(event, dict) or event.get("source_run_id") != run.get("run_id"):
            continue
        if event.get("payload_digest") != run.get("payload_digest"):
            raise ValueError("CANDIDATE_ACQUISITION_PARSE_SOURCE_CHANGED")
        key = event.get("candidate_acquisition_identity_key")
        if type(event.get("position")) is not int or not isinstance(key, str) or not key:
            raise ValueError("CANDIDATE_ACQUISITION_PARSE_IDENTITY_MISSING")
        keys.add(key)
        resolved.add(event["position"])
    for event in evidence.get("result_dispositions", []):
        if (isinstance(event, dict) and event.get("source_run_id") == run.get("run_id")
                and event.get("outcome") == "non_candidate"
                and event.get("payload_digest") == run.get("payload_digest")
                and type(event.get("position")) is int):
            resolved.add(event["position"])
    return keys, sorted(position for position in receipt["unknown_positions"]
                        if position not in resolved)


def verified_receipt(run: dict) -> dict | None:
    receipt = run.get("candidate_acquisition")
    if receipt is None:
        return None
    if (not isinstance(receipt, dict) or receipt.get("revision") != REVISION
            or receipt.get("run_id") != run.get("run_id")
            or receipt.get("query_id") != run.get("query_id")
            or receipt.get("plan_entry_sha256") != run.get("plan_entry_sha256")
            or receipt.get("payload_digest") != run.get("payload_digest")):
        raise ValueError("CANDIDATE_ACQUISITION_RECEIPT_INVALID")
    unsigned = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != sha256_json(unsigned):
        raise ValueError("CANDIDATE_ACQUISITION_RECEIPT_CHANGED")
    rows = receipt.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, dict)
            or not isinstance(row.get("identity_key"), str)
            or type(row.get("position")) is not int for row in rows):
        raise ValueError("CANDIDATE_ACQUISITION_ROWS_INVALID")
    return receipt


def make_receipt(task: dict, evidence: dict, run: dict, plan_row: dict,
                 normalized: Any) -> dict | None:
    if not enabled(task) or not plan_row or plan_row.get("action_purpose") != "discovery" \
            or plan_row.get("discovery_role") not in {"browser_fallback", "refinement", "pagination"} \
            or not str(run.get("provider") or "").endswith("browser"):
        return None
    run_id = run["run_id"]
    cards = _cards(normalized)
    rows = []
    explicit_positions = set()
    for ordinal, card in enumerate(cards, 1):
        explicit = card.get("source_position") or card.get("result_position")
        position = explicit or ordinal
        if type(position) is not int or position < 1:
            position = ordinal
        elif type(explicit) is int:
            explicit_positions.add(position)
        key, basis = _identity(run.get("evidence_type", ""), card,
                               str(run.get("jurisdiction") or ""), run_id, ordinal)
        rows.append({"position": position, "identity_key": key, "basis": basis,
                     "source_record_sha256": card.get("source_record_sha256") or ""})
    scope = (plan_row.get("discovery_intent_id"), plan_row.get("refinement_round"))
    if not isinstance(scope[0], str) or not scope[0] or type(scope[1]) is not int or scope[1] < 0:
        raise ValueError("CANDIDATE_ACQUISITION_SCOPE_INVALID")
    previous_keys = set()
    for prior in evidence.get("source_runs", []):
        if not isinstance(prior, dict):
            continue
        receipt = verified_receipt(prior)
        if receipt and (receipt.get("purpose_id"), receipt.get("version")) == scope:
            keys, _ = execution_state(evidence, prior, receipt)
            previous_keys.update(keys)
    keys = {row["identity_key"] for row in rows}
    index = run.get("result_processing") or {}
    all_positions = {row.get("position") for row in index.get("rows", []) if isinstance(row, dict)}
    parsed_positions = ({row["position"] for row in rows}
                        if len(cards) == len(all_positions) else explicit_positions)
    receipt = {"revision": REVISION, "run_id": run_id,
               "query_id": run.get("query_id"), "plan_entry_sha256": run.get("plan_entry_sha256"),
               "payload_digest": run.get("payload_digest"),
               "purpose_id": scope[0], "version": scope[1], "rows": rows,
               "unknown_positions": sorted(position for position in all_positions - parsed_positions
                                           if type(position) is int),
               "new_unique_count": len(keys - previous_keys),
               "cumulative_unique_count": len(previous_keys | keys)}
    receipt["receipt_sha256"] = sha256_json(receipt)
    return receipt


def current_candidate_stats(candidates: dict, run_ids: set[str]) -> dict:
    rows = []
    for collection in COLLECTIONS.values():
        for candidate in candidates.get(collection, []):
            if not isinstance(candidate, dict) or not candidate.get("candidate_id"):
                continue
            if any(isinstance(ref, dict) and ref.get("source_run_id") in run_ids
                   for ref in candidate.get("sources", [])):
                rows.append(candidate["candidate_id"])
    ids = sorted(set(rows))
    return {"current_candidate_count": len(ids), "current_candidate_ids": ids,
            "basis": "current_normalized_candidates"}


def current_views(evidence: dict, candidates: dict) -> list[dict]:
    """Persist a current projection without changing any acquisition receipt."""
    grouped: dict[tuple[str, int], dict] = {}
    for run in evidence.get("source_runs", []):
        if not isinstance(run, dict):
            continue
        receipt = verified_receipt(run)
        if receipt is None:
            continue
        scope = (receipt["purpose_id"], receipt["version"])
        group = grouped.setdefault(scope, {"purpose_id": scope[0], "version": scope[1],
            "source_run_ids": set(), "identity_keys": set(), "unparsed_result_positions": []})
        group["source_run_ids"].add(run["run_id"])
        keys, unresolved = execution_state(evidence, run, receipt)
        group["identity_keys"].update(keys)
        group["unparsed_result_positions"].extend({"source_run_id": run["run_id"], "position": position}
            for position in unresolved)
    views = []
    for scope in sorted(grouped):
        group = grouped[scope]
        views.append({"purpose_id": scope[0], "version": scope[1],
            "source_run_ids": sorted(group["source_run_ids"]),
            "execution_consumed_count": len(group["identity_keys"]),
            "unparsed_result_positions": group["unparsed_result_positions"],
            **current_candidate_stats(candidates, group["source_run_ids"])})
    return views

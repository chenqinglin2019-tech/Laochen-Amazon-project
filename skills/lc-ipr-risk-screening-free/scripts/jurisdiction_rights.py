"""The shipped table of rights that do or do not exist in a target country (institution statements).

A reviewer may only declare a scope "not applicable" by citing an actual institution source. Nothing in a task's
own evidence ever says that a country has no utility model system, so without this table such scopes stayed
pending for ever. The table ships with the skill (``references/jurisdiction-rights.json``), every entry names an
official page, and task creation copies the entries that concern the task's countries into
``evidence.collections.institution_references`` as program-written evidence (no file, no network, no run).
"""
from __future__ import annotations

from pathlib import Path

from common import load_json, sha256_file

REVISION = "jurisdiction-rights-v1"
KIND = "institution_reference"
PROVIDER = "institution_reference"
OPERATION = "jurisdiction_rights_table"
TABLE = Path(__file__).resolve().parents[1] / "references" / "jurisdiction-rights.json"
REQUIRED = ("jurisdiction", "right_type", "applicable", "statement_zh", "statement_en", "source_title", "source_url",
            "retrieved")


def load_table(path: Path = TABLE) -> dict:
    table = load_json(path)
    if not isinstance(table, dict) or table.get("revision") != REVISION or not isinstance(table.get("entries"), list):
        raise ValueError("JURISDICTION_RIGHTS_TABLE_INVALID")
    seen = set()
    for entry in table["entries"]:
        if (not isinstance(entry, dict) or any(key not in entry for key in REQUIRED)
                or type(entry["applicable"]) is not bool
                or not str(entry["source_url"]).startswith("https://")
                or any(not str(entry[key]).strip() for key in ("statement_zh", "statement_en", "source_title"))):
            raise ValueError("JURISDICTION_RIGHTS_ENTRY_INVALID")
        key = (entry["jurisdiction"], entry["right_type"])
        if key in seen:
            raise ValueError("JURISDICTION_RIGHTS_ENTRY_DUPLICATE")
        seen.add(key)
    return table


def evidence_id(jurisdiction: str, right_type: str) -> str:
    return "EV-INST-%s-%s" % (str(jurisdiction).upper(), str(right_type).upper())


def institution_entries(jurisdictions, created_at: str, path: Path = TABLE) -> list[dict]:
    """Program evidence entries for every table row that concerns one of the task's countries.

    Deliberately without ``path``/``sha256``/``source_url`` at the top level: the entry is a statement, not a
    retained original, so the review host neither attaches it as a file nor lists it as unsent material; the
    evidence index still registers it, so reviewers can cite it and the finalizer can bind to it.
    """
    table = load_table(path)
    digest = sha256_file(path)
    wanted = {str(value).upper() for value in jurisdictions}
    rows = []
    for entry in table["entries"]:
        if str(entry["jurisdiction"]).upper() not in wanted:
            continue
        rows.append({"evidence_id": evidence_id(entry["jurisdiction"], entry["right_type"]),
            "provider": PROVIDER, "operation": OPERATION, "kind": KIND,
            "jurisdiction": str(entry["jurisdiction"]).upper(), "right_type": entry["right_type"],
            "collected_at": created_at, "source_environment": "skill_reference",
            "authority_scope": "institution_statement_only", "reference_revision": REVISION,
            "reference_sha256": digest, "payload": {key: entry[key] for key in REQUIRED if key in entry}
            | {key: entry[key] for key in ("verification", "note") if key in entry}})
    return sorted(rows, key=lambda row: row["evidence_id"])


def not_applicable_scopes(entries) -> set:
    """(jurisdiction, right_type) pairs the entries declare as absent institutions."""
    return {(row.get("jurisdiction"), row.get("right_type")) for row in entries
            if isinstance(row, dict) and isinstance(row.get("payload"), dict) and row["payload"].get("applicable") is False}

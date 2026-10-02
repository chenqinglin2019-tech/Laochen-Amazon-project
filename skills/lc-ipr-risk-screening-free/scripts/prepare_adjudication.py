#!/usr/bin/env python3
"""Prepare the chief adjudication: a bound skeleton plus a worksheet of the units that need a decision.

Reads both final reviews, checks they match the live input digest, applies the task's own
conflict rule (``assessment_estimate._row_conflicts``) and writes

* ``adjudication.json`` -- live digest, ``review_refs`` (hash of each whole review) and one draft
  decision per unit that needs the chief (a copy of the first review's row). ``reviewer``,
  ``review_context.session_id`` and every ``adjudication_reasoning`` are left empty on purpose:
  the publication gate rejects the file until the chief has actually decided and filled them.
* ``adjudication-worksheet.json`` -- for each such unit the conflicting fields with both reviewers'
  values side by side, so the chief does not have to diff two full reviews.

No validator is changed and nothing is decided here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path

from common import atomic_write_json, ensure_object, load_json, sha256_json

UNIT_KEYS = ("scenario_id", "jurisdiction", "right_type", "candidate_id", "assessment_object")
SHOWN_FIELDS = ("risk", "right_state", "exclusion_basis", "evidence_confidence", "module_id", "out_of_scope",
                "future_signal", "signal_only", "scope_exclusion_basis")


def _claims(row):
    return sorted({(str(claim.get("claim_id")), str(claim.get("claim_type")), str(claim.get("conclusion")))
                   for claim in row.get("comparison", {}).get("claims", []) if isinstance(claim, dict)})


def _summary(row):
    shown = {key: row.get(key) for key in SHOWN_FIELDS if key in row}
    if row.get("comparison", {}).get("claims"):
        shown["claims"] = [list(item) for item in _claims(row)]
    exception = row.get("applicability_exception")
    if exception:
        shown["applicability_exception"] = {"kind": exception.get("kind"), "reasoning": exception.get("reasoning")}
    for key in ("reasoning", "pending_reasoning"):
        if isinstance(row.get(key), str) and row[key].strip():
            shown[key] = row[key] if len(row[key]) <= 800 else row[key][:800] + "…"
    return shown


def build(task_dir: Path, first_path: Path, second_path: Path, *, reviewer: str = "", session_id: str = ""):
    from assessment_estimate import _review_scope_key, _row_conflicts, validate_product_scope_coverage
    from review_readiness import current_digest
    task_dir = Path(task_dir).resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    digest = current_digest(task_dir)
    reviews = {}
    for label, path in (("first", first_path), ("second", second_path)):
        review = ensure_object(load_json(Path(path)), label + " review")
        context = review.get("review_context")
        if not isinstance(context, dict) or context.get("evidence_digest") != digest:
            raise ValueError("PREPARE_ADJUDICATION_REVIEW_STALE: " + label + " (re-run the final review for the current inputs)")
        validate_product_scope_coverage(review.get("assessments", []), task,
            error_code="PREPARE_ADJUDICATION_PRODUCT_SCOPE_MISSING:" + label)
        reviews[label] = review
    left = {_review_scope_key(row, task): row for row in reviews["first"]["assessments"]}
    right = {_review_scope_key(row, task): row for row in reviews["second"]["assessments"]}
    refs = {"first": sha256_json(reviews["first"]), "second": sha256_json(reviews["second"])}
    decisions, worksheet, counts = [], [], {}
    for key in sorted(set(left) | set(right), key=str):
        conflicts = (_row_conflicts(left[key], right[key], task) if key in left and key in right
                     else ["review_scope_missing"])
        chosen = left.get(key) or right[key]
        # A chosen row carrying an applicability exception always needs the chief, even without a conflict.
        needs = bool(conflicts) or bool(chosen.get("applicability_exception"))
        if not needs:
            continue
        for name in conflicts:
            counts[name] = counts.get(name, 0) + 1
        draft = deepcopy(chosen)
        draft["adjudication_reasoning"] = ""
        draft["review_refs"] = dict(refs)
        decisions.append(draft)
        worksheet.append({"unit": {name: chosen.get(name) for name in UNIT_KEYS if name in chosen},
            "conflicts": conflicts or ["applicability_exception_requires_chief"],
            "first": _summary(left[key]) if key in left else None,
            "second": _summary(right[key]) if key in right else None})
    adjudication = {"reviewer": reviewer, "review_context": {"session_id": session_id, "evidence_digest": digest},
                    "review_refs": refs, "decisions": decisions}
    return adjudication, {"schema": "IPR-ADJUDICATION-WORKSHEET/1.0", "evidence_digest": digest,
                          "units_total": len(set(left) | set(right)), "units_requiring_decision": len(decisions),
                          "conflict_field_counts": dict(sorted(counts.items())), "units": worksheet}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--first-review", type=Path)
    parser.add_argument("--second-review", type=Path)
    parser.add_argument("--output", type=Path, help="Skeleton path; default TASK/adjudication.json (never overwritten)")
    parser.add_argument("--worksheet", type=Path, help="Worksheet path; default TASK/adjudication-worksheet.json")
    parser.add_argument("--reviewer", default="", help="Chief reviewer name; left empty when omitted")
    parser.add_argument("--session-id", default=os.environ.get("CODEX_THREAD_ID", ""),
                        help="Chief session id; default $CODEX_THREAD_ID, empty when unset")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    first = args.first_review or task_dir / "first-review.json"
    second = args.second_review or task_dir / "second-review.json"
    output = args.output or task_dir / "adjudication.json"
    sheet = args.worksheet or task_dir / "adjudication-worksheet.json"
    if output.exists() or sheet.exists():
        parser.error("refusing to overwrite an existing adjudication or worksheet; choose new paths")
    adjudication, worksheet = build(task_dir, first, second, reviewer=args.reviewer, session_id=args.session_id)
    atomic_write_json(output, adjudication)
    atomic_write_json(sheet, worksheet)
    print(json.dumps({"adjudication": str(output), "worksheet": str(sheet),
                      "units_total": worksheet["units_total"],
                      "units_requiring_decision": worksheet["units_requiring_decision"],
                      "conflict_field_counts": worksheet["conflict_field_counts"],
                      "still_required": ["reviewer", "review_context.session_id"]
                      + (["adjudication_reasoning for every decision", "final risk/evidence in each decision row"]
                         if adjudication["decisions"] else [])}, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Append and validate reviewer materiality decisions for normalized candidates."""

from __future__ import annotations

import argparse
import copy
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from common import (
    add_history, assert_active_free_policy, atomic_write_json, ensure_object,
    is_active_schema, load_json, now_iso, stable_id,
)
from provider_utils import evidence_lock
import decision_workflow as workflow
from runtime_timing import timed_cli


LEDGER_FILENAME = "materiality-annotations.json"
LEDGER_SCHEMA_VERSION = "1.0"
DECISIONS = {True: "material", False: "excluded"}
CANDIDATE_COLLECTIONS = (
    "patents", "trademarks", "copyright_assets", "enforcement",
)


def empty_materiality_ledger(task_id: str, *, task: dict | None = None) -> dict[str, Any]:
    return {
        "schema_version": workflow.LEDGER_SCHEMA_VERSION if workflow.decision_workflow_enabled(task or {}) else LEDGER_SCHEMA_VERSION,
        "task_id": task_id,
        "annotations": [],
    }


def load_materiality_ledger(task_dir: Path, task_id: str, *, task: dict | None = None) -> dict[str, Any]:
    path = task_dir / LEDGER_FILENAME
    if not path.is_file():
        return empty_materiality_ledger(task_id, task=task)
    return ensure_object(load_json(path), LEDGER_FILENAME)


def iter_candidates(candidates: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for collection in CANDIDATE_COLLECTIONS:
        rows = candidates.get(collection, [])
        if not isinstance(rows, list):
            continue
        for item in rows:
            if isinstance(item, dict):
                yield collection, item


def candidate_identity_fingerprint(collection: str, item: dict[str, Any]) -> str:
    """Hash stable normalized identity, excluding fields that detail calls enrich."""
    return workflow.candidate_identity_fingerprint(collection, item)


def candidate_index(
    candidates: dict[str, Any],
) -> tuple[dict[str, tuple[str, dict[str, Any]]], list[str]]:
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    errors: list[str] = []
    for collection, item in iter_candidates(candidates):
        candidate_id = str(item.get("candidate_id") or "").strip()
        if not candidate_id:
            errors.append(f"{collection} contains a candidate without candidate_id")
            continue
        if candidate_id in index:
            errors.append(f"duplicate candidate_id across normalized candidates: {candidate_id}")
            continue
        index[candidate_id] = (collection, item)
    return index, errors


def _valid_timestamp(value: object) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def materiality_annotation_complete(item: dict[str, Any]) -> bool:
    annotation = item.get("materiality_annotation")
    if not isinstance(annotation, dict):
        return False
    material = item.get("material")
    expected = DECISIONS.get(material) if isinstance(material, bool) else None
    return bool(
        expected
        and item.get("disposition") == expected
        and str(item.get("material_reason") or "").strip()
        and annotation.get("decision") == expected
        and annotation.get("material") is material
        and str(annotation.get("annotation_id") or "").strip()
        and str(annotation.get("reviewer") or "").strip()
        and str(annotation.get("candidate_identity_fingerprint") or "").strip()
        and _valid_timestamp(annotation.get("annotated_at"))
    )


def materiality_ledger_errors(
    ledger: dict[str, Any], task_id: str, candidates: dict[str, Any], *,
    require_applied: bool = True, task: dict | None = None,
    evidence: dict | None = None, supplement: dict | None = None,
) -> list[str]:
    if workflow.decision_workflow_enabled(task or {}) or ledger.get("schema_version") == workflow.LEDGER_SCHEMA_VERSION:
        if not task or task.get("task_id") != task_id:
            return ["TRIAGE_TASK_CONTEXT_REQUIRED"]
        return workflow.triage_ledger_errors(task, ledger, candidates, evidence=evidence, supplement=supplement)
    errors: list[str] = []
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        errors.append("materiality ledger schema_version must be 1.0")
    if ledger.get("task_id") != task_id:
        errors.append("materiality ledger task_id does not match task")
    annotations = ledger.get("annotations")
    if not isinstance(annotations, list):
        return [*errors, "materiality ledger annotations must be an array"]

    index, candidate_errors = candidate_index(candidates)
    errors.extend(candidate_errors)
    annotation_ids: set[str] = set()
    audit_keys: set[tuple[str, str, str, str, str, str]] = set()
    latest: dict[str, dict[str, Any]] = {}
    last_time: datetime | None = None
    for position, annotation in enumerate(annotations):
        prefix = f"materiality annotation {position + 1}"
        if not isinstance(annotation, dict):
            errors.append(f"{prefix} must be an object")
            continue
        annotation_id = str(annotation.get("annotation_id") or "").strip()
        candidate_id = str(annotation.get("candidate_id") or "").strip()
        fingerprint = str(annotation.get("candidate_identity_fingerprint") or "").strip()
        reason = str(annotation.get("material_reason") or "").strip()
        reviewer = str(annotation.get("reviewer") or "").strip()
        annotated_at = str(annotation.get("annotated_at") or "").strip()
        material = annotation.get("material")
        decision = str(annotation.get("decision") or "").strip()
        expected_decision = DECISIONS.get(material) if isinstance(material, bool) else None
        if not annotation_id:
            errors.append(f"{prefix} has no annotation_id")
        elif annotation_id in annotation_ids:
            errors.append(f"duplicate materiality annotation_id: {annotation_id}")
        annotation_ids.add(annotation_id)
        if not candidate_id:
            errors.append(f"{prefix} has no candidate_id")
        if expected_decision is None or decision != expected_decision:
            errors.append(f"{prefix} decision/material must explicitly be material or excluded")
        if not reason:
            errors.append(f"{prefix} has no material_reason")
        if not reviewer:
            errors.append(f"{prefix} has no reviewer")
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            errors.append(f"{prefix} has an invalid candidate identity fingerprint")
        if not _valid_timestamp(annotated_at):
            errors.append(f"{prefix} has an invalid annotated_at timestamp")
        else:
            parsed = datetime.fromisoformat(annotated_at.replace("Z", "+00:00"))
            if last_time is not None and parsed < last_time:
                errors.append("materiality annotations must remain in chronological append order")
            last_time = parsed
        audit_key = (candidate_id, fingerprint, annotated_at, decision, reason, reviewer)
        if audit_key in audit_keys:
            errors.append(f"duplicate materiality annotation audit record: {candidate_id}")
        audit_keys.add(audit_key)
        bound = index.get(candidate_id)
        if bound is None:
            errors.append(f"materiality annotation references an unknown candidate: {candidate_id}")
        elif fingerprint != candidate_identity_fingerprint(*bound):
            errors.append(f"materiality annotation candidate fingerprint mismatch: {candidate_id}")
        latest[candidate_id] = annotation

    if not require_applied:
        return errors
    for candidate_id, (collection, item) in index.items():
        annotation = latest.get(candidate_id)
        applied = item.get("materiality_annotation")
        if annotation is None:
            errors.append(f"candidate has no materiality ledger decision: {candidate_id}")
            if applied:
                errors.append(f"candidate has an annotation not present in the ledger: {candidate_id}")
            if str(item.get("disposition") or "unreviewed") != "unreviewed":
                errors.append(f"candidate disposition has no reviewer ledger decision: {candidate_id}")
            continue
        expected = {
            key: annotation.get(key)
            for key in (
                "annotation_id", "candidate_id", "candidate_identity_fingerprint",
                "material", "decision", "material_reason", "reviewer", "annotated_at",
            )
        }
        if applied != expected:
            errors.append(f"candidate does not contain the latest materiality annotation: {candidate_id}")
        if (
            item.get("material") is not annotation.get("material")
            or item.get("disposition") != annotation.get("decision")
            or str(item.get("material_reason") or "") != annotation.get("material_reason")
            or not materiality_annotation_complete(item)
            or annotation.get("candidate_identity_fingerprint")
            != candidate_identity_fingerprint(collection, item)
        ):
            errors.append(f"candidate materiality decision is stale: {candidate_id}")
    return errors


def apply_materiality_annotations(
    ledger: dict[str, Any], task_id: str, candidates: dict[str, Any],
    *, task: dict | None = None, evidence: dict | None = None, supplement: dict | None = None,
) -> None:
    if workflow.decision_workflow_enabled(task or {}) or ledger.get("schema_version") == workflow.LEDGER_SCHEMA_VERSION:
        errors = materiality_ledger_errors(ledger, task_id, candidates, require_applied=False,
                                          task=task, evidence=evidence, supplement=supplement)
        if errors:
            raise ValueError("INVALID_MATERIALITY_LEDGER: " + "; ".join(errors))
        summary = workflow.triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)
        for _, item in iter_candidates(candidates):
            signals = item.setdefault("priority_signals", [])
            if item.get("material") is True:
                signal = {"kind": "source_material", "reason": str(item.get("material_reason") or "source_marked_material")}
                if signal not in signals:
                    signals.append(signal)
            item["material"] = False
            item.pop("materiality_annotation", None)
            item.pop("material_reason", None)
            records = [r for r in summary["records"] if r["candidate_id"] == item.get("candidate_id")]
            item["triage_by_scenario"] = {sid: [r for r in records if r["scenario_id"] == sid]
                                           for sid in workflow.scenario_index(task)}
            # Compatibility display only; all new consumers use scenario records.
            primary = [r for r in records if r["scenario_id"] == task["primary_scenario_id"]
                       and r["jurisdiction"] == str(item.get("jurisdiction") or item.get("office") or "").upper()]
            item["disposition"] = primary[0]["decision"] if len(primary) == 1 else "unreviewed"
        return
    errors = materiality_ledger_errors(
        ledger, task_id, candidates, require_applied=False,
    )
    if errors:
        raise ValueError("INVALID_MATERIALITY_LEDGER: " + "; ".join(errors))
    latest: dict[str, dict[str, Any]] = {}
    for annotation in ledger.get("annotations", []):
        latest[str(annotation["candidate_id"])] = annotation
    for _, item in iter_candidates(candidates):
        candidate_id = str(item.get("candidate_id") or "")
        annotation = latest.get(candidate_id)
        if annotation is None:
            item.pop("materiality_annotation", None)
            item["disposition"] = "unreviewed"
            continue
        item["material"] = annotation["material"]
        item["material_reason"] = annotation["material_reason"]
        item["disposition"] = annotation["decision"]
        item["materiality_annotation"] = {
            key: annotation[key]
            for key in (
                "annotation_id", "candidate_id", "candidate_identity_fingerprint",
                "material", "decision", "material_reason", "reviewer", "annotated_at",
            )
        }


def _append_scenario_decisions(task_dir: Path, task: dict, candidates: dict, args: argparse.Namespace) -> None:
    """Validate a batch completely before appending each independently bound record."""
    index, errors = candidate_index(candidates)
    if errors:
        raise ValueError("INVALID_NORMALIZED_CANDIDATES: " + "; ".join(errors))
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    from workflow_v24 import correction_enabled, scenario_supplement
    if correction_enabled(task):
        supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    else:
        supplement_path = task_dir / "supplemental-evidence.json"
        supplement = ensure_object(load_json(supplement_path), supplement_path.name) if supplement_path.is_file() else None
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    errors = materiality_ledger_errors(ledger, task["task_id"], candidates, require_applied=False,
                                      task=task, evidence=evidence, supplement=supplement)
    if errors:
        raise ValueError("INVALID_MATERIALITY_LEDGER: " + "; ".join(errors))
    if args.input:
        payload = load_json(args.input.expanduser().resolve())
        decisions = payload.get("decisions") if isinstance(payload, dict) else payload
        if not isinstance(decisions, list) or not decisions:
            raise ValueError("TRIAGE_INPUT_DECISIONS_REQUIRED")
        if any((args.candidate_id, args.decision, args.material, args.reason, args.material_reason,
                args.scenario_id, args.jurisdiction, args.right_type, args.evidence_ref,
                args.missing_information, args.next_actions_json, args.reading_level,
                args.basis_summary, args.reopen_condition)):
            raise ValueError("TRIAGE_INPUT_CANNOT_MIX_SINGLE_DECISION_FLAGS")
    else:
        if args.decision and args.material:
            raise ValueError("TRIAGE_DECISION_AND_MATERIAL_CONFLICT")
        selected = args.decision or ({"true": "selected", "false": "not_selected"}.get(args.material))
        decisions = [{"candidate_id": args.candidate_id, "decision": selected,
                      "reason": args.reason or args.material_reason, "reviewer": args.reviewer,
                      "scenario_id": args.scenario_id or task["primary_scenario_id"],
                      "jurisdiction": args.jurisdiction, "right_type": args.right_type,
                      "evidence_refs": args.evidence_ref,
                      "reading_level": args.reading_level, "basis_summary": args.basis_summary,
                      "reopen_conditions": args.reopen_condition,
                      "missing_information": args.missing_information,
                      "next_actions": json.loads(args.next_actions_json) if args.next_actions_json else []}]
    pending = copy.deepcopy(ledger)
    appended = []
    # Draft rows mutate only the detached pending ledger, never snapshot inputs.
    with workflow.decision_snapshot(task, evidence, candidates, None, ledger, supplement):
        for decision in decisions:
            if not isinstance(decision, dict):
                raise ValueError("TRIAGE_INPUT_DECISION_MUST_BE_OBJECT")
            decision = dict(decision)
            bound = index.get(decision.get("candidate_id"))
            if bound is None:
                raise ValueError("UNKNOWN_CANDIDATE_ID: " + str(decision.get("candidate_id")))
            # Explicit reading/basis/reopen fields describe an actual review.
            decision["reviewer"] = decision.get("reviewer") or args.reviewer
            if not decision.get("jurisdiction"):
                decision.pop("jurisdiction", None)
            if not decision.get("right_type"):
                decision.pop("right_type", None)
            decision["annotated_at"] = now_iso()
            decision["annotation_id"] = stable_id("TRIAGE", task["task_id"], str(decision["candidate_id"]),
                                                  str(decision.get("scenario_id")), str(time.time_ns()))
            row = workflow.make_annotation(task, *bound, decision, evidence=evidence, supplement=supplement)
            pending["annotations"].append(row)
            appended.append(row)
    errors = materiality_ledger_errors(pending, task["task_id"], candidates, require_applied=False,
                                      task=task, evidence=evidence, supplement=supplement)
    if errors:
        raise ValueError("INVALID_MATERIALITY_LEDGER: " + "; ".join(errors))
    pending["updated_at"] = appended[-1]["annotated_at"]
    with workflow.decision_snapshot(task, evidence, candidates, None, pending, supplement):
        summary = workflow.triage_summary(task, candidates, pending, evidence=evidence, supplement=supplement)
    task.setdefault("checkpoints", {})["materiality_review"] = {
        "status": "success" if not summary["counts"]["unreviewed"] and not summary["counts"]["needs_info"] else "incomplete",
        "at": pending["updated_at"], "decision_workflow_revision": workflow.REVISION,
        "counts": summary["counts"], "by_scenario": summary["by_scenario"],
    }
    for row in appended:
        add_history(task, str(task.get("state") or "ready_for_assessment"),
                    f"Scenario triage appended: {row['annotation_id']} {row['candidate_id']} "
                    f"{row['scenario_id']}/{row['jurisdiction']}/{row['right_type']}={row['decision']}")
    atomic_write_json(task_dir / LEDGER_FILENAME, pending)
    atomic_write_json(task_dir / "task.json", task)


@timed_cli("candidate_triage")
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Append one reviewer materiality decision to the task audit ledger.",
    )
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--candidate-id")
    parser.add_argument("--material", choices=("true", "false"))
    parser.add_argument("--material-reason")
    parser.add_argument("--reviewer")
    parser.add_argument("--decision", choices=sorted(workflow.DECISIONS))
    parser.add_argument("--reason")
    parser.add_argument("--scenario-id")
    parser.add_argument("--jurisdiction")
    parser.add_argument("--right-type")
    parser.add_argument("--evidence-ref", action="append", default=[])
    parser.add_argument("--missing-information", action="append", default=[])
    parser.add_argument("--next-actions-json")
    parser.add_argument("--reading-level", choices=sorted(workflow.READING_LEVELS))
    parser.add_argument("--basis-summary")
    parser.add_argument("--reopen-condition", action="append", default=[])
    parser.add_argument("--input", "--decisions", dest="input", type=Path, help="JSON array or {decisions:[...]} for scenario triage; each row is appended separately")
    args = parser.parse_args()

    task_dir = args.task_dir.expanduser().resolve()
    reason = (args.material_reason or "").strip()
    reviewer = (args.reviewer or "").strip()
    candidate_id = (args.candidate_id or "").strip()
    with evidence_lock(task_dir):
        task = ensure_object(load_json(task_dir / "task.json"), "task.json")
        if not is_active_schema(task):
            raise SystemExit("LEGACY_TASK_READ_ONLY: materiality annotations require 2.3-free")
        assert_active_free_policy(task)
        candidates = ensure_object(
            load_json(task_dir / "normalized-candidates.json"),
            "normalized-candidates.json",
        )
        if workflow.decision_workflow_enabled(task):
            try:
                _append_scenario_decisions(task_dir, task, candidates, args)
            except (ValueError, TypeError) as exc:
                raise SystemExit(str(exc)) from exc
            print(task_dir / LEDGER_FILENAME)
            return
        if any((args.input, args.decision, args.reason, args.scenario_id, args.jurisdiction,
                args.right_type, args.evidence_ref, args.missing_information, args.next_actions_json,
                args.reading_level, args.basis_summary, args.reopen_condition)):
            raise SystemExit("TRIAGE_REVISION_REQUIRED: legacy tasks retain the material/excluded CLI")
        if not candidate_id or not reason or not reviewer or args.material is None:
            raise SystemExit("candidate-id, material, material-reason and reviewer must be non-empty")
        index, candidate_errors = candidate_index(candidates)
        if candidate_errors:
            raise SystemExit("INVALID_NORMALIZED_CANDIDATES: " + "; ".join(candidate_errors))
        bound = index.get(candidate_id)
        if bound is None:
            raise SystemExit(f"UNKNOWN_CANDIDATE_ID: {candidate_id}")
        ledger = load_materiality_ledger(task_dir, str(task.get("task_id") or ""))
        existing_errors = materiality_ledger_errors(
            ledger, str(task.get("task_id") or ""), candidates,
            require_applied=False,
        )
        if existing_errors:
            raise SystemExit("INVALID_MATERIALITY_LEDGER: " + "; ".join(existing_errors))
        material = args.material == "true"
        annotated_at = now_iso()
        annotation = {
            "annotation_id": stable_id(
                "MAT", str(task.get("task_id") or ""), candidate_id,
                annotated_at, reviewer, str(time.time_ns()),
            ),
            "candidate_id": candidate_id,
            "candidate_identity_fingerprint": candidate_identity_fingerprint(*bound),
            "material": material,
            "decision": DECISIONS[material],
            "material_reason": reason,
            "reviewer": reviewer,
            "annotated_at": annotated_at,
        }
        ledger["annotations"].append(annotation)
        ledger["updated_at"] = annotated_at
        atomic_write_json(task_dir / LEDGER_FILENAME, ledger)
        reviewed = {str(item.get("candidate_id") or "") for item in ledger["annotations"]}
        task.setdefault("checkpoints", {})["materiality_review"] = {
            "status": "success" if set(index) <= reviewed else "incomplete",
            "at": annotated_at,
            "reviewed_candidates": len(set(index) & reviewed),
            "candidate_count": len(index),
        }
        add_history(
            task, str(task.get("state") or "ready_for_assessment"),
            f"Materiality reviewer decision appended for {candidate_id}: {DECISIONS[material]}",
        )
        atomic_write_json(task_dir / "task.json", task)
    print(task_dir / LEDGER_FILENAME)


if __name__ == "__main__":
    main()

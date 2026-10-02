#!/usr/bin/env python3
"""Write input files for the most frequent Agent review actions with every derivable field prefilled.

The Agent used to hand-write these JSON files from the prose ``required_input`` of an action card,
re-deriving clue ids, direction ids, query and run ids and hashing nothing but its own memory. This
tool fills only what the task state already determines (scope, ids, runs, the exact clue/direction
inventory) and leaves every judgment as ``null``. A ``null`` is rejected by the recorders, so an
unfilled template can never be recorded by accident, and nothing here decides a review outcome.

    python scripts/input_template.py --task-dir DIR --output-dir NEW_DIR [--work-id WORK-...]

Without ``--work-id`` every currently supported work entry gets a template. Supported reasons:
DISCOVERY_DIRECTION_REVIEW_REQUIRED, DISCOVERY_EXPRESSION_REVIEW_REQUIRED,
DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED (-> record_discovery_semantics.py, ``{"events":[...]}``),
SOURCE_OPERATION_REVIEW_REQUIRED (-> record_source_operation.py, ``{"reviews":[...]}``) and
REVIEW_PROGRESS_QUERY_NOT_PLANNED (-> record_review_progress.py, one initialize/add event).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import atomic_write_json, ensure_object, load_json, sha256_json

DISCOVERY_STAGES = {"DISCOVERY_DIRECTION_REVIEW_REQUIRED": "direction",
                    "DISCOVERY_EXPRESSION_REVIEW_REQUIRED": "before",
                    "DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED": "after"}
OPERATION_REASON = "SOURCE_OPERATION_REVIEW_REQUIRED"
PROGRESS_REASON = "REVIEW_PROGRESS_QUERY_NOT_PLANNED"
RESULT_REASON = "SOURCE_RESULTS_PENDING_PROCESSING"
HANDOFF_REASON = "CANDIDATE_HANDOFF_READY"
RECOVERY_REASONS = frozenset({"SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED", "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED",
                              "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY"})
SUPPORTED_REASONS = frozenset({*DISCOVERY_STAGES, OPERATION_REASON, PROGRESS_REASON, RESULT_REASON,
                               HANDOFF_REASON, *RECOVERY_REASONS})


def supported(entry: dict) -> bool:
    """Work entries this tool can prefill: the listed reasons, and candidate triage decisions."""
    return isinstance(entry, dict) and bool(entry.get("work_id")) and (
        entry.get("reason") in SUPPORTED_REASONS
        or (entry.get("kind") == "triage" and bool(entry.get("candidate_id"))))
CLASSIFICATION_KINDS = {"ipc", "cpc", "uspc", "locarno", "nice", "similar_group", "figurative_classification",
                        "jpo_figurative_classification", "design_code"}
LANGUAGE_KINDS = {"translation", "original_japanese", "english", "romaji", "reading"}


def _plan_row(plan: dict, query_id) -> tuple:
    matches = [(provider, row) for provider, rows in plan.get("queries", {}).items() for row in rows
               if isinstance(row, dict) and row.get("query_id") == query_id]
    return matches[0] if len(matches) == 1 else (None, None)


def direction_template(task: dict, entry: dict):
    import discovery_semantics as ds
    scenario, right = entry.get("scenario_id"), entry.get("right_type")
    directions = ds._directions(task, scenario, right)
    unmapped = sorted(ds._unmapped_facts(task))
    template = {"stage": "direction", "scenario_id": scenario, "jurisdiction": entry.get("jurisdiction"),
                "right_type": right, "reviewer": None, "reason": None,
                "clues": [{"clue_id": clue, "disposition": None, "reason": None}
                          for clue in sorted(ds._clues(task, scenario, right))],
                "directions": [{"direction_id": item["direction_id"], "question": None,
                                "clue_ids": sorted({"fact:" + fid for fid in item["fact_ids"]}
                                                   | {"object:" + oid for oid in item["object_ids"]}),
                                "method": None, "proposed_sources": None, "evidence_needed": None,
                                "supplement_trigger": None} for item in directions]}
    if unmapped:
        template["unmapped_clues"] = [{"clue_id": "fact:" + fid, "disposition": None, "reason": None}
                                      for fid in unmapped]
    guide = {"clue_dispositions": sorted(ds.CLUE_STATES),
             "note": "covered_by_other also needs evidence_refs (existing evidence ids); unmapped clues may not be 'included'; "
                     "every direction's clue_ids are already the exact required set"}
    return template, guide


def before_template(task: dict, plan: dict, entry: dict):
    provider, row = _plan_row(plan, entry.get("query_id"))
    if row is None or not entry.get("direction_id"):
        return None, "QUERY_OR_DIRECTION_UNKNOWN"
    template = {"stage": "before", "scenario_id": entry.get("scenario_id"), "jurisdiction": entry.get("jurisdiction"),
                "right_type": entry.get("right_type"), "direction_id": entry["direction_id"],
                "query_id": row["query_id"], "reviewer": None, "reason": None, "semantic_fit": None,
                "expression_reason": None, "concepts_in_query": None, "uncovered_clues": None,
                "independent_structure": None, "whole_product_constraint": None}
    kind = row.get("discovery_scope", {}).get("expression_basis", {}).get("kind")
    if kind in CLASSIFICATION_KINDS:
        template["classification_basis"] = {"source": None, "meaning": None, "applicability": None}
    if kind in LANGUAGE_KINDS:
        template["language_basis"] = {"original": None, "submitted": None, "source": None, "relationship": None}
    guide = {"actual_query_to_review": row.get("q"), "provider": provider,
             "semantic_fit": ["full", "partial", "mismatch"],
             "note": "full needs uncovered_clues=[]; partial needs a non-empty uncovered_clues; concepts_in_query non-empty; "
                     "independent_structure and whole_product_constraint are booleans (both true needs constraint_reason)"}
    return template, guide


def after_template(task: dict, plan: dict, evidence: dict, entry: dict):
    import discovery_semantics as ds
    provider, row = _plan_row(plan, entry.get("query_id"))
    run = next((r for r in evidence.get("source_runs", []) if r.get("run_id") == entry.get("source_run_id")), None)
    if row is None or run is None or not entry.get("direction_id"):
        return None, "QUERY_RUN_OR_DIRECTION_UNKNOWN"
    template = {"stage": "after", "scenario_id": entry.get("scenario_id"), "jurisdiction": entry.get("jurisdiction"),
                "right_type": entry.get("right_type"), "direction_id": entry["direction_id"],
                "query_id": row["query_id"], "source_run_id": run["run_id"], "evidence_refs": None,
                "reviewer": None, "reason": None, "original_problem_checked": None, "problem_covered": None,
                "result_reason": None, "uncovered_clues": None, "excluded_by_narrowing": None, "next_action": None}
    guide = {"evidence_ids_of_this_run": sorted(ds._linked_evidence(evidence, run)),
             "next_action": ["none", "refine", "fallback", "awaiting_information", "awaiting_capability"],
             "note": "original_problem_checked must be true; problem_covered=true needs next_action none and empty "
                     "uncovered_clues/excluded_by_narrowing; otherwise next_action must not be none"}
    return template, guide


def operation_template(task: dict, plan: dict, evidence: dict, entry: dict):
    import source_operation as so
    provider, row = _plan_row(plan, entry.get("query_id"))
    if row is None:
        return None, "QUERY_UNKNOWN"
    runs = so._runs(evidence, provider, row)
    if not runs:
        return None, "NO_RUN_FOR_QUERY"
    run = runs[-1]
    template = {"provider": provider, "query_id": row["query_id"], "source_run_id": run["run_id"],
                "reviewer": None, "reason": None, "decision": None,
                "checks": {"request_response_binding": None, "field_effect": None, "pagination": None,
                           "known_number": None, "original_content": None, "current_status": None}}
    guide = {"operation": row.get("operation"), "runs_for_query": [r.get("run_id") for r in runs],
             "decision": ["accepted", "rejected", "unvalidated"],
             "check_values": sorted(so.GOOD | so.BAD),
             "note": "request_response_binding is a boolean; accepted needs it true and the checks this operation "
                     "requires verified; the run id above is the latest run, change it if another run was reviewed"}
    return template, guide


def progress_item(task: dict, plan: dict, entry: dict):
    import review_progress_stage_a as rp
    provider, row = _plan_row(plan, entry.get("query_id"))
    if row is None:
        return None, "QUERY_UNKNOWN"
    scope = {"scenario_id": entry.get("scenario_id"), "jurisdiction": row.get("jurisdiction"),
             "right_type": row.get("right_type"), "product_version": rp._version(task)}
    identity = sha256_json({"query_id": row["query_id"], "scope": scope})[:20]
    return {"item_id": "ITEM-" + identity, "kind": "query", "scope": scope, "module_ids": None,
            "acceptance_condition": None, "query_id": row["query_id"]}, None


def _bound_candidates(candidates: dict, run_id: str, rows: dict) -> dict:
    """position -> candidate ids whose retained source is exactly that row of this run (as the recorder checks)."""
    bound: dict = {}
    for name in ("patents", "trademarks", "copyright_assets", "enforcement"):
        for candidate in candidates.get(name, []):
            if not isinstance(candidate, dict):
                continue
            for source in candidate.get("sources", []):
                if not isinstance(source, dict) or source.get("source_run_id") != run_id:
                    continue
                position = source.get("source_position") or source.get("result_position")
                hashes = {source.get("source_record_sha256"), source.get("original_source_record_sha256")} - {None}
                for row_position, row in rows.items():
                    if ((position is None and not hashes) or (position is not None and position != row_position)
                            or (hashes and row["raw_sha256"] not in hashes)):
                        continue
                    bound.setdefault(row_position, []).append(candidate.get("candidate_id"))
    return {position: sorted(set(ids)) for position, ids in bound.items()}


def result_processing_event(task_dir: Path, evidence: dict, candidates: dict, entry: dict):
    import source_result_processing as srp
    run = next((r for r in evidence.get("source_runs", []) if r.get("run_id") == entry.get("source_run_id")), None)
    if run is None:
        return None, "RUN_UNKNOWN"
    if entry.get("result_form") == srp.WHOLE_RECORD:
        return None, "WHOLE_RECORD_REVIEW_NEEDS_READING_UNITS_USE_THE_CARD"
    unparsed = sorted(entry.get("pending_parse_positions") or [])
    positions = [p for p in sorted(entry.get("pending_positions") or []) if p not in unparsed]
    if not positions:
        return None, "NO_PARSED_PENDING_POSITION" + ("_PARSE_ROWS_FIRST" if unparsed else "")
    index, _ = srp._retained_run(task_dir, run, evidence)
    rows = {row["position"]: row for row in index["rows"]}
    event = {"source_run_id": run["run_id"],
             "decisions": [{"position": position, "outcome": None, "reviewer": None, "reason": None}
                           for position in positions]}
    guide = {"source_run_id": run["run_id"], "provider": run.get("provider"), "query_id": run.get("query_id"),
             "outcome": sorted(srp.OUTCOMES), "raw_paths": run.get("raw_paths"),
             "bound_candidates_by_position": {str(k): v for k, v in
                                              _bound_candidates(candidates, run["run_id"], rows).items() if k in positions},
             "unparsed_positions_need_parsed_rows_first": unparsed,
             "note": "add candidate_ids (one of the bound ids above) only for outcome candidate/duplicate_source; "
                     "non_candidate takes none; every position needs the reading you actually did as reason"}
    return event, guide


def handoff_item(entry: dict):
    """One candidate of the shared handoff batch: a scope review per still-open scenario/country."""
    scopes = entry.get("remaining_scopes") or []
    if not scopes or not entry.get("candidate_id"):
        return None, "NO_REMAINING_SCOPE"
    reviews = [{"candidate_id": entry["candidate_id"], "scenario_id": scope.get("scenario_id"),
                "jurisdiction": scope.get("jurisdiction"), "applicability": None, "reason": None, "evidence_refs": None}
               for scope in scopes]
    return {"candidate_id": entry["candidate_id"], "scope_reviews": reviews}, {
        "candidate_id": entry["candidate_id"], "ready_evidence_ids": entry.get("ready_evidence_refs", []),
        "pending_evidence_ids": entry.get("pending_evidence_refs", [])}


def _recovery_run(entry: dict, evidence: dict, wanted_states: set, status_ok=None):
    import recovery_stage_b as rb
    refs = (entry.get("recovery") or {}).get("source_run_refs") or []
    runs = {r.get("run_id"): r for r in evidence.get("source_runs", []) if isinstance(r, dict)}
    for ref in reversed(refs):
        run = runs.get(ref.get("run_id")) if isinstance(ref, dict) else None
        if run is not None and rb.effective_submission(evidence, run) in wanted_states and (
                status_ok is None or run.get("status") in status_ok):
            return run
    return None


def _new_failure_policy(task: dict) -> bool:
    return (task.get("retrieval_workflow_revision") == "api-first-v3"
            and task.get("assessment_revision") == "known-findings-risk-v1"
            and task.get("presentation_policy_revision") == "operator-report-v1")


def recovery_request(task: dict, evidence: dict, entry: dict):
    import hashlib
    from common import sha256_json as digest
    reason = entry.get("reason")
    if reason == "SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED":
        run = _recovery_run(entry, evidence, {"submitted"}, {"failed", "access_limited"})
    elif reason == "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED":
        run = _recovery_run(entry, evidence, {"not_submitted"})
    else:
        run = _recovery_run(entry, evidence, {"unknown"})
    if run is None:
        return None, None, "NO_MATCHING_RUN"
    base = {"source_run_id": run["run_id"], "source_run_sha256": digest(run)}
    if reason == "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED":
        request = {"kind": "pre_submission_repair", **base, "reviewer": None, "reasoning": None,
                   "failure_cause": None, "repair_basis": None, "condition_check": None, "receipt_review": None}
        guide = {"note": "Only for a run confirmed NOT submitted: what failed, the actual repair, and the re-check of the "
                         "execution conditions. It does not spend a submitted-failure retry and never resends by itself."}
    elif reason == "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY":
        request = {"kind": "unknown_check", **base, "reviewer": None, "reasoning": None, "outcome": None,
                   "original_receipt_review": None, "basis": None, "check_method": None}
        guide = {"outcome": ["not_submitted", "submitted_running", "submitted_failed", "result_obtained", "still_unknown"],
                 "check_method": ["existing_receipt", "existing_page", "qualified_status_query"],
                 "note": "qualified_status_query also needs query_is_read_only=true and source_rule_ref; result_obtained needs "
                         "result_run_id; still_unknown needs disposition continue_check|waiting|limited (limited needs the four "
                         "*_reviewed/done booleans and their *_basis texts). Never resubmit an unknown request."}
    else:
        paths = run.get("raw_paths", [])
        review = {"reviewer": None, "reasoning": None, "receipt_review": None, "material_review": None,
                  "remaining_work": None, "repair_basis": None, "source_rule_ref": None, "source_allows_retry": None}
        if not paths:
            review["receipt_absence_reason"] = None
        guide = {"run_error": {key: run.get(key) for key in ("error_code", "detail", "status", "provider", "operation")},
                 "retained_receipts": paths,
                 "note": "material_review must cover any retained readable material (process it first); source_allows_retry "
                         "true = one bounded retry may follow; for a v3 no-retry choose false and add retry_disposition="
                         "not_requested plus no_retry_reason (task-limit proof: retry_constraint)"}
        if _new_failure_policy(task):
            # New operator tasks record the receipt disposition and the retry decision atomically.
            request = {"kind": "failure_closeout", **base,
                       "receipt_disposition": ({"outcome": None} if paths else None), "failure_review": review}
            guide["closeout"] = ("receipt_disposition.outcome must be non_result_error when the receipt has no result rows; "
                                 "null (as prefilled) only because the run retained no body; failure_cause is taken from the run")
        else:
            request = {"kind": "failure_review", **base, "receipt_paths": paths,
                       "failure_cause": ": ".join(str(run.get(k)) for k in ("error_code", "detail") if run.get(k)) or None,
                       **review}
    name = "recovery-" + str(run["run_id"]) + ".json"
    return {"name": name, "request": request}, guide, None


def _label(candidate: dict) -> str:
    for key in ("title", "publication_number", "registration_number", "mark_text", "name", "snippet"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return ""


def triage_decision(task: dict, candidates: dict, entry: dict):
    import annotate_materiality as am
    import decision_workflow as dw
    index, _errors = am.candidate_index(candidates)
    bound = index.get(entry.get("candidate_id"))
    if bound is None:
        return None, "CANDIDATE_UNKNOWN"
    _collection, candidate = bound
    scenario, right = entry.get("scenario_id"), entry.get("right_type")
    jurisdiction = str(entry.get("jurisdiction") or "").upper()
    template = {"candidate_id": entry["candidate_id"], "scenario_id": scenario, "jurisdiction": entry.get("jurisdiction"),
                "right_type": right, "decision": None, "reason": None, "reviewer": None, "reading_level": None,
                "basis_summary": None, "evidence_refs": None, "reopen_conditions": None}
    guide = {"candidate_id": entry["candidate_id"], "label": _label(candidate), "reason_open": entry.get("reason"),
             "candidate_evidence_ids": sorted({s.get("evidence_id") for s in candidate.get("sources", [])
                                               if isinstance(s, dict) and s.get("evidence_id")})}
    if dw.triage_scope_enabled(task):
        scope = dw.candidate_scope_details(task, scenario, right, candidate)
        origin = str(candidate.get("jurisdiction") or candidate.get("office") or "").upper()
        gaps = ({"target_jurisdiction"} if origin != jurisdiction else set()) | ({"right_type"} if right == "unknown" else set())
        relation = {"product_object_ids": None, "direction_ids": None, "scope_reason": None,
                    "evidence_refs": None, "identity_gaps": sorted(gaps)}
        if gaps:
            relation["identity_location"] = {"reason": None, "affected_work": None, "next_action": None}
        template["candidate_relation"] = relation
        template["comparison"] = {"candidate_content": None, "product_content": None, "relationship": None}
        guide["included_product_objects"] = {o["object_id"]: o["ready_direction_ids"]
                                             for o in scope["objects"] if o["scope_status"] == "included"}
        guide["identity_gaps_prefilled_are_the_minimum"] = sorted(gaps)
        guide["comparison_extra_keys_by_decision"] = {
            "selected": ["investigation_question"], "not_selected": ["difference", "applicability_limit"],
            "needs_info": ["missing_fact_effect", "completion_condition", "existing_material_review"]}
    return template, guide


def build(task_dir: Path, work_ids=None):
    """Return ({file name: content}, [file summaries], [skipped entries]) for the current work view."""
    from workflow_v24 import work_view_from_dir
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    plan = load_json(task_dir / "search-plan.json") if (task_dir / "search-plan.json").is_file() else {}
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    entries = [row for row in work_view_from_dir(task_dir).get("entries", []) if isinstance(row, dict)]
    wanted = set(work_ids or [])
    unknown = wanted - {row.get("work_id") for row in entries}
    if unknown:
        raise ValueError("INPUT_TEMPLATE_WORK_ID_NOT_CURRENT: " + ",".join(sorted(unknown)))
    files, summaries, skipped = {}, [], []
    discovery = {"direction": [], "before": [], "after": []}
    operations, progress_items, results, triage, handoffs, recoveries = [], [], [], [], [], []
    candidates = load_json(task_dir / "normalized-candidates.json") if (task_dir / "normalized-candidates.json").is_file() else {}
    for entry in entries:
        if wanted and entry.get("work_id") not in wanted:
            continue
        reason = entry.get("reason")
        if not supported(entry):
            if wanted:
                skipped.append({"work_id": entry.get("work_id"), "reason": "NO_TEMPLATE_FOR_" + str(reason)})
            continue
        if reason in DISCOVERY_STAGES:
            stage = DISCOVERY_STAGES[reason]
            template, guide = (direction_template(task, entry) if stage == "direction" else
                               before_template(task, plan, entry) if stage == "before" else
                               after_template(task, plan, evidence, entry))
            target = discovery[stage]
        elif reason == OPERATION_REASON:
            template, guide = operation_template(task, plan, evidence, entry)
            target = operations
        elif reason == RESULT_REASON:
            template, guide = result_processing_event(task_dir, evidence, candidates, entry)
            target = results
        elif reason == HANDOFF_REASON:
            template, guide = handoff_item(entry)
            target = handoffs
        elif reason in RECOVERY_REASONS:
            found, guide, error = recovery_request(task, evidence, entry)
            template = found
            if found is None:
                guide = error
            target = recoveries
        elif reason not in SUPPORTED_REASONS:
            template, guide = triage_decision(task, candidates, entry)
            target = triage
        else:
            template, guide = progress_item(task, plan, entry)
            target = progress_items
        if template is None:
            skipped.append({"work_id": entry.get("work_id"), "reason": guide})
            continue
        target.append({"work_id": entry.get("work_id"), "template": template, "guide": guide})
    for stage, items in discovery.items():
        if items:
            name = "discovery-" + stage + ".json"
            files[name] = {"events": [item["template"] for item in items]}
            summaries.append({"file": name, "recorder": "record_discovery_semantics.py", "count": len(items),
                              "work_ids": [item["work_id"] for item in items],
                              "fill": _null_paths(files[name]), "guide": [item["guide"] for item in items]})
    if handoffs:
        files["candidate-handoff.json"] = {
            "candidate_ids": [item["template"]["candidate_id"] for item in handoffs],
            "scope_reviews": [row for item in handoffs for row in item["template"]["scope_reviews"]],
            "reviewer": None, "reason": None}
        summaries.append({"file": "candidate-handoff.json", "recorder": "record_candidate_handoff.py",
                          "count": len(handoffs), "work_ids": [item["work_id"] for item in handoffs],
                          "fill": _null_paths({"x": [files["candidate-handoff.json"]]}) ,
                          "guide": {"applicability": sorted(_handoff_applicability()),
                                    "candidates": [item["guide"] for item in handoffs],
                                    "note": "one batch = one reviewer/reason for all listed candidates; each scope review's "
                                            "evidence_refs must be a non-empty subset of that candidate's ready_evidence_ids "
                                            "and actually read; drop a candidate from candidate_ids AND scope_reviews to hand it "
                                            "off separately"}})
    for item in recoveries:
        template = item["template"]
        name = template["name"]
        files[name] = template["request"]
        summaries.append({"file": name, "recorder": "record_recovery_review.py", "count": 1,
                          "work_ids": [item["work_id"]], "fill": _null_paths({"x": [template["request"]]}),
                          "guide": item["guide"]})
    if results:
        files["result-processing.json"] = {"events": [item["template"] for item in results]}
        summaries.append({"file": "result-processing.json", "recorder": "record_source_result_processing.py",
                          "count": len(results), "work_ids": [item["work_id"] for item in results],
                          "fill": _null_paths(files["result-processing.json"]),
                          "guide": [item["guide"] for item in results], "batch_input": True})
    if triage:
        files["triage-decisions.json"] = {"decisions": [item["template"] for item in triage]}
        import decision_workflow as dw
        summaries.append({"file": "triage-decisions.json", "recorder": "annotate_materiality.py",
                          "count": len(triage), "work_ids": [item["work_id"] for item in triage],
                          "fill": _null_paths(files["triage-decisions.json"]),
                          "guide": {"decision": sorted(dw.DECISIONS), "reading_level": sorted(dw.READING_LEVELS),
                                    "candidates": [item["guide"] for item in triage],
                                    "note": "reopen_conditions and evidence_refs are lists of strings; candidate_relation.evidence_refs "
                                            "must be a subset of evidence_refs; add the decision-specific comparison keys "
                                            "(comparison_extra_keys_by_decision); needs_info also needs missing_information[] and "
                                            "structured next_actions[] (see the candidate follow-up reference); "
                                            "product_object_ids/direction_ids come from included_product_objects"}})
    if operations:
        files["source-operation.json"] = {"reviews": [item["template"] for item in operations]}
        summaries.append({"file": "source-operation.json", "recorder": "record_source_operation.py",
                          "count": len(operations), "work_ids": [item["work_id"] for item in operations],
                          "fill": _null_paths(files["source-operation.json"]),
                          "guide": [item["guide"] for item in operations]})
    if progress_items:
        import review_progress_stage_a as rp
        first = not rp._events(evidence)
        event = {"kind": "initialize" if first else "add", "actor": None, "reasoning": None,
                 "items": [item["template"] for item in progress_items]}
        if not first:
            event["upstream_ref"] = None
        files["review-progress.json"] = event
        summaries.append({"file": "review-progress.json", "recorder": "record_review_progress.py",
                          "count": len(progress_items), "work_ids": [item["work_id"] for item in progress_items],
                          "fill": _null_paths(event),
                          "guide": {"module_ids": sorted(_module_ids()),
                                    "note": "module_ids: pick the modules that own each item's right type; "
                                            "acceptance_condition: what completing the query must show"}})
    return files, summaries, skipped


def _handoff_applicability():
    from candidate_handoff import APPLICABILITY
    return APPLICABILITY


def _module_ids():
    from assessment_estimate import MODULE_RIGHTS
    return MODULE_RIGHTS


def _null_paths(value, prefix=""):
    """Dotted paths of every null the Agent must still fill (compact: repeated list rows collapse)."""
    if not prefix and isinstance(value, dict) and len(value) == 1 and isinstance(next(iter(value.values())), list):
        # {"events": [...]} / {"reviews": [...]} wrappers only batch identical rows.
        return sorted({path.removeprefix("[].") for path in _null_paths(next(iter(value.values())))})
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            found += _null_paths(child, prefix + key + ".")
            if child is None:
                found.append(prefix + key)
    elif isinstance(value, list):
        for child in value:
            found += _null_paths(child, prefix + "[].")
    return sorted(set(found))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="A new directory for the template files")
    parser.add_argument("--work-id", action="append", help="Only this current work entry (repeatable)")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    if args.output_dir.exists():
        parser.error("--output-dir must not exist; choose a new directory")
    files, summaries, skipped = build(task_dir, args.work_id)
    if files:
        args.output_dir.mkdir(parents=True)
        for name, content in files.items():
            atomic_write_json(args.output_dir / name, content)
    for summary in summaries:
        summary["file"] = str(args.output_dir / summary["file"])
        summary["command"] = ("python scripts/" + summary["recorder"] + " --task-dir " + str(task_dir)
                              + " --input " + summary["file"])
    print(json.dumps({"written": summaries, "skipped": skipped,
                      "rule": "Every null is a judgment only you can make; recorders reject unfilled templates."},
                     ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()

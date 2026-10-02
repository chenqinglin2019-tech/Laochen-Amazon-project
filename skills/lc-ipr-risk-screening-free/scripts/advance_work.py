#!/usr/bin/env python3
"""Advance source work and emit recorder-bound cards for every remaining action."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import atomic_write_json, ensure_object, load_json, now_iso, sha256_file, sha256_json
from review_readiness import dispatch_view as work_view_from_dir
from runtime_timing import progress_view


API_PROVIDERS = {"epo_ops", "euipo_trademark", "euipo_design", "jpo_api", "inpi_api",
                 "serper_patents", "serper_search", "serper_web", "serper_images", "serpapi_google_patents",
                 "serpapi_google_lens", "signa"}


def phase_for(row: dict[str, Any], browser: bool) -> str:
    phase = str(row.get("execution_phase") or "")
    if browser:
        return "fallback" if phase == "discovery_fallback" else "verification"
    return "discovery" if phase.startswith("discovery") else "verification"


def plan_rows(plan: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    result = {}
    for provider, rows in plan.get("queries", {}).items():
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and isinstance(row.get("query_id"), str):
                result[row["query_id"]] = (provider, row)
    return result


def actionable_packet(view: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Project every current next-work obligation into one dispatcher packet.

    ``review_work`` is deliberately a separate projection in ``next_work``.
    It must still be consumed here: otherwise a run can appear to have
    finished after retrieval even though its required independent reviews have
    never happened.
    """
    packet = {"source": [], "agent": [], "repair": [], "review": [], "waiting": []}
    for entry in view.get("entries", []):
        if not isinstance(entry, dict):
            raise ValueError("INVALID_NEXT_WORK_ITEM")
        state, kind = entry.get("state"), entry.get("kind")
        if state == "ready" and kind == "source_lookup": packet["source"].append(entry)
        elif state == "awaiting_review" and kind == "source_lookup": packet["agent"].append(entry)
        elif kind == "plan_repair" and state in {"ready", "awaiting_review"}: packet["repair"].append(entry)
        elif kind in {"product_analysis", "agent_investigation", "agent_read", "professional_review", "triage"} and state in {"ready", "awaiting_review"}:
            packet["agent"].append(entry)
        elif state in {"awaiting_access", "awaiting_user", "submission_unknown", "blocked"}:
            packet["waiting"].append(entry)
        else:
            raise ValueError("UNKNOWN_NEXT_WORK_KIND_OR_STATE: " + str(kind) + "/" + str(state))
    for entry in view.get("review_work", {}).get("entries", []):
        if not isinstance(entry, dict):
            raise ValueError("INVALID_SCOPE_REVIEW_WORK_ITEM")
        if entry.get("kind") != "scope_review":
            raise ValueError("UNKNOWN_REVIEW_WORK_KIND: " + str(entry.get("kind")))
        if entry.get("state") in {"ready", "awaiting_review"}:
            packet["review"].append(entry)
        elif entry.get("state") in {"awaiting_access", "awaiting_user", "submission_unknown", "blocked"}:
            packet["waiting"].append(entry)
        else:
            raise ValueError("UNKNOWN_SCOPE_REVIEW_STATE: " + str(entry.get("state")))
    return packet


def source_entries_after_triage_priority(task: dict, view: dict) -> tuple[list[dict], bool]:
    from candidate_triage_stage import light_triage_pending
    deferred = bool(task.get("triage_stage_revision") and light_triage_pending(view))
    return ([] if deferred else actionable_packet(view)["source"], deferred)


def action_card(task_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    """Describe one Agent action; supported review cards also name the input-template generator."""
    card = _action_card(task_dir, entry)
    from input_template import supported as template_supported
    if template_supported(entry):
        # The tool prefills every derivable field and leaves each judgment null (never recordable unfilled).
        card["input_template"] = {"tool": str(Path(__file__).resolve().parent / "input_template.py"),
            "args": ["--task-dir", str(task_dir), "--work-id", entry["work_id"], "--output-dir", "<new-directory>"]}
    return card


def _action_card(task_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    """Describe one Agent action without claiming that it was completed."""
    scripts = Path(__file__).resolve().parent
    kind, reason = entry.get("kind"), entry.get("reason")
    card = {"work_id": entry.get("work_id"), "scope": {key: entry.get(key) for key in
            ("scenario_id", "jurisdiction", "right_type", "candidate_id", "query_id")},
            "reason": reason, "depends_on": entry.get("source_run_refs", []),
            "validation": "Re-run next_work; this work_id must be absent only after its recorder accepts evidence."}
    if reason in {"PROGRESS_DIAGNOSIS_OR_REPAIR_REQUIRED", "PROGRESS_TECHNICAL_STOP_REQUIRED"}:
        return {**card, "action": "diagnose_and_repair_original_action" if reason ==
            "PROGRESS_DIAGNOSIS_OR_REPAIR_REQUIRED" else "record_technical_stop_and_recovery_condition",
            "recorder": str(scripts / "record_progress.py"),
            "action_id": entry.get("linked_action_id"),
            "required_input": ["original command and receipt", "retained files and adapter",
                "submission facts", "new verifiable repair evidence", "remaining work and recovery condition"]}
    if kind == "source_lookup" and reason in {"SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED",
                                              "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED"}:
        return {**card, "action": ("review_failed_source_before_retry" if
                reason == "SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED" else "review_pre_submission_repair"),
            "recorder": str(scripts / "record_recovery_review.py"),
            "source_run_refs": entry.get("recovery", {}).get("source_run_refs", []),
            "required_input": (["exact original run/hash and receipt", "retained material review",
                "remaining work and failure cause", "repair basis and source retry rule"] if
                reason == "SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED" else
                ["exact original run/hash and receipt", "confirmed non-submission",
                 "failure cause", "actual repair and renewed execution-condition check"]),
            "validation": "A bound review is required before another external submission; normal source and budget gates still apply."}
    if kind == "source_lookup" and reason == "RETAINED_RESULT_REVIEW_REQUIRED":
        return {**card, "action": "review_bound_retained_result",
            "source_run_refs": entry.get("recovery", {}).get("source_run_refs", []),
            "required_input": ["original request and result match", "retained raw result",
                "position-bound processing or applicable discovery review"],
            "validation": "Process the retained result using its existing recorder; it is not a fresh source request."}
    if kind == "source_lookup" and reason == "TRIAGE_REVIEW_REQUIRED":
        # This dispatch reason also represents unmerged or unresolved-identity
        # API cards. Reading the existing receipt must precede scoped triage.
        return {**card, "action": "review_retained_discovery_candidates",
            "provider": entry.get("provider"), "query_id": entry.get("query_id"),
            "recorder": str(scripts / "annotate_materiality.py"),
            "merge_recorder": str(scripts / "merge_candidates.py"),
            "identity_recorder": str(scripts / "record_candidate_identity_correction.py"),
            "required_input": ["exact query and retained source-run references",
                "all acquired cards preserved in normalized candidates",
                "source-backed identity correction only when identity is unresolved",
                "current scenario/country/right decision with reading basis and evidence references"],
            "validation": "Review retained cards, merge if needed, then record current scoped decisions. Re-run next_work; this card neither submits a request nor proves triage or coverage complete."}
    if kind == 'product_analysis':
        return {**card,'action':'review_product_scope_or_generate_plan','recorder':str(scripts/'record_product_scope.py'),
            'reason':'Record sourced scope/fact dependencies. For changed dependencies with an unchanged valid request, record query_revalidations with a new review_id, query_id, plan_entry_sha256, source_refs and reason; otherwise expand with justified terms. Preserve auth and identity.'}
    if kind == "source_lookup" and reason == "REVIEW_PROGRESS_QUERY_NOT_PLANNED":
        return {**card, "action": "register_current_query_progress",
            "recorder": str(scripts / "record_review_progress.py"),
            "query_id": entry.get("query_id"),
            "required_input": ["current necessary query and plan-entry hash", "purpose and upstream basis"],
            "validation": "Register only a current necessary plan item; obsolete queries must remain withdrawn, not be marked completed."}
    if kind == "agent_investigation" and reason == "REVIEW_PROGRESS_QUERY_NOT_PLANNED":
        return {**card, "action": "register_current_query_progress",
            "recorder": str(scripts / "record_review_progress.py"),
            "required_input": ["current necessary query and plan-entry hash", "purpose and upstream basis"],
            "validation": "Register only a current necessary plan item; obsolete queries must remain withdrawn, not be marked completed."}
    if kind == "agent_investigation" and reason == "DISCOVERY_DIRECTION_REVIEW_REQUIRED":
        return {**card, "action": "review_discovery_direction",
            "recorder": str(scripts / "record_discovery_semantics.py"),
            "required_input": ["current direction, product clues and prior retained results", "remaining gap and bounded route"],
            "validation": "A sourced direction review is required; this card is not a source submission or coverage proof."}
    if kind == "agent_investigation" and reason in {
            "DISCOVERY_EXPRESSION_REVIEW_REQUIRED", "DISCOVERY_RESULT_SEMANTIC_REVIEW_REQUIRED"}:
        return {**card, "action": ("review_discovery_expression" if reason ==
                "DISCOVERY_EXPRESSION_REVIEW_REQUIRED" else "review_discovery_result_semantics"),
            "recorder": str(scripts / "record_discovery_semantics.py"),
            "stage": "before" if reason == "DISCOVERY_EXPRESSION_REVIEW_REQUIRED" else "after",
            "direction_id": entry.get("direction_id"),
            "required_input": ["current direction and exact query identity", "actual expression and uncovered clues",
                               "retained source and original problem coverage for result review"],
            "validation": "Record a bound semantic review; this card does not submit a query or declare the direction covered."}
    if kind == "agent_investigation" and reason in {
            "SOURCE_OPERATION_REVIEW_REQUIRED", "SOURCE_OPERATION_RUN_BINDING_INVALID",
            "SOURCE_OPERATION_REJECTED_REPLAN_REQUIRED"}:
        return {**card, "action": "review_source_operation_or_replan",
            "recorder": str(scripts / "record_source_operation.py"),
            "plan_recorder": str(scripts / "generate_search_plan.py"),
            "provider": entry.get("provider"), "query_id": entry.get("query_id"),
            "required_input": ["exact planned request and bound retained response",
                "field effect, pagination and requested content checks",
                "reviewed repair or alternative route if the operation is rejected"],
            "validation": "Keep failed/unvalidated operations unaccepted; record a sourced review or repair the plan before re-running next_work. This card does not authorize resubmission."}
    if kind == "agent_investigation" and reason in {
            "SOURCE_RESULTS_PENDING_PROCESSING", "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID"}:
        if entry.get('result_form') == 'whole_record_receipt':
            return {**card, 'action':'read_retained_patent_record',
                'recorder':str(scripts / 'record_source_result_processing.py'),
                'source_run_id':entry.get('source_run_id'),
                'reading_units':entry.get('reading_units'),
                'required_input':['record_content_review with the listed reading_units',
                    'actual reader and exact whole-record analysis; image links are not reviewed drawings'],
                'validation':'Bind the complete retained record to its known candidate; do not emit search cards for citations or family lists.'}
        return {**card, "action": "review_retained_source_results",
            "recorder": str(scripts / "record_source_result_processing.py"),
            "source_run_id": entry.get("source_run_id"),
            "pending_positions": entry.get("pending_positions", []),
            "required_input": ["source_run_id", "retained raw receipt", "position-bound result decisions"],
            "validation": "Re-run next_work; material processing completes only when every acquired position has a reviewed destination."}
    if kind == "agent_investigation" and reason == "HISTORICAL_DYNAMIC_FACT_RECHECK_REQUIRED":
        return {**card, "action": "recheck_historical_dynamic_fact",
            "recorder": str(scripts / "record_continuation.py"),
            "source_run_id": entry.get("source_run_id"),
            "reconciliation_id": entry.get("reconciliation_id"),
            "required_input": ["current source result bound to the same fact", "retained and reviewed raw material",
                "original versus current fact comparison", "affected specialty review"],
            "validation": "A source-bound evidence_recheck_complete event closes this work; affected specialty conclusions still require their own review."}
    if kind == "agent_investigation" and reason == "CANDIDATE_HANDOFF_READY":
        return {**card, "action": "review_candidate_scope_and_handoff",
            "recorder": str(scripts / "record_candidate_handoff.py"),
            "candidate_id": entry.get("candidate_id"),
            "ready_evidence_refs": entry.get("ready_evidence_refs", []),
            "pending_evidence_refs": entry.get("pending_evidence_refs", []),
            "required_input": ["candidate_ids", "scope_reviews per receiving scenario/country",
                               "ready evidence references", "reviewer", "reason"],
            "validation": "Re-run next_work; this candidate is handed off only at the current identity/content digest."}
    if kind == "agent_investigation" and reason == "CANDIDATE_HANDOFF_SOURCE_PENDING":
        return {**card, "action": "resolve_candidate_source_binding",
            "candidate_id": entry.get("candidate_id"),
            "pending_evidence_refs": entry.get("pending_evidence_refs", []),
            "required_input": ["retained source or import registration",
                               "missing result position/disposition", "smallest correction action"],
            "validation": "Repair source/result processing and rerun next_work; a handoff cannot use an unreviewed or missing source."}
    if kind == "agent_investigation" and reason == "CANDIDATE_IDENTITY_DIRECTION_PENDING":
        return {**card, "action": "locate_candidate_identity_and_direction",
            "bounded_public_recorder": str(scripts / "record_public_identity.py"),
            "candidate_id": entry.get("candidate_id"),
            "identity_gaps": entry.get("identity_gaps", []),
            "identity_location": entry.get("identity_location", {}),
            "evidence_refs": entry.get("evidence_refs", []),
            "required_input": ["retained candidate and product-object evidence",
                               "smallest identity or direction question", "bounded next action"],
            "validation": "Keep the association decision; only a sourced identity correction or reviewed scope relation can authorize country/right-specific work."}
    if kind == "agent_investigation" and reason in {
            "FOLLOWUP_DISCOVERY_BINDING_REQUIRED", "FOLLOWUP_RESULT_REVIEW_REQUIRED"}:
        return {**card, "action": "bind_or_review_candidate_followup",
            "recorder": str(scripts / "record_candidate_followup.py"),
            "action_id": entry.get("action_id"), "query_id": entry.get("query_id"),
            "required_input": ["current needs_info decision", "exact planned request or retained result",
                               "actual discovery and verification obligations", "reviewer and reason"],
            "validation": "A discovery/mixed request needs a pre-execution binding; each acquired result needs its own review before a new decision."}
    if kind == "agent_investigation" and reason in {
            "TRIAGE_SELECTED_HANDOFF_REQUIRED", "TRIAGE_CHANGE_REVIEW_REQUIRED",
            "TRIAGE_ATTRIBUTION_REQUIRED", "TRIAGE_IDENTITY_CHANGE_IMPACT_REQUIRED"}:
        return {**card, "action": "review_candidate_triage_stage",
            "recorder": str(scripts / "record_candidate_triage_stage.py"),
            "annotation_id": entry.get("annotation_id"),
            "reopen_event_id": entry.get("reopen_event_id"),
            "required_input": ["current candidate and scoped decision", "retained evidence and actual reading scope",
                               "affected old decision and dependencies for reopen", "reviewer and concrete basis"],
            "validation": "Re-run next_work; only a reviewed current decision and accurate selected handoff close this stage item."}
    if kind == "agent_investigation" and str(reason or "").startswith("SPECIALTY_"):
        return {**card, "action": "review_patent_or_design_specialty",
            "recorder": str(scripts / "record_specialty_analysis.py"),
            "required_input": ["current selected handoff and scope", "actual material and reading locations",
                               "fact purpose or claim/design unit", "remaining obligation and review basis"],
            "validation": "Re-run next_work; only an evidence-bound module-06 event can close the specified specialty obligation."}
    if kind == "agent_investigation" and str(reason or "").startswith("M07_"):
        return {**card, "action": "review_distinctive_rights",
            "recorder": str(scripts / "record_distinctive_rights.py"),
            "required_input": ["current selected handoff and concrete object/subject version",
                               "reviewed registration or public-fact track and actual material",
                               "trademark, copyright or trade-dress review and enforcement event when applicable",
                               "remaining dependency, date meaning and source basis"],
            "validation": "Re-run next_work; review current 07A-07D scoped obligations, batch disposition and handoff usability. Module 07 completion does not authorize publication."}
    if kind == "agent_investigation" and entry.get("provider") == "asset_provenance":
        query_ids = entry.get("shared_query_ids") or [entry.get("query_id", "")]
        query_flags = [value for query_id in query_ids for value in ("--query-id", query_id)]
        card.update(action="public_asset_investigation", recorder=str(scripts / "record_asset_provenance.py"),
                    command=[sys.executable, str(scripts / "record_asset_provenance.py"), "--task-dir", str(task_dir),
                             *query_flags, "--input", "<agent-review.json>"],
                    **({"work_ids": entry["shared_work_ids"], "query_ids": query_ids,
                        "jurisdictions": entry.get("shared_jurisdictions", [])} if entry.get("shared_work_ids") else {}),
                    required_input=["retained sources", "artifact hashes", "step evidence_refs", "reasoning"])
    elif kind == "plan_repair" and reason == "API_DISCOVERY_REVIEW_REQUIRED":
        card.update(action="review_discovery_result", recorder=str(scripts / "record_discovery_review.py"),
                    command=[sys.executable, str(scripts / "record_discovery_review.py"), "--task-dir", str(task_dir),
                             "--query-id", entry.get("query_id", ""), "--input", "<review.json>"],
                    required_input=["source_run_id", "evidence_ids", "triage_digest", "outcome", "reasoning"])
    elif kind == "triage":
        card.update(action="candidate_triage", recorder=str(scripts / "annotate_materiality.py"),
                    required_input=["scenario-bound decision", "evidence references"])
    elif kind == "agent_read":
        card.update(action="read_retained_original", required_input=["comparison findings", "evidence references"])
    elif kind == "professional_review":
        action = entry.get("action") if isinstance(entry.get("action"), dict) else {}
        basis = action.get("followup_basis") if isinstance(action.get("followup_basis"), dict) else {}
        card.update(action="obtain_external_professional_review",
            recorder=str(scripts / "record_candidate_followup.py"),
            action_id=entry.get("action_id"), question=action.get("question"),
            evidence_refs=basis.get("existing_evidence_refs", []),
            required_input=["actual external professional opinion if obtained; otherwise the concrete pending dependency",
                "specific claim/drawing question and retained source materials actually provided",
                "resume condition; do not fabricate an opinion or infer a hard source limit"],
            validation="A waiting review preserves needs_info and is not a clearance. When professional evidence becomes available, register it and make a new scoped triage decision.")
    elif kind == "scope_review":
        card.update(action="independent_scope_review", recorder="<first-review.json or second-review.json>",
                    required_input=["frozen evidence digest", "scope assessment", "reviewer and unique session ID",
                                    "execution attestation with agent ID, run ID and assessment digest"],
                    validation="Write the assigned review without seeing the other review; re-run next_work with both reviews.")
    elif kind == 'source_lookup' and entry.get('state') == 'awaiting_review':
        card.update(**{'action':'review_retained_source_obligation',
            'provider':entry.get('provider'),'query_id':entry.get('query_id'),
            'recorders':[str(scripts/name) for name in ('record_source_result_processing.py',
                'record_source_operation.py','annotate_materiality.py','record_candidate_followup.py')],
            'required_input':['exact original query and source-run/evidence references',
                'actual retained material and the reason-specific completion condition',
                'use the applicable existing recorder; preserve missing fields and remaining actions'],
            'validation':'This review card does not submit a source request or assert completion; the original reason-specific gates remain required.'})
    else:
        if kind != "plan_repair":
            raise ValueError("UNKNOWN_AGENT_WORK_KIND: " + str(kind))
        card.update(action="repair_plan", recorder=str(scripts / "generate_search_plan.py"),
                    required_input=["reason-specific evidence or query terms"])
    return card


def action_card_entries(packet: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Group asset fact gathering while retaining every underlying work identity."""
    result = [entry for key in ("agent", "repair", "review") for entry in packet[key]
              if not (key == "agent" and entry.get("provider") == "asset_provenance")]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for entry in packet["agent"]:
        if entry.get("provider") == "asset_provenance":
            groups[(str(entry.get("scenario_id") or ""), str(entry.get("right_type") or ""))].append(entry)
    for entries in groups.values():
        merged = dict(entries[0])
        merged["shared_work_ids"] = [entry.get("work_id") for entry in entries]
        merged["shared_query_ids"] = list(dict.fromkeys(entry.get("query_id") for entry in entries if entry.get("query_id")))
        merged["shared_jurisdictions"] = sorted({str(entry.get("jurisdiction")) for entry in entries if entry.get("jurisdiction")})
        result.append(merged)
    return result


from completion_check import workflow_stage, review_paths, OPTIONAL_INPUTS


_TIMING_KEYS = frozenset({"recorded_at", "observed_at", "started_at", "finished_at", "elapsed_ms",
                          "generated_at", "reviewed_at", "updated_at"})


def _without_timing(value):
    """Drop wall-clock metadata that changes on every run without changing any fact."""
    if isinstance(value, dict):
        return {key: _without_timing(child) for key, child in value.items() if key not in _TIMING_KEYS}
    if isinstance(value, list):
        return [_without_timing(child) for child in value]
    return value


def _progress_facts(evidence: dict[str, Any]) -> dict[str, Any]:
    """Evidence with 08D round bookkeeping replaced by its business-relevant facts.

    Every begin/finish/diagnosis event carries a unique id and timestamp, so
    hashing them would make each dispatch look like progress and reset the
    Stop-hook stall counter even when nothing changed. 08D itself bounds rounds,
    repairs and stops; here only rounds with effective progress, repairs
    (bound to a verified file), technical stops and reopenings count.
    """
    result = {key: value for key, value in evidence.items() if key != "progress_events"}
    facts = []
    for row in evidence.get("progress_events", []):
        if not isinstance(row, dict):
            continue
        kind = row.get("kind")
        if kind == "finish" and row.get("effective_progress"):
            facts.append({"kind": kind, "action_id": row.get("action_id"), "outcome": row.get("outcome")})
        elif kind in {"repair", "technical_stop", "reopen"}:
            facts.append({"kind": kind, "action_id": row.get("action_id"),
                          "evidence_ref": row.get("evidence_ref") or row.get("new_evidence_ref")})
    result["progress_effective_facts"] = facts
    return result


def progress_digest(task_dir: Path, *review_paths: Path | None) -> str:
    evidence = _progress_facts(ensure_object(load_json(task_dir / "evidence.json"), "evidence.json"))
    ledger = load_json(task_dir / "materiality-annotations.json") if (task_dir / "materiality-annotations.json").is_file() else {}
    candidates = load_json(task_dir / "normalized-candidates.json") if (task_dir / "normalized-candidates.json").is_file() else {}
    from decision_workflow import semantic_content
    plan = load_json(task_dir / "search-plan.json") if (task_dir / "search-plan.json").is_file() else {}
    return sha256_json({
        # Count-only tracking missed real obligation changes; semantic hashes
        # intentionally ignore timestamps/capture wrappers but include plan,
        # candidate and ledger facts.
        "evidence": semantic_content(evidence),
        "candidates": semantic_content(candidates),
        "ledger": semantic_content(ledger),
        "plan": semantic_content(plan),
        "task_state": semantic_content({key: value for key, value in load_json(task_dir / "task.json").items() if key not in {"updated_at", "checkpoints", "history"}}),
        "reviews": {str(path): sha256_file(path) for path in review_paths if path and path.is_file()},
        "optional_inputs": {name: semantic_content(_without_timing(load_json(task_dir / name))) if (task_dir / name).is_file() else None
                            for name in OPTIONAL_INPUTS},
    })


def _compact_review_progress(value):
    """Counts and per-scope totals only; the full item ledger stays in continuous-work-status.json."""
    if not isinstance(value, dict):
        return value
    return {key: child for key, child in value.items() if key not in {"items", "history", "by_scope_module"}}


def _compact_stage_risk(value):
    """Headline and counts; judgments, comparisons and facts stay in continuous-work-status.json."""
    if not isinstance(value, dict):
        return value
    overall = value.get("overall") if isinstance(value.get("overall"), dict) else {}
    return {"status": value.get("status"), "judgment_count": len(value.get("judgments", [])),
            "overall": {key: overall[key] for key in ("stage_risk", "risk", "verification_status", "confidence",
                                                      "coverage_ready_for_09C") if key in overall},
            "review_progress": value.get("review_progress"),
            "signal_count": len(value.get("signals", [])),
            "scopes_without_any_judgment": len(value.get("scopes_without_any_judgment", []))}


def _compact_per_work_progress(rows):
    """Only actions that need attention; quiet rounds are in continuous-work-status.json."""
    return [row for row in rows if isinstance(row, dict) and (row.get("diagnosis_required") or row.get("repair_required")
            or row.get("stop_required") or row.get("consecutive_no_progress"))]


def execute_sources(task_dir: Path, plan: dict[str, Any], entries: list[dict[str, Any]], *, admitted_ids=()) -> list[dict[str, Any]]:
    if not entries:
        return []
    from execution_budget import execution_budget
    if not (task_dir / 'task.json').is_file():
        return _execute_sources(task_dir, plan, entries)
    with execution_budget(task_dir, 'sources', admitted_ids=admitted_ids) as deadline:
        return _execute_sources(task_dir, plan, entries, deadline=deadline)


def _execute_sources(task_dir, plan, entries, *, deadline=None):
    index = plan_rows(plan)
    results = []
    batches: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for entry in entries:
        found = index.get(str(entry.get("query_id") or ""))
        if not found:
            results.append({"error": "PLAN_ROW_MISSING", "work_id": entry.get("work_id"), "query_id": entry.get("query_id")})
            continue
        provider, row = found
        runner = "api" if provider in API_PROVIDERS else "browser" if provider.endswith("_browser") or provider == "uspto_tsdr" else ""
        if not runner:
            results.append({"error": "UNSUPPORTED_EXECUTOR", "work_id": entry.get("work_id"), "provider": provider,
                            "query_id": row.get("query_id")})
            continue
        phase = phase_for(row, runner == "browser")
        # The API runner already owns provider/account lanes, quota locks and
        # dependency ordering.  Passing one provider per subprocess disabled
        # that safe cross-provider concurrency.  Browser routes remain split
        # because their interactive sessions are intentionally serialized.
        batch_provider = provider if runner == "browser" else "*"
        batches[(runner, batch_provider, phase)].append(row["query_id"])
    root = Path(__file__).resolve().parent
    for (runner, provider, phase), ids in sorted(batches.items()):
        script = root / ("run_api_plan.py" if runner == "api" else "run_browser_plan.py")
        command = [sys.executable, str(script), "--task-dir", str(task_dir), "--query-ids", *ids, "--phase", phase,
                   *(["--skip-final-view"] if runner == "api" else [])]
        if deadline is None:
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
        else:
            from execution_budget import run_bounded, child_environment, remaining
            try:
                remaining(deadline, 1800)
                completed = run_bounded(command, deadline=deadline, timeout=1800,
                    text=True, encoding='utf-8', env=child_environment(task_dir, deadline))
            except (subprocess.TimeoutExpired, ValueError) as exc:
                results.append({'runner': runner, 'provider': provider, 'phase': phase, 'query_ids': ids,
                    'returncode': 2, 'error_code': 'EXECUTION_TIME_BUDGET_EXHAUSTED',
                    'detail': str(exc), 'incomplete': True})
                break
        results.append({"runner": runner, "provider": provider, "phase": phase, "query_ids": ids,
                        "returncode": completed.returncode, "stdout": completed.stdout[-1200:], "stderr": completed.stderr[-1200:]})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--guard-session-id", help="Actual Codex session ID; update explicit review/output locations")
    parser.add_argument("--execute-sources", action="store_true", help="Run exact ready API/browser rows and emit remaining Agent action cards")
    parser.add_argument("--write-agent-packet", action="store_true", help="Persist recorder-bound Agent action cards")
    parser.add_argument("--output-format", choices=("compact", "full"), default="compact",
                        help="Print a compact dispatcher summary by default; full preserves the historical JSON output")
    parser.add_argument("--first-review", type=Path)
    parser.add_argument("--second-review", type=Path)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--output-dir", type=Path, help="New report directory; never the task directory")
    parser.add_argument("--deliver-to", type=Path,
                        help="With --publish: also freeze, deliver and check completion into this NEW entry directory")
    parser.add_argument("--publish", action="store_true", help="Publish only after all work and both reviews are accepted")
    parser.add_argument("--require-complete", action="store_true", help="Exit non-zero unless the verified report bundle exists")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    # Share completion_check's documented default filenames; only select an
    # existing file so initial source work still runs before reviews are written.
    for key, path in zip(("first_review", "second_review", "adjudication"),
                        review_paths(task_dir, args.first_review, args.second_review, args.adjudication)):
        if getattr(args, key) is None and path.is_file():
            setattr(args, key, path)
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    if task.get("execution_policy_revision") not in {"continuous-work-v1", "continuous-work-v2"}:
        raise ValueError("CONTINUOUS_WORK_POLICY_NOT_ENABLED: historical tasks retain their frozen behavior")
    from codex_guard import register_if_requested
    register_if_requested(args.guard_session_id, task_dir, output_dir=args.output_dir,
        first_review=args.first_review, second_review=args.second_review, adjudication=args.adjudication)
    if args.execute_sources and task.get("continuous_progress_revision"):
        # Close rounds a previously interrupted dispatch left open, before the work view is derived:
        # an open begin would otherwise fail every later begin with PROGRESS_ACTIONABLE_ROUND_REQUIRED.
        from continuous_progress_stage_d import recover_interrupted_rounds
        recover_interrupted_rounds(task_dir, "advance_work")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json") if (task_dir/"search-plan.json").is_file() else {}
    first = load_json(args.first_review) if args.first_review else None
    second = load_json(args.second_review) if args.second_review else None
    before = work_view_from_dir(task_dir, first_review=first, second_review=second)
    from execution_budget import snapshot as budget_snapshot
    runtime_budget = budget_snapshot(task_dir)
    source_entries, defer_sources = source_entries_after_triage_priority(task, before)
    if runtime_budget and runtime_budget['stop_reason']:
        source_entries = []
    from execution_budget import policy as budget_policy
    limits = budget_policy(task)
    if limits and task.get('continuous_progress_revision'):
        existing = load_json(task_dir / 'evidence.json').get('progress_events', [])
        available = max(0, min(
            limits['max_action_rounds'] - sum(r.get('kind') == 'begin' for r in existing),
            limits['max_no_progress_rounds'] - sum(r.get('kind') == 'finish' and r.get('effective_progress') is False for r in existing)))
        allowed = list(dict.fromkeys(row.get('linked_action_id') for row in source_entries))[:available]
        source_entries = [row for row in source_entries if row.get('linked_action_id') in allowed]
    progress_rounds = []
    if args.execute_sources and source_entries and task.get("continuous_progress_revision"):
        from continuous_progress_stage_d import record_events as record_progress_events
        seen_actions = set()
        begin_requests = []
        for entry in source_entries:
            action_id = entry.get("linked_action_id")
            if action_id in seen_actions:
                continue
            seen_actions.add(action_id)
            begin_requests.append({"kind": "begin", "work_id": entry["work_id"],
                "actor": "advance_work", "reasoning": "Dispatch the exact ready source action"})
        # One evidence load/write and one work view for the whole dispatch instead of one per action.
        progress_rounds = record_progress_events(task_dir, begin_requests) if begin_requests else []
    try:
        source_results = execute_sources(task_dir, plan, source_entries, admitted_ids=[row['event_id'] for row in progress_rounds]) if args.execute_sources and source_entries else []
    except ValueError as exc:
        if not str(exc).startswith('EXECUTION_'):
            raise
        source_results = [{'code': str(exc), 'incomplete': True, 'not_submitted': True}]
    if progress_rounds:
        from continuous_progress_stage_d import record_events as record_progress_events
        record_progress_events(task_dir, [{"kind": "finish", "begin_id": begin["event_id"],
            "actor": "advance_work", "reasoning": "Reviewed original source dispatch outcome",
            "action_taken": "execute_exact_ready_source"} for begin in progress_rounds])
    # No source execution means no task input changed between these points.
    # Reuse the frozen view instead of loading and deriving the full workflow a
    # second time.  Executed batches are always followed by a fresh derivation.
    after = work_view_from_dir(task_dir, first_review=first, second_review=second) if source_results else before
    packet = actionable_packet(after)
    packet["action_cards"] = [action_card(task_dir, entry) for entry in action_card_entries(packet)]
    stage = workflow_stage(after, packet, first_review=args.first_review, second_review=args.second_review,
                           adjudication=args.adjudication, output_dir=args.output_dir, task_dir=task_dir)
    runtime_budget = budget_snapshot(task_dir)
    if runtime_budget and runtime_budget['stop_reason'] and packet['source']:
        stage = 'execution_stopped'
    elif runtime_budget and runtime_budget['stop_reason'] and stage == 'investigation' and not any(
            packet[key] for key in ('agent', 'repair', 'review')):
        stage = 'execution_stopped'
    elif runtime_budget and runtime_budget['review_remaining_seconds'] <= 0 and stage == 'independent_review':
        stage = 'execution_stopped'
    publication = None
    if args.publish:
        if stage != "publication":
            raise ValueError("PUBLISH_REQUIRES_COMPLETED_WORK_AND_DUAL_REVIEW: current stage=" + stage)
        if args.output_dir is None or args.output_dir.resolve() == task_dir:
            raise ValueError("PUBLISH_REQUIRES_NEW_OUTPUT_DIRECTORY")
        from publish_report import publish
        delivery_options = ({"deliver_to": args.deliver_to, "require_complete": args.require_complete}
                            if args.deliver_to else {})
        publication = publish(task_dir, args.first_review, args.second_review, adjudication=args.adjudication,
                              output_dir=args.output_dir, mode="auto", **delivery_options)
        # Without --deliver-to a new task has only a verified build here and
        # explicit entry delivery remains a separate step. With it, the
        # transaction already re-ran the completion check at the actual entry.
        # Historical tasks preserve their contract.  A separately invoked
        # completion check (and the stop hook) still revalidates from source.
        completion = publication.get("completion") or {}
        stage = (completion.get("stage") or "validation") if completion else \
            "delivery" if publication.get("build_only") else "complete" if publication.get("delivery_status") == "completed" else "validation"
    current_progress = progress_digest(task_dir, args.first_review, args.second_review, args.adjudication)
    status_path = task_dir / "continuous-work-status.json"
    prior = load_json(status_path) if status_path.is_file() else {}
    unchanged = int(prior.get("consecutive_no_progress") or 0) + 1 if prior.get("progress_digest") == current_progress else 0
    status = {
        "schema": "IPR-CONTINUOUS-WORK/1.0", "task_id": task["task_id"], "updated_at": now_iso(),
        "progress_digest": current_progress, "consecutive_no_progress": unchanged,
        "work_status": after.get("status"), "stage": stage, "counts": after.get("counts", {}), "source_batches": source_results,
        "publication": publication,
        "packet": packet,
        "invalidated_reviews": after.get("invalidated_reviews", []),
    }
    if runtime_budget:
        status['execution_budget'] = runtime_budget
    if task.get("continuous_progress_revision"):
        # A dispatcher invocation is not a work round. The 08D recorder owns
        # per-action attempts and evidence-bound outcomes.
        status["per_work_progress"] = after.get("per_work_progress", [])
        status["technical_stops"] = after.get("technical_stops", [])
        status["consecutive_no_progress"] = None
    if task.get("review_progress_revision"):
        status["review_progress"] = after.get("review_progress")
    if after.get("actual_query_execution_progress") is not None:
        status["actual_query_execution_progress"] = after["actual_query_execution_progress"]
    if task.get("stage_risk_revision"):
        status["stage_risk"] = after.get("stage_risk")
    if defer_sources:
        status["source_dispatch_deferred"] = "ACQUIRED_CANDIDATE_LIGHT_TRIAGE_FIRST"
    if not task.get("continuous_progress_revision") and unchanged >= 2 and (packet["source"] or packet["agent"] or packet["repair"] or packet["review"]):
        status["no_progress_diagnosis"] = {
            "kind": "internal_follow_up_required",
            "detail": "Two advances produced no new source run, evidence, candidate, or triage decision. Inspect the listed repair/Agent actions; do not relabel them as an external source limitation.",
            "work_ids": [entry.get("work_id") for key in ("source", "agent", "repair", "review") for entry in packet[key]],
        }
    atomic_write_json(status_path, status)
    if args.write_agent_packet:
        atomic_write_json(task_dir / "agent-work-packet.json", {"schema": "IPR-AGENT-ACTIONS/1.0",
            "task_id": task["task_id"], "generated_at": status["updated_at"], "actions": packet["action_cards"]})
    if args.output_format == "full":
        printable = status
    else:
        current_keys = (("source", "agent", "repair") if stage == "investigation"
                        else ("review",) if stage == "independent_review" else ())
        compact_entries = action_card_entries({**packet,
            "agent": packet["agent"] if "agent" in current_keys else [],
            "repair": packet["repair"] if "repair" in current_keys else [],
            "review": packet["review"] if "review" in current_keys else []})
        compact_actions = ([{"work_id": item.get("work_id"), "action": "execute_ready_source",
                             "scope": {key: item.get(key) for key in ("scenario_id", "jurisdiction", "right_type", "query_id") if item.get(key)},
                             "reason": item.get("reason")} for item in packet["source"]]
                           if "source" in current_keys else [])
        for item in compact_entries:
            card = action_card(task_dir, item)
            compact_actions.append({
                "work_id": item.get("work_id"), "action": card.get("action"),
                "scope": {key: item.get(key) for key in
                          ("scenario_id", "jurisdiction", "right_type", "candidate_id", "query_id") if item.get(key)},
                "reason": item.get("reason"),
                **({"work_ids": card["work_ids"], "query_ids": card["query_ids"],
                    "jurisdictions": card.get("jurisdictions", [])} if card.get("work_ids") else {}),
            })
        printable = {
            "schema": status["schema"], "task_id": status["task_id"], "updated_at": status["updated_at"],
            "work_status": status["work_status"], "stage": status["stage"], "counts": status["counts"],
            "actions": compact_actions,
            "waiting": [{"work_id": item.get("work_id"), "state": item.get("state"), "kind": item.get("kind"),
                         "reason": item.get("reason")} for item in packet["waiting"]],
            "details_file": str(status_path),
            **({'execution_budget': runtime_budget} if runtime_budget else {}),
            **({"per_work_progress": _compact_per_work_progress(status["per_work_progress"]),
                "technical_stops": status["technical_stops"]} if task.get("continuous_progress_revision") else {}),
            **({"review_progress": _compact_review_progress(status["review_progress"])} if task.get("review_progress_revision") else {}),
            **({"actual_query_execution_progress": _compact_review_progress(status["actual_query_execution_progress"])}
               if "actual_query_execution_progress" in status else {}),
            **({"stage_risk": _compact_stage_risk(status["stage_risk"])} if task.get("stage_risk_revision") else {}),
            **({"agent_packet_file": str(task_dir / "agent-work-packet.json")} if args.write_agent_packet else {}),
            **({"publication": publication} if publication else {}),
            **({"no_progress_diagnosis": status["no_progress_diagnosis"]} if status.get("no_progress_diagnosis") else {}),
        }
    # Auxiliary progress is only a CLI projection. It is never saved to the
    # canonical work view, status digest, evidence or review inputs.
    output = {**printable, "runtime_progress": progress_view(task_dir, after, stage_hint=stage)}
    print(json.dumps(output, ensure_ascii=False, indent=2) if args.output_format == "full"
          else json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    if args.require_complete and stage not in {"complete", "limited_round_closed"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

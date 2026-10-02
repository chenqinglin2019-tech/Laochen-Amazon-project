"""09C: frozen stage batches, authenticated independent reviews and chief decisions."""
from __future__ import annotations

import hashlib
import hmac
import os
from copy import deepcopy
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_file, sha256_json
from review_progress_stage_a import ledger
from stage_risk_stage_b import RISKS, _registry as evidence_registry, snapshot as risk_snapshot

REVISION = "stage-review-stage-c-v1"
TRIGGERS = {"deliverable_batch", "user_stage_request", "wait_or_stop", "pre_delivery", "material_invalidation"}
BUSINESS_SCOPE = ("scenario_id", "jurisdiction", "right_type", "product_version")
COVERAGE_SUBJECTS = {"necessary_directions", "excluded_candidates", "unreviewed_material", "unresolved_scopes"}


def enabled(task: dict) -> bool:
    from final_review import enabled as final_enabled
    if final_enabled(task):
        return False
    value = task.get("stage_review_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("STAGE_REVIEW_REVISION_INVALID")
    return True


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _events(evidence: dict) -> list[dict]:
    rows = evidence.get("stage_review_events", [])
    if not isinstance(rows, list):
        raise ValueError("STAGE_REVIEW_EVENTS_INVALID")
    previous = ""
    for number, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or row.get("version") != number or
                row.get("previous_event_id") != previous or
                row.get("event_id") != "STAGE-REVIEW-" + sha256_json({
                    "task_id": evidence.get("task_id"), "event": {k: v for k, v in row.items() if k != "event_id"}})[:24]):
            raise ValueError("STAGE_REVIEW_EVENT_CHAIN_INVALID")
        previous = row["event_id"]
    return rows


def _batch(rows: list[dict], batch_id: str) -> dict:
    result = next((row for row in rows if row.get("kind") == "freeze" and row["event_id"] == batch_id), None)
    if result is None:
        raise ValueError("STAGE_REVIEW_BATCH_UNKNOWN")
    return result


def export_batch_input(task_dir: Path, batch_id: str) -> dict:
    task = load_json(Path(task_dir) / "task.json")
    evidence = load_json(Path(task_dir) / "evidence.json")
    if not enabled(task) or evidence.get("task_id") != task.get("task_id"):
        raise ValueError("STAGE_REVIEW_TASK_MISMATCH")
    batch = _batch(_events(evidence), batch_id)
    _assert_current(task, evidence, batch, Path(task_dir))
    return {"schema": "IPR-STAGE-REVIEW-INPUT/1.0", "task_id": task["task_id"],
        "batch_id": batch_id, "evidence_digest": batch["evidence_digest"],
        "scope": deepcopy(batch["scope"]), "items": deepcopy(batch["items"]),
        "coverage": deepcopy(batch["coverage"]), "coverage_notes": deepcopy(batch["coverage_notes"]),
        "source_facts": deepcopy(batch["source_facts"]),
        "candidate_inventory": deepcopy(batch["candidate_inventory"]),
        "unjudged_candidate_ids": deepcopy(batch["unjudged_candidate_ids"]),
        "missing_source_refs": deepcopy(batch["missing_source_refs"]),
        "product_snapshot": deepcopy(batch["product_snapshot"]),
        "scenario_snapshot": deepcopy(batch["scenario_snapshot"]),
        "reuse": deepcopy(batch["reuse"])}


def _reviews(rows: list[dict], batch_id: str) -> list[dict]:
    return [row for row in rows if row.get("kind") == "review" and row.get("batch_id") == batch_id]


def _candidate_inventory(task_dir: Path, scope: dict) -> list[dict]:
    path = Path(task_dir) / "normalized-candidates.json"
    if not path.is_file():
        return []
    from annotate_materiality import iter_candidates
    inventory = []
    for provider, candidate in iter_candidates(load_json(path)):
        if candidate.get("right_type") != scope.get("right_type"):
            continue
        if not _text(candidate.get("candidate_id")):
            raise ValueError("STAGE_REVIEW_CANDIDATE_IDENTITY_REQUIRED")
        inventory.append({"provider": provider, "candidate_id": candidate["candidate_id"],
                          "candidate_sha256": sha256_json(candidate),
                          "jurisdiction": candidate.get("jurisdiction"),
                          "title": candidate.get("title")})
    return sorted(inventory, key=lambda row: (row["candidate_id"], row["provider"]))


def _assert_current(task: dict, evidence: dict, batch: dict, task_dir: Path | None = None) -> None:
    current, coverage = _current_items(task, evidence, batch["scope"], task_dir)
    if (set(current) != set(batch["items"]) or
            any(sha256_json(current[key]) != digest for key, digest in batch["item_digests"].items()) or
            {tuple(row[k] for k in BUSINESS_SCOPE) for row in coverage["scope"]} !=
            {tuple(row[k] for k in BUSINESS_SCOPE) for row in batch["coverage"]["scope"]} or
            {tuple(row[k] for k in BUSINESS_SCOPE) for row in coverage["unreviewed"]} !=
            {tuple(row[k] for k in BUSINESS_SCOPE) for row in batch["coverage"]["unreviewed"]} or
            (task_dir is not None and _candidate_inventory(task_dir, batch["scope"]) != batch["candidate_inventory"])):
        raise ValueError("STAGE_REVIEW_FROZEN_INPUT_STALE")


def _current_items(task: dict, evidence: dict, scope: dict,
                   task_dir: Path | None = None) -> tuple[dict, dict]:
    progress = ledger(task, evidence)
    risk = risk_snapshot(task, evidence, progress, task_dir)
    items = {}
    for row in [*risk.get("judgments", []), *risk.get("signals", [])]:
        item_scope = row.get("scope", {})
        if all(item_scope.get(k) == scope.get(k) for k in BUSINESS_SCOPE if k != "right_type") and (
                item_scope.get("right_type") in (None, "", scope.get("right_type"))):
            items[row["event_id"]] = row
    matching = [row for row in progress.get("by_scope", []) if all(
        row.get(k) == scope.get(k) for k in BUSINESS_SCOPE)]
    reviewed = {tuple(row["scope"].get(k) for k in BUSINESS_SCOPE) for row in risk.get("judgments", [])
                if row.get("applicability") == "current"}
    unreviewed = [row for row in matching if tuple(row.get(k) for k in BUSINESS_SCOPE) not in reviewed]
    return items, {"plan_version": progress.get("plan_version"), "scope": matching,
                   "unreviewed": unreviewed}


def _freeze(task: dict, evidence: dict, request: dict, rows: list[dict], candidate_inventory: list[dict] | None = None,
            task_dir: Path | None = None) -> dict:
    scope = request.get("scope")
    if not isinstance(scope, dict) or any(not _text(scope.get(k)) for k in BUSINESS_SCOPE):
        raise ValueError("STAGE_REVIEW_SCOPE_REQUIRED")
    if request.get("trigger") not in TRIGGERS or not _text(request.get("trigger_reasoning")):
        raise ValueError("STAGE_REVIEW_TRIGGER_REQUIRED")
    items, coverage = _current_items(task, evidence, scope, task_dir)
    if not coverage["scope"]:
        raise ValueError("STAGE_REVIEW_DEFINED_PLAN_SCOPE_REQUIRED")
    ids = request.get("item_ids")
    if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or set(ids) != set(items):
        raise ValueError("STAGE_REVIEW_ALL_CURRENT_ITEMS_REQUIRED")
    notes = request.get("coverage_notes")
    if (not isinstance(notes, list) or len(notes) != len(COVERAGE_SUBJECTS) or
            {row.get("subject") for row in notes if isinstance(row, dict)} != COVERAGE_SUBJECTS or
            any(not isinstance(row, dict) or
                not all(_text(row.get(k)) for k in ("subject", "disposition", "reasoning")) for row in notes)):
        raise ValueError("STAGE_REVIEW_COVERAGE_AND_EXCLUSIONS_REQUIRED")
    if coverage["unreviewed"] and not any(row["subject"] == "unreviewed_material" and
            row["disposition"] == "unreviewed" for row in notes):
        raise ValueError("STAGE_REVIEW_UNREVIEWED_SCOPE_UNDISCLOSED")
    invalidation_id = request.get("invalidation_id")
    if request["trigger"] == "material_invalidation":
        invalidation = next((row for row in evidence.get("stage_risk_events", []) if
            row.get("event_id") == invalidation_id and row.get("kind") == "invalidate"), None)
        if not invalidation or any(invalidation["scope"].get(k) != scope[k] for k in BUSINESS_SCOPE) or \
                invalidation.get("judgment_id") not in items:
            raise ValueError("STAGE_REVIEW_INVALIDATION_REQUIRED")
    elif invalidation_id:
        raise ValueError("STAGE_REVIEW_INVALIDATION_TRIGGER_REQUIRED")
    reuse = request.get("reuse", {})
    if not isinstance(reuse, dict) or not set(reuse) <= set(items):
        raise ValueError("STAGE_REVIEW_REUSE_INVALID")
    for item_id, prior_batch_id in reuse.items():
        prior = _batch(rows, prior_batch_id)
        if (not any(row.get("kind") == "adjudicate" and row.get("batch_id") == prior_batch_id and
                    row.get("status") == "complete" for row in rows) or
                prior["item_digests"].get(item_id) != sha256_json(items[item_id])):
            raise ValueError("STAGE_REVIEW_REUSE_UNPROVEN")
    frozen = {item_id: deepcopy(items[item_id]) for item_id in sorted(items)}
    candidate_inventory = candidate_inventory or []
    judged_ids = {row.get("scope", {}).get("candidate_id") for row in frozen.values()}
    unjudged_ids = sorted({row["candidate_id"] for row in candidate_inventory} - judged_ids)
    excluded_note = next(row for row in notes if row["subject"] == "excluded_candidates")
    if unjudged_ids and (excluded_note.get("candidate_ids") != unjudged_ids or
                          excluded_note["disposition"] not in {"excluded", "unreviewed", "not_applicable"}):
        raise ValueError("STAGE_REVIEW_UNJUDGED_CANDIDATES_UNEXPLAINED")
    required_refs = {ref for row in frozen.values() for field in ("evidence_refs", "outcome_refs")
                     for ref in row.get(field, [])}
    registry = evidence_registry(task, evidence, task_dir)
    from delivery_inspection_stage_d import enabled as inspection_enabled, dependency_refs
    if inspection_enabled(task):
        required_refs.update(dependency_refs(registry, sorted(required_refs)))
    missing_refs = sorted(required_refs - set(registry))
    scenario = next((row for row in task.get("assessment_scenarios", []) if
                     row.get("scenario_id") == scope["scenario_id"]), None)
    payload = {"scope": deepcopy(scope), "trigger": request["trigger"],
        "trigger_reasoning": request["trigger_reasoning"], "invalidation_id": invalidation_id,
        "items": frozen, "item_digests": {key: sha256_json(value) for key, value in frozen.items()},
        "coverage": coverage, "coverage_notes": deepcopy(notes), "reuse": deepcopy(reuse),
        "candidate_inventory": deepcopy(candidate_inventory), "unjudged_candidate_ids": unjudged_ids,
        "source_facts": {ref: deepcopy(registry[ref]) for ref in sorted(required_refs & set(registry))},
        "missing_source_refs": missing_refs,
        "product_snapshot": deepcopy(task.get("product", {})),
        "scenario_snapshot": deepcopy(scenario),
        "stage_risk_cutoff": len(evidence.get("stage_risk_events", [])),
        "evidence_cutoff": len(evidence.get("source_runs", [])),
        "product_digest": sha256_json(task.get("product", {}))}
    payload["evidence_digest"] = sha256_json(payload)
    return payload


def _receipt(request: dict, batch: dict, prior: list[dict]) -> dict:
    receipt = request.get("isolation_receipt")
    if not isinstance(receipt, dict) or any(not _text(receipt.get(k)) for k in (
            "host", "run_id", "session_id", "agent_id", "reviewer", "workspace_id",
            "audit_log_path", "audit_log_sha256")):
        raise ValueError("STAGE_REVIEW_HOST_ISOLATION_RECEIPT_REQUIRED")
    if (receipt.get("input_digest") != batch["evidence_digest"] or
            receipt.get("first_review_visible") is not False or
            receipt.get("visible_review_ids") != [] or
            receipt.get("read_review_ids") != [] or
            receipt.get("output_created_after_isolation") is not True or
            receipt.get("task_directory_mounted") is not False):
        raise ValueError("STAGE_REVIEW_INPUT_FORK_OR_LEAK")
    if any(any(receipt[k] == old["isolation_receipt"][k] for k in (
            "reviewer", "session_id", "agent_id", "run_id", "workspace_id")) for old in prior):
        raise ValueError("STAGE_REVIEW_REVIEWER_OR_WORKSPACE_REUSED")
    log_path = Path(receipt["audit_log_path"])
    if not log_path.is_absolute() or not log_path.is_file() or sha256_file(log_path) != receipt["audit_log_sha256"]:
        raise ValueError("STAGE_REVIEW_AUDIT_LOG_MISSING_OR_CHANGED")
    log = load_json(log_path)
    if (not isinstance(log, dict) or log.get("workspace_id") != receipt["workspace_id"] or
            log.get("input_digest") != batch["evidence_digest"] or
            log.get("mounted_artifacts") != ["frozen_input"] or
            log.get("read_artifacts") != ["frozen_input"] or
            log.get("task_directory_mounted") is not False):
        raise ValueError("STAGE_REVIEW_AUDIT_LOG_SHOWS_FORK_OR_LEAK")
    key = os.environ.get("LC_IPR_REVIEW_HOST_KEY")
    signature = receipt.get("host_hmac_sha256")
    unsigned = {k: v for k, v in receipt.items() if k != "host_hmac_sha256"}
    if not key or not _text(signature) or not hmac.compare_digest(
            hmac.new(key.encode(), sha256_json(unsigned).encode(), hashlib.sha256).hexdigest(), signature):
        raise ValueError("STAGE_REVIEW_HOST_ATTESTATION_INVALID")
    return deepcopy(receipt)


def _review(request: dict, batch: dict, prior: list[dict]) -> dict:
    if len(prior) >= 2:
        raise ValueError("STAGE_REVIEW_TWO_REVIEWS_ALREADY_SUBMITTED")
    if request.get("evidence_digest") != batch["evidence_digest"]:
        raise ValueError("STAGE_REVIEW_DIGEST_MISMATCH")
    receipt = _receipt(request, batch, prior)
    items = request.get("items")
    expected = set(batch["items"]) - set(batch["reuse"])
    if not isinstance(items, dict) or set(items) != expected:
        raise ValueError("STAGE_REVIEW_ITEM_COVERAGE_INCOMPLETE")
    for item_id, item in items.items():
        frozen = batch["items"][item_id]
        if (not isinstance(item, dict) or not _text(item.get("reasoning")) or
                not isinstance(item.get("evidence_refs"), list) or
                not set(item["evidence_refs"]) <= (
                    (set(frozen.get("evidence_refs", [])) | set(frozen.get("outcome_refs", []))) &
                    set(batch["source_facts"])) or
                not isinstance(item.get("gaps"), list) or any(not isinstance(gap, dict) or
                    not all(_text(gap.get(k)) for k in ("missing_fact", "impact", "minimal_action"))
                    for gap in item.get("gaps", [])) or not _text(item.get("comparison"))):
            raise ValueError("STAGE_REVIEW_REASONING_OR_FROZEN_REFS_REQUIRED")
        if frozen.get("kind") == "signal_review":
            if item.get("stage_risk") is not None or not _text(item.get("signal_conclusion")):
                raise ValueError("STAGE_REVIEW_SIGNAL_SEPARATE_REQUIRED")
        elif item.get("stage_risk") not in RISKS:
            raise ValueError("STAGE_REVIEW_GRADE_INVALID")
    coverage = request.get("coverage")
    if not isinstance(coverage, dict) or set(coverage) != {"plan", "unreviewed", "exclusions", "limitations"} or \
            any(not _text(value) for value in coverage.values()):
        raise ValueError("STAGE_REVIEW_COVERAGE_REASONING_REQUIRED")
    return {"batch_id": batch["event_id"], "evidence_digest": batch["evidence_digest"],
            "isolation_receipt": receipt, "items": deepcopy(items), "coverage": deepcopy(coverage),
            "reviewer": receipt["reviewer"], "review_number": len(prior) + 1,
            "review_sha256": sha256_json({"items": items, "coverage": coverage})}


def _adjudicate(request: dict, batch: dict, reviews: list[dict], rows: list[dict]) -> dict:
    if len(reviews) != 2 or any(row.get("kind") == "adjudicate" and row.get("batch_id") == batch["event_id"] for row in rows):
        raise ValueError("STAGE_REVIEW_TWO_VALID_REVIEWS_REQUIRED")
    for index, review in enumerate(reviews):
        _receipt({"isolation_receipt": review["isolation_receipt"]}, batch, reviews[:index])
    refs = request.get("review_refs")
    if refs != [{"event_id": row["event_id"], "sha256": row["review_sha256"]} for row in reviews]:
        raise ValueError("STAGE_REVIEW_REVIEW_FINGERPRINT_MISMATCH")
    decisions = request.get("decisions")
    expected = set(batch["items"]) - set(batch["reuse"])
    if not isinstance(decisions, dict) or set(decisions) != expected:
        raise ValueError("STAGE_REVIEW_CHIEF_COVERAGE_INCOMPLETE")
    supplements = []
    missing = set(batch.get("missing_source_refs", []))
    if any(missing & (set(batch["items"][item_id].get("evidence_refs", [])) |
                      set(batch["items"][item_id].get("outcome_refs", []))) and
           (not isinstance(decision, dict) or decision.get("status") != "needs_supplement")
           for item_id, decision in decisions.items()):
        raise ValueError("STAGE_REVIEW_MISSING_SOURCE_REQUIRES_SUPPLEMENT")
    for item_id in expected:
        first, second = (row["items"][item_id] for row in reviews)
        decision = decisions[item_id]
        if not isinstance(decision, dict) or not _text(decision.get("reasoning")) or not _text(decision.get("fact_basis")):
            raise ValueError("STAGE_REVIEW_CHIEF_FACT_REASONING_REQUIRED")
        conflict = any(first.get(key) != second.get(key) for key in (
            "stage_risk", "signal_conclusion", "evidence_refs", "comparison", "gaps", "reasoning"))
        if decision.get("conflict") is not conflict:
            raise ValueError("STAGE_REVIEW_CONFLICT_NOT_LOCATED")
        if decision.get("status") == "needs_supplement":
            gap = decision.get("gap")
            if not isinstance(gap, dict) or not all(_text(gap.get(k)) for k in (
                    "missing_fact", "impact", "minimal_action", "responsible_step")):
                raise ValueError("STAGE_REVIEW_MINIMAL_SUPPLEMENT_REQUIRED")
            supplements.append({"item_id": item_id, **deepcopy(gap)})
        elif decision.get("status") == "resolved":
            if batch["items"][item_id].get("kind") == "signal_review":
                if decision.get("signal_conclusion") not in {first.get("signal_conclusion"), second.get("signal_conclusion")}:
                    raise ValueError("STAGE_REVIEW_SIGNAL_DECISION_REQUIRED")
            elif decision.get("stage_risk") not in {first.get("stage_risk"), second.get("stage_risk")} or \
                    decision.get("stage_risk") not in RISKS:
                raise ValueError("STAGE_REVIEW_GRADE_MUST_HAVE_FACTUAL_BASIS")
            chosen = decision.get("stage_risk")
            frozen = batch["items"][item_id]
            if chosen in {"高", "极高"} and (frozen.get("verification_status") != "verified" or
                    not frozen.get("scope", {}).get("candidate_id") or frozen.get("right_state") != "active" or
                    not frozen.get("right_state_evidence_refs") or
                    (chosen == "极高" and frozen.get("important_exclusions_checked") is not True)):
                raise ValueError("STAGE_REVIEW_HIGH_GRADE_REQUIRES_09B_FACTS")
            if chosen == "极低" and (frozen.get("verification_status") != "verified" or
                    frozen.get("basis") != "decisive_exclusion" or frozen.get("scope_complete") is not True or
                    not frozen.get("decisive_exclusion_refs")):
                raise ValueError("STAGE_REVIEW_VERY_LOW_REQUIRES_09B_EXCLUSION")
        else:
            raise ValueError("STAGE_REVIEW_CHIEF_DECISION_REQUIRED")
    if not _text(request.get("coverage_reasoning")) or not _text(request.get("chief_reviewer")):
        raise ValueError("STAGE_REVIEW_CHIEF_COVERAGE_REASONING_REQUIRED")
    if request["chief_reviewer"] in {row["reviewer"] for row in reviews}:
        raise ValueError("STAGE_REVIEW_CHIEF_MUST_BE_DISTINCT")
    return {"batch_id": batch["event_id"], "evidence_digest": batch["evidence_digest"],
            "review_refs": deepcopy(refs), "decisions": deepcopy(decisions),
            "coverage_reasoning": request["coverage_reasoning"],
            "chief_reviewer": request["chief_reviewer"],
            "status": "needs_supplement" if supplements else "complete", "supplements": supplements}


def record_event(task_dir: Path, request: dict) -> dict:
    from provider_utils import evidence_lock
    task_dir = Path(task_dir)
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        evidence = load_json(task_dir / "evidence.json")
        if not enabled(task) or evidence.get("task_id") != task.get("task_id"):
            raise ValueError("STAGE_REVIEW_TASK_MISMATCH")
        rows = _events(evidence)
        if not isinstance(request, dict) or not _text(request.get("actor")):
            raise ValueError("STAGE_REVIEW_ACTOR_REQUIRED")
        kind = request.get("kind")
        if kind == "freeze":
            requested_scope = request.get("scope") if isinstance(request.get("scope"), dict) else {}
            payload = _freeze(task, evidence, request, rows, _candidate_inventory(task_dir, requested_scope), task_dir)
        else:
            batch = _batch(rows, request.get("batch_id"))
            _assert_current(task, evidence, batch, task_dir)
            prior = _reviews(rows, batch["event_id"])
            if kind == "review":
                payload = _review(request, batch, prior)
            elif kind == "adjudicate":
                payload = _adjudicate(request, batch, prior, rows)
            else:
                raise ValueError("STAGE_REVIEW_KIND_INVALID")
        event = {"kind": kind, **payload, "actor": request["actor"],
                 "recorded_at": now_iso(), "version": len(rows) + 1,
                 "previous_event_id": rows[-1]["event_id"] if rows else ""}
        event["event_id"] = "STAGE-REVIEW-" + sha256_json({"task_id": task["task_id"], "event": event})[:24]
        evidence.setdefault("stage_review_events", []).append(event)
        atomic_write_json(task_dir / "evidence.json", evidence)
        return event


def supplement_entries(task: dict, evidence: dict | None) -> list[dict]:
    if not enabled(task) or not evidence:
        return []
    rows = _events(evidence)
    result = []
    for event in rows:
        if event["kind"] != "adjudicate" or event["status"] != "needs_supplement":
            continue
        batch = _batch(rows, event["batch_id"])
        for gap in event["supplements"]:
            newer = any(row["kind"] == "freeze" and row["version"] > event["version"] and
                        any(item.get("prior_judgment_id") == gap["item_id"] for item in row.get("items", {}).values()) and
                        any(chief["kind"] == "adjudicate" and chief.get("batch_id") == row["event_id"] and
                            chief.get("status") == "complete" for chief in rows)
                        for row in rows)
            if newer:
                continue
            result.append({"work_id": "WORK-" + sha256_json({"chief": event["event_id"], "item": gap["item_id"]})[:24],
                "gap_event_id": event["event_id"], "kind": "agent_investigation", "state": "awaiting_review",
                "reason": "STAGE_REVIEW_MINIMAL_SUPPLEMENT", "question": gap["missing_fact"],
                "completion_condition": gap["minimal_action"], "impact": gap["impact"],
                "responsible_step": gap["responsible_step"], "stage_item_id": gap["item_id"],
                **{key: batch["scope"][key] for key in BUSINESS_SCOPE}})
    return result


def project(task: dict, view: dict, evidence: dict | None, task_dir: Path | None = None) -> dict:
    if not enabled(task) or evidence is None:
        return view
    result = deepcopy(view)
    rows = _events(evidence)
    risk = result.get("stage_risk", {})
    latest = {}
    for event in rows:
        if event["kind"] == "freeze":
            latest[tuple(event["scope"][k] for k in BUSINESS_SCOPE)] = event
    batches = []
    for batch in latest.values():
        reviews = _reviews(rows, batch["event_id"])
        chief = next((row for row in rows if row["kind"] == "adjudicate" and row["batch_id"] == batch["event_id"]), None)
        try:
            _assert_current(task, evidence, batch, task_dir)
            stale = False
        except ValueError as exc:
            if str(exc) != "STAGE_REVIEW_FROZEN_INPUT_STALE":
                raise
            stale = True
        status = "stale_recheck_required" if stale else chief["status"] if chief else \
                 "awaiting_chief" if len(reviews) == 2 else "awaiting_second_review" if reviews else "awaiting_reviews"
        batches.append({"batch_id": batch["event_id"], "scope": batch["scope"],
            "evidence_digest": batch["evidence_digest"], "status": status,
            "review_count": len(reviews), "chief_event_id": chief["event_id"] if chief else None,
            "item_ids": sorted(batch["items"]), "reuse": batch["reuse"],
            "coverage": batch["coverage"], "coverage_notes": batch["coverage_notes"]})
    risk["stage_review"] = {"revision": REVISION, "batches": batches,
        "status": "recorded_batches_complete" if batches and all(row["status"] == "complete" for row in batches)
            else "pending_or_recheck_required"}
    for judgment in risk.get("judgments", []):
        matching = next((batch for batch in batches if judgment["event_id"] in batch["item_ids"]), None)
        if matching:
            judgment["review_status"] = "chief_reviewed" if matching["status"] == "complete" else matching["status"]
            judgment["review_batch_id"] = matching["batch_id"]
            if matching["status"] == "complete":
                frozen = _batch(rows, matching["batch_id"])
                origin_batch_id = frozen["reuse"].get(judgment["event_id"], matching["batch_id"])
                chief = next(row for row in rows if row["kind"] == "adjudicate" and
                             row.get("batch_id") == origin_batch_id and row["status"] == "complete")
                decision = chief["decisions"].get(judgment["event_id"])
                if decision:
                    judgment["single_review_stage_risk"] = judgment["stage_risk"]
                    judgment["stage_risk"] = decision["stage_risk"]
                    judgment["chief_reasoning"] = decision["reasoning"]
                    judgment["chief_fact_basis"] = decision["fact_basis"]
                    judgment["chief_event_id"] = chief["event_id"]
                    judgment["display_grade"] = ("暂定低" if judgment["verification_status"] == "pending" and
                        judgment["stage_risk"] == "低" else f"阶段性{judgment['stage_risk']}" if
                        judgment["verification_status"] == "pending" else f"双审主审{judgment['stage_risk']}")
    for signal in risk.get("signals", []):
        matching = next((batch for batch in batches if signal["event_id"] in batch["item_ids"]), None)
        if matching:
            signal["review_status"] = "chief_reviewed" if matching["status"] == "complete" else matching["status"]
            signal["review_batch_id"] = matching["batch_id"]
            if matching["status"] == "complete":
                frozen = _batch(rows, matching["batch_id"])
                origin_batch_id = frozen["reuse"].get(signal["event_id"], matching["batch_id"])
                chief = next(row for row in rows if row["kind"] == "adjudicate" and
                             row.get("batch_id") == origin_batch_id and row["status"] == "complete")
                decision = chief["decisions"].get(signal["event_id"])
                if decision:
                    signal["chief_signal_conclusion"] = decision["signal_conclusion"]
                    signal["chief_event_id"] = chief["event_id"]
    from stage_risk_stage_b import _summary
    for summary in risk.get("by_country", []):
        related = [row for row in risk.get("judgments", []) if all(row["scope"].get(k) == summary.get(k)
                   for k in ("scenario_id", "jurisdiction", "product_version"))]
        revised = _summary(related, scope={k: summary[k] for k in
                            ("scenario_id", "jurisdiction", "product_version")})
        summary.update({k: revised[k] for k in ("stage_risk", "display_grade", "applicability",
            "previous_risk", "valid_partial_highest", "drivers", "suspended_judgments")})
        reviewed = bool(related) and all(row["review_status"] == "chief_reviewed" for row in related
                                       if row["applicability"] == "current")
        summary["review_status"] = "complete" if reviewed and summary.get("coverage_ready_for_09C") else "pending"
        summary["verification_status"] = (revised["verification_status"] if summary["review_status"] == "complete"
                                           else "pending")
        summary["confidence"] = revised["confidence"] if summary["verification_status"] == "verified" else None
    for summary in risk.get("by_scenario", []):
        related = [row for row in risk.get("judgments", []) if row["scope"]["scenario_id"] == summary["scenario_id"]]
        revised = _summary(related, scope={k: summary[k] for k in ("scenario_id", "product_version")})
        summary.update({k: revised[k] for k in ("stage_risk", "display_grade", "applicability",
            "previous_risk", "valid_partial_highest", "drivers", "suspended_judgments")})
        summary["review_status"] = ("complete" if related and all(row["review_status"] == "chief_reviewed"
            for row in related if row["applicability"] == "current") else "pending")
        summary["verification_status"] = revised["verification_status"] if summary["review_status"] == "complete" else "pending"
        summary["confidence"] = revised["confidence"] if summary["verification_status"] == "verified" else None
    primary = task.get("primary_scenario_id") or "product_entry"
    overall = next((row for row in risk.get("by_scenario", []) if row["scenario_id"] == primary), None)
    if overall and risk.get("overall"):
        target = risk["overall"]
        target.update({k: overall.get(k) for k in ("stage_risk", "display_grade", "applicability",
            "previous_risk", "valid_partial_highest", "drivers", "suspended_judgments")})
        target["review_status"] = ("complete" if overall["review_status"] == "complete" and
                                   target.get("coverage_ready_for_09C") else "pending")
        target["verification_status"] = overall["verification_status"] if target["review_status"] == "complete" else "pending"
        target["confidence"] = overall["confidence"] if target["verification_status"] == "verified" else None
        if target["stage_risk"] == "极低" and target["review_status"] != "complete":
            target.update(stage_risk="低", display_grade="暂定低", verification_status="pending", confidence=None)
    if risk.get("judgments") and all(row.get("review_status") == "chief_reviewed"
                                     for row in risk["judgments"] if row["applicability"] == "current"):
        risk["status"] = "chief_reviewed_for_recorded_judgments"
    result["stage_risk"] = risk
    if "work_view_sha256" in result:
        result["work_view_sha256"] = sha256_json({k: v for k, v in result.items()
            if k not in {"work_view_sha256", "review_work"}})
    return result

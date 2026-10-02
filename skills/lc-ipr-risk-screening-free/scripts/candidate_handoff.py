"""04C incremental, source-bound candidate handoff to module 05."""
from __future__ import annotations

from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_json, stable_id
from decision_workflow import candidate_content_sha256, candidate_identity_fingerprint
from source_result_processing import progress as result_progress, _latest_decisions, _retained_run, WHOLE_RECORD

REVISION = "candidate-handoff-v1"
FILENAME = "candidate-handoffs.json"
COLLECTIONS = ("patents", "trademarks", "copyright_assets", "enforcement")
APPLICABILITY = {"applicable", "not_applicable", "unknown"}


def enabled(task: dict) -> bool:
    value = task.get("candidate_handoff_revision")
    if value is None:
        return False
    if value != REVISION:
        raise ValueError("CANDIDATE_HANDOFF_REVISION_INVALID")
    return True


def load_ledger(task_dir: Path, task: dict) -> dict:
    path = task_dir / FILENAME
    ledger = load_json(path) if path.is_file() else {"revision": REVISION,
        "task_id": task["task_id"], "batches": []}
    if (not isinstance(ledger, dict) or ledger.get("revision") != REVISION
            or ledger.get("task_id") != task["task_id"]
            or not isinstance(ledger.get("batches"), list)):
        raise ValueError("CANDIDATE_HANDOFF_LEDGER_INVALID")
    previous = ""
    for batch in ledger["batches"]:
        if not isinstance(batch, dict) or batch.get("previous_batch_id") != previous:
            raise ValueError("CANDIDATE_HANDOFF_HISTORY_CHANGED")
        unsigned = {key: value for key, value in batch.items() if key != "batch_id"}
        if batch.get("batch_id") != stable_id("HANDOFF", task["task_id"], sha256_json(unsigned)):
            raise ValueError("CANDIDATE_HANDOFF_HISTORY_CHANGED")
        previous = batch["batch_id"]
    return ledger


def _index(candidates: dict) -> dict[str, tuple[str, dict]]:
    return {row["candidate_id"]: (collection, row)
        for collection in COLLECTIONS for row in candidates.get(collection, [])
        if isinstance(row, dict) and row.get("candidate_id")}


def _required_scopes(task: dict, candidate: dict) -> set[tuple[str, str]]:
    from decision_workflow import light_triage_right_allowed, triage_scope_enabled, UNLOCATED
    right = candidate.get("right_type")
    countries = task.get("target_jurisdictions", [])
    if triage_scope_enabled(task):
        origin = str(candidate.get("jurisdiction") or candidate.get("office") or "").upper()
        countries = [origin] if origin in countries else [UNLOCATED]
    return {(scenario["scenario_id"], country)
            for scenario in task.get("assessment_scenarios", [])
            if isinstance(scenario, dict) and scenario.get("scenario_id")
            and light_triage_right_allowed(task, scenario, right)
            for country in countries}


def _source_state(ref: dict, evidence: dict, task_dir: Path, candidate: dict | None = None) -> tuple[str, str]:
    eid = ref.get("evidence_id")
    if not eid or not any(isinstance(entry, dict) and entry.get("evidence_id") == eid
                          for entries in evidence.get("collections", {}).values()
                          if isinstance(entries, list) for entry in entries):
        return "pending", "SOURCE_EVIDENCE_MISSING"
    run_id = ref.get("source_run_id")
    if not run_id:
        return "ready", "REGISTERED_IMPORT_OR_REUSE"
    runs = [run for run in evidence.get("source_runs", [])
            if isinstance(run, dict) and run.get("run_id") == run_id]
    if len(runs) != 1:
        return "pending", "SOURCE_RUN_MISSING"
    run = runs[0]
    index = run.get("result_processing")
    if not isinstance(index, dict):
        return "pending", "SOURCE_RESULT_INDEX_MISSING"
    try:
        progress = result_progress(task_dir, run, evidence)
        if (progress.get('result_form') == WHOLE_RECORD and run.get('provider') == 'epo_ops'
                and run.get('operation') == 'candidate_detail'
                and run.get('request_params',{}).get('detail_operation') == 'images'):
            # This is one exact image-document receipt, not a search result card.
            # progress already verifies the original run, raw XML, identity,
            # retained TIFF bytes/pages and the unchanged whole-record signature.
            reviewed = progress.get('record_content_review')
            if not progress.get('material_processing_complete') or not isinstance(reviewed,dict):
                return 'pending', 'SOURCE_RECORD_CONTENT_NOT_REVIEWED'
            bound = reviewed.get('binding',{})
            entries = [entry for rows in evidence.get('collections',{}).values() if isinstance(rows,list)
                for entry in rows if isinstance(entry,dict) and entry.get('evidence_id') == eid
                and entry.get('source_run_id') == run_id]
            if (not isinstance(candidate,dict) or len(entries) != 1
                    or bound.get('entry_sha256') != sha256_json(entries[0])
                    or bound.get('candidate_id') != candidate.get('candidate_id')
                    or bound.get('publication_number') != candidate.get('publication_number')
                    or bound.get('jurisdiction') != candidate.get('jurisdiction')
                    or ref.get('provider') != run.get('provider')
                    or any(ref.get(key) is not None and ref[key] != 1
                           for key in ('source_position','result_position'))
                    or any(ref.get(key) and ref[key] != run.get('payload_digest')
                           for key in ('source_record_sha256','original_source_record_sha256'))
                    or (ref.get('plan_entry_sha256') and ref['plan_entry_sha256'] != run.get('plan_entry_sha256'))):
                return 'pending', 'SOURCE_RECORD_IDENTITY_MISMATCH'
            return 'ready', 'REVIEWED_WHOLE_RECORD_SOURCE'
        index, _ = _retained_run(task_dir, run, evidence)
        decisions = _latest_decisions(evidence, run_id, index)
    except (OSError, ValueError, KeyError, TypeError):
        return "pending", "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID"
    position = ref.get("source_position") or ref.get("result_position")
    if type(position) is not int:
        digest = ref.get("source_record_sha256") or ref.get("original_source_record_sha256")
        matches = [row["position"] for row in index.get("rows", []) if digest
                   and row.get("raw_sha256") == digest]
        position = matches[0] if len(matches) == 1 else None
    if position not in decisions:
        return "pending", "SOURCE_POSITION_NOT_REVIEWED"
    if decisions[position]["outcome"] not in {"candidate", "duplicate_source"}:
        return "pending", "SOURCE_POSITION_NOT_CANDIDATE"
    return "ready", "REVIEWED_SOURCE_POSITION"


def project(task: dict, evidence: dict, candidates: dict, task_dir: Path) -> dict:
    if not enabled(task):
        return {"revision": None, "rows": [], "material_processing_complete": False}
    ledger = load_ledger(task_dir, task)
    latest = {item["candidate_id"]: item for batch in ledger["batches"]
              for item in batch["candidates"]}
    rows = []
    for cid, (collection, candidate) in _index(candidates).items():
        ready, pending = [], []
        for ref in candidate.get("sources", []):
            if not isinstance(ref, dict):
                continue
            state, reason = _source_state(ref, evidence, task_dir, candidate)
            source_entry = next((entry for entries in evidence.get("collections", {}).values()
                if isinstance(entries, list) for entry in entries
                if isinstance(entry, dict) and entry.get("evidence_id") == ref.get("evidence_id")), {})
            value = {"evidence_id": ref.get("evidence_id"),
                     "source_run_id": ref.get("source_run_id"),
                     "source_anchor": ref.get("source_anchor"), "reason": reason,
                     "source_entry_kind": source_entry.get("kind") or "source_result",
                     "original_collected_at": (source_entry.get("source_checked_at")
                        or source_entry.get("collected_at") or ref.get("collected_at")),
                     "retention_checked_at": source_entry.get("checked_at")
                        if source_entry.get("kind") == "historical_source_reuse" else None}
            (ready if state == "ready" else pending).append(value)
        identity = candidate_identity_fingerprint(collection, candidate)
        content = candidate_content_sha256(candidate, evidence, task=task)
        digest = sha256_json({"identity": identity, "content": content})
        previous = latest.get(cid)
        required_scopes = _required_scopes(task, candidate)
        completed_scopes = {(review["scenario_id"], review["jurisdiction"])
            for batch in ledger["batches"] for item in batch["candidates"]
            if item["candidate_id"] == cid and item["handoff_digest"] == digest
            for review in batch["scope_reviews"] if review["candidate_id"] == cid}
        remaining = sorted(required_scopes - completed_scopes)
        rows.append({"candidate_id": cid, "collection": collection,
                     "identity_status": candidate.get("identity_status"),
                     "ready_sources": ready, "pending_sources": pending,
                     "remaining_scopes": [{"scenario_id": sid, "jurisdiction": country}
                                          for sid, country in remaining],
                     "handoff_digest": digest,
                     "handoff_state": ("source_pending" if not ready else "current" if previous
                         and previous.get("handoff_digest") == digest and not remaining
                         else "ready")})
    unfinished_runs = []
    for run in evidence.get("source_runs", []):
        if not isinstance(run, dict) or run.get("evidence_type") not in {
                "patent", "trademark", "copyright", "enforcement"}:
            continue
        try:
            if not result_progress(task_dir, run, evidence)["material_processing_complete"]:
                unfinished_runs.append(run.get("run_id"))
        except (OSError, ValueError, KeyError, TypeError):
            unfinished_runs.append(run.get("run_id"))
    return {"revision": REVISION, "rows": rows,
            "material_processing_complete": not unfinished_runs
                and not any(row["pending_sources"] or not row["ready_sources"] for row in rows),
            "unfinished_source_run_ids": unfinished_runs,
            "candidate_handoff_complete": all(row["handoff_state"] == "current" for row in rows)}


def work_entries(task: dict, evidence: dict, candidates: dict, task_dir: Path) -> list[dict]:
    if not enabled(task):
        return []
    view = project(task, evidence, candidates, task_dir)
    return [{"kind": "agent_investigation", "state": "awaiting_review",
             "candidate_id": row["candidate_id"], "right_type": next(
                 (candidate.get("right_type") for _, candidate in _index(candidates).values()
                  if candidate.get("candidate_id") == row["candidate_id"]), "unknown"),
             "reason": ("CANDIDATE_HANDOFF_READY" if row["handoff_state"] == "ready"
                        else "CANDIDATE_HANDOFF_SOURCE_PENDING"),
             "handoff_digest": row["handoff_digest"],
             "remaining_scopes": row["remaining_scopes"],
             "ready_evidence_refs": sorted({ref["evidence_id"] for ref in row["ready_sources"]
                                             if ref.get("evidence_id")}),
             "pending_evidence_refs": sorted({ref["evidence_id"] for ref in row["pending_sources"]
                                               if ref.get("evidence_id")})}
            for row in view["rows"] if row["handoff_state"] in {"ready", "source_pending"}]


def record_batch(task_dir: Path, request: dict) -> dict:
    from provider_utils import evidence_lock
    task_dir = task_dir.resolve()
    with evidence_lock(task_dir):
        task = load_json(task_dir / "task.json")
        if not enabled(task) or task.get("state") == "completed":
            raise ValueError("CANDIDATE_HANDOFF_NOT_WRITABLE")
        evidence = load_json(task_dir / "evidence.json")
        candidates = load_json(task_dir / "normalized-candidates.json")
        ledger = load_ledger(task_dir, task)
        if isinstance(request, dict) and isinstance(request.get("candidate_ids"), list) \
                and isinstance(request.get("scope_reviews"), list):
            for prior in ledger["batches"]:
                if ([item["candidate_id"] for item in prior["candidates"]] == request["candidate_ids"]
                        and prior["scope_reviews"] == request["scope_reviews"]
                        and prior["reviewer"] == request.get("reviewer")
                        and prior["reason"] == request.get("reason")):
                    return prior
        view = project(task, evidence, candidates, task_dir)
        ready = {row["candidate_id"]: row for row in view["rows"]
                 if row["handoff_state"] == "ready"}
        if not isinstance(request, dict) or not isinstance(request.get("candidate_ids"), list) \
                or not request["candidate_ids"] \
                or any(not isinstance(cid, str) or not cid for cid in request["candidate_ids"]) \
                or len(request["candidate_ids"]) != len(set(request["candidate_ids"])) \
                or not all(isinstance(request.get(field), str) and request[field].strip()
                           for field in ("reviewer", "reason")):
            raise ValueError("CANDIDATE_HANDOFF_REQUEST_INVALID")
        ids = request["candidate_ids"]
        if any(cid not in ready for cid in ids):
            raise ValueError("CANDIDATE_HANDOFF_CANDIDATE_NOT_READY")
        scope_reviews = request.get("scope_reviews")
        if not isinstance(scope_reviews, list) or not scope_reviews:
            raise ValueError("CANDIDATE_HANDOFF_SCOPE_REVIEW_REQUIRED")
        scenario_ids = {row.get("scenario_id") for row in task.get("assessment_scenarios", [])}
        from decision_workflow import triage_scope_enabled, UNLOCATED
        countries = set(task.get("target_jurisdictions", []))
        if triage_scope_enabled(task):
            countries.add(UNLOCATED)
        current_index = _index(candidates)
        allowed_scopes = {cid: _required_scopes(task, current_index[cid][1]) for cid in ids}
        remaining_scopes = {cid: {(item["scenario_id"], item["jurisdiction"])
                                  for item in ready[cid]["remaining_scopes"]} for cid in ids}
        supported = {cid: {ref["evidence_id"] for ref in ready[cid]["ready_sources"]
                           if ref.get("evidence_id")} for cid in ids}
        seen = set()
        for review in scope_reviews:
            if not isinstance(review, dict):
                raise ValueError("CANDIDATE_HANDOFF_SCOPE_REVIEW_INVALID")
            key = (review.get("candidate_id"), review.get("scenario_id"), review.get("jurisdiction"))
            if (key in seen or key[0] not in ids or key[1] not in scenario_ids
                    or key[2] not in countries or (key[1], key[2]) not in allowed_scopes[key[0]]
                    or (key[1], key[2]) not in remaining_scopes[key[0]]
                    or review.get("applicability") not in APPLICABILITY
                    or not isinstance(review.get("reason"), str) or not review["reason"].strip()
                    or not isinstance(review.get("evidence_refs"), list)
                    or not review["evidence_refs"]
                    or any(not isinstance(ref, str) or not ref for ref in review["evidence_refs"])
                    or len(review["evidence_refs"]) != len(set(review["evidence_refs"]))
                    or not set(review["evidence_refs"]) <= supported[key[0]]):
                raise ValueError("CANDIDATE_HANDOFF_SCOPE_REVIEW_INVALID")
            seen.add(key)
        if any(cid not in {review["candidate_id"] for review in scope_reviews} for cid in ids):
            raise ValueError("CANDIDATE_HANDOFF_SCOPE_REVIEW_MISSING")
        event = {"candidates": [{"candidate_id": cid,
                  "handoff_digest": ready[cid]["handoff_digest"],
                  "identity_status": ready[cid]["identity_status"],
                  "ready_sources": ready[cid]["ready_sources"],
                  "pending_sources": ready[cid]["pending_sources"]} for cid in ids],
                 "scope_reviews": scope_reviews, "reviewer": request["reviewer"].strip(),
                 "reason": request["reason"].strip(),
                 "previous_batch_id": ledger["batches"][-1]["batch_id"] if ledger["batches"] else "",
                 "recorded_at": now_iso()}
        event["batch_id"] = stable_id("HANDOFF", task["task_id"], sha256_json(event))
        ledger["batches"].append(event)
        atomic_write_json(task_dir / FILENAME, ledger)
        return event

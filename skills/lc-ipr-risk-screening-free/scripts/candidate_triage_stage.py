"""05C receipt-batch progress, reviewed reopenings and module-05 completion.

Source runs and the existing work view remain the execution/queue authorities.
These events record only triage review and selected-candidate handoff.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, sha256_json, stable_id

REVISION = "candidate-triage-stage-v1"
EVENTS = "candidate_triage_stage_events"
SCOPE = ("candidate_id", "scenario_id", "jurisdiction", "right_type")
KINDS = {"batch_review", "reopen", "reopen_review", "selected_handoff", "duplicate_reference"}
CHANGE_KINDS = {"candidate_content", "product_fact", "product_scope", "identity_correction",
                "source_correction", "source_conflict", "merge", "split"}


def enabled(task: dict | None) -> bool:
    value = (task or {}).get("triage_stage_revision")
    if value is None:
        return False
    if value != REVISION or (task or {}).get("triage_followup_revision") != "candidate-followup-v1":
        raise ValueError("TRIAGE_STAGE_REVISION_INVALID")
    return True


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value, *, nonempty=True) -> bool:
    return (isinstance(value, list) and (bool(value) or not nonempty)
            and all(_text(item) for item in value) and len(value) == len(set(value)))


def events(task: dict) -> list[dict]:
    rows = task.get(EVENTS, [])
    if not isinstance(rows, list):
        raise ValueError("TRIAGE_STAGE_EVENTS_INVALID")
    previous = ""
    for row in rows:
        if (not isinstance(row, dict) or row.get("kind") not in KINDS
                or row.get("previous_event_id") != previous):
            raise ValueError("TRIAGE_STAGE_EVENTS_CHANGED")
        unsigned = {key: value for key, value in row.items() if key != "event_id"}
        expected = stable_id("TRIAGE-STAGE", task["task_id"], sha256_json(unsigned))
        if row.get("event_id") != expected:
            raise ValueError("TRIAGE_STAGE_EVENTS_CHANGED")
        previous = expected
    return rows


def _append(task: dict, row: dict) -> dict:
    prior = events(task)
    entry = {**row, "previous_event_id": prior[-1]["event_id"] if prior else "", "recorded_at": now_iso()}
    entry["event_id"] = stable_id("TRIAGE-STAGE", task["task_id"], sha256_json(entry))
    task.setdefault(EVENTS, []).append(entry)
    return entry


def _scope(row: dict) -> tuple:
    return tuple(row.get(key) for key in SCOPE)


def latest_reopen(task: dict, scope: tuple) -> dict | None:
    return next((event for event in reversed(events(task)) if event["kind"] == "reopen"
        and any(_scope(item) == scope or _scope(item.get("target_scope") or {}) == scope
                for item in event["affected"])), None)


def reopen_reason(task: dict, annotation: dict) -> str | None:
    """A new annotation alone cannot silently clear a reopened old decision."""
    if not enabled(task):
        return None
    event = latest_reopen(task, _scope(annotation))
    if event is None:
        return None
    if not any(row["kind"] == "reopen_review" and row.get("reopen_event_id") == event["event_id"]
               and row.get("new_annotation_id") == annotation.get("annotation_id")
               and row.get("new_annotation_sha256") == sha256_json(annotation)
               and _scope(row) == _scope(annotation) for row in events(task)):
        return "TRIAGE_CHANGE_REVIEW_REQUIRED"
    return None


def _context(task_dir: Path):
    from annotate_materiality import load_materiality_ledger
    from workflow_v24 import scenario_supplement
    task = load_json(task_dir / "task.json")
    if not enabled(task) or task.get("state") == "completed":
        raise ValueError("TRIAGE_STAGE_NOT_WRITABLE")
    evidence = load_json(task_dir / "evidence.json")
    candidates = load_json(task_dir / "normalized-candidates.json")
    plan = load_json(task_dir / "search-plan.json")
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    _verify_event_sources(events(task), evidence, supplement, ledger)
    return task, evidence, candidates, plan, ledger, supplement


def _candidate(candidates: dict, cid: str):
    from annotate_materiality import iter_candidates
    matches = [(collection, row) for collection, row in iter_candidates(candidates)
               if row.get("candidate_id") == cid]
    if len(matches) != 1:
        raise ValueError("TRIAGE_STAGE_CANDIDATE_UNKNOWN")
    return matches[0]


def _annotation(ledger: dict, annotation_id: str) -> dict:
    rows = [row for row in ledger.get("annotations", []) if row.get("annotation_id") == annotation_id]
    if len(rows) != 1:
        raise ValueError("TRIAGE_STAGE_ANNOTATION_UNKNOWN")
    return rows[0]


def _current(task, evidence, candidates, ledger, supplement, scope):
    from decision_workflow import effective_decision
    collection, candidate = _candidate(candidates, scope[0])
    return effective_decision(task, ledger, collection, candidate, *scope[1:],
                              evidence=evidence, supplement=supplement)


def _refs(evidence, supplement, refs):
    from decision_workflow import evidence_index
    if not _strings(refs) or not set(refs) <= set(evidence_index(evidence, supplement)):
        raise ValueError("TRIAGE_STAGE_EVIDENCE_INVALID")


def _verify_event_sources(history, evidence, supplement, ledger):
    from decision_workflow import evidence_index
    indexed = evidence_index(evidence, supplement)
    annotations = {row.get("annotation_id"): row for row in ledger.get("annotations", [])}
    for event in history:
        if event["kind"] == "reopen":
            if any(ref not in indexed or sha256_json(indexed[ref]) != digest
                   for ref, digest in event.get("change_evidence_sha256", {}).items()):
                raise ValueError("TRIAGE_REOPEN_EVIDENCE_CHANGED")
        elif event["kind"] == "reopen_review":
            row = annotations.get(event.get("new_annotation_id"))
            if row is None or sha256_json(row) != event.get("new_annotation_sha256"):
                raise ValueError("TRIAGE_REOPEN_REVIEW_DECISION_CHANGED")
        elif event["kind"] == "selected_handoff":
            row = annotations.get(event.get("annotation_id"))
            if row is None or sha256_json(row) != event.get("annotation_sha256"):
                raise ValueError("TRIAGE_HANDOFF_DECISION_CHANGED")
        elif event["kind"] == "batch_review":
            if sha256_json(event.get("batch_snapshot")) != event.get("batch_snapshot_sha256"):
                raise ValueError("TRIAGE_BATCH_SNAPSHOT_CHANGED")


def record_reopen(task_dir: Path, request: dict) -> dict:
    from provider_utils import evidence_lock
    with evidence_lock(task_dir):
        task, evidence, candidates, _, ledger, supplement = _context(task_dir)
        if not isinstance(request, dict) or request.get("change_kind") not in CHANGE_KINDS \
                or not _text(request.get("change_summary")) or not _text(request.get("reviewer")) \
                or not _text(request.get("reason")) or not _strings(request.get("dependency_ids")):
            raise ValueError("TRIAGE_REOPEN_BASIS_REQUIRED")
        _refs(evidence, supplement, request.get("change_evidence_refs"))
        affected = request.get("affected")
        if not isinstance(affected, list) or not affected:
            raise ValueError("TRIAGE_REOPEN_AFFECTED_REQUIRED")
        reviewed = []
        material_change = False
        for item in affected:
            if not isinstance(item, dict) or not _text(item.get("annotation_id")):
                raise ValueError("TRIAGE_REOPEN_AFFECTED_INVALID")
            old = _annotation(ledger, item["annotation_id"])
            scope = {key: old[key] for key in SCOPE}
            if any(item.get(key) != scope[key] for key in SCOPE):
                raise ValueError("TRIAGE_REOPEN_SCOPE_MISMATCH")
            if item.get("impact") not in {"direct", "widened"} or not _text(item.get("impact_reason")):
                raise ValueError("TRIAGE_REOPEN_IMPACT_REQUIRED")
            if item["impact"] == "widened" and not _text(item.get("reasonable_scope_reason")):
                raise ValueError("TRIAGE_REOPEN_WIDENING_BASIS_REQUIRED")
            target = item.get("target_candidate_id", scope["candidate_id"])
            target_scope = item.get("target_scope", {**scope, "candidate_id": target}) if target is not None else None
            new_version_sha256 = None
            if target is not None:
                if (not isinstance(target_scope, dict) or target_scope.get("candidate_id") != target
                        or not all(_text(target_scope.get(key)) for key in SCOPE)):
                    raise ValueError("TRIAGE_REOPEN_TARGET_SCOPE_INVALID")
                _, target_candidate = _candidate(candidates, target)
                if target_scope["right_type"] != target_candidate.get("right_type"):
                    raise ValueError("TRIAGE_REOPEN_TARGET_RIGHT_MISMATCH")
            if request["change_kind"] in {"merge", "split"} and not _text(item.get("attribution_reason")):
                raise ValueError("TRIAGE_REOPEN_ATTRIBUTION_REQUIRED")
            if target is not None:
                from decision_workflow import (candidate_content_sha256, candidate_identity_fingerprint,
                    triage_product_digest, scenario_index)
                collection, candidate = _candidate(candidates, target)
                current_versions = (candidate_identity_fingerprint(collection, candidate),
                    candidate_content_sha256(candidate, evidence, supplement, task=task),
                    triage_product_digest(task, target_scope["scenario_id"], target_scope["right_type"], target),
                    scenario_index(task)[target_scope["scenario_id"]]["scenario_sha256"])
                new_version_sha256 = sha256_json(current_versions)
                old_versions = tuple(old.get(key) for key in
                    ("candidate_identity_fingerprint", "candidate_content_sha256",
                     "product_identity_sha256", "scenario_sha256"))
                material_change |= current_versions != old_versions
            material_change |= not set(request["change_evidence_refs"]) <= set(old.get("evidence_refs", []))
            reviewed.append({**scope, "annotation_id": old["annotation_id"],
                "impact": item["impact"], "impact_reason": item["impact_reason"],
                "reasonable_scope_reason": item.get("reasonable_scope_reason"),
                "target_candidate_id": target, "target_scope": target_scope,
                "attribution_reason": item.get("attribution_reason"),
                "new_version_sha256": new_version_sha256,
                "old_version_sha256": sha256_json({key: old.get(key) for key in
                    ("candidate_identity_fingerprint", "candidate_content_sha256",
                     "product_identity_sha256", "scenario_sha256", "basis_sha256")})})
        if len({_scope(item) for item in reviewed}) != len(reviewed):
            raise ValueError("TRIAGE_REOPEN_DUPLICATE_SCOPE")
        alias_id = request.get("identity_correction_event_id")
        if request["change_kind"] in {"merge", "split"}:
            aliases = [alias for alias in candidates.get("identity_aliases", [])
                       if alias.get("event_id") == alias_id and alias.get("kind") == request["change_kind"]]
            if candidates.get("identity_aliases") and (len(aliases) != 1
                    or not {row["candidate_id"] for row in reviewed} <= set(aliases[0]["old_candidate_ids"])):
                raise ValueError("TRIAGE_REOPEN_IDENTITY_EVENT_REQUIRED")
        if not material_change and request["change_kind"] not in {"merge", "split"}:
            raise ValueError("TRIAGE_REOPEN_MATERIAL_CHANGE_REQUIRED")
        from decision_workflow import evidence_index
        indexed = evidence_index(evidence, supplement)
        row = {"kind": "reopen", "change_kind": request["change_kind"],
            "identity_correction_event_id": alias_id,
            "change_summary": request["change_summary"], "change_evidence_refs": request["change_evidence_refs"],
            "change_evidence_sha256": {ref: sha256_json(indexed[ref])
                                       for ref in request["change_evidence_refs"]},
            "affected": reviewed, "dependency_ids": request["dependency_ids"],
            "reviewer": request["reviewer"], "reason": request["reason"]}
        for prior in reversed(events(task)):
            if prior.get("kind") == "reopen" and all(prior.get(key) == row[key]
                    for key in ("change_kind", "change_summary", "change_evidence_refs",
                                "change_evidence_sha256", "affected",
                                "dependency_ids", "reviewer", "reason")):
                return prior
        event = _append(task, row)
        atomic_write_json(task_dir / "task.json", task)
        return event


def record_reopen_review(task_dir: Path, request: dict) -> dict:
    from provider_utils import evidence_lock
    with evidence_lock(task_dir):
        task, evidence, candidates, _, ledger, supplement = _context(task_dir)
        reopen = next((row for row in events(task) if row.get("event_id") == request.get("reopen_event_id")
                       and row["kind"] == "reopen"), None)
        if reopen is None:
            raise ValueError("TRIAGE_REOPEN_EVENT_UNKNOWN")
        old = next((row for row in reopen["affected"] if row["annotation_id"] == request.get("old_annotation_id")), None)
        if old is None or old.get("target_candidate_id") is None:
            raise ValueError("TRIAGE_REOPEN_ATTRIBUTION_PENDING")
        scope = old["target_scope"]
        fresh = _annotation(ledger, request.get("new_annotation_id"))
        if _scope(fresh) != _scope(scope) or fresh["annotation_id"] == old["annotation_id"]:
            raise ValueError("TRIAGE_REOPEN_NEW_DECISION_REQUIRED")
        plain_task = {key: value for key, value in task.items() if key not in {"triage_stage_revision", EVENTS}}
        current = _current(plain_task, evidence, candidates, ledger, supplement, _scope(scope))
        if not current.get("current") or current.get("annotation", {}).get("annotation_id") != fresh["annotation_id"]:
            raise ValueError("TRIAGE_REOPEN_NEW_DECISION_NOT_CURRENT")
        _refs(evidence, supplement, request.get("reviewed_evidence_refs"))
        if not set(request["reviewed_evidence_refs"]) <= set(fresh.get("evidence_refs", [])):
            raise ValueError("TRIAGE_REOPEN_EVIDENCE_NOT_IN_DECISION")
        if not _text(request.get("basis")) or not _text(request.get("reviewer")):
            raise ValueError("TRIAGE_REOPEN_REVIEW_BASIS_REQUIRED")
        previous = _annotation(ledger, old["annotation_id"])
        if fresh["decision"] == previous["decision"] and not _text(request.get("same_conclusion_basis")):
            raise ValueError("TRIAGE_REOPEN_SAME_CONCLUSION_BASIS_REQUIRED")
        row = {"kind": "reopen_review", **scope, "reopen_event_id": reopen["event_id"],
            "old_annotation_id": old["annotation_id"], "new_annotation_id": fresh["annotation_id"],
            "new_annotation_sha256": sha256_json(fresh), "reviewed_evidence_refs": request["reviewed_evidence_refs"],
            "basis": request["basis"], "same_conclusion_basis": request.get("same_conclusion_basis"),
            "reviewer": request["reviewer"]}
        for prior in reversed(events(task)):
            if prior.get("kind") == "reopen_review" and all(prior.get(key) == row[key]
                    for key in ("reopen_event_id", "old_annotation_id", "new_annotation_id",
                                "new_annotation_sha256", "reviewed_evidence_refs", "basis",
                                "same_conclusion_basis", "reviewer")):
                return prior
        event = _append(task, row)
        atomic_write_json(task_dir / "task.json", task)
        return event


def record_selected_handoff(task_dir: Path, request: dict) -> dict:
    from provider_utils import evidence_lock
    with evidence_lock(task_dir):
        task, evidence, candidates, _, ledger, supplement = _context(task_dir)
        scope = tuple(request.get(key) for key in SCOPE)
        current = _current(task, evidence, candidates, ledger, supplement, scope)
        if current.get("decision") != "selected" or not current.get("current"):
            raise ValueError("TRIAGE_SELECTED_CURRENT_REQUIRED")
        annotation = current["annotation"]
        if request.get("annotation_id") != annotation["annotation_id"]:
            raise ValueError("TRIAGE_SELECTED_ANNOTATION_MISMATCH")
        refs = request.get("evidence_refs")
        _refs(evidence, supplement, refs)
        if not set(refs) <= set(annotation["evidence_refs"]):
            raise ValueError("TRIAGE_SELECTED_EVIDENCE_NOT_READ")
        if (not isinstance(request.get("reading_scope"), dict) or not request["reading_scope"]
                or request["reading_scope"].get("level") != annotation.get("reading_level")
                or not _strings(request.get("verification_gaps"), nonempty=False)
                or not _text(request.get("reviewer")) or not _text(request.get("reason"))):
            raise ValueError("TRIAGE_SELECTED_HANDOFF_BASIS_REQUIRED")
        gaps = annotation.get("candidate_relation", {}).get("identity_gaps", [])
        if not set(gaps) <= set(request["verification_gaps"]):
            raise ValueError("TRIAGE_SELECTED_IDENTITY_GAPS_MISSING")
        row = {"kind": "selected_handoff", **{key: annotation[key] for key in SCOPE},
            "annotation_id": annotation["annotation_id"], "annotation_sha256": sha256_json(annotation),
            "product_version_sha256": annotation["product_identity_sha256"],
            "candidate_version_sha256": annotation["candidate_content_sha256"],
            "evidence_refs": refs, "reading_scope": request["reading_scope"],
            "association": annotation.get("comparison"), "candidate_relation": annotation.get("candidate_relation"),
            "verification_gaps": request["verification_gaps"], "reviewer": request["reviewer"],
            "reason": request["reason"]}
        for prior in reversed(events(task)):
            if prior.get("kind") == "selected_handoff" and _scope(prior) == _scope(row) \
                    and all(prior.get(key) == row[key] for key in ("annotation_sha256",
                        "evidence_refs", "reading_scope", "verification_gaps", "reviewer", "reason")):
                return prior
        event = _append(task, row)
        atomic_write_json(task_dir / "task.json", task)
        return event


def record_duplicate_reference(task_dir: Path, request: dict) -> dict:
    from provider_utils import evidence_lock
    with evidence_lock(task_dir):
        task, evidence, candidates, _, ledger, supplement = _context(task_dir)
        scope = tuple(request.get(key) for key in SCOPE)
        current = _current(task, evidence, candidates, ledger, supplement, scope)
        if not current.get("current"):
            raise ValueError("TRIAGE_DUPLICATE_CURRENT_DECISION_REQUIRED")
        _refs(evidence, supplement, request.get("duplicate_evidence_refs"))
        if not _text(request.get("same_content_basis")) or not _text(request.get("reviewer")):
            raise ValueError("TRIAGE_DUPLICATE_BASIS_REQUIRED")
        from decision_workflow import evidence_index, factual_content
        _, candidate = _candidate(candidates, scope[0])
        candidate_refs = {row.get("evidence_id") for row in candidate.get("sources", [])
                          if isinstance(row, dict)}
        if not set(request["duplicate_evidence_refs"]) <= candidate_refs:
            raise ValueError("TRIAGE_DUPLICATE_SOURCE_NOT_LINKED")
        indexed = evidence_index(evidence, supplement)
        prior_content = {sha256_json(factual_content(indexed[ref]["payload"]))
                         for ref in current["annotation"]["evidence_refs"]
                         if indexed[ref].get("payload") not in (None, {}, [])}
        if not prior_content or any(indexed[ref].get("payload") in (None, {}, [])
               or sha256_json(factual_content(indexed[ref]["payload"])) not in prior_content
               for ref in request["duplicate_evidence_refs"]):
            raise ValueError("TRIAGE_DUPLICATE_CONTENT_CHANGED")
        row = {"kind": "duplicate_reference", **dict(zip(SCOPE, scope)),
            "annotation_id": current["annotation"]["annotation_id"],
            "annotation_sha256": sha256_json(current["annotation"]),
            "duplicate_evidence_refs": request["duplicate_evidence_refs"],
            "same_content_basis": request["same_content_basis"], "reviewer": request["reviewer"]}
        event = _append(task, row)
        atomic_write_json(task_dir / "task.json", task)
        return event


def record_batch_review(task_dir: Path, request: dict) -> dict:
    """Freeze one observed receipt batch without claiming module completion."""
    from provider_utils import evidence_lock
    with evidence_lock(task_dir):
        task, evidence, candidates, _, ledger, supplement = _context(task_dir)
        if not isinstance(request, dict) or not all(_text(request.get(key)) for key in
                ("batch_id", "reviewer", "reason")):
            raise ValueError("TRIAGE_BATCH_REVIEW_BASIS_REQUIRED")
        current = project(task, evidence, candidates, ledger, task_dir=task_dir, supplement=supplement)
        batches = [row for row in current["batches"] if row["batch_id"] == request["batch_id"]]
        if len(batches) != 1:
            raise ValueError("TRIAGE_BATCH_UNKNOWN")
        snapshot = batches[0]
        row = {"kind": "batch_review", "batch_id": request["batch_id"],
            "batch_snapshot": snapshot, "batch_snapshot_sha256": sha256_json(snapshot),
            "stage_version_sha256": current["current_version_sha256"],
            "reviewer": request["reviewer"], "reason": request["reason"]}
        for prior in reversed(events(task)):
            if prior.get("kind") == "batch_review" and all(prior.get(key) == row[key]
                    for key in ("batch_id", "batch_snapshot_sha256", "reviewer", "reason")):
                return prior
        event = _append(task, row)
        atomic_write_json(task_dir / "task.json", task)
        return event


def project(task, evidence, candidates, ledger, *, plan=None, source_work=None,
            task_dir: Path | None = None, supplement=None) -> dict:
    from decision_workflow import triage_summary
    if not enabled(task):
        return {"revision": None}
    history = events(task)
    _verify_event_sources(history, evidence, supplement, ledger)
    triage = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)
    records = triage["records"]
    handoffs = {(row["candidate_id"], row["scenario_id"], row["jurisdiction"], row["right_type"],
        row["annotation_id"], row["annotation_sha256"]) for row in history if row["kind"] == "selected_handoff"}
    selected_pending = [row for row in records if row["current"] and row["decision"] == "selected"
        and (*_scope(row), row["annotation"]["annotation_id"], sha256_json(row["annotation"])) not in handoffs]
    unresolved = [row for row in records if not row["current"] or row["decision"] == "needs_info"]
    dispositions = [row for row in triage.get("scope_dispositions", []) if row["scope_status"] == "pending"]
    pending_reopens = []
    for event in history:
        if event["kind"] != "reopen":
            continue
        for item in event["affected"]:
            target = item.get("target_candidate_id")
            reviews = [row for row in history if row["kind"] == "reopen_review"
                       and row.get("reopen_event_id") == event["event_id"]
                       and row.get("old_annotation_id") == item["annotation_id"]]
            if target is None or not reviews:
                pending_reopens.append({**item, "reopen_event_id": event["event_id"],
                    "reason": "TRIAGE_ATTRIBUTION_REQUIRED" if target is None else "TRIAGE_CHANGE_REVIEW_REQUIRED"})
    uncovered_aliases = []
    for alias in candidates.get("identity_aliases", []):
        if not isinstance(alias, dict) or alias.get("kind") not in {"merge", "split"}:
            continue
        old_ids = {row["annotation_id"] for row in ledger.get("annotations", [])
                   if row.get("candidate_id") in alias.get("old_candidate_ids", [])}
        covered = {item["annotation_id"] for event in history if event["kind"] == "reopen"
                   and event.get("identity_correction_event_id") == alias.get("event_id")
                   for item in event["affected"]}
        if old_ids - covered:
            uncovered_aliases.append({"identity_correction_event_id": alias.get("event_id"),
                "kind": alias["kind"], "old_candidate_ids": alias["old_candidate_ids"],
                "current_candidate_ids": alias.get("current_candidate_ids", []),
                "unreviewed_annotation_ids": sorted(old_ids - covered),
                "reason": "TRIAGE_IDENTITY_CHANGE_IMPACT_REQUIRED"})
    by_run = {run.get("run_id"): index for index, run in enumerate(evidence.get("source_runs", []))
              if isinstance(run, dict)}
    batch_candidates = {}
    candidate_versions = []
    from decision_workflow import candidate_content_sha256, candidate_identity_fingerprint
    for collection in ("patents", "trademarks", "copyright_assets", "enforcement"):
        for candidate in candidates.get(collection, []):
            cid = candidate.get("candidate_id")
            candidate_versions.append((cid, candidate_identity_fingerprint(collection, candidate),
                candidate_content_sha256(candidate, evidence, supplement, task=task)))
            for source in candidate.get("sources", []):
                key = source.get("source_run_id") or "import:" + str(source.get("evidence_id") or cid)
                batch_candidates.setdefault(key, set()).add(cid)
            if not candidate.get("sources"):
                batch_candidates.setdefault("unbound:" + str(cid), set()).add(cid)
    batches = []
    for index, run in enumerate(evidence.get("source_runs", [])):
        if not isinstance(run, dict) or run.get("evidence_type") not in {"patent", "trademark", "copyright", "enforcement"}:
            continue
        rid = run.get("run_id")
        processing = None
        if task_dir is not None:
            from source_result_processing import progress
            try:
                processing = progress(task_dir, run, evidence)
            except (OSError, ValueError, KeyError, TypeError):
                processing = {"material_processing_complete": False,
                    "reason": "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID", "pending_positions": []}
        else:
            processing = {"material_processing_complete": False,
                          "reason": "SOURCE_RESULT_PROGRESS_NOT_LOADED", "pending_positions": []}
        ids = sorted(batch_candidates.get(rid, set()))
        open_ids = sorted({row["candidate_id"] for row in unresolved if row["candidate_id"] in ids})
        batches.append({"batch_id": rid, "received_order": index, "query_id": run.get("query_id"),
            "received_material_sha256": run.get("payload_digest") or sha256_json(run.get("result_processing")),
            "candidate_ids": ids, "triage_pending_candidate_ids": open_ids,
            "selected_pending_handoff_ids": sorted({row["candidate_id"] for row in selected_pending
                                                    if row["candidate_id"] in ids}),
            "material_processing": processing,
            "batch_processed": bool(processing["material_processing_complete"] and not open_ids)})
    for index, (key, ids) in enumerate(batch_candidates.items(), len(batches)):
        if key in by_run:
            continue
        open_ids = sorted({row["candidate_id"] for row in unresolved if row["candidate_id"] in ids})
        batches.append({"batch_id": key, "received_order": index, "candidate_ids": sorted(ids),
            "triage_pending_candidate_ids": open_ids,
            "selected_pending_handoff_ids": sorted({row["candidate_id"] for row in selected_pending
                                                    if row["candidate_id"] in ids}),
            "material_processing": {"material_processing_complete": not key.startswith("unbound:")},
            "batch_processed": not open_ids and not key.startswith("unbound:")})
    from candidate_followup import latest_event
    waiting, limited = [], []
    for row in unresolved:
        if row.get("decision") != "needs_info" or not row.get("current"):
            continue
        actions = row.get("next_actions", [])
        reviews = [latest_event(task, "result_review", row["annotation"]["annotation_id"],
                                action.get("action_id")) for action in actions]
        if reviews and all(review and review.get("outcome") == "waiting" for review in reviews):
            waiting.append(row)
        elif reviews and all(review and review.get("outcome") == "limited" for review in reviews):
            limited.append(row)
    raw_pending = [row for row in batches if not row["material_processing"]["material_processing_complete"]]
    plan_rows = {row.get("query_id"): row for rows in (plan or {}).get("queries", {}).values()
                 for row in rows if isinstance(row, dict)}
    def module_source(query_id):
        if plan is None:
            return True
        purpose = str(plan_rows.get(query_id, {}).get("action_purpose") or "")
        return purpose in {"discovery", "recall", "provenance"} or purpose.startswith("needs_info:")
    open_queries = [run.get("query_id") for run in evidence.get("source_runs", [])
                    if run.get("evidence_type") in {"patent", "trademark", "copyright", "enforcement"}
                    and (run.get("submission_state") == "unknown"
                         or run.get("status") in {"pending", "running"})]
    open_queries.extend(row.get("query_id") for row in source_work or []
                        if row.get("kind") == "source_lookup"
                        and row.get("state") in {"ready", "awaiting_access", "submission_unknown"}
                        and module_source(row.get("query_id")))
    unreviewed_followup = [row for row in source_work or []
                           if row.get("reason") == "FOLLOWUP_RESULT_REVIEW_REQUIRED"]
    unresolved_count = len(unresolved) + len(dispositions) + len(pending_reopens) + len(uncovered_aliases)
    if batches and not raw_pending and not open_queries and not unreviewed_followup \
            and not selected_pending and unresolved_count == 0:
        status = "normal_complete"
    elif (not raw_pending and not open_queries and not unreviewed_followup and not selected_pending
          and not pending_reopens and not uncovered_aliases and not dispositions
          and unresolved and len(waiting) == len(unresolved)):
        status = "waiting"
    elif (not raw_pending and not open_queries and not unreviewed_followup and not selected_pending
          and not pending_reopens and not uncovered_aliases and not dispositions
          and unresolved and len(limited) == len(unresolved)):
        status = "limited"
    else:
        status = "in_progress"
    return {"revision": REVISION, "status": status, "batches": batches,
        "batch_review_history": [{"event_id": row["event_id"], "batch_id": row["batch_id"],
            "batch_snapshot": row["batch_snapshot"], "recorded_at": row["recorded_at"]}
            for row in history if row["kind"] == "batch_review"],
        "open_source_query_ids": sorted({qid for qid in open_queries if qid}),
        "unreviewed_followup_run_ids": sorted({row.get("source_run_id") for row in unreviewed_followup
                                               if row.get("source_run_id")}),
        "scope_pending": dispositions, "triage_pending": unresolved,
        "selected_pending_handoff": selected_pending, "reopen_pending": pending_reopens,
        "identity_change_impact_pending": uncovered_aliases,
        "waiting_count": len(waiting), "limited_count": len(limited),
        "current_version_sha256": sha256_json({"candidate_versions": sorted(candidate_versions),
            "product_scope_sha256": sha256_json(task.get("product_scope", {})),
            "batch_materials": [(row["batch_id"], row["received_material_sha256"])
                                for row in batches if "received_material_sha256" in row],
            "records": [(row["candidate_id"], row["scenario_id"], row["jurisdiction"],
                         row["right_type"], (row.get("annotation") or {}).get("annotation_id")) for row in records]}),
        "completion_meaning": "module_05_only; downstream_verification_and_publication_separate"}


def work_entries(stage: dict) -> list[dict]:
    result = []
    for row in stage.get("selected_pending_handoff", []):
        result.append({**{key: row[key] for key in SCOPE}, "kind": "agent_investigation",
            "state": "awaiting_review", "reason": "TRIAGE_SELECTED_HANDOFF_REQUIRED",
            "annotation_id": row["annotation"]["annotation_id"]})
    for row in stage.get("reopen_pending", []):
        result.append({**{key: row[key] for key in SCOPE}, "kind": "agent_investigation",
            "state": "awaiting_review", "reason": row["reason"],
            "reopen_event_id": row["reopen_event_id"]})
    for alias in stage.get("identity_change_impact_pending", []):
        result.append({"kind": "agent_investigation", "state": "awaiting_review",
            "reason": alias["reason"], "identity_correction_event_id": alias["identity_correction_event_id"],
            "old_candidate_ids": alias["old_candidate_ids"],
            "current_candidate_ids": alias["current_candidate_ids"],
            "unreviewed_annotation_ids": alias["unreviewed_annotation_ids"]})
    return result


def light_triage_pending(view: dict) -> bool:
    """Preexisting acquired work takes precedence over starting new sources."""
    return any(row.get("reason") in {"CANDIDATE_TRIAGE_REQUIRED", "TRIAGE_CHANGE_REVIEW_REQUIRED",
        "TRIAGE_ATTRIBUTION_REQUIRED", "TRIAGE_IDENTITY_CHANGE_IMPACT_REQUIRED",
        "TRIAGE_SELECTED_HANDOFF_REQUIRED",
        "SOURCE_RESULTS_PENDING_PROCESSING", "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID",
        "FOLLOWUP_RESULT_REVIEW_REQUIRED"} and row.get("state") in {"ready", "awaiting_review"}
        for row in view.get("entries", []))


def prioritize_work(entries: list[dict], stage: dict) -> list[dict]:
    """Sort the same obligations; old receipts win ties, never discard work."""
    age = {}
    run_age = {}
    for batch in stage.get("batches", []):
        run_age[batch["batch_id"]] = batch["received_order"]
        for cid in batch["candidate_ids"]:
            age[cid] = min(batch["received_order"], age.get(cid, batch["received_order"]))
    ranks = {"TRIAGE_CHANGE_REVIEW_REQUIRED": 0, "TRIAGE_ATTRIBUTION_REQUIRED": 0,
        "TRIAGE_IDENTITY_CHANGE_IMPACT_REQUIRED": 0,
        "SOURCE_RESULTS_PENDING_PROCESSING": 1, "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID": 1,
        "CANDIDATE_TRIAGE_REQUIRED": 2, "TRIAGE_SELECTED_HANDOFF_REQUIRED": 3,
        "FOLLOWUP_RESULT_REVIEW_REQUIRED": 3}
    shared = {}
    for row in entries:
        key = next((str(row[field]) for field in ("source_run_id", "query_id", "evidence_obligation_id")
                    if row.get(field)), None)
        if key:
            shared.setdefault(key, set()).add(row.get("candidate_id") or row.get("work_id"))
    output = []
    for original in entries:
        row = dict(original)
        reason = row.get("reason")
        rank = ranks.get(reason, 5 if row.get("kind") != "source_lookup" else 6)
        shared_key = next((str(row[field]) for field in ("source_run_id", "query_id", "evidence_obligation_id")
                           if row.get(field)), None)
        shared_dependency = bool(shared_key and len(shared.get(shared_key, ())) > 1)
        if shared_dependency and row.get("kind") != "source_lookup":
            rank = min(rank, 1)
        receipt_age = age.get(row.get("candidate_id"), run_age.get(row.get("source_run_id"), 10**9))
        row["triage_priority"] = {"rank": rank, "received_order": receipt_age,
            "basis": ("material_change_or_conflict" if rank == 0 else
                      "shared_dependency" if shared_dependency else
                      "retained_material_review" if rank <= 3 else "independent_necessary_work")}
        output.append(row)
    return sorted(output, key=lambda row: (row["triage_priority"]["rank"],
        row["triage_priority"]["received_order"], row.get("work_id", "")))

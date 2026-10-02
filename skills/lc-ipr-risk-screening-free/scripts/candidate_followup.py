"""05B candidate follow-up classification and append-only result reviews.

The existing discovery planner and source ledger remain the authority for
requests and consumption. This module binds one candidate question to those
exact rows/runs; it does not create a second execution or quota counter.
"""
from __future__ import annotations

from pathlib import Path
import re

from common import atomic_write_json, load_json, now_iso, sha256_json, stable_id

REVISION = "candidate-followup-v1"
EVENTS = "candidate_followup_events"
LOCATOR_KEYS = ("record_number", "serial_number", "publication_number",
                "application_number", "source_record_id", "record_url", "document")
EXPANSION_KEYS = ("include_related", "expand_related", "follow_citations",
                  "family_members", "search_related", "browse_results")
EXACT_CONTROL_KEYS = set(LOCATOR_KEYS) | {"q", "candidate_id", "mode", "strategy",
    "query_compiler_revision", "language", "hl", "gl", "page", "page_number", "section"}


def enabled(task: dict | None) -> bool:
    value = (task or {}).get("triage_followup_revision")
    if value is None:
        return False
    if value != REVISION or (task or {}).get("triage_scope_revision") != "candidate-triage-scope-v1":
        raise ValueError("CANDIDATE_FOLLOWUP_REVISION_INVALID")
    return True


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value) -> bool:
    return isinstance(value, list) and bool(value) and all(_text(item) for item in value) and len(value) == len(set(value))


def _normal(value) -> str:
    return "".join(char for char in str(value or "").upper() if char.isalnum())


def request_class(provider: str, operation: str, params: dict, *, locator: dict | None = None) -> str:
    """Classify what the wire request can return, not its purpose label."""
    if not isinstance(params, dict):
        return "invalid"
    locator_values = [_normal(params.get(key)) for key in LOCATOR_KEYS if _text(params.get(key))]
    exact_locator = len(set(locator_values)) == 1 and bool(locator_values)
    query = _normal(params.get("q"))
    reviewed_locator = _normal((locator or {}).get("value"))
    query_contains_locator = bool(reviewed_locator and query and reviewed_locator in query)
    if query_contains_locator and not exact_locator:
        locator_values = [reviewed_locator]
        exact_locator = True
    broad_query = bool(query and (not exact_locator or query != locator_values[0]))
    controls = set(EXACT_CONTROL_KEYS)
    # These adapters need wire selectors in addition to the record locator.
    # Accept only a same-record selector; family expansion remains discovery.
    if operation == "candidate_detail" and exact_locator and not broad_query:
        number = locator_values[0]
        if provider == "serpapi_google_patents":
            match = re.fullmatch(r"patent/([A-Za-z]{2}[A-Za-z0-9]+)/[a-z]{2}", str(params.get("patent_id") or ""))
            if match and _normal(match.group(1)) == number:
                controls.add("patent_id")
        elif provider == "epo_ops":
            if (_normal(params.get("document")) == number
                    and params.get("detail_operation") in {"biblio", "fulltext", "images", "legal"}):
                controls.update({"document", "detail_operation"})
        if controls != EXACT_CONTROL_KEYS and params.get("right_type") in {"patent", "utility_model", "design"}:
            controls.add("right_type")
    expansion = (any(params.get(key) not in (None, False, "", [], 0) for key in EXPANSION_KEYS)
        or any(key not in controls and value not in (None, False, "", [], 0)
               for key, value in params.items()))
    broad_operation = operation in {"search", "patent_recall", "design_recall", "trademark_recall", "family_search"}
    if exact_locator and (broad_query or expansion or broad_operation):
        return "mixed"
    if broad_query or expansion or broad_operation or not exact_locator:
        return "discovery"
    if operation in {"candidate_verification", "candidate_detail", "document_retrieval", "number_lookup"}:
        return "targeted"
    return "discovery"


def action_errors(action: dict, *, known_evidence: set[str] | None = None) -> list[str]:
    """05B decision-time minimum action contract; historical actions bypass it."""
    errors = []
    basis = action.get("followup_basis")
    if (not isinstance(basis, dict) or not all(_text(basis.get(key)) for key in
            ("missing_fact", "decision_effect", "evidence_needed", "existing_material_review",
             "completion_condition", "new_value"))
            or not _strings(basis.get("obligation_ids"))
            or not isinstance(basis.get("existing_evidence_refs"), list)
            or not all(_text(ref) for ref in basis["existing_evidence_refs"])):
        errors.append("FOLLOWUP_MINIMUM_BASIS_REQUIRED")
    elif known_evidence is not None and not set(basis["existing_evidence_refs"]) <= known_evidence:
        errors.append("FOLLOWUP_EXISTING_EVIDENCE_UNKNOWN")
    kind = action.get("kind")
    if kind == "agent_read":
        existing_refs = basis.get("existing_evidence_refs") if isinstance(basis, dict) else None
        if (not _strings(action.get("evidence_refs"))
                or not isinstance(existing_refs, list)
                or not all(_text(ref) for ref in existing_refs)
                or not set(action["evidence_refs"]) <= set(existing_refs)):
            errors.append("FOLLOWUP_LOCAL_MATERIAL_REQUIRED")
    elif kind == "source_lookup":
        actual = request_class(action.get("provider"), action.get("operation"), action.get("params"))
        if actual != "targeted":
            errors.append("FOLLOWUP_DISCOVERY_ROUTE_REQUIRED")
        locator = action.get("target_locator")
        if (not isinstance(locator, dict) or locator.get("kind") not in LOCATOR_KEYS
                or not _text(locator.get("value")) or not _strings(locator.get("evidence_refs"))
                or not _text(locator.get("unique_reason"))
                or not isinstance(action.get("params"), dict)
                or _normal(action["params"].get(locator["kind"])) != _normal(locator["value"])):
            errors.append("FOLLOWUP_EXACT_LOCATOR_REQUIRED")
        elif known_evidence is not None and not set(locator["evidence_refs"]) <= known_evidence:
            errors.append("FOLLOWUP_LOCATOR_EVIDENCE_UNKNOWN")
    elif kind == "discovery_binding":
        if (not _text(action.get("query_id")) or action.get("request_mode") not in {"discovery", "mixed"}
                or not _text(action.get("request_scope_reason"))):
            errors.append("FOLLOWUP_DISCOVERY_BINDING_REQUIRED")
        if action.get("request_mode") == "mixed" and not _strings(action.get("verification_obligation_ids")):
            errors.append("FOLLOWUP_MIXED_DUAL_OBLIGATION_REQUIRED")
        if action.get("request_mode") == "mixed":
            locator = action.get("target_locator")
            if (not isinstance(locator, dict) or locator.get("kind") not in LOCATOR_KEYS
                    or not _text(locator.get("value")) or not _strings(locator.get("evidence_refs"))
                    or not _text(locator.get("unique_reason"))):
                errors.append("FOLLOWUP_MIXED_LOCATOR_REQUIRED")
            elif known_evidence is not None and not set(locator["evidence_refs"]) <= known_evidence:
                errors.append("FOLLOWUP_LOCATOR_EVIDENCE_UNKNOWN")
    elif kind == "user_information":
        if not _text(action.get("user_exclusive_reason")):
            errors.append("FOLLOWUP_USER_EXCLUSIVE_REASON_REQUIRED")
    elif kind == "professional_review":
        # A professional opinion is an external dependency, not a source query.
        # Bind it to the retained material already reviewed and keep the question
        # explicit; the result recorder may then record a waiting state without
        # claiming a hard source limit or inventing an opinion.
        if not _text(action.get("question")):
            errors.append("FOLLOWUP_PROFESSIONAL_QUESTION_REQUIRED")
        if any(key in action for key in ("provider", "operation", "params", "query_id", "target_locator")):
            errors.append("FOLLOWUP_PROFESSIONAL_MUST_NOT_BE_SOURCE_LOOKUP")
        refs = basis.get("existing_evidence_refs") if isinstance(basis, dict) else None
        if not _strings(refs):
            errors.append("FOLLOWUP_PROFESSIONAL_EVIDENCE_REQUIRED")
    return errors


def events(task: dict) -> list[dict]:
    rows = task.get(EVENTS, [])
    if not isinstance(rows, list):
        raise ValueError("FOLLOWUP_EVENTS_INVALID")
    previous = ""
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("previous_event_id") != previous:
            raise ValueError("FOLLOWUP_EVENTS_CHANGED")
        unsigned = {key: value for key, value in row.items() if key != "event_id"}
        expected = stable_id("FOLLOWUP", task["task_id"], sha256_json(unsigned))
        if row.get("event_id") != expected or expected in seen:
            raise ValueError("FOLLOWUP_EVENTS_CHANGED")
        seen.add(expected)
        previous = expected
    return rows


def latest_event(task: dict, kind: str, annotation_id: str, action_id: str) -> dict | None:
    return next((row for row in reversed(events(task)) if row.get("kind") == kind
        and row.get("annotation_id") == annotation_id and row.get("action_id") == action_id), None)


def verify_review_sources(task: dict, evidence: dict, supplement: dict | None = None, *,
                          ledger: dict | None = None) -> None:
    from decision_workflow import evidence_index
    indexed = evidence_index(evidence, supplement)
    runs = {run.get("run_id"): run for run in evidence.get("source_runs", [])}
    for event in events(task):
        if event.get("kind") != "result_review":
            continue
        if event.get("run_id") and (event["run_id"] not in runs
                or sha256_json(runs[event["run_id"]]) != event.get("run_sha256")):
            raise ValueError("FOLLOWUP_REVIEW_RUN_CHANGED")
        if any(ref not in indexed or sha256_json(indexed[ref]) != digest
               for ref, digest in event.get("result_evidence_sha256", {}).items()):
            raise ValueError("FOLLOWUP_REVIEW_EVIDENCE_CHANGED")
        resolution = event.get("material_resolution")
        if event.get("outcome") == "resolved_by_material":
            from common import sha256_file
            if not isinstance(resolution, dict) or not resolution.get("replacement_materials"):
                raise ValueError("FOLLOWUP_REPLACEMENT_MATERIAL_REQUIRED")
            if ledger is not None:
                annotations = [item for item in ledger.get("annotations", [])
                    if item.get("annotation_id") == resolution.get("resolved_annotation_id")]
                if len(annotations) != 1 or sha256_json(annotations[0]) != resolution.get("resolved_annotation_sha256"):
                    raise ValueError("FOLLOWUP_REPLACEMENT_DECISION_CHANGED")
            for material in resolution["replacement_materials"]:
                ref = material.get("evidence_id")
                if ref not in indexed or sha256_json(indexed[ref]) != material.get("evidence_sha256"):
                    raise ValueError("FOLLOWUP_REPLACEMENT_EVIDENCE_CHANGED")
                review_digest = material.get("source_review_sha256")
                if review_digest and not any(sha256_json(item) == review_digest
                        for item in evidence.get("record_content_reviews", [])):
                    raise ValueError("FOLLOWUP_REPLACEMENT_READING_CHANGED")
            files = list(resolution.get("original_raw_sha256", {}).items())
            files += [(item.get("path"), item.get("sha256")) for material in resolution["replacement_materials"]
                      for item in material.get("file_refs", [])]
            if not files or any(not isinstance(path, str) or not Path(path).is_file()
                                or sha256_file(Path(path)) != digest for path, digest in files):
                raise ValueError("FOLLOWUP_REPLACEMENT_FILE_CHANGED")
            reviews = {item.get("review_id"): item for item in evidence.get("recovery_reviews", [])}
            if any(rid not in reviews or sha256_json(reviews[rid]) != digest
                   for rid, digest in resolution.get("recovery_review_sha256", {}).items()):
                raise ValueError("FOLLOWUP_REVIEW_RECOVERY_CHANGED")



def _resolved_material(task_dir, task, evidence, supplement, candidate, old, action, run, decision, request):
    """Review an old acquisition against separately retained, actually read content.

    Original result refs continue to belong to the original run. Replacement
    bytes and the new decision are a second, explicit binding, never a rewrite
    of source status or an assertion of current legal effect.
    """
    from common import resolve_retained_path
    from decision_workflow import evidence_index
    from recovery_stage_b import effective_submission
    if (task.get("retrieval_workflow_revision") != "api-first-v3" or not run
            or action.get("kind") != "source_lookup"
            or not action.get("required_facts")
            or not set(action["required_facts"]) <= {"protection_content", "representative_figures", "independent_claims", "design_views"}
            or run.get("status") not in {"success", "failed", "access_limited"}
            or effective_submission(evidence, run) != "submitted"
            or request.get("original_run_sha256") != sha256_json(run)):
        raise ValueError("FOLLOWUP_MATERIAL_ORIGINAL_RUN_NOT_RESOLVED")
    annotation = decision.get("annotation", {})
    if (not decision.get("current") or decision.get("decision") not in {"not_selected", "needs_info"}
            or annotation.get("annotation_id") == old["annotation_id"]
            or request.get("resolved_annotation_id") != annotation.get("annotation_id")
            or request.get("resolved_annotation_sha256") != sha256_json(annotation)):
        raise ValueError("FOLLOWUP_MATERIAL_UPDATED_DECISION_REQUIRED")
    remaining = decision.get("next_actions", [])
    if (decision["decision"] == "needs_info" and (not remaining or any(
            item.get("kind") != "user_information" or action_errors(item)
            for item in remaining))):
        raise ValueError("FOLLOWUP_MATERIAL_SOURCE_WORK_REMAINS")
    if (decision["decision"] == "not_selected" and remaining
            or not _strings(request.get("resolved_facts"))
            or set(request["resolved_facts"]) != set(action["required_facts"])
            or not _text(request.get("original_response_reading"))):
        raise ValueError("FOLLOWUP_MATERIAL_RESOLUTION_SCOPE_REQUIRED")
    raw_hashes = request.get("original_raw_sha256")
    paths = run.get("raw_paths", [])
    if not paths or not isinstance(raw_hashes, dict) or set(raw_hashes) != set(paths):
        raise ValueError("FOLLOWUP_MATERIAL_ORIGINAL_RECEIPT_REQUIRED")
    for path, digest in raw_hashes.items():
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
            raise ValueError("FOLLOWUP_MATERIAL_ORIGINAL_RECEIPT_REQUIRED")
        resolve_retained_path(task_dir, path, expected_sha256=digest)
    if len(paths) == 1 and raw_hashes[paths[0]] != run.get("payload_digest"):
        raise ValueError("FOLLOWUP_MATERIAL_ORIGINAL_RECEIPT_CHANGED")
    recovery = [item for item in evidence.get("recovery_reviews", [])
        if item.get("source_run_id") == run["run_id"] and item.get("source_run_sha256") == sha256_json(run)]
    if run.get("status") != "success" and not any(
            item.get("kind") == "failure_review" or item.get("kind") == "unknown_check"
            and item.get("outcome") == "submitted_failed" for item in recovery):
        raise ValueError("FOLLOWUP_MATERIAL_FAILURE_REVIEW_REQUIRED")
    materials = request.get("replacement_materials")
    if not isinstance(materials, list) or not materials:
        raise ValueError("FOLLOWUP_REPLACEMENT_MATERIAL_REQUIRED")
    indexed = evidence_index(evidence, supplement)
    seen, bindings = set(), []
    number, country = _normal(candidate.get("publication_number")), candidate.get("jurisdiction")
    if not number or country != old.get("jurisdiction") or not number.startswith(str(country)):
        raise ValueError("FOLLOWUP_REPLACEMENT_EXACT_IDENTITY_REQUIRED")
    expected_level = "image_comparison" if set(action["required_facts"]) & {"representative_figures", "design_views"} else "independent_claims"
    if annotation.get("reading_level") != expected_level:
        raise ValueError("FOLLOWUP_REPLACEMENT_READING_REQUIRED")
    for material in materials:
        if not isinstance(material, dict):
            raise ValueError("FOLLOWUP_REPLACEMENT_MATERIAL_REQUIRED")
        ref = material.get("evidence_id")
        entry = indexed.get(ref, {})
        if (not entry or ref in seen or ref not in annotation.get("evidence_refs", [])
                or entry.get("source_run_id") == run["run_id"]
                or _normal(material.get("publication_number")) != number
                or material.get("jurisdiction") != country
                or material.get("reading_level") != expected_level
                or not all(_text(material.get(key)) for key in ("identity_reading", "content_reading", "limitations"))
                or not isinstance(material.get("pages_read"), list) or not material["pages_read"]
                or any(type(page) is not int or page < 1 for page in material["pages_read"])):
            raise ValueError("FOLLOWUP_REPLACEMENT_READING_OR_IDENTITY_INVALID")
        seen.add(ref)
        application = material.get("application_identity_reading")
        if application is not None:
            if (not isinstance(application, dict) or not _text(application.get("pdf_cover"))
                    or not _text(application.get("ops"))
                    or _normal(application["ops"]) != _normal(candidate.get("application_number"))
                    or len(_normal(application["pdf_cover"])) < 6
                    or _normal(application["pdf_cover"]) not in _normal(application["ops"])):
                raise ValueError("FOLLOWUP_REPLACEMENT_APPLICATION_MISMATCH")
        source_review = None
        if entry.get("source_run_id"):
            runs = [item for item in evidence.get("source_runs", []) if item.get("run_id") == entry["source_run_id"]]
            if len(runs) != 1 or runs[0].get("status") != "success":
                raise ValueError("FOLLOWUP_REPLACEMENT_SOURCE_INCOMPLETE")
            from source_result_processing import progress
            processed = progress(task_dir, runs[0], evidence)
            source_review = processed.get("record_content_review")
            if (not processed.get("material_processing_complete") or not source_review
                    or source_review.get("binding", {}).get("candidate_id") != candidate.get("candidate_id")
                    or _normal(source_review.get("binding", {}).get("publication_number")) != number
                    or source_review.get("binding", {}).get("jurisdiction") != country):
                raise ValueError("FOLLOWUP_REPLACEMENT_SOURCE_INCOMPLETE")
            records = entry.get("payload", {}).get("candidates", [])
            exact = [item for item in records if _normal(item.get("publication_number")) == number
                     and item.get("jurisdiction") == country]
            if len(exact) != 1:
                raise ValueError("FOLLOWUP_REPLACEMENT_EXACT_IDENTITY_REQUIRED")
            media = exact[0].get("media", [])
            allowed = {item.get("path"): item for item in media if item.get("is_thumbnail") is False}
            allowed_pages = {item.get("page_number") for item in allowed.values()}
            if not set(material["pages_read"]) <= allowed_pages:
                raise ValueError("FOLLOWUP_REPLACEMENT_UNREAD_PAGE")
        else:
            if (entry.get("kind") not in {"patent_document", "design_drawings"}
                    or entry.get("authority_scope") != "published_document_only"
                    or _normal(entry.get("publication_number")) != number
                    or entry.get("jurisdiction") != country
                    or entry.get("candidate_id") not in {None, candidate.get("candidate_id")}
                    or not str(entry.get("path", "")).lower().endswith(".pdf")
                    or type(entry.get("page_count")) is not int
                    or max(material["pages_read"]) > entry["page_count"]
                    or 1 not in material["pages_read"]):
                raise ValueError("FOLLOWUP_REPLACEMENT_EXACT_DOCUMENT_REQUIRED")
            allowed = {entry["path"]: entry}
        files = material.get("file_refs")
        if (not isinstance(files, list) or not files or any(not isinstance(item, dict) for item in files)
                or {item.get("path") for item in files} != set(allowed)):
            raise ValueError("FOLLOWUP_REPLACEMENT_FILE_BINDING_REQUIRED")
        for item in files:
            archived = allowed[item["path"]]
            if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) or item["sha256"] != archived.get("sha256"):
                raise ValueError("FOLLOWUP_REPLACEMENT_FILE_CHANGED")
            path = resolve_retained_path(task_dir, item["path"], expected_sha256=item["sha256"], expected_bytes=archived.get("bytes"))
            if not entry.get("source_run_id"):
                with path.open("rb") as handle:
                    if handle.read(5) != b"%PDF-":
                        raise ValueError("FOLLOWUP_REPLACEMENT_NOT_ORIGINAL_PDF")
        canonical_files = [{"path": str(resolve_retained_path(task_dir, item["path"], expected_sha256=item["sha256"])),
            "sha256": item["sha256"]} for item in files]
        bindings.append({**material, "file_refs": canonical_files, "evidence_sha256": sha256_json(entry),
            "source_review_sha256": sha256_json(source_review) if source_review else None})
    return {"resolved_annotation_id": annotation["annotation_id"],
        "resolved_annotation_sha256": sha256_json(annotation),
        "resolved_facts": list(request["resolved_facts"]),
        "original_response_reading": request["original_response_reading"],
        "original_raw_sha256": {str(resolve_retained_path(task_dir, path, expected_sha256=digest)): digest
            for path, digest in raw_hashes.items()},
        "effective_submission": "submitted",
        "recovery_review_sha256": {item["review_id"]: sha256_json(item) for item in recovery},
        "replacement_materials": bindings,
        "remaining_user_action_ids": [item["action_id"] for item in remaining]}


def professional_wait_proof(task, evidence, record, action, *, supplement=None):
    """Bind a current M05 expert dependency to its retained, unchanged materials."""
    from decision_workflow import evidence_index
    if (not enabled(task) or not record.get("current") or record.get("decision") != "needs_info"
            or action.get("kind") != "professional_review"):
        return None
    annotation = record.get("annotation", {})
    if action not in record.get("next_actions", []):
        return None
    event = latest_event(task, "result_review", annotation.get("annotation_id"), action.get("action_id"))
    scope = {key: record.get(key) for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type")}
    indexed = evidence_index(evidence, supplement)
    refs = event.get("result_evidence_refs", []) if event else []
    if (not event or event.get("outcome") != "waiting" or event.get("run_id") or event.get("query_id")
            or any(event.get(key) != value for key, value in scope.items())
            or not _text(event.get("dependency")) or not _text(event.get("resume_condition"))
            or not refs or not set(refs) <= set(action.get("followup_basis", {}).get("existing_evidence_refs", []))
            or action_errors(action, known_evidence=set(indexed))
            or set(event.get("result_evidence_sha256", {})) != set(refs)
            or any(ref not in indexed or sha256_json(indexed[ref]) != event["result_evidence_sha256"][ref]
                   for ref in refs)):
        return None
    return {"kind": "candidate_followup_professional_wait", **scope,
        "annotation_id": annotation["annotation_id"], "annotation_sha256": sha256_json(annotation),
        "action_id": action["action_id"], "action_sha256": sha256_json(action),
        "event_id": event["event_id"], "event_sha256": sha256_json(event),
        "result_evidence_sha256": dict(event["result_evidence_sha256"]),
        "dependency": event["dependency"], "resume_condition": event["resume_condition"],
        "official_verification": "not_verified"}


def pending_review_entries(task, evidence, plan, ledger, supplement=None) -> list[dict]:
    """An acquired follow-up remains work even if a later triage decision exists."""
    if not enabled(task):
        return []
    verify_review_sources(task, evidence, supplement, ledger=ledger)
    reviewed = {(row.get("annotation_id"), row.get("action_id"), row.get("run_id")): row
                for row in events(task) if row.get("kind") == "result_review"}
    bindings = {(row.get("annotation_id"), row.get("action_id")): row
                for row in events(task) if row.get("kind") == "discovery_binding"}
    plan_rows = {(provider, row.get("query_id"), sha256_json(row)): row
                 for provider, rows in plan.get("queries", {}).items() for row in rows}
    result = []
    for annotation in ledger.get("annotations", []):
        if not isinstance(annotation, dict) or annotation.get("decision") != "needs_info":
            continue
        for action in annotation.get("next_actions", []):
            if not isinstance(action, dict) or action.get("kind") not in {"source_lookup", "discovery_binding"}:
                continue
            aid, ann_id = action.get("action_id"), annotation.get("annotation_id")
            binding = bindings.get((ann_id, aid)) if action.get("kind") == "discovery_binding" else None
            if action.get("kind") == "discovery_binding" and not binding:
                continue
            for run in evidence.get("source_runs", []):
                if run.get("submission_state") == "not_submitted" or run.get("status") in {"cancelled", "not_applicable"}:
                    continue
                key = (run.get("provider"), run.get("query_id"), run.get("plan_entry_sha256"))
                row = plan_rows.get(key)
                if row is None:
                    continue
                if binding:
                    applies = (binding.get("provider"), binding.get("query_id"), binding.get("plan_entry_sha256")) == key
                else:
                    applies = (row.get("triage_decision_id") == ann_id and row.get("triage_action_id") == aid)
                if not applies:
                    continue
                prior = reviewed.get((ann_id, aid, run.get("run_id")))
                if prior:
                    continue
                scope = {field: annotation.get(field) for field in
                         ("candidate_id", "scenario_id", "jurisdiction", "right_type")}
                result.append({**scope, "kind": "agent_investigation", "state": "awaiting_review",
                    "reason": "FOLLOWUP_RESULT_REVIEW_REQUIRED", "action_id": aid,
                    "query_id": run.get("query_id"), "source_run_id": run.get("run_id")})
    return result


def _append(task: dict, row: dict) -> dict:
    prior = events(task)
    entry = {**row, "previous_event_id": prior[-1]["event_id"] if prior else ""}
    entry["event_id"] = stable_id("FOLLOWUP", task["task_id"], sha256_json(entry))
    task.setdefault(EVENTS, []).append(entry)
    return entry


def _context(task_dir: Path):
    from annotate_materiality import load_materiality_ledger
    from decision_workflow import effective_decision
    from workflow_v24 import scenario_supplement
    task = load_json(task_dir / "task.json")
    if not enabled(task):
        raise ValueError("FOLLOWUP_NOT_ENABLED")
    candidates = load_json(task_dir / "normalized-candidates.json")
    evidence = load_json(task_dir / "evidence.json")
    plan = load_json(task_dir / "search-plan.json")
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    events(task)
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    verify_review_sources(task, evidence, supplement, ledger=ledger)
    def resolved(*args, **kwargs):
        kwargs.setdefault("supplement", supplement)
        return effective_decision(*args, **kwargs)
    return task, candidates, evidence, plan, ledger, resolved, supplement


def _action(task, candidates, evidence, ledger, effective_decision, request):
    found = [(collection, candidate) for collection in ("patents", "trademarks", "copyright_assets", "enforcement")
             for candidate in candidates.get(collection, []) if candidate.get("candidate_id") == request.get("candidate_id")]
    if len(found) != 1:
        raise ValueError("FOLLOWUP_CANDIDATE_UNKNOWN")
    collection, candidate = found[0]
    result = effective_decision(task, ledger, collection, candidate, request.get("scenario_id"),
        request.get("jurisdiction"), request.get("right_type"), evidence=evidence)
    if not result.get("current") or result.get("decision") != "needs_info":
        raise ValueError("FOLLOWUP_CURRENT_NEEDS_INFO_REQUIRED")
    action = next((item for item in result.get("next_actions", [])
        if item.get("action_id") == request.get("action_id")), None)
    if action is None:
        raise ValueError("FOLLOWUP_ACTION_UNKNOWN")
    return result, action


def _historical_action(ledger, request):
    rows = [row for row in ledger.get("annotations", []) if row.get("annotation_id") == request.get("annotation_id")]
    if len(rows) != 1 or rows[0].get("decision") != "needs_info":
        raise ValueError("FOLLOWUP_OLD_DECISION_REQUIRED")
    row = rows[0]
    if any(row.get(key) != request.get(key) for key in
           ("candidate_id", "scenario_id", "jurisdiction", "right_type")):
        raise ValueError("FOLLOWUP_OLD_SCOPE_MISMATCH")
    action = next((item for item in row.get("next_actions", [])
                   if item.get("action_id") == request.get("action_id")), None)
    if action is None:
        raise ValueError("FOLLOWUP_ACTION_UNKNOWN")
    return row, action


def _plan_row(plan, query_id):
    found = [(provider, row) for provider, rows in plan.get("queries", {}).items()
             for row in rows if row.get("query_id") == query_id]
    if len(found) != 1:
        raise ValueError("FOLLOWUP_QUERY_UNKNOWN")
    return found[0]


def dispatch_error(task, provider, row, candidates, ledger, evidence, supplement=None) -> str | None:
    if not enabled(task):
        return None
    if row.get("action_purpose") == "discovery":
        bindings = [event for event in events(task) if event.get("kind") == "discovery_binding"
                    and event.get("query_id") == row.get("query_id")]
        if not bindings:
            return None  # Ordinary discovery remains under the 03A/04C gates.
        from decision_workflow import effective_decision
        def resolved(*args, **kwargs):
            kwargs.setdefault("supplement", supplement)
            return effective_decision(*args, **kwargs)
        for binding in bindings:
            if binding.get("provider") != provider or binding.get("plan_entry_sha256") != sha256_json(row):
                return "FOLLOWUP_DISCOVERY_BINDING_STALE"
            try:
                decision, action = _action(task, candidates, evidence, ledger, resolved, binding)
            except ValueError:
                return "FOLLOWUP_DISCOVERY_DECISION_STALE"
            if (decision["annotation"]["annotation_id"] != binding["annotation_id"]
                    or action.get("kind") != "discovery_binding" or action.get("query_id") != row.get("query_id")
                    or action.get("request_mode") != binding.get("request_mode")):
                return "FOLLOWUP_DISCOVERY_BINDING_STALE"
        return None
    if row.get("triage_action_id") and str(row.get("action_purpose") or "").startswith("needs_info:"):
        from provider_utils import PLAN_META_KEYS
        from common import DECISION_PLAN_META_KEYS
        params = {key: value for key, value in row.items() if key not in PLAN_META_KEYS and key not in DECISION_PLAN_META_KEYS}
        if request_class(provider, row.get("operation"), params) != "targeted":
            return "FOLLOWUP_DISCOVERY_ROUTE_REQUIRED"
    return None


def record_binding(task_dir: Path, request: dict) -> dict:
    """Bind one existing discovery row to a candidate question before execution."""
    from provider_utils import evidence_lock
    with evidence_lock(task_dir):
        task, candidates, evidence, plan, ledger, effective, supplement = _context(task_dir)
        decision, action = _action(task, candidates, evidence, ledger, effective, request)
        if action.get("kind") != "discovery_binding":
            raise ValueError("FOLLOWUP_DISCOVERY_ACTION_REQUIRED")
        provider, row = _plan_row(plan, action["query_id"])
        if (request.get("query_id") != row["query_id"] or row.get("action_purpose") != "discovery"
                or row.get("scenario_id") not in (None, decision["scenario_id"])
                or row.get("jurisdiction") != decision["jurisdiction"]
                or row.get("right_type") != decision["right_type"]):
            raise ValueError("FOLLOWUP_DISCOVERY_SCOPE_MISMATCH")
        from provider_utils import PLAN_META_KEYS
        params = {key: value for key, value in row.items() if key not in PLAN_META_KEYS}
        actual_class = request_class(provider, row.get("operation"), params,
                                     locator=action.get("target_locator"))
        if actual_class != action["request_mode"]:
            raise ValueError("FOLLOWUP_ACTUAL_REQUEST_CLASS_MISMATCH")
        if action["request_mode"] == "mixed":
            locator = action["target_locator"]
            if (_normal(params.get(locator["kind"])) != _normal(locator["value"])
                    and _normal(locator["value"]) not in _normal(params.get("q"))):
                raise ValueError("FOLLOWUP_MIXED_LOCATOR_MISMATCH")
        for prior in events(task):
            if (prior.get("kind") == "discovery_binding"
                    and prior.get("candidate_id") == decision["candidate_id"]
                    and prior.get("annotation_id") == decision["annotation"]["annotation_id"]
                    and prior.get("action_id") == action["action_id"]
                    and prior.get("query_id") == row["query_id"]
                    and prior.get("plan_entry_sha256") == sha256_json(row)):
                return prior
        if any(run.get("query_id") == row["query_id"] and run.get("provider") == provider
               and run.get("plan_entry_sha256") == sha256_json(row)
               and run.get("submission_state") != "not_submitted" for run in evidence.get("source_runs", [])):
            raise ValueError("FOLLOWUP_BIND_BEFORE_EXECUTION_REQUIRED")
        from discovery_budget import dispatch_block as budget_block
        error = budget_block(task, plan, evidence, provider, row)
        if error:
            raise ValueError(error)
        binding = {"kind": "discovery_binding", "candidate_id": decision["candidate_id"],
            "scenario_id": decision["scenario_id"], "jurisdiction": decision["jurisdiction"],
            "right_type": decision["right_type"], "annotation_id": decision["annotation"]["annotation_id"],
            "action_id": action["action_id"], "query_id": row["query_id"], "provider": provider,
            "plan_entry_sha256": sha256_json(row), "request_mode": action["request_mode"],
            "obligation_ids": action["followup_basis"]["obligation_ids"],
            "verification_obligation_ids": action.get("verification_obligation_ids", []),
            "reviewer": request.get("reviewer"), "reason": request.get("reason"), "recorded_at": now_iso()}
        if not _text(binding["reviewer"]) or not _text(binding["reason"]):
            raise ValueError("FOLLOWUP_REVIEWER_REASON_REQUIRED")
        event = _append(task, binding)
        atomic_write_json(task_dir / "task.json", task)
        return event


def record_review(task_dir: Path, request: dict) -> dict:
    """Review a retained local/source result; never convert a run into a decision."""
    from provider_utils import evidence_lock
    from decision_workflow import evidence_index
    with evidence_lock(task_dir):
        task, candidates, evidence, plan, ledger, effective, supplement = _context(task_dir)
        outcome = request.get("outcome")
        old, action = _historical_action(ledger, request)
        scope = {key: old[key] for key in ("candidate_id", "scenario_id", "jurisdiction", "right_type")}
        annotation_id = old["annotation_id"]
        from annotate_materiality import iter_candidates
        matches = [(collection, candidate) for collection, candidate in iter_candidates(candidates)
                   if candidate.get("candidate_id") == old["candidate_id"]]
        if len(matches) != 1:
            raise ValueError("FOLLOWUP_CANDIDATE_UNKNOWN")
        candidate = matches[0][1]
        decision = effective(task, ledger, *matches[0], old["scenario_id"],
                             old["jurisdiction"], old["right_type"], evidence=evidence)
        if outcome == "sufficient" and (not decision.get("current")
                or decision.get("decision") not in {"selected", "not_selected"}
                or decision["annotation"]["annotation_id"] == old["annotation_id"]):
            raise ValueError("FOLLOWUP_UPDATED_DECISION_REQUIRED")
        query_id = action.get("query_id") if action.get("kind") == "discovery_binding" else request.get("query_id")
        run = None
        if action.get("kind") in {"source_lookup", "discovery_binding"}:
            provider, row = _plan_row(plan, query_id)
            if action.get("kind") == "source_lookup" and (row.get("triage_action_id") != action["action_id"]
                    or row.get("triage_decision_id") != annotation_id
                    or provider != action.get("provider") or row.get("operation") != action.get("operation")):
                raise ValueError("FOLLOWUP_SOURCE_ACTION_MISMATCH")
            if action.get("kind") == "discovery_binding" and not any(event.get("kind") == "discovery_binding"
                    and event.get("query_id") == query_id and event.get("annotation_id") == annotation_id
                    and event.get("plan_entry_sha256") == sha256_json(row) for event in events(task)):
                raise ValueError("FOLLOWUP_DISCOVERY_BINDING_MISSING")
            matches = [item for item in evidence.get("source_runs", []) if item.get("run_id") == request.get("run_id")
                and item.get("query_id") == query_id and item.get("provider") == provider
                and item.get("plan_entry_sha256") == sha256_json(row)]
            if len(matches) != 1:
                raise ValueError("FOLLOWUP_SOURCE_RUN_REQUIRED")
            run = matches[0]
        elif action.get("kind") not in {"agent_read", "professional_review"}:
            raise ValueError("FOLLOWUP_REVIEW_ACTION_UNSUPPORTED")
        refs = request.get("result_evidence_refs")
        if not isinstance(refs, list) or not all(_text(ref) for ref in refs) or not set(refs) <= set(evidence_index(evidence, supplement)):
            raise ValueError("FOLLOWUP_RESULT_EVIDENCE_INVALID")
        if run and refs:
            indexed = evidence_index(evidence, supplement)
            if not all(indexed[ref].get("source_run_id") == run.get("run_id")
                    or ref in run.get("evidence_ids", []) for ref in refs):
                raise ValueError("FOLLOWUP_RESULT_SOURCE_MISMATCH")
        local_refs = (action.get("evidence_refs", []) if action.get("kind") == "agent_read"
                      else action.get("followup_basis", {}).get("existing_evidence_refs", []))
        if not run and not set(refs) <= set(local_refs):
            raise ValueError("FOLLOWUP_LOCAL_RESULT_MISMATCH")
        if action.get("kind") == "professional_review" and outcome == "waiting" and not refs:
            raise ValueError("FOLLOWUP_PROFESSIONAL_REVIEW_BASIS_REQUIRED")
        if outcome not in {"sufficient", "continue", "waiting", "limited", "resolved_by_material"}:
            raise ValueError("FOLLOWUP_OUTCOME_INVALID")
        if outcome == "sufficient":
            if not refs or not set(refs) <= set(decision["annotation"].get("evidence_refs", [])):
                raise ValueError("FOLLOWUP_UPDATED_DECISION_EVIDENCE_REQUIRED")
        if outcome == "continue" and (not _text(request.get("unresolved_fact"))
                or not _text(request.get("next_value")) or not _text(request.get("boundary_remaining"))
                or not _text(request.get("next_action_id"))
                or request.get("next_action_id") == action["action_id"]):
            raise ValueError("FOLLOWUP_CONTINUATION_BASIS_REQUIRED")
        if outcome == "waiting" and (not _text(request.get("dependency")) or not _text(request.get("resume_condition"))):
            raise ValueError("FOLLOWUP_WAITING_DEPENDENCY_REQUIRED")
        if outcome == "limited" and (not _text(request.get("limit_evidence")) or not _text(request.get("impact"))
                or not _text(request.get("resume_condition")) or not run
                or run.get("status") not in {"access_limited", "failed"}
                or run.get("submission_state") == "unknown"
                or run.get("error_code") not in {"FREE_QUOTA_EXHAUSTED", "AUTOMATION_PROHIBITED",
                    "SOURCE_OPERATION_UNAVAILABLE", "LICENCE_DENIED"}
                or request.get("limit_evidence") != run.get("error_code")
                or request.get("no_recovery_pending") is not True):
            raise ValueError("FOLLOWUP_LIMIT_EVIDENCE_REQUIRED")
        resolution = (_resolved_material(task_dir, task, evidence, supplement, candidate, old,
            action, run, decision, request) if outcome == "resolved_by_material" else None)
        binding = {"kind": "result_review", **scope, "annotation_id": annotation_id,
            "action_id": action["action_id"], "query_id": query_id, "run_id": run.get("run_id") if run else None,
            "run_sha256": sha256_json(run) if run else None, "result_evidence_refs": refs,
            "result_evidence_sha256": {ref: sha256_json(evidence_index(evidence, supplement)[ref]) for ref in refs},
            "outcome": outcome, "reason": request.get("reason"), "reviewer": request.get("reviewer"),
            "unresolved_fact": request.get("unresolved_fact"), "next_value": request.get("next_value"),
            "boundary_remaining": request.get("boundary_remaining"), "next_action_id": request.get("next_action_id"),
            "dependency": request.get("dependency"), "resume_condition": request.get("resume_condition"),
            "limit_evidence": request.get("limit_evidence"), "impact": request.get("impact"),
            "no_recovery_pending": request.get("no_recovery_pending"),
            "recorded_at": now_iso()}
        if resolution is not None:
            binding["material_resolution"] = resolution
        if not _text(binding["reviewer"]) or not _text(binding["reason"]):
            raise ValueError("FOLLOWUP_REVIEWER_REASON_REQUIRED")
        for prior in events(task):
            if prior.get("kind") == "result_review" and all(prior.get(key) == binding.get(key)
                    for key in ("annotation_id", "action_id", "run_id", "run_sha256", "outcome", "material_resolution")):
                return prior
        event = _append(task, binding)
        atomic_write_json(task_dir / "task.json", task)
        return event

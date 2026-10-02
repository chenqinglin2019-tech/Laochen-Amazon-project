"""08B: source-request recovery facts and a bounded external retry gate."""
from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path

from common import atomic_write_json, load_json, now_iso, resolve_retained_path, sha256_file, sha256_json

REVISION = "continuous-recovery-stage-b-v1"
QUERY_FIELDS = ("q", "query", "filters", "range", "strategy", "query_compiler_revision",
                "query_image_sha256", "query_target_sha256")
TARGET_FIELDS = ("page", "page_number", "resource_id", "document_id", "publication_number",
                 "application_number", "registration_number", "serial_number", "record_number")
SUCCESS = {"success", "no_result"}
LIMIT_CODES = ("RATE_LIMIT", "QUOTA", "CREDIT", "AUTH", "LOGIN", "CAPTCHA", "MFA",
               "LICENSE", "LICENCE", "PERMISSION", "ENTITLEMENT")
REPAIR_CODES = {"USPTO_QUERY_REJECTED", "UNSUPPORTED_QUERY_SEMANTICS",
                "API_DISCOVERY_QUERY_SYNTAX_UNSUPPORTED", "EPO_QUERY_SYNTAX_REJECTED",
                "BROWSER_QUERY_SEMANTICS_UNSUPPORTED", "BROWSER_QUERY_BINDING_FAILED"}


def enabled(task: dict) -> bool:
    revision = task.get("continuous_recovery_revision")
    if revision is None:
        return False
    if revision != REVISION:
        raise ValueError("CONTINUOUS_RECOVERY_REVISION_INVALID")
    return True


def request_identity(task: dict, provider: str, value: dict) -> dict:
    params = value.get("request_params") if isinstance(value.get("request_params"), dict) else value
    query = {name: params[name] for name in QUERY_FIELDS if params.get(name) not in (None, "")}
    if not query and value.get("query"):
        query["q"] = value["query"]
    target = {name: params[name] for name in TARGET_FIELDS if params.get(name) not in (None, "")}
    # An unidentified request cannot receive a fresh automatic retry budget.
    version = sha256_json(query) if query else None
    identity = {"task_id": task.get("task_id"), "provider": provider,
                "operation": value.get("operation"), "jurisdiction": value.get("jurisdiction"),
                "right_type": value.get("right_type") or params.get("right_type"),
                "query_version_sha256": version, "target": target}
    return {**identity, "recovery_object_id": "RECOVERY-" + sha256_json(identity)[:24]}


def _reviews(evidence: dict, run: dict) -> list[dict]:
    return [review for review in evidence.get("recovery_reviews", [])
            if isinstance(review, dict) and review.get("source_run_id") == run.get("run_id")
            and review.get("source_run_sha256") == sha256_json(run)]


def _legacy_reviews(evidence: dict, run: dict) -> list[dict]:
    return [review for review in evidence.get("submission_state_reviews", [])
            if isinstance(review, dict) and review.get("source_run_id") == run.get("run_id")
            and review.get("source_run_sha256") == sha256_json(run)
            and review.get("query_id") == run.get("query_id")
            and review.get("plan_entry_sha256") == run.get("plan_entry_sha256")
            and all(review.get(key) for key in ("reviewer", "reasoning", "reviewed_at"))]


def effective_submission(evidence: dict, run: dict) -> str:
    state = run.get("submission_state")
    if state in {"submitted", "not_submitted"}:
        return state
    for review in _legacy_reviews(evidence, run):
        if review.get("method") == "pre_source_guard_audit" and review.get("submission_state") == "not_submitted":
            from workflow_v24 import _pre_source_guard_failure
            if _pre_source_guard_failure(run):
                return "not_submitted"
        if (review.get("method") == "epo_search_receipt_audit" and
                review.get("submission_state") == "submitted" and review.get("result") == "no_result"):
            return "submitted"
    for review in reversed(_reviews(evidence, run)):
        if review.get("kind") == "unknown_check":
            outcome = review.get("outcome")
            if outcome == "not_submitted":
                return "not_submitted"
            if outcome in {"submitted_running", "submitted_failed", "result_obtained"}:
                return "submitted"
    return "unknown"


def effective_result(evidence: dict, run: dict) -> str:
    if any(review.get("method") == "epo_search_receipt_audit" and
           review.get("submission_state") == "submitted" and review.get("result") == "no_result"
           for review in _legacy_reviews(evidence, run)):
        return "no_result"
    return str(run.get("status") or "unknown")


def _latest(evidence: dict, run: dict, kind: str) -> dict | None:
    return next((review for review in reversed(_reviews(evidence, run))
                 if review.get("kind") == kind), None)


def _same_runs(task: dict, evidence: dict, provider: str, row: dict) -> tuple[dict, list[dict]]:
    identity = request_identity(task, provider, row)
    if (not identity["query_version_sha256"] and not identity["target"]) or not identity["operation"]:
        return identity, []
    runs = [run for run in evidence.get("source_runs", []) if isinstance(run, dict)
            and run.get("provider") == provider and run.get("status") not in {"cancelled", "not_applicable"}
            and (request_identity(task, provider, run)["recovery_object_id"] == identity["recovery_object_id"]
                 or (run.get("query_id") == row.get("query_id") and
                     run.get("plan_entry_sha256") == sha256_json(row) and
                     not request_identity(task, provider, run)["query_version_sha256"]))]
    return identity, runs


def no_retry_audit(task, evidence, provider, row, task_dir=None):
    """Validate a confirmed failure audit; this alone is never a delivery permission."""
    if task.get('retrieval_workflow_revision') != 'api-first-v3':
        return None
    _, runs = _same_runs(task, evidence, provider, row)
    exact = [run for run in runs if run.get('query_id') == row.get('query_id')
        and run.get('plan_entry_sha256') == sha256_json(row)]
    if not exact or any(effective_submission(evidence, run) == 'unknown' for run in runs):
        return None
    run = exact[-1]
    review = _latest(evidence, run, 'failure_review')
    if (not review or run.get('status') not in {'failed', 'access_limited'}
            or effective_submission(evidence, run) != 'submitted'
            or review.get('retry_disposition') != 'not_requested'
            or review.get('source_allows_retry') is not False or not review.get('no_retry_reason')
            or review.get('review_id') != 'REC-REV-' + sha256_json({k:v for k,v in review.items() if k != 'review_id'})[:24]):
        return None
    if task_dir is not None:
        try:
            paths = run.get('raw_paths', [])
            if paths != review.get('receipt_paths', []) or not paths:
                return None
            for retained in paths:
                resolve_retained_path(Path(task_dir), retained,
                    expected_sha256=run.get('payload_digest') if len(paths) == 1 else '')
            from source_result_processing import progress
            if not progress(Path(task_dir), run, evidence)['material_processing_complete']:
                return None
        except (OSError, ValueError, KeyError, TypeError):
            return None
    return {'source_run_id':run['run_id'], 'source_run_sha256':sha256_json(run),
        'review_id':review['review_id'], 'review_sha256':sha256_json(review),
        'plan_entry_sha256':sha256_json(row), 'retry_constraint':review.get('retry_constraint')}


def task_limit_no_retry_proof(task, evidence, provider, row, task_dir):
    audit = no_retry_audit(task, evidence, provider, row, task_dir)
    if not audit or task_dir is None:
        return None
    if provider in {'serpapi_google_patents', 'serpapi_google_lens'}:
        from serpapi_patents_client import consumed_queries
        selection = 'serpapi_free_enhancement'
    elif provider == 'signa':
        from signa_client import consumed_queries
        selection = 'signa_free_enhancement'
    else:
        return None
    maximum = (task.get(selection) or {}).get('max_queries_per_task')
    count = consumed_queries(evidence)
    constraint = {'kind':'task_request_limit', 'provider':provider,
        'plan_entry_sha256':sha256_json(row), 'max_queries_per_task':maximum, 'consumed_queries':count}
    if (isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0
            or count < maximum or audit.get('retry_constraint') != constraint):
        return None
    return audit


def recovery_state(task: dict, evidence: dict, provider: str, row: dict) -> dict | None:
    if not enabled(task):
        return None
    identity, runs = _same_runs(task, evidence, provider, row)
    if not identity["query_version_sha256"] and not identity["target"]:
        return {**identity, "state": "blocked", "reason": "RECOVERY_REQUEST_IDENTITY_UNKNOWN"}
    if not runs:
        return None
    linked_late = {review.get("result_run_id") for run in runs
                   for review in _reviews(evidence, run) if review.get("kind") == "late_result_link"
                   or (review.get("kind") == "unknown_check" and review.get("outcome") == "result_obtained")}
    actual = [run for run in runs if run.get("run_id") not in linked_late]
    refs = [{"run_id": run.get("run_id"), "sha256": sha256_json(run)} for run in runs]
    common = {**identity, "source_run_refs": refs,
              "unknown_reserved_count": sum(effective_submission(evidence, run) == "unknown" for run in actual)}
    if any(effective_result(evidence, run) in SUCCESS for run in runs):
        return {**common, "state": "result_available", "reason": "RETAINED_RESULT_REVIEW_REQUIRED",
                "late_result_linked": bool(linked_late),
                "audited_result": any(effective_result(evidence, run) != run.get("status") for run in runs)}
    unknown = [run for run in actual if effective_submission(evidence, run) == "unknown"]
    if unknown:
        check = _latest(evidence, unknown[-1], "unknown_check")
        if check and check.get("outcome") == "still_unknown":
            disposition = check.get("disposition")
            state = "blocked" if disposition == "limited" else "awaiting_access" if disposition == "waiting" else "submission_unknown"
            reason = ("SUBMISSION_UNKNOWN_EVIDENCED_LIMIT" if state == "blocked" else
                      "SUBMISSION_UNKNOWN_DEPENDENCY" if state == "awaiting_access" else
                      "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY")
            return {**common, "state": state, "reason": reason, "unknown_review_id": check["review_id"]}
        return {**common, "state": "submission_unknown", "reason": "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY"}
    running = [run for run in actual if (_latest(evidence, run, "unknown_check") or {}).get("outcome") == "submitted_running"]
    if running:
        return {**common, "state": "awaiting_access", "reason": "SOURCE_RESULT_PENDING"}
    failures = [run for run in actual if effective_submission(evidence, run) == "submitted"
                and (effective_result(evidence, run) in {"failed", "access_limited"}
                     or (_latest(evidence, run, "unknown_check") or {}).get("outcome") == "submitted_failed")]
    if not failures:
        if actual and all(effective_submission(evidence, run) == "not_submitted" for run in actual):
            repair = _latest(evidence, actual[-1], "pre_submission_repair")
            return {**common, "state": "ready" if repair else "awaiting_review",
                    "reason": "CONFIRMED_NOT_SUBMITTED_RECHECK" if repair else "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED",
                    "submitted_attempts": 0, "remaining_automatic_retries": 1,
                    **({"repair_review_id": repair["review_id"]} if repair else {})}
        return None
    last = failures[-1]
    audit = no_retry_audit(task, evidence, provider, row)
    if audit:
        return {**common, "state":"blocked", "reason":"SOURCE_RETRY_NOT_REQUESTED",
            "submitted_attempts":len(failures), "remaining_automatic_retries":0,
            "no_retry_audit":audit}
    code = str(last.get("error_code") or "").upper()
    if code in REPAIR_CODES:
        return None  # Existing plan/adapter repair owns semantic errors.
    if any(marker in code for marker in LIMIT_CODES):
        return {**common, "state": "awaiting_access", "reason": "SOURCE_RETRY_DEPENDENCY_REQUIRED",
                "submitted_attempts": len(failures)}
    if len(failures) >= 2:
        return {**common, "state": "blocked", "reason": "SOURCE_AUTOMATIC_RETRY_EXHAUSTED",
                "submitted_attempts": len(failures), "remaining_automatic_retries": 0}
    review = _latest(evidence, last, "failure_review")
    if not review or not review.get("source_allows_retry"):
        return {**common, "state": "awaiting_review", "reason": "SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED",
                "submitted_attempts": 1, "remaining_automatic_retries": 1}
    return {**common, "state": "ready", "reason": "SOURCE_BOUNDED_RECOVERY_READY",
            "submitted_attempts": 1, "remaining_automatic_retries": 1,
            "recovery_review_id": review["review_id"]}


def dispatch_block(task: dict, evidence: dict, provider: str, row: dict) -> str | None:
    state = recovery_state(task, evidence, provider, row)
    if not state or state["state"] == "ready" or (state["state"] == "result_available"
            and not state.get("late_result_linked") and not state.get("audited_result")):
        return None
    return state["reason"]


def project(task: dict, view: dict, evidence: dict | None, plan: dict | None) -> dict:
    if not enabled(task) or not evidence or not plan:
        return view
    result = deepcopy(view)
    rows = {(provider, row.get("query_id")): row for provider, values in plan.get("queries", {}).items()
            for row in values if isinstance(row, dict)}
    for entry in result.get("entries", []):
        if entry.get("kind") != "source_lookup":
            continue
        row = rows.get((entry.get("provider"), entry.get("query_id")))
        if not row:
            continue
        recovery = recovery_state(task, evidence, entry["provider"], row)
        if recovery:
            entry["recovery"] = recovery
            if recovery["state"] == "result_available" and (recovery.get("late_result_linked") or
                    recovery.get("audited_result")):
                entry["state"], entry["reason"] = "awaiting_review", "RETAINED_RESULT_REVIEW_REQUIRED"
            elif (recovery["state"] not in {"ready", "result_available"} and not
                  (recovery["reason"] == "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED" and
                   entry.get("state") in {"awaiting_access", "blocked"})):
                entry["state"], entry["reason"] = recovery["state"], recovery["reason"]
            elif recovery["state"] == "ready" and (entry.get("state") == "ready" or
                    (entry.get("state") == "submission_unknown" and
                     recovery["reason"] == "CONFIRMED_NOT_SUBMITTED_RECHECK")):
                entry["state"], entry["reason"] = "ready", recovery["reason"]
    result["counts"] = {state: sum(item.get("state") == state for item in result.get("entries", []))
        for state in ("ready", "awaiting_review", "awaiting_access", "awaiting_user", "submission_unknown", "blocked")}
    result["status"] = "incomplete" if result.get("entries") or result.get("unresolved_scopes") else "complete"
    return result


def record_review(task_dir: Path, request: dict, *, _context=None, _processing_state=None) -> dict:
    """Append a source-bound audit. This never changes the original run or sends a request."""
    from provider_utils import evidence_lock
    with evidence_lock(task_dir) if _context is None else nullcontext():
        task, evidence = ((load_json(task_dir / "task.json"), load_json(task_dir / "evidence.json"))
                          if _context is None else _context)
        if not enabled(task) or evidence.get("task_id") != task.get("task_id"):
            raise ValueError("RECOVERY_TASK_MISMATCH")
        source_id = request.get("source_run_id")
        runs = [run for run in evidence.get("source_runs", []) if run.get("run_id") == source_id]
        if len(runs) != 1 or not request.get("reviewer") or not request.get("reasoning"):
            raise ValueError("RECOVERY_SOURCE_AND_REVIEW_REQUIRED")
        run = runs[0]
        if request.get("source_run_sha256") != sha256_json(run):
            raise ValueError("RECOVERY_SOURCE_SHA_MISMATCH")
        kind = request.get("kind")
        if kind == "pre_submission_repair":
            if effective_submission(evidence, run) != "not_submitted" or not all(request.get(key) for key in
                    ("failure_cause", "repair_basis", "condition_check", "receipt_review")):
                raise ValueError("RECOVERY_PRE_SUBMISSION_REPAIR_INCOMPLETE")
        elif kind == "failure_review":
            if effective_submission(evidence, run) != "submitted" or run.get("status") not in {"failed", "access_limited"}:
                raise ValueError("RECOVERY_NOT_A_CONFIRMED_FAILURE")
            if not all(request.get(key) for key in ("receipt_review", "material_review", "remaining_work",
                                                    "failure_cause", "repair_basis", "source_rule_ref")):
                raise ValueError("RECOVERY_REVIEW_INCOMPLETE")
            paths = run.get("raw_paths", [])
            if (paths and request.get("receipt_paths") != paths) or (not paths and
                    not request.get("receipt_absence_reason")):
                raise ValueError("RECOVERY_ORIGINAL_RECEIPT_NOT_AUDITED")
            for retained in paths:
                try:
                    resolve_retained_path(task_dir, retained,
                        expected_sha256=run.get("payload_digest") if len(paths) == 1 else "")
                except (OSError, ValueError) as exc:
                    raise ValueError("RECOVERY_RETAINED_MATERIAL_INVALID") from exc
            if isinstance(run.get("result_processing"), dict):
                from source_result_processing import progress
                try:
                    processing = _processing_state if _processing_state is not None else progress(task_dir, run, evidence)
                    if not processing["material_processing_complete"]:
                        raise ValueError("RECOVERY_RETAINED_PROCESSING_PENDING")
                except (OSError, KeyError, TypeError) as exc:
                    raise ValueError("RECOVERY_RETAINED_PROCESSING_INVALID") from exc
            no_retry = (task.get('retrieval_workflow_revision') == 'api-first-v3'
                and request.get('retry_disposition') == 'not_requested'
                and request.get('source_allows_retry') is False and bool(request.get('no_retry_reason')))
            if request.get("source_allows_retry") is not True and not no_retry:
                raise ValueError("RECOVERY_SOURCE_RETRY_NOT_ALLOWED")
            if request.get('retry_disposition') not in (None, 'requested', 'not_requested') or (
                    request.get('retry_disposition') == 'not_requested' and not no_retry):
                raise ValueError('RECOVERY_RETRY_DISPOSITION_INVALID')
        elif kind == "unknown_check":
            previous = _latest(evidence, run, "unknown_check")
            if effective_submission(evidence, run) in {"submitted", "not_submitted"} or (previous and
                    (previous.get("basis") == request.get("basis") or previous.get("outcome") != "still_unknown")):
                raise ValueError("RECOVERY_NOT_UNRESOLVED_UNKNOWN")
            if request.get("outcome") not in {"not_submitted", "submitted_running", "submitted_failed", "result_obtained", "still_unknown"}:
                raise ValueError("RECOVERY_UNKNOWN_OUTCOME_INVALID")
            if (not request.get("original_receipt_review") or not request.get("basis") or
                    request.get("check_method") not in {"existing_receipt", "existing_page", "qualified_status_query"}):
                raise ValueError("RECOVERY_UNKNOWN_CHECK_BASIS_REQUIRED")
            if (request["check_method"] == "qualified_status_query" and
                    (request.get("query_is_read_only") is not True or not request.get("source_rule_ref"))):
                raise ValueError("RECOVERY_STATUS_QUERY_NOT_READ_ONLY")
            if request["outcome"] == "result_obtained":
                result = next((item for item in evidence.get("source_runs", [])
                               if item.get("run_id") == request.get("result_run_id")), None)
                original_identity = request_identity(task, run.get("provider"), run)
                if (not original_identity["query_version_sha256"] and not original_identity["target"]
                        or not result or result is run or result.get("status") not in SUCCESS | {"failed"}
                        or request_identity(task, run.get("provider"), result)["recovery_object_id"] !=
                           original_identity["recovery_object_id"]):
                    raise ValueError("RECOVERY_UNKNOWN_RESULT_NOT_BOUND")
            if request["outcome"] == "still_unknown":
                if request.get("disposition") not in {"continue_check", "waiting", "limited"}:
                    raise ValueError("RECOVERY_UNKNOWN_DISPOSITION_REQUIRED")
                if request["disposition"] == "limited" and not all(request.get(key) is True for key in
                    ("materials_reviewed", "actionable_work_done", "no_check_route", "no_recovery_dependency")):
                    raise ValueError("RECOVERY_UNKNOWN_LIMIT_PRECONDITIONS_REQUIRED")
                if request["disposition"] == "limited" and not all(request.get(key) for key in
                    ("materials_review_basis", "actionable_work_basis", "no_check_route_basis",
                     "no_recovery_dependency_basis")):
                    raise ValueError("RECOVERY_UNKNOWN_LIMIT_BASIS_REQUIRED")
        elif kind == "late_result_link":
            result = next((item for item in evidence.get("source_runs", [])
                           if item.get("run_id") == request.get("result_run_id")), None)
            original_identity = request_identity(task, run.get("provider"), run)
            if (run.get("submission_state") in {"submitted", "not_submitted"}
                    or not original_identity["query_version_sha256"] and not original_identity["target"]
                    or not result or result is run
                    or request_identity(task, run.get("provider"), result)["recovery_object_id"] !=
                       original_identity["recovery_object_id"]
                    or result.get("status") not in SUCCESS | {"failed"} or not request.get("match_basis")):
                raise ValueError("RECOVERY_LATE_RESULT_NOT_BOUND")
        else:
            raise ValueError("RECOVERY_REVIEW_KIND_INVALID")
        allowed = {"kind", "source_run_id", "source_run_sha256", "reviewer", "reasoning", "receipt_review",
                   "material_review", "remaining_work", "failure_cause", "repair_basis", "condition_check",
                   "source_allows_retry", "retry_disposition", "no_retry_reason", "retry_constraint",
                   "source_rule_ref", "receipt_paths", "receipt_absence_reason",
                   "outcome", "original_receipt_review", "basis", "check_method", "query_is_read_only",
                   "disposition", "materials_reviewed", "materials_review_basis", "actionable_work_basis",
                   "no_check_route_basis", "no_recovery_dependency_basis",
                   "actionable_work_done", "no_check_route", "no_recovery_dependency", "result_run_id", "match_basis"}
        event = {key: request[key] for key in allowed if key in request}
        event["recovery_object_id"] = request_identity(task, run["provider"], run)["recovery_object_id"]
        if _context is not None:
            # New atomic closeout repeats reuse only the latest exact audit;
            # legacy one-event append/history behavior stays unchanged.
            prior = _latest(evidence, run, kind)
            if prior and {key: value for key, value in prior.items()
                          if key not in {'recorded_at', 'review_id'}} == event:
                return prior
        event["recorded_at"] = now_iso()
        event["review_id"] = "REC-REV-" + sha256_json(event)[:24]
        evidence.setdefault("recovery_reviews", []).append(event)
        if _context is None:
            atomic_write_json(task_dir / "evidence.json", evidence)
        return event


def record_failure_closeout(task_dir: Path, *, source_run_id: str, source_run_sha256: str,
                            receipt_disposition: dict | None, failure_review: dict) -> dict:
    """Atomically bind one real failure's receipt disposition and retry decision.

    Source facts are reused, while material/remaining-work/repair judgments and
    retry choice must be supplied. This records no new source request and grants
    no general publication permission. An invalid second event writes nothing.
    """
    from provider_utils import evidence_lock
    from source_result_processing import append_receipt_disposition, progress
    task_dir = Path(task_dir).resolve()
    with evidence_lock(task_dir):
        task_path, evidence_path = task_dir / 'task.json', task_dir / 'evidence.json'
        source_files = {path: sha256_file(path) for path in (task_path, evidence_path)}
        task, evidence = load_json(task_path), load_json(evidence_path)
        if (task.get('retrieval_workflow_revision') != 'api-first-v3'
                or task.get('assessment_revision') != 'known-findings-risk-v1'
                or task.get('presentation_policy_revision') != 'operator-report-v1'):
            raise ValueError('RECOVERY_FAILURE_CLOSEOUT_NEW_POLICY_REQUIRED')
        if not enabled(task) or evidence.get('task_id') != task.get('task_id'):
            raise ValueError('RECOVERY_TASK_MISMATCH')
        runs = [row for row in evidence.get('source_runs', []) if row.get('run_id') == source_run_id]
        if len(runs) != 1 or source_run_sha256 != sha256_json(runs[0]):
            raise ValueError('RECOVERY_SOURCE_SHA_MISMATCH')
        run = runs[0]
        if effective_submission(evidence, run) != 'submitted' or run.get('status') not in {'failed', 'access_limited'}:
            raise ValueError('RECOVERY_NOT_A_CONFIRMED_FAILURE')
        if not isinstance(failure_review, dict) or not failure_review:
            raise ValueError('RECOVERY_FAILURE_CLOSEOUT_REVIEW_REQUIRED')
        request = deepcopy(failure_review)
        for key, value in (('source_run_id', source_run_id), ('source_run_sha256', source_run_sha256),
                           ('kind', 'failure_review'), ('receipt_paths', run.get('raw_paths', []))):
            if key in request and request[key] != value:
                raise ValueError('RECOVERY_FAILURE_CLOSEOUT_SOURCE_CONFLICT:' + key)
            request[key] = deepcopy(value)
        # These are original reported failure facts, not a new cause diagnosis.
        if not request.get('failure_cause'):
            request['failure_cause'] = ': '.join(str(run.get(key)) for key in ('error_code', 'detail') if run.get(key))
        before = sha256_json(evidence)
        if receipt_disposition is not None:
            if not isinstance(receipt_disposition, dict):
                raise ValueError('RECOVERY_FAILURE_CLOSEOUT_RECEIPT_INVALID')
            receipt = deepcopy(receipt_disposition)
            if set(receipt) - {'outcome', 'reviewer', 'reason', 'source_run_id', 'source_run_sha256'}:
                raise ValueError('RECOVERY_FAILURE_CLOSEOUT_RECEIPT_INVALID')
            for key, value in (('source_run_id', source_run_id), ('source_run_sha256', source_run_sha256)):
                if key in receipt and receipt.pop(key) != value:
                    raise ValueError('RECOVERY_FAILURE_CLOSEOUT_SOURCE_CONFLICT:' + key)
            receipt.setdefault('reviewer', request.get('reviewer'))
            receipt.setdefault('reason', request.get('receipt_review'))
            append_receipt_disposition(task_dir, source_run_id, receipt, _context=(task, evidence))
        # Exactly one refresh, used by the original recovery validation and by
        # the returned closeout. Retained rows cannot be auto-marked reviewed.
        processing = progress(task_dir, run, evidence) if isinstance(run.get('result_processing'), dict) else None
        event = record_review(task_dir, request, _context=(task, evidence), _processing_state=processing)
        receipt = next((row for row in evidence.get('receipt_dispositions', [])
                        if row.get('source_run_id') == source_run_id), None)
        facts = {'submission_state': effective_submission(evidence, run),
                 **{key: deepcopy(run.get(key)) for key in
                    ('provider', 'operation', 'query_id', 'status', 'quota', 'error_code', 'detail',
                     'raw_paths', 'payload_digest')}}
        binding = {'source_run_id': source_run_id, 'source_run_sha256': source_run_sha256,
                   'source_facts': facts, 'receipt_disposition_sha256': sha256_json(receipt) if receipt else None,
                   'recovery_review_id': event['review_id'], 'recovery_review_sha256': sha256_json(event)}
        old = next((row for row in reversed(evidence.get('failure_closeouts', []))
                    if {key: row.get(key) for key in binding} == binding), None)
        if old is None:
            old = {**binding, 'recorded_at': now_iso()}
            old['closeout_id'] = 'FAILURE-CLOSEOUT-' + sha256_json(old)[:24]
            evidence.setdefault('failure_closeouts', []).append(old)
        if any(sha256_file(path) != digest for path, digest in source_files.items()):
            raise ValueError('RECOVERY_FAILURE_CLOSEOUT_INPUT_CHANGED')
        # Recheck raw originals without another material/progress computation.
        for retained in run.get('raw_paths', []):
            resolve_retained_path(task_dir, retained,
                expected_sha256=run.get('payload_digest') if len(run['raw_paths']) == 1 else '')
        changed = sha256_json(evidence) != before
        if changed:
            atomic_write_json(evidence_path, evidence)
        return {'closeout': deepcopy(old), 'failure_review': deepcopy(event),
                'receipt_disposition': deepcopy(receipt), 'material_progress': processing, 'recorded': changed}

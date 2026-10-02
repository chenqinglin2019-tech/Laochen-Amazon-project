#!/usr/bin/env python3
"""Versioned automation-first routing and append-only search planning.

The 2.3 builders remain frozen. Availability never rewrites a task's obligations:
an unavailable route is a gap, not an empty search or a request for manual work.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import unicodedata
from typing import Any
from completion_policy import supported as necessary_work_enabled, evidence_delivery_enabled

from common import (
    CURRENT_SCHEMA_VERSION, EU_COUNTRIES, EU_UTILITY_MODEL_COUNTRIES,
    atomic_write_json, build_coverage_requirements, is_v24, load_json,
    normalize_text, now_iso, sha256_json, serper_free_enabled, serpapi_free_enabled,
    signa_free_enabled, load_skill_config, recall_integrity_enabled, RECALL_INTEGRITY_REVISION,
    DECISION_PLAN_META_KEYS, API_FIRST_PLAN_META_KEYS,
)

TARGET_COUNTRIES = {"US", "GB", "FR", "DE", "IT", "ES", "JP", "EU"}
LANGUAGES = {"US": "en", "GB": "en", "EU": "en", "FR": "fr", "DE": "de", "IT": "it", "ES": "es", "JP": "ja"}
NON_REGISTERED_RIGHTS = {"copyright", "trade_dress", "unregistered_design"}
SEARCH_META_KEYS = {"search_dimension", "search_language", "execution_phase", "publication_scope"}
SCENARIO_META_KEYS = DECISION_PLAN_META_KEYS
WORKFLOW_CORRECTION_REVISION = "workflow-correction-v1"
REQUIRED_FACTS = frozenset({"abstract", "representative_figures", "protection_content", "current_status", "goods_services"})
# These dispositions describe a temporary execution/work state, not a removal
# of an authorized obligation. A later pass must reconsider them.
TEMPORARY_DISPATCH_CODES = frozenset({"PRODUCT_SCOPE_WAITING", "PRODUCT_SCOPE_REVIEW_REQUIRED", "QUERY_IMAGE_INPUT_OR_PERMISSION_UNAVAILABLE", "PRODUCT_FACT_VERSION_REVIEW_REQUIRED", "PRODUCT_TARGET_CHANGE_REVIEW_REQUIRED", "PRODUCT_CHANGE_QUERY_REVIEW_REQUIRED", "TRIAGE_BOUNDED_ACTION_ALREADY_ATTEMPTED",
    "TRIAGE_ATTEMPT_STATE_UNKNOWN", "TRIAGE_REVIEW_REQUIRED", "DISCOVERY_DIRECTION_REVIEW_REQUIRED",
    "DISCOVERY_EXPRESSION_REVIEW_REQUIRED", "DISCOVERY_EXPRESSION_MISMATCH",
    "SOURCE_OPERATION_UNAVAILABLE", "SOURCE_FAILURE_RECOVERY_REVIEW_REQUIRED",
    "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED", "REVIEW_PROGRESS_QUERY_NOT_PLANNED",
    "SOURCE_RETRY_DEPENDENCY_REQUIRED", "SOURCE_RESULT_PENDING",
    "SOURCE_AUTOMATIC_RETRY_EXHAUSTED", "RECOVERY_REQUEST_IDENTITY_UNKNOWN",
    "SUBMISSION_UNKNOWN_EVIDENCED_LIMIT", "SUBMISSION_UNKNOWN_DEPENDENCY",
    "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY", "RETAINED_RESULT_REVIEW_REQUIRED"})
RECALL_PLANNING_REVISION = "identity-discovery-v1"
RETRIEVAL_WORKFLOW_REVISION = "api-first-v2"
AXES = {
    "patent": ["text", "classification"], "utility_model": ["text", "classification"],
    "design": ["text", "classification", "image"],
    "trademark_word": ["text", "phonetic"],
    "trademark_figurative": ["classification", "image"],
}


def identity_discovery_enabled(task: dict) -> bool:
    return recall_integrity_enabled(task) and task.get("recall_planning_revision") == RECALL_PLANNING_REVISION


def api_first_enabled(task: dict) -> bool:
    from common import api_first_revision_enabled
    return (scenario_workflow_enabled(task) and correction_enabled(task)
            and api_first_revision_enabled(task.get("retrieval_workflow_revision")))


def scenario_workflow_enabled(task: dict) -> bool:
    from decision_workflow import decision_workflow_enabled
    return decision_workflow_enabled(task)


def correction_enabled(task: dict) -> bool:
    from decision_workflow import correction_enabled as enabled
    return enabled(task)


def reading_contract_valid(row: dict) -> bool:
    facts, scope = row.get("required_facts"), row.get("reading_scope")
    if (not isinstance(facts, list) or not facts
            or any(not isinstance(fact, str) or fact not in REQUIRED_FACTS for fact in facts) or len(set(facts)) != len(facts)
            or not isinstance(scope, dict) or not isinstance(scope.get("level"), str) or scope.get("level") not in REQUIRED_FACTS):
        return False
    pages = scope.get("page_numbers", [])
    return (isinstance(pages, list) and all(type(page) is int and page > 0 for page in pages) and len(set(pages)) == len(pages)
            and ("representative_figures" not in facts or bool(pages)))


def requested_facts_satisfied(row: dict, payload: dict) -> bool:
    """Content retrieval credit never implies current official verification."""
    if not reading_contract_valid(row) or not isinstance(payload, dict):
        return False
    from provider_utils import validate_text_evidence
    try:
        validate_text_evidence(payload, expected_stage="retained")
    except (ValueError, TypeError):
        return False
    if payload.get("candidate_id") != row.get("candidate_id"):
        return False
    number = re.sub(r"[^A-Za-z0-9]", "", str(row.get("record_number") or row.get("serial_number") or row.get("q") or "")).upper()
    observed = re.sub(r"[^A-Za-z0-9]", "", str(payload.get("publication_number") or payload.get("record_number") or payload.get("serial_number") or "")).upper()
    if not number or observed != number:
        return False
    obtained = payload.get("satisfied_facts", [])
    if not isinstance(obtained, list) or any(not isinstance(fact, str) for fact in obtained) or not set(row["required_facts"]) <= set(obtained):
        return False
    if "current_status" in row["required_facts"]:
        verification = payload.get("official_verification") or {}
        if not isinstance(verification, dict) or verification.get("status") != "verified" or verification.get("identity_match") is not True:
            return False
    if row.get("reading_scope", {}).get("page_numbers"):
        document = payload.get("published_document") or {}
        pages = document.get("document_pages", []) if isinstance(document, dict) else []
        if not isinstance(pages, list) or not set(row["reading_scope"]["page_numbers"]) <= {page.get("page") for page in pages if isinstance(page, dict) and type(page.get("page")) is int}:
            return False
    return True


def plan_row_index(plan: dict) -> dict[str, list[tuple[str, dict]]]:
    from decision_workflow import _snapshot_value
    def build():
        indexed = {}
        for provider, rows in plan.get("queries", {}).items():
            for row in rows:
                indexed.setdefault(row.get("query_id"), []).append((provider, row))
        return indexed
    return _snapshot_value("workflow_plan_rows", (plan,), build)


def action_attempt_state(evidence: dict, provider: str, row: dict) -> dict:
    """Read explicit submission facts, preserving ambiguity after a crash."""
    from decision_workflow import _snapshot_value
    def indexed():
        values = {}
        for run in evidence.get("source_runs", []):
            values.setdefault((run.get("provider"), run.get("query_id"), run.get("plan_entry_sha256")), []).append(run)
        return values
    runs = _snapshot_value("workflow_attempts", (evidence,), indexed).get((provider, row.get("query_id"), sha256_json(row)), [])
    meaningful = [run for run in runs if run.get("status") not in {"cancelled", "not_applicable"}]
    reviewed = {}
    audited_submitted = set()
    for review in evidence.get("submission_state_reviews", []):
        if not isinstance(review, dict):
            continue
        for run in meaningful:
            if (review.get("method") == "pre_source_guard_audit" and review.get("source_run_id") == run.get("run_id")
                    and review.get("source_run_sha256") == sha256_json(run)
                    and review.get("query_id") == row.get("query_id")
                    and review.get("plan_entry_sha256") == sha256_json(row)
                    and review.get("submission_state") == "not_submitted"
                    and review.get("reviewer") and review.get("reasoning") and review.get("reviewed_at")
                    and _pre_source_guard_failure(run)):
                reviewed[run["run_id"]] = review
            if (review.get("method") == "epo_search_receipt_audit" and review.get("source_run_id") == run.get("run_id")
                    and review.get("source_run_sha256") == sha256_json(run)
                    and review.get("query_id") == row.get("query_id") and review.get("plan_entry_sha256") == sha256_json(row)
                    and review.get("submission_state") == "submitted" and review.get("result") == "no_result"
                    and review.get("reviewer") and review.get("reasoning") and review.get("reviewed_at")):
                audited_submitted.add(run["run_id"])
    from recovery_stage_b import effective_submission
    submitted = [run for run in meaningful if effective_submission(evidence, run) == "submitted" or run.get("run_id") in audited_submitted]
    unknown = [run for run in meaningful if effective_submission(evidence, run) == "unknown"
               and run.get("run_id") not in reviewed]
    return {"state": "submitted" if submitted else "unknown" if unknown else "not_submitted",
            "run": (submitted or unknown or meaningful or [None])[-1], "attempted": bool(meaningful),
            "submission_reviews": list(reviewed.values())}


def _pre_source_guard_failure(run):
    return (run.get("submission_state") not in {"submitted", "not_submitted"}
            and run.get("error_code") == "BROWSER_EXECUTION_FAILED" and not run.get("raw_paths")
            and bool(re.fullmatch(r"SCENARIO_DISPATCH_(?:INPUT_INVALID|RUNTIME_UNAVAILABLE|INVALID_RESPONSE|TIMEOUT): current scenario/triage does not authorize this action", str(run.get("detail") or ""))))


def review_pre_source_guard_failure(task_dir: Path, run_id: str, *, reviewer: str, reasoning: str) -> dict:
    """Append an exact audit of a known pre-browser failure, never rewrite it.

    Deliberately not a generic override for unknown submissions. The retained
    failure must identify the shared guard, which runs before source execution.
    """
    from provider_utils import evidence_lock
    if not correction_enabled(load_json(task_dir / "task.json")) or not reviewer.strip() or not reasoning.strip():
        raise ValueError("SUBMISSION_REVIEW_CONTEXT_REQUIRED")
    with evidence_lock(task_dir):
        evidence = load_json(task_dir / "evidence.json")
        matches = [run for run in evidence.get("source_runs", []) if run.get("run_id") == run_id]
        if len(matches) != 1 or not _pre_source_guard_failure(matches[0]):
            raise ValueError("SUBMISSION_REVIEW_NOT_A_PRE_SOURCE_GUARD_FAILURE")
        run = matches[0]
        review = {"method": "pre_source_guard_audit", "source_run_id": run_id,
                  "source_run_sha256": sha256_json(run), "query_id": run["query_id"],
                  "plan_entry_sha256": run["plan_entry_sha256"], "submission_state": "not_submitted",
                  "reviewer": reviewer, "reasoning": reasoning, "reviewed_at": now_iso()}
        review["review_id"] = "SUBREV-" + sha256_json(review)[:24]
        evidence.setdefault("submission_state_reviews", []).append(review)
        atomic_write_json(task_dir / "evidence.json", evidence)
    return review


def record_action_recovery(task_dir: Path, provider: str, row: dict, *, implementation_sha256: str = "") -> dict | None:
    """Append a pre-dispatch intention for a reviewed bounded retry or no-submit repair.

    This is not a replacement receipt or a grant to retry unknown/submitted work.
    Call under the scheduler's existing execution lock, immediately before dispatch.
    """
    task = load_json(task_dir / "task.json")
    if not correction_enabled(task):
        return None
    evidence = load_json(task_dir / "evidence.json")
    from continuation_stage_c import dispatch_block as continuation_dispatch_block
    if continuation_dispatch_block(task, evidence, row):
        raise ValueError("USER_ACTIVE_PAUSE")
    from recovery_stage_b import recovery_state
    bounded = recovery_state(task, evidence, provider, row)
    if bounded and bounded.get("reason") == "SOURCE_BOUNDED_RECOVERY_READY":
        prior = bounded["source_run_refs"][-1]
        identity = {"recovery_object_id": bounded["recovery_object_id"],
                    "prior_source_run_id": prior["run_id"], "prior_source_run_sha256": prior["sha256"],
                    "recovery_review_id": bounded["recovery_review_id"]}
        recovery = {**identity, "recovery_id": "REC-" + sha256_json(identity)[:24],
                    "created_at": now_iso(), "reason": "reviewed_submitted_failure_retry",
                    "prior_submission_state": "submitted", "external_attempt_ordinal": 2}
    else:
        state = action_attempt_state(evidence, provider, row)
        if not state["attempted"] or state["state"] != "not_submitted":
            return None
        prior = state["run"]
        identity = {"provider": provider, "query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                    "prior_source_run_id": prior.get("run_id"), "prior_source_run_sha256": sha256_json(prior),
                    "implementation_sha256": implementation_sha256}
        recovery = {**identity, "recovery_id": "REC-" + sha256_json(identity)[:24], "created_at": now_iso(),
                    "reason": "confirmed_not_submitted_retry", "prior_submission_state": "not_submitted"}
        if state.get("submission_reviews"):
            recovery["prior_submission_state_recorded"] = prior.get("submission_state")
            recovery["submission_review_ids"] = [item["review_id"] for item in state["submission_reviews"]]
    # API and browser have distinct dispatcher locks. Use an existing file-lock
    # primitive and a separate appendix so retry notes cannot race plan updates.
    from provider_utils import file_lock
    with file_lock(task_dir / ".action-recoveries.lock"):
        path = task_dir / "action-recoveries.json"
        journal = load_json(path) if path.is_file() else {"task_id": task["task_id"], "revision": WORKFLOW_CORRECTION_REVISION, "records": []}
        if journal.get("task_id") != task["task_id"] or journal.get("revision") != WORKFLOW_CORRECTION_REVISION:
            raise ValueError("ACTION_RECOVERY_IDENTITY_MISMATCH")
        records = journal["records"]
        existing = next((item for item in records if item.get("recovery_id") == recovery["recovery_id"]), None)
        if existing:
            from recovery_stage_b import enabled as recovery_enabled
            if recovery_enabled(task):
                raise ValueError("RECOVERY_RETRY_INTENTION_UNRESOLVED")
            return existing
        records.append(recovery)
        atomic_write_json(path, journal)
    return recovery


def browser_submitted_failure_state(task: dict, evidence: dict, provider: str, row: dict) -> dict | None:
    """Bound ordinary failed submissions for one immutable new-policy row.

    Successful/partial retrieval, source limits, syntax repair and unsubmitted
    actions retain their existing policies. The append-only source runs are the
    counter; changing a status file or browser implementation cannot reset it.
    """
    if (not necessary_work_enabled(task)
            or not (provider.endswith("_browser") or provider == "uspto_tsdr")):
        return None
    digest = sha256_json(row)
    runs = [run for run in evidence.get("source_runs", []) if isinstance(run, dict)
        and run.get("provider") == provider and run.get("query_id") == row.get("query_id")
        and run.get("plan_entry_sha256") == digest and run.get("status") not in {"cancelled", "not_applicable"}]
    reviewed = {item["source_run_id"] for item in action_attempt_state(evidence, provider, row).get("submission_reviews", [])}
    from recovery_stage_b import effective_submission
    unknown = [run for run in runs if effective_submission(evidence, run) not in {"submitted", "not_submitted"}
        and run.get("run_id") not in reviewed]
    if unknown:
        return {"state": "submission_unknown", "reason": "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY",
            "plan_entry_sha256": digest,
            "source_run_refs": [{"run_id": run.get("run_id"), "sha256": sha256_json(run)} for run in unknown]}
    # A qualified success belongs to normal completion/partial recovery. Never
    # turn retained positive evidence into a failed ordinary search budget.
    if any(run.get("status") in {"success", "no_result"} for run in runs):
        return None
    excluded = {"USPTO_QUERY_REJECTED", "UNSUPPORTED_QUERY_SEMANTICS", "BROWSER_QUERY_SEMANTICS_UNSUPPORTED",
        "INTERNAL_ROUTE_CONTRACT_ERROR", "AUTOMATION_NOT_VALIDATED", "AUTOMATION_PROHIBITED",
        "AUTOMATIC_QUERY_FIELD_UNSUPPORTED", "AUTOMATIC_QUERY_FILTER_UNSUPPORTED", "AUTOMATIC_QUERY_LANGUAGE_UNSUPPORTED",
        "CURRENT_STATUS_ROUTE_UNAVAILABLE", "AUTH_REQUIRED", "LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "MFA_REQUIRED",
        "CONSENT_REQUIRED", "QR_REQUIRED", "QUOTA_EXHAUSTED", "FREE_QUOTA_EXHAUSTED", "RATE_LIMITED"}
    failures = []
    for run in runs:
        coverage = (run.get("metadata") or {}).get("search_coverage") or {}
        codes = {str(value or "").upper() for value in (run.get("error_code"), coverage.get("error_code"), coverage.get("stop_reason"))}
        if (run.get("status") in {"failed", "access_limited"} and run.get("submission_state") == "submitted"
                and not codes & excluded and not any(code.startswith(("BROWSER_RATE_LIMIT", "BROWSER_PARTIAL_")) for code in codes)):
            failures.append(run)
    if not failures:
        return None
    # The sole runtime settings file is shared by dispatch and publication;
    # neither backend credentials nor caller/status overrides alter this cap.
    config = load_json(Path(__file__).resolve().parents[1] / "references" / "runtime-config.json")
    limit = config.get("cdp", {}).get("submitted_failure_resume_limit", 1)
    limit = limit if type(limit) is int and 0 <= limit <= 1 else 1
    maximum = 1 + limit
    exhausted = len(failures) >= maximum
    return {"state": "blocked" if exhausted else "ready",
        "reason": "BROWSER_SUBMITTED_FAILURE_RECOVERY_EXHAUSTED" if exhausted else "BROWSER_SUBMITTED_FAILURE_RECOVERY_AVAILABLE",
        "plan_entry_sha256": digest, "failure_count": len(failures), "max_submitted_failures": maximum,
        "remaining_attempts": max(0, maximum - len(failures)), "last_error_code": failures[-1].get("error_code"),
        "detail": ("The exact browser plan row has exhausted its bounded recovery after submitted failures."
            if exhausted else "One bounded recovery remains for the exact browser plan row after a submitted failure."),
        "source_run_refs": [{"run_id": run.get("run_id"), "sha256": sha256_json(run)} for run in failures]}


def browser_partial_recovery_state(task: dict, evidence: dict, provider: str, row: dict,
                                   current: dict | None = None) -> dict | None:
    """Project a bounded partial recovery from retained runs, never static access.

    Runs survive a missing status file. The snapshot retains the configured
    limit, but it cannot erase already recorded attempts. No local credential
    or implementation lookup is involved in offline publication validation.
    """
    if (not necessary_work_enabled(task)
            or not (provider.endswith("_browser") or provider == "uspto_tsdr")):
        return None
    from assessment_v24 import bound_runs, NON_PRODUCTION
    runs = [run for run in bound_runs(evidence, {"queries": {provider: [row]}}, provider, row)
            if str(run.get("source_environment") or "").casefold() not in NON_PRODUCTION
            and run.get("authoritative_for_final_rating") is not False]
    current = current if isinstance(current, dict) and current.get("plan_entry_sha256") == sha256_json(row) else {}
    reviewed = {item["source_run_id"] for item in action_attempt_state(evidence, provider, row)["submission_reviews"]}
    if any(run.get("submission_state") not in {"submitted", "not_submitted"}
           and run.get("run_id") not in reviewed for run in runs):
        return None
    def coverage(run):
        value = (run.get("metadata") or {}).get("search_coverage") or {}
        return value if isinstance(value, dict) else {}
    def codes(value, cov):
        return {str(item or "").upper() for item in
            (value.get("error_code"), value.get("source_error_code"), cov.get("error_code"), cov.get("stop_reason"))}
    latest = runs[-1] if runs else {}
    latest_codes = codes(latest, coverage(latest)) | codes(current, {})
    if (any(code.startswith("BROWSER_RATE_LIMIT") for code in latest_codes)
            or latest_codes & {"USPTO_QUERY_REJECTED", "UNSUPPORTED_QUERY_SEMANTICS",
                "INTERNAL_ROUTE_CONTRACT_ERROR", "AUTOMATION_NOT_VALIDATED", "AUTOMATION_PROHIBITED",
                "AUTOMATIC_QUERY_FIELD_UNSUPPORTED", "AUTOMATIC_QUERY_FILTER_UNSUPPORTED",
                "AUTH_REQUIRED", "LOGIN_REQUIRED", "CAPTCHA_REQUIRED", "MFA_REQUIRED", "CONSENT_REQUIRED", "QR_REQUIRED"}):
        return None  # Source access and Agent-repair work keep their own policy.
    partial = []
    for index, run in enumerate(runs):
        cov = coverage(run)
        if run.get("status") not in {"success", "no_result"} or cov.get("schema_valid") is not True:
            continue
        if cov.get("truncated") is False:
            partial = []  # A later complete capture supersedes older partial evidence.
        elif cov.get("truncated") is True and not any(code.startswith("BROWSER_RATE_LIMIT") for code in codes(run, cov)):
            partial.append((index, run))
    if not partial:
        return None
    first_index = partial[0][0]
    attempted = [run for run in runs[first_index:] if run.get("submission_state") == "submitted"]
    attempts = max(0, len(attempted) - 1)
    limit = current.get("partial_resume_limit", 1)
    limit = limit if type(limit) is int and 0 <= limit <= 1 else 1
    exhausted = attempts >= limit
    cov = coverage(partial[-1][1])
    return {"state": "blocked" if exhausted else "ready",
        "reason": "BROWSER_PARTIAL_RESUME_LIMIT" if exhausted else "BROWSER_PARTIAL_RESUME_AVAILABLE",
        "partial_resume_attempts": attempts, "partial_resume_limit": limit,
        "source_stop_reason": cov.get("stop_reason") or "coverage incomplete",
        "detail": "Retained partial results exhausted their bounded automatic recovery; candidate review remains required."
            if exhausted else "One bounded recovery of the retained partial result remains.",
        "source_run_refs": [{"run_id": run["run_id"], "sha256": sha256_json(run)} for run in runs[first_index:]]}


def _identity_user_actions(task, evidence, record, supplement=None):
    """Current validated user-only prerequisites can defer identity investigation."""
    from candidate_followup import enabled as followup_enabled, action_errors, latest_event
    from decision_workflow import evidence_index
    if (task.get('retrieval_workflow_revision') != 'api-first-v3' or not followup_enabled(task)
            or record.get('current') is not True or record.get('decision') != 'needs_info'):
        return []
    annotation = record.get('annotation', {})
    actions = record.get('next_actions')
    if (not isinstance(actions, list) or not actions or not annotation.get('annotation_id')
            or annotation.get('reading_level') not in {'result_record','title','abstract','fulltext','protection_content'}):
        return []
    known = set(evidence_index(evidence, supplement))
    refs = annotation.get('evidence_refs')
    if not isinstance(refs, list) or not refs or not set(refs) <= known:
        return []
    for action in actions:
        basis = action.get('followup_basis', {}) if isinstance(action, dict) else {}
        if (not isinstance(action, dict) or action.get('kind') != 'user_information'
                or not str(action.get('question') or '').strip()
                or action_errors(action, known_evidence=known)
                or not basis.get('existing_evidence_refs')):
            return []
        review = latest_event(task, 'result_review', annotation['annotation_id'], action.get('action_id'))
        if review is not None and review.get('outcome') != 'waiting':
            return []
    return actions


def derive_work_view(task: dict, evidence: dict, candidates: dict, plan: dict, ledger: dict, *,
                     supplement=None, evidence_root=None, task_dir=None, coverage=None,
                     browser_status=None, source_capabilities=None) -> dict:
    """One read-only next-work projection; no new completion/authority store.

    Existing coverage decides evidence obligations, current triage decides human
    reasoning work, and receipts decide dispatch state. Historical attempts are
    retained elsewhere and do not contaminate this necessary-work view.
    """
    from decision_workflow import decision_snapshot, triage_summary, triage_scope_enabled, UNLOCATED
    from assessment_v24 import scenario_coverage_by_scope
    from runtime_v24 import operation_accepted
    if not correction_enabled(task):
        return {"revision": None, "status": "legacy", "entries": [], "counts": {}}
    with decision_snapshot(task, evidence, candidates, plan, ledger, supplement):
        groups = coverage if coverage is not None else scenario_coverage_by_scope(task, evidence, candidates, plan,
            ledger=ledger, supplement=supplement, evidence_root=evidence_root)
        triage = triage_summary(task, candidates, ledger, evidence=evidence, supplement=supplement)
        browser_rows = {r.get("query_id"): r for r in (browser_status or {}).get("queries", []) if isinstance(r, dict)}
        capabilities = source_capabilities or {}
        entries = []
        def add(value):
            value["work_id"] = "WORK-" + sha256_json({key: value.get(key) for key in
                ("scenario_id", "jurisdiction", "right_type", "candidate_id", "query_id", "action_id", "kind", "reason")})[:24]
            entries.append(value)
        for group in groups:
            scope = {key: group[key] for key in ("scenario_id", "jurisdiction", "right_type")}
            complete_obligations = {ob["evidence_obligation_id"] for ob in group.get("obligations", []) if ob.get("complete")}
            by_query = {q["query_id"]: q for q in group.get("queries", [])}
            for query_id, result in by_query.items():
                matches = plan_row_index(plan).get(query_id, [])
                if len(matches) != 1:
                    add({**scope, "kind": "plan_repair", "query_id": query_id, "state": "blocked", "reason": "PLAN_QUERY_IDENTITY_INVALID"})
                    continue
                provider, row = matches[0]
                if (task.get('retrieval_workflow_revision') == 'api-first-v3'
                        and validated_query_cancellation(task, plan, row)
                        and not any(run.get('provider') == provider and run.get('query_id') == query_id
                            for run in evidence.get('source_runs', []) if isinstance(run, dict))):
                    continue  # Unsubmitted, explicitly withdrawn; no evidence or obligation completion is claimed.
                # A successful qualified alternative satisfies the obligation;
                # do not schedule every unavailable backup for the same fact.
                if result.get("complete") or row.get("evidence_obligation_id") in complete_obligations:
                    continue
                base = {**scope, "query_id": query_id, "provider": provider, "candidate_id": row.get("triage_candidate_id") or row.get("candidate_id"),
                        "action_id": row.get("triage_action_id"), "kind": "agent_investigation" if provider == "asset_provenance" else "source_lookup",
                        "required_facts": row.get("required_facts", []), "reading_scope": row.get("reading_scope"),
                        "evidence_obligation_id": row.get("evidence_obligation_id")}
                block = scenario_dispatch_block(task, plan, provider, row, candidates, ledger, evidence,
                                                supplement=supplement, task_dir=task_dir)
                attempt = action_attempt_state(evidence, provider, row)
                run = attempt["run"] or {}
                current = browser_rows.get(query_id, {})
                if current.get("plan_entry_sha256") != sha256_json(row):
                    current = {}
                # A not-submitted repair cannot be acted on until the known
                # route or access dependency is available. Keep that existing
                # blocker visible in the work queue; dispatch still enforces
                # the repair review after the dependency is resolved.
                if block and block.get("reason") == "PRE_SUBMISSION_REPAIR_REVIEW_REQUIRED" and (
                    run.get("error_code") in {"CURRENT_STATUS_ROUTE_UNAVAILABLE", "AUTOMATION_NOT_VALIDATED",
                        "AUTOMATION_PROHIBITED", "INTERNAL_ROUTE_CONTRACT_ERROR"}
                    or (provider in capabilities and not capabilities[provider].get("executable")
                        and capabilities[provider].get("reason") != "browser_adapter_requires_real_route_acceptance")):
                    block = None
                failed_submission = browser_submitted_failure_state(task, evidence, provider, row)
                partial_recovery = browser_partial_recovery_state(task, evidence, provider, row, current)
                material = scenario_reading_material(task, plan, evidence, candidates, ledger, provider, row,
                    supplement=supplement, evidence_root=evidence_root, task_dir=task_dir) if not block or block.get("reason") in TEMPORARY_DISPATCH_CODES else None
                external_actions = result.get("external_information_actions")
                if (necessary_work_enabled(task) and provider == "asset_provenance"
                        and result.get("investigation_status") == "completed"
                        and result.get("retrieval_complete") is True and isinstance(external_actions, list) and external_actions):
                    # query_coverage validates the completed public investigation
                    # and each supplier-only question before exposing these.
                    for action in external_actions:
                        add({**base, "kind": "user_information", "state": "awaiting_user",
                            "reason": "EXTERNAL_INFORMATION_REQUIRED", "action_id": action["action_id"], "action": deepcopy(action),
                            **{key: action[key] for key in ("question", "owner", "evidence_needed", "reasoning")},
                            "evidence_refs": list(dict.fromkeys([*result.get("evidence_refs", []), *action["evidence_refs"]]))})
                    continue
                if material is not None:
                    base.update(kind="agent_read", reading_material=material, evidence_refs=material.get("evidence_refs", []))
                    state, reason = "awaiting_review", "RETAINED_ORIGINAL_REQUIRES_READING"
                elif result.get("retrieval_complete"):
                    state, reason = "awaiting_review", result.get("gap") or "RETRIEVED_RESULTS_REQUIRE_TRIAGE"
                elif block:
                    reason = block["reason"]
                    state = "submission_unknown" if reason == "TRIAGE_ATTEMPT_STATE_UNKNOWN" else "awaiting_user" if reason == "PRODUCT_SCOPE_WAITING" else "awaiting_access" if reason == "SOURCE_OPERATION_UNAVAILABLE" else "awaiting_review" if reason in TEMPORARY_DISPATCH_CODES else "blocked"
                elif provider == "asset_provenance":
                    state, reason = "ready", "AGENT_INVESTIGATION_REQUIRED"
                else:
                    if (necessary_work_enabled(task)
                            and (current.get("dispatch") == "rate_limit_deferred" or current.get("phase") == "await_source_retry")
                            and str(current.get("error_code") or current.get("source_error_code") or "").upper()
                                in {"BROWSER_RATE_LIMITED", "BROWSER_RATE_LIMIT_COOLDOWN", "BROWSER_RATE_LIMIT_RECOVERY_EXHAUSTED",
                                    "BROWSER_RATE_LIMIT_RECOVERY_UNVERIFIED"}):
                        state, reason = "awaiting_access", str(current.get("error_code") or current["source_error_code"]).upper()
                    elif partial_recovery:
                        base.update({key: value for key, value in partial_recovery.items() if key not in {"state", "reason"}})
                        state, reason = partial_recovery["state"], partial_recovery["reason"]
                    elif current.get("dispatch") == "partial_deferred" or result.get("gap") == "RETRIEVAL_TRUNCATED":
                        state, reason = "awaiting_review", "RETRIEVAL_TRUNCATED_REPLAN_REQUIRED"
                    elif run.get("status") == "needs_user_action" or current.get("status") == "needs_user_action":
                        state, reason = "awaiting_access", run.get("error_code") or current.get("error_code") or "ACCESS_INTERACTION_REQUIRED"
                    elif failed_submission and failed_submission["state"] == "submission_unknown":
                        base.update({key: value for key, value in failed_submission.items() if key not in {"state", "reason"}})
                        state, reason = failed_submission["state"], failed_submission["reason"]
                    elif attempt["attempted"] and attempt["state"] == "unknown":
                        state, reason = "submission_unknown", "VERIFY_PRIOR_SUBMISSION_BEFORE_RETRY"
                    elif run.get("error_code") == "BROWSER_QUERY_BINDING_FAILED":
                        # A received result set without an exact history binding
                        # needs an adapter repair/observation, not another blind
                        # submission of the same query.
                        base.update(kind="plan_repair")
                        state, reason = "ready", "BROWSER_QUERY_BINDING_REPAIR_REQUIRED"
                    elif run.get("error_code") in {"USPTO_QUERY_REJECTED", "UNSUPPORTED_QUERY_SEMANTICS"}:
                        state, reason = "ready", run["error_code"]
                    elif failed_submission:
                        base.update({key: value for key, value in failed_submission.items() if key not in {"state", "reason"}})
                        state, reason = failed_submission["state"], failed_submission["reason"]
                    elif run.get("error_code") in {"CURRENT_STATUS_ROUTE_UNAVAILABLE", "AUTOMATION_NOT_VALIDATED", "AUTOMATION_PROHIBITED", "INTERNAL_ROUTE_CONTRACT_ERROR"}:
                        state, reason = "blocked", run["error_code"]
                    elif current.get("dispatch") == "blocked_reused":
                        state, reason = "blocked", current.get("error_code") or "SOURCE_ROUTE_UNAVAILABLE"
                    elif current.get("dispatch") == "rate_limit_deferred":
                        state, reason = "awaiting_access", current.get("error_code") or "SOURCE_RETRY_CONDITION_REQUIRED"
                    elif (provider in capabilities and not capabilities[provider].get("executable")
                          and not (evidence_delivery_enabled(task) and operation_accepted(capabilities[provider], row))):
                        reason = capabilities[provider].get("reason") or "SOURCE_CAPABILITY_UNAVAILABLE"
                        # A local route/acceptance check is Agent work. It does
                        # not establish an accepted source or require a login.
                        state = ("ready" if reason == "browser_adapter_requires_real_route_acceptance"
                                 else "blocked" if reason in {"automation_policy_incompatible", "free_entitlement_unvalidated"}
                                 else "awaiting_access")
                    elif result.get("gap") and "TRUNCAT" in result["gap"]:
                        state, reason = "awaiting_review", result["gap"]
                    else:
                        state, reason = "ready", "CONFIRMED_NOT_SUBMITTED_RETRY" if attempt["attempted"] and attempt["state"] == "not_submitted" else "NECESSARY_ACTION_PENDING"
                add({**base, "state": state, "reason": reason})
            # Axes and selected verification not yet planned remain visible.
            for gap in group.get("gaps", []):
                if any(marker in gap for marker in ("AXIS_MISSING", "LOCAL_LANGUAGE_MISSING", "UNPLANNED", "ACTION_OBLIGATION_BINDING_MISSING")):
                    add({**scope, "kind": "plan_repair", "state": "ready", "reason": gap})
        scope_keys = {(g["scenario_id"], g["jurisdiction"], g["right_type"]) for g in groups}
        planned_actions = {(provider, row.get("operation"), row.get("triage_candidate_id") or row.get("candidate_id"),
            row.get("scenario_id"), row.get("triage_jurisdiction") or row.get("jurisdiction"), row.get("right_type"),
            row.get("triage_action_id"), row.get("triage_decision_sha256"))
            for provider, rows in plan.get("queries", {}).items() for row in rows if row.get("triage_action_id")}
        candidate_origins = {item.get("candidate_id"): str(item.get("jurisdiction") or "").upper()
            for rows in candidates.values() if isinstance(rows, list)
            for item in rows if isinstance(item, dict)}
        for disposition in triage.get('scope_dispositions',[]):
            if disposition['scope_status']=='pending':
                add({**disposition,'kind':'product_analysis','state':'ready','reason':'CANDIDATE_OBJECT_SCOPE_REVIEW_REQUIRED'})
        for record in triage["records"]:
            scope = {key: record[key] for key in ("scenario_id", "jurisdiction", "right_type")}
            if triage_scope_enabled(task) and (record["jurisdiction"] == UNLOCATED
                    or record["right_type"] == "unknown"
                    or candidate_origins.get(record["candidate_id"]) != record["jurisdiction"]):
                base = {**scope, "candidate_id": record["candidate_id"]}
                state = record["decision"] if record.get("current") else "unreviewed"
                if state == "unreviewed":
                    add({**base, "kind": "triage", "state": "awaiting_review",
                         "reason": "CANDIDATE_TRIAGE_REQUIRED"})
                elif state in {"selected", "needs_info"}:
                    relation = record.get("annotation", {}).get("candidate_relation", {})
                    from public_identity import current as public_identity_current, limitation as public_identity_limit
                    public_review = public_identity_current(task,evidence,candidates,ledger,base,
                        supplement=supplement,task_dir=task_dir)
                    if public_review:
                        add(public_identity_limit(public_review,{**base,'kind':'agent_investigation',
                            'reason':'CANDIDATE_IDENTITY_DIRECTION_PENDING'}))
                        continue
                    user_actions = _identity_user_actions(task, evidence, record, supplement)
                    if user_actions:
                        for action in user_actions:
                            add({**base, 'kind':'user_information', 'state':'awaiting_user',
                                'reason':'CANDIDATE_IDENTITY_DIRECTION_PENDING',
                                'action_id':action['action_id'], 'action':deepcopy(action),
                                'identity_gaps':relation.get('identity_gaps', []),
                                'identity_location':relation.get('identity_location', {}),
                                'evidence_refs':list(dict.fromkeys([*record['annotation']['evidence_refs'],
                                    *action['followup_basis']['existing_evidence_refs']])),
                                'dependency':action['followup_basis']['missing_fact'],
                                'resume_condition':action['followup_basis']['completion_condition'],
                                'user_dependency_binding':{'annotation_id':record['annotation']['annotation_id'],
                                    'annotation_sha256':sha256_json(record['annotation']),
                                    'action_sha256':sha256_json(action)}})
                        continue
                    add({**base, "kind": "agent_investigation", "state": "awaiting_review",
                         "reason": "CANDIDATE_IDENTITY_DIRECTION_PENDING",
                         "identity_gaps": relation.get("identity_gaps", []),
                         "identity_location": relation.get("identity_location", {}),
                         "evidence_refs": record.get("annotation", {}).get("evidence_refs", [])})
                continue
            if tuple(scope.values()) not in scope_keys:
                continue
            state = record["decision"] if record.get("current") else "unreviewed"
            base = {**scope, "candidate_id": record["candidate_id"]}
            if state == "unreviewed":
                add({**base, "kind": "triage", "state": "awaiting_review", "reason": record.get("stale_reason") or "CANDIDATE_TRIAGE_REQUIRED"})
            elif state == "needs_info":
                actions = record.get("next_actions", [])
                from candidate_followup import (enabled as followup_enabled, latest_event as followup_event,
                    professional_wait_proof)
                followup = followup_enabled(task)
                for action in actions:
                    prior_review = (followup_event(task, "result_review", record["annotation"]["annotation_id"],
                        action.get("action_id")) if followup else None)
                    if prior_review:
                        if prior_review["outcome"] in {"waiting", "limited"}:
                            add({**base, "kind": "agent_investigation", "action_id": action.get("action_id"),
                                "state": ("awaiting_access" if action.get("kind") == "professional_review"
                                          else "awaiting_user") if prior_review["outcome"] == "waiting" else "blocked",
                                "reason": "FOLLOWUP_" + prior_review["outcome"].upper(),
                                "action_kind": action.get("kind"),
                                "dependency": prior_review.get("dependency"),
                                "resume_condition": prior_review.get("resume_condition"),
                                "limit_evidence": prior_review.get("limit_evidence"),
                                "delivery_limit": professional_wait_proof(
                                    task, evidence, record, action, supplement=supplement)})
                        elif prior_review["outcome"] == "continue":
                            add({**base, "kind": "triage", "action_id": action.get("action_id"),
                                "state": "awaiting_review", "reason": "FOLLOWUP_NEXT_DECISION_REQUIRED"})
                        continue
                    if followup and action.get("kind") == "discovery_binding":
                        from candidate_followup import latest_event
                        bound = latest_event(task, "discovery_binding", record["annotation"]["annotation_id"],
                                             action.get("action_id"))
                        if not bound:
                            add({**base, "kind": "agent_investigation", "action_id": action.get("action_id"),
                                "query_id": action.get("query_id"), "state": "ready",
                                "reason": "FOLLOWUP_DISCOVERY_BINDING_REQUIRED"})
                            continue
                        continue
                    if action.get("kind") == "source_lookup":
                        key = (action.get("provider"), action.get("operation"), record["candidate_id"],
                            record["scenario_id"], record["jurisdiction"], record["right_type"], action.get("action_id"),
                            sha256_json(record.get("annotation") or {}))
                        if key not in planned_actions:
                            add({**base, "kind": "plan_repair", "state": "ready", "reason": "NEEDS_INFO_ACTION_UNPLANNED",
                                "action_id": action.get("action_id"), "action": action, "provider": action.get("provider"),
                                "required_facts": action.get("required_facts", []), "reading_scope": action.get("reading_scope")})
                        continue  # Existing exact rows above remain the single source of dispatch work.
                    kind = action.get("kind")
                    add({**base, "kind": kind, "action_id": action.get("action_id"), "action": action,
                        "required_facts": action.get("required_facts", []), "reading_scope": action.get("reading_scope"),
                        "evidence_refs": action.get("evidence_refs", []),
                        "state": "awaiting_user" if kind in {"user_evidence", "user_information"} else "awaiting_review",
                        "reason": action.get("purpose") or "CANDIDATE_INFORMATION_REQUIRED"})
                if not any(item.get("candidate_id") == record["candidate_id"] and item.get("scenario_id") == record["scenario_id"]
                           and item.get("jurisdiction") == record["jurisdiction"] for item in entries):
                    add({**base, "kind": "triage", "state": "awaiting_review", "reason": "NEEDS_INFO_REVIEW_REQUIRED"})
        from candidate_followup import pending_review_entries
        for pending in pending_review_entries(task, evidence, plan, ledger, supplement):
            if not any(item.get("reason") == pending["reason"]
                    and item.get("action_id") == pending["action_id"]
                    and item.get("source_run_id") == pending["source_run_id"] for item in entries):
                add(pending)
        counts = {state: sum(item["state"] == state for item in entries) for state in
                  ("ready", "awaiting_review", "awaiting_access", "awaiting_user", "submission_unknown", "blocked")}
        unresolved_scopes = [{**{key: group[key] for key in ("scenario_id", "jurisdiction", "right_type")}, "gaps": group.get("gaps", [])}
                             for group in groups if group.get("gaps")]
        return {"revision": WORKFLOW_CORRECTION_REVISION, "status": "incomplete" if entries or unresolved_scopes else "complete",
                "entries": entries, "counts": counts, "unresolved_scopes": unresolved_scopes,
                "completion_meaning": "necessary_investigation_and_triage_only; independent risk reviews remain separate"}


def resolved_work_view(task, evidence, candidates, plan, ledger, *, supplement=None,
                       evidence_root=None, task_dir=None, coverage=None, browser_status=None,
                       source_capabilities=None, _skip_selected_disposition=False):
    """One frozen-input work projection for v2 dispatch, delivery and validation."""
    from discovery_semantics import verify as verify_semantics
    verify_semantics(task, plan, evidence, task_dir)
    from necessary_completion import refine_work_view, sanitize_snapshots, capability_map
    from runtime_v24 import resolved_capabilities
    snapshots = {"source-capabilities.json": {"task_id": task["task_id"],
        "sources": list((source_capabilities or {}).values())}}
    if browser_status is not None:
        snapshots["browser-execution-status.json"] = browser_status
    snapshots = sanitize_snapshots(task, snapshots)
    caps = resolved_capabilities(task, evidence, plan,
        capability_map(task, snapshots["source-capabilities.json"]), task_dir,
        browser_status=snapshots.get("browser-execution-status.json"))
    browser_status = snapshots.get("browser-execution-status.json")
    result = derive_work_view(task, evidence, candidates, plan, ledger,
        supplement=supplement, evidence_root=evidence_root, task_dir=task_dir,
        coverage=coverage, browser_status=browser_status, source_capabilities=caps)
    if api_first_enabled(task):
        from api_first_planning import next_work_entries
        additions = next_work_entries(task, plan, evidence, candidates, ledger, supplement,
            task_dir=task_dir, source_capabilities=caps, browser_status=browser_status)
        result["entries"].extend(additions)
    from discovery_semantics import work_entries as semantic_work_entries
    result["entries"].extend(semantic_work_entries(task, plan, evidence,
        candidates=candidates, ledger=ledger, supplement=supplement, task_dir=task_dir))
    from source_operation import work_entries as operation_work_entries
    result["entries"].extend(operation_work_entries(task, plan, evidence, task_dir, caps))
    from source_result_processing import work_entries as result_work_entries
    result["entries"].extend(result_work_entries(task, evidence, task_dir))
    if task_dir is not None:
        from candidate_handoff import work_entries as handoff_work_entries, project as handoff_project
        result["entries"].extend(handoff_work_entries(task, evidence, candidates, task_dir))
        if task.get("candidate_handoff_revision") == "candidate-handoff-v1":
            result["candidate_handoff"] = handoff_project(task, evidence, candidates, task_dir)
    result = refine_work_view(task, result, plan, caps, evidence=evidence, candidates=candidates,
        ledger=ledger, supplement=supplement, task_dir=task_dir, coverage=coverage,
        _skip_selected_disposition=_skip_selected_disposition)
    if task_dir is not None and task.get("triage_stage_revision"):
        from candidate_triage_stage import project as triage_stage_project, work_entries as triage_stage_work
        result["candidate_triage_stage"] = triage_stage_project(task, evidence, candidates, ledger,
            plan=plan, source_work=result["entries"], task_dir=task_dir, supplement=supplement)
        result["entries"].extend(triage_stage_work(result["candidate_triage_stage"]))
    if task.get("specialty_analysis_revision"):
        from specialty_analysis import project as specialty_project, work_entries as specialty_work
        result["specialty_analysis"] = specialty_project(task, evidence, candidates, ledger,
            supplement=supplement, source_work=result["entries"], plan=plan, capabilities=caps, task_dir=task_dir)
        result["entries"].extend(specialty_work(result["specialty_analysis"]))
    if task.get("distinctive_rights_revision"):
        from distinctive_rights import project as m07_project, work_entries as m07_work
        result["distinctive_rights"] = m07_project(task, evidence, candidates, ledger,
            supplement=supplement, source_work=result["entries"], plan=plan,
            capabilities=caps, task_dir=task_dir)
        result["entries"].extend(m07_work(result["distinctive_rights"]))
    # A language binding already present on an executed query is coverage
    # metadata, not a second executable repair.  Keep it auditable without
    # inflating the completion queue.
    information = []
    actionable_entries = []
    for entry in result["entries"]:
        reason = str(entry.get("reason") or entry.get("planning_gap") or "")
        if (entry.get("kind") in {"plan_repair", "coverage_information"}
                and (reason.endswith(":LOCAL_LANGUAGE_MISSING")
                     or reason == "LOCAL_LANGUAGE_BOUND_TO_PLANNED_QUERY")):
            information.append({**deepcopy(entry), "state": "information"})
            continue
        actionable_entries.append(entry)
    result["entries"] = actionable_entries
    result["information"] = sorted(information, key=lambda entry: sha256_json(entry))
    for scope in result.get("unresolved_scopes", []):
        scope["gaps"] = [gap for gap in scope.get("gaps", []) if not str(gap).endswith(":LOCAL_LANGUAGE_MISSING")]
    result["unresolved_scopes"] = [scope for scope in result.get("unresolved_scopes", []) if scope.get("gaps")]

    plan_index = plan_row_index(plan)
    unique = {}
    for original in result["entries"]:
        entry = deepcopy(original)
        identity = {key: entry.get(key) for key in ("scenario_id", "jurisdiction", "right_type",
            "kind", "query_id", "candidate_id", "action_id", "requirement_id", "dimension",
            "search_dimension", "discovery_intent_id", "planning_gap")}
        if entry.get("obligation_id"):
            identity["obligation_id"] = entry["obligation_id"]
        if task.get("triage_stage_revision"):
            for stage_key in ("reopen_event_id", "identity_correction_event_id"):
                if entry.get(stage_key):
                    identity[stage_key] = entry[stage_key]
        if (not entry.get("query_id") and not entry.get("action_id")) or entry.get("kind") == "plan_repair":
            identity["reason"] = entry.get("reason")
        if entry.get("reason") in {"SOURCE_RESULTS_PENDING_PROCESSING",
                                   "SOURCE_RESULT_RECEIPT_OR_INDEX_INVALID"}:
            identity["source_run_id"] = entry.get("source_run_id")
        entry["work_id"] = "WORK-" + sha256_json(identity)[:24]
        matches = plan_index.get(entry.get("query_id"), [])
        if len(matches) == 1:
            provider, row = matches[0]
            linked = [{"run_id": run["run_id"], "sha256": sha256_json(run)}
                for run in evidence.get("source_runs", []) if run.get("query_id") == row["query_id"]
                and run.get("provider") == provider and run.get("plan_entry_sha256") == sha256_json(row)]
            entry["source_run_refs"] = sorted({sha256_json(ref): ref for ref in
                [*entry.get("source_run_refs", []), *linked]}.values(),
                key=lambda ref: (str(ref.get("run_id", "")), str(ref.get("sha256", ""))))
        if entry.get("provider") in caps:
            entry["capability_sha256"] = sha256_json(caps[entry["provider"]])
        unique[sha256_json(entry)] = entry
    # Multiple axes can describe the same planning repair.  Preserve every
    # reason on one actionable row while leaving query-specific reviews and
    # evidence obligations distinct.
    coalesced = {}
    for entry in unique.values():
        if entry.get("kind") == "plan_repair" and not entry.get("query_id") and not entry.get("action_id"):
            key = tuple(entry.get(name) for name in ("scenario_id", "jurisdiction", "right_type", "kind", "state"))
            prior = coalesced.get(key)
            if prior is None:
                coalesced[key] = entry
            else:
                reasons = [*prior.get("related_reasons", [prior.get("reason")]), *entry.get("related_reasons", [entry.get("reason")])]
                prior["related_reasons"] = sorted({reason for reason in reasons if reason})
                prior["work_id"] = "WORK-" + sha256_json({"scope": key, "reasons": prior["related_reasons"]})[:24]
        else:
            coalesced[("unique", sha256_json(entry))] = entry
    if task.get("triage_stage_revision") and result.get("candidate_triage_stage"):
        from candidate_triage_stage import prioritize_work
        result["entries"] = prioritize_work(list(coalesced.values()), result["candidate_triage_stage"])
    else:
        result["entries"] = sorted(coalesced.values(), key=lambda entry: (entry["work_id"], sha256_json(entry)))
    result["counts"] = {state: sum(entry["state"] == state for entry in result["entries"])
        for state in ("ready", "awaiting_review", "awaiting_access", "awaiting_user", "submission_unknown", "blocked")}
    result["status"] = "incomplete" if result["entries"] or result.get("unresolved_scopes") else "complete"
    from product_scope import project_work
    from continuous_work_stage_a import project as continuous_project
    from continuation_stage_c import project as continuation_project
    from continuous_progress_stage_d import project as progress_project
    from review_progress_stage_a import project as review_progress_project
    from stage_risk_stage_b import project as stage_risk_project
    from execution_budget import project as budget_project
    return budget_project(task, evidence, plan, stage_risk_project(task, review_progress_project(task, progress_project(task, continuation_project(task,
        continuous_project(task, project_work(task, result, plan), evidence, plan), evidence), evidence), evidence, plan=plan, task_dir=task_dir), evidence, task_dir=task_dir), task_dir)


def work_view_from_dir(task_dir: Path, *, browser_status=None, source_capabilities=None,
                       first_review=None, second_review=None) -> dict:
    from decision_workflow import decision_snapshot
    task = load_json(task_dir / "task.json")
    import product_scope as ps
    if ps.enabled(task): ps.verify(task,load_json(task_dir/'evidence.json'),task_dir)
    if not (task_dir/'search-plan.json').is_file() and (ps.enabled(task) or task.get('product_scope_required')):
        view=ps.project_work(task,{'entries':[],'status':'incomplete','unresolved_scopes':[]})
        if not view['entries'] or (ps.enabled(task) and any(ps.direction_state(task,d)=='ready' for d in ps.directions(task))):
            view['entries'].append({'work_id':'WORK-product-plan','kind':'product_analysis','state':'ready','reason':'PRODUCT_PLAN_REQUIRED'})
        from continuous_work_stage_a import project as continuous_project
        from continuation_stage_c import project as continuation_project
        evidence = load_json(task_dir / 'evidence.json')
        from continuous_progress_stage_d import project as progress_project
        from review_progress_stage_a import project as review_progress_project
        from stage_risk_stage_b import project as stage_risk_project
        return stage_risk_project(task, review_progress_project(task, progress_project(task, continuation_project(task,
            continuous_project(task, ps.project_work(task,view)), evidence), evidence), evidence), evidence, task_dir=task_dir)
    plan = load_json(task_dir / "search-plan.json")
    candidates, ledger, evidence = _scenario_context(task_dir, task)
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    # One view owns one immutable pure-index memo, including initial coverage.
    # Public proof reuse additionally rehashes each actual file at view exit.
    from public_identity import validation_snapshot
    with decision_snapshot(task, evidence, candidates, plan, ledger, supplement), \
            validation_snapshot(task_dir, task, evidence, candidates, plan, ledger, supplement):
        if browser_status is None and (task_dir / "browser-execution-status.json").is_file():
            browser_status = load_json(task_dir / "browser-execution-status.json")
        from necessary_completion import enabled as completion_enabled, capability_map, refine_work_view, review_work
        strict_completion = completion_enabled(task)
        if source_capabilities is None and strict_completion:
            saved = task_dir / "source-capabilities.json"
            source_capabilities = capability_map(task, load_json(saved) if saved.is_file() else None)
        if source_capabilities is None and correction_enabled(task):
            from runtime_v24 import capabilities
            source_capabilities = {row["provider"]: row for row in capabilities(task, load_skill_config())}
        scopes = None
        if strict_completion:
            from assessment_v24 import scenario_coverage_by_scope
            scopes = scenario_coverage_by_scope(task, evidence, candidates, plan, ledger=ledger,
                supplement=supplement, evidence_root=task_dir)
        if evidence_delivery_enabled(task):
            result = resolved_work_view(task, evidence, candidates, plan, ledger,
                supplement=supplement, evidence_root=task_dir, task_dir=task_dir, coverage=scopes,
                browser_status=browser_status, source_capabilities=source_capabilities)
            result["review_work"] = review_work(task, evidence, candidates, plan, ledger, scopes,
                first_review, second_review, supplement=supplement, evidence_root=task_dir)
            from continuation_stage_c import project as continuation_project
            result = continuation_project(task, result, evidence)
            from continuous_progress_stage_d import project as progress_project
            result = progress_project(task, result, evidence)
            from review_progress_stage_a import project as review_progress_project
            result = review_progress_project(task, result, evidence, plan=plan, task_dir=task_dir)
            from stage_risk_stage_b import project as stage_risk_project
            result = stage_risk_project(task, result, evidence, task_dir=task_dir)
            result["work_view_sha256"] = sha256_json({key: value for key, value in result.items()
                if key not in {"work_view_sha256", "review_work"}})
            return result
        result = derive_work_view(task, evidence, candidates, plan, ledger, supplement=supplement, task_dir=task_dir,
            coverage=scopes, browser_status=browser_status, source_capabilities=source_capabilities)
        if strict_completion:
            result = refine_work_view(task, result, plan, source_capabilities or {})
            result["review_work"] = review_work(task, evidence, candidates, plan, ledger, scopes,
                first_review, second_review, supplement=supplement, evidence_root=task_dir)
        if api_first_enabled(task):
            from api_first_planning import next_work_entries
            additions = next_work_entries(task, plan, evidence, candidates, ledger, supplement, task_dir=task_dir)
            seen = {sha256_json(item) for item in result["entries"]}
            result["entries"].extend(item for item in additions if sha256_json(item) not in seen)
            result["counts"] = {state: sum(item["state"] == state for item in result["entries"])
                for state in ("ready", "awaiting_review", "awaiting_access", "awaiting_user", "submission_unknown", "blocked")}
            if result["entries"]:
                result["status"] = "incomplete"
        from continuous_work_stage_a import project as continuous_project
        from continuation_stage_c import project as continuation_project
        from continuous_progress_stage_d import project as progress_project
        from review_progress_stage_a import project as review_progress_project
        from stage_risk_stage_b import project as stage_risk_project
        return stage_risk_project(task, review_progress_project(task, progress_project(task, continuation_project(task,
            continuous_project(task, result, evidence, plan), evidence), evidence), evidence, plan=plan, task_dir=task_dir), evidence, task_dir=task_dir)


def scenario_row_bindings(task: dict, row: dict) -> list[dict]:
    """Return current, exact scenario bindings; old rows are never reinterpreted."""
    from decision_workflow import scenario_index, scenario_sha256, scenario_right_types
    if not scenario_workflow_enabled(task):
        return []
    scenarios = scenario_index(task)
    bindings = row.get("scenario_bindings")
    if bindings is None:
        bindings = [{"scenario_id": row.get("scenario_id"), "scenario_sha256": row.get("scenario_sha256")}]
    if not isinstance(bindings, list) or not bindings:
        return []
    seen = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            return []
        identity = binding.get("scenario_id")
        if (identity not in scenarios or identity in seen
                or binding.get("scenario_sha256") != scenario_sha256(scenarios[identity])
                or row.get("right_type") not in scenario_right_types(scenarios[identity])):
            return []
        seen.add(identity)
    return bindings


def necessary_scenario_row_bindings(task: dict, row: dict) -> list[dict]:
    """Filter obligations without rewriting or invalidating original bindings."""
    from decision_workflow import scenario_index, necessary_scenario_right_types
    scenarios = scenario_index(task)
    return [binding for binding in scenario_row_bindings(task, row)
            if row.get("right_type") in necessary_scenario_right_types(task, scenarios[binding["scenario_id"]])]


def bind_scenario_action(task: dict, provider: str, row: dict, *, purpose: str,
                         decision: dict | None = None, obligation_key: Any = None,
                         scenario_id: str | None = None) -> dict:
    """Bind a newly constructed row, never mutate an existing plan entry."""
    from decision_workflow import scenario_index, scenario_sha256, necessary_scenario_right_types
    from provider_utils import query_identity, PLAN_META_KEYS
    bound = deepcopy(row)
    bound.update(decision_workflow_revision=task["decision_workflow_revision"], action_purpose=purpose)
    if correction_enabled(task):
        bound["workflow_correction_revision"] = WORKFLOW_CORRECTION_REVISION
        if provider == "uspto_patent_browser" and bound.get("operation") == "candidate_verification":
            # PPS 4.3 writes literal PN searches back as quoted terms in its
            # editor/history. Bind new actions to that same exact spelling;
            # never weaken history equality or reinterpret older receipts.
            bound["query_compiler_revision"] = "ppubs-quoted-record-v1"
    from product_change import enabled as product_change_enabled
    if product_change_enabled(task):
        bound['product_target_sha256'] = task['product_identity']['sha256']
        bound['product_change_version'] = task['product_change_version']
    if decision:
        annotation = decision["annotation"]
        bound.update(scenario_id=decision["scenario_id"], scenario_sha256=decision["scenario_sha256"],
                     triage_decision_id=annotation["annotation_id"], triage_decision_sha256=sha256_json(annotation),
                     triage_jurisdiction=decision["jurisdiction"], triage_candidate_id=decision["candidate_id"])
    else:
        bound["scenario_bindings"] = [{"scenario_id": key, "scenario_sha256": scenario_sha256(value)}
                                      for key, value in sorted(scenario_index(task).items())
                                      if row.get("right_type") in necessary_scenario_right_types(task, value)
                                      and (scenario_id is None or key == scenario_id)]
        if scenario_id is not None and not bound["scenario_bindings"]:
            raise ValueError("ACTION_SCENARIO_NOT_APPLICABLE")
    import product_scope as ps
    from product_change import dispatch_reason as product_change_dispatch_reason
    change_reason = product_change_dispatch_reason(task,row)
    if change_reason: return blocked(change_reason)
    if ps.enabled(task):
        original = bound.get('scenario_bindings') or ([{'scenario_id':bound['scenario_id'],'scenario_sha256':bound['scenario_sha256']}] if bound.get('scenario_id') else [])
        filtered = ps.bind(task,bound,original)
        if 'scenario_bindings' in bound: bound['scenario_bindings'] = filtered
    from product_delivery import bind_fact_versions
    bind_fact_versions(task, bound)
    bound["evidence_obligation_id"] = "OBL-" + sha256_json({
        "scope": {key: bound.get(key) for key in ("scenario_id", "scenario_sha256", "scenario_bindings", "jurisdiction", "right_type", "triage_jurisdiction")},
        "purpose": purpose, "key": obligation_key if obligation_key is not None else bound.get("candidate_id")})[:20]
    identity = {key: value for key, value in bound.items() if key not in PLAN_META_KEYS or key in SCENARIO_META_KEYS}
    identity["right_type"] = bound["right_type"]
    bound["query_id"] = query_identity(provider, bound["operation"], bound["jurisdiction"], str(bound.get("q") or ""), identity)
    return bound


def _scenario_context(task_dir: Path, task: dict) -> tuple[dict, dict, dict]:
    from annotate_materiality import load_materiality_ledger
    candidates = load_json(task_dir / "normalized-candidates.json") if (task_dir / "normalized-candidates.json").is_file() else {}
    evidence = load_json(task_dir / "evidence.json")
    ledger = load_materiality_ledger(task_dir, task["task_id"], task=task)
    return candidates, ledger, evidence


def scenario_supplement(task_dir: Path, *, task=None, evidence=None, explicit_path=None, loader=None) -> dict | None:
    """Load the shared supplement contract; legacy tasks retain their old branch.

    The batch decoder may supply its existing loader, but file verification is
    never cached across dispatches or replaced by a timestamp/manifest hash.
    """
    task_dir = Path(task_dir)
    task = load_json(task_dir / "task.json") if task is None else task
    read = loader or load_json
    if not correction_enabled(task):
        path = Path(explicit_path) if explicit_path is not None else task_dir / "supplemental-evidence.json"
        return read(path) if path.is_file() else None
    # Local import reuses the assessment parser and validator without creating
    # an import cycle or a second manifest/attachment acceptance rule.
    from assessment_estimate import resolve_estimate_supplement, validate_supplement
    from common import ensure_object
    path = resolve_estimate_supplement(task_dir, task, explicit_path)
    if path is None:
        return None
    supplement = ensure_object(read(path), "supplement")
    if evidence is None and (task_dir / "evidence.json").is_file():
        evidence = load_json(task_dir / "evidence.json")
    root = task.get("evidence_root") or task.get("historical_evidence_root") or task_dir
    validate_supplement(supplement, root, task=task, evidence=evidence)
    return supplement


def scenario_fact_reuse(task: dict, plan: dict, evidence: dict, candidates: dict, ledger: dict,
                        provider: str, row: dict, *, supplement=None, evidence_root=None,
                        task_dir=None) -> dict | None:
    """Qualified original facts may close an obligation, never become a new run."""
    import product_scope as ps
    if ps.dispatch_reason(task,row): return None
    from trusted_api import action_facts
    accepted = action_facts(task, evidence, row)
    if accepted is not None:
        return accepted
    from same_task_evidence import qualified_fact_reuse
    return qualified_fact_reuse(task, plan, evidence, candidates, ledger, provider, row,
                               supplement=supplement, evidence_root=evidence_root, task_dir=task_dir)


def scenario_reading_material(task: dict, plan: dict, evidence: dict, candidates: dict, ledger: dict,
                              provider: str, row: dict, *, supplement=None, evidence_root=None, task_dir=None) -> dict | None:
    from same_task_evidence import qualified_reading_material
    return qualified_reading_material(task, plan, evidence, candidates, ledger, provider, row,
        supplement=supplement, evidence_root=evidence_root, task_dir=task_dir)


def scenario_fact_reuse_from_dir(task_dir: Path, provider: str, row: dict) -> dict | None:
    task = load_json(task_dir / "task.json")
    if not scenario_workflow_enabled(task):
        return None
    plan = load_json(task_dir / "search-plan.json")
    candidates, ledger, evidence = _scenario_context(task_dir, task)
    return scenario_fact_reuse(task, plan, evidence, candidates, ledger, provider, row,
                               supplement=scenario_supplement(task_dir, task=task, evidence=evidence), task_dir=task_dir)


def scenario_historical_reuse(task: dict, provider: str, row: dict, candidates: dict,
                              supplement: dict | None, *, evidence_root=None,
                              scenario_id: str | None = None) -> dict | None:
    """Reuse retained facts, not execution receipts or old triage decisions.

    A shared action is skipped only when every currently bound scenario has an
    explicit retained-source review. A scope assessment may consume just its own.
    """
    import product_scope as ps
    if ps.enabled(task) and ps.binding_state(task,row,scenario_id)!='ready': return None
    if not scenario_workflow_enabled(task) or not isinstance(supplement, dict):
        return None
    from historical_evidence import historical_action_reuse, historical_evidence_root
    try:
        root = historical_evidence_root(task, supplement, evidence_root)
    except (OSError, ValueError, TypeError):
        return None
    if root is None or not isinstance(supplement.get("evidence"), list):
        return None
    reuse_ids = [item.get("evidence_id") for item in supplement["evidence"]
                 if isinstance(item, dict) and item.get("kind") == "historical_source_reuse"]
    if any(not isinstance(identity, str) or not identity for identity in reuse_ids) or len(set(reuse_ids)) != len(reuse_ids):
        return None
    bindings = necessary_scenario_row_bindings(task, row)
    if scenario_id is not None:
        bindings = [binding for binding in bindings if binding["scenario_id"] == scenario_id]
    if not bindings:
        return None
    retained = []
    for binding in bindings:
        scoped = {**supplement, "evidence": [item for item in supplement["evidence"]
                  if isinstance(item, dict) and isinstance(item.get("reuse_binding"), dict)
                  and item["reuse_binding"].get("scenario_id") == binding["scenario_id"]]}
        result = historical_action_reuse(task, provider, row, candidates, scoped, root)
        if not result or result.get("complete") is not True:
            return None
        retained.append(result)
    if scenario_id is not None:
        return retained[0]
    return {"complete": True, "dispatch": "historical_reused", "source_query_performed": False,
            "authority_scope": "retained_source_facts_only", "by_scenario": retained}


def scenario_historical_reuse_from_dir(task_dir: Path, provider: str, row: dict) -> dict | None:
    task = load_json(task_dir / "task.json")
    if not scenario_workflow_enabled(task):
        return None
    plan = load_json(task_dir / "search-plan.json")
    candidates, ledger, evidence = _scenario_context(task_dir, task)
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    if scenario_dispatch_block(task, plan, provider, row, candidates, ledger, evidence,
                               supplement=supplement, task_dir=task_dir):
        return None
    return scenario_historical_reuse(task, provider, row, candidates, supplement)


def scenario_dispatch_block(task: dict, plan: dict, provider: str, row: dict,
                            candidates: dict, ledger: dict, evidence: dict, *, supplement: dict | None = None,
                            for_dispatch: bool = True, task_dir: Path | None = None) -> dict | None:
    """Authorization only: a source material flag cannot grant workflow authority."""
    if not scenario_workflow_enabled(task):
        return None
    from decision_workflow import effective_decision
    from annotate_materiality import iter_candidates
    def blocked(code):
        return {"code": code, "query_id": row.get("query_id"), "reason": code,
                "status": "cancelled", "submission_state": "not_submitted"}
    if for_dispatch:
        from continuation_stage_c import dispatch_block as continuation_dispatch_block
        if continuation_dispatch_block(task, evidence, row):
            return blocked("USER_ACTIVE_PAUSE")
    def recovery_or_none():
        if for_dispatch:
            from recovery_stage_b import dispatch_block as recovery_dispatch_block
            reason = recovery_dispatch_block(task, evidence, provider, row)
            if reason:
                return blocked(reason)
        return None
    from common import plan_free_policy_matches_task
    from provider_utils import PLAN_META_KEYS, query_identity
    if (task.get("schema_version") != "2.4-free" or plan.get("schema_version") != task.get("schema_version")
            or plan.get("task_id") != task.get("task_id") or not plan_free_policy_matches_task(task, plan)):
        return blocked("SCENARIO_PLAN_IDENTITY_MISMATCH")
    if (evidence.get("task_id") != task.get("task_id") or evidence.get("schema_version") != task.get("schema_version")
            or (candidates.get("task_id") is not None and candidates.get("task_id") != task.get("task_id"))):
        return blocked("SCENARIO_EVIDENCE_IDENTITY_MISMATCH")
    matches = plan_row_index(plan).get(row.get("query_id"), [])
    identity = {key: value for key, value in row.items() if key not in PLAN_META_KEYS or key in SCENARIO_META_KEYS}
    identity["right_type"] = row.get("right_type")
    if (len(matches) != 1 or matches[0][0] != provider or sha256_json(matches[0][1]) != sha256_json(row)
            or row.get("query_id") != query_identity(provider, row.get("operation"), row.get("jurisdiction"), str(row.get("q") or ""), identity)):
        return blocked("SCENARIO_QUERY_IDENTITY_MISMATCH")
    # A resolved candidate's old action cannot become live again merely because
    # its progress or product binding now requires review. Keep temporary gates
    # for current actions, after establishing plan/row identity above.
    if for_dispatch and row.get("triage_action_id") and row.get("triage_candidate_id"):
        found_current = [(collection, item) for collection, item in iter_candidates(candidates)
                         if item.get("candidate_id") == row.get("triage_candidate_id")]
        if len(found_current) == 1:
            current_decision = effective_decision(task, ledger, *found_current[0], row.get("scenario_id"),
                row.get("triage_jurisdiction") or row.get("jurisdiction"), row.get("right_type"),
                evidence=evidence, supplement=supplement)
            if (current_decision.get("current") is True
                    and (current_decision.get("annotation") or {}).get("annotation_id") != row.get("triage_decision_id")):
                return blocked("TRIAGE_ACTION_STALE")
    if for_dispatch:
        from continuous_progress_stage_d import dispatch_block as progress_dispatch_block
        progress_reason = progress_dispatch_block(task, evidence, provider, row)
        if progress_reason:
            return blocked(progress_reason)
        from review_progress_stage_a import dispatch_block as review_progress_dispatch_block
        review_progress_reason = review_progress_dispatch_block(task, evidence, provider, row)
        if review_progress_reason:
            return blocked(review_progress_reason)
    from product_delivery import validate_image_query
    image_reason = validate_image_query(task, provider, row)
    if image_reason: return blocked(image_reason)
    from product_delivery import validate_fact_query
    fact_reason = validate_fact_query(task, row)
    if fact_reason: return blocked(fact_reason)
    import product_scope as ps
    if ps.enabled(task):
        reason = ps.dispatch_reason(task,row)
        if reason: return blocked(reason)
    from source_operation import enabled as operation_review_enabled
    if for_dispatch and operation_review_enabled(task):
        from source_operation_registry import latest_states
        operation_key = tuple(row.get(key, '') for key in
            ('jurisdiction', 'right_type', 'operation', 'query_compiler_revision', 'search_dimension'))
        if latest_states(provider).get(operation_key) == 'unavailable':
            return blocked('SOURCE_OPERATION_UNAVAILABLE')
    if for_dispatch and validated_query_cancellation(task, plan, row):
        return blocked("SCENARIO_ACTION_CANCELLED")
    if for_dispatch and validated_query_substitution(task, plan, row):
        return blocked("SCENARIO_ACTION_REPLACED")
    if (plan.get("decision_workflow_revision") != task.get("decision_workflow_revision")
            or row.get("decision_workflow_revision") != task.get("decision_workflow_revision")
            or not scenario_row_bindings(task, row)):
        return blocked("SCENARIO_ACTION_STALE")
    if correction_enabled(task) and (plan.get("workflow_correction_revision") != WORKFLOW_CORRECTION_REVISION
            or row.get("workflow_correction_revision") != WORKFLOW_CORRECTION_REVISION):
        return blocked("WORKFLOW_CORRECTION_ACTION_STALE")
    if not necessary_scenario_row_bindings(task, row):
        return blocked("SCENARIO_ACTION_NOT_NECESSARY")
    if correction_enabled(task) and for_dispatch and action_attempt_state(evidence, provider, row)["state"] == "unknown":
        return blocked("TRIAGE_ATTEMPT_STATE_UNKNOWN")
    if api_first_enabled(task) and for_dispatch:
        from api_first_planning import dispatch_block
        api_block = dispatch_block(task, plan, evidence, candidates, ledger, provider, row,
                                   supplement, task_dir=task_dir)
        if api_block:
            if evidence_delivery_enabled(task):
                temporary = {"API_DISCOVERY_MERGE_REQUIRED": "TRIAGE_REVIEW_REQUIRED",
                    "API_DISCOVERY_TRIAGE_REQUIRED": "TRIAGE_REVIEW_REQUIRED",
                    "API_DISCOVERY_CARD_IDENTITY_REVIEW_REQUIRED": "TRIAGE_REVIEW_REQUIRED",
                    "API_DISCOVERY_SUBMISSION_UNKNOWN_NO_RETRY": "TRIAGE_ATTEMPT_STATE_UNKNOWN"}
                if api_block in temporary:
                    # Keep the authorized row while its independent review or
                    # submission audit is pending; do not append cancellation.
                    return {**blocked(temporary[api_block]), "cause": api_block}
            return blocked(api_block)
    if for_dispatch and task.get("triage_followup_revision"):
        from candidate_followup import dispatch_error as followup_dispatch_error
        followup_error = followup_dispatch_error(task, provider, row, candidates, ledger, evidence,
                                                 supplement=supplement)
        if followup_error:
            return blocked(followup_error)
    if for_dispatch and row.get('action_purpose') == 'discovery':
        from discovery_semantics import dispatch_error
        semantic_error = dispatch_error(task, plan, evidence, provider, row)
        if semantic_error: return blocked(semantic_error)
    if (task.get("specialty_workflow_revision") == "asset-scope-v1"
            and provider == "uspto_tmsearch_browser" and row.get("jurisdiction") == "US"
            and row.get("right_type") == "trademark_figurative"
            and row.get("operation") == "trademark_recall"
            and (row.get("filters") or {}).get("field") not in {"design_code", "mark_description"}):
        # Old brand/OCR word rows are not figurative obligations in the new
        # contract. Their original bytes/receipts remain; valid DC/DE axes and
        # observed-mark review are still required before this scope completes.
        return blocked("FIGURATIVE_QUERY_FIELD_UNSUPPORTED")
    if provider == "asset_provenance" and task.get("specialty_workflow_revision") == "asset-scope-v1":
        from record_asset_provenance import asset_scope
        bindings = scenario_row_bindings(task, row)
        if len(bindings) != 1 or row.get("asset_scope_sha256") != asset_scope(task, bindings[0]["scenario_id"], row.get("right_type"))["scope_sha256"]:
            return blocked("PROVENANCE_SCOPE_STALE")
    if not set(str(row.get("jurisdiction") or "").split(",")) <= set(task.get("target_jurisdictions", [])) and not (
            row.get("jurisdiction") == "EP" and row.get("action_purpose") == "document_content"):
        return blocked("SCENARIO_COUNTRY_NOT_IN_SCOPE")
    candidate_id = row.get("triage_candidate_id") or row.get("candidate_id")
    requires_candidate = (row.get("operation") in {"candidate_verification", "candidate_detail", "document_retrieval"}
                          or row.get("action_purpose") not in {"recall", "provenance", "discovery"}
                          or row.get("execution_phase") in {"verification", "enrichment", "needs_info"}
                          or any(str(ref).startswith("candidate:") for ref in row.get("derived_from", []))
                          or (row.get("execution_phase") == "expansion" and row.get("search_dimension") in {"owner", "classification"}
                              and not (api_first_enabled(task) and row.get("action_purpose") == "discovery")))
    if requires_candidate and (not candidate_id or not row.get("triage_decision_id") or not row.get("triage_decision_sha256")
                               or not row.get("triage_jurisdiction") or not row.get("scenario_id") or row.get("scenario_bindings")):
        return blocked("TRIAGE_ACTION_BINDING_REQUIRED")
    if not candidate_id and not row.get("triage_decision_id"):
        return recovery_or_none()  # Shared initial product recall/provenance, not candidate authority.
    found = [(collection, item) for collection, item in iter_candidates(candidates) if item.get("candidate_id") == candidate_id]
    if len(found) != 1:
        return blocked("TRIAGE_CANDIDATE_IDENTITY_MISSING")
    if row.get("triage_jurisdiction") != row.get("jurisdiction") and not (
            row.get("jurisdiction") == "EP" and row.get("action_purpose") == "document_content"):
        return blocked("TRIAGE_ACTION_COUNTRY_MISMATCH")
    collection, candidate = found[0]
    from decision_workflow import triage_scope_enabled, UNLOCATED
    if triage_scope_enabled(task) and (row.get("triage_jurisdiction") == UNLOCATED
            or candidate.get("right_type") == "unknown"
            or str(candidate.get("jurisdiction") or "").upper() != row.get("triage_jurisdiction")):
        return blocked("TRIAGE_IDENTITY_LOCATION_REQUIRED")
    decision = effective_decision(task, ledger, collection, candidate, row.get("scenario_id"),
                                  row.get("triage_jurisdiction") or row.get("jurisdiction"),
                                  row.get("right_type"), evidence=evidence, supplement=supplement)
    annotation = decision.get("annotation") or {}
    if (decision.get("current") is not True or annotation.get("annotation_id") != row.get("triage_decision_id")
            or sha256_json(annotation) != row.get("triage_decision_sha256")):
        return blocked("TRIAGE_ACTION_STALE")
    if decision.get("decision") == "selected":
        return recovery_or_none()
    if decision.get("decision") == "needs_info" and row.get("triage_action_id"):
        from provider_utils import PLAN_META_KEYS
        params = {key: value for key, value in row.items() if key not in PLAN_META_KEYS and key not in SCENARIO_META_KEYS}
        for action in decision.get("next_actions", []):
            expected_params = deepcopy(action.get("params"))
            if (correction_enabled(task) and provider == "uspto_patent_browser"
                    and row.get("operation") == "candidate_verification"
                    and row.get("query_compiler_revision") == "ppubs-quoted-record-v1"
                    and isinstance(expected_params, dict)):
                expected_params.setdefault("query_compiler_revision", "ppubs-quoted-record-v1")
            if (action.get("action_id") == row["triage_action_id"] and action.get("kind") == "source_lookup"
                    and action.get("provider") == provider and action.get("operation") == row.get("operation")
                    and action.get("max_attempts") == 1 and expected_params == params
                    and row.get("action_purpose") == "needs_info:" + str(action.get("purpose") or "")):
                if for_dispatch and any(run.get("provider") == provider and run.get("query_id") == row.get("query_id")
                       and run.get("plan_entry_sha256") == sha256_json(row) and run.get("status") not in {"cancelled", "not_applicable"}
                       and run.get("submission_state") != "not_submitted" for run in evidence.get("source_runs", [])):
                    if correction_enabled(task):
                        attempt = action_attempt_state(evidence, provider, row)
                        if attempt["state"] == "unknown":
                            return blocked("TRIAGE_ATTEMPT_STATE_UNKNOWN")
                        if attempt["state"] == "submitted":
                            if (attempt["run"] or {}).get("status") in {"success", "no_result"}:
                                return blocked("TRIAGE_REVIEW_REQUIRED")
                            # 08B owns the single reviewed recovery of a failed
                            # submission. Keep legacy bounds and all later
                            # reading/source gates; never grant a fresh action.
                            from recovery_stage_b import recovery_state
                            recovery = recovery_state(task, evidence, provider, row)
                            if not recovery or recovery["state"] != "ready":
                                return blocked("TRIAGE_BOUNDED_ACTION_ALREADY_ATTEMPTED")
                    else:
                        return blocked("TRIAGE_BOUNDED_ACTION_ALREADY_ATTEMPTED")
                if correction_enabled(task) and not reading_contract_valid(row):
                    return blocked("NEEDS_INFO_READING_CONTRACT_INVALID")
                return recovery_or_none()
    return blocked("TRIAGE_ACTION_NOT_SELECTED")


def scenario_dispatch_block_from_dir(task_dir: Path, provider: str, row: dict) -> dict | None:
    task = load_json(task_dir / "task.json")
    if not scenario_workflow_enabled(task):
        return None
    plan = load_json(task_dir / "search-plan.json")
    matches = [item for item in plan.get("queries", {}).get(provider, []) if item.get("query_id") == row.get("query_id")]
    if len(matches) != 1 or sha256_json(matches[0]) != sha256_json(row):
        return {"code": "SCENARIO_PLAN_ROW_CHANGED", "reason": "SCENARIO_PLAN_ROW_CHANGED", "status": "cancelled"}
    candidates, ledger, evidence = _scenario_context(task_dir, task)
    blocked = scenario_dispatch_block(task, plan, provider, row, candidates, ledger, evidence,
                                   supplement=scenario_supplement(task_dir, task=task, evidence=evidence),
                                   task_dir=task_dir)
    if blocked:
        return blocked
    if api_first_enabled(task):
        from api_first_planning import followup_source_files_error
        source_error = followup_source_files_error(task_dir, task, evidence, row)
        if source_error:
            return {"code": source_error, "reason": source_error, "status": "cancelled", "submission_state": "not_submitted"}
        from discovery_budget import source_files_error as purpose_source_files_error
        source_error = purpose_source_files_error(task_dir, task, plan, evidence, row)
        if source_error:
            return {"code": source_error, "reason": source_error, "status": "cancelled", "submission_state": "not_submitted"}
    from discovery_semantics import enabled as semantics_enabled, verify as verify_semantics
    if semantics_enabled(task) and row.get('action_purpose') == 'discovery':
        try:
            verify_semantics(task, plan, evidence, task_dir)
        except ValueError as exc:
            return {"code": str(exc), "reason": str(exc), "status": "cancelled", "submission_state": "not_submitted"}
    failure = browser_submitted_failure_state(task, evidence, provider, row)
    if failure and failure["state"] in {"blocked", "submission_unknown"}:
        return {**failure, "code": failure["reason"], "status": "access_limited", "submission_state": "not_submitted"}
    return None


def reconcile_scenario_actions(task_dir: Path, task: dict, plan: dict,
                               candidates: dict | None = None, ledger: dict | None = None, evidence: dict | None = None) -> None:
    """Append cancellation audit for stale actions; retain all query bytes."""
    if not scenario_workflow_enabled(task):
        return
    if candidates is None or ledger is None or evidence is None:
        candidates, ledger, evidence = _scenario_context(task_dir, task)
    dispositions = plan.setdefault("execution_dispositions", [])
    if not isinstance(dispositions, list):
        raise ValueError("EXECUTION_DISPOSITIONS_INVALID")
    supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
    from decision_workflow import decision_snapshot
    pending = []
    with decision_snapshot(task, evidence, candidates, plan, ledger, supplement):
        for provider, rows in plan.get("queries", {}).items():
            for row in rows:
                blocked = scenario_dispatch_block(task, plan, provider, row, candidates, ledger, evidence,
                                                  supplement=supplement, task_dir=task_dir)
                if blocked and not validated_query_cancellation(task, plan, row):
                    if correction_enabled(task) and blocked["code"] in TEMPORARY_DISPATCH_CODES:
                        continue
                    pending.append({"query_id": row["query_id"], "plan_entry_sha256": sha256_json(row),
                                        "status": "cancelled", "reason": blocked["reason"],
                                        "recorded_at": now_iso(), "recorded_by": "scenario-triage-reconciler"})
    dispositions.extend(pending)


def assert_recall_planning_contract(task: dict, plan: dict | None = None) -> None:
    correction_enabled(task)
    retrieval_revision = task.get("retrieval_workflow_revision")
    from common import api_first_revision_enabled
    if retrieval_revision is not None and (not api_first_revision_enabled(retrieval_revision) or not api_first_enabled(task)):
        raise ValueError("RETRIEVAL_WORKFLOW_REVISION_INVALID")
    if plan is not None and plan.get("retrieval_workflow_revision") != retrieval_revision:
        raise ValueError("RETRIEVAL_WORKFLOW_REVISION_MISMATCH")
    epo_revision = task.get("epo_query_revision")
    if epo_revision not in (None, "ops-cql-v1"):
        raise ValueError("EPO_QUERY_REVISION_INVALID")
    if plan is not None and plan.get("epo_query_revision") != epo_revision:
        raise ValueError("EPO_QUERY_REVISION_MISMATCH")
    if api_first_enabled(task) and plan is not None:
        if (plan.get("retrieval_policy") != task.get("retrieval_policy")
                or plan.get("retrieval_policy_sha256") != sha256_json(task.get("retrieval_policy"))):
            raise ValueError("RETRIEVAL_POLICY_CHANGED")
    if plan is not None and plan.get("workflow_correction_revision") != task.get("workflow_correction_revision"):
        raise ValueError("WORKFLOW_CORRECTION_REVISION_MISMATCH")
    execution_revision = task.get("execution_policy_revision")
    if execution_revision not in (None, "continuous-work-v1", "continuous-work-v2"):
        raise ValueError("EXECUTION_POLICY_REVISION_INVALID")
    if plan is not None and plan.get("execution_policy_revision") != execution_revision:
        raise ValueError("EXECUTION_POLICY_REVISION_MISMATCH")
    specialty = task.get("specialty_workflow_revision")
    if specialty not in (None, "asset-scope-v1") or (specialty and not scenario_workflow_enabled(task)):
        raise ValueError("SPECIALTY_WORKFLOW_REVISION_INVALID")
    if plan is not None and plan.get("specialty_workflow_revision") != specialty:
        raise ValueError("SPECIALTY_WORKFLOW_REVISION_MISMATCH")
    if scenario_workflow_enabled(task):
        from decision_workflow import scenario_index
        scenario_index(task)
        if plan is not None and plan.get("decision_workflow_revision") != task.get("decision_workflow_revision"):
            raise ValueError("DECISION_WORKFLOW_REVISION_MISMATCH")
    revision = task.get("recall_planning_revision")
    if revision is not None and (revision != RECALL_PLANNING_REVISION or not recall_integrity_enabled(task)):
        raise ValueError("RECALL_PLANNING_REVISION_INVALID")
    if plan is not None and plan.get("recall_planning_revision") != revision:
        raise ValueError("RECALL_PLANNING_REVISION_MISMATCH")
    if plan is not None and identity_discovery_enabled(task) and not api_first_enabled(task):
        followups = task.get("discovery_followups", [])
        target_ids = {r.get("query_id") for r in plan.get("queries", {}).get("serpapi_google_patents", []) if isinstance(r, dict)}
        if (not isinstance(followups, list) or any(not isinstance(d, dict) or not isinstance(d.get("query_id"), str) or not d["query_id"]
                or d["query_id"] not in target_ids for d in followups)):
            raise ValueError("DISCOVERY_FOLLOWUPS_INVALID")


def product_clue_inventory(task: dict) -> list[dict]:
    """Return meaningful captured/analysed clues, never marketing paragraphs."""
    product = task.get("product") or {}
    raw = product.get("raw_capture") or {}
    clues = []
    for parent, fields, prefix in ((product, ("structure",), "product"),
                                   (raw, ("structure", "visual_features", "ocr_text"), "product.raw_capture")):
        if not isinstance(parent, dict):
            continue
        for field in fields:
            values = parent.get(field) or []
            if not isinstance(values, list):
                raise ValueError(f"{prefix}.{field} must be an array")
            for index, value in enumerate(values):
                text = str(value.get("description") or "") if isinstance(value, dict) else value if isinstance(value, str) else ""
                if normalize_text(text) in {"", "unknown", "not available", "n a", "none", "未知", "不详", "未提供"}:
                    continue
                clues.append({"source_path": f"{prefix}.{field}[{index}]", "source_sha256": sha256_json(value),
                              "value": text.strip(), "kind": field})
    return clues


def clue_handoff_gaps(task: dict) -> list[dict]:
    if not identity_discovery_enabled(task):
        return []
    inventory = product_clue_inventory(task)
    analysis = task.get("product", {}).get("analysis") or {}
    if not isinstance(analysis, dict):
        return [{"code": "CLUE_DISPOSITIONS_INVALID", "blocking_planning": True}]
    rows = analysis.get("clue_dispositions", [])
    supplied = task.get("query_terms")
    terms = {sha256_json(t): t for t in supplied if isinstance(t, dict)} if isinstance(supplied, list) else {}
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        return [{"code": "CLUE_DISPOSITIONS_INVALID", "blocking_planning": True}]
    gaps = []
    for clue in inventory:
        matches = [r for r in rows if r.get("source_path") == clue["source_path"]]
        valid = len(matches) == 1
        row = matches[0] if valid else {}
        valid = valid and row.get("source_sha256") == clue["source_sha256"] and isinstance(row.get("reason"), str) and bool(row["reason"].strip())
        if row.get("disposition") == "mapped":
            refs = row.get("query_term_sha256")
            valid = valid and isinstance(refs, list) and bool(refs) and all(isinstance(ref, str) and ref in terms for ref in refs)
        elif row.get("disposition") == "needs_verification":
            # An uncertain OCR transcription remains a retained, unresolved
            # fact in the v2 delivery. It cannot silently become a query term.
            facts = task.get('product_scope', {}).get('facts', [])
            valid = (valid and task.get('product_delivery_revision') == 'image-fact-v1'
                     and clue['kind'] == 'ocr_text' and isinstance(row.get('question'), str)
                     and bool(row['question'].strip()) and not row.get('query_term_sha256')
                     and not any(term.get('derived_from') == clue['source_path'] for term in terms.values())
                     and any(fact.get('source_path') == clue['source_path']
                             and sha256_json(fact.get('value')) == clue['source_sha256']
                             and fact.get('status') == 'unknown'
                             and fact.get('verification') == 'unverified'
                             and fact.get('question') == row['question'] for fact in facts))
        else:
            valid = valid and row.get("disposition") == "excluded"
        if not valid:
            gaps.append({"code": "PRODUCT_CLUE_UNACCOUNTED", "blocking_planning": True,
                         "source_path": clue["source_path"], "source_sha256": clue["source_sha256"]})
    return gaps


def validated_discovery_followup(task_dir: Path, task: dict, plan: dict, evidence: dict,
                                 row: dict, max_age_hours: float = 48) -> dict | None:
    """Permit a single unused fallback after a traceable recall-quality decision.

    This cannot retry an already-consumed query, add queries, enable a provider,
    increase a budget, or replace the client's account/credit validation.
    """
    if api_first_enabled(task):
        from api_first_planning import followup_validation
        candidates, ledger, _ = _scenario_context(task_dir, task)
        if row.get("discovery_role") == "primary":
            return None
        error = followup_validation(task, plan, evidence, candidates, ledger, row,
            scenario_supplement(task_dir, task=task, evidence=evidence), task_dir=task_dir)
        if error:
            raise ValueError(error)
        return next(d for d in task.get("discovery_followups", []) if d.get("query_id") == row.get("query_id"))
    if not identity_discovery_enabled(task) or not serpapi_free_enabled(task):
        return None
    assert_recall_planning_contract(task, plan)
    decisions = task.get("discovery_followups", [])
    if not isinstance(decisions, list):
        raise ValueError("DISCOVERY_FOLLOWUPS_INVALID")
    decisions = [d for d in decisions if isinstance(d, dict) and d.get("query_id") == row.get("query_id")]
    if not decisions:
        return None
    if len(decisions) != 1:
        raise ValueError("DISCOVERY_FOLLOWUP_AMBIGUOUS")
    decision = decisions[0]
    if (not task.get("task_id") or plan.get("task_id") != task["task_id"]
            or evidence.get("task_id") != task["task_id"] or evidence.get("schema_version") != task.get("schema_version")):
        raise ValueError("DISCOVERY_FOLLOWUP_TASK_MISMATCH")
    primary = [p for p in plan.get("queries", {}).get("serper_patents", []) if p.get("query_id") == row.get("fallback_query_id")]
    targets = [p for p in plan.get("queries", {}).get("serpapi_google_patents", []) if p == row]
    if (len(primary) != 1 or len(targets) != 1 or decision.get("plan_entry_sha256") != sha256_json(row)
            or decision.get("reason_code") not in {"zero_results", "insufficient_relevant_candidates"}
            or not isinstance(decision.get("reason"), str) or not decision["reason"].strip()
            or not isinstance(decision.get("reviewer"), str) or not decision["reviewer"].strip()):
        raise ValueError("DISCOVERY_FOLLOWUP_BINDING_INVALID")
    runs = [r for r in evidence.get("source_runs", []) if isinstance(r, dict) and r.get("run_id") == decision.get("source_run_id")]
    from runtime_v24 import source_files_complete, source_fresh
    if (len(runs) != 1 or runs[0].get("provider") != "serper_patents"
            or runs[0].get("query_id") != primary[0]["query_id"]
            or runs[0].get("plan_entry_sha256") != sha256_json(primary[0])
            or runs[0].get("status") not in {"success", "no_result"}
            or not source_files_complete(task_dir, evidence, runs[0]) or not source_fresh(runs[0], max_age_hours)):
        raise ValueError("DISCOVERY_FOLLOWUP_SOURCE_INVALID")
    if runs[0].get("fixture") or runs[0].get("test_only") or runs[0].get("source_environment") in {"test_fixture", "sandbox", "non_production"}:
        raise ValueError("DISCOVERY_FOLLOWUP_NON_PRODUCTION")
    refs = decision.get("evidence_ids")
    linked = {e.get("evidence_id") for values in evidence.get("collections", {}).values() if isinstance(values, list)
              for e in values if isinstance(e, dict) and e.get("source_run_id") == runs[0]["run_id"]}
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in linked for ref in refs):
        raise ValueError("DISCOVERY_FOLLOWUP_EVIDENCE_INVALID")
    if decision["reason_code"] == "zero_results" and runs[0]["status"] != "no_result":
        raise ValueError("DISCOVERY_FOLLOWUP_NOT_ZERO")
    return decision


def product_identity_digest(product: dict[str, Any], *, task: dict | None = None) -> str:
    """Bind analysis to observed identity/content, never collection timestamps."""
    if task is not None and correction_enabled(task):
        from decision_workflow import observed_product_sha256
        return observed_product_sha256(product)
    identity = {key: product.get(key) for key in (
        "requested_asin", "actual_asin", "title", "brand", "manufacturer",
        "category", "bullets", "media_identity",
    )}
    variant = product.get("variant")
    identity["variant"] = {key: variant.get(key) for key in ("label", "value", "confirmed")} if isinstance(variant, dict) else variant
    specifications = product.get("specifications")
    identity["specifications"] = {key: value for key, value in specifications.items()
        if not re.search(r"review|rating|rank|price|date first available|availability|库存|评价|评分|排名|价格", str(key), re.I)} if isinstance(specifications, dict) else specifications
    return sha256_json(identity)


def product_analysis_readiness(task: dict[str, Any]) -> dict[str, Any]:
    """Separate analysis prerequisites from follow-up work still to be done."""
    import product_scope as ps
    if ps.enabled(task): return ps.readiness(task)
    if task.get("product_scope_required"):
        return {"ready": False, "gaps": [{"code":"PRODUCT_SCOPE_REVIEW_REQUIRED","blocking_planning":True}], "patent_claim_followup":{"required":False}}
    if not recall_integrity_enabled(task):
        return {"ready": True, "gaps": [], "patent_claim_followup": {"required": False}}
    product = task.get("product", {})
    analysis = product.get("analysis") or {}
    gaps = []
    from product_entry import enabled as entry_enabled, assert_frozen
    if entry_enabled(task):
        try:
            assert_frozen(task)
        except ValueError as exc:
            gaps.append({"code": str(exc), "blocking_planning": True})
    structure = product.get("structure")
    if not isinstance(structure, list) or not any(
            str(item.get("description") or "").strip() if isinstance(item, dict)
            else isinstance(item, str) and item.strip() for item in structure):
        gaps.append({"code": "PRODUCT_STRUCTURE_MISSING", "blocking_planning": True})
    if not isinstance(task.get("query_terms"), list) or not task["query_terms"]:
        gaps.append({"code": "QUERY_TERMS_MISSING", "blocking_planning": True})
    if not isinstance(analysis, dict) or analysis.get("status") != "confirmed":
        gaps.append({"code": "PRODUCT_ANALYSIS_UNCONFIRMED", "blocking_planning": True})
    elif analysis.get("identity_sha256") != product_identity_digest(product, task=task):
        gaps.append({"code": "PRODUCT_ANALYSIS_STALE", "blocking_planning": True})
    claims = product.get("visible_ip_claims") or []
    bullets = product.get("bullets") or []
    claim_text = " ".join(str(v) for v in [*(claims if isinstance(claims, list) else [claims]),
                          product.get("title", ""), *(bullets if isinstance(bullets, list) else [bullets])])
    required = bool(re.search(r"\bpatent(?:ed|s|\s+pending)?\b|专利|特許|brevet|patentiert|patentado|brevettato", claim_text, re.I))
    followup = product.get("patent_claim_followup") or {}
    complete = (isinstance(followup, dict) and followup.get("status") == "completed"
                and bool(str(followup.get("findings") or "").strip())
                and isinstance(followup.get("evidence_ids"), list) and bool(followup["evidence_ids"]))
    if required and not complete:
        gaps.append({"code": "PATENT_CLAIM_FOLLOWUP_MISSING", "blocking_planning": False})
    gaps.extend(clue_handoff_gaps(task))
    return {"ready": not any(g["blocking_planning"] for g in gaps), "gaps": gaps,
            "patent_claim_followup": {"required": required, "status": "completed" if complete else "pending" if required else "not_required"}}


def boolean_tokens(value: str, revision: str | None = None) -> list[str]:
    """A bounded Boolean grammar, not an arbitrary provider query language."""
    if revision == "ppubs-boolean-v2":
        # Share the accepted PPS grammar with receipt validation. The resulting
        # token list retains the planner's existing spaced-parenthesis format.
        from record_browser_execution import compile_ppubs_boolean
        value = compile_ppubs_boolean(value, revision)
        return re.findall(r'''"[^"\r\n]+"|\(|\)|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*''', value)
    pattern = r'"[^"\n]+"|\(|\)|[^\W_]+(?:[-\x27][^\W_]+)*\*?'
    matches = list(re.finditer(pattern, value, re.UNICODE))
    cursor = 0
    tokens = []
    for match in matches:
        if value[cursor:match.start()].strip():
            raise ValueError("Unsupported query syntax; supply words, short phrases and Boolean operators")
        tokens.append(match.group())
        cursor = match.end()
    if value[cursor:].strip() or not tokens:
        raise ValueError("Invalid or empty Boolean query")
    if len(re.findall(r"[^\W_]+", value, re.UNICODE)) > 24:
        raise ValueError("Query must be decomposed into bounded feature groups, not marketing paragraphs")
    if not any(t in {"AND", "OR", "NOT", "(", ")"} for t in tokens):
        tokens = [part for i, token in enumerate(tokens) for part in (["AND", token] if i else [token])]
    expect_operand, depth = True, 0
    for token in tokens:
        if token == "(" and expect_operand:
            depth += 1
        elif token == ")" and not expect_operand and depth:
            depth -= 1
        elif token == "NOT" and expect_operand:
            continue
        elif token in {"AND", "OR"} and not expect_operand:
            expect_operand = True
        elif token not in {"AND", "OR", "NOT", "(", ")"} and expect_operand:
            if token.startswith('"') and len(token.split()) > 8:
                raise ValueError("Phrase queries are limited to eight words")
            expect_operand = False
        else:
            raise ValueError("Invalid Boolean query expression")
    if expect_operand or depth:
        raise ValueError("Unbalanced or incomplete Boolean query")
    return tokens


def brand_byline_disposition(task: dict[str, Any]) -> dict[str, Any] | None:
    """An Amazon byline placeholder is not an observed word mark.

    The new completion contract filters bylines; API v3 also accepts the exact
    Generic brand-field value. Keep raw metadata and a reason in the plan; marks with
    the same spelling never inherit this source-specific disposition.
    """
    api_v3 = task.get("retrieval_workflow_revision") == "api-first-v3"
    if not necessary_work_enabled(task) and not api_v3:
        return None
    product = task.get("product") or {}
    if api_v3 and (task.get("request", {}).get("entry_type") == "user_materials"
                   or product.get("brand_role") == "own"):
        return None
    raw = product.get("brand_byline_raw")
    source_path = "product.brand_byline_raw"
    if not isinstance(raw, str) or not raw.strip():
        # Exact Amazon metadata value only; do not match a compound brand,
        # an independently observed mark, or the user's separately supplied name.
        value = product.get("brand")
        if not api_v3 or not isinstance(value, str) or value.strip().casefold() != "generic":
            return None
        raw, source_path = value, "product.brand"
    brand = re.sub(r"^Brand\s*:\s*", "", raw.strip(), flags=re.I)
    brand = re.sub(r"^Visit\s+the\s+(.+?)\s+Store$", r"\1", brand, flags=re.I).strip()
    if brand.casefold() not in {"generic", "unbranded"}:
        return None
    return {"derived_from": "product.brand", "source_path": source_path,
            "raw_value": raw, "value": brand, "disposition": "excluded",
            "code": "AMAZON_BRAND_BYLINE_PLACEHOLDER",
            "reason": "Amazon brand byline identifies a Generic/Unbranded placeholder, not an independently observed mark"}


def brand_name_query_disposition(task: dict[str, Any]) -> dict[str, Any] | None:
    """Presentation-only applicability for the reference Amazon brand name."""
    disposition = brand_byline_disposition(task)
    if (task.get("retrieval_workflow_revision") != "api-first-v3" or not disposition
            or disposition["value"].strip().casefold() != "generic"):
        return None
    return {"status": "not_required", "assessment_object": "reference_brand_name",
            "right_type": "trademark_word", "source_path": disposition["source_path"],
            "display": "无风险（Generic 通用占位，仅名称项）",
            "reason": "Amazon 品牌字段 Generic 是通用占位，不执行该名称的发现或详情查询。",
            "limitation": "仅适用于参考商品品牌名称；未提供的自有品牌未评估，其他知识产权风险按原专项结论。"}


def validated_query_cancellation(task: dict, plan: dict, row: dict) -> dict | None:
    """Return only an explicit, hash-bound cancellation in an integrity plan.

    Malformed dispositions never suppress execution. Keep the original records
    for audit; consumers share this validation instead of interpreting truthiness.
    """
    if not recall_integrity_enabled(task) or not recall_integrity_enabled(plan) or not isinstance(row, dict):
        return None
    dispositions = plan.get("execution_dispositions")
    query_id = row.get("query_id")
    if not isinstance(dispositions, list) or not isinstance(query_id, str) or not query_id:
        return None
    digest = sha256_json(row)
    from decision_workflow import _snapshot_value
    def index_dispositions():
        indexed = {}
        for value in dispositions:
            if isinstance(value, dict):
                indexed.setdefault((value.get("query_id"), value.get("plan_entry_sha256")), []).append(value)
        return indexed
    indexed = _snapshot_value("workflow_cancellations", (plan,), index_dispositions)
    for item in indexed.get((query_id, digest), []):
        if (isinstance(item, dict) and item.get("query_id") == query_id
                and item.get("plan_entry_sha256") == digest and item.get("status") == "cancelled"
                and isinstance(item.get("reason"), str) and item["reason"].strip()):
            from source_operation import enabled as operation_review_enabled
            if operation_review_enabled(task):
                from scope_cancellation import scope_change_required, valid_scope_cancellation
                if scope_change_required(task, row) and not valid_scope_cancellation(task, row, item):
                    continue
            return item
    return None


def validated_query_substitution(task: dict, plan: dict, row: dict, *, scenario_id: str | None = None) -> dict | None:
    """Explicit equivalence is hash/scope/purpose bound and never execution proof."""
    if not scenario_workflow_enabled(task):
        return None
    all_rows = [item for rows in plan.get("queries", {}).values() for item in rows]
    indexed = {item.get("query_id"): item for item in all_rows}
    if len(indexed) != len(all_rows):
        return None
    substitutions = plan.get("action_substitutions", [])
    if not isinstance(substitutions, list):
        return None
    valid = {}
    for item in substitutions:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key].strip() for key in ("reason", "reviewer")):
            continue
        old, new = indexed.get(item.get("old_query_id")), indexed.get(item.get("new_query_id"))
        if not old or not new or old["query_id"] == new["query_id"]:
            continue
        if item.get("old_plan_entry_sha256") != sha256_json(old) or item.get("new_plan_entry_sha256") != sha256_json(new):
            continue
        if any(item.get(key) != old.get(key) or old.get(key) != new.get(key) for key in ("jurisdiction", "right_type", "action_purpose")):
            continue
        scope = {"scenario_id": item.get("scenario_id"), "scenario_sha256": item.get("scenario_sha256")}
        if scope not in scenario_row_bindings(task, old) or scope not in scenario_row_bindings(task, new):
            continue
        if (old.get("triage_candidate_id") or old.get("candidate_id")) != (new.get("triage_candidate_id") or new.get("candidate_id")):
            continue
        key = (old["query_id"], scope["scenario_id"])
        if key in valid:
            valid[key] = None  # Ambiguous alternatives must be clarified.
        else:
            valid[key] = item
    selected = [item for (identity, sid), item in valid.items() if identity == row.get("query_id") and item
                and (scenario_id is None or sid == scenario_id)]
    for item in selected:
        seen, current = {item["old_query_id"]}, item
        while current:
            target = current["new_query_id"]
            if target in seen:
                return None
            seen.add(target)
            current = valid.get((target, item["scenario_id"]))
    return selected[0] if selected else None


def planned_execution_gaps(task: dict, plan: dict, evidence: dict, *, candidates: dict | None = None,
                           ledger: dict | None = None, supplement: dict | None = None, evidence_root=None) -> list[dict]:
    """Audit required work separately from file integrity or empty candidates.

    Failures may be substituted only by a complete, bound same-axis query from
    another provider with the same provenance. Optional discovery never blocks.
    Explicit cancellations live outside immutable query rows.
    """
    if scenario_workflow_enabled(task):
        return scenario_execution_gaps(task, plan, evidence, candidates=candidates, ledger=ledger, supplement=supplement, evidence_root=evidence_root)
    if not recall_integrity_enabled(task):
        return []
    rows = [r for group in plan.get("queries", {}).values() for r in group
            if r.get("execute_by_default") is True and r.get("required_for") != "discovery_only"]
    providers = {row["query_id"]: provider for provider, group in plan.get("queries", {}).items() for row in group}
    term_ids = {item["query_id"]: item["term_id"] for item in plan.get("expansion_queue", [])
                if item.get("query_id") and item.get("term_id")}
    bound = {}
    for row in rows:
        matches = [run for run in evidence.get("source_runs", [])
                   if run.get("provider") == providers[row["query_id"]] and run.get("query_id") == row.get("query_id")
                   and run.get("plan_entry_sha256") == sha256_json(row)]
        if matches:
            bound[row["query_id"]] = matches[-1]

    def pagination_complete(row: dict, total: Any) -> bool:
        provider = providers[row["query_id"]]
        if provider not in {"epo_ops", "euipo_trademark", "euipo_design", "inpi_api"} or not isinstance(total, int) or isinstance(total, bool) or total <= 0:
            return False
        intervals = []
        for other in rows:
            if (providers[other["query_id"]], other.get("q"), other.get("jurisdiction"), other.get("right_type"), other.get("requirement_ids")) != (
                    provider, row.get("q"), row.get("jurisdiction"), row.get("right_type"), row.get("requirement_ids")):
                continue
            run = bound.get(other["query_id"], {})
            meta = run.get("metadata", {}).get("search_coverage", {})
            count = meta.get("retrieved_hits")
            if run.get("status") != "success" or meta.get("schema_valid") is not True or meta.get("total_hits") != total or not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                continue
            try:
                offset = int(str(other["range"]).split("-")[0]) - 1 if provider == "epo_ops" else int(other.get("position", 0)) if provider == "inpi_api" else int(other.get("page", 0)) * int(other.get("size", 25))
            except (KeyError, TypeError, ValueError):
                continue
            intervals.append((offset, offset + count))
        reached = 0
        for start, end in sorted(intervals):
            if start > reached:
                return False
            reached = max(reached, end)
        return reached >= total

    def complete(row: dict) -> bool:
        run = bound.get(row["query_id"], {})
        if run.get("status") not in {"success", "no_result"}:
            return False
        if row.get("operation") in {"candidate_verification", "candidate_detail", "document_retrieval"}:
            return True
        coverage = run.get("metadata", {}).get("search_coverage", {})
        return coverage.get("schema_valid") is True and (coverage.get("truncated") is False
                or pagination_complete(row, coverage.get("total_hits")))

    gaps = []
    for row in rows:
        if validated_query_cancellation(task, plan, row):
            continue
        if complete(row):
            continue
        run = bound.get(row["query_id"], {})
        # Not-yet-executed expansion is work, not an alternative-source failure.
        if run and any(providers[other["query_id"]] != providers[row["query_id"]]
                       and other.get("right_type") == row.get("right_type")
                       and other.get("jurisdiction") == row.get("jurisdiction")
                       and other.get("search_dimension") == row.get("search_dimension")
                       and other.get("execution_phase") == row.get("execution_phase")
                       and other.get("derived_from") == row.get("derived_from")
                       and ((term_ids.get(row["query_id"]) and term_ids.get(other["query_id"]) == term_ids[row["query_id"]])
                            or other.get("q") == row.get("q"))
                       and bool(set(other.get("requirement_ids", [])) & set(row.get("requirement_ids", [])))
                       and complete(other) for other in rows):
            continue
        coverage = run.get("metadata", {}).get("search_coverage", {})
        status = run.get("status", "not_executed")
        code = ("PLANNED_QUERY_NOT_EXECUTED" if not run else
                "SEARCH_RESULT_TRUNCATED" if coverage.get("truncated") is True else
                "SEARCH_RESULT_COVERAGE_UNKNOWN" if status in {"success", "no_result"} else
                "PLANNED_QUERY_" + str(status).upper())
        gaps.append({"code": code, "query_id": row["query_id"], "provider": providers[row["query_id"]],
                     "jurisdiction": row.get("jurisdiction"), "right_type": row.get("right_type"),
                     "requirement_ids": row.get("requirement_ids", []), "dimension": row.get("search_dimension"),
                     "status": status, "error_code": run.get("error_code", ""), "assigned_to": "agent"})
    return gaps


def scenario_execution_gaps(task: dict, plan: dict, evidence: dict, *, candidates: dict | None = None,
                             ledger: dict | None = None, supplement: dict | None = None, evidence_root=None,
                             coverage: list[dict] | None = None) -> list[dict]:
    if not scenario_workflow_enabled(task):
        return planned_execution_gaps(task, plan, evidence)
    if candidates is None or ledger is None:
        return [{"code": "TRIAGE_CONTEXT_REQUIRED", "assigned_to": "agent"}]
    from assessment_v24 import scenario_coverage_by_scope
    gaps = []
    scopes = coverage if coverage is not None else scenario_coverage_by_scope(task, evidence, candidates, plan, ledger=ledger, supplement=supplement, evidence_root=evidence_root)
    for scope in scopes:
        for gap in scope["gaps"]:
            gaps.append({"code": gap, "scenario_id": scope["scenario_id"], "scenario_sha256": scope["scenario_sha256"],
                         "jurisdiction": scope["jurisdiction"], "right_type": scope["right_type"], "assigned_to": "agent"})
    for issue in candidates.get("official_export_issues", []):
        if not isinstance(issue, dict):
            continue
        for scope in scopes:
            if (scope.get("jurisdiction") == issue.get("jurisdiction")
                    and scope.get("right_type") in issue.get("affected_right_types", [])):
                gaps.append({"code": "OFFICIAL_EXPORT_UNREADABLE", "scenario_id": scope["scenario_id"],
                    "scenario_sha256": scope["scenario_sha256"], "jurisdiction": scope["jurisdiction"],
                    "right_type": scope["right_type"], "evidence_id": issue.get("evidence_id"),
                    "assigned_to": "agent"})
    return gaps


def _text_language(value: str, declared: object = "") -> str:
    """Keep a claimed locale from silently relabelling incompatible CJK text."""
    language = str(declared or "").strip().casefold()
    if re.search(r"[\u3040-\u30ff]", value):
        return "ja" if language not in {"ja", "zh"} else language
    if re.search(r"[\u3400-\u9fff]", value):
        # Han characters alone cannot distinguish Chinese from Japanese, but
        # they are never valid evidence of an English/French/etc. query term.
        return language if language in {"ja", "zh"} else "zh"
    return language


def build_coverage_requirements_v24(jurisdictions: list[str], *, screening_revision: str | None = None,
                                  specialty_workflow_revision: str | None = None) -> list[dict[str, Any]]:
    """Capabilities are alternatives; distinct search axes and territories are not."""
    result = []
    targets = list(dict.fromkeys(str(j).upper() for j in jurisdictions))
    for source_requirement in build_coverage_requirements(targets):
        # The frozen builder intentionally shares route dicts across rights.
        # Copy each requirement independently before changing one right's route.
        requirement = deepcopy(source_requirement)
        right = requirement["right_type"]
        if right in {"copyright", "enforcement"}:
            continue  # Policy homepages are not copyright/litigation search databases.
        jurisdiction = requirement["jurisdiction"]
        routes = requirement["routes"]
        # Aggregator + national register are not both mandatory network calls.
        routes[:] = [r for r in routes if r["provider"] not in {"tmview_browser", "designview_browser", "prv_open_data"}]
        if not routes:
            continue  # Removed aggregator-only discovery is not a legal obligation.
        for route in routes:
            if screening_revision == RECALL_INTEGRITY_REVISION and jurisdiction == "US" and right == "design" and route["provider"] == "uspto_patent_browser" and route["operation"] == "patent_recall":
                route["operation"] = "design_recall"
            if route["method"].startswith("cdp"):
                route["method"] = "cdp_agent"
            route["required"] = False
        requirement["completion_policy"] = "any"
        requirement["required_axes"] = AXES.get(right, []) if requirement["phase"] == "official_recall" else []
        if specialty_workflow_revision == "asset-scope-v1" and jurisdiction == "US" and right == "trademark_figurative" and requirement["phase"] == "official_recall":
            requirement["required_axes"] = ["classification", "description", "visual_comparison"]
            routes.append({"provider": "asset_provenance", "operation": "provenance_review", "method": "agent", "priority": 2, "required": False})
        requirement["required_language"] = LANGUAGES.get(jurisdiction, "")
        requirement["expansion_required"] = requirement["phase"] == "official_recall" and right in {"patent", "utility_model", "design"}
        if jurisdiction in {"GB", "FR", "DE", "IT", "ES"} and right in {"patent", "utility_model"} and requirement["phase"] == "official_recall":
            if not any(r["provider"] == "epo_ops" and r["operation"] == "search" for r in routes):
                routes.append({"provider": "epo_ops", "operation": "search", "method": "api", "priority": 2, "required": False})
            requirement["publication_scope"] = [jurisdiction, "EP", "WO"] if right == "patent" else [jurisdiction]
        if jurisdiction == "ES":
            routes.insert(0, {"provider": "oepm_api", "operation": "search" if requirement["phase"] == "official_recall" else "candidate_verification", "method": "api", "priority": 1, "required": False})
        result.append(requirement)
    for jurisdiction in targets:
        rights = ["copyright", "trade_dress"]
        if jurisdiction in {"EU", "GB"}:
            rights.append("unregistered_design")
        for right in rights:
            result.append({
                "requirement_id": f"COV-{jurisdiction}-{right.upper()}-PROVENANCE",
                "jurisdiction": jurisdiction, "right_type": right, "phase": "provenance",
                "required_for": "low_risk", "completion_policy": "any",
                "required_axes": ((["public_use", "source_identification", "functionality"] if right == "trade_dress" else ["provenance", "visual_comparison"])
                                  if specialty_workflow_revision == "asset-scope-v1" else ["provenance", "image"]), "required_language": "",
                "expansion_required": False,
                "routes": [{"provider": "asset_provenance", "operation": "provenance_review", "method": "agent", "priority": 1, "required": False}],
            })
    return result


def term_records(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Use actual features first and retain only their evidenced language."""
    product = task.get("product", {})
    import product_scope as ps
    scoped = ps.enabled(task)
    strict = recall_integrity_enabled(task)
    byline_placeholder = brand_byline_disposition(task)
    terms: list[dict[str, Any]] = []
    def add(value: Any, kind: str, source: str, language: str = "", **extra: Any) -> None:
        text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()
        if not text:
            return
        actual_language = _text_language(text, language)
        from product_delivery import fact_for_path
        fact = fact_for_path(task, source)
        if fact:
            extra = {**extra, "fact_id": fact["fact_id"], "fact_version": fact["version"],
                     "fact_nature": fact["nature"], "fact_verification": fact["verification"]}
        row = {"value": text, "kind": kind, "derived_from": source, "language": actual_language, **extra}
        if not any((r["value"], r["kind"], r.get("language")) == (text, kind, actual_language) and (not scoped or r["derived_from"] == source) for r in terms):
            terms.append(row)
    language = product.get("language") or LANGUAGES.get(task.get("request", {}).get("marketplace", ""), "")
    for i, feature in enumerate(product.get("structure", []) if not strict else []):
        if isinstance(feature, dict):
            add(feature.get("description"), "structural_feature", f"product.structure[{i}]", feature.get("language", language))
        else:
            add(feature, "structural_feature", f"product.structure[{i}]", language)
    if scoped:
        for i, obj in enumerate(ps.scope(task)['objects']):
            if obj['kind'] in {'brand','logo'} and obj.get('text'):
                add(obj['text'], 'brand', f'product.scope_objects[{i}]', obj.get('language','en'), strategy='phrase')
    for key in (() if scoped else (("brand",) if strict else ("category", "title", "brand", "manufacturer"))):
        if key == "brand" and byline_placeholder:
            continue
        add(product.get(key), {"title": "product", "manufacturer": "owner"}.get(key, key), f"product.{key}", language,
            **({"strategy": "phrase"} if strict else {}))
    if identity_discovery_enabled(task):
        # A manufacturer is an identity clue, not a patent assignee assertion.
        add(product.get("manufacturer"), "manufacturer", "product.manufacturer", language, strategy="phrase")
    for i, feature in enumerate(product.get("bullets", []) if not strict else []):
        add(feature, "function", f"product.bullets[{i}]", language)
    allowed = {"structural_feature", "synonym", "translation", "original_japanese", "english", "romaji", "reading", "pronunciation", "phonetic", "owner", "applicant", "inventor", "ipc", "cpc", "uspc", "locarno", "nice", "similar_group", "figurative_classification", "jpo_figurative_classification", "design", "brand", "ocr", "product", "category", "function"}
    if identity_discovery_enabled(task):
        allowed.add("manufacturer")
    if task.get("specialty_workflow_revision") == "asset-scope-v1":
        allowed.update({"design_code", "mark_description"})
    supplied = task.get("query_terms", [])
    if not isinstance(supplied, list):
        raise ValueError("query_terms must be an array")
    for i, item in enumerate(supplied):
        if not isinstance(item, dict) or item.get("kind") not in allowed or not str(item.get("derived_from") or "").strip() or not str(item.get("value") or "").strip():
            raise ValueError(f"query_terms[{i}] requires a supported kind, value and derived_from")
        lang = str(item.get("language") or ("ja" if item["kind"] in {"original_japanese", "reading"} else "en" if item["kind"] == "english" else ""))
        if item["kind"] in {"translation", "synonym", "phonetic"} and not lang:
            raise ValueError(f"query_terms[{i}] must identify its language")
        kind, value = item["kind"], item["value"]
        if (byline_placeholder and kind == "brand" and item["derived_from"] in
                {"product.brand", "product.brand_byline_raw", "product.raw_capture.brand"}
                and str(value).strip().casefold() in {byline_placeholder["value"].casefold(),
                    byline_placeholder["raw_value"].strip().casefold()}):
            # An explicit image/OCR/mark-inventory observation remains eligible,
            # even when the observed word itself is GENERIC or UNBRANDED.
            continue
        if kind in {"design_code", "mark_description"}:
            match = re.fullmatch(r"product\.mark_inventory\[(\d+)\]", str(item["derived_from"]))
            inventory = product.get("mark_inventory", [])
            if scoped:
                match = re.fullmatch(r"product\.scope_objects\[(\d+)\]", str(item["derived_from"]))
                inventory = [{'form':'graphic' if o['kind']=='logo' else 'text','evidence_refs':o['source_refs'],
                              'graphic_description':o['description']} for o in ps.scope(task)['objects']]
            mark = inventory[int(match[1])] if match and int(match[1]) < len(inventory) else {}
            if (mark.get("form") not in {"stylized_text", "graphic", "composite"}
                    or not mark.get("evidence_refs") or not mark.get("graphic_description")):
                raise ValueError("FIGURATIVE_TERM_REQUIRES_OBSERVED_MARK")
            if kind == "design_code" and not re.fullmatch(r"(?:\d{6}|\d{2}\.\d{2}\.\d{2})", str(value)):
                raise ValueError("FIGURATIVE_DESIGN_CODE_INVALID")
        if kind in {"ipc", "cpc"} and not re.fullmatch(r"[A-HY]\d{2}[A-Z](?:\d{1,4}/\d{1,8})?", str(value).replace(" ", "")):
            raise ValueError(f"query_terms[{i}] has an invalid IPC/CPC code")
        if kind == "locarno" and not re.fullmatch(r"\d{2}-\d{2}", str(value)):
            raise ValueError(f"query_terms[{i}] has an invalid Locarno code")
        extra = {"scheme": item["scheme"]} if item.get("scheme") else {}
        from discovery_budget import enabled as purpose_budget_enabled
        if purpose_budget_enabled(task):
            problem = item.get("discovery_problem_id")
            if problem is not None or any(key in item for key in
                                          ("discovery_problem_reason", "different_from_purpose_id")):
                if (not isinstance(problem, str) or not problem.strip()
                        or any(not isinstance(item.get(key), str) or not item[key].strip()
                               for key in ("discovery_problem_reason", "different_from_purpose_id"))):
                    raise ValueError("DISCOVERY_NEW_PURPOSE_REASON_REQUIRED")
                extra.update({key:item[key] for key in
                    ("discovery_problem_id", "discovery_problem_reason", "different_from_purpose_id")})
        if strict:
            if not re.match(r"^(?:product\.|images\[|candidate:|evidence:|EV-)", str(item["derived_from"])):
                raise ValueError(f"query_terms[{i}] must reference product, image, candidate or evidence provenance")
            strategy = item.get("strategy", "phrase" if kind in {"owner", "applicant", "brand", "ocr", "manufacturer"} else "boolean")
            if strategy not in {"boolean", "phrase", "record_number"}:
                raise ValueError(f"query_terms[{i}] has an unsupported strategy")
            if strategy == "record_number":
                raise ValueError("Known-number verification belongs to candidate actions, not recall query_terms")
            if _dimension({"kind": kind}) not in {"classification", "owner"} and not lang:
                raise ValueError(f"query_terms[{i}] must identify its target language")
            if _dimension({"kind": kind}) != "classification":
                if strategy == "phrase" and (len(str(value).split()) > 8 or re.search(r'["\n\r]', str(value))):
                    raise ValueError(f"query_terms[{i}] phrase must be a short unquoted phrase")
                if strategy == "boolean":
                    if necessary_work_enabled(task):
                        # Normalize only supported operators outside quoted
                        # phrases. Source query_terms remain unchanged.
                        value = re.sub(r'"[^"\n]+"|\b(?:AND|OR|NOT)\b',
                            lambda match: match.group() if match.group().startswith('"') else match.group().upper(),
                            str(value), flags=re.I)
                    boolean_tokens(str(value))
            extra["strategy"] = strategy
        add(value, kind, item["derived_from"], lang, **extra)
    return terms


def _dimension(term: dict[str, Any]) -> str:
    kind = term["kind"]
    if kind in {"ipc", "cpc", "uspc", "locarno", "nice", "similar_group", "figurative_classification", "jpo_figurative_classification", "design_code"}:
        return "classification"
    if kind == "mark_description":
        return "description"
    if kind in {"reading", "pronunciation", "phonetic"}:
        return "phonetic"
    return "owner" if kind in {"owner", "applicant", "inventor"} else "text"


def _applicable(term: dict[str, Any], right: str, *, task: dict | None = None) -> bool:
    import product_scope as ps
    if ps.enabled(task or {}) and not ps.term_allowed(task,term,right): return False
    kind = term["kind"]
    # A USPC D-class describes designs, not utility-patent subject matter.
    # Keep the old planner contract unchanged for unmarked historical tasks.
    if (correction_enabled(task or {}) and kind == "uspc"
            and re.fullmatch(r"D\d+\s*/\s*\d+(?:\.\d+)?", str(term.get("value") or "").strip(), re.I)
            and right in {"patent", "utility_model"}):
        return False
    if right in {"patent", "utility_model"}:
        return kind in {"structural_feature", "category", "product", "function", "translation", "synonym", "english", "original_japanese", "ipc", "cpc", "uspc", "owner", "applicant", "inventor"}
    if right == "design":
        return kind in {"design", "category", "product", "translation", "synonym", "english", "original_japanese", "locarno", "uspc", "owner", "applicant", "inventor"}
    if right.startswith("trademark"):
        if kind in {"design_code", "mark_description"}:
            return right == "trademark_figurative"
        return kind in {"brand", "ocr", "reading", "pronunciation", "phonetic", "translation", "nice", "similar_group", "figurative_classification", "jpo_figurative_classification"}
    return False


def _target_language_compatible(term: dict[str, Any], jurisdiction: str) -> bool:
    """A text search cannot claim local-language coverage with another script."""
    if _dimension(term) in {"classification", "owner"}:
        # Identifiers and legal entity names are not translated by this
        # language gate; their provenance is checked separately.
        return True
    required = LANGUAGES.get(jurisdiction, "")
    if not required:
        return True
    return str(term.get("language") or "").casefold() == required


def _scope(jurisdiction: str, right: str) -> list[str]:
    if jurisdiction == "EU":
        return ["EP", "WO"]
    if jurisdiction in {"GB", "FR", "DE", "IT", "ES"} and right == "patent":
        return [jurisdiction, "EP", "WO"]
    return [jurisdiction] + (["WO"] if right == "patent" else [])


def _api_params(provider: str, term: dict[str, Any], jurisdiction: str, right: str, *,
                query_compiler_revision: str | None = None) -> dict[str, Any] | None:
    value = term["value"]
    escaped = value.replace('"', ' ').replace('\\', ' ')
    dim = _dimension(term)
    if provider == "epo_ops":
        if term["kind"] == "locarno":
            return None  # OPS does not expose a Locarno field; do not fake it as text.
        if term["kind"] not in {"ipc", "cpc"} and dim == "classification":
            return None
        field = term["kind"] if term["kind"] in {"ipc", "cpc"} else "in" if term["kind"] == "inventor" else "pa" if dim == "owner" else "ta"
        if query_compiler_revision == "ops-cql-v1":
            from epo_query import compile_ops_query
            return {"q": compile_ops_query(countries=_scope(jurisdiction, right), field=field,
                value=value, strategy=term.get("strategy", "boolean")), "range": "1-25"}
        prefix = " or ".join(f"pn={country}*" for country in _scope(jurisdiction, right))
        if term.get("strategy") == "boolean" and (dim == "text" or term["kind"] == "inventor"):
            expression = " ".join(token.lower() if token in {"AND", "OR", "NOT"} else token if token in {"(", ")"} else f'{field}="{token.strip(chr(34))}"' for token in boolean_tokens(value))
            return {"q": f"({prefix}) and ({expression})", "range": "1-25"}
        return {"q": f'({prefix}) and {field}="{escaped}"', "range": "1-25"}
    if provider in {"euipo_trademark", "euipo_design"}:
        from euipo_client import search_rsql
        locarno = provider == "euipo_design" and term["kind"] == "locarno"
        if (dim != "text" and not locarno) or right == "trademark_figurative":
            return None
        if term.get("strategy") == "boolean" and any(token in {"AND", "OR", "NOT", "(", ")"} for token in value.split()):
            return None  # Boolean groups need an accepted RSQL compiler, not literal text.
        product = "trademark" if provider == "euipo_trademark" else "design"
        if locarno:
            value = value.replace("-", ".")
        return {"q": value, "query": search_rsql(product, value, right), "page": 0, "size": 25}
    if provider == "inpi_api":
        # Only documented full-text syntax is generated here. Structured fields
        # can be expanded once the authenticated schema is accepted.
        if dim != "text":
            return None
        if term.get("strategy") == "boolean" and re.search(r"\b(?:AND|OR|NOT)\b", value):
            return None  # Do not put English Boolean operators in French syntax.
        if any(c in escaped for c in "[]=()"):
            return None
        field = "(TIT OU ABFR)" if right in {"patent", "utility_model"} else "Mark_Exp" if right.startswith("trademark") else "DesignTitle"
        query = f"[{field}=({escaped})]" if right in {"patent", "utility_model"} else f"[{field}={escaped}]"
        return {"q": query, "collections": ["FR"], "position": 0, "size": 25}
    if provider == "oepm_api":
        return None  # Explicitly unvalidated; never generate a guessed API query.
    if provider.endswith("browser") or provider == "uspto_tsdr":
        if provider == "uspto_tmsearch_browser" and right == "trademark_figurative" and term["kind"] == "design_code":
            return {"q": value, "filters": {"field": "design_code"}, "strategy": "classification"}
        if provider == "uspto_patent_browser" and term.get("strategy") and term["kind"] == "locarno":
            return None
        if provider == "uspto_patent_browser" and term.get("strategy"):
            from record_browser_execution import compile_ppubs_query
            try:
                compile_ppubs_query({"q": value, "strategy": term["strategy"], "right_type": right,
                                     **({"query_compiler_revision": query_compiler_revision} if query_compiler_revision else {})}, term["kind"])
            except ValueError:
                return None  # Unsupported syntax stays a planning gap, never a live zero.
        query = " ".join(boolean_tokens(value, query_compiler_revision)) if term.get("strategy") == "boolean" and dim == "text" else value
        return {"q": query, "filters": {"field": term["kind"], "language": term.get("language", "")},
                **({"strategy": term["strategy"]} if term.get("strategy") else {}),
                **({"query_compiler_revision": query_compiler_revision} if query_compiler_revision else {})}
    return None


def _add(queries: dict[str, list[dict[str, Any]]], provider: str, row: dict[str, Any]) -> None:
    rows = queries.setdefault(provider, [])
    found = next((r for r in rows if r["query_id"] == row["query_id"]), None)
    if found:
        return  # Append-only: executed rows and their evidence hashes never change.
    else:
        rows.append(row)


def append_identity_discovery(task: dict, terms: list[dict], queries: dict,
                              gaps: list[dict], phase: str) -> None:
    """Reserve existing discovery slots for features AND attributed identities."""
    from generate_search_plan import entry, serper_discovery_entry, serpapi_discovery_entry
    intents = {"en": ("patent", "lawsuit OR infringement"),
               "fr": ("brevet", "litige OR contrefaçon"),
               "de": ("Patent", "Klage OR Patentverletzung"),
               "it": ("brevetto", "causa OR contraffazione"),
               "es": ("patente", "demanda OR infracción"),
               "ja": ("特許", "訴訟 OR 侵害")}
    identities = []
    for term in terms:
        if term["kind"] not in {"brand", "ocr", "manufacturer", "owner", "applicant", "inventor"}:
            continue
        value = str(term["value"]).strip()
        if normalize_text(value) in {"", "unknown", "none", "n a", "未知", "未提供"}:
            continue
        if len(value.split()) > 8 or re.search(r'["\n\r]', value):
            gaps.append({"code": "IDENTITY_DISCOVERY_TERM_UNUSABLE", "derived_from": term["derived_from"], "blocking_planning": False})
            continue
        if not any(t["value"] == value for t in identities):
            identities.append(term)
    if len(identities) > 8:
        gaps.append({"code": "IDENTITY_DISCOVERY_GROUP_TRUNCATED", "deferred_sources": [t["derived_from"] for t in identities[8:]], "blocking_planning": False})
    identities = identities[:8]
    features = [t for t in terms if t["kind"] in {"structural_feature", "category", "product", "function", "translation", "synonym", "english", "original_japanese"}]
    from product_delivery import selected_public_image, query_row_binding
    selected_image = selected_public_image(task)
    images = [selected_image] if selected_image else []

    def append(provider: str, row: dict, maximum: int) -> None:
        row.update(search_dimension="text", execution_phase=phase)
        if any(old["query_id"] == row["query_id"] for old in queries.get(provider, [])):
            return
        count = sum(len(rows) for p, rows in queries.items() if p.startswith("serpapi_")) if provider.startswith("serpapi_") else len(queries.get(provider, []))
        if count >= maximum:
            gaps.append({"code": "DISCOVERY_QUERY_DEFERRED_BY_CAP", "provider": provider,
                         "query_id": row["query_id"], "derived_from": row["derived_from"], "blocking_planning": False})
            return
        _add(queries, provider, row)

    for jurisdiction in task["target_jurisdictions"]:
        language = LANGUAGES[jurisdiction]
        local_identities = [t for t in identities if language == "ja" or not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", t["value"])]
        for term in identities:
            if term not in local_identities:
                gaps.append({"code": "IDENTITY_TARGET_SCRIPT_MISSING", "jurisdiction": jurisdiction,
                             "derived_from": term["derived_from"], "blocking_planning": False})
        identity_q = "(" + " OR ".join(
            "(" + " ".join(boolean_tokens(t["value"])) + ")" if t.get("strategy") == "boolean"
            else '"' + t["value"] + '"' for t in local_identities
        ) + ")" if local_identities else ""
        identity_sources = [t["derived_from"] for t in local_identities]
        local_features = [t for t in features if _target_language_compatible(t, jurisdiction)]
        seeds = [(t["value"], [t["derived_from"]]) for t in local_features[:1]]
        if local_identities:
            seeds.append((identity_q, identity_sources))
        seeds.extend((t["value"], [t["derived_from"]]) for t in local_features[1:])
        if serper_free_enabled(task):
            for value, refs in seeds:
                row = serper_discovery_entry("serper_patents", "patents", jurisdiction, value, refs, "patent")
                row["search_language"] = language
                append("serper_patents", row, 4)
            web_seeds = [(f"{identity_q} {intents[language][0]}", identity_sources),
                         (f"{identity_q} ({intents[language][1]})", identity_sources)] if local_identities else []
            for value, refs in web_seeds:
                row = serper_discovery_entry("serper_web", "search", jurisdiction, value, refs, "enforcement")
                row["search_language"] = language
                append("serper_web", row, 3)
            for term in local_features[:3]:
                row = serper_discovery_entry("serper_images", "images", jurisdiction, term["value"], [term["derived_from"]], "copyright")
                row["search_language"] = language
                append("serper_images", row, 3)
        if serpapi_free_enabled(task):
            maximum = task["serpapi_free_enhancement"]["max_queries_per_task"]
            patent_slots = maximum - (1 if images and not queries.get("serpapi_google_lens") else 0)
            for value, refs in seeds:
                matching = next((r for r in queries.get("serper_patents", []) if r["q"] == value and r["jurisdiction"] == jurisdiction), None)
                row = serpapi_discovery_entry(jurisdiction, value, refs, "patent", fallback_query_id=matching["query_id"] if matching else "")
                row["search_language"] = language
                append("serpapi_google_patents", row, patent_slots)
    if serpapi_free_enabled(task) and images and not queries.get("serpapi_google_lens"):
        row = entry("serpapi_google_lens", "image_search", task["request"]["marketplace"],
                    {"q": images[0]["source_url"], "image_url": images[0]["source_url"], "type": "all", "hl": "en", "country": "us"},
                    required=False, right_type="copyright", requirement_ids=[], derived_from=[f"images[{task['images'].index(images[0])}].source_url"], wave=2)
        row.update(query_row_binding(task, images[0]))
        row.update(role="discovery_only", required_for="discovery_only", execute_by_default=True,
                   authoritative_for_final_rating=False, search_language="")
        append("serpapi_google_lens", row, task["serpapi_free_enhancement"]["max_queries_per_task"])
        if row in queries.get("serpapi_google_lens", []):
            row["search_dimension"] = "image"


def generate_plan(task_dir: Path, *, expand: bool = False) -> dict[str, Any]:
    from generate_search_plan import entry, serper_discovery_entry, serpapi_discovery_entry, signa_discovery_entry
    from common import assert_active_free_policy, assert_default_discovery_plan_contract
    task = load_json(task_dir / "task.json")
    from product_entry import enabled as entry_enabled, evidence_errors
    if entry_enabled(task):
        errors = evidence_errors(task, load_json(task_dir / "evidence.json"), task_dir)
        if errors:
            raise ValueError("PRODUCT_EVIDENCE_INVALID: " + "; ".join(errors))
    import product_scope as ps
    ps.verify(task,load_json(task_dir / "evidence.json"),task_dir)
    assert_recall_planning_contract(task)
    if recall_integrity_enabled(task):
        for requirement in task.get("coverage_requirements", []):
            if requirement.get("phase") != "official_recall":
                continue
            for route in requirement.get("routes", []):
                if (route.get("provider") == "uspto_patent_browser"
                        and route.get("operation") != {"patent": "patent_recall", "design": "design_recall"}.get(requirement.get("right_type"))):
                    raise ValueError(f"INTERNAL_ROUTE_CONTRACT_ERROR: {requirement.get('right_type')} cannot use {route.get('operation')}")
    assert_active_free_policy(task)
    if not is_v24(task):
        raise ValueError("The automation planner requires a 2.4-free task")
    if task.get("state") not in {"collecting", "ready_for_assessment", "incomplete", "assessing", "needs_review"}:
        raise ValueError("Accepted product evidence is required before search planning")
    path = task_dir / "search-plan.json"
    previous = load_json(path) if path.exists() else None
    if previous and (previous.get("task_id") != task["task_id"] or previous.get("schema_version") != CURRENT_SCHEMA_VERSION):
        raise ValueError("Existing plan identity mismatch")
    if previous:
        assert_recall_planning_contract(task, previous)
    readiness = product_analysis_readiness(task)
    if not readiness["ready"]:
        raise ValueError("PRODUCT_ANALYSIS_NOT_READY: " + ", ".join(g["code"] for g in readiness["gaps"] if g["blocking_planning"]))
    if previous and not expand:
        if scenario_workflow_enabled(task):
            reconcile_scenario_actions(task_dir, task, previous)
            atomic_write_json(path, previous)
        return previous  # Revalidate input; never silently rehash executed entries.
    terms = term_records(task)
    if scenario_workflow_enabled(task):
        terms = [term for term in terms if not str(term.get("derived_from") or "").startswith("candidate:")]
    queries = deepcopy(previous.get("queries", {})) if previous else {}
    phase = "expansion" if expand else "initial"
    if expand:
        candidates = load_json(task_dir / "normalized-candidates.json") if (task_dir / "normalized-candidates.json").exists() else {}
        if scenario_workflow_enabled(task):
            from decision_workflow import effective_selected_candidates, scenario_index, necessary_scenario_right_types
            _, ledger, evidence = _scenario_context(task_dir, task)
            selected = effective_selected_candidates(task, candidates, ledger, evidence=evidence,
                supplement=scenario_supplement(task_dir, task=task, evidence=evidence))
            scenarios = scenario_index(task)
            selected = [decision for decision in selected if decision["right_type"] in
                        necessary_scenario_right_types(task, scenarios[decision["scenario_id"]])]
        for collection in ("patents", "trademarks"):
            for candidate in candidates.get(collection, []):
                decisions = [value for value in selected if value.get("candidate_id") == candidate.get("candidate_id")] if scenario_workflow_enabled(task) else [None]
                if not decisions or (not scenario_workflow_enabled(task) and candidate.get("material") is not True):
                    continue
                for field, kind in (("owner", "owner"), ("owners", "owner"), ("applicant", "applicant"), ("applicants", "applicant"), ("inventor", "inventor"), ("inventors", "inventor"), ("ipc", "ipc"), ("cpc", "cpc"), ("ipc_classes", "ipc"), ("cpc_classes", "cpc"), ("locarno", "locarno"), ("uspc", "uspc")):
                    values = candidate.get(field, [])
                    for value in values if isinstance(values, list) else [values]:
                        if isinstance(value, str) and value.strip():
                            if kind in {"ipc", "cpc"}:
                                match = re.match(r"^\s*([A-HY]\d{2}[A-Z])\s*(\d{1,4})\s*/\s*(\d{1,8})(?:\s|\(|$)", value)
                                if match:
                                    value = f"{match[1]}{match[2]}/{match[3]}"
                                elif not re.fullmatch(r"[A-HY]\d{2}[A-Z]", value.strip()):
                                    continue
                            for decision in decisions:
                                terms.append({"value": value.strip(), "kind": kind, "language": "", "derived_from": f"candidate:{candidate['candidate_id']}:{field}",
                                              **({"_triage_decision": decision} if decision else {}),
                                              **({"strategy": "boolean" if kind in {"ipc", "cpc", "uspc", "locarno", "inventor"} else "phrase"} if recall_integrity_enabled(task) else {})})
    # Discovery is not scheduling: retain unplanned terms for later bounded waves.
    selected_terms = list({sha256_json(t): t for t in terms}.values())
    planning_gaps, expansion_queue = deepcopy(readiness["gaps"]), []
    for requirement in task["coverage_requirements"]:
        if requirement["phase"] != "official_recall":
            continue
        if api_first_enabled(task):
            continue  # Discovery is planned below; do not create broad CDP work.
        jurisdiction, right = requirement["jurisdiction"], requirement["right_type"]
        eligible = [
            t for t in selected_terms
            if _applicable(t, right, task=task) and _target_language_compatible(t, jurisdiction)
            and not (task.get("specialty_workflow_revision") == "asset-scope-v1" and jurisdiction == "US"
                     and right == "trademark_figurative" and t["kind"] not in {"design_code", "mark_description"})
            and (not t.get("_triage_decision") or (t["_triage_decision"].get("jurisdiction") == jurisdiction
                                                   and t["_triage_decision"].get("right_type") == right))
        ]
        # Do not fall back to a different language after local terms are
        # exhausted.  The resulting planning gap is more honest than a query
        # that looks complete but cannot support target-language recall.
        eligible.sort(key=lambda t: _dimension(t) == "owner")
        for route in requirement["routes"]:
            if route["operation"] in {"candidate_detail", "candidate_verification"}:
                continue
            for dimension in dict.fromkeys(_dimension(t) for t in eligible):
                scheduled_now = 0
                for term in [t for t in eligible if _dimension(t) == dimension]:
                    compiler_revision = ("ppubs-boolean-v2" if
                        necessary_work_enabled(task)
                        and route["provider"] == "uspto_patent_browser"
                        and term.get("strategy") == "boolean" and dimension != "classification" else None)
                    if route["provider"] == "epo_ops" and task.get("epo_query_revision"):
                        compiler_revision = task["epo_query_revision"]
                    if compiler_revision:
                        try:
                            boolean_tokens(term["value"], compiler_revision)
                        except ValueError as exc:
                            planning_gaps.append({"requirement_id": requirement["requirement_id"],
                                "jurisdiction": jurisdiction, "right_type": right, "provider": route["provider"],
                                "dimension": dimension, "code": "UNSUPPORTED_QUERY_SEMANTICS",
                                "reason": str(exc), "term_id": sha256_json(term), "query": term["value"],
                                "derived_from": [term["derived_from"]], "assigned_to": "agent"})
                            continue
                    params = _api_params(route["provider"], term, jurisdiction, right,
                                         query_compiler_revision=compiler_revision)
                    if params is None:
                        expansion_queue.append({"term_id": sha256_json(term), "provider": route["provider"],
                                                "requirement_id": requirement["requirement_id"], "dimension": dimension,
                                                "state": "deferred", "reason": "query_semantics_unimplemented"})
                        continue
                    if (identity_discovery_enabled(task) and route["provider"] == "uspto_tmsearch_browser"
                            and (right == "trademark_word" or task.get("specialty_workflow_revision") == "asset-scope-v1")):
                        # Bind the corrected field-tag control mapping to new
                        # query IDs; never reinterpret previously executed rows.
                        params["query_compiler_revision"] = "tm-figurative-fields-v1" if right == "trademark_figurative" else "tm-field-tags-v1"
                        from record_browser_execution import planned_browser_query
                        try:
                            planned_browser_query(route["provider"], {**params, "operation": route["operation"], "right_type": right,
                                "derived_from": [term["derived_from"]]})
                        except ValueError as exc:
                            planning_gaps.append({"requirement_id": requirement["requirement_id"],
                                "dimension": dimension, "code": "UNSUPPORTED_QUERY_SEMANTICS",
                                "reason": str(exc), "term_id": sha256_json(term), "assigned_to": "agent"})
                            continue
                    row = entry(route["provider"], route["operation"], jurisdiction, params,
                                required=False, right_type=right, requirement_ids=[requirement["requirement_id"]],
                                derived_from=[term["derived_from"]], wave=2 if expand else 1)
                    row.update(required_for="low_risk", execute_by_default=True, search_dimension=dimension,
                               search_language=term.get("language", ""), execution_phase=("initial" if scenario_workflow_enabled(task) and not term.get("_triage_decision") else phase))
                    if route["provider"] == "epo_ops":
                        row["publication_scope"] = _scope(jurisdiction, right)
                    if scenario_workflow_enabled(task):
                        row = bind_scenario_action(task, route["provider"], row, purpose="recall",
                                                   decision=term.get("_triage_decision"),
                                                   obligation_key={"requirement": requirement["requirement_id"],
                                                                   "dimension": dimension, "term": {key: value for key, value in term.items() if key != "_triage_decision"}})
                    existing = any(old["query_id"] == row["query_id"] for old in queries.get(route["provider"], []))
                    state = "scheduled" if existing or scheduled_now < 3 else "deferred"
                    expansion_queue.append({"term_id": sha256_json(term), "query_id": row["query_id"],
                                            "provider": route["provider"], "requirement_id": requirement["requirement_id"],
                                            "dimension": dimension, "state": state,
                                            "reason": "already_planned" if existing else "per_wave_limit" if state == "deferred" else "appended_this_wave"})
                    if not existing and state == "scheduled":
                        _add(queries, route["provider"], row)
                        scheduled_now += 1
        for dimension in requirement.get("required_axes", []):
            if not any(requirement["requirement_id"] in r.get("requirement_ids", []) and r.get("search_dimension") == dimension for rows in queries.values() for r in rows):
                planning_gaps.append({"requirement_id": requirement["requirement_id"], "dimension": dimension, "code": "SEARCH_DIMENSION_UNPLANNED", "assigned_to": "agent"})
        language_dimension = "description" if task.get("specialty_workflow_revision") == "asset-scope-v1" and right == "trademark_figurative" and jurisdiction == "US" else "text"
        if (requirement.get("required_language") and not any(
                _dimension(term) == language_dimension for term in eligible)):
            planning_gaps.append({"requirement_id": requirement["requirement_id"], "dimension": language_dimension,
                                  "code": "LOCAL_LANGUAGE_TERMS_MISSING", "language": requirement["required_language"], "assigned_to": "agent"})
    if task.get("specialty_workflow_revision") == "asset-scope-v1":
        from record_asset_provenance import asset_scope, INVESTIGATION_STEPS
        from decision_workflow import scenario_index, necessary_scenario_right_types
        for requirement in task["coverage_requirements"]:
            right = requirement["right_type"]
            if right not in INVESTIGATION_STEPS or (right == "trademark_figurative" and requirement["phase"] != "official_recall"):
                continue
            for sid, scenario in scenario_index(task).items():
                if right not in necessary_scenario_right_types(task, scenario):
                    continue
                scope = asset_scope(task, sid, right)
                for dimension in INVESTIGATION_STEPS[right]:
                    if right == "trademark_figurative" and dimension == "classification":
                        from record_asset_provenance import applicable_assets
                        marks = applicable_assets(task, sid, right)
                        if marks and not all(item.get("classification_review", {}).get("status") == "not_applicable" for item in marks):
                            continue  # Real applicable codes use the TM executor.
                    row = entry("asset_provenance", "provenance_review", requirement["jurisdiction"],
                        {"q": f"{right}:{dimension}:{scope['scope_sha256']}", "asset_scope_sha256": scope["scope_sha256"]},
                        required=False, right_type=right, requirement_ids=[requirement["requirement_id"]],
                        derived_from=["product.mark_inventory" if right == "trademark_figurative" else "product.assets"], wave=2)
                    row.update(required_for="low_risk", execute_by_default=False, search_dimension=dimension,
                               search_language="", execution_phase="initial")
                    row = bind_scenario_action(task, "asset_provenance", row, purpose="provenance", scenario_id=sid,
                        obligation_key={"requirement": requirement["requirement_id"], "dimension": dimension, "scope": scope["scope_sha256"]})
                    _add(queries, "asset_provenance", row)
        planning_gaps = [gap for gap in planning_gaps if not (gap.get("code") == "SEARCH_DIMENSION_UNPLANNED"
            and any(gap["requirement_id"] in row.get("requirement_ids", []) and gap["dimension"] == row.get("search_dimension")
                    for rows in queries.values() for row in rows))]
    if not previous:
        for requirement in task["coverage_requirements"]:
            if requirement["phase"] == "provenance" and task.get("specialty_workflow_revision") != "asset-scope-v1":
                for dimension in requirement["required_axes"]:
                    row = entry("asset_provenance", "provenance_review", requirement["jurisdiction"],
                                {"q": f"product-assets:{dimension}"}, required=False,
                                right_type=requirement["right_type"], requirement_ids=[requirement["requirement_id"]], derived_from=["product.assets"], wave=2)
                    row.update(required_for="low_risk", execute_by_default=False, search_dimension=dimension, search_language="", execution_phase="initial")
                    if scenario_workflow_enabled(task):
                        row = bind_scenario_action(task, "asset_provenance", row, purpose="provenance", obligation_key={"requirement": requirement["requirement_id"], "dimension": dimension})
                    _add(queries, "asset_provenance", row)
        text = [t for t in terms if t["kind"] in {"structural_feature", "category", "product", "function"}]
        brands = [t for t in terms if t["kind"] in {"brand", "ocr"}]
        jurisdictions = task["target_jurisdictions"]
        if serper_free_enabled(task) and not identity_discovery_enabled(task) and not api_first_enabled(task):
            for provider, seed, maximum in (("serper_patents", text, 4), ("serper_web", brands or text, 3), ("serper_images", text, 3)):
                for i, term in enumerate(seed[:maximum]):
                    right = "patent" if provider == "serper_patents" else "copyright" if provider == "serper_images" else "enforcement"
                    operation = {"serper_patents": "patents", "serper_web": "search", "serper_images": "images"}[provider]
                    row = serper_discovery_entry(provider, operation, jurisdictions[i % len(jurisdictions)], term["value"], [term["derived_from"]], right)
                    row.update(search_dimension="text", search_language=term.get("language", ""), execution_phase="initial")
                    _add(queries, provider, row)
        if signa_free_enabled(task) and brands and not api_first_enabled(task):
            office_map = {"US": "US", "EU": "EM", "GB": "GB", "FR": "FR"}
            offices = [office_map[j] for j in jurisdictions if j in office_map]
            for term in brands[:3] if offices else []:
                row = signa_discovery_entry(
                    ",".join(jurisdictions), term["value"], [term["derived_from"]], offices,
                )
                _add(queries, "signa", row)
        if serpapi_free_enabled(task) and not identity_discovery_enabled(task) and not api_first_enabled(task):
            from product_delivery import selected_public_image, query_row_binding
            selected_image = selected_public_image(task)
            images = [selected_image] if selected_image else []
            for i, term in enumerate(text[:2 if images else 3]):
                jurisdiction = jurisdictions[i % len(jurisdictions)]
                country = "EP" if jurisdiction == "EU" else jurisdiction
                matching = next((r for r in queries.get("serper_patents", []) if r["q"] == term["value"]), None)
                row = serpapi_discovery_entry(jurisdiction, term["value"], [term["derived_from"]], "patent", fallback_query_id=matching["query_id"] if matching else "")
                row.update(search_dimension="text", search_language=term.get("language", ""), execution_phase="initial")
                _add(queries, "serpapi_google_patents", row)
            if images:
                row = entry("serpapi_google_lens", "image_search", task["request"]["marketplace"],
                            {"q": images[0]["source_url"], "image_url": images[0]["source_url"], "type": "all", "hl": "en", "country": "us"},
                            required=False, right_type="copyright", requirement_ids=[], derived_from=[f"images[{task['images'].index(images[0])}].source_url"], wave=2)
                row.update(query_row_binding(task, images[0]))
                row.update(role="discovery_only", required_for="discovery_only", execute_by_default=True, authoritative_for_final_rating=False,
                           search_dimension="image", search_language="", execution_phase="initial")
                _add(queries, "serpapi_google_lens", row)
    if api_first_enabled(task):
        from api_first_planning import append_initial
        append_initial(task_dir, task, [t for t in selected_terms if not t.get("_triage_decision")], queries,
            planning_gaps, expansion_queue, retained_terms=selected_terms)
    elif identity_discovery_enabled(task):
        append_identity_discovery(task, selected_terms, queries, planning_gaps, phase)
    from product_delivery import enabled as delivery_enabled, selected_public_image
    if delivery_enabled(task) and task.get('product',{}).get('query_image',{}).get('status')=='selected' and not selected_public_image(task):
        planning_gaps.append({'code':'QUERY_IMAGE_ROUTE_UNAVAILABLE','dimension':'image','provider':'serpapi_google_lens',
            'reason':'Selected main image has no supported public URL or provider-and-purpose permission.',
            'assigned_to':'agent','blocking_planning':False})
    previous_ids = {row["query_id"] for values in (previous or {}).get("queries", {}).values() for row in values}
    if scenario_workflow_enabled(task):
        # Optional discovery retains its original task budget and one shared
        # product query; bind only newly built rows, never old evidence.
        remapped_ids = {}
        for provider, rows in queries.items():
            for index, row in enumerate(rows):
                if row["query_id"] not in previous_ids and not row.get("decision_workflow_revision"):
                    rows[index] = bind_scenario_action(task, provider, row, purpose="discovery", obligation_key=row["query_id"])
                    remapped_ids[row["query_id"]] = rows[index]["query_id"]
            deduplicated = {}
            for row in rows:
                deduplicated.setdefault(row["query_id"], row)
            queries[provider] = list(deduplicated.values())
        for rows in queries.values():
            for row in rows:
                if row["query_id"] not in previous_ids and row.get("fallback_query_id") in remapped_ids:
                    row["fallback_query_id"] = remapped_ids[row["fallback_query_id"]]
    from product_delivery import bind_fact_versions
    for rows in queries.values():
        for row in rows:
            if not previous or row['query_id'] not in previous_ids:
                bind_fact_versions(task,row)
    plan = {
        "schema_version": CURRENT_SCHEMA_VERSION, "task_id": task["task_id"],
        "created_at": previous["created_at"] if previous else now_iso(), "updated_at": now_iso(),
        "free_policy": task["free_policy"], "free_policy_revision": task["free_policy_revision"],
        **{key: task[key] for key in ("serper_free_enhancement", "serpapi_free_enhancement", "signa_free_enhancement")},
        "terms": selected_terms, "queries": queries, "planning_gaps": planning_gaps,
        **({"screening_revision": task["screening_revision"], "analysis_readiness": readiness} if recall_integrity_enabled(task) else {}),
        **({"recall_planning_revision": task["recall_planning_revision"]} if identity_discovery_enabled(task) else {}),
        **({"specialty_workflow_revision": task["specialty_workflow_revision"]} if task.get("specialty_workflow_revision") else {}),
        **({"decision_workflow_revision": task["decision_workflow_revision"]} if scenario_workflow_enabled(task) else {}),
        **({"workflow_correction_revision": WORKFLOW_CORRECTION_REVISION} if correction_enabled(task) else {}),
        **({"execution_policy_revision": task["execution_policy_revision"]} if task.get("execution_policy_revision") else {}),
        **({"retrieval_workflow_revision": task["retrieval_workflow_revision"]} if api_first_enabled(task) else {}),
        **({"epo_query_revision": task["epo_query_revision"]} if task.get("epo_query_revision") else {}),
        **({"retrieval_policy": deepcopy(task.get("retrieval_policy")),
            "retrieval_policy_sha256": sha256_json(task.get("retrieval_policy"))} if api_first_enabled(task) else {}),
        **({"term_dispositions": [brand_byline_disposition(task)]} if brand_byline_disposition(task) else {}),
        "expansion_queue": expansion_queue,
        "term_counts": {"discovered": len(selected_terms), "scheduled_routes": sum(r["state"] == "scheduled" for r in expansion_queue),
                        "deferred_routes": sum(r["state"] == "deferred" for r in expansion_queue)},
        "execution_policy": {"browser_execution": "agent_with_access_verification_only", "paid_execution_enabled": False,
                             "commercial_providers_enabled": any((serper_free_enabled(task), serpapi_free_enabled(task), signa_free_enabled(task))),
                             "commercial_freemium_allowlist": [n for n,f in (("serper", serper_free_enabled), ("signa", signa_free_enabled), ("serpapi", serpapi_free_enabled)) if f(task)]},
        "expansion": {"attempted": expand or bool(previous and previous.get("expansion", {}).get("attempted")),
                      "reason": "candidate-derived classified/owner queries appended; missing axes remain gaps" if expand else "run after initial candidate review"},
    }
    if previous and "execution_dispositions" in previous and recall_integrity_enabled(task):
        # Preserve the cancellation audit verbatim; validity is checked at use,
        # never by mutating or dropping historical query/disposition records.
        plan["execution_dispositions"] = deepcopy(previous["execution_dispositions"])
    if previous and scenario_workflow_enabled(task) and "action_substitutions" in previous:
        plan["action_substitutions"] = deepcopy(previous["action_substitutions"])
    if previous and correction_enabled(task) and "action_recoveries" in previous:
        plan["action_recoveries"] = deepcopy(previous["action_recoveries"])
    if scenario_workflow_enabled(task):
        reconcile_scenario_actions(task_dir, task, plan)
    if expand:
        append_next_pages(task_dir, plan)
    assert_default_discovery_plan_contract(task, plan, task_dir=task_dir)
    atomic_write_json(path, plan)
    if expand and scenario_workflow_enabled(task):
        # Rebuild selected-candidate obligations from the current decisions.
        # Rebuilding the discovery plan must not erase their unresolved gaps;
        # copying the old gaps would retain obligations for invalid decisions.
        if task.get("retrieval_workflow_revision") == "api-first-v3":
            append_scenario_candidate_actions(task_dir, task, candidates)
            plan = load_json(path)
        else:
            derived = append_scenario_candidate_actions(task_dir, task, candidates, gaps_only=True)
            plan.update(derived)
            atomic_write_json(path, plan)
    return plan


def _pagination_lineage(provider: str, row: dict, plan: dict) -> list[dict] | None:
    """Resolve only exact pagination-parent links; refinements start their own bound."""
    lineage, seen = [], set()
    while True:
        key = row.get("query_id")
        if not key or key in seen:
            return None
        lineage.append(row)
        seen.add(key)
        if row.get("discovery_role") != "pagination":
            return lineage
        parents = [item for item in plan.get("queries", {}).get(provider, [])
                   if item.get("query_id") == row.get("parent_query_id")]
        if (len(parents) != 1 or sha256_json(parents[0]) != row.get("parent_plan_entry_sha256")
                or any(row.get(k) != parents[0].get(k) for k in
                       ("discovery_intent_id", "refinement_round", "q", "jurisdiction", "right_type"))):
            return None
        row = parents[0]


def _pagination_frozen_scope_block(task_dir: Path, task: dict, plan: dict,
                                    evidence: dict, provider: str, source: dict,
                                    next_size: int) -> str | None:
    if source.get("action_purpose") != "discovery" or not isinstance(source.get("discovery_scope"), dict):
        return None  # Historical rows without this frozen scope keep their original limit.
    lineage = _pagination_lineage(provider, source, plan)
    if lineage is None:
        return "DISCOVERY_PAGINATION_PARENT_INVALID"
    root = lineage[-1]
    scope = root.get("discovery_scope", {})
    pages_limit, cards_limit = scope.get("max_pages"), scope.get("max_candidates")
    if (type(pages_limit) is not int or pages_limit < 1
            or type(cards_limit) is not int or cards_limit < 1):
        return "DISCOVERY_SCOPE_INVALID"
    reviews = [review for review in task.get("discovery_followups", [])
               if isinstance(review, dict) and review.get("role") == "review"
               and review.get("outcome") == "stop_bounded_discovery"
               and review.get("parent_query_id") in {row["query_id"] for row in lineage}]
    if reviews:
        from api_first_planning import review_validation
        candidates, ledger, _ = _scenario_context(task_dir, task)
        supplement = scenario_supplement(task_dir, task=task, evidence=evidence)
        for row in lineage:
            if any(review.get("parent_query_id") == row["query_id"]
                   and review_validation(task, plan, evidence, candidates, ledger, row, review, supplement) is None
                   for review in reviews):
                return "API_DISCOVERY_BOUNDED_STOP"
    branch = []
    for row in plan.get("queries", {}).get(provider, []):
        ancestry = _pagination_lineage(provider, row, plan)
        if ancestry and ancestry[-1].get("query_id") == root["query_id"]:
            branch.append(row)
    keys = {(row.get("query_id"), sha256_json(row)) for row in branch}
    pages, cards, seen = 0, 0, set()
    from discovery_budget import _run_pages
    for run in evidence.get("source_runs", []):
        if (not isinstance(run, dict) or run.get("provider") != provider
                or (run.get("query_id"), run.get("plan_entry_sha256")) not in keys
                or run.get("run_id") in seen):
            continue
        seen.add(run.get("run_id"))
        acquired_pages = _run_pages(run, include_valid_failed=True)
        if not acquired_pages:
            continue
        count = run.get("result_processing", {}).get("returned_count")
        if count is None:
            count = run.get("metadata", {}).get("search_coverage", {}).get("retrieved_hits")
        if type(count) is not int or count < 0:
            return "DISCOVERY_CANDIDATE_COUNT_PENDING_PARSE"
        pages += acquired_pages
        cards += count
    if pages + 1 > pages_limit:
        return "DISCOVERY_SCOPE_PAGE_LIMIT"
    if cards + next_size > cards_limit:
        return "DISCOVERY_SCOPE_CANDIDATE_LIMIT"
    return None


def append_next_pages(task_dir: Path, plan: dict) -> None:
    """Advance bounded pages only from successful, hash-bound actual responses."""
    from generate_search_plan import entry
    evidence = load_json(task_dir / "evidence.json")
    task = load_json(task_dir / "task.json")
    limit = 8  # Per query; hitting the bound remains explicitly truncated.
    pagination_gaps = []
    plan["pagination_gaps"] = pagination_gaps
    for provider, rows in list(plan["queries"].items()):
        if provider not in {"epo_ops", "euipo_trademark", "euipo_design", "inpi_api"}:
            for source in rows:
                if validated_query_cancellation(task, plan, source):
                    continue
                bound = [r for r in evidence.get("source_runs", []) if r.get("provider") == provider and r.get("query_id") == source["query_id"] and r.get("plan_entry_sha256") == sha256_json(source)]
                if not bound or bound[-1].get("status") != "success":
                    continue
                meta = bound[-1].get("metadata", {}).get("search_coverage", {})
                if meta.get("truncated") or meta.get("stop_reason") == "browser_current_page_only":
                    pagination_gaps.append({"query_id": source["query_id"], "provider": provider,
                                            "state": "deferred", "code": "PAGINATION_NOT_VALIDATED", "coverage": meta})
            continue
        for source in list(rows):
            if validated_query_cancellation(task, plan, source):
                continue
            if source.get("operation") != "search":
                continue
            bound = [r for r in evidence.get("source_runs", []) if r.get("provider") == provider and r.get("query_id") == source["query_id"] and r.get("plan_entry_sha256") == sha256_json(source)]
            if not bound or bound[-1].get("status") != "success":
                continue
            meta = bound[-1].get("metadata", {}).get("search_coverage", {})
            from discovery_budget import enabled as purpose_budget_enabled, snapshot as purpose_budget_snapshot
            if purpose_budget_enabled(task) and source.get("action_purpose") == "discovery":
                budget = purpose_budget_snapshot(task, plan, evidence, source)
                if budget["remaining_pages"] == 0:
                    pagination_gaps.append({"query_id": source["query_id"], "provider": provider,
                        "state": "deferred", "code": "DISCOVERY_VERSION_PAGE_LIMIT",
                        "purpose_id": budget["purpose_id"], "version": budget["version"]})
                    continue
            total, retrieved = meta.get("total_hits"), meta.get("retrieved_hits")
            if meta.get("schema_valid") is not True or isinstance(total, bool) or not isinstance(total, int) or not isinstance(retrieved, int) or retrieved <= 0:
                continue
            from provider_utils import PLAN_META_KEYS
            params = {k: v for k, v in source.items() if k not in PLAN_META_KEYS}
            if provider == "epo_ops":
                start, end = map(int, str(source.get("range", "1-25")).split("-"))
                size, offset = end - start + 1, start - 1
                if size <= 0:
                    continue
                if offset + size < total and offset // size + 1 >= limit:
                    pagination_gaps.append({"query_id": source["query_id"], "provider": provider, "state": "deferred", "code": "PAGE_LIMIT_REACHED", "total_hits": total})
                if offset + size >= total or offset // size + 1 >= limit:
                    continue
                params["range"] = f"{end + 1}-{end + size}"
            else:
                size = int(source.get("size", 25))
                offset = int(source.get("position", 0)) if provider == "inpi_api" else int(source.get("page", 0)) * size
                if size > 0 and offset + size < total and offset // size + 1 >= limit:
                    pagination_gaps.append({"query_id": source["query_id"], "provider": provider, "state": "deferred", "code": "PAGE_LIMIT_REACHED", "total_hits": total})
                if size <= 0 or offset + size >= total or offset // size + 1 >= limit:
                    continue
                params["position" if provider == "inpi_api" else "page"] = offset + size if provider == "inpi_api" else offset // size + 1
            frozen_block = _pagination_frozen_scope_block(task_dir, task, plan, evidence,
                provider, source, size)
            if frozen_block:
                pagination_gaps.append({"query_id": source["query_id"], "provider": provider,
                    "state": "deferred", "code": frozen_block, "total_hits": total})
                continue
            row = entry(provider, "search", source["jurisdiction"], params, required=False,
                        right_type=source["right_type"], requirement_ids=source["requirement_ids"], derived_from=source["derived_from"], wave=2)
            row.update(required_for=source["required_for"], execute_by_default=True,
                       **{k: source[k] for k in SEARCH_META_KEYS if k in source})
            if purpose_budget_enabled(task) and source.get("action_purpose") == "discovery":
                row.update({key: deepcopy(source[key]) for key in API_FIRST_PLAN_META_KEYS
                            if key in source and key not in {"parent_query_id", "parent_plan_entry_sha256"}})
                row.update(discovery_role="pagination", parent_query_id=source["query_id"],
                           parent_plan_entry_sha256=sha256_json(source),
                           role="discovery_only", authoritative_for_final_rating=False,
                           provider_role=source.get("provider_role"), source_upstream=source.get("source_upstream"))
                row["discovery_scope"] = {**row["discovery_scope"], "max_pages": 1,
                    "pagination_basis": {"source_run_id": bound[-1]["run_id"],
                                         "source_run_sha256": sha256_json(bound[-1])}}
            if scenario_workflow_enabled(task):
                from provider_utils import query_identity
                row.update({key: deepcopy(source[key]) for key in SCENARIO_META_KEYS if key in source
                            and not (purpose_budget_enabled(task) and source.get("action_purpose") == "discovery"
                                     and key in API_FIRST_PLAN_META_KEYS)})
                identity = {key: value for key, value in row.items() if key not in PLAN_META_KEYS or key in SCENARIO_META_KEYS}
                identity["right_type"] = row["right_type"]
                row["query_id"] = query_identity(provider, "search", row["jurisdiction"], row["q"], identity)
            _add(plan["queries"], provider, row)


def append_candidate_actions(task_dir: Path, task: dict, candidates: dict) -> None:
    """Append known-number actions; absent identity is an agent retrieval gap."""
    if scenario_workflow_enabled(task):
        return append_scenario_candidate_actions(task_dir, task, candidates)
    from generate_search_plan import entry
    from merge_candidates import _candidate_document_for_jurisdiction, _jp_candidate_number, _epo_candidate_document
    path = task_dir / "search-plan.json"
    if not path.is_file():
        return
    plan = load_json(path)
    queries = plan["queries"]
    gaps = []
    detail_cap = int(load_skill_config().get("limits", {}).get("epo_candidate_detail_limit", 18))
    for collection in ("patents", "trademarks"):
        for candidate in candidates.get(collection, []):
            if not candidate.get("material"):
                continue
            right, identifier = candidate["right_type"], candidate["candidate_id"]
            origin = str(candidate.get("jurisdiction") or candidate.get("office") or "").upper()
            origin = {"EUIPO": "EU", "EM": "EU", "USPTO": "US"}.get(origin, origin)
            for requirement in task["coverage_requirements"]:
                country = requirement["jurisdiction"]
                if requirement["phase"] != "candidate_verification" or requirement["right_type"] != right:
                    continue
                european_patent = right == "patent" and origin in {"EU", "EP", "WO"} and country in {"EU", "GB", "FR", "DE", "IT", "ES"}
                if origin != country and not european_patent and origin != "WO":
                    continue
                for route in requirement["routes"]:
                    provider = route["provider"]
                    if route["operation"] != "candidate_verification" or provider == "oepm_api":
                        continue
                    number = _candidate_document_for_jurisdiction(candidate, country) if right in {"patent", "utility_model"} else str(candidate.get("application_number") or candidate.get("serial_number") or candidate.get("registration_number") or candidate.get("publication_number") or candidate.get("record_number") or "")
                    # EP effect is queried by the known EP number in each target
                    # register; lack of a national number is not proof of absence.
                    if not number and european_patent:
                        number = _candidate_document_for_jurisdiction(candidate, "EU")
                    if provider == "jpo_api":
                        number, number_kind = _jp_candidate_number(candidate, right)
                    if not number:
                        gaps.append({"candidate_id": identifier, "requirement_id": requirement["requirement_id"], "code": "OFFICIAL_IDENTIFIER_MISSING", "assigned_to": "agent"})
                        continue
                    params = {"q": number, "candidate_id": identifier}
                    if provider == "inpi_api":
                        if origin != "FR":
                            continue  # FR national notice endpoint is not an EP effect register.
                        params["identifier"] = number
                    elif provider in {"euipo_trademark", "euipo_design"}:
                        params.update(identifier=number, detail=True)
                    elif provider == "jpo_api":
                        params.update(number=number, number_kind=number_kind)
                    elif provider == "uspto_tsdr":
                        params.update(serial_number=number, mode="agent")
                    else:
                        params["record_number"] = number
                        if provider != "uspto_patent_browser":
                            params["mode"] = "agent"
                    if recall_integrity_enabled(task) and (provider.endswith("browser") or provider == "uspto_tsdr"):
                        params["strategy"] = "record_number"
                    row = entry(provider, "candidate_verification", country, params, required=False,
                                right_type=right, requirement_ids=[requirement["requirement_id"]], derived_from=[f"candidate:{identifier}"], wave=2)
                    row.update(required_for="formal", execute_by_default=True, search_dimension="identifier", search_language="", execution_phase="verification")
                    _add(queries, provider, row)
            if right == "patent":
                document = _epo_candidate_document(candidate)
                eligible = [req for req in task["coverage_requirements"] if req["right_type"] == right and any(r["provider"] == "epo_ops" and r["operation"] == "candidate_detail" for r in req["routes"])]
                # One bibliographic/family/legal set per candidate. These are
                # enrichment, never evidence of national enforceability.
                if eligible and document:
                    requirement = next((req for req in eligible if req["jurisdiction"] == origin or req["jurisdiction"] == "EU" and origin in {"EP", "WO"}), eligible[0])
                    for detail in ("biblio", "family", "legal"):
                        if sum(r.get("operation") == "candidate_detail" for r in queries.get("epo_ops", [])) >= detail_cap:
                            gaps.append({"candidate_id": identifier, "code": "FAMILY_ENRICHMENT_TASK_LIMIT", "assigned_to": "agent"})
                            break
                        row = entry("epo_ops", "candidate_detail", requirement["jurisdiction"],
                                    {"q": document, "document": document, "detail_operation": detail, "candidate_id": identifier}, required=False,
                                    right_type=right, requirement_ids=[requirement["requirement_id"]], derived_from=[f"candidate:{identifier}"], wave=2)
                        row.update(required_for="comparison", execute_by_default=True, search_dimension="family" if detail == "family" else "identifier", search_language="", execution_phase="enrichment")
                        _add(queries, "epo_ops", row)
                document = _candidate_document_for_jurisdiction(candidate, "EU")
                if re.fullmatch(r"EP\d+[AB]\d", document):
                    row = entry("epo_publication_server", "document_retrieval", "EP",
                                {"q": document, "document": document, "format": "xml", "candidate_id": identifier}, required=False,
                                right_type=right, requirement_ids=[], derived_from=[f"candidate:{identifier}"], wave=2)
                    row.update(required_for="comparison", execute_by_default=True, search_dimension="claims", search_language="", execution_phase="verification")
                    _add(queries, "epo_publication_server", row)
                # Google Patents Details is a content fallback only.  It shares
                # the already opted-in SerpApi account and is never a current-
                # status verification source.
                if document and task.get("retrieval_workflow_revision") == RETRIEVAL_WORKFLOW_REVISION and serpapi_free_enabled(task):
                    row = entry("serpapi_google_patents", "candidate_detail", origin or country,
                                {"q": document, "patent_id": "patent/" + document + "/en", "candidate_id": identifier},
                                required=False, right_type=right, requirement_ids=[], derived_from=[f"candidate:{identifier}"], wave=2)
                    row.update(required_for="comparison", execute_by_default=True, search_dimension="claims",
                               search_language="", execution_phase="verification", source_upstream="google_patents",
                               provider_role="fallback")
                    _add(queries, "serpapi_google_patents", row)
    plan["candidate_action_gaps"] = gaps
    for candidate in candidates.get("copyright_assets", []):
        right = candidate.get("right_type", "copyright")
        if right not in NON_REGISTERED_RIGHTS:
            continue
        for requirement in task["coverage_requirements"]:
            if requirement["phase"] != "provenance" or requirement["right_type"] != right:
                continue
            row = entry("asset_provenance", "provenance_review", requirement["jurisdiction"],
                        {"q": "candidate-source:" + candidate["candidate_id"], "candidate_id": candidate["candidate_id"]}, required=False,
                        right_type=right, requirement_ids=[requirement["requirement_id"]], derived_from=[f"candidate:{candidate['candidate_id']}"], wave=2)
            row.update(required_for="comparison", execute_by_default=False, search_dimension="provenance", search_language="", execution_phase="verification")
            _add(queries, "asset_provenance", row)
    plan["updated_at"] = now_iso()
    atomic_write_json(path, plan)


def _owner_verification_required(task, decision):
    from specialty_analysis import _intake, events, SCOPE
    scope = tuple(decision.get(key) for key in SCOPE)
    intake = _intake(task, scope)
    if not intake or intake.get("annotation_id") != decision.get("annotation", {}).get("annotation_id"):
        return False
    current = [row for row in events(task) if tuple(row.get(key) for key in SCOPE) == scope
               and row.get("intake_event_id") == intake["event_id"]]
    facts = [row for row in current if row.get("kind") == "fact" and row.get("fact_kind") == "rights_holder"]
    if facts:
        return facts[-1].get("outcome") == "unknown"
    classifications = {row.get("handoff_gap"): row for row in current
                       if row.get("kind") == "handoff_classification"}
    return any("rights_holder" in row.get("fact_kinds", []) for row in classifications.values())


def append_scenario_candidate_actions(task_dir: Path, task: dict, candidates: dict, *, gaps_only: bool = False):
    """Deep verification is a selected-decision action, not a recall side effect."""
    from decision_workflow import triage_summary, scenario_index, necessary_scenario_right_types, triage_scope_enabled, UNLOCATED
    from generate_search_plan import entry
    from merge_candidates import _candidate_document_for_jurisdiction, _jp_candidate_number, _epo_candidate_document
    from annotate_materiality import iter_candidates
    path = task_dir / "search-plan.json"
    if not path.is_file():
        return
    plan = load_json(path)
    assert_recall_planning_contract(task, plan)
    _, ledger, evidence = _scenario_context(task_dir, task)
    summary = triage_summary(task, candidates, ledger, evidence=evidence,
        supplement=scenario_supplement(task_dir, task=task, evidence=evidence))
    scenarios = scenario_index(task)
    indexed = {item["candidate_id"]: item for _, item in iter_candidates(candidates)}
    gaps, queues = [], []
    queries = plan["queries"]
    detail_cap = int(load_skill_config().get("limits", {}).get("epo_candidate_detail_limit", 18))
    for decision in summary.get("records", []):
        candidate = indexed[decision["candidate_id"]]
        country, right = decision["jurisdiction"], decision["right_type"]
        if triage_scope_enabled(task) and (country == UNLOCATED or right == "unknown"
                or str(candidate.get("jurisdiction") or "").upper() != country):
            # A source-backed association is not authority to submit a
            # country/right-specific verification or needs-info request.
            continue
        if right not in necessary_scenario_right_types(task, scenarios[decision["scenario_id"]]):
            continue
        if not decision.get("current") or decision.get("decision") not in {"selected", "needs_info"}:
            if decision.get("decision") == "unreviewed" or not decision.get("current"):
                queues.append({**decision, "queue": "triage"})
            continue
        requirements = [req for req in task["coverage_requirements"]
                        if req["jurisdiction"] == country and req["right_type"] == right]
        if decision["decision"] == "needs_info":
            for action in decision.get("next_actions", []):
                if action.get("kind") != "source_lookup":
                    queues.append({"candidate_id": decision["candidate_id"], "scenario_id": decision["scenario_id"],
                                   "jurisdiction": country, "right_type": right, "queue": action.get("kind"), "action": action})
                    continue
                provider, operation, params = action.get("provider"), action.get("operation"), action.get("params")
                # A candidate-verification action is naturally expressed with
                # its record_number.  Normalize that identifier into the
                # planner's exact query field before checking the execution
                # contract; otherwise a valid approved action is stranded as
                # "unplanned" solely because it did not duplicate the same
                # identifier in two input keys.
                if (provider == "uspto_patent_browser" and operation == "candidate_verification"
                        and isinstance(params, dict) and not str(params.get("q") or "").strip()
                        and str(params.get("record_number") or "").strip()):
                    params = {**params, "q": params["record_number"]}
                eligible = [req for req in requirements if any(route.get("provider") == provider and route.get("operation") == operation for route in (
                    req.get("routes", []) + (req.get("gap_only_routes", []) if task.get("retrieval_workflow_revision") == "api-first-v3" else [])))]
                if (not eligible and task.get("retrieval_workflow_revision") == "api-first-v3"
                        and provider == "serpapi_google_patents" and operation == "candidate_detail"
                        and right in {"patent", "utility_model", "design"}):
                    # The selected-candidate API reader is also available for
                    # a bounded 05B content gap, using the same exact contract.
                    from candidate_followup import request_class
                    from common import provider_execution_error
                    if (isinstance(params, dict) and request_class(provider, operation, params) == "targeted"
                            and not provider_execution_error(task, provider, operation, jurisdiction=country, right_type=right)):
                        eligible = [req for req in requirements if req.get("phase") == "candidate_verification"]
                if operation == "candidate_verification" and provider == "uspto_patent_browser" and not eligible:
                    # The US design coverage requirement configures the PPS
                    # recall route.  Exact-record verification is a narrower
                    # follow-up on that same official route, not a second
                    # discovery provider, and remains bound to one candidate.
                    eligible = [req for req in requirements if any(
                        route.get("provider") == provider and route.get("operation") == "design_recall"
                        for route in req.get("routes", []))]
                if (not eligible or not isinstance(params, dict) or not str(params.get("q") or "").strip()
                        or action.get("max_attempts") != 1 or not action.get("action_id")
                        or (params.get("candidate_id") and params["candidate_id"] != decision["candidate_id"])):
                    gaps.append({"code": "NEEDS_INFO_ACTION_UNSUPPORTED", "candidate_id": decision["candidate_id"],
                                 "scenario_id": decision["scenario_id"], "jurisdiction": country, "right_type": right,
                                 "action_id": action.get("action_id"), "assigned_to": "agent"})
                    continue
                if operation == "candidate_verification" and provider in {"uspto_patent_browser", "uspto_tsdr"}:
                    field = "record_number" if provider == "uspto_patent_browser" else "serial_number"
                    identifier = re.sub(r"[^A-Za-z0-9]", "", str(params.get(field) or "")).upper()
                    requested = re.sub(r"[^A-Za-z0-9]", "", str(params.get("q") or "")).upper()
                    if (not identifier or identifier != requested
                            or params.get("candidate_id") != decision["candidate_id"]):
                        gaps.append({"code": "INTERNAL_CANDIDATE_PLAN_CONTRACT_ERROR",
                                     "candidate_id": decision["candidate_id"], "scenario_id": decision["scenario_id"],
                                     "jurisdiction": country, "right_type": right,
                                     "action_id": action["action_id"], "assigned_to": "agent",
                                     "reason": f"{provider} requires matching q/{field} and candidate_id; action not submitted."})
                        continue
                dimension = "identifier"
                if api_first_enabled(task) and provider == "asset_provenance":
                    from record_asset_provenance import specialty_enabled, asset_scope, INVESTIGATION_STEPS
                    scope = asset_scope(task, decision["scenario_id"], right)
                    reading_scope = action.get("reading_scope")
                    dimension = reading_scope.get("investigation_step") if isinstance(reading_scope, dict) else None
                    if (not specialty_enabled(task) or operation != "provenance_review"
                            or dimension not in INVESTIGATION_STEPS.get(right, ())
                            or params.get("asset_scope_sha256") != scope["scope_sha256"]
                            or params.get("candidate_id") != decision["candidate_id"]):
                        gaps.append({"code": "NEEDS_INFO_ACTION_UNSUPPORTED", "candidate_id": decision["candidate_id"],
                                     "scenario_id": decision["scenario_id"], "jurisdiction": country, "right_type": right,
                                     "action_id": action["action_id"], "assigned_to": "agent",
                                     "reason": "asset_provenance requires provenance_review, the current asset_scope_sha256, "
                                               "matching candidate_id and an explicit allowed reading_scope.investigation_step; "
                                               "repair the Agent action before planning."})
                        continue
                row = entry(provider, operation, country, deepcopy(params), required=False, right_type=right,
                            requirement_ids=[req["requirement_id"] for req in eligible],
                            derived_from=[f"candidate:{decision['candidate_id']}"], wave=2)
                row.update(required_for="comparison", execute_by_default=True, search_dimension=dimension,
                           search_language="", execution_phase="needs_info", triage_action_id=action["action_id"])
                if correction_enabled(task):
                    row.update(required_facts=deepcopy(action.get("required_facts")), reading_scope=deepcopy(action.get("reading_scope")))
                    if not reading_contract_valid(row):
                        gaps.append({"code": "NEEDS_INFO_READING_CONTRACT_INVALID", "candidate_id": decision["candidate_id"],
                                     "scenario_id": decision["scenario_id"], "jurisdiction": country, "right_type": right,
                                     "action_id": action["action_id"], "assigned_to": "agent"})
                        continue
                row = bind_scenario_action(task, provider, row, purpose="needs_info:" + action["purpose"],
                                           decision=decision, obligation_key=action["action_id"])
                _add(queries, provider, row)
            continue
        from trusted_api import enabled as api_trust_enabled, REGISTERED as API_REGISTERED
        if api_trust_enabled(task) and right in API_REGISTERED:
            from candidate_api_actions import append as append_api_actions
            gaps.extend(append_api_actions(task, evidence, queries, candidate, decision, requirements, plan=plan, task_dir=task_dir))
            continue
        origin = str(candidate.get("jurisdiction") or candidate.get("office") or "").upper()
        origin = {"EUIPO": "EU", "EM": "EU", "USPTO": "US"}.get(origin, origin)
        for requirement in requirements:
            if requirement["phase"] != "candidate_verification":
                continue
            for route in requirement["routes"]:
                provider = route["provider"]
                if route["operation"] != "candidate_verification" or provider == "oepm_api":
                    continue
                number = _candidate_document_for_jurisdiction(candidate, country) if right in {"patent", "utility_model", "design"} else str(candidate.get("serial_number") or candidate.get("application_number") or candidate.get("registration_number") or candidate.get("publication_number") or candidate.get("record_number") or "")
                if not number and right == "patent" and origin in {"EU", "EP", "WO"} and country in {"EU", "GB", "FR", "DE", "IT", "ES"}:
                    number = _candidate_document_for_jurisdiction(candidate, "EU")
                if provider == "jpo_api":
                    number, number_kind = _jp_candidate_number(candidate, right)
                if not number or provider == "inpi_api" and origin != "FR":
                    gaps.append({"code": "OFFICIAL_IDENTIFIER_MISSING", "candidate_id": decision["candidate_id"],
                                 "scenario_id": decision["scenario_id"], "jurisdiction": country, "right_type": right,
                                 "requirement_id": requirement["requirement_id"], "assigned_to": "agent"})
                    continue
                params = {"q": number, "candidate_id": decision["candidate_id"]}
                if provider == "inpi_api":
                    params["identifier"] = number
                elif provider in {"euipo_trademark", "euipo_design"}:
                    params.update(identifier=number, detail=True)
                elif provider == "jpo_api":
                    params.update(number=number, number_kind=number_kind)
                elif provider == "uspto_tsdr":
                    params.update(serial_number=number, mode="agent", strategy="record_number")
                else:
                    params["record_number"] = number
                    if provider != "uspto_patent_browser":
                        params["mode"] = "agent"
                    if provider.endswith("browser"):
                        params["strategy"] = "record_number"
                row = entry(provider, "candidate_verification", country, params, required=False,
                            right_type=right, requirement_ids=[requirement["requirement_id"]], derived_from=[f"candidate:{decision['candidate_id']}"], wave=2)
                row.update(required_for="formal", execute_by_default=True, search_dimension="identifier", search_language="", execution_phase="verification")
                if correction_enabled(task) and provider == "uspto_patent_browser":
                    # PPS is an official publication/document source, not a
                    # current-status or ownership register. Do not send it an
                    # impossible status request and mislabel the local routing
                    # refusal as an official-source failure.
                    content = deepcopy(row)
                    content.update(required_for="comparison", search_dimension="claims", required_facts=["protection_content"],
                                   reading_scope={"level": "protection_content"})
                    _add(queries, provider, bind_scenario_action(task, provider, content, purpose="document_content", decision=decision))
                    route_prefix = "US_DESIGN" if right == "design" else "US_PATENT"
                    status_reason = ("Accepted candidate-specific current-status register/event and Assignment Center routes "
                                     "must be implemented and accepted before current status or ownership can be claimed."
                                     if right == "design" else
                                     "Patent Center, maintenance-fee and Assignment Center verification must be implemented and accepted before current status or ownership can be claimed.")
                    gaps.append({"code": route_prefix + "_STATUS_ROUTE_UNIMPLEMENTED", "candidate_id": decision["candidate_id"],
                                 "scenario_id": decision["scenario_id"], "jurisdiction": country, "right_type": right,
                                 "required_facts": ["current_status"],
                                 "requirement_id": requirement["requirement_id"], "assigned_to": "implementation",
                                 "reason": status_reason})
                    if _owner_verification_required(task, decision):
                        gaps.append({"code": route_prefix + "_OWNER_ROUTE_UNIMPLEMENTED", "candidate_id": decision["candidate_id"],
                                     "scenario_id": decision["scenario_id"], "jurisdiction": country, "right_type": right,
                                     "required_facts": ["rights_holder"],
                                     "requirement_id": requirement["requirement_id"], "assigned_to": "implementation",
                                     "reason": "An accepted candidate-specific Assignment Center route is required to verify the current rights holder; an original publication is only dated bibliographic evidence."})
                    continue
                _add(queries, provider, bind_scenario_action(task, provider, row, purpose="official_verification", decision=decision))
        if right == "patent":
            document = _epo_candidate_document(candidate)
            enrich_requirements = [req["requirement_id"] for req in requirements if any(
                route.get("provider") == "epo_ops" and route.get("operation") == "candidate_detail" for route in req.get("routes", []))]
            for detail in ("biblio", "family", "legal") if document and enrich_requirements else ():
                if sum(row.get("operation") == "candidate_detail" for row in queries.get("epo_ops", [])) >= detail_cap:
                    break
                row = entry("epo_ops", "candidate_detail", country,
                            {"q": document, "document": document, "detail_operation": detail, "candidate_id": decision["candidate_id"]},
                            required=False, right_type=right, requirement_ids=enrich_requirements, derived_from=[f"candidate:{decision['candidate_id']}"], wave=2)
                row.update(required_for="optional_enrichment", execute_by_default=True, search_dimension="family" if detail == "family" else "identifier", search_language="", execution_phase="enrichment")
                _add(queries, "epo_ops", bind_scenario_action(task, "epo_ops", row, purpose="enrichment", decision=decision, obligation_key=detail))
            document = _candidate_document_for_jurisdiction(candidate, "EU")
            if re.fullmatch(r"EP\d+[AB]\d", document):
                row = entry("epo_publication_server", "document_retrieval", "EP",
                            {"q": document, "document": document, "format": "xml", "candidate_id": decision["candidate_id"]},
                            required=False, right_type=right, requirement_ids=[], derived_from=[f"candidate:{decision['candidate_id']}"], wave=2)
                row.update(required_for="comparison", execute_by_default=True, search_dimension="claims", search_language="", execution_phase="verification")
                _add(queries, "epo_publication_server", bind_scenario_action(task, "epo_publication_server", row, purpose="document_content", decision=decision))
            document = _epo_candidate_document(candidate)
            if document and task.get("retrieval_workflow_revision") == RETRIEVAL_WORKFLOW_REVISION and serpapi_free_enabled(task):
                row = entry("serpapi_google_patents", "candidate_detail", country,
                            {"q": document, "patent_id": "patent/" + document + "/en", "candidate_id": decision["candidate_id"]},
                            required=False, right_type=right, requirement_ids=[], derived_from=[f"candidate:{decision['candidate_id']}"], wave=2)
                row.update(required_for="comparison", execute_by_default=True, search_dimension="claims", search_language="",
                           execution_phase="verification", source_upstream="google_patents", provider_role="fallback")
                _add(queries, "serpapi_google_patents", bind_scenario_action(task, "serpapi_google_patents", row,
                    purpose="document_content", decision=decision, obligation_key="serpapi_details"))
        if right in NON_REGISTERED_RIGHTS:
            for requirement in requirements:
                if requirement["phase"] != "provenance":
                    continue
                from record_asset_provenance import specialty_enabled, asset_scope, INVESTIGATION_STEPS
                scope = asset_scope(task, decision["scenario_id"], right) if specialty_enabled(task) else None
                for dimension in INVESTIGATION_STEPS[right] if scope is not None else ("provenance",):
                    params = {"q": "candidate-source:" + decision["candidate_id"], "candidate_id": decision["candidate_id"]}
                    if scope is not None:
                        params.update(q=params["q"] + ":" + dimension + ":" + scope["scope_sha256"], asset_scope_sha256=scope["scope_sha256"])
                    row = entry("asset_provenance", "provenance_review", country, params,
                                required=False, right_type=right, requirement_ids=[requirement["requirement_id"]], derived_from=[f"candidate:{decision['candidate_id']}"], wave=2)
                    row.update(required_for="comparison", execute_by_default=False, search_dimension=dimension, search_language="", execution_phase="verification")
                    _add(queries, "asset_provenance", bind_scenario_action(task, "asset_provenance", row, purpose="provenance", decision=decision,
                        **({"obligation_key": {"dimension": dimension, "scope": scope["scope_sha256"]}} if scope is not None else {})))
    if gaps_only:
        # Plan expansion preserves its existing query contract; only refresh
        # derived work here. The explicit candidate-action stage adds queries.
        return {"candidate_action_gaps": gaps, "triage_action_queue": queues}
    plan["candidate_action_gaps"], plan["triage_action_queue"] = gaps, queues
    reconcile_scenario_actions(task_dir, task, plan, candidates, ledger, evidence)
    plan["updated_at"] = now_iso()
    atomic_write_json(path, plan)

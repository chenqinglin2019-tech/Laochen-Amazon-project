#!/usr/bin/env python3
"""Execute immutable 2.4 browser rows serially; humans only restore access."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from common import (assert_active_free_policy, atomic_write_json, load_json,
                    now_iso, path_within, plan_free_policy_matches_task, sha256_file, load_skill_config,
                    recall_integrity_enabled)
from provider_utils import (PLAN_META_KEYS, ProviderError, authorize_exact_plan_execution,
                            record_error, redact_sensitive_text)
from execution_lock import execution_lock
from record_browser_execution import canonical_digest, validate_browser_execution
from workflow_v24 import (validated_query_cancellation, reconcile_scenario_actions,
                         scenario_workflow_enabled, correction_enabled, TEMPORARY_DISPATCH_CODES,
                         record_action_recovery)

ROOT = Path(__file__).resolve().parents[1]
CDP = ROOT / "tools" / "cdp" / "cdp-cli.mjs"
SUCCESS = {"success", "no_result"}
USER_ACTIONS = ["login", "captcha", "mfa", "consent", "qr"]
# Local backoff policy, not a claim about USPTO's reset time. After expiry the
# browser still checks the visible limit notice before any submission.
RATE_LIMIT_BACKOFF_SECONDS = 900


def browser_provider(provider: str) -> bool:
    return provider.endswith("_browser") or provider == "uspto_tsdr"


def browser_implementation_digest(task: dict) -> str:
    """Invalidate browser reuse for implementation/settings changes, never credentials."""
    files = [CDP, *sorted((ROOT / "tools" / "cdp").glob("*adapter*.mjs")),
             ROOT / "references" / "runtime-config.json"]
    digest = canonical_digest({str(p.relative_to(ROOT)): sha256_file(p)
                               for p in files if p.is_file()})
    if correction_enabled(task):
        digest = canonical_digest({"browser": digest,
            "python": {name: sha256_file(ROOT / "scripts" / name) for name in
                ("workflow_v24.py", "run_browser_plan.py", "provider_utils.py", "record_uspto_patent_chrome_verification.py")}})
    return digest


def _rate_limited(value: dict) -> bool:
    coverage = value.get("result_coverage") or {}
    return (value.get("error_code") == "BROWSER_RATE_LIMITED"
            or isinstance(coverage, dict) and any(coverage.get(key) == "BROWSER_RATE_LIMITED"
                                                 for key in ("error_code", "stop_reason")))


class _BatchInputs:
    """Reuse decoded JSON, never freshness, across one serial dispatch batch.

    Every row rereads and hashes current bytes. An evidence write, new triage
    or cancellation invalidates the decoded entry without relying on mtime.
    """
    def __init__(self, task_dir):
        self.task_dir = task_dir
        self.decoded = {}
        self.memo_state = {}
        self.reading_material = None

    def read(self, filename, default=None):
        path = self.task_dir / filename
        if not path.is_file():
            self.decoded.pop(filename, None)
            if default is not None:
                return default
            raise ValueError("BROWSER_INPUT_MISSING: " + filename)
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).digest()
        prior = self.decoded.get(filename)
        if prior is None or prior[0] != digest:
            self.decoded[filename] = digest, json.loads(payload)
        return self.decoded[filename][1]

    def disposition(self, provider, row):
        from decision_workflow import decision_snapshot
        from workflow_v24 import scenario_dispatch_block, scenario_fact_reuse, scenario_historical_reuse, scenario_reading_material, scenario_supplement
        from annotate_materiality import empty_materiality_ledger
        task, plan = self.read("task.json"), self.read("search-plan.json")
        self.reading_material = None
        cancelled = validated_query_cancellation(task, plan, row)
        if cancelled or not scenario_workflow_enabled(task):
            return cancelled, None, None
        evidence = self.read("evidence.json")
        candidates = self.read("normalized-candidates.json", {})
        ledger = self.read("materiality-annotations.json", empty_materiality_ledger(task["task_id"], task=task))
        if correction_enabled(task):
            supplement = scenario_supplement(self.task_dir, task=task, evidence=evidence,
                loader=lambda path: self.read(path.name))
        else:
            supplement_path = self.task_dir / "supplemental-evidence.json"
            supplement = self.read("supplemental-evidence.json") if supplement_path.is_file() else None
        with decision_snapshot(task, evidence, candidates, plan, ledger, supplement,
                               memo_state=self.memo_state if correction_enabled(task) else None):
            cancelled = scenario_dispatch_block(task, plan, provider, row, candidates, ledger, evidence, supplement=supplement)
            if cancelled:
                from workflow_v24 import TEMPORARY_DISPATCH_CODES
                if cancelled.get("reason") in TEMPORARY_DISPATCH_CODES:
                    self.reading_material = scenario_reading_material(task, plan, evidence, candidates, ledger, provider, row,
                        supplement=supplement, task_dir=self.task_dir)
                    if self.reading_material is not None:
                        return None, None, None
                return cancelled, None, None
            fact = scenario_fact_reuse(task, plan, evidence, candidates, ledger, provider, row,
                supplement=supplement, task_dir=self.task_dir)
            if fact is not None:
                return None, fact, None
            self.reading_material = scenario_reading_material(task, plan, evidence, candidates, ledger, provider, row,
                supplement=supplement, task_dir=self.task_dir)
            if self.reading_material is not None:
                return None, None, None
            historical = scenario_historical_reuse(task, provider, row, candidates, supplement)
            return None, None, historical


def recorder_command(provider: str, entry: dict, task_dir: Path, capture: Path) -> list[str]:
    if entry["operation"] == "candidate_verification":
        script = {"uspto_tsdr": "record_tsdr_browser_verification.py",
                  "uspto_patent_browser": "record_uspto_patent_chrome_verification.py"}.get(provider)
        extra = []
    elif provider == "uspto_tmsearch_browser":
        script, extra = "record_uspto_tmsearch_browser_result.py", []
    elif provider == "uspto_patent_browser":
        script, extra = "record_patent_browser_recall.py", ["--provider", provider]
    else:
        script, extra = None, []
    if not script:
        raise ValueError("AUTOMATION_NOT_VALIDATED: no automatic recorder for route")
    return [sys.executable, str(ROOT / "scripts" / script), "--task-dir", str(task_dir), "--capture", str(capture), *extra]


def run_process(command: list[str], timeout: int = 180) -> dict:
    try:
        # The CDP CLI calls the same Python authority before opening a source.
        # Inherit this verified interpreter, not an unrelated system python3
        # whose installed PDF/runtime dependencies may differ.
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False,
                                env={**os.environ, "LC_IPR_PYTHON": sys.executable})
    except subprocess.TimeoutExpired:
        return {"status": "access_limited", "error_code": "BROWSER_EXECUTION_TIMEOUT",
                "detail": "The automatic browser operation exceeded its bounded timeout."}
    try:
        payload = json.loads(result.stdout)
        if isinstance(payload, dict):
            if result.returncode and payload.get("status") in SUCCESS:
                return {"status": "access_limited", "error_code": "BROWSER_EXIT_STATUS_MISMATCH", "detail": "The command returned success but exited unsuccessfully."}
            return payload
    except (ValueError, TypeError):
        pass
    if result.returncode == 0:
        return {"status": "success", "recorded_status": result.stdout.strip()}
    detail = redact_sensitive_text(result.stderr or result.stdout)[:800] or "Browser command failed."
    contract_error = re.search(r"\b(CANDIDATE_PLAN_[A-Z_]+):", detail)
    if contract_error:
        return {"status": "failed", "error_code": contract_error.group(1),
                "phase": "validate_plan", "submission_state": "not_submitted", "detail": detail}
    guard_error = re.search(r"\b(SCENARIO_[A-Z_]+|DECISION_WORKFLOW_REVISION_UNSUPPORTED):", detail)
    if guard_error:
        # These are emitted by assertScenarioActionDispatch before the browser
        # route executes. Other subprocess failures remain submission unknown.
        return {"status": "failed", "error_code": guard_error.group(1),
                "phase": "validate_plan", "submission_state": "not_submitted", "detail": detail}
    return {"status": "access_limited", "error_code": "BROWSER_EXECUTION_FAILED",
            "detail": detail}


def request_params(entry: dict) -> dict:
    return {**{k: v for k, v in entry.items() if k not in PLAN_META_KEYS}, "right_type": entry.get("right_type", "")}


def record_failure(task_dir: Path, task: dict, provider: str, entry: dict, result: dict) -> str:
    params = request_params(entry)
    authorize_exact_plan_execution(task_dir, task, provider, entry["operation"], entry["query_id"],
                                   jurisdiction=entry["jurisdiction"], right_type=entry["right_type"],
                                   query=str(entry.get("q") or entry.get("query") or ""), request_params=params)
    status = result.get("status") if result.get("status") in {"needs_user_action", "failed"} else "access_limited"
    evidence_type = "official_verification" if entry["operation"] == "candidate_verification" else "trademark" if entry["right_type"].startswith("trademark") else "patent"
    recorded = record_error(task_dir, provider=provider, operation=entry["operation"],
                            query=str(entry.get("q") or entry.get("query") or ""), jurisdiction=entry["jurisdiction"],
                            evidence_type=evidence_type, query_id=entry["query_id"], request_params=params,
                            submission_state=str(result.get("submission_state") or "unknown"),
                            execution_phase=str(result.get("phase") or ""),
                            error_value=ProviderError(str(result.get("error_code") or "BROWSER_ACCESS_LIMITED"), status,
                                                      redact_sensitive_text(result.get("detail") or "Browser route could not be completed.")))
    return str(recorded.get("run_id") or "")


def partial_result(value: dict) -> bool:
    coverage = value.get("result_coverage") or {}
    return isinstance(coverage, dict) and (coverage.get("truncated") is True or coverage.get("completeness") in {"partial", "unknown"})


def completed_capture(task_dir: Path, task: dict, provider: str, entry: dict, previous: dict, *, allow_partial: bool = True) -> bool:
    """Historical name: validates evidence integrity, not retrieval completeness.

    A real positive in a partial result remains admissible recall evidence.
    The scheduler separately uses partial_result() to decide bounded resumption.
    """
    captured_status = previous.get("capture_status") or previous.get("status")
    if captured_status not in SUCCESS or previous.get("plan_entry_sha256") != canonical_digest(entry):
        return False
    try:
        capture_path = Path(previous["capture_path"]).resolve()
        if not path_within(capture_path, task_dir) or sha256_file(capture_path) != previous["capture_sha256"]:
            return False
        capture = load_json(capture_path)
        if capture.get("status") != captured_status or capture.get("query_id") != entry.get("query_id"):
            return False
        if recall_integrity_enabled(task) and partial_result(capture) and not allow_partial:
            return False
        for key in ("provider", "operation", "right_type", "task_id"):
            expected = provider if key == "provider" else task.get("task_id") if key == "task_id" else entry.get(key)
            if capture.get(key) is not None and capture.get(key) != expected:
                return False
        validate_browser_execution(capture, task, task_dir, provider)
        receipt = load_json(Path(capture["query_execution"]["path"]))
        if receipt.get("plan_entry_sha256") != canonical_digest(entry) or receipt.get("query_id") != entry.get("query_id"):
            return False
        evidence = load_json(task_dir / "evidence.json")
        if evidence.get("task_id") != task["task_id"] or evidence.get("schema_version") != task["schema_version"]:
            return False
        return any(run.get("query_id") == entry["query_id"] and run.get("provider") == provider
                   and run.get("status") == captured_status and run.get("plan_entry_sha256") == canonical_digest(entry)
                   for run in evidence.get("source_runs", []))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def execute_plan(task_dir: Path, wave: int = 0, *, query_id_filter: str = "",
                 query_ids_filter: list[str] | None = None, runner=run_process) -> dict[str, Any]:
    run_started = time.monotonic()
    if query_ids_filter is not None and (query_id_filter or not isinstance(query_ids_filter, (list, tuple))
            or not query_ids_filter or any(not isinstance(q, str) or not q for q in query_ids_filter)
            or len(query_ids_filter) != len(set(query_ids_filter))):
        raise ValueError("SEARCH_PLAN_INVALID: query-ids must be distinct exact browser rows; cannot mix query-id")
    selected_ids = set(query_ids_filter or ([query_id_filter] if query_id_filter else []))
    task_dir = task_dir.resolve()
    task = load_json(task_dir / "task.json")
    assert_active_free_policy(task)
    if task.get("schema_version") != "2.4-free":
        raise ValueError("LEGACY_TASK_READ_ONLY: browser plan scheduler only accepts 2.4-free")
    plan = load_json(task_dir / "search-plan.json")
    if plan.get("task_id") != task.get("task_id") or plan.get("schema_version") != task["schema_version"] or not plan_free_policy_matches_task(task, plan):
        raise ValueError("SEARCH_PLAN_IDENTITY_MISMATCH")
    evidence = load_json(task_dir / "evidence.json")
    if evidence.get("task_id") != task["task_id"] or evidence.get("schema_version") != task["schema_version"]:
        raise ValueError("BROWSER_EVIDENCE_TASK_MISMATCH")
    all_entries = [entry for entries in plan.get("queries", {}).values() for entry in entries]
    ids = [str(entry.get("query_id") or "") for entry in all_entries if isinstance(entry, dict)]
    if len(ids) != len(all_entries) or any(not q for q in ids) or len(set(ids)) != len(ids):
        raise ValueError("SEARCH_PLAN_INVALID: missing or duplicate query ids")
    browser_ids = {row.get("query_id") for provider, entries in plan.get("queries", {}).items()
                   if browser_provider(provider) for row in entries}
    if selected_ids and not selected_ids <= browser_ids:
        raise ValueError("SEARCH_PLAN_INVALID: query-id must select an exact browser row")
    if correction_enabled(task) and any(row.get("query_id") in selected_ids and row.get("execute_by_default") is False for row in all_entries):
        raise ValueError("SELECTED_QUERY_NOT_EXECUTABLE: exact selection cannot enable a disabled browser route")
    if scenario_workflow_enabled(task):
        reconcile_scenario_actions(task_dir, task, plan)
        atomic_write_json(task_dir / "search-plan.json", plan)
    status_path = task_dir / "browser-execution-status.json"
    previous = load_json(status_path) if status_path.exists() else {}
    if previous and previous.get("task_id") != task["task_id"]:
        raise ValueError("BROWSER_EXECUTION_TASK_MISMATCH")
    rows = {r["query_id"]: r for r in previous.get("queries", [])}
    prior_pauses = previous.get("provider_pauses")
    rate_wait = {p: value for p, value in (prior_pauses if isinstance(prior_pauses, dict) else {}).items()
                 if isinstance(value, dict) and value.get("error_code") == "BROWSER_RATE_LIMITED"
                 and isinstance(value.get("resume_after_epoch"), (float, int))
                 and not isinstance(value["resume_after_epoch"], bool)
                 and time.time() < value["resume_after_epoch"] <= time.time() + RATE_LIMIT_BACKOFF_SECONDS}
    report = {"schema_version": "1.0", "task_id": task["task_id"], "started_at": now_iso(),
              "queries": list(rows.values()), "provider_pauses": rate_wait, "required_user_actions": [], "status": "success"}
    node = shutil.which("node")
    config = load_skill_config()
    cdp_budget = min(165, max(1, float(config.get("cdp", {}).get("operation_timeout_ms", 165000)) / 1000))
    capability_cache, access_wait = {}, set()
    implementation_digest = browser_implementation_digest(task)
    static_errors = {"INTERNAL_ROUTE_CONTRACT_ERROR", "AUTOMATION_NOT_VALIDATED", "AUTOMATIC_QUERY_FIELD_UNSUPPORTED", "AUTOMATIC_QUERY_FILTER_UNSUPPORTED", "AUTOMATIC_QUERY_LANGUAGE_UNSUPPORTED", "BROWSER_QUERY_SEMANTICS_UNSUPPORTED", "UNSUPPORTED_QUERY_SEMANTICS", "CURRENT_STATUS_ROUTE_UNAVAILABLE"}
    batch = _BatchInputs(task_dir)
    batch_ids = set()
    report["selected_query_ids"] = sorted(selected_ids)
    report["initialization_elapsed_ms"] = round((time.monotonic() - run_started) * 1000)
    report["preflight_elapsed_ms"] = 0
    for provider, entries in plan.get("queries", {}).items():
        if not browser_provider(provider):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or wave and not (correction_enabled(task) and selected_ids) and entry.get("wave", 1) != wave or entry.get("execute_by_default") is False:
                continue
            query_id = str(entry.get("query_id") or "")
            if selected_ids and query_id not in selected_ids:
                continue
            batch_ids.add(query_id)
            preflight_started = time.monotonic()
            cancellation, reused_fact, historical = batch.disposition(provider, entry)
            preflight_ms = round((time.monotonic() - preflight_started) * 1000)
            report["preflight_elapsed_ms"] += preflight_ms
            if cancellation:
                temporary = correction_enabled(task) and cancellation.get("reason") in TEMPORARY_DISPATCH_CODES
                rows[query_id] = {"query_id": query_id, "provider": provider, "jurisdiction": entry["jurisdiction"],
                                  "right_type": entry["right_type"], "operation": entry["operation"],
                                  "plan_entry_sha256": canonical_digest(entry), "status": "awaiting_review" if temporary else "cancelled", "dispatch": "deferred" if temporary else "cancelled",
                                  "submission_state": "not_submitted", "reason": cancellation["reason"],
                                  "detail": cancellation["reason"], "finished_at": now_iso()}
                continue
            if batch.reading_material is not None:
                rows[query_id] = {"query_id": query_id, "provider": provider, "jurisdiction": entry["jurisdiction"],
                    "right_type": entry["right_type"], "operation": entry["operation"], "plan_entry_sha256": canonical_digest(entry),
                    "status": "awaiting_review", "dispatch": "agent_read_required", "submission_state": "not_submitted",
                    "source_query_performed": False, "reading_material": batch.reading_material, "finished_at": now_iso()}
                continue
            if reused_fact is not None:
                rows[query_id] = {"query_id": query_id, "provider": provider, "jurisdiction": entry["jurisdiction"],
                                  "right_type": entry["right_type"], "operation": entry["operation"],
                                  "plan_entry_sha256": canonical_digest(entry), "status": "fact_reused", "dispatch": "fact_reused",
                                  "submission_state": "not_submitted", "source_query_performed": False,
                                  "fact_reuse": reused_fact, "finished_at": now_iso()}
                continue
            if historical is not None:
                rows[query_id] = {"query_id": query_id, "provider": provider, "jurisdiction": entry["jurisdiction"],
                                  "right_type": entry["right_type"], "operation": entry["operation"],
                                  "plan_entry_sha256": canonical_digest(entry), "status": "success", "dispatch": "historical_reused",
                                  "submission_state": "not_submitted", "source_query_performed": False,
                                  "historical_reuse": historical, "finished_at": now_iso()}
                continue
            params = request_params(entry)
            authorize_exact_plan_execution(task_dir, task, provider, entry["operation"], query_id,
                                           jurisdiction=entry["jurisdiction"], right_type=entry["right_type"],
                                           query=str(entry.get("q") or entry.get("query") or ""), request_params=params)
            prior = rows.get(query_id, {})
            if provider in rate_wait:
                if completed_capture(task_dir, task, provider, entry, prior, allow_partial=False):
                    prior["resumed_without_query"] = True
                    continue
                # Do not spend the one partial-resume attempt on a request that
                # is deliberately not dispatched, or discard its real evidence.
                rows[query_id] = {**prior, "query_id": query_id, "provider": provider,
                                  "jurisdiction": entry["jurisdiction"], "right_type": entry["right_type"],
                                  "operation": entry["operation"], "plan_entry_sha256": canonical_digest(entry),
                                  "status": "incomplete" if prior.get("status") in SUCCESS | {"incomplete"} else "access_limited",
                                  "dispatch": "rate_limit_deferred", "phase": "await_source_retry",
                                  "submission_state": "not_submitted", "error_code": "BROWSER_RATE_LIMIT_COOLDOWN",
                                  "detail": "Provider requests paused after its Too Many Requests notice; no query or dialog dismissal attempted.",
                                  "resume_after_epoch": rate_wait[provider]["resume_after_epoch"], "finished_at": now_iso()}
                if prior.get("capture_status") in SUCCESS or prior.get("status") in SUCCESS:
                    rows[query_id]["capture_status"] = prior.get("capture_status") or prior["status"]
                continue
            partial_resumes = 0
            retained_partial = prior.get("retained_partial_capture")
            if (recall_integrity_enabled(task) and prior.get("partial_resume_attempts") == 1
                    and prior.get("implementation_sha256") == implementation_digest
                    and prior.get("status") not in SUCCESS | {"incomplete"}
                    and isinstance(retained_partial, dict)
                    and completed_capture(task_dir, task, provider, entry, retained_partial, allow_partial=True)):
                prior.update(dispatch="partial_deferred", resumed_without_query=True,
                             partial_stop_reason="The one automatic partial-result resume failed; original partial evidence is retained.")
                continue
            if completed_capture(task_dir, task, provider, entry, prior, allow_partial=True):
                captured = load_json(Path(prior["capture_path"]))
                if recall_integrity_enabled(task) and partial_result(captured):
                    prior["result_coverage"] = captured["result_coverage"]
                    attempts = prior.get("partial_resume_attempts", 0)
                    attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) and attempts >= 0 else 0
                    attempts = attempts if prior.get("implementation_sha256") == implementation_digest else 0
                    if attempts >= 1:
                        prior.update(status="incomplete", capture_status="success", dispatch="partial_deferred",
                                     resumed_without_query=True, error_code="BROWSER_PARTIAL_RESUME_LIMIT",
                                     detail="Partial result retained; one automatic resume was exhausted. " + str(prior.get("result_coverage", {}).get("stop_reason") or "coverage incomplete"))
                        continue
                    partial_resumes = attempts + 1
                    retained_partial = {key: prior[key] for key in ("status", "capture_status", "capture_path", "capture_sha256", "plan_entry_sha256", "result_coverage") if key in prior}
                else:
                    prior["resumed_without_query"] = True
                    continue
            if prior.get("error_code") in static_errors and prior.get("plan_entry_sha256") == canonical_digest(entry) and prior.get("implementation_sha256") == implementation_digest:
                prior["resumed_without_query"] = True
                prior["dispatch"] = "blocked_reused"
                continue
            tick = time.monotonic()
            row_deadline = tick + 180
            def remaining(limit):
                seconds = min(limit, row_deadline - time.monotonic())
                if seconds <= 0:
                    raise ValueError("OPERATION_DEADLINE_EXCEEDED")
                return seconds
            row = {"implementation_sha256": implementation_digest, "query_id": query_id, "provider": provider, "jurisdiction": entry["jurisdiction"],
                   "right_type": entry["right_type"], "operation": entry["operation"],
                   "plan_entry_sha256": canonical_digest(entry), "started_at": now_iso(), "preflight_elapsed_ms": preflight_ms}
            if recall_integrity_enabled(task):
                row["partial_resume_attempts"] = partial_resumes
                if partial_resumes:
                    row["retained_partial_capture"] = retained_partial
            try:
                route = (provider, entry["jurisdiction"], entry["right_type"], entry["operation"])
                if not node:
                    result = {"status": "access_limited", "error_code": "NODE_UNAVAILABLE", "phase": "validate_runtime", "submission_state": "not_submitted", "detail": "Node.js is unavailable."}
                elif provider in access_wait:
                    result = {"status": "needs_user_action", "error_code": "BROWSER_ACCESS_VERIFICATION_PENDING", "phase": "await_access", "submission_state": "not_submitted", "detail": "Complete only login, CAPTCHA, or QR verification on the existing page; the agent then reruns this wave."}
                else:
                    if route not in capability_cache:
                        capability_cache[route] = runner([node, str(CDP), "automation-capability", "--provider", provider,
                                                         "--jurisdiction", entry["jurisdiction"], "--right-type", entry["right_type"], "--operation", entry["operation"]], remaining(20))
                    capability = capability_cache[route]
                    if capability.get("executor_available") is not True:
                        result = {"status": "failed" if capability.get("error_code") == "INTERNAL_ROUTE_CONTRACT_ERROR" else "access_limited", "error_code": capability.get("error_code", "AUTOMATION_NOT_VALIDATED"),
                                  "phase": "validate_route", "submission_state": "not_submitted",
                                  "detail": capability.get("detail", "No automatic browser executor has been accepted for this route."), "browser_capability": capability}
                    else:
                        recovery = record_action_recovery(task_dir, provider, entry, implementation_sha256=implementation_digest)
                        if recovery:
                            row["recovery_id"] = recovery["recovery_id"]
                        result = runner([node, str(CDP), "run-planned-query", "--task-dir", str(task_dir), "--query-id", query_id, "--acceptance-probe", "--deadline-epoch-ms", str(round((time.time() + min(cdp_budget, remaining(180) - 10)) * 1000))], remaining(180))
                status = str(result.get("status") or "access_limited")
                if correction_enabled(task):
                    row["submission_state"] = result.get("submission_state") or "unknown"
                    row["phase"] = result.get("phase") or ""
                if status == "needs_user_action":
                    access_wait.add(provider)
                capture_file = result.get("capture_path")
                if capture_file:
                    capture_path = Path(str(capture_file)).resolve()
                    if not capture_path.is_file() or not path_within(capture_path, task_dir):
                        raise ValueError("Browser capture is outside this task or missing")
                    capture = load_json(capture_path)
                    if capture.get("status") != status:
                        raise ValueError("Browser result status does not match the capture")
                    validate_browser_execution(capture, task, task_dir, provider)
                    # Receipt-validated capture is authoritative when CLI summaries omit details.
                    result = {**result, **{key: capture[key] for key in ("error_code", "detail", "phase", "submission_state") if capture.get(key)}}
                    recorded = runner(recorder_command(provider, entry, task_dir, capture_path), remaining(60))
                    if recorded.get("status") != "success" or recorded.get("recorded_status") not in (None, "", status):
                        raise ValueError("Browser recorder rejected the capture: " + str(recorded.get("detail", "validation failure")))
                    row.update(capture_path=str(capture_path), capture_sha256=sha256_file(capture_path),
                               query_execution=capture.get("query_execution"), result_coverage=capture.get("result_coverage", {}),
                               media_coverage=capture.get("media_coverage", {}), browser_capability=capture.get("browser_capability", {}))
                elif status in SUCCESS:
                    raise ValueError("Browser completion lacks a plan-bound capture")
                else:
                    row["source_run_id"] = record_failure(task_dir, task, provider, entry, result)
                row.update(status=status, phase=result.get("phase", ""), submission_state=result.get("submission_state", ""), error_code=str(result.get("error_code") or ""),
                           detail=redact_sensitive_text(result.get("detail") or "")[:800])
                if _rate_limited(row):
                    rate_wait[provider] = {"error_code": "BROWSER_RATE_LIMITED", "query_id": query_id,
                                           "observed_at": now_iso(), "resume_after_epoch": time.time() + RATE_LIMIT_BACKOFF_SECONDS}
                if recall_integrity_enabled(task) and status == "success" and (partial_result(row) or _rate_limited(row)):
                    row.update(status="incomplete", capture_status="success", error_code="BROWSER_RESULT_PARTIAL",
                               detail="Validated partial results retained; retrieval is incomplete: " + str(row["result_coverage"].get("stop_reason") or "coverage incomplete"))
            except (OSError, ValueError, TypeError, KeyError, ProviderError) as exc:
                row.update(status="access_limited", error_code="BROWSER_ROW_FAILED", detail=redact_sensitive_text(exc)[:800])
                try:
                    row["source_run_id"] = record_failure(task_dir, task, provider, entry, row)
                except (OSError, ValueError, TypeError, KeyError, ProviderError) as record_exc:
                    row["record_error"] = redact_sensitive_text(record_exc)[:400]
            row["finished_at"] = now_iso()
            row["elapsed_ms"] = round((time.monotonic() - tick) * 1000)
            row["dispatch"] = "executed"
            with (task_dir / "browser-attempts.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"task_id": task["task_id"], **row}, ensure_ascii=False) + "\n")
            rows[query_id] = row
            report.update(queries=list(rows.values()), updated_at=now_iso())
            atomic_write_json(status_path, report)
    status_rows = [rows[q] for q in batch_ids if q in rows] if correction_enabled(task) else list(rows.values())
    access_wait = {str(r["provider"]) for r in status_rows if r.get("status") == "needs_user_action"}
    report["required_user_actions"] = [{"provider": p, "actions": USER_ACTIONS, "business_actions_by": "agent"} for p in sorted(access_wait)]
    report["status"] = ("needs_user_action" if access_wait else "failed" if any(r.get("status") == "failed" for r in status_rows)
                        else "access_limited" if any(r.get("status") not in SUCCESS | {"cancelled", "incomplete", "fact_reused", "awaiting_review"} for r in status_rows)
                        else "incomplete" if any(r.get("status") in {"cancelled", "incomplete", "awaiting_review"} for r in status_rows) else "success")
    if correction_enabled(task):
        from workflow_v24 import work_view_from_dir
        report["batch_status"] = report["status"]
        report["batch_query_ids"] = sorted(batch_ids)
        report["work_view"] = work_view_from_dir(task_dir, browser_status={"queries": list(rows.values())})
        report["work_status"] = report["work_view"]["status"]
    report["finished_at"] = now_iso()
    report["dispatcher_elapsed_ms"] = round((time.monotonic() - run_started) * 1000)
    report["queries"] = list(rows.values())
    atomic_write_json(status_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True, type=Path)
    parser.add_argument("--wave", type=int, choices=(1, 2), default=0, help="Default: both waves")
    selected = parser.add_mutually_exclusive_group()
    selected.add_argument("--query-id", default="", help="Execute one exact generated browser row, preserving normal recording and locking")
    selected.add_argument("--query-ids", nargs="+", help="Execute these exact IDs serially in plan order, with one batch initialization")
    args = parser.parse_args()
    try:
        with execution_lock(args.task_dir, "browser"):
            report = execute_plan(args.task_dir, args.wave, query_id_filter=args.query_id, query_ids_filter=args.query_ids)
        print(json.dumps({"status": report["status"], "status_path": str(args.task_dir.resolve() / "browser-execution-status.json"),
                          "query_count": len(report["queries"]), "required_user_actions": report["required_user_actions"]}, ensure_ascii=False))
    except (OSError, ValueError, ProviderError) as exc:
        print(json.dumps({"status": "access_limited", "error_code": "BROWSER_PLAN_FAILED", "detail": redact_sensitive_text(exc)[:800]}, ensure_ascii=False))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()

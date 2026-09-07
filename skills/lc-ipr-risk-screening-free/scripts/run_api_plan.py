#!/usr/bin/env python3
"""Execute official/free API search-plan entries with resumability and hard cost gates."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from common import (
    AUTHORIZED_FREE_COMMERCIAL_PROVIDERS, COMMERCIAL_PROVIDERS, SERPAPI_PROVIDER,
    SERPER_PROVIDERS, SIGNA_PROVIDER, WIPO_PROVIDERS,
    assert_default_discovery_plan_contract, assert_provider_execution_allowed,
    authorize_serpapi_free_plan_entry,
    authorize_serper_free_plan_entry, authorize_signa_free_plan_entry,
    credential, ensure_object, is_active_schema, load_json, load_skill_config,
    plan_free_policy_matches_task, serpapi_free_enabled, serper_free_enabled,
    signa_free_enabled, task_free_policy_valid,
)
from epo_quota_ledger import EpoQuotaLedger
from jpo_api_client import persisted_quota_block_reason, required_endpoint_pools
from provider_utils import (
    ProviderError, record_error, redact_sensitive_text, sanitize_for_evidence,
)


API_PROVIDERS = {
    "epo_ops", "euipo_trademark", "euipo_design", "jpo_api",
    SERPAPI_PROVIDER, SIGNA_PROVIDER, *SERPER_PROVIDERS,
}
KNOWN_NOT_READY = {"inpi_api", "prv_open_data"}
TERMINAL = {"success", "no_result", "not_applicable"}
SOURCE_STATUSES = TERMINAL | {"needs_user_action", "access_limited", "failed"}
EXPOSED_OUTPUT_LIMIT = 500


def bounded_redacted_output(value: Any, limit: int = EXPOSED_OUTPUT_LIMIT) -> str:
    """Redact a complete stream before retaining only its bounded diagnostic tail."""
    safe = redact_sensitive_text(value).strip()
    if limit <= 0:
        return ""
    if len(safe) <= limit:
        return safe
    marker = "[truncated]\n"
    if limit <= len(marker):
        return marker[:limit]
    return marker + safe[-(limit - len(marker)):]


def flag(command: list[str], name: str, value: Any) -> None:
    if value not in (None, "", []):
        command.extend([name, str(value)])


def command_for(
    scripts: Path, task_dir: Path, provider: str, item: dict[str, Any],
) -> list[str]:
    q = str(item.get("q") or item.get("query") or "")
    new_clients = {"inpi_api": "inpi_client.py", "epo_publication_server": "eps_client.py", "serpapi_google_lens": "serpapi_lens_client.py"}
    if provider in new_clients:
        return [sys.executable, str(scripts / new_clients[provider]), "--task-dir", str(task_dir), "--query-id", str(item.get("query_id") or "")]
    if provider in SERPER_PROVIDERS:
        return [
            sys.executable, str(scripts / "serper_client.py"),
            "--task-dir", str(task_dir),
            "--query-id", str(item.get("query_id") or ""),
        ]
    if provider == SERPAPI_PROVIDER:
        return [
            sys.executable, str(scripts / "serpapi_patents_client.py"),
            "--task-dir", str(task_dir),
            "--query-id", str(item.get("query_id") or ""),
        ]
    if provider == SIGNA_PROVIDER:
        return [
            sys.executable, str(scripts / "signa_client.py"),
            "--task-dir", str(task_dir),
            "--query-id", str(item.get("query_id") or ""),
        ]
    if provider == "epo_ops":
        planned_operation = str(item.get("operation") or "search")
        detail_operation = str(item.get("detail_operation") or "")
        if planned_operation == "candidate_detail":
            if detail_operation not in {"biblio", "family", "legal"}:
                raise ValueError(f"Unsupported EPO candidate detail operation: {detail_operation!r}")
            if not q or not str(item.get("candidate_id") or "").strip():
                raise ValueError("EPO candidate detail requires a document and candidate_id")
        elif planned_operation != "search":
            raise ValueError(f"Unsupported EPO planned operation: {planned_operation!r}")
        command = [
            sys.executable, str(scripts / "epo_ops_client.py"),
            "--task-dir", str(task_dir), "--operation",
            detail_operation if planned_operation == "candidate_detail" else "search",
            "--query", q,
        ]
        flag(command, "--jurisdiction", item.get("jurisdiction"))
        flag(command, "--right-type", item.get("right_type"))
        flag(command, "--query-id", item.get("query_id"))
        if planned_operation == "search":
            flag(command, "--range", item.get("range"))
        else:
            flag(command, "--candidate-id", item.get("candidate_id"))
        return command
    if provider in {"euipo_trademark", "euipo_design"}:
        product = "trademark" if provider.endswith("trademark") else "design"
        command = [
            sys.executable, str(scripts / "euipo_client.py"), product,
            "--task-dir", str(task_dir), "--query", q,
        ]
        flag(command, "--page", item.get("page"))
        flag(command, "--size", item.get("size"))
        flag(command, "--right-type", item.get("right_type"))
        flag(command, "--rsql", item.get("query"))
        flag(command, "--query-id", item.get("query_id"))
        if item.get("operation") == "candidate_verification":
            command.append("--verify")
            flag(command, "--identifier", item.get("identifier") or item.get("application_number") or q)
            flag(command, "--candidate-id", item.get("candidate_id"))
        return command
    if provider == "jpo_api":
        if item.get("operation") != "candidate_verification":
            raise ValueError("JPO API is identifier-detail-only and cannot execute discovery queries")
        case_number = str(
            item.get("number") or item.get("application_number")
            or item.get("identifier") or q
        ).strip()
        command = [
            sys.executable, str(scripts / "jpo_api_client.py"),
            "--task-dir", str(task_dir),
            "--right-type", str(item.get("right_type") or ""),
            "--number", case_number,
            "--number-kind", str(item.get("number_kind") or "application"),
        ]
        flag(command, "--candidate-id", item.get("candidate_id"))
        flag(command, "--query-id", item.get("query_id"))
        if item.get("required_for") == "formal":
            command.append("--mandatory")
        return command
    raise ValueError(f"Unsupported official/free API provider: {provider}")


def numeric_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value or "").replace(",", ""))
    return int(match.group()) if match else None


def epo_free_quota_block_reason(
    task_dir: Path, evidence: dict[str, Any], config: dict[str, Any], pending_count: int,
) -> str:
    del pending_count  # Reservations are per actual request, not per planned batch.
    cfg = config.get("providers", {}).get("epo_ops", {})
    if cfg.get("allow_overage") is not False or config.get("free_policy", {}).get("allow_overage") is not False:
        return "EPO_OVERAGE_POLICY_INVALID"
    free_limit = int(cfg.get("documented_free_bytes_per_week", 0))
    margin = int(cfg.get("free_stop_margin_bytes", 0))
    estimate = int(cfg.get("estimated_max_response_bytes_per_query", 0))
    if free_limit <= 0 or estimate <= 0:
        return "EPO_FREE_QUOTA_CONFIGURATION_MISSING"

    consumer_key = credential(config, "epo_consumer_key")
    if consumer_key:
        try:
            shared = EpoQuotaLedger(config, consumer_key).snapshot()
        except ProviderError as exc:
            return exc.code
        if shared.get("stop_required") is True:
            return str(shared.get("stop_code") or "EPO_SHARED_FREE_QUOTA_STOP")
        shared_effective = (
            int(shared.get("registered_used_bytes") or 0)
            + int(shared.get("unconfirmed_consumed_bytes") or 0)
            + sum(
                int(item.get("bytes") or 0)
                for item in (shared.get("reservations") or {}).values()
                if isinstance(item, dict)
            )
        )
        if shared_effective + int(shared.get("reservation_bytes") or estimate) >= int(shared.get("stop_at_bytes") or 0):
            return "EPO_SHARED_FREE_QUOTA_NEAR_LIMIT"

    observed_bytes = 0
    for run in evidence.get("source_runs", []):
        if run.get("provider") != "epo_ops":
            continue
        if str(run.get("error_code") or "") in {
            "FREE_QUOTA_EXHAUSTED", "FREE_QUOTA_STOP_THRESHOLD",
            "PAID_QUOTA_USAGE_DETECTED", "PAID_PLAN_REQUIRED",
        }:
            return "EPO_RECORDED_FREE_QUOTA_STOP"
        for raw in run.get("raw_paths", []):
            path = Path(str(raw))
            if path.is_file():
                observed_bytes += path.stat().st_size
        for key, value in (run.get("quota") or {}).items():
            lowered = str(key).casefold()
            number = numeric_value(value)
            if number is None:
                continue
            if "remaining" in lowered and ("byte" in lowered or "week" in lowered):
                if number <= margin + estimate:
                    return "EPO_REPORTED_FREE_QUOTA_NEAR_LIMIT"
            if "used" in lowered and ("byte" in lowered or "week" in lowered):
                if number + margin + estimate >= free_limit:
                    return "EPO_REPORTED_FREE_QUOTA_NEAR_LIMIT"
    if observed_bytes + margin + estimate >= free_limit:
        return "EPO_TASK_FREE_QUOTA_NEAR_LIMIT"
    return ""


def record_blocked(
    task_dir: Path, provider: str, item: dict[str, Any], code: str, detail: str,
    *, fatal: bool = True,
) -> dict[str, Any]:
    query = str(item.get("q") or item.get("query") or "")
    right_type = str(item.get("right_type") or "")
    evidence_type = (
        "official_verification" if item.get("operation") == "candidate_verification" else
        "trademark" if right_type in {"trademark_word", "trademark_figurative"} else
        "copyright" if right_type == "copyright" else
        "enforcement" if right_type == "enforcement" else
        "patent"
    )
    run = record_error(
        task_dir,
        provider=provider,
        operation=str(item.get("operation") or "search"),
        query=query,
        jurisdiction=str(item.get("jurisdiction") or ""),
        evidence_type=evidence_type,
        error_value=ProviderError(code, "access_limited", detail),
        mandatory=False,
        request_params={
            **{
                key: value for key, value in item.items()
                if key not in {
                "query_id", "operation", "jurisdiction", "right_type", "required",
                "required_for", "requirement_ids", "wave", "derived_from",
                "execute_by_default", "execute_when", "fallback_provider",
                "requirement_id", "role", "authoritative_for_final_rating",
                }
            },
            "right_type": str(item.get("right_type") or ""),
        },
        query_id=str(item.get("query_id") or ""),
    )
    return {
        "provider": bounded_redacted_output(provider),
        "query_id": bounded_redacted_output(item.get("query_id")),
        "q": bounded_redacted_output(query),
        "returncode": 2 if fatal else 0,
        "status": run["status"],
        "error_code": bounded_redacted_output(code),
        "fallback_required": not fatal,
        "stderr": bounded_redacted_output(detail),
    }


def command_status(stdout: str) -> str:
    safe_stdout = redact_sensitive_text(stdout)
    line = safe_stdout.strip().splitlines()[-1] if safe_stdout.strip() else ""
    if not line:
        return "failed"
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return line if line in SOURCE_STATUSES else "failed"
    status = str(payload.get("status") or "") if isinstance(payload, dict) else ""
    return status if status in SOURCE_STATUSES else "failed"


def command_payload(stdout: str) -> dict[str, Any]:
    safe_stdout = redact_sensitive_text(stdout)
    line = safe_stdout.strip().splitlines()[-1] if safe_stdout.strip() else ""
    if not line:
        return {}
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return {}
    sanitized = sanitize_for_evidence(payload) if isinstance(payload, dict) else {}
    return sanitized if isinstance(sanitized, dict) else {}


def completed_result(provider: str, item: dict[str, Any], result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    payload = command_payload(result.stdout)
    return {
        "provider": bounded_redacted_output(provider),
        "query_id": bounded_redacted_output(item.get("query_id")),
        "q": bounded_redacted_output(item.get("q") or item.get("query")),
        "returncode": result.returncode,
        "status": command_status(result.stdout),
        "error_code": bounded_redacted_output(payload.get("error_code")),
        "fallback_provider": bounded_redacted_output(payload.get("fallback_provider")),
        "stderr": bounded_redacted_output(result.stderr),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run official/free API entries from search-plan.json.")
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--wave", choices=("1", "2", "all"), default="1")
    parser.add_argument("--include-optional", action="store_true")
    parser.add_argument("--max-workers", type=int, default=0)
    parser.add_argument("--query-ids", nargs="+", help="Execute exact API IDs as one resumable batch (2.4 only)")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    if load_json(task_dir / "task.json").get("schema_version") == "2.4-free":
        from runtime_v24 import execute_api_plan
        result = execute_api_plan(task_dir, wave=args.wave, include_optional=args.include_optional, max_workers=args.max_workers, query_ids_filter=args.query_ids)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("status") != "success":
            raise SystemExit(2)
        return
    if args.query_ids is not None:
        raise SystemExit("Exact API batches require a 2.4 task")
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    if not is_active_schema(task):
        raise SystemExit("LEGACY_TASK_READ_ONLY: API execution is disabled for 2.1/2.2 tasks")
    if plan.get("schema_version") != task.get("schema_version") or plan.get("task_id") != task.get("task_id"):
        raise SystemExit("Search-plan identity/schema does not match task")
    if not task_free_policy_valid(task) or not plan_free_policy_matches_task(task, plan):
        raise SystemExit("FREE_POLICY_INVALID: task and plan must use the same immutable recognized free policy")
    try:
        assert_default_discovery_plan_contract(task, plan)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    query_providers = set(plan.get("queries", {}))
    forbidden_wipo = sorted(query_providers & WIPO_PROVIDERS)
    if forbidden_wipo:
        raise SystemExit("WIPO_PROVIDER_DISABLED: " + ", ".join(forbidden_wipo))
    forbidden_commercial = sorted(
        (query_providers & COMMERCIAL_PROVIDERS) - AUTHORIZED_FREE_COMMERCIAL_PROVIDERS
    )
    if forbidden_commercial:
        raise SystemExit("COMMERCIAL_PROVIDER_DISABLED: " + ", ".join(forbidden_commercial))

    completed = {
        str(run.get("query_id")) for run in evidence.get("source_runs", [])
        if run.get("status") in TERMINAL and run.get("query_id")
    }
    pending: list[tuple[str, dict[str, Any]]] = []
    results: list[dict[str, Any]] = []
    for provider, entries in plan.get("queries", {}).items():
        entries = entries if isinstance(entries, list) else []
        for item in entries:
            if not isinstance(item, dict):
                continue
            try:
                if provider in SERPER_PROVIDERS:
                    authorize_serper_free_plan_entry(
                        task, plan, provider,
                        str(item.get("operation") or ""),
                        str(item.get("query_id") or ""),
                    )
                elif provider == SERPAPI_PROVIDER:
                    authorize_serpapi_free_plan_entry(
                        task, plan, str(item.get("operation") or ""),
                        str(item.get("query_id") or ""),
                    )
                elif provider == SIGNA_PROVIDER:
                    authorize_signa_free_plan_entry(
                        task, plan, str(item.get("query_id") or ""),
                    )
                assert_provider_execution_allowed(
                    task,
                    provider,
                    str(item.get("operation") or "search"),
                    jurisdiction=str(item.get("jurisdiction") or ""),
                    right_type=str(item.get("right_type") or ""),
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
        if provider in KNOWN_NOT_READY:
            for item in entries:
                if isinstance(item, dict) and item.get("query_id") not in completed:
                    results.append(record_blocked(
                        task_dir, provider, item, "ADAPTER_SETUP_REQUIRED",
                        f"{provider} is declared as a free fallback route but has not passed its smoke test",
                        fatal=False,
                    ))
            continue
        if provider not in API_PROVIDERS:
            continue
        for item in entries:
            if not isinstance(item, dict) or item.get("query_id") in completed:
                continue
            if (
                not item.get("required", True)
                and not item.get("execute_by_default", False)
                and not args.include_optional
            ):
                continue
            if args.wave != "all" and int(item.get("wave", 1)) != int(args.wave):
                continue
            pending.append((provider, item))

    config = load_skill_config()
    scripts = Path(__file__).resolve().parent
    maximum = int(config.get("performance", {}).get("max_api_concurrency", 3))
    serial_providers = {
        "epo_ops", "jpo_api", SERPAPI_PROVIDER, SIGNA_PROVIDER, *SERPER_PROVIDERS,
    }
    parallel_pending = [entry for entry in pending if entry[0] not in serial_providers]
    epo_pending = [entry for entry in pending if entry[0] == "epo_ops"]
    jpo_pending = [entry for entry in pending if entry[0] == "jpo_api"]
    serper_pending = [entry for entry in pending if entry[0] in SERPER_PROVIDERS]
    signa_pending = [entry for entry in pending if entry[0] == SIGNA_PROVIDER]
    serpapi_pending = [entry for entry in pending if entry[0] == SERPAPI_PROVIDER]
    workers = max(1, min(args.max_workers or maximum, maximum, len(parallel_pending) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                subprocess.run,
                command_for(scripts, task_dir, provider, item),
                capture_output=True, text=True, check=False,
            ): (provider, item)
            for provider, item in parallel_pending
        }
        for future in as_completed(futures):
            provider, item = futures[future]
            results.append(completed_result(provider, item, future.result()))

    # Keep one OPS subprocess at a time within this task.  The client also uses
    # an account-scoped file lock and shared ledger, so a sibling task/process
    # cannot reserve the same remaining free allowance.
    for index, (provider, item) in enumerate(epo_pending):
        current_evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
        quota_reason = epo_free_quota_block_reason(
            task_dir, current_evidence, config, len(epo_pending) - index,
        )
        if quota_reason:
            for blocked_provider, blocked_item in epo_pending[index:]:
                results.append(record_blocked(
                    task_dir, blocked_provider, blocked_item, "FREE_QUOTA_EXHAUSTED",
                    f"{quota_reason}; EPO subprocess was stopped before network execution and paid overage is disabled",
                ))
            break
        result = subprocess.run(
            command_for(scripts, task_dir, provider, item),
            capture_output=True, text=True, check=False,
        )
        results.append(completed_result(provider, item, result))

    # JPO limits are endpoint-scoped and daily.  Run these commands one at a time,
    # re-reading evidence before every subprocess so a prior remaining=0 result is
    # a hard pre-network stop for all later candidates.
    jpo_limits = config.get("providers", {}).get("jpo_api", {}).get("daily_limits", {})
    for provider, item in jpo_pending:
        number_kind = str(item.get("number_kind") or "application")
        quota_reason = persisted_quota_block_reason(
            task_dir, required_endpoint_pools(number_kind), jpo_limits,
        )
        if quota_reason:
            results.append(record_blocked(
                task_dir, provider, item, "FREE_QUOTA_EXHAUSTED",
                f"{quota_reason}; JPO subprocess was stopped before authentication or retrieval",
            ))
            continue
        result = subprocess.run(
            command_for(scripts, task_dir, provider, item),
            capture_output=True, text=True, check=False,
        )
        results.append(completed_result(provider, item, result))

    # Selected Serper discovery is task-bound,
    # has a single shared budget across its three endpoints, and is serialized
    # so each subprocess can re-read the latest recorded balance before making
    # at most one HTTP request.
    for provider, item in serper_pending:
        result = subprocess.run(
            command_for(scripts, task_dir, provider, item),
            capture_output=True, text=True, check=False,
        )
        results.append(completed_result(provider, item, result))

    # Selected Signa discovery is serialized so each request can
    # re-check account/usage/credit guards and persist a task-wide stop signal.
    for provider, item in signa_pending:
        result = subprocess.run(
            command_for(scripts, task_dir, provider, item),
            capture_output=True, text=True, check=False,
        )
        results.append(completed_result(provider, item, result))

    # SerpApi is a Google Patents resilience lane.  When its plan row is bound
    # to a Serper row, avoid spending a second free search after that exact
    # Serper request completed normally.  Access/quota/provider failures do
    # trigger the fallback.
    for provider, item in serpapi_pending:
        fallback_query_id = str(item.get("fallback_query_id") or "")
        if fallback_query_id:
            current_evidence = ensure_object(
                load_json(task_dir / "evidence.json"), "evidence.json",
            )
            fallback_complete = any(
                run.get("provider") == "serper_patents"
                and str(run.get("query_id") or "") == fallback_query_id
                and run.get("status") in TERMINAL
                for run in current_evidence.get("source_runs", [])
                if isinstance(run, dict)
            )
            if fallback_complete:
                results.append({
                    "provider": provider,
                    "query_id": str(item.get("query_id") or ""),
                    "q": str(item.get("q") or ""),
                    "returncode": 0,
                    "status": "not_applicable",
                    "error_code": "",
                    "fallback_provider": "serper_patents",
                    "stderr": "",
                })
                continue
        result = subprocess.run(
            command_for(scripts, task_dir, provider, item),
            capture_output=True, text=True, check=False,
        )
        results.append(completed_result(provider, item, result))
    print(json.dumps({
        "workers": workers,
        "scheduled": len(pending),
        "free_only": True,
        "paid_execution_enabled": False,
        "serper_free_enhancement_enabled": serper_free_enabled(task),
        "signa_free_enhancement_enabled": signa_free_enabled(task),
        "serpapi_free_enhancement_enabled": serpapi_free_enabled(task),
        "results": results,
    }, ensure_ascii=False, indent=2))
    if any(item["returncode"] != 0 for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Strictly validate evidence coverage, report freshness and secret boundaries."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any

from common import (
    ENV_CREDENTIALS, SOURCE_STATUSES, SUPPORTED_SCHEMA_VERSIONS, ensure_object, load_json,
    load_skill_config, path_within, sha256_file, sha256_json,
)


FORBIDDEN_BROWSER_FIELDS = {
    "cdp_endpoint", "endpoint", "websocket", "websocket_url",
    "remote_debugging_port", "profile_dir", "user_data_dir",
    "cookies", "local_storage", "localstorage",
}


def forbidden_browser_paths(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).casefold() in FORBIDDEN_BROWSER_FIELDS:
                found.append(path)
            found.extend(forbidden_browser_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(forbidden_browser_paths(item, f"{prefix}[{index}]"))
    return found
from finalize_assessment import (
    low_risk_gate_gaps, material_unverified, required_query_gaps, source_gaps,
)


def configured_secrets(config: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in config.get("credentials", {}).values() if isinstance(config.get("credentials"), dict) else []:
        if isinstance(value, str) and len(value) >= 8:
            values.append(value)
    for key in ("backend_token", "euipo_client_secret"):
        value = config.get(key)
        if isinstance(value, str) and len(value) >= 8:
            values.append(value)
    for env_name in ENV_CREDENTIALS.values():
        value = os.environ.get(env_name, "")
        if len(value) >= 8:
            values.append(value)
    return list(dict.fromkeys(values))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate one IPR task directory.")
    parser.add_argument("--task-dir", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    errors: list[str] = []
    required_files = [
        "task.json", "evidence.json", "assessment.json", "search-plan.json",
        "normalized-candidates.json", "report.md", "report.html", "report-manifest.json",
    ]
    for name in required_files:
        if not (task_dir / name).is_file():
            errors.append(f"Missing {name}")
    if errors:
        raise SystemExit("validation failed:\n- " + "\n- ".join(errors))

    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    assessment = ensure_object(load_json(task_dir / "assessment.json"), "assessment.json")
    plan = ensure_object(load_json(task_dir / "search-plan.json"), "search-plan.json")
    candidates = ensure_object(load_json(task_dir / "normalized-candidates.json"), "normalized-candidates.json")
    manifest = ensure_object(load_json(task_dir / "report-manifest.json"), "report-manifest.json")
    journal_path = task_dir / "browser-candidate-journal.json"
    journal = ensure_object(load_json(journal_path), "browser-candidate-journal.json") if journal_path.exists() else {
        "schema_version": "1.0", "task_id": task.get("task_id"), "entries": [],
    }

    task_schema = str(task.get("schema_version") or "")
    if task_schema not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(f"Unsupported task schema version: {task_schema}")
    for label, payload in (("task", task), ("evidence", evidence), ("assessment", assessment), ("plan", plan), ("candidates", candidates)):
        if payload.get("schema_version") != task_schema:
            errors.append(f"{label} schema version mismatch")
        if payload.get("task_id") != task.get("task_id"):
            errors.append(f"{label} task_id mismatch")

    expected_state = {"completed": "completed", "incomplete": "incomplete", "needs_review": "needs_review"}.get(str(assessment.get("status")))
    if expected_state and task.get("state") != expected_state:
        errors.append(f"Task state {task.get('state')} does not match assessment status {assessment.get('status')}")

    if len(task.get("images", [])) != 1:
        errors.append("Exactly one main image is required")
    else:
        image = task["images"][0]
        path = Path(str(image.get("path", ""))).resolve()
        if not path.is_file() or not path_within(path, task_dir / "images") or sha256_file(path) != image.get("sha256"):
            errors.append("Main image path/hash validation failed")

    if journal.get("schema_version") != "1.0" or journal.get("task_id") != task.get("task_id"):
        errors.append("Browser candidate journal identity/schema mismatch")
    journal_entries = journal.get("entries", [])
    if not isinstance(journal_entries, list):
        errors.append("Browser candidate journal entries must be an array")
        journal_entries = []
    unresolved_journal: list[str] = []
    verified_patent_ids = {
        re.sub(r"[^A-Za-z0-9]", "", str(item.get(key) or "")).upper()
        for item in candidates.get("patents", [])
        if item.get("official_verification", {}).get("status") == "verified"
        for key in ("publication_number", "grant_number", "application_number", "record_number")
        if item.get(key)
    }
    for entry in journal_entries:
        if not isinstance(entry, dict):
            errors.append("Browser candidate journal entry must be an object")
            continue
        record = re.sub(r"[^A-Za-z0-9]", "", str(entry.get("record_number") or "")).upper()
        status = str(entry.get("status") or "")
        if not record or not entry.get("provider"):
            errors.append("Browser candidate journal entry is missing provider/record_number")
        if status not in {"pending", "success", "no_result", "needs_user_action", "access_limited", "failed"}:
            errors.append(f"Invalid browser candidate journal status: {status}")
        if status == "success" and record not in verified_patent_ids:
            errors.append(f"Successful viewed candidate was not ingested as officially verified: {record}")
        if status in {"pending", "needs_user_action", "access_limited", "failed"}:
            unresolved_journal.append(record or "unknown")
        for key in ("screenshot_path", "capture_path"):
            raw_path = entry.get(key)
            if not raw_path:
                continue
            path = Path(str(raw_path)).resolve()
            expected_root = task_dir / ("screenshots" if key == "screenshot_path" else "")
            if not path.is_file() or not path_within(path, expected_root):
                errors.append(f"Browser candidate journal {key} is missing or outside task: {raw_path}")

    run_ids: set[str] = set()
    for run in evidence.get("source_runs", []):
        run_id = str(run.get("run_id") or "")
        if not run_id or run_id in run_ids:
            errors.append(f"Missing or duplicate run_id: {run_id}")
        run_ids.add(run_id)
        if not run.get("query_id"):
            errors.append(f"Source run has no query_id: {run_id}")
        if run.get("status") not in SOURCE_STATUSES:
            errors.append(f"Invalid source status: {run.get('status')}")
        if run.get("status") == "no_result" and run.get("error_code"):
            errors.append(f"no_result run has error code: {run_id}")
        for raw in run.get("raw_paths", []):
            path = Path(str(raw)).resolve()
            if not path.is_file() or not path_within(path, task_dir / "raw"):
                errors.append(f"Raw evidence is missing or outside task raw/: {raw}")
            elif run.get("payload_digest") and sha256_file(path) != run.get("payload_digest"):
                errors.append(f"Raw evidence digest mismatch: {raw}")

    recomputed_sources = source_gaps(task, evidence, candidates, plan)
    recomputed_queries = required_query_gaps(task, evidence, plan)
    recomputed_gates = low_risk_gate_gaps(task, evidence, plan)
    recomputed_unverified = material_unverified(candidates)
    coverage = assessment.get("coverage", {})
    comparisons = (
        ("missing_required_sources", recomputed_sources),
        ("missing_required_queries", recomputed_queries),
        ("missing_low_risk_gate_sources", recomputed_gates),
        ("unverified_material_candidates", recomputed_unverified),
    )
    for key, recomputed in comparisons:
        if sorted(coverage.get(key, [])) != sorted(recomputed):
            errors.append(f"Assessment coverage is stale for {key}")

    if assessment.get("status") == "completed":
        if assessment.get("overall", {}).get("risk") not in {"极低", "低", "中", "高", "极高"}:
            errors.append("Completed assessment has no valid final risk")
        if recomputed_sources or recomputed_queries or recomputed_unverified:
            errors.append("Completed assessment has unresolved mandatory evidence")
        if recomputed_gates and assessment.get("overall", {}).get("risk") in {"极低", "低"}:
            errors.append("Completed low-risk assessment has unfinished patent-browser gates")
        if unresolved_journal:
            errors.append("Completed assessment has unresolved viewed patent candidates")
    elif assessment.get("status") == "incomplete" and assessment.get("overall", {}).get("risk"):
        errors.append("Incomplete assessment must not expose a final risk")

    browser = evidence.get("collections", {}).get("browser", [])
    if not browser:
        errors.append("Browser evidence is missing")
    else:
        screenshots = browser[0].get("screenshots", {})
        hashes = browser[0].get("screenshot_hashes", {})
        for role, raw_path in screenshots.items():
            path = Path(str(raw_path)).resolve()
            if not path.is_file() or not path_within(path, task_dir / "screenshots"):
                errors.append(f"Browser screenshot is missing or outside task: {role}")
            elif hashes.get(role) != sha256_file(path):
                errors.append(f"Browser screenshot digest mismatch: {role}")

    if manifest.get("report_schema_version") != "1.0" or manifest.get("task_id") != task.get("task_id"):
        errors.append("Report manifest identity/schema mismatch")
    task_for_digest = {**task, "outputs": {}}
    expected_digests = {
        "task": sha256_json(task_for_digest), "evidence": sha256_json(evidence),
        "assessment": sha256_json(assessment), "candidates": sha256_json(candidates),
        "candidate_journal": sha256_json(journal),
    }
    if manifest.get("input_digests") != expected_digests:
        errors.append("Report is stale relative to task evidence or assessment")
    for item in manifest.get("key_evidence", []):
        path = Path(str(item.get("path", ""))).resolve()
        if not path.is_file() or not path_within(path, task_dir) or sha256_file(path) != item.get("sha256"):
            errors.append(f"Key evidence path/hash mismatch: {path}")

    report_md = (task_dir / "report.md").read_text(encoding="utf-8")
    report_html = (task_dir / "report.html").read_text(encoding="utf-8")
    for entry in journal_entries:
        record = str(entry.get("record_number") or "") if isinstance(entry, dict) else ""
        if record and record not in report_md and record not in report_html:
            errors.append(f"Viewed patent candidate is missing from report: {record}")
    if 'name="report-schema" content="IPR-EVIDENCE-DOSSIER/1.0"' not in report_html:
        errors.append("HTML report does not use the fixed dossier format")
    secrets = configured_secrets(load_skill_config())
    public_text = report_md + report_html + (task_dir / "evidence.json").read_text(encoding="utf-8")
    if journal_path.exists():
        public_text += journal_path.read_text(encoding="utf-8")
    if any(secret in public_text for secret in secrets):
        errors.append("A configured secret appears in report or evidence JSON")
    browser_leaks = forbidden_browser_paths({
        "task": task, "evidence": evidence, "assessment": assessment,
        "plan": plan, "candidates": candidates, "journal": journal, "manifest": manifest,
    })
    if browser_leaks:
        errors.append("Forbidden browser session fields appear in artifacts: " + ", ".join(browser_leaks[:5]))

    if errors:
        raise SystemExit("validation failed:\n- " + "\n- ".join(errors))
    print("run valid")


if __name__ == "__main__":
    main()

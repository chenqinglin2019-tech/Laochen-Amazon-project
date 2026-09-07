#!/usr/bin/env python3
"""Audit a held-out recall oracle against retained, real browser executions.

This command never submits queries. The oracle belongs to the evaluator, not the
planner. Passing this check proves one recall case, not exhaustive IP clearance.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

from assessment_v24 import NON_PRODUCTION, bound_runs, evidence_index
from common import atomic_write_json, load_json, load_skill_config, now_iso, sha256_file, sha256_json
from run_browser_plan import completed_capture


def publication_identity(value):
    number = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    match = re.fullmatch(r"(?:US)?(D?)(0*\d+)(?:[A-Z]\d?)?", number)
    return ("US" + match[1] + str(int(match[2]))) if match else number


def nonproduction(value):
    if isinstance(value, dict):
        return (any(str(value.get(key) or "").casefold() in NON_PRODUCTION | {"synthetic", "offline"}
                    for key in ("source_environment", "environment", "kind"))
                or any(value.get(key) is True for key in ("test_only", "fixture", "synthetic", "simulation", "mock"))
                or any(nonproduction(item) for item in value.values()))
    return isinstance(value, list) and any(nonproduction(item) for item in value)


def live_capture_origin(capture, task_dir):
    """After completed_capture, require an official origin and untainted receipt.

    Normal browser recorders historically omit source_environment. Absence is
    not a production assertion: the validated capture/receipt chain supplies
    provenance instead. Explicit null, unknown or test labels still fail.
    """
    try:
        parsed = urlparse(str(capture.get("final_url") or ""))
        hosts = load_skill_config()["providers"]["uspto_patent_browser"]["browser_allowed_hosts"]
        if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password:
            return False
        reference = capture["query_execution"]
        path = Path(reference["path"]).resolve()
        if not path.is_relative_to(task_dir / "raw" / "browser-execution") or sha256_file(path) != reference["sha256"]:
            return False
        receipt = load_json(path)
        return (not nonproduction([capture, receipt])
                and all("source_environment" not in value or value["source_environment"] == "production"
                        for value in (capture, receipt))
                and receipt.get("final_url") == capture["final_url"]
                and receipt.get("mode") == "automatic" and receipt.get("business_actions_by") == "agent")
    except (OSError, ValueError, KeyError, TypeError):
        return False


def evaluate_recall(task_dir: Path, oracle: dict) -> dict:
    task_dir = task_dir.resolve()
    task = load_json(task_dir / "task.json")
    plan = load_json(task_dir / "search-plan.json")
    evidence = load_json(task_dir / "evidence.json")
    candidates = load_json(task_dir / "normalized-candidates.json")
    status_path = task_dir / "browser-execution-status.json"
    executions = load_json(status_path) if status_path.exists() else {}
    if any(data.get("task_id") != task["task_id"] for data in (plan, evidence, candidates)):
        raise ValueError("RECALL_ACCEPTANCE_TASK_MISMATCH")
    if nonproduction(task) or nonproduction(plan):
        raise ValueError("LIVE_RECALL_ACCEPTANCE_REJECTS_NONPRODUCTION_INPUT")
    expected = oracle.get("expected_publication_numbers")
    if (oracle.get("schema") != "IPR-RECALL-ORACLE/1.0"
            or not isinstance(expected, list) or not expected
            or not all(isinstance(value, str) and value.strip() for value in expected)
            or oracle.get("right_type") not in {"patent", "design"}
            or oracle.get("jurisdiction") != "US"
            or oracle.get("asin") != task.get("product", {}).get("requested_asin")):
        raise ValueError("RECALL_ORACLE_INVALID")
    expected = {publication_identity(value) for value in expected}
    if any(not re.fullmatch(r"USD\d+" if oracle["right_type"] == "design" else r"US\d+", value)
           for value in expected):
        raise ValueError("RECALL_ORACLE_RIGHT_TYPE_MISMATCH")
    # Identity evidence is separately reviewed; a same-name patent is not truth.
    identity = oracle.get("identity_review", {})
    artifacts = identity.get("artifacts", [])
    if not identity.get("reviewer") or not identity.get("reasoning") or not artifacts:
        raise ValueError("RECALL_ORACLE_IDENTITY_REVIEW_REQUIRED")
    for artifact in artifacts:
        path = Path(artifact.get("path", "")).resolve()
        if (not path.is_file() or artifact.get("sha256") != sha256_file(path)
                or not str(artifact.get("source_url", "")).startswith("https://")):
            raise ValueError("RECALL_ORACLE_IDENTITY_ARTIFACT_INVALID")
    rows = {row["query_id"]: row for row in executions.get("queries", [])}
    index = evidence_index(evidence)
    found = {}
    for candidate in candidates.get("patents", []):
        identities = {publication_identity(candidate.get(key)) for key in
                      ("publication_number", "grant_number", "record_number")}
        matching = identities & expected
        if not matching or candidate.get("right_type") != oracle["right_type"]:
            continue
        if nonproduction(candidate):
            continue
        for ref in candidate.get("evidence_refs", []):
            entry = index.get(ref, {})
            provider, query_id = entry.get("provider"), entry.get("query_id")
            if provider != "uspto_patent_browser":
                continue
            if nonproduction(entry):
                continue
            query = next((row for row in plan.get("queries", {}).get(provider, [])
                          if row.get("query_id") == query_id), None)
            if not query or query.get("operation") != oracle["right_type"] + "_recall":
                continue
            if query.get("jurisdiction") != "US" or query.get("right_type") != oracle["right_type"]:
                continue
            # Known-number lookup validates retrieval, not product-led recall.
            query_numbers = {publication_identity(number) for number in
                             re.findall(r"(?:US)?D?\d{5,}(?:[A-Z]\d?)?", str(query.get("q", "")).upper())}
            if query.get("candidate_id") or query.get("strategy") == "record_number" or query_numbers & expected:
                continue
            if not any(run.get("status") == "success"
                       and ("source_environment" not in run or run["source_environment"] == "production")
                       and not nonproduction(run) and run.get("run_id") == entry.get("source_run_id")
                       for run in bound_runs(evidence, plan, provider, query)):
                continue
            execution = rows.get(query_id, {})
            if not completed_capture(task_dir, task, provider, query, execution):
                continue
            capture = load_json(Path(execution["capture_path"]))
            if not live_capture_origin(capture, task_dir):
                continue
            if any(capture.get(key) != query.get(key) for key in ("query_id", "right_type")):
                continue
            if any(key in capture and capture[key] != query.get(key) for key in ("operation", "jurisdiction")):
                continue
            captured_numbers = {publication_identity(item.get(key))
                                for item in capture.get("candidates", [])
                                for key in ("publication_number", "grant_number", "record_number")}
            # Require the exact identity in the original result, not only in a
            # manually edited normalized candidate linked to the same query.
            raw_numbers = {publication_identity(item.get(key))
                           for item in entry.get("payload", {}).get("candidates", [])
                           for key in ("publication_number", "grant_number", "record_number")}
            for number in matching & raw_numbers & captured_numbers:
                found[number] = {"candidate_id": candidate.get("candidate_id"),
                                 "evidence_id": ref, "query_id": query_id}
    missing = sorted(expected - found.keys())
    return {"schema": "IPR-RECALL-ACCEPTANCE/1.0", "task_id": task["task_id"],
            "checked_at": now_iso(), "oracle_sha256": sha256_json(oracle),
            "status": "passed" if not missing else "incomplete",
            "scope": "One product-led US browser recall case; not complete search or legal clearance.",
            "found": found, "missing": missing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True, type=Path)
    parser.add_argument("--oracle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output file; previous acceptance evidence is immutable")
    result = evaluate_recall(args.task_dir, load_json(args.oracle))
    atomic_write_json(args.output, result)
    print(result["status"] + ": " + str(args.output))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Two-phase gate for credentials/free access and collected product evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from auth_gate import SAFE_FAILURE, require_auth
from common import (
    EU_COUNTRIES, add_gap, add_history, atomic_write_json, ensure_object, image_info, load_json, load_skill_config,
    now_iso, parse_iso, sha256_file,
)
from epo_ops_client import probe as probe_epo
from euipo_client import probe as probe_euipo
from provider_utils import ProviderError, record_error, record_result
from serpapi_patents_client import probe as probe_serpapi
from serper_client import probe as probe_serper
from signa_client import probe as probe_signa


def record_probe(
    task_dir: Path, provider: str, jurisdiction: str,
    call: Callable[[], dict[str, Any]], *, mandatory: bool = True,
) -> bool:
    try:
        info = call()
        record_result(task_dir, provider=provider, operation="preflight_probe", query="runtime-access",
            jurisdiction=jurisdiction, evidence_type="official_verification", status="success",
            normalized={"probe": info}, quota=info.get("quota", {}), mandatory=mandatory)
        return True
    except ProviderError as exc:
        record_error(task_dir, provider=provider, operation="preflight_probe", query="runtime-access",
            jurisdiction=jurisdiction, evidence_type="official_verification", error_value=exc,
            mandatory=mandatory)
        return False


def phase_credentials(task_dir: Path) -> str:
    task_path = task_dir / "task.json"
    task = ensure_object(load_json(task_path), "task.json")
    if task.get("state") not in {"pending", "preflight_credentials", "incomplete"}:
        raise SystemExit(f"Credential preflight cannot run from state {task.get('state')!r}")
    add_history(task, "preflight_credentials", "Credential and free-access preflight started")
    atomic_write_json(task_path, task)
    try:
        require_auth()
    except SystemExit:
        task = ensure_object(load_json(task_path), "task.json")
        add_gap(task, "cloud_auth", "GLOBAL", "access_limited", "AUTH_FAILED", SAFE_FAILURE)
        task.setdefault("errors", []).append({"at": now_iso(), "code": "AUTH_FAILED", "detail": SAFE_FAILURE})
        add_history(task, "incomplete", SAFE_FAILURE)
        atomic_write_json(task_path, task)
        raise SystemExit(SAFE_FAILURE) from None

    jurisdictions = [str(value).upper() for value in task.get("target_jurisdictions", [])]
    checks: list[tuple[str, str, Callable[[], dict[str, Any]], bool]] = [
        ("serpapi_google_patents", ",".join(jurisdictions), probe_serpapi, True),
        ("serper_patents", ",".join(jurisdictions), probe_serper, True),
    ]
    if "epo_ops" in set(task.get("required_sources", [])) | set(task.get("low_risk_gate_sources", [])):
        checks.insert(0, (
            "epo_ops", ",".join(jurisdictions), probe_epo,
            "epo_ops" in task.get("required_sources", []),
        ))
    if "signa" in task.get("required_sources", []):
        eu_target = "EU" in jurisdictions or any(value in EU_COUNTRIES for value in jurisdictions)
        signa_jurisdictions = (["EU"] if eu_target else []) + [
            value for value in jurisdictions if value not in {"US", "EU"} and value not in EU_COUNTRIES
        ]
        signa_jurisdictions = list(dict.fromkeys(signa_jurisdictions or jurisdictions))
        checks.append(("signa", ",".join(signa_jurisdictions), lambda: probe_signa(signa_jurisdictions), True))
    if "EU" in jurisdictions or any(value in EU_COUNTRIES for value in jurisdictions):
        checks.extend([
            ("euipo_trademark", "EU", lambda: probe_euipo("trademark"), True),
            ("euipo_design", "EU", lambda: probe_euipo("design"), True),
        ])
    results = {
        provider: record_probe(task_dir, provider, jurisdiction, call, mandatory=mandatory)
        for provider, jurisdiction, call, mandatory in checks
    }
    if "US" in jurisdictions:
        detail = "TSDR API route is disabled; visible Chrome desktop over CDP is mandatory"
        record_result(task_dir, provider="uspto_tsdr", operation="api_preflight", query="disabled-api-route",
            jurisdiction="US", evidence_type="official_verification", status="not_applicable",
            normalized=None, detail=detail, mandatory=False)
        results["uspto_tsdr"] = True
        task = ensure_object(load_json(task_path), "task.json")
        task.setdefault("checkpoints", {})["tsdr_route"] = {
            "status": "chrome_desktop_cdp_required",
            "at": now_iso(), "detail": detail,
        }
        atomic_write_json(task_path, task)
    if results.get("serper_patents"):
        probe_run = next((run for run in load_json(task_dir / "evidence.json")["source_runs"] if run["provider"] == "serper_patents" and run["operation"] == "preflight_probe"), None)
        for provider in ("serper_web", "serper_images"):
            record_result(task_dir, provider=provider, operation="preflight_probe", query="shared-serper-api",
                jurisdiction=",".join(jurisdictions), evidence_type="official_verification", status="success",
                normalized={"probe": {"ready": True, "shared_with": "serper_patents"}}, quota=(probe_run or {}).get("quota", {}))
    task = ensure_object(load_json(task_path), "task.json")
    failed_required = [provider for provider, ok in results.items() if not ok and provider in task.get("required_sources", [])]
    if failed_required:
        task.setdefault("errors", []).append({"at": now_iso(), "code": "PREFLIGHT_REQUIRED_MISSING", "detail": ", ".join(failed_required)})
        add_history(task, "incomplete", "Required free-access probes failed: " + ", ".join(failed_required))
        outcome = "incomplete"
    else:
        task.setdefault("checkpoints", {})["credential_preflight"] = {"status": "success", "at": now_iso(), "providers": sorted(results)}
        add_history(task, "awaiting_browser", "Credential preflight passed; waiting for Amazon capture and browser patent-source confirmation")
        outcome = "awaiting_browser"
    atomic_write_json(task_path, task)
    return outcome


def phase_evidence(
    task_dir: Path, browser_capability_confirmed: bool,
    chrome_desktop_confirmed: bool, cdp_capability_confirmed: bool,
) -> str:
    task_path, evidence_path = task_dir / "task.json", task_dir / "evidence.json"
    task = ensure_object(load_json(task_path), "task.json")
    evidence = ensure_object(load_json(evidence_path), "evidence.json")
    if task.get("state") not in {"awaiting_browser", "preflight_evidence", "incomplete", "needs_user_action"}:
        raise SystemExit(f"Evidence preflight cannot run from state {task.get('state')!r}")
    add_history(task, "preflight_evidence", "Product identity and evidence preflight started")
    errors: list[tuple[str, str]] = []
    product = task.get("product", {})
    if not product.get("actual_asin") or product.get("actual_asin") != product.get("requested_asin"):
        errors.append(("AMAZON_ASIN_MISMATCH", "Requested and actual ASIN are not confirmed equal"))
    if not isinstance(product.get("variant"), dict) or product.get("variant", {}).get("confirmed") is not True:
        errors.append(("AMAZON_ASIN_MISMATCH", "Current Amazon variant is not confirmed"))
    images = task.get("images", [])
    if not isinstance(images, list) or len(images) != 1:
        errors.append(("MAIN_IMAGE_UNAVAILABLE", "Exactly one main image is required"))
    else:
        image = images[0]
        path = Path(str(image.get("path", "")))
        if not path.is_file() or image.get("sha256") != sha256_file(path):
            errors.append(("MAIN_IMAGE_UNAVAILABLE", "Main image is absent or changed"))
        else:
            mime, width, height = image_info(path)
            if mime != image.get("mime_type") or (width and width != image.get("width")) or (height and height != image.get("height")):
                errors.append(("MAIN_IMAGE_UNAVAILABLE", "Main image metadata does not match file"))
    if not task.get("target_jurisdictions"):
        errors.append(("COVERAGE_UNVERIFIED", "Target jurisdiction is missing"))
    if task.get("schema_version") == "2.1-free":
        if not browser_capability_confirmed:
            errors.append(("COVERAGE_UNVERIFIED", "Legacy Codex browser capability was not confirmed"))
        if "US" in {str(value).upper() for value in task.get("target_jurisdictions", [])} and not chrome_desktop_confirmed:
            errors.append(("COVERAGE_UNVERIFIED", "Legacy Chrome desktop capability was not confirmed"))
    elif not cdp_capability_confirmed:
        errors.append(("COVERAGE_UNVERIFIED", "Visible Chrome CDP capability was not confirmed"))
    browser_runs = [run for run in evidence.get("source_runs", []) if run.get("provider") == "amazon_browser" and run.get("status") == "success"]
    if not browser_runs:
        errors.append(("RESPONSE_SCHEMA_CHANGED", "Accepted Amazon browser evidence is missing"))
    credential_checkpoint = task.get("checkpoints", {}).get("credential_preflight", {})
    if credential_checkpoint.get("status") != "success":
        errors.append(("AUTH_FAILED", "Successful credential preflight checkpoint is missing"))
    else:
        try:
            age_hours = (parse_iso(now_iso()) - parse_iso(credential_checkpoint["at"])).total_seconds() / 3600
            max_age = int(load_skill_config().get("freshness", {}).get("provider_probe_max_age_hours", 24))
            if age_hours > max_age:
                errors.append(("COVERAGE_UNVERIFIED", f"Credential preflight is older than {max_age} hours"))
        except (KeyError, ValueError):
            errors.append(("RESPONSE_SCHEMA_CHANGED", "Credential preflight timestamp is invalid"))
    if errors:
        for code, detail in errors:
            task.setdefault("errors", []).append({"at": now_iso(), "code": code, "detail": detail})
            add_gap(task, "amazon_browser", task.get("request", {}).get("marketplace", ""), "failed", code, detail)
        add_history(task, "incomplete", "; ".join(detail for _, detail in errors))
        outcome = "incomplete"
    else:
        browser_sources = set(task.get("required_sources", [])) | set(task.get("low_risk_gate_sources", []))
        if "wipo_patentscope_browser" in browser_sources:
            record_result(
                task_dir, provider="wipo_patentscope_browser", operation="browser_capability",
                query="official-registry", jurisdiction=",".join(task["target_jurisdictions"]),
                evidence_type="official_verification", status="success",
                normalized={
                    "capability_confirmed": True, "browser": "chrome_desktop",
                    "capture_transport": "manual",
                    "note": "Operator-confirmed PATENTSCOPE capture is required; no automated query or DOM extraction",
                },
            )
        for provider in ("uspto_tmsearch_browser", "uspto_patent_browser", "uspto_tsdr"):
            if provider in browser_sources:
                record_result(task_dir, provider=provider, operation="browser_capability", query="official-registry",
                    jurisdiction=",".join(task["target_jurisdictions"]), evidence_type="official_verification", status="success",
                    normalized={
                        "capability_confirmed": True, "browser": "chrome_desktop",
                        "capture_transport": "cdp",
                        "note": "Visible Chrome CDP capability confirmed; candidate-level official checks remain required",
                    })
        task = ensure_object(load_json(task_path), "task.json")
        task.setdefault("checkpoints", {})["evidence_preflight"] = {"status": "success", "at": now_iso()}
        add_history(task, "collecting", "Evidence preflight passed")
        outcome = "collecting"
    atomic_write_json(task_path, task)
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description="Run two-phase preflight.")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--phase", choices=["credentials", "evidence"], required=True)
    parser.add_argument("--browser-capability-confirmed", action="store_true")
    parser.add_argument("--chrome-desktop-confirmed", action="store_true")
    parser.add_argument("--cdp-capability-confirmed", action="store_true")
    args = parser.parse_args()
    task_dir = args.task.resolve().parent
    outcome = (
        phase_credentials(task_dir)
        if args.phase == "credentials"
        else phase_evidence(
            task_dir, args.browser_capability_confirmed,
            args.chrome_desktop_confirmed, args.cdp_capability_confirmed,
        )
    )
    print(outcome)


if __name__ == "__main__":
    main()

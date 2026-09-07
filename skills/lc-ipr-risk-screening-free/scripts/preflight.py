#!/usr/bin/env python3
"""Two-phase gate for credentials/free access and collected product evidence."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from auth_gate import SAFE_FAILURE, require_auth
from common import (
    add_gap, add_history, assert_active_free_policy, atomic_write_json, coverage_routes, ensure_object,
    credential, image_info, is_active_schema, load_json, load_skill_config, now_iso,
    parse_iso, serpapi_free_enabled, serper_free_enabled, sha256_file,
    signa_free_enabled, skill_root,
)
from epo_ops_client import probe as probe_epo
from euipo_client import probe as probe_euipo
from provider_utils import ProviderError, record_error, record_result, require_provider_operation


LOCAL_CREDENTIAL_FIELDS = {
    "backend_token", "epo_consumer_key", "epo_consumer_secret",
    "euipo_client_id", "euipo_client_secret", "jpo_api_username",
    "jpo_api_password", "serpapi_api_key", "serper_api_key",
    "signa_api_key", "rapidapi_key",
}


def local_secret_findings(root: Path | None = None) -> list[str]:
    """Return only file/field labels for stale local secrets, never their values."""
    selected_root = root or skill_root()
    findings: list[str] = []

    def inspect(filename: str, value: Any, path: tuple[str, ...] = ()) -> None:
        if not isinstance(value, dict):
            return
        for raw_name, item in value.items():
            name = str(raw_name)
            item_path = (*path, name)
            if name in LOCAL_CREDENTIAL_FIELDS and item not in (None, ""):
                findings.append(f"{filename}:{'.'.join(item_path)}")
            if isinstance(item, dict):
                inspect(filename, item, item_path)

    for filename in ("config.json", "config.local.json"):
        path = selected_root / filename
        if not path.is_file():
            continue
        try:
            payload = ensure_object(load_json(path), filename)
        except (OSError, ValueError):
            findings.append(f"{filename}:unreadable")
            continue
        inspect(filename, payload)
    return sorted(set(findings))


def local_provider_credentials_present() -> bool:
    """Compatibility predicate for any stale provider credential field."""
    return any(not finding.endswith("backend_token") for finding in local_secret_findings())


def credential_storage_checkpoint() -> dict[str, Any]:
    """Build a value-free local secret scan result before cloud authentication."""
    local_secrets = local_secret_findings()
    local_query_secrets = any(not finding.endswith("backend_token") for finding in local_secrets)
    local_backend_token = any(finding.endswith("backend_token") for finding in local_secrets)
    return {
        "status": "rotation_required" if local_secrets else "environment_or_keychain_only",
        "at": now_iso(),
        "provider_credentials_in_local_file": local_query_secrets,
        "backend_token_in_local_file": local_backend_token,
        "local_secret_fields": local_secrets,
        "detail": (
            "Remove local credential fields and rotate exposed values; runtime ignores all config-file credentials"
            if local_secrets else
            "Credentials are read only from environment variables or fixed macOS Keychain accounts"
        ),
    }


def probe_euipo_production(product: str) -> dict[str, Any]:
    info = probe_euipo(product)
    if info.get("environment") != "production" or info.get("authoritative_for_final_rating") is not True:
        raise ProviderError(
            "EUIPO_PRODUCTION_REQUIRED", "access_limited",
            "EUIPO Sandbox cannot satisfy a formal 2.3 coverage requirement",
        )
    return info


def probe_epo_production() -> dict[str, Any]:
    info = probe_epo()
    if info.get("environment") != "production" or info.get("authoritative_for_final_rating") is not True:
        raise ProviderError(
            "EPO_PRODUCTION_REQUIRED", "access_limited",
            "EPO local fixtures cannot satisfy a formal 2.3 coverage requirement",
        )
    return info


def probe_jpo() -> dict[str, Any]:
    try:
        from jpo_api_client import probe as actual_probe
    except (ImportError, AttributeError) as exc:
        raise ProviderError(
            "PROVIDER_UNAVAILABLE", "failed", "JPO API client/probe is unavailable",
        ) from exc
    info = actual_probe()
    if not isinstance(info, dict) or not (
        info.get("ready") is True or info.get("status") == "success"
    ):
        raise ProviderError("COVERAGE_UNVERIFIED", "access_limited", "JPO API probe did not confirm readiness")
    if info.get("environment") != "production" or info.get("authoritative_for_final_rating") is not True:
        raise ProviderError(
            "JPO_PRODUCTION_REQUIRED", "access_limited",
            "JPO local fixtures cannot satisfy a formal 2.3 coverage requirement",
        )
    return info


def probe_configured_adapter(provider: str) -> dict[str, Any]:
    cfg = load_skill_config().get("providers", {}).get(provider, {})
    status = str(cfg.get("adapter_status") or "").strip()
    if status != "ready":
        raise ProviderError(
            "ADAPTER_SETUP_REQUIRED", "access_limited",
            f"{provider} adapter is {status or 'not configured'}; its browser fallback remains required",
        )
    return {"ready": True, "adapter_status": status, "access_tier": cfg.get("access_tier", "")}


def probe_signa_safe(offices: list[str]) -> dict[str, Any]:
    """Run only Signa's non-search account, billing, usage, and office checks."""
    try:
        from signa_client import probe as actual_probe
    except (ImportError, AttributeError) as exc:
        raise ProviderError(
            "PROVIDER_UNAVAILABLE", "failed", "Signa client/probe is unavailable",
        ) from exc
    info = actual_probe(offices)
    if not isinstance(info, dict) or info.get("ready") is not True:
        raise ProviderError(
            "COVERAGE_UNVERIFIED", "access_limited",
            "Signa safe preflight did not confirm a zero-payment discovery account",
        )
    return info


def record_probe(
    task_dir: Path, provider: str, jurisdiction: str,
    call: Callable[[], dict[str, Any]], *, mandatory: bool = True,
) -> bool:
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    evidence_type = "credential_check" if provider == "signa" else "official_verification"
    try:
        require_provider_operation(task, provider, "credential_check")
        info = call()
        record_result(task_dir, provider=provider, operation="credential_check", query="runtime-access",
            jurisdiction=jurisdiction, evidence_type=evidence_type, status="success",
            normalized={"probe": info}, quota=info.get("quota", {}), mandatory=mandatory,
            source_environment=str(info.get("environment") or ""),
            authoritative_for_final_rating=(
                info.get("authoritative_for_final_rating")
                if isinstance(info.get("authoritative_for_final_rating"), bool) else None
            ))
        return True
    except ProviderError as exc:
        record_error(task_dir, provider=provider, operation="credential_check", query="runtime-access",
            jurisdiction=jurisdiction, evidence_type=evidence_type, error_value=exc,
            mandatory=mandatory)
        return False


def phase_credentials(task_dir: Path) -> str:
    if load_json(task_dir / "task.json").get("schema_version") == "2.4-free":
        from runtime_v24 import preflight_credentials
        return preflight_credentials(task_dir)
    task_path = task_dir / "task.json"
    task = ensure_object(load_json(task_path), "task.json")
    if not is_active_schema(task):
        raise SystemExit("Legacy 2.1/2.2 tasks are evidence-read-only; provider preflight is disabled")
    assert_active_free_policy(task)
    if task.get("state") not in {"pending", "preflight_credentials", "incomplete"}:
        raise SystemExit(f"Credential preflight cannot run from state {task.get('state')!r}")
    add_history(task, "preflight_credentials", "Credential and free-access preflight started")
    task.setdefault("checkpoints", {})["credential_storage"] = credential_storage_checkpoint()
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
    route_providers = {str(route.get("provider") or "") for route in coverage_routes(task)}
    config = load_skill_config()
    checks: list[tuple[str, str, Callable[[], dict[str, Any]], bool]] = []
    if "epo_ops" in route_providers:
        checks.append(("epo_ops", ",".join(jurisdictions), probe_epo_production, False))
    if "euipo_trademark" in route_providers:
        checks.append(("euipo_trademark", "EU", lambda: probe_euipo_production("trademark"), False))
    if "euipo_design" in route_providers:
        checks.append(("euipo_design", "EU", lambda: probe_euipo_production("design"), False))
    if "jpo_api" in route_providers:
        # JPO is an identifier-detail route with a J-PlatPat fallback, so a
        # missing account must not prevent discovery and high-risk reporting.
        checks.append(("jpo_api", "JP", probe_jpo, False))
    for provider, jurisdiction in (("inpi_api", "FR"), ("prv_open_data", "SE")):
        if provider in route_providers:
            checks.append((
                provider, jurisdiction,
                lambda selected=provider: probe_configured_adapter(selected), False,
            ))
    signa_cfg = config.get("providers", {}).get("signa", {})
    signa_office_map = signa_cfg.get("office_map", {})
    signa_excluded = {
        str(value).upper() for value in signa_cfg.get("excluded_offices", [])
    }
    signa_offices = list(dict.fromkeys(
        str(signa_office_map.get(value) or "").upper()
        for value in jurisdictions
        if str(signa_office_map.get(value) or "").upper()
        and str(signa_office_map.get(value) or "").upper() not in signa_excluded
    ))
    if signa_free_enabled(task) and signa_offices:
        checks.append((
            "signa", ",".join(jurisdictions),
            lambda: probe_signa_safe(signa_offices), False,
        ))
    results = {
        provider: record_probe(task_dir, provider, jurisdiction, call, mandatory=mandatory)
        for provider, jurisdiction, call, mandatory in checks
    }
    if "US" in jurisdictions:
        detail = "TSDR API route is disabled; visible Chrome desktop over CDP is mandatory"
        record_result(task_dir, provider="uspto_tsdr", operation="credential_check", query="disabled-api-route",
            jurisdiction="US", evidence_type="official_verification", status="not_applicable",
            normalized=None, detail=detail, mandatory=False)
        results["uspto_tsdr"] = True
        task = ensure_object(load_json(task_path), "task.json")
        task.setdefault("checkpoints", {})["tsdr_route"] = {
            "status": "chrome_desktop_cdp_required",
            "at": now_iso(), "detail": detail,
        }
        atomic_write_json(task_path, task)
    task = ensure_object(load_json(task_path), "task.json")
    optional_credentials: dict[str, dict[str, Any]] = {}
    selected_optional = {
        "serper": serper_free_enabled(task),
        "signa": signa_free_enabled(task),
        "serpapi": serpapi_free_enabled(task),
    }
    credential_specs = {
        "serper": ("serper_api_key", "SERPER_API_KEY"),
        "signa": ("signa_api_key", "SIGNA_API_KEY"),
        "serpapi": ("serpapi_api_key", "SERPAPI_API_KEY"),
    }
    for provider, (credential_name, env_name) in credential_specs.items():
        available = bool(credential(config, credential_name))
        enabled = selected_optional[provider]
        optional_credentials[provider] = {
            "enabled": enabled,
            "credential_env": env_name,
            "credential_available": available,
            "status": (
                "configured_pending_provider_check" if enabled and available else
                "missing" if enabled else
                "available_not_selected" if available else
                "not_selected"
            ),
        }
    if serper_free_enabled(task):
        serper_ready = optional_credentials["serper"]["credential_available"]
        for provider in ("serper_patents", "serper_web", "serper_images"):
            results[provider] = serper_ready
            if not serper_ready:
                add_gap(
                    task, provider, ",".join(jurisdictions), "access_limited",
                    "AUTH_MISSING",
                    "Optional Serper discovery was selected but SERPER_API_KEY is unavailable",
                    mandatory=False,
                )
        optional_credentials["serper"]["status"] = (
            "ready_for_first_planned_query" if serper_ready else "missing"
        )
    if signa_free_enabled(task) and signa_offices:
        signa_ready = results.get("signa") is True
        optional_credentials["signa"]["status"] = "ready" if signa_ready else "unavailable"
    elif signa_free_enabled(task):
        results["signa"] = False
        optional_credentials["signa"]["status"] = "not_applicable_for_target_office"
        add_gap(
            task, "signa", ",".join(jurisdictions), "access_limited",
            "SIGNA_OFFICE_UNSUPPORTED",
            "Optional Signa discovery was selected, but no live configured Signa office maps to the target jurisdiction",
            mandatory=False,
        )
    if serpapi_free_enabled(task):
        serpapi_ready = optional_credentials["serpapi"]["credential_available"]
        results["serpapi_google_patents"] = serpapi_ready
        optional_credentials["serpapi"]["status"] = (
            "ready_for_account_check" if serpapi_ready else "missing"
        )
        if not serpapi_ready:
            add_gap(
                task, "serpapi_google_patents", ",".join(jurisdictions),
                "access_limited", "AUTH_MISSING",
                "Optional SerpApi discovery was selected but SERPAPI_API_KEY is unavailable",
                mandatory=False,
            )
    unavailable = sorted(provider for provider, ok in results.items() if not ok)
    for provider in unavailable:
        if not any(gap.get("provider") == provider for gap in task.get("coverage_gaps", [])):
            add_gap(
                task, provider, ",".join(jurisdictions), "access_limited",
                "FREE_SOURCE_UNAVAILABLE",
                "Free provider preflight failed; collection may continue and the loss remains explicit",
                mandatory=False,
            )
    task.setdefault("checkpoints", {})["credential_preflight"] = {
        "status": "success",
        "at": now_iso(),
        "providers": {provider: ("ready" if ok else "unavailable") for provider, ok in sorted(results.items())},
        "free_only": True,
        "unavailable": unavailable,
        "optional_discovery_credentials": {
            "required_for_minimum": False,
            "providers": optional_credentials,
            "detail": (
                "Serper, Signa, and SerpApi are optional discovery enhancements. "
                "Provide the named credential and explicitly select its task flag to improve recall; "
                "an unselected or missing optional provider does not block the official minimum route."
            ),
        },
    }
    note = "Credential preflight completed; waiting for Amazon capture and visible official-registry capability"
    if unavailable:
        note += "; unavailable free sources: " + ", ".join(unavailable)
    add_history(task, "awaiting_browser", note)
    outcome = "awaiting_browser"
    atomic_write_json(task_path, task)
    return outcome


def phase_evidence(
    task_dir: Path, browser_capability_confirmed: bool,
    chrome_desktop_confirmed: bool, cdp_capability_confirmed: bool,
) -> str:
    if load_json(task_dir / "task.json").get("schema_version") == "2.4-free":
        from runtime_v24 import preflight_evidence
        return preflight_evidence(task_dir)
    task_path, evidence_path = task_dir / "task.json", task_dir / "evidence.json"
    task = ensure_object(load_json(task_path), "task.json")
    evidence = ensure_object(load_json(evidence_path), "evidence.json")
    if not is_active_schema(task):
        raise SystemExit("Legacy 2.1/2.2 tasks are evidence-read-only; evidence preflight is disabled")
    assert_active_free_policy(task)
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
    del browser_capability_confirmed, chrome_desktop_confirmed
    needs_cdp = any(
        str(route.get("method") or "").startswith("cdp")
        for route in coverage_routes(task)
    )
    if needs_cdp and not cdp_capability_confirmed:
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
        cdp_providers = sorted({
            str(route.get("provider") or "")
            for route in coverage_routes(task)
            if str(route.get("method") or "").startswith("cdp")
            and str(route.get("provider") or "")
        })
        for provider in cdp_providers:
            record_result(
                task_dir, provider=provider, operation="browser_capability",
                query="official-registry", jurisdiction=",".join(task["target_jurisdictions"]),
                evidence_type="official_verification", status="success",
                normalized={
                    "capability_confirmed": True,
                    "browser": "chrome_desktop",
                    "capture_transport": "cdp",
                    "note": "Visible Chrome CDP capability confirmed; recall and candidate checks remain separate",
                },
                mandatory=False,
            )
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

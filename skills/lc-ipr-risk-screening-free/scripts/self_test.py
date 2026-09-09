#!/usr/bin/env python3
"""Offline contract and end-to-end tests for the 2.3 official-free-only skill."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import patch

from offline_test_support import isolated_test_environment, offline_environment

from common import (
    AUTHORIZED_FREE_COMMERCIAL_PROVIDERS, COMMERCIAL_PROVIDERS,
    FREE_POLICY_REVISION, LEGACY_DEFAULT_DISCOVERY_REVISION, MODULE_IDS,
    SCHEMA_VERSION,
    SERPAPI_FREE_MAX_QUERIES_PER_TASK, SERPAPI_OPERATION, SERPAPI_PROVIDER,
    SERPER_PROVIDERS, SIGNA_FREE_MAX_QUERIES_PER_TASK, SIGNA_OPERATION,
    SIGNA_PROVIDER,
    SERPER_PROVIDER_OPERATIONS, SERPER_PROVIDER_QUERY_CAPS, WIPO_PROVIDERS,
    add_gap,
    active_free_policy, build_coverage_requirements, default_jurisdictions,
    intrinsic_patent_right_type, load_skill_config, normalize_text, now_iso,
    optional_discovery_incomplete_queries,
    assert_active_free_policy, authorize_serpapi_free_plan_entry,
    authorize_serper_free_plan_entry, authorize_signa_free_plan_entry,
    provider_execution_error, sha256_json, task_free_policy_valid,
)
from annotate_materiality import (
    apply_materiality_annotations, candidate_identity_fingerprint,
    empty_materiality_ledger,
)
import euipo_client as euipo_runtime
import serpapi_patents_client as serpapi_runtime
import serper_client as serper_runtime
import signa_client as signa_runtime
from epo_ops_client import (
    normalize_detail, normalize_search, source_profile as epo_source_profile,
)
from euipo_client import (
    _resolved_endpoints as euipo_resolved_endpoints,
    search_parameters as euipo_search_parameters,
    search_rsql as euipo_search_rsql,
    source_profile as euipo_source_profile,
    verified_detail as euipo_verified_detail,
)
from finalize_assessment import (
    _same_candidate, coverage_requirement_gaps, formal_rating_evidence_by_module,
    material_unverified, paid_recommendations, required_query_gaps,
)
from jpo_api_client import JpoApiClient, normalize_verification
from merge_candidates import (
    EPO_DETAIL_OPERATIONS, append_epo_candidate_detail_actions,
    append_eu_candidate_verification_actions,
    append_jp_candidate_verification_actions, append_us_candidate_verification_actions,
    apply_candidate_contract, better_verification,
    apply_verifications, merge, verification_index,
)
import provider_utils as provider_runtime
from provider_utils import ProviderError, coverage_route_policy
from record_registry_browser import _recall_plan_binding
from report_v2 import (
    COVERAGE_BOUNDARIES, SECTION_ORDER, candidate_rows, coverage_gap_groups,
    is_official_record_url, release_gate,
)
import run_api_plan as api_runner
from run_api_plan import command_for as api_command_for
from security_quota_test import (
    test_credentials as test_secure_credential_sources,
    test_cross_process_reservation_and_restart,
    test_ops_client_reserves_before_offline_http,
    test_paid_header_and_week_window,
    test_plan_runner_reads_shared_account_state,
)
from test_candidate_gate_hardening import (
    test_evidence_backed_medium_high_gate,
    test_excluded_mismatch_action_is_repairable,
    test_public_candidate_chain, test_public_candidate_verification_actions,
    test_jplatpat_skip_requires_exact_jpo_plan,
    test_registry_verification_records_planned_query,
)


SCRIPTS = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS.parent
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def command(
    *arguments: str, env: dict[str, str] | None = None,
    succeeds: bool = True, contains: str = "",
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, *arguments], text=True, encoding="utf-8", capture_output=True,
        env=offline_environment(env), check=False, timeout=30,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if succeeds and result.returncode:
        raise AssertionError(f"command failed: {' '.join(arguments)}\n{output}")
    if not succeeds and result.returncode == 0:
        raise AssertionError(f"command unexpectedly succeeded: {' '.join(arguments)}")
    if contains and contains not in output:
        raise AssertionError(f"missing {contains!r}: {' '.join(arguments)}\n{output}")
    return result


def report_browser_acceptance(report_path: Path) -> None:
    """Run real layout/print checks when Node and a system Chrome are available."""
    node = shutil.which("node")
    if not node:
        print("SKIP report browser acceptance: node is unavailable")
        return
    env = offline_environment()
    env["REPORT_V2_HTML"] = str(report_path)
    test_path = SKILL_ROOT / "tools" / "cdp" / "report-v2-layout.test.mjs"
    result = subprocess.run(
        [node, "--test", str(test_path)], text=True, encoding="utf-8", capture_output=True,
        env=env, cwd=test_path.parent, check=False, timeout=60,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode:
        raise AssertionError(f"report browser acceptance failed:\n{output}")
    if "# SKIP" in output:
        print("SKIP report browser acceptance: system Chrome is unavailable")


def new_task(
    root: Path, name: str, url: str, jurisdictions: str, *extra_arguments: str,
) -> Path:
    task_dir = root / name
    command(
        str(SCRIPTS / "create_task.py"), "--url", url,
        "--jurisdictions", jurisdictions, "--output-dir", str(task_dir),
        "--schema-version", "2.3-free", *extra_arguments,
        env={**os.environ, "LC_IPR_TEST_MODE": "1"},
    )
    return task_dir


def prepare_product(task_dir: Path, *, japanese: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    evidence = json.loads((task_dir / "evidence.json").read_text(encoding="utf-8"))
    image = task_dir / "images" / "main.png"
    core = task_dir / "screenshots" / "product-core.png"
    details = task_dir / "screenshots" / "product-details.png"
    for path in (image, core, details):
        path.write_bytes(PNG)
    digest = hashlib.sha256(PNG).hexdigest()
    asin = task["product"]["requested_asin"]
    task["product"].update({
        "actual_asin": asin,
        "title": "猫の肉球 マウスパッド" if japanese else "Cat paw ergonomic mouse pad",
        "brand": "猫工房" if japanese else "MOCKMARK",
        "manufacturer": "猫工房株式会社" if japanese else "Mock Inc.",
        "category": "Mouse Pads",
        "bullets": ["手首を支える肉球形状" if japanese else "Cat paw wrist support"],
        "specifications": {"material": "silicone"},
        "structure": ["肉球シルエット" if japanese else "cat paw silhouette"],
        "variant": {"label": "Color", "value": "Pink", "confirmed": True},
    })
    task["images"] = [{
        "image_id": "IMG-001", "role": "main", "path": str(image),
        "source_url": "https://m.media-amazon.com/images/I/offline-test.png",
        "sha256": digest, "bytes": len(PNG), "mime_type": "image/png",
        "width": 1, "height": 1, "format": "PNG", "collected_at": now_iso(),
    }]
    browser = {
        "evidence_id": "EV-PRODUCT", "source": "amazon_browser",
        "final_url": task["request"]["url"], "product": task["product"],
        "screenshots": {"product_core": str(core), "product_details": str(details)},
        "screenshot_hashes": {"product_core": digest, "product_details": digest},
        "screenshot_bytes": {"product_core": len(PNG), "product_details": len(PNG)},
        "visual_features": ["肉球形状" if japanese else "cat paw silhouette"],
        "ocr_text": ["猫工房" if japanese else "MOCKMARK"],
        "collected_at": now_iso(),
    }
    evidence["collections"]["browser"] = [browser]
    evidence["collections"]["product"] = [browser]
    write_json(task_dir / "task.json", task)
    write_json(task_dir / "evidence.json", evidence)
    return task, evidence


def reviewed_materiality_fixture(
    task: dict[str, Any], candidates: dict[str, Any],
    decisions: dict[str, tuple[bool, str]],
) -> dict[str, Any]:
    ledger = empty_materiality_ledger(str(task["task_id"]))
    annotated_at = now_iso()
    for collection in ("patents", "trademarks"):
        for item in candidates.get(collection, []):
            candidate_id = str(item.get("candidate_id") or "")
            if candidate_id not in decisions:
                continue
            material, reason = decisions[candidate_id]
            ledger["annotations"].append({
                "annotation_id": f"MAT-TEST-{len(ledger['annotations']) + 1:03d}",
                "candidate_id": candidate_id,
                "candidate_identity_fingerprint": candidate_identity_fingerprint(collection, item),
                "material": material,
                "decision": "material" if material else "excluded",
                "material_reason": reason,
                "reviewer": "offline-test-reviewer",
                "annotated_at": annotated_at,
            })
    ledger["updated_at"] = annotated_at
    apply_materiality_annotations(ledger, str(task["task_id"]), candidates)
    return ledger


def routes(requirements: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (str(route["provider"]), str(route["operation"]))
        for requirement in requirements
        for route in requirement.get("routes", [])
    }


def current_policy_contract() -> dict[str, Any]:
    """Canonical policy identity fields for hand-built current-schema fixtures."""
    return {
        "free_policy": active_free_policy(),
        "free_policy_revision": FREE_POLICY_REVISION,
        "serper_free_enhancement": {
            "enabled": False, "role": "discovery_only", "max_queries_per_task": 10,
        },
        "signa_free_enhancement": {
            "enabled": False, "role": "discovery_only",
            "max_queries_per_task": SIGNA_FREE_MAX_QUERIES_PER_TASK,
            "authoritative_for_final_rating": False,
        },
        "serpapi_free_enhancement": {
            "enabled": False, "role": "discovery_only", "max_queries_per_task": 3,
            "fallback_only_when_serper_enabled": True,
        },
    }


def test_routing(root: Path) -> None:
    assert SCHEMA_VERSION == "2.3-free"
    assert active_free_policy() == {
        "mode": "official_free_only", "allow_registration": True,
        "allow_commercial_freemium": True,
        "commercial_freemium_mode": "explicit_opt_in",
        "commercial_freemium_default_enabled": [],
        "commercial_freemium_opt_in": ["serper", "signa", "serpapi"],
        "commercial_freemium_allowlist": ["serper", "signa", "serpapi"],
        "allow_paid": False,
        "allow_overage": False, "on_quota_exhausted": "stop_and_report",
    }
    us = build_coverage_requirements(["US"])
    us_routes = routes(us)
    assert {
        ("epo_ops", "search"), ("epo_ops", "candidate_detail"),
        ("uspto_patent_browser", "patent_recall"),
    } <= us_routes
    epo_detail_routes = [
        route for requirement in us for route in requirement.get("routes", [])
        if route.get("provider") == "epo_ops" and route.get("operation") == "candidate_detail"
    ]
    assert epo_detail_routes and all(route.get("required") is False for route in epo_detail_routes)
    assert {("uspto_tmsearch_browser", "trademark_recall"), ("uspto_tsdr", "candidate_verification")} <= us_routes
    assert not ({provider for provider, _ in us_routes} & (WIPO_PROVIDERS | COMMERCIAL_PROVIDERS))

    assert default_jurisdictions("DE") == ["EU", "DE"]
    de = build_coverage_requirements(default_jurisdictions("DE"))
    assert {item["jurisdiction"] for item in de} <= {"EU", "DE"}
    assert {("euipo_design", "search"), ("euipo_trademark", "search"), ("official_registry_browser", "candidate_verification")} <= routes(de)
    for country in ("DE", "FR", "IT", "ES", "PL"):
        country_requirements = build_coverage_requirements(["EU", country])
        utility = {
            item["requirement_id"]: item for item in country_requirements
            if item["right_type"] == "utility_model"
        }
        assert set(utility) == {
            f"COV-{country}-UTILITY-MODEL-RECALL",
            f"COV-{country}-UTILITY-MODEL-VERIFY",
        }
    gb = build_coverage_requirements(["GB"])
    assert gb and {item["jurisdiction"] for item in gb} == {"GB"}
    assert not any(
        route["provider"] in {"euipo_trademark", "euipo_design"}
        for item in gb for route in item["routes"]
    )

    fr = routes(build_coverage_requirements(["EU", "FR"]))
    se = routes(build_coverage_requirements(["EU", "SE"]))
    assert ("inpi_api", "search") in fr and ("official_registry_browser", "candidate_verification") in fr
    assert ("prv_open_data", "search") in se and ("official_registry_browser", "candidate_verification") in se
    assert {"inpi_api", "prv_open_data"} <= api_runner.KNOWN_NOT_READY

    jp_requirements = build_coverage_requirements(["JP"])
    utility_verify = next(item for item in jp_requirements if item["requirement_id"] == "COV-JP-UTILITY_MODEL-VERIFY")
    patent_verify = next(item for item in jp_requirements if item["requirement_id"] == "COV-JP-PATENT-VERIFY")
    assert {item["provider"] for item in utility_verify["routes"]} == {"jplatpat_browser"}
    assert {item["provider"] for item in patent_verify["routes"]} == {"jpo_api", "jplatpat_browser"}

    unsupported = new_task(root, "unsupported-at", "https://www.amazon.de/dp/B0FREE2301", "AT")
    task = json.loads((unsupported / "task.json").read_text(encoding="utf-8"))
    assert task["free_policy_revision"] == FREE_POLICY_REVISION
    assert task["serper_free_enhancement"]["enabled"] is False
    assert task["signa_free_enhancement"]["enabled"] is False
    assert task["serpapi_free_enhancement"]["enabled"] is False
    optional_selection = task["checkpoints"]["optional_discovery_selection"]
    assert optional_selection["status"] == "not_selected"
    assert optional_selection["required_for_minimum"] is False
    assert optional_selection["providers"] == {
        "serper": {"enabled": False, "credential_file": ".env", "credential_key": "SERPER_API_KEY"},
        "signa": {"enabled": False, "credential_file": ".env", "credential_key": "SIGNA_API_KEY"},
        "serpapi": {"enabled": False, "credential_file": ".env", "credential_key": "SERPAPI_API_KEY"},
    }
    initial_ledger = json.loads(
        (unsupported / "materiality-annotations.json").read_text(encoding="utf-8")
    )
    assert initial_ledger["task_id"] == task["task_id"] and initial_ledger["annotations"] == []
    assert task["target_jurisdictions"] == ["EU", "AT"]
    assert any(item["jurisdiction"] == "EU" for item in task["coverage_requirements"])
    assert any(gap["error_code"] == "UNSUPPORTED_JURISDICTION_ROUTE" for gap in task["coverage_gaps"])
    assert {("tmview_browser", "trademark_recall"), ("designview_browser", "design_recall")} <= routes(task["coverage_requirements"])


def test_optional_discovery_incomplete_query_contract(root: Path) -> None:
    default_dir = new_task(
        root, "optional-discovery-incomplete-default-off",
        "https://www.amazon.com/dp/B0FREE2330", "US",
    )
    default_task = json.loads((default_dir / "task.json").read_text(encoding="utf-8"))
    plan = {"queries": {
        "serper_patents": [{"query_id": "QRY-OPTIONAL-SERPER"}],
        SERPAPI_PROVIDER: [{
            "query_id": "QRY-OPTIONAL-SERPAPI",
            "fallback_provider": "serper_patents",
            "fallback_query_id": "QRY-OPTIONAL-SERPER",
        }],
    }}
    assert optional_discovery_incomplete_queries(
        default_task, {"source_runs": []}, plan,
    ) == {}

    selected_dir = new_task(
        root, "optional-discovery-incomplete-selected",
        "https://www.amazon.com/dp/B0FREE2331", "US",
        "--enable-serper-free", "--enable-serpapi-free",
    )
    selected_task = json.loads((selected_dir / "task.json").read_text(encoding="utf-8"))
    assert optional_discovery_incomplete_queries(
        selected_task, {"source_runs": []}, plan,
    ) == {
        "serper": ["QRY-OPTIONAL-SERPER"],
        "serpapi": ["QRY-OPTIONAL-SERPAPI"],
    }

    fallback_evidence = {"source_runs": [{
        "provider": "serper_patents", "query_id": "QRY-OPTIONAL-SERPER",
        "status": "no_result",
    }]}
    satisfied = optional_discovery_incomplete_queries(
        selected_task, fallback_evidence, plan,
    )
    assert "serpapi" not in satisfied
    assert satisfied == {}


def test_route_requires_all_exact_planned_queries() -> None:
    requirement_id = "COV-FR-PATENT-RECALL"
    task = {
        "schema_version": SCHEMA_VERSION, "task_id": "TASK-FR-ROUTE-ALL",
        "target_jurisdictions": ["EU", "FR"], **current_policy_contract(),
        "coverage_requirements": build_coverage_requirements(["EU", "FR"]),
        "coverage_gaps": [],
    }
    plan = {"queries": {"inpi_api": [{
        "query_id": "Q1", "q": "mouse pad", "operation": "search",
        "jurisdiction": "FR", "right_type": "patent", "required": True,
        "requirement_ids": [requirement_id],
    }, {
        "query_id": "Q2", "q": "wrist support", "operation": "search",
        "jurisdiction": "FR", "right_type": "patent", "required": True,
        "requirement_ids": [requirement_id],
    }]}}

    def run(query_id: str) -> dict[str, Any]:
        return {
            "run_id": f"RUN-{query_id}", "query_id": query_id,
            "provider": "inpi_api", "operation": "search",
            "jurisdiction": "FR", "right_type": "patent", "status": "no_result",
            "requirement_ids": [requirement_id], "source_environment": "production",
            "authoritative_for_final_rating": True,
        }

    partial = {"source_runs": [run("Q1"), run("UNPLANNED")], "collections": {}}
    assert requirement_id in coverage_requirement_gaps(
        task, partial, {"patents": [], "trademarks": []}, plan,
    )
    complete = {"source_runs": [*partial["source_runs"], run("Q2")], "collections": {}}
    assert requirement_id not in coverage_requirement_gaps(
        task, complete, {"patents": [], "trademarks": []}, plan,
    )


def test_paid_recommendations_require_exhausted_free_routes() -> None:
    requirement_id = "COV-US-PATENT-RECALL"
    task = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "TASK-PAID-FALLBACK-GATE",
        "target_jurisdictions": ["US"],
        **current_policy_contract(),
        "coverage_requirements": build_coverage_requirements(["US"]),
        "coverage_gaps": [],
    }
    plan = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task["task_id"],
        **current_policy_contract(),
        "queries": {
            "epo_ops": [{
                "query_id": "QRY-PAID-EPO", "q": "pn=US* and ta=mouse",
                "operation": "search", "jurisdiction": "US", "right_type": "patent",
                "required": True, "requirement_ids": [requirement_id],
            }],
            "uspto_patent_browser": [{
                "query_id": "QRY-PAID-USPTO", "q": "mouse pad",
                "operation": "patent_recall", "jurisdiction": "US",
                "right_type": "patent", "required": True,
                "requirement_ids": [requirement_id],
            }],
        },
    }

    def run(
        provider: str, operation: str, query_id: str, status: str, error_code: str,
    ) -> dict[str, Any]:
        return {
            "run_id": f"RUN-{query_id}-{error_code or status}",
            "query_id": query_id, "provider": provider, "operation": operation,
            "jurisdiction": "US", "right_type": "patent", "status": status,
            "error_code": error_code, "requirement_ids": [requirement_id],
        }

    assert paid_recommendations(task, [requirement_id], plan, {"source_runs": []}) == []
    only_one_route = {"source_runs": [
        run("epo_ops", "search", "QRY-PAID-EPO", "access_limited", "FREE_QUOTA_EXHAUSTED"),
    ]}
    assert paid_recommendations(task, [requirement_id], plan, only_one_route) == []
    free_remediation_remains = {"source_runs": [
        run("epo_ops", "search", "QRY-PAID-EPO", "access_limited", "AUTH_FAILED"),
        run(
            "uspto_patent_browser", "patent_recall", "QRY-PAID-USPTO",
            "access_limited", "OFFICIAL_REGISTRY_ACCESS_LIMITED",
        ),
    ]}
    assert paid_recommendations(
        task, [requirement_id], plan, free_remediation_remains,
    ) == []

    exhausted = {"source_runs": [
        run("epo_ops", "search", "QRY-PAID-EPO", "success", ""),
        run(
            "uspto_patent_browser", "patent_recall", "QRY-PAID-USPTO",
            "access_limited", "OFFICIAL_REGISTRY_ACCESS_LIMITED",
        ),
    ]}
    recommendations = paid_recommendations(task, [requirement_id], plan, exhausted)
    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation["jurisdiction"] == "US"
    assert recommendation["module"] == "utility_patent"
    assert recommendation["estimated_calls"] == 2
    assert recommendation["free_exhaustion_evidence"] == [
        "OFFICIAL_REGISTRY_ACCESS_LIMITED",
    ]
    assert recommendation["cost_cap"] == {
        "amount": 0,
        "currency": "USD",
        "status": "not_authorized",
        "basis": "current executable cap; obtain a current quote and explicit numeric approval before changing it",
    }
    assert recommendation["authorized_spend_cap"]["amount"] == 0
    assert recommendation["approval_required"] is True
    assert recommendation["automatic_execution"] is False

    unsupported_requirements = build_coverage_requirements(["EU", "AT"])
    unsupported_task = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "TASK-UNSUPPORTED-AT",
        "target_jurisdictions": ["EU", "AT"],
        **current_policy_contract(),
        "coverage_requirements": unsupported_requirements,
        "coverage_gaps": [{
            "error_code": "UNSUPPORTED_JURISDICTION_ROUTE", "jurisdiction": "AT",
        }],
    }
    unsupported_plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": unsupported_task["task_id"],
        **current_policy_contract(),
        "queries": {},
    }
    unsupported_runs: list[dict[str, Any]] = []
    query_number = 0
    for requirement in unsupported_requirements:
        if requirement.get("jurisdiction") != "AT":
            continue
        for route in requirement.get("routes", []):
            query_number += 1
            query_id = f"QRY-AT-FREE-{query_number:02d}"
            provider = str(route["provider"])
            operation = str(route["operation"])
            right_type = str(requirement["right_type"])
            requirement_id_at = str(requirement["requirement_id"])
            unsupported_plan["queries"].setdefault(provider, []).append({
                "query_id": query_id, "q": "controlled discovery",
                "operation": operation, "jurisdiction": "AT",
                "right_type": right_type, "required": True,
                "requirement_ids": [requirement_id_at],
            })
            unsupported_runs.append({
                "run_id": f"RUN-{query_id}", "query_id": query_id,
                "provider": provider, "operation": operation,
                "jurisdiction": "AT", "right_type": right_type,
                "status": "no_result", "error_code": "",
                "requirement_ids": [requirement_id_at],
            })

    unsupported_gap = ["UNSUPPORTED_JURISDICTION_ROUTE:AT"]
    assert paid_recommendations(
        unsupported_task, unsupported_gap, unsupported_plan, {"source_runs": []},
    ) == []
    assert paid_recommendations(
        unsupported_task, unsupported_gap, unsupported_plan,
        {"source_runs": unsupported_runs[:-1]},
    ) == []
    unsupported = paid_recommendations(
        unsupported_task, unsupported_gap, unsupported_plan,
        {"source_runs": unsupported_runs},
    )
    assert len(unsupported) == 1
    assert unsupported[0]["jurisdiction"] == "AT"
    assert unsupported[0]["estimated_calls"] == len(unsupported_runs)
    assert unsupported[0]["free_exhaustion_evidence"] == [
        "UNSUPPORTED_JURISDICTION_ROUTE",
    ]


def test_no_paid_or_wipo_network(root: Path) -> None:
    task_dir = new_task(root, "commercial-guards", "https://www.amazon.com/dp/B0FREE2302", "US")
    task, _ = prepare_product(task_dir)
    task["state"] = "collecting"
    write_json(task_dir / "task.json", task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert not (set(plan["queries"]) & AUTHORIZED_FREE_COMMERCIAL_PROVIDERS)
    assert plan["execution_policy"]["commercial_freemium_allowlist"] == []
    assert plan["execution_policy"]["commercial_providers_enabled"] is False
    assert not any(
        gap.get("provider") in AUTHORIZED_FREE_COMMERCIAL_PROVIDERS
        for gap in task["coverage_gaps"]
    )
    for provider in sorted(WIPO_PROVIDERS):
        assert provider_execution_error(task, provider) == "WIPO_PROVIDER_DISABLED"
    for provider in sorted(COMMERCIAL_PROVIDERS - AUTHORIZED_FREE_COMMERCIAL_PROVIDERS):
        assert provider_execution_error(task, provider) == "COMMERCIAL_PROVIDER_DISABLED"
    for provider in sorted(SERPER_PROVIDERS):
        operation = SERPER_PROVIDER_OPERATIONS[provider]
        assert provider_execution_error(task, provider, operation) == "SERPER_FREE_NOT_ENABLED"
    assert (
        provider_execution_error(task, SIGNA_PROVIDER, SIGNA_OPERATION)
        == "SIGNA_FREE_NOT_ENABLED"
    )
    assert provider_execution_error(
        task, SERPAPI_PROVIDER, SERPAPI_OPERATION,
    ) == "SERPAPI_FREE_NOT_ENABLED"
    mutated = json.loads(json.dumps(task))
    mutated["coverage_requirements"] = [
        item for item in mutated["coverage_requirements"]
        if item.get("phase") == "candidate_verification"
    ][:1]
    assert provider_execution_error(
        mutated, "epo_ops", "search", jurisdiction="US", right_type="patent",
    ) == "COVERAGE_REQUIREMENTS_INVALID"

    env = os.environ.copy()
    env.update({
        "LC_IPR_TEST_MODE": "1", "SERPAPI_BASE_URL": "http://127.0.0.1:9",
        "SERPER_BASE_URL": "http://127.0.0.1:9", "SIGNA_BASE_URL": "http://127.0.0.1:9",
        "RAPIDAPI_USPTO_BASE_URL": "http://127.0.0.1:9",
    })
    commands = (
        ("SERPAPI_FREE_NOT_ENABLED", "serpapi_patents_client.py", "--task-dir", str(task_dir), "--query-id", "QRY-DISABLED"),
        ("SIGNA_FREE_NOT_ENABLED", "signa_client.py", "--task-dir", str(task_dir), "--query-id", "QRY-DISABLED"),
        ("COMMERCIAL_PROVIDER_DISABLED", "rapidapi_uspto_trademark_client.py", "--task-dir", str(task_dir), "--query", "MOCK"),
    )
    for expected, name, *args in commands:
        command(str(SCRIPTS / name), *args, env=env, succeeds=False, contains=expected)
    command(str(SCRIPTS / "blacklist_check.py"), "--task-dir", str(task_dir))
    command(
        str(SCRIPTS / "record_patent_browser_recall.py"), "--task-dir", str(task_dir),
        "--provider", "wipo_patentscope_browser", "--capture", str(root / "absent.json"),
        succeeds=False, contains="WIPO_PROVIDER_DISABLED",
    )

def test_legacy_23_policy_without_revision(root: Path) -> None:
    """A frozen pre-revision 2.3 task stays readable/plannable without migration."""
    task_dir = new_task(
        root, "legacy-23-no-policy-revision",
        "https://www.amazon.com/dp/B0FREE2309", "US",
    )
    task, _ = prepare_product(task_dir)
    task["state"] = "collecting"
    task.pop("free_policy_revision", None)
    task["free_policy"] = {
        "mode": "official_free_only",
        "allow_registration": True,
        "allow_commercial_freemium": True,
        "commercial_freemium_mode": "explicit_opt_in",
        "commercial_freemium_allowlist": ["serper", "serpapi"],
        "allow_paid": False,
        "allow_overage": False,
        "on_quota_exhausted": "stop_and_report",
    }
    task["serper_free_enhancement"] = {
        "enabled": False, "role": "discovery_only", "max_queries_per_task": 10,
    }
    task.pop("signa_free_enhancement", None)
    write_json(task_dir / "task.json", task)

    assert task_free_policy_valid(task)
    assert_active_free_policy(task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert plan["free_policy_revision"] == ""
    assert not (set(plan["queries"]) & ({SIGNA_PROVIDER, SERPAPI_PROVIDER} | SERPER_PROVIDERS))
    assert plan["execution_policy"]["commercial_providers_enabled"] is False


def test_frozen_default_discovery_revision(root: Path) -> None:
    task_dir = new_task(
        root, "frozen-default-discovery-revision",
        "https://www.amazon.com/dp/B0FREE2308", "US",
    )
    task, _ = prepare_product(task_dir)
    task["state"] = "collecting"
    task["free_policy_revision"] = LEGACY_DEFAULT_DISCOVERY_REVISION
    task["free_policy"] = {
        "mode": "official_free_only",
        "allow_registration": True,
        "allow_commercial_freemium": True,
        "commercial_freemium_mode": "default_bounded",
        "commercial_freemium_default_enabled": ["serper", "signa"],
        "commercial_freemium_opt_in": ["serpapi"],
        "commercial_freemium_allowlist": ["serper", "signa", "serpapi"],
        "allow_paid": False,
        "allow_overage": False,
        "on_quota_exhausted": "stop_and_report",
    }
    task["serper_free_enhancement"]["enabled"] = True
    task["signa_free_enhancement"]["enabled"] = True
    write_json(task_dir / "task.json", task)

    assert task_free_policy_valid(task)
    assert_active_free_policy(task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert plan["free_policy_revision"] == LEGACY_DEFAULT_DISCOVERY_REVISION
    assert set(plan["queries"]) & SERPER_PROVIDERS
    assert SIGNA_PROVIDER in plan["queries"]
    assert plan["execution_policy"]["commercial_freemium_allowlist"] == [
        "serper", "signa",
    ]


def test_optional_signa_discovery_contract(root: Path) -> None:
    task_dir = new_task(
        root, "signa-explicit-opt-in",
        "https://www.amazon.com/dp/B0FREE2313", "US,FR,GB,SE",
        "--enable-signa-free",
    )
    task, _ = prepare_product(task_dir)
    task["state"] = "collecting"
    task["query_terms"] = [{
        "value": "MOCK HOLDINGS",
        "kind": "owner",
        "derived_from": "operator.additional_owner",
    }]
    write_json(task_dir / "task.json", task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))

    assert task["free_policy_revision"] == FREE_POLICY_REVISION
    assert task["signa_free_enhancement"] == {
        "enabled": True,
        "role": "discovery_only",
        "max_queries_per_task": SIGNA_FREE_MAX_QUERIES_PER_TASK,
        "authoritative_for_final_rating": False,
    }
    optional_selection = task["checkpoints"]["optional_discovery_selection"]
    assert optional_selection["status"] == "selected"
    assert optional_selection["required_for_minimum"] is False
    assert optional_selection["providers"]["signa"] == {
        "enabled": True, "credential_file": ".env", "credential_key": "SIGNA_API_KEY",
    }
    assert not any(
        provider == SIGNA_PROVIDER
        for provider, _ in routes(task["coverage_requirements"])
    )
    entries = plan["queries"][SIGNA_PROVIDER]
    assert len(entries) == SIGNA_FREE_MAX_QUERIES_PER_TASK == 3
    assert plan["signa_free_enhancement"] == task["signa_free_enhancement"]
    assert plan["execution_policy"]["commercial_freemium_allowlist"] == ["signa"]
    assert not (set(plan["queries"]) & SERPER_PROVIDERS)
    assert SERPAPI_PROVIDER not in plan["queries"]
    config = load_skill_config()
    signa_config = config["providers"][SIGNA_PROVIDER]
    assert signa_config["default_enabled"] is False
    assert signa_config["network_enabled_when_opted_in"] is True
    assert signa_config["allow_paid"] is False
    assert signa_config["allow_overage"] is False
    assert signa_config["allow_automatic_recharge"] is False
    assert "WO" in signa_config["excluded_offices"]

    expected_offices = {"US", "EM", "FR", "GB", "SE"}
    for item in entries:
        assert item["operation"] == SIGNA_OPERATION
        assert item["right_type"] == "trademark_word"
        assert item["strategies"] == ["exact", "phonetic", "fuzzy", "prefix"]
        assert item["limit"] == 25
        assert item["options"] == {"include_total": False}
        assert set(item["filters"]["offices"]) == expected_offices
        assert "WO" not in item["filters"]["offices"]
        assert item["required"] is False
        assert item["required_for"] == "discovery_only"
        assert item["requirement_ids"] == []
        assert item["role"] == "discovery_only"
        assert item["execute_by_default"] is True
        assert item["authoritative_for_final_rating"] is False
        assert authorize_signa_free_plan_entry(
            task, plan, item["query_id"],
        )["query_id"] == item["query_id"]
        built = api_command_for(SCRIPTS, task_dir, SIGNA_PROVIDER, item)
        assert "--query-id" in built and item["query_id"] in built
        assert "--query" not in built and "--jurisdiction" not in built

    tampered = json.loads(json.dumps(plan))
    tampered_item = tampered["queries"][SIGNA_PROVIDER][0]
    tampered_item["q"] += " altered"
    try:
        authorize_signa_free_plan_entry(task, tampered, tampered_item["query_id"])
    except ValueError as exc:
        assert "SIGNA_QUERY_ID_CONTENT_MISMATCH" in str(exc)
    else:
        raise AssertionError("tampered Signa query must be rejected")

    wo_tampered = json.loads(json.dumps(plan))
    wo_item = wo_tampered["queries"][SIGNA_PROVIDER][0]
    wo_item["filters"]["offices"].append("WO")
    try:
        authorize_signa_free_plan_entry(task, wo_tampered, wo_item["query_id"])
    except ValueError as exc:
        assert "SIGNA_REQUEST_BOUNDS_INVALID" in str(exc)
    else:
        raise AssertionError("WO must never be accepted as a Signa office")

    over_cap = json.loads(json.dumps(plan))
    over_cap["queries"][SIGNA_PROVIDER].append(
        json.loads(json.dumps(over_cap["queries"][SIGNA_PROVIDER][0]))
    )
    try:
        authorize_signa_free_plan_entry(
            task, over_cap, entries[0]["query_id"],
        )
    except ValueError as exc:
        assert "SIGNA_TASK_QUERY_LIMIT_EXCEEDED" in str(exc)
    else:
        raise AssertionError("Signa must remain bounded to three searches")

    controlled_env = ("LC_IPR_TEST_MODE", "SIGNA_BASE_URL")
    previous_env = {name: os.environ.pop(name, None) for name in controlled_env}
    original_credential = signa_runtime.credential
    try:
        signa_runtime.credential = lambda _config, _name: ""
        missing_payload = signa_runtime.execute(task_dir, entries[0]["query_id"])
    finally:
        signa_runtime.credential = original_credential
        for name, value in previous_env.items():
            if value is not None:
                os.environ[name] = value
    assert missing_payload["status"] == "access_limited"
    assert missing_payload["error_code"] == "AUTH_FAILED"
    missing_task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert missing_task["state"] == "collecting"
    missing_gap = next(
        gap for gap in missing_task["coverage_gaps"]
        if gap.get("provider") == SIGNA_PROVIDER
        and gap.get("error_code") == "AUTH_FAILED"
    )
    assert missing_gap["mandatory"] is False


def test_optional_serper_discovery(root: Path) -> None:
    default_dir = new_task(
        root, "serper-default-off", "https://www.amazon.com/dp/B0FREE2310", "US",
    )
    default_task, _ = prepare_product(default_dir)
    default_task["state"] = "collecting"
    write_json(default_dir / "task.json", default_task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(default_dir))
    default_plan = json.loads((default_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert default_task["serper_free_enhancement"] == {
        "enabled": False, "role": "discovery_only", "max_queries_per_task": 10,
    }
    assert not (set(default_plan["queries"]) & SERPER_PROVIDERS)
    assert default_plan["execution_policy"]["commercial_freemium_allowlist"] == []
    assert default_plan["execution_policy"]["commercial_providers_enabled"] is False
    assert not any(
        gap.get("provider") in SERPER_PROVIDERS
        for gap in default_task["coverage_gaps"]
    )

    task_dir = new_task(
        root, "serper-explicit-opt-in", "https://www.amazon.com/dp/B0FREE2311", "US",
        "--enable-serper-free",
    )
    task, _ = prepare_product(task_dir)
    task["state"] = "collecting"
    write_json(task_dir / "task.json", task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert task["free_policy_revision"] == FREE_POLICY_REVISION
    assert task["serper_free_enhancement"] == {
        "enabled": True, "role": "discovery_only", "max_queries_per_task": 10,
    }
    assert not ({provider for provider, _ in routes(task["coverage_requirements"])} & SERPER_PROVIDERS)
    assert plan["serper_free_enhancement"] == task["serper_free_enhancement"]
    assert plan["free_policy_revision"] == FREE_POLICY_REVISION
    assert plan["execution_policy"]["commercial_providers_enabled"] is True
    assert plan["execution_policy"]["commercial_freemium_allowlist"] == ["serper"]
    assert SIGNA_PROVIDER not in plan["queries"]
    assert SERPAPI_PROVIDER not in plan["queries"]
    assert plan["execution_policy"]["paid_execution_enabled"] is False

    config = load_skill_config()
    serper_config = config["providers"]["serper"]
    assert serper_config["supported_operations"] == ["patents", "search", "images"]
    assert serper_config["default_enabled"] is False
    assert serper_config["network_enabled_when_opted_in"] is True
    assert serper_config["documented_signup_free_queries"] == 2500
    assert serper_config["documented_balance_model"] == "one_time_balance_no_reset_assumed"
    assert serper_config["allow_paid"] is False
    assert serper_config["allow_overage"] is False
    assert serper_config["allow_automatic_recharge"] is False
    expected_limits = SERPER_PROVIDER_QUERY_CAPS
    serper_entries = {
        provider: plan["queries"].get(provider, []) for provider in SERPER_PROVIDERS
    }
    assert all(0 < len(serper_entries[provider]) <= maximum for provider, maximum in expected_limits.items())
    assert sum(map(len, serper_entries.values())) <= 10
    for provider, entries in serper_entries.items():
        operation = SERPER_PROVIDER_OPERATIONS[provider]
        assert provider_execution_error(task, provider, operation) == ""
        assert provider_execution_error(task, provider, "lens") == "PROVIDER_OPERATION_NOT_CONFIGURED"
        for item in entries:
            assert item["operation"] == operation
            assert item["required"] is False
            assert item["required_for"] == "discovery_only"
            assert item["requirement_ids"] == []
            assert item["authoritative_for_final_rating"] is False
            assert item["role"] == "discovery_only"
            assert item["execute_by_default"] is True
            assert authorize_serper_free_plan_entry(
                task, plan, provider, operation, item["query_id"],
            )["query_id"] == item["query_id"]
    for provider in COMMERCIAL_PROVIDERS - AUTHORIZED_FREE_COMMERCIAL_PROVIDERS:
        assert provider_execution_error(task, provider) == "COMMERCIAL_PROVIDER_DISABLED"

    missing_key_dir = new_task(
        root, "serper-missing-key", "https://www.amazon.com/dp/B0FREE2314", "US",
        "--enable-serper-free",
    )
    missing_key_task, _ = prepare_product(missing_key_dir)
    missing_key_task["state"] = "collecting"
    write_json(missing_key_dir / "task.json", missing_key_task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(missing_key_dir))
    missing_key_plan = json.loads(
        (missing_key_dir / "search-plan.json").read_text(encoding="utf-8")
    )
    missing_item = missing_key_plan["queries"]["serper_patents"][0]
    controlled_env = ("LC_IPR_TEST_MODE", "SERPER_BASE_URL")
    previous_env = {name: os.environ.pop(name, None) for name in controlled_env}
    original_credential = serper_runtime.credential
    try:
        serper_runtime.credential = lambda _config, _name: ""
        missing_payload = serper_runtime.execute(missing_key_dir, missing_item["query_id"])
    finally:
        serper_runtime.credential = original_credential
        for name, value in previous_env.items():
            if value is not None:
                os.environ[name] = value
    assert missing_payload["status"] == "access_limited"
    assert missing_payload["error_code"] == "AUTH_FAILED"
    missing_key_task = json.loads(
        (missing_key_dir / "task.json").read_text(encoding="utf-8")
    )
    assert missing_key_task["state"] == "collecting"
    missing_gap = next(
        gap for gap in missing_key_task["coverage_gaps"]
        if gap.get("provider") == "serper_patents"
        and gap.get("error_code") == "AUTH_FAILED"
    )
    assert missing_gap["mandatory"] is False

    secret = "serper-offline-secret-7843"
    received: list[dict[str, Any]] = []
    response_mode = {"quota": False}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            received.append({
                "path": self.path,
                "key": self.headers.get("X-API-KEY", ""),
                "payload": json.loads(body.decode("utf-8")),
            })
            if response_mode["quota"]:
                payload = {"message": "free quota reached", "api_key": secret}
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(429)
            elif self.path.endswith("/images"):
                payload = {
                    "images": [{
                        "title": "Lookalike image", "imageUrl": "https://images.example.test/1.png",
                        "link": "https://seller.example.test/lookalike",
                    }],
                    "api_key": secret,
                }
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
            else:
                payload = {
                    "organic": [{
                        "title": "Discovery candidate",
                        "link": (
                            "https://patents.google.com/patent/US1234567A1/en"
                            if self.path.endswith("/patents")
                            else "https://news.example.test/dispute"
                        ),
                        "snippet": "Unverified third-party discovery result",
                    }],
                    "api_key": secret,
                }
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("X-Credits-Remaining", "2499")
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = os.environ.copy()
    env.update({
        "LC_IPR_TEST_MODE": "1",
        "SERPER_BASE_URL": f"http://127.0.0.1:{server.server_port}",
    })
    try:
        selected = {provider: entries[0] for provider, entries in serper_entries.items()}
        executable_plan = json.loads(json.dumps(plan))
        executable_plan["queries"] = {
            provider: [selected[provider]] for provider in SERPER_PROVIDERS
        }
        write_json(task_dir / "search-plan.json", executable_plan)
        stale_task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        add_gap(
            stale_task, "serper_patents", "US", "access_limited",
            "AUTH_MISSING", "stale optional preflight gap", mandatory=False,
        )
        add_gap(
            stale_task, "serper_patents", "US", "failed",
            "RESPONSE_SCHEMA_CHANGED", "unrelated sibling query failure",
            mandatory=False, query_id="QRY-SERPER-SIBLING-FAILURE",
        )
        write_json(task_dir / "task.json", stale_task)
        result = command(
            str(SCRIPTS / "run_api_plan.py"), "--task-dir", str(task_dir), "--wave", "2",
            env=env,
        )
        runner_payload = json.loads(result.stdout)
        assert runner_payload["scheduled"] == 3
        assert runner_payload["paid_execution_enabled"] is False
        assert runner_payload["serper_free_enhancement_enabled"] is True
        assert {item["status"] for item in runner_payload["results"]} == {"success"}
        assert {item["returncode"] for item in runner_payload["results"]} == {0}
        assert len(received) == 3
        assert {item["path"] for item in received} == {"/patents", "/search", "/images"}
        assert all(item["key"] == serper_runtime.TEST_CREDENTIAL for item in received)
        assert all(set(item["payload"]) == {"q", "num"} for item in received)
        for provider, item in selected.items():
            built = api_command_for(SCRIPTS, task_dir, provider, item)
            assert "--query-id" in built and item["query_id"] in built
            assert "--query" not in built and "--operation" not in built

        evidence = json.loads((task_dir / "evidence.json").read_text(encoding="utf-8"))
        runs = [run for run in evidence["source_runs"] if run["provider"] in SERPER_PROVIDERS]
        assert len(runs) == 3
        assert all(run["requirement_ids"] == [] for run in runs)
        assert all(run["authoritative_for_final_rating"] is False for run in runs)
        assert all(run["source_environment"] == "test_fixture" for run in runs)
        assert all(run["quota"]["network_request_attempted"] is True for run in runs)
        assert all(run["quota"]["X-Credits-Remaining"] == "2499" for run in runs)
        assert all(secret not in json.dumps(run) for run in runs)
        assert all(secret.encode("utf-8") not in Path(raw).read_bytes() for run in runs for raw in run["raw_paths"])
        recovered_task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert not any(
            gap.get("provider") == "serper_patents"
            and gap.get("error_code") == "AUTH_MISSING"
            and not gap.get("query_id")
            for gap in recovered_task["coverage_gaps"]
        )
        assert any(
            gap.get("provider") == "serper_patents"
            and gap.get("error_code") == "RESPONSE_SCHEMA_CHANGED"
            and gap.get("query_id") == "QRY-SERPER-SIBLING-FAILURE"
            for gap in recovered_task["coverage_gaps"]
        )

        write_json(task_dir / "search-plan.json", plan)
        command(str(SCRIPTS / "merge_candidates.py"), "--task-dir", str(task_dir))
        candidates = json.loads((task_dir / "normalized-candidates.json").read_text(encoding="utf-8"))
        serper_rows = [row for row in candidate_rows(candidates) if "serper_patents" in row["sources"]]
        assert serper_rows and all(row["url"] == "" for row in serper_rows)

        provider_cap_tamper = json.loads(json.dumps(plan))
        provider_cap_tamper["queries"] = {
            "serper_patents": [
                json.loads(json.dumps(serper_entries["serper_patents"][index % len(serper_entries["serper_patents"])]))
                for index in range(5)
            ],
            "serper_web": [
                json.loads(json.dumps(serper_entries["serper_web"][index % len(serper_entries["serper_web"])]))
                for index in range(3)
            ],
            "serper_images": [
                json.loads(json.dumps(serper_entries["serper_images"][index % len(serper_entries["serper_images"])]))
                for index in range(2)
            ],
        }
        write_json(task_dir / "search-plan.json", provider_cap_tamper)
        before = len(received)
        command(
            str(SCRIPTS / "serper_client.py"), "--task-dir", str(task_dir),
            "--query-id", provider_cap_tamper["queries"]["serper_web"][0]["query_id"],
            env=env, succeeds=False, contains="SERPER_PROVIDER_QUERY_LIMIT_EXCEEDED",
        )
        assert len(received) == before
        write_json(task_dir / "search-plan.json", plan)

        tampered = json.loads(json.dumps(plan))
        tampered_item = tampered["queries"]["serper_patents"][0]
        tampered_item["q"] += " altered"
        write_json(task_dir / "search-plan.json", tampered)
        before = len(received)
        command(
            str(SCRIPTS / "serper_client.py"), "--task-dir", str(task_dir),
            "--query-id", tampered_item["query_id"], env=env,
            succeeds=False, contains="SERPER_QUERY_ID_CONTENT_MISMATCH",
        )
        assert len(received) == before
        write_json(task_dir / "search-plan.json", plan)
        command(
            str(SCRIPTS / "serper_client.py"), "--task-dir", str(task_dir),
            "--query-id", selected["serper_patents"]["query_id"],
            "--query", "unplanned text", env=env,
            succeeds=False, contains="unrecognized arguments",
        )
        assert len(received) == before

        evidence = json.loads((task_dir / "evidence.json").read_text(encoding="utf-8"))
        used = sum(
            run.get("provider") in SERPER_PROVIDERS
            and (run.get("quota") or {}).get("network_request_attempted") is True
            for run in evidence["source_runs"]
        )
        for index in range(10 - used):
            evidence["source_runs"].append({
                "run_id": f"RUN-SERPER-CAP-{index}",
                "query_id": f"QRY-SERPER-CAP-{index}",
                "provider": "serper_patents", "operation": "patents",
                "status": "success", "quota": {"network_request_attempted": True},
            })
        write_json(task_dir / "evidence.json", evidence)
        capped = command(
            str(SCRIPTS / "serper_client.py"), "--task-dir", str(task_dir),
            "--query-id", selected["serper_patents"]["query_id"], env=env,
        )
        capped_payload = json.loads(capped.stdout)
        assert capped_payload["status"] == "access_limited"
        assert capped_payload["error_code"] == "SERPER_TASK_QUERY_LIMIT_REACHED"
        assert len(received) == before

        quota_dir = new_task(
            root, "serper-quota-stop", "https://www.amazon.com/dp/B0FREE2312", "US",
            "--enable-serper-free",
        )
        quota_task, _ = prepare_product(quota_dir)
        quota_task["state"] = "collecting"
        write_json(quota_dir / "task.json", quota_task)
        command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(quota_dir))
        quota_plan = json.loads((quota_dir / "search-plan.json").read_text(encoding="utf-8"))
        quota_entries = [
            item for provider in SERPER_PROVIDERS
            for item in quota_plan["queries"].get(provider, [])
        ]
        response_mode["quota"] = True
        quota_before = len(received)
        exhausted = command(
            str(SCRIPTS / "serper_client.py"), "--task-dir", str(quota_dir),
            "--query-id", quota_entries[0]["query_id"], env=env,
        )
        exhausted_payload = json.loads(exhausted.stdout)
        assert exhausted_payload["status"] == "access_limited"
        assert exhausted_payload["error_code"] == "FREE_QUOTA_EXHAUSTED"
        assert len(received) == quota_before + 1
        failed_task = json.loads((quota_dir / "task.json").read_text(encoding="utf-8"))
        assert failed_task["state"] == "collecting"
        discovery_gap = next(
            gap for gap in failed_task["coverage_gaps"]
            if gap.get("provider") in SERPER_PROVIDERS
            and gap.get("error_code") == "FREE_QUOTA_EXHAUSTED"
        )
        assert discovery_gap["mandatory"] is False
        response_mode["quota"] = False
        stopped = command(
            str(SCRIPTS / "serper_client.py"), "--task-dir", str(quota_dir),
            "--query-id", quota_entries[-1]["query_id"], env=env,
        )
        stopped_payload = json.loads(stopped.stdout)
        assert stopped_payload["status"] == "access_limited"
        assert stopped_payload["error_code"] == "FREE_QUOTA_EXHAUSTED"
        assert len(received) == quota_before + 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    for directory in (task_dir, missing_key_dir, root / "serper-quota-stop"):
        assert all(
            secret.encode("utf-8") not in path.read_bytes()
            for path in directory.rglob("*") if path.is_file()
        )


def test_serpapi_free_opt_in_and_fallback(root: Path) -> None:
    default_dir = new_task(
        root, "serpapi-default-off", "https://www.amazon.com/dp/B0FREE2320", "US",
    )
    default_task, _ = prepare_product(default_dir)
    default_task["state"] = "collecting"
    write_json(default_dir / "task.json", default_task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(default_dir))
    default_plan = json.loads((default_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert default_task["serpapi_free_enhancement"] == {
        "enabled": False, "role": "discovery_only", "max_queries_per_task": 3,
        "fallback_only_when_serper_enabled": True,
    }
    assert not (set(default_plan["queries"]) & AUTHORIZED_FREE_COMMERCIAL_PROVIDERS)
    assert default_plan["execution_policy"]["commercial_freemium_allowlist"] == []

    task_dir = new_task(
        root, "serpapi-explicit-opt-in", "https://www.amazon.com/dp/B0FREE2321", "US",
        "--enable-serpapi-free",
    )
    task, _ = prepare_product(task_dir)
    task["state"] = "collecting"
    write_json(task_dir / "task.json", task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    entries = plan["queries"][SERPAPI_PROVIDER]
    assert 0 < len(entries) <= SERPAPI_FREE_MAX_QUERIES_PER_TASK
    assert plan["execution_policy"]["commercial_freemium_allowlist"] == ["serpapi"]
    assert not (set(plan["queries"]) & SERPER_PROVIDERS)
    assert SIGNA_PROVIDER not in plan["queries"]
    for item in entries:
        assert item["required"] is False
        assert item["required_for"] == "discovery_only"
        assert item["requirement_ids"] == []
        assert item["authoritative_for_final_rating"] is False
        assert item["num"] == 100
        assert authorize_serpapi_free_plan_entry(
            task, plan, SERPAPI_OPERATION, item["query_id"],
        )["query_id"] == item["query_id"]
    assert provider_execution_error(task, SERPAPI_PROVIDER, SERPAPI_OPERATION) == ""
    assert provider_execution_error(task, SERPAPI_PROVIDER, "lens") == "PROVIDER_OPERATION_NOT_CONFIGURED"

    config = load_skill_config()
    provider_config = config["providers"]["serpapi"]
    assert provider_config["default_enabled"] is False
    assert provider_config["network_enabled_when_opted_in"] is True
    assert provider_config["documented_free_searches_per_month"] == 250
    assert provider_config["account_api_unmetered"] is True
    assert provider_config["free_plan_only"] is True
    assert provider_config["allow_automatic_early_renewal"] is False
    assert provider_config["allow_extra_credits"] is False
    assert provider_config["allow_paid"] is False
    assert provider_config["allow_overage"] is False

    missing_key_dir = new_task(
        root, "serpapi-missing-key", "https://www.amazon.com/dp/B0FREE2326", "US",
        "--enable-serpapi-free",
    )
    missing_key_task, _ = prepare_product(missing_key_dir)
    missing_key_task["state"] = "collecting"
    write_json(missing_key_dir / "task.json", missing_key_task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(missing_key_dir))
    missing_key_plan = json.loads(
        (missing_key_dir / "search-plan.json").read_text(encoding="utf-8")
    )
    missing_item = missing_key_plan["queries"][SERPAPI_PROVIDER][0]
    controlled_env = ("LC_IPR_TEST_MODE", "SERPAPI_BASE_URL")
    previous_env = {name: os.environ.pop(name, None) for name in controlled_env}
    original_credential = serpapi_runtime.credential
    try:
        serpapi_runtime.credential = lambda _config, _name: ""
        missing_payload = serpapi_runtime.execute(
            missing_key_dir, missing_item["query_id"],
        )
    finally:
        serpapi_runtime.credential = original_credential
        for name, value in previous_env.items():
            if value is not None:
                os.environ[name] = value
    assert missing_payload["status"] == "access_limited"
    assert missing_payload["error_code"] == "AUTH_FAILED"
    missing_key_task = json.loads(
        (missing_key_dir / "task.json").read_text(encoding="utf-8")
    )
    assert missing_key_task["state"] == "collecting"
    missing_gap = next(
        gap for gap in missing_key_task["coverage_gaps"]
        if gap.get("provider") == SERPAPI_PROVIDER
        and gap.get("error_code") == "AUTH_FAILED"
    )
    assert missing_gap["mandatory"] is False

    secret = "serpapi-offline-secret-9231"
    received: list[str] = []
    mode = {"plan_name": "Free Plan", "price": "0.00", "omit_extra_credits": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            received.append(self.path)
            if self.path.startswith("/account.json"):
                payload = {
                    "account_status": "Active",
                    "plan_name": mode["plan_name"],
                    "plan_monthly_price": mode["price"],
                    "searches_per_month": 250,
                    "plan_searches_left": 249,
                    "extra_credits": 0,
                    "this_month_usage": 1,
                    "plan_renewal_date": "2026-10-01",
                    "api_key": secret,
                }
                if mode["omit_extra_credits"]:
                    payload.pop("extra_credits")
            elif self.path.startswith("/search.json"):
                payload = {
                    "search_metadata": {"status": "Success"},
                    "organic_results": [{
                        "publication_number": "US-1234567-A1",
                        "title": "Cat paw support",
                        "snippet": "Unverified Google Patents discovery result",
                        "patent_link": "https://patents.google.com/patent/US1234567A1/en",
                    }],
                    "api_key": secret,
                }
            else:
                self.send_response(404)
                self.end_headers()
                return
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = os.environ.copy()
    env.update({
        "LC_IPR_TEST_MODE": "1",
        "SERPAPI_BASE_URL": f"http://127.0.0.1:{server.server_port}",
    })
    try:
        selected = entries[0]
        executable = json.loads(json.dumps(plan))
        executable["queries"] = {SERPAPI_PROVIDER: [selected]}
        if selected.get("fallback_query_id"):
            executable["queries"]["serper_patents"] = [next(
                item for item in plan["queries"]["serper_patents"]
                if item["query_id"] == selected["fallback_query_id"]
            )]
        write_json(task_dir / "search-plan.json", executable)
        stale_task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        add_gap(
            stale_task, SERPAPI_PROVIDER, "US", "access_limited",
            "AUTH_MISSING", "stale optional preflight gap", mandatory=False,
        )
        add_gap(
            stale_task, SERPAPI_PROVIDER, "US", "failed",
            "RESPONSE_SCHEMA_CHANGED", "unrelated sibling query failure",
            mandatory=False, query_id="QRY-SERPAPI-SIBLING-FAILURE",
        )
        write_json(task_dir / "task.json", stale_task)
        response = command(
            str(SCRIPTS / "serpapi_patents_client.py"), "--task-dir", str(task_dir),
            "--query-id", selected["query_id"], env=env,
        )
        assert json.loads(response.stdout)["status"] == "success"
        assert len(received) == 2
        assert received[0].startswith("/account.json?")
        assert received[1].startswith("/search.json?")
        evidence = json.loads((task_dir / "evidence.json").read_text(encoding="utf-8"))
        run = next(run for run in evidence["source_runs"] if run["provider"] == SERPAPI_PROVIDER)
        assert run["requirement_ids"] == []
        assert run["authoritative_for_final_rating"] is False
        assert run["quota"]["network_request_attempted"] is True
        assert run["quota"]["plan_name"] == "Free Plan"
        assert run["quota"]["plan_searches_left"] == 249
        recovered_task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        assert not any(
            gap.get("provider") == SERPAPI_PROVIDER
            and gap.get("error_code") == "AUTH_MISSING"
            and not gap.get("query_id")
            for gap in recovered_task["coverage_gaps"]
        )
        assert any(
            gap.get("provider") == SERPAPI_PROVIDER
            and gap.get("error_code") == "RESPONSE_SCHEMA_CHANGED"
            and gap.get("query_id") == "QRY-SERPAPI-SIBLING-FAILURE"
            for gap in recovered_task["coverage_gaps"]
        )
        assert all(
            secret.encode("utf-8") not in path.read_bytes()
            for path in task_dir.rglob("*") if path.is_file()
        )

        # A direct CLI retry of the same query must not consume search quota.
        before = len(received)
        duplicate = command(
            str(SCRIPTS / "serpapi_patents_client.py"), "--task-dir", str(task_dir),
            "--query-id", selected["query_id"], env=env,
        )
        assert json.loads(duplicate.stdout)["error_code"] == "FREE_SEARCH_ALREADY_RESERVED"
        assert len(received) == before
        # Different original planned queries still reach the per-task cap.
        assert len(entries) == 3
        executable["queries"][SERPAPI_PROVIDER].extend(entries[1:])
        write_json(task_dir / "search-plan.json", executable)
        for other in entries[1:]:
            repeated = command(
                str(SCRIPTS / "serpapi_patents_client.py"), "--task-dir", str(task_dir),
                "--query-id", other["query_id"], env=env,
            )
            assert json.loads(repeated.stdout)["status"] == "success"
        before = len(received)
        capped = command(
            str(SCRIPTS / "serpapi_patents_client.py"), "--task-dir", str(task_dir),
            "--query-id", selected["query_id"], env=env,
        )
        capped_payload = json.loads(capped.stdout)
        assert capped_payload["status"] == "access_limited"
        assert capped_payload["error_code"] == "SERPAPI_TASK_QUERY_LIMIT_REACHED"
        assert len(received) == before

        paid_dir = new_task(
            root, "serpapi-paid-block", "https://www.amazon.com/dp/B0FREE2322", "US",
            "--enable-serpapi-free",
        )
        paid_task, _ = prepare_product(paid_dir)
        paid_task["state"] = "collecting"
        write_json(paid_dir / "task.json", paid_task)
        command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(paid_dir))
        paid_plan = json.loads((paid_dir / "search-plan.json").read_text(encoding="utf-8"))
        paid_item = paid_plan["queries"][SERPAPI_PROVIDER][0]
        mode["plan_name"] = "Starter"
        mode["price"] = 25
        before = len(received)
        blocked = command(
            str(SCRIPTS / "serpapi_patents_client.py"), "--task-dir", str(paid_dir),
            "--query-id", paid_item["query_id"], env=env,
        )
        blocked_payload = json.loads(blocked.stdout)
        assert blocked_payload["status"] == "access_limited"
        assert blocked_payload["error_code"] == "PAID_PLAN_REQUIRED"
        assert len(received) == before + 1
        blocked_evidence = json.loads((paid_dir / "evidence.json").read_text(encoding="utf-8"))
        blocked_run = next(
            run for run in blocked_evidence["source_runs"]
            if run["provider"] == SERPAPI_PROVIDER
        )
        assert blocked_run["quota"]["network_request_attempted"] is False
        mode["plan_name"] = "Free"
        mode["price"] = "0.00"

        lookalike_dir = new_task(
            root, "serpapi-plan-lookalike-block", "https://www.amazon.com/dp/B0FREE2325", "US",
            "--enable-serpapi-free",
        )
        lookalike_task, _ = prepare_product(lookalike_dir)
        lookalike_task["state"] = "collecting"
        write_json(lookalike_dir / "task.json", lookalike_task)
        command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(lookalike_dir))
        lookalike_plan = json.loads(
            (lookalike_dir / "search-plan.json").read_text(encoding="utf-8")
        )
        lookalike_item = lookalike_plan["queries"][SERPAPI_PROVIDER][0]
        mode["plan_name"] = "Free Plan Plus"
        before = len(received)
        blocked = command(
            str(SCRIPTS / "serpapi_patents_client.py"), "--task-dir", str(lookalike_dir),
            "--query-id", lookalike_item["query_id"], env=env,
        )
        blocked_payload = json.loads(blocked.stdout)
        assert blocked_payload["status"] == "access_limited"
        assert blocked_payload["error_code"] == "PAID_PLAN_REQUIRED"
        assert len(received) == before + 1
        mode["plan_name"] = "Free"

        unknown_credit_dir = new_task(
            root, "serpapi-unknown-extra-credit", "https://www.amazon.com/dp/B0FREE2324", "US",
            "--enable-serpapi-free",
        )
        unknown_credit_task, _ = prepare_product(unknown_credit_dir)
        unknown_credit_task["state"] = "collecting"
        write_json(unknown_credit_dir / "task.json", unknown_credit_task)
        command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(unknown_credit_dir))
        unknown_credit_plan = json.loads(
            (unknown_credit_dir / "search-plan.json").read_text(encoding="utf-8")
        )
        unknown_credit_item = unknown_credit_plan["queries"][SERPAPI_PROVIDER][0]
        mode["omit_extra_credits"] = True
        before = len(received)
        blocked = command(
            str(SCRIPTS / "serpapi_patents_client.py"), "--task-dir", str(unknown_credit_dir),
            "--query-id", unknown_credit_item["query_id"], env=env,
        )
        blocked_payload = json.loads(blocked.stdout)
        assert blocked_payload["status"] == "failed"
        assert blocked_payload["error_code"] == "RESPONSE_SCHEMA_CHANGED"
        assert len(received) == before + 1
        mode["omit_extra_credits"] = False

        fallback_dir = new_task(
            root, "serpapi-fallback-skip", "https://www.amazon.com/dp/B0FREE2323", "US",
            "--enable-serper-free", "--enable-serpapi-free",
        )
        fallback_task, _ = prepare_product(fallback_dir)
        fallback_task["state"] = "collecting"
        write_json(fallback_dir / "task.json", fallback_task)
        command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(fallback_dir))
        fallback_plan = json.loads((fallback_dir / "search-plan.json").read_text(encoding="utf-8"))
        serpapi_item = next(
            item for item in fallback_plan["queries"][SERPAPI_PROVIDER]
            if item.get("fallback_query_id")
        )
        serper_item = next(
            item for item in fallback_plan["queries"]["serper_patents"]
            if item["query_id"] == serpapi_item["fallback_query_id"]
        )
        fallback_plan["queries"] = {
            **{
                provider: json.loads(json.dumps(fallback_plan["queries"][provider]))
                for provider in SERPER_PROVIDERS
            },
            SERPAPI_PROVIDER: [serpapi_item],
        }
        write_json(fallback_dir / "search-plan.json", fallback_plan)
        for provider in SERPER_PROVIDERS:
            operation = SERPER_PROVIDER_OPERATIONS[provider]
            evidence_type = (
                "patent" if operation == "patents" else
                "enforcement" if operation == "search" else "copyright"
            )
            for item in fallback_plan["queries"][provider]:
                provider_runtime.record_result(
                    fallback_dir,
                    provider=provider,
                    operation=operation,
                    query=str(item["q"]),
                    jurisdiction=str(item["jurisdiction"]),
                    evidence_type=evidence_type,
                    status="not_applicable",
                    normalized=None,
                    detail="offline fixture: primary Serper discovery is already complete",
                    mandatory=False,
                    request_params={
                        "q": item["q"], "num": item["num"],
                        "right_type": item["right_type"],
                    },
                    query_id=str(item["query_id"]),
                    quota={"network_request_attempted": False},
                    source_environment="test_fixture",
                    authoritative_for_final_rating=False,
                )
        assert any(
            run.get("query_id") == serper_item["query_id"]
            and run.get("status") == "not_applicable"
            for run in json.loads(
                (fallback_dir / "evidence.json").read_text(encoding="utf-8")
            )["source_runs"]
        )
        before = len(received)
        direct_skip = command(
            str(SCRIPTS / "serpapi_patents_client.py"), "--task-dir", str(fallback_dir),
            "--query-id", serpapi_item["query_id"], env=env,
        )
        assert json.loads(direct_skip.stdout)["status"] == "not_applicable"
        assert len(received) == before
        runner = command(
            str(SCRIPTS / "run_api_plan.py"), "--task-dir", str(fallback_dir),
            "--wave", "2", env=env,
        )
        runner_payload = json.loads(runner.stdout)
        assert runner_payload["scheduled"] == 1
        assert runner_payload["serpapi_free_enhancement_enabled"] is True
        assert runner_payload["results"][0]["status"] == "not_applicable"
        assert len(received) == before

        unbound = json.loads(json.dumps(fallback_plan))
        unbound_item = unbound["queries"][SERPAPI_PROVIDER][0]
        for key in ("execute_when", "fallback_provider", "fallback_query_id"):
            unbound_item.pop(key, None)
        try:
            authorize_serpapi_free_plan_entry(
                fallback_task, unbound, SERPAPI_OPERATION, unbound_item["query_id"],
            )
        except ValueError as exc:
            assert "SERPAPI_FALLBACK_BINDING_REQUIRED" in str(exc)
        else:
            raise AssertionError("matching Serper query must remain bound as the primary lane")

        tampered = json.loads(json.dumps(fallback_plan))
        tampered_item = tampered["queries"][SERPAPI_PROVIDER][0]
        tampered_item["q"] += " altered"
        try:
            authorize_serpapi_free_plan_entry(
                fallback_task, tampered, SERPAPI_OPERATION, tampered_item["query_id"],
            )
        except ValueError as exc:
            assert "SERPAPI_QUERY_ID_CONTENT_MISMATCH" in str(exc)
        else:
            raise AssertionError("tampered SerpApi query must be rejected")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_redaction_and_runner_output_contract() -> None:
    secrets = {
        "cookie": "cookie-value-71",
        "set_cookie": "set-cookie-value-72",
        "ibm": "ibm-client-value-73",
        "api": "api-key-value-74",
        "client": "client-id-value-75",
        "consumer": "consumer-key-value-76",
        "token": "token-value-77",
        "secret": "secret-value-78",
        "password": "password-value-79",
        "user": "user-value-80",
    }
    for variant in (
        "COOKIE", "set_cookie", "X_IBM_CLIENT_ID", "x-api-key", "ClientId",
        "consumer-key", "authToken", "private_secret", "PASSWORD_HASH", "end-user",
        "JPO_API_USERNAME", "EPO_OPS_CONSUMER_KEY", "AWS_ACCESS_KEY_ID",
    ):
        assert provider_runtime.is_sensitive_key(variant), variant
    assert not provider_runtime.is_sensitive_key("User-Agent")
    text = "\n".join((
        f"Cookie: session={secrets['cookie']}; theme=dark",
        f"sEt-CoOkIe: sid={secrets['set_cookie']}; HttpOnly",
        f"X-IBM-Client-Id: {secrets['ibm']}",
        f"x_api_key={secrets['api']}",
        f"client-ID={secrets['client']}",
        f"consumer_key={secrets['consumer']}",
        f'{{"accessToken":"{secrets["token"]}"}}',
        f"client-secret: {secrets['secret']}",
        f"--PASSWORD {secrets['password']}",
        f"User_Name={secrets['user']}",
        "User-Agent: safe-offline-agent",
    ))
    redacted_text = provider_runtime.redact_sensitive_text(text)
    assert all(secret not in redacted_text for secret in secrets.values())
    assert redacted_text.count(provider_runtime.REDACTED) >= len(secrets)
    assert "User-Agent: safe-offline-agent" in redacted_text
    nested_text = provider_runtime.redact_sensitive_text(
        f"headers={{'Cookie': '{secrets['cookie']}', "
        f"'X_IBM_CLIENT_ID': '{secrets['ibm']}'}}"
    )
    assert secrets["cookie"] not in nested_text and secrets["ibm"] not in nested_text

    safe_url = provider_runtime.sanitize_evidence_url(
        "https://url-user:url-password@example.test/path?q=mouse-pad"
        "&CLIENT-ID=url-client&consumer_key=url-consumer&AccessToken=url-token"
        "&safe=kept#password=url-fragment"
    )
    for secret in (
        "url-user", "url-password", "url-client", "url-consumer", "url-token",
        "url-fragment",
    ):
        assert secret not in safe_url
    assert safe_url.startswith("https://example.test/path?")
    assert "q=mouse-pad" in safe_url and "safe=kept" in safe_url
    assert "#" not in safe_url
    embedded = provider_runtime.redact_sensitive_text(
        "failed at https://example.test/a?X-API-KEY=embedded-api&q=kept."
    )
    assert "embedded-api" not in embedded and "q=kept" in embedded

    safe_headers = provider_runtime.sanitize_headers({
        "Cookie": secrets["cookie"],
        "SET_COOKIE": secrets["set_cookie"],
        "X_IBM_CLIENT_ID": secrets["ibm"],
        "x-api-key": secrets["api"],
        "Authorization": f"Bearer {secrets['token']}",
        "User-Agent": "safe-offline-agent",
    })
    assert all(
        value == provider_runtime.REDACTED
        for key, value in safe_headers.items()
        if key != "User-Agent"
    )
    assert safe_headers["User-Agent"] == "safe-offline-agent"

    request_params = provider_runtime.sanitized_request_params({
        "q": "mouse pad", "CLIENT_ID": secrets["client"],
        "consumer-key": secrets["consumer"], "nested": {
            "RefreshToken": secrets["token"], "safe": "kept",
        },
    })
    assert request_params == {"nested": {"safe": "kept"}, "q": "mouse pad"}

    json_body = json.dumps({
        "headers": {"Set-Cookie": secrets["set_cookie"]},
        "client_id": secrets["client"],
        "nested": {"consumerKey": secrets["consumer"], "safe": "kept"},
        "url": "https://example.test/?token=body-url-token&safe=kept",
    }).encode()
    safe_json = json.loads(provider_runtime.sanitize_raw_evidence(json_body, "json"))
    assert safe_json["headers"]["Set-Cookie"] == provider_runtime.REDACTED
    assert safe_json["client_id"] == provider_runtime.REDACTED
    assert safe_json["nested"]["consumerKey"] == provider_runtime.REDACTED
    assert safe_json["nested"]["safe"] == "kept"
    assert "body-url-token" not in safe_json["url"]

    with tempfile.TemporaryDirectory(prefix="lc-ipr-redaction-record-") as temporary:
        task_dir = Path(temporary)
        task = {
            "schema_version": SCHEMA_VERSION,
            "task_id": "TASK-REDACTION-OFFLINE",
            "state": "collecting",
            "target_jurisdictions": ["US"],
            **current_policy_contract(),
            "coverage_requirements": build_coverage_requirements(["US"]),
            "coverage_gaps": [],
            "history": [],
        }
        write_json(task_dir / "task.json", task)
        write_json(task_dir / "evidence.json", {
            "schema_version": SCHEMA_VERSION,
            "task_id": task["task_id"],
            "source_runs": [],
            "collections": {"blacklist": []},
        })
        query_secret = "query-token-value-82"
        recorded = provider_runtime.record_result(
            task_dir,
            provider="local_high_risk_ip",
            operation="blacklist_check",
            query=f"mouse pad?token={query_secret}",
            jurisdiction="US",
            evidence_type="blacklist",
            status="success",
            normalized={"headers": {"Cookie": secrets["cookie"]}, "safe": "kept"},
            raw_body=json_body,
            raw_suffix="json",
            request_params={
                "q": "mouse pad", "X-IBM-Client-Id": secrets["ibm"],
                "client_secret": secrets["secret"],
            },
            mandatory=False,
        )
        persisted = (task_dir / "evidence.json").read_text(encoding="utf-8")
        persisted_raw = Path(recorded["raw_paths"][0]).read_text(encoding="utf-8")
        for secret in (*secrets.values(), query_secret, "body-url-token"):
            assert secret not in persisted
            assert secret not in persisted_raw
        assert "X-IBM-Client-Id" not in recorded["request_params"]
        assert "client_secret" not in recorded["request_params"]

    xml_body = (
        f'<root password="{secrets["password"]}">'
        f'<user>{secrets["user"]}</user>'
        f'<client-secret>{secrets["secret"]}</client-secret><safe>kept</safe></root>'
    ).encode()
    safe_xml = provider_runtime.sanitize_raw_evidence(xml_body, "xml").decode()
    assert secrets["password"] not in safe_xml
    assert secrets["user"] not in safe_xml
    assert secrets["secret"] not in safe_xml
    assert "<safe>kept</safe>" in safe_xml
    form_body = provider_runtime.sanitize_raw_evidence(
        (
            f"grant_type=client_credentials&CLIENT-ID={secrets['client']}"
            f"&consumer_key={secrets['consumer']}&safe=kept"
        ).encode(),
        "txt",
    ).decode()
    assert secrets["client"] not in form_body and secrets["consumer"] not in form_body
    assert "safe=kept" in form_body
    assert provider_runtime.sanitize_raw_evidence(PNG, "png") == PNG

    leaked_stream_value = "stream-secret-value-81" * 40
    bad_result = subprocess.CompletedProcess(
        ["offline-fixture"], 1,
        f"X-API-Key: {leaked_stream_value}\nnot-json\n",
        f"Set-Cookie: session={leaked_stream_value}; HttpOnly\n",
    )
    exposed = api_runner.completed_result(
        "epo_ops", {"query_id": "Q-OFFLINE", "q": "mouse pad"}, bad_result,
    )
    assert exposed["status"] == "failed"
    assert leaked_stream_value not in json.dumps(exposed)
    assert provider_runtime.REDACTED in exposed["stderr"]
    assert len(exposed["stderr"]) <= api_runner.EXPOSED_OUTPUT_LIMIT
    assert api_runner.command_status(f"api_key={leaked_stream_value}") == "failed"
    assert api_runner.command_status("success\n") == "success"

    payload_result = subprocess.CompletedProcess(
        ["offline-fixture"], 1,
        json.dumps({
            "status": "access_limited",
            "error_code": f"token={secrets['token']}",
            "fallback_provider": f"client_secret={secrets['secret']}",
        }) + "\n",
        "safe diagnostic " * 100,
    )
    exposed_payload = api_runner.completed_result(
        "jpo_api", {"query_id": "Q-OFFLINE-2", "q": "known number"}, payload_result,
    )
    assert exposed_payload["status"] == "access_limited"
    assert secrets["token"] not in exposed_payload["error_code"]
    assert secrets["secret"] not in exposed_payload["fallback_provider"]
    assert len(exposed_payload["stderr"]) <= api_runner.EXPOSED_OUTPUT_LIMIT
    assert exposed_payload["stderr"].startswith("[truncated]\n")


def test_unicode_and_japanese_plan(root: Path) -> None:
    assert normalize_text("ＡＢＣ 猫 ねこ ネコ") == "abc猫ねこネコ"
    task_dir = new_task(root, "japanese-plan", "https://www.amazon.co.jp/dp/B0FREE2303", "JP")
    task, _ = prepare_product(task_dir, japanese=True)
    task["state"] = "collecting"
    task["query_terms"] = [
        {"value": "猫の肉球", "kind": "original_japanese", "derived_from": "operator.original_name"},
        {"value": "cat paw", "kind": "english", "derived_from": "operator.supplied_translation"},
        {"value": "neko nikukyu", "kind": "romaji", "derived_from": "operator.supplied_romaji"},
        {"value": "neko nikukyu", "kind": "romaji", "derived_from": "catalog.supplied_romaji"},
        {"value": "猫工房株式会社", "kind": "applicant", "derived_from": "operator.applicant"},
        {"value": "G06F 3/039", "kind": "ipc", "scheme": "ipc", "derived_from": "operator.ipc"},
        {"value": "G06F 3/039", "kind": "cpc", "scheme": "cpc", "derived_from": "operator.cpc"},
        {"value": "14-02", "kind": "locarno", "derived_from": "operator.locarno"},
        {"value": "9", "kind": "nice", "derived_from": "operator.nice"},
        {"value": "11C01", "kind": "similar_group", "derived_from": "operator.similar_group"},
        {"value": "ネコニクキュウ", "kind": "pronunciation", "derived_from": "operator.pronunciation"},
        {"value": "ねこのにくきゅう", "kind": "reading", "derived_from": "operator.reading"},
        {
            "value": "03.01.01", "kind": "figurative_classification",
            "scheme": "jpo_figurative_classification",
            "derived_from": "operator.jpo_figurative_classification",
        },
    ]
    write_json(task_dir / "task.json", task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    for value in ("猫の肉球", "cat paw", "neko nikukyu"):
        assert any(
            item["value"] == value and item["derived_from"].startswith("operator.")
            for item in plan["terms"]
        )
    class_terms = [item for item in plan["terms"] if item["kind"] == "classification"]
    assert class_terms and all(item["derived_from"].startswith("rule:CLASS_HINTS") for item in class_terms)
    assert {"epo_ops", "jplatpat_browser", "public_web_browser"} <= set(plan["queries"])
    first_queries = json.loads(json.dumps(plan["queries"], ensure_ascii=False, sort_keys=True))
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))
    rerun = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert rerun["queries"] == first_queries
    epo = plan["queries"]["epo_ops"]
    assert {item["right_type"] for item in epo} == {"patent", "utility_model"}
    assert {item["operation"] for item in epo} == {"search"}
    assert len(epo) <= 6 and all(item["required"] for item in epo)
    for value in ("猫の肉球", "cat paw", "neko nikukyu", "猫工房株式会社", "G06F 3/039"):
        assert any(value in item["q"] for item in epo)
    assert any('cpc="G06F 3/039"' in item["q"] for item in epo)
    jp_entries = plan["queries"]["jplatpat_browser"]
    expected_bindings = {
        ("patent", "patent_recall"),
        ("utility_model", "utility_model_recall"),
        ("design", "design_recall"),
        ("trademark_word", "trademark_recall"),
        ("trademark_figurative", "trademark_recall"),
    }
    assert {(item["right_type"], item["operation"]) for item in jp_entries} == expected_bindings
    assert all(item["required"] and item["requirement_ids"] for item in jp_entries)
    per_right = {
        right_type: [item for item in jp_entries if item["right_type"] == right_type]
        for right_type, _ in expected_bindings
    }
    assert all(len(items) <= 12 for items in per_right.values())
    routed_sources = {
        source for item in [*epo, *jp_entries] for source in item.get("derived_from", [])
    }
    assert {
        "operator.original_name", "operator.supplied_translation", "operator.supplied_romaji",
        "catalog.supplied_romaji", "operator.applicant", "operator.ipc", "operator.cpc",
        "operator.locarno", "operator.nice", "operator.similar_group",
        "operator.pronunciation", "operator.reading", "operator.jpo_figurative_classification",
    } <= routed_sources
    for kind in ("english", "romaji"):
        assert {
            item["value"] for item in plan["terms"] if item.get("kind") == kind
        } == {
            item["value"] for item in task["query_terms"] if item.get("kind") == kind
        }
    assert plan["classification_candidates"]["locarno"] == ["14-02"]
    assert "11C01" in plan["classification_candidates"]["similar_group"]
    assert all(
        ("pn=JP*" in item["q"] and "pn=WO*" in item["q"])
        if item["right_type"] == "patent" else
        ("pn=JP*" in item["q"] and "pn=WO*" not in item["q"])
        for item in plan["queries"]["epo_ops"]
    )
    assert "jpo_api" not in plan["queries"]
    assert not (set(plan["queries"]) & (WIPO_PROVIDERS | COMMERCIAL_PROVIDERS))
    assert any(item["right_type"] == "utility_model" for item in plan["queries"]["jplatpat_browser"])
    append_jp_candidate_verification_actions(task_dir, task, [{
        "candidate_id": "C-JP-PAT", "jurisdiction": "JP", "right_type": "patent",
        "publication_number": "JP2021022359A", "material": True,
    }, {
        "candidate_id": "C-JP-UM", "jurisdiction": "JP", "right_type": "utility_model",
        "registration_number": "3234567", "material": True,
    }], [])
    candidate_plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert any(
        item.get("candidate_id") == "C-JP-PAT" and item.get("execute_by_default") is True
        for item in candidate_plan["queries"]["jpo_api"]
    )
    assert not any(
        item.get("candidate_id") == "C-JP-UM"
        for item in candidate_plan["queries"]["jpo_api"]
    )
    assert any(
        item.get("candidate_id") == "C-JP-UM"
        and item.get("operation") == "candidate_verification"
        for item in candidate_plan["queries"]["jplatpat_browser"]
    )
    figurative = [
        item for item in plan["queries"]["jplatpat_browser"]
        if item["right_type"] == "trademark_figurative"
    ]
    assert {item["q"] for item in figurative} == {"03.01.01"}
    assert all(item["classification_scheme"] == "jpo_figurative_classification" for item in figurative)


def test_query_plan_right_type_binding(root: Path) -> None:
    gb_dir = new_task(root, "gb-only-plan", "https://www.amazon.co.uk/dp/B0FREE2306", "GB")
    gb_task, _ = prepare_product(gb_dir)
    gb_task["state"] = "collecting"
    write_json(gb_dir / "task.json", gb_task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(gb_dir))
    gb_plan = json.loads((gb_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert not ({"euipo_trademark", "euipo_design", "epo_ops"} & set(gb_plan["queries"]))
    assert not any(
        item["right_type"] == "trademark_figurative"
        for entries in gb_plan["queries"].values() for item in entries
    )

    de_dir = new_task(root, "eu-de-plan", "https://www.amazon.de/dp/B0FREE2307", "DE")
    de_task, _ = prepare_product(de_dir)
    assert de_task["target_jurisdictions"] == ["EU", "DE"]
    de_task["state"] = "collecting"
    de_task["query_terms"] = [
        {
            "value": "01.01.02", "kind": "figurative_classification",
            "scheme": "vienna_classification", "derived_from": "operator.vienna_class",
        },
        {
            "value": "03.01.06", "kind": "figurative_classification",
            "scheme": "uspto_design_code", "derived_from": "operator.uspto_design_code",
        },
    ]
    write_json(de_dir / "task.json", de_task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(de_dir))
    de_plan = json.loads((de_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert all(
        "pn=EP*" in item["q"] and "pn=WO*" in item["q"]
        for item in de_plan["queries"]["epo_ops"]
        if item["right_type"] == "patent"
    )
    euipo_word = [
        item for item in de_plan["queries"]["euipo_trademark"]
        if item["right_type"] == "trademark_word"
    ]
    euipo_figurative = [
        item for item in de_plan["queries"]["euipo_esearch_browser"]
        if item["right_type"] == "trademark_figurative"
    ]
    assert euipo_word and euipo_figurative
    assert {item["q"] for item in euipo_figurative} == {"01.01.02"}
    assert all(item["requirement_ids"] == ["COV-EU-TRADEMARK-WORD-RECALL"] for item in euipo_word)
    assert all(
        item["query"].startswith("wordMarkSpecification.verbalElement==")
        and set(item) >= {"q", "query", "page", "size"}
        for item in euipo_word
    )
    assert all(
        item["requirement_ids"] == ["COV-EU-TRADEMARK-FIGURATIVE-RECALL"]
        and "classification_scheme:vienna_classification" in item["derived_from"]
        for item in euipo_figurative
    )
    assert all(
        item["query_mode"] == "vienna_classification"
        and item["classification_scheme"] == "vienna_classification"
        for item in euipo_figurative
    )
    assert all(
        item["query"].startswith("productIndications==")
        for item in de_plan["queries"]["euipo_design"]
    )
    de_figurative = [
        item for item in de_plan["queries"]["tmview_browser"]
        if item["right_type"] == "trademark_figurative"
    ]
    de_word = [
        item for item in de_plan["queries"]["tmview_browser"]
        if item["right_type"] == "trademark_word"
    ]
    assert {item["q"] for item in de_figurative} == {"01.01.02"}
    assert de_word and all(item["requirement_ids"] == ["COV-DE-TRADEMARK-WORD-DISCOVERY"] for item in de_word)
    assert all(item["requirement_ids"] == ["COV-DE-TRADEMARK-FIGURATIVE-DISCOVERY"] for item in de_figurative)
    national_word = [
        item for item in de_plan["queries"]["official_registry_browser"]
        if item["right_type"] == "trademark_word"
    ]
    assert national_word and all(
        item["requirement_ids"] == ["COV-DE-TRADEMARK-WORD-RECALL"]
        for item in national_word
    )
    utility = [
        item for item in de_plan["queries"]["official_registry_browser"]
        if item["right_type"] == "utility_model"
    ]
    assert utility and all(item["requirement_ids"] == ["COV-DE-UTILITY-MODEL-RECALL"] for item in utility)

    us_dir = new_task(root, "us-figurative-plan", "https://www.amazon.com/dp/B0FREE2308", "US")
    us_task, _ = prepare_product(us_dir)
    us_task["state"] = "collecting"
    us_task["query_terms"] = de_task["query_terms"]
    write_json(us_dir / "task.json", us_task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(us_dir))
    us_plan = json.loads((us_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert all(
        ("pn=US*" in item["q"] and "pn=WO*" in item["q"])
        if item["right_type"] == "patent" else
        ("pn=US*" in item["q"] and "pn=WO*" not in item["q"])
        for item in us_plan["queries"]["epo_ops"]
    )
    us_fig = [
        item for item in us_plan["queries"]["uspto_tmsearch_browser"]
        if item["right_type"] == "trademark_figurative"
    ]
    us_word = [
        item for item in us_plan["queries"]["uspto_tmsearch_browser"]
        if item["right_type"] == "trademark_word"
    ]
    assert {item["q"] for item in us_fig} == {"03.01.06"}
    assert us_word and all(item["requirement_ids"] == ["COV-US-TRADEMARK_WORD-RECALL"] for item in us_word)
    assert all(item["requirement_ids"] == ["COV-US-TRADEMARK_FIGURATIVE-RECALL"] for item in us_fig)
    public_us = us_plan["queries"]["public_web_browser"]
    assert {
        item.get("source_key") for item in public_us
    } == {"copyright_records", "ttabvue", "ptab", "copyright_claims_board"}
    assert all(item["query_id"] and item["requirement_ids"] for item in public_us)
    assert all(
        f"official_source:{item['source_key']}" in item["derived_from"]
        for item in public_us
    )
    ptab_query = next(item for item in public_us if item["source_key"] == "ptab")
    try:
        _recall_plan_binding(
            us_dir, "public_web_browser", "enforcement_recall", "US",
            "enforcement", ptab_query["q"],
            {"query_id": ptab_query["query_id"], "source_key": "ttabvue"},
            {
                "q": ptab_query["q"], "mode": "manual_capture",
                "right_type": "enforcement", "source_key": "ttabvue",
            },
            ptab_query["query_id"],
        )
        raise AssertionError("a PTAB query_id accepted a TTABVUE capture")
    except ValueError as exc:
        assert "source_key" in str(exc)
    public_runs = [{
        "run_id": f"RUN-{item['source_key']}",
        "query_id": item["query_id"],
        "provider": "public_web_browser",
        "operation": item["operation"],
        "jurisdiction": "US",
        "right_type": item["right_type"],
        "status": "no_result",
        "requirement_ids": item["requirement_ids"],
    } for item in public_us]
    partial_public = {
        "source_runs": [
            run for run in public_runs if run["query_id"] != next(
                item["query_id"] for item in public_us if item["source_key"] == "ptab"
            )
        ],
        "collections": {},
    }
    assert "COV-US-ENFORCEMENT-RECALL" in coverage_requirement_gaps(
        us_task, partial_public, {"patents": [], "trademarks": []}, us_plan,
    )
    assert "COV-US-ENFORCEMENT-RECALL" not in coverage_requirement_gaps(
        us_task, {"source_runs": public_runs, "collections": {}},
        {"patents": [], "trademarks": []}, us_plan,
    )


def test_candidate_right_type_binding() -> None:
    runs = {"RUN-EPO-DESIGN": {"right_type": "design", "status": "success"}}
    candidates = merge("patent", [{
        "evidence_id": "EV-EPO-DESIGN", "source_run_id": "RUN-EPO-DESIGN",
        "provider": "epo_ops", "right_type": "design", "payload": [{
            "publication_number": "US1234567S1", "jurisdiction": "US",
            "source": "epo_ops", "material": False,
        }],
    }], runs)
    apply_candidate_contract("patent", candidates)
    assert candidates[0]["right_type"] == "design"
    assert candidates[0]["module"] == "appearance_patent"

    shared_number = "2020008423"
    official = verification_index([
        {
            "evidence_id": "EV-PAT", "payload": {
                "candidate_id": "C-PAT", "right_type": "patent",
                "application_number": shared_number,
                "official_verification": {"status": "verified", "legal_status": "patent-active"},
            },
        },
        {
            "evidence_id": "EV-DESIGN", "payload": {
                "candidate_id": "C-DESIGN", "right_type": "design",
                "application_number": shared_number,
                "official_verification": {"status": "partial", "legal_status": "design-pending"},
            },
        },
    ])
    design_candidates = [{
        "candidate_id": "C-DESIGN", "right_type": "design",
        "application_number": shared_number,
        "official_verification": {"status": "not_checked"},
    }]
    apply_verifications("patent", design_candidates, official)
    assert design_candidates[0]["official_verification"]["legal_status"] == "design-pending"
    assert set(design_candidates[0]["verification_refs"]) == {"EV-DESIGN"}


def test_intrinsic_document_types_and_trademark_keys() -> None:
    assert not _same_candidate(
        {"candidate_id": "C-WORD-A", "serial_number": "87654321"},
        {"candidate_id": "C-WORD-B", "serial_number": "87654321"},
    )
    assert _same_candidate(
        {"candidate_id": "C-WORD-A", "serial_number": "87654321"},
        {"serial_number": "87654321"},
    )
    assert intrinsic_patent_right_type("US", "USD123456S1") == "design"
    assert intrinsic_patent_right_type("JP", "JP2020123456U") == "utility_model"
    assert intrinsic_patent_right_type("WO", "WO2024123456A1") == "patent"
    runs = {
        "RUN-US-PAT": {"right_type": "patent", "status": "success"},
        "RUN-US-DES": {"right_type": "design", "status": "success"},
        "RUN-JP-PAT": {"right_type": "patent", "status": "success"},
        "RUN-JP-UM": {"right_type": "utility_model", "status": "success"},
    }
    entries = [{
        "evidence_id": f"EV-{run_id}", "source_run_id": run_id,
        "provider": "epo_ops", "right_type": runs[run_id]["right_type"],
        "payload": [{
            "publication_number": number, "jurisdiction": jurisdiction,
            "kind_code": kind_code, "source": "epo_ops", "material": False,
        }],
    } for run_id, jurisdiction, number, kind_code in (
        ("RUN-US-PAT", "US", "USD123456S1", "S1"),
        ("RUN-US-DES", "US", "USD123456S1", "S1"),
        ("RUN-JP-PAT", "JP", "JP2020123456U", "U"),
        ("RUN-JP-UM", "JP", "JP2020123456U", "U"),
    )]
    patents = merge("patent", entries, runs)
    apply_candidate_contract("patent", patents)
    assert len(patents) == 2
    assert {
        item["publication_number"]: item["right_type"] for item in patents
    } == {
        "USD123456S1": "design", "JP2020123456U": "utility_model",
    }
    assert all(len(item["sources"]) == 2 for item in patents)

    trademark_runs = {
        "RUN-WORD": {"right_type": "trademark_word", "status": "success"},
        "RUN-FIG": {"right_type": "trademark_figurative", "status": "success"},
    }
    trademarks = merge("trademark", [{
        "evidence_id": "EV-WORD", "source_run_id": "RUN-WORD",
        "right_type": "trademark_word", "payload": [{
            "jurisdiction": "US", "serial_number": "87654321",
            "right_type": "trademark_word", "mark_text": "PAW",
        }],
    }, {
        "evidence_id": "EV-FIG", "source_run_id": "RUN-FIG",
        "right_type": "trademark_figurative", "payload": [{
            "jurisdiction": "US", "serial_number": "87654321",
            "right_type": "trademark_figurative", "mark_text": "PAW",
            "figurative_id": "03.01.06",
        }],
    }], trademark_runs)
    apply_candidate_contract("trademark", trademarks)
    assert len(trademarks) == 2
    assert {item["right_type"] for item in trademarks} == {
        "trademark_word", "trademark_figurative",
    }
    assert len({item["candidate_id"] for item in trademarks}) == 2

    task = {
        "schema_version": SCHEMA_VERSION, "task_id": "TASK-TM-STRICT-TYPE",
        "target_jurisdictions": ["US"], **current_policy_contract(),
        "coverage_requirements": build_coverage_requirements(["US"]),
    }
    for item in trademarks:
        item["material"] = True
        item["verification_refs"] = [f"EV-VERIFY-{item['right_type']}"]
    reviewed_materiality_fixture(task, {"patents": [], "trademarks": trademarks}, {
        item["candidate_id"]: (True, "同号文字与图形权利分别审阅")
        for item in trademarks
    })
    checked_at = now_iso()
    runs: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    for item in trademarks:
        right_type = item["right_type"]
        evidence_id = f"EV-VERIFY-{right_type}"
        requirement_id = f"COV-US-{right_type.upper()}-VERIFY"
        official = {
            "status": "verified", "authority": "USPTO", "method": "cdp_assisted",
            "identity_match": True, "legal_status": "registered", "owner": ["Owner"],
            "classes": ["25"], "media": [], "checked_at": checked_at,
            "url": "https://tsdr.uspto.gov/#caseNumber=87654321",
        }
        item["official_verification"] = official
        run_id = f"RUN-VERIFY-{right_type}"
        runs.append({
            "run_id": run_id, "query_id": f"QRY-{right_type}",
            "provider": "uspto_tsdr", "operation": "candidate_verification",
            "jurisdiction": "US", "right_type": right_type, "status": "success",
            "requirement_ids": [requirement_id],
            "request_params": {
                "candidate_id": item["candidate_id"], "serial_number": "87654321",
            },
        })
        entries.append({
            "evidence_id": evidence_id, "source_run_id": run_id,
            "query_id": f"QRY-{right_type}",
            "provider": "uspto_tsdr", "operation": "candidate_verification",
            "jurisdiction": "US", "right_type": right_type,
            "requirement_ids": [requirement_id], "payload": {
                "candidate_id": item["candidate_id"], "right_type": right_type,
                "serial_number": "87654321", "official_verification": official,
            },
        })
    assert material_unverified(
        {"patents": [], "trademarks": trademarks}, strict=True,
        evidence={"source_runs": runs, "collections": {"official_verifications": entries}},
        task=task,
    ) == [
        next(
            item["candidate_id"] for item in trademarks
            if item["right_type"] == "trademark_figurative"
        )
    ]


def test_epo_candidate_detail_contracts(root: Path) -> None:
    task_dir = new_task(root, "epo-detail", "https://www.amazon.com/dp/B0FREE2309", "US")
    task, _ = prepare_product(task_dir)
    task["state"] = "collecting"
    write_json(task_dir / "task.json", task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))

    assert provider_execution_error(
        task, "epo_ops", "candidate_detail", jurisdiction="US", right_type="patent",
    ) == ""
    assert coverage_route_policy(
        task, "epo_ops", "candidate_detail", jurisdiction="US", right_type="patent",
    ) == (True, False)
    blocked_task = json.loads(json.dumps(task))
    for requirement in blocked_task["coverage_requirements"]:
        requirement["routes"] = [
            route for route in requirement.get("routes", [])
            if not (
                route.get("provider") == "epo_ops"
                and route.get("operation") == "candidate_detail"
            )
        ]
    assert provider_execution_error(
        blocked_task, "epo_ops", "candidate_detail",
        jurisdiction="US", right_type="patent",
    ) == "COVERAGE_REQUIREMENTS_INVALID"
    write_json(task_dir / "task.json", blocked_task)
    blocked_env = os.environ.copy()
    blocked_env.update({
        "LC_IPR_TEST_MODE": "1", "EPO_OPS_BASE_URL": "http://127.0.0.1:9",
        "EPO_OPS_AUTH_URL": "http://127.0.0.1:9/token",
    })
    command(
        str(SCRIPTS / "epo_ops_client.py"), "--task-dir", str(task_dir),
        "--operation", "biblio", "--query", "US1234567A1",
        "--jurisdiction", "US", "--right-type", "patent",
        "--candidate-id", "C-BLOCKED", "--query-id", "Q-BLOCKED",
        env=blocked_env, succeeds=False, contains="COVERAGE_REQUIREMENTS_INVALID",
    )
    write_json(task_dir / "task.json", task)

    patent_requirement = next(
        requirement for requirement in task["coverage_requirements"]
        if requirement.get("requirement_id") == "COV-US-PATENT-RECALL"
    )
    mini_task = {
        "schema_version": SCHEMA_VERSION, **current_policy_contract(),
        "coverage_requirements": [patent_requirement],
    }
    mini_evidence = {"source_runs": [{
        "run_id": "RUN-EPO-SEARCH", "query_id": "Q-EPO-SEARCH",
        "provider": "epo_ops", "operation": "search", "jurisdiction": "US",
        "right_type": "patent", "status": "no_result",
        "source_environment": "production", "authoritative_for_final_rating": True,
        "requirement_ids": ["COV-US-PATENT-RECALL"],
    }, {
        "run_id": "RUN-USPTO-RECALL", "query_id": "Q-USPTO-RECALL",
        "provider": "uspto_patent_browser", "operation": "patent_recall",
        "jurisdiction": "US", "right_type": "patent", "status": "no_result",
        "requirement_ids": ["COV-US-PATENT-RECALL"],
    }], "collections": {}}
    mini_plan = {"queries": {
        "epo_ops": [{
            "query_id": "Q-EPO-SEARCH", "operation": "search",
            "jurisdiction": "US", "right_type": "patent", "required": True,
            "requirement_ids": ["COV-US-PATENT-RECALL"],
        }],
        "uspto_patent_browser": [{
            "query_id": "Q-USPTO-RECALL", "operation": "patent_recall",
            "jurisdiction": "US", "right_type": "patent", "required": True,
            "requirement_ids": ["COV-US-PATENT-RECALL"],
        }],
    }}
    assert coverage_requirement_gaps(
        mini_task, mini_evidence, {"patents": [], "trademarks": []}, mini_plan,
    ) == []

    patents = [{
        "candidate_id": f"C-EPO-{index:02d}", "jurisdiction": "US",
        "right_type": "patent", "publication_number": f"US12345{index:02d}A1",
        "material": True,
        "sources": [{
            "provider": "epo_ops", "operation": "search", "jurisdiction": "US",
        }],
    } for index in range(8)]
    patents.append({
        "candidate_id": "C-EPO-NONMATERIAL", "jurisdiction": "US",
        "right_type": "patent", "publication_number": "US9999999A1",
        "material": False,
        "sources": [{"provider": "epo_ops", "operation": "search", "jurisdiction": "US"}],
    })
    append_epo_candidate_detail_actions(task_dir, task, patents)
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    detail_actions = [
        item for item in plan["queries"]["epo_ops"]
        if item.get("operation") == "candidate_detail"
    ]
    configured_limit = load_skill_config()["limits"]["epo_candidate_detail_limit"]
    expected = (configured_limit // len(EPO_DETAIL_OPERATIONS)) * len(EPO_DETAIL_OPERATIONS)
    assert len(detail_actions) == expected and len(detail_actions) <= configured_limit
    assert {item["detail_operation"] for item in detail_actions} == set(EPO_DETAIL_OPERATIONS)
    assert all(
        item.get("required") is False and item.get("execute_by_default") is True
        and item.get("requirement_ids") == ["COV-US-PATENT-RECALL"]
        and item.get("candidate_id") != "C-EPO-NONMATERIAL"
        for item in detail_actions
    )
    before = [item["query_id"] for item in detail_actions]
    append_epo_candidate_detail_actions(task_dir, task, patents)
    repeated = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert [
        item["query_id"] for item in repeated["queries"]["epo_ops"]
        if item.get("operation") == "candidate_detail"
    ] == before

    family_action = next(item for item in detail_actions if item["detail_operation"] == "family")
    built = api_runner.command_for(SCRIPTS, task_dir, "epo_ops", family_action)
    assert built[built.index("--operation") + 1] == "family"
    assert built[built.index("--candidate-id") + 1] == family_action["candidate_id"]
    assert built[built.index("--query-id") + 1] == family_action["query_id"]

    biblio_xml = b"""<world-patent-data><exchange-document><bibliographic-data>
      <publication-reference><document-id><country>US</country><doc-number>1234567</doc-number><kind>A1</kind></document-id></publication-reference>
      <application-reference><document-id><country>US</country><doc-number>20230001234</doc-number><kind>A</kind></document-id></application-reference>
      <invention-title>Ergonomic support</invention-title>
      <applicant-name><name>Example Corp</name></applicant-name>
      <classification-ipcr><text>G06F 3/039</text></classification-ipcr>
      <patent-classification><classification-scheme office="CPC"/><section>G</section><class>06</class><subclass>F</subclass><main-group>3</main-group><subgroup>039</subgroup></patent-classification>
    </bibliographic-data></exchange-document></world-patent-data>"""
    family_xml = b"""<world-patent-data><family><family-member family-id="42">
      <publication-reference><document-id><country>US</country><doc-number>1234567</doc-number><kind>A1</kind></document-id></publication-reference>
      <publication-reference><document-id><country>EP</country><doc-number>2222222</doc-number><kind>A1</kind></document-id></publication-reference>
    </family-member></family></world-patent-data>"""
    legal_xml = b"""<world-patent-data><publication-reference><document-id><country>US</country><doc-number>1234567</doc-number><kind>A1</kind></document-id></publication-reference>
      <legal-event code="A1" date="20240101" desc="Published application"/>
    </world-patent-data>"""
    payloads = [
        normalize_detail("biblio", "US1234567A1", biblio_xml, candidate_id="C-EPO-MERGE"),
        normalize_detail("family", "US1234567A1", family_xml, candidate_id="C-EPO-MERGE"),
        normalize_detail("legal", "US1234567A1", legal_xml, candidate_id="C-EPO-MERGE"),
    ]
    entries = [{
        "evidence_id": "EV-EPO-SEARCH", "source_run_id": "RUN-EPO-SEARCH",
        "provider": "epo_ops", "operation": "search", "jurisdiction": "US",
        "right_type": "patent", "payload": [{
            "candidate_id": "C-EPO-MERGE", "publication_number": "US1234567A1",
            "jurisdiction": "US", "source": "epo_ops", "material": True,
        }],
    }]
    runs = {"RUN-EPO-SEARCH": {"status": "success", "right_type": "patent"}}
    for index, payload in enumerate(payloads):
        run_id = f"RUN-EPO-DETAIL-{index}"
        entries.append({
            "evidence_id": f"EV-EPO-DETAIL-{index}", "source_run_id": run_id,
            "provider": "epo_ops", "operation": "candidate_detail",
            "jurisdiction": "US", "right_type": "patent", "payload": payload,
        })
        runs[run_id] = {"status": "success", "right_type": "patent"}
    merged = merge("patent", entries, runs)
    assert len(merged) == 1
    enriched = merged[0]
    assert enriched["title"] == "Ergonomic support"
    assert enriched["owners"] == ["Example Corp"]
    assert enriched["ipc_classes"] and enriched["cpc_classes"]
    assert enriched["family_id"] == "42" and len(enriched["family_members"]) == 2
    assert enriched["legal_events"][0]["code"] == "A1"
    assert set(enriched["detail_operations"]) == set(EPO_DETAIL_OPERATIONS)
    expect_provider_error(lambda: normalize_detail("legal", "US1234567A1", b"<world-patent-data/>"), "RESPONSE_SCHEMA_CHANGED")
    expect_provider_error(
        lambda: normalize_detail(
            "biblio", "US1234567A1", biblio_xml.replace(b"1234567", b"7654321"),
        ),
        "RESPONSE_IDENTITY_MISMATCH",
    )

    # Persist a near-limit OPS header after the first mocked request. The
    # second request must be rejected before another subprocess is started.
    sequential_plan = json.loads(json.dumps(plan))
    sequential_plan["queries"] = {
        "epo_ops": [{**item, "wave": 1} for item in detail_actions[:2]],
    }
    write_json(task_dir / "search-plan.json", sequential_plan)
    task_evidence = json.loads((task_dir / "evidence.json").read_text(encoding="utf-8"))
    task_evidence["source_runs"] = []
    write_json(task_dir / "evidence.json", task_evidence)
    calls: list[list[str]] = []
    original_run = api_runner.subprocess.run
    original_credential = api_runner.credential
    original_argv = sys.argv

    def fake_epo_run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(arguments))
        current = json.loads((task_dir / "evidence.json").read_text(encoding="utf-8"))
        epo_cfg = load_skill_config()["providers"]["epo_ops"]
        used = (
            int(epo_cfg["documented_free_bytes_per_week"])
            - int(epo_cfg["free_stop_margin_bytes"])
            - int(epo_cfg["estimated_max_response_bytes_per_query"])
        )
        current["source_runs"].append({
            "run_id": "RUN-EPO-QUOTA", "provider": "epo_ops",
            "operation": "candidate_detail", "status": "success",
            "quota": {"X-RegisteredQuotaPerWeek-Used": str(used)}, "raw_paths": [],
        })
        write_json(task_dir / "evidence.json", current)
        return subprocess.CompletedProcess(arguments, 0, '{"status":"success"}\n', "")

    try:
        api_runner.credential = lambda config, name: ""
        api_runner.subprocess.run = fake_epo_run
        sys.argv = ["run_api_plan.py", "--task-dir", str(task_dir), "--wave", "1"]
        with redirect_stdout(io.StringIO()):
            try:
                api_runner.main()
            except SystemExit as exc:
                assert exc.code == 1
            else:
                raise AssertionError("quota-stopped EPO batch must return non-zero")
    finally:
        api_runner.subprocess.run = original_run
        api_runner.credential = original_credential
        sys.argv = original_argv
    assert len(calls) == 1, "the second EPO request must stop before network execution"


def test_euipo_110_contract() -> None:
    cfg = load_skill_config()["providers"]["euipo"]
    controlled_names = (
        "EUIPO_TOKEN_URL", "EUIPO_TRADEMARK_BASE_URL", "EUIPO_DESIGN_BASE_URL",
        "EUIPO_ENVIRONMENT", "EUIPO_AUTHORITATIVE_FOR_FINAL_RATING", "LC_IPR_TEST_MODE",
    )
    previous = {name: os.environ.pop(name, None) for name in controlled_names}
    try:
        os.environ["EUIPO_ENVIRONMENT"] = "production"
        assert euipo_search_rsql(
            "trademark", "猫工房", "trademark_word",
        ) == "wordMarkSpecification.verbalElement==*猫工房*"
        assert euipo_search_rsql(
            "design", "mouse pad", "design",
        ) == 'productIndications=="*mouse pad*"'
        assert euipo_search_rsql("design", "14.04", "design") == "locarnoClasses==14.04"
        expect_provider_error(
            lambda: euipo_search_rsql("trademark", "01.01.02", "trademark_figurative"),
            "EUIPO_FIGURATIVE_CLASS_SEARCH_UNSUPPORTED",
        )
        api_params, evidence_params = euipo_search_parameters(
            "trademark", "猫工房", "trademark_word", 0, 25,
        )
        assert set(api_params) == {"query", "page", "size"}
        assert evidence_params["q"] == "猫工房"
        assert evidence_params["right_type"] == "trademark_word"
        assert euipo_resolved_endpoints(cfg, "production")["trademark"].startswith(
            "https://api.euipo.europa.eu/"
        )
        tampered = {**cfg, "trademark_base_url": "https://api-sandbox.euipo.europa.eu/trademark-search"}
        expect_provider_error(
            lambda: euipo_resolved_endpoints(tampered, "production"),
            "EUIPO_ENVIRONMENT_ENDPOINT_MISMATCH",
        )

        mark = euipo_verified_detail("trademark", "000084601", {
            "applicationNumber": "000084601",
            "wordMarkSpecification": {"verbalElement": "White wine"},
            "markImage": {"imageFormat": "JPG", "viennaClasses": ["01.01.02"]},
            "applicants": [{"identifier": "1516", "name": "Owner GmbH"}],
            "status": "REGISTERED",
            "goodsAndServices": [{"classNumber": 8, "description": []}],
        }, [{"role": "image", "path": "/tmp/mark.jpg"}], "trademark_figurative")
        assert mark["nice_classes"] == ["8"]
        assert mark["official_verification"]["status"] == "verified"
        design = euipo_verified_detail("design", "000000013-0001", {
            "designNumber": "000000013-0001",
            "productIndications": [{"language": "en", "terms": ["mouse pads"]}],
            "locarnoClasses": ["14.04"],
            "applicants": [{"identifier": "1516", "name": "Owner GmbH"}],
            "status": "REGISTERED_AND_FULLY_PUBLISHED",
            "views": [{"order": 1, "imageFormat": "JPG"}],
        }, [{"role": "view-1", "path": "/tmp/design.jpg"}], "design")
        assert design["title"] == "mouse pads"
        assert design["official_verification"]["classes"] == ["14.04"]
        assert design["official_verification"]["status"] == "verified"

        # Local fixture endpoints can exercise parsing, but can never masquerade
        # as authoritative EUIPO Production evidence.
        os.environ["LC_IPR_TEST_MODE"] = "1"
        os.environ["EUIPO_TOKEN_URL"] = "http://127.0.0.1:18080/token"
        os.environ["EUIPO_TRADEMARK_BASE_URL"] = "http://127.0.0.1:18080/trademark-search"
        os.environ["EUIPO_DESIGN_BASE_URL"] = "http://127.0.0.1:18080/design-search"
        assert euipo_source_profile() == ("test_fixture", False)
    finally:
        for name in controlled_names:
            os.environ.pop(name, None)
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


def test_euipo_probe_is_oauth_only() -> None:
    controlled_names = (
        "EUIPO_TOKEN_URL", "EUIPO_TRADEMARK_BASE_URL", "EUIPO_DESIGN_BASE_URL",
        "EUIPO_ENVIRONMENT",
        "EUIPO_AUTHORITATIVE_FOR_FINAL_RATING", "LC_IPR_TEST_MODE",
    )
    previous = {name: os.environ.pop(name, None) for name in controlled_names}
    original_http_json = euipo_runtime.http_json
    original_token_cache = dict(euipo_runtime._TOKEN_CACHE)
    calls: list[tuple[str, str]] = []

    def fake_http_json(url: str, *, method: str = "GET", **_: object) -> tuple[dict, dict, bytes]:
        calls.append((method, url))
        if url.endswith("/token"):
            return {"access_token": "fixture-token", "expires_in": 300}, {}, b"{}"
        return {"content": []}, {}, b"{}"

    try:
        os.environ.update({
            "LC_IPR_TEST_MODE": "1",
            "EUIPO_ENVIRONMENT": "production",
            "EUIPO_TOKEN_URL": "http://127.0.0.1:18081/token",
            "EUIPO_TRADEMARK_BASE_URL": "http://127.0.0.1:18081/trademark-search",
            "EUIPO_DESIGN_BASE_URL": "http://127.0.0.1:18081/design-search",
        })
        euipo_runtime.http_json = fake_http_json
        euipo_runtime._TOKEN_CACHE.update({"access_token": "", "expires_at": 0.0})
        with patch.object(euipo_runtime, "credential", return_value="fixture-credential"):
            result = euipo_runtime.probe()

        assert calls == [("POST", "http://127.0.0.1:18081/token")]
        assert result["oauth_ready"] is True
        assert result["configured_environment"] == "production"
        assert set(result["coverage"]) == {"trademark", "design"}
        assert all(
            product["search_probe_performed"] is False
            and product["subscription_status"] == "deferred_to_exact_planned_query"
            for product in result["coverage"].values()
        )
    finally:
        euipo_runtime.http_json = original_http_json
        euipo_runtime._TOKEN_CACHE.clear()
        euipo_runtime._TOKEN_CACHE.update(original_token_cache)
        for name in controlled_names:
            os.environ.pop(name, None)
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


def test_api_fixture_authority_guards() -> None:
    controlled = (
        "LC_IPR_TEST_MODE", "EPO_OPS_BASE_URL", "EPO_OPS_AUTH_URL",
        "JPO_API_BASE_URL", "JPO_AUTH_URL",
    )
    previous = {name: os.environ.pop(name, None) for name in controlled}
    try:
        os.environ.update({
            "LC_IPR_TEST_MODE": "1",
            "EPO_OPS_BASE_URL": "http://127.0.0.1:18081/rest-services",
            "EPO_OPS_AUTH_URL": "http://127.0.0.1:18081/token",
            "JPO_API_BASE_URL": "http://127.0.0.1:18082/api",
            "JPO_AUTH_URL": "http://127.0.0.1:18082/auth",
        })
        assert epo_source_profile() == ("test_fixture", False)
        jpo_client = JpoApiClient(config={"providers": {"jpo_api": {}}})
        assert jpo_client.source_environment == "test_fixture"
        assert jpo_client.authoritative_for_final_rating is False
    finally:
        for name in controlled:
            os.environ.pop(name, None)
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value

    requirements = build_coverage_requirements(["US"])
    task = {
        "schema_version": SCHEMA_VERSION, "target_jurisdictions": ["US"],
        **current_policy_contract(), "coverage_requirements": requirements,
    }
    runs = [{
        "run_id": "RUN-EPO-FIXTURE", "query_id": "Q-EPO-FIXTURE",
        "provider": "epo_ops", "operation": "search", "jurisdiction": "US",
        "right_type": "patent", "status": "no_result",
        "requirement_ids": ["COV-US-PATENT-RECALL"],
        "source_environment": "test_fixture", "authoritative_for_final_rating": False,
    }, {
        "run_id": "RUN-USPTO", "query_id": "Q-USPTO",
        "provider": "uspto_patent_browser", "operation": "patent_recall",
        "jurisdiction": "US", "right_type": "patent", "status": "no_result",
        "requirement_ids": ["COV-US-PATENT-RECALL"],
    }]
    evidence = {"source_runs": runs, "collections": {}}
    authority_plan = {"queries": {
        "epo_ops": [{
            "query_id": "Q-EPO-FIXTURE", "operation": "search",
            "jurisdiction": "US", "right_type": "patent", "required": True,
            "requirement_ids": ["COV-US-PATENT-RECALL"],
        }],
        "uspto_patent_browser": [{
            "query_id": "Q-USPTO", "operation": "patent_recall",
            "jurisdiction": "US", "right_type": "patent", "required": True,
            "requirement_ids": ["COV-US-PATENT-RECALL"],
        }],
    }}
    gaps = coverage_requirement_gaps(task, evidence, {"patents": [], "trademarks": []}, authority_plan)
    assert "COV-US-PATENT-RECALL" in gaps
    runs[0].update({
        "source_environment": "production", "authoritative_for_final_rating": True,
    })
    gaps = coverage_requirement_gaps(task, evidence, {"patents": [], "trademarks": []}, authority_plan)
    assert "COV-US-PATENT-RECALL" not in gaps

    checked_at = now_iso()
    verification = {
        "status": "verified", "authority": "Japan Patent Office (JPO)",
        "method": "official_free_api", "identity_match": True,
        "legal_status": "registered", "owner": ["Owner"], "classes": [],
        "media": [], "url": "https://ip-data.jpo.go.jp/api/patent/v1/app_progress/2020008423",
        "checked_at": checked_at,
    }
    jp_task = {
        "schema_version": SCHEMA_VERSION, "task_id": "TASK-JPO-FIXTURE",
        "target_jurisdictions": ["JP"],
        **current_policy_contract(),
        "coverage_requirements": build_coverage_requirements(["JP"]),
    }
    jp_candidates = {"patents": [{
        "candidate_id": "C-JPO-FIXTURE", "jurisdiction": "JP", "right_type": "patent",
        "application_number": "2020008423", "material": True,
        "verification_refs": ["EV-JPO-FIXTURE"], "official_verification": verification,
    }], "trademarks": []}
    reviewed_materiality_fixture(
        jp_task, jp_candidates,
        {"C-JPO-FIXTURE": (True, "功能特征与当前商品相关")},
    )
    jp_run = {
        "run_id": "RUN-JPO-FIXTURE", "query_id": "Q-JPO-FIXTURE",
        "provider": "jpo_api", "operation": "candidate_verification",
        "jurisdiction": "JP", "right_type": "patent", "status": "success",
        "requirement_ids": ["COV-JP-PATENT-VERIFY"],
        "request_params": {"candidate_id": "C-JPO-FIXTURE", "number": "2020008423"},
        "source_environment": "test_fixture", "authoritative_for_final_rating": False,
    }
    jp_evidence = {
        "source_runs": [jp_run], "collections": {"official_verifications": [{
            "evidence_id": "EV-JPO-FIXTURE", "source_run_id": "RUN-JPO-FIXTURE",
            "query_id": "Q-JPO-FIXTURE",
            "provider": "jpo_api", "operation": "candidate_verification",
            "jurisdiction": "JP", "right_type": "patent",
            "requirement_ids": ["COV-JP-PATENT-VERIFY"],
            "payload": {
                "candidate_id": "C-JPO-FIXTURE", "right_type": "patent",
                "application_number": "2020008423", "official_verification": verification,
            },
        }]},
    }
    assert material_unverified(jp_candidates, strict=True, evidence=jp_evidence, task=jp_task) == [
        "C-JPO-FIXTURE"
    ]
    jp_run.update({
        "source_environment": "production", "authoritative_for_final_rating": True,
    })
    assert material_unverified(jp_candidates, strict=True, evidence=jp_evidence, task=jp_task) == []


def test_national_effect_and_identity_mismatch_gates() -> None:
    checked = datetime.now(timezone.utc).replace(microsecond=0)

    def timestamp(minutes: int) -> str:
        return (checked + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")

    def verification(
        authority: str, url: str, checked_at: str, *, identity_match: bool = True,
        media: list[Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "verified" if identity_match else "identity_mismatch",
            "authority": authority, "method": "cdp_assisted",
            "identity_match": identity_match, "legal_status": "active",
            "owner": ["Owner"], "classes": ["25"],
            "media": [] if media is None else media,
            "url": url, "checked_at": checked_at,
        }

    def evidence_entry(
        provider: str, jurisdiction: str, requirement_id: str,
        evidence_id: str, candidate_id: str, official: dict[str, Any],
        *, right_type: str = "patent", number: str = "EP1234567A1",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        run_id = f"RUN-{evidence_id}"
        query_id = f"QRY-{evidence_id}"
        run = {
            "run_id": run_id, "query_id": query_id,
            "provider": provider, "operation": "candidate_verification",
            "jurisdiction": jurisdiction, "right_type": right_type,
            "status": "success", "requirement_ids": [requirement_id],
            "request_params": {"candidate_id": candidate_id, "number": number},
            "source_environment": "production", "authoritative_for_final_rating": True,
        }
        row = {
            "evidence_id": evidence_id, "source_run_id": run_id,
            "query_id": query_id,
            "provider": provider, "operation": "candidate_verification",
            "jurisdiction": jurisdiction, "right_type": right_type,
            "requirement_ids": [requirement_id], "payload": {
                "candidate_id": candidate_id, "right_type": right_type,
                "publication_number": number,
                "official_verification": official,
            },
        }
        return run, row

    summary_verified = verification(
        "Summary registry", "https://register.epo.org/", timestamp(-30),
    )
    summary_newer_mismatch = verification(
        "Summary registry", "https://register.epo.org/", timestamp(-20),
        identity_match=False,
    )
    assert better_verification(
        summary_verified, summary_newer_mismatch,
    )["status"] == "identity_mismatch"
    assert better_verification(
        summary_verified,
        verification(
            "Summary registry", "https://register.epo.org/", timestamp(-30),
            identity_match=False,
        ),
    )["status"] == "identity_mismatch"

    eu_task = {
        "schema_version": SCHEMA_VERSION, "task_id": "TASK-EP-NATIONAL",
        "target_jurisdictions": ["EU", "DE"], **current_policy_contract(),
        "coverage_requirements": build_coverage_requirements(["EU", "DE"]),
    }
    epo_verified = verification(
        "European Patent Office", "https://register.epo.org/espacenet/application?number=EP1234567",
        timestamp(-20),
    )
    eu_candidate = {"patents": [{
        "candidate_id": "C-EP-NATIONAL", "jurisdiction": "EP",
        "right_type": "patent", "publication_number": "EP1234567A1",
        "material": True, "verification_refs": ["EV-EPO-REGISTER"],
        "official_verification": epo_verified,
    }], "trademarks": []}
    reviewed_materiality_fixture(
        eu_task, eu_candidate,
        {"C-EP-NATIONAL": (True, "EP 文献与商品功能特征相关")},
    )
    epo_run, epo_entry = evidence_entry(
        "epo_register_browser", "EU", "COV-EU-PATENT-VERIFY",
        "EV-EPO-REGISTER", "C-EP-NATIONAL", epo_verified,
    )
    eu_evidence = {
        "source_runs": [epo_run],
        "collections": {"official_verifications": [epo_entry]},
    }
    assert material_unverified(
        eu_candidate, strict=True, evidence=eu_evidence, task=eu_task,
    ) == ["C-EP-NATIONAL"]
    assert "COV-DE-PATENT-VERIFY" in coverage_requirement_gaps(
        eu_task, eu_evidence, eu_candidate, {"queries": {}},
    )
    de_verified = verification(
        "German Patent and Trade Mark Office",
        "https://register.dpma.de/DPMAregister/pat/register?AKZ=EP1234567",
        timestamp(-10),
    )
    de_run, de_entry = evidence_entry(
        "official_registry_browser", "DE", "COV-DE-PATENT-VERIFY",
        "EV-DE-REGISTER", "C-EP-NATIONAL", de_verified,
    )
    eu_candidate["patents"][0]["verification_refs"].append("EV-DE-REGISTER")
    eu_evidence["source_runs"].append(de_run)
    eu_evidence["collections"]["official_verifications"].append(de_entry)
    de_plan_entry = {
        "query_id": de_run["query_id"], "q": "EP1234567A1",
        "candidate_id": "C-EP-NATIONAL", "number": "EP1234567A1",
        "operation": "candidate_verification", "jurisdiction": "DE",
        "right_type": "patent", "required": False, "required_for": "formal",
        "requirement_ids": ["COV-DE-PATENT-VERIFY"], "wave": 1,
        "derived_from": ["normalized-candidates:C-EP-NATIONAL"],
    }
    de_plan = {"queries": {"official_registry_browser": [de_plan_entry]}}
    de_plan_digest = sha256_json(de_plan_entry)
    de_run.update({
        "query": "EP1234567A1", "plan_entry_sha256": de_plan_digest,
    })
    de_entry["plan_entry_sha256"] = de_plan_digest
    assert material_unverified(
        eu_candidate, strict=True, evidence=eu_evidence, task=eu_task,
    ) == []
    assert "COV-DE-PATENT-VERIFY" not in coverage_requirement_gaps(
        eu_task, eu_evidence, eu_candidate, de_plan,
    )
    de_mismatch = verification(
        "German Patent and Trade Mark Office",
        "https://register.dpma.de/DPMAregister/pat/register?AKZ=EP1234567",
        timestamp(-8), identity_match=False,
    )
    de_mismatch_run, de_mismatch_entry = evidence_entry(
        "official_registry_browser", "DE", "COV-DE-PATENT-VERIFY",
        "EV-DE-MISMATCH", "C-EP-NATIONAL", de_mismatch,
    )
    newer_eu_verified = verification(
        "European Patent Office", "https://register.epo.org/espacenet/application?number=EP1234567",
        timestamp(-5),
    )
    newer_eu_run, newer_eu_entry = evidence_entry(
        "epo_register_browser", "EU", "COV-EU-PATENT-VERIFY",
        "EV-EPO-NEWER", "C-EP-NATIONAL", newer_eu_verified,
    )
    eu_candidate["patents"][0]["verification_refs"].extend([
        "EV-DE-MISMATCH", "EV-EPO-NEWER",
    ])
    eu_evidence["source_runs"].extend([de_mismatch_run, newer_eu_run])
    eu_evidence["collections"]["official_verifications"].extend([
        de_mismatch_entry, newer_eu_entry,
    ])
    assert material_unverified(
        eu_candidate, strict=True, evidence=eu_evidence, task=eu_task,
    ) == ["C-EP-NATIONAL"], "a later EU match must not clear a DE mismatch"
    newest_de_verified = verification(
        "German Patent and Trade Mark Office",
        "https://register.dpma.de/DPMAregister/pat/register?AKZ=EP1234567",
        timestamp(-1),
    )
    newest_de_run, newest_de_entry = evidence_entry(
        "official_registry_browser", "DE", "COV-DE-PATENT-VERIFY",
        "EV-DE-NEWEST", "C-EP-NATIONAL", newest_de_verified,
    )
    eu_candidate["patents"][0]["verification_refs"].append("EV-DE-NEWEST")
    eu_evidence["source_runs"].append(newest_de_run)
    eu_evidence["collections"]["official_verifications"].append(newest_de_entry)
    assert material_unverified(
        eu_candidate, strict=True, evidence=eu_evidence, task=eu_task,
    ) == []
    eu_candidate["patents"][0]["official_verification"] = verification(
        "Unbound reviewer note", "https://register.epo.org/",
        timestamp(0), identity_match=False,
    )
    assert material_unverified(
        eu_candidate, strict=True, evidence=eu_evidence, task=eu_task,
    ) == ["C-EP-NATIONAL"], "an unscoped top-level mismatch must remain blocking"
    eu_candidate["patents"][0]["official_verification"] = newest_de_verified

    jp_task = {
        "schema_version": SCHEMA_VERSION, "task_id": "TASK-JP-MISMATCH-TIME",
        "target_jurisdictions": ["JP"], **current_policy_contract(),
        "coverage_requirements": build_coverage_requirements(["JP"]),
    }
    old_verified = verification(
        "Japan Patent Office", "https://ip-data.jpo.go.jp/api/patent/v1/app_progress/2020008423",
        timestamp(-30),
    )
    mismatch = verification(
        "Japan Patent Office", "https://ip-data.jpo.go.jp/api/patent/v1/app_progress/2020008423",
        timestamp(-20), identity_match=False,
    )
    jp_candidate = {"patents": [{
        "candidate_id": "C-JP-MISMATCH", "jurisdiction": "JP",
        "right_type": "patent", "application_number": "2020008423",
        "material": False, "verification_refs": ["EV-JP-OLD", "EV-JP-MISMATCH"],
        "official_verification": old_verified,
    }], "trademarks": []}
    reviewed_materiality_fixture(
        jp_task, jp_candidate,
        {"C-JP-MISMATCH": (False, "候选与商品技术特征无关")},
    )
    old_run, old_entry = evidence_entry(
        "jpo_api", "JP", "COV-JP-PATENT-VERIFY", "EV-JP-OLD",
        "C-JP-MISMATCH", old_verified, number="JP2020008423A",
    )
    mismatch_run, mismatch_entry = evidence_entry(
        "jpo_api", "JP", "COV-JP-PATENT-VERIFY", "EV-JP-MISMATCH",
        "C-JP-MISMATCH", mismatch, number="JP2020008423A",
    )
    jp_evidence = {
        "source_runs": [old_run, mismatch_run],
        "collections": {"official_verifications": [old_entry, mismatch_entry]},
    }
    assert material_unverified(
        jp_candidate, strict=True, evidence=jp_evidence, task=jp_task,
    ) == ["C-JP-MISMATCH"]
    newer_verified = verification(
        "J-PlatPat", "https://www.j-platpat.inpit.go.jp/",
        timestamp(-5),
    )
    newer_run, newer_entry = evidence_entry(
        "jplatpat_browser", "JP", "COV-JP-PATENT-VERIFY", "EV-JP-NEW",
        "C-JP-MISMATCH", newer_verified, number="JP2020008423A",
    )
    jp_candidate["patents"][0]["verification_refs"].append("EV-JP-NEW")
    jp_evidence["source_runs"].append(newer_run)
    jp_evidence["collections"]["official_verifications"].append(newer_entry)
    assert material_unverified(
        jp_candidate, strict=True, evidence=jp_evidence, task=jp_task,
    ) == []


def test_eu_candidate_verification_actions(root: Path) -> None:
    task_dir = root / "eu-candidate-actions"
    task_dir.mkdir(parents=True)
    task = {
        "schema_version": SCHEMA_VERSION, "task_id": "TASK-EU-CANDIDATE-ACTIONS",
        "state": "collecting", **current_policy_contract(),
        "target_jurisdictions": ["EU", "DE"],
        "coverage_requirements": build_coverage_requirements(["EU", "DE"]),
    }
    write_json(task_dir / "search-plan.json", {
        "schema_version": SCHEMA_VERSION, "task_id": task["task_id"], "queries": {},
        **current_policy_contract(),
    })
    designs = [{
        "candidate_id": "C-EU-DESIGN", "jurisdiction": "EU",
        "right_type": "design", "publication_number": "000000013-0001",
        "material": True,
    }, {
        "candidate_id": "C-EP-PATENT", "jurisdiction": "EP",
        "right_type": "patent", "publication_number": "EP1234567A1",
        "material": True,
    }, {
        "candidate_id": "C-WO-EP-FAMILY", "jurisdiction": "WO",
        "right_type": "patent", "publication_number": "WO2024123456A1",
        "family_members": ["EP4234567A1", "DE112024001234B4"],
        "material": True,
    }]
    marks = [{
        "candidate_id": "C-EU-WORD", "jurisdiction": "EU",
        "right_type": "trademark_word", "application_number": "000084601",
        "material": True,
    }, {
        "candidate_id": "C-EU-FIG", "office": "euipo",
        "right_type": "trademark_figurative", "application_number": "018765432",
        "material": True,
    }, {
        "candidate_id": "C-EU-REG-ONLY", "jurisdiction": "EU",
        "right_type": "trademark_word", "registration_number": "009999999",
        "material": True,
    }]
    append_eu_candidate_verification_actions(task_dir, task, designs, marks)
    plan = load_skill_config()  # ensure the normal config remains parseable
    assert plan["providers"]["euipo"]["environment"] == "production"
    generated = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    design_actions = generated["queries"]["euipo_design"]
    mark_actions = generated["queries"]["euipo_trademark"]
    epo_register_actions = generated["queries"]["epo_register_browser"]
    national_actions = generated["queries"]["official_registry_browser"]
    assert len(design_actions) == 1 and len(mark_actions) == 2
    assert len(epo_register_actions) == 2 and len(national_actions) == 2
    assert {
        row["candidate_id"] for row in epo_register_actions
    } == {"C-EP-PATENT", "C-WO-EP-FAMILY"}
    national_by_candidate = {row["candidate_id"]: row for row in national_actions}
    assert national_by_candidate["C-EP-PATENT"]["record_number"] == "EP1234567A1"
    assert national_by_candidate["C-WO-EP-FAMILY"]["record_number"] == "DE112024001234B4"
    assert all(
        row["jurisdiction"] == "DE"
        and row["requirement_ids"] == ["COV-DE-PATENT-VERIFY"]
        for row in national_actions
    )
    assert {row["right_type"] for row in mark_actions} == {
        "trademark_word", "trademark_figurative",
    }
    assert all(
        row["operation"] == "candidate_verification"
        and row["execute_by_default"] is True
        and row["required"] is False
        and row["requirement_ids"]
        for row in [*design_actions, *mark_actions]
    )
    built = api_command_for(SCRIPTS, task_dir, "euipo_trademark", mark_actions[0])
    assert "--verify" in built
    assert built[built.index("--identifier") + 1] == mark_actions[0]["identifier"]
    assert built[built.index("--candidate-id") + 1] == mark_actions[0]["candidate_id"]
    before = {
        row["query_id"] for rows in generated["queries"].values() for row in rows
    }
    append_eu_candidate_verification_actions(task_dir, task, designs, marks)
    repeated = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert {
        row["query_id"] for rows in repeated["queries"].values() for row in rows
    } == before

    class EuipoFixtureHandler(BaseHTTPRequestHandler):
        def _send(self, payload: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            self._send(json.dumps({
                "access_token": "fixture-token", "expires_in": 300,
            }).encode(), "application/json")

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            if self.path == "/trademark-search/trademarks/000084601":
                self._send(json.dumps({
                    "applicationNumber": "000084601",
                    "wordMarkSpecification": {"verbalElement": "White wine"},
                    "applicants": [{"identifier": "1516", "name": "Owner GmbH"}],
                    "status": "REGISTERED",
                    "goodsAndServices": [{"classNumber": 8, "description": []}],
                }).encode(), "application/json")
                return
            self.send_error(404)

        def log_message(self, *_: Any) -> None:
            return

    write_json(task_dir / "task.json", task)
    write_json(task_dir / "evidence.json", {
        "schema_version": SCHEMA_VERSION, "task_id": task["task_id"],
        "source_runs": [], "collections": {"official_verifications": []},
    })
    server = ThreadingHTTPServer(("127.0.0.1", 0), EuipoFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    env = os.environ.copy()
    env.update({
        "LC_IPR_TEST_MODE": "1", "EUIPO_ENVIRONMENT": "production",
        "EUIPO_TOKEN_URL": f"http://127.0.0.1:{port}/token",
        "EUIPO_TRADEMARK_BASE_URL": f"http://127.0.0.1:{port}/trademark-search",
        "EUIPO_DESIGN_BASE_URL": f"http://127.0.0.1:{port}/design-search",
    })
    try:
        result = command(*built[1:], env=env, contains="access_limited")
        assert result.returncode == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    recorded = json.loads((task_dir / "evidence.json").read_text(encoding="utf-8"))
    run = recorded["source_runs"][-1]
    payload = recorded["collections"]["official_verifications"][-1]["payload"]
    assert run["source_environment"] == "test_fixture"
    assert run["authoritative_for_final_rating"] is False
    assert payload["candidate_id"] == "C-EU-WORD"
    assert payload["official_verification"]["status"] == "not_checked"


def test_wo_family_candidate_routes(root: Path) -> None:
    task_dir = root / "wo-family-actions"
    task_dir.mkdir(parents=True)
    task = {
        "schema_version": SCHEMA_VERSION, "task_id": "TASK-WO-FAMILY-ACTIONS",
        "state": "collecting", **current_policy_contract(),
        "target_jurisdictions": ["US", "EU", "DE", "JP"],
        "coverage_requirements": build_coverage_requirements(["US", "EU", "DE", "JP"]),
    }
    write_json(task_dir / "search-plan.json", {
        "schema_version": SCHEMA_VERSION, "task_id": task["task_id"],
        "queries": {}, **current_policy_contract(),
    })
    candidate = {
        "candidate_id": "C-WO-MULTI", "jurisdiction": "WO",
        "right_type": "patent", "publication_number": "WO2024123456A1",
        "family_members": [
            "US20240123456A1", "EP4234567A1", "DE112024001234B4",
            "JP2024123456A",
        ],
        "material": True,
    }
    append_us_candidate_verification_actions(task_dir, task, [candidate], [{
        "candidate_id": "C-US-FIG-ACTION", "jurisdiction": "US",
        "right_type": "trademark_figurative", "serial_number": "87654321",
        "material": True,
    }])
    append_eu_candidate_verification_actions(task_dir, task, [candidate], [])
    append_jp_candidate_verification_actions(task_dir, task, [candidate], [])
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    expected = {
        "uspto_patent_browser": ("US", "US20240123456A1"),
        "epo_register_browser": ("EU", "EP4234567A1"),
        "official_registry_browser": ("DE", "DE112024001234B4"),
        "jpo_api": ("JP", "JP2024123456A"),
        "jplatpat_browser": ("JP", "JP2024123456A"),
    }
    for provider, (jurisdiction, record) in expected.items():
        actions = [
            row for row in plan["queries"].get(provider, [])
            if row.get("candidate_id") == "C-WO-MULTI"
        ]
        assert len(actions) == 1, provider
        action = actions[0]
        assert action["operation"] == "candidate_verification"
        assert action["jurisdiction"] == jurisdiction
        assert action["right_type"] == "patent"
        assert action["q"] == record and action["requirement_ids"]
    tsdr = next(
        row for row in plan["queries"]["uspto_tsdr"]
        if row["candidate_id"] == "C-US-FIG-ACTION"
    )
    assert tsdr["serial_number"] == "87654321"
    assert tsdr["right_type"] == "trademark_figurative"
    assert tsdr["requirement_ids"] == ["COV-US-TRADEMARK_FIGURATIVE-VERIFY"]


def test_official_public_record_url_allowlist() -> None:
    for url in (
        "https://publicrecords.copyright.gov/",
        "https://ttabvue.uspto.gov/ttabvue/",
        "https://ptab.uspto.gov/",
        "https://ccb.gov/",
        "https://dockets.ccb.gov/case/detail/example",
    ):
        assert is_official_record_url(url), url

    for url in (
        "https://publicrecords.copyright.gov.evil.example/",
        "https://ttabvue-uspto.gov.example/",
        "https://ptab.uspto.gov.attacker.example/",
        "https://ccb.gov.example/",
        "https://user@ccb.gov/",
        "http://ccb.gov/",
    ):
        assert not is_official_record_url(url), url


def expect_provider_error(callable_value: Any, code: str) -> None:
    try:
        callable_value()
    except ProviderError as exc:
        assert exc.code == code, (exc.code, exc.detail)
    else:
        raise AssertionError(f"Expected ProviderError {code}")


def test_quota_and_jpo_contracts() -> None:
    config = load_skill_config()
    test_secure_credential_sources()
    test_cross_process_reservation_and_restart()
    test_paid_header_and_week_window()
    test_ops_client_reserves_before_offline_http()
    test_plan_runner_reads_shared_account_state()
    attempts = 0
    original_build_opener = provider_runtime.request.build_opener

    def quota_429(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        raise provider_runtime.error.HTTPError(
            "http://127.0.0.1:9/test", 429,
            "quota", {}, io.BytesIO(b'{"error":"quota"}'),
        )

    try:
        class OfflineOpener:
            open = staticmethod(quota_429)
        provider_runtime.request.build_opener = lambda *args: OfflineOpener()
        expect_provider_error(
            lambda: provider_runtime.http_request(
                "http://127.0.0.1:9/test", retries=3,
            ),
            "FREE_QUOTA_EXHAUSTED",
        )
    finally:
        provider_runtime.request.build_opener = original_build_opener
    assert attempts == 1, "HTTP 429 must hard-stop without a retry"
    progress = {
        "applicationNumber": "2023123456", "inventionTitle": "猫用マット",
        "updateDate": "20260901", "applicantAttorney": [{"name": "Example KK"}],
    }
    registration = {
        "registrationNumber": "7654321",
        "rightPersonInformation": [{"rightPersonName": "Example KK"}],
    }
    fixed = {"URL": "https://www.j-platpat.inpit.go.jp/c1801/PU/JP-2023-123456/11/ja"}
    patent, complete, reason = normalize_verification("patent", "2023123456", progress, registration, fixed)
    assert complete and not reason and patent["official_verification"]["identity_match"] is True

    trademark_progress = {
        "applicationNumber": "2023123456", "trademarkForDisplay": "猫工房",
        "updateDate": "20260901", "applicantAttorney": [{"name": "Example KK"}],
        "goodsServiceInformation": [{"goodsServiceClass": "20", "similarCode": "19B23", "goodsServiceName": "mats"}],
    }
    _, trademark_complete, _ = normalize_verification(
        "trademark_word", "2023123456", trademark_progress, registration, fixed,
    )
    assert trademark_complete
    design_progress = {
        "applicationNumber": "2023123456", "designArticle": "マット",
        "designClass": "C1-200", "updateDate": "20260901",
        "applicantAttorney": [{"name": "Example KK"}],
    }
    design, design_complete, design_reason = normalize_verification(
        "design", "2023123456", design_progress, registration, fixed,
    )
    assert not design_complete and "official_media" in design_reason
    assert design["official_verification"]["fallback_provider"] == "jplatpat_browser"

    transport_calls: list[str] = []

    def forbidden_transport(*args: Any, **kwargs: Any) -> Any:
        transport_calls.append(str(args[0] if args else "called"))
        raise AssertionError("utility-model verification must not use the JPO API")

    client = JpoApiClient(config=config, transport=forbidden_transport)
    expect_provider_error(lambda: client.verify("utility_model", "2023123456"), "JPO_API_UNSUPPORTED_RIGHT_TYPE")
    assert not transport_calls


def test_materiality_annotation_reachability(root: Path) -> None:
    task_dir = new_task(
        root, "materiality-reachability",
        "https://www.amazon.com/dp/B0FREE2310", "US,EU,JP",
    )
    task, evidence = prepare_product(task_dir)
    task["state"] = "collecting"
    write_json(task_dir / "task.json", task)
    command(str(SCRIPTS / "generate_search_plan.py"), "--task-dir", str(task_dir))

    def add_recall(
        provider: str, operation: str, jurisdiction: str, right_type: str,
        evidence_id: str, payload: Any,
    ) -> None:
        run_id = f"RUN-{evidence_id}"
        evidence["source_runs"].append({
            "run_id": run_id, "query_id": f"QRY-{evidence_id}",
            "provider": provider, "operation": operation,
            "jurisdiction": jurisdiction, "right_type": right_type,
            "status": "success", "raw_paths": [],
            "source_environment": "production", "authoritative_for_final_rating": True,
        })
        evidence["collections"]["patents"].append({
            "evidence_id": evidence_id, "source_run_id": run_id,
            "query_id": f"QRY-{evidence_id}", "provider": provider,
            "operation": operation, "query": "mouse pad",
            "jurisdiction": jurisdiction, "right_type": right_type,
            "collected_at": now_iso(), "payload": payload,
        })

    add_recall(
        "epo_ops", "search", "US", "patent", "EV-EPO-US",
        normalize_search(b'<world><exchange-document country="US" doc-number="1234567" kind="A1"/></world>'),
    )
    add_recall(
        "epo_ops", "search", "JP", "patent", "EV-EPO-JP",
        normalize_search(b'<world><exchange-document country="JP" doc-number="2020123456" kind="A"/></world>'),
    )
    add_recall("euipo_design", "search", "EU", "design", "EV-EUIPO-DESIGN", [{
        "right_type": "design", "publication_number": "015012345-0001",
        "jurisdiction": "EU", "locarno": ["06-04"], "title": "Mouse pads",
        "views": [], "source": "euipo_design", "material": False,
        "source_environment": "production", "authoritative_for_final_rating": True,
        "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
    }])
    add_recall("jplatpat_browser", "design_recall", "JP", "design", "EV-JPLAT-DESIGN", {
        "right_type": "design", "jurisdiction": "JP", "operation": "design_recall",
        "query": "マウスパッド", "source_url": "https://www.j-platpat.inpit.go.jp/",
        "checked_at": now_iso(), "capture_transport": "cdp",
        "candidates": [{
            "candidate_id": "", "right_type": "design", "jurisdiction": "JP",
            "record_number": "JP1700001", "registration_number": "1700001",
            "title": "マウスパッド", "owner": "Example KK", "legal_status": "registered",
            "classes": ["J5-20"], "material": False, "source": "jplatpat_browser",
            "official_verification": {"status": "not_checked", "source": "jplatpat_browser", "url": "", "checked_at": ""},
        }],
    })
    write_json(task_dir / "evidence.json", evidence)
    command(str(SCRIPTS / "merge_candidates.py"), "--task-dir", str(task_dir))
    first = json.loads((task_dir / "normalized-candidates.json").read_text(encoding="utf-8"))
    first_rows = [*first["patents"], *first["trademarks"]]
    assert len(first_rows) == 4
    assert all(item["material"] is False and item["disposition"] == "unreviewed" for item in first_rows)
    assert set(material_unverified(first, strict=True, evidence=evidence, task=task)) == {
        item["candidate_id"] for item in first_rows
    }
    first_plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert not any(
        item.get("candidate_id")
        for entries in first_plan["queries"].values() for item in entries
        if item.get("operation") in {"candidate_detail", "candidate_verification"}
    )

    ids = {
        str(item.get("publication_number") or item.get("record_number")): item["candidate_id"]
        for item in first_rows
    }
    reasons = {
        ids["US1234567A1"]: "美国专利标题与商品结构需要比对",
        ids["JP2020123456A"]: "日本专利与商品功能特征可能相关",
        ids["015012345-0001"]: "欧盟外观产品指示与商品类别一致",
        ids["JP1700001"]: "日本意匠类别与商品外观相关",
    }
    command(
        str(SCRIPTS / "annotate_materiality.py"), "--task-dir", str(task_dir),
        "--candidate-id", ids["US1234567A1"], "--material", "true",
        "--material-reason", "", "--reviewer", "reviewer-a",
        succeeds=False, contains="must be non-empty",
    )
    for candidate_id, reason in reasons.items():
        command(
            str(SCRIPTS / "annotate_materiality.py"), "--task-dir", str(task_dir),
            "--candidate-id", candidate_id, "--material", "true",
            "--material-reason", reason, "--reviewer", "reviewer-a",
        )

    command(str(SCRIPTS / "merge_candidates.py"), "--task-dir", str(task_dir))
    second = json.loads((task_dir / "normalized-candidates.json").read_text(encoding="utf-8"))
    second_rows = [*second["patents"], *second["trademarks"]]
    assert all(
        item["material"] is True and item["disposition"] == "material"
        and item["materiality_annotation"]["reviewer"] == "reviewer-a"
        for item in second_rows
    )
    plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    dynamic = [
        (provider, item) for provider, entries in plan["queries"].items()
        for item in entries if item.get("candidate_id")
        and item.get("operation") in {"candidate_detail", "candidate_verification"}
    ]
    assert {
        item["candidate_id"] for provider, item in dynamic
        if provider == "epo_ops" and item["operation"] == "candidate_detail"
    } == {ids["US1234567A1"], ids["JP2020123456A"]}
    assert any(provider == "euipo_design" and item["candidate_id"] == ids["015012345-0001"] for provider, item in dynamic)
    for candidate_id in (ids["JP2020123456A"], ids["JP1700001"]):
        assert any(provider == "jpo_api" and item["candidate_id"] == candidate_id for provider, item in dynamic)
        assert any(provider == "jplatpat_browser" and item["candidate_id"] == candidate_id for provider, item in dynamic)

    checked_at = now_iso()
    jp_candidate_id = ids["JP2020123456A"]
    jp_verification = {
        "status": "verified", "authority": "Japan Patent Office (JPO)",
        "source": "JPO Patent Information Retrieval API", "method": "official_free_api",
        "identity_match": True, "legal_status": "published", "owner": ["Example KK"],
        "classes": [], "media": [],
        "url": "https://ip-data.jpo.go.jp/api/patent/v1/app_progress/2020123456",
        "checked_at": checked_at,
    }
    evidence = json.loads((task_dir / "evidence.json").read_text(encoding="utf-8"))
    evidence["source_runs"].append({
        "run_id": "RUN-JPO-DETAIL", "query_id": "QRY-JPO-DETAIL",
        "provider": "jpo_api", "operation": "candidate_verification",
        "jurisdiction": "JP", "right_type": "patent", "status": "success",
        "requirement_ids": ["COV-JP-PATENT-VERIFY"], "raw_paths": [],
        "request_params": {
            "candidate_id": jp_candidate_id, "number": "2020123456",
        },
        "source_environment": "production", "authoritative_for_final_rating": True,
    })
    evidence["collections"]["official_verifications"].append({
        "evidence_id": "EV-JPO-DETAIL", "source_run_id": "RUN-JPO-DETAIL",
        "query_id": "QRY-JPO-DETAIL", "provider": "jpo_api",
        "operation": "candidate_verification", "jurisdiction": "JP",
        "right_type": "patent", "requirement_ids": ["COV-JP-PATENT-VERIFY"],
        "collected_at": checked_at, "payload": {
            "candidate_id": jp_candidate_id, "right_type": "patent", "jurisdiction": "JP",
            "application_number": "2020123456", "title": "Ergonomic support",
            "official_verification": jp_verification,
        },
    })
    write_json(task_dir / "evidence.json", evidence)
    command(str(SCRIPTS / "merge_candidates.py"), "--task-dir", str(task_dir))
    third = json.loads((task_dir / "normalized-candidates.json").read_text(encoding="utf-8"))
    third_rows = [*third["patents"], *third["trademarks"]]
    assert len(third_rows) == 4 and len({item["candidate_id"] for item in third_rows}) == 4
    verified_jp = next(item for item in third_rows if item["candidate_id"] == jp_candidate_id)
    assert verified_jp["official_verification"]["identity_match"] is True
    assert "EV-JPO-DETAIL" in verified_jp["verification_refs"]
    assert verified_jp["materiality_annotation"]["material_reason"] == reasons[jp_candidate_id]

    excluded_ids = {ids["015012345-0001"], ids["JP1700001"]}
    for candidate_id in excluded_ids:
        command(
            str(SCRIPTS / "annotate_materiality.py"), "--task-dir", str(task_dir),
            "--candidate-id", candidate_id, "--material", "false",
            "--material-reason", "复核后与当前商品关键特征不匹配",
            "--reviewer", "reviewer-b",
        )
    command(str(SCRIPTS / "merge_candidates.py"), "--task-dir", str(task_dir))
    final_candidates = json.loads((task_dir / "normalized-candidates.json").read_text(encoding="utf-8"))
    final_plan = json.loads((task_dir / "search-plan.json").read_text(encoding="utf-8"))
    assert all(
        item["disposition"] == "excluded" and item["material"] is False
        for item in final_candidates["patents"] if item["candidate_id"] in excluded_ids
    )
    assert not any(
        item.get("candidate_id") in excluded_ids
        for entries in final_plan["queries"].values() for item in entries
        if item.get("operation") in {"candidate_detail", "candidate_verification"}
    )


def assessment_for(
    task: dict[str, Any], evidence: dict[str, Any], candidates: dict[str, Any],
    plan: dict[str, Any], risk: str, status: str = "completed",
) -> dict[str, Any]:
    missing = coverage_requirement_gaps(task, evidence, candidates, plan)
    grouped = coverage_gap_groups(task, missing)
    query_gaps = required_query_gaps(task, evidence, plan)
    unverified = material_unverified(
        candidates, strict=True, evidence=evidence, task=task, search_plan=plan,
    )
    final_risk = risk if status == "completed" else ""
    formal_by_module = formal_rating_evidence_by_module(
        task, evidence, candidates, plan,
    )
    risk_module = next(
        (module_id for module_id in MODULE_IDS if formal_by_module.get(module_id)),
        "",
    )
    return {
        "schema_version": task["schema_version"], "task_id": task["task_id"],
        "generated_at": now_iso(), "status": status,
        "overall": {
            "risk": final_risk, "confidence": "高" if status == "completed" else "",
            "discovery_signal": "中" if status != "completed" else risk,
            "provisional": status != "completed", "reasons": ["离线验收固定数据"],
        },
        "modules": {
            module: {
                "risk": risk if module == risk_module else "低",
                "confidence": "高", "reasoning": "离线验收模块说明",
                "findings": [{
                    "finding_id": f"F-{index:03d}", "title": "固定发现",
                    "evidence_refs": [
                        sorted(formal_by_module[module])[0]
                        if module == risk_module else "EV-PRODUCT"
                    ],
                    "recommended_action": "保留证据",
                }],
            }
            for index, module in enumerate(MODULE_IDS, 1)
        },
        "review": {"required": False, "human_review_required": False},
        "coverage": {
            "missing_coverage_requirements": missing,
            "missing_formal_requirements": grouped["formal"],
            "missing_low_risk_requirements": [*grouped["low_risk"], *grouped["unsupported"]],
            "missing_required_sources": [], "missing_required_queries": query_gaps,
            "missing_low_risk_gate_sources": [], "optional_source_losses": [],
            "unverified_material_candidates": unverified,
        },
        "recommended_actions": ["对重大候选保留官方核验链接"],
        "paid_recommendations": paid_recommendations(task, missing, plan, evidence),
    }


def test_v2_report(root: Path) -> None:
    task_dir = new_task(root, "v2-report", "https://www.amazon.com/dp/B0FREE2304", "US")
    task, evidence = prepare_product(task_dir)
    task["state"] = "completed"
    checked_at = now_iso()
    candidates = {
        "schema_version": SCHEMA_VERSION, "task_id": task["task_id"], "generated_at": checked_at,
        "patents": [{
            "candidate_id": "C-US-PAT-001", "jurisdiction": "US", "right_type": "patent",
            "publication_number": "US1234567A1", "title": "Ergonomic support",
            "owners": ["Example Corp"], "legal_status": "published", "material": True,
            "material_reason": "功能特征需进一步比对", "disposition": "material",
            "score": 99,
            "evidence_refs": ["EV-PRODUCT"], "verification_refs": ["EV-USPTO-001"],
            "official_verification": {
                "status": "verified", "authority": "USPTO", "method": "cdp_assisted",
                "identity_match": True, "legal_status": "published", "owner": ["Example Corp"],
                "classes": [], "media": [], "checked_at": checked_at,
                "source": "USPTO Patent Public Search",
                "url": "https://ppubs.uspto.gov/pubwebapp/external.html?q=US1234567A1",
            },
        }],
        "trademarks": [{
            "candidate_id": "C-US-TM-EXCLUDED", "jurisdiction": "US",
            "right_type": "trademark_word", "serial_number": "87654321",
            "mark_text": "UNRELATED", "owner": "Other Corp", "material": False,
            "material_reason": "文字与商品品牌不匹配", "disposition": "excluded",
            "evidence_refs": ["EV-PRODUCT"],
            "official_verification": {"status": "not_checked", "source": "", "url": "", "checked_at": ""},
        }],
    }
    materiality_ledger = reviewed_materiality_fixture(task, candidates, {
        "C-US-PAT-001": (True, "功能特征需进一步比对"),
        "C-US-TM-EXCLUDED": (False, "文字与商品品牌不匹配"),
    })
    candidate_media_paths: list[Path] = []
    candidate_media: list[dict[str, Any]] = []
    for index in range(13):
        path = task_dir / "images" / f"candidate-{index:02d}.png"
        blob = PNG + bytes([index])
        path.write_bytes(blob)
        candidate_media_paths.append(path)
        candidate_media.append({
            "role": f"candidate-{index:02d}", "path": str(path),
            "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob),
            "mime_type": "image/png",
        })
    candidates["patents"][0]["media"] = candidate_media
    patent_requirement = next(
        item["requirement_id"] for item in task["coverage_requirements"]
        if item.get("jurisdiction") == "US"
        and item.get("right_type") == "patent"
        and item.get("phase") == "candidate_verification"
    )
    official_payload = {
        **candidates["patents"][0],
        "official_verification": dict(candidates["patents"][0]["official_verification"]),
    }
    evidence["source_runs"].append({
        "run_id": "RUN-USPTO-001", "attempt_id": "RUN-USPTO-001",
        "query_id": "QRY-USPTO-001", "provider": "uspto_patent_browser",
        "operation": "candidate_verification", "query": "US1234567A1",
        "request_params": {
            "right_type": "patent", "candidate_id": "C-US-PAT-001",
            "record_number": "US1234567A1",
        }, "jurisdiction": "US",
        "right_type": "patent", "requirement_ids": [patent_requirement],
        "started_at": checked_at, "finished_at": checked_at, "status": "success",
        "evidence_type": "official_verification", "raw_paths": [],
        "payload_digest": hashlib.sha256(b"official-fixture").hexdigest(),
        "error_code": "", "detail": "", "retry_count": 0, "quota": {}, "data_date": "",
    })
    evidence["collections"]["official_verifications"].append({
        "evidence_id": "EV-USPTO-001", "source_run_id": "RUN-USPTO-001",
        "query_id": "QRY-USPTO-001", "provider": "uspto_patent_browser",
        "operation": "candidate_verification", "query": "US1234567A1",
        "jurisdiction": "US", "right_type": "patent",
        "requirement_ids": [patent_requirement], "collected_at": checked_at,
        "payload": official_payload,
    })
    assert material_unverified(
        candidates, strict=True,
        evidence={"source_runs": [], "collections": {"official_verifications": []}},
        task=task,
    ) == ["C-US-PAT-001"]
    plan = {
        "schema_version": SCHEMA_VERSION, "task_id": task["task_id"],
        "created_at": checked_at, "terms": [], "classification_candidates": {},
        "queries": {"uspto_patent_browser": [{
            "query_id": "QRY-USPTO-001", "q": "US1234567A1",
            "candidate_id": "C-US-PAT-001", "right_type": "patent",
            "record_number": "US1234567A1",
            "operation": "candidate_verification", "jurisdiction": "US",
            "required": False, "required_for": "formal",
            "requirement_ids": [patent_requirement], "wave": 2,
            "derived_from": ["normalized-candidates:C-US-PAT-001"],
            "execute_by_default": True,
        }]},
        "execution_policy": {
            "commercial_freemium_allowlist": [],
            "commercial_providers_enabled": False,
            "paid_execution_enabled": False,
        },
        **current_policy_contract(),
    }
    plan_entry_digest = sha256_json(plan["queries"]["uspto_patent_browser"][0])
    evidence["source_runs"][-1]["plan_entry_sha256"] = plan_entry_digest
    evidence["collections"]["official_verifications"][-1]["plan_entry_sha256"] = plan_entry_digest
    assessment = assessment_for(task, evidence, candidates, plan, "高")
    assert assessment["coverage"]["missing_low_risk_requirements"]
    assert not assessment["coverage"]["missing_formal_requirements"]
    write_json(task_dir / "task.json", task)
    write_json(task_dir / "evidence.json", evidence)
    write_json(task_dir / "normalized-candidates.json", candidates)
    write_json(task_dir / "materiality-annotations.json", materiality_ledger)
    write_json(task_dir / "search-plan.json", plan)
    write_json(task_dir / "assessment.json", assessment)

    command(str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir))
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")
    expected = {"report.html", "report.md", "report-data.json", "report-findings.csv", "report-manifest.json"}
    assert all((task_dir / name).is_file() for name in expected)
    report_data = json.loads((task_dir / "report-data.json").read_text(encoding="utf-8"))
    manifest = json.loads((task_dir / "report-manifest.json").read_text(encoding="utf-8"))
    html = (task_dir / "report.html").read_text(encoding="utf-8")
    markdown = (task_dir / "report.md").read_text(encoding="utf-8")
    assert report_data["report_mode"] == "Formal" and report_data["decision"]["final_risk"] == "高"
    assert report_data["coverage"]["candidate_count"] == 2
    assert report_data["product"]["main_visual"]["role"] == "main"
    assert len(report_data["visual_evidence"]) == 12
    assert all(item["role"] != "main" for item in report_data["visual_evidence"])
    assert all(item["similarity_display"] == "未评分" for item in report_data["visual_evidence"])
    assert "images/candidate-12.png" not in {
        item["relative_path"] for item in report_data["visual_evidence"]
    }
    assert set(manifest["artifacts"]) == {"report.html", "report.md", "report-data.json", "report-findings.csv"}
    assert manifest["content_digest"] and manifest["formal_status"]["formal_allowed"] is True
    assert html.count("<section id=") == 8
    positions = [html.index(f'<section id="{section}"') for section in SECTION_ORDER]
    assert positions == sorted(positions)
    assert "grid-template-columns: 236px" in html and "max-width: 1180px" in html
    assert "@media (max-width: 900px)" in html and "@media (max-width: 580px)" in html
    assert "@media print" in html and "<script" not in html.casefold()
    assert "data:image/png;base64," in html and "<details" in html
    assert "未评分" in html
    assert all(boundary in html and boundary in markdown for boundary in COVERAGE_BOUNDARIES)
    visible_position = html.index("C-US-PAT-001")
    details_position = html.index('<details class="fold print-hidden">')
    screen_excluded_position = html.index("C-US-TM-EXCLUDED", details_position)
    print_position = html.index(
        '<div class="print-only excluded-print" data-print-excluded-count="1">',
        screen_excluded_position,
    )
    print_excluded_position = html.index("C-US-TM-EXCLUDED", print_position)
    assert (
        visible_position < details_position < screen_excluded_position
        < print_position < print_excluded_position
    )
    report_browser_acceptance(task_dir / "report.html")

    original_assessment = (task_dir / "assessment.json").read_bytes()
    missing_module_assessment = json.loads(original_assessment)
    missing_module_assessment["modules"].pop("enforcement")
    invalid_gate = release_gate(
        task, evidence, missing_module_assessment, candidates,
        {"schema_version": "1.0", "task_id": task["task_id"], "entries": []}, plan,
    )
    assert invalid_gate["formal_allowed"] is False
    assert "ASSESSMENT_MODULES_INVALID" in {
        blocker["code"] for blocker in invalid_gate["blockers"]
    }
    write_json(task_dir / "assessment.json", missing_module_assessment)
    command(
        str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="INVALID_ASSESSMENT_MODULES",
    )
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="INVALID_ASSESSMENT_MODULES",
    )
    invalid_field_assessment = json.loads(original_assessment)
    invalid_field_assessment["modules"]["enforcement"]["confidence"] = "unknown"
    write_json(task_dir / "assessment.json", invalid_field_assessment)
    command(
        str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="INVALID_ASSESSMENT_MODULES",
    )
    (task_dir / "assessment.json").write_bytes(original_assessment)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    original_ledger = (task_dir / "materiality-annotations.json").read_bytes()
    changed_ledger = json.loads(original_ledger)
    changed_ledger["annotations"][0]["material_reason"] = "未经重新 merge 的新判断"
    write_json(task_dir / "materiality-annotations.json", changed_ledger)
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="materiality",
    )
    (task_dir / "materiality-annotations.json").write_bytes(original_ledger)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    incomplete_ledger = json.loads(original_ledger)
    incomplete_ledger["annotations"] = incomplete_ledger["annotations"][:1]
    write_json(task_dir / "materiality-annotations.json", incomplete_ledger)
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="no materiality ledger decision",
    )
    duplicate_ledger = json.loads(original_ledger)
    duplicate_ledger["annotations"][1]["annotation_id"] = duplicate_ledger["annotations"][0]["annotation_id"]
    write_json(task_dir / "materiality-annotations.json", duplicate_ledger)
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="duplicate materiality annotation_id",
    )
    fingerprint_ledger = json.loads(original_ledger)
    fingerprint_ledger["annotations"][0]["candidate_identity_fingerprint"] = "0" * 64
    write_json(task_dir / "materiality-annotations.json", fingerprint_ledger)
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="candidate fingerprint mismatch",
    )
    (task_dir / "materiality-annotations.json").write_bytes(original_ledger)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    original_html = (task_dir / "report.html").read_bytes()
    (task_dir / "report.html").write_bytes(original_html + b"\n")
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="artifact digest/byte mismatch",
    )
    (task_dir / "report.html").write_bytes(original_html)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    original_task = (task_dir / "task.json").read_bytes()
    invalid_task = json.loads(original_task)
    invalid_task["coverage_requirements"] = invalid_task["coverage_requirements"][:1]
    write_json(task_dir / "task.json", invalid_task)
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="COVERAGE_REQUIREMENTS_INVALID",
    )
    command(
        str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="COVERAGE_REQUIREMENTS_INVALID",
    )
    (task_dir / "task.json").write_bytes(original_task)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    original_manifest = (task_dir / "report-manifest.json").read_bytes()
    (task_dir / "report-manifest.json").write_bytes(original_manifest + b"\n")
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="manifest file digest mismatch",
    )
    (task_dir / "report-manifest.json").write_bytes(original_manifest)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    original_evidence = (task_dir / "evidence.json").read_bytes()
    invalid_evidence = json.loads(original_evidence)
    invalid_evidence["source_runs"][0]["right_type"] = "design"
    write_json(task_dir / "evidence.json", invalid_evidence)
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="invalid requirement binding",
    )
    (task_dir / "evidence.json").write_bytes(original_evidence)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    unplanned_evidence = json.loads(original_evidence)
    verification_entry = unplanned_evidence["collections"]["official_verifications"][0]
    verification_run = next(
        run for run in unplanned_evidence["source_runs"]
        if run.get("run_id") == verification_entry.get("source_run_id")
    )
    verification_entry["query_id"] = "QRY-NOT-IN-PLAN"
    verification_run["query_id"] = "QRY-NOT-IN-PLAN"
    write_json(task_dir / "evidence.json", unplanned_evidence)
    command(
        str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="OFFICIAL_VERIFICATION_PLAN_BINDING_INVALID",
    )
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="OFFICIAL_VERIFICATION_PLAN_BINDING_INVALID",
    )
    (task_dir / "evidence.json").write_bytes(original_evidence)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    original_candidates = (task_dir / "normalized-candidates.json").read_bytes()
    forged_candidates = json.loads(original_candidates)
    forged_candidates["patents"][0]["official_verification"]["owner"] = ["Forged Owner"]
    write_json(task_dir / "normalized-candidates.json", forged_candidates)
    command(
        str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="top-level official_verification",
    )
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="top-level official_verification",
    )
    (task_dir / "normalized-candidates.json").write_bytes(original_candidates)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    main_image = Path(task["images"][0]["path"])
    original_image = main_image.read_bytes()
    main_image.write_bytes(original_image + b"tamper")
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="Main image path/hash validation failed",
    )
    main_image.write_bytes(original_image)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    omitted_visual = candidate_media_paths[-1]
    original_omitted_visual = omitted_visual.read_bytes()
    omitted_visual.write_bytes(original_omitted_visual + b"tamper")
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="Declared visual integrity failure",
    )
    omitted_visual.write_bytes(original_omitted_visual)
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")

    assessment = assessment_for(task, evidence, candidates, plan, "高", status="incomplete")
    task["state"] = "incomplete"
    write_json(task_dir / "task.json", task)
    write_json(task_dir / "assessment.json", assessment)
    command(str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir))
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")
    draft = json.loads((task_dir / "report-data.json").read_text(encoding="utf-8"))
    draft_html = (task_dir / "report.html").read_text(encoding="utf-8")
    draft_markdown = (task_dir / "report.md").read_text(encoding="utf-8")
    draft_csv = list(csv.DictReader(io.StringIO(
        (task_dir / "report-findings.csv").read_text(encoding="utf-8-sig")
    )))
    assert draft["report_mode"] == "Draft"
    assert draft["decision"]["final_risk"] is None and draft["decision"]["display_risk"] == "中"
    assert [module["module_id"] for module in draft["modules"]] == MODULE_IDS
    assert all(
        module["risk"] == "无法判断"
        and module["confidence"] == "无法判断"
        and module["risk_basis"] == "discovery_only"
        for module in draft["modules"]
    )
    assert draft_html.count("发现层风险（非正式）") == 1
    assert draft_markdown.count("发现层风险（非正式）") == 1
    assert all(
        row["module_risk"] == "无法判断" and row["module_confidence"] == "无法判断"
        for row in draft_csv
    )

    forbidden = task_dir / "wipo-capture.json"
    forbidden.write_text("{}\n", encoding="utf-8")
    command(
        str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="prohibit WIPO",
    )
    forbidden.unlink()
    task["free_policy"] = {**active_free_policy(), "allow_paid": True}
    write_json(task_dir / "task.json", task)
    command(
        str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="FREE_POLICY_INVALID",
    )


def test_legacy_report(root: Path) -> None:
    task_dir = new_task(root, "legacy-report", "https://www.amazon.com/dp/B0FREE2305", "US")
    task, evidence = prepare_product(task_dir)
    task.update({
        "schema_version": "2.2-free", "state": "completed",
        "required_sources": [], "low_risk_gate_sources": [], "optional_sources": [],
    })
    task.pop("coverage_requirements", None)
    task.pop("free_policy", None)
    evidence["schema_version"] = "2.2-free"
    candidates = {
        "schema_version": "2.2-free", "task_id": task["task_id"],
        "generated_at": now_iso(), "patents": [], "trademarks": [],
    }
    plan = {"schema_version": "2.2-free", "task_id": task["task_id"], "queries": {}}
    assessment = {
        "schema_version": "2.2-free", "task_id": task["task_id"], "status": "completed",
        "overall": {"risk": "中", "confidence": "高", "provisional": False, "reasons": []},
        "modules": {
            module: {"risk": "中", "confidence": "高", "reasoning": "legacy", "findings": []}
            for module in MODULE_IDS
        },
        "review": {"required": False, "human_review_required": False},
        "coverage": {
            "missing_required_sources": [], "missing_required_queries": [],
            "missing_low_risk_gate_sources": [], "optional_source_losses": [],
            "unverified_material_candidates": [],
        },
        "recommended_actions": [],
    }
    for name, value in (
        ("task.json", task), ("evidence.json", evidence), ("normalized-candidates.json", candidates),
        ("search-plan.json", plan), ("assessment.json", assessment),
    ):
        write_json(task_dir / name, value)
    command(str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir))
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")
    assert 'name="report-schema" content="IPR-EVIDENCE-DOSSIER/1.0"' in (task_dir / "report.html").read_text(encoding="utf-8")
    command(
        str(SCRIPTS / "record_patent_browser_recall.py"), "--task-dir", str(task_dir),
        "--provider", "wipo_patentscope_browser", "--capture", str(root / "absent.json"),
        succeeds=False, contains="LEGACY_TASK_READ_ONLY",
    )


def test_legacy_21_espacenet_gate(root: Path) -> None:
    task_dir = new_task(root, "legacy-21-espacenet", "https://www.amazon.com/dp/B0FREE2304", "US")
    task, evidence = prepare_product(task_dir)
    task.update({
        "schema_version": "2.1-free", "state": "completed",
        "required_sources": [], "low_risk_gate_sources": ["espacenet_browser"],
        "optional_sources": [],
    })
    task.pop("coverage_requirements", None)
    task.pop("free_policy", None)
    evidence["schema_version"] = "2.1-free"
    candidates = {
        "schema_version": "2.1-free", "task_id": task["task_id"],
        "generated_at": now_iso(), "patents": [], "trademarks": [],
    }
    query_id = "LEGACY-ESPACENET-001"
    query = "cat paw ergonomic mouse pad"
    plan = {
        "schema_version": "2.1-free", "task_id": task["task_id"],
        "queries": {"espacenet_browser": [{"query_id": query_id, "q": query}]},
    }
    assessment = {
        "schema_version": "2.1-free", "task_id": task["task_id"], "status": "completed",
        "overall": {"risk": "低", "confidence": "高", "provisional": False, "reasons": []},
        "modules": {
            module: {"risk": "低", "confidence": "高", "reasoning": "legacy", "findings": []}
            for module in MODULE_IDS
        },
        "review": {"required": False, "human_review_required": False},
        "coverage": {
            "missing_required_sources": [], "missing_required_queries": [],
            "missing_low_risk_gate_sources": [], "optional_source_losses": [],
            "unverified_material_candidates": [],
        },
        "recommended_actions": [],
    }
    for name, value in (
        ("task.json", task), ("evidence.json", evidence),
        ("normalized-candidates.json", candidates), ("search-plan.json", plan),
        ("assessment.json", assessment),
    ):
        write_json(task_dir / name, value)

    # A legacy low-risk rebuild must remain invalid until every planned
    # Espacenet patent_recall has matching terminal evidence.
    command(str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir))
    command(
        str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir),
        succeeds=False, contains="Assessment coverage is stale for missing_low_risk_gate_sources",
    )

    evidence["source_runs"].append({
        "run_id": "RUN-LEGACY-ESPACENET-001", "provider": "espacenet_browser",
        "operation": "patent_recall", "status": "no_result", "query_id": query_id,
        "query": query, "jurisdiction": "US", "raw_paths": [],
    })
    write_json(task_dir / "evidence.json", evidence)
    command(str(SCRIPTS / "build_report.py"), "--task-dir", str(task_dir))
    command(str(SCRIPTS / "validate_run.py"), "--task-dir", str(task_dir), contains="run valid")
    assert 'name="report-schema" content="IPR-EVIDENCE-DOSSIER/1.0"' in (
        task_dir / "report.html"
    ).read_text(encoding="utf-8")


def _main() -> None:
    with tempfile.TemporaryDirectory(prefix="lc-ipr-2.3-self-test-") as temporary:
        root = Path(temporary)
        test_routing(root)
        test_optional_discovery_incomplete_query_contract(root)
        test_route_requires_all_exact_planned_queries()
        test_paid_recommendations_require_exhausted_free_routes()
        test_no_paid_or_wipo_network(root)
        test_legacy_23_policy_without_revision(root)
        test_frozen_default_discovery_revision(root)
        test_optional_signa_discovery_contract(root)
        test_optional_serper_discovery(root)
        test_serpapi_free_opt_in_and_fallback(root)
        test_redaction_and_runner_output_contract()
        test_unicode_and_japanese_plan(root)
        test_query_plan_right_type_binding(root)
        test_candidate_right_type_binding()
        test_intrinsic_document_types_and_trademark_keys()
        test_euipo_110_contract()
        test_euipo_probe_is_oauth_only()
        test_api_fixture_authority_guards()
        test_national_effect_and_identity_mismatch_gates()
        test_eu_candidate_verification_actions(root)
        test_wo_family_candidate_routes(root)
        test_epo_candidate_detail_contracts(root)
        test_official_public_record_url_allowlist()
        test_quota_and_jpo_contracts()
        test_materiality_annotation_reachability(root)
        test_public_candidate_chain()
        test_public_candidate_verification_actions()
        test_evidence_backed_medium_high_gate()
        test_excluded_mismatch_action_is_repairable()
        test_registry_verification_records_planned_query()
        test_jplatpat_skip_requires_exact_jpo_plan()
        test_v2_report(root)
        test_legacy_report(root)
        test_legacy_21_espacenet_gate(root)
    print("self-test passed: schema/optional-discovery/routing/cost/JPO/CDP-report/legacy")


def main() -> None:
    with isolated_test_environment():
        _main()


if __name__ == "__main__":
    main()

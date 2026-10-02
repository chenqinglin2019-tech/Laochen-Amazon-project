#!/usr/bin/env python3
"""Create a single-product task from an Amazon URL or reviewed user materials."""

from __future__ import annotations

import argparse
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from common import (
    AMAZON_EU_COUNTRIES, EU_COUNTRIES, FREE_POLICY_REVISION, MARKETPLACE_BY_HOST,
    SCHEMA_VERSION, CURRENT_SCHEMA_VERSION, AUTOMATION_POLICY_REVISION, active_free_policy,
    atomic_write_json, build_coverage_requirements, default_jurisdictions,
    load_skill_config, now_iso, serper_free_enhancement, signa_free_enhancement, split_csv,
    serpapi_free_enhancement, stable_id,
    RECALL_INTEGRITY_REVISION, API_FIRST_V3_REVISION,
)
from decision_workflow import REVISION as DECISION_WORKFLOW_REVISION, default_assessment_scenarios


ASIN_PATTERNS = [r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)", r"[?&]asin=([A-Z0-9]{10})(?:&|$)"]


def parse_amazon_url(raw_url: str) -> tuple[str, str, str]:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    if host not in MARKETPLACE_BY_HOST or parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must be a supported Amazon product URL")
    asin = ""
    for pattern in ASIN_PATTERNS:
        match = re.search(pattern, raw_url, flags=re.IGNORECASE)
        if match:
            asin = match.group(1).upper()
            break
    return host, MARKETPLACE_BY_HOST[host], asin


def main() -> None:
    parser = argparse.ArgumentParser(description="Create one free-tier IPR task from an Amazon URL or reviewed user materials.")
    parser.epilog = "New tasks use API-first retrieval, independent final review, and known-findings-risk-v1 operating grades with separate query progress. Historical tasks retain their original policy."
    entry = parser.add_mutually_exclusive_group(required=True)
    entry.add_argument("--url")
    entry.add_argument("--product-input", type=Path, help="Reviewed product-input-v2 JSON (v1 compatibility accepted); country must be explicit")
    parser.add_argument("--jurisdictions", default="")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report-export", action="append", choices=("markdown", "csv"), default=[])
    parser.add_argument("--stage-carrier", action="append", choices=("reply", "html", "markdown", "csv"))
    parser.add_argument("--guard-session-id", help="Actual Codex session ID; opt into session-scoped continuation")
    parser.add_argument("--schema-version", choices=("2.3-free", "2.4-free"), default=CURRENT_SCHEMA_VERSION,
                        help=argparse.SUPPRESS)
    parser.add_argument("--product-role", choices=("actual_product", "reference_product"), default=None,
                        help="Whether the URL describes the actual intended product or only a reference competitor")
    parser.add_argument("--genuine-resale", action="store_true",
                        help="Explicitly request an additional genuine-resale scenario; does not assert authenticity or permission")
    parser.add_argument(
        "--enable-serper-free", action="store_true",
        help=(
            "Optionally add bounded Serper patent, web, and image discovery; "
            "requires SERPER_API_KEY; valid returned fields support analysis directly."
        ),
    )
    parser.add_argument("--use-serper-existing-balance", action="store_true",
                        help="Only with explicit user authorization: use existing Serper credits without account-page inspection; never purchase or recharge")
    parser.add_argument(
        "--enable-signa-free", action="store_true",
        help=(
            "Optionally add bounded Signa trademark discovery; requires SIGNA_API_KEY. "
            "Valid returned details and samples support analysis directly."
        ),
    )
    parser.add_argument(
        "--enable-serpapi-free", action="store_true",
        help=(
            "Optionally add bounded SerpApi Free-plan Google Patents discovery; requires "
            "SERPAPI_API_KEY. Source selection follows country, right and required information."
        ),
    )
    args = parser.parse_args()
    if args.use_serper_existing_balance and not args.enable_serper_free:
        raise SystemExit("Existing Serper balance authorization requires --enable-serper-free")
    if args.use_serper_existing_balance and args.schema_version != CURRENT_SCHEMA_VERSION:
        raise SystemExit("Existing Serper balance authorization requires a new API-first task")
    if args.schema_version != CURRENT_SCHEMA_VERSION and os.environ.get("LC_IPR_TEST_MODE") != "1":
        raise SystemExit("New tasks use 2.4-free; 2.3 creation is reserved for frozen compatibility tests")
    schema_version = args.schema_version
    current = schema_version == CURRENT_SCHEMA_VERSION

    from product_entry import REVISION as ENTRY_REVISION, COUNTRIES, load_materials
    materials = None
    if args.product_input:
        if not current:
            raise SystemExit("User materials require the current task schema")
        if not args.jurisdictions.strip():
            raise SystemExit("USER_MATERIALS_TARGET_COUNTRY_REQUIRED")
        materials = load_materials(args.product_input)
        host, marketplace, asin = "", "", ""
    else:
        host, marketplace, asin = parse_amazon_url(args.url)
        if not asin:
            raise SystemExit("Amazon product URL must contain a ten-character ASIN")
    jurisdictions = split_csv(args.jurisdictions) or default_jurisdictions(marketplace)
    if current and (not any(v in COUNTRIES for v in jurisdictions) or set(jurisdictions) - COUNTRIES - {"EU"}):
        raise SystemExit("SUPPORTED_TARGET_COUNTRY_REQUIRED")
    if "EU" not in jurisdictions and any(value in EU_COUNTRIES for value in jurisdictions):
        jurisdictions = ["EU", *jurisdictions]
    if not jurisdictions:
        raise SystemExit("At least one target jurisdiction is required")
    config = load_skill_config()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if args.output_dir:
        output_dir = args.output_dir.expanduser().resolve()
    else:
        configured_root = Path(str(config.get("default_runs_dir", "runs-free"))).expanduser()
        root = configured_root if configured_root.is_absolute() else Path.cwd() / configured_root
        output_dir = (root / f"{asin or 'PRODUCT'}_{stamp}").resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"Output directory must be empty: {output_dir}")

    created = now_iso()
    task_id = f"IPRF-{uuid.uuid4().hex[:12]}"
    coverage_requirements = build_coverage_requirements(jurisdictions)
    if current:
        from workflow_v24 import build_coverage_requirements_v24, TARGET_COUNTRIES
        coverage_requirements = build_coverage_requirements_v24(jurisdictions, screening_revision=RECALL_INTEGRITY_REVISION, specialty_workflow_revision="asset-scope-v1")
    supported_jurisdictions = TARGET_COUNTRIES if current else {"US", "EU", "JP", "GB", *AMAZON_EU_COUNTRIES}
    unsupported = sorted(set(jurisdictions) - supported_jurisdictions)
    task = {
        "schema_version": schema_version,
        "task_id": task_id,
        "state": "pending",
        "created_at": created,
        "updated_at": created,
        "request": {"url": args.url or "", "amazon_host": host, "marketplace": marketplace},
        "product": {
            "requested_asin": asin, "actual_asin": "", "title": "", "brand": "",
            "manufacturer": "", "category": "", "bullets": [], "specifications": {},
            "structure": [], "visible_ip_claims": [], "variant": {},
            **({"input_role": args.product_role or "reference_product", "intended_use": "", "assets": [], "image_coverage": {"status": "unknown", "missing_views": []}} if current else {}),
        },
        "images": [],
        "target_jurisdictions": jurisdictions,
        "coverage_requirements": coverage_requirements,
        "free_policy": active_free_policy(),
        "free_policy_revision": AUTOMATION_POLICY_REVISION if current else FREE_POLICY_REVISION,
        "serper_free_enhancement": serper_free_enhancement(args.enable_serper_free),
        "signa_free_enhancement": signa_free_enhancement(args.enable_signa_free),
        "serpapi_free_enhancement": serpapi_free_enhancement(args.enable_serpapi_free),
        "optional_sources": [],
        "checkpoints": {
            "optional_discovery_selection": {
                "status": "selected" if any((
                    args.enable_serper_free,
                    args.enable_signa_free,
                    args.enable_serpapi_free,
                )) else "not_selected",
                "at": created,
                "required_for_minimum": False,
                "providers": {
                    "serper": {
                        "enabled": args.enable_serper_free,
                        "credential_file": ".env", "credential_key": "SERPER_API_KEY",
                    },
                    "signa": {
                        "enabled": args.enable_signa_free,
                        "credential_file": ".env", "credential_key": "SIGNA_API_KEY",
                    },
                    "serpapi": {
                        "enabled": args.enable_serpapi_free,
                        "credential_file": ".env", "credential_key": "SERPAPI_API_KEY",
                    },
                },
                "detail": (
                    "Official free APIs and visible official-register CDP are the minimum route. "
                    "Serper, Signa, and SerpApi are optional recall enhancements; provide their "
                    "credentials and select the matching create-task flags only when desired."
                ),
            },
        },
        "coverage_gaps": [
            {
                "provider": "official_registry_browser",
                "jurisdiction": jurisdiction,
                "status": "access_limited",
                "error_code": "UNSUPPORTED_JURISDICTION_ROUTE",
                "affected_modules": [],
                "detail": (
                    f"No accepted official-registry adapter is configured for {jurisdiction}; "
                    "the jurisdiction cannot receive a formal low-risk conclusion"
                ),
                "mandatory": True,
                "query_id": "",
                "at": created,
            }
            for jurisdiction in unsupported
        ],
        "errors": [], "outputs": {}, "paid_recommendations": [],
        "history": [{
            "state": "pending", "at": created,
            "note": (
                "URL task shell created with the official-free/API and visible-CDP minimum route; "
                "selected optional discovery: "
                + (
                    ", ".join(
                        name for name, enabled in (
                            ("Serper", args.enable_serper_free),
                            ("Signa", args.enable_signa_free),
                            ("SerpApi", args.enable_serpapi_free),
                        ) if enabled
                    ) or "none"
                )
            ),
        }],
    }
    if current:
        # Policy is versioned separately from immutable collection contracts.
        # Existing tasks without this field retain their historical evaluator.
        task["assessment_policy"] = "evidence-estimate-v1"
        task["assessment_revision"] = "known-findings-risk-v1"
        task["presentation_policy_revision"] = "operator-report-v1"
        task["product_structure_policy"] = "use_provided_else_unavailable_v1"
        # Progress and scope-change history use the same initial version.
        task["product_change_version"] = 1
        task["final_review_execution_revision"] = "module-double-review-v1"
        task["screening_revision"] = RECALL_INTEGRITY_REVISION
        task["recall_planning_revision"] = "identity-discovery-v1"
        task["specialty_workflow_revision"] = "asset-scope-v1"
        task["decision_workflow_revision"] = DECISION_WORKFLOW_REVISION
        task["workflow_correction_revision"] = "workflow-correction-v1"
        # The dispatcher consumes the existing next_work projection.  This is
        # a new-task policy marker only; historical runs retain their prior
        # stopping and recovery semantics.
        task["execution_policy_revision"] = "continuous-work-v2"
        task["continuous_work_stage_revision"] = "continuous-work-stage-a-v1"
        task["continuous_recovery_revision"] = "continuous-recovery-stage-b-v1"
        task["continuous_continuation_revision"] = "continuous-continuation-stage-c-v1"
        task["continuous_progress_revision"] = "continuous-progress-stage-d-v1"
        from execution_budget import DEFAULTS, REVISION as BUDGET_REVISION, policy as budget_policy
        task['execution_budget_revision'] = BUDGET_REVISION
        task['execution_budget'] = {**DEFAULTS, **config.get('execution_budget', {})}
        budget_policy(task)
        task["review_progress_revision"] = "review-progress-stage-a-v1"
        task["stage_risk_revision"] = "stage-risk-stage-b-v1"
        task["stage_review_revision"] = "stage-review-stage-c-v1"
        task["stage_delivery_revision"] = "stage-delivery-stage-d-v1"
        task["report_presentation_revision"] = "report-presentation-stage-a-v1"
        task["business_status_revision"] = "business-status-stage-b-v1"
        task["delivery_versions_revision"] = "delivery-versions-stage-e-v1"
        task["delivery_inspection_revision"] = "delivery-inspection-stage-d-v1"
        task["report_package_revision"] = "report-package-stage-c-v1"
        task["report_exports"] = sorted(set(args.report_export))
        task["stage_carriers"] = sorted(set(args.stage_carrier or ["reply"]))
        from completion_policy import CURRENT_REVISION
        task["completion_policy_revision"] = CURRENT_REVISION
        task["retrieval_workflow_revision"] = API_FIRST_V3_REVISION
        task["review_policy_revision"] = "final-double-review-v1"
        task["discovery_budget_revision"] = "discovery-purpose-budget-v1"
        task["discovery_semantics_revision"] = "discovery-semantics-v1"
        task["source_operation_revision"] = "source-operation-v2"
        task["result_processing_revision"] = "source-result-processing-v1"
        task["candidate_identity_revision"] = "candidate-identity-v1"
        task["candidate_acquisition_revision"] = "candidate-acquisition-v1"
        task["candidate_handoff_revision"] = "candidate-handoff-v1"
        task["triage_scope_revision"] = "candidate-triage-scope-v1"
        task["triage_followup_revision"] = "candidate-followup-v1"
        task["triage_stage_revision"] = "candidate-triage-stage-v1"
        task["specialty_analysis_revision"] = "specialty-analysis-v1"
        task["distinctive_rights_revision"] = "distinctive-rights-v1"
        task["epo_query_revision"] = "ops-cql-v1"
        # New-task policies (existing tasks lack these keys and keep their behavior):
        # limited reports for failed/stopped actions, and structured-only reviewer conflicts.
        task["limited_delivery_revision"] = "failure-limits-v1"
        task["review_conflict_revision"] = "structured-conflicts-v1"
        retrieval = config["api_first"]
        task["retrieval_policy"] = dict(retrieval)
        task["serper_free_enhancement"]["max_queries_per_task"] = retrieval["serper_max_requests"]
        task["serpapi_free_enhancement"]["max_queries_per_task"] = retrieval["serpapi_max_requests"]
        task["serpapi_free_enhancement"]["fallback_only_when_serper_enabled"] = False
        if args.use_serper_existing_balance:
            task["serper_existing_balance_authorization"] = {
                "authorized": True, "source": "explicit_user_instruction", "authorized_at": created,
                "max_requests": retrieval["serper_max_requests"], "allow_recharge": False, "allow_new_purchase": False,
            }
        task["assessment_scenarios"] = default_assessment_scenarios(genuine_resale=args.genuine_resale)
        task["primary_scenario_id"] = "product_entry"
        task["execution_scenario_ids"] = ["product_entry"]
        task["request"]["genuine_resale"] = args.genuine_resale
        task["product"]["intended_use"] = (
            "选品进入：以链接展示的结构、功能与用途作同结构条件假设；不判断原卖家责任，"
            "不依赖未知许可，不默认沿用品牌或复制素材。"
        )
        task["execution_policy"] = {
            "mode": "automation_first", "human_actions": ["login", "captcha", "mfa", "consent", "qr"],
            "manual_business_work": False, "cost_ceiling_usd": 0,
        }
        task["query_terms"] = []
        task["checkpoints"]["optional_discovery_selection"]["detail"] = (
            "Available selected free APIs perform bounded discovery before agent triage and targeted verification. "
            "Missing capabilities remain explicit; browser discovery requires a reviewed bounded fallback."
        )
    if current:
        task["product_entry_revision"] = ENTRY_REVISION
        task["product_scope_required"] = True
        task["request"].update(entry_type="user_materials" if materials else "amazon_url",
                               jurisdiction_source="user" if args.jurisdictions.strip() else "marketplace")
        task["product"].update(product_id=stable_id("PRODUCT", task_id),
                               input_role_source="user" if args.product_role else "default")
        task["product_identity"] = {"status": "pending"}
        if materials:
            task["product"]["intended_use"] = task["product"]["intended_use"].replace("链接展示", "用户资料展示")
            task["request"].update(input_path=str(args.product_input.expanduser().resolve()),
                                   input_fingerprint=materials["fingerprint"])
            task["history"][0]["note"] = "Single-product user-materials task created; credentials preflight and source retention pending."
    evidence = {
        "schema_version": schema_version, "task_id": task_id,
        "created_at": created, "updated_at": created, "source_runs": [],
        "collections": {
            "product": [], "patents": [], "trademarks": [], "copyright_assets": [],
            "enforcement": [], "official_verifications": [], "browser": [], "blacklist": [],
            **({"asset_provenance": []} if current else {}),
        },
    }
    assessment = {
        "schema_version": schema_version, "task_id": task_id, "status": "not_started",
        "overall": {
            "risk": "", "confidence": "", "discovery_signal": "",
            "provisional": True, "reasons": [],
        },
        "modules": {}, "review": {"required": False, "human_review_required": False},
    }
    if current and task.get("retrieval_workflow_revision") == API_FIRST_V3_REVISION:
        from coverage_v3 import build_requirements, PUBLIC_DISCOVERY_REVISION
        task['public_discovery_routing_revision'] = PUBLIC_DISCOVERY_REVISION
        task["coverage_requirements"] = build_requirements(task, task["coverage_requirements"])
    for subdir in ("raw", "images", "screenshots"):
        (output_dir / subdir).mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "task.json", task)
    atomic_write_json(output_dir / "evidence.json", evidence)
    atomic_write_json(output_dir / "assessment.json", assessment)
    atomic_write_json(output_dir / "materiality-annotations.json", {
        "schema_version": "2.0" if current else "1.0", "task_id": task_id,
        "created_at": created, "updated_at": created, "annotations": [],
    })
    from codex_guard import register_if_requested
    register_if_requested(args.guard_session_id, output_dir)
    print(output_dir)


if __name__ == "__main__":
    main()

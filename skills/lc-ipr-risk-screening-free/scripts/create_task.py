#!/usr/bin/env python3
"""Create a URL-only single-product screening task shell."""

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
    serpapi_free_enhancement,
    RECALL_INTEGRITY_REVISION,
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
    parser = argparse.ArgumentParser(description="Create one free-tier IPR task from an Amazon URL.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--jurisdictions", default="")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--schema-version", choices=("2.3-free", "2.4-free"), default=CURRENT_SCHEMA_VERSION,
                        help=argparse.SUPPRESS)
    parser.add_argument("--product-role", choices=("actual_product", "reference_product"), default="reference_product",
                        help="Whether the URL describes the actual intended product or only a reference competitor")
    parser.add_argument("--genuine-resale", action="store_true",
                        help="Explicitly request an additional genuine-resale scenario; does not assert authenticity or permission")
    parser.add_argument(
        "--enable-serper-free", action="store_true",
        help=(
            "Optionally add bounded Serper patent, web, and image discovery; "
            "requires SERPER_API_KEY and never satisfies an official coverage gate."
        ),
    )
    parser.add_argument(
        "--enable-signa-free", action="store_true",
        help=(
            "Optionally add bounded Signa word-mark discovery; requires SIGNA_API_KEY "
            "and every material hit still requires official-register verification."
        ),
    )
    parser.add_argument(
        "--enable-serpapi-free", action="store_true",
        help=(
            "Optionally add bounded SerpApi Free-plan Google Patents discovery; requires "
            "SERPAPI_API_KEY and, when Serper is also selected, runs only as its fallback."
        ),
    )
    args = parser.parse_args()
    if args.schema_version != CURRENT_SCHEMA_VERSION and os.environ.get("LC_IPR_TEST_MODE") != "1":
        raise SystemExit("New tasks use 2.4-free; 2.3 creation is reserved for frozen compatibility tests")
    schema_version = args.schema_version
    current = schema_version == CURRENT_SCHEMA_VERSION

    host, marketplace, asin = parse_amazon_url(args.url)
    if not asin:
        raise SystemExit("Amazon product URL must contain a ten-character ASIN")
    jurisdictions = split_csv(args.jurisdictions) or default_jurisdictions(marketplace)
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
        output_dir = (root / f"{asin}_{stamp}").resolve()
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
        "request": {"url": args.url, "amazon_host": host, "marketplace": marketplace},
        "product": {
            "requested_asin": asin, "actual_asin": "", "title": "", "brand": "",
            "manufacturer": "", "category": "", "bullets": [], "specifications": {},
            "structure": [], "visible_ip_claims": [], "variant": {},
            **({"input_role": args.product_role, "intended_use": "", "assets": [], "image_coverage": {"status": "unknown", "missing_views": []}} if current else {}),
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
        task["screening_revision"] = RECALL_INTEGRITY_REVISION
        task["recall_planning_revision"] = "identity-discovery-v1"
        task["specialty_workflow_revision"] = "asset-scope-v1"
        task["decision_workflow_revision"] = DECISION_WORKFLOW_REVISION
        task["workflow_correction_revision"] = "workflow-correction-v1"
        task["assessment_scenarios"] = default_assessment_scenarios(genuine_resale=args.genuine_resale)
        task["primary_scenario_id"] = "product_entry"
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
            "Selected free discovery sources broaden recall. Unconfigured official APIs do not block task startup; "
            "unfulfilled search and verification capabilities remain explicit coverage gaps."
        )
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
    for subdir in ("raw", "images", "screenshots"):
        (output_dir / subdir).mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "task.json", task)
    atomic_write_json(output_dir / "evidence.json", evidence)
    atomic_write_json(output_dir / "assessment.json", assessment)
    atomic_write_json(output_dir / "materiality-annotations.json", {
        "schema_version": "2.0" if current else "1.0", "task_id": task_id,
        "created_at": created, "updated_at": created, "annotations": [],
    })
    print(output_dir)


if __name__ == "__main__":
    main()

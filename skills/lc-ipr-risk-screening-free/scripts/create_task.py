#!/usr/bin/env python3
"""Create a URL-only single-product screening task shell."""

from __future__ import annotations

import argparse
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from common import (
    MARKETPLACE_BY_HOST, SCHEMA_VERSION, atomic_write_json, default_jurisdictions,
    load_skill_config, low_risk_gate_providers, now_iso, required_providers, split_csv,
)


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
    args = parser.parse_args()

    host, marketplace, asin = parse_amazon_url(args.url)
    if not asin:
        raise SystemExit("Amazon product URL must contain a ten-character ASIN")
    jurisdictions = split_csv(args.jurisdictions) or default_jurisdictions(marketplace)
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
    providers = required_providers(jurisdictions)
    optional_sources = ["serper_lens", "copyright_registry"]
    if "US" in {value.upper() for value in jurisdictions}:
        # EPO OPS is a US low-risk gate, but an account issue must not prevent
        # detected higher-risk evidence from being collected and reported.
        optional_sources.extend(["epo_ops", "signa", "rapidapi_uspto_trademark"])
    task = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "state": "pending",
        "created_at": created,
        "updated_at": created,
        "request": {"url": args.url, "amazon_host": host, "marketplace": marketplace},
        "product": {
            "requested_asin": asin, "actual_asin": "", "title": "", "brand": "",
            "manufacturer": "", "category": "", "bullets": [], "specifications": {},
            "structure": [], "visible_ip_claims": [], "variant": {},
        },
        "images": [],
        "target_jurisdictions": jurisdictions,
        "required_sources": providers,
        "low_risk_gate_sources": low_risk_gate_providers(jurisdictions),
        "optional_sources": optional_sources,
        "checkpoints": {}, "coverage_gaps": [], "errors": [], "outputs": {},
        "history": [{"state": "pending", "at": created, "note": "URL task shell created"}],
    }
    evidence = {
        "schema_version": SCHEMA_VERSION, "task_id": task_id,
        "created_at": created, "updated_at": created, "source_runs": [],
        "collections": {
            "product": [], "patents": [], "trademarks": [], "copyright_assets": [],
            "enforcement": [], "official_verifications": [], "browser": [], "blacklist": [],
        },
    }
    assessment = {
        "schema_version": SCHEMA_VERSION, "task_id": task_id, "status": "not_started",
        "overall": {"risk": "", "confidence": "", "provisional": True, "reasons": []},
        "modules": {}, "review": {"required": False, "human_review_required": False},
    }
    for subdir in ("raw", "images", "screenshots"):
        (output_dir / subdir).mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "task.json", task)
    atomic_write_json(output_dir / "evidence.json", evidence)
    atomic_write_json(output_dir / "assessment.json", assessment)
    print(output_dir)


if __name__ == "__main__":
    main()

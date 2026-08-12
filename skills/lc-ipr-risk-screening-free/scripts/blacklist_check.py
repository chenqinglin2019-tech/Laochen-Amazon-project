#!/usr/bin/env python3
"""Check Amazon text evidence against the local high-risk IP list."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import ensure_object, load_json, normalize_text, skill_root
from provider_utils import record_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local high-risk IP alias check.")
    parser.add_argument("--task-dir", type=Path, required=True)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    task = ensure_object(load_json(task_dir / "task.json"), "task.json")
    evidence = ensure_object(load_json(task_dir / "evidence.json"), "evidence.json")
    source = load_json(skill_root() / "assets" / "high-risk-ip.json")
    browser = evidence.get("collections", {}).get("browser", [])
    raw_haystack = " ".join([
        str(task.get("product", {}).get("title", "")), str(task.get("product", {}).get("brand", "")),
        " ".join(map(str, task.get("product", {}).get("bullets", []))),
        " ".join(map(str, browser[0].get("ocr_text", []) if browser else [])),
        " ".join(map(str, browser[0].get("visual_features", []) if browser else [])),
    ])
    hits = []
    for entry in source.get("entries", []):
        aliases = []
        for alias in entry.get("aliases", []):
            value = str(alias).strip()
            if not value:
                continue
            if re.fullmatch(r"[A-Za-z0-9 -]+", value):
                matched = bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", raw_haystack, flags=re.IGNORECASE))
            else:
                matched = normalize_text(value) in normalize_text(raw_haystack)
            if matched:
                aliases.append(alias)
        if aliases:
            hits.append({"id": entry.get("id"), "owner": entry.get("owner"), "type": entry.get("type"), "matched_aliases": aliases, "escalation_only": True})
    run = record_result(task_dir, provider="local_high_risk_ip", operation="alias_check", query=task.get("product", {}).get("actual_asin", ""),
        jurisdiction=",".join(task.get("target_jurisdictions", [])), evidence_type="blacklist",
        status="success" if hits else "no_result", normalized={"hits": hits}, mandatory=False)
    print(run["status"])


if __name__ == "__main__":
    main()

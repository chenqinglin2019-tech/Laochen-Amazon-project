#!/usr/bin/env python3
"""Export a grouped manual-review report from a Mapping 2.1/2.2 JSON file."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def build_report(mapping: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in mapping.get("manual_review", []):
        key = (str(item.get("role") or ""), str(item.get("field") or ""))
        entry = grouped.setdefault(
            key,
            {
                "role": key[0],
                "field": key[1],
                "label": item.get("label", ""),
                "value": item.get("value", ""),
                "reason": item.get("reason", ""),
                "data_definition": item.get("data_definition", {}),
                "template_restriction": item.get("template_restriction", {}),
                "source_rows": [],
            },
        )
        source_row = item.get("source_row")
        if source_row not in entry["source_rows"]:
            entry["source_rows"].append(source_row)
    fields = sorted(
        grouped.values(),
        key=lambda item: (item["role"], item["field"]),
    )
    counts_by_role: dict[str, int] = defaultdict(int)
    for item in fields:
        counts_by_role[item["role"]] += 1
        item["source_rows"] = sorted(item["source_rows"])
    task = mapping.get("task") if isinstance(mapping.get("task"), dict) else {}
    raw_summary = mapping.get("generation_summary")
    generation_summary = dict(raw_summary) if isinstance(raw_summary, dict) else {}
    generation_summary["manual_review_unique_fields"] = {
        role: counts_by_role.get(role, 0)
        for role in ("Child", "Parent")
    }
    generation_summary["manual_review_cells"] = len(mapping.get("manual_review", []))
    return {
        "schema_version": "1.0",
        "task_id": task.get("task_id"),
        "result_status": task.get("result_status"),
        "upload_eligibility": "NOT_FOR_UPLOAD",
        "manual_review_value": "信息不足，请人工核对",
        "field_count": len(fields),
        "cell_count": len(mapping.get("manual_review", [])),
        "counts_by_role": dict(sorted(counts_by_role.items())),
        "generation_summary": generation_summary,
        "fields": fields,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    report = build_report(mapping)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

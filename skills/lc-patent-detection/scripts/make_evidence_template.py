#!/usr/bin/env python3
"""Create a blank evidence JSON template for one Wisdom Bud / Feishu task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from laochen_auth_gate import require_laochen_auth


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    require_laochen_auth()
    parser = argparse.ArgumentParser(description="Create a Wisdom Bud evidence template.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--sku", default="")
    parser.add_argument("--asin", default="")
    parser.add_argument("--marketplace", default="")
    parser.add_argument("--source-image", default="")
    parser.add_argument("--record-ids", default="")
    parser.add_argument("--risk-field", default="专利")
    parser.add_argument("--pdf-field", default="专利pdf")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = {
        "product": {
            "title": args.title,
            "sku": args.sku,
            "asin": args.asin,
            "marketplace": args.marketplace,
            "source_image": args.source_image,
        },
        "feishu": {
            "app_token": "",
            "table_id": "",
            "record_ids": split_csv(args.record_ids),
            "risk_field": args.risk_field,
            "pdf_field": args.pdf_field,
        },
        "zhihuiya_evidence": [
            {
                "task_url": "",
                "search_mode": "appearance/design image search",
                "selected_jurisdiction": args.marketplace,
                "status": "pending",
                "result_count": "",
                "screenshot_paths": [],
                "candidates": [],
                "notes": "",
            }
        ],
        "conclusion": {
            "risk_value": "",
            "confidence": "",
            "core_reasons": [],
        },
        "outputs": {},
        "writeback": {
            "status": "",
            "pdf_file_token": "",
            "updated_record_ids": [],
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()

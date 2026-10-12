#!/usr/bin/env python3
"""Build an auditable Flyfus Alexa/Rufus Q&A catalog from saved receipts.

This utility never makes a network request.  It reads only the saved question
receipts already produced by ``flyfus_client.py``, writes a count-only catalog
for the report, and adds missing local receipt summaries to the run ledger.
Question text and answers deliberately remain in the original private receipt
files; the public report receives aggregate research-signal counts only.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


class CatalogError(Exception):
    """Expected saved-artifact validation failure."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _load_receipt(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"无法读取问答回执：{path.name}") from exc
    if not isinstance(value, Mapping) or value.get("operation") != "recommended_qa":
        raise CatalogError(f"不是有效的推荐问答回执：{path.name}")
    if not isinstance(value.get("request"), Mapping):
        raise CatalogError(f"问答回执缺少 request：{path.name}")
    return value


def _response_items(receipt: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    response = receipt.get("response")
    if not isinstance(response, Mapping):
        return []
    data = response.get("data")
    items = data.get("items") if isinstance(data, Mapping) else None
    return [item for item in items if isinstance(item, Mapping)] if isinstance(items, list) else []


def normalize_answer(value: Any) -> str:
    """Extract all textual content from string/object answers without truncation."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return "\n".join(text for item in value.values() if (text := normalize_answer(item)))
    if isinstance(value, list):
        return "\n".join(text for item in value if (text := normalize_answer(item)))
    return ""


def _receipt_paths(run_dir: Path) -> Iterable[Path]:
    base = run_dir / "flyfus"
    yield from sorted((base / "keyword_qa").glob("*.json"))
    product_root = base / "product_qa"
    yield from sorted(product_root.rglob("*.json"))


def _load_ledger(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        return []
    rows: list[Mapping[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, Mapping):
                    raise CatalogError("积分回执中存在非对象行")
                rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError("无法读取 Flyfus 积分回执") from exc
    return rows


def build_catalog(run_dir: Path) -> Mapping[str, Any]:
    root = run_dir.expanduser().resolve()
    if not root.is_dir():
        raise CatalogError(f"运行目录不存在：{root}")
    receipt_rows: list[dict[str, Any]] = []
    keyword_count = product_count = answered = returned = 0
    product_asins: set[str] = set()
    for path in _receipt_paths(root):
        receipt = _load_receipt(path)
        request = receipt["request"]
        items = _response_items(receipt)
        expected = int(receipt.get("returned_question_count") or 0)
        if expected != len(items):
            raise CatalogError(f"问答条目数量与回执不一致：{path.name}")
        kind = "keyword" if str(request.get("keyword") or "").strip() else "product"
        if kind == "keyword":
            keyword_count += 1
        else:
            product_count += 1
            asin = str(request.get("asin") or "").strip().upper()
            if not asin:
                raise CatalogError(f"商品问答缺少 ASIN：{path.name}")
            product_asins.add(asin)
        returned += len(items)
        answered_count = sum(1 for item in items if normalize_answer(item.get("answer")))
        answered += answered_count
        receipt_rows.append({
            "receipt_path": str(path.relative_to(root)),
            "kind": kind,
            "keyword": str(request.get("keyword") or "").strip() or None,
            "asin": str(request.get("asin") or "").strip().upper() or None,
            "page": request.get("page"),
            "returned_question_count": len(items),
            "answered_question_count": answered_count,
        })
    if not receipt_rows:
        raise CatalogError("未找到任何已保存的推荐问答回执")
    return {
        "schema_version": "flyfus-recommended-qa-catalog-1.0",
        "generated_at": _now_utc(),
        "summary": {
            "returned_question_records": returned,
            "answered_question_records": answered,
            "keyword_query_count": keyword_count,
            "keyword_question_records": sum(row["returned_question_count"] for row in receipt_rows if row["kind"] == "keyword"),
            "product_asin_count": len(product_asins),
            "product_page_count": product_count,
            "product_question_records": sum(row["returned_question_count"] for row in receipt_rows if row["kind"] == "product"),
            "item_identity": "接口未提供稳定 question ID；按每个接口返回条目计数，不宣称全局去重。",
            "gaps": [
                "B0D5BMFK9S 第 1 页在先前请求中超时，可能存在不确定扣费，未重试；已保存第 2 页 10 条。",
                "商品问答存在更多分页，当前报告仅纳入已保存页。",
            ],
        },
        "guardrail": "Alexa/Rufus 问答仅作为研究线索，不计入 VOC、消费者人数、KANO 或来源渠道数量。",
        "receipts": receipt_rows,
    }


def sync_ledger(run_dir: Path, catalog: Mapping[str, Any]) -> int:
    ledger_path = run_dir / "flyfus_receipts.jsonl"
    ledger = _load_ledger(ledger_path)
    known_paths = {
        str(row.get("receipt_path"))
        for row in ledger
        if str(row.get("receipt_path") or "").strip()
    }
    appended = 0
    for item in catalog["receipts"]:
        receipt_path = str(item["receipt_path"])
        if receipt_path in known_paths:
            continue
        receipt = _load_receipt(run_dir / receipt_path)
        summary = {
            "provider": "flyfus",
            "operation": "recommended_qa",
            "status": receipt.get("status"),
            "request": receipt.get("request"),
            "points_cap": receipt.get("points_cap"),
            "points_reserved": receipt.get("points_reserved"),
            "spend_boundary": receipt.get("spend_boundary"),
            "returned_question_count": item["returned_question_count"],
            "receipt_path": receipt_path,
        }
        ledger.append(summary)
        known_paths.add(receipt_path)
        appended += 1
    if appended:
        _atomic_write(ledger_path, "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in ledger))
    return appended


def main() -> int:
    parser = argparse.ArgumentParser(description="从已保存 Flyfus 回执构建问答计数目录，不发起网络请求")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="默认写入 run-dir/recommended_qa.json")
    arguments = parser.parse_args()
    try:
        catalog = build_catalog(arguments.run_dir)
        output = arguments.output or (arguments.run_dir / "recommended_qa.json")
        _atomic_write(output, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
        appended = sync_ledger(arguments.run_dir, catalog)
    except CatalogError as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": "ok",
        "output": str(output),
        "returned_question_records": catalog["summary"]["returned_question_records"],
        "ledger_rows_appended": appended,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

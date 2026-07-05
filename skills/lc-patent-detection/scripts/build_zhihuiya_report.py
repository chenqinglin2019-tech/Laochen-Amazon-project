#!/usr/bin/env python3
"""Build reports from Wisdom Bud / PatSnap evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from laochen_auth_gate import require_laochen_auth


RISK_VALUES = {"高", "中", "低"}


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(text(item) for item in value if text(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Evidence JSON must be an object.")
    payload.setdefault("zhihuiya_evidence", [])
    payload.setdefault("conclusion", {})
    payload.setdefault("outputs", {})
    return payload


def candidate_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    rows: list[dict[str, str]] = []
    for branch in payload.get("zhihuiya_evidence", []):
        if not isinstance(branch, dict):
            continue
        branch_status = text(branch.get("status"))
        jurisdiction = text(branch.get("selected_jurisdiction"))
        for candidate in branch.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            official = candidate.get("official_verification") if isinstance(candidate.get("official_verification"), dict) else {}
            rows.append(
                {
                    "product_title": text(product.get("title")),
                    "sku": text(product.get("sku")),
                    "marketplace": text(product.get("marketplace")),
                    "selected_jurisdiction": jurisdiction,
                    "branch_status": branch_status,
                    "record_number": text(candidate.get("record_number")),
                    "title_or_article": text(candidate.get("title_or_article")),
                    "country": text(candidate.get("country")),
                    "rank": text(candidate.get("rank")),
                    "similarity_score": text(candidate.get("similarity_score")),
                    "similarity_note": text(candidate.get("similarity_note")),
                    "screenshot_path": text(candidate.get("screenshot_path")),
                    "official_status": text(official.get("status") or "not_checked"),
                    "official_source": text(official.get("source")),
                    "official_url": text(official.get("url")),
                    "official_notes": text(official.get("notes")),
                }
            )
    return rows


def parse_score(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def infer_risk(payload: dict[str, Any], rows: list[dict[str, str]]) -> tuple[str, list[str], str]:
    conclusion = payload.get("conclusion") if isinstance(payload.get("conclusion"), dict) else {}
    explicit = text(conclusion.get("risk_value"))
    if explicit in RISK_VALUES:
        reasons = [text(item) for item in conclusion.get("core_reasons", []) if text(item)]
        return explicit, reasons or ["使用证据 JSON 中已有风险值。"], text(conclusion.get("confidence") or "中")

    if not rows:
        return "低", ["智慧芽 / PatSnap 未记录有效候选。"], "中"

    best_score = None
    for row in rows:
        score = parse_score(row.get("similarity_score"))
        if score is not None:
            best_score = score if best_score is None else max(best_score, score)

    if best_score is not None and best_score >= 80:
        return "高", [f"智慧芽 / PatSnap 最高相似度 {best_score:g}，达到高风险阈值。"], "中"
    if best_score is not None and best_score < 60:
        return "低", [f"智慧芽 / PatSnap 候选最高相似度 {best_score:g}，低于中风险阈值。"], "中"

    skipped = [row for row in rows if row.get("official_status") in {"skipped_not_found", "access_limited", "not_checked", ""}]
    if skipped:
        return "中", ["存在智慧芽 / PatSnap 候选，官方核验未确认或已跳过，按中风险写回。"], "中"
    return "中", ["存在智慧芽 / PatSnap 候选，需要业务复核。"], "中"


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "product_title",
        "sku",
        "marketplace",
        "selected_jurisdiction",
        "record_number",
        "title_or_article",
        "country",
        "rank",
        "similarity_score",
        "similarity_note",
        "screenshot_path",
        "official_status",
        "official_source",
        "official_url",
        "official_notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        output.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in row) + " |")
    return output


def write_md(payload: dict[str, Any], rows: list[dict[str, str]], risk: str, reasons: list[str], confidence: str, path: Path) -> None:
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    lines = [
        "# 智慧芽专利查询报告",
        "",
        f"**风险写回值:** {risk}",
        f"**置信度:** {confidence}",
        "",
        "## 核心理由",
    ]
    for reason in reasons[:3]:
        lines.append(f"- {reason}")
    lines.extend(
        [
            "",
            "## 产品信息",
            *md_table(
                ["字段", "值"],
                [
                    ["标题", text(product.get("title"))],
                    ["SKU", text(product.get("sku"))],
                    ["ASIN", text(product.get("asin"))],
                    ["站点", text(product.get("marketplace"))],
                    ["产品图", text(product.get("source_image"))],
                ],
            ),
            "",
            "## 智慧芽 / PatSnap 候选",
        ]
    )
    if rows:
        lines.extend(
            md_table(
                ["辖区", "编号", "标题/品类", "相似度", "官方状态", "截图"],
                [
                    [
                        row["selected_jurisdiction"],
                        row["record_number"],
                        row["title_or_article"],
                        row["similarity_score"],
                        row["official_status"],
                        row["screenshot_path"],
                    ]
                    for row in rows
                ],
            )
        )
    else:
        lines.append("未记录有效候选。")
    lines.extend(
        [
            "",
            "## 规则",
            "官方来源查不到或无法访问时，记录为 `skipped_not_found` / `access_limited`，不阻塞飞书写回。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pdf_from_md(md_path: Path, pdf_path: Path) -> None:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except Exception as exc:
        raise RuntimeError("PDF output requires reportlab. Install requirements.txt or omit --output-pdf.") from exc

    text_lines = md_path.read_text(encoding="utf-8").splitlines()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4, rightMargin=32, leftMargin=32, topMargin=32, bottomMargin=32)
    styles = getSampleStyleSheet()
    story = []
    for line in text_lines:
        if line.startswith("# "):
            story.append(Paragraph(line[2:], styles["Title"]))
        elif line.startswith("## "):
            story.append(Spacer(1, 8))
            story.append(Paragraph(line[3:], styles["Heading2"]))
        elif line.startswith("- "):
            story.append(Paragraph("• " + line[2:], styles["BodyText"]))
        elif line.strip():
            story.append(Paragraph(line.replace("|", " | "), styles["BodyText"]))
        else:
            story.append(Spacer(1, 6))
    doc.build(story)


def main() -> None:
    require_laochen_auth()
    parser = argparse.ArgumentParser(description="Build reports from Wisdom Bud / PatSnap evidence.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-pdf", type=Path)
    args = parser.parse_args()

    payload = load_json(args.input)
    rows = candidate_rows(payload)
    risk, reasons, confidence = infer_risk(payload, rows)
    payload["conclusion"] = {
        "risk_value": risk,
        "confidence": confidence,
        "core_reasons": reasons[:3],
    }
    payload.setdefault("outputs", {})
    payload["outputs"].update(
        {
            "report_md": str(args.output_md),
            "findings_csv": str(args.output_csv),
            "report_pdf": str(args.output_pdf) if args.output_pdf else "",
        }
    )

    write_md(payload, rows, risk, reasons, confidence, args.output_md)
    write_csv(rows, args.output_csv)
    if args.output_pdf:
        write_pdf_from_md(args.output_md, args.output_pdf)

    output_json = args.output_json or args.input
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

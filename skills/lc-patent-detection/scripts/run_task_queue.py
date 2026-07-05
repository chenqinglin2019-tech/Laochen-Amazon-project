#!/usr/bin/env python3
"""Run Wisdom Bud report generation and optional Feishu writeback sequentially."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from laochen_auth_gate import require_laochen_auth

def slug(value: str) -> str:
    output = []
    for char in value.lower():
        if char.isalnum():
            output.append(char)
        elif output and output[-1] != "-":
            output.append("-")
    return "".join(output).strip("-")[:64] or "task"


def main() -> None:
    require_laochen_auth()
    parser = argparse.ArgumentParser(description="Run Wisdom Bud / Feishu patent tasks sequentially.")
    parser.add_argument("queue_json", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--writeback", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tasks = json.loads(args.queue_json.read_text(encoding="utf-8-sig"))
    if not isinstance(tasks, list):
        raise SystemExit("queue_json must be a list")

    script_dir = Path(__file__).resolve().parent
    build_script = script_dir / "build_zhihuiya_report.py"
    write_script = script_dir / "feishu_writeback.py"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = []

    for index, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            raise SystemExit(f"Task {index} must be an object")
        evidence_path = Path(str(task.get("evidence_json", "")))
        if not evidence_path.exists():
            raise SystemExit(f"Task {index} evidence_json not found: {evidence_path}")
        name = evidence_path.stem
        out_dir = args.output_dir / f"{index:03d}-{slug(name)}"
        out_dir.mkdir(parents=True, exist_ok=True)
        local_evidence = out_dir / "evidence.json"
        shutil.copy2(evidence_path, local_evidence)
        report_md = out_dir / "report.md"
        findings_csv = out_dir / "findings.csv"
        report_pdf = out_dir / "report.pdf"
        subprocess.check_call(
            [
                sys.executable,
                str(build_script),
                "--input",
                str(local_evidence),
                "--output-md",
                str(report_md),
                "--output-csv",
                str(findings_csv),
                "--output-pdf",
                str(report_pdf),
            ]
        )
        writeback_status = "skipped"
        if args.writeback:
            command = [
                sys.executable,
                str(write_script),
                "--evidence-json",
                str(local_evidence),
                "--report-pdf",
                str(report_pdf),
                "--response-json",
                str(out_dir / "writeback-response.json"),
            ]
            for record_id in task.get("record_ids", []):
                command.extend(["--record-id", str(record_id)])
            if task.get("risk_field"):
                command.extend(["--risk-field", str(task["risk_field"])])
            if task.get("pdf_field"):
                command.extend(["--pdf-field", str(task["pdf_field"])])
            if args.dry_run:
                command.append("--dry-run")
            subprocess.check_call(command)
            writeback_status = "dry_run" if args.dry_run else "completed"
        summary.append({"index": index, "evidence_json": str(local_evidence), "writeback": writeback_status})

    (args.output_dir / "queue-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

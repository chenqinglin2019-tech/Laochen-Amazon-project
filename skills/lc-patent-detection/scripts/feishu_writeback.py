#!/usr/bin/env python3
"""Upload a report PDF and write Wisdom Bud patent results back to Feishu/Lark Bitable."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import request

from laochen_auth_gate import require_laochen_auth

API_BASE = "https://open.feishu.cn/open-apis"
ALLOWED_RISK = {"高", "中", "低"}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Evidence JSON must be an object.")
    return payload


def post_json(url: str, token: str | None, payload: dict[str, Any], method: str = "POST") -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, data=body, headers=headers, method=method)
    with request.urlopen(req, timeout=60) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data) if data else {}


def tenant_token(args: argparse.Namespace) -> str:
    direct = args.tenant_access_token or os.environ.get("FEISHU_TENANT_ACCESS_TOKEN", "")
    if direct:
        return direct
    app_id = args.app_id or os.environ.get("FEISHU_APP_ID", "")
    app_secret = args.app_secret or os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise ValueError("Provide FEISHU_TENANT_ACCESS_TOKEN or FEISHU_APP_ID + FEISHU_APP_SECRET.")
    data = post_json(
        f"{API_BASE}/auth/v3/tenant_access_token/internal",
        None,
        {"app_id": app_id, "app_secret": app_secret},
    )
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"Failed to get tenant token: {data}")
    return token


def multipart_upload(url: str, token: str, fields: dict[str, str], file_field: str, file_path: Path) -> dict[str, Any]:
    boundary = "----codex" + uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
    )
    parts.append(file_path.read_bytes())
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=120) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data) if data else {}


def upload_pdf(token: str, app_token: str, report_pdf: Path) -> str:
    if not report_pdf.exists() or report_pdf.stat().st_size <= 0:
        raise ValueError(f"Report PDF does not exist or is empty: {report_pdf}")
    data = multipart_upload(
        f"{API_BASE}/drive/v1/medias/upload_all",
        token,
        {
            "file_name": report_pdf.name,
            "parent_type": "bitable_file",
            "parent_node": app_token,
            "size": str(report_pdf.stat().st_size),
        },
        "file",
        report_pdf,
    )
    file_token = data.get("data", {}).get("file_token") or data.get("file_token")
    if not file_token:
        raise RuntimeError(f"PDF upload did not return file_token: {data}")
    return file_token


def update_record(token: str, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    url = f"{API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    return post_json(url, token, {"fields": fields}, method="PUT")


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    require_laochen_auth()
    parser = argparse.ArgumentParser(description="Write Wisdom Bud patent result back to Feishu/Lark Bitable.")
    parser.add_argument("--evidence-json", type=Path, required=True)
    parser.add_argument("--report-pdf", type=Path)
    parser.add_argument("--record-id", action="append", default=[])
    parser.add_argument("--record-ids", default="")
    parser.add_argument("--risk-value", default="")
    parser.add_argument("--risk-field", default="")
    parser.add_argument("--pdf-field", default="")
    parser.add_argument("--app-token", default="")
    parser.add_argument("--table-id", default="")
    parser.add_argument("--tenant-access-token", default="")
    parser.add_argument("--app-id", default="")
    parser.add_argument("--app-secret", default="")
    parser.add_argument("--response-json", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    evidence = read_json(args.evidence_json)
    feishu = evidence.get("feishu") if isinstance(evidence.get("feishu"), dict) else {}
    conclusion = evidence.get("conclusion") if isinstance(evidence.get("conclusion"), dict) else {}

    app_token = args.app_token or os.environ.get("FEISHU_APP_TOKEN", "") or str(feishu.get("app_token", ""))
    table_id = args.table_id or os.environ.get("FEISHU_TABLE_ID", "") or str(feishu.get("table_id", ""))
    risk_field = args.risk_field or os.environ.get("FEISHU_RISK_FIELD", "") or str(feishu.get("risk_field", "专利"))
    pdf_field = args.pdf_field or os.environ.get("FEISHU_PDF_FIELD", "") or str(feishu.get("pdf_field", "专利pdf"))
    record_ids = [*args.record_id, *split_csv(args.record_ids), *[str(item) for item in feishu.get("record_ids", []) if str(item)]]
    record_ids = list(dict.fromkeys(record_ids))
    risk_value = args.risk_value or str(conclusion.get("risk_value", ""))

    if risk_value not in ALLOWED_RISK:
        raise ValueError(f"Risk value must be one of {sorted(ALLOWED_RISK)}; got {risk_value!r}.")
    if not app_token:
        raise ValueError("Missing app_token. Use --app-token or FEISHU_APP_TOKEN.")
    if not table_id:
        raise ValueError("Missing table_id. Use --table-id or FEISHU_TABLE_ID.")
    if not record_ids:
        raise ValueError("Missing record_id. Use --record-id, --record-ids, or evidence.feishu.record_ids.")

    pdf_token = ""
    fields: dict[str, Any] = {risk_field: risk_value}

    if args.dry_run:
        result = {"dry_run": True, "app_token": "***", "table_id": "***", "record_ids": record_ids, "fields": fields}
    else:
        token = tenant_token(args)
        if args.report_pdf and pdf_field:
            pdf_token = upload_pdf(token, app_token, args.report_pdf)
            fields[pdf_field] = [{"file_token": pdf_token, "name": args.report_pdf.name}]
        updates = []
        for record_id in record_ids:
            updates.append({"record_id": record_id, "response": update_record(token, app_token, table_id, record_id, fields)})
            time.sleep(0.1)
        result = {"dry_run": False, "pdf_file_token": pdf_token, "updated_record_ids": record_ids, "updates": updates}

    evidence["writeback"] = {
        "status": "dry_run" if args.dry_run else "completed",
        "pdf_file_token": pdf_token,
        "updated_record_ids": record_ids,
    }
    args.evidence_json.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.response_json:
        args.response_json.parent.mkdir(parents=True, exist_ok=True)
        args.response_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)

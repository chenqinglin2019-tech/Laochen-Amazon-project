#!/usr/bin/env python3
"""Private backend for the Codex Harness 飞鱼神图 custom app."""

from __future__ import annotations

import argparse
import cgi
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = APP_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
GENERATED_DIR = DATA_DIR / "generated"
DB_PATH = DATA_DIR / "app.sqlite3"
TOKEN_PATH = DATA_DIR / "feiyushentu.toml"
CLI_PATH = APP_ROOT / "backend" / "vendor" / "feiyushentu_amazon.py"
HARNESS_ORIGIN = os.environ.get("HARNESS_ORIGIN", "http://127.0.0.1:38080").rstrip("/")

MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_FILES = 6
MAX_GENERATION_COUNT = 15
DB_LOCK = threading.RLock()
ACTIVE_STATUSES = ("queued", "uploading", "generating", "archive_retrying")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def to_int(value, fallback: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_directories() -> None:
    for directory in (DATA_DIR, UPLOAD_DIR, GENERATED_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def init_db() -> None:
    ensure_directories()
    with DB_LOCK, connect_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                total INTEGER NOT NULL,
                ai_model TEXT NOT NULL,
                fixed_setting_json TEXT NOT NULL,
                setting_json TEXT NOT NULL,
                uploads_json TEXT NOT NULL,
                task_ids_json TEXT NOT NULL DEFAULT '[]',
                result_json TEXT,
                error TEXT,
                retry_of TEXT,
                FOREIGN KEY (retry_of) REFERENCES jobs(id)
            )
            """
        )
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        connection.execute(
            f"UPDATE jobs SET status = 'generation_failed', error = ?, updated_at = ? "
            f"WHERE status IN ({placeholders})",
            ("服务曾重启，请使用重试功能重新生成。", utc_now(), *ACTIVE_STATUSES),
        )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def fetch_job(job_id: str) -> dict:
    with DB_LOCK, connect_db() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise AppError(404, "job_not_found", "未找到该生成任务。")
    return row_to_dict(row) or {}


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def list_jobs(page: int = 1, size: int = 20, start: str = "", end: str = "") -> tuple[list[dict], int, int, int]:
    """Newest first, filtered by created_at date, paginated on the server."""
    size = max(1, min(size, 50))
    clauses: list[str] = []
    params: list = []
    if DATE_RE.match(start or ""):
        clauses.append("substr(created_at, 1, 10) >= ?")
        params.append(start)
    if DATE_RE.match(end or ""):
        clauses.append("substr(created_at, 1, 10) <= ?")
        params.append(end)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with DB_LOCK, connect_db() as connection:
        total = int(
            connection.execute(f"SELECT COUNT(*) FROM jobs{where}", params).fetchone()[0]
        )
        pages = max(1, (total + size - 1) // size)
        page = max(1, min(page, pages))
        rows = connection.execute(
            f"SELECT * FROM jobs{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, size, (page - 1) * size),
        ).fetchall()
    return [row_to_dict(row) or {} for row in rows], total, page, size


def update_job(job_id: str, **fields) -> None:
    allowed = {"status", "task_ids_json", "result_json", "error"}
    invalid = set(fields) - allowed
    if invalid:
        raise ValueError(f"Unsupported job fields: {sorted(invalid)}")
    fields["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id]
    with DB_LOCK, connect_db() as connection:
        connection.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)


def insert_job(payload: dict, uploads: list[dict], retry_of: str | None = None) -> dict:
    job_id = "job-" + uuid.uuid4().hex
    timestamp = utc_now()
    with DB_LOCK, connect_db() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, created_at, updated_at, status, title, description, total,
                ai_model, fixed_setting_json, setting_json, uploads_json,
                task_ids_json, retry_of
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, '[]', ?)
            """,
            (
                job_id,
                timestamp,
                timestamp,
                payload["title"],
                payload["description"],
                payload["total"],
                payload["ai_model"],
                json.dumps(payload["fixed_setting"], ensure_ascii=False),
                json.dumps(payload["setting"], ensure_ascii=False),
                json.dumps(uploads, ensure_ascii=False),
                retry_of,
            ),
        )
    return fetch_job(job_id)


def parse_json_object(value: str, label: str) -> dict:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AppError(400, "invalid_input", f"{label} 格式不正确。") from exc
    if not isinstance(parsed, dict):
        raise AppError(400, "invalid_input", f"{label} 必须是对象。")
    return parsed


def validate_payload(fields: dict[str, str]) -> dict:
    title = str(fields.get("title") or "").strip()
    description = str(fields.get("description") or "").strip()
    ai_model = str(fields.get("ai_model") or "").strip()
    if not title or len(title) > 200:
        raise AppError(400, "invalid_title", "请输入不超过 200 个字符的商品标题。")
    if not description or len(description) > 3000:
        raise AppError(400, "invalid_description", "请输入不超过 3000 个字符的商品描述。")
    if not ai_model or len(ai_model) > 200:
        raise AppError(400, "invalid_model", "请选择模型。")
    try:
        total = int(str(fields.get("total") or ""))
    except ValueError as exc:
        raise AppError(400, "invalid_total", "生成数量必须是整数。") from exc
    if total < 1 or total > MAX_GENERATION_COUNT:
        raise AppError(400, "invalid_total", f"每次可生成 1–{MAX_GENERATION_COUNT} 张图片。")
    fixed_setting = parse_json_object(fields.get("fixed_setting", "{}"), "固定设置")
    setting = parse_json_object(fields.get("setting", "{}"), "模型设置")
    setting.pop("images", None)
    return {
        "title": title,
        "description": description,
        "total": total,
        "ai_model": ai_model,
        "fixed_setting": fixed_setting,
        "setting": setting,
    }


def image_kind(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def safe_name(value: str) -> str:
    basename = Path(value or "image").name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(basename).stem).strip("._")
    return (stem or "image")[:80]


def parse_image_urls(raw: str) -> list[dict]:
    """Accept a JSON array of public image URLs as an alternative to file uploads."""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AppError(400, "invalid_image_urls", "商品图链接格式不正确。") from exc
    if not isinstance(values, list):
        raise AppError(400, "invalid_image_urls", "商品图链接格式不正确。")
    records: list[dict] = []
    for value in values:
        url = str(value or "").strip()
        if not url:
            continue
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or len(url) > 2048:
            raise AppError(400, "invalid_image_urls", "请使用 http 或 https 开头的公网图片链接。")
        records.append({"url": url, "original_name": Path(parsed.path).name[:180] or "image"})
    return records


def save_uploads(items: list[cgi.FieldStorage], urls: list[dict] | None = None) -> list[dict]:
    urls = urls or []
    if not items and not urls:
        raise AppError(400, "missing_images", "上传产品图片")
    if len(items) + len(urls) > MAX_FILES:
        raise AppError(400, "too_many_images", f"最多上传 {MAX_FILES} 张参考图片。")
    saved: list[dict] = []
    try:
        for item in items:
            if not item.filename or item.file is None:
                continue
            content = item.file.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise AppError(413, "file_too_large", "单张图片不能超过 12 MB。")
            kind = image_kind(content)
            if kind is None:
                raise AppError(400, "invalid_image", "仅支持 JPG、PNG 或 WebP 图片。")
            extension, mime_type = kind
            stored_name = f"{uuid.uuid4().hex}_{safe_name(item.filename)}{extension}"
            target = UPLOAD_DIR / stored_name
            temporary = UPLOAD_DIR / f".{stored_name}.part"
            with temporary.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o640)
            os.replace(temporary, target)
            saved.append(
                {
                    "path": str(target),
                    "original_name": Path(item.filename).name[:180],
                    "mime_type": mime_type,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    except Exception:
        for record in saved:
            try:
                Path(record["path"]).unlink()
            except FileNotFoundError:
                pass
        raise
    saved.extend(urls)
    if not saved:
        raise AppError(400, "missing_images", "上传产品图片")
    return saved


def run_cli(arguments: list[str], *, stdin_text: str | None = None, timeout: int = 120) -> dict:
    command = [
        sys.executable,
        str(CLI_PATH),
        "--config-path",
        str(TOKEN_PATH),
        *arguments,
    ]
    try:
        completed = subprocess.run(
            command,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError(504, "upstream_timeout", "飞鱼神图请求超时，请稍后重试。") from exc
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AppError(502, "invalid_upstream_response", "飞鱼神图返回了无法识别的响应。") from exc
    if not isinstance(result, dict):
        raise AppError(502, "invalid_upstream_response", "飞鱼神图返回了无法识别的响应。")
    return result


def user_error(result: dict, fallback: str) -> str:
    code = result.get("code")
    if code is None and isinstance(result.get("response"), dict):
        code = result["response"].get("code")
    if code in (10002, 10003):
        return "请输入飞鱼神图的token" if code == 10002 else "飞鱼神图 Token 无效，请重新配置。"
    if code == 11008:
        return "飞鱼神图账号已被禁用，请检查账号或更换 Token。"
    message = str(result.get("message") or "").strip()
    return message[:500] if message else fallback


def job_arguments(row: dict) -> tuple[list[str], list[dict]]:
    uploads = json.loads(row["uploads_json"])
    arguments = [
        "--total", str(row["total"]),
        "--title", row["title"],
        "--desc", row["description"],
        "--fixed-setting", row["fixed_setting_json"],
        "--ai-model", row["ai_model"],
        "--setting", row["setting_json"],
    ]
    for upload in uploads:
        if upload.get("url"):
            arguments.extend(["--image", str(upload["url"])])
            continue
        path = Path(upload["path"])
        if not path.is_file():
            raise AppError(409, "upload_missing", "原参考图片已不存在，无法重试。")
        arguments.extend(["--image", str(path)])
    return arguments, uploads


def derive_status(result: dict) -> tuple[str, str | None]:
    state = result.get("state")
    archive = result.get("archive") if isinstance(result.get("archive"), dict) else {}
    archive_status = archive.get("status")
    if state == "timeout":
        return "timeout", "生成超时，可使用原参数重试。"
    if state == "failed":
        return "generation_failed", user_error(result, "图片生成失败，请重试。")
    if state == "success":
        if archive_status == "partial":
            return "archive_partial", "图片已生成，但部分文件归档失败。"
        if archive_status == "failed":
            return "archive_failed", "图片已生成，但文件归档失败。"
        return "success", None
    return "generation_failed", user_error(result, "图片生成失败，请重试。")


def process_job(job_id: str) -> None:
    try:
        row = fetch_job(job_id)
        arguments, _uploads = job_arguments(row)
        update_job(job_id, status="uploading", error=None)
        submitted = run_cli(["submit", *arguments], timeout=300)
        if not submitted.get("ok"):
            update_job(
                job_id,
                status="generation_failed",
                result_json=json.dumps(submitted, ensure_ascii=False),
                error=user_error(submitted, "生成任务创建失败，请重试。"),
            )
            return
        task_ids = [str(item) for item in submitted.get("task_ids") or [] if item]
        if not task_ids:
            raise AppError(502, "missing_task_ids", "生成任务没有返回任务编号。")
        update_job(
            job_id,
            status="generating",
            task_ids_json=json.dumps(task_ids, ensure_ascii=False),
            error=None,
        )
        output_dir = GENERATED_DIR / job_id
        status_args = ["status"]
        for task_id in task_ids:
            status_args.extend(["--task-id", task_id])
        status_args.extend(
            ["--poll-interval", "5", "--max-polls", "120", "--output-dir", str(output_dir)]
        )
        result = run_cli(status_args, timeout=660)
        result["submitted"] = {
            "task_ids": task_ids,
            "payload": submitted.get("payload"),
        }
        status, error = derive_status(result)
        update_job(
            job_id,
            status=status,
            result_json=json.dumps(result, ensure_ascii=False),
            error=error,
        )
    except Exception as exc:
        message = exc.message if isinstance(exc, AppError) else "生成服务发生错误，请重试。"
        update_job(job_id, status="generation_failed", error=message[:500])


def retry_archive(job_id: str) -> None:
    try:
        row = fetch_job(job_id)
        result = json.loads(row.get("result_json") or "{}")
        archive = result.get("archive") if isinstance(result.get("archive"), dict) else {}
        prior_records = archive.get("images") if isinstance(archive.get("images"), list) else []
        successful = [item for item in prior_records if item.get("archive_status") == "success"]
        failed_urls = [
            str(item.get("source_url"))
            for item in prior_records
            if item.get("archive_status") != "success" and item.get("source_url")
        ]
        if not failed_urls:
            failed_urls = [
                str(item.get("source_url"))
                for item in result.get("generated_images") or []
                if item.get("source_url")
            ]
        if not failed_urls:
            raise AppError(409, "nothing_to_archive", "没有可重新归档的图片地址。")
        retry_dir = GENERATED_DIR / job_id / ("retry-" + uuid.uuid4().hex[:8])
        arguments = ["download", "--output-dir", str(retry_dir)]
        for source_url in failed_urls:
            arguments.extend(["--url", source_url])
        retried = run_cli(arguments, timeout=300)
        new_archive = retried.get("archive") if isinstance(retried.get("archive"), dict) else {}
        new_records = new_archive.get("images") if isinstance(new_archive.get("images"), list) else []
        combined = successful + new_records
        failures = sum(1 for item in combined if item.get("archive_status") != "success")
        successes = len(combined) - failures
        if failures == 0 and combined:
            archive_status = "success"
            status = "success"
            error = None
        elif successes:
            archive_status = "partial"
            status = "archive_partial"
            error = "图片已生成，但部分文件归档仍然失败。"
        else:
            archive_status = "failed"
            status = "archive_failed"
            error = "图片已生成，但文件归档仍然失败。"
        result["archive"] = {
            "requested": True,
            "status": archive_status,
            "success": successes,
            "failed": failures,
            "images": combined,
        }
        update_job(
            job_id,
            status=status,
            result_json=json.dumps(result, ensure_ascii=False),
            error=error,
        )
    except Exception as exc:
        message = exc.message if isinstance(exc, AppError) else "重新归档失败，请稍后重试。"
        row = fetch_job(job_id)
        previous = json.loads(row.get("result_json") or "{}")
        archive = previous.get("archive") if isinstance(previous.get("archive"), dict) else {}
        status = "archive_partial" if archive.get("status") == "partial" else "archive_failed"
        update_job(job_id, status=status, error=message[:500])


def start_worker(target, *arguments) -> None:
    thread = threading.Thread(target=target, args=arguments, daemon=True)
    thread.start()


def public_data_url(local_path: str | None, root: Path, segment: str) -> str | None:
    if not local_path:
        return None
    try:
        relative = Path(local_path).resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    encoded = "/".join(urllib.parse.quote(part, safe="") for part in relative.parts)
    return f"/custom-api/amazon-image-generator/files/{segment}/{encoded}"


def public_file_url(local_path: str | None) -> str | None:
    return public_data_url(local_path, GENERATED_DIR, "generated")


def source_image_urls(uploads: list[dict]) -> list[str]:
    """Product images the user supplied, as URLs the page can render."""
    urls: list[str] = []
    for upload in uploads or []:
        if upload.get("url"):
            urls.append(str(upload["url"]))
            continue
        served = public_data_url(upload.get("path"), UPLOAD_DIR, "uploads")
        if served:
            urls.append(served)
    return urls


def public_job(row: dict) -> dict:
    fixed_setting = json.loads(row["fixed_setting_json"])
    setting = json.loads(row["setting_json"])
    task_ids = json.loads(row["task_ids_json"] or "[]")
    raw_result = json.loads(row["result_json"] or "{}")
    archive = raw_result.get("archive") if isinstance(raw_result.get("archive"), dict) else {}
    records = archive.get("images") if isinstance(archive.get("images"), list) else []
    images = []
    for item in records:
        images.append(
            {
                "source_url": item.get("source_url"),
                "download_url": public_file_url(item.get("local_path")),
                "filename": item.get("filename"),
                "size_bytes": item.get("size_bytes"),
                "mime_type": item.get("mime_type"),
                "sha256": item.get("sha256"),
                "archive_status": item.get("archive_status"),
                "error": item.get("error"),
            }
        )
    if not images:
        for item in raw_result.get("generated_images") or []:
            images.append(
                {
                    "source_url": item.get("source_url"),
                    "download_url": None,
                    "filename": None,
                    "size_bytes": None,
                    "mime_type": None,
                    "sha256": None,
                    "archive_status": "not_started",
                    "error": None,
                }
            )
    return {
        "id": row["id"],
        "source_images": source_image_urls(json.loads(row["uploads_json"] or "[]")),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": row["status"],
        "title": row["title"],
        "description": row["description"],
        "total": row["total"],
        "ai_model": row["ai_model"],
        "fixed_setting": fixed_setting,
        "setting": setting,
        "task_ids": task_ids,
        "retry_of": row.get("retry_of"),
        "error": row.get("error"),
        "archive_status": archive.get("status") or "not_started",
        "images": images,
    }


def harness_session(headers) -> dict:
    cookie = str(headers.get("Cookie") or "")
    if not cookie or len(cookie) > 8192:
        raise AppError(401, "unauthorized", "请先登录 Codex Harness，再刷新本页。")
    request = urllib.request.Request(
        HARNESS_ORIGIN + "/api/v1/session",
        method="GET",
        headers={"Accept": "application/json", "Cookie": cookie},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise AppError(401, "unauthorized", "登录状态已失效，请重新登录。") from exc
    session = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(session, dict):
        raise AppError(401, "unauthorized", "登录状态已失效，请重新登录。")
    if session.get("role") != "root":
        raise AppError(403, "root_required", "飞鱼神图栏目当前仅对管理员开放。")
    return session


def authorize(headers, *, mutation: bool = False) -> dict:
    session = harness_session(headers)
    if mutation:
        supplied = str(headers.get("x-csrf-token") or "")
        expected = str(session.get("csrfToken") or "")
        if not supplied or not expected or not hmac.compare_digest(supplied, expected):
            raise AppError(403, "csrf_invalid", "安全校验已过期，请刷新页面后重试。")
    return session


def require_transport_acknowledgement(headers) -> None:
    origin = str(headers.get("Origin") or "")
    parsed = urllib.parse.urlsplit(origin)
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in local_hosts):
        return
    acknowledgement = str(headers.get("x-insecure-token-ack") or "")
    if parsed.scheme == "http" and hmac.compare_digest(acknowledgement, "confirmed"):
        return
    raise AppError(
        428,
        "transport_ack_required",
        "HTTP 会明文传输 Token，请确认风险后再保存。",
    )


class AppHandler(BaseHTTPRequestHandler):
    server_version = "FeiyuModule/1.0"

    def log_message(self, fmt: str, *args) -> None:
        message = fmt % args
        sys.stderr.write(f"{utc_now()} {self.client_address[0]} {message}\n")

    def send_json(self, status: int, data=None, error: AppError | None = None) -> None:
        request_id = uuid.uuid4().hex
        if error is None:
            payload = {"data": data, "requestId": request_id}
        else:
            payload = {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "requestId": request_id,
                }
            }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def handle_error(self, exc: Exception) -> None:
        if isinstance(exc, AppError):
            self.send_json(exc.status, error=exc)
            return
        self.send_json(500, error=AppError(500, "internal_error", "服务发生错误，请稍后重试。"))

    def parsed_path(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlsplit(self.path)
        return parsed.path.rstrip("/") or "/", urllib.parse.parse_qs(parsed.query)

    def do_GET(self) -> None:
        try:
            path, query = self.parsed_path()
            if path == "/health":
                self.send_json(200, {"ok": True})
                return
            authorize(self.headers)
            if path == "/api/bootstrap":
                token = run_cli(["check-token"], timeout=10)
                self.send_json(200, {"token_configured": bool(token.get("token_configured"))})
                return
            if path == "/api/config":
                token = run_cli(["check-token"], timeout=10)
                if not token.get("token_configured"):
                    raise AppError(409, "token_required", "请输入飞鱼神图的token")
                result = run_cli(["fetch-config"], timeout=90)
                if not result.get("ok"):
                    raise AppError(502, "config_failed", user_error(result, "无法获取模型配置。"))
                self.send_json(200, {"summary": result.get("summary") or {}})
                return
            if path == "/api/jobs":
                page = to_int((query.get("page") or ["1"])[0], 1)
                size = to_int((query.get("size") or (query.get("limit") or ["20"]))[0], 20)
                start = (query.get("start") or [""])[0]
                end = (query.get("end") or [""])[0]
                rows, total, page, size = list_jobs(page, size, start, end)
                self.send_json(
                    200,
                    {
                        "jobs": [public_job(row) for row in rows],
                        "total": total,
                        "page": page,
                        "size": size,
                    },
                )
                return
            match = re.fullmatch(r"/api/jobs/(job-[a-f0-9]{32})", path)
            if match:
                self.send_json(200, {"job": public_job(fetch_job(match.group(1)))})
                return
            file_match = re.fullmatch(r"/files/generated/(.+)", path)
            if file_match:
                self.send_data_file(GENERATED_DIR, file_match.group(1), query)
                return
            upload_match = re.fullmatch(r"/files/uploads/(.+)", path)
            if upload_match:
                self.send_data_file(UPLOAD_DIR, upload_match.group(1), query)
                return
            raise AppError(404, "not_found", "接口不存在。")
        except Exception as exc:
            self.handle_error(exc)

    def do_POST(self) -> None:
        try:
            path, _query = self.parsed_path()
            authorize(self.headers, mutation=True)
            if path == "/api/token":
                require_transport_acknowledgement(self.headers)
                payload = self.read_json()
                token = str(payload.get("token") or "").strip()
                if not token or len(token) > 4096 or "\n" in token or "\r" in token:
                    raise AppError(400, "invalid_token", "请输入有效的飞鱼神图 Token。")
                result = run_cli(["set-token", "--stdin"], stdin_text=token, timeout=15)
                if not result.get("ok"):
                    raise AppError(502, "token_save_failed", "Token 保存失败，请重试。")
                self.send_json(200, {"token_configured": True})
                return
            if path == "/api/jobs":
                self.create_job()
                return
            retry_match = re.fullmatch(r"/api/jobs/(job-[a-f0-9]{32})/retry", path)
            if retry_match:
                source = fetch_job(retry_match.group(1))
                if source["status"] in ACTIVE_STATUSES:
                    raise AppError(409, "job_active", "当前任务仍在处理中。")
                payload = {
                    "title": source["title"],
                    "description": source["description"],
                    "total": source["total"],
                    "ai_model": source["ai_model"],
                    "fixed_setting": json.loads(source["fixed_setting_json"]),
                    "setting": json.loads(source["setting_json"]),
                }
                uploads = json.loads(source["uploads_json"])
                row = insert_job(payload, uploads, retry_of=source["id"])
                start_worker(process_job, row["id"])
                self.send_json(202, {"job": public_job(row)})
                return
            archive_match = re.fullmatch(r"/api/jobs/(job-[a-f0-9]{32})/retry-archive", path)
            if archive_match:
                row = fetch_job(archive_match.group(1))
                if row["status"] not in ("archive_partial", "archive_failed"):
                    raise AppError(409, "archive_not_retryable", "当前任务不需要重新归档。")
                update_job(row["id"], status="archive_retrying", error=None)
                start_worker(retry_archive, row["id"])
                self.send_json(202, {"job": public_job(fetch_job(row["id"]))})
                return
            raise AppError(404, "not_found", "接口不存在。")
        except Exception as exc:
            self.handle_error(exc)

    def read_json(self) -> dict:
        length = self.content_length()
        if length > 1024 * 1024:
            raise AppError(413, "body_too_large", "请求内容过大。")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise AppError(400, "invalid_json", "请求格式不正确。") from exc
        if not isinstance(payload, dict):
            raise AppError(400, "invalid_json", "请求格式不正确。")
        return payload

    def content_length(self) -> int:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise AppError(400, "invalid_length", "请求长度不正确。") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise AppError(413, "body_too_large", "上传内容不能超过 64 MB。")
        return length

    def create_job(self) -> None:
        length = self.content_length()
        content_type = str(self.headers.get("Content-Type") or "")
        if not content_type.startswith("multipart/form-data"):
            raise AppError(415, "multipart_required", "请使用表单上传产品图片。")
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            },
            keep_blank_values=True,
        )
        fields: dict[str, str] = {}
        file_items: list[cgi.FieldStorage] = []
        for item in form.list or []:
            if item.name == "images" and item.filename:
                file_items.append(item)
            elif item.name in {
                "title", "description", "total", "ai_model", "fixed_setting",
                "setting", "image_urls"
            }:
                fields[item.name] = str(item.value or "")
        payload = validate_payload(fields)
        uploads = save_uploads(file_items, parse_image_urls(fields.get("image_urls", "")))
        row = insert_job(payload, uploads)
        start_worker(process_job, row["id"])
        self.send_json(202, {"job": public_job(row)})

    def send_generated_file(self, encoded_relative: str, query: dict[str, list[str]]) -> None:
        self.send_data_file(GENERATED_DIR, encoded_relative, query)

    def send_data_file(self, root: Path, encoded_relative: str, query: dict[str, list[str]]) -> None:
        decoded = urllib.parse.unquote(encoded_relative)
        candidate = (root / decoded).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise AppError(404, "file_not_found", "文件不存在。") from exc
        if not candidate.is_file():
            raise AppError(404, "file_not_found", "文件不存在。")
        size = candidate.stat().st_size
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        disposition = "attachment" if (query.get("download") or [""])[0] == "1" else "inline"
        encoded_name = urllib.parse.quote(candidate.name, safe="")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{encoded_name}")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with candidate.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="飞鱼神图自定义栏目后端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=39081)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.host not in ("127.0.0.1", "::1"):
        print("For safety this backend may only listen on loopback.", file=sys.stderr)
        return 2
    if not CLI_PATH.is_file():
        print(f"Missing helper script: {CLI_PATH}", file=sys.stderr)
        return 2
    init_db()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    server.daemon_threads = True
    print(f"{utc_now()} listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

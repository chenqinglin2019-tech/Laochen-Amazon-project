#!/usr/bin/env python3
"""FeiyuShentu Amazon image generation helper."""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import getpass
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


BASE_URL = "https://server.feiyushentu.com/api/v0.1"
DEFAULT_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
CONFIG_PATH_ENV = "FEIYUSHENTU_CONFIG_PATH"
CONFIG_PATH = DEFAULT_CONFIG_PATH
TOKEN_KEY = "feiyushentu_token"
DEFAULT_POLL_INTERVAL = 5
DEFAULT_MAX_POLLS = 120
SKILL_ROOT = Path(__file__).resolve().parent.parent
SENSITIVE_FIELD_NAMES = {
    "authorization",
    "feiyushentu_token",
    "secretid",
    "secretkey",
    "token",
}


class SkillError(Exception):
    def __init__(self, message: str, error_type: str = "error", payload=None):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.payload = payload


class ApiError(SkillError):
    def __init__(self, message: str, code=None, payload=None):
        error_type = "api_error"
        if code == 10002:
            error_type = "token_empty"
            message = "FeiyuShentu token is empty or was not passed."
        elif code == 10003:
            error_type = "token_invalid"
            message = "FeiyuShentu token is invalid. Replace feiyushentu_token."
        elif code == 11008:
            error_type = "account_disabled"
            message = "FeiyuShentu account is disabled. Check the account or replace the token."
        super().__init__(message, error_type, payload)
        self.code = code


def redact_sensitive(value, secrets):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in SENSITIVE_FIELD_NAMES else redact_sensitive(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
    return value


def emit(obj, status: int = 0) -> int:
    try:
        token = load_token()
    except Exception:
        token = ""
    safe_obj = redact_sensitive(obj, [token] if token else [])
    print(json.dumps(safe_obj, ensure_ascii=False, indent=2))
    return status


def parse_json_object(raw: str, name: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SkillError(f"{name} must be valid JSON: {exc}", "invalid_json")
    if not isinstance(value, dict):
        raise SkillError(f"{name} must be a JSON object.", "invalid_json")
    return value


def parse_toml_string(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip('"')
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    return raw.split("#", 1)[0].strip()


def resolve_config_path(explicit_path=None) -> Path:
    raw_path = explicit_path or os.environ.get(CONFIG_PATH_ENV)
    if not raw_path:
        return DEFAULT_CONFIG_PATH
    return Path(raw_path).expanduser().resolve()


def load_token() -> str:
    if not CONFIG_PATH.exists():
        return ""
    pattern = re.compile(rf"^\s*{re.escape(TOKEN_KEY)}\s*=\s*(.*?)\s*$")
    for line in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            return parse_toml_string(match.group(1)).strip()
    return ""


def save_token(token: str) -> None:
    token = token.strip()
    if not token:
        raise SkillError("Token is empty.", "token_empty")
    if "\n" in token or "\r" in token:
        raise SkillError("Token must be a single line.", "invalid_token")

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    new_line = f"{TOKEN_KEY} = {json.dumps(token, ensure_ascii=False)}\n"
    pattern = re.compile(rf"^(\s*){re.escape(TOKEN_KEY)}\s*=")

    if CONFIG_PATH.exists():
        lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = []

    replaced = False
    updated_lines = []
    for line in lines:
        if pattern.match(line):
            if not replaced:
                updated_lines.append(new_line)
                replaced = True
            continue
        updated_lines.append(line)

    if not replaced:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] += "\n"
        updated_lines.append(new_line)

    fd, temp_name = tempfile.mkstemp(prefix=f".{CONFIG_PATH.name}.", dir=CONFIG_PATH.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write("".join(updated_lines))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, CONFIG_PATH)
        os.chmod(CONFIG_PATH, 0o600)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def token_or_error() -> str:
    token = load_token()
    if not token:
        raise SkillError(
            "Missing feiyushentu_token in the configured token file.",
            "token_missing",
        )
    return token


def request_json(path: str, method: str, payload=None, timeout: int = 60) -> dict:
    token = token_or_error()
    url = f"{BASE_URL}{path}"
    body = None if method == "GET" else json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "token": token,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise SkillError(
            f"HTTP {exc.code} from FeiyuShentu: {response_body}",
            "http_error",
            {"status": exc.code, "body": response_body},
        )
    except urllib.error.URLError as exc:
        raise SkillError(f"Network error: {exc}", "network_error")

    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise SkillError(
            f"FeiyuShentu returned non-JSON response: {exc}",
            "invalid_response",
            {"body": response_body},
        )

    code = data.get("code")
    if code != 200:
        raise ApiError(data.get("msg") or f"FeiyuShentu API error: {code}", code, data)
    return data


def api_post(path: str, payload=None, timeout: int = 60) -> dict:
    try:
        return request_json(path, "POST", payload, timeout)
    except ApiError as exc:
        if isinstance(exc.payload, dict):
            exc.payload.setdefault("endpoint", path)
        else:
            exc.payload = {"endpoint": path, "response": exc.payload}
        raise


def build_config_summary(data: dict) -> dict:
    result = {"fixedSetting": [], "model": []}
    body = data.get("data") or {}
    for item in body.get("fixedSetting") or []:
        result["fixedSetting"].append(
            {
                "title": item.get("title"),
                "field": item.get("field"),
                "default": item.get("default"),
                # Options keep their original shape: display name, submit value.
                "options": item.get("value") or [],
            }
        )
    for model in body.get("model") or []:
        result["model"].append(
            {
                # name is the display label; value is what goes out as aiModel.
                "name": model.get("name"),
                "label": model.get("label"),
                "value": model.get("value"),
                "points": model.get("points"),
                "plan": model.get("plan"),
                "setting": model.get("setting") or [],
            }
        )
    return result


def is_http_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def quote_component(value: str) -> str:
    return urllib.parse.quote(str(value), safe="-_.~")


def quote_path(path: str) -> str:
    return urllib.parse.quote(path, safe="/-_.~")


def cos_authorization(method: str, uri: str, host: str, token: str, secret_id: str, secret_key: str, expired_time) -> str:
    start = int(time.time()) - 60
    end = int(expired_time or (start + 1800))
    key_time = f"{start};{end}"

    signed_headers = {
        "host": host,
        "x-cos-security-token": token,
    }
    header_keys = sorted(signed_headers)
    header_list = ";".join(header_keys)
    header_string = "&".join(
        f"{quote_component(key)}={quote_component(signed_headers[key])}" for key in header_keys
    )

    http_string = "\n".join(
        [
            method.lower(),
            uri,
            "",
            header_string,
            "",
        ]
    )
    http_string_hash = hashlib.sha1(http_string.encode("utf-8")).hexdigest()
    string_to_sign = "\n".join(["sha1", key_time, http_string_hash, ""])

    sign_key = hmac.new(
        secret_key.encode("utf-8"),
        key_time.encode("utf-8"),
        hashlib.sha1,
    ).hexdigest()
    signature = hmac.new(
        sign_key.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).hexdigest()

    return "&".join(
        [
            "q-sign-algorithm=sha1",
            f"q-ak={quote_component(secret_id)}",
            f"q-sign-time={key_time}",
            f"q-key-time={key_time}",
            f"q-header-list={header_list}",
            "q-url-param-list=",
            f"q-signature={signature}",
        ]
    )


def cos_object_path(source: Path) -> str:
    today = _dt.datetime.now().strftime("%Y%m%d")
    filename = source.name.replace("/", "_").replace("\x00", "")
    return f"/Plug/RRRRRS//{today}/{uuid.uuid4().hex}_{filename}"


def upload_to_cos(local_path: str, cos_data: dict) -> str:
    source = Path(local_path).expanduser()
    if not source.exists() or not source.is_file():
        raise SkillError(f"Reference image does not exist: {local_path}", "missing_image")

    required = ["token", "secretId", "secretKey", "bucket", "region", "domain"]
    missing = [key for key in required if not cos_data.get(key)]
    if missing:
        raise SkillError(f"Image upload token response missing fields: {', '.join(missing)}", "invalid_upload_token")

    object_path = cos_object_path(source)
    encoded_path = quote_path(object_path)
    host = f"{cos_data['bucket']}.cos.{cos_data['region']}.myqcloud.com"
    upload_url = f"https://{host}{encoded_path}"
    mime_type = mimetypes.guess_type(str(source))[0] or "application/octet-stream"
    authorization = cos_authorization(
        "PUT",
        encoded_path,
        host,
        cos_data["token"],
        cos_data["secretId"],
        cos_data["secretKey"],
        cos_data.get("expiredTime"),
    )

    data = source.read_bytes()
    request = urllib.request.Request(
        upload_url,
        data=data,
        method="PUT",
        headers={
            "Authorization": authorization,
            "Content-Type": mime_type,
            "Content-Length": str(len(data)),
            "Host": host,
            "x-cos-security-token": cos_data["token"],
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SkillError(
            f"Image upload failed with HTTP {exc.code}: {body}",
            "image_upload_failed",
            {"status": exc.code, "body": body},
        )
    except urllib.error.URLError as exc:
        raise SkillError(f"Image upload network error: {exc}", "image_upload_failed")

    domain = str(cos_data["domain"]).strip()
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    return f"{domain.rstrip('/')}{encoded_path}"


def prepare_images(values) -> list:
    raw_images = []
    for item in values:
        if isinstance(item, list):
            raw_images.extend(item)
        elif item:
            raw_images.append(item)

    if not raw_images:
        raise SkillError("setting.images is required.", "missing_images")

    local_images = [image for image in raw_images if not is_http_url(str(image))]
    cos_data = None
    if local_images:
        cos_response = api_post("/common/yun.token", {})
        cos_data = cos_response.get("data") or {}

    prepared = []
    seen = set()
    for image in raw_images:
        image = str(image)
        final_url = image if is_http_url(image) else upload_to_cos(image, cos_data)
        if final_url not in seen:
            prepared.append(final_url)
            seen.add(final_url)
    return prepared


def submit_task(total: str, title: str, desc: str, fixed_setting: dict, ai_model: str, setting: dict) -> dict:
    images = setting.get("images")
    if not images:
        raise SkillError("setting.images is required.", "missing_images")
    if not isinstance(images, list):
        raise SkillError("setting.images must be an array of image URLs.", "invalid_images")

    payload = {
        "total": str(total),
        "title": title,
        "desc": desc,
        "fixedSetting": fixed_setting,
        "aiModel": ai_model,
        "setting": setting,
    }
    response = api_post("/amazon/amazon.img.task.agent.add", payload)
    tasks = response.get("data") or []
    task_ids = [item.get("task_id") for item in tasks if item.get("task_id")]
    if not task_ids:
        raise SkillError("Add-task response did not contain task_id.", "missing_task_id", response)
    return {"payload": payload, "response": response, "task_ids": task_ids}


def request_task_status(joined_task_ids: str, status_method: str) -> dict:
    if status_method == "post-json":
        return api_post("/amazon/amazon.img.task.status", {"taskIds": joined_task_ids})
    query = urllib.parse.urlencode({"taskIds": joined_task_ids})
    path = f"/amazon/amazon.img.task.status?{query}"
    if status_method == "post-query":
        return api_post(path, {})
    if status_method == "get-query":
        return request_json(path, "GET")
    raise SkillError(f"Unsupported status method: {status_method}", "invalid_status_method")


def poll_tasks(
    task_ids,
    interval: int = DEFAULT_POLL_INTERVAL,
    max_polls: int = DEFAULT_MAX_POLLS,
    verbose: bool = False,
    status_method: str = "post-query",
) -> dict:
    task_ids = [task_id for task_id in task_ids if task_id]
    if not task_ids:
        raise SkillError("task_ids is required.", "missing_task_id")

    joined = ",".join(task_ids)
    last_response = None
    for attempt in range(1, max_polls + 1):
        response = request_task_status(joined, status_method)
        last_response = response
        rows = response.get("data") or []
        by_id = {row.get("task_id"): row for row in rows if row.get("task_id")}

        if verbose:
            progress = {
                task_id: {
                    "status": by_id.get(task_id, {}).get("status"),
                    "progress": by_id.get(task_id, {}).get("progress"),
                }
                for task_id in task_ids
            }
            print(json.dumps({"attempt": attempt, "progress": progress}, ensure_ascii=False), file=sys.stderr)

        failed = [row for row in rows if row.get("status") == -1]
        if failed:
            return {
                "ok": False,
                "state": "failed",
                "message": "One or more image generation tasks failed.",
                "task_ids": task_ids,
                "failed": failed,
                "last_response": response,
            }

        all_done = all(by_id.get(task_id, {}).get("status") == 3 for task_id in task_ids)
        if all_done:
            images = []
            generated_images = []
            for task_id in task_ids:
                task_images = by_id.get(task_id, {}).get("images") or []
                images.extend(task_images)
                generated_images.extend(
                    {"task_id": task_id, "source_url": url} for url in task_images
                )
            return {
                "ok": True,
                "state": "success",
                "task_ids": task_ids,
                "images": images,
                "generated_images": generated_images,
                "last_response": response,
            }

        if attempt < max_polls:
            time.sleep(interval)

    return {
        "ok": False,
        "state": "timeout",
        "message": "Image generation did not finish before the polling limit.",
        "task_ids": task_ids,
        "last_response": last_response,
    }


def safe_path_segment(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
    return cleaned or fallback


def resolve_output_dir(output_dir: str) -> Path:
    target_dir = Path(output_dir).expanduser().resolve()
    try:
        target_dir.relative_to(SKILL_ROOT)
    except ValueError:
        pass
    else:
        raise SkillError(
            "Generated images cannot be stored inside the skill directory.",
            "invalid_output_dir",
        )
    return target_dir


def unique_target(target_dir: Path, basename: str) -> Path:
    target = target_dir / basename
    if not target.exists():
        return target
    for index in range(2, 10000):
        candidate = target_dir / f"{target.stem}_{index}{target.suffix}"
        if not candidate.exists():
            return candidate
    return target_dir / f"{target.stem}_{uuid.uuid4().hex[:8]}{target.suffix}"


def response_content_type(response) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    if hasattr(headers, "get_content_type"):
        return headers.get_content_type() or ""
    return str(headers.get("Content-Type") or "").split(";", 1)[0].strip()


def download_image_record(record: dict, root_dir: Path, group_by_task: bool) -> dict:
    source_url = str(record.get("source_url") or "")
    task_id = str(record.get("task_id") or "")
    if not is_http_url(source_url):
        raise SkillError(f"Invalid download URL: {source_url}", "invalid_url")

    target_dir = root_dir
    if group_by_task:
        target_dir = root_dir / safe_path_segment(task_id, "unassigned")
    target_dir.mkdir(parents=True, exist_ok=True)

    parsed = urllib.parse.urlparse(source_url)
    raw_basename = Path(urllib.parse.unquote(parsed.path)).name
    basename = safe_path_segment(raw_basename, f"{uuid.uuid4().hex}.png")
    target = unique_target(target_dir, basename)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target_dir)
    digest = hashlib.sha256()
    size_bytes = 0
    mime_type = ""
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            with urllib.request.urlopen(source_url, timeout=120) as response:
                mime_type = response_content_type(response)
                if mime_type and not (
                    mime_type.startswith("image/") or mime_type == "application/octet-stream"
                ):
                    raise SkillError(
                        f"Download returned non-image content for {source_url}: {mime_type}",
                        "download_failed",
                    )
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    size_bytes += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size_bytes == 0:
            raise SkillError(f"Downloaded image is empty: {source_url}", "download_failed")
        os.replace(temp_name, target)
    except urllib.error.URLError as exc:
        raise SkillError(f"Download failed for {source_url}: {exc}", "download_failed") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass

    return {
        "task_id": task_id or None,
        "source_url": source_url,
        "local_path": str(target),
        "filename": target.name,
        "size_bytes": size_bytes,
        "mime_type": mime_type or None,
        "sha256": digest.hexdigest(),
        "archive_status": "success",
        "error": None,
    }


def archive_generated_images(records, output_dir: str, group_by_task: bool = True) -> dict:
    root_dir = resolve_output_dir(output_dir)
    archived = []
    for item in records:
        record = item if isinstance(item, dict) else {"task_id": None, "source_url": item}
        try:
            archived.append(download_image_record(record, root_dir, group_by_task))
        except Exception as exc:
            archived.append(
                {
                    "task_id": record.get("task_id"),
                    "source_url": record.get("source_url"),
                    "local_path": None,
                    "filename": None,
                    "size_bytes": None,
                    "mime_type": None,
                    "sha256": None,
                    "archive_status": "failed",
                    "error": exc.message if isinstance(exc, SkillError) else str(exc),
                }
            )

    succeeded = sum(1 for item in archived if item["archive_status"] == "success")
    failed = len(archived) - succeeded
    if failed == 0 and archived:
        status = "success"
    elif succeeded:
        status = "partial"
    else:
        status = "failed"
    return {
        "requested": True,
        "status": status,
        "output_dir": str(root_dir),
        "success": succeeded,
        "failed": failed,
        "images": archived,
    }


def apply_archive(result: dict, output_dir) -> dict:
    if not output_dir:
        result["archive"] = {
            "requested": False,
            "status": "not_requested",
            "images": [],
        }
        return result
    if not result.get("ok"):
        result["archive"] = {
            "requested": True,
            "status": "not_started",
            "output_dir": str(resolve_output_dir(output_dir)),
            "images": [],
        }
        return result

    records = result.get("generated_images") or result.get("images") or []
    archive = archive_generated_images(records, output_dir)
    result["archive"] = archive
    if archive["status"] != "success":
        result["ok"] = False
    return result


def cmd_check_token(_args) -> int:
    token = load_token()
    return emit(
        {
            "ok": bool(token),
            "token_configured": bool(token),
        },
        0 if token else 1,
    )


def read_new_token(args) -> str:
    if args.stdin:
        return sys.stdin.read().strip()
    if sys.stdin.isatty():
        return getpass.getpass("FeiyuShentu token: ").strip()
    raise SkillError(
        "Use set-token --stdin for non-interactive token updates.",
        "token_input_required",
    )


def cmd_set_token(args) -> int:
    save_token(read_new_token(args))
    return emit(
        {
            "ok": True,
            "token_configured": True,
        }
    )


def cmd_fetch_config(args) -> int:
    response = api_post("/common/plug.select.field", {})
    result = {"ok": True, "summary": build_config_summary(response)}
    if args.raw:
        result["raw"] = response
    return emit(result)


def cmd_upload(args) -> int:
    cos_response = api_post("/common/yun.token", {})
    cos_data = cos_response.get("data") or {}
    uploaded = [upload_to_cos(path, cos_data) for path in args.image]
    return emit({"ok": True, "images": uploaded})


def cmd_submit(args) -> int:
    fixed_setting = parse_json_object(args.fixed_setting, "fixed-setting")
    setting = parse_json_object(args.setting, "setting")
    image_values = []
    if isinstance(setting.get("images"), list):
        image_values.append(setting.get("images"))
    image_values.extend(args.image or [])
    setting["images"] = prepare_images(image_values)
    result = submit_task(args.total, args.title, args.desc, fixed_setting, args.ai_model, setting)
    return emit({"ok": True, **result})


def cmd_status(args) -> int:
    output_dir = str(resolve_output_dir(args.output_dir)) if args.output_dir else None
    task_ids = []
    for item in args.task_id:
        task_ids.extend([part.strip() for part in item.split(",") if part.strip()])
    result = poll_tasks(task_ids, args.poll_interval, args.max_polls, args.verbose, args.status_method)
    result = apply_archive(result, output_dir)
    return emit(result, 0 if result.get("ok") else 1)


def cmd_generate(args) -> int:
    output_dir = str(resolve_output_dir(args.output_dir)) if args.output_dir else None
    fixed_setting = parse_json_object(args.fixed_setting, "fixed-setting")
    setting = parse_json_object(args.setting, "setting")
    image_values = []
    if isinstance(setting.get("images"), list):
        image_values.append(setting.get("images"))
    image_values.extend(args.image or [])
    setting["images"] = prepare_images(image_values)

    submitted = submit_task(args.total, args.title, args.desc, fixed_setting, args.ai_model, setting)
    if args.no_poll:
        archive = {
            "requested": bool(output_dir),
            "status": "pending" if output_dir else "not_requested",
            "images": [],
        }
        if output_dir:
            archive["output_dir"] = output_dir
        return emit({"ok": True, **submitted, "archive": archive})

    polled = poll_tasks(submitted["task_ids"], args.poll_interval, args.max_polls, args.verbose, args.status_method)
    polled = apply_archive(polled, output_dir)
    return emit(
        {
            **polled,
            "submitted": submitted,
        },
        0 if polled.get("ok") else 1,
    )


def cmd_download(args) -> int:
    archive = archive_generated_images(args.url, args.output_dir, group_by_task=False)
    paths = [item["local_path"] for item in archive["images"] if item["local_path"]]
    ok = archive["status"] == "success"
    return emit({"ok": ok, "paths": paths, "archive": archive}, 0 if ok else 1)


def split_image_values(raw: str) -> list:
    return [item.strip() for item in re.split(r"[|\n]", raw or "") if item.strip()]


def cmd_batch(args) -> int:
    output_dir = str(resolve_output_dir(args.output_dir)) if args.output_dir else None
    fixed_setting = parse_json_object(args.fixed_setting, "fixed-setting")
    base_setting = parse_json_object(args.setting, "setting")
    input_path = Path(args.csv).expanduser()
    if not input_path.is_file():
        raise SkillError(f"CSV file not found: {input_path}", "csv_not_found")

    results = []
    with input_path.open("r", encoding=args.encoding, newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"title", "desc", "total"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise SkillError(
                f"CSV is missing required columns: {', '.join(missing)}",
                "invalid_csv",
            )
        if "image_urls" not in (reader.fieldnames or []) and "images" not in (reader.fieldnames or []):
            raise SkillError("CSV must include image_urls or images column.", "invalid_csv")

        for row_number, row in enumerate(reader, start=2):
            result = {
                "row": row_number,
                "title": (row.get("title") or "").strip(),
                "task_ids": "",
                "status": "failed",
                "image_urls": "",
                "local_paths": "",
                "image_records": [],
                "archive_status": "not_started" if output_dir else "not_requested",
                "archive_error": "",
                "error": "",
            }
            try:
                if not result["title"] or not (row.get("desc") or "").strip() or not (row.get("total") or "").strip():
                    raise SkillError("title, desc, and total cannot be empty.", "invalid_csv_row")
                raw_images = row.get("image_urls") or row.get("images") or ""
                setting = dict(base_setting)
                configured_images = setting.get("images") if isinstance(setting.get("images"), list) else []
                setting["images"] = prepare_images(configured_images + split_image_values(raw_images))
                submitted = submit_task(
                    row["total"].strip(),
                    result["title"],
                    row["desc"].strip(),
                    fixed_setting,
                    args.ai_model,
                    setting,
                )
                polled = poll_tasks(
                    submitted["task_ids"],
                    args.poll_interval,
                    args.max_polls,
                    args.verbose,
                    args.status_method,
                )
                result["task_ids"] = ",".join(submitted["task_ids"])
                if polled.get("ok"):
                    result["image_urls"] = "|".join(polled.get("images") or [])
                    polled = apply_archive(polled, output_dir)
                    archive = polled["archive"]
                    result["archive_status"] = archive["status"]
                    result["image_records"] = archive["images"]
                    result["local_paths"] = "|".join(
                        item["local_path"] for item in archive["images"] if item["local_path"]
                    )
                    archive_errors = [item["error"] for item in archive["images"] if item["error"]]
                    result["archive_error"] = " | ".join(archive_errors)
                    if archive["status"] in {"success", "not_requested"}:
                        result["status"] = "success"
                    else:
                        result["status"] = f"archive_{archive['status']}"
                        result["error"] = result["archive_error"] or "image_archive_failed"
                else:
                    result["error"] = polled.get("message") or polled.get("state") or "generation_failed"
            except (ApiError, SkillError) as exc:
                result["error"] = exc.message
            results.append(result)

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "row",
                "title",
                "task_ids",
                "status",
                "image_urls",
                "local_paths",
                "image_records",
                "archive_status",
                "archive_error",
                "error",
            ],
        )
        writer.writeheader()
        for result in results:
            csv_result = dict(result)
            csv_result["image_records"] = json.dumps(result["image_records"], ensure_ascii=False)
            writer.writerow(csv_result)
    failed = sum(1 for item in results if item["status"] != "success")
    return emit({"ok": failed == 0, "input": str(input_path), "output": str(output_path), "total_rows": len(results), "success": len(results) - failed, "failed": failed, "results": results}, 0 if failed == 0 else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FeiyuShentu Amazon image generation helper.")
    parser.add_argument(
        "--config-path",
        help=f"Token config TOML path. Overrides {CONFIG_PATH_ENV}; defaults to ~/.codex/config.toml.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check-token", help="Check whether feiyushentu_token exists.")
    check.set_defaults(func=cmd_check_token)

    set_token = subparsers.add_parser("set-token", help="Save or replace feiyushentu_token.")
    set_token.add_argument(
        "--stdin",
        action="store_true",
        help="Read the new token from standard input. Without this flag, prompt securely in a terminal.",
    )
    set_token.set_defaults(func=cmd_set_token)

    fetch = subparsers.add_parser("fetch-config", help="Fetch selectable fixed settings and models.")
    fetch.add_argument("--raw", action="store_true", help="Include the full raw FeiyuShentu response.")
    fetch.set_defaults(func=cmd_fetch_config)

    upload = subparsers.add_parser("upload", help="Upload local reference images for generation.")
    upload.add_argument("--image", action="append", required=True, help="Local image path. Repeatable.")
    upload.set_defaults(func=cmd_upload)

    submit = subparsers.add_parser("submit", help="Submit a generation task without polling.")
    add_generation_args(submit)
    submit.set_defaults(func=cmd_submit)

    status = subparsers.add_parser("status", help="Poll task status.")
    status.add_argument("--task-id", action="append", required=True, help="Task ID or comma-separated IDs.")
    status.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    status.add_argument("--max-polls", type=int, default=DEFAULT_MAX_POLLS)
    status.add_argument(
        "--status-method",
        choices=["post-json", "post-query", "get-query"],
        default="post-query",
        help="Task status request format. Default uses POST with taskIds in the query string.",
    )
    status.add_argument("--verbose", action="store_true")
    status.add_argument(
        "--output-dir",
        help="Archive successful generated images under this caller-owned directory.",
    )
    status.set_defaults(func=cmd_status)

    generate = subparsers.add_parser("generate", help="Submit a task and poll until success, failure, or timeout.")
    add_generation_args(generate)
    generate.add_argument("--no-poll", action="store_true")
    generate.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    generate.add_argument("--max-polls", type=int, default=DEFAULT_MAX_POLLS)
    generate.add_argument(
        "--status-method",
        choices=["post-json", "post-query", "get-query"],
        default="post-query",
        help="Task status request format. Default uses POST with taskIds in the query string.",
    )
    generate.add_argument("--verbose", action="store_true")
    generate.add_argument(
        "--output-dir",
        help="Archive successful generated images under this caller-owned directory.",
    )
    generate.set_defaults(func=cmd_generate)

    download = subparsers.add_parser("download", help="Download generated image URLs.")
    download.add_argument("--url", action="append", required=True, help="Generated image URL. Repeatable.")
    download.add_argument("--output-dir", required=True, help="Directory selected by the user.")
    download.set_defaults(func=cmd_download)

    batch = subparsers.add_parser("batch", help="Generate images for every row in a CSV file.")
    batch.add_argument("--csv", required=True, help="Input CSV path.")
    batch.add_argument("--output", required=True, help="Output CSV path.")
    batch.add_argument("--fixed-setting", required=True, help="JSON object confirmed from fixedSetting.")
    batch.add_argument("--ai-model", required=True, help="Model value from model[].value.")
    batch.add_argument("--setting", required=True, help="JSON object for selected model settings.")
    batch.add_argument("--encoding", default="utf-8-sig", help="Input CSV encoding.")
    batch.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    batch.add_argument("--max-polls", type=int, default=DEFAULT_MAX_POLLS)
    batch.add_argument(
        "--status-method",
        choices=["post-json", "post-query", "get-query"],
        default="post-query",
        help="Task status request format.",
    )
    batch.add_argument("--verbose", action="store_true")
    batch.add_argument(
        "--output-dir",
        help="Archive successful generated images under this caller-owned directory.",
    )
    batch.set_defaults(func=cmd_batch)

    return parser


def add_generation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--total", required=True, help="Number of images to generate; sent as string.")
    parser.add_argument("--title", required=True, help="Product title.")
    parser.add_argument("--desc", required=True, help="Product description.")
    parser.add_argument("--fixed-setting", required=True, help="JSON object confirmed from fixedSetting.")
    parser.add_argument("--ai-model", required=True, help="Model value from model[].value.")
    parser.add_argument("--setting", required=True, help="JSON object for selected model settings.")
    parser.add_argument("--image", action="append", help="Reference image URL or local path. Repeatable.")


def main(argv=None) -> int:
    global CONFIG_PATH
    parser = build_parser()
    args = parser.parse_args(argv)
    CONFIG_PATH = resolve_config_path(args.config_path)
    try:
        return args.func(args)
    except ApiError as exc:
        return emit(
            {
                "ok": False,
                "error_type": exc.error_type,
                "code": exc.code,
                "message": exc.message,
                "response": exc.payload,
            },
            1,
        )
    except SkillError as exc:
        return emit(
            {
                "ok": False,
                "error_type": exc.error_type,
                "message": exc.message,
                "details": exc.payload,
            },
            1,
        )


if __name__ == "__main__":
    sys.exit(main())

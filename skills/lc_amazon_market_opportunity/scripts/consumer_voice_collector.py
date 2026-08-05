#!/usr/bin/env python3
"""Resumable consumer-voice collector for the market-opportunity workflow.

The collector is intentionally independent from last30days and agent-reach.  It
uses only the Python standard library, keeps resumable state in SQLite, and
exposes injection points for HTTP and subprocess execution so pagination and
fallback behaviour can be tested without contacting a platform.
"""

from __future__ import annotations

import argparse
import copy
import getpass
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


SCHEMA_VERSION = "2.0.0"
DEFAULT_DAILY_YOUTUBE_QUOTA = 10_000
MIN_YOUTUBE_QUOTA_RESERVE = 2_500
DEFAULT_REMINDER_INTERVAL_MINUTES = 10
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
BUNDLED_PYTHON = Path(
    "/Users/laochen/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
)
DEFAULT_LAST30DAYS_SCRIPT = Path(
    "/Users/laochen/.codex/skills/last30days/scripts/last30days.py"
)
SCOPES = (
    "category_30d",
    "segment_1_90d",
    "segment_2_90d",
    "segment_3_90d",
)
FUNNEL_STAGE_FIELDS = (
    "fetched_records",
    "unique_records",
    "within_window_records",
    "relevant_records",
    "consumer_records",
    "deduplicated_records",
    "valid_voices",
)
STOP_REASONS = frozenset(
    {
        "upper_bound_reached",
        "queues_exhausted",
        "low_increment_3_batches",
        "platform_or_quota_limit",
        "collection_deadline",
        "total_deadline",
        "manual_stop",
    }
)
COST_STATUSES = frozenset(
    {
        "provider_confirmed_actual",
        "estimated_from_price_snapshot",
        "quota_only",
        "unknown",
        "not_metered",
    }
)
FINALIZATION_RESERVE_SECONDS = 300.0
TIMED_PHASES: Dict[str, Dict[str, Any]] = {
    "agent_reach": {"meter_scope": "collection_and_total", "finalization_allowed": False},
    "codex_coding": {"meter_scope": "total_only", "finalization_allowed": False},
    "product_analysis": {"meter_scope": "total_only", "finalization_allowed": False},
    "supply_validation": {"meter_scope": "total_only", "finalization_allowed": False},
    "concept_images": {"meter_scope": "total_only", "finalization_allowed": False},
    "report_finalize": {"meter_scope": "total_only", "finalization_allowed": True},
    "manifest_finalize": {"meter_scope": "total_only", "finalization_allowed": True},
    "youtube_api_setup": {"meter_scope": "unmetered", "finalization_allowed": True},
}


def _scope_targets(category_min: int, category_max: int, segment_min: int, segment_max: int) -> Dict[str, Dict[str, Any]]:
    result = {
        "category_30d": {
            "share": 0.4,
            "valid_min": category_min,
            "valid_max": category_max,
        }
    }
    for index in range(1, 4):
        result["segment_%d_90d" % index] = {
            "share": 0.2,
            "valid_min": segment_min,
            "valid_max": segment_max,
        }
    return result


RESEARCH_LEVELS: Dict[str, Dict[str, Any]] = {
    "quick": {
        "sample_target": {
            "total_valid_min": 500,
            "total_valid_max": 1000,
            "per_scope": _scope_targets(200, 400, 100, 200),
            "min_platforms": 3,
        },
        "time_budget_minutes": {"collection": 35, "total": 60},
    },
    "standard": {
        "sample_target": {
            "total_valid_min": 1000,
            "total_valid_max": 3000,
            "per_scope": _scope_targets(400, 1200, 200, 600),
            "min_platforms": 3,
        },
        "time_budget_minutes": {"collection": 55, "total": 90},
    },
    "deep": {
        "sample_target": {
            "total_valid_min": 3000,
            "total_valid_max": 5000,
            "per_scope": _scope_targets(1200, 2000, 600, 1000),
            "min_platforms": 3,
        },
        "time_budget_minutes": {"collection": 75, "total": 120},
    },
}

YOUTUBE_LEVEL_BUDGETS: Dict[str, Dict[str, int]] = {
    "quick": {"comment_request_budget": 1000, "search_call_max": 10},
    "standard": {"comment_request_budget": 2500, "search_call_max": 20},
    "deep": {"comment_request_budget": 5000, "search_call_max": 30},
}

YOUTUBE_CONFIG_DEFAULTS: Dict[str, str] = {
    "YOUTUBE_DATA_API_ENABLED": "true",
    "YOUTUBE_DATA_API_KEY": "",
    "YOUTUBE_API_DAILY_QUOTA_UNITS": "10000",
    "YOUTUBE_API_QUOTA_RESERVE": "2500",
    "YOUTUBE_SEARCH_API_ENABLED": "false",
    "YOUTUBE_API_MAX_RESULTS": "100",
    "YOUTUBE_API_MAX_WORKERS": "4",
}
YOUTUBE_CONFIG_KEYS = tuple(YOUTUBE_CONFIG_DEFAULTS)

DEFAULT_LEVEL_REMINDER = "本次默认采用快速验证（500–1,000条，最长60分钟）。你也可以选择标准研究（1,000–3,000条，最长90分钟）或深度研究（3,000–5,000条，最长120分钟），样本更多，但会消耗更长时间。"
PRIMARY_SOCIAL_PLATFORMS = ("reddit", "x", "youtube", "tiktok", "instagram")
QUANTITATIVE_PLATFORMS = frozenset(PRIMARY_SOCIAL_PLATFORMS)
PLATFORM_ALIASES = {"twitter": "x", "x.com": "x"}


class CollectorError(Exception):
    """Expected collector failure safe to show after redaction."""


class ConfigurationError(CollectorError):
    """Invalid or missing local configuration."""


class QuotaLimitError(CollectorError):
    """The configured quota budget cannot admit another request."""


class RetryableHttpError(CollectorError):
    """A transient HTTP response that may be retried within the task deadline."""

    def __init__(self, status_code: int, message: Optional[str] = None):
        super().__init__(message or "YouTube API HTTP %d" % status_code)
        self.status_code = int(status_code)


class DeadlineError(CollectorError):
    """A hard execution deadline was reached."""

    def __init__(self, stop_reason: str):
        if stop_reason not in {"collection_deadline", "total_deadline"}:
            raise ValueError("invalid deadline stop reason")
        super().__init__(stop_reason)
        self.stop_reason = stop_reason


class StopCollection(CollectorError):
    def __init__(self, stop_reason: str):
        if stop_reason not in STOP_REASONS:
            raise ValueError("invalid stop reason")
        super().__init__(stop_reason)
        self.stop_reason = stop_reason


def interleave_youtube_batches_by_scope(
    rows: Sequence[Mapping[str, Any]], scope_order: Sequence[str]
) -> List[Mapping[str, Any]]:
    """Keep discovery first, then round-robin comment batches across scopes."""

    def field(row: Mapping[str, Any], key: str) -> Any:
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return None

    discovery = [row for row in rows if str(field(row, "source") or "") != "youtube"]
    youtube = [row for row in rows if str(field(row, "source") or "") == "youtube"]
    grouped: Dict[str, List[Mapping[str, Any]]] = {scope: [] for scope in scope_order}
    unknown: List[Mapping[str, Any]] = []
    for row in youtube:
        scope = str(field(row, "scope") or "")
        if scope in grouped:
            grouped[scope].append(row)
        else:
            unknown.append(row)
    scheduled: List[Mapping[str, Any]] = []
    while any(grouped.values()):
        for scope in scope_order:
            if grouped[scope]:
                scheduled.append(grouped[scope].pop(0))
    return [*discovery, *scheduled, *unknown]


class ScopeUpperReached(CollectorError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: Optional[datetime] = None) -> str:
    current = value or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def current_boot_id() -> str:
    """Return a stable identifier for the OS boot and monotonic clock domain.

    On macOS, different Python runtimes can expose incompatible monotonic
    epochs.  Binding the hashed executable/runtime domain prevents a phase
    started by one interpreter from being charged as many hours by another.
    """
    clock_domain = hashlib.sha256(
        (
            os.path.realpath(sys.executable)
            + "\0"
            + sys.implementation.name
            + "\0"
            + ".".join(str(value) for value in sys.version_info[:3])
        ).encode("utf-8")
    ).hexdigest()[:16]
    linux_boot_id = Path("/proc/sys/kernel/random/boot_id")
    if linux_boot_id.is_file():
        try:
            value = linux_boot_id.read_text(encoding="utf-8").strip()
            if value:
                return hashlib.sha256(
                    ("linux\0" + value + "\0" + clock_domain).encode("utf-8")
                ).hexdigest()[:24]
        except OSError:
            pass
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["sysctl", "-n", "kern.boottime"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                return hashlib.sha256(
                    (
                        "darwin\0"
                        + completed.stdout.strip()
                        + "\0"
                        + clock_domain
                    ).encode("utf-8")
                ).hexdigest()[:24]
        except (OSError, subprocess.SubprocessError):
            pass
    # Fallback: the estimated boot epoch rounded to five minutes is stable
    # across processes while avoiding a host/user identifier in artifacts.
    estimated_boot_bucket = int((time.time() - time.monotonic()) // 300)
    return hashlib.sha256(
        (
            "fallback\0%s\0%d\0%s"
            % (os.name, estimated_boot_bucket, clock_domain)
        ).encode("utf-8")
    ).hexdigest()[:24]


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
        os.chmod(str(path), mode)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _atomic_write_bytes(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".%s." % path.name, dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
        os.chmod(str(path), mode)
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _secure_directory(path: Path) -> None:
    """Create a private task directory and keep it private on POSIX hosts."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(path, 0o700)


def _secure_runtime_tree(root: Path) -> None:
    """Normalize collector-owned runtime artifacts after an external tool exits."""
    if not root.exists():
        return
    if os.name == "nt":
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts)):
        try:
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        except FileNotFoundError:
            # External tools may atomically rotate transient artifacts.
            continue
    os.chmod(root, 0o700)


def write_json(path: Path, value: Any, mode: int = 0o600) -> None:
    _atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n", mode=mode)


_SECRET_PATTERNS = (
    re.compile(r"(?i)(YOUTUBE_(?:DATA_)?API_KEY\s*=\s*)[^\s\"']+"),
    re.compile(r"(?i)([?&](?:key|api[_-]?key)=)[^&\s]+"),
    re.compile(r"AIza[0-9A-Za-z_-]{16,}"),
)


def redact_text(value: Any, known_secrets: Sequence[str] = ()) -> str:
    text = str(value)
    for secret in known_secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    text = _SECRET_PATTERNS[0].sub(r"\1<redacted>", text)
    text = _SECRET_PATTERNS[1].sub(r"\1<redacted>", text)
    text = _SECRET_PATTERNS[2].sub("<redacted>", text)
    return text


def redact_value(value: Any, known_secrets: Sequence[str] = ()) -> Any:
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, child in value.items():
            if str(key).lower() in {"key", "api_key", "youtube_api_key", "token", "secret"}:
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = redact_value(child, known_secrets)
        return result
    if isinstance(value, list):
        return [redact_value(child, known_secrets) for child in value]
    if isinstance(value, tuple):
        return [redact_value(child, known_secrets) for child in value]
    if isinstance(value, str):
        return redact_text(value, known_secrets)
    return value


def default_youtube_config_path() -> Path:
    configured = os.environ.get("LCADMO_YOUTUBE_API_CONFIG", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "lc_amazon_market_opportunity" / "youtube_api.env"


def youtube_global_quota_ledger_path(config_path: Path) -> Path:
    configured = os.environ.get("LCADMO_YOUTUBE_QUOTA_LEDGER", "").strip()
    if configured:
        return Path(configured).expanduser()
    return config_path.expanduser().parent / "youtube_quota_ledger.sqlite3"


class YoutubeGlobalQuotaLedger:
    """Process-safe daily quota reservations shared by tasks using one config."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS quota_reservations(
                reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                utc_day TEXT NOT NULL,
                units INTEGER NOT NULL,
                task_id TEXT,
                batch_id TEXT,
                operation TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            )"""
        )
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "YoutubeGlobalQuotaLedger":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def reserve(
        self,
        units: int,
        daily_limit: int,
        reserve: int,
        occurred_at: datetime,
        task_id: Optional[str],
        batch_id: Optional[str],
        operation: str,
    ) -> Dict[str, int]:
        amount = int(units)
        if amount <= 0:
            return {"used_before": 0, "used_after": 0}
        day = occurred_at.astimezone(timezone.utc).date().isoformat()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT COALESCE(SUM(units),0) FROM quota_reservations WHERE utc_day=?",
                (day,),
            ).fetchone()
            used = int(row[0] if row else 0)
            if used + amount > int(daily_limit) - int(reserve):
                self.connection.execute("ROLLBACK")
                raise QuotaLimitError("YouTube 全局日配额将触及固定保留量")
            self.connection.execute(
                """INSERT INTO quota_reservations(
                    utc_day,units,task_id,batch_id,operation,occurred_at
                ) VALUES(?,?,?,?,?,?)""",
                (day, amount, task_id, batch_id, operation, iso_utc(occurred_at)),
            )
            self.connection.execute("COMMIT")
            return {"used_before": used, "used_after": used + amount}
        except QuotaLimitError:
            raise
        except sqlite3.Error:
            try:
                self.connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise


def parse_env_file(path: Path, require_secure: bool = True) -> Dict[str, str]:
    if not path.exists():
        raise ConfigurationError("YouTube API 配置不存在：%s" % path)
    mode = stat.S_IMODE(path.stat().st_mode)
    if require_secure and os.name != "nt" and mode != 0o600:
        raise ConfigurationError("YouTube API 配置权限必须为 0600，当前为 %04o" % mode)
    values: Dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ConfigurationError("配置第 %d 行不是 KEY=VALUE" % line_number)
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
            raw_value = raw_value[1:-1]
        values[key] = raw_value
    return values


def setup_youtube_api_config(path: Path) -> Dict[str, Any]:
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        return {
            "status": "exists_not_overwritten",
            "config_path": str(path),
            "secure_permissions": os.name == "nt" or mode == 0o600,
            "instructions": _youtube_setup_instructions(path),
        }
    body = (
        "# YouTube Data API v3 private configuration. Never paste the key into chat.\n"
        + "\n".join("%s=%s" % item for item in YOUTUBE_CONFIG_DEFAULTS.items())
        + "\n"
    )
    _atomic_write_text(path, body, mode=0o600)
    return {
        "status": "created",
        "config_path": str(path),
        "mode": "0600" if os.name != "nt" else "platform_managed",
        "instructions": _youtube_setup_instructions(path),
    }


def _youtube_setup_instructions(path: Path) -> List[str]:
    return [
        "在 Google Cloud Console 创建或选择项目：https://console.cloud.google.com/",
        "启用 YouTube Data API v3：https://console.cloud.google.com/apis/library/youtube.googleapis.com",
        "创建 API key，并限制到 YouTube Data API v3；如有固定出口，再增加 IP 限制。",
        "只在本机编辑 %s，填写 YOUTUBE_DATA_API_KEY，并保持 YOUTUBE_DATA_API_ENABLED=true。" % path,
        "YOUTUBE_API_MAX_WORKERS 是允许的并发上限；当前为保证 SQLite 断点与配额顺序一致，实际执行线程数为 1。",
        "不要把 API key 粘贴到对话、命令行参数、截图或报告中。",
    ]


def _parse_bool_config(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ConfigurationError("%s 必须为 true 或 false" % name)
    return normalized == "true"


def load_youtube_api_config(path: Path, require_key: bool = False) -> Dict[str, Any]:
    values = parse_env_file(path, require_secure=True)
    unknown = sorted(set(values) - set(YOUTUBE_CONFIG_KEYS))
    missing = [key for key in YOUTUBE_CONFIG_KEYS if key not in values]
    if unknown or missing:
        details = []
        if unknown:
            details.append("未知字段：%s" % ",".join(unknown))
        if missing:
            details.append("缺少字段：%s" % ",".join(missing))
        raise ConfigurationError("YouTube 配置字段不符合固定契约；%s" % "；".join(details))
    enabled = _parse_bool_config("YOUTUBE_DATA_API_ENABLED", values["YOUTUBE_DATA_API_ENABLED"])
    search_enabled = _parse_bool_config(
        "YOUTUBE_SEARCH_API_ENABLED", values["YOUTUBE_SEARCH_API_ENABLED"]
    )
    key = values["YOUTUBE_DATA_API_KEY"].strip()
    try:
        daily_quota = int(values["YOUTUBE_API_DAILY_QUOTA_UNITS"])
        reserve = int(values["YOUTUBE_API_QUOTA_RESERVE"])
        max_results = int(values["YOUTUBE_API_MAX_RESULTS"])
        max_workers = int(values["YOUTUBE_API_MAX_WORKERS"])
    except ValueError:
        raise ConfigurationError("YouTube quota/max 配置必须是整数")
    if daily_quota <= 0:
        raise ConfigurationError("YOUTUBE_API_DAILY_QUOTA_UNITS 必须为正整数")
    if reserve < MIN_YOUTUBE_QUOTA_RESERVE or reserve >= daily_quota:
        raise ConfigurationError("YOUTUBE_API_QUOTA_RESERVE 必须 >=2500 且小于 daily quota")
    if not 1 <= max_results <= 100:
        raise ConfigurationError("YOUTUBE_API_MAX_RESULTS 必须在 1-100")
    if not 1 <= max_workers <= 8:
        raise ConfigurationError("YOUTUBE_API_MAX_WORKERS 必须在 1-8")
    if (enabled or require_key) and not key:
        raise ConfigurationError("YouTube Data API 已启用但未填写 YOUTUBE_DATA_API_KEY")
    return {
        "enabled": enabled,
        "api_key": key,
        "daily_quota_units": daily_quota,
        "quota_reserve": reserve,
        "search_enabled": search_enabled,
        "max_results": max_results,
        "max_workers": max_workers,
    }


def disabled_youtube_runtime_config() -> Dict[str, Any]:
    """Return a secret-free runtime config that preserves all non-key defaults."""
    return {
        "enabled": False,
        "api_key": "",
        "daily_quota_units": int(YOUTUBE_CONFIG_DEFAULTS["YOUTUBE_API_DAILY_QUOTA_UNITS"]),
        "quota_reserve": int(YOUTUBE_CONFIG_DEFAULTS["YOUTUBE_API_QUOTA_RESERVE"]),
        "search_enabled": False,
        "max_results": int(YOUTUBE_CONFIG_DEFAULTS["YOUTUBE_API_MAX_RESULTS"]),
        "max_workers": int(YOUTUBE_CONFIG_DEFAULTS["YOUTUBE_API_MAX_WORKERS"]),
    }


def load_youtube_config_for_collection(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Load YouTube config without allowing setup errors to abort other collectors."""
    try:
        config = load_youtube_api_config(path)
    except ConfigurationError as exc:
        return disabled_youtube_runtime_config(), {
            "status": "needs_setup",
            "config_path": str(path),
            "error": redact_text(exc),
            "instructions": _youtube_setup_instructions(path),
        }
    status = "enabled" if config["enabled"] else "disabled"
    return config, {
        "status": status,
        "config_path": str(path),
        "instructions": [] if status == "enabled" else _youtube_setup_instructions(path),
    }


def check_youtube_api_config(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "config_path": str(path),
        "exists": path.exists(),
        "secure_permissions": False,
        "configured": False,
        "status": "unconfigured",
    }
    if not path.exists():
        return result
    mode = stat.S_IMODE(path.stat().st_mode)
    result["mode"] = "%04o" % mode
    result["secure_permissions"] = os.name == "nt" or mode == 0o600
    try:
        config = load_youtube_api_config(path)
        result.update(
            {
                "configured": bool(config["enabled"] and config["api_key"]),
                "enabled": config["enabled"],
                "search_enabled": config["search_enabled"],
                "status": "configured" if config["enabled"] and config["api_key"] else "disabled",
                "daily_quota_units": config["daily_quota_units"],
                "quota_reserve": config["quota_reserve"],
                "max_results": config["max_results"],
                "max_workers": config["max_workers"],
            }
        )
    except (ConfigurationError, ValueError) as exc:
        error = redact_text(exc)
        result["status"] = (
            "needs_setup" if "未填写 YOUTUBE_DATA_API_KEY" in error else "invalid"
        )
        result["error"] = error
    return result


def youtube_api_live_check(path: Path, http_client: Optional[Any] = None) -> Dict[str, Any]:
    """Validate the configured key with one official read-only videos.list call."""
    base = check_youtube_api_config(path)
    if base.get("status") != "configured":
        base["live_check"] = {"attempted": False, "status": "not_configured"}
        return base
    config = load_youtube_api_config(path, require_key=True)
    http = http_client or UrllibHttpClient()
    try:
        with YoutubeGlobalQuotaLedger(youtube_global_quota_ledger_path(path)) as ledger:
            ledger.reserve(
                1,
                int(config["daily_quota_units"]),
                int(config["quota_reserve"]),
                utc_now(),
                None,
                None,
                "videos.list.live_check",
            )
        response = http.get_json(
            YOUTUBE_API_BASE + "/videos",
            {
                "part": "id",
                "id": "dQw4w9WgXcQ",
            },
            20.0,
            headers={"x-goog-api-key": config["api_key"]},
        )
        if isinstance(response.get("error"), Mapping):
            message = response["error"].get("message") or "YouTube API error"
            raise CollectorError(redact_text(message, (config["api_key"],)))
        base["live_check"] = {
            "attempted": True,
            "status": "ok",
            "operation": "videos.list",
            "read_only": True,
            "quota_units": 1,
        }
        base["status"] = "ok"
    except Exception as exc:
        base["live_check"] = {
            "attempted": True,
            "status": "failed",
            "operation": "videos.list",
            "error": redact_text(exc, (config["api_key"],)),
        }
        base["status"] = "invalid_or_unreachable"
    return base


def research_plan(research_level: str, reminders_enabled: bool = True, reminder_interval_minutes: int = DEFAULT_REMINDER_INTERVAL_MINUTES) -> Dict[str, Any]:
    if research_level not in RESEARCH_LEVELS:
        raise ConfigurationError("未知 research level：%s" % research_level)
    if reminder_interval_minutes <= 0:
        raise ConfigurationError("提醒间隔必须为正数")
    fixed = copy.deepcopy(RESEARCH_LEVELS[research_level])
    return {
        "research_level": research_level,
        "sample_target": fixed["sample_target"],
        "time_budget_minutes": fixed["time_budget_minutes"],
    }


def collection_policy(
    research_level: str,
    reminders_enabled: bool = True,
    reminder_interval_minutes: int = DEFAULT_REMINDER_INTERVAL_MINUTES,
    research_level_explicit: bool = False,
) -> Dict[str, Any]:
    if research_level not in RESEARCH_LEVELS:
        raise ConfigurationError("未知 research level：%s" % research_level)
    return {
        "reminder_policy": {
            "enabled": bool(reminders_enabled),
            "mode": "non_blocking",
            "interval_minutes": reminder_interval_minutes,
        },
        "youtube_api_budget": copy.deepcopy(YOUTUBE_LEVEL_BUDGETS[research_level]),
        "research_level_explicit": bool(research_level_explicit),
    }


def _normalize_exact_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_platform(value: Any) -> str:
    platform = str(value or "unknown").strip().casefold()
    return PLATFORM_ALIASES.get(platform, platform)


def _author_hash(source: str, author_id: str, author_label: str) -> Optional[str]:
    identity = author_id.strip() or author_label.strip()
    if not identity:
        return None
    digest = hashlib.sha256((source + "\0" + identity).encode("utf-8")).hexdigest()
    return "author_%s" % digest[:24]


def canonicalize_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        split = urllib_parse.urlsplit(text)
    except ValueError:
        return text
    ignored_query_keys = {
        "fbclid", "gclid", "si", "ref", "ref_source", "context", "depth",
        "feature", "ab_channel", "pp", "t", "s", "share_id",
    }
    query = sorted(
        (key, child)
        for key, child in urllib_parse.parse_qsl(split.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in ignored_query_keys
    )
    host = split.netloc.lower().rstrip(".")
    host_aliases = {
        "www.reddit.com": "reddit.com",
        "old.reddit.com": "reddit.com",
        "new.reddit.com": "reddit.com",
        "np.reddit.com": "reddit.com",
        "www.youtube.com": "youtube.com",
        "m.youtube.com": "youtube.com",
        "www.x.com": "x.com",
        "mobile.x.com": "x.com",
        "twitter.com": "x.com",
        "www.twitter.com": "x.com",
        "mobile.twitter.com": "x.com",
        "www.instagram.com": "instagram.com",
        "www.tiktok.com": "tiktok.com",
        "m.tiktok.com": "tiktok.com",
    }
    host = host_aliases.get(host, host)
    return urllib_parse.urlunsplit(
        (split.scheme.lower(), host, split.path.rstrip("/"), urllib_parse.urlencode(query), "")
    )


def is_comment_level_url(source: str, value: str) -> bool:
    if not value:
        return False
    try:
        split = urllib_parse.urlsplit(value)
        query = dict(urllib_parse.parse_qsl(split.query, keep_blank_values=True))
    except ValueError:
        return False
    platform = normalize_platform(source)
    if platform == "youtube":
        return bool(query.get("lc"))
    if platform == "reddit":
        parts = [part for part in split.path.split("/") if part]
        try:
            position = parts.index("comments")
        except ValueError:
            return False
        return len(parts) > position + 3
    if platform == "x":
        return bool(re.search(r"/status/\d+/?$", split.path))
    if platform in {"tiktok", "instagram"}:
        return bool(query.get("comment_id") or query.get("commentId"))
    return False


def _identity_entity_kind(source: str, comment: Mapping[str, Any], canonical_url: str) -> str:
    parent_id = str(
        comment.get("parent_content_id") or comment.get("parent_comment_id") or ""
    ).strip()
    content_id = str(comment.get("content_id") or comment.get("comment_id") or "").strip()
    video_id = str(comment.get("video_id") or "").strip()
    if parent_id or is_comment_level_url(source, canonical_url):
        return "message"
    if source == "youtube" and video_id and content_id and content_id != video_id:
        return "message"
    return "content"


def _identity_alias_candidates(comment: Mapping[str, Any]) -> List[Tuple[str, str, str]]:
    """Return all provable hard identities, ordered from strongest to weakest."""
    source = normalize_platform(comment.get("source") or comment.get("platform"))
    content_id = str(comment.get("content_id") or comment.get("comment_id") or "").strip()
    canonical_url = canonicalize_url(comment.get("url"))
    entity_kind = _identity_entity_kind(source, comment, canonical_url)
    actual_parent_id = str(
        comment.get("parent_content_id") or comment.get("parent_comment_id") or ""
    ).strip()
    url_is_direct = bool(
        canonical_url
        and (not actual_parent_id or is_comment_level_url(source, canonical_url))
    )
    aliases: List[Tuple[str, str, str]] = []

    def add(kind: str, material: str, value: str) -> None:
        key = hashlib.sha256(material.encode("utf-8")).hexdigest()
        if not any(existing[0] == key for existing in aliases):
            aliases.append((key, kind, value))

    derived_id = ""
    if not content_id and url_is_direct:
        derived_id = _native_content_id_from_url(
            source,
            canonical_url,
            prefer_comment=entity_kind == "message",
        )
    stable_id = content_id or derived_id
    if stable_id:
        add(
            "content_id",
            "id\0%s\0%s\0%s" % (source, entity_kind, stable_id),
            "%s:%s:%s" % (source, entity_kind, stable_id),
        )

    parent_id = str(
        comment.get("parent_content_id")
        or comment.get("parent_comment_id")
        or comment.get("thread_id")
        or ""
    ).strip()
    if canonical_url:
        try:
            parsed = urllib_parse.urlsplit(canonical_url)
            public_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except ValueError:
            public_url = False
        if public_url and url_is_direct:
            add(
                "canonical_url",
                "url\0%s\0%s" % (source, canonical_url),
                canonical_url,
            )

    author_id = str(comment.get("author_id") or "").strip()
    author_label = str(comment.get("author_label") or comment.get("author_display_name") or "").strip()
    author_hash = str(comment.get("author_hash") or _author_hash(source, author_id, author_label) or "")
    published_at = str(comment.get("published_at") or "").strip()
    exact_text = _normalize_exact_text(comment.get("text"))
    if not aliases and parent_id and (author_hash or author_label) and published_at and exact_text:
        material = "fallback\0%s\0%s\0%s\0%s\0%s" % (
            source,
            parent_id,
            author_hash or author_label,
            published_at,
            exact_text,
        )
        add("fallback_composite", material, material)

    if not aliases:
        opaque = str(comment.get("_opaque_identity") or uuid.uuid4().hex)
        add("opaque", "opaque\0%s\0%s" % (source, opaque), opaque)
    return aliases


def hard_dedupe_key(comment: Mapping[str, Any]) -> str:
    """Build the primary hard identity; text similarity never participates."""
    aliases = _identity_alias_candidates(comment)
    if not aliases:
        raise CollectorError("无法生成硬身份")
    return aliases[0][0]


def has_complete_hard_identity(comment: Mapping[str, Any]) -> bool:
    source = normalize_platform(comment.get("source") or comment.get("platform"))
    if str(comment.get("content_id") or comment.get("comment_id") or "").strip():
        return True
    url = canonicalize_url(comment.get("url"))
    if is_comment_level_url(source, url):
        return True
    parent_id = str(
        comment.get("parent_content_id")
        or comment.get("parent_comment_id")
        or comment.get("thread_id")
        or ""
    ).strip()
    author_id = str(comment.get("author_id") or "").strip()
    author_label = str(comment.get("author_label") or comment.get("author_display_name") or "").strip()
    published_at = str(comment.get("published_at") or "").strip()
    exact_text = _normalize_exact_text(comment.get("text"))
    return bool(parent_id and (author_id or author_label or comment.get("author_hash")) and published_at and exact_text)


def _choose_richer_text(existing: Any, incoming: Any) -> str:
    old = _normalize_exact_text(existing)
    new = _normalize_exact_text(incoming)
    if not old:
        return new
    if not new:
        return old
    return new if len(new) > len(old) else old


def _choose_source_timestamp(existing: Any, incoming: Any) -> Optional[str]:
    old = parse_timestamp(existing)
    new = parse_timestamp(incoming)
    if old is None:
        return iso_utc(new) if new else None
    if new is None:
        return iso_utc(old)
    return iso_utc(max(old, new))


def _url_quality(source: str, value: str, parent_content_id: Optional[str]) -> Tuple[int, int]:
    if not value:
        return (0, 0)
    try:
        parsed = urllib_parse.urlsplit(value)
    except ValueError:
        return (0, 0)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return (0, 0)
    direct = not parent_content_id or is_comment_level_url(source, value)
    if not direct:
        return (1, -len(value))
    return (3 if is_comment_level_url(source, value) else 2, -len(value))


def _raw_provenance_document(
    existing_raw: Any,
    incoming: Mapping[str, Any],
    *,
    source: str,
    batch_id: str,
    query_id: str,
    scope: str,
    captured_at: str,
    existing_captured_at: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        loaded = json.loads(str(existing_raw or "{}")) if not isinstance(existing_raw, Mapping) else dict(existing_raw)
    except json.JSONDecodeError:
        loaded = {}
    base = dict(loaded) if isinstance(loaded, Mapping) else {}
    provenance = base.pop("_raw_provenance", [])
    if not isinstance(provenance, list):
        provenance = []
    if base and not provenance:
        provenance.append(
            {
                "source": source,
                "batch_id": None,
                "query_id": None,
                "scope": None,
                "captured_at": existing_captured_at or captured_at,
                "payload": base,
            }
        )
    redacted_incoming = redact_value(dict(incoming))
    if not isinstance(redacted_incoming, Mapping):
        redacted_incoming = {}
    incoming_payload = dict(redacted_incoming)
    incoming_payload.pop("_raw_provenance", None)
    entry = {
        "source": source,
        "batch_id": batch_id or None,
        "query_id": query_id or None,
        "scope": scope,
        "captured_at": captured_at,
        "payload": incoming_payload,
    }
    fingerprint = compact_json({key: entry[key] for key in ("source", "batch_id", "query_id", "scope", "payload")})
    existing_fingerprints = {
        compact_json({key: child.get(key) for key in ("source", "batch_id", "query_id", "scope", "payload")})
        for child in provenance
        if isinstance(child, Mapping)
    }
    if fingerprint not in existing_fingerprints:
        provenance.append(entry)

    merged = dict(base)
    for key, value in incoming_payload.items():
        if key == "engagement" and isinstance(value, Mapping):
            current = merged.get(key) if isinstance(merged.get(key), Mapping) else {}
            combined = dict(current)
            for metric, metric_value in value.items():
                previous = combined.get(metric)
                if isinstance(metric_value, (int, float)) and isinstance(previous, (int, float)):
                    combined[metric] = max(previous, metric_value)
                elif previous in (None, "", [], {}):
                    combined[metric] = metric_value
            merged[key] = combined
        elif merged.get(key) in (None, "", [], {}):
            merged[key] = value
    merged["_raw_provenance"] = provenance
    return merged


def scope_window_days(scope: str) -> int:
    if scope == "category_30d":
        return 30
    if scope in SCOPES:
        return 90
    raise ConfigurationError("未知 collection scope：%s" % scope)


class CollectorStore:
    """SQLite persistence for tasks, queues, comments, checkpoints and quota."""

    def __init__(self, path: Path):
        self.path = Path(path)
        _secure_directory(self.path.parent)
        self.connection = sqlite3.connect(str(self.path), timeout=30.0)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.init_schema()
        self._secure_sqlite_files()

    def _secure_sqlite_files(self) -> None:
        if os.name == "nt":
            return
        for suffix in ("", "-wal", "-shm", "-journal"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                os.chmod(candidate, 0o600)

    def close(self) -> None:
        self.connection.close()
        self._secure_sqlite_files()

    def __enter__(self) -> "CollectorStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def init_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_name TEXT NOT NULL,
                topic TEXT NOT NULL,
                research_level TEXT NOT NULL,
                research_plan_json TEXT NOT NULL,
                collection_policy_json TEXT NOT NULL DEFAULT '{}',
                end_at TEXT NOT NULL,
                status TEXT NOT NULL,
                stop_reason TEXT,
                collection_stop_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                collection_elapsed_seconds REAL NOT NULL DEFAULT 0,
                total_elapsed_seconds REAL NOT NULL DEFAULT 0,
                run_count INTEGER NOT NULL DEFAULT 0,
                daily_quota_units INTEGER NOT NULL,
                project_dir TEXT,
                run_dir TEXT,
                last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                backend TEXT NOT NULL,
                scope TEXT NOT NULL,
                query_id TEXT NOT NULL,
                query_text TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                video_url TEXT,
                priority INTEGER NOT NULL DEFAULT 100,
                status TEXT NOT NULL,
                raw_candidate_count INTEGER NOT NULL DEFAULT 0,
                new_valid_count INTEGER NOT NULL DEFAULT 0,
                duplicate_count INTEGER NOT NULL DEFAULT 0,
                page_count INTEGER NOT NULL DEFAULT 0,
                request_count INTEGER NOT NULL DEFAULT 0,
                quota_units INTEGER NOT NULL DEFAULT 0,
                estimated_cost_usd REAL,
                started_at TEXT,
                finished_at TEXT,
                error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_batches_task_status
                ON batches(task_id, status, priority, created_at);
            CREATE TABLE IF NOT EXISTS comments (
                record_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                content_id TEXT,
                hard_key TEXT NOT NULL,
                parent_content_id TEXT,
                thread_id TEXT,
                video_id TEXT,
                author_id TEXT,
                author_label TEXT,
                author_hash TEXT,
                text TEXT NOT NULL,
                published_at TEXT,
                updated_at_source TEXT,
                canonical_url TEXT,
                within_window INTEGER NOT NULL DEFAULT 0,
                is_relevant INTEGER NOT NULL DEFAULT 1,
                is_consumer INTEGER NOT NULL DEFAULT 1,
                technical_eligible INTEGER NOT NULL DEFAULT 0,
                eligible_for_quantitation INTEGER NOT NULL DEFAULT 0,
                exclusion_reason TEXT,
                raw_json TEXT NOT NULL DEFAULT '{}',
                coding_status TEXT NOT NULL DEFAULT 'uncoded',
                coding_json TEXT,
                coding_batch_id TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                UNIQUE(task_id, hard_key)
            );
            CREATE INDEX IF NOT EXISTS idx_comments_task_eligible
                ON comments(task_id, eligible_for_quantitation);
            CREATE TABLE IF NOT EXISTS comment_identity_aliases (
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                alias_key TEXT NOT NULL,
                record_id TEXT NOT NULL REFERENCES comments(record_id) ON DELETE CASCADE,
                alias_kind TEXT NOT NULL,
                alias_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(task_id, alias_key)
            );
            CREATE INDEX IF NOT EXISTS idx_identity_aliases_record
                ON comment_identity_aliases(record_id);
            CREATE TABLE IF NOT EXISTS comment_discoveries (
                discovery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                record_id TEXT NOT NULL REFERENCES comments(record_id) ON DELETE CASCADE,
                batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
                scope TEXT NOT NULL,
                query_id TEXT NOT NULL,
                source TEXT NOT NULL,
                within_window INTEGER NOT NULL,
                discovered_at TEXT NOT NULL,
                UNIQUE(record_id, batch_id, scope, query_id)
            );
            CREATE INDEX IF NOT EXISTS idx_discoveries_task_scope
                ON comment_discoveries(task_id, scope, source);
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE CASCADE,
                checkpoint_key TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_id, batch_id, checkpoint_key)
            );
            CREATE TABLE IF NOT EXISTS quota_ledger (
                ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                batch_id TEXT REFERENCES batches(batch_id) ON DELETE SET NULL,
                source TEXT NOT NULL,
                operation TEXT NOT NULL,
                units INTEGER NOT NULL,
                unit_name TEXT NOT NULL,
                estimated_cost_usd REAL,
                actual_cost_usd REAL,
                cost_status TEXT NOT NULL DEFAULT 'unknown',
                currency TEXT,
                price_snapshot_at TEXT,
                pricing_basis TEXT,
                occurred_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_quota_task_time
                ON quota_ledger(task_id, occurred_at);
            CREATE TABLE IF NOT EXISTS timing_sessions (
                phase_run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                workflow_session_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                meter_scope TEXT NOT NULL,
                finalization_allowed INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                boot_id TEXT NOT NULL,
                anchor_monotonic_ns INTEGER NOT NULL,
                committed_seconds REAL NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                last_heartbeat_at TEXT NOT NULL,
                finished_at TEXT,
                close_reason TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_timing_one_running_phase
                ON timing_sessions(task_id) WHERE status='running';
            CREATE INDEX IF NOT EXISTS idx_timing_task_phase
                ON timing_sessions(task_id,phase,status);
            CREATE TABLE IF NOT EXISTS timing_events (
                event_id TEXT PRIMARY KEY,
                phase_run_id TEXT NOT NULL REFERENCES timing_sessions(phase_run_id) ON DELETE CASCADE,
                delta_seconds REAL NOT NULL,
                committed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS manifest_finalize_intents (
                intent_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                phase_run_id TEXT NOT NULL REFERENCES timing_sessions(phase_run_id) ON DELETE CASCADE,
                event_id TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                requested_status TEXT NOT NULL,
                candidate_sha256 TEXT NOT NULL,
                fallback_sha256 TEXT NOT NULL,
                fallback_manifest_bytes BLOB NOT NULL,
                state TEXT NOT NULL,
                final_status TEXT,
                final_manifest_sha256 TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_id, phase_run_id)
            );
            CREATE INDEX IF NOT EXISTS idx_manifest_intents_task_state
                ON manifest_finalize_intents(task_id,state,created_at);
            """
        )
        self.connection.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )
        self.connection.commit()
        self._ensure_task_columns()
        self._ensure_comment_columns()
        self._ensure_identity_aliases()
        self._ensure_quota_columns()

    def _ensure_task_columns(self) -> None:
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(tasks)").fetchall()}
        for name in ("project_dir", "run_dir", "collection_policy_json", "collection_stop_reason"):
            if name not in columns:
                default = " DEFAULT '{}'" if name == "collection_policy_json" else ""
                self.connection.execute("ALTER TABLE tasks ADD COLUMN %s TEXT%s" % (name, default))
        self.connection.commit()

    def _ensure_comment_columns(self) -> None:
        columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(comments)").fetchall()
        }
        if "technical_eligible" not in columns:
            self.connection.execute(
                "ALTER TABLE comments ADD COLUMN technical_eligible INTEGER NOT NULL DEFAULT 0"
            )
            rows = self.connection.execute("SELECT * FROM comments").fetchall()
            for row in rows:
                source = normalize_platform(row["source"])
                url = canonicalize_url(row["canonical_url"])
                try:
                    parsed = urllib_parse.urlsplit(url)
                    public_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
                except ValueError:
                    public_url = False
                direct = bool(
                    public_url
                    and (
                        not row["parent_content_id"]
                        or is_comment_level_url(source, url)
                    )
                )
                identity = has_complete_hard_identity(
                    {
                        "source": source,
                        "content_id": row["content_id"],
                        "url": url,
                        "parent_content_id": row["parent_content_id"],
                        "thread_id": row["thread_id"],
                        "author_hash": row["author_hash"],
                        "author_label": row["author_label"],
                        "published_at": row["published_at"],
                        "text": row["text"],
                    }
                )
                technical = bool(
                    source in QUANTITATIVE_PLATFORMS
                    and row["within_window"]
                    and str(row["text"] or "").strip()
                    and row["published_at"]
                    and identity
                    and direct
                )
                self.connection.execute(
                    "UPDATE comments SET technical_eligible=? WHERE record_id=?",
                    (int(technical), row["record_id"]),
                )
            self.connection.commit()

    def _ensure_identity_aliases(self) -> None:
        """Backfill all provable identities for resumable databases."""
        rows = self.connection.execute(
            """SELECT record_id,task_id,source,content_id,parent_content_id,thread_id,
            video_id,author_id,author_label,author_hash,text,published_at,canonical_url,
            hard_key,first_seen_at FROM comments ORDER BY first_seen_at,record_id"""
        ).fetchall()
        with self.connection:
            for row in rows:
                payload = dict(row)
                payload["url"] = payload.pop("canonical_url")
                aliases = _identity_alias_candidates(payload)
                aliases.append((str(row["hard_key"]), "legacy_primary", str(row["hard_key"])))
                for alias_key, alias_kind, alias_value in aliases:
                    self.connection.execute(
                        """INSERT OR IGNORE INTO comment_identity_aliases(
                        task_id,alias_key,record_id,alias_kind,alias_value,created_at
                        ) VALUES(?,?,?,?,?,?)""",
                        (
                            row["task_id"],
                            alias_key,
                            row["record_id"],
                            alias_kind,
                            alias_value,
                            row["first_seen_at"],
                        ),
                    )

    def _ensure_quota_columns(self) -> None:
        columns = {
            row[1]: row for row in self.connection.execute("PRAGMA table_info(quota_ledger)").fetchall()
        }
        additions = {
            "actual_cost_usd": "REAL",
            "cost_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "currency": "TEXT",
            "price_snapshot_at": "TEXT",
            "pricing_basis": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in columns:
                self.connection.execute(
                    "ALTER TABLE quota_ledger ADD COLUMN %s %s" % (name, declaration)
                )
        self.connection.commit()
        estimated = columns.get("estimated_cost_usd")
        self._quota_estimated_nullable = not bool(estimated and int(estimated[3]))

    def create_task(
        self,
        task_name: str,
        topic: str,
        research_level: str,
        end_at: str,
        queues: Sequence[Mapping[str, Any]],
        reminders_enabled: bool = True,
        reminder_interval_minutes: int = DEFAULT_REMINDER_INTERVAL_MINUTES,
        daily_quota_units: int = DEFAULT_DAILY_YOUTUBE_QUOTA,
        project_dir: Optional[Path] = None,
        run_dir: Optional[Path] = None,
        task_id: Optional[str] = None,
        research_level_explicit: bool = False,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        plan = research_plan(research_level, reminders_enabled, reminder_interval_minutes)
        policy = collection_policy(
            research_level,
            reminders_enabled,
            reminder_interval_minutes,
            research_level_explicit,
        )
        parsed_end = parse_timestamp(end_at)
        if parsed_end is None:
            raise ConfigurationError("end_at 必须是带时区 ISO 8601")
        if daily_quota_units <= 0:
            raise ConfigurationError("daily_quota_units 必须为正整数")
        if run_dir is not None:
            _secure_directory(run_dir.resolve())
        identifier = task_id or "cvt_%s" % uuid.uuid4().hex[:20]
        timestamp = iso_utc(now)
        with self.connection:
            self.connection.execute(
                """INSERT INTO tasks(
                    task_id, task_name, topic, research_level, research_plan_json,collection_policy_json,
                    end_at, status, created_at, updated_at, daily_quota_units,project_dir,run_dir
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier,
                    task_name or identifier,
                    topic,
                    research_level,
                    compact_json(plan),
                    compact_json(policy),
                    iso_utc(parsed_end),
                    "planned",
                    timestamp,
                    timestamp,
                    int(daily_quota_units),
                    str(project_dir.resolve()) if project_dir else None,
                    str(run_dir.resolve()) if run_dir else None,
                ),
            )
            for position, queue in enumerate(queues):
                self._insert_batch(identifier, queue, position, timestamp)
        return self.task_payload(identifier, include_batches=True)

    def add_batch(self, task_id: str, queue: Mapping[str, Any]) -> Dict[str, Any]:
        self.task_row(task_id)
        timestamp = iso_utc()
        position = int(
            self.connection.execute("SELECT COUNT(*) FROM batches WHERE task_id=?", (task_id,)).fetchone()[0]
        )
        with self.connection:
            self._insert_batch(task_id, queue, position, timestamp)
        batch_id = str(queue.get("batch_id") or "")
        if batch_id:
            row = self.connection.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        else:
            row = self.connection.execute(
                "SELECT * FROM batches WHERE task_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (task_id,)
            ).fetchone()
        if row is None:
            raise CollectorError("批次创建失败")
        return self.batch_payload(row)

    def _insert_batch(self, task_id: str, queue: Mapping[str, Any], position: int, timestamp: str) -> None:
        source = normalize_platform(queue.get("source") or queue.get("platform") or "youtube")
        scope = str(queue.get("scope") or "category_30d").strip()
        if scope not in SCOPES:
            raise ConfigurationError("queue scope 无效：%s" % scope)
        backend = str(queue.get("backend") or "auto").strip().lower()
        if backend not in {"auto", "youtube-data-api", "yt-dlp", "external", "last30days", "agent-reach"}:
            raise ConfigurationError("queue backend 无效：%s" % backend)
        batch_id = str(queue.get("batch_id") or "cvb_%s" % uuid.uuid4().hex[:20])
        query_id = str(queue.get("query_id") or "%s_q%04d" % (scope, position + 1))
        metadata = queue.get("metadata") if isinstance(queue.get("metadata"), Mapping) else {}
        self.connection.execute(
            """INSERT INTO batches(
                batch_id, task_id, source, backend, scope, query_id, query_text,
                video_id, video_url, priority, status, metadata_json, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                batch_id,
                task_id,
                source,
                backend,
                scope,
                query_id,
                str(queue.get("query_text") or queue.get("query") or ""),
                str(queue.get("video_id") or "") or None,
                str(queue.get("video_url") or queue.get("url") or "") or None,
                int(queue.get("priority", 100 + position)),
                "planned",
                compact_json(metadata),
                timestamp,
                timestamp,
            ),
        )

    def task_row(self, task_id: str) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise CollectorError("任务不存在：%s" % task_id)
        return row

    def resolve_task_id(self, task_id: Optional[str]) -> str:
        if task_id:
            self.task_row(task_id)
            return task_id
        rows = self.connection.execute("SELECT task_id FROM tasks ORDER BY created_at DESC LIMIT 2").fetchall()
        if not rows:
            raise CollectorError("数据库中没有任务")
        if len(rows) > 1:
            raise CollectorError("数据库包含多个任务，请显式传 --task-id")
        return str(rows[0]["task_id"])

    def task_payload(self, task_id: str, include_batches: bool = False) -> Dict[str, Any]:
        row = self.task_row(task_id)
        payload = dict(row)
        payload["research_plan"] = json.loads(str(payload.pop("research_plan_json")))
        payload["collection_policy"] = json.loads(str(payload.pop("collection_policy_json") or "{}"))
        if include_batches:
            payload["queues"] = [self.batch_payload(child) for child in self.list_batches(task_id)]
        return payload

    @staticmethod
    def batch_payload(row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["metadata"] = json.loads(str(result.pop("metadata_json") or "{}"))
        result.pop("estimated_cost_usd", None)
        raw = int(result.get("raw_candidate_count") or 0)
        new = int(result.get("new_valid_count") or 0)
        result["increment_rate"] = (new / raw) if raw else 0.0
        return result

    def list_batches(self, task_id: str, statuses: Optional[Sequence[str]] = None) -> List[sqlite3.Row]:
        parameters: List[Any] = [task_id]
        condition = "task_id=?"
        if statuses:
            condition += " AND status IN (%s)" % ",".join("?" for _ in statuses)
            parameters.extend(statuses)
        return list(
            self.connection.execute(
                "SELECT * FROM batches WHERE %s ORDER BY priority, created_at, batch_id" % condition,
                tuple(parameters),
            ).fetchall()
        )

    def update_task(self, task_id: str, **changes: Any) -> None:
        allowed = {
            "status",
            "stop_reason",
            "collection_stop_reason",
            "updated_at",
            "started_at",
            "finished_at",
            "collection_elapsed_seconds",
            "total_elapsed_seconds",
            "run_count",
            "last_error",
            "research_level",
            "research_plan_json",
            "collection_policy_json",
            "daily_quota_units",
        }
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError("invalid task fields: %s" % sorted(invalid))
        if changes.get("stop_reason") is not None and changes["stop_reason"] not in STOP_REASONS:
            raise ValueError("invalid stop reason")
        if (
            changes.get("collection_stop_reason") is not None
            and changes["collection_stop_reason"] not in STOP_REASONS
        ):
            raise ValueError("invalid collection stop reason")
        if not changes:
            return
        assignments = ",".join("%s=?" % key for key in changes)
        with self.connection:
            self.connection.execute(
                "UPDATE tasks SET %s WHERE task_id=?" % assignments,
                tuple(changes.values()) + (task_id,),
            )

    def upgrade_research_level(self, task_id: str, requested: Optional[str]) -> str:
        row = self.task_row(task_id)
        current = str(row["research_level"])
        if requested is None or requested == current:
            return current
        order = {name: index for index, name in enumerate(("quick", "standard", "deep"))}
        if requested not in order:
            raise ConfigurationError("未知 research level：%s" % requested)
        if order[requested] < order[current]:
            raise ConfigurationError("resume 只允许保持或升级研究档位，禁止从 %s 降到 %s" % (current, requested))
        previous_policy = json.loads(str(row["collection_policy_json"] or "{}"))
        reminder = previous_policy.get("reminder_policy", {})
        upgraded = research_plan(requested)
        upgraded_policy = collection_policy(
            requested,
            bool(reminder.get("enabled", True)),
            int(reminder.get("interval_minutes", DEFAULT_REMINDER_INTERVAL_MINUTES)),
            bool(previous_policy.get("research_level_explicit", False)),
        )
        timestamp = iso_utc()
        rows = self.connection.execute(
            "SELECT rowid AS _rowid,* FROM batches WHERE task_id=? ORDER BY created_at,rowid",
            (task_id,),
        ).fetchall()
        latest_by_root: Dict[str, Dict[str, Any]] = {}
        already_cloned: set[str] = set()
        for batch_row in rows:
            batch = self.batch_payload(batch_row)
            source = str(batch.get("source") or "")
            backend = str(batch.get("backend") or "")
            if source not in {"last30days", "youtube"} and backend not in {
                "last30days",
                "youtube-data-api",
                "yt-dlp",
                "auto",
            }:
                continue
            metadata = batch.get("metadata") if isinstance(batch.get("metadata"), Mapping) else {}
            # A yt-dlp fallback is a child of its official YouTube batch, not
            # an independent acquisition chain.  Cloning both on upgrade would
            # duplicate the same video and create a second fallback lineage.
            if metadata.get("fallback_for_batch_id"):
                continue
            root_batch_id = str(metadata.get("upgrade_root_batch_id") or batch["batch_id"])
            latest_by_root[root_batch_id] = batch
            if str(metadata.get("upgrade_target_level") or "") == requested:
                already_cloned.add(root_batch_id)

        clones: List[Dict[str, Any]] = []
        for root_batch_id, batch in latest_by_root.items():
            if root_batch_id in already_cloned or str(batch.get("status")) != "completed":
                continue
            source = str(batch.get("source") or "")
            metadata = dict(batch.get("metadata") or {})
            root_query_id = str(metadata.get("upgrade_root_query_id") or batch["query_id"])
            clone_backend = "last30days" if source == "last30days" else (
                "auto" if batch.get("video_id") else "yt-dlp"
            )
            metadata.update(
                {
                    "upgrade_root_batch_id": root_batch_id,
                    "upgrade_root_query_id": root_query_id,
                    "upgraded_from_batch_id": str(batch["batch_id"]),
                    "upgrade_from_level": current,
                    "upgrade_target_level": requested,
                }
            )
            clones.append(
                {
                    "source": source,
                    "backend": clone_backend,
                    "scope": batch["scope"],
                    "query_id": "%s__upgrade_%s" % (root_query_id, requested),
                    "query_text": batch.get("query_text") or "",
                    "video_id": batch.get("video_id"),
                    "video_url": batch.get("video_url"),
                    "priority": int(batch.get("priority") or 100) + 1000,
                    "metadata": metadata,
                }
            )

        with self.connection:
            self.connection.execute(
                """UPDATE tasks SET research_level=?,research_plan_json=?,collection_policy_json=?,
                status='planned',stop_reason=NULL,collection_stop_reason=NULL,
                finished_at=NULL,last_error=NULL,updated_at=?
                WHERE task_id=?""",
                (
                    requested,
                    compact_json(upgraded),
                    compact_json(upgraded_policy),
                    timestamp,
                    task_id,
                ),
            )
            start_position = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM batches WHERE task_id=?", (task_id,)
                ).fetchone()[0]
            )
            for offset, clone in enumerate(clones):
                self._insert_batch(task_id, clone, start_position + offset, timestamp)
        return requested

    def timing_usage(
        self,
        task_id: str,
        *,
        include_running: bool = True,
        boot_id: Optional[str] = None,
        monotonic_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        task = self.task_row(task_id)
        active_boot = boot_id or current_boot_id()
        active_monotonic = int(monotonic_ns if monotonic_ns is not None else time.monotonic_ns())
        external_total = 0.0
        external_collection = 0.0
        unmetered = 0.0
        sessions: List[Dict[str, Any]] = []
        rows = self.connection.execute(
            "SELECT * FROM timing_sessions WHERE task_id=? ORDER BY started_at,phase_run_id",
            (task_id,),
        ).fetchall()
        for row in rows:
            seconds = max(0.0, float(row["committed_seconds"] or 0))
            running_interval = 0.0
            if (
                include_running
                and str(row["status"]) == "running"
                and str(row["boot_id"]) == active_boot
            ):
                running_interval = max(
                    0.0,
                    (active_monotonic - int(row["anchor_monotonic_ns"])) / 1_000_000_000,
                )
                seconds += running_interval
            meter_scope = str(row["meter_scope"])
            if meter_scope == "collection_and_total":
                external_collection += seconds
                external_total += seconds
            elif meter_scope == "total_only":
                external_total += seconds
            else:
                unmetered += seconds
            sessions.append(
                {
                    "phase_run_id": str(row["phase_run_id"]),
                    "workflow_session_id": str(row["workflow_session_id"]),
                    "phase": str(row["phase"]),
                    "meter_scope": meter_scope,
                    "finalization_allowed": bool(row["finalization_allowed"]),
                    "status": str(row["status"]),
                    "committed_seconds": round(float(row["committed_seconds"] or 0), 6),
                    "running_uncommitted_seconds": round(running_interval, 6),
                    "started_at": row["started_at"],
                    "last_heartbeat_at": row["last_heartbeat_at"],
                    "finished_at": row["finished_at"],
                    "close_reason": row["close_reason"],
                }
            )
        internal_collection = max(0.0, float(task["collection_elapsed_seconds"] or 0))
        internal_total = max(0.0, float(task["total_elapsed_seconds"] or 0))
        return {
            "internal_collection_seconds": internal_collection,
            "internal_total_seconds": internal_total,
            "external_collection_seconds": external_collection,
            "external_total_seconds": external_total,
            "unmetered_seconds": unmetered,
            "effective_collection_seconds": internal_collection + external_collection,
            "effective_total_seconds": internal_total + external_total,
            "sessions": sessions,
        }

    def timing_gate(
        self,
        task_id: str,
        next_phase: Optional[str] = None,
        *,
        boot_id: Optional[str] = None,
        monotonic_ns: Optional[int] = None,
    ) -> Dict[str, Any]:
        if next_phase is not None and next_phase not in TIMED_PHASES:
            raise ConfigurationError("未知计时阶段：%s" % next_phase)
        task = self.task_payload(task_id)
        usage = self.timing_usage(
            task_id,
            include_running=True,
            boot_id=boot_id,
            monotonic_ns=monotonic_ns,
        )
        budget = task["research_plan"]["time_budget_minutes"]
        total_budget = float(budget["total"]) * 60
        collection_budget = float(budget["collection"]) * 60
        total_remaining = total_budget - float(usage["effective_total_seconds"])
        collection_remaining = collection_budget - float(usage["effective_collection_seconds"])
        expansion_remaining = total_remaining - FINALIZATION_RESERVE_SECONDS
        spec = TIMED_PHASES.get(next_phase or "", {})
        meter_scope = str(spec.get("meter_scope") or "")
        finalization_allowed = bool(spec.get("finalization_allowed"))
        if meter_scope == "unmetered":
            allowed = True
            action = "unmetered_setup"
            max_step_seconds: Optional[float] = None
        elif finalization_allowed:
            allowed = total_remaining > 0
            action = "finalize" if allowed else "deadline_exceeded"
            max_step_seconds = max(0.0, total_remaining)
        elif expansion_remaining <= 0:
            allowed = False
            action = "finalize_now"
            max_step_seconds = 0.0
        elif meter_scope == "collection_and_total" and collection_remaining <= 0:
            allowed = False
            action = "stop_collection"
            max_step_seconds = 0.0
        else:
            allowed = True
            action = "continue"
            if meter_scope == "collection_and_total":
                max_step_seconds = max(
                    0.0, min(expansion_remaining, collection_remaining)
                )
            else:
                max_step_seconds = max(0.0, expansion_remaining)
        return {
            "next_phase": next_phase,
            "allowed": allowed,
            "action": action,
            "finalization_reserve_seconds": FINALIZATION_RESERVE_SECONDS,
            "collection_budget_seconds": collection_budget,
            "total_budget_seconds": total_budget,
            "collection_used_seconds": round(float(usage["effective_collection_seconds"]), 6),
            "total_used_seconds": round(float(usage["effective_total_seconds"]), 6),
            "collection_remaining_seconds": round(collection_remaining, 6),
            "total_remaining_seconds": round(total_remaining, 6),
            "expansion_remaining_seconds": round(expansion_remaining, 6),
            "max_step_seconds": (
                round(max_step_seconds, 6) if max_step_seconds is not None else None
            ),
            "deadline_exceeded": total_remaining <= 0,
            "finalization_only": expansion_remaining <= 0,
        }

    def abandon_open_timing_sessions(
        self,
        task_id: str,
        *,
        reason: str = "resume_recovery",
        now: Optional[datetime] = None,
    ) -> int:
        timestamp = iso_utc(now)
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE timing_sessions SET status='abandoned',finished_at=?,close_reason=?
                WHERE task_id=? AND status='running'""",
                (timestamp, reason, task_id),
            )
        return int(cursor.rowcount or 0)

    def begin_timing_phase(
        self,
        task_id: str,
        phase: str,
        workflow_session_id: str,
        *,
        phase_run_id: Optional[str] = None,
        boot_id: Optional[str] = None,
        monotonic_ns: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if phase not in TIMED_PHASES:
            raise ConfigurationError("未知计时阶段：%s" % phase)
        workflow_id = str(workflow_session_id or "").strip()
        if not workflow_id:
            raise ConfigurationError("phase-start 必须提供 workflow_session_id")
        active_boot = boot_id or current_boot_id()
        active_monotonic = int(monotonic_ns if monotonic_ns is not None else time.monotonic_ns())
        timestamp = iso_utc(now)
        open_row = self.connection.execute(
            "SELECT * FROM timing_sessions WHERE task_id=? AND status='running'",
            (task_id,),
        ).fetchone()
        if open_row is not None and str(open_row["boot_id"]) != active_boot:
            self.abandon_open_timing_sessions(task_id, reason="boot_changed", now=now)
            open_row = None
        if open_row is not None:
            if (
                str(open_row["phase"]) == phase
                and str(open_row["workflow_session_id"]) == workflow_id
            ):
                return {
                    "phase_run_id": str(open_row["phase_run_id"]),
                    "phase": phase,
                    "status": "running",
                    "replayed": True,
                }
            raise ConfigurationError("同一任务已有运行中的计时阶段：%s" % open_row["phase"])
        gate = self.timing_gate(
            task_id,
            phase,
            boot_id=active_boot,
            monotonic_ns=active_monotonic,
        )
        if not gate["allowed"]:
            raise ConfigurationError("阶段门禁要求停止扩展并立即收尾：%s" % gate["action"])
        spec = TIMED_PHASES[phase]
        identifier = phase_run_id or "phase_%s" % uuid.uuid4().hex[:24]
        with self.connection:
            self.connection.execute(
                """INSERT INTO timing_sessions(
                phase_run_id,task_id,workflow_session_id,phase,meter_scope,
                finalization_allowed,status,boot_id,anchor_monotonic_ns,
                committed_seconds,started_at,last_heartbeat_at
                ) VALUES(?,?,?,?,?,?,'running',?,?,0,?,?)""",
                (
                    identifier,
                    task_id,
                    workflow_id,
                    phase,
                    spec["meter_scope"],
                    int(bool(spec["finalization_allowed"])),
                    active_boot,
                    active_monotonic,
                    timestamp,
                    timestamp,
                ),
            )
        return {
            "phase_run_id": identifier,
            "phase": phase,
            "status": "running",
            "replayed": False,
            "gate": gate,
        }

    def _commit_timing_phase(
        self,
        task_id: str,
        phase_run_id: str,
        event_id: str,
        *,
        finish: bool,
        boot_id: Optional[str] = None,
        monotonic_ns: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        identifier = str(event_id or "").strip()
        if not identifier:
            raise ConfigurationError("heartbeat/end 必须提供 event_id")
        existing_event = self.connection.execute(
            "SELECT * FROM timing_events WHERE event_id=?", (identifier,)
        ).fetchone()
        if existing_event is not None:
            if str(existing_event["phase_run_id"]) != phase_run_id:
                raise ConfigurationError("event_id 已用于另一计时阶段")
            owner = self.connection.execute(
                "SELECT task_id FROM timing_sessions WHERE phase_run_id=?", (phase_run_id,)
            ).fetchone()
            if owner is None or str(owner["task_id"]) != task_id:
                raise ConfigurationError("event_id 不属于当前任务")
            return {
                "phase_run_id": str(existing_event["phase_run_id"]),
                "event_id": identifier,
                "delta_seconds": float(existing_event["delta_seconds"]),
                "replayed": True,
            }
        row = self.connection.execute(
            "SELECT * FROM timing_sessions WHERE task_id=? AND phase_run_id=?",
            (task_id, phase_run_id),
        ).fetchone()
        if row is None:
            raise ConfigurationError("计时阶段不存在：%s" % phase_run_id)
        if str(row["status"]) != "running":
            raise ConfigurationError("计时阶段已关闭：%s" % phase_run_id)
        active_boot = boot_id or current_boot_id()
        if str(row["boot_id"]) != active_boot:
            self.abandon_open_timing_sessions(task_id, reason="boot_changed", now=now)
            raise ConfigurationError("系统已重启；未提交区间已放弃，请 resume 后重新开始阶段")
        active_monotonic = int(monotonic_ns if monotonic_ns is not None else time.monotonic_ns())
        delta = max(
            0.0,
            (active_monotonic - int(row["anchor_monotonic_ns"])) / 1_000_000_000,
        )
        timestamp = iso_utc(now)
        with self.connection:
            self.connection.execute(
                "INSERT INTO timing_events(event_id,phase_run_id,delta_seconds,committed_at) VALUES(?,?,?,?)",
                (identifier, phase_run_id, delta, timestamp),
            )
            self.connection.execute(
                """UPDATE timing_sessions SET committed_seconds=committed_seconds+?,
                anchor_monotonic_ns=?,last_heartbeat_at=?,status=?,finished_at=?,close_reason=?
                WHERE phase_run_id=?""",
                (
                    delta,
                    active_monotonic,
                    timestamp,
                    "completed" if finish else "running",
                    timestamp if finish else None,
                    "completed" if finish else None,
                    phase_run_id,
                ),
            )
        gate = self.timing_gate(
            task_id,
            str(row["phase"]),
            boot_id=active_boot,
            monotonic_ns=active_monotonic,
        )
        task = self.task_row(task_id)
        task_updates: Dict[str, Any] = {}
        if gate["deadline_exceeded"] or gate["action"] == "finalize_now":
            collection_reason = task["collection_stop_reason"] or (
                task["stop_reason"] if task["stop_reason"] != "total_deadline" else None
            )
            task_updates.update(
                stop_reason="total_deadline",
                collection_stop_reason=collection_reason,
            )
        elif gate["action"] == "stop_collection":
            task_updates["collection_stop_reason"] = "collection_deadline"
            if task["stop_reason"] != "total_deadline":
                task_updates["stop_reason"] = "collection_deadline"
        if task_updates:
            task_updates["updated_at"] = timestamp
            self.update_task(task_id, **task_updates)
        return {
            "phase_run_id": phase_run_id,
            "event_id": identifier,
            "delta_seconds": round(delta, 6),
            "status": "completed" if finish else "running",
            "replayed": False,
            "gate": gate,
        }

    def heartbeat_timing_phase(
        self,
        task_id: str,
        phase_run_id: str,
        event_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self._commit_timing_phase(
            task_id, phase_run_id, event_id, finish=False, **kwargs
        )

    def end_timing_phase(
        self,
        task_id: str,
        phase_run_id: str,
        event_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self._commit_timing_phase(
            task_id, phase_run_id, event_id, finish=True, **kwargs
        )

    def abandon_timing_phase(
        self,
        task_id: str,
        phase_run_id: str,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        timestamp = iso_utc(now)
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE timing_sessions SET status='abandoned',finished_at=?,close_reason='explicit_abandon'
                WHERE task_id=? AND phase_run_id=? AND status='running'""",
                (timestamp, task_id, phase_run_id),
            )
        if not cursor.rowcount:
            raise ConfigurationError("没有可放弃的运行中阶段：%s" % phase_run_id)
        return {"phase_run_id": phase_run_id, "status": "abandoned"}

    @staticmethod
    def _manifest_intent_payload(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "intent_id": str(row["intent_id"]),
            "task_id": str(row["task_id"]),
            "phase_run_id": str(row["phase_run_id"]),
            "event_id": str(row["event_id"]),
            "manifest_path": str(row["manifest_path"]),
            "requested_status": str(row["requested_status"]),
            "candidate_sha256": str(row["candidate_sha256"]),
            "fallback_sha256": str(row["fallback_sha256"]),
            "state": str(row["state"]),
            "final_status": row["final_status"],
            "final_manifest_sha256": row["final_manifest_sha256"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def manifest_finalize_intent(
        self, task_id: str, phase_run_id: str
    ) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            "SELECT * FROM manifest_finalize_intents WHERE task_id=? AND phase_run_id=?",
            (task_id, phase_run_id),
        ).fetchone()
        return self._manifest_intent_payload(row) if row is not None else None

    def create_manifest_finalize_intent(
        self,
        task_id: str,
        phase_run_id: str,
        event_id: str,
        manifest_path: Path,
        requested_status: str,
        candidate_sha256: str,
        fallback_manifest_bytes: bytes,
        *,
        intent_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if requested_status not in {"ready", "partial", "failed"}:
            raise ConfigurationError("manifest intent 状态无效：%s" % requested_status)
        identifier = str(event_id or "").strip()
        if not identifier:
            raise ConfigurationError("manifest intent 必须提供 event_id")
        candidate_hash = str(candidate_sha256 or "").strip().casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", candidate_hash):
            raise ConfigurationError("manifest candidate SHA-256 无效")
        fallback_bytes = bytes(fallback_manifest_bytes)
        fallback_hash = hashlib.sha256(fallback_bytes).hexdigest()
        resolved_manifest = Path(manifest_path).expanduser().resolve()
        phase = self.connection.execute(
            "SELECT * FROM timing_sessions WHERE task_id=? AND phase_run_id=?",
            (task_id, phase_run_id),
        ).fetchone()
        if phase is None or str(phase["phase"]) != "manifest_finalize":
            raise ConfigurationError("manifest intent 必须绑定 manifest_finalize 阶段")
        if str(phase["status"]) != "running":
            raise ConfigurationError("manifest_finalize 阶段已经关闭")
        existing = self.connection.execute(
            "SELECT * FROM manifest_finalize_intents WHERE task_id=? AND phase_run_id=?",
            (task_id, phase_run_id),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["event_id"]) != identifier
                or str(existing["manifest_path"]) != str(resolved_manifest)
                or str(existing["requested_status"]) != requested_status
                or str(existing["candidate_sha256"]) != candidate_hash
            ):
                raise ConfigurationError("manifest finalize intent 与既有幂等记录不一致")
            result = self._manifest_intent_payload(existing)
            result["replayed"] = True
            return result
        timestamp = iso_utc(now)
        intent_identifier = intent_id or "manifest_intent_%s" % uuid.uuid4().hex[:24]
        with self.connection:
            self.connection.execute(
                """INSERT INTO manifest_finalize_intents(
                intent_id,task_id,phase_run_id,event_id,manifest_path,requested_status,
                candidate_sha256,fallback_sha256,fallback_manifest_bytes,state,
                created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,'preparing',?,?)""",
                (
                    intent_identifier,
                    task_id,
                    phase_run_id,
                    identifier,
                    str(resolved_manifest),
                    requested_status,
                    candidate_hash,
                    fallback_hash,
                    sqlite3.Binary(fallback_bytes),
                    timestamp,
                    timestamp,
                ),
            )
        result = self.manifest_finalize_intent(task_id, phase_run_id)
        assert result is not None
        result["replayed"] = False
        return result

    def mark_manifest_finalize_intent_written(
        self,
        task_id: str,
        intent_id: str,
        *,
        now: Optional[datetime] = None,
    ) -> None:
        timestamp = iso_utc(now)
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE manifest_finalize_intents SET state='manifest_written',updated_at=?
                WHERE task_id=? AND intent_id=? AND state='preparing'""",
                (timestamp, task_id, intent_id),
            )
        if not cursor.rowcount:
            row = self.connection.execute(
                "SELECT state FROM manifest_finalize_intents WHERE task_id=? AND intent_id=?",
                (task_id, intent_id),
            ).fetchone()
            if row is None or str(row["state"]) != "manifest_written":
                raise ConfigurationError("manifest intent 无法进入 manifest_written")

    def complete_manifest_finalize_intent(
        self,
        task_id: str,
        intent_id: str,
        final_status: str,
        final_manifest_sha256: str,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        if final_status not in {"ready", "partial", "failed"}:
            raise ConfigurationError("manifest 最终状态无效：%s" % final_status)
        final_hash = str(final_manifest_sha256 or "").strip().casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", final_hash):
            raise ConfigurationError("manifest 最终 SHA-256 无效")
        row = self.connection.execute(
            "SELECT * FROM manifest_finalize_intents WHERE task_id=? AND intent_id=?",
            (task_id, intent_id),
        ).fetchone()
        if row is None:
            raise ConfigurationError("manifest intent 不存在：%s" % intent_id)
        if str(row["state"]) == "committed":
            if row["final_status"] != final_status or row["final_manifest_sha256"] != final_hash:
                raise ConfigurationError("manifest intent 已以另一结果提交")
            result = self._manifest_intent_payload(row)
            result["replayed"] = True
            return result
        if str(row["state"]) != "manifest_written":
            raise ConfigurationError("manifest intent 尚未完成候选写入")
        phase = self.connection.execute(
            "SELECT status FROM timing_sessions WHERE task_id=? AND phase_run_id=?",
            (task_id, row["phase_run_id"]),
        ).fetchone()
        event = self.connection.execute(
            "SELECT phase_run_id FROM timing_events WHERE event_id=?",
            (row["event_id"],),
        ).fetchone()
        if (
            phase is None
            or str(phase["status"]) != "completed"
            or event is None
            or str(event["phase_run_id"]) != str(row["phase_run_id"])
        ):
            raise ConfigurationError("manifest intent 必须在计时阶段成功结束后提交")
        if self.timing_gate(task_id, "manifest_finalize")["deadline_exceeded"]:
            raise ConfigurationError("manifest_finalize 已超过总时间上限，禁止提交候选manifest")
        manifest_path = Path(str(row["manifest_path"]))
        if not manifest_path.is_file() or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != final_hash:
            raise ConfigurationError("manifest 最终文件与提交 SHA-256 不一致")
        timestamp = iso_utc(now)
        with self.connection:
            self.connection.execute(
                """UPDATE manifest_finalize_intents SET state='committed',final_status=?,
                final_manifest_sha256=?,updated_at=?,error=NULL WHERE intent_id=?""",
                (final_status, final_hash, timestamp, intent_id),
            )
            self.connection.execute(
                """UPDATE tasks SET status='completed',finished_at=?,updated_at=?
                WHERE task_id=?""",
                (timestamp, timestamp, task_id),
            )
        result = self.manifest_finalize_intent(task_id, str(row["phase_run_id"]))
        assert result is not None
        result["replayed"] = False
        return result

    def rollback_manifest_finalize_intent(
        self,
        task_id: str,
        intent_id: str,
        error_message: str,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM manifest_finalize_intents WHERE task_id=? AND intent_id=?",
            (task_id, intent_id),
        ).fetchone()
        if row is None:
            raise ConfigurationError("manifest intent 不存在：%s" % intent_id)
        state = str(row["state"])
        if state == "committed":
            raise ConfigurationError("已提交的manifest intent禁止回滚")
        fallback = bytes(row["fallback_manifest_bytes"])
        manifest_path = Path(str(row["manifest_path"]))
        _atomic_write_bytes(manifest_path, fallback)
        fallback_hash = hashlib.sha256(fallback).hexdigest()
        fallback_status: Optional[str] = None
        try:
            fallback_document = json.loads(fallback.decode("utf-8"))
            raw_status = (
                fallback_document.get("status", {}).get("consumer_product_discovery")
                if isinstance(fallback_document, Mapping)
                and isinstance(fallback_document.get("status"), Mapping)
                else None
            )
            if raw_status in {"ready", "partial", "failed"}:
                fallback_status = str(raw_status)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        timestamp = iso_utc(now)
        with self.connection:
            self.connection.execute(
                """UPDATE manifest_finalize_intents SET state='rolled_back',final_status=?,
                final_manifest_sha256=?,error=?,updated_at=? WHERE intent_id=?""",
                (
                    fallback_status,
                    fallback_hash,
                    redact_text(error_message),
                    timestamp,
                    intent_id,
                ),
            )
            self.connection.execute(
                """UPDATE tasks SET status=CASE WHEN status='completed'
                    THEN 'collection_completed' ELSE status END,
                    finished_at=NULL,updated_at=? WHERE task_id=?""",
                (timestamp, task_id),
            )
        result = self.manifest_finalize_intent(task_id, str(row["phase_run_id"]))
        assert result is not None
        result["replayed"] = state == "rolled_back"
        return result

    def recover_manifest_finalize_intents(
        self,
        task_id: str,
        *,
        abandon_running: bool = False,
        reason: str = "recovered_uncommitted_manifest_intent",
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        rows = self.connection.execute(
            """SELECT * FROM manifest_finalize_intents
            WHERE task_id=? AND state IN ('preparing','manifest_written')
            ORDER BY created_at,intent_id""",
            (task_id,),
        ).fetchall()
        recovered: List[Dict[str, Any]] = []
        for row in rows:
            phase = self.connection.execute(
                "SELECT status FROM timing_sessions WHERE phase_run_id=?",
                (row["phase_run_id"],),
            ).fetchone()
            if phase is not None and str(phase["status"]) == "running":
                if not abandon_running:
                    continue
                self.abandon_open_timing_sessions(task_id, reason=reason, now=now)
            recovered.append(
                self.rollback_manifest_finalize_intent(
                    task_id, str(row["intent_id"]), reason, now=now
                )
            )
        return {"recovered_count": len(recovered), "intents": recovered}

    def quota_units_for_operations(self, task_id: str, operations: Sequence[str]) -> int:
        if not operations:
            return 0
        row = self.connection.execute(
            "SELECT COALESCE(SUM(units),0) AS total FROM quota_ledger WHERE task_id=? AND operation IN (%s)"
            % ",".join("?" for _ in operations),
            (task_id, *operations),
        ).fetchone()
        return int(row["total"] if row else 0)

    def operation_count(self, task_id: str, operation: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS total FROM quota_ledger WHERE task_id=? AND operation=?",
            (task_id, operation),
        ).fetchone()
        return int(row["total"] if row else 0)

    def update_batch(self, batch_id: str, **changes: Any) -> None:
        allowed = {
            "status",
            "raw_candidate_count",
            "new_valid_count",
            "duplicate_count",
            "page_count",
            "request_count",
            "quota_units",
            "estimated_cost_usd",
            "started_at",
            "finished_at",
            "error",
            "updated_at",
            "backend",
        }
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError("invalid batch fields: %s" % sorted(invalid))
        if not changes:
            return
        assignments = ",".join("%s=?" % key for key in changes)
        with self.connection:
            self.connection.execute(
                "UPDATE batches SET %s WHERE batch_id=?" % assignments,
                tuple(changes.values()) + (batch_id,),
            )

    def checkpoint(self, task_id: str, batch_id: str, key: str = "collector") -> Dict[str, Any]:
        row = self.connection.execute(
            "SELECT state_json FROM checkpoints WHERE task_id=? AND batch_id=? AND checkpoint_key=?",
            (task_id, batch_id, key),
        ).fetchone()
        return json.loads(str(row["state_json"])) if row else {}

    def save_checkpoint(self, task_id: str, batch_id: str, state: Mapping[str, Any], key: str = "collector") -> None:
        timestamp = iso_utc()
        with self.connection:
            self.connection.execute(
                """INSERT INTO checkpoints(task_id,batch_id,checkpoint_key,state_json,updated_at)
                VALUES(?,?,?,?,?) ON CONFLICT(task_id,batch_id,checkpoint_key)
                DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at""",
                (task_id, batch_id, key, compact_json(state), timestamp),
            )

    def clear_checkpoint(self, task_id: str, batch_id: str, key: str = "collector") -> None:
        with self.connection:
            self.connection.execute(
                "DELETE FROM checkpoints WHERE task_id=? AND batch_id=? AND checkpoint_key=?",
                (task_id, batch_id, key),
            )

    def record_quota(
        self,
        task_id: str,
        batch_id: Optional[str],
        source: str,
        operation: str,
        units: int,
        estimated_cost_usd: Optional[float] = None,
        actual_cost_usd: Optional[float] = None,
        cost_status: str = "unknown",
        currency: Optional[str] = None,
        price_snapshot_at: Optional[str] = None,
        pricing_basis: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        occurred_at: Optional[datetime] = None,
    ) -> None:
        if cost_status not in COST_STATUSES:
            raise ConfigurationError("未知 cost_status：%s" % cost_status)
        normalized_currency = str(currency or "").upper() or None
        if cost_status == "provider_confirmed_actual" and (
            actual_cost_usd is None or normalized_currency != "USD" or not pricing_basis
        ):
            raise ConfigurationError(
                "provider_confirmed_actual 必须提供 USD 金额和提供方账单依据"
            )
        if cost_status == "estimated_from_price_snapshot" and (
            estimated_cost_usd is None
            or normalized_currency != "USD"
            or not price_snapshot_at
            or not pricing_basis
        ):
            raise ConfigurationError(
                "estimated_from_price_snapshot 必须提供 USD 金额、价格快照时间和计算依据"
            )
        timestamp = iso_utc(occurred_at)
        stored_estimate = (
            estimated_cost_usd
            if estimated_cost_usd is not None or self._quota_estimated_nullable
            else 0.0
        )
        with self.connection:
            self.connection.execute(
                """INSERT INTO quota_ledger(
                    task_id,batch_id,source,operation,units,unit_name,
                    estimated_cost_usd,actual_cost_usd,cost_status,currency,
                    price_snapshot_at,pricing_basis,occurred_at,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    batch_id,
                    source,
                    operation,
                    int(units),
                    "youtube_quota_unit" if source == "youtube" else "request",
                    stored_estimate,
                    actual_cost_usd,
                    cost_status,
                    normalized_currency,
                    price_snapshot_at,
                    pricing_basis,
                    timestamp,
                    compact_json(metadata or {}),
                ),
            )

    def quota_used_on(self, task_id: str, day: datetime) -> int:
        start = day.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        row = self.connection.execute(
            """SELECT COALESCE(SUM(units),0) AS total FROM quota_ledger
            WHERE task_id=? AND occurred_at>=? AND occurred_at<?""",
            (task_id, iso_utc(start), iso_utc(end)),
        ).fetchone()
        return int(row["total"] if row else 0)

    def _comment_for_identity_aliases(
        self,
        task_id: str,
        aliases: Sequence[Tuple[str, str, str]],
    ) -> Optional[sqlite3.Row]:
        keys = [item[0] for item in aliases]
        if not keys:
            return None
        placeholders = ",".join("?" for _ in keys)
        rows = self.connection.execute(
            """SELECT DISTINCT c.* FROM comments c
            JOIN comment_identity_aliases a ON a.record_id=c.record_id
            WHERE a.task_id=? AND a.alias_key IN (%s)
            ORDER BY c.first_seen_at,c.record_id""" % placeholders,
            (task_id, *keys),
        ).fetchall()
        if not rows:
            rows = self.connection.execute(
                "SELECT * FROM comments WHERE task_id=? AND hard_key IN (%s) ORDER BY first_seen_at,record_id"
                % placeholders,
                (task_id, *keys),
            ).fetchall()
        if len(rows) > 1:
            raise CollectorError("同一组硬身份别名指向多个 canonical 留言，需先修复历史数据")
        return rows[0] if rows else None

    def _register_identity_aliases(
        self,
        task_id: str,
        record_id: str,
        aliases: Sequence[Tuple[str, str, str]],
        timestamp: str,
    ) -> None:
        for alias_key, alias_kind, alias_value in aliases:
            owner = self.connection.execute(
                "SELECT record_id FROM comment_identity_aliases WHERE task_id=? AND alias_key=?",
                (task_id, alias_key),
            ).fetchone()
            if owner is not None and str(owner["record_id"]) != record_id:
                raise CollectorError("硬身份别名已属于另一 canonical 留言")
            self.connection.execute(
                """INSERT OR IGNORE INTO comment_identity_aliases(
                task_id,alias_key,record_id,alias_kind,alias_value,created_at
                ) VALUES(?,?,?,?,?,?)""",
                (task_id, alias_key, record_id, alias_kind, alias_value, timestamp),
            )

    def insert_comment(
        self,
        task_id: str,
        batch: Mapping[str, Any],
        comment: Mapping[str, Any],
        now: Optional[datetime] = None,
    ) -> Tuple[str, bool, bool]:
        """Insert a comment and discovery.

        Returns ``(record_id, new_hard_unique, new_valid_unique)``.  Text is
        deliberately not a standalone identity key.
        """
        task = self.task_row(task_id)
        source = normalize_platform(comment.get("source") or batch.get("source") or "youtube")
        scope = str(batch.get("scope") or "category_30d")
        query_id = str(batch.get("query_id") or "")
        batch_id = str(batch.get("batch_id") or "")
        incoming_text = _normalize_exact_text(comment.get("text"))
        incoming_published = parse_timestamp(comment.get("published_at"))
        incoming_content_id = str(comment.get("content_id") or comment.get("comment_id") or "").strip() or None
        incoming_parent_id = str(
            comment.get("parent_content_id") or comment.get("parent_comment_id") or ""
        ).strip() or None
        incoming_thread_id = str(comment.get("thread_id") or "").strip() or None
        incoming_video_id = str(comment.get("video_id") or batch.get("video_id") or "").strip() or None
        incoming_author_id = str(comment.get("author_id") or "").strip()
        incoming_author_label = str(
            comment.get("author_label") or comment.get("author_display_name") or ""
        ).strip()
        incoming_url = canonicalize_url(comment.get("url"))
        if not incoming_url and source == "youtube" and incoming_video_id and incoming_content_id:
            incoming_url = "https://youtube.com/watch?%s" % urllib_parse.urlencode(
                {"lc": incoming_content_id, "v": incoming_video_id}
            )
            incoming_url = canonicalize_url(incoming_url)
        end_at = parse_timestamp(task["end_at"])
        if end_at is None:
            raise CollectorError("任务 end_at 无效")
        normalized: Dict[str, Any] = dict(comment)
        normalized.update(
            {
                "source": source,
                "content_id": incoming_content_id,
                "parent_content_id": incoming_parent_id,
                "thread_id": incoming_thread_id,
                "video_id": incoming_video_id,
                "author_id": incoming_author_id,
                "author_label": incoming_author_label,
                "author_hash": _author_hash(source, incoming_author_id, incoming_author_label),
                "url": incoming_url,
                "text": incoming_text,
                "published_at": iso_utc(incoming_published) if incoming_published else None,
            }
        )
        normalized["_opaque_identity"] = "%s\0%s" % (
            batch_id,
            str(comment.get("source_position") or comment.get("raw_index") or uuid.uuid4().hex),
        )
        aliases = _identity_alias_candidates(normalized)
        key = aliases[0][0]
        existing = self._comment_for_identity_aliases(task_id, aliases)
        was_valid = bool(existing and existing["eligible_for_quantitation"])
        existing_is_coded = bool(existing and str(existing["coding_status"]) == "coded")
        new_unique = existing is None

        content_id = str(existing["content_id"] or "").strip() if existing else ""
        content_id = content_id or str(incoming_content_id or "")
        parent_content_id = str(existing["parent_content_id"] or "").strip() if existing else ""
        parent_content_id = parent_content_id or str(incoming_parent_id or "")
        thread_id = str(existing["thread_id"] or "").strip() if existing else ""
        thread_id = thread_id or str(incoming_thread_id or "")
        video_id = str(existing["video_id"] or "").strip() if existing else ""
        video_id = video_id or str(incoming_video_id or "")
        old_author_id = str(existing["author_id"] or "").strip() if existing else ""
        author_id = old_author_id or incoming_author_id
        old_author_label = str(existing["author_label"] or "").strip() if existing else ""
        author_label = (
            incoming_author_label
            if not old_author_id and incoming_author_id and incoming_author_label
            else old_author_label or incoming_author_label
        )
        author_hash = _author_hash(source, author_id, author_label)
        text = _choose_richer_text(existing["text"] if existing else "", incoming_text)
        published_text = (
            str(existing["published_at"] or "") if existing else ""
        ) or (iso_utc(incoming_published) if incoming_published else "")
        published = parse_timestamp(published_text)
        updated_at_source = _choose_source_timestamp(
            existing["updated_at_source"] if existing else None,
            comment.get("updated_at"),
        )
        old_url = canonicalize_url(existing["canonical_url"] if existing else "")
        canonical_url = old_url
        if _url_quality(source, incoming_url, parent_content_id or None) > _url_quality(
            source, old_url, parent_content_id or None
        ):
            canonical_url = incoming_url

        window_start = end_at - timedelta(days=scope_window_days(scope))
        discovery_within_window = bool(
            published is not None and window_start <= published < end_at
        )
        within_window = bool(
            discovery_within_window or (existing and existing["within_window"])
        )
        relevant = bool(existing["is_relevant"]) if existing_is_coded else bool(text)
        consumer = bool(existing["is_consumer"]) if existing_is_coded else bool(text)
        merged_identity: Dict[str, Any] = {
            "source": source,
            "content_id": content_id or None,
            "parent_content_id": parent_content_id or None,
            "thread_id": thread_id or None,
            "video_id": video_id or None,
            "author_id": author_id,
            "author_label": author_label,
            "author_hash": author_hash,
            "url": canonical_url,
            "text": text,
            "published_at": iso_utc(published) if published else None,
            "_opaque_identity": key,
        }
        identity_complete = has_complete_hard_identity(merged_identity)
        parsed_url = urllib_parse.urlsplit(canonical_url) if canonical_url else None
        has_public_url = bool(
            parsed_url
            and parsed_url.scheme in {"http", "https"}
            and parsed_url.netloc
        )
        has_direct_link = bool(
            has_public_url
            and (
                not parent_content_id
                or is_comment_level_url(source, canonical_url)
            )
        )
        supported_platform = source in QUANTITATIVE_PLATFORMS
        technical_eligible = (
            within_window
            and bool(text)
            and published is not None
            and identity_complete
            and has_direct_link
            and supported_platform
        )
        eligible = bool(technical_eligible and relevant and consumer)
        if existing_is_coded:
            eligible = bool(existing["eligible_for_quantitation"])
        exclusion_reason = None
        if not text:
            exclusion_reason = "empty_text"
        elif published is None:
            exclusion_reason = "missing_or_invalid_published_at"
        elif not within_window:
            exclusion_reason = "outside_scope_window"
        elif not supported_platform:
            exclusion_reason = "unsupported_platform"
        elif not identity_complete:
            exclusion_reason = "missing_hard_identity"
        elif not has_public_url:
            exclusion_reason = "missing_source_url"
        elif not has_direct_link:
            exclusion_reason = "missing_comment_permalink"
        timestamp = iso_utc(now)
        record_id = str(existing["record_id"]) if existing else "voice_%s" % hashlib.sha256(
            (task_id + "\0" + key).encode("utf-8")
        ).hexdigest()[:24]
        raw_document = _raw_provenance_document(
            existing["raw_json"] if existing else {},
            comment,
            source=source,
            batch_id=batch_id,
            query_id=query_id,
            scope=scope,
            captured_at=timestamp,
            existing_captured_at=str(existing["first_seen_at"] or "") if existing else None,
        )
        merged_aliases = _identity_alias_candidates(merged_identity)
        all_aliases = list(aliases)
        for alias in merged_aliases:
            if not any(existing_alias[0] == alias[0] for existing_alias in all_aliases):
                all_aliases.append(alias)
        with self.connection:
            if existing is None:
                self.connection.execute(
                    """INSERT INTO comments(
                        record_id,task_id,source,content_id,hard_key,parent_content_id,
                        thread_id,video_id,author_id,author_label,author_hash,text,
                        published_at,updated_at_source,canonical_url,within_window,
                        is_relevant,is_consumer,technical_eligible,eligible_for_quantitation,
                        exclusion_reason,raw_json,first_seen_at,last_seen_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        record_id,
                        task_id,
                        source,
                        content_id or None,
                        key,
                        parent_content_id or None,
                        thread_id or None,
                        video_id or None,
                        author_id or None,
                        author_label or None,
                        author_hash,
                        text,
                        iso_utc(published) if published else None,
                        updated_at_source,
                        canonical_url or None,
                        int(within_window),
                        int(relevant),
                        int(consumer),
                        int(technical_eligible),
                        int(eligible),
                        exclusion_reason,
                        compact_json(raw_document),
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                self.connection.execute(
                    """UPDATE comments SET
                        content_id=?,parent_content_id=?,thread_id=?,video_id=?,
                        author_id=?,author_label=?,author_hash=?,text=?,published_at=?,
                        updated_at_source=?,canonical_url=?,raw_json=?,last_seen_at=?,
                        within_window=?,technical_eligible=?,
                        eligible_for_quantitation=CASE
                            WHEN coding_status='coded' THEN eligible_for_quantitation
                            ELSE ?
                        END,
                        exclusion_reason=CASE
                            WHEN coding_status='coded' THEN exclusion_reason
                            WHEN ?=1 THEN NULL
                            ELSE ?
                        END
                    WHERE record_id=?""",
                    (
                        content_id or None,
                        parent_content_id or None,
                        thread_id or None,
                        video_id or None,
                        author_id or None,
                        author_label or None,
                        author_hash,
                        text,
                        iso_utc(published) if published else None,
                        updated_at_source,
                        canonical_url or None,
                        compact_json(raw_document),
                        timestamp,
                        int(within_window),
                        int(technical_eligible),
                        int(eligible),
                        int(eligible),
                        exclusion_reason,
                        record_id,
                    ),
                )
            self._register_identity_aliases(
                task_id,
                record_id,
                list(all_aliases) + [(str(existing["hard_key"]), "legacy_primary", str(existing["hard_key"]))]
                if existing
                else all_aliases,
                timestamp,
            )
            self.connection.execute(
                """INSERT OR IGNORE INTO comment_discoveries(
                    task_id,record_id,batch_id,scope,query_id,source,within_window,discovered_at
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    record_id,
                    batch_id,
                    scope,
                    query_id,
                    source,
                    int(discovery_within_window),
                    timestamp,
                ),
            )
        return record_id, new_unique, bool(eligible and not was_valid and not existing_is_coded)

    def valid_count(self, task_id: str, scope: Optional[str] = None) -> int:
        if scope is None:
            row = self.connection.execute(
                "SELECT COUNT(*) AS total FROM comments WHERE task_id=? AND eligible_for_quantitation=1",
                (task_id,),
            ).fetchone()
            return int(row["total"] if row else 0)
        if scope == "category_30d":
            row = self.connection.execute(
                """SELECT COUNT(DISTINCT c.record_id) AS total
                FROM comments c JOIN comment_discoveries d ON d.record_id=c.record_id
                WHERE c.task_id=? AND c.eligible_for_quantitation=1
                  AND d.scope=? AND d.within_window=1""",
                (task_id, scope),
            ).fetchone()
            return int(row["total"] if row else 0)
        if scope not in SCOPES:
            raise ConfigurationError("未知 collection scope：%s" % scope)

        # Before semantic coding, route membership is provisional and query
        # discovery is used for acquisition caps. After coding, a segment
        # route counts only explicit is_member=true evidence. This allows a
        # same-level resume to refill a segment whose query hits were generic.
        rows = self.connection.execute(
            """SELECT DISTINCT c.record_id,c.coding_status,c.coding_json,
            CASE WHEN EXISTS(
                SELECT 1 FROM comment_discoveries d
                WHERE d.record_id=c.record_id AND d.scope=? AND d.within_window=1
            ) THEN 1 ELSE 0 END AS provisional_scope_hit
            FROM comments c
            WHERE c.task_id=? AND c.eligible_for_quantitation=1
              AND (
                c.coding_status='coded'
                OR EXISTS(
                    SELECT 1 FROM comment_discoveries d
                    WHERE d.record_id=c.record_id AND d.scope=? AND d.within_window=1
                )
              )""",
            (scope, task_id, scope),
        ).fetchall()
        total = 0
        for child in rows:
            if str(child["coding_status"]) != "coded":
                total += int(bool(child["provisional_scope_hit"]))
                continue
            try:
                coding = json.loads(str(child["coding_json"] or "{}"))
            except json.JSONDecodeError:
                continue
            memberships = coding.get("segment_memberships") if isinstance(coding, Mapping) else None
            if isinstance(memberships, list) and any(
                isinstance(membership, Mapping)
                and membership.get("segment_id") == scope
                and membership.get("is_member") is True
                for membership in memberships
            ):
                total += 1
        return total

    def low_increment_tail(
        self, task_id: str, scope: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        where = ["task_id=?", "status='completed'", "finished_at IS NOT NULL"]
        parameters: List[Any] = [task_id]
        if scope is not None:
            where.append("scope=?")
            parameters.append(scope)
        rows = self.connection.execute(
            """SELECT batch_id,source,scope,raw_candidate_count,new_valid_count,
            finished_at,metadata_json
            FROM batches WHERE %s
            ORDER BY finished_at DESC,batch_id DESC""" % " AND ".join(where),
            tuple(parameters),
        ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            raw = int(row["raw_candidate_count"] or 0)
            new = int(row["new_valid_count"] or 0)
            try:
                metadata = json.loads(str(row["metadata_json"] or "{}"))
            except json.JSONDecodeError:
                metadata = {}
            if raw == 0 and isinstance(metadata, Mapping) and metadata.get(
                "fallback_for_batch_id"
            ):
                # An empty/superseded technical fallback is not an independent
                # search batch and must not manufacture a saturation signal.
                continue
            result.append(
                {
                    "batch_id": row["batch_id"],
                    "platform": row["source"],
                    "scope": row["scope"],
                    "raw_candidate_count": raw,
                    "new_valid_count": new,
                    "increment_rate": (new / raw) if raw else 0.0,
                }
            )
            if len(result) == 3:
                break
        return list(reversed(result))

    def has_three_low_increment_batches(
        self, task_id: str, scope: Optional[str] = None
    ) -> bool:
        tail = self.low_increment_tail(task_id, scope=scope)
        return len(tail) == 3 and all(float(item["increment_rate"]) < 0.03 for item in tail)

    def has_completed_comment_expansion_batch(self, task_id: str, scope: str) -> bool:
        """Return whether a scope received an actual YouTube comment-page attempt."""

        return (
            self.connection.execute(
                """SELECT 1 FROM batches
                WHERE task_id=? AND scope=? AND source='youtube'
                  AND status='completed' AND finished_at IS NOT NULL
                LIMIT 1""",
                (task_id, scope),
            ).fetchone()
            is not None
        )

    def _funnel_slice(
        self,
        task_id: str,
        scope: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Dict[str, int]:
        batch_where = ["task_id=?"]
        batch_parameters: List[Any] = [task_id]
        discovery_where = ["d.task_id=?"]
        discovery_parameters: List[Any] = [task_id]
        if scope is not None:
            batch_where.append("scope=?")
            batch_parameters.append(scope)
            discovery_where.append("d.scope=?")
            discovery_parameters.append(scope)
        if source is not None:
            discovery_where.append("d.source=?")
            discovery_parameters.append(source)
        discovery_row = self.connection.execute(
            "SELECT COUNT(*) AS total FROM comment_discoveries d WHERE %s"
            % " AND ".join(discovery_where),
            tuple(discovery_parameters),
        ).fetchone()
        discovered = int(discovery_row["total"] if discovery_row else 0)
        if source is None:
            raw_batch_row = self.connection.execute(
                "SELECT COALESCE(SUM(raw_candidate_count),0) AS total FROM batches WHERE %s"
                % " AND ".join(batch_where),
                tuple(batch_parameters),
            ).fetchone()
            raw_batch_total = int(raw_batch_row["total"] if raw_batch_row else 0)
        else:
            raw_batch_total = 0
        common = " FROM comments c JOIN comment_discoveries d ON d.record_id=c.record_id WHERE " + " AND ".join(
            discovery_where
        )

        def count(extra: str = "") -> int:
            row = self.connection.execute(
                "SELECT COUNT(DISTINCT c.record_id) AS total" + common + extra,
                tuple(discovery_parameters),
            ).fetchone()
            return int(row["total"] if row else 0)

        unique = count()
        within = count(" AND d.within_window=1")
        relevant = count(" AND d.within_window=1 AND c.is_relevant=1")
        consumer = count(" AND d.within_window=1 AND c.is_relevant=1 AND c.is_consumer=1")
        deduplicated = consumer
        valid = count(" AND d.within_window=1 AND c.eligible_for_quantitation=1")
        return {
            # raw_candidate_count records pre-normalization candidates, while
            # discoveries record every normalized fetch observation. External
            # imports and resumed batches can make the former under-report, so
            # use the larger auditable count. This guarantees that the funnel
            # starts at or above its hard-unique stage without inventing data.
            "fetched_records": max(raw_batch_total, discovered),
            "unique_records": unique,
            "within_window_records": within,
            "relevant_records": relevant,
            "consumer_records": consumer,
            "deduplicated_records": deduplicated,
            "valid_voices": valid,
            "excluded_records": max(0, unique - valid),
        }

    def collection_funnel(self, task_id: str) -> Dict[str, Any]:
        self.task_row(task_id)
        funnel: Dict[str, Any] = self._funnel_slice(task_id)
        funnel["per_scope"] = []
        for scope in SCOPES:
            scope_values = self._funnel_slice(task_id, scope=scope)
            scope_values["valid_voices"] = self.valid_count(task_id, scope=scope)
            scope_values.pop("excluded_records", None)
            funnel["per_scope"].append(dict({"scope_id": scope}, **scope_values))
        sources = [
            str(row["source"])
            for row in self.connection.execute(
                """SELECT source FROM (
                SELECT DISTINCT source FROM comment_discoveries WHERE task_id=?
                UNION
                SELECT DISTINCT source FROM batches
                WHERE task_id=? AND source IN ('reddit','x','twitter','youtube','tiktok','instagram')
                ) ORDER BY source""",
                (task_id, task_id),
            ).fetchall()
        ]
        funnel["per_platform"] = []
        for source in sources:
            platform_values = self._funnel_slice(task_id, source=source)
            funnel["per_platform"].append(
                {
                    "platform": source,
                    "fetched_records": platform_values["fetched_records"],
                    "valid_voices": platform_values["valid_voices"],
                }
            )
        reason_rows = self.connection.execute(
            """SELECT COALESCE(exclusion_reason,'not_eligible') AS reason,COUNT(*) AS count
            FROM comments WHERE task_id=? AND eligible_for_quantitation=0
            GROUP BY COALESCE(exclusion_reason,'not_eligible') ORDER BY count DESC,reason""",
            (task_id,),
        ).fetchall()
        funnel["exclusion_reasons"] = [dict(row) for row in reason_rows]
        return funnel

    def coding_records(self, task_id: str, include_coded: bool = False) -> List[Dict[str, Any]]:
        condition = "c.task_id=?"
        parameters: List[Any] = [task_id]
        if not include_coded:
            condition += " AND c.coding_status!='coded'"
        rows = self.connection.execute(
            "SELECT c.* FROM comments c WHERE %s ORDER BY c.published_at,c.record_id" % condition,
            tuple(parameters),
        ).fetchall()
        records: List[Dict[str, Any]] = []
        for row in rows:
            discoveries = self.connection.execute(
                """SELECT scope,query_id,batch_id,source,within_window,discovered_at
                FROM comment_discoveries WHERE record_id=? ORDER BY discovery_id""",
                (row["record_id"],),
            ).fetchall()
            records.append(
                {
                    "record_id": row["record_id"],
                    "platform": row["source"],
                    "content_id": row["content_id"],
                    "parent_content_id": row["parent_content_id"],
                    "thread_id": row["thread_id"],
                    "video_id": row["video_id"],
                    "author_hash": row["author_hash"],
                    "author_label": row["author_label"],
                    "text": row["text"],
                    "published_at": row["published_at"],
                    "url": row["canonical_url"],
                    "collection_scopes": sorted({str(child["scope"]) for child in discoveries}),
                    "query_ids": sorted({str(child["query_id"]) for child in discoveries}),
                    "discoveries": [dict(child) for child in discoveries],
                    "coding": json.loads(str(row["coding_json"])) if row["coding_json"] else {
                        "eligible_for_quantitation": bool(row["eligible_for_quantitation"]),
                        "is_relevant": bool(row["is_relevant"]),
                        "is_consumer": bool(row["is_consumer"]),
                        "exclusion_reason": row["exclusion_reason"],
                        "sentiment": "neutral",
                        "use_scenes": [],
                        "persona_tags": [],
                        "need_codes": [],
                        "satisfaction_codes": [],
                        "dissatisfaction_codes": [],
                        "innovation_signals": [],
                        "kano_evidence": [],
                        "evidence_confidence": "low",
                        "coding_notes": None,
                        "summary_zh": "",
                        "language": "und",
                        "region_hint": None,
                        "community": None,
                        "segment_memberships": [],
                    },
                }
            )
        return records

    def autocode_technical_exclusions(self, task_id: str) -> int:
        """Finalize deterministic technical exclusions before Codex batches."""

        rows = self.connection.execute(
            """SELECT record_id,is_relevant,is_consumer,exclusion_reason
            FROM comments
            WHERE task_id=? AND technical_eligible=0 AND coding_status!='coded'""",
            (task_id,),
        ).fetchall()
        if not rows:
            return 0
        updates: List[Tuple[str, str]] = []
        for row in rows:
            coding = {
                "eligible_for_quantitation": False,
                "is_relevant": bool(row["is_relevant"]),
                "is_consumer": bool(row["is_consumer"]),
                "exclusion_reason": str(row["exclusion_reason"] or "technical_precheck_excluded"),
                "sentiment": "neutral",
                "use_scenes": [],
                "persona_tags": [],
                "need_codes": [],
                "satisfaction_codes": [],
                "dissatisfaction_codes": [],
                "innovation_signals": [],
                "kano_evidence": [],
                "evidence_confidence": "low",
                "coding_notes": "技术预检已确定不可进入量化分母，未调用语义编码。",
                "summary_zh": "技术规则排除，未进入量化分析。",
                "language": "und",
                "region_hint": None,
                "community": None,
                "segment_memberships": [],
            }
            updates.append((compact_json(coding), str(row["record_id"])))
        with self.connection:
            self.connection.executemany(
                """UPDATE comments
                SET coding_status='coded',coding_json=?,coding_batch_id='technical_precheck'
                WHERE record_id=?""",
                updates,
            )
        return len(updates)

    def mark_prepared(self, record_ids: Sequence[str], coding_batch_id: str) -> None:
        if not record_ids:
            return
        with self.connection:
            self.connection.executemany(
                "UPDATE comments SET coding_status='prepared',coding_batch_id=? WHERE record_id=?",
                [(coding_batch_id, record_id) for record_id in record_ids],
            )

    def merge_coding(self, task_id: str, records: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
        seen: set = set()
        updated = 0
        unchanged = 0
        with self.connection:
            for item in records:
                record_id = str(item.get("record_id") or "")
                if not record_id:
                    raise CollectorError("coding record 缺少 record_id")
                if record_id in seen:
                    raise CollectorError("coding 输入包含重复 record_id：%s" % record_id)
                seen.add(record_id)
                existing = self.connection.execute(
                    "SELECT * FROM comments WHERE task_id=? AND record_id=?", (task_id, record_id)
                ).fetchone()
                if existing is None:
                    raise CollectorError("coding record 不属于任务：%s" % record_id)
                coding = item.get("coding")
                if not isinstance(coding, Mapping):
                    raise CollectorError("coding 必须是对象：%s" % record_id)
                relevant = coding.get("is_relevant", bool(existing["is_relevant"]))
                consumer = coding.get("is_consumer", bool(existing["is_consumer"]))
                eligible = coding.get(
                    "eligible_for_quantitation", bool(existing["eligible_for_quantitation"])
                )
                if not isinstance(relevant, bool) or not isinstance(consumer, bool) or not isinstance(eligible, bool):
                    raise CollectorError("coding eligibility 字段必须是 boolean：%s" % record_id)
                if eligible and (not relevant or not consumer or not existing["within_window"]):
                    raise CollectorError("eligible 记录必须 relevant、consumer 且在时间窗内：%s" % record_id)
                if eligible and not bool(existing["technical_eligible"]):
                    raise CollectorError(
                        "编码不得把缺少硬身份、留言直链、支持平台或可靠时间窗的技术无效记录提升为有效：%s"
                        % record_id
                    )
                exclusion = coding.get("exclusion_reason")
                if not eligible and not str(exclusion or "").strip():
                    exclusion = "excluded_by_coding"
                encoded = compact_json(coding)
                if existing["coding_json"] == encoded and existing["coding_status"] == "coded":
                    unchanged += 1
                    continue
                self.connection.execute(
                    """UPDATE comments SET is_relevant=?,is_consumer=?,eligible_for_quantitation=?,
                    exclusion_reason=?,coding_json=?,coding_status='coded' WHERE record_id=?""",
                    (int(relevant), int(consumer), int(eligible), exclusion, encoded, record_id),
                )
                updated += 1
        return {"updated": updated, "unchanged": unchanged}


class UrllibHttpClient:
    """Small injectable JSON HTTP client."""

    def get_json(
        self,
        url: str,
        params: Mapping[str, Any],
        timeout: float,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Mapping[str, Any]:
        query = urllib_parse.urlencode({key: value for key, value in params.items() if value is not None})
        request = urllib_request.Request(
            url + ("?" + query if query else ""),
            headers=dict(
                {"Accept": "application/json", "User-Agent": "lc-amazon-market-opportunity/2"},
                **dict(headers or {}),
            ),
        )
        try:
            with urllib_request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code < 600:
                raise RetryableHttpError(exc.code)
            raise CollectorError("YouTube API HTTP %d" % exc.code)
        except (urllib_error.URLError, TimeoutError) as exc:
            raise CollectorError("YouTube API 网络错误：%s" % redact_text(exc))
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise CollectorError("YouTube API 返回非 JSON：%s" % exc)
        if not isinstance(decoded, Mapping):
            raise CollectorError("YouTube API 返回结构无效")
        return decoded


def default_runner(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _youtube_author_id(snippet: Mapping[str, Any]) -> str:
    value = snippet.get("authorChannelId")
    if isinstance(value, Mapping):
        return str(value.get("value") or "")
    return str(value or "")


def youtube_comment_record(
    payload: Mapping[str, Any],
    video_id: str,
    thread_id: str,
    parent_content_id: Optional[str] = None,
) -> Dict[str, Any]:
    snippet = payload.get("snippet") if isinstance(payload.get("snippet"), Mapping) else {}
    content_id = str(payload.get("id") or "")
    text = snippet.get("textOriginal") or snippet.get("textDisplay") or ""
    return {
        "source": "youtube",
        "content_id": content_id,
        "parent_content_id": parent_content_id,
        "thread_id": thread_id,
        "video_id": video_id,
        "author_id": _youtube_author_id(snippet),
        "author_label": str(snippet.get("authorDisplayName") or ""),
        "text": str(text),
        "published_at": snippet.get("publishedAt"),
        "updated_at": snippet.get("updatedAt"),
        "url": "https://www.youtube.com/watch?%s"
        % urllib_parse.urlencode({"v": video_id, "lc": content_id})
        if content_id
        else "",
        "engagement": {"likes": int(snippet.get("likeCount") or 0)},
    }


class YoutubeDataApiCollector:
    """YouTube commentThreads/comments paginator with resumable offsets."""

    def __init__(
        self,
        api_key: str,
        http_client: Optional[Any] = None,
        timeout: float = 20.0,
        timeout_provider: Optional[Callable[[], float]] = None,
        retry_wait: Optional[Callable[[float], None]] = None,
        max_retries: int = 2,
    ):
        if not api_key:
            raise ConfigurationError("未配置 YouTube API key")
        self.api_key = api_key
        self.http = http_client or UrllibHttpClient()
        self.timeout = timeout
        self.timeout_provider = timeout_provider
        self.retry_wait = retry_wait or time.sleep
        self.max_retries = max(0, int(max_retries))

    @staticmethod
    def _retryable_status(value: Any) -> Optional[int]:
        status = getattr(value, "status_code", None)
        if status is None and isinstance(value, Mapping):
            status = value.get("code")
        if status is None:
            match = re.search(r"(?:HTTP\s*)?(429|5\d\d)(?:\D|$)", str(value), flags=re.IGNORECASE)
            status = int(match.group(1)) if match else None
        try:
            normalized = int(status) if status is not None else None
        except (TypeError, ValueError):
            return None
        return normalized if normalized == 429 or (normalized is not None and 500 <= normalized < 600) else None

    def _get(
        self,
        resource: str,
        params: Mapping[str, Any],
        before_request: Callable[[str, int], None],
    ) -> Mapping[str, Any]:
        operation = resource + ".list"
        # YouTube's current granular quota model charges one unit for these
        # read/list operations.  Per-level search call counts are enforced
        # separately by ``before_request``.
        for attempt in range(self.max_retries + 1):
            before_request(operation, 1)
            request_timeout = max(0.1, float(self.timeout))
            if self.timeout_provider is not None:
                request_timeout = max(
                    0.1,
                    min(request_timeout, float(self.timeout_provider())),
                )
            try:
                result = self.http.get_json(
                    "%s/%s" % (YOUTUBE_API_BASE, resource),
                    dict(params),
                    request_timeout,
                    headers={"x-goog-api-key": self.api_key},
                )
            except Exception as exc:
                if self._retryable_status(exc) is not None and attempt < self.max_retries:
                    self.retry_wait(min(0.5 * (2 ** attempt), 2.0))
                    continue
                raise CollectorError(redact_text(exc, (self.api_key,)))
            error = result.get("error") if isinstance(result.get("error"), Mapping) else None
            if error is not None:
                if self._retryable_status(error) is not None and attempt < self.max_retries:
                    self.retry_wait(min(0.5 * (2 ** attempt), 2.0))
                    continue
                message = error.get("message") or "YouTube API error"
                raise CollectorError(redact_text(message, (self.api_key,)))
            return result
        raise CollectorError("YouTube API 重试次数已耗尽")

    def collect(
        self,
        video_id: str,
        checkpoint: Mapping[str, Any],
        emit: Callable[[Mapping[str, Any]], None],
        save_checkpoint: Callable[[Mapping[str, Any]], None],
        before_request: Callable[[str, int], None],
        should_stop: Callable[[], None],
        include_replies: bool = True,
    ) -> Dict[str, int]:
        if not video_id:
            raise ConfigurationError("youtube-data-api batch 缺少 video_id")
        state: Dict[str, Any] = dict(checkpoint or {})
        thread_page_token = state.get("thread_page_token") or None
        item_offset = int(state.get("item_offset") or 0)
        raw_count = 0
        page_count = 0
        while True:
            should_stop()
            response = self._get(
                "commentThreads",
                {
                    "part": "snippet,replies",
                    "videoId": video_id,
                    "maxResults": 100,
                    "order": "time",
                    "textFormat": "plainText",
                    "pageToken": thread_page_token,
                },
                before_request,
            )
            page_count += 1
            items = response.get("items") if isinstance(response.get("items"), list) else []
            for index in range(item_offset, len(items)):
                should_stop()
                thread = items[index] if isinstance(items[index], Mapping) else {}
                thread_id = str(thread.get("id") or "")
                thread_snippet = thread.get("snippet") if isinstance(thread.get("snippet"), Mapping) else {}
                top = thread_snippet.get("topLevelComment")
                if isinstance(top, Mapping):
                    emit(youtube_comment_record(top, video_id, thread_id))
                    raw_count += 1
                top_id = str(top.get("id") or "") if isinstance(top, Mapping) else ""
                replies = thread.get("replies") if isinstance(thread.get("replies"), Mapping) else {}
                embedded = replies.get("comments") if isinstance(replies.get("comments"), list) else []
                for reply in embedded:
                    if isinstance(reply, Mapping):
                        emit(youtube_comment_record(reply, video_id, thread_id, parent_content_id=top_id))
                        raw_count += 1
                total_replies = int(thread_snippet.get("totalReplyCount") or 0)
                reply_parent = state.get("reply_parent_id")
                reply_token = state.get("reply_page_token") if reply_parent == top_id else None
                if include_replies and top_id and total_replies > len(embedded):
                    while True:
                        should_stop()
                        reply_response = self._get(
                            "comments",
                            {
                                "part": "snippet",
                                "parentId": top_id,
                                "maxResults": 100,
                                "textFormat": "plainText",
                                "pageToken": reply_token,
                            },
                            before_request,
                        )
                        page_count += 1
                        reply_items = (
                            reply_response.get("items")
                            if isinstance(reply_response.get("items"), list)
                            else []
                        )
                        for reply in reply_items:
                            if isinstance(reply, Mapping):
                                emit(youtube_comment_record(reply, video_id, thread_id, parent_content_id=top_id))
                                raw_count += 1
                        reply_token = reply_response.get("nextPageToken") or None
                        save_checkpoint(
                            {
                                "thread_page_token": thread_page_token,
                                "item_offset": index,
                                "reply_parent_id": top_id,
                                "reply_page_token": reply_token,
                            }
                        )
                        if not reply_token:
                            break
                state = {
                    "thread_page_token": thread_page_token,
                    "item_offset": index + 1,
                    "reply_parent_id": None,
                    "reply_page_token": None,
                }
                save_checkpoint(state)
            next_token = response.get("nextPageToken") or None
            save_checkpoint(
                {
                    "thread_page_token": next_token,
                    "item_offset": 0,
                    "reply_parent_id": None,
                    "reply_page_token": None,
                }
            )
            if not next_token:
                break
            thread_page_token = next_token
            item_offset = 0
            state = {}
        return {"raw_candidate_count": raw_count, "page_count": page_count}

    def search_videos(
        self,
        query: str,
        before_request: Callable[[str, int], None],
        max_results: int = 50,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        response = self._get(
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": query,
                "maxResults": min(50, max(1, int(max_results))),
                "pageToken": page_token,
                "safeSearch": "none",
            },
            before_request,
        )
        video_ids: List[str] = []
        for item in response.get("items") if isinstance(response.get("items"), list) else []:
            if not isinstance(item, Mapping):
                continue
            identity = item.get("id")
            if isinstance(identity, Mapping) and identity.get("videoId"):
                video_ids.append(str(identity["videoId"]))
        return {"video_ids": video_ids, "next_page_token": response.get("nextPageToken")}


class YtDlpCollector:
    """Fallback adapter; subprocess execution is injectable for tests."""

    def __init__(
        self,
        runner: Optional[Callable[[Sequence[str], float], subprocess.CompletedProcess]] = None,
        binary: str = "yt-dlp",
        timeout: float = 120.0,
    ):
        self.runner = runner or default_runner
        self.binary = binary
        self.timeout = timeout

    def collect(
        self,
        target: str,
        emit: Callable[[Mapping[str, Any]], None],
        should_stop: Callable[[], None],
    ) -> Dict[str, int]:
        if not target:
            raise ConfigurationError("yt-dlp batch 缺少 video URL/ID/query")
        should_stop()
        command = [
            self.binary,
            "--skip-download",
            "--write-comments",
            "--dump-single-json",
            "--no-warnings",
            target,
        ]
        try:
            completed = self.runner(command, self.timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CollectorError("yt-dlp 执行失败：%s" % redact_text(exc))
        if completed.returncode != 0:
            raise CollectorError("yt-dlp 返回失败：%s" % redact_text(completed.stderr or "unknown error"))
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CollectorError("yt-dlp 返回非 JSON：%s" % exc)
        raw_count = 0

        def walk(entry: Mapping[str, Any]) -> None:
            nonlocal raw_count
            video_id = str(entry.get("id") or "")
            comments = entry.get("comments") if isinstance(entry.get("comments"), list) else []
            for comment_index, item in enumerate(comments):
                should_stop()
                if not isinstance(item, Mapping):
                    continue
                timestamp = item.get("timestamp") or item.get("time")
                content_id = str(item.get("id") or "")
                emit(
                    {
                        "source": "youtube",
                        "content_id": content_id,
                        "parent_content_id": str(item.get("parent") or "") or None,
                        "thread_id": str(item.get("parent") or content_id),
                        "video_id": video_id,
                        "author_id": str(item.get("author_id") or ""),
                        "author_label": str(item.get("author") or ""),
                        "text": str(item.get("text") or ""),
                        "published_at": iso_utc(parse_timestamp(timestamp)) if parse_timestamp(timestamp) else None,
                        "url": "https://www.youtube.com/watch?%s"
                        % urllib_parse.urlencode({"v": video_id, "lc": content_id})
                        if video_id and content_id
                        else "",
                        "engagement": {"likes": int(item.get("like_count") or 0)},
                        "source_position": "%s:%d" % (video_id or "unknown-video", comment_index),
                    }
                )
                raw_count += 1
            children = entry.get("entries") if isinstance(entry.get("entries"), list) else []
            for child in children:
                if isinstance(child, Mapping):
                    walk(child)

        if isinstance(payload, Mapping):
            walk(payload)
        return {"raw_candidate_count": raw_count, "page_count": 1, "request_count": 1}


def _youtube_video_id(item: Mapping[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    direct = str(item.get("video_id") or metadata.get("video_id") or "").strip()
    if direct:
        return direct
    url = str(item.get("url") or "")
    try:
        split = urllib_parse.urlsplit(url)
    except ValueError:
        return ""
    query = dict(urllib_parse.parse_qsl(split.query))
    if query.get("v"):
        return query["v"]
    if split.netloc.lower().endswith("youtu.be"):
        return split.path.strip("/").split("/", 1)[0]
    match = re.search(r"/(?:shorts|embed)/([^/?]+)", split.path)
    return match.group(1) if match else ""


_LAST30DAYS_LOCAL_RANK_ID = re.compile(
    r"^(?:R|X|Y|T|I|YT|TK|IG)\d+$",
    flags=re.IGNORECASE,
)


def _native_content_id_from_url(platform: str, value: Any, *, prefer_comment: bool = False) -> str:
    """Extract a platform identity from a canonical public URL.

    last30days ``item_id`` values such as R1/X2 are result-local ranks, not
    platform IDs.  URL-derived identities are stable across query batches.
    """
    url = canonicalize_url(value)
    if not url:
        return ""
    try:
        split = urllib_parse.urlsplit(url)
        query = dict(urllib_parse.parse_qsl(split.query, keep_blank_values=True))
    except ValueError:
        return ""
    normalized = platform.casefold()
    if normalized == "reddit":
        parts = [part for part in split.path.split("/") if part]
        try:
            position = parts.index("comments")
        except ValueError:
            return ""
        post_id = parts[position + 1] if len(parts) > position + 1 else ""
        comment_id = parts[position + 3] if len(parts) > position + 3 else ""
        return comment_id if prefer_comment and comment_id else post_id
    if normalized in {"x", "twitter"}:
        match = re.search(r"/status/(\d+)(?:/|$)", split.path)
        return match.group(1) if match else ""
    if normalized == "youtube":
        if prefer_comment and query.get("lc"):
            return str(query["lc"])
        return _youtube_video_id({"url": url})
    if normalized == "tiktok":
        if prefer_comment and (query.get("comment_id") or query.get("commentId")):
            return str(query.get("comment_id") or query.get("commentId"))
        match = re.search(r"/video/(\d+)(?:/|$)", split.path)
        return match.group(1) if match else ""
    if normalized == "instagram":
        if prefer_comment and (query.get("comment_id") or query.get("commentId")):
            return str(query.get("comment_id") or query.get("commentId"))
        match = re.search(r"/(?:p|reel|tv)/([^/?]+)", split.path)
        return match.group(1) if match else ""
    return ""


def _stable_last30days_content_id(platform: str, raw_id: Any, url: Any, *, prefer_comment: bool = False) -> str:
    derived = _native_content_id_from_url(platform, url, prefer_comment=prefer_comment)
    if derived:
        return derived
    candidate = str(raw_id or "").strip()
    if not candidate or _LAST30DAYS_LOCAL_RANK_ID.fullmatch(candidate):
        return ""
    return candidate


def _extract_last30days_payload(
    payload: Any,
    batch: Mapping[str, Any],
    emit: Callable[[Mapping[str, Any]], None],
) -> List[str]:
    if not isinstance(payload, Mapping):
        return []
    by_source = payload.get("items_by_source")
    if not isinstance(by_source, Mapping):
        return []
    video_ids: List[str] = []
    seen_videos = set()
    allowed_sources = {"reddit", "x", "youtube", "tiktok", "instagram"}
    for source, raw_items in by_source.items():
        if not isinstance(raw_items, list):
            continue
        platform = normalize_platform(source)
        if platform not in allowed_sources:
            continue
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, Mapping):
                continue
            item = dict(raw_item)
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
            parent_id = _stable_last30days_content_id(
                platform,
                item.get("id") or item.get("item_id"),
                item.get("url"),
            )
            video_id = _youtube_video_id(item) if platform == "youtube" else ""
            if video_id and video_id not in seen_videos:
                seen_videos.add(video_id)
                video_ids.append(video_id)
            parent_text = str(item.get("body") or item.get("snippet") or item.get("title") or "").strip()
            if parent_text:
                emit(
                    {
                        "source": platform,
                        "content_id": video_id or parent_id,
                        "parent_content_id": None,
                        "thread_id": video_id or parent_id,
                        "video_id": video_id or None,
                        "author_label": str(item.get("author") or ""),
                        "text": parent_text,
                        "published_at": item.get("published_at"),
                        "url": item.get("url"),
                        "raw_origin": "last30days_parent",
                        "source_position": "%s:%d:parent" % (platform, index),
                    }
                )
            comments = metadata.get("top_comments") if isinstance(metadata.get("top_comments"), list) else []
            for comment_index, comment in enumerate(comments):
                if not isinstance(comment, Mapping):
                    continue
                comment_text = str(comment.get("excerpt") or comment.get("text") or "").strip()
                if not comment_text:
                    continue
                emit(
                    {
                        "source": platform,
                        "content_id": _stable_last30days_content_id(
                            platform,
                            comment.get("id") or comment.get("comment_id"),
                            comment.get("url"),
                            prefer_comment=True,
                        ),
                        "parent_content_id": video_id or parent_id,
                        "thread_id": video_id or parent_id,
                        "video_id": video_id or None,
                        "author_id": str(comment.get("author_id") or ""),
                        "author_label": str(comment.get("author") or ""),
                        "text": comment_text,
                        "published_at": comment.get("published_at") or comment.get("date"),
                        "url": comment.get("url"),
                        "raw_origin": "last30days_top_comment",
                        "source_position": "%s:%d:%d" % (platform, index, comment_index),
                    }
                )
    return video_ids


class NonBlockingReminder:
    def __init__(
        self,
        enabled: bool,
        interval_seconds: float,
        sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
        monotonic: Callable[[], float] = time.monotonic,
        research_level: Optional[str] = None,
        offer_level_options: bool = False,
    ):
        self.enabled = enabled
        self.interval_seconds = interval_seconds
        self.sink = sink or self._stderr_sink
        self.monotonic = monotonic
        self.research_level = research_level
        self.offer_level_options = offer_level_options
        self.next_due = monotonic() + interval_seconds

    @staticmethod
    def _stderr_sink(payload: Mapping[str, Any]) -> None:
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stderr.flush()

    def maybe(self, payload: Mapping[str, Any]) -> None:
        if not self.enabled:
            return
        current = self.monotonic()
        if current < self.next_due:
            return
        message = dict(payload)
        message.update({"event": "progress_reminder", "blocking": False, "at": iso_utc()})
        if self.research_level == "quick" and self.offer_level_options:
            message.update(
                {
                    "optional_research_levels": ["standard", "deep"],
                    "level_note": "当前继续按 quick 执行；后续可用 resume 升到 standard 或 deep，无需本次确认。",
                }
            )
        self.sink(message)
        self.next_due = current + self.interval_seconds


class CollectorService:
    """Run/resume orchestration with hard limits and persisted checkpoints."""

    def __init__(
        self,
        store: CollectorStore,
        api_key: str = "",
        http_client: Optional[Any] = None,
        runner: Optional[Callable[[Sequence[str], float], subprocess.CompletedProcess]] = None,
        yt_dlp_binary: str = "yt-dlp",
        http_timeout: float = 20.0,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = utc_now,
        reminder_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
        youtube_config: Optional[Mapping[str, Any]] = None,
        global_quota_ledger_path: Optional[Path] = None,
    ):
        self.store = store
        self.api_key = api_key
        self.http_client = http_client
        self.runner = runner
        self.yt_dlp_binary = yt_dlp_binary
        self.http_timeout = http_timeout
        self.monotonic = monotonic
        self.now = now
        self.reminder_sink = reminder_sink
        self.global_quota_ledger_path = (
            Path(global_quota_ledger_path) if global_quota_ledger_path is not None else None
        )
        self.youtube_config = dict(
            youtube_config
            or {
                "enabled": bool(api_key),
                "daily_quota_units": DEFAULT_DAILY_YOUTUBE_QUOTA,
                "quota_reserve": MIN_YOUTUBE_QUOTA_RESERVE,
                "search_enabled": False,
                "max_results": 100,
                "max_workers": 4,
            }
        )
        self._last30days_runtime: Optional[Dict[str, Any]] = None

    def run(self, task_id: str, resume: bool = False) -> Dict[str, Any]:
        if resume:
            # A prior external phase may have died without an end event.  Keep
            # committed heartbeat time, but never count the idle gap to resume.
            self.store.abandon_open_timing_sessions(task_id, reason="resume_recovery")
            self.store.recover_manifest_finalize_intents(
                task_id, abandon_running=False, reason="resume_recovery"
            )
        elif self.store.connection.execute(
            "SELECT 1 FROM timing_sessions WHERE task_id=? AND status='running' LIMIT 1",
            (task_id,),
        ).fetchone() is not None:
            raise ConfigurationError("存在运行中的外部计时阶段；请先 heartbeat/end 或使用 resume 恢复")
        task = self.store.task_payload(task_id)
        plan = task["research_plan"]
        budget = plan["time_budget_minutes"]
        target = plan["sample_target"]
        reminder_policy = task["collection_policy"]["reminder_policy"]
        reminder = NonBlockingReminder(
            bool(reminder_policy["enabled"]),
            float(reminder_policy["interval_minutes"]) * 60,
            sink=self.reminder_sink,
            monotonic=self.monotonic,
            research_level=str(task["research_level"]),
            offer_level_options=bool(task["collection_policy"].get("research_level_explicit")),
        )
        started_mono = self.monotonic()
        timing_usage = self.store.timing_usage(task_id, include_running=False)
        base_collection = float(timing_usage["effective_collection_seconds"])
        base_total = float(timing_usage["effective_total_seconds"])
        now_text = iso_utc(self.now())
        self.store.update_task(
            task_id,
            status="running",
            stop_reason=None,
            started_at=task["started_at"] or now_text,
            updated_at=now_text,
            run_count=int(task["run_count"]) + 1,
            last_error=None,
        )
        statuses = ["planned"] if not resume else ["planned", "paused", "error", "running"]
        batches = [
            row
            for row in self.store.list_batches(task_id, statuses=statuses)
            if str(row["backend"] or "") != "external"
        ]
        known_batch_ids = {str(row["batch_id"]) for row in batches}
        stop_reason: Optional[str] = None
        fatal_errors = 0

        def elapsed() -> float:
            return max(0.0, self.monotonic() - started_mono)

        def all_scope_uppers_reached() -> bool:
            return all(
                self.store.valid_count(task_id, scope=scope_id)
                >= int(scope_target["valid_max"])
                for scope_id, scope_target in target["per_scope"].items()
            )

        def all_scopes_saturated() -> bool:
            """Apply the 3-batch saturation rule per route instead of globally."""

            for scope_id, scope_target in target["per_scope"].items():
                if self.store.valid_count(task_id, scope=scope_id) >= int(
                    scope_target["valid_max"]
                ):
                    continue
                # Broad discovery is not comment expansion. Requiring a real
                # YouTube batch prevents low yield in the first scheduled route
                # from terminating the other three routes before they are sampled.
                if not self.store.has_completed_comment_expansion_batch(task_id, scope_id):
                    return False
                if not self.store.has_three_low_increment_batches(task_id, scope=scope_id):
                    return False
            return True

        def enforce_deadlines() -> None:
            if (
                base_total + elapsed()
                >= float(budget["total"]) * 60 - FINALIZATION_RESERVE_SECONDS
            ):
                raise DeadlineError("total_deadline")
            if base_collection + elapsed() >= float(budget["collection"]) * 60:
                raise DeadlineError("collection_deadline")
            if all_scope_uppers_reached():
                raise StopCollection("upper_bound_reached")

        def remaining_seconds() -> float:
            current_elapsed = elapsed()
            collection_remaining = (
                float(budget["collection"]) * 60 - base_collection - current_elapsed
            )
            expansion_remaining = (
                float(budget["total"]) * 60
                - FINALIZATION_RESERVE_SECONDS
                - base_total
                - current_elapsed
            )
            if expansion_remaining <= 0:
                raise DeadlineError("total_deadline")
            if collection_remaining <= 0:
                raise DeadlineError("collection_deadline")
            return min(collection_remaining, expansion_remaining)

        try:
            batch_index = 0
            youtube_schedule_initialized = False
            while batch_index < len(batches):
                remaining_rows = batches[batch_index:]
                if (
                    not youtube_schedule_initialized
                    and remaining_rows
                    and all(str(row["source"] or "") == "youtube" for row in remaining_rows)
                ):
                    scope_order = sorted(
                        target["per_scope"],
                        key=lambda scope_id: (
                            self.store.valid_count(task_id, scope=scope_id)
                            / max(1, int(target["per_scope"][scope_id]["valid_min"])),
                            list(target["per_scope"]).index(scope_id),
                        ),
                    )
                    batches[batch_index:] = interleave_youtube_batches_by_scope(
                        remaining_rows, scope_order
                    )
                    youtube_schedule_initialized = True
                batch_row = batches[batch_index]
                batch_index += 1
                enforce_deadlines()
                batch = self.store.batch_payload(batch_row)
                scope = str(batch["scope"])
                scope_max = int(target["per_scope"][scope]["valid_max"])
                if self.store.valid_count(task_id, scope=scope) >= scope_max:
                    self.store.update_batch(
                        str(batch["batch_id"]),
                        status="paused",
                        finished_at=None,
                        updated_at=iso_utc(self.now()),
                        error="scope_upper_reached",
                    )
                    continue
                try:
                    self._run_batch(
                        task, batch, enforce_deadlines, reminder, scope_max, remaining_seconds
                    )
                except ScopeUpperReached:
                    self.store.update_batch(
                        str(batch["batch_id"]),
                        status="paused",
                        finished_at=None,
                        updated_at=iso_utc(self.now()),
                        error="scope_upper_reached",
                    )
                except DeadlineError as exc:
                    stop_reason = exc.stop_reason
                    self.store.update_batch(
                        str(batch["batch_id"]), status="paused", updated_at=iso_utc(self.now())
                    )
                    break
                except StopCollection as exc:
                    stop_reason = exc.stop_reason
                    self.store.update_batch(
                        str(batch["batch_id"]), status="paused", updated_at=iso_utc(self.now())
                    )
                    break
                except QuotaLimitError as exc:
                    fatal_errors += 1
                    stop_reason = "platform_or_quota_limit"
                    self.store.update_batch(
                        str(batch["batch_id"]),
                        status="paused",
                        error=redact_text(exc, (self.api_key,)),
                        updated_at=iso_utc(self.now()),
                    )
                    break
                except CollectorError as exc:
                    fatal_errors += 1
                    self.store.update_batch(
                        str(batch["batch_id"]),
                        status="error",
                        error=redact_text(exc, (self.api_key,)),
                        finished_at=iso_utc(self.now()),
                        updated_at=iso_utc(self.now()),
                    )
                for queued in self.store.list_batches(task_id, statuses=["planned"]):
                    if str(queued["backend"] or "") == "external":
                        continue
                    queued_id = str(queued["batch_id"])
                    if queued_id not in known_batch_ids:
                        known_batch_ids.add(queued_id)
                        batches.append(queued)
                if all_scopes_saturated():
                    stop_reason = "low_increment_3_batches"
                    break
            if stop_reason is None:
                if all_scope_uppers_reached():
                    stop_reason = "upper_bound_reached"
                elif self.store.connection.execute(
                    """SELECT 1 FROM batches
                    WHERE task_id=? AND status='paused'
                      AND backend IN ('auto','youtube-data-api')
                      AND error LIKE 'youtube_official_pending:%'
                    LIMIT 1""",
                    (task_id,),
                ).fetchone() is not None:
                    # The best-effort fallback may have completed, but the
                    # official checkpoint remains resumable and the task is
                    # not truthfully queue-exhausted yet.
                    stop_reason = "platform_or_quota_limit"
                elif fatal_errors and not self.store.list_batches(task_id, statuses=["planned", "paused"]):
                    stop_reason = "platform_or_quota_limit"
                else:
                    stop_reason = "queues_exhausted"
        except KeyboardInterrupt:
            stop_reason = "manual_stop"
        except DeadlineError as exc:
            stop_reason = exc.stop_reason
        finally:
            duration = elapsed()
            current = self.store.task_row(task_id)
            terminal = stop_reason in {"upper_bound_reached", "queues_exhausted", "low_increment_3_batches"}
            self.store.update_task(
                task_id,
                status="collection_completed" if terminal else "paused",
                stop_reason=stop_reason or "manual_stop",
                collection_stop_reason=stop_reason or "manual_stop",
                updated_at=iso_utc(self.now()),
                finished_at=None,
                collection_elapsed_seconds=float(current["collection_elapsed_seconds"]) + duration,
                total_elapsed_seconds=float(current["total_elapsed_seconds"]) + duration,
            )
        refreshed = self.store.task_row(task_id)
        run_dir_value = str(refreshed["run_dir"] or "")
        agent_queue_refresh = (
            refresh_agent_reach_queue(Path(run_dir_value), self.store, task_id)
            if run_dir_value
            else {"status": "skipped", "reason": "task_has_no_run_dir"}
        )
        external_import = (
            _import_external_agent_records(Path(run_dir_value), self.store, task_id)
            if run_dir_value
            else {"files_scanned": 0, "records_seen": 0, "new_valid": 0}
        )
        post_collection_duration = max(0.0, elapsed() - duration)
        if post_collection_duration:
            current = self.store.task_row(task_id)
            self.store.update_task(
                task_id,
                updated_at=iso_utc(self.now()),
                total_elapsed_seconds=(
                    float(current["total_elapsed_seconds"]) + post_collection_duration
                ),
            )
        receipt = build_receipt(self.store, task_id)
        receipt["youtube_execution"] = {
            "configured_worker_upper_bound": int(
                self.youtube_config.get("max_workers") or 1
            ),
            "actual_workers": 1,
            "execution_mode": "sequential_checkpoint_safe",
        }
        receipt["agent_reach_queue_refresh"] = agent_queue_refresh
        receipt["external_agent_import"] = external_import
        return receipt

    def _run_batch(
        self,
        task: Mapping[str, Any],
        batch: Mapping[str, Any],
        enforce_deadlines: Callable[[], None],
        reminder: NonBlockingReminder,
        scope_max: int,
        remaining_seconds: Callable[[], float],
    ) -> None:
        task_id = str(task["task_id"])
        batch_id = str(batch["batch_id"])
        started = iso_utc(self.now())
        self.store.update_batch(
            batch_id, status="running", started_at=batch.get("started_at") or started, updated_at=started, error=None
        )
        counters = {
            "raw": int(batch.get("raw_candidate_count") or 0),
            "new": int(batch.get("new_valid_count") or 0),
            "duplicates": int(batch.get("duplicate_count") or 0),
            "pages": int(batch.get("page_count") or 0),
            "requests": int(batch.get("request_count") or 0),
            "quota": int(batch.get("quota_units") or 0),
        }
        target_total_max = int(task["research_plan"]["sample_target"]["total_valid_max"])

        def should_stop() -> None:
            enforce_deadlines()
            if self.store.valid_count(task_id, scope=str(batch["scope"])) >= scope_max:
                raise ScopeUpperReached("scope upper bound reached")
            reminder.maybe(
                {
                    "task_id": task_id,
                    "batch_id": batch_id,
                    "valid_voices": self.store.valid_count(task_id),
                    "target_valid_max": target_total_max,
                }
            )

        def emit(comment: Mapping[str, Any]) -> None:
            should_stop()
            _, new_unique, new_valid = self.store.insert_comment(task_id, batch, comment, now=self.now())
            counters["raw"] += 1
            if new_valid:
                counters["new"] += 1
            if not new_unique:
                counters["duplicates"] += 1

        def save_checkpoint(state: Mapping[str, Any]) -> None:
            self.store.save_checkpoint(task_id, batch_id, state)

        def before_request(operation: str, units: int) -> None:
            should_stop()
            current = self.now()
            daily_limit = int(self.youtube_config.get("daily_quota_units") or task["daily_quota_units"])
            reserve = max(
                MIN_YOUTUBE_QUOTA_RESERVE,
                int(self.youtube_config.get("quota_reserve") or MIN_YOUTUBE_QUOTA_RESERVE),
            )
            level_budget = task["collection_policy"]["youtube_api_budget"]
            if operation in {"commentThreads.list", "comments.list"}:
                used = self.store.quota_units_for_operations(
                    task_id, ("commentThreads.list", "comments.list")
                )
                if used + units > int(level_budget["comment_request_budget"]):
                    raise QuotaLimitError("YouTube 评论请求已达 %s 档位预算" % task["research_level"])
            if operation == "search.list":
                if not bool(self.youtube_config.get("search_enabled")):
                    raise QuotaLimitError("YouTube 官方 search 默认关闭")
                if self.store.operation_count(task_id, "search.list") >= int(level_budget["search_call_max"]):
                    raise QuotaLimitError("YouTube search 已达 %s 档位调用上限" % task["research_level"])
            quota_state: Dict[str, int]
            if self.global_quota_ledger_path is not None:
                with YoutubeGlobalQuotaLedger(self.global_quota_ledger_path) as global_ledger:
                    quota_state = global_ledger.reserve(
                        units,
                        daily_limit,
                        reserve,
                        current,
                        task_id,
                        batch_id,
                        operation,
                    )
            else:
                used_before = self.store.quota_used_on(task_id, current)
                if used_before + units > daily_limit - reserve:
                    raise QuotaLimitError("YouTube quota 将触及固定保留量")
                quota_state = {
                    "used_before": used_before,
                    "used_after": used_before + units,
                }
            self.store.record_quota(
                task_id,
                batch_id,
                "youtube",
                operation,
                units,
                cost_status="quota_only",
                pricing_basis="YouTube Data API quota usage; no per-request monetary charge is recorded.",
                occurred_at=current,
                metadata={
                    "accounting_scope": (
                        "shared_user_config_daily_ledger"
                        if self.global_quota_ledger_path is not None
                        else "task_local_fallback"
                    ),
                    "global_daily_used_before": quota_state["used_before"],
                    "global_daily_used_after": quota_state["used_after"],
                    "daily_limit": daily_limit,
                    "fixed_reserve": reserve,
                    "available_before_reserve_after": max(
                        0, daily_limit - reserve - quota_state["used_after"]
                    ),
                },
            )
            counters["requests"] += 1
            counters["quota"] += units

        if str(batch["source"]) == "last30days" or str(batch["backend"]) == "last30days":
            self._run_last30days_batch(
                task, batch, counters, emit, before_request, should_stop, remaining_seconds
            )
            self._persist_batch_counters(batch_id, counters, "last30days")
            self.store.update_batch(
                batch_id,
                status="completed",
                backend="last30days",
                finished_at=iso_utc(self.now()),
                updated_at=iso_utc(self.now()),
                error=None,
            )
            return

        backend = str(batch["backend"])
        used_backend = backend
        page_start = counters["pages"]
        api_error: Optional[CollectorError] = None
        api_succeeded = False
        batch_metadata = batch.get("metadata") if isinstance(batch.get("metadata"), Mapping) else {}
        fallback_for = str(batch_metadata.get("fallback_for_batch_id") or "")
        if backend == "yt-dlp" and fallback_for:
            official_row = self.store.connection.execute(
                "SELECT status FROM batches WHERE task_id=? AND batch_id=?",
                (task_id, fallback_for),
            ).fetchone()
            if official_row is not None and str(official_row["status"]) == "completed":
                self._persist_batch_counters(batch_id, counters, backend)
                self.store.update_batch(
                    batch_id,
                    status="completed",
                    backend=backend,
                    finished_at=iso_utc(self.now()),
                    updated_at=iso_utc(self.now()),
                    error=None,
                )
                return
        official_candidate = backend in {"auto", "youtube-data-api"} and bool(batch.get("video_id"))

        def retry_wait(delay: float) -> None:
            should_stop()
            allowed = remaining_seconds()
            wait_for = min(max(0.0, float(delay)), allowed)
            if wait_for:
                time.sleep(wait_for)
            should_stop()

        if official_candidate and self.api_key:
            try:
                api = YoutubeDataApiCollector(
                    self.api_key,
                    self.http_client,
                    timeout=min(self.http_timeout, remaining_seconds()),
                    timeout_provider=remaining_seconds,
                    retry_wait=retry_wait,
                )
                result = api.collect(
                    str(batch["video_id"]),
                    self.store.checkpoint(task_id, batch_id),
                    emit,
                    save_checkpoint,
                    before_request,
                    should_stop,
                )
                counters["pages"] += int(result.get("page_count") or 0)
                used_backend = "youtube-data-api"
                api_succeeded = True
                self.store.clear_checkpoint(task_id, batch_id)
            except (ScopeUpperReached, DeadlineError, StopCollection):
                self._persist_batch_counters(batch_id, counters, used_backend)
                raise
            except QuotaLimitError as exc:
                api_error = exc
            except CollectorError as exc:
                api_error = exc
        elif official_candidate:
            api_error = ConfigurationError("YouTube 官方通道等待本机 API key")
        elif backend == "youtube-data-api":
            raise ConfigurationError("youtube-data-api batch 缺少 video_id")

        if official_candidate and not api_succeeded:
            assert api_error is not None
            self._enqueue_ytdlp_fallback(task, batch, api_error)
            self._persist_batch_counters(batch_id, counters, backend)
            self.store.update_batch(
                batch_id,
                status="paused",
                backend=backend,
                finished_at=None,
                updated_at=iso_utc(self.now()),
                error="youtube_official_pending: " + redact_text(api_error, (self.api_key,)),
            )
            return

        need_fallback = backend == "yt-dlp" or (backend == "auto" and not official_candidate)
        if need_fallback:
            target = str(
                batch.get("video_url")
                or ("https://www.youtube.com/watch?v=" + str(batch["video_id"]) if batch.get("video_id") else "")
                or batch.get("query_text")
                or ""
            )
            fallback = YtDlpCollector(
                self.runner,
                self.yt_dlp_binary,
                timeout=min(120.0, remaining_seconds()),
            )
            try:
                result = fallback.collect(target, emit, should_stop)
                counters["pages"] += int(result.get("page_count") or 0)
                counters["requests"] += int(result.get("request_count") or 0)
                used_backend = "yt-dlp"
                self.store.record_quota(
                    task_id,
                    batch_id,
                    "youtube",
                    "yt-dlp",
                    0,
                    cost_status="not_metered",
                    pricing_basis="Local yt-dlp fallback has no collector-recorded provider meter; infrastructure and network costs are excluded.",
                    metadata={
                        "fallback_from": (
                            batch.get("metadata", {}).get("fallback_for_batch_id")
                            if isinstance(batch.get("metadata"), Mapping)
                            else None
                        )
                    },
                )
                self.store.clear_checkpoint(task_id, batch_id)
            except (ScopeUpperReached, DeadlineError, StopCollection):
                self._persist_batch_counters(batch_id, counters, used_backend)
                raise
            except CollectorError as fallback_error:
                self._persist_batch_counters(batch_id, counters, used_backend)
                raise fallback_error
        batch_metadata = batch.get("metadata") if isinstance(batch.get("metadata"), Mapping) else {}
        if api_succeeded or batch_metadata.get("discovery_fallback") == "yt-dlp-search":
            discovery_anchor = self._youtube_search_anchor(task_id, batch)
            search_error = self._expand_youtube_search_for_scope(
                task,
                discovery_anchor,
                before_request,
                should_stop,
                remaining_seconds,
                exclude_batch_id=batch_id,
            )
            if (
                bool(self.youtube_config.get("search_enabled"))
                and self._youtube_video_candidate_gap(
                    task,
                    str(batch["scope"]),
                    exclude_batch_id=batch_id,
                ) > 0
            ):
                self._enqueue_ytdlp_search(task, discovery_anchor, search_error)
        if backend == "external":
            raise CollectorError("external batch 只能由外部导入，不能由 run 执行")
        self._persist_batch_counters(batch_id, counters, used_backend)
        self.store.update_batch(
            batch_id,
            status="completed",
            backend=used_backend,
            page_count=max(page_start, counters["pages"]),
            finished_at=iso_utc(self.now()),
            updated_at=iso_utc(self.now()),
            error=None,
        )

    def _run_last30days_batch(
        self,
        task: Mapping[str, Any],
        batch: Mapping[str, Any],
        counters: Dict[str, int],
        emit: Callable[[Mapping[str, Any]], None],
        before_request: Callable[[str, int], None],
        should_stop: Callable[[], None],
        remaining_seconds: Callable[[], float],
    ) -> None:
        should_stop()
        runner = self.runner or default_runner
        if self._last30days_runtime is None:
            self._last30days_runtime = detect_last30days_python(
                runner,
                timeout_provider=remaining_seconds,
            )
        runtime = self._last30days_runtime
        if not runtime["available"]:
            raise CollectorError("last30days 需要 Python 3.12+，doctor 未找到可用解释器")
        script = Path(os.environ.get("LAST30DAYS_SCRIPT", str(DEFAULT_LAST30DAYS_SCRIPT))).expanduser()
        if not script.is_file():
            raise CollectorError("last30days 脚本不存在：%s" % script)
        run_dir = Path(str(task.get("run_dir") or self.store.path.parent))
        output_dir = run_dir / "last30days"
        _secure_directory(output_dir)
        output = output_dir / (str(batch["query_id"]) + ".json")
        plan_path = output_dir / (str(batch["query_id"]) + ".plan.json")
        metadata = batch.get("metadata") if isinstance(batch.get("metadata"), Mapping) else {}
        days = int(metadata.get("days") or scope_window_days(str(batch["scope"])))
        as_of = str(metadata.get("as_of_utc_date") or parse_timestamp(task["end_at"]).date().isoformat())
        query_text = str(batch["query_text"])
        write_json(
            plan_path,
            {
                "intent": "opinion",
                "freshness_mode": "balanced_recent",
                "cluster_mode": "debate",
                "raw_topic": query_text,
                "subqueries": [
                    {
                        "label": str(batch["query_id"]),
                        "search_query": query_text,
                        "ranking_query": query_text,
                        "sources": list(PRIMARY_SOCIAL_PLATFORMS),
                        "weight": 1.0,
                    }
                ],
            },
        )
        command = [
            str(runtime["selected"]),
            str(script),
            query_text,
            "--emit=json",
            "--json-profile=raw",
            "--days=%d" % days,
            "--as-of=%s" % as_of,
            "--max-results=200",
            "--max-per-source=100",
            "--search=reddit,x,youtube,tiktok,instagram",
            "--plan",
            str(plan_path),
            "--output",
            str(output),
            "--save-dir",
            str(output_dir),
        ]
        level = str(task["research_level"])
        if level == "quick":
            command.append("--quick")
        elif level == "deep":
            command.append("--deep")
        try:
            completed = runner(command, max(0.1, remaining_seconds()))
        except subprocess.TimeoutExpired:
            should_stop()
            raise DeadlineError("collection_deadline")
        except (OSError, subprocess.SubprocessError) as exc:
            raise CollectorError("last30days 执行失败：%s" % redact_text(exc))
        finally:
            # last30days owns its internal file creation.  The private parent
            # prevents exposure while it runs; normalize every retained child
            # immediately afterwards so later sharing cannot widen permissions.
            _secure_runtime_tree(output_dir)
        counters["requests"] += 1
        self.store.record_quota(
            str(task["task_id"]),
            str(batch["batch_id"]),
            "last30days",
            "research.run",
            1,
            cost_status="unknown",
            pricing_basis="last30days backend/provider charges were not supplied to the collector.",
        )
        if completed.returncode != 0:
            raise CollectorError("last30days 返回失败：%s" % redact_text(completed.stderr or completed.stdout))
        should_stop()
        if output.is_file():
            raw_text = output.read_text(encoding="utf-8")
        else:
            raw_text = completed.stdout
            _atomic_write_text(output, raw_text, mode=0o600)
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise CollectorError("last30days 未返回合法 raw JSON：%s" % exc)
        video_ids = _extract_last30days_payload(payload, batch, emit)
        counters["pages"] += 1
        self._enqueue_youtube_videos(task, batch, video_ids)
        search_error = self._expand_youtube_search_for_scope(
            task,
            batch,
            before_request,
            should_stop,
            remaining_seconds,
        )
        if not video_ids and not self._youtube_pending_video_ids(
            str(task["task_id"]), str(batch["scope"])
        ):
            self._enqueue_ytdlp_search(task, batch, search_error)

    def _youtube_pending_video_ids(
        self,
        task_id: str,
        scope: str,
        *,
        exclude_batch_id: Optional[str] = None,
    ) -> set[str]:
        parameters: List[Any] = [task_id, scope]
        exclusion = ""
        if exclude_batch_id:
            exclusion = " AND batch_id!=?"
            parameters.append(exclude_batch_id)
        rows = self.store.connection.execute(
            """SELECT DISTINCT video_id FROM batches
            WHERE task_id=? AND scope=? AND source='youtube'
              AND video_id IS NOT NULL AND video_id!=''
              AND status IN ('planned','running','paused')%s""" % exclusion,
            tuple(parameters),
        ).fetchall()
        return {str(row["video_id"]) for row in rows if str(row["video_id"] or "").strip()}

    def _youtube_video_candidate_gap(
        self,
        task: Mapping[str, Any],
        scope: str,
        *,
        exclude_batch_id: Optional[str] = None,
    ) -> int:
        """Return conservative video candidates needed to reach a route minimum.

        A queued video is credited as at most one future valid voice.  This is
        deliberately conservative: a comment-rich video can close the gap
        sooner, while an empty video is replaced after its batch completes.
        Both the route upper bound and the union upper bound cap discovery.
        """
        target = task["research_plan"]["sample_target"]
        route = target["per_scope"][scope]
        scope_valid = self.store.valid_count(str(task["task_id"]), scope=scope)
        union_valid = self.store.valid_count(str(task["task_id"]))
        minimum_gap = max(0, int(route["valid_min"]) - scope_valid)
        scope_capacity = max(0, int(route["valid_max"]) - scope_valid)
        union_capacity = max(0, int(target["total_valid_max"]) - union_valid)
        admissible_gap = min(minimum_gap, scope_capacity, union_capacity)
        pending = len(
            self._youtube_pending_video_ids(
                str(task["task_id"]),
                scope,
                exclude_batch_id=exclude_batch_id,
            )
        )
        return max(0, admissible_gap - pending)

    def _youtube_search_anchor(self, task_id: str, batch: Mapping[str, Any]) -> Mapping[str, Any]:
        """Resolve a generated video/fallback batch to its broad discovery batch."""
        current = dict(batch)
        seen: set[str] = set()
        for _ in range(3):
            metadata = current.get("metadata") if isinstance(current.get("metadata"), Mapping) else {}
            parent_id = str(
                metadata.get("discovered_by_batch")
                or metadata.get("fallback_for_batch_id")
                or ""
            ).strip()
            if not parent_id or parent_id in seen:
                break
            seen.add(parent_id)
            row = self.store.connection.execute(
                "SELECT * FROM batches WHERE task_id=? AND batch_id=?",
                (task_id, parent_id),
            ).fetchone()
            if row is None:
                break
            current = self.store.batch_payload(row)
        return current

    def _expand_youtube_search_for_scope(
        self,
        task: Mapping[str, Any],
        discovery_batch: Mapping[str, Any],
        before_request: Callable[[str, int], None],
        should_stop: Callable[[], None],
        remaining_seconds: Callable[[], float],
        *,
        exclude_batch_id: Optional[str] = None,
    ) -> Optional[str]:
        """Page official search only while a route minimum still lacks candidates."""
        if not bool(self.youtube_config.get("search_enabled")) or not self.api_key:
            return None
        task_id = str(task["task_id"])
        scope = str(discovery_batch["scope"])
        query_text = re.sub(
            r"^ytsearch\d*:", "", str(discovery_batch.get("query_text") or "").strip()
        ).strip()
        if not query_text:
            return None
        anchor = self._youtube_search_anchor(task_id, discovery_batch)
        anchor_id = str(anchor.get("batch_id") or discovery_batch.get("batch_id") or "")
        if not anchor_id:
            return None
        state = self.store.checkpoint(task_id, anchor_id, key="youtube_search_discovery")
        if state.get("exhausted"):
            return None
        page_token = state.get("next_page_token") or None
        level_budget = task["collection_policy"]["youtube_api_budget"]
        remaining_calls = max(
            0,
            int(level_budget["search_call_max"])
            - self.store.operation_count(task_id, "search.list"),
        )
        if remaining_calls <= 0:
            return "YouTube search 已达 %s 档位调用上限" % task["research_level"]

        def search_retry_wait(delay: float) -> None:
            should_stop()
            allowed = remaining_seconds()
            wait_for = min(max(0.0, float(delay)), allowed)
            if wait_for:
                time.sleep(wait_for)
            should_stop()

        api = YoutubeDataApiCollector(
            self.api_key,
            self.http_client,
            timeout=min(self.http_timeout, remaining_seconds()),
            timeout_provider=remaining_seconds,
            retry_wait=search_retry_wait,
        )
        # Discover incrementally so one scope cannot consume the task-wide
        # search budget before the other scopes receive a turn or before real
        # comment yield is observed. The persisted nextPageToken lets the next
        # completed broad/YouTube batch continue from the following page.
        page_budget = min(1, remaining_calls)
        calls = 0
        try:
            while calls < page_budget:
                should_stop()
                needed = self._youtube_video_candidate_gap(
                    task,
                    scope,
                    exclude_batch_id=exclude_batch_id,
                )
                if needed <= 0:
                    break
                search = api.search_videos(
                    query_text,
                    before_request,
                    max_results=min(
                        needed,
                        int(self.youtube_config.get("max_results") or 50),
                    ),
                    page_token=page_token,
                )
                calls += 1
                self._enqueue_youtube_videos(
                    task,
                    anchor,
                    list(search.get("video_ids") or []),
                    max_new=needed,
                )
                page_token = search.get("next_page_token") or None
                self.store.save_checkpoint(
                    task_id,
                    anchor_id,
                    {
                        "next_page_token": page_token,
                        "exhausted": not bool(page_token),
                        "last_query_text": query_text,
                    },
                    key="youtube_search_discovery",
                )
                if not page_token:
                    break
        except (QuotaLimitError, CollectorError) as exc:
            # Optional discovery must not terminate Reddit/X/yt-dlp queues.
            return redact_text(exc, (self.api_key,))
        return None

    def _enqueue_youtube_videos(
        self,
        task: Mapping[str, Any],
        discovery_batch: Mapping[str, Any],
        video_ids: Sequence[str],
        *,
        max_new: Optional[int] = None,
    ) -> List[str]:
        task_id = str(task["task_id"])
        existing_rows = self.store.connection.execute(
            "SELECT scope,video_id FROM batches WHERE task_id=? AND source='youtube' AND video_id IS NOT NULL",
            (task_id,),
        ).fetchall()
        existing = {(str(row["scope"]), str(row["video_id"])) for row in existing_rows}
        added: List[str] = []
        for video_id in video_ids:
            if max_new is not None and len(added) >= max(0, int(max_new)):
                break
            normalized = str(video_id).strip()
            scope_video = (str(discovery_batch["scope"]), normalized)
            if not normalized or scope_video in existing:
                continue
            self.store.add_batch(
                task_id,
                {
                    "source": "youtube",
                    "backend": "auto",
                    "scope": discovery_batch["scope"],
                    "query_id": "%s_yt_%s" % (discovery_batch["query_id"], normalized),
                    "query_text": discovery_batch["query_text"],
                    "video_id": normalized,
                    "video_url": "https://www.youtube.com/watch?v=" + normalized,
                    "priority": int(discovery_batch.get("priority") or 100) + 100,
                    "metadata": {"discovered_by_batch": discovery_batch["batch_id"]},
                },
            )
            existing.add(scope_video)
            added.append(normalized)
        return added

    def _enqueue_ytdlp_fallback(
        self,
        task: Mapping[str, Any],
        official_batch: Mapping[str, Any],
        reason: CollectorError,
    ) -> None:
        """Create an independent best-effort fallback without consuming the API checkpoint."""
        task_id = str(task["task_id"])
        official_batch_id = str(official_batch["batch_id"])
        digest = hashlib.sha256((task_id + "\0" + official_batch_id).encode("utf-8")).hexdigest()[:18]
        fallback_batch_id = "cvb_ytdlp_%s" % digest
        if self.store.connection.execute(
            "SELECT 1 FROM batches WHERE batch_id=? LIMIT 1", (fallback_batch_id,)
        ).fetchone() is not None:
            return
        self.store.add_batch(
            task_id,
            {
                "batch_id": fallback_batch_id,
                "source": "youtube",
                "backend": "yt-dlp",
                "scope": official_batch["scope"],
                "query_id": str(official_batch["query_id"]) + "__ytdlp_fallback",
                "query_text": official_batch.get("query_text") or "",
                "video_id": official_batch.get("video_id"),
                "video_url": official_batch.get("video_url")
                or (
                    "https://www.youtube.com/watch?v=" + str(official_batch["video_id"])
                    if official_batch.get("video_id")
                    else ""
                ),
                "priority": int(official_batch.get("priority") or 100) + 1,
                "metadata": {
                    "fallback_for_batch_id": official_batch_id,
                    "fallback_reason": redact_text(reason, (self.api_key,)),
                    "official_backend": str(official_batch.get("backend") or "auto"),
                },
            },
        )

    def _enqueue_ytdlp_search(
        self,
        task: Mapping[str, Any],
        discovery_batch: Mapping[str, Any],
        discovery_error: Optional[str] = None,
    ) -> None:
        task_id = str(task["task_id"])
        query_id = str(discovery_batch["query_id"]) + "_ytsearch"
        existing = self.store.connection.execute(
            "SELECT 1 FROM batches WHERE task_id=? AND query_id=? LIMIT 1",
            (task_id, query_id),
        ).fetchone()
        if existing is not None:
            return
        query_text = str(discovery_batch.get("query_text") or "").strip()
        if not query_text:
            return
        self.store.add_batch(
            task_id,
            {
                "source": "youtube",
                "backend": "yt-dlp",
                "scope": discovery_batch["scope"],
                "query_id": query_id,
                "query_text": query_text if query_text.startswith("ytsearch") else "ytsearch50:" + query_text,
                "priority": int(discovery_batch.get("priority") or 100) + 150,
                "metadata": {
                    "discovered_by_batch": discovery_batch["batch_id"],
                    "discovery_fallback": "yt-dlp-search",
                    "official_search_error": discovery_error,
                },
            },
        )

    def _persist_batch_counters(self, batch_id: str, counters: Mapping[str, int], backend: str) -> None:
        self.store.update_batch(
            batch_id,
            backend=backend,
            raw_candidate_count=int(counters["raw"]),
            new_valid_count=int(counters["new"]),
            duplicate_count=int(counters["duplicates"]),
            page_count=int(counters["pages"]),
            request_count=int(counters["requests"]),
            quota_units=int(counters["quota"]),
            updated_at=iso_utc(self.now()),
        )


def prepare_coding(
    store: CollectorStore,
    task_id: str,
    output_dir: Path,
    batch_size: int = 200,
    include_coded: bool = False,
) -> Dict[str, Any]:
    if batch_size <= 0:
        raise ConfigurationError("batch_size 必须为正整数")
    started = time.monotonic()
    task_row = store.task_row(task_id)
    if task_row["run_dir"]:
        _import_external_agent_records(Path(str(task_row["run_dir"])), store, task_id)
    technical_auto_excluded_count = store.autocode_technical_exclusions(task_id)
    records = store.coding_records(task_id, include_coded=include_coded)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = iso_utc()
    files: List[Dict[str, Any]] = []
    for offset in range(0, len(records), batch_size):
        chunk = records[offset : offset + batch_size]
        batch_id = "coding_%04d" % (offset // batch_size + 1)
        path = output_dir / (batch_id + ".json")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "coding_batch_id": batch_id,
            "generated_at": generated_at,
            "hard_dedupe_policy": "identity_only_no_text_only_or_parent_url_only",
            "records": chunk,
        }
        write_json(path, payload)
        store.mark_prepared([str(item["record_id"]) for item in chunk], batch_id)
        files.append({"coding_batch_id": batch_id, "path": str(path), "record_count": len(chunk)})
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "generated_at": generated_at,
        "record_count": len(records),
        "technical_auto_excluded_count": technical_auto_excluded_count,
        "files": files,
    }
    manifest_path = output_dir / "coding_manifest.json"
    write_json(manifest_path, manifest)
    task = store.task_row(task_id)
    store.update_task(
        task_id,
        updated_at=iso_utc(),
        total_elapsed_seconds=float(task["total_elapsed_seconds"]) + (time.monotonic() - started),
    )
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _external_import_targets(payload: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Read exact route bindings attached to one shared deep-read output."""
    raw_targets = payload.get("output_import_targets")
    if not isinstance(raw_targets, list):
        raw_targets = payload.get("import_targets")
    result: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    if isinstance(raw_targets, list):
        for item in raw_targets:
            if not isinstance(item, Mapping):
                continue
            scope = str(item.get("scope_id") or item.get("scope") or "").strip()
            query_id = str(item.get("query_id") or "").strip()
            if not scope or not query_id or (scope, query_id) in seen:
                continue
            seen.add((scope, query_id))
            result.append({"scope_id": scope, "query_id": query_id})
    return result


def _import_external_agent_records(run_dir: Path, store: CollectorStore, task_id: str) -> Dict[str, Any]:
    """Import agent-reach handoffs without crossing task or route upper bounds.

    A per-group cursor is retained even after completion so an unchanged file
    is not scanned again.  If the handoff file changes, hard identity dedupe
    makes replay safe while newly appended records can still be imported.
    """
    root = run_dir / "agent_reach"
    if not root.is_dir():
        return {"files_scanned": 0, "records_seen": 0, "new_valid": 0, "status": "no_files"}
    task = store.task_payload(task_id)
    target = task["research_plan"]["sample_target"]
    total_max = int(target["total_valid_max"])
    per_scope = target["per_scope"]
    health_artifacts = {"doctor.json", "check_update.json"}
    files = sorted(
        path
        for path in root.glob("*.json")
        if path.is_file() and path.name not in health_artifacts
    )
    seen = 0
    new_valid_total = 0
    imported_files = 0
    paused_batches: List[Dict[str, Any]] = []
    total_cap_reached = False
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CollectorError("agent-reach 导入文件无效 %s：%s" % (path, redact_text(exc)))
        if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
            raise CollectorError("agent-reach 导入文件必须包含 records 数组：%s" % path)
        records = [item for item in payload["records"] if isinstance(item, Mapping)]
        default_scope = str(payload.get("scope_id") or "")
        default_query = str(payload.get("query_id") or path.stem)
        payload_targets = _external_import_targets(payload)
        groups: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
        for record in records:
            record_targets = _external_import_targets(record)
            if record_targets:
                targets = record_targets
            elif record.get("scope_id") or record.get("query_id"):
                targets = [
                    {
                        "scope_id": str(record.get("scope_id") or default_scope),
                        "query_id": str(record.get("query_id") or default_query),
                    }
                ]
            elif payload_targets:
                targets = payload_targets
            else:
                targets = [{"scope_id": default_scope, "query_id": default_query}]
            seen_targets: set[Tuple[str, str]] = set()
            for target_row in targets:
                scope = str(target_row.get("scope_id") or default_scope)
                query_id = str(target_row.get("query_id") or default_query)
                if scope not in SCOPES:
                    raise CollectorError("agent-reach record scope_id 无效：%s" % scope)
                marker = (scope, query_id)
                if marker in seen_targets:
                    continue
                seen_targets.add(marker)
                groups.setdefault(marker, []).append(record)
        for (scope, query_id), children in groups.items():
            digest = hashlib.sha256((str(path.resolve()) + "\0" + scope + "\0" + query_id).encode("utf-8")).hexdigest()[:18]
            batch_id = "arimport_" + digest
            existing = store.connection.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            if existing is None:
                store.add_batch(
                    task_id,
                    {
                        "batch_id": batch_id,
                        "source": "agent-reach",
                        "backend": "external",
                        "scope": scope,
                        "query_id": query_id,
                        "query_text": str(payload.get("query_text") or ""),
                        "priority": 900,
                        "metadata": {"input_path": str(path)},
                    },
                )
                existing = store.connection.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
            batch = store.batch_payload(existing)
            input_digest = hashlib.sha256(compact_json(children).encode("utf-8")).hexdigest()
            cursor = store.checkpoint(task_id, batch_id, key="external_import")
            if cursor.get("input_sha256") == input_digest:
                offset = min(len(children), max(0, int(cursor.get("record_offset") or 0)))
            else:
                offset = 0
            new_valid = 0
            duplicates = 0
            processed_to = offset
            pause_reason: Optional[str] = None
            for record_index in range(offset, len(children)):
                if store.valid_count(task_id) >= total_max:
                    pause_reason = "total_upper_reached"
                    total_cap_reached = True
                    break
                scope_max = int(per_scope[scope]["valid_max"])
                if store.valid_count(task_id, scope=scope) >= scope_max:
                    pause_reason = "scope_upper_reached"
                    break
                record = children[record_index]
                normalized = dict(record)
                normalized["source"] = str(record.get("platform") or record.get("source") or "unknown")
                normalized["content_id"] = str(
                    record.get("content_id") or record.get("comment_id") or ""
                )
                normalized["parent_content_id"] = record.get("parent_content_id")
                normalized["author_label"] = record.get("author_label")
                normalized["text"] = record.get("exact_text") or record.get("text") or ""
                normalized["source_position"] = "%s:%d" % (path.name, record_index)
                _, new_unique, became_valid = store.insert_comment(task_id, batch, normalized)
                new_valid += int(became_valid)
                duplicates += int(not new_unique)
                seen += 1
                processed_to = record_index + 1
                store.save_checkpoint(
                    task_id,
                    batch_id,
                    {
                        "input_sha256": input_digest,
                        "input_size": len(children),
                        "record_offset": processed_to,
                    },
                    key="external_import",
                )
            prior_new = int(batch.get("new_valid_count") or 0)
            prior_duplicates = int(batch.get("duplicate_count") or 0)
            completed = pause_reason is None and processed_to >= len(children)
            store.save_checkpoint(
                task_id,
                batch_id,
                {
                    "input_sha256": input_digest,
                    "input_size": len(children),
                    "record_offset": processed_to,
                    "completed": completed,
                },
                key="external_import",
            )
            store.update_batch(
                batch_id,
                status="completed" if completed else "paused",
                raw_candidate_count=max(int(batch.get("raw_candidate_count") or 0), processed_to),
                new_valid_count=prior_new + new_valid,
                duplicate_count=prior_duplicates + duplicates,
                finished_at=iso_utc() if completed else None,
                updated_at=iso_utc(),
                error=pause_reason,
            )
            new_valid_total += new_valid
            if pause_reason:
                paused_batches.append(
                    {
                        "batch_id": batch_id,
                        "scope_id": scope,
                        "reason": pause_reason,
                        "record_offset": processed_to,
                        "input_size": len(children),
                    }
                )
            if total_cap_reached:
                break
        imported_files += 1
        if total_cap_reached:
            break
    return {
        "status": "paused_at_upper_bound" if paused_batches else "ok",
        "files_scanned": len(files),
        "files_imported": imported_files,
        "records_seen": seen,
        "new_valid": new_valid_total,
        "paused_batches": paused_batches,
    }


def refresh_agent_reach_queue(
    run_dir: Path,
    store: CollectorStore,
    task_id: str,
    max_targets_per_task: int = 25,
) -> Dict[str, Any]:
    """Attach concrete Reddit/X targets discovered by broad collection.

    The collector does not pretend to execute the agent-reach skill itself.
    Instead it turns the generic handoff into an auditable, URL-level queue
    that the parent Codex workflow must execute with that skill.
    """
    queue_path = run_dir / "agent_reach_queue.json"
    if not queue_path.is_file():
        return {"status": "skipped", "reason": "queue_missing", "target_url_count": 0}
    try:
        payload = json.loads(queue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorError("agent-reach 队列无效：%s" % redact_text(exc))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("tasks"), list):
        raise CollectorError("agent-reach 队列必须包含 tasks 数组")

    route_specs: List[Dict[str, str]] = []
    seen_routes: set[Tuple[str, str]] = set()
    for raw_task in payload["tasks"]:
        if not isinstance(raw_task, Mapping):
            continue
        declared_targets = _external_import_targets(raw_task)
        if not declared_targets:
            declared_targets = [
                {
                    "scope_id": str(raw_task.get("scope_id") or ""),
                    "query_id": str(raw_task.get("query_id") or ""),
                }
            ]
        query_texts = raw_task.get("query_texts")
        fallback_query_text = str(raw_task.get("query_text") or "")
        source_task_ids = raw_task.get("source_task_ids")
        fallback_task_id = str(raw_task.get("task_id") or "")
        for index, target in enumerate(declared_targets):
            scope = str(target.get("scope_id") or "").strip()
            query_id = str(target.get("query_id") or "").strip()
            if scope not in SCOPES or not query_id or (scope, query_id) in seen_routes:
                continue
            query_text = fallback_query_text
            if isinstance(query_texts, list) and index < len(query_texts):
                query_text = str(query_texts[index] or fallback_query_text)
            source_task_id = fallback_task_id
            if isinstance(source_task_ids, list) and index < len(source_task_ids):
                source_task_id = str(source_task_ids[index] or fallback_task_id)
            seen_routes.add((scope, query_id))
            route_specs.append(
                {
                    "scope_id": scope,
                    "query_id": query_id,
                    "query_text": query_text,
                    "source_task_id": source_task_id,
                }
            )

    grouped: Dict[str, Dict[str, Any]] = {}
    for route in route_specs:
        rows = store.connection.execute(
            """SELECT DISTINCT c.canonical_url,c.source,c.thread_id,c.content_id,
            c.first_seen_at
            FROM comments c
            JOIN comment_discoveries d ON d.record_id=c.record_id
            WHERE c.task_id=? AND d.scope=? AND d.query_id=? AND d.within_window=1
              AND c.source IN ('reddit','x')
              AND c.canonical_url IS NOT NULL AND c.canonical_url!=''
            ORDER BY c.first_seen_at,c.canonical_url LIMIT ?""",
            (
                task_id,
                route["scope_id"],
                route["query_id"],
                int(max_targets_per_task),
            ),
        ).fetchall()
        for row in rows:
            platform = normalize_platform(row["source"])
            url = canonicalize_url(row["canonical_url"])
            thread_id = str(row["thread_id"] or "").strip()
            identity = (
                "%s\0thread\0%s" % (platform, thread_id)
                if thread_id
                else "%s\0url\0%s" % (platform, url)
            )
            entry = grouped.setdefault(
                identity,
                {
                    "platform": platform,
                    "url": url,
                    "thread_id": thread_id or None,
                    "content_ids": set(),
                    "routes": {},
                    "query_texts": set(),
                    "source_task_ids": set(),
                    "first_seen_at": str(row["first_seen_at"] or ""),
                },
            )
            if row["content_id"]:
                entry["content_ids"].add(str(row["content_id"]))
            route_key = (route["scope_id"], route["query_id"])
            entry["routes"][route_key] = {
                "scope_id": route["scope_id"],
                "query_id": route["query_id"],
            }
            if route["query_text"]:
                entry["query_texts"].add(route["query_text"])
            if route["source_task_id"]:
                entry["source_task_ids"].add(route["source_task_id"])

    updated_tasks: List[Dict[str, Any]] = []
    for identity, entry in sorted(
        grouped.items(),
        key=lambda item: (
            item[1]["first_seen_at"],
            item[1]["platform"],
            item[1]["thread_id"] or item[1]["url"],
        ),
    ):
        routes = sorted(
            entry["routes"].values(),
            key=lambda item: (item["scope_id"], item["query_id"]),
        )
        digest = hashlib.sha256((task_id + "\0" + identity).encode("utf-8")).hexdigest()[:18]
        collection_scopes = sorted({item["scope_id"] for item in routes})
        query_ids = sorted({item["query_id"] for item in routes})
        target = {
            "platform": entry["platform"],
            "url": entry["url"],
            "thread_id": entry["thread_id"],
            "content_ids": sorted(entry["content_ids"]),
            "collection_scopes": collection_scopes,
            "query_ids": query_ids,
        }
        updated_tasks.append(
            {
                "task_id": "ar_thread_" + digest,
                "scope_id": routes[0]["scope_id"],
                "query_id": routes[0]["query_id"],
                "collection_scopes": collection_scopes,
                "query_ids": query_ids,
                "output_import_targets": routes,
                "source_task_ids": sorted(entry["source_task_ids"]),
                "query_texts": sorted(entry["query_texts"]),
                "status": "pending_agent_execution",
                "target_urls": [target],
                "target_count": 1,
                "output_path": "agent_reach/ar_thread_%s.json" % digest,
                "instruction": (
                    "使用 agent-reach 仅深读该 Reddit/X 父线程及完整可访问回复树一次；"
                    "输出文件保留 output_import_targets，使同一原声可导入全部适用采集路。"
                ),
            }
        )
    total_targets = len(updated_tasks)
    refreshed = dict(payload)
    refreshed["tasks"] = updated_tasks
    import_contract = dict(refreshed.get("import_contract") or {})
    import_contract["route_binding"] = (
        "Records may omit scope_id/query_id when the output preserves the task's "
        "output_import_targets; collector expands each hard-identity record to every exact route."
    )
    refreshed["import_contract"] = import_contract
    refreshed["targets_refreshed_at"] = iso_utc()
    write_json(queue_path, refreshed)
    return {
        "status": "ready_for_agent_execution" if total_targets else "no_discovered_targets",
        "queue_path": str(queue_path),
        "task_count": len(updated_tasks),
        "target_url_count": total_targets,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first_nested_value(value: Any, keys: Sequence[str]) -> Any:
    if isinstance(value, Mapping):
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
        for child in value.values():
            found = _first_nested_value(child, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_nested_value(child, keys)
            if found not in (None, ""):
                return found
    return None


def _source_artifact(path: Path) -> Dict[str, Any]:
    timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return {"path": str(path), "sha256": _sha256_file(path), "snapshot_at": iso_utc(timestamp)}


def _project_context(
    project_dir: Path,
    expected_dashboard_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    analysis_path = project_dir / "market_opportunity" / "07_opportunity_analysis.json"
    dashboard_path = project_dir / "market_opportunity" / "市场机会深挖看板.html"
    input_path = project_dir / "market_research" / "01_input_manifest.json"
    if not analysis_path.is_file() or not dashboard_path.is_file() or not input_path.is_file():
        raise CollectorError("物化 coding 缺少机会分析、原看板或输入 manifest")
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    input_manifest = json.loads(input_path.read_text(encoding="utf-8"))
    marketplace = str(
        _first_nested_value(input_manifest, ("marketplace", "site", "country"))
        or analysis.get("marketplace")
        or "US"
    ).upper()
    if marketplace == "GB":
        marketplace = "UK"
    language = str(
        _first_nested_value(input_manifest, ("listing_language", "language"))
        or analysis.get("listing_language")
        or "en"
    )
    keyword = str(
        analysis.get("keyword")
        or _first_nested_value(input_manifest, ("keyword", "category_keyword", "search_term"))
        or "unknown category"
    )
    category_node = analysis.get("category_node") or _first_nested_value(
        input_manifest, ("category_node", "node")
    )
    dashboard_artifact = _source_artifact(dashboard_path)
    expected_dashboard = str(expected_dashboard_sha256 or "").strip().casefold()
    if expected_dashboard and dashboard_artifact["sha256"].casefold() != expected_dashboard:
        raise CollectorError("原机会看板SHA-256与消费者声音plan基线不一致，已停止物化")
    return {
        "project_root": str(project_dir),
        "marketplace": marketplace,
        "listing_language": language,
        "category_keyword": keyword,
        "category_node": str(category_node) if category_node not in (None, "") else None,
        "opportunity_analysis": _source_artifact(analysis_path),
        "opportunity_dashboard": dashboard_artifact,
    }


def _agent_reach_query_id(value: Any) -> str:
    """Return the stable public query id used by plan, runs and discoveries."""

    query_id = str(value or "").strip()
    if not query_id:
        query_id = "import"
    return query_id if query_id.startswith("ar_") else "ar_" + query_id


def _coding_query_plan(
    store: CollectorStore,
    task_id: str,
    listing_language: str,
    end_at: datetime,
) -> Dict[str, Any]:
    lanes: List[Dict[str, Any]] = []
    task_topic = str(store.task_row(task_id)["topic"] or "target product category")
    all_intents = [
        "purchase_selection",
        "usage_scenario",
        "satisfaction_recommendation",
        "failure_complaint_return",
        "alternative_replacement",
        "diy_workaround",
        "feature_request",
        "reverse_need",
    ]
    for scope in SCOPES:
        rows = store.connection.execute(
            """SELECT query_text FROM batches WHERE task_id=? AND scope=? AND source='last30days'
            ORDER BY priority,batch_id""",
            (task_id, scope),
        ).fetchall()
        queries = []
        for row in rows:
            query = str(row["query_text"] or "")
            if query and query not in queries:
                queries.append(query)
        if not queries:
            queries = [task_topic + " " + scope]
        days = scope_window_days(scope)
        lanes.append(
            {
                "query_id": scope + "_primary",
                "scope_id": scope,
                "primary_tool": "last30days",
                "days": days,
                "as_of_utc_date": end_at.astimezone(timezone.utc).date().isoformat(),
                "start_at": iso_utc(end_at - timedelta(days=days)),
                "end_at": iso_utc(end_at),
                "queries": queries[:2],
                "intents": all_intents,
                "target_platforms": ["reddit", "x", "youtube", "tiktok", "instagram"],
            }
        )
    gaps_by_query_id: Dict[str, Dict[str, Any]] = {}

    def register_gap(
        raw_query_id: Any,
        scope_ids: Sequence[str],
        query: Any,
        reason: str,
    ) -> None:
        query_id = _agent_reach_query_id(raw_query_id)
        normalized_scopes = [scope for scope in SCOPES if scope in set(scope_ids)]
        if not normalized_scopes:
            return
        existing = gaps_by_query_id.get(query_id)
        if existing is not None:
            existing["scope_ids"] = [
                scope
                for scope in SCOPES
                if scope in set(existing["scope_ids"]) | set(normalized_scopes)
            ]
            if not existing.get("query") and query:
                existing["query"] = str(query)
            return
        gaps_by_query_id[query_id] = {
            "query_id": query_id,
            "scope_ids": normalized_scopes,
            "tool": "agent-reach",
            "reason": reason,
            "platform": "multi-platform",
            "query": str(query or "gap fill"),
        }

    run_dir = Path(str(store.task_row(task_id)["run_dir"] or store.path.parent))
    queue_path = run_dir / "agent_reach_queue.json"
    if queue_path.is_file():
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        for item in queue.get("tasks", []) if isinstance(queue, Mapping) else []:
            if not isinstance(item, Mapping) or str(item.get("scope_id")) not in SCOPES:
                continue
            targets = _external_import_targets(item)
            if targets:
                for target in targets:
                    register_gap(
                        target["query_id"],
                        [target["scope_id"]],
                        item.get("query_text"),
                        "定向深读并补齐 last30days 的正文、回复或平台覆盖缺口。",
                    )
                continue
            register_gap(
                item.get("query_id") or item.get("task_id"),
                [str(item["scope_id"])],
                item.get("query_text"),
                "定向深读并补齐 last30days 的正文、回复或平台覆盖缺口。",
            )

    # The queue is only a plan. Imported agent-reach files may declare more
    # precise route bindings (or be supplied independently), so materialize
    # every actual import batch as well. Source runs and voice discoveries use
    # this same id transformation, keeping their provenance contract aligned.
    for row in store.list_batches(task_id):
        batch = store.batch_payload(row)
        if normalize_platform(batch.get("source")) != "agent-reach":
            continue
        register_gap(
            batch.get("query_id"),
            [str(batch.get("scope") or "")],
            batch.get("query_text"),
            "agent-reach 实际导入批次的可追溯查询绑定。",
        )
    return {
        "query_language": listing_language,
        "primary_lanes": lanes,
        "gap_fill_queries": list(gaps_by_query_id.values()),
    }


def _last30days_platform_statuses(
    batch: Mapping[str, Any],
    raw_artifact: Optional[Path],
    fallback_status: str,
) -> List[Dict[str, Any]]:
    payload: Mapping[str, Any] = {}
    if raw_artifact is not None and raw_artifact.is_file():
        try:
            loaded = json.loads(raw_artifact.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            payload = {}
    raw_status = payload.get("source_status")
    status_by_platform: Dict[str, Mapping[str, Any]] = {}
    if isinstance(raw_status, Mapping):
        for name, value in raw_status.items():
            if isinstance(value, Mapping):
                status_by_platform[normalize_platform(name)] = value
    elif isinstance(raw_status, list):
        for value in raw_status:
            if not isinstance(value, Mapping):
                continue
            platform = normalize_platform(value.get("platform") or value.get("source"))
            if platform in QUANTITATIVE_PLATFORMS:
                status_by_platform[platform] = value
    item_counts: Dict[str, int] = {}
    by_source = payload.get("items_by_source")
    if isinstance(by_source, Mapping):
        for name, values in by_source.items():
            platform = normalize_platform(name)
            if platform in QUANTITATIVE_PLATFORMS and isinstance(values, list):
                item_counts[platform] = len(values)
    statuses: List[Dict[str, Any]] = []
    for platform in PRIMARY_SOCIAL_PLATFORMS:
        entry = status_by_platform.get(platform)
        if entry is None:
            if platform in item_counts:
                status = "ok" if item_counts[platform] else "no_results"
            else:
                status = "not_run" if payload else fallback_status
            result_count = item_counts.get(platform, 0)
            message = None
            backend = str(batch.get("backend") or "last30days")
        else:
            count_value = (
                entry.get("items_returned")
                if entry.get("items_returned") is not None
                else entry.get("result_count")
            )
            try:
                result_count = int(count_value) if count_value is not None else item_counts.get(platform, 0)
            except (TypeError, ValueError):
                result_count = item_counts.get(platform, 0)
            status = _schema_status(entry.get("state") or entry.get("status"), fallback_status)
            if entry.get("attempted") is False:
                status = "not_run"
            elif status == "ok" and result_count == 0:
                status = "no_results"
            message = str(entry.get("message") or entry.get("error") or entry.get("reason") or "") or None
            backend = str(entry.get("active_backend") or entry.get("backend") or batch.get("backend") or "last30days")
        statuses.append(
            {
                "platform": platform,
                "backend": backend,
                "status": status,
                "result_count": result_count,
                "message": message,
            }
        )
    return statuses


def _aggregate_platform_status(
    platform_statuses: Sequence[Mapping[str, Any]],
    fallback_status: str,
) -> str:
    values = [str(item.get("status") or "error") for item in platform_statuses]
    if not values:
        return fallback_status
    successful = {"ok", "no_results"}
    if all(value in successful for value in values):
        return "ok" if any(value == "ok" for value in values) else "no_results"
    if any(value in successful for value in values):
        return "partial"
    if any(value == "partial" for value in values):
        return "partial"
    if all(value == "not_run" for value in values):
        return "not_run"
    return fallback_status if fallback_status not in successful else "partial"


def _source_runs(store: CollectorStore, task_id: str, run_dir: Path) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for row in store.list_batches(task_id):
        batch = store.batch_payload(row)
        source = normalize_platform(batch["source"])
        backend = str(batch["backend"])
        if source == "agent-reach":
            tool = "agent-reach"
            role = "targeted_gap_fill"
        elif source == "youtube":
            tool = "yt-dlp" if backend == "yt-dlp" else "youtube-data-api"
            role = "deep_thread_read"
        else:
            tool = "last30days"
            role = "broad_primary_collection"
        status_map = {
            "completed": "ok" if int(batch["raw_candidate_count"]) else "no_results",
            "error": "error",
            "paused": "partial",
            "running": "partial",
            "planned": "not_run",
        }
        raw_artifact = None
        platform_statuses: List[Dict[str, Any]]
        fallback_status = status_map.get(str(batch["status"]), "error")
        if source == "last30days":
            candidate = run_dir / "last30days" / (str(batch["query_id"]) + ".json")
            raw_artifact = str(candidate) if candidate.is_file() else None
            platform_statuses = _last30days_platform_statuses(
                batch,
                candidate if candidate.is_file() else None,
                fallback_status,
            )
        elif tool == "agent-reach":
            candidate = batch["metadata"].get("input_path")
            raw_artifact = str(candidate) if candidate else None
            platform_statuses = [
                {
                    "platform": source,
                    "backend": str(batch["backend"]),
                    "status": fallback_status,
                    "result_count": int(batch["raw_candidate_count"]),
                    "message": batch["error"],
                }
            ]
        else:
            platform_statuses = [
                {
                    "platform": source,
                    "backend": str(batch["backend"]),
                    "status": fallback_status,
                    "result_count": int(batch["raw_candidate_count"]),
                    "message": batch["error"],
                }
            ]
        run_status = (
            _aggregate_platform_status(platform_statuses, fallback_status)
            if source == "last30days"
            else fallback_status
        )
        result.append(
            {
                "run_id": str(batch["batch_id"]),
                "tool": tool,
                "role": role,
                "scope_ids": [str(batch["scope"])],
                "query_ids": [
                    str(batch["scope"]) + "_primary"
                    if tool != "agent-reach"
                    else _agent_reach_query_id(batch["query_id"])
                ],
                "started_at": batch["started_at"] or batch["created_at"],
                "finished_at": batch["finished_at"] or batch["updated_at"],
                "status": run_status,
                "platform_statuses": platform_statuses,
                "raw_artifact": raw_artifact,
                "error_summary": batch["error"],
            }
        )
    return result


def _schema_status(value: Any, default: str = "error") -> str:
    allowed = {
        "ok", "no_results", "partial", "auth_failed", "rate_limited",
        "timeout", "unavailable", "error", "not_run",
    }
    text = str(value or "").strip().lower()
    aliases = {
        "success": "ok",
        "healthy": "ok",
        "ready": "ok",
        "warn": "partial",
        "warning": "partial",
        "degraded": "partial",
        "off": "unavailable",
        "disabled": "unavailable",
        "skipped": "not_run",
        "failed": "error",
        "invalid_json": "error",
    }
    text = aliases.get(text, text)
    return text if text in allowed else default


def _artifact_timestamp(path: Path) -> str:
    return iso_utc(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))


def _agent_reach_health(run_dir: Path) -> Dict[str, Any]:
    root = run_dir / "agent_reach"
    doctor_path = root / "doctor.json"
    update_path = root / "check_update.json"

    doctor_payload: Mapping[str, Any] = {}
    if doctor_path.is_file():
        try:
            loaded = json.loads(doctor_path.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                doctor_payload = loaded
        except (OSError, json.JSONDecodeError):
            doctor_payload = {"status": "error"}
    active_backends: List[Dict[str, Any]] = []
    raw_backends = doctor_payload.get("active_backends") or doctor_payload.get("platforms")
    if raw_backends is None:
        top_level_platforms = {
            key: value
            for key, value in doctor_payload.items()
            if normalize_platform(key) in QUANTITATIVE_PLATFORMS
            and isinstance(value, Mapping)
            and any(child in value for child in ("active_backend", "backend", "status"))
        }
        raw_backends = top_level_platforms or None
    if isinstance(raw_backends, Mapping):
        raw_backends = [dict(value, platform=key) if isinstance(value, Mapping) else {"platform": key, "active_backend": value} for key, value in raw_backends.items()]
    if isinstance(raw_backends, list):
        for item in raw_backends:
            if not isinstance(item, Mapping):
                continue
            platform = str(item.get("platform") or item.get("name") or "").strip()
            if not platform:
                continue
            active_backends.append(
                {
                    "platform": normalize_platform(platform),
                    "active_backend": str(item.get("active_backend") or item.get("backend") or "") or None,
                    "status": _schema_status(item.get("status"), "ok"),
                }
            )
    explicit_doctor_status = doctor_payload.get("status")
    if explicit_doctor_status is not None:
        doctor_status = _schema_status(explicit_doctor_status, "ok")
    elif active_backends:
        backend_statuses = [str(item["status"]) for item in active_backends]
        doctor_status = (
            "ok"
            if all(status == "ok" for status in backend_statuses)
            else "partial"
            if any(status in {"ok", "partial"} for status in backend_statuses)
            else "unavailable"
        )
    else:
        doctor_status = "ok" if doctor_path.is_file() else "not_run"
    doctor = {
        "ran_at": _artifact_timestamp(doctor_path) if doctor_path.is_file() else iso_utc(),
        "status": doctor_status,
        "active_backends": active_backends,
        "raw_artifact": str(doctor_path) if doctor_path.is_file() else None,
    }

    update_payload: Mapping[str, Any] = {}
    update_text = ""
    if update_path.is_file():
        try:
            update_text = update_path.read_text(encoding="utf-8").strip()
            loaded = json.loads(update_text)
            if isinstance(loaded, Mapping):
                update_payload = loaded
        except OSError as exc:
            update_payload = {"status": "error", "message": redact_text(exc)}
        except json.JSONDecodeError:
            current_match = re.search(
                r"(?:当前版本|current\s+version)\s*[:：]\s*v?([0-9][\w.-]*)",
                update_text,
                flags=re.IGNORECASE,
            )
            latest_match = re.search(
                r"(?:最新版本|latest\s+version)\s*[:：]\s*v?([0-9][\w.-]*)",
                update_text,
                flags=re.IGNORECASE,
            )
            lowered = update_text.casefold()
            if re.search(r"已是最新|up[ -]to[ -]date", update_text, flags=re.IGNORECASE):
                text_status = "ok"
            elif re.search(r"新版本|update\s+available", update_text, flags=re.IGNORECASE):
                text_status = "partial"
            elif any(token in lowered for token in ("error", "failed", "失败", "错误")):
                text_status = "error"
            else:
                text_status = "ok" if update_text else "error"
            update_payload = {
                "status": text_status,
                "current_version": current_match.group(1) if current_match else None,
                "latest_version": latest_match.group(1) if latest_match else None,
                "message": redact_text(update_text) or "empty output",
            }
    check_update = {
        "ran_at": _artifact_timestamp(update_path) if update_path.is_file() else None,
        "status": _schema_status(update_payload.get("status"), "ok") if update_path.is_file() else "not_run",
        "current_version": str(update_payload.get("current_version") or "") or None,
        "latest_version": str(update_payload.get("latest_version") or "") or None,
        "message": str(update_payload.get("message") or "") or (
            None if update_path.is_file() else "等待 agent-reach 队列执行完成。"
        ),
    }
    return {"doctor": doctor, "check_update": check_update}


def _safe_need_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", text).strip("-._")
    return normalized or "need_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def materialize_social_voice_coding(store: CollectorStore, task_id: str) -> Dict[str, Any]:
    task = store.task_payload(task_id)
    if not task.get("project_dir") or not task.get("run_dir"):
        return {"status": "skipped", "reason": "task_has_no_project_run_dir"}
    project_dir = Path(str(task["project_dir"]))
    run_dir = Path(str(task["run_dir"]))
    selection_path = run_dir / "selected_segments.json"
    if not selection_path.is_file():
        return {"status": "skipped", "reason": "selected_segments_missing"}
    pending_coding = int(
        store.connection.execute(
            "SELECT COUNT(*) FROM comments WHERE task_id=? AND coding_status!='coded'",
            (task_id,),
        ).fetchone()[0]
    )
    if pending_coding:
        return {
            "status": "deferred",
            "reason": "coding_incomplete",
            "pending_coding_records": pending_coding,
        }
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    snapshot = (
        selection.get("project_snapshot")
        if isinstance(selection, Mapping)
        and isinstance(selection.get("project_snapshot"), Mapping)
        else {}
    )
    snapshot_dashboard = (
        snapshot.get("opportunity_dashboard")
        if isinstance(snapshot.get("opportunity_dashboard"), Mapping)
        else {}
    )
    project = _project_context(
        project_dir,
        str(snapshot_dashboard.get("sha256") or "") or None,
    )
    end_at = parse_timestamp(task["end_at"])
    if end_at is None:
        raise CollectorError("task end_at 无效")
    query_plan = _coding_query_plan(store, task_id, str(project["listing_language"]), end_at)
    known_query_ids = {item["query_id"] for item in query_plan["primary_lanes"]} | {
        item["query_id"] for item in query_plan["gap_fill_queries"]
    }
    voices: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    need_codes: Dict[str, str] = {}
    dedup_groups: List[Dict[str, Any]] = []
    rows = store.connection.execute("SELECT * FROM comments WHERE task_id=? ORDER BY record_id", (task_id,)).fetchall()
    for row in rows:
        discoveries = store.connection.execute(
            """SELECT d.*,b.backend,b.source AS batch_source FROM comment_discoveries d
            JOIN batches b ON b.batch_id=d.batch_id WHERE d.record_id=? ORDER BY d.discovery_id""",
            (row["record_id"],),
        ).fetchall()
        raw_coding = json.loads(str(row["coding_json"])) if row["coding_json"] else {}
        is_coded = row["coding_status"] == "coded"
        url = str(row["canonical_url"] or "")
        published = parse_timestamp(row["published_at"])
        final_eligible = bool(row["eligible_for_quantitation"] and is_coded and published and url.startswith(("http://", "https://")))
        if final_eligible:
            mapped_discoveries = []
            scopes = set()
            query_ids = set()
            for discovery in discoveries:
                # One hard-unique message may be found by both a 30-day and a
                # 90-day route.  Only the discoveries inside their own route
                # window may contribute to collection scopes or denominators.
                if not bool(discovery["within_window"]):
                    continue
                scope = str(discovery["scope"])
                tool_query = (
                    scope + "_primary"
                    if discovery["batch_source"] != "agent-reach"
                    else _agent_reach_query_id(discovery["query_id"])
                )
                if tool_query not in known_query_ids:
                    tool_query = scope + "_primary"
                scopes.add(scope)
                query_ids.add(tool_query)
                mapped_discoveries.append(
                    {
                        "discovery_id": "discovery_%s" % discovery["discovery_id"],
                        "source_run_id": str(discovery["batch_id"]),
                        "query_id": tool_query,
                        "scope_id": scope,
                        "platform": str(row["source"]),
                        "backend": str(discovery["backend"]),
                        "source_content_id": str(row["content_id"] or row["record_id"]),
                        "source_url": url,
                        "retrieved_at": str(discovery["discovered_at"]),
                    }
                )
            coding_fields = {
                "sentiment": raw_coding.get("sentiment", "neutral"),
                "use_scenes": list(raw_coding.get("use_scenes") or []),
                "persona_tags": list(raw_coding.get("persona_tags") or []),
                "need_codes": [_safe_need_code(value) for value in raw_coding.get("need_codes") or []],
                "satisfaction_codes": [_safe_need_code(value) for value in raw_coding.get("satisfaction_codes") or []],
                "dissatisfaction_codes": [_safe_need_code(value) for value in raw_coding.get("dissatisfaction_codes") or []],
                "innovation_signals": list(raw_coding.get("innovation_signals") or []),
                "kano_evidence": list(raw_coding.get("kano_evidence") or []),
                "evidence_confidence": raw_coding.get("evidence_confidence", "low"),
                "coding_notes": raw_coding.get("coding_notes"),
            }
            for key in ("need_codes", "satisfaction_codes", "dissatisfaction_codes"):
                for code in coding_fields[key]:
                    need_codes.setdefault(code, code)
            for item in coding_fields["innovation_signals"] + coding_fields["kano_evidence"]:
                if isinstance(item, Mapping) and item.get("need_code"):
                    original = str(item["need_code"])
                    safe = _safe_need_code(original)
                    item["need_code"] = safe
                    need_codes.setdefault(safe, original)
            memberships = [
                item
                for item in raw_coding.get("segment_memberships", [])
                if isinstance(item, Mapping) and item.get("segment_id") in {segment.get("segment_id") for segment in selection.get("selected_segments", [])}
            ]
            raw = json.loads(str(row["raw_json"] or "{}"))
            engagement_raw = raw.get("engagement") if isinstance(raw.get("engagement"), Mapping) else {}
            author_hash = str(row["author_hash"] or "unknown_" + hashlib.sha256(str(row["record_id"]).encode()).hexdigest()[:16])
            voices.append(
                {
                    "voice_id": str(row["record_id"]),
                    "platform": str(row["source"]),
                    "backend": str(discoveries[0]["backend"] if discoveries else "collector"),
                    "content_type": "video_comment" if row["source"] == "youtube" else ("reply" if row["parent_content_id"] else "post"),
                    "content_id": row["content_id"],
                    "thread_id": row["thread_id"],
                    "parent_id": row["parent_content_id"],
                    "parent_content_id": row["parent_content_id"],
                    "community": raw_coding.get("community"),
                    "author_hash": author_hash,
                    "author_label": row["author_label"],
                    "author_identity_status": raw_coding.get("author_identity_status", "pseudonymous" if row["author_hash"] else "unknown"),
                    "published_at": iso_utc(published),
                    "collected_at": str(row["first_seen_at"]),
                    "language": str(raw_coding.get("language") or project["listing_language"]),
                    "region_hint": raw_coding.get("region_hint"),
                    "excerpt": str(row["text"])[:1000],
                    "summary_zh": str(raw_coding.get("summary_zh") or row["text"])[:1000],
                    "normalized_url": url,
                    "engagement": {
                        "likes": engagement_raw.get("likes"),
                        "replies": engagement_raw.get("replies"),
                        "shares": engagement_raw.get("shares"),
                        "views": engagement_raw.get("views"),
                        "score": engagement_raw.get("score"),
                        "captured_at": str(row["first_seen_at"]),
                    },
                    "actor_type": "consumer",
                    "eligible_for_quantitation": True,
                    "exclusion_reasons": [],
                    "collection_scopes": sorted(scopes),
                    "query_ids": sorted(query_ids),
                    "segment_memberships": memberships,
                    "discoveries": mapped_discoveries,
                    "coding": coding_fields,
                }
            )
            if len(mapped_discoveries) > 1:
                method = "content_id" if row["content_id"] else ("comment_permalink" if is_comment_level_url(str(row["source"]), url) else "fallback_composite")
                dedup_groups.append(
                    {
                        "dedup_group_id": "dedup_" + str(row["record_id"]),
                        "canonical_voice_id": str(row["record_id"]),
                        "duplicate_record_ids": [item["discovery_id"] for item in mapped_discoveries[1:]],
                        "method": method,
                        "similarity": None,
                        "reason": "同一硬身份在多个查询或采集批次重复发现。",
                    }
                )
        else:
            discovery = discoveries[0] if discoveries else None
            reason = str(row["exclusion_reason"] or ("other" if is_coded else "uncoded"))
            reason_map = {
                "missing_or_invalid_published_at": "missing_or_unreliable_date",
                "outside_scope_window": "outside_window",
                "seller_promotion": "brand_or_seller_promotion",
                "missing_hard_identity": "untraceable_source",
                "empty_text": "no_consumer_opinion",
                "uncoded": "other",
            }
            source_url = url if url.startswith(("http://", "https://")) else "https://invalid.local/untraceable/" + str(row["record_id"])
            excluded.append(
                {
                    "record_id": str(row["record_id"]),
                    "source_run_id": str(discovery["batch_id"] if discovery else "unknown_run"),
                    "query_id": (str(discovery["scope"]) + "_primary") if discovery else "category_30d_primary",
                    "scope_id": str(discovery["scope"] if discovery else "category_30d"),
                    "platform": str(row["source"]),
                    "backend": str(discovery["backend"] if discovery else "collector"),
                    "content_id": str(row["content_id"] or row["record_id"]),
                    "published_at": iso_utc(published) if published else None,
                    "url": source_url,
                    "excerpt": str(row["text"] or "")[:1000],
                    "exclusion_reasons": [reason_map.get(reason, "other")],
                }
            )
    funnel = store.collection_funnel(task_id)
    funnel["valid_voices"] = len(voices)
    funnel["excluded_records"] = len(excluded)
    for item in funnel["per_scope"]:
        scope_id = str(item["scope_id"])
        if scope_id == "category_30d":
            semantic_valid = sum(
                1 for voice in voices if scope_id in voice["collection_scopes"]
            )
        else:
            semantic_valid = sum(
                1
                for voice in voices
                if any(
                    isinstance(membership, Mapping)
                    and membership.get("segment_id") == scope_id
                    and membership.get("is_member") is True
                    for membership in voice["segment_memberships"]
                )
            )
        item["valid_voices"] = semantic_valid
        # Segment membership may be established from a voice first found by
        # another route. Keep the per-scope funnel monotonic while preserving
        # query-route acquisition counts by lifting only stages below the
        # final semantic denominator.
        for field in FUNNEL_STAGE_FIELDS[:-1]:
            item[field] = max(int(item.get(field) or 0), semantic_valid)
    for item in funnel["per_platform"]:
        item["valid_voices"] = sum(1 for voice in voices if item["platform"] == voice["platform"])
    counts: Dict[str, int] = {}
    for item in excluded:
        reason = item["exclusion_reasons"][0]
        counts[reason] = counts.get(reason, 0) + 1
    funnel["exclusion_reasons"] = [{"reason": key, "count": counts[key]} for key in sorted(counts)]
    document = {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "generated_at": iso_utc(),
        "end_at": iso_utc(end_at),
        "windows": {
            "interval_semantics": "[start_at,end_at)",
            "category_30d": {"scope_id": "category_30d", "days": 30, "start_at": iso_utc(end_at - timedelta(days=30)), "end_at": iso_utc(end_at)},
            "segment_90d": {"days": 90, "start_at": iso_utc(end_at - timedelta(days=90)), "end_at": iso_utc(end_at)},
        },
        "top3_selection": selection["top3_selection"],
        "segments": selection.get("selected_segments", []),
        "query_plan": query_plan,
        "source_runs": _source_runs(store, task_id, run_dir),
        "agent_reach_health": _agent_reach_health(run_dir),
        "need_dictionary": [
            {"need_code": code, "name_zh": label, "definition": "消费者编码需求：" + label, "inclusions": [label], "exclusions": ["不属于该需求的表达"], "synonyms": [label]}
            for code, label in sorted(need_codes.items())
        ],
        "voices": voices,
        "dedup_groups": dedup_groups,
        "excluded_records": excluded,
        "llm_calls": [],
        "research_plan": task["research_plan"],
        "collection_funnel": funnel,
        "stop_reason": task["stop_reason"] or "manual_stop",
    }
    output = run_dir / "social_voice_coding.json"
    write_json(output, document)
    runtime = detect_last30days_python()
    if not runtime["available"]:
        raise CollectorError("无法找到 Python 3.12+ 校验 social_voice_coding.json")
    validator = Path(__file__).resolve().parent / "consumer_product_report.py"
    completed = default_runner(
        [str(runtime["selected"]), str(validator), "validate-coding", "--input", str(output)],
        120.0,
    )
    if completed.returncode != 0:
        raise CollectorError(
            "social_voice_coding.json 未通过确定性校验：%s"
            % redact_text(completed.stderr or completed.stdout)
        )
    return {
        "status": "materialized",
        "path": str(output),
        "voice_count": len(voices),
        "excluded_count": len(excluded),
        "validation": "passed",
    }


def _coding_payloads(paths: Sequence[Path]) -> Iterator[Mapping[str, Any]]:
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise CollectorError("coding 文件顶层必须是对象：%s" % path)
        if isinstance(payload.get("records"), list):
            yield payload
            continue
        if isinstance(payload.get("files"), list):
            children = []
            for child in payload["files"]:
                if not isinstance(child, Mapping) or not child.get("path"):
                    raise CollectorError("coding manifest 的 files 无效：%s" % path)
                child_path = Path(str(child["path"]))
                if not child_path.is_absolute():
                    child_path = path.parent / child_path
                children.append(child_path)
            for nested in _coding_payloads(children):
                yield nested
            continue
        raise CollectorError("coding 文件既没有 records 也没有 files：%s" % path)


def merge_coding(store: CollectorStore, task_id: str, input_paths: Sequence[Path]) -> Dict[str, Any]:
    started = time.monotonic()
    all_records: List[Mapping[str, Any]] = []
    for payload in _coding_payloads(input_paths):
        if str(payload.get("task_id") or "") != task_id:
            raise CollectorError("coding 文件 task_id 不匹配")
        all_records.extend(item for item in payload["records"] if isinstance(item, Mapping))
    result = store.merge_coding(task_id, all_records)
    merged = dict({"task_id": task_id, "input_records": len(all_records)}, **result)
    merged["coding_artifact"] = materialize_social_voice_coding(store, task_id)
    task = store.task_row(task_id)
    store.update_task(
        task_id,
        updated_at=iso_utc(),
        total_elapsed_seconds=float(task["total_elapsed_seconds"]) + (time.monotonic() - started),
    )
    return merged


def build_receipt(store: CollectorStore, task_id: str) -> Dict[str, Any]:
    task = store.task_payload(task_id)
    plan = task["research_plan"]
    timing = store.timing_usage(task_id, include_running=True)
    budget_gate = store.timing_gate(task_id)
    funnel = store.collection_funnel(task_id)
    per_scope_counts = {item["scope_id"]: int(item["valid_voices"]) for item in funnel["per_scope"]}
    target = plan["sample_target"]
    valid_platforms = sum(1 for item in funnel["per_platform"] if int(item["valid_voices"]) > 0)
    scope_met = all(
        per_scope_counts.get(scope, 0) >= int(spec["valid_min"])
        for scope, spec in target["per_scope"].items()
    )
    target_met = (
        int(funnel["valid_voices"]) >= int(target["total_valid_min"])
        and scope_met
        and valid_platforms >= int(target["min_platforms"])
    )
    quota_rows = store.connection.execute(
        """SELECT source,operation,unit_name,cost_status,currency,price_snapshot_at,pricing_basis,
        SUM(units) AS units,SUM(estimated_cost_usd) AS estimated_cost_usd,
        SUM(actual_cost_usd) AS actual_cost_usd,COUNT(*) AS request_entries
        FROM quota_ledger WHERE task_id=?
        GROUP BY source,operation,unit_name,cost_status,currency,price_snapshot_at,pricing_basis
        ORDER BY source,operation,cost_status""",
        (task_id,),
    ).fetchall()
    cost_entries: List[Dict[str, Any]] = []
    actual_amounts: List[float] = []
    estimated_amounts: List[float] = []
    for row in quota_rows:
        status = str(row["cost_status"] or "unknown")
        amount: Optional[float] = None
        if status == "provider_confirmed_actual" and row["actual_cost_usd"] is not None:
            amount = round(float(row["actual_cost_usd"]), 8)
            actual_amounts.append(amount)
        elif status == "estimated_from_price_snapshot" and row["estimated_cost_usd"] is not None:
            amount = round(float(row["estimated_cost_usd"]), 8)
            estimated_amounts.append(amount)
        cost_entries.append(
            {
                "source": str(row["source"]),
                "operation": str(row["operation"]),
                "request_entries": int(row["request_entries"] or 0),
                "units": int(row["units"] or 0),
                "unit_name": str(row["unit_name"]),
                "cost_status": status,
                "amount": amount,
                "currency": row["currency"],
                "price_snapshot_at": row["price_snapshot_at"],
                "calculation_basis": row["pricing_basis"],
            }
        )
    checkpoints = [
        {
            "batch_id": row["batch_id"],
            "checkpoint_key": row["checkpoint_key"],
            "state": json.loads(str(row["state_json"])),
            "updated_at": row["updated_at"],
        }
        for row in store.connection.execute(
            "SELECT * FROM checkpoints WHERE task_id=? ORDER BY batch_id,checkpoint_key", (task_id,)
        ).fetchall()
    ]
    latest_youtube_quota = store.connection.execute(
        """SELECT metadata_json FROM quota_ledger
        WHERE task_id=? AND source='youtube' AND unit_name='youtube_quota_unit'
        ORDER BY ledger_id DESC LIMIT 1""",
        (task_id,),
    ).fetchone()
    quota_snapshot: Dict[str, Any] = {}
    if latest_youtube_quota is not None:
        try:
            loaded_snapshot = json.loads(str(latest_youtube_quota["metadata_json"] or "{}"))
            if isinstance(loaded_snapshot, Mapping):
                quota_snapshot = dict(loaded_snapshot)
        except json.JSONDecodeError:
            quota_snapshot = {}
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "run_dir": task.get("run_dir"),
        "generated_at": iso_utc(),
        "started_at": task.get("started_at"),
        "finished_at": task.get("finished_at"),
        "research_plan": plan,
        "collection_policy": task["collection_policy"],
        "status": task["status"],
        "stop_reason": task["stop_reason"],
        "collection_stop_reason": task.get("collection_stop_reason") or (
            task["stop_reason"] if task["stop_reason"] != "total_deadline" else None
        ),
        "target_attainment": {
            "target_met": target_met,
            "total_valid": int(funnel["valid_voices"]),
            "per_scope_valid": per_scope_counts,
            "valid_platforms": valid_platforms,
            "min_platforms": int(target["min_platforms"]),
        },
        "youtube_execution": {
            "configured_worker_upper_bound": None,
            "actual_workers": 1,
            "execution_mode": "sequential_checkpoint_safe",
        },
        "collection_funnel": funnel,
        "time_usage_minutes": {
            "collection": round(float(timing["effective_collection_seconds"]) / 60, 4),
            "total": round(float(timing["effective_total_seconds"]) / 60, 4),
            "internal_collector_and_local_processing": round(
                float(timing["internal_total_seconds"]) / 60, 4
            ),
            "external_metered": round(float(timing["external_total_seconds"]) / 60, 4),
            "unmetered_human_setup_wait": {
                "status": "recorded" if float(timing["unmetered_seconds"]) > 0 else "not_recorded",
                "minutes": (
                    round(float(timing["unmetered_seconds"]) / 60, 4)
                    if float(timing["unmetered_seconds"]) > 0
                    else None
                ),
                "included_in_collection_or_total": False,
            },
        },
        "budget_gate": budget_gate,
        "timing_sessions": timing["sessions"],
        "manifest_finalize_intents": [
            store._manifest_intent_payload(row)
            for row in store.connection.execute(
                "SELECT * FROM manifest_finalize_intents WHERE task_id=? ORDER BY created_at,intent_id",
                (task_id,),
            ).fetchall()
        ],
        "quota_and_cost": {
            "daily_quota_limit": int(task["daily_quota_units"]),
            "fixed_quota_reserve": int(
                quota_snapshot.get("fixed_reserve") or MIN_YOUTUBE_QUOTA_RESERVE
            ),
            "global_daily_used_after": quota_snapshot.get("global_daily_used_after"),
            "available_before_reserve_after": quota_snapshot.get(
                "available_before_reserve_after"
            ),
            "quota_accounting_scope": (
                quota_snapshot.get("accounting_scope") if quota_snapshot else "no_youtube_request"
            ),
            "ledger": cost_entries,
            "quota_units": sum(
                int(row["units"] or 0)
                for row in quota_rows
                if str(row["unit_name"]) == "youtube_quota_unit"
            ),
            "request_entries": sum(int(row["request_entries"] or 0) for row in quota_rows),
            "provider_confirmed_actual_cost_usd": (
                round(sum(actual_amounts), 8) if actual_amounts else None
            ),
            "estimated_direct_cost_usd": (
                round(sum(estimated_amounts), 8) if estimated_amounts else None
            ),
            "cost_statuses": sorted({entry["cost_status"] for entry in cost_entries}),
            "cost_basis": "direct provider charges recorded for this run only",
            "excluded_costs": [
                "one-time human API setup time",
                "local compute and network costs",
                "existing subscriptions unless a provider charge was recorded",
            ],
            "unknown_is_not_zero": True,
        },
        "recent_3_batches": store.low_increment_tail(task_id),
        "queues": [store.batch_payload(row) for row in store.list_batches(task_id)],
        "checkpoints": checkpoints,
    }


def _contract_artifact_dir(
    store: CollectorStore,
    task_id: str,
    fallback: Optional[Path] = None,
) -> Path:
    task = store.task_row(task_id)
    declared = str(task["run_dir"] or "").strip()
    root = Path(declared).expanduser() if declared else (fallback or store.path.parent)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_redacted_contract_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    known_secrets: Sequence[str] = (),
) -> None:
    safe = redact_value(payload, known_secrets)
    rendered = json.dumps(safe, ensure_ascii=False, indent=2) + "\n"
    for secret in known_secrets:
        if secret and secret in rendered:
            raise CollectorError("合同产物脱敏失败，已停止写入：%s" % path.name)
    _atomic_write_text(path, rendered, mode=0o600)


def build_research_plan_artifact(task: Mapping[str, Any]) -> Dict[str, Any]:
    plan = task.get("research_plan") if isinstance(task.get("research_plan"), Mapping) else {}
    policy = task.get("collection_policy") if isinstance(task.get("collection_policy"), Mapping) else {}
    queues = task.get("queues") if isinstance(task.get("queues"), list) else []
    project_snapshot: Dict[str, Any] = {}
    run_dir = str(task.get("run_dir") or "").strip()
    if run_dir:
        selection_path = Path(run_dir) / "selected_segments.json"
        if selection_path.is_file():
            try:
                selection = json.loads(selection_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                selection = {}
            if isinstance(selection, Mapping) and isinstance(
                selection.get("project_snapshot"), Mapping
            ):
                project_snapshot = copy.deepcopy(dict(selection["project_snapshot"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": str(task.get("task_id") or ""),
        "generated_at": iso_utc(),
        "end_at": task.get("end_at"),
        "research_plan": copy.deepcopy(dict(plan)),
        "collection_policy": copy.deepcopy(dict(policy)),
        "scope_order": list(SCOPES),
        "queue_count": len(queues),
        "project_dir": task.get("project_dir"),
        "run_dir": task.get("run_dir"),
        "project_snapshot": project_snapshot,
    }


def build_collection_state(
    store: CollectorStore,
    task_id: str,
    receipt: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    current_receipt = dict(receipt or build_receipt(store, task_id))
    task = store.task_payload(task_id)
    queues = current_receipt.get("queues")
    queue_items = [item for item in (queues if isinstance(queues, list) else []) if isinstance(item, Mapping)]
    status_counts: Dict[str, int] = {}
    queue_rows: List[Dict[str, Any]] = []
    for item in queue_items:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        queue_rows.append(
            {
                "batch_id": item.get("batch_id"),
                "source": item.get("source"),
                "backend": item.get("backend"),
                "scope_id": item.get("scope"),
                "query_id": item.get("query_id"),
                "status": status,
                "raw_candidate_count": int(item.get("raw_candidate_count") or 0),
                "new_valid_count": int(item.get("new_valid_count") or 0),
                "duplicate_count": int(item.get("duplicate_count") or 0),
                "page_count": int(item.get("page_count") or 0),
                "request_count": int(item.get("request_count") or 0),
                "quota_units": int(item.get("quota_units") or 0),
                "increment_rate": float(item.get("increment_rate") or 0),
                "started_at": item.get("started_at"),
                "finished_at": item.get("finished_at"),
                "updated_at": item.get("updated_at"),
                "error": item.get("error"),
            }
        )
    checkpoints = current_receipt.get("checkpoints")
    checkpoint_rows = [
        {
            "batch_id": item.get("batch_id"),
            "checkpoint_name": item.get("checkpoint_key"),
            "updated_at": item.get("updated_at"),
        }
        for item in (checkpoints if isinstance(checkpoints, list) else [])
        if isinstance(item, Mapping)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "generated_at": iso_utc(),
        "research_level": task.get("research_level"),
        "status": current_receipt.get("status"),
        "stop_reason": current_receipt.get("stop_reason"),
        "end_at": task.get("end_at"),
        "started_at": current_receipt.get("started_at"),
        "finished_at": current_receipt.get("finished_at"),
        "run_count": int(task.get("run_count") or 0),
        "target_attainment": copy.deepcopy(current_receipt.get("target_attainment") or {}),
        "collection_funnel": copy.deepcopy(current_receipt.get("collection_funnel") or {}),
        "time_usage_minutes": copy.deepcopy(current_receipt.get("time_usage_minutes") or {}),
        "queue_summary": {
            "total": len(queue_rows),
            "by_status": dict(sorted(status_counts.items())),
        },
        "queues": queue_rows,
        "checkpoint_summary": {
            "count": len(checkpoint_rows),
            "items": checkpoint_rows,
        },
    }


def build_source_status(
    store: CollectorStore,
    task_id: str,
    run_dir: Path,
    receipt: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    current_receipt = dict(receipt or build_receipt(store, task_id))
    source_runs = _source_runs(store, task_id, run_dir)
    status_counts: Dict[str, int] = {}
    for item in source_runs:
        status = str(item.get("status") or "error")
        status_counts[status] = status_counts.get(status, 0) + 1
    funnel = current_receipt.get("collection_funnel")
    quota = current_receipt.get("quota_and_cost")
    quota_map = quota if isinstance(quota, Mapping) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "generated_at": iso_utc(),
        "status": current_receipt.get("status"),
        "stop_reason": current_receipt.get("stop_reason"),
        "source_run_summary": {
            "total": len(source_runs),
            "by_status": dict(sorted(status_counts.items())),
        },
        "source_runs": source_runs,
        "per_platform": copy.deepcopy(
            funnel.get("per_platform", []) if isinstance(funnel, Mapping) else []
        ),
        "youtube_usage": {
            "daily_quota_limit": quota_map.get("daily_quota_limit"),
            "fixed_quota_reserve": quota_map.get("fixed_quota_reserve"),
            "quota_units": quota_map.get("quota_units"),
            "request_entries": quota_map.get("request_entries"),
            "cost_statuses": copy.deepcopy(quota_map.get("cost_statuses") or []),
            "provider_confirmed_actual_cost_usd": quota_map.get(
                "provider_confirmed_actual_cost_usd"
            ),
            "estimated_direct_cost_usd": quota_map.get("estimated_direct_cost_usd"),
            "unknown_is_not_zero": quota_map.get("unknown_is_not_zero", True),
        },
    }


def write_research_plan_artifact(
    store: CollectorStore,
    task_id: str,
    run_dir: Optional[Path] = None,
    *,
    known_secrets: Sequence[str] = (),
) -> Path:
    root = _contract_artifact_dir(store, task_id, run_dir)
    path = root / "research_plan.json"
    task = store.task_payload(task_id, include_batches=True)
    _write_redacted_contract_json(
        path, build_research_plan_artifact(task), known_secrets=known_secrets
    )
    return path


def write_collection_contract_artifacts(
    store: CollectorStore,
    task_id: str,
    receipt: Mapping[str, Any],
    run_dir: Optional[Path] = None,
    *,
    known_secrets: Sequence[str] = (),
) -> Dict[str, str]:
    root = _contract_artifact_dir(store, task_id, run_dir)
    plan_path = write_research_plan_artifact(
        store, task_id, root, known_secrets=known_secrets
    )
    state_path = root / "collection_state.json"
    source_path = root / "source_status.json"
    _write_redacted_contract_json(
        state_path,
        build_collection_state(store, task_id, receipt),
        known_secrets=known_secrets,
    )
    _write_redacted_contract_json(
        source_path,
        build_source_status(store, task_id, root, receipt),
        known_secrets=known_secrets,
    )
    return {
        "research_plan": str(plan_path),
        "collection_state": str(state_path),
        "source_status": str(source_path),
    }


def _python_version(
    executable: str,
    runner: Callable[[Sequence[str], float], subprocess.CompletedProcess] = default_runner,
    timeout_seconds: float = 10.0,
) -> Optional[Tuple[int, int, int]]:
    try:
        completed = runner(
            [executable, "-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"],
            max(0.1, float(timeout_seconds)),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", str(completed.stdout))
    if not match:
        return None
    return tuple(int(child) for child in match.groups())  # type: ignore[return-value]


def detect_last30days_python(
    runner: Callable[[Sequence[str], float], subprocess.CompletedProcess] = default_runner,
    timeout_provider: Optional[Callable[[], float]] = None,
) -> Dict[str, Any]:
    candidates: List[str] = []
    configured = os.environ.get("LCADMO_PYTHON", "").strip()
    if configured:
        candidates.append(configured)
    for name in ("python3.13", "python3.12"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)
    if BUNDLED_PYTHON.exists():
        candidates.append(str(BUNDLED_PYTHON))
    if sys.version_info >= (3, 12):
        candidates.append(sys.executable)
    checked: List[Dict[str, Any]] = []
    seen = set()
    for candidate in candidates:
        path = str(Path(candidate).expanduser())
        if path in seen:
            continue
        seen.add(path)
        probe_timeout = 10.0
        if timeout_provider is not None:
            probe_timeout = min(probe_timeout, float(timeout_provider()))
        version = _python_version(path, runner, probe_timeout)
        usable = version is not None and version >= (3, 12, 0)
        checked.append(
            {
                "path": path,
                "version": ".".join(str(child) for child in version) if version else None,
                "usable": usable,
            }
        )
        if usable:
            return {"available": True, "selected": path, "checked": checked}
    return {"available": False, "selected": None, "checked": checked}


def doctor_report(
    db_path: Optional[Path],
    config_path: Path,
    runner: Callable[[Sequence[str], float], subprocess.CompletedProcess] = default_runner,
) -> Dict[str, Any]:
    python_report = detect_last30days_python(runner)
    script = Path(os.environ.get("LAST30DAYS_SCRIPT", str(DEFAULT_LAST30DAYS_SCRIPT))).expanduser()
    db_report: Dict[str, Any] = {"configured": db_path is not None}
    if db_path is not None:
        db_report.update({"path": str(db_path), "exists": db_path.exists()})
        if db_path.exists():
            try:
                connection = sqlite3.connect("file:%s?mode=ro" % urllib_parse.quote(str(db_path)), uri=True)
                row = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
                connection.close()
                db_report.update({"readable": True, "schema_version": row[0] if row else None})
            except sqlite3.Error as exc:
                db_report.update({"readable": False, "error": redact_text(exc)})
    youtube = check_youtube_api_config(config_path)
    yt_dlp_path = shutil.which("yt-dlp")
    agent_reach_path = shutil.which("agent-reach")
    agent_reach_doctor: Dict[str, Any] = {"attempted": False, "status": "unavailable"}
    if agent_reach_path:
        try:
            completed = runner([agent_reach_path, "doctor", "--json"], 45.0)
            agent_reach_doctor = {
                "attempted": True,
                "status": "ok" if completed.returncode == 0 else "failed",
                "exit_code": completed.returncode,
            }
            if completed.returncode == 0:
                try:
                    agent_reach_doctor["report"] = redact_value(json.loads(completed.stdout))
                except json.JSONDecodeError:
                    agent_reach_doctor["status"] = "invalid_json"
            elif completed.stderr:
                agent_reach_doctor["error"] = redact_text(completed.stderr)
        except (OSError, subprocess.SubprocessError) as exc:
            agent_reach_doctor = {
                "attempted": True,
                "status": "failed",
                "error": redact_text(exc),
            }
    last30days_available = bool(script.exists() and python_report["available"])
    agent_reach_available = bool(
        agent_reach_path and agent_reach_doctor.get("status") == "ok"
    )
    ready = bool(
        last30days_available
        and agent_reach_available
        and (youtube.get("configured") or yt_dlp_path)
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok" if ready else "partial",
        "collector_python": {
            "executable": sys.executable,
            "version": ".".join(str(child) for child in sys.version_info[:3]),
            "compatible": sys.version_info >= (3, 9),
        },
        "sqlite": {"version": sqlite3.sqlite_version, "database": db_report},
        "youtube_api": youtube,
        "yt_dlp": {"available": bool(yt_dlp_path), "command": yt_dlp_path},
        "last30days": {
            "available": last30days_available,
            "script": str(script),
            "python": python_report,
            "required_python": ">=3.12",
        },
        "agent_reach": {
            "available": agent_reach_available,
            "binary_available": bool(agent_reach_path),
            "command": agent_reach_path,
            "doctor": agent_reach_doctor,
        },
        "notes": [
            "collector 自身兼容 Python 3.9+；last30days 使用独立探测到的 Python 3.12+。",
            "doctor 只检查，不修改 last30days 或 agent-reach。",
        ],
    }


def _load_plan_file(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ConfigurationError("plan-file 顶层必须是对象")
    return dict(payload)


def _parse_scoped_value(value: str, default_scope: str) -> Tuple[str, str]:
    prefix, separator, remainder = value.partition(":")
    if separator and prefix in SCOPES:
        return prefix, remainder
    return default_scope, value


QUERY_INTENT_GROUPS = (
    (
        "purchase_selection_recommendation",
        "satisfaction_recommendation_repurchase",
        "installation_compatibility_usage_scenario",
    ),
    (
        "failure_complaint_return_alternative",
        "diy_modification_workaround",
        "feature_request_reverse_need_idea",
    ),
)


def _new_run_dir(project_dir: Path, now: Optional[datetime] = None) -> Path:
    opportunity = project_dir / "market_opportunity"
    opportunity.mkdir(parents=True, exist_ok=True)
    stamp = (now or utc_now()).astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
    candidate = opportunity / ("consumer_voice_" + stamp)
    if candidate.exists():
        candidate = opportunity / ("consumer_voice_%s_%s" % (stamp, uuid.uuid4().hex[:6]))
    candidate.mkdir(parents=True, exist_ok=False)
    if os.name != "nt":
        os.chmod(candidate, 0o700)
    return candidate


def _select_project_segments(
    project_dir: Path,
    run_dir: Path,
    runner: Callable[[Sequence[str], float], subprocess.CompletedProcess] = default_runner,
) -> Dict[str, Any]:
    analysis = project_dir / "market_opportunity" / "07_opportunity_analysis.json"
    dashboard = project_dir / "market_opportunity" / "市场机会深挖看板.html"
    manifest = project_dir / "project_manifest.json"
    if not manifest.is_file() or not analysis.is_file() or not dashboard.is_file():
        raise ConfigurationError(
            "project-dir 缺少 project_manifest.json、07_opportunity_analysis.json 或原机会看板"
        )
    python_report = detect_last30days_python(runner)
    if not python_report["available"]:
        raise ConfigurationError("找不到 Python 3.12+，无法调用固定 Top3 选择逻辑")
    selector = Path(__file__).resolve().parent / "consumer_product_report.py"
    output = run_dir / "selected_segments.json"
    completed = runner(
        [
            str(python_report["selected"]),
            str(selector),
            "select-segments",
            "--analysis",
            str(analysis),
            "--output",
            str(output),
        ],
        120.0,
    )
    if completed.returncode != 0 or not output.is_file():
        raise CollectorError("Top3 选择失败：%s" % redact_text(completed.stderr or completed.stdout))
    payload = json.loads(output.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise CollectorError("selected_segments.json 顶层无效")
    result = dict(payload)
    result["project_snapshot"] = {
        "capture_stage": "consumer_voice_plan",
        "captured_at": iso_utc(),
        "opportunity_dashboard": _source_artifact(dashboard),
    }
    write_json(output, result)
    return result


def _project_query_queues(
    selection: Mapping[str, Any],
    end_at: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    source = selection.get("source") if isinstance(selection.get("source"), Mapping) else {}
    category_term = str(source.get("keyword") or source.get("category_node") or "").strip()
    if not category_term:
        category_term = "target product category"
    selected = selection.get("selected_segments") if isinstance(selection.get("selected_segments"), list) else []
    scope_terms: Dict[str, str] = {"category_30d": category_term}
    for item in selected:
        if not isinstance(item, Mapping):
            continue
        scope = str(item.get("segment_id") or "")
        if scope not in SCOPES:
            continue
        raw_terms: List[str] = []
        canonical_key = str(item.get("canonical_key") or "").strip()
        if canonical_key:
            canonical_value = canonical_key.rsplit(":", 1)[-1]
            raw_terms.append(re.sub(r"[_-]+", " ", canonical_value).strip())
        raw_terms.append(str(item.get("feature") or "").strip())
        raw_terms.extend(
            str(value).strip()
            for value in item.get("synonyms", [])
            if str(value).strip()
        )
        unique_terms: List[str] = []
        seen_terms: set[str] = set()
        for value in raw_terms:
            normalized = re.sub(r"\s+", " ", value).strip()
            marker = normalized.casefold()
            if not normalized or marker in seen_terms:
                continue
            seen_terms.add(marker)
            if re.fullmatch(r"[A-Za-z0-9+#.]+", normalized):
                unique_terms.append(normalized)
            else:
                unique_terms.append('"%s"' % normalized.replace('"', " "))
        segment_filter = " OR ".join(unique_terms)
        scope_terms[scope] = (
            "%s (%s)" % (category_term, segment_filter)
            if segment_filter
            else category_term
        )
    end = parse_timestamp(end_at)
    if end is None:
        raise ConfigurationError("end_at 无效")
    as_of = end.astimezone(timezone.utc).date().isoformat()
    queues: List[Dict[str, Any]] = []
    query_rows: List[Dict[str, Any]] = []
    agent_tasks: List[Dict[str, Any]] = []
    for scope in SCOPES:
        if scope != "category_30d" and scope not in scope_terms:
            continue
        base = scope_terms[scope]
        days = scope_window_days(scope)
        texts = (
            '%s (buying OR choose OR recommend OR satisfied OR repurchase OR install OR compatibility OR "real use")'
            % base,
            '%s (failure OR complaint OR return OR alternative OR DIY OR modification OR workaround OR wish OR "do not want")'
            % base,
        )
        for index, (query_text, intents) in enumerate(zip(texts, QUERY_INTENT_GROUPS), 1):
            query_variant_id = "%s_q%d" % (scope, index)
            metadata = {"intents": list(intents), "days": days, "as_of_utc_date": as_of}
            queues.append(
                {
                    "source": "last30days",
                    "backend": "last30days",
                    "scope": scope,
                    "query_id": query_variant_id,
                    "query_text": query_text,
                    "priority": 10 + len(queues),
                    "metadata": metadata,
                }
            )
            query_rows.append(
                {
                    "query_id": query_variant_id,
                    "scope_id": scope,
                    "query_text": query_text,
                    "intent_coverage": list(intents),
                    "days": days,
                    "as_of_utc_date": as_of,
                    "planned_sources": ["last30days", "agent-reach-gap-fill"],
                }
            )
            agent_tasks.append(
                {
                    "task_id": "ar_" + query_variant_id,
                    "scope_id": scope,
                    "query_id": query_variant_id,
                    "query_text": query_text,
                    "status": "pending_agent_execution",
                    "instruction": (
                        "先依据 agent-reach doctor 的 active_backend 仅深读重点 Reddit/X 线程；"
                        "YouTube 评论由官方 Data API 分页采集，agent-reach 只补 last30days 的 Reddit/X 缺口。"
                    ),
                    "output_path": "agent_reach/%s.json" % query_variant_id,
                }
            )
    query_plan = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": iso_utc(),
        "end_at": iso_utc(end),
        "top3_selection": selection.get("top3_selection"),
        "segments": selected,
        "project_snapshot": selection.get("project_snapshot"),
        "constraints": {
            "max_queries_per_scope": 2,
            "semantic_intents": [intent for group in QUERY_INTENT_GROUPS for intent in group],
            "category_window_days": 30,
            "segment_window_days": 90,
        },
        "queries": query_rows,
    }
    agent_queue = {
        "schema_version": SCHEMA_VERSION,
        "execution_mode": "agent_queue",
        "doctor_command": ["agent-reach", "doctor", "--json"],
        "check_update_command": ["agent-reach", "check-update"],
        "tasks": agent_tasks,
        "import_contract": {
            "format": "consumer_voice_external_records_v1",
            "required_fields": [
                "platform",
                "content_id_or_deterministic_fallback_fields",
                "parent_content_id",
                "author_label_or_hash",
                "published_at",
                "exact_text",
                "url",
                "scope_id",
                "query_id",
            ],
            "dedupe": "collector hard identity only; never text-only or parent-URL-only",
            "handoff": "place each task JSON at output_path, then use prepare-coding after import/integration",
        },
    }
    return queues, query_plan, agent_queue


def _find_project_run_dir(project_dir: Path) -> Path:
    opportunity = project_dir / "market_opportunity"
    candidates = sorted(
        (
            child
            for child in opportunity.glob("consumer_voice_*")
            if child.is_dir() and (child / "collector.sqlite3").is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    if not candidates:
        raise ConfigurationError("project-dir 下没有已计划的 consumer_voice 运行目录，请先执行 plan")
    return candidates[0]


def _reusable_planned_project_run(
    project_dir: Path,
    requested_level: Optional[str],
) -> Optional[Tuple[Path, Path]]:
    """Return the latest explicit plan instead of silently creating a second task."""
    try:
        run_dir = _find_project_run_dir(project_dir)
    except ConfigurationError:
        return None
    db_path = run_dir / "collector.sqlite3"
    try:
        with CollectorStore(db_path) as store:
            task_id = store.resolve_task_id(None)
            row = store.task_row(task_id)
            if str(row["status"]) != "planned":
                return None
            if requested_level and requested_level != str(row["research_level"]):
                return None
    except (CollectorError, sqlite3.Error, OSError):
        return None
    return db_path, run_dir


def task_registry_path() -> Path:
    configured = os.environ.get("LCADMO_TASK_REGISTRY", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "lc_amazon_market_opportunity" / "task_registry.json"


def register_task(task_id: str, db_path: Path, run_dir: Optional[Path]) -> None:
    path = task_registry_path()
    registry: Dict[str, Any] = {"schema_version": SCHEMA_VERSION, "tasks": {}}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping) and isinstance(loaded.get("tasks"), Mapping):
                registry = {"schema_version": SCHEMA_VERSION, "tasks": dict(loaded["tasks"])}
        except (OSError, json.JSONDecodeError):
            pass
    registry["tasks"][task_id] = {
        "db_path": str(db_path.resolve()),
        "run_dir": str(run_dir.resolve()) if run_dir else None,
        "updated_at": iso_utc(),
    }
    _atomic_write_text(path, json.dumps(registry, ensure_ascii=False, indent=2) + "\n", mode=0o600)


def resolve_registered_task(task_id: str) -> Tuple[Path, Optional[Path]]:
    path = task_registry_path()
    if not path.is_file():
        raise ConfigurationError("task registry 不存在，无法只凭 --task-id 定位任务")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ConfigurationError("task registry 权限必须为 0600")
    payload = json.loads(path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, Mapping) else None
    item = tasks.get(task_id) if isinstance(tasks, Mapping) else None
    if not isinstance(item, Mapping) or not item.get("db_path"):
        raise ConfigurationError("task registry 中没有任务：%s" % task_id)
    run = Path(str(item["run_dir"])) if item.get("run_dir") else None
    return Path(str(item["db_path"])), run


def resolve_storage_paths(args: argparse.Namespace, create: bool = False) -> Tuple[Path, Optional[Path], Optional[Path]]:
    project_dir = Path(args.project_dir).expanduser().resolve() if getattr(args, "project_dir", None) else None
    run_dir = Path(args.run_dir).expanduser().resolve() if getattr(args, "run_dir", None) else None
    db = Path(args.db).expanduser().resolve() if getattr(args, "db", None) else None
    if db is None and run_dir is None and project_dir is None and getattr(args, "task_id", None):
        db, run_dir = resolve_registered_task(str(args.task_id))
    if create and project_dir and run_dir is None:
        run_dir = _new_run_dir(project_dir)
    if not create and project_dir and run_dir is None and db is None:
        run_dir = _find_project_run_dir(project_dir)
    if run_dir is not None:
        _secure_directory(run_dir)
        db = db or (run_dir / "collector.sqlite3")
    if db is None:
        raise ConfigurationError("必须提供 --project-dir、--run-dir 或高级参数 --db")
    return db, project_dir, run_dir


def _queues_from_arguments(args: argparse.Namespace, plan_file: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw_queues = plan_file.get("queues", plan_file.get("batches", []))
    if raw_queues and not isinstance(raw_queues, list):
        raise ConfigurationError("plan-file queues 必须是数组")
    queues: List[Dict[str, Any]] = [dict(item) for item in raw_queues if isinstance(item, Mapping)]
    for value in args.video_id or []:
        scope, video_id = _parse_scoped_value(value, args.scope)
        queues.append(
            {
                "source": "youtube",
                "backend": args.backend,
                "scope": scope,
                "video_id": video_id,
                "video_url": "https://www.youtube.com/watch?v=" + video_id,
            }
        )
    for value in args.video_url or []:
        scope, video_url = _parse_scoped_value(value, args.scope)
        query = dict(urllib_parse.parse_qsl(urllib_parse.urlsplit(video_url).query))
        queues.append(
            {
                "source": "youtube",
                "backend": args.backend,
                "scope": scope,
                "video_id": query.get("v"),
                "video_url": video_url,
            }
        )
    for value in args.query or []:
        scope, query_text = _parse_scoped_value(value, args.scope)
        queues.append(
            {
                "source": "youtube",
                "backend": "yt-dlp" if args.backend == "auto" else args.backend,
                "scope": scope,
                "query_text": query_text if query_text.startswith("ytsearch") else "ytsearch50:" + query_text,
            }
        )
    return queues


def create_plan_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    db_path, project_dir, run_dir = resolve_storage_paths(args, create=True)
    plan_file = _load_plan_file(args.plan_file)
    declared_level = plan_file.get("research_level") or (plan_file.get("research_plan") or {}).get(
        "research_level"
    )
    level_was_explicit = bool(declared_level or args.research_level)
    file_level = str(declared_level or args.research_level or "quick")
    if not level_was_explicit:
        sys.stderr.write(DEFAULT_LEVEL_REMINDER + "\n")
        sys.stderr.flush()
    fixed = research_plan(file_level, not args.no_reminders, args.reminder_interval_minutes)
    supplied_research_plan = plan_file.get("research_plan")
    if isinstance(supplied_research_plan, Mapping):
        for key in ("sample_target", "time_budget_minutes"):
            if key in supplied_research_plan and supplied_research_plan[key] != fixed[key]:
                raise ConfigurationError("plan-file 不得覆盖固定档位的 %s" % key)
    end_at = str(plan_file.get("end_at") or args.end_at or iso_utc())
    query_plan_payload: Optional[Dict[str, Any]] = None
    agent_queue_payload: Optional[Dict[str, Any]] = None
    selection: Optional[Dict[str, Any]] = None
    if project_dir is not None:
        if run_dir is None:
            raise ConfigurationError("project plan 未创建 run-dir")
        selection = _select_project_segments(project_dir, run_dir)
        queues, query_plan_payload, agent_queue_payload = _project_query_queues(selection, end_at)
        write_json(run_dir / "query_plan.json", query_plan_payload)
        write_json(run_dir / "agent_reach_queue.json", agent_queue_payload)
    else:
        queues = _queues_from_arguments(args, plan_file)
    topic = str(
        plan_file.get("topic")
        or args.topic
        or ((selection or {}).get("source") or {}).get("keyword")
        or ""
    )
    task_name = str(plan_file.get("task_name") or args.task_name or "consumer-voice-%s" % file_level)
    youtube_setup = None
    if not args.youtube_config.exists():
        youtube_setup = setup_youtube_api_config(args.youtube_config)
    youtube_config, youtube_channel = load_youtube_config_for_collection(args.youtube_config)
    if youtube_setup is not None:
        youtube_channel = dict(youtube_channel)
        youtube_channel["first_use_setup"] = youtube_setup
    daily_quota_units = int(youtube_config["daily_quota_units"])
    with CollectorStore(db_path) as store:
        result = store.create_task(
            task_name,
            topic,
            file_level,
            end_at,
            queues,
            reminders_enabled=not args.no_reminders,
            reminder_interval_minutes=args.reminder_interval_minutes,
            research_level_explicit=level_was_explicit,
            daily_quota_units=daily_quota_units,
            project_dir=project_dir,
            run_dir=run_dir,
            task_id=args.task_id,
        )
        research_plan_path = write_research_plan_artifact(
            store,
            str(result["task_id"]),
            run_dir or db_path.parent,
            known_secrets=(str(youtube_config.get("api_key") or ""),),
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "task_id": result["task_id"],
        "research_plan": result["research_plan"],
        "collection_policy": result["collection_policy"],
        "end_at": result["end_at"],
        "queue_count": len(result["queues"]),
        "queues": result["queues"],
        "project_dir": str(project_dir) if project_dir else None,
        "run_dir": str(run_dir) if run_dir else None,
        "database": str(db_path),
        "selected_segments": selection.get("selected_segments", []) if selection else [],
        "query_plan_path": str(run_dir / "query_plan.json") if run_dir else None,
        "agent_reach_queue_path": str(run_dir / "agent_reach_queue.json") if run_dir else None,
        "research_plan_path": str(research_plan_path),
        "youtube_channel_status": youtube_channel["status"],
        "youtube_configuration": youtube_channel,
        "warning": "提醒为 non_blocking；档位目标与时限不可自定义。",
    }
    register_task(str(result["task_id"]), db_path, run_dir)
    output = args.output or (run_dir / "collector_plan_receipt.json" if run_dir else None)
    if output:
        write_json(output, payload)
    return payload


def _runtime_api_config(path: Path) -> Tuple[str, int]:
    if not path.exists():
        return "", DEFAULT_DAILY_YOUTUBE_QUOTA
    config, _ = load_youtube_config_for_collection(path)
    return (str(config["api_key"]) if config["enabled"] else "", int(config["daily_quota_units"]))


def _write_or_print(payload: Mapping[str, Any], output: Optional[Path] = None) -> None:
    safe = redact_value(payload)
    if output is not None:
        write_json(output, safe)
    sys.stdout.write(json.dumps(safe, ensure_ascii=False, indent=2) + "\n")


def _add_db_task_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-dir", type=Path, help="market_project root (preferred)")
    parser.add_argument("--run-dir", type=Path, help="existing consumer_voice run directory")
    parser.add_argument("--db", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--task-id", help="Task id; optional when run-dir has one task")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="可恢复的消费者声音采集器（Python 3.9+ 标准库）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="创建固定档位采集计划和 SQLite 任务")
    plan.add_argument("--project-dir", type=Path, help="market_project root (preferred)")
    plan.add_argument("--run-dir", type=Path)
    plan.add_argument("--db", type=Path, help=argparse.SUPPRESS)
    plan.add_argument("--task-id")
    plan.add_argument("--task-name")
    plan.add_argument("--topic", default="")
    plan.add_argument("--research-level", "--profile", choices=tuple(RESEARCH_LEVELS), default=None)
    plan.add_argument("--end-at", help="ISO 8601; default now UTC")
    plan.add_argument("--plan-file", type=Path)
    plan.add_argument("--output", type=Path)
    plan.add_argument("--scope", choices=SCOPES, default="category_30d")
    plan.add_argument("--backend", choices=("auto", "youtube-data-api", "yt-dlp"), default="auto")
    plan.add_argument("--video-id", action="append")
    plan.add_argument("--video-url", action="append")
    plan.add_argument("--query", action="append")
    plan.add_argument("--youtube-config", type=Path, default=default_youtube_config_path())
    plan.add_argument("--reminder-interval-minutes", type=int, default=DEFAULT_REMINDER_INTERVAL_MINUTES)
    plan.add_argument("--no-reminders", action="store_true")

    for name in ("run", "resume"):
        child = subparsers.add_parser(name, help="执行采集" if name == "run" else "从检查点续跑")
        _add_db_task_arguments(child)
        child.add_argument("--youtube-config", type=Path, default=default_youtube_config_path())
        child.add_argument("--yt-dlp", default="yt-dlp")
        child.add_argument("--http-timeout-seconds", type=float, default=20.0)
        child.add_argument("--output", type=Path)
        child.add_argument("--research-level", choices=tuple(RESEARCH_LEVELS))

    prepare = subparsers.add_parser("prepare-coding", help="生成逐条编码批次")
    _add_db_task_arguments(prepare)
    prepare.add_argument("--output-dir", type=Path)
    prepare.add_argument("--batch-size", type=int, default=200)
    prepare.add_argument("--include-coded", action="store_true")

    merge = subparsers.add_parser("merge-coding", help="校验并回写编码结果")
    _add_db_task_arguments(merge)
    merge.add_argument("--input", type=Path, action="append", required=True)

    receipt = subparsers.add_parser("receipt", help="输出样本、时间、quota 与成本收据")
    _add_db_task_arguments(receipt)
    receipt.add_argument("--output", type=Path)
    timing_action = receipt.add_mutually_exclusive_group()
    timing_action.add_argument("--phase-start", choices=tuple(TIMED_PHASES))
    timing_action.add_argument("--phase-heartbeat", metavar="PHASE_RUN_ID")
    timing_action.add_argument("--phase-end", metavar="PHASE_RUN_ID")
    timing_action.add_argument("--phase-abandon", metavar="PHASE_RUN_ID")
    timing_action.add_argument("--gate", action="store_true")
    receipt.add_argument("--workflow-session-id")
    receipt.add_argument("--event-id")
    receipt.add_argument("--next-phase", choices=tuple(TIMED_PHASES))

    doctor = subparsers.add_parser("doctor", help="只读检查本地采集依赖")
    doctor.add_argument("--project-dir", type=Path)
    doctor.add_argument("--run-dir", type=Path)
    doctor.add_argument("--db", type=Path)
    doctor.add_argument("--task-id")
    doctor.add_argument("--youtube-config", type=Path, default=default_youtube_config_path())

    setup = subparsers.add_parser("youtube-api-setup", help="以 0600 写入本地 YouTube API 配置")
    setup.add_argument("--config", type=Path, default=default_youtube_config_path())

    check = subparsers.add_parser("youtube-api-check", help="联网执行官方只读请求并验证配置")
    check.add_argument("--config", type=Path, default=default_youtube_config_path())
    return parser


def execute(args: argparse.Namespace) -> Mapping[str, Any]:
    if args.command == "plan":
        return create_plan_from_args(args)
    if args.command in {"run", "resume"}:
        create_new_project_run = bool(
            args.command == "run" and args.project_dir and not args.run_dir and not args.db
        )
        if create_new_project_run:
            reusable = _reusable_planned_project_run(
                Path(args.project_dir).expanduser().resolve(), args.research_level
            )
            if reusable is not None:
                db_path, run_dir = reusable
            else:
                plan_args = argparse.Namespace(
                    command="plan",
                    project_dir=args.project_dir,
                    run_dir=None,
                    db=args.db,
                    task_id=args.task_id,
                    task_name=None,
                    topic="",
                    research_level=args.research_level,
                    end_at=None,
                    plan_file=None,
                    output=None,
                    scope="category_30d",
                    backend="auto",
                    video_id=None,
                    video_url=None,
                    query=None,
                    youtube_config=args.youtube_config,
                    reminder_interval_minutes=DEFAULT_REMINDER_INTERVAL_MINUTES,
                    no_reminders=False,
                )
                planned = create_plan_from_args(plan_args)
                db_path = Path(str(planned["database"]))
                run_dir = Path(str(planned["run_dir"]))
        else:
            db_path, _, run_dir = resolve_storage_paths(args, create=False)
        youtube_setup = None
        if not args.youtube_config.exists():
            youtube_setup = setup_youtube_api_config(args.youtube_config)
        youtube_config, youtube_channel = load_youtube_config_for_collection(args.youtube_config)
        key = str(youtube_config["api_key"]) if youtube_config["enabled"] else ""
        with CollectorStore(db_path) as store:
            task_id = store.resolve_task_id(args.task_id)
            if args.command == "resume":
                store.upgrade_research_level(task_id, args.research_level)
            elif args.research_level and args.research_level != store.task_row(task_id)["research_level"]:
                raise ConfigurationError("已有任务请使用 resume --research-level 升档")
            service = CollectorService(
                store,
                api_key=key,
                yt_dlp_binary=args.yt_dlp,
                http_timeout=args.http_timeout_seconds,
                youtube_config=youtube_config,
                global_quota_ledger_path=youtube_global_quota_ledger_path(args.youtube_config),
            )
            result = service.run(task_id, resume=args.command == "resume")
            result["youtube_channel_status"] = youtube_channel["status"]
            result["youtube_configuration"] = youtube_channel
            if youtube_setup is not None or youtube_channel["status"] != "enabled":
                result["youtube_setup"] = youtube_setup or youtube_channel
            result["contract_artifacts"] = write_collection_contract_artifacts(
                store,
                task_id,
                result,
                run_dir or db_path.parent,
                known_secrets=(key,),
            )
        output = args.output or (run_dir / "collection_receipt.json" if run_dir else None)
        if output:
            write_json(output, redact_value(result))
        return result
    if args.command == "prepare-coding":
        db_path, _, run_dir = resolve_storage_paths(args, create=False)
        with CollectorStore(db_path) as store:
            task_id = store.resolve_task_id(args.task_id)
            output_dir = args.output_dir or ((run_dir or db_path.parent) / "coding_batches")
            return prepare_coding(store, task_id, output_dir, args.batch_size, args.include_coded)
    if args.command == "merge-coding":
        db_path, _, _ = resolve_storage_paths(args, create=False)
        with CollectorStore(db_path) as store:
            task_id = store.resolve_task_id(args.task_id)
            return merge_coding(store, task_id, args.input)
    if args.command == "receipt":
        db_path, _, run_dir = resolve_storage_paths(args, create=False)
        with CollectorStore(db_path) as store:
            task_id = store.resolve_task_id(args.task_id)
            timing_action: Optional[Mapping[str, Any]] = None
            manifest_recovery: Optional[Mapping[str, Any]] = None
            plain_receipt = not any(
                (
                    args.phase_start,
                    args.phase_heartbeat,
                    args.phase_end,
                    args.phase_abandon,
                    args.gate,
                )
            )
            if plain_receipt or args.phase_start == "manifest_finalize":
                manifest_recovery = store.recover_manifest_finalize_intents(
                    task_id,
                    abandon_running=True,
                    reason=(
                        "receipt_recovery" if plain_receipt else "next_timed_finalize_recovery"
                    ),
                )
            if args.phase_start:
                if not args.workflow_session_id:
                    raise ConfigurationError("--phase-start 必须同时提供 --workflow-session-id")
                timing_action = store.begin_timing_phase(
                    task_id,
                    args.phase_start,
                    args.workflow_session_id,
                )
            elif args.phase_heartbeat:
                if not args.event_id:
                    raise ConfigurationError("--phase-heartbeat 必须同时提供幂等 --event-id")
                timing_action = store.heartbeat_timing_phase(
                    task_id,
                    args.phase_heartbeat,
                    args.event_id,
                )
            elif args.phase_end:
                if not args.event_id:
                    raise ConfigurationError("--phase-end 必须同时提供幂等 --event-id")
                timing_action = store.end_timing_phase(
                    task_id,
                    args.phase_end,
                    args.event_id,
                )
            elif args.phase_abandon:
                timing_action = store.abandon_timing_phase(task_id, args.phase_abandon)
            elif args.gate:
                timing_action = store.timing_gate(task_id, args.next_phase)
            result = build_receipt(store, task_id)
            if timing_action is not None:
                result["timing_action"] = timing_action
            if manifest_recovery is not None:
                result["manifest_finalize_recovery"] = manifest_recovery
            coding_path = (run_dir or db_path.parent) / "social_voice_coding.json"
            result["coding_artifact"] = {
                "status": "existing" if coding_path.is_file() else "not_materialized",
                "path": str(coding_path),
            }
            result["contract_artifacts"] = write_collection_contract_artifacts(
                store,
                task_id,
                result,
                run_dir or db_path.parent,
            )
        output = args.output or (run_dir / "collection_receipt.json" if run_dir else None)
        if output:
            write_json(output, redact_value(result))
        return result
    if args.command == "doctor":
        db_path = args.db
        if args.project_dir or args.run_dir or args.task_id:
            try:
                db_path, _, _ = resolve_storage_paths(args, create=False)
            except ConfigurationError:
                db_path = None
        return doctor_report(db_path, args.youtube_config)
    if args.command == "youtube-api-setup":
        return setup_youtube_api_config(args.config)
    if args.command == "youtube-api-check":
        return youtube_api_live_check(args.config)
    raise CollectorError("未知命令")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = execute(args)
        _write_or_print(result)
        return 0
    except (CollectorError, ConfigurationError, json.JSONDecodeError, OSError, sqlite3.Error) as exc:
        error = {"status": "error", "error": redact_text(exc)}
        sys.stderr.write(json.dumps(error, ensure_ascii=False) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

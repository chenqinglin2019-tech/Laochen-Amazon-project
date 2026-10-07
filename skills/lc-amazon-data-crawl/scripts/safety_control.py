"""Local safety controls for the Amazon/SellerSprite crawler.

This module deliberately has no dependency on the cloud-auth gate, Chrome
profiles, extension storage, cookies, or provider credentials.  It only
persists a minimal local pause record after an observed risk signal.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import random
import tempfile
import threading
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

from run_outcome import current_run_id, replace_with_retry, write_heartbeat

try:  # POSIX process lock
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    _fcntl = None

try:  # Windows process lock
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - POSIX
    _msvcrt = None


SAFETY_SCHEMA_VERSION = 1
DEFAULT_RISK_COOLDOWN_SECONDS = 24 * 60 * 60
LOCK_SENTINEL_OFFSET = 1 << 30
# Upper bounds for persisted throttle deadlines, so a clock/timezone change or
# a corrupted record can never turn into hours of silent waiting.
MAX_PERSISTED_WAIT_SECONDS = {
    "rest_until": 25 * 60,
    "next_allowed_at": 2 * 60,
    "captcha_cooldown_until": 15 * 60,
}
OPERATION_MODES = ("supervised", "unattended")


def operation_mode(value: Any) -> str:
    mode = str(value or "supervised").strip().lower()
    if mode not in OPERATION_MODES:
        raise ValueError("operation_mode 只能是 supervised 或 unattended。")
    return mode


def apply_operation_policy(runtime: Any, mode: str, *, image: bool = False) -> None:
    """Override only traffic and waiting controls, never crawl semantics."""

    mode = operation_mode(mode)
    runtime.operation_mode = mode
    runtime.page_timeout = 90
    runtime.page_scroll_max_rounds = 18
    runtime.page_scroll_stable_rounds = 2
    if getattr(runtime, "mode", "") == "storefront":
        runtime.storefront_plugin_stable_seconds = 10.0
    runtime.delay_seconds_min, runtime.delay_seconds_max = (
        (20.0, 30.0) if mode == "supervised" else (45.0, 75.0)
    )
    runtime.batch_pause_pages_min = runtime.batch_pause_pages_max = (
        20 if mode == "supervised" else 10
    )
    runtime.batch_pause_seconds_min, runtime.batch_pause_seconds_max = (
        (180.0, 300.0) if mode == "supervised" else (900.0, 1200.0)
    )
    schedule = ((60.0, 60.0),) if mode == "supervised" else ((120.0, 120.0), (300.0, 300.0))
    if image:
        runtime.amazon_page_unavailable_retry_schedule_seconds = schedule
        if mode == "supervised":
            runtime.find_similar_timeout = 20
            runtime.lens_results_timeout = 40
            runtime.plugin_timeout = 20
            runtime.page_scroll_wait_seconds = 2.0
        else:
            runtime.find_similar_timeout = 12
            runtime.lens_results_timeout = 60
            runtime.plugin_timeout = 180
            runtime.page_scroll_wait_seconds = 1.0
    else:
        if hasattr(runtime, "amazon_page_retry_schedule_seconds"):
            runtime.amazon_page_retry_schedule_seconds = schedule
        else:
            runtime.amazon_page_retry_schedule = schedule
        runtime.plugin_timeout = 40 if mode == "supervised" else 180
        if mode == "supervised":
            runtime.page_scroll_wait_seconds = 2.0
        else:
            runtime.page_scroll_wait_seconds = 1.0
    runtime.manual_pause_timeout = 900 if mode == "supervised" else 0


def policy_description(runtime: Any) -> str:
    retry = next(
        (getattr(runtime, name) for name in (
            "amazon_page_unavailable_retry_schedule_seconds",
            "amazon_page_retry_schedule_seconds",
            "amazon_page_retry_schedule",
        ) if hasattr(runtime, name)),
        (),
    )
    details = (
        f"运行策略：{runtime.operation_mode}；导航 {runtime.delay_seconds_min:g}–"
        f"{runtime.delay_seconds_max:g} 秒；每 {runtime.batch_pause_pages_min} 次休息 "
        f"{runtime.batch_pause_seconds_min / 60:g}–{runtime.batch_pause_seconds_max / 60:g} 分钟"
        + ("，每 100 次改为 10–12 分钟" if runtime.operation_mode == "supervised" else "")
        + f"；普通故障等待 {retry}；页面 {runtime.page_timeout} 秒；插件 {runtime.plugin_timeout} 秒；"
        f"预滚动自适应（底部检查每次≤{runtime.page_scroll_wait_seconds:g} 秒）；"
        + (f"人工等待最多 {runtime.manual_pause_timeout} 秒" if runtime.operation_mode == "supervised"
         else "需人工介入时立即保存断点退出")
    )
    if hasattr(runtime, "find_similar_timeout"):
        details += f"；找相似 {runtime.find_similar_timeout} 秒；Lens 基础 {runtime.lens_results_timeout} 秒"
    elif runtime.operation_mode == "supervised" and getattr(runtime, "mode", "") != "storefront":
        details += "；列表插件有效进展时总上限 80 秒"
    return details


class SafetyPausedError(RuntimeError):
    """Raised before a crawler-owned action would add new remote traffic.

    ``kind`` is ``risk_pause``, ``review_not_due`` or ``lock_held`` and maps to
    the run_outcome exit codes.
    """

    def __init__(self, message: str, *, kind: str = "risk_pause", resume_at: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.resume_at = resume_at


class SafetyWaitCancelled(RuntimeError):
    """A cancelled wait must not consume an action or its saved rest."""


@dataclass(frozen=True)
class RiskSignal:
    platform: str
    reason: str
    message: str
    cooldown_seconds: int = DEFAULT_RISK_COOLDOWN_SECONDS
    retry_after_seconds: int = 0


def parse_retry_after(value: str, now: Optional[dt.datetime] = None) -> int:
    raw = str(value or "").strip()
    if raw.isdigit():
        return int(raw)
    try:
        target = parsedate_to_datetime(raw)
        current = now or dt.datetime.now(target.tzinfo)
        return max(int((target - current).total_seconds()), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _redacted_page_url(value: Any) -> str:
    """Keep a diagnostic location without persisting query tokens or fragments."""

    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        if parsed.scheme and parsed.netloc:
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))[:500]
    except ValueError:
        pass
    return raw.split("?", 1)[0].split("#", 1)[0][:500]


RISK_BODY_MAX_CHARS = 4000
# Titles Amazon uses for block pages themselves (search/product titles contain
# the user's keyword or product name and must never trip a pause).
AMAZON_BLOCK_TITLES = {
    "robot check": ("captcha_or_robot_check", "Amazon 要求机器人验证。"),
    "sorry! something went wrong!": ("captcha_or_robot_check", "Amazon 要求验证。"),
    "error: the request could not be satisfied": ("access_denied", "Amazon 拒绝访问当前页面。"),
    "access denied": ("access_denied", "Amazon 拒绝访问当前页面。"),
    "429 too many requests": ("rate_limited", "Amazon 提示请求过于频繁。"),
}
AMAZON_RISK_MARKERS = (
    ("captcha", "captcha_or_robot_check", "Amazon 要求验证码或机器人验证。"),
    ("robot check", "captcha_or_robot_check", "Amazon 要求机器人验证。"),
    ("sorry, we just need to make sure", "captcha_or_robot_check", "Amazon 要求验证。"),
    ("click the button below to continue shopping", "captcha_or_robot_check", "Amazon 要求确认后继续。"),
    ("automated access", "automated_access", "Amazon 拒绝自动化访问。"),
    ("unusual traffic", "unusual_traffic", "Amazon 检测到异常流量。"),
    ("异常流量", "unusual_traffic", "Amazon 检测到异常流量。"),
    ("too many requests", "rate_limited", "Amazon 提示请求过于频繁。"),
    ("request was blocked", "rate_limited", "Amazon 阻止了当前请求。"),
    ("request has been blocked", "rate_limited", "Amazon 阻止了当前请求。"),
    ("请求被阻止", "rate_limited", "Amazon 阻止了当前请求。"),
    ("access denied", "access_denied", "Amazon 拒绝访问当前页面。"),
    ("you don't have permission to access", "access_denied", "Amazon 拒绝访问当前页面。"),
    ("拒绝访问", "access_denied", "Amazon 拒绝访问当前页面。"),
)


def classify_amazon_risk(
    *,
    http_status: Optional[int],
    title: str = "",
    body_text: str = "",
    retry_after: str = "",
) -> Optional[RiskSignal]:
    """Return only high-confidence Amazon traffic-risk signals.

    Transport 5xx and an ordinary missing DOM are intentionally not risks:
    they retain the existing page-recovery behavior.  403/429 and explicit
    robot/traffic pages must never be retried automatically.
    """

    if http_status == 429:
        return RiskSignal("amazon", "http_429", "Amazon 返回 429 限流响应。", retry_after_seconds=parse_retry_after(retry_after))
    if http_status == 403:
        return RiskSignal("amazon", "http_403", "Amazon 拒绝访问当前页面。")
    # Amazon block/CAPTCHA pages are tiny.  On a full listing or product page
    # the title and body carry the user's keyword and product names ("Access
    # Denied Sign", "Captcha Puzzle Book"), so text markers count only on short
    # pages; long pages trip only on an exact block-page title.
    title_text = _normalized_text(title)
    body = _normalized_text(body_text)
    exact = AMAZON_BLOCK_TITLES.get(title_text.strip(" .:"))
    if exact:
        return RiskSignal("amazon", exact[0], exact[1])
    if len(body) > RISK_BODY_MAX_CHARS:
        return None
    text = f"{title_text} {body}"
    for marker, reason, message in AMAZON_RISK_MARKERS:
        if marker in text:
            return RiskSignal("amazon", reason, message)
    return None


def classify_sellersprite_risk(text: str) -> Optional[RiskSignal]:
    """Classify only account/rate/verification messages shown by the plugin."""

    normalized = _normalized_text(text)
    markers = (
        ("访问频繁", "rate_limited", "卖家精灵提示访问过于频繁。"),
        ("请求过于频繁", "rate_limited", "卖家精灵提示请求过于频繁。"),
        ("too many requests", "rate_limited", "卖家精灵提示请求过于频繁。"),
        ("请求频繁", "rate_limited", "卖家精灵提示请求过于频繁。"),
        ("账号异常", "account_restricted", "卖家精灵提示账号异常。"),
        ("账号受限", "account_restricted", "卖家精灵提示账号受限。"),
        ("account restricted", "account_restricted", "卖家精灵提示账号受限。"),
        ("配额已用完", "quota_exhausted", "卖家精灵提示可用配额已耗尽。"),
        ("额度已用完", "quota_exhausted", "卖家精灵提示可用配额已耗尽。"),
        ("quota exceeded", "quota_exhausted", "卖家精灵提示可用配额已耗尽。"),
        ("验证失败", "verification_required", "卖家精灵要求额外验证。"),
        ("security verification", "verification_required", "卖家精灵要求额外验证。"),
    )
    for marker, reason, message in markers:
        if marker in normalized:
            return RiskSignal("sellersprite", reason, message, cooldown_seconds=0 if reason == "quota_exhausted" else DEFAULT_RISK_COOLDOWN_SECONDS)
    return None


def default_safety_root() -> Path:
    """A user-local root shared by generated runners without touching profiles."""

    return Path.home() / ".lc-amazon-data-crawl" / "safety"


def write_run_summary(job_dir: Path, mode: str, safety: "LocalSafetyController") -> None:
    """Write a separate operational snapshot without changing business exports."""
    try:
        state = json.loads((job_dir / "state.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        state = {}
    state = state if isinstance(state, dict) else {}
    traffic = safety._load_traffic()
    pause = safety._load_pause()
    summary = {
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "operation_mode": mode,
        "navigation_attempts_global": int(traffic.get("actions_count") or 0),
        "next_allowed_at": traffic.get("next_allowed_at"),
        "rest_until": traffic.get("rest_until"),
        "risk_reason": pause.get("reason") if pause else None,
        "risk_not_before": pause.get("not_before") if pause else None,
        "pending_count": len(state.get("queue") or state.get("pending") or []),
        "deferred_count": sum(len(state.get(key) or []) for key in ("deferred_tasks", "deferred_pages", "deferred_sources")),
        "has_current": bool(state.get("current") or state.get("in_flight")),
        "recent_failures": list(state.get("operation_recent_outcomes") or []).count(False),
        "consecutive_failures": int(state.get("operation_consecutive_failures") or 0),
        "skipped_count": len(state.get("skipped_items") or []),
        "safety_pause_file": str(safety.pause_path),
    }
    job_dir.mkdir(parents=True, exist_ok=True)
    target = job_dir / "run_summary.json"
    fd, name = tempfile.mkstemp(prefix=".run_summary.", dir=str(job_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        replace_with_retry(name, target)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def record_operational_outcome(state: Any, success: bool) -> bool:
    """Failure-window accounting for the current process only.

    Counters used to survive restarts, so after three failures every later run
    stopped on its first deferred item and never reached healthy work.
    """
    if state.data.get("operation_run_id") != current_run_id():
        state.data["operation_run_id"] = current_run_id()
        state.data["operation_recent_outcomes"] = []
        state.data["operation_consecutive_failures"] = 0
    outcomes = (list(state.data.get("operation_recent_outcomes") or []) + [bool(success)])[-20:]
    consecutive = 0 if success else int(state.data.get("operation_consecutive_failures") or 0) + 1
    state.data["operation_recent_outcomes"] = outcomes
    state.data["operation_consecutive_failures"] = consecutive
    state.flush()
    return consecutive >= 3 or outcomes.count(False) >= 5


class LocalSafetyController:
    """Persistent risk pause plus a single local crawler process lock."""

    def __init__(
        self,
        storage_root: Optional[Path] = None,
        *,
        clock: Callable[[], dt.datetime] = dt.datetime.now,
        batch_pause_pages_min: int = 20,
        batch_pause_pages_max: int = 20,
        batch_pause_seconds_min: float = 180,
        batch_pause_seconds_max: float = 300,
        mode: str = "supervised",
    ) -> None:
        self.storage_root = (storage_root or default_safety_root()).expanduser()
        self.pause_path = self.storage_root / "risk-pause.json"
        self.lock_path = self.storage_root / "crawler.lock"
        self.traffic_path = self.storage_root / "traffic-state.json"
        self._clock = clock
        self._lock_handle: Optional[Any] = None
        self._review_mode = False
        self._probe_sent = False
        self._probe_verified = False
        self._probe_key = ""
        self.job_label = ""
        self._action_lock = threading.Lock()
        self.mode = operation_mode(mode)
        self._batch_pause_pages_min = int(batch_pause_pages_min)
        self._batch_pause_pages_max = int(batch_pause_pages_max)
        self._batch_pause_seconds_min = float(batch_pause_seconds_min)
        self._batch_pause_seconds_max = float(batch_pause_seconds_max)
        self.work_key = ""
        self.status_path: Optional[Path] = None

    def _now(self) -> dt.datetime:
        return self._clock().replace(microsecond=0)

    @staticmethod
    def _parse_iso(value: Any) -> Optional[dt.datetime]:
        try:
            return dt.datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    def _load_pause(self) -> Optional[Dict[str, Any]]:
        try:
            value = json.loads(self.pause_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return None
        return dict(value) if isinstance(value, dict) and value.get("active") else None

    def _load_traffic(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.traffic_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            value = {}
        return dict(value) if isinstance(value, dict) else {}

    def _write_pause(self, value: Dict[str, Any]) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.pause_path.name}.", suffix=".tmp", dir=str(self.storage_root)
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            replace_with_retry(str(temp_path), self.pause_path)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def _write_traffic(self, value: Dict[str, Any]) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".traffic-state.", dir=str(self.storage_root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            replace_with_retry(name, self.traffic_path)
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass

    def set_work_key(self, key: str) -> None:
        self.work_key = str(key or "")

    def heartbeat(self, phase: str, *, until: str = "", detail: str = "") -> None:
        write_heartbeat(self.status_path, phase, until=until, detail=detail)

    def _wait_until(self, deadline: dt.datetime, reason: str, stop_event=None) -> None:
        remaining = max((deadline - self._now()).total_seconds(), 0.0)
        while remaining > 0:
            print(f"{reason}；剩余约 {remaining:.0f} 秒。", flush=True)
            self.heartbeat("waiting", until=deadline.isoformat(), detail=reason)
            chunk = min(remaining, 30.0)
            if stop_event is not None:
                if stop_event.wait(chunk):
                    raise SafetyWaitCancelled("采集节流等待已取消。")
            else:
                time.sleep(chunk)
            remaining = min(max((deadline - self._now()).total_seconds(), 0.0), remaining - chunk)

    def acquire(self) -> None:
        if self._lock_handle is not None:
            return
        self.storage_root.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            if _fcntl is not None:
                _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            elif _msvcrt is not None:  # pragma: no cover - Windows
                # Lock a sentinel byte far beyond the JSON so other processes
                # (guard, safety-status) can still read the holder record.
                handle.seek(LOCK_SENTINEL_OFFSET)
                _msvcrt.locking(handle.fileno(), _msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover
                raise SafetyPausedError("当前系统不支持本机采集进程锁。")
        except (BlockingIOError, OSError) as exc:
            handle.close()
            holder = self.lock_holder()
            raise SafetyPausedError(
                "本机已有 Amazon 数据采集任务运行"
                + (f"（进程 {holder.get('pid')}，开始于 {holder.get('acquired_at')}，任务 {holder.get('job') or '未知'}）" if holder else "")
                + "；为保护账号，本次未启动。不要重复启动，等待该进程结束。",
                kind="lock_held",
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "acquired_at": self._now().isoformat(), "job": self.job_label}, ensure_ascii=False))
        handle.flush()
        os.fsync(handle.fileno())
        self._lock_handle = handle

    def lock_holder(self) -> Dict[str, Any]:
        try:
            value = json.loads(self.lock_path.read_text(encoding="utf-8").strip() or "{}")
        except (OSError, ValueError, TypeError):
            return {}
        return dict(value) if isinstance(value, dict) else {}

    def release(self) -> None:
        handle, self._lock_handle = self._lock_handle, None
        if handle is None:
            return
        try:
            # Clear the holder record while still holding the lock, so a stale
            # pid can never be mistaken for a running crawl later.
            try:
                handle.seek(0)
                handle.truncate()
                handle.flush()
            except OSError:
                pass
            if _fcntl is not None:
                _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
            elif _msvcrt is not None:  # pragma: no cover - Windows
                handle.seek(LOCK_SENTINEL_OFFSET)
                _msvcrt.locking(handle.fileno(), _msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()

    def lock_is_held(self) -> bool:
        """Probe the crawler lock itself (another process holds it)."""
        if self._lock_handle is not None:
            return True
        if not self.lock_path.exists():
            return False
        try:
            handle = self.lock_path.open("a+", encoding="utf-8")
        except OSError:
            return False
        try:
            if _fcntl is not None:
                try:
                    _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                except (BlockingIOError, OSError):
                    return True
                _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
                return False
            if _msvcrt is not None:  # pragma: no cover - Windows
                handle.seek(LOCK_SENTINEL_OFFSET)
                try:
                    _msvcrt.locking(handle.fileno(), _msvcrt.LK_NBLCK, 1)
                except OSError:
                    return True
                handle.seek(LOCK_SENTINEL_OFFSET)
                _msvcrt.locking(handle.fileno(), _msvcrt.LK_UNLCK, 1)
                return False
            return False
        finally:
            handle.close()

    def begin(self, *, resume_after_review: bool = False) -> None:
        pause = self._load_pause()
        if pause is None:
            return
        not_before = self._parse_iso(pause.get("not_before"))
        now = self._now()
        automatic_probe = pause.get("kind") == "rate_probe" and not_before is not None and now >= not_before
        resume_at = not_before.isoformat(sep=" ") if not_before else ""
        if not resume_after_review and not automatic_probe:
            raise SafetyPausedError(self._pause_message(pause), kind="risk_pause", resume_at=resume_at)
        if not_before is not None and now < not_before:
            raise SafetyPausedError(
                f"风险暂停尚未到期，最早可在 {resume_at} 后人工复核恢复。",
                kind="review_not_due",
                resume_at=resume_at,
            )
        pause["review_requested_at"] = now.isoformat()
        pause["review_attempt_pending"] = True
        self._write_pause(pause)
        self._review_mode = True
        self._probe_sent = False
        self._probe_verified = False

    def note_risk_checked(self) -> None:
        """Crawlers call this after a loaded page passed the Amazon risk check."""
        if self._review_mode and self._probe_sent:
            self._probe_verified = True

    @property
    def review_probe_pending(self) -> bool:
        """A review/rate probe is running and has not yet passed the risk check."""
        return bool(self._review_mode and not self._probe_verified)

    @property
    def rate_probe_active(self) -> bool:
        pause = self._load_pause()
        return bool(self._review_mode and pause and pause.get("kind") == "rate_probe")

    def before_remote_action(self, action: str, stop_event=None) -> None:
        if stop_event is not None and stop_event.is_set():
            raise SafetyWaitCancelled("采集操作已取消。")
        pause = self._load_pause()
        if pause is not None and not (
            self._review_mode and bool(pause.get("review_attempt_pending"))
        ):
            raise SafetyPausedError(self._pause_message(pause, action=action), kind="risk_pause")
        if pause is not None and not self._probe_sent:
            # Any pending item may probe: binding the probe to one work key
            # deadlocked when that item was finished, skipped or in another job.
            self._probe_sent = True
            self._probe_key = self.work_key
        elif pause is not None and self._probe_verified and pause.get("platform") != "sellersprite":
            # The probe page passed the Amazon risk check: the review passed.
            self.complete_review_success()
        elif pause is not None and self._probe_verified and self.work_key == self._probe_key:
            # SellerSprite pause: the probe item may finish its own page work;
            # the pause clears when that page commits (complete_review_success).
            pass
        elif pause is not None:
            # One probe per run.  The probe never reached a risk verdict
            # (navigation error, timeout, plugin stall), so the pause stays and
            # no further traffic is sent in this run.
            raise SafetyPausedError(
                "复核页面没有成功加载到可判断的状态，风险暂停保持不变，本次运行停止。"
                "稍后再按 --resume-after-review 复核一次。",
                kind="risk_pause",
                resume_at=str(pause.get("not_before") or "").replace("T", " "),
            )
        self.heartbeat("navigating", detail=action)

        with self._action_lock:
            state = self._load_traffic()
            count = int(state.get("actions_count") or 0)
            due = count > 0 and count % self._batch_pause_pages_min == 0
            existing_rest = self._parse_iso(state.get("rest_until"))
            if due and int(state.get("rest_for") or 0) == count and existing_rest is not None:
                # Interrupted during this rest: keep the persisted deadline.
                # Re-drawing it made every restart wait a full rest again.
                pass
            elif due and int(state.get("rested_after") or 0) < count:
                long_rest = self.mode == "supervised" and count % 100 == 0
                low, high = ((600.0, 720.0) if long_rest else
                             (self._batch_pause_seconds_min, self._batch_pause_seconds_max))
                duration = random.uniform(low, high)
                new_deadline = self._now() + dt.timedelta(seconds=duration)
                old_deadline = self._parse_iso(state.get("rest_until"))
                state["rest_until"] = max(new_deadline, old_deadline).isoformat() if old_deadline else new_deadline.isoformat()
                state["rest_for"] = count
                self._write_traffic(state)
            now = self._now()
            deadlines = [
                min(parsed, now + dt.timedelta(seconds=MAX_PERSISTED_WAIT_SECONDS[key]))
                for key in ("rest_until", "next_allowed_at", "captcha_cooldown_until")
                for parsed in (self._parse_iso(state.get(key)),)
                if parsed is not None
            ]
            deadline = max(deadlines, default=None)
            if deadline and self._now() < deadline:
                if stop_event is None:
                    self._wait_until(deadline, "采集节流等待")
                else:
                    self._wait_until(deadline, "采集节流等待", stop_event)
            if stop_event is not None and stop_event.is_set():
                raise SafetyWaitCancelled("采集操作已取消。")
            if int(state.get("rest_for") or 0) == count:
                state["rested_after"] = count
                state.pop("rest_until", None)
                state.pop("rest_for", None)
            state["actions_count"] = count + 1
            spacing = random.uniform(20.0, 30.0) if self.mode == "supervised" else random.uniform(45.0, 75.0)
            state["next_allowed_at"] = (self._now() + dt.timedelta(seconds=spacing)).isoformat()
            state["last_mode"] = self.mode
            self._write_traffic(state)

    def trip(self, signal: RiskSignal, *, page_url: str = "") -> None:
        now = self._now()
        previous = self._load_pause()
        traffic = self._load_traffic()
        rate = signal.reason in {"http_429", "rate_limited"}
        old_rate_at = self._parse_iso(traffic.get("rate_detected_at"))
        repeat = bool(rate and old_rate_at and (now - old_rate_at).total_seconds() < 86400)
        cooldown = max(int(signal.cooldown_seconds), 0)
        if rate and not repeat:
            cooldown = max(1800, int(getattr(signal, "retry_after_seconds", 0) or 0))
            traffic["rate_detected_at"] = now.isoformat()
            self._write_traffic(traffic)
        if signal.reason == "captcha_or_robot_check" and self.mode == "unattended":
            cooldown = 0
        not_before = now + dt.timedelta(seconds=cooldown)
        previous_deadline = self._parse_iso(previous.get("not_before")) if previous else None
        if previous_deadline is not None:
            not_before = max(not_before, previous_deadline)
        self._review_mode = False
        self._probe_sent = False
        self._write_pause(
            {
                "schema_version": SAFETY_SCHEMA_VERSION,
                "active": True,
                "platform": signal.platform,
                "reason": signal.reason,
                "message": signal.message,
                "detected_at": now.isoformat(),
                "not_before": not_before.isoformat(),
                "page_url": _redacted_page_url(page_url),
                "work_key": self.work_key,
                "job": self.job_label,
                "kind": "rate_probe" if rate and not repeat else "manual_review",
                "rate_detected_at": (old_rate_at or now).isoformat() if rate else "",
                "review_required": not (rate and not repeat),
            }
        )
        raise SafetyPausedError(
            f"已触发 {signal.platform} 风险暂停：{signal.message} 已保存断点，"
            f"最早 {not_before.isoformat(sep=' ')} 后复核。",
            kind="risk_pause",
            resume_at=not_before.isoformat(sep=" "),
        )

    def captcha_cleared(self, *, page_url: str = "") -> None:
        """Wait once after a human clears a challenge; a second challenge hard-pauses."""
        state = self._load_traffic()
        now = self._now()
        previous = self._parse_iso(state.get("captcha_detected_at"))
        if previous and (now - previous).total_seconds() < 86400:
            self.trip(RiskSignal("amazon", "captcha_repeated", "再次出现人工验证。"), page_url=page_url)
        state["captcha_detected_at"] = now.isoformat()
        state["captcha_cooldown_until"] = (now + dt.timedelta(minutes=10)).isoformat()
        self._write_traffic(state)
        self._wait_until(now + dt.timedelta(minutes=10), "人工验证后冷却")

    def complete_review_success(self) -> None:
        if not self._review_mode:
            return
        pause = self._load_pause()
        if pause is not None and bool(pause.get("review_attempt_pending")):
            try:
                self.pause_path.unlink()
            except FileNotFoundError:
                pass
        self._review_mode = False
        self._probe_sent = False
        self._probe_verified = False

    def fail_review(self) -> None:
        """Close an unfinished review at process exit without escalating it.

        A new risk signal during the probe already rewrote the pause in
        ``trip``.  Reaching here otherwise means the probe was never sent
        (config error, lock, other item) or ended without a risk verdict, so the
        pause stays exactly as it was and one later run may probe again.  The
        old behaviour escalated to a 24 h manual review without any request.
        """
        if not self._review_mode:
            return
        pause = self._load_pause()
        if pause is not None:
            pause["review_attempt_pending"] = False
            self._write_pause(pause)
        self._review_mode = False
        self._probe_sent = False

    @staticmethod
    def _pause_message(pause: Dict[str, Any], *, action: str = "") -> str:
        prefix = f"执行 {action} 前" if action else ""
        return (
            f"{prefix}检测到未解除的风险暂停：{pause.get('platform') or 'unknown'}/"
            f"{pause.get('reason') or 'unknown'}。{pause.get('message') or ''} "
            f"最早 {str(pause.get('not_before') or '').replace('T', ' ')} 后，请用户确认浏览器页面正常，"
            "再加 --resume-after-review 运行（任何待处理项都可作为复核）。"
            "查看状态：./lc-amazon-data-crawl.sh safety-status"
        ).strip()

    def __enter__(self) -> "LocalSafetyController":
        self.acquire()
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.release()

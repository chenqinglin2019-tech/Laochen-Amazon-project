"""Shared Amazon/Lens page-health classification and retry orchestration.

This module deliberately has no imports from crawler modules.  Front, category,
and image crawlers can therefore use it without creating circular imports.
Callers remain responsible for taking a browser snapshot and for atomically
embedding the mapping supplied to ``write_state`` under ``amazon_page_retry``
in their job state.
"""

from __future__ import annotations

import copy
import math
import random
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from numbers import Real
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple, TypeVar
from urllib.parse import urlsplit, urlunsplit


RETRY_SCHEDULE_CONFIG_KEY = "amazon_page_unavailable_retry_schedule_seconds"
DEFAULT_RETRY_SCHEDULE_SECONDS: Tuple[Tuple[int, int], ...] = (
    (180, 300),
    (180, 300),
    (1800, 1800),
    (3600, 3600),
)
# Descriptive alias for callers that keep several retry schedules.
DEFAULT_AMAZON_PAGE_RETRY_SCHEDULE_SECONDS = DEFAULT_RETRY_SCHEDULE_SECONDS
MAX_ATTEMPTS = 5
MAX_HEARTBEAT_SECONDS = 60.0

PAGE_KINDS = frozenset(
    {"product", "search_category", "lens_upload", "lens_results"}
)


class RetryConfigurationError(ValueError):
    """Raised when the configured retry schedule is not safe and deterministic."""


class PageHealthStatus(str, Enum):
    HEALTHY = "healthy"
    VERIFIED_EMPTY = "verified_empty"
    TRANSIENT_UNAVAILABLE = "transient_unavailable"
    INTERACTIVE_VERIFICATION = "interactive_verification"
    AMAZON_SIGN_IN = "amazon_sign_in"


@dataclass(frozen=True)
class PageSnapshot:
    """Browser-independent facts collected after a page readiness timeout.

    ``expected_content_present`` and ``explicit_empty`` must be derived from
    page-kind-specific DOM checks by the caller.  Text is used only for strong
    terminal/transient signatures; a lone word such as ``sorry`` never wins
    over a positive expected-content check.
    """

    page_kind: str
    url: str = ""
    title: str = ""
    body_text: str = ""
    http_status: Optional[int] = None
    navigation_error: str = ""
    expected_content_present: bool = False
    explicit_empty: bool = False


@dataclass(frozen=True)
class PageHealthAssessment:
    status: PageHealthStatus
    reason: str
    page_kind: str

    @property
    def retryable(self) -> bool:
        return self.status is PageHealthStatus.TRANSIENT_UNAVAILABLE


RetrySchedule = Tuple[Tuple[float, float], ...]


def _schedule_number(value: object, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RetryConfigurationError(f"{location} 必须是有限非负数，且不能是布尔值。")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise RetryConfigurationError(f"{location} 必须是有限非负数。")
    return number


def parse_retry_schedule(value: object) -> RetrySchedule:
    """Strictly validate the four waits that separate five attempts."""

    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise RetryConfigurationError(
            f"{RETRY_SCHEDULE_CONFIG_KEY} 必须是包含 4 项的数组。"
        )
    if len(value) != 4:
        raise RetryConfigurationError(
            f"{RETRY_SCHEDULE_CONFIG_KEY} 必须固定包含 4 项，对应 5 次尝试之间的等待。"
        )
    result = []
    for index, pair in enumerate(value, start=1):
        if isinstance(pair, (str, bytes)) or not isinstance(pair, (list, tuple)):
            raise RetryConfigurationError(
                f"{RETRY_SCHEDULE_CONFIG_KEY}[{index - 1}] 必须是 [min, max]。"
            )
        if len(pair) != 2:
            raise RetryConfigurationError(
                f"{RETRY_SCHEDULE_CONFIG_KEY}[{index - 1}] 必须恰好包含 2 个数。"
            )
        minimum = _schedule_number(
            pair[0], f"{RETRY_SCHEDULE_CONFIG_KEY}[{index - 1}][0]"
        )
        maximum = _schedule_number(
            pair[1], f"{RETRY_SCHEDULE_CONFIG_KEY}[{index - 1}][1]"
        )
        if minimum > maximum:
            raise RetryConfigurationError(
                f"{RETRY_SCHEDULE_CONFIG_KEY}[{index - 1}] 的 min 不能大于 max。"
            )
        result.append((minimum, maximum))
    return tuple(result)


def retry_schedule_from_config(config: Mapping[str, Any]) -> RetrySchedule:
    """Return the default only when the key is absent; explicit null is invalid."""

    if not isinstance(config, Mapping):
        raise RetryConfigurationError("爬虫配置必须是 JSON 对象。")
    if RETRY_SCHEDULE_CONFIG_KEY not in config:
        return parse_retry_schedule(DEFAULT_RETRY_SCHEDULE_SECONDS)
    return parse_retry_schedule(config[RETRY_SCHEDULE_CONFIG_KEY])


def _normalized_text(*values: str) -> str:
    return " ".join(" ".join(str(value or "").lower().split()) for value in values)


def _is_amazon_host(host: str) -> bool:
    normalized = host.lower().strip(".")
    return normalized == "amazon.com" or ".amazon." in f".{normalized}."


def _amazon_sign_in(snapshot: PageSnapshot, haystack: str) -> bool:
    parsed = urlsplit(str(snapshot.url or ""))
    path = parsed.path.lower().rstrip("/")
    amazon_host = _is_amazon_host(parsed.hostname or "")
    if amazon_host and (
        path.startswith("/ap/signin")
        or path.startswith("/gp/sign-in")
        or path == "/signin"
    ):
        return True
    # Text alone is deliberately insufficient.  Require an Amazon page and a
    # form-like pair of markers so product prose mentioning sign-in stays safe.
    form_markers = (
        "email or mobile phone number",
        "enter your email or mobile phone number",
        "请输入电子邮件地址或手机号码",
        "e-mail-adresse oder mobiltelefonnummer",
    )
    return bool(
        amazon_host
        and "sign in" in haystack
        and any(marker in haystack for marker in form_markers)
    )


def _interactive_verification(snapshot: PageSnapshot, haystack: str) -> bool:
    path = urlsplit(str(snapshot.url or "")).path.lower()
    if "validatecaptcha" in path:
        return True
    strong_markers = (
        "robot check",
        "enter the characters you see",
        "type the characters you see in this image",
        "complete the captcha",
        "请输入您在图片中看到的字符",
        "机器人检测",
        "我不是机器人",
    )
    if any(marker in haystack for marker in strong_markers):
        return True
    return "captcha" in haystack and any(
        marker in haystack
        for marker in ("verify", "verification", "characters", "验证码")
    )


_TRANSIENT_TEXT_SIGNATURES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "amazon_dog_error",
        (
            "sorry, something went wrong on our end",
            "sorry, we couldn't find that page",
            "sorry, we couldn’t find that page",
            "meet the dogs of amazon",
            "dogs of amazon",
            "the web address you entered is not a functioning page",
        ),
    ),
    (
        "rate_limited",
        (
            "unusual traffic",
            "request has been blocked",
            "request was blocked",
            "too many requests",
            "异常流量",
            "请求被阻止",
        ),
    ),
    (
        "access_denied",
        (
            "access denied",
            "you don't have permission to access",
            "you do not have permission to access",
            "拒绝访问",
            "无权访问",
        ),
    ),
)


def classify_page_snapshot(snapshot: PageSnapshot) -> PageHealthAssessment:
    """Purely classify one Amazon/Lens snapshot without touching a browser."""

    if not isinstance(snapshot, PageSnapshot):
        raise TypeError("snapshot 必须是 PageSnapshot。")
    if snapshot.page_kind not in PAGE_KINDS:
        raise ValueError(
            f"page_kind 必须是 {', '.join(sorted(PAGE_KINDS))} 之一。"
        )
    if type(snapshot.expected_content_present) is not bool:
        raise TypeError("expected_content_present 必须是布尔值。")
    if type(snapshot.explicit_empty) is not bool:
        raise TypeError("explicit_empty 必须是布尔值。")
    if snapshot.expected_content_present and snapshot.explicit_empty:
        raise ValueError("expected_content_present 与 explicit_empty 不能同时为 true。")
    status_code = snapshot.http_status
    if status_code is not None:
        if isinstance(status_code, bool) or not isinstance(status_code, int):
            raise TypeError("http_status 必须是整数或 null。")
        if not 100 <= status_code <= 599:
            raise ValueError("http_status 必须介于 100 和 599。")

    haystack = _normalized_text(snapshot.title, snapshot.body_text)
    if _amazon_sign_in(snapshot, haystack):
        return PageHealthAssessment(
            PageHealthStatus.AMAZON_SIGN_IN, "amazon_sign_in", snapshot.page_kind
        )
    if _interactive_verification(snapshot, haystack):
        return PageHealthAssessment(
            PageHealthStatus.INTERACTIVE_VERIFICATION,
            "captcha_or_robot_check",
            snapshot.page_kind,
        )
    if str(snapshot.navigation_error or "").strip():
        return PageHealthAssessment(
            PageHealthStatus.TRANSIENT_UNAVAILABLE,
            "navigation_error",
            snapshot.page_kind,
        )
    if status_code == 429:
        return PageHealthAssessment(
            PageHealthStatus.TRANSIENT_UNAVAILABLE,
            "http_429",
            snapshot.page_kind,
        )
    if status_code is not None and 500 <= status_code <= 599:
        return PageHealthAssessment(
            PageHealthStatus.TRANSIENT_UNAVAILABLE,
            f"http_{status_code}",
            snapshot.page_kind,
        )

    # DOM evidence is authoritative over incidental prose.  In particular, a
    # healthy listing whose description/review says "sorry" remains healthy.
    if snapshot.expected_content_present:
        return PageHealthAssessment(
            PageHealthStatus.HEALTHY, "expected_content_present", snapshot.page_kind
        )

    for reason, markers in _TRANSIENT_TEXT_SIGNATURES:
        if any(marker in haystack for marker in markers):
            return PageHealthAssessment(
                PageHealthStatus.TRANSIENT_UNAVAILABLE, reason, snapshot.page_kind
            )

    if snapshot.explicit_empty:
        return PageHealthAssessment(
            PageHealthStatus.VERIFIED_EMPTY, "explicit_empty", snapshot.page_kind
        )
    if not str(snapshot.title or "").strip() and not str(snapshot.body_text or "").strip():
        reason = "blank_page"
    else:
        reason = "expected_content_missing"
    return PageHealthAssessment(
        PageHealthStatus.TRANSIENT_UNAVAILABLE, reason, snapshot.page_kind
    )


def redact_error(value: object, limit: int = 600) -> str:
    """Make an exception safe for job state/logs without exposing credentials."""

    text = " ".join(str(value or "").split())
    substitutions = (
        (
            r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+",
            r"\1[REDACTED]",
        ),
        (
            r"(?i)(bearer\s+)[a-z0-9._~+/=-]+",
            r"\1[REDACTED]",
        ),
        (
            r"(?i)([\"']?(?:api[_-]?key|token|secret|password|cookie)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;}]+",
            r"\1[REDACTED]",
        ),
    )
    for pattern, replacement in substitutions:
        text = re.sub(pattern, replacement, text)
    safe_limit = max(int(limit), 0)
    if len(text) > safe_limit:
        text = text[:safe_limit].rstrip() + "…"
    return text


def sanitize_state_url(value: str) -> str:
    """Remove URL credentials and fragments while retaining the page address."""

    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return raw.split("#", 1)[0]
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))


class TransientAmazonPageUnavailable(RuntimeError):
    """Signal to the controller that the current attempt may be retried."""

    def __init__(self, message: str, *, reason: str = "", url: str = "") -> None:
        super().__init__(message)
        self.reason = str(reason or "transient_unavailable")
        self.url = str(url or "")

    @classmethod
    def from_assessment(
        cls, assessment: PageHealthAssessment, *, url: str = ""
    ) -> "TransientAmazonPageUnavailable":
        if not assessment.retryable:
            raise ValueError("只有 transient_unavailable 页面可以进入自动重试。")
        return cls(assessment.reason, reason=assessment.reason, url=url)


class AmazonPageRetryExhausted(RuntimeError):
    """Raised after the fifth transient failure; the job must pause for rerun."""

    failure_code = "amazon_page_unavailable_retry_exhausted"

    def __init__(self, state: Mapping[str, Any], last_error: BaseException) -> None:
        self.state = copy.deepcopy(dict(state))
        self.last_error = last_error
        super().__init__(
            f"{self.failure_code}: 五次页面尝试均失败，已保存断点，需用户手动继续。"
        )


@dataclass(frozen=True)
class RetryAttempt:
    cycle: int
    attempt_number: int
    max_attempts: int
    domain: str
    work_key: str
    stage: str
    url: str


def _load_none() -> Optional[Mapping[str, Any]]:
    return None


def _mapping_noop(_state: Mapping[str, Any]) -> None:
    return None


def _noop() -> None:
    return None


def _cooldown_noop(_domain: str, _deadline: float) -> None:
    return None


@dataclass(frozen=True)
class RetryCallbacks:
    """Side effects supplied by a crawler's own state/browser infrastructure."""

    load_state: Callable[[], Optional[Mapping[str, Any]]] = _load_none
    write_state: Callable[[Mapping[str, Any]], None] = _mapping_noop
    clear_state: Callable[[], None] = _noop
    cleanup: Callable[[], None] = _noop
    begin_domain_cooldown: Callable[[str, float], None] = _cooldown_noop
    end_domain_cooldown: Callable[[str, float], None] = _cooldown_noop
    heartbeat: Callable[[Mapping[str, Any]], None] = _mapping_noop


T = TypeVar("T")


class AmazonPageRetryController:
    """Serialize and persist a five-attempt recovery cycle for one work stage."""

    def __init__(
        self,
        *,
        domain: str,
        work_key: str,
        stage: str,
        url: str,
        schedule: Sequence[Sequence[Real]] = DEFAULT_RETRY_SCHEDULE_SECONDS,
        callbacks: Optional[RetryCallbacks] = None,
        clock: Callable[[], float] = time.time,
        rng: Optional[Any] = None,
        waiter: Callable[[float], Any] = time.sleep,
        heartbeat_seconds: float = MAX_HEARTBEAT_SECONDS,
    ) -> None:
        self.domain = str(domain or "").strip().lower()
        self.work_key = str(work_key or "").strip()
        self.stage = str(stage or "").strip()
        self.url = sanitize_state_url(url)
        if not self.domain:
            raise ValueError("domain 不能为空。")
        if not self.work_key:
            raise ValueError("work_key 不能为空。")
        if not self.stage:
            raise ValueError("stage 不能为空。")
        self.schedule = parse_retry_schedule(schedule)
        self.callbacks = callbacks or RetryCallbacks()
        if not callable(clock) or not callable(waiter):
            raise TypeError("clock 和 waiter 必须可调用。")
        self.clock = clock
        self.rng = rng if rng is not None else random.SystemRandom()
        self.waiter = waiter
        if isinstance(heartbeat_seconds, bool) or not isinstance(heartbeat_seconds, Real):
            raise ValueError("heartbeat_seconds 必须是大于 0 且不超过 60 的有限数。")
        self.heartbeat_seconds = float(heartbeat_seconds)
        if (
            not math.isfinite(self.heartbeat_seconds)
            or self.heartbeat_seconds <= 0
            or self.heartbeat_seconds > MAX_HEARTBEAT_SECONDS
        ):
            raise ValueError("heartbeat_seconds 必须是大于 0 且不超过 60 的有限数。")
        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._current_state: Optional[Dict[str, Any]] = None

    def current_state(self) -> Optional[Dict[str, Any]]:
        with self._state_lock:
            return copy.deepcopy(self._current_state)

    def _uniform(self, minimum: float, maximum: float) -> float:
        method = getattr(self.rng, "uniform", None)
        if callable(method):
            selected = method(minimum, maximum)
        elif callable(self.rng):
            selected = self.rng(minimum, maximum)
        else:
            raise TypeError("rng 必须可调用，或提供 uniform(min, max)。")
        if isinstance(selected, bool) or not isinstance(selected, Real):
            raise TypeError("rng.uniform 必须返回数值。")
        result = float(selected)
        if not math.isfinite(result) or result < minimum or result > maximum:
            raise ValueError("rng.uniform 返回值必须位于请求区间内。")
        return result

    def _matching_saved_state(self) -> Optional[Dict[str, Any]]:
        loaded = self.callbacks.load_state()
        if loaded is None:
            return None
        if not isinstance(loaded, Mapping):
            return None
        if isinstance(loaded.get("amazon_page_retry"), Mapping):
            loaded = loaded["amazon_page_retry"]  # type: ignore[assignment]
        state = dict(loaded)
        if (
            str(state.get("domain") or "").lower() != self.domain
            or str(state.get("work_key") or "") != self.work_key
            or str(state.get("stage") or "") != self.stage
        ):
            return None
        return state

    def _persist(self, state: Mapping[str, Any], *, heartbeat: bool = False) -> None:
        snapshot = copy.deepcopy(dict(state))
        snapshot["updated_at"] = float(self.clock())
        with self._state_lock:
            self._current_state = copy.deepcopy(snapshot)
        # This callback is where the owning crawler performs its atomic state
        # flush.  It is always invoked before any wait begins.
        self.callbacks.write_state(copy.deepcopy(snapshot))
        if heartbeat:
            self.callbacks.heartbeat(copy.deepcopy(snapshot))

    def _clear(self) -> None:
        self.callbacks.clear_state()
        with self._state_lock:
            self._current_state = None

    def _identity_state(self, *, status: str, cycle: int) -> Dict[str, Any]:
        return {
            "status": status,
            "domain": self.domain,
            "work_key": self.work_key,
            "stage": self.stage,
            "cycle": int(cycle),
            "url": self.url,
        }

    @staticmethod
    def _safe_positive_int(value: object, default: int) -> int:
        if isinstance(value, bool):
            return default
        try:
            result = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return default
        return result if result > 0 else default

    def _resume_position(self) -> Tuple[int, int, Optional[Dict[str, Any]]]:
        saved = self._matching_saved_state()
        if not saved:
            return 1, 1, None
        cycle = self._safe_positive_int(saved.get("cycle"), 1)
        status = str(saved.get("status") or "")
        if status == "manual_resume_required":
            # Re-running the same command is the manual resume action.  It
            # starts a fresh five-attempt cycle only for this exact work/stage.
            self._clear()
            return cycle + 1, 1, None
        if status not in {"waiting", "attempting"}:
            return 1, 1, None
        next_attempt = self._safe_positive_int(saved.get("next_attempt"), 1)
        if next_attempt > MAX_ATTEMPTS:
            next_attempt = MAX_ATTEMPTS
        return cycle, next_attempt, saved

    def _attempt_state(
        self, cycle: int, attempt_number: int, attempts_completed: int
    ) -> Dict[str, Any]:
        state = self._identity_state(status="attempting", cycle=cycle)
        state.update(
            {
                "attempts_completed": int(attempts_completed),
                "next_attempt": int(attempt_number),
                "selected_wait_seconds": None,
                "next_retry_at": None,
                "remaining_wait_seconds": None,
                "error": "",
            }
        )
        return state

    def _waiting_state(
        self,
        *,
        cycle: int,
        attempts_completed: int,
        next_attempt: int,
        wait_seconds: float,
        next_retry_at: float,
        error: BaseException,
    ) -> Dict[str, Any]:
        state = self._identity_state(status="waiting", cycle=cycle)
        state.update(
            {
                "attempts_completed": int(attempts_completed),
                "next_attempt": int(next_attempt),
                "selected_wait_seconds": float(wait_seconds),
                "next_retry_at": float(next_retry_at),
                "remaining_wait_seconds": max(
                    float(next_retry_at) - float(self.clock()), 0.0
                ),
                "error": redact_error(error),
            }
        )
        return state

    def _manual_state(
        self, *, cycle: int, error: BaseException
    ) -> Dict[str, Any]:
        state = self._identity_state(status="manual_resume_required", cycle=cycle)
        state.update(
            {
                "attempts_completed": MAX_ATTEMPTS,
                "next_attempt": 1,
                "selected_wait_seconds": None,
                "next_retry_at": None,
                "remaining_wait_seconds": None,
                "error": redact_error(error),
                "failure_code": AmazonPageRetryExhausted.failure_code,
            }
        )
        return state

    def _wait_until(self, state: Dict[str, Any], deadline: float) -> None:
        self.callbacks.begin_domain_cooldown(self.domain, deadline)
        try:
            while True:
                remaining = max(float(deadline) - float(self.clock()), 0.0)
                if remaining <= 0:
                    return
                self.waiter(min(remaining, self.heartbeat_seconds))
                remaining = max(float(deadline) - float(self.clock()), 0.0)
                state["remaining_wait_seconds"] = remaining
                state["next_retry_at"] = float(deadline)
                self._persist(state, heartbeat=True)
        finally:
            self.callbacks.end_domain_cooldown(self.domain, deadline)

    def run(
        self,
        operation: Callable[[RetryAttempt], T],
        *,
        initial_failure: Optional[TransientAmazonPageUnavailable] = None,
    ) -> T:
        """Run ``operation`` until success or the fifth transient failure.

        Only :class:`TransientAmazonPageUnavailable` is retried.  Any other
        normal exception is cleaned up, clears this retry record, and is
        propagated.  ``KeyboardInterrupt``/``SystemExit`` are cleaned up but
        leave the attempt record intact so a rerun can safely retry it.

        Concurrent crawlers may execute attempt 1 before taking a serialized
        recovery lock.  Passing that failure as ``initial_failure`` records it
        as the first completed attempt and starts with the first configured
        wait, rather than repeating attempt 1 and accidentally performing six
        attempts.  A matching saved checkpoint always takes precedence.
        """

        if not callable(operation):
            raise TypeError("operation 必须可调用。")
        with self._run_lock:
            cycle, attempt_number, saved = self._resume_position()
            if initial_failure is not None and not isinstance(
                initial_failure, TransientAmazonPageUnavailable
            ):
                raise TypeError(
                    "initial_failure 必须是 TransientAmazonPageUnavailable 或 null。"
                )
            if saved is not None and str(saved.get("status") or "") == "waiting":
                raw_deadline = saved.get("next_retry_at")
                if isinstance(raw_deadline, bool) or not isinstance(raw_deadline, Real):
                    # A corrupt waiting record cannot produce a trustworthy
                    # deadline.  Retry the same attempt immediately.
                    saved = None
                else:
                    deadline = float(raw_deadline)
                    if math.isfinite(deadline):
                        waiting_state = copy.deepcopy(saved)
                        waiting_state["next_retry_at"] = deadline
                        waiting_state["remaining_wait_seconds"] = max(
                            deadline - float(self.clock()), 0.0
                        )
                        self._persist(waiting_state)
                        self._wait_until(waiting_state, deadline)

            if saved is None and initial_failure is not None:
                self.callbacks.cleanup()
                minimum, maximum = self.schedule[0]
                wait_seconds = self._uniform(minimum, maximum)
                deadline = float(self.clock()) + wait_seconds
                waiting_state = self._waiting_state(
                    cycle=cycle,
                    attempts_completed=1,
                    next_attempt=2,
                    wait_seconds=wait_seconds,
                    next_retry_at=deadline,
                    error=initial_failure,
                )
                self._persist(waiting_state)
                self._wait_until(waiting_state, deadline)
                attempt_number = 2

            while attempt_number <= MAX_ATTEMPTS:
                attempts_completed = attempt_number - 1
                self._persist(
                    self._attempt_state(cycle, attempt_number, attempts_completed)
                )
                attempt = RetryAttempt(
                    cycle=cycle,
                    attempt_number=attempt_number,
                    max_attempts=MAX_ATTEMPTS,
                    domain=self.domain,
                    work_key=self.work_key,
                    stage=self.stage,
                    url=self.url,
                )
                try:
                    result = operation(attempt)
                except TransientAmazonPageUnavailable as exc:
                    self.callbacks.cleanup()
                    if attempt_number == MAX_ATTEMPTS:
                        manual_state = self._manual_state(cycle=cycle, error=exc)
                        self._persist(manual_state)
                        raise AmazonPageRetryExhausted(manual_state, exc) from exc
                    minimum, maximum = self.schedule[attempt_number - 1]
                    wait_seconds = self._uniform(minimum, maximum)
                    deadline = float(self.clock()) + wait_seconds
                    waiting_state = self._waiting_state(
                        cycle=cycle,
                        attempts_completed=attempt_number,
                        next_attempt=attempt_number + 1,
                        wait_seconds=wait_seconds,
                        next_retry_at=deadline,
                        error=exc,
                    )
                    # Persist the chosen random value and absolute deadline
                    # before sleeping.  Restart never samples this wait again.
                    self._persist(waiting_state)
                    self._wait_until(waiting_state, deadline)
                    attempt_number += 1
                    continue
                except BaseException as exc:
                    self.callbacks.cleanup()
                    if isinstance(exc, Exception):
                        self._clear()
                    raise
                self.callbacks.cleanup()
                self._clear()
                return result

            raise AssertionError("不可达的 Amazon 页面重试状态。")


class DomainCooldownRegistry:
    """Thread-safe per-domain cooldown shared by concurrent navigation workers."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        waiter: Callable[[float], Any] = time.sleep,
        heartbeat_seconds: float = MAX_HEARTBEAT_SECONDS,
    ) -> None:
        self.clock = clock
        self.waiter = waiter
        self.heartbeat_seconds = float(heartbeat_seconds)
        if (
            not callable(clock)
            or not callable(waiter)
            or not math.isfinite(self.heartbeat_seconds)
            or self.heartbeat_seconds <= 0
            or self.heartbeat_seconds > MAX_HEARTBEAT_SECONDS
        ):
            raise ValueError("冷却心跳必须是大于 0 且不超过 60 秒的有限数。")
        self._lock = threading.Lock()
        self._deadlines: Dict[str, float] = {}

    @staticmethod
    def _domain(value: str) -> str:
        domain = str(value or "").strip().lower()
        if not domain:
            raise ValueError("domain 不能为空。")
        return domain

    def extend(self, domain: str, deadline: float) -> None:
        key = self._domain(domain)
        value = float(deadline)
        if not math.isfinite(value):
            raise ValueError("cooldown deadline 必须是有限时间戳。")
        with self._lock:
            self._deadlines[key] = max(value, self._deadlines.get(key, value))

    def release(self, domain: str, deadline: float) -> None:
        """Release only this wait; never erase a newer concurrent deadline."""

        key = self._domain(domain)
        value = float(deadline)
        with self._lock:
            current = self._deadlines.get(key)
            if current is not None and current <= value:
                self._deadlines.pop(key, None)

    def deadline(self, domain: str) -> float:
        key = self._domain(domain)
        now = float(self.clock())
        with self._lock:
            value = self._deadlines.get(key, 0.0)
            if value <= now:
                self._deadlines.pop(key, None)
                return 0.0
            return value

    def remaining(self, domain: str) -> float:
        return max(self.deadline(domain) - float(self.clock()), 0.0)

    def wait(
        self,
        domain: str,
        on_heartbeat: Optional[Callable[[str, float], None]] = None,
    ) -> None:
        key = self._domain(domain)
        while True:
            remaining = self.remaining(key)
            if remaining <= 0:
                return
            self.waiter(min(remaining, self.heartbeat_seconds))
            if on_heartbeat is not None:
                on_heartbeat(key, self.remaining(key))


__all__ = [
    "AmazonPageRetryController",
    "AmazonPageRetryExhausted",
    "DEFAULT_AMAZON_PAGE_RETRY_SCHEDULE_SECONDS",
    "DEFAULT_RETRY_SCHEDULE_SECONDS",
    "DomainCooldownRegistry",
    "MAX_ATTEMPTS",
    "MAX_HEARTBEAT_SECONDS",
    "PAGE_KINDS",
    "PageHealthAssessment",
    "PageHealthStatus",
    "PageSnapshot",
    "RETRY_SCHEDULE_CONFIG_KEY",
    "RetryAttempt",
    "RetryCallbacks",
    "RetryConfigurationError",
    "TransientAmazonPageUnavailable",
    "classify_page_snapshot",
    "parse_retry_schedule",
    "redact_error",
    "retry_schedule_from_config",
    "sanitize_state_url",
]

#!/usr/bin/env python3
"""Browser backends shared by the Amazon crawler modes."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple

from selenium.common.exceptions import (
    JavascriptException,
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By


CRAWLER_WINDOW_NAME_PREFIX = "__lc_amazon_data_crawl_owned__:"
_CRAWLER_WINDOW_MARKER_VERSION = "v1"
_ACTIVE_CDP_OWNER_IDS: Set[str] = set()


def cdp_endpoint(debugger_address: str) -> str:
    address = (debugger_address or "").strip().rstrip("/")
    if not address:
        raise WebDriverException("debugger_address 不能为空。")
    if address.startswith(("http://", "https://", "ws://", "wss://")):
        return address
    return f"http://{address}"


def expected_profile_path(user_data_dir: Path, profile_directory: str) -> Path:
    return (user_data_dir / (profile_directory or "Default")).expanduser().resolve()


def profile_paths_match(
    actual_profile_path: str,
    user_data_dir: Path,
    profile_directory: str,
) -> bool:
    if not (actual_profile_path or "").strip():
        return False
    actual = Path(actual_profile_path).expanduser().resolve()
    return actual == expected_profile_path(user_data_dir, profile_directory)


class CdpElement:
    def __init__(self, locator: Any) -> None:
        self._locator = locator

    @property
    def text(self) -> str:
        try:
            return str(self._locator.inner_text() or "")
        except Exception as exc:  # pragma: no cover - translated at backend boundary
            raise WebDriverException(str(exc)) from exc

    def send_keys(self, value: str) -> None:
        try:
            if str(self._locator.get_attribute("type") or "").lower() == "file":
                self._locator.set_input_files(value)
            else:
                self._locator.fill(value, timeout=1000)
        except Exception as exc:  # pragma: no cover - translated at backend boundary
            raise WebDriverException(str(exc)) from exc

    def clear(self) -> None:
        try:
            self._locator.fill("", timeout=1000)
        except Exception as exc:  # pragma: no cover - translated at backend boundary
            raise WebDriverException(str(exc)) from exc

    def type_text(self, value: str) -> None:
        try:
            self._locator.press_sequentially(value, delay=50)
        except Exception as exc:  # pragma: no cover - translated at backend boundary
            raise WebDriverException(str(exc)) from exc

    def click(self) -> None:
        try:
            self._locator.click(timeout=1000)
        except Exception as exc:  # pragma: no cover - translated at backend boundary
            raise WebDriverException(str(exc)) from exc


class CdpSwitchTo:
    def __init__(self, driver: "CdpWebDriver") -> None:
        self._driver = driver

    def window(self, handle: str) -> None:
        pages = self._driver._page_map()
        page = pages.get(handle)
        if page is None:
            raise WebDriverException(f"没有找到 CDP 标签页：{handle}")
        self._driver._page = page
        try:
            page.bring_to_front()
        except Exception as exc:
            raise WebDriverException(str(exc)) from exc


class CdpWebDriver:
    """Small Selenium-compatible facade backed by Playwright CDP.

    Existing crawler extraction functions intentionally keep their current
    WebDriver-shaped surface. This facade translates that narrow surface to a
    Playwright page and never closes a user-owned attached browser.
    """

    is_cdp_driver = True
    owned_page_close_interval_seconds = 0.5
    owned_page_close_stabilize_seconds = 2.0

    def __init__(
        self,
        debugger_address: str,
        page_timeout: int,
        expected_user_data_dir: Path,
        profile_directory: str,
        owns_browser: bool = False,
        owned_process: Optional[Any] = None,
    ) -> None:
        try:
            from playwright.sync_api import (
                Error as PlaywrightError,
                TimeoutError as PlaywrightTimeoutError,
                sync_playwright,
            )
        except ImportError as exc:
            raise WebDriverException(
                "CDP 后端需要 Playwright。请先执行 ./lc-amazon-data-crawl.sh install。"
            ) from exc

        self._playwright_error = PlaywrightError
        self._playwright_timeout_error = PlaywrightTimeoutError
        self._page_timeout = max(int(page_timeout), 1)
        self._owns_browser = bool(owns_browser)
        self._owned_process = owned_process
        self._closed = False
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._browser_cdp_session = None
        self._owned_pages: Dict[int, Any] = {}
        self._owned_page_roles: Dict[int, str] = {}
        self._owned_page_listener_ids: Set[int] = set()
        self._worker_page = None
        self._owner_id = uuid.uuid4().hex
        self._owner_pid = os.getpid()
        self._context_page_listener_installed = False
        self._action_page_captures: Dict[str, Dict[int, Any]] = {}
        self._ownership_close_failures: List[str] = []
        self._last_http_status: Optional[int] = None
        self._last_navigation_error = ""
        self._sleep_fn: Callable[[float], None] = time.sleep
        self._monotonic_fn: Callable[[], float] = time.monotonic
        self.switch_to = CdpSwitchTo(self)

        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(
                cdp_endpoint(debugger_address),
                timeout=self._page_timeout * 1000,
                no_defaults=True,
            )
            if not self._browser.contexts:
                raise WebDriverException("CDP 浏览器没有可用的默认上下文。")
            self._browser_cdp_session = self._browser.new_browser_cdp_session()
            self._context = self._browser.contexts[0]
            self._verify_profile(expected_user_data_dir, profile_directory)
            _ACTIVE_CDP_OWNER_IDS.add(self._owner_id)
            self._install_context_page_listener()
            self._cleanup_stale_crawler_pages()
            self.restore_worker_page()
        except WebDriverException:
            self._disconnect_only()
            raise
        except PlaywrightTimeoutError as exc:
            self._disconnect_only()
            raise TimeoutException(f"CDP 连接超时：{exc}") from exc
        except PlaywrightError as exc:
            self._disconnect_only()
            raise WebDriverException(f"CDP 连接失败：{exc}") from exc

    def _verify_profile(self, user_data_dir: Path, profile_directory: str) -> None:
        expected = expected_profile_path(user_data_dir, profile_directory)
        probe = None
        try:
            probe = self._context.new_page()
            probe.goto("chrome://version/", wait_until="domcontentloaded", timeout=self._page_timeout * 1000)
            profile_text = str(probe.locator("#profile_path").text_content(timeout=5000) or "").strip()
            if not profile_text:
                raise WebDriverException("无法从 chrome://version 确认当前 Chrome Profile。")
            actual = Path(profile_text).expanduser().resolve()
            if not profile_paths_match(profile_text, user_data_dir, profile_directory):
                raise WebDriverException(
                    "CDP 连接的 Chrome Profile 与配置不一致。"
                    f"期望：{expected}；实际：{actual}。"
                )
        except WebDriverException:
            raise
        except Exception as exc:
            raise WebDriverException(f"Chrome Profile 校验失败：{exc}") from exc
        finally:
            if probe is not None:
                try:
                    probe.close()
                except Exception:
                    pass

    def _ensure_ownership_state(self) -> None:
        """Initialize ownership fields for normal and lightweight test instances."""
        if not hasattr(self, "_owned_pages"):
            self._owned_pages = {}
        if not hasattr(self, "_owned_page_roles"):
            self._owned_page_roles = {}
        if not hasattr(self, "_owned_page_listener_ids"):
            self._owned_page_listener_ids = set()
        if not hasattr(self, "_worker_page"):
            self._worker_page = None
        if not hasattr(self, "_owner_id"):
            self._owner_id = uuid.uuid4().hex
        if not hasattr(self, "_owner_pid"):
            self._owner_pid = os.getpid()
        if not hasattr(self, "_context_page_listener_installed"):
            self._context_page_listener_installed = False
        if not hasattr(self, "_action_page_captures"):
            self._action_page_captures = {}
        if not hasattr(self, "_ownership_close_failures"):
            self._ownership_close_failures = []
        if not hasattr(self, "_last_http_status"):
            self._last_http_status = None
        if not hasattr(self, "_last_navigation_error"):
            self._last_navigation_error = ""
        if not hasattr(self, "_sleep_fn"):
            self._sleep_fn = time.sleep
        if not hasattr(self, "_monotonic_fn"):
            self._monotonic_fn = time.monotonic
        _ACTIVE_CDP_OWNER_IDS.add(self._owner_id)

    def _window_marker(self, role: str) -> str:
        normalized_role = "worker" if role == "worker" else "popup"
        return (
            f"{CRAWLER_WINDOW_NAME_PREFIX}{_CRAWLER_WINDOW_MARKER_VERSION}:"
            f"{self._owner_pid}:{self._owner_id}:{normalized_role}"
        )

    @staticmethod
    def _read_window_name(page: Any) -> str:
        try:
            return str(page.evaluate("() => window.name || ''") or "")
        except Exception:
            return ""

    def _mark_owned_page(self, page: Any, role: str) -> bool:
        marker = self._window_marker(role)
        try:
            if page.is_closed():
                return False
            actual = page.evaluate(
                "marker => { window.name = marker; return window.name; }",
                marker,
            )
            return str(actual or "") == marker
        except Exception:
            return False

    @staticmethod
    def _parse_window_marker(marker: str) -> Optional[Tuple[int, str, str]]:
        if not marker.startswith(CRAWLER_WINDOW_NAME_PREFIX):
            return None
        payload = marker[len(CRAWLER_WINDOW_NAME_PREFIX) :]
        parts = payload.split(":", 3)
        if len(parts) != 4 or parts[0] != _CRAWLER_WINDOW_MARKER_VERSION:
            # A malformed or future-version marker is not ownership proof.
            return None
        try:
            owner_pid = int(parts[1])
        except (TypeError, ValueError):
            return None
        if owner_pid <= 0 or not parts[2] or parts[3] not in {"worker", "popup"}:
            return None
        return owner_pid, parts[2], parts[3]

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _marker_is_stale(self, marker: str) -> bool:
        parsed = self._parse_window_marker(marker)
        if parsed is None:
            return False
        owner_pid, owner_id, _role = parsed
        if owner_id == self._owner_id:
            return False
        if owner_pid == os.getpid():
            return owner_id not in _ACTIVE_CDP_OWNER_IDS
        return not self._pid_is_running(owner_pid)

    def _marker_is_owned_by_self(self, marker: str) -> bool:
        parsed = self._parse_window_marker(marker)
        return bool(
            parsed is not None
            and parsed[0] == self._owner_pid
            and parsed[1] == self._owner_id
        )

    def _install_context_page_listener(self) -> None:
        self._ensure_ownership_state()
        if self._context is None or self._context_page_listener_installed:
            return
        try:
            self._context.on("page", self._on_context_page)
        except Exception:
            return
        self._context_page_listener_installed = True

    def _on_context_page(self, page: Any) -> None:
        """Track page events; claim immediately only with an owned opener."""
        self._ensure_ownership_state()
        for candidates in self._action_page_captures.values():
            candidates[id(page)] = page
        try:
            opener = page.opener()
        except Exception:
            opener = None
        if opener is not None and id(opener) in self._owned_pages:
            self._remember_owned_page(page, role="popup")

    def _on_owned_popup(self, popup: Any) -> None:
        self._remember_owned_page(popup, role="popup")

    def _remember_owned_page(self, page: Any, role: str = "popup") -> None:
        """Register one crawler-created page and recursively observe its popups."""
        if page is None:
            return
        self._ensure_ownership_state()
        page_id = id(page)
        normalized_role = "worker" if role == "worker" else "popup"
        self._owned_pages[page_id] = page
        self._owned_page_roles[page_id] = normalized_role
        if page_id not in self._owned_page_listener_ids:
            try:
                page.on("popup", self._on_owned_popup)
                self._owned_page_listener_ids.add(page_id)
            except Exception:
                pass
        self._mark_owned_page(page, normalized_role)

    def _discover_owned_opener_descendants(self) -> None:
        """Recover opener-linked events missed while Playwright was dispatching."""
        if self._context is None:
            return
        changed = True
        while changed:
            changed = False
            for page in list(self._context.pages):
                page_id = id(page)
                if page_id in self._owned_pages:
                    marker = self._read_window_name(page)
                    if not self._marker_is_owned_by_self(marker):
                        self._mark_owned_page(
                            page,
                            self._owned_page_roles.get(page_id, "popup"),
                        )
                    continue
                try:
                    opener = page.opener()
                except Exception:
                    continue
                if opener is not None and id(opener) in self._owned_pages:
                    self._remember_owned_page(page, role="popup")
                    changed = True

    def _configure_worker_page(self, page: Any) -> None:
        try:
            page.set_default_timeout(self._page_timeout * 1000)
            page.set_default_navigation_timeout(self._page_timeout * 1000)
        except Exception as exc:
            raise WebDriverException(f"无法配置 CDP 抓取标签页：{exc}") from exc

    def ensure_worker_page(self) -> str:
        """Return this driver's dedicated worker handle, recreating it if lost."""
        self._ensure_ownership_state()
        if self._closed or self._context is None:
            raise WebDriverException("CDP 浏览器连接已经关闭。")
        worker = self._worker_page
        if worker is None or worker.is_closed():
            try:
                worker = self._context.new_page()
            except Exception as exc:
                raise self._translate(exc) from exc
            self._worker_page = worker
            self._remember_owned_page(worker, role="worker")
            self._configure_worker_page(worker)
        else:
            self._remember_owned_page(worker, role="worker")
        handle = self._handle_for_page(worker)
        if not handle:
            raise WebDriverException("无法取得 CDP 抓取标签页句柄。")
        return handle

    def restore_worker_page(self) -> str:
        """Make the dedicated worker current without selecting an unrelated tab."""
        handle = self.ensure_worker_page()
        worker = self._worker_page
        self._page = worker
        try:
            worker.bring_to_front()
        except Exception as exc:
            raise self._translate(exc) from exc
        return handle

    def _handle_for_page(self, wanted_page: Any) -> str:
        for handle, page in self._page_map().items():
            if page is wanted_page:
                return handle
        return ""

    def _require_page(self) -> Any:
        if self._page is None or self._page.is_closed():
            self.restore_worker_page()
        return self._page

    def _translate(self, exc: Exception, javascript: bool = False) -> WebDriverException:
        if isinstance(exc, self._playwright_timeout_error):
            return TimeoutException(str(exc))
        if javascript:
            return JavascriptException(str(exc))
        return WebDriverException(str(exc))

    def _page_map(self) -> Dict[str, Any]:
        if self._context is None:
            return {}
        return {f"cdp-{id(page)}": page for page in self._context.pages if not page.is_closed()}

    @property
    def current_url(self) -> str:
        return str(self._require_page().url or "")

    @property
    def title(self) -> str:
        try:
            return str(self._require_page().title() or "")
        except Exception as exc:
            raise self._translate(exc) from exc

    @property
    def page_source(self) -> str:
        try:
            return str(self._require_page().content() or "")
        except Exception as exc:
            raise self._translate(exc) from exc

    @property
    def window_handles(self) -> List[str]:
        return list(self._page_map())

    @property
    def current_window_handle(self) -> str:
        current_page = self._require_page()
        for handle, page in self._page_map().items():
            if page is current_page:
                return handle
        raise WebDriverException("当前 CDP 标签页不存在。")

    @property
    def last_http_status(self) -> Optional[int]:
        self._ensure_ownership_state()
        return self._last_http_status

    @property
    def last_navigation_error(self) -> str:
        self._ensure_ownership_state()
        return self._last_navigation_error

    def set_page_load_timeout(self, timeout: int) -> None:
        self._page_timeout = max(int(timeout), 1)
        if self._page is not None:
            self._page.set_default_navigation_timeout(self._page_timeout * 1000)

    def get(self, url: str) -> None:
        self._ensure_ownership_state()
        self._last_http_status = None
        self._last_navigation_error = ""
        try:
            response = self._require_page().goto(
                url,
                wait_until="domcontentloaded",
                timeout=self._page_timeout * 1000,
            )
            raw_status = getattr(response, "status", None)
            self._last_http_status = (
                int(raw_status) if raw_status is not None else None
            )
        except Exception as exc:
            self._last_navigation_error = str(exc)
            raise self._translate(exc) from exc

    def refresh(self) -> None:
        try:
            self._require_page().reload(
                wait_until="domcontentloaded",
                timeout=self._page_timeout * 1000,
            )
        except Exception as exc:
            raise self._translate(exc) from exc

    def execute_script(self, script: str, *args: Any) -> Any:
        expression = (
            "(args) => { return (function() {\n"
            + script
            + "\n}).apply(null, args); }"
        )
        try:
            return self._require_page().evaluate(expression, list(args))
        except Exception as exc:
            raise self._translate(exc, javascript=True) from exc

    def find_element(self, by: str = By.ID, value: Optional[str] = None) -> CdpElement:
        selector_value = value or ""
        if by == By.CSS_SELECTOR:
            selector = selector_value
        elif by == By.TAG_NAME:
            selector = selector_value
        elif by == By.ID:
            selector = f"#{selector_value}"
        else:
            raise WebDriverException(f"CDP 后端暂不支持定位方式：{by}")
        try:
            locator = self._require_page().locator(selector).first
            if locator.count() <= 0:
                raise NoSuchElementException(f"没有找到元素：{selector}")
            return CdpElement(locator)
        except NoSuchElementException:
            raise
        except Exception as exc:
            raise self._translate(exc) from exc

    def save_screenshot(self, path: str) -> bool:
        try:
            self._require_page().screenshot(path=path, full_page=True)
            return True
        except Exception as exc:
            raise self._translate(exc) from exc

    def register_owned_window_handle(self, handle: str) -> None:
        """Claim a popup created by an explicit crawler action.

        Some Amazon/SellerSprite popups use ``noopener`` and therefore have no
        Playwright opener relationship. The caller must only register a handle
        observed immediately after its own click/upload action.
        """
        page = self._page_map().get(handle)
        if page is None:
            raise WebDriverException(f"没有找到要登记的 CDP 标签页：{handle}")
        self._remember_owned_page(page, role="popup")

    def begin_owned_page_action(self, label: str = "") -> str:
        """Begin a crawler action that may create a true ``noopener`` page.

        Only context ``page`` events emitted while the token is active are
        candidates. They remain unowned until a caller proves their purpose
        with a stage-specific URL predicate.
        """

        self._ensure_ownership_state()
        token = f"{str(label or 'action')}:{uuid.uuid4().hex}"
        self._action_page_captures[token] = {}
        return token

    def claim_owned_action_pages(
        self,
        token: str,
        url_predicate: Callable[[str], bool],
    ) -> List[str]:
        """Claim only matching pages observed during one explicit action."""

        self._ensure_ownership_state()
        if not callable(url_predicate):
            raise TypeError("url_predicate 必须可调用。")
        candidates = self._action_page_captures.get(str(token), {})
        claimed: List[str] = []
        for page in list(candidates.values()):
            try:
                if page.is_closed():
                    continue
                url = str(page.url or "")
            except Exception:
                continue
            try:
                matches = bool(url_predicate(url))
            except Exception:
                matches = False
            if not matches:
                continue
            self._remember_owned_page(page, role="popup")
            handle = self._handle_for_page(page)
            if handle:
                claimed.append(handle)
        return claimed

    def end_owned_page_action(self, token: str) -> None:
        """End a capture and leave every unmatched/user page untouched."""

        self._ensure_ownership_state()
        self._action_page_captures.pop(str(token), None)

    @property
    def owned_window_handles(self) -> List[str]:
        """Open handles proven to belong to this driver, in context order."""
        self._ensure_ownership_state()
        self._discover_owned_opener_descendants()
        return [
            handle
            for handle, page in self._page_map().items()
            if id(page) in self._owned_pages
        ]

    def owned_handle_snapshot(self) -> FrozenSet[str]:
        """Capture the owned set before one crawler work item starts."""
        return frozenset(self.owned_window_handles)

    @property
    def ownership_close_failures(self) -> Tuple[str, ...]:
        """Recorded close errors, including the first error before a retry."""
        self._ensure_ownership_state()
        return tuple(self._ownership_close_failures)

    def _record_close_failure(self, page: Any, attempt: int, exc: Exception) -> None:
        handle = self._handle_for_page(page) or f"closed-cdp-{id(page)}"
        self._ownership_close_failures.append(
            f"handle={handle} attempt={attempt} error={type(exc).__name__}: {exc}"
        )

    def _close_page_with_retry(self, page: Any) -> bool:
        for attempt in (1, 2):
            try:
                if page.is_closed():
                    return True
                page.close()
                return True
            except Exception as exc:
                self._record_close_failure(page, attempt, exc)
        return False

    @staticmethod
    def _page_opener_depth(page: Any, candidates: Dict[int, Any]) -> int:
        depth = 0
        seen: Set[int] = set()
        current = page
        while id(current) not in seen:
            seen.add(id(current))
            try:
                opener = current.opener()
            except Exception:
                break
            if opener is None or id(opener) not in candidates:
                break
            depth += 1
            current = opener
        return depth

    def _owned_pages_with_descendants(self) -> List[Any]:
        """Return event-owned pages children-first without claiming unknown tabs."""
        self._ensure_ownership_state()
        self._discover_owned_opener_descendants()
        owned = dict(self._owned_pages)
        return sorted(
            owned.values(),
            key=lambda page: (
                self._page_opener_depth(page, owned),
                self._owned_page_roles.get(id(page), "popup") != "worker",
            ),
            reverse=True,
        )

    def _prune_closed_owned_pages(self) -> None:
        for page_id, page in list(self._owned_pages.items()):
            try:
                closed = page.is_closed()
            except Exception:
                closed = True
            if not closed:
                continue
            self._owned_pages.pop(page_id, None)
            self._owned_page_roles.pop(page_id, None)
            self._owned_page_listener_ids.discard(page_id)

    def _close_owned_pages_stably(
        self,
        should_close: Callable[[str, Any], bool],
    ) -> int:
        """Close selected owned pages while allowing delayed popup events to arrive."""
        self._ensure_ownership_state()
        deadline = self._monotonic_fn() + self.owned_page_close_stabilize_seconds
        closed_page_ids: Set[int] = set()
        attempted_page_ids: Set[int] = set()
        while True:
            self._discover_owned_opener_descendants()
            page_map = self._page_map()
            handles_by_id = {id(page): handle for handle, page in page_map.items()}
            for page in self._owned_pages_with_descendants():
                page_id = id(page)
                handle = handles_by_id.get(page_id, "")
                if (
                    page_id in attempted_page_ids
                    or not handle
                    or not should_close(handle, page)
                ):
                    continue
                attempted_page_ids.add(page_id)
                if self._close_page_with_retry(page):
                    closed_page_ids.add(page_id)

            now = self._monotonic_fn()
            if now >= deadline:
                break
            self._sleep_fn(
                min(self.owned_page_close_interval_seconds, max(deadline - now, 0.0))
            )

        self._prune_closed_owned_pages()
        return len(closed_page_ids)

    def close_owned_since(self, snapshot: FrozenSet[str] | Set[str]) -> int:
        """Close only crawler-owned popup pages created after ``snapshot``.

        The worker page is never closed here. After a two-second stabilization
        window, the worker is restored (or recreated if it disappeared).
        """
        before = {str(handle) for handle in snapshot}
        worker_id = id(self._worker_page) if self._worker_page is not None else None
        closed = self._close_owned_pages_stably(
            lambda handle, page: handle not in before and id(page) != worker_id
        )
        self.restore_worker_page()
        return closed

    def close(self) -> None:
        page = self._require_page()
        page_id = id(page)
        self._discover_owned_opener_descendants()
        if page_id not in self._owned_pages:
            self.restore_worker_page()
            raise WebDriverException("拒绝关闭未被爬虫标记为 owned 的 CDP 标签页。")
        if not self._close_page_with_retry(page):
            raise WebDriverException("关闭 crawler-owned CDP 标签页失败，已重试一次。")
        self._owned_pages.pop(page_id, None)
        self._owned_page_roles.pop(page_id, None)
        self._owned_page_listener_ids.discard(page_id)
        if page is self._worker_page:
            self._worker_page = None
        self.restore_worker_page()

    def _close_owned_pages(self) -> None:
        self._close_owned_pages_stably(lambda _handle, _page: True)
        self._owned_pages.clear()
        self._owned_page_roles.clear()
        self._owned_page_listener_ids.clear()
        self._worker_page = None

    def _cleanup_stale_crawler_pages(self) -> int:
        """Close only pages carrying a marker whose owning process is gone."""
        self._ensure_ownership_state()
        if self._context is None:
            return 0
        stale: Dict[int, Any] = {}
        for page in list(self._context.pages):
            marker = self._read_window_name(page)
            if marker and self._marker_is_stale(marker):
                stale[id(page)] = page
        closed = 0
        for page in sorted(
            stale.values(),
            key=lambda candidate: self._page_opener_depth(candidate, stale),
            reverse=True,
        ):
            if self._close_page_with_retry(page):
                closed += 1
        return closed

    def _disconnect_only(self) -> None:
        owner_id = getattr(self, "_owner_id", "")
        if owner_id:
            _ACTIVE_CDP_OWNER_IDS.discard(owner_id)
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None
        self._browser = None
        self._browser_cdp_session = None
        self._context = None
        self._page = None
        self._owned_pages = {}
        self._owned_page_roles = {}
        self._owned_page_listener_ids = set()
        self._worker_page = None
        self._context_page_listener_installed = False
        self._action_page_captures = {}
        self._owned_process = None

    def quit(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._owns_browser and self._browser_cdp_session is not None:
                self._browser_cdp_session.send("Browser.close")
                if self._owned_process is not None:
                    try:
                        self._owned_process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self._owned_process.terminate()
                        try:
                            self._owned_process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            self._owned_process.kill()
                            self._owned_process.wait(timeout=2)
            else:
                self._close_owned_pages()
        except Exception:
            pass
        finally:
            self._disconnect_only()

    def detach(self) -> None:
        """Disconnect without closing pages or the Chrome process."""
        if self._closed:
            return
        self._closed = True
        self._disconnect_only()

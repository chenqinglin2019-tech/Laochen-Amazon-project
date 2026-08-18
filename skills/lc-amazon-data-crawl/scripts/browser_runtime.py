#!/usr/bin/env python3
"""Browser backends shared by the Amazon crawler modes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from selenium.common.exceptions import (
    JavascriptException,
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By


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
            self._page = self._context.new_page()
            self._remember_owned_page(self._page)
            self._page.set_default_timeout(self._page_timeout * 1000)
            self._page.set_default_navigation_timeout(self._page_timeout * 1000)
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

    def _require_page(self) -> Any:
        if self._page is None or self._page.is_closed():
            raise WebDriverException("CDP 抓取标签页已经关闭。")
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

    def set_page_load_timeout(self, timeout: int) -> None:
        self._page_timeout = max(int(timeout), 1)
        if self._page is not None:
            self._page.set_default_navigation_timeout(self._page_timeout * 1000)

    def get(self, url: str) -> None:
        try:
            self._require_page().goto(
                url,
                wait_until="domcontentloaded",
                timeout=self._page_timeout * 1000,
            )
        except Exception as exc:
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

    def _remember_owned_page(self, page: Any) -> None:
        """Record a page explicitly created by this driver connection."""
        if page is None:
            return
        self._owned_pages[id(page)] = page

    def register_owned_window_handle(self, handle: str) -> None:
        """Claim a popup created by an explicit crawler action.

        Some Amazon/SellerSprite popups use ``noopener`` and therefore have no
        Playwright opener relationship. The caller must only register a handle
        observed immediately after its own click/upload action.
        """
        page = self._page_map().get(handle)
        if page is None:
            raise WebDriverException(f"没有找到要登记的 CDP 标签页：{handle}")
        self._remember_owned_page(page)

    def close(self) -> None:
        page = self._require_page()
        page_id = id(page)
        try:
            page.close()
        except Exception as exc:
            raise self._translate(exc) from exc
        self._owned_pages.pop(page_id, None)
        remaining = self._page_map()
        self._page = next(iter(remaining.values()), None)

    def _owned_pages_with_descendants(self) -> List[Any]:
        """Return owned pages and their popup descendants, children first.

        Every CDP connection sees all pages in the shared browser context, so
        creation time does not establish ownership. Another worker or the user
        may create a tab after this driver connects. Ownership starts only from
        pages explicitly created by this instance and expands through
        Playwright's opener relationship.
        """
        owned = dict(self._owned_pages)
        if self._context is None:
            return list(reversed(list(owned.values())))

        changed = True
        while changed:
            changed = False
            for page in list(self._context.pages):
                page_id = id(page)
                if page_id in owned:
                    continue
                try:
                    opener = page.opener()
                except Exception:
                    continue
                if opener is not None and id(opener) in owned:
                    owned[page_id] = page
                    changed = True

        return list(reversed(list(owned.values())))

    def _close_owned_pages(self) -> None:
        for page in self._owned_pages_with_descendants():
            try:
                if page.is_closed():
                    continue
                page.close()
            except Exception:
                pass
        self._owned_pages.clear()

    def _disconnect_only(self) -> None:
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

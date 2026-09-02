from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Callable, Optional

from selenium.common.exceptions import WebDriverException


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from browser_runtime import (
    CRAWLER_WINDOW_NAME_PREFIX,
    CdpSwitchTo,
    CdpWebDriver,
    _ACTIVE_CDP_OWNER_IDS,
)


class FakePage:
    def __init__(
        self,
        name: str,
        opener: Optional["FakePage"] = None,
        window_name: str = "",
        close_failures: int = 0,
        goto_status: Optional[int] = 200,
        goto_error: Optional[Exception] = None,
        url: str = "about:blank",
    ) -> None:
        self.name = name
        self.url = url
        self.window_name = window_name
        self._opener = opener
        self._closed = False
        self._listeners: dict[str, list[Callable[[FakePage], None]]] = {}
        self.close_failures = close_failures
        self.close_calls = 0
        self.close_order: Optional[int] = None
        self.front_count = 0
        self.default_timeout = 0
        self.default_navigation_timeout = 0
        self.goto_status = goto_status
        self.goto_error = goto_error

    def opener(self) -> Optional["FakePage"]:
        return self._opener

    def on(self, event: str, callback: Callable[["FakePage"], None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def emit_popup(self, popup: "FakePage") -> None:
        for callback in list(self._listeners.get("popup", [])):
            callback(popup)

    def evaluate(self, expression: str, *args: str) -> str:
        if args and "window.name = marker" in expression:
            self.window_name = str(args[0])
        return self.window_name

    def set_default_timeout(self, timeout: int) -> None:
        self.default_timeout = timeout

    def set_default_navigation_timeout(self, timeout: int) -> None:
        self.default_navigation_timeout = timeout

    def bring_to_front(self) -> None:
        self.front_count += 1

    def goto(self, *_args: object, **_kwargs: object) -> object:
        if self.goto_error is not None:
            raise self.goto_error
        if self.goto_status is None:
            return None
        return FakeResponse(self.goto_status)

    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self.close_calls += 1
        if self.close_failures > 0:
            self.close_failures -= 1
            raise RuntimeError(f"close failed for {self.name}")
        self.close_order = FakeContext.next_close_order()
        self._closed = True


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class FakeContext:
    _close_counter = 0

    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages
        self._listeners: dict[str, list[Callable[[FakePage], None]]] = {}
        self.created_pages: list[FakePage] = []

    def on(self, event: str, callback: Callable[[FakePage], None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def emit_page(self, page: FakePage) -> None:
        if page not in self.pages:
            self.pages.append(page)
        for callback in list(self._listeners.get("page", [])):
            callback(page)

    def new_page(self) -> FakePage:
        page = FakePage(f"created-{len(self.created_pages) + 1}")
        self.created_pages.append(page)
        self.emit_page(page)
        return page

    @classmethod
    def next_close_order(cls) -> int:
        cls._close_counter += 1
        return cls._close_counter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.events: list[tuple[float, Callable[[], None]]] = []
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def schedule(self, at: float, callback: Callable[[], None]) -> None:
        self.events.append((at, callback))
        self.events.sort(key=lambda item: item[0])

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        target = self.now + seconds
        while self.events and self.events[0][0] <= target:
            at, callback = self.events.pop(0)
            self.now = at
            callback()
        self.now = target


def make_attached_driver(context: FakeContext, worker_page: FakePage) -> CdpWebDriver:
    driver = CdpWebDriver.__new__(CdpWebDriver)
    driver._closed = False
    driver._owns_browser = False
    driver._owned_process = None
    driver._playwright = None
    driver._browser = None
    driver._browser_cdp_session = None
    driver._context = context
    driver._page_timeout = 30
    driver._playwright_timeout_error = TimeoutError
    driver._page = worker_page
    driver._worker_page = worker_page
    driver._owned_pages = {}
    driver.switch_to = CdpSwitchTo(driver)
    driver._ensure_ownership_state()
    driver._install_context_page_listener()
    driver._remember_owned_page(worker_page, role="worker")
    return driver


def attach_fake_clock(driver: CdpWebDriver) -> FakeClock:
    clock = FakeClock()
    driver._monotonic_fn = clock.monotonic
    driver._sleep_fn = clock.sleep
    return clock


class CdpPageOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeContext._close_counter = 0
        _ACTIVE_CDP_OWNER_IDS.clear()

    def test_quit_closes_only_calling_worker_and_preserves_concurrent_user_tabs(self) -> None:
        user_page = FakePage("user")
        worker_a_page = FakePage("worker-a")
        context = FakeContext([user_page, worker_a_page])
        worker_a = make_attached_driver(context, worker_a_page)
        attach_fake_clock(worker_a)

        worker_b_page = FakePage("worker-b")
        late_user_page = FakePage("late-user")
        context.pages.extend([worker_b_page, late_user_page])
        worker_b = make_attached_driver(context, worker_b_page)
        attach_fake_clock(worker_b)

        worker_a.quit()

        self.assertTrue(worker_a_page.is_closed())
        self.assertFalse(worker_b_page.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertFalse(late_user_page.is_closed())

        worker_b.quit()
        self.assertTrue(worker_b_page.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertFalse(late_user_page.is_closed())

    def test_popup_events_register_recursive_tree_and_close_children_first(self) -> None:
        user_page = FakePage("user")
        worker_page = FakePage("worker")
        context = FakeContext([user_page, worker_page])
        driver = make_attached_driver(context, worker_page)
        attach_fake_clock(driver)
        popup = FakePage("popup", opener=worker_page)
        nested = FakePage("nested", opener=popup)

        context.emit_page(popup)
        worker_page.emit_popup(popup)
        context.emit_page(nested)
        popup.emit_popup(nested)

        self.assertEqual(len(driver.owned_window_handles), 3)
        self.assertTrue(popup.window_name.startswith(CRAWLER_WINDOW_NAME_PREFIX))
        self.assertTrue(nested.window_name.startswith(CRAWLER_WINDOW_NAME_PREFIX))

        driver.quit()

        self.assertTrue(worker_page.is_closed())
        self.assertTrue(popup.is_closed())
        self.assertTrue(nested.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertLess(nested.close_order or 0, popup.close_order or 0)
        self.assertLess(popup.close_order or 0, worker_page.close_order or 0)

    def test_close_owned_since_catches_explicit_noopener_and_delayed_popup(self) -> None:
        user_page = FakePage("user")
        worker_page = FakePage("worker")
        context = FakeContext([user_page, worker_page])
        driver = make_attached_driver(context, worker_page)
        clock = attach_fake_clock(driver)
        snapshot = driver.owned_handle_snapshot()
        noopener = FakePage("noopener")
        context.emit_page(noopener)
        noopener_handle = next(
            handle for handle, page in driver._page_map().items() if page is noopener
        )
        driver.register_owned_window_handle(noopener_handle)
        delayed_popup = FakePage("delayed", opener=noopener)
        concurrent_user_page = FakePage("concurrent-user")
        clock.schedule(0.75, lambda: context.emit_page(concurrent_user_page))
        clock.schedule(1.0, lambda: context.emit_page(delayed_popup))

        closed = driver.close_owned_since(snapshot)

        self.assertEqual(closed, 2)
        self.assertTrue(noopener.is_closed())
        self.assertTrue(delayed_popup.is_closed())
        self.assertFalse(worker_page.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertFalse(concurrent_user_page.is_closed())
        self.assertIs(driver._page, worker_page)
        self.assertEqual(clock.sleeps, [0.5, 0.5, 0.5, 0.5])

    def test_action_scope_claims_matching_noopener_but_preserves_user_page(self) -> None:
        worker_page = FakePage("worker")
        context = FakeContext([worker_page])
        driver = make_attached_driver(context, worker_page)
        attach_fake_clock(driver)
        snapshot = driver.owned_handle_snapshot()
        token = driver.begin_owned_page_action("find-similar")
        user_page = FakePage("user", url="https://example.com/stylesnap")
        result_page = FakePage(
            "result",
            url="https://www.amazon.com/stylesnap/products?searchType=flow",
        )
        context.emit_page(user_page)
        context.emit_page(result_page)

        claimed = driver.claim_owned_action_pages(
            token,
            lambda url: url.startswith("https://www.amazon.com/stylesnap/"),
        )
        driver.end_owned_page_action(token)
        closed = driver.close_owned_since(snapshot)

        self.assertEqual(len(claimed), 1)
        self.assertEqual(closed, 1)
        self.assertTrue(result_page.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertFalse(worker_page.is_closed())

    def test_restore_worker_recreates_lost_page_without_selecting_user_page(self) -> None:
        user_page = FakePage("user")
        lost_worker = FakePage("lost-worker")
        context = FakeContext([user_page, lost_worker])
        driver = make_attached_driver(context, lost_worker)
        lost_worker._closed = True

        handle = driver.restore_worker_page()

        replacement = context.created_pages[-1]
        self.assertIs(driver._page, replacement)
        self.assertIs(driver._worker_page, replacement)
        self.assertEqual(handle, driver.current_window_handle)
        self.assertTrue(replacement.window_name.startswith(CRAWLER_WINDOW_NAME_PREFIX))
        self.assertFalse(user_page.is_closed())

    def test_stale_marker_cleanup_closes_only_dead_owner_pages(self) -> None:
        dead_owner_page = FakePage(
            "stale",
            window_name=f"{CRAWLER_WINDOW_NAME_PREFIX}v1:99999999:dead:worker",
        )
        user_page = FakePage("user", window_name="ordinary-user-window")
        live_owner_id = "live-owner"
        live_owner_page = FakePage(
            "live",
            window_name=(
                f"{CRAWLER_WINDOW_NAME_PREFIX}v1:{os.getpid()}:"
                f"{live_owner_id}:worker"
            ),
        )
        worker_page = FakePage("worker")
        context = FakeContext(
            [dead_owner_page, user_page, live_owner_page, worker_page]
        )
        _ACTIVE_CDP_OWNER_IDS.add(live_owner_id)
        driver = make_attached_driver(context, worker_page)

        closed = driver._cleanup_stale_crawler_pages()

        self.assertEqual(closed, 1)
        self.assertTrue(dead_owner_page.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertFalse(live_owner_page.is_closed())
        self.assertFalse(worker_page.is_closed())

    def test_malformed_crawler_marker_is_not_ownership_proof(self) -> None:
        malformed = FakePage(
            "malformed",
            window_name=f"{CRAWLER_WINDOW_NAME_PREFIX}future:broken",
        )
        worker_page = FakePage("worker")
        context = FakeContext([malformed, worker_page])
        driver = make_attached_driver(context, worker_page)

        closed = driver._cleanup_stale_crawler_pages()

        self.assertEqual(closed, 0)
        self.assertFalse(malformed.is_closed())

    def test_next_connection_cleans_detached_same_process_worker_marker(self) -> None:
        user_page = FakePage("user")
        old_worker = FakePage("old-worker")
        context = FakeContext([user_page, old_worker])
        old_driver = make_attached_driver(context, old_worker)
        old_driver.detach()
        new_worker = FakePage("new-worker")
        context.pages.append(new_worker)
        new_driver = make_attached_driver(context, new_worker)

        closed = new_driver._cleanup_stale_crawler_pages()

        self.assertEqual(closed, 1)
        self.assertTrue(old_worker.is_closed())
        self.assertFalse(new_worker.is_closed())
        self.assertFalse(user_page.is_closed())

    def test_close_retries_once_and_records_first_failure(self) -> None:
        worker_page = FakePage("worker")
        popup = FakePage("flaky", opener=worker_page, close_failures=1)
        context = FakeContext([worker_page])
        driver = make_attached_driver(context, worker_page)
        attach_fake_clock(driver)
        snapshot = driver.owned_handle_snapshot()
        context.emit_page(popup)

        closed = driver.close_owned_since(snapshot)

        self.assertEqual(closed, 1)
        self.assertEqual(popup.close_calls, 2)
        self.assertEqual(len(driver.ownership_close_failures), 1)
        self.assertIn("attempt=1", driver.ownership_close_failures[0])

    def test_permanent_close_failure_is_attempted_exactly_twice(self) -> None:
        worker_page = FakePage("worker")
        popup = FakePage("broken", opener=worker_page, close_failures=99)
        context = FakeContext([worker_page])
        driver = make_attached_driver(context, worker_page)
        attach_fake_clock(driver)
        snapshot = driver.owned_handle_snapshot()
        context.emit_page(popup)

        closed = driver.close_owned_since(snapshot)

        self.assertEqual(closed, 0)
        self.assertEqual(popup.close_calls, 2)
        self.assertEqual(len(driver.ownership_close_failures), 2)
        self.assertFalse(popup.is_closed())

    def test_close_refuses_unknown_current_page_and_restores_worker(self) -> None:
        worker_page = FakePage("worker")
        user_page = FakePage("user")
        context = FakeContext([worker_page, user_page])
        driver = make_attached_driver(context, worker_page)
        driver._page = user_page

        with self.assertRaisesRegex(WebDriverException, "拒绝关闭"):
            driver.close()

        self.assertFalse(user_page.is_closed())
        self.assertFalse(worker_page.is_closed())
        self.assertIs(driver._page, worker_page)

    def test_switching_current_page_never_transfers_ownership(self) -> None:
        worker_page = FakePage("worker")
        user_page = FakePage("user")
        context = FakeContext([worker_page, user_page])
        driver = make_attached_driver(context, worker_page)
        attach_fake_clock(driver)
        user_handle = next(
            handle for handle, page in driver._page_map().items() if page is user_page
        )

        driver.switch_to.window(user_handle)
        driver.quit()

        self.assertTrue(worker_page.is_closed())
        self.assertFalse(user_page.is_closed())

    def test_get_exposes_429_and_503_response_status(self) -> None:
        for status in (429, 503):
            with self.subTest(status=status):
                worker_page = FakePage("worker", goto_status=status)
                context = FakeContext([worker_page])
                driver = make_attached_driver(context, worker_page)

                driver.get("https://www.amazon.com/example")

                self.assertEqual(driver.last_http_status, status)
                self.assertEqual(driver.last_navigation_error, "")

    def test_get_records_navigation_error_and_clears_previous_status(self) -> None:
        worker_page = FakePage("worker", goto_status=429)
        context = FakeContext([worker_page])
        driver = make_attached_driver(context, worker_page)
        driver.get("https://www.amazon.com/rate-limited")
        worker_page.goto_error = RuntimeError("net::ERR_TIMED_OUT")

        with self.assertRaisesRegex(WebDriverException, "ERR_TIMED_OUT"):
            driver.get("https://www.amazon.com/retry")

        self.assertIsNone(driver.last_http_status)
        self.assertEqual(driver.last_navigation_error, "net::ERR_TIMED_OUT")


if __name__ == "__main__":
    unittest.main()

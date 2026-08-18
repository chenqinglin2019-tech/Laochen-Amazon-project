from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Optional


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from browser_runtime import CdpWebDriver


class FakePage:
    def __init__(self, name: str, opener: Optional["FakePage"] = None) -> None:
        self.name = name
        self._opener = opener
        self._closed = False
        self.close_order: Optional[int] = None

    def opener(self) -> Optional["FakePage"]:
        return self._opener

    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self.close_order = FakeContext.next_close_order()
        self._closed = True


class FakeContext:
    _close_counter = 0

    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages

    @classmethod
    def next_close_order(cls) -> int:
        cls._close_counter += 1
        return cls._close_counter


def make_attached_driver(context: FakeContext, owned_page: FakePage) -> CdpWebDriver:
    driver = CdpWebDriver.__new__(CdpWebDriver)
    driver._closed = False
    driver._owns_browser = False
    driver._owned_process = None
    driver._playwright = None
    driver._browser = None
    driver._browser_cdp_session = None
    driver._context = context
    driver._page = owned_page
    driver._owned_pages = {}
    driver._remember_owned_page(owned_page)
    return driver


class CdpPageOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeContext._close_counter = 0

    def test_quit_closes_only_the_calling_drivers_page(self) -> None:
        user_page = FakePage("user")
        worker_a_page = FakePage("worker-a")
        context = FakeContext([user_page, worker_a_page])
        worker_a = make_attached_driver(context, worker_a_page)

        # These tabs appear after worker A connected. Creation time alone must
        # not make them worker A's responsibility.
        worker_b_page = FakePage("worker-b")
        late_user_page = FakePage("late-user")
        context.pages.extend([worker_b_page, late_user_page])
        worker_b = make_attached_driver(context, worker_b_page)

        worker_a.quit()

        self.assertTrue(worker_a_page.is_closed())
        self.assertFalse(worker_b_page.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertFalse(late_user_page.is_closed())

        worker_b.quit()

        self.assertTrue(worker_b_page.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertFalse(late_user_page.is_closed())

    def test_quit_closes_owned_popup_tree_but_not_other_worker_popups(self) -> None:
        user_page = FakePage("user")
        worker_a_page = FakePage("worker-a")
        worker_a_popup = FakePage("worker-a-popup", opener=worker_a_page)
        worker_a_nested_popup = FakePage(
            "worker-a-nested-popup", opener=worker_a_popup
        )
        worker_b_page = FakePage("worker-b")
        worker_b_popup = FakePage("worker-b-popup", opener=worker_b_page)
        context = FakeContext(
            [
                user_page,
                worker_a_page,
                worker_a_popup,
                worker_a_nested_popup,
                worker_b_page,
                worker_b_popup,
            ]
        )
        worker_a = make_attached_driver(context, worker_a_page)

        worker_a.quit()

        self.assertTrue(worker_a_page.is_closed())
        self.assertTrue(worker_a_popup.is_closed())
        self.assertTrue(worker_a_nested_popup.is_closed())
        self.assertFalse(worker_b_page.is_closed())
        self.assertFalse(worker_b_popup.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertLess(
            worker_a_nested_popup.close_order or 0,
            worker_a_page.close_order or 0,
        )

    def test_switching_current_page_does_not_transfer_ownership(self) -> None:
        worker_page = FakePage("worker")
        user_page = FakePage("user")
        context = FakeContext([worker_page, user_page])
        driver = make_attached_driver(context, worker_page)
        driver._page = user_page

        driver.quit()

        self.assertTrue(worker_page.is_closed())
        self.assertFalse(user_page.is_closed())

    def test_explicitly_registered_noopener_popup_is_owned(self) -> None:
        worker_page = FakePage("worker")
        noopener_popup = FakePage("crawler-popup")
        user_page = FakePage("user")
        context = FakeContext([worker_page, noopener_popup, user_page])
        driver = make_attached_driver(context, worker_page)
        popup_handle = next(
            handle
            for handle, page in driver._page_map().items()
            if page is noopener_popup
        )

        driver.register_owned_window_handle(popup_handle)
        driver.quit()

        self.assertTrue(worker_page.is_closed())
        self.assertTrue(noopener_popup.is_closed())
        self.assertFalse(user_page.is_closed())

    def test_close_current_claimed_popup_keeps_other_tabs_available(self) -> None:
        worker_page = FakePage("worker")
        noopener_popup = FakePage("crawler-popup")
        user_page = FakePage("user")
        context = FakeContext([worker_page, noopener_popup, user_page])
        driver = make_attached_driver(context, worker_page)
        popup_handle = next(
            handle
            for handle, page in driver._page_map().items()
            if page is noopener_popup
        )
        driver.register_owned_window_handle(popup_handle)
        driver._page = noopener_popup

        self.assertEqual(driver.current_window_handle, popup_handle)
        driver.close()

        self.assertTrue(noopener_popup.is_closed())
        self.assertFalse(worker_page.is_closed())
        self.assertFalse(user_page.is_closed())
        self.assertNotIn(popup_handle, driver.window_handles)


if __name__ == "__main__":
    unittest.main()

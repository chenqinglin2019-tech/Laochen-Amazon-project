from __future__ import annotations

import functools
import http.server
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "browser_ownership"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from browser_runtime import CdpWebDriver, _ACTIVE_CDP_OWNER_IDS


CHROME_CANDIDATES = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path(
        "/Applications/Google Chrome for Testing.app/Contents/MacOS/"
        "Google Chrome for Testing"
    ),
)


def find_system_chrome() -> Optional[Path]:
    for candidate in CHROME_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


try:
    import playwright.sync_api  # noqa: F401
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
else:
    PLAYWRIGHT_AVAILABLE = True


class QuietFixtureHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


class LocalFixtureServer:
    def __init__(self) -> None:
        handler = functools.partial(QuietFixtureHandler, directory=str(FIXTURE_DIR))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "LocalFixtureServer":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def wait_for_devtools_port(user_data_dir: Path, process: subprocess.Popen[bytes]) -> int:
    port_file = user_data_dir / "DevToolsActivePort"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Chrome exited before CDP became ready (exit={process.returncode}).")
        try:
            first_line = port_file.read_text(encoding="utf-8").splitlines()[0]
            port = int(first_line)
        except (FileNotFoundError, IndexError, OSError, ValueError):
            time.sleep(0.05)
            continue
        if port > 0:
            return port
    raise RuntimeError("Chrome did not write DevToolsActivePort within 15 seconds.")


def fixture_role_from_url(url: str) -> str:
    return str(parse_qs(urlparse(url).query).get("role", [""])[0])


def fixture_role(page: object) -> str:
    try:
        url = str(getattr(page, "url", "") or "")
    except Exception:
        return ""
    return fixture_role_from_url(url)


@unittest.skipUnless(find_system_chrome(), "system Google Chrome is unavailable")
@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, "Playwright is unavailable")
class RealChromeOwnershipIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        _ACTIVE_CDP_OWNER_IDS.clear()

    def test_real_chrome_popup_ownership_returns_to_baseline_and_preserves_users(self) -> None:
        chrome = find_system_chrome()
        self.assertIsNotNone(chrome)

        with tempfile.TemporaryDirectory(prefix="lc-browser-ownership-") as temp_dir:
            user_data_dir = Path(temp_dir) / "chrome-profile"
            user_data_dir.mkdir()
            process = subprocess.Popen(
                [
                    str(chrome),
                    "--headless=new",
                    "--remote-debugging-address=127.0.0.1",
                    "--remote-debugging-port=0",
                    f"--user-data-dir={user_data_dir}",
                    "--profile-directory=Default",
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-extensions",
                    "--disable-popup-blocking",
                    "--disable-sync",
                    "--no-default-browser-check",
                    "--no-first-run",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            driver: Optional[CdpWebDriver] = None
            try:
                port = wait_for_devtools_port(user_data_dir, process)
                with LocalFixtureServer() as server:
                    driver = CdpWebDriver(
                        debugger_address=f"127.0.0.1:{port}",
                        page_timeout=10,
                        expected_user_data_dir=user_data_dir,
                        profile_directory="Default",
                    )
                    driver.get(f"{server.origin}/main.html")
                    worker = driver._worker_page
                    context = driver._context
                    self.assertIsNotNone(worker)
                    self.assertIsNotNone(context)

                    baseline_user = context.new_page()
                    baseline_user.goto(
                        f"{server.origin}/child.html?role=baseline-user",
                        wait_until="domcontentloaded",
                    )
                    driver.restore_worker_page()
                    baseline_page_ids = {id(page) for page in context.pages}
                    owned_baseline = driver.owned_handle_snapshot()

                    # A normal popup is proved by its opener relationship.
                    with context.expect_page(timeout=5000) as ordinary_info:
                        worker.locator("#open-ordinary-popup").click()
                    ordinary = ordinary_info.value
                    ordinary.wait_for_load_state("domcontentloaded")
                    self.assertEqual(fixture_role(ordinary), "ordinary-popup")

                    # A noopener page is only a candidate during the explicit
                    # action. A concurrent user-created tab is deliberately
                    # opened inside the same capture and must remain unowned.
                    action_token = driver.begin_owned_page_action("real-noopener")
                    driver.restore_worker_page()
                    with context.expect_page(timeout=5000) as result_info:
                        worker.locator("#open-noopener-result").click()
                    result = result_info.value
                    result.wait_for_load_state("domcontentloaded")
                    self.assertEqual(fixture_role(result), "action-result")
                    concurrent_user = context.new_page()
                    concurrent_user.goto(
                        f"{server.origin}/child.html?role=concurrent-user",
                        wait_until="domcontentloaded",
                    )
                    claimed = driver.claim_owned_action_pages(
                        action_token,
                        lambda url: fixture_role_from_url(url) == "action-result",
                    )
                    driver.end_owned_page_action(action_token)

                    # This timer fires after close_owned_since has started. It
                    # proves that the stabilization loop observes and closes a
                    # delayed opener descendant instead of leaking it.
                    seen_pages: list[object] = []
                    context.on("page", lambda page: seen_pages.append(page))
                    driver.restore_worker_page()
                    worker.locator("#open-delayed-descendant").click()
                    started = time.monotonic()
                    closed = driver.close_owned_since(owned_baseline)
                    elapsed = time.monotonic() - started

                    delayed = next(
                        (page for page in seen_pages if fixture_role(page) == "delayed-descendant"),
                        None,
                    )
                    self.assertEqual(len(claimed), 1)
                    self.assertEqual(closed, 3)
                    self.assertTrue(ordinary.is_closed())
                    self.assertTrue(result.is_closed())
                    self.assertIsNotNone(delayed, "the delayed descendant never opened")
                    self.assertTrue(delayed.is_closed())
                    self.assertFalse(baseline_user.is_closed())
                    self.assertFalse(concurrent_user.is_closed())
                    self.assertEqual(set(driver.owned_window_handles), set(owned_baseline))
                    self.assertEqual(
                        {id(page) for page in context.pages},
                        baseline_page_ids | {id(concurrent_user)},
                    )
                    self.assertIs(driver._page, worker)
                    self.assertGreaterEqual(elapsed, 1.9)
            finally:
                if driver is not None:
                    driver.quit()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()

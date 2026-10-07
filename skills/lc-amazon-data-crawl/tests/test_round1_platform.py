"""Round-1 platform fixes: browser startup, launchers, installer, Windows, packaging.

PowerShell behaviour tests run when `pwsh` (or Windows `powershell`) is on PATH
or LC_TEST_PWSH points at one; the static checks below always run.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_ROOT / "scripts"
TESTS_DIR = Path(__file__).resolve().parent
for entry in (SCRIPTS_DIR, TESTS_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import browser_runtime  # noqa: E402
import package_skill  # noqa: E402
import start_cdp_browser as scb  # noqa: E402
import test_runner_packaging as packaging_tests  # noqa: E402

auth_binary_name = packaging_tests.auth_binary_name

AUTH_DENIED = "云端鉴权未通过，本轮不继续执行。"
WINDOWS_AUTH = "lc-auth-check-windows-amd64.exe"
LAUNCHER_PS1 = SCRIPTS_DIR / "runner" / "lc-amazon-data-crawl.ps1"
LAUNCHER_CMD = SCRIPTS_DIR / "runner" / "lc-amazon-data-crawl.cmd"
PS_SCRIPTS = (
    SCRIPTS_DIR / "check_auth.ps1",
    SCRIPTS_DIR / "setup_runner.ps1",
    SCRIPTS_DIR / "install_for_user.ps1",
    LAUNCHER_PS1,
)


def find_pwsh() -> Optional[str]:
    configured = os.environ.get("LC_TEST_PWSH", "").strip()
    if configured and Path(configured).is_file():
        return configured
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    return None


PWSH = find_pwsh()


def bash_launcher_text() -> str:
    setup = (SCRIPTS_DIR / "setup_runner.sh").read_text(encoding="utf-8")
    match = re.search(
        r"^cat > \"\$TARGET_DIR/lc-amazon-data-crawl\.sh\" <<'EOF'\n(.*?)^EOF$", setup, re.S | re.M
    )
    assert match, "bash launcher heredoc not found"
    return match.group(1)


def bash_commands() -> set:
    text = bash_launcher_text()
    body = text.split('case "$COMMAND" in', 1)[1]
    labels = set()
    for label in re.findall(r"^  ([a-z|\-]+)\)$", body, re.M):
        labels.update(label.split("|"))
    return labels - {"help", "-h", "--help"}


def ps1_commands() -> set:
    text = LAUNCHER_PS1.read_text(encoding="utf-8-sig")
    body = text.split("switch -Exact ($Command) {", 1)[1]
    return set(re.findall(r"^    '([a-z\-]+)' \{$", body, re.M))


def ps1_command_block(command: str) -> str:
    text = LAUNCHER_PS1.read_text(encoding="utf-8-sig")
    block = text.split(f"    '{command}' {{\n", 1)[1]
    return block.split("\n    }\n", 1)[0]


def bash_command_block(command: str) -> str:
    text = bash_launcher_text()
    block = text.split(f"\n  {command})\n", 1)[1]
    return block.split("\n    ;;\n", 1)[0]


class FakeCdpServer:
    """Answers /json/version and /json/list like a Chrome debug endpoint."""

    def __init__(self, targets: Optional[List[Dict[str, Any]]] = None, browser_id: str = "abc-123") -> None:
        self.targets = targets or []
        self.browser_id = browser_id
        self.requests: List[str] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer.requests.append(self.path)
                if self.path == "/json/version":
                    payload: Any = {
                        "Browser": "Chrome/141.0.0.0",
                        "webSocketDebuggerUrl": f"ws://{outer.address}/devtools/browser/{outer.browser_id}",
                    }
                elif self.path in ("/json/list", "/json"):
                    payload = outer.targets
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: Any) -> None:
                return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    @property
    def ws_path(self) -> str:
        return f"/devtools/browser/{self.browser_id}"

    def __enter__(self) -> "FakeCdpServer":
        self.thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def write_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


# ---------------------------------------------------------------------------
# browser_runtime: Windows-safe liveness probe and the shared profile default
# ---------------------------------------------------------------------------


class PidProbeTests(unittest.TestCase):
    def test_windows_probe_never_sends_a_signal(self) -> None:
        def forbidden(*_args: Any) -> None:
            raise AssertionError("os.kill(pid, 0) is CTRL_C_EVENT on Windows")

        with patch.object(browser_runtime, "_IS_WINDOWS", True), patch.object(
            browser_runtime, "_windows_pid_is_running", return_value=True
        ) as windows_probe, patch.object(browser_runtime.os, "kill", forbidden):
            self.assertTrue(browser_runtime.pid_is_running(424242))
            self.assertTrue(browser_runtime.CdpWebDriver._pid_is_running(424242))
        self.assertEqual(windows_probe.call_count, 2)

    def test_windows_probe_errors_mean_not_running(self) -> None:
        with patch.object(browser_runtime, "_IS_WINDOWS", True), patch.object(
            browser_runtime, "_windows_pid_is_running", side_effect=OSError("no kernel32")
        ):
            self.assertFalse(browser_runtime.pid_is_running(424242))

    def test_posix_probe(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX only")
        self.assertTrue(browser_runtime.pid_is_running(os.getpid()))
        self.assertFalse(browser_runtime.pid_is_running(0))
        self.assertFalse(browser_runtime.pid_is_running("bad"))
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(browser_runtime.pid_is_running(child.pid))

    def test_single_profile_default(self) -> None:
        self.assertEqual(browser_runtime.DEFAULT_CHROME_USER_DATA_DIR, "chrome_profiles/lc-amazon-data-crawl-cft")
        user_data_dir, profile, address, _timeout = scb.browser_settings({})
        self.assertEqual(user_data_dir, (scb.ROOT_DIR / "chrome_profiles/lc-amazon-data-crawl-cft").resolve())
        self.assertEqual((profile, address), ("Default", "127.0.0.1:9222"))
        for template in (SKILL_ROOT / "assets" / "config").glob("*.json"):
            raw = json.loads(template.read_text(encoding="utf-8"))
            if "chrome_user_data_dir" in raw:
                self.assertEqual(raw["chrome_user_data_dir"], browser_runtime.DEFAULT_CHROME_USER_DATA_DIR, template.name)

    def test_profile_mismatch_message_is_actionable(self) -> None:
        text = (SCRIPTS_DIR / "browser_runtime.py").read_text(encoding="utf-8")
        self.assertIn("请关闭那个 Chrome 窗口后重新运行同一命令", text)
        self.assertIn("127.0.0.1:9223", text)


# ---------------------------------------------------------------------------
# I7: chrome_binary auto / install-browser
# ---------------------------------------------------------------------------


class ChromeDiscoveryTests(unittest.TestCase):
    def test_missing_browser_names_install_browser_and_alternative(self) -> None:
        with patch.object(scb, "discover_chrome_for_testing", return_value=None):
            with self.assertRaises(scb.BrowserStartError) as caught:
                scb.resolve_chrome_binary({"chrome_binary": "auto"})
        message = str(caught.exception)
        self.assertEqual(caught.exception.exit_code, 30)
        self.assertIn("./lc-amazon-data-crawl.sh install-browser", message)
        self.assertIn(".\\lc-amazon-data-crawl.cmd install-browser", message)
        self.assertIn("python -m playwright install chromium", message)
        self.assertIn("Chrome for Testing", message)
        self.assertIn("chrome_binary", message)
        self.assertNotIn("lc-amazon-data-crawl.sh install。", message)

    def test_explicit_missing_binary_is_config_error(self) -> None:
        with self.assertRaises(scb.BrowserStartError) as caught:
            scb.resolve_chrome_binary({"chrome_binary": "/nonexistent/chrome"})
        self.assertEqual(caught.exception.exit_code, 40)

    def test_playwright_cache_roots_cover_every_os(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            env = {"LOCALAPPDATA": str(Path(temp_dir) / "LocalAppData"), "PLAYWRIGHT_BROWSERS_PATH": str(Path(temp_dir) / "custom")}
            with patch.dict(os.environ, env), patch.object(scb.Path, "home", return_value=home):
                roots = scb.playwright_cache_roots()
        self.assertIn(Path(env["PLAYWRIGHT_BROWSERS_PATH"]), roots)
        self.assertIn(home / "Library/Caches/ms-playwright", roots)
        self.assertIn(home / ".cache/ms-playwright", roots)
        self.assertIn(Path(env["LOCALAPPDATA"]) / "ms-playwright", roots)

    def test_auto_detects_playwright_chromium_layouts(self) -> None:
        layouts = {
            "linux": "chromium-1243/chrome-linux64/chrome",
            "windows": "chromium-1243/chrome-win64/chrome.exe",
            "mac_cft": "chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            "mac_chromium": "chromium-1100/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
        }
        for name, relative in layouts.items():
            with self.subTest(layout=name), tempfile.TemporaryDirectory() as temp_dir:
                cache = Path(temp_dir) / "ms-playwright"
                binary = write_executable(cache / relative, "exit 0\n")
                # Headless shell is not a usable headed browser and must not be chosen.
                write_executable(cache / "chromium_headless_shell-1243/chrome-linux/headless_shell", "exit 0\n")
                with patch.object(scb, "playwright_cache_roots", return_value=[cache]), patch.object(
                    scb, "chrome_binary_version_key", return_value=(1,)
                ):
                    candidates = [c for c in scb.default_chrome_for_testing_candidates() if str(c).startswith(str(cache))]
                    self.assertEqual([p.resolve() for p in candidates], [binary.resolve()])
                    self.assertEqual(scb.discover_chrome_for_testing(candidates), binary.resolve())

    def test_windows_version_lookup_never_executes_chrome(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = write_executable(Path(temp_dir) / "chrome-win64" / "chrome.exe", "exit 0\n")
            (binary.parent / "143.0.7499.4.manifest").write_text("", encoding="utf-8")
            with patch.object(scb, "IS_WINDOWS", True), patch.object(
                scb.subprocess, "run", side_effect=AssertionError("must not execute chrome.exe")
            ):
                self.assertEqual(scb.chrome_binary_version_key(binary), (143, 0, 7499, 4))
                self.assertFalse(scb.is_branded_chrome(binary))


# ---------------------------------------------------------------------------
# I14: branded Chrome guard on every OS
# ---------------------------------------------------------------------------


class BrandedChromeTests(unittest.TestCase):
    def test_branded_detection_by_path(self) -> None:
        branded = (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/opt/google/chrome/chrome",
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "C:\\Users\\me\\AppData\\Local\\Google\\Chrome SxS\\Application\\chrome.exe",
        )
        unbranded = (
            "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
            "/home/me/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome",
            "C:\\Users\\me\\AppData\\Local\\ms-playwright\\chromium-1243\\chrome-win64\\chrome.exe",
            "/usr/bin/chromium",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        )
        with patch.object(scb.subprocess, "run", side_effect=AssertionError("path decides")):
            for value in branded:
                self.assertTrue(scb.is_branded_chrome(Path(value)), value)
            for value in unbranded:
                self.assertFalse(scb.is_branded_chrome(Path(value)), value)

    def test_branded_detection_by_version_output(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX only")
        with tempfile.TemporaryDirectory() as temp_dir:
            custom = write_executable(Path(temp_dir) / "custom-browser", 'echo "Google Chrome 141.0.7390.54"\n')
            cft = write_executable(Path(temp_dir) / "other-browser", 'echo "Google Chrome for Testing 141.0.7390.54"\n')
            self.assertTrue(scb.is_branded_chrome(custom))
            self.assertFalse(scb.is_branded_chrome(cft))

    def test_guard_allows_old_branded_and_blocks_137_plus(self) -> None:
        path = Path("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe")
        with patch.object(scb, "chrome_binary_version_key", return_value=(136, 0, 0, 0)):
            self.assertFalse(scb.branded_chrome_blocks_extension(path))
        with patch.object(scb, "chrome_binary_version_key", return_value=(141, 0, 0, 0)):
            self.assertTrue(scb.branded_chrome_blocks_extension(path))
        with patch.object(scb, "chrome_binary_version_key", return_value=()):
            self.assertTrue(scb.branded_chrome_blocks_extension(path))

    def test_branded_launch_with_extension_is_refused_with_remedy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extension = Path(temp_dir) / "ext"
            extension.mkdir()
            config = {
                "chrome_binary": "/usr/bin/google-chrome",
                "extension_path": str(extension),
                "chrome_user_data_dir": str(Path(temp_dir) / "profile"),
                "debugger_address": f"127.0.0.1:{free_port()}",
            }
            with patch.object(scb, "resolve_chrome_binary", return_value=Path("/usr/bin/google-chrome")), patch.object(
                scb, "chrome_binary_version_key", return_value=(141, 0, 0, 0)
            ), patch.object(scb.subprocess, "Popen", side_effect=AssertionError("must not launch")):
                with self.assertRaises(scb.BrowserStartError) as caught:
                    scb.start_browser(config)
        self.assertEqual(caught.exception.exit_code, 30)
        self.assertIn("install-browser", str(caught.exception))
        self.assertIn('extension_path 设为 ""', str(caught.exception))


# ---------------------------------------------------------------------------
# I13 / I14 / I8: running Chrome checks without opening tabs
# ---------------------------------------------------------------------------


class RunningBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.profile = Path(self.temp.name) / "profile"
        self.profile.mkdir()
        self.extension = Path(self.temp.name) / "ext"
        self.extension.mkdir()
        (self.extension / "manifest.json").write_text(json.dumps({"version": "5.0.0"}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, server: FakeCdpServer, **overrides: Any) -> Dict[str, Any]:
        config = {
            "browser_backend": "cdp",
            "browser_mode": "reuse",
            "chrome_user_data_dir": str(self.profile),
            "debugger_address": server.address,
            "extension_path": str(self.extension),
            "sellersprite_required": True,
        }
        config.update(overrides)
        return config

    def write_active_port(self, port: int, ws_path: str) -> None:
        (self.profile / "DevToolsActivePort").write_text(f"{port}\n{ws_path}\n", encoding="utf-8")

    def no_tabs(self) -> Any:
        return patch.object(scb, "CdpWebDriver", side_effect=AssertionError("fast path must not open tabs"))

    def test_running_dedicated_chrome_with_extension_is_fast(self) -> None:
        targets = [{"type": "service_worker", "url": f"chrome-extension://{scb.SELLERSPRITE_EXTENSION_ID}/background.js"}]
        with FakeCdpServer(targets) as server, self.no_tabs():
            self.write_active_port(server.port, server.ws_path)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                scb.start_browser(self.config(server))
        self.assertIn("Profile 校验通过", output.getvalue())

    def test_extension_missing_in_running_chrome_needs_human(self) -> None:
        targets = [{"type": "page", "url": "about:blank"}]
        with FakeCdpServer(targets) as server, self.no_tabs():
            self.write_active_port(server.port, server.ws_path)
            with self.assertRaises(scb.BrowserStartError) as caught:
                scb.start_browser(self.config(server))
        self.assertEqual(caught.exception.exit_code, 30)
        message = str(caught.exception)
        self.assertIn("没有加载卖家精灵扩展", message)
        self.assertIn("关闭这个专用 Chrome 窗口", message)
        self.assertIn(str(self.profile), message)

    def test_extension_matched_by_unpacked_path_id(self) -> None:
        # Config paths are resolved before launch (/var -> /private/var on macOS).
        unpacked_id = scb.extension_id_from_path(self.extension.resolve())
        targets = [{"type": "service_worker", "url": f"chrome-extension://{unpacked_id}/sw.js"}]
        with FakeCdpServer(targets) as server, self.no_tabs():
            self.write_active_port(server.port, server.ws_path)
            scb.ensure_running_extension(self.config(server), server.address, self.profile, scb.browser_version_info(server.address))

    def test_launch_marker_proves_extension_even_when_worker_idle(self) -> None:
        with FakeCdpServer([]) as server, self.no_tabs():
            self.write_active_port(server.port, server.ws_path)
            scb.write_launch_marker(self.profile, server.ws_path, self.extension)
            scb.start_browser(self.config(server))
            # A marker from an earlier Chrome process does not count.
            scb.write_launch_marker(self.profile, "/devtools/browser/old", self.extension)
            with self.assertRaises(scb.BrowserStartError):
                scb.start_browser(self.config(server))

    def test_optional_extension_only_warns(self) -> None:
        with FakeCdpServer([]) as server, self.no_tabs():
            self.write_active_port(server.port, server.ws_path)
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
                scb.start_browser(self.config(server, sellersprite_required=False))
        self.assertIn("没有加载卖家精灵扩展", errors.getvalue())

    def test_auto_extension_not_installed_needs_human(self) -> None:
        with FakeCdpServer([]) as server, self.no_tabs(), patch.object(
            scb, "discover_sellersprite_extension", return_value=None
        ):
            self.write_active_port(server.port, server.ws_path)
            with self.assertRaises(scb.BrowserStartError) as caught:
                scb.start_browser(self.config(server, extension_path="auto"))
        self.assertEqual(caught.exception.exit_code, 30)

    def test_port_held_by_another_profile_is_actionable(self) -> None:
        with FakeCdpServer([]) as server, self.no_tabs():
            self.write_active_port(server.port, "/devtools/browser/other-process")
            with self.assertRaises(scb.BrowserStartError) as caught:
                scb.start_browser(self.config(server))
        message = str(caught.exception)
        self.assertEqual(caught.exception.exit_code, 30)
        self.assertIn(server.address, message)
        self.assertIn("Chrome/141.0.0.0", message)
        self.assertIn(str(self.profile), message)
        self.assertIn("127.0.0.1:9223", message)

    def test_port_mismatch_points_to_dedicated_port(self) -> None:
        with FakeCdpServer([], browser_id="foreign") as foreign, FakeCdpServer([], browser_id="ours") as ours:
            self.write_active_port(ours.port, ours.ws_path)
            with self.assertRaises(scb.BrowserStartError) as caught:
                scb.ensure_running_profile(
                    foreign.address, self.profile, "Default", 5, scb.browser_version_info(foreign.address)
                )
        self.assertIn(f"debugger_address 改成 {ours.address}", str(caught.exception))

    def test_unknown_profile_falls_back_to_chrome_version_check(self) -> None:
        with FakeCdpServer([]) as server, patch.object(scb, "verify_profile") as verify:
            scb.ensure_running_profile(server.address, self.profile, "Default", 5, scb.browser_version_info(server.address))
        verify.assert_called_once()

    def test_profile_mismatch_from_full_check_exits_30(self) -> None:
        from selenium.common.exceptions import WebDriverException

        with patch.object(scb, "CdpWebDriver", side_effect=WebDriverException("CDP 连接的 Chrome Profile 与配置不一致。")):
            with self.assertRaises(scb.BrowserStartError) as caught:
                scb.verify_profile("127.0.0.1:1", self.profile, "Default", 5)
        self.assertEqual(caught.exception.exit_code, 30)


class LaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, port: int, binary: Path) -> Dict[str, Any]:
        return {
            "browser_backend": "cdp",
            "browser_mode": "reuse",
            "chrome_binary": str(binary),
            "chrome_user_data_dir": str(self.profile),
            "debugger_address": f"127.0.0.1:{port}",
            "extension_path": "",
        }

    def test_profile_open_without_debug_port_fails_fast(self) -> None:
        binary = write_executable(self.root / "chromium" / "chrome", "exit 0\n")
        with patch.object(scb, "profile_in_use", return_value=True), patch.object(
            scb.subprocess, "Popen", side_effect=AssertionError("must not launch")
        ):
            with self.assertRaises(scb.BrowserStartError) as caught:
                scb.start_browser(self.config(free_port(), binary))
        self.assertEqual(caught.exception.exit_code, 30)
        self.assertIn("没有开启调试端口", str(caught.exception))

    def test_handoff_to_existing_chrome_does_not_wait_90_seconds(self) -> None:
        # A second Chrome on an open profile forwards its URL and exits at once.
        binary = write_executable(self.root / "chromium" / "chrome", "exit 0\n")
        started = time.monotonic()
        with patch.object(scb, "profile_in_use", return_value=False):
            with self.assertRaises(scb.BrowserStartError) as caught:
                scb.start_browser(self.config(free_port(), binary))
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(caught.exception.exit_code, 30)
        self.assertIn("立即退出", str(caught.exception))

    def test_detached_browser_stderr_is_preserved_privately(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX executable fixture")
        binary = write_executable(self.root / "chromium" / "chrome", 'echo "renderer diagnostic" >&2\nexit 0\n')
        with patch.object(scb, "profile_in_use", return_value=False):
            with self.assertRaises(scb.BrowserStartError):
                scb.start_browser(self.config(free_port(), binary))
        log = self.profile / "lc-crawler-browser-stderr.log"
        self.assertIn("renderer diagnostic", log.read_text())
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)

    def test_port_used_by_non_chrome_program(self) -> None:
        binary = write_executable(self.root / "chromium" / "chrome", "exit 0\n")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(5)
            port = listener.getsockname()[1]
            with patch.object(scb, "browser_version_info", return_value=None), patch.object(
                scb.subprocess, "Popen", side_effect=AssertionError("must not launch")
            ):
                with self.assertRaises(scb.BrowserStartError) as caught:
                    scb.start_browser(self.config(port, binary))
        self.assertIn("已被其他程序占用", str(caught.exception))

    def test_posix_singleton_lock_detection(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX only")
        self.profile.mkdir()
        lock = self.profile / "SingletonLock"
        os.symlink(f"{socket.gethostname()}-{os.getpid()}", lock)
        self.assertTrue(scb.profile_in_use(self.profile))
        lock.unlink()
        os.symlink(f"{socket.gethostname()}-999999999", lock)
        self.assertFalse(scb.profile_in_use(self.profile))

    def test_detached_launch_flags_per_os(self) -> None:
        with patch.object(scb, "IS_WINDOWS", True):
            windows = scb.launch_popen_kwargs()
        self.assertNotIn("start_new_session", windows)
        self.assertTrue(windows["creationflags"] & 0x00000008)
        self.assertTrue(windows["creationflags"] & 0x00000200)
        with patch.object(scb, "IS_WINDOWS", False):
            self.assertTrue(scb.launch_popen_kwargs()["start_new_session"])

    def test_main_exit_codes(self) -> None:
        missing = self.root / "missing.json"
        broken = self.root / "broken.json"
        broken.write_text("{", encoding="utf-8")
        for path, expected in ((missing, 40), (broken, 40)):
            with self.subTest(path=path.name), patch.object(sys, "argv", ["start_cdp_browser.py", "--config", str(path)]):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(scb.main(), expected)

    def test_extension_ids(self) -> None:
        digest = hashlib.sha256(b"/tmp/ext").hexdigest()[:32]
        expected = "".join(chr(ord("a") + int(c, 16)) for c in digest)
        self.assertEqual(scb.extension_id_from_path(Path("/tmp/ext"), windows=False), expected)
        windows_id = scb.extension_id_from_path(Path("c:\\ext"), windows=True)
        self.assertEqual(windows_id, scb._extension_id_from_bytes("C:\\ext".encode("utf-16-le")))
        self.assertIn(scb.SELLERSPRITE_EXTENSION_ID, scb.candidate_extension_ids(None))


# ---------------------------------------------------------------------------
# Python launchers (run_*_crawl.py)
# ---------------------------------------------------------------------------


class CrawlLauncherTests(unittest.TestCase):
    LAUNCHERS = ("run_amazon_front_crawl", "run_category_rank_crawl", "run_amazon_image_competitor_crawl")

    def test_windows_venv_paths_and_exit_passthrough(self) -> None:
        import importlib

        for name in self.LAUNCHERS:
            with self.subTest(launcher=name):
                module = importlib.import_module(name)
                parts = [path.relative_to(module.ROOT_DIR).as_posix() for path in module.VENV_PYTHONS]
                self.assertIn(".venv/Scripts/python.exe", parts)
                self.assertIn(".venv-scrapling/Scripts/python.exe", parts)
                for code in (0, 10, 20, 21, 30, 40, 50, 2):
                    self.assertEqual(module.child_exit_code(code), code)
                    self.assertEqual(module.run_child([sys.executable, "-c", f"raise SystemExit({code})"]), code)
                self.assertEqual(module.child_exit_code(-15), 143)

    def test_missing_config_is_config_error(self) -> None:
        for name in self.LAUNCHERS:
            with self.subTest(launcher=name):
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS_DIR / f"{name}.py"), "--config", "/nonexistent/config.json"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 40, result.stderr)


# ---------------------------------------------------------------------------
# Runner generation, launchers and auth-call budget (bash side)
# ---------------------------------------------------------------------------


def make_platform_fixture(root: Path) -> tuple:
    """Reuse the packaging fixture (without re-collecting its tests) plus round-1 files."""
    helper = packaging_tests.RunnerPackagingTests("test_auth_prefers_local_config")
    skill, runner = helper.make_fixture(root)
    for name in (
        "check_auth.ps1",
        "setup_runner.ps1",
        "install_for_user.ps1",
        "migrate_unique_runner.py",
        "package_skill.py",
        "run_outcome.py",
        "safety_cli.py",
    ):
        shutil.copy2(SCRIPTS_DIR / name, skill / "scripts" / name)
    (skill / "scripts" / "runner").mkdir()
    for name in ("lc-amazon-data-crawl.ps1", "lc-amazon-data-crawl.cmd"):
        shutil.copy2(SCRIPTS_DIR / "runner" / name, skill / "scripts" / "runner" / name)
    return skill, runner


def counting_auth(path: Path, counter: Path, status: int = 0) -> None:
    write_executable(path, f'printf x >> "{counter}"\nexit {status}\n')


class BashRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name == "nt":
            self.skipTest("bash runner tests need a POSIX shell")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.skill, self.runner = make_platform_fixture(self.root)
        self.counter = self.root / "auth-calls"
        self.env = {k: v for k, v in os.environ.items() if k != "LC_AUTH_VERIFIED_AT"}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def setup_runner(self, env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.skill / "scripts" / "setup_runner.sh"), str(self.runner)],
            text=True, capture_output=True, env=env or self.env, check=True,
        )

    def auth_calls(self) -> int:
        return len(self.counter.read_text()) if self.counter.exists() else 0

    def test_runner_gets_windows_entry_points_and_skips_maintenance_tools(self) -> None:
        self.setup_runner()
        for relative in ("lc-amazon-data-crawl.ps1", "lc-amazon-data-crawl.cmd", "scripts/check_auth.ps1",
                         "scripts/check_auth.sh", "scripts/run_outcome.py", "scripts/safety_cli.py"):
            self.assertTrue((self.runner / relative).is_file(), relative)
        self.assertFalse((self.runner / "scripts" / "migrate_unique_runner.py").exists())
        self.assertFalse((self.runner / "scripts" / "package_skill.py").exists())
        self.assertEqual(
            (self.runner / "lc-amazon-data-crawl.cmd").read_bytes(), LAUNCHER_CMD.read_bytes()
        )

    def test_nothing_in_a_runner_imports_migrate_unique_runner(self) -> None:
        for path in SCRIPTS_DIR.glob("*.py"):
            if path.name == "migrate_unique_runner.py":
                continue
            self.assertNotIn("migrate_unique_runner", path.read_text(encoding="utf-8"), path.name)

    def test_install_for_user_calls_cloud_auth_once(self) -> None:
        (self.skill / "config.json").write_text(json.dumps({"backend_url": "fixture", "backend_token": "t"}), encoding="utf-8")
        counting_auth(self.skill / "tools" / "bin" / auth_binary_name(), self.counter)
        env = dict(self.env, LC_AMAZON_INSTALL_SETUP_ONLY="1")
        subprocess.run(["bash", str(self.skill / "scripts" / "install_for_user.sh"), str(self.runner)],
                       text=True, capture_output=True, env=env, check=True)
        self.assertEqual(self.auth_calls(), 1)

    def test_recent_auth_is_honored_only_by_setup_install_doctor(self) -> None:
        self.setup_runner()
        counting_auth(self.runner / "tools" / "bin" / auth_binary_name(), self.counter)
        fresh = dict(self.env, LC_AUTH_VERIFIED_AT=str(int(time.time())))
        launcher = str(self.runner / "lc-amazon-data-crawl.sh")
        subprocess.run(["bash", launcher, "doctor"], env=fresh, text=True, capture_output=True, check=True)
        self.assertEqual(self.auth_calls(), 0)
        for command in ("amazon-front-dry-run", "amazon-front-run", "category-rank-run", "image-competitor-run",
                        "cdp-browser-start", "sellersprite-check", "install-browser"):
            before = self.auth_calls()
            subprocess.run(["bash", launcher, command], env=fresh, text=True, capture_output=True)
            self.assertEqual(self.auth_calls(), before + 1, command)
        for stale_value in (str(int(time.time()) - 601), str(int(time.time()) + 120), "abc", ""):
            before = self.auth_calls()
            subprocess.run(["bash", launcher, "doctor"], env=dict(self.env, LC_AUTH_VERIFIED_AT=stale_value),
                           text=True, capture_output=True, check=True)
            self.assertEqual(self.auth_calls(), before + 1, stale_value)

    def test_launcher_guard_before_browser_and_exit_codes_propagate(self) -> None:
        self.setup_runner()
        log = self.root / "python-calls"
        python = self.runner / ".venv" / "bin" / "python"
        write_executable(
            python,
            f'printf "%s\\n" "$*" >> "{log}"\n'
            'case "$1" in *start_cdp_browser.py) exit "${FAKE_START_EXIT:-0}";; '
            '*safety_cli.py) exit "${FAKE_GUARD_EXIT:-0}";; *) exit "${FAKE_RUN_EXIT:-0}";; esac\n',
        )
        launcher = str(self.runner / "lc-amazon-data-crawl.sh")
        result = subprocess.run(["bash", launcher, "amazon-front-run", "--config", "config/x.json"],
                                env=dict(self.env, FAKE_RUN_EXIT="21"), text=True, capture_output=True)
        self.assertEqual(result.returncode, 21)
        calls = log.read_text().splitlines()
        self.assertIn("safety_cli.py guard", calls[0])
        self.assertIn("start_cdp_browser.py --if-needed --config config/x.json", calls[1])
        self.assertIn("run_amazon_front_crawl.py --config config/x.json", calls[2])
        log.unlink()
        result = subprocess.run(["bash", launcher, "category-rank-run"], env=dict(self.env, FAKE_GUARD_EXIT="50"),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 50)
        self.assertEqual(len(log.read_text().splitlines()), 1)
        log.unlink()
        result = subprocess.run(["bash", launcher, "image-competitor-run"], env=dict(self.env, FAKE_START_EXIT="30"),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 30)
        self.assertEqual(len(log.read_text().splitlines()), 2)
        log.unlink()
        result = subprocess.run(["bash", launcher, "install-browser"], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(log.read_text().strip(), "-m playwright install chromium")


# ---------------------------------------------------------------------------
# Windows launchers: static checks (always) and behaviour (when pwsh exists)
# ---------------------------------------------------------------------------


class WindowsStaticTests(unittest.TestCase):
    def test_command_parity_with_bash_launcher(self) -> None:
        bash = bash_commands()
        self.assertTrue({"install", "install-browser", "doctor", "safety-status", "safety-clear"} <= bash)
        self.assertEqual(ps1_commands(), bash)

    def test_auth_policy_matches_bash(self) -> None:
        for command in bash_commands():
            ps1 = ps1_command_block(command)
            bash = bash_command_block(command)
            self.assertEqual("require_cloud_auth" in bash, "Invoke-CloudAuth" in ps1, command)
            self.assertEqual("--allow-recent" in bash, "-AllowRecent" in ps1, command)
            self.assertEqual("auto_start_reuse_browser" in bash, "Start-ReuseBrowserIfNeeded" in ps1, command)
            self.assertEqual("ensure_installed" in bash, "Assert-Installed" in ps1, command)
            if "--allow-recent" in bash:
                self.assertIn(command, {"install", "doctor"})

    def test_launcher_paths_and_exit_handling(self) -> None:
        text = LAUNCHER_PS1.read_text(encoding="utf-8-sig")
        self.assertIn("[IO.Path]::Combine($VenvDir, 'Scripts', 'python.exe')", text)
        self.assertIn("'.venv-scrapling'", text)
        self.assertIn("exit $LASTEXITCODE", text)
        guard = text.index("(Get-RunnerScript 'safety_cli.py') guard")
        start = text.index("(Get-RunnerScript 'start_cdp_browser.py') --if-needed")
        self.assertLess(guard, start)
        self.assertIn("-m playwright install chromium", text)
        self.assertNotIn("&&", text)  # Windows PowerShell 5.1 has no pipeline chain operators

    def test_ps1_files_are_utf8_with_bom_and_5_1_compatible(self) -> None:
        for path in PS_SCRIPTS:
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), f"{path.name} needs a UTF-8 BOM for PowerShell 5.1")
            text = raw.decode("utf-8-sig")
            for construct in (" ?? ", " ?. ", "&&", "||", "-AsHashtable", "ForEach-Object -Parallel"):
                self.assertNotIn(construct, text, f"{path.name}: {construct}")

    def test_cmd_shim(self) -> None:
        raw = LAUNCHER_CMD.read_bytes()
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        text = raw.decode("ascii")
        self.assertIn('-ExecutionPolicy Bypass -File "%~dp0lc-amazon-data-crawl.ps1" %*', text)
        self.assertIn("exit /b %ERRORLEVEL%", text)

    def test_check_auth_ps1_mirrors_sh(self) -> None:
        ps1 = (SCRIPTS_DIR / "check_auth.ps1").read_text(encoding="utf-8-sig")
        sh = (SCRIPTS_DIR / "check_auth.sh").read_text(encoding="utf-8")
        self.assertIn(WINDOWS_AUTH, ps1)
        for message in (AUTH_DENIED, "云端鉴权工具缺失，本轮不继续执行。", "鉴权程序启动准备失败："):
            self.assertIn(message, ps1)
            self.assertIn(message.rstrip("："), sh)
        for code in ("exit 2", "exit 3", "exit 4"):
            self.assertIn(code, ps1)
        self.assertIn("config.local.json", ps1)
        self.assertIn("LC_AUTH_VERIFIED_AT", ps1)
        self.assertIn("-le 600", ps1)

    def test_install_ps1_hides_token_and_writes_atomically(self) -> None:
        text = (SCRIPTS_DIR / "install_for_user.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Read-Host -AsSecureString", text)
        self.assertIn("ZeroFreeBSTR", text)
        self.assertIn("[IO.File]::Replace($temporary, $LocalConfig, $null)", text)
        self.assertIn("Protect-UserFile", text)
        self.assertIn("LC_AUTH_VERIFIED_AT", text)
        self.assertNotIn("Write-Output $token", text)

    def test_setup_ps1_copies_both_launchers(self) -> None:
        text = (SCRIPTS_DIR / "setup_runner.ps1").read_text(encoding="utf-8-sig")
        for needle in ("'check_auth.sh', 'check_auth.ps1'", "lc-amazon-data-crawl.sh", "'lc-amazon-data-crawl.ps1', 'lc-amazon-data-crawl.cmd'",
                       "'migrate_unique_runner.py', 'package_skill.py'", "migrate_operation_config.py", "-AllowRecent"):
            self.assertIn(needle, text)


@unittest.skipUnless(PWSH, "PowerShell not available (set LC_TEST_PWSH)")
class WindowsBehaviourTests(unittest.TestCase):
    """Runs the .ps1 entry points under PowerShell (pwsh on macOS/Linux works too)."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="鉴权 中文 ")
        self.root = Path(self.temp.name)
        self.skill, self.runner = make_platform_fixture(self.root)
        self.counter = self.root / "auth-calls"
        counting_auth(self.skill / "tools" / "bin" / WINDOWS_AUTH, self.counter)
        self.env = {k: v for k, v in os.environ.items() if k not in ("LC_AUTH_VERIFIED_AT", "LC_AMAZON_INSTALL_SETUP_ONLY")}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def ps(self, script: Path, *args: str, env: Optional[Dict[str, str]] = None, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
            text=True, capture_output=True, env=env or self.env, input=stdin, timeout=120,
        )

    def auth_calls(self) -> int:
        return len(self.counter.read_text()) if self.counter.exists() else 0

    def test_check_auth_exit_codes_and_messages(self) -> None:
        script = self.skill / "scripts" / "check_auth.ps1"
        result = self.ps(script)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        counting_auth(self.skill / "tools" / "bin" / WINDOWS_AUTH, self.counter, status=1)
        result = self.ps(script)
        self.assertEqual(result.returncode, 4)
        self.assertEqual(result.stderr.strip(), AUTH_DENIED)
        before = self.auth_calls()
        fresh = dict(self.env, LC_AUTH_VERIFIED_AT=str(int(time.time())))
        self.assertEqual(self.ps(script, "-AllowRecent", env=fresh).returncode, 0)
        self.assertEqual(self.auth_calls(), before)
        self.assertEqual(self.ps(script, env=fresh).returncode, 4)
        (self.skill / "tools" / "bin" / WINDOWS_AUTH).unlink()
        result = self.ps(script)
        self.assertEqual(result.returncode, 2)
        self.assertIn("鉴权工具缺失", result.stderr)

    def test_setup_creates_runner_usable_on_both_systems(self) -> None:
        result = self.ps(self.skill / "scripts" / "setup_runner.ps1", str(self.runner))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.auth_calls(), 1)
        self.assertEqual((self.runner / "lc-amazon-data-crawl.sh").read_text(encoding="utf-8"), bash_launcher_text())
        for relative in ("lc-amazon-data-crawl.ps1", "lc-amazon-data-crawl.cmd", "scripts/check_auth.ps1",
                         "scripts/check_auth.sh", "scripts/run_outcome.py", "config.json",
                         "config/doubao_embedding_vision.json", "config/amazon_front_crawler.json"):
            self.assertTrue((self.runner / relative).is_file(), relative)
        self.assertFalse((self.runner / "scripts" / "migrate_unique_runner.py").exists())
        ignore = (self.runner / ".gitignore").read_text(encoding="utf-8").splitlines()
        for line in ("config.json", "config.local.json", "config/doubao_embedding_vision.json", ".venv/"):
            self.assertEqual(ignore.count(line), 1, line)
        self.assertEqual(self.ps(self.skill / "scripts" / "setup_runner.ps1", str(self.runner)).returncode, 0)
        self.assertEqual((self.runner / ".gitignore").read_text(encoding="utf-8").splitlines(), ignore)
        # The bash launcher written by PowerShell works on POSIX.
        if os.name != "nt":
            counting_auth(self.runner / "tools" / "bin" / auth_binary_name(), self.counter, status=1)
            bash = subprocess.run(["bash", str(self.runner / "lc-amazon-data-crawl.sh"), "doctor"], text=True, capture_output=True)
            self.assertEqual(bash.returncode, 4)

    def test_setup_stops_before_writing_when_auth_fails(self) -> None:
        counting_auth(self.skill / "tools" / "bin" / WINDOWS_AUTH, self.counter, status=1)
        result = self.ps(self.skill / "scripts" / "setup_runner.ps1", str(self.runner))
        self.assertEqual(result.returncode, 4)
        self.assertEqual(result.stderr.strip(), AUTH_DENIED)
        self.assertEqual(sorted(p.name for p in self.runner.iterdir()), [".gitignore"])

    def make_runner(self) -> Path:
        result = self.ps(self.skill / "scripts" / "setup_runner.ps1", str(self.runner))
        self.assertEqual(result.returncode, 0, result.stderr)
        counting_auth(self.runner / "tools" / "bin" / WINDOWS_AUTH, self.counter)
        log = self.root / "python-calls"
        body = (
            f'printf "%s\\n" "$*" >> "{log}"\n'
            'case "$1" in *start_cdp_browser.py) exit "${FAKE_START_EXIT:-0}";; '
            '*safety_cli.py) exit "${FAKE_GUARD_EXIT:-0}";; *) exit "${FAKE_RUN_EXIT:-0}";; esac\n'
        )
        if os.name == "nt":  # pragma: no cover - real Windows uses a .cmd-free stub
            self.skipTest("fake venv python needs a POSIX shell")
        write_executable(self.runner / ".venv" / "bin" / "python", body)
        return log

    def test_every_command_stops_on_auth_failure(self) -> None:
        log = self.make_runner()
        counting_auth(self.runner / "tools" / "bin" / WINDOWS_AUTH, self.counter, status=1)
        for command in ("install", "install-browser", "doctor", "amazon-front-dry-run", "amazon-front-run",
                        "category-rank-dry-run", "category-rank-run", "image-competitor-dry-run",
                        "image-competitor-run", "cdp-browser-start", "sellersprite-check"):
            with self.subTest(command=command):
                result = self.ps(self.runner / "lc-amazon-data-crawl.ps1", command)
                self.assertEqual(result.returncode, 4, result.stderr)
                self.assertEqual(result.stderr.strip(), AUTH_DENIED)
                self.assertFalse(log.exists())

    def test_guard_start_run_order_and_exit_codes(self) -> None:
        log = self.make_runner()
        launcher = self.runner / "lc-amazon-data-crawl.ps1"
        result = self.ps(launcher, "amazon-front-run", "--config", "config/x.json", "--operation-mode", "unattended",
                         env=dict(self.env, FAKE_RUN_EXIT="21"))
        self.assertEqual(result.returncode, 21, result.stderr)
        calls = log.read_text().splitlines()
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[0].endswith("safety_cli.py guard"))
        self.assertTrue(calls[1].endswith("start_cdp_browser.py --if-needed --config config/x.json"))
        self.assertTrue(calls[2].endswith("run_amazon_front_crawl.py --config config/x.json --operation-mode unattended"))
        log.unlink()
        self.assertEqual(self.ps(launcher, "category-rank-run", env=dict(self.env, FAKE_GUARD_EXIT="50")).returncode, 50)
        self.assertEqual(len(log.read_text().splitlines()), 1)
        log.unlink()
        self.assertEqual(self.ps(launcher, "image-competitor-run", "--config=config/y.json",
                                 env=dict(self.env, FAKE_START_EXIT="30")).returncode, 30)
        self.assertTrue(log.read_text().splitlines()[1].endswith("--if-needed --config config/y.json"))
        log.unlink()
        for code in ("10", "20", "40"):
            self.assertEqual(self.ps(launcher, "category-rank-dry-run", env=dict(self.env, FAKE_RUN_EXIT=code)).returncode, int(code))
        self.assertTrue(log.read_text().splitlines()[0].endswith("run_category_rank_crawl.py --dry-run"))
        log.unlink()
        self.assertEqual(self.ps(launcher, "install-browser").returncode, 0)
        self.assertEqual(log.read_text().strip(), "-m playwright install chromium")
        log.unlink()
        before = self.auth_calls()
        self.assertEqual(self.ps(launcher, "safety-clear", "--confirm-reviewed").returncode, 0)
        self.assertEqual(self.ps(launcher, "safety-status").returncode, 0)
        self.assertEqual(self.auth_calls(), before)
        self.assertEqual([line.split("safety_cli.py ")[1] for line in log.read_text().splitlines()],
                         ["clear --confirm-reviewed", "status"])
        unknown = self.ps(launcher, "nope")
        self.assertEqual(unknown.returncode, 2)
        self.assertIn("Unknown command: nope", unknown.stderr)
        self.assertIn("install-browser", self.ps(launcher, "help").stdout)

    def test_doctor_reports_without_secrets(self) -> None:
        self.make_runner()
        (self.runner / "config" / "doubao_embedding_vision.json").write_text(json.dumps({
            "api_key": "secret-key-not-logged", "model": "m", "base_url": "u", "api_path": "p", "encoding_format": "float"}),
            encoding="utf-8")
        fresh = dict(self.env, LC_AUTH_VERIFIED_AT=str(int(time.time())))
        result = self.ps(self.runner / "lc-amazon-data-crawl.ps1", "doctor", env=fresh)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.auth_calls(), 1)  # only the setup call; doctor honored the recent check
        self.assertIn("doubao_embedding_vision: ready", result.stdout)
        self.assertIn("doubao_same_product_mini: unconfigured", result.stdout)
        self.assertIn("config/amazon_front_keyword_search.json: ok", result.stdout)
        self.assertNotIn("secret-key-not-logged", result.stdout + result.stderr)

    def test_installer_uses_one_auth_call_and_existing_token(self) -> None:
        (self.skill / "config.local.json").write_text(json.dumps({"backend_url": "fixture", "backend_token": "tok"}), encoding="utf-8")
        env = dict(self.env, LC_AMAZON_INSTALL_SETUP_ONLY="1")
        result = self.ps(self.skill / "scripts" / "install_for_user.ps1", str(self.runner), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.auth_calls(), 1)
        self.assertIn("安装完成", result.stdout)
        self.assertEqual(json.loads((self.runner / "config.local.json").read_text(encoding="utf-8"))["backend_token"], "tok")

    def test_installer_refuses_without_token_input(self) -> None:
        (self.skill / "config.json").write_text(json.dumps({"backend_url": "fixture", "backend_token": ""}), encoding="utf-8")
        env = dict(self.env, LC_AMAZON_INSTALL_SETUP_ONLY="1")
        script = self.skill / "scripts" / "install_for_user.ps1"
        noninteractive = self.ps(script, str(self.runner), env=env)
        # Piped stdin (an agent) must not silently "succeed" without a token.
        piped = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(self.runner)],
            text=True, capture_output=True, env=env, input="piped-token\n", timeout=120,
        )
        for result in (noninteractive, piped):
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("未读到授权令牌", result.stderr)
            self.assertNotIn("piped-token", result.stdout + result.stderr)
        self.assertFalse((self.skill / "config.local.json").exists())
        self.assertEqual(self.auth_calls(), 0)

    @unittest.skipIf(os.name == "nt", "pty-driven prompt test is POSIX only")
    def test_installer_hidden_prompt_writes_local_config(self) -> None:
        import pty
        import select

        (self.skill / "config.json").write_text(json.dumps({"backend_url": "fixture", "backend_token": ""}), encoding="utf-8")
        master, slave = pty.openpty()
        process = subprocess.Popen(
            [PWSH, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(self.skill / "scripts" / "install_for_user.ps1"), str(self.runner)],
            stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(self.env, LC_AMAZON_INSTALL_SETUP_ONLY="1", TERM="dumb"),
        )
        os.close(slave)
        chunks: List[bytes] = []
        reader = threading.Thread(target=lambda: chunks.extend(iter(lambda: process.stdout.read1(4096), b"")), daemon=True)
        reader.start()
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and "显示".encode("utf-8") not in b"".join(chunks) and process.poll() is None:
                select.select([master], [], [], 0.1)
                time.sleep(0.1)
            os.write(master, b"recipient-token\r")
            process.wait(timeout=120)
            reader.join(timeout=10)
            err = process.stderr.read()
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()
        text = b"".join(chunks).decode("utf-8", "replace") + err.decode("utf-8", "replace")
        self.assertEqual(process.returncode, 0, text)
        self.assertNotIn("recipient-token", text)
        self.assertIn("安装完成", text)
        for config in (self.skill / "config.local.json", self.runner / "config.local.json"):
            self.assertEqual(json.loads(config.read_text(encoding="utf-8"))["backend_token"], "recipient-token")
        self.assertEqual(json.loads((self.skill / "config.json").read_text(encoding="utf-8"))["backend_token"], "")
        self.assertEqual(self.auth_calls(), 1)
        self.assertEqual([p.name for p in self.skill.glob(".config.local.*")], [])


# ---------------------------------------------------------------------------
# I18: packaging
# ---------------------------------------------------------------------------


class PackageSkillTests(unittest.TestCase):
    def make_skill(self, root: Path, token: str = "") -> Path:
        skill = root / "lc-amazon-data-crawl"
        files = {
            "SKILL.md": "x",
            "config.json": json.dumps({"backend_url": "u", "backend_token": token}),
            "config.local.json": json.dumps({"backend_token": "local-secret"}),
            "scripts/a.py": "print(1)\n",
            "scripts/__pycache__/a.cpython-312.pyc": "x",
            "scripts/b.pyc": "x",
            "assets/config/doubao_embedding_vision.example.json": json.dumps({"api_key": ""}),
            "__MACOSX/scripts/._a.py": "x",
            "scripts/._a.py": "x",
            ".DS_Store": "x",
            ".git/HEAD": "x",
            "outputs/job/run_summary.json": "{}",
            "chrome_profiles/p/Default/Cookies": "x",
            "tools/bin/lc-auth-check-linux-amd64": "bin",
            "old.zip": "x",
        }
        for relative, content in files.items():
            path = skill / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        (skill / "tools/bin/lc-auth-check-linux-amd64").chmod(0o755)
        return skill

    def run_main(self, *args: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = package_skill.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_builds_clean_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill = self.make_skill(Path(temp_dir))
            output = Path(temp_dir) / "dist" / "skill.zip"
            code, _out, _err = self.run_main("--skill-dir", str(skill), "--output", str(output))
            self.assertEqual(code, 0)
            with zipfile.ZipFile(output) as archive:
                names = sorted(archive.namelist())
                mode = archive.getinfo("lc-amazon-data-crawl/tools/bin/lc-auth-check-linux-amd64").external_attr >> 16
        self.assertEqual(names, sorted(f"lc-amazon-data-crawl/{n}" for n in (
            "SKILL.md", "config.json", "scripts/a.py", "assets/config/doubao_embedding_vision.example.json",
            "tools/bin/lc-auth-check-linux-amd64")))
        if os.name != "nt":
            self.assertTrue(mode & stat.S_IXUSR)

    def test_refuses_token_without_printing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill = self.make_skill(Path(temp_dir), token="super-secret-token")
            output = Path(temp_dir) / "skill.zip"
            code, out, err = self.run_main("--skill-dir", str(skill), "--output", str(output))
            self.assertEqual(code, 1)
            self.assertIn("token present", err)
            self.assertNotIn("super-secret-token", out + err)
            self.assertFalse(output.exists())
            code, out, err = self.run_main("--skill-dir", str(skill), "--output", str(output), "--allow-token")
            self.assertEqual(code, 0)
            self.assertNotIn("super-secret-token", out + err)
            self.assertTrue(output.exists())

    def test_refuses_populated_doubao_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill = self.make_skill(Path(temp_dir))
            (skill / "assets/config/doubao_same_product_mini.json").write_text(json.dumps({"api_key": "ark-secret"}), encoding="utf-8")
            code, out, err = self.run_main("--skill-dir", str(skill), "--output", str(Path(temp_dir) / "s.zip"))
            self.assertEqual(code, 1)
            self.assertIn("api_key present", err)
            self.assertNotIn("ark-secret", out + err)

    def test_real_skill_tree_packages_without_local_artifacts(self) -> None:
        files = [p.as_posix() for p in package_skill.iter_package_files(SKILL_ROOT)]
        self.assertIn("scripts/package_skill.py", files)
        self.assertIn("scripts/runner/lc-amazon-data-crawl.cmd", files)
        for name in files:
            self.assertFalse(name.endswith((".pyc", ".DS_Store")), name)
            self.assertNotIn("__pycache__", name)
            self.assertNotIn("config.local.json", name)
            self.assertFalse(name.startswith((".git/", ".claude/", "outputs/", "chrome_profiles/")), name)


if __name__ == "__main__":
    unittest.main()

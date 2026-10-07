#!/usr/bin/env python3
"""Start a user-owned CDP Chrome and auto-load SellerSprite.

The process is intentionally detached from the runner. Crawlers should connect
with browser_mode=attach/reuse so their shutdown only closes crawler-owned tabs.

Exit codes follow run_outcome: 0 ready, 30 needs_human (browser / profile /
extension setup the user must fix), 40 config_error.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse
from urllib.request import urlopen

from selenium.common.exceptions import WebDriverException

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from browser_runtime import DEFAULT_CHROME_USER_DATA_DIR, CdpWebDriver, pid_is_running
from run_outcome import EXIT_CONFIG_ERROR, EXIT_NEEDS_HUMAN


ROOT_DIR = Path(__file__).resolve().parent.parent
SELLERSPRITE_EXTENSION_ID = "lnbmbgocenenhhhdojdielgnmeflbnfb"
VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+\.\d+)(?!\d)")
IS_WINDOWS = os.name == "nt"
# Branded Google Chrome ignores --load-extension from this major version on.
BRANDED_LOAD_EXTENSION_REMOVED_MAJOR = 137
# Written into the dedicated profile after this tool launched Chrome, so a later
# reuse can tell "launched by us with the extension" without opening any tab.
LAUNCH_MARKER_NAME = "lc-amazon-data-crawl-launch.json"

INSTALL_BROWSER_HINT = (
    "请在 runner 目录运行一次 `./lc-amazon-data-crawl.sh install-browser`"
    "（Windows：`.\\lc-amazon-data-crawl.cmd install-browser`），"
    "它会执行 `python -m playwright install chromium` 下载可自动加载扩展的 Chromium；"
    "或者自行安装 Chrome for Testing（https://googlechromelabs.github.io/chrome-for-testing/），"
    "再把配置里的 chrome_binary 改成它的可执行文件路径。"
)


class BrowserStartError(RuntimeError):
    def __init__(self, message: str, exit_code: int = EXIT_NEEDS_HUMAN) -> None:
        super().__init__(message)
        self.exit_code = int(exit_code)


def load_config(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BrowserStartError(f"没有找到配置文件：{path}", EXIT_CONFIG_ERROR) from exc
    except json.JSONDecodeError as exc:
        raise BrowserStartError(f"配置文件不是有效 JSON：{path}", EXIT_CONFIG_ERROR) from exc
    if not isinstance(data, dict):
        raise BrowserStartError("配置文件根节点必须是 JSON 对象。", EXIT_CONFIG_ERROR)
    return data


def resolve_config_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


def default_chrome_roots() -> List[Path]:
    roots = [
        Path.home() / "Library/Application Support/Google/Chrome",
        Path.home() / "Library/Application Support/Google/Chrome Beta",
        Path.home() / "Library/Application Support/Google/Chrome Dev",
        Path.home() / "Library/Application Support/Chromium",
        Path.home() / ".config/google-chrome",
        Path.home() / ".config/chromium",
    ]
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        roots.extend(
            [
                Path(local_app_data) / "Google/Chrome/User Data",
                Path(local_app_data) / "Chromium/User Data",
            ]
        )
    return roots


def version_key(value: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for part in str(value or "").split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def playwright_cache_roots() -> List[Path]:
    """Every location `python -m playwright install chromium` may write to."""
    roots: List[Path] = []
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if custom and custom != "0":
        roots.append(Path(custom).expanduser())
    roots.append(Path.home() / "Library/Caches/ms-playwright")  # macOS
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        roots.append(Path(xdg_cache) / "ms-playwright")  # Linux with XDG override
    roots.append(Path.home() / ".cache/ms-playwright")  # Linux
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        roots.append(Path(local_app_data) / "ms-playwright")  # Windows
    roots.append(Path.home() / "AppData/Local/ms-playwright")  # Windows fallback
    unique: List[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


PLAYWRIGHT_CHROMIUM_PATTERNS = (
    "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    "chromium-*/chrome-linux*/chrome",
    "chromium-*/chrome-win*/chrome.exe",
)

LOCAL_CFT_PATTERNS = (
    "*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "*/chrome-linux*/chrome",
    "chrome-linux*/chrome",
    "*/chrome-win*/chrome.exe",
    "chrome-win*/chrome.exe",
)


def default_chrome_for_testing_candidates() -> List[Path]:
    candidates: List[Path] = [
        Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        Path.home()
        / "Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    ]
    glob_specs: List[Tuple[Path, str]] = [
        (ROOT_DIR / "tools/chrome-for-testing", pattern) for pattern in LOCAL_CFT_PATTERNS
    ]
    for root in playwright_cache_roots():
        glob_specs.extend((root, pattern) for pattern in PLAYWRIGHT_CHROMIUM_PATTERNS)
    for root, pattern in glob_specs:
        if root.is_dir():
            candidates.extend(root.glob(pattern))
    return candidates


def _sibling_version_key(path: Path) -> Tuple[int, ...]:
    """Windows builds keep a `<version>` folder or `<version>.manifest` beside chrome.exe."""
    best: Tuple[int, ...] = ()
    try:
        siblings = list(path.parent.iterdir())
    except OSError:
        return best
    for sibling in siblings:
        match = VERSION_RE.search(sibling.name)
        if match:
            best = max(best, version_key(match.group(1)))
    return best


def chrome_binary_version_key(path: Path) -> Tuple[int, ...]:
    path_versions = VERSION_RE.findall(str(path))
    if path_versions:
        return version_key(path_versions[-1])
    if IS_WINDOWS:
        # `chrome.exe --version` prints nothing on Windows and may open a
        # browser window, so never execute it there.
        return _sibling_version_key(path)
    try:
        result = subprocess.run(
            [str(path), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    match = VERSION_RE.search(f"{result.stdout} {result.stderr}")
    return version_key(match.group(1)) if match else ()


def discover_chrome_for_testing(
    candidates: Optional[Sequence[Path]] = None,
) -> Optional[Path]:
    resolved: List[Tuple[Tuple[int, ...], float, Path]] = []
    seen = set()
    for candidate in candidates or default_chrome_for_testing_candidates():
        path = candidate.expanduser().resolve()
        if path in seen or not path.is_file() or not os.access(path, os.X_OK):
            continue
        seen.add(path)
        resolved.append(
            (
                chrome_binary_version_key(path),
                path.stat().st_mtime,
                path,
            )
        )
    if not resolved:
        return None
    resolved.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return resolved[0][2]


def iter_sellersprite_manifests(search_roots: Iterable[Path]) -> Iterable[Path]:
    for root in search_roots:
        if not root.is_dir():
            continue
        yield from root.glob(
            f"*/Extensions/{SELLERSPRITE_EXTENSION_ID}/*/manifest.json"
        )


def discover_sellersprite_extension(
    search_roots: Optional[Sequence[Path]] = None,
) -> Optional[Path]:
    candidates: List[Tuple[Tuple[int, ...], float, Path]] = []
    for manifest_path in iter_sellersprite_manifests(
        search_roots or default_chrome_roots()
    ):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict):
            continue
        if not str(manifest.get("version") or "").strip():
            continue
        extension_dir = manifest_path.parent.resolve()
        candidates.append(
            (
                version_key(str(manifest.get("version") or "")),
                manifest_path.stat().st_mtime,
                extension_dir,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def extension_configured(config: Dict[str, Any]) -> bool:
    return bool(str(config.get("extension_path") or "").strip())


def extension_required(config: Dict[str, Any]) -> bool:
    return extension_configured(config) and bool(config.get("sellersprite_required", True))


def resolve_extension_path(config: Dict[str, Any]) -> Optional[Path]:
    raw_value = str(config.get("extension_path") or "").strip()
    if raw_value.lower() == "auto":
        return discover_sellersprite_extension()
    if not raw_value:
        return None
    path = resolve_config_path(raw_value)
    if not path.is_dir():
        raise BrowserStartError(f"没有找到卖家精灵扩展目录：{path}", EXIT_CONFIG_ERROR)
    return path


def _extension_id_from_bytes(data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()[:32]
    return "".join(chr(ord("a") + int(char, 16)) for char in digest)


def extension_id_from_key(public_key: str) -> Optional[str]:
    try:
        raw = base64.b64decode(str(public_key or "").strip(), validate=False)
    except (binascii.Error, ValueError):
        return None
    return _extension_id_from_bytes(raw) if raw else None


def extension_id_from_path(path: Path, windows: Optional[bool] = None) -> str:
    """ID Chrome assigns to an unpacked extension without a manifest key."""
    windows = IS_WINDOWS if windows is None else windows
    text = str(path)
    if windows:
        if len(text) >= 2 and text[1] == ":":
            text = text[0].upper() + text[1:]
        return _extension_id_from_bytes(text.encode("utf-16-le"))
    return _extension_id_from_bytes(os.fsencode(text))


def candidate_extension_ids(extension_dir: Optional[Path]) -> Set[str]:
    ids = {SELLERSPRITE_EXTENSION_ID}
    if extension_dir is None:
        return ids
    try:
        manifest = json.loads((extension_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    if isinstance(manifest, dict) and manifest.get("key"):
        key_id = extension_id_from_key(str(manifest.get("key")))
        if key_id:
            ids.add(key_id)
    ids.add(extension_id_from_path(extension_dir))
    return ids


def resolve_chrome_binary(config: Dict[str, Any]) -> Path:
    raw_value = str(config.get("chrome_binary") or "auto").strip() or "auto"
    if raw_value.lower() == "auto":
        detected = discover_chrome_for_testing()
        if detected is None:
            raise BrowserStartError(
                "未检测到 Chrome for Testing / Chromium（chrome_binary: auto）。" + INSTALL_BROWSER_HINT
            )
        return detected
    path = resolve_config_path(raw_value)
    if not path.is_file():
        raise BrowserStartError(f"没有找到 Chrome：{path}", EXIT_CONFIG_ERROR)
    return path


_BRANDED_MAC_NAMES = {
    "google chrome",
    "google chrome beta",
    "google chrome dev",
    "google chrome canary",
}


def _branded_by_path(text: str) -> Optional[bool]:
    normalized = text.replace("\\", "/").lower()
    name = normalized.rstrip("/").rsplit("/", 1)[-1]
    if "for testing" in normalized or "ms-playwright" in normalized or "chromium" in normalized:
        return False
    if name in _BRANDED_MAC_NAMES:  # macOS app binary
        return True
    if name.startswith("google-chrome") or "/opt/google/chrome" in normalized:  # Linux
        return True
    if name == "chrome.exe" and re.search(r"/google/chrome[^/]*/application/", normalized):  # Windows
        return True
    if name == "chrome.exe" and re.search(r"/chrome-win\d*/", normalized):
        return False
    return None


def is_branded_chrome(path: Path) -> bool:
    """True for official Google Chrome (not Chrome for Testing / Chromium)."""
    verdict = _branded_by_path(str(path))
    if verdict is not None:
        return verdict
    try:
        resolved = Path(path).resolve()
    except OSError:
        resolved = Path(path)
    if str(resolved) != str(path):
        verdict = _branded_by_path(str(resolved))
        if verdict is not None:
            return verdict
    if IS_WINDOWS:
        return False
    try:
        result = subprocess.run(
            [str(path), "--version"], check=False, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    output = f"{result.stdout} {result.stderr}"
    return bool(re.search(r"Google Chrome(?! for Testing)\s+\d", output))


def branded_chrome_blocks_extension(path: Path) -> bool:
    if not is_branded_chrome(path):
        return False
    version = chrome_binary_version_key(path)
    if version and version[0] < BRANDED_LOAD_EXTENSION_REMOVED_MAJOR:
        return False
    return True


def debugger_ready(address: str, timeout: float = 2.0) -> bool:
    endpoint = f"http://{address.strip().rstrip('/')}/json/version"
    try:
        with urlopen(endpoint, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def fetch_debugger_json(address: str, path: str, timeout: float = 2.0) -> Any:
    endpoint = f"http://{address.strip().rstrip('/')}{path}"
    with urlopen(endpoint, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def browser_version_info(address: str) -> Optional[Dict[str, Any]]:
    try:
        payload = fetch_debugger_json(address, "/json/version")
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def websocket_path(version_info: Optional[Dict[str, Any]]) -> str:
    if not version_info:
        return ""
    return urlparse(str(version_info.get("webSocketDebuggerUrl") or "")).path


def wait_for_debugger(address: str, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if debugger_ready(address):
            return True
        time.sleep(0.5)
    return False


def wait_for_launched_debugger(
    address: str,
    process: Any,
    timeout: float = 90.0,
    poll_seconds: float = 0.5,
) -> str:
    """Return "ready", "exited" (Chrome handed off to another instance) or "timeout"."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if debugger_ready(address):
            return "ready"
        if process is not None and process.poll() is not None:
            # A second Chrome on an already-open profile forwards its URL to
            # the running instance and exits; that instance has no debug port.
            time.sleep(min(1.0, poll_seconds * 2))
            return "ready" if debugger_ready(address) else "exited"
        time.sleep(poll_seconds)
    return "timeout"


def debugger_port(address: str) -> int:
    try:
        return int(address.rsplit(":", 1)[-1])
    except (TypeError, ValueError) as exc:
        raise BrowserStartError(
            "debugger_address 需要形如 127.0.0.1:9222。", EXIT_CONFIG_ERROR
        ) from exc


def debugger_host(address: str) -> str:
    host = address.strip()
    for prefix in ("http://", "https://", "ws://", "wss://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.rsplit(":", 1)[0].strip("[]")
    return host or "127.0.0.1"


def port_accepts_connections(address: str, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((debugger_host(address), debugger_port(address)), timeout=timeout):
            return True
    except OSError:
        return False


def read_devtools_active_port(user_data_dir: Path) -> Optional[Tuple[int, str]]:
    """Chrome writes `<port>\\n/devtools/browser/<uuid>` here on every debug launch."""
    try:
        lines = (user_data_dir / "DevToolsActivePort").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return None
    if len(lines) < 2:
        return None
    try:
        port = int(lines[0].strip())
    except ValueError:
        return None
    return port, lines[1].strip()


def profile_in_use(user_data_dir: Path) -> bool:
    """True when a live Chrome already holds this user-data-dir."""
    if IS_WINDOWS:
        lock_path = user_data_dir / "lockfile"
        if not lock_path.exists():
            return False
        try:
            # Chrome holds it with FILE_SHARE_READ only; a write open fails.
            handle = os.open(str(lock_path), os.O_RDWR)
        except PermissionError:
            return True
        except OSError:
            return False
        os.close(handle)
        return False
    try:
        target = os.readlink(str(user_data_dir / "SingletonLock"))
    except OSError:
        return False
    host, _, pid_text = target.rpartition("-")
    try:
        pid = int(pid_text)
    except ValueError:
        return False
    if host and host != socket.gethostname():
        return False
    return pid_is_running(pid)


def read_launch_marker(user_data_dir: Path) -> Dict[str, Any]:
    try:
        payload = json.loads((user_data_dir / LAUNCH_MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_launch_marker(
    user_data_dir: Path, browser_ws_path: str, extension_path: Optional[Path]
) -> None:
    payload = {
        "browser_ws_path": browser_ws_path,
        "extension_path": str(extension_path) if extension_path else "",
        "launched_at": dt.datetime.now().replace(microsecond=0).isoformat(),
    }
    try:
        fd, temporary = tempfile.mkstemp(prefix=".lc-launch.", dir=str(user_data_dir))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, user_data_dir / LAUNCH_MARKER_NAME)
    except OSError:
        pass
    finally:
        if os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def loaded_extension_ids(address: str) -> Set[str]:
    try:
        targets = fetch_debugger_json(address, "/json/list")
    except Exception:
        return set()
    ids: Set[str] = set()
    for target in targets if isinstance(targets, list) else []:
        if not isinstance(target, dict):
            continue
        parsed = urlparse(str(target.get("url") or ""))
        if parsed.scheme == "chrome-extension" and parsed.netloc:
            ids.add(parsed.netloc)
    return ids


def verify_profile(
    address: str,
    user_data_dir: Path,
    profile_directory: str,
    page_timeout: int,
) -> None:
    driver: Optional[CdpWebDriver] = None
    try:
        driver = CdpWebDriver(
            debugger_address=address,
            page_timeout=page_timeout,
            expected_user_data_dir=user_data_dir,
            profile_directory=profile_directory,
            owns_browser=False,
        )
    except WebDriverException as exc:
        raise BrowserStartError(str(getattr(exc, "msg", "") or exc)) from exc
    finally:
        if driver is not None:
            driver.quit()


def foreign_browser_message(
    address: str,
    user_data_dir: Path,
    version_info: Optional[Dict[str, Any]],
    active: Optional[Tuple[int, str]],
) -> str:
    browser = str((version_info or {}).get("Browser") or "未知版本")
    message = (
        f"调试端口 {address} 已被另一个 Chrome（{browser}）占用，"
        f"它用的不是专用 Profile（{user_data_dir}）。"
        "请关闭那个带调试端口启动的 Chrome 窗口后重新运行同一命令；"
        "如果它必须保留，请在配置里把 debugger_address 改成空闲端口（例如 127.0.0.1:9223）。"
    )
    if active is not None:
        other = f"{debugger_host(address)}:{active[0]}"
        if active[0] != debugger_port(address) and websocket_path(browser_version_info(other)) == active[1]:
            message += f"专用 Profile 当前正运行在 {other}，也可以把 debugger_address 改成 {other}。"
    return message


def ensure_running_profile(
    address: str,
    user_data_dir: Path,
    profile_directory: str,
    page_timeout: int,
    version_info: Optional[Dict[str, Any]],
) -> None:
    """Fast check without opening tabs; fall back to chrome://version only when unsure."""
    active = read_devtools_active_port(user_data_dir)
    ws_path = websocket_path(version_info)
    if active is not None and ws_path:
        if active[1] == ws_path:
            return
        raise BrowserStartError(
            foreign_browser_message(address, user_data_dir, version_info, active)
        )
    # No DevToolsActivePort in the dedicated profile: confirm via chrome://version.
    verify_profile(address, user_data_dir, profile_directory, page_timeout)


def ensure_running_extension(
    config: Dict[str, Any],
    address: str,
    user_data_dir: Path,
    version_info: Optional[Dict[str, Any]],
) -> None:
    if not extension_configured(config):
        return
    required = extension_required(config)
    extension_dir = resolve_extension_path(config)
    if extension_dir is None:
        if required:
            raise BrowserStartError(
                "未检测到卖家精灵扩展；请先在任一 Chrome Profile 安装卖家精灵后重试。"
            )
        return
    marker = read_launch_marker(user_data_dir)
    ws_path = websocket_path(version_info)
    if ws_path and marker.get("browser_ws_path") == ws_path and marker.get("extension_path"):
        return  # this exact Chrome process was launched by us with --load-extension
    if candidate_extension_ids(extension_dir) & loaded_extension_ids(address):
        return
    message = (
        "专用 Chrome 已在运行，但没有加载卖家精灵扩展（extension_path 只在本工具启动专用 Chrome 时生效）。"
        f"请只关闭这个专用 Chrome 窗口（Profile：{user_data_dir}），不要关闭你日常使用的 Chrome，"
        "然后重新运行同一命令，runner 会带着扩展重新启动它。"
    )
    if required:
        raise BrowserStartError(message)
    print(f"提示：{message}", file=sys.stderr)


def launch_popen_kwargs() -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if IS_WINDOWS:
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
        )
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    return kwargs


def browser_settings(config: Dict[str, Any]) -> Tuple[Path, str, str, int]:
    user_data_dir = resolve_config_path(
        str(config.get("chrome_user_data_dir") or DEFAULT_CHROME_USER_DATA_DIR)
    )
    profile_directory = (
        str(config.get("chrome_profile_directory") or "Default").strip()
        or "Default"
    )
    address = (
        str(config.get("debugger_address") or "127.0.0.1:9222").strip()
        or "127.0.0.1:9222"
    )
    try:
        page_timeout = max(int(config.get("page_timeout") or 90), 1)
    except (TypeError, ValueError) as exc:
        raise BrowserStartError("page_timeout 必须是正整数。", EXIT_CONFIG_ERROR) from exc
    return user_data_dir, profile_directory, address, page_timeout


def launch_with_diagnostics(command, user_data_dir):
    stderr_path = user_data_dir / "lc-crawler-browser-stderr.log"
    fd = os.open(str(stderr_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stderr_log:
        if not IS_WINDOWS:
            os.chmod(stderr_path, 0o600)
        kwargs = launch_popen_kwargs()
        kwargs["stderr"] = stderr_log
        return subprocess.Popen(command, **kwargs)


def start_browser(config: Dict[str, Any]) -> None:
    if str(config.get("browser_backend") or "cdp").strip().lower() != "cdp":
        raise BrowserStartError("cdp-browser-start 只支持 browser_backend=cdp。", EXIT_CONFIG_ERROR)

    user_data_dir, profile_directory, address, page_timeout = browser_settings(config)
    port = debugger_port(address)

    version_info = browser_version_info(address)
    if version_info is not None:
        ensure_running_profile(address, user_data_dir, profile_directory, page_timeout, version_info)
        ensure_running_extension(config, address, user_data_dir, version_info)
        print("CDP 浏览器已在运行，Profile 校验通过；runner 可直接 reuse。")
        return

    chrome_binary = resolve_chrome_binary(config)
    extension_path = resolve_extension_path(config)
    extension_auto = (
        str(config.get("extension_path") or "").strip().lower() == "auto"
    )
    if (
        bool(config.get("sellersprite_required", True))
        and extension_auto
        and extension_path is None
    ):
        raise BrowserStartError(
            "未检测到卖家精灵扩展；请先在任一 Chrome Profile 安装后重试。"
        )
    if extension_path is not None and branded_chrome_blocks_extension(chrome_binary):
        raise BrowserStartError(
            f"chrome_binary 指向正式版 Google Chrome（{chrome_binary}）；正式版 Chrome 137+ "
            "不支持命令行自动加载扩展。请把 chrome_binary 改为 \"auto\" 并运行 install-browser，"
            "或改用 Chrome for Testing / Chromium；如果坚持用正式版 Chrome，请在专用 Profile 里"
            "手动加载卖家精灵后把 extension_path 设为 \"\"。"
        )
    if port_accepts_connections(address):
        raise BrowserStartError(
            f"端口 {address} 已被其他程序占用，但它不是可用的 Chrome 调试端口。"
            "请关闭占用该端口的程序，或在配置里把 debugger_address 改成空闲端口（例如 127.0.0.1:9223）。"
        )
    if profile_in_use(user_data_dir):
        raise BrowserStartError(
            f"专用 Profile（{user_data_dir}）已在一个没有开启调试端口的 Chrome 里打开。"
            "请只关闭这个专用 Chrome 窗口（不要关闭你日常使用的 Chrome），然后重新运行同一命令。"
        )

    user_data_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(chrome_binary),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={profile_directory}",
        "--no-first-run",
        "--enable-logging=stderr",
        "--new-window",
        "about:blank",
    ]
    if extension_path is not None:
        command.insert(-2, f"--load-extension={extension_path}")

    try:
        # Keep browser errors locally; DEVNULL erased evidence of renderer/GPU
        # failures. Parent closes its handle; the detached child keeps its copy.
        process = launch_with_diagnostics(command, user_data_dir)
    except OSError as exc:
        raise BrowserStartError(f"无法启动 Chrome（{chrome_binary}）：{exc}") from exc
    state = wait_for_launched_debugger(address, process)
    if state == "exited":
        raise BrowserStartError(
            f"Chrome 启动后立即退出，调试端口 {address} 没有打开。通常是专用 Profile（{user_data_dir}）"
            "已在另一个没有调试端口的 Chrome 窗口里打开。请只关闭这个专用 Chrome 窗口后重新运行同一命令。"
        )
    if state != "ready":
        raise BrowserStartError(
            f"专用 Chrome 已启动，但 CDP 调试端口 {address} 未在 90 秒内就绪。"
            "请关闭这个专用 Chrome 窗口后重新运行同一命令；如仍失败，把 debugger_address 改成空闲端口。"
        )
    version_info = browser_version_info(address)
    ws_path = websocket_path(version_info)
    # Chrome may answer /json/version a moment before DevToolsActivePort is rewritten.
    settle_deadline = time.monotonic() + 5.0
    while ws_path and time.monotonic() < settle_deadline:
        active = read_devtools_active_port(user_data_dir)
        if active is not None and active[1] == ws_path:
            break
        time.sleep(0.2)
    write_launch_marker(user_data_dir, ws_path, extension_path)
    ensure_running_profile(address, user_data_dir, profile_directory, page_timeout, version_info)
    if extension_path is None:
        print("专用 CDP Chrome 已启动；runner 可直接 reuse。")
    else:
        print(
            "专用 CDP Chrome 已启动，并已自动加载检测到的卖家精灵扩展；"
            "runner 可直接 reuse。"
        )


def should_auto_start(config: Dict[str, Any]) -> bool:
    backend = str(config.get("browser_backend") or "cdp").strip().lower()
    mode = str(config.get("browser_mode") or "launch").strip().lower()
    return backend == "cdp" and mode == "reuse"


def diagnostics() -> Dict[str, Any]:
    browser = discover_chrome_for_testing()
    extension = discover_sellersprite_extension()
    return {
        "chrome_for_testing": "ready" if browser else "missing",
        "chrome_for_testing_version": (
            ".".join(str(part) for part in chrome_binary_version_key(browser))
            if browser
            else ""
        ),
        "sellersprite_extension": "ready" if extension else "missing",
        "sellersprite_extension_version": extension.name if extension else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="启动由用户持有、供 runner reuse 的专用 CDP Chrome。"
    )
    parser.add_argument("--config", help="抓取任务配置文件")
    parser.add_argument(
        "--if-needed",
        action="store_true",
        help="仅在配置为 cdp/reuse 时启动；其他后端或模式直接返回。",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="只检查 Chrome for Testing 与卖家精灵扩展，不启动浏览器。",
    )
    args = parser.parse_args()
    if args.diagnose:
        report = diagnostics()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if report["chrome_for_testing"] != "ready":
            print("缺少 Chrome for Testing / Chromium：" + INSTALL_BROWSER_HINT, file=sys.stderr)
        return 0
    if not args.config:
        parser.error("--config 是必需参数。")
    config_path = resolve_config_path(args.config)
    try:
        config = load_config(config_path)
        if args.if_needed and not should_auto_start(config):
            return 0
        from safety_control import LocalSafetyController, SafetyPausedError
        safety = LocalSafetyController()
        try:
            safety.acquire()
            start_browser(config)
        except SafetyPausedError as exc:
            print(str(exc), file=sys.stderr)
            return 50
        finally:
            safety.release()
    except BrowserStartError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

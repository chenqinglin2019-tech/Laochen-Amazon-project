#!/usr/bin/env python3
"""Start a user-owned CDP Chrome and auto-load SellerSprite.

The process is intentionally detached from the runner. Crawlers should connect
with browser_mode=attach/reuse so their shutdown only closes crawler-owned tabs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.request import urlopen

from selenium.common.exceptions import WebDriverException

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from browser_runtime import CdpWebDriver


ROOT_DIR = Path(__file__).resolve().parent.parent
SELLERSPRITE_EXTENSION_ID = "lnbmbgocenenhhhdojdielgnmeflbnfb"
VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+\.\d+)(?!\d)")


class BrowserStartError(RuntimeError):
    pass


def load_config(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BrowserStartError(f"没有找到配置文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise BrowserStartError(f"配置文件不是有效 JSON：{path}") from exc
    if not isinstance(data, dict):
        raise BrowserStartError("配置文件根节点必须是 JSON 对象。")
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


def default_chrome_for_testing_candidates() -> List[Path]:
    candidates: List[Path] = [
        Path("/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        Path.home()
        / "Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    ]
    glob_specs = [
        (
            ROOT_DIR / "tools/chrome-for-testing",
            "*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        ),
        (
            Path.home() / "Library/Caches/ms-playwright",
            "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        ),
        (
            Path.home() / ".cache/ms-playwright",
            "chromium-*/chrome-linux*/chrome",
        ),
    ]
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        glob_specs.append(
            (
                Path(local_app_data) / "ms-playwright",
                "chromium-*/chrome-win*/chrome.exe",
            )
        )
    for root, pattern in glob_specs:
        if root.is_dir():
            candidates.extend(root.glob(pattern))
    return candidates


def chrome_binary_version_key(path: Path) -> Tuple[int, ...]:
    path_versions = VERSION_RE.findall(str(path))
    if path_versions:
        return version_key(path_versions[-1])
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


def resolve_extension_path(config: Dict[str, Any]) -> Optional[Path]:
    raw_value = str(config.get("extension_path") or "").strip()
    if raw_value.lower() == "auto":
        return discover_sellersprite_extension()
    if not raw_value:
        return None
    path = resolve_config_path(raw_value)
    if not path.is_dir():
        raise BrowserStartError(f"没有找到卖家精灵扩展目录：{path}")
    return path


def resolve_chrome_binary(config: Dict[str, Any]) -> Path:
    raw_value = str(config.get("chrome_binary") or "auto").strip() or "auto"
    if raw_value.lower() == "auto":
        detected = discover_chrome_for_testing()
        if detected is None:
            raise BrowserStartError(
                "未检测到 Chrome for Testing。请先执行 "
                "./lc-amazon-data-crawl.sh install。"
            )
        return detected
    path = resolve_config_path(raw_value)
    if not path.is_file():
        raise BrowserStartError(f"没有找到 Chrome：{path}")
    return path


def debugger_ready(address: str, timeout: float = 2.0) -> bool:
    endpoint = f"http://{address.strip().rstrip('/')}/json/version"
    try:
        with urlopen(endpoint, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for_debugger(address: str, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if debugger_ready(address):
            return True
        time.sleep(0.5)
    return False


def debugger_port(address: str) -> int:
    try:
        return int(address.rsplit(":", 1)[-1])
    except (TypeError, ValueError) as exc:
        raise BrowserStartError(
            "debugger_address 需要形如 127.0.0.1:9222。"
        ) from exc


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
        raise BrowserStartError(str(exc)) from exc
    finally:
        if driver is not None:
            driver.quit()


def start_browser(config: Dict[str, Any]) -> None:
    if str(config.get("browser_backend") or "cdp").strip().lower() != "cdp":
        raise BrowserStartError("cdp-browser-start 只支持 browser_backend=cdp。")

    chrome_binary = resolve_chrome_binary(config)

    user_data_dir = resolve_config_path(
        str(
            config.get("chrome_user_data_dir")
            or "chrome_profiles/lc-amazon-data-crawl"
        )
    )
    profile_directory = (
        str(config.get("chrome_profile_directory") or "Default").strip()
        or "Default"
    )
    address = (
        str(config.get("debugger_address") or "127.0.0.1:9222").strip()
        or "127.0.0.1:9222"
    )
    page_timeout = max(int(config.get("page_timeout") or 90), 1)

    if debugger_ready(address):
        verify_profile(
            address, user_data_dir, profile_directory, page_timeout
        )
        print("CDP 浏览器已在运行，Profile 校验通过；runner 可直接 reuse。")
        return

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
    if extension_path is not None and chrome_binary.name == "Google Chrome":
        raise BrowserStartError(
            "正式版 Chrome 137+ 不支持命令行自动加载扩展；"
            "请把 chrome_binary 改为 Chrome for Testing 或 Chromium。"
        )

    user_data_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(chrome_binary),
        f"--remote-debugging-port={debugger_port(address)}",
        f"--user-data-dir={user_data_dir}",
        f"--profile-directory={profile_directory}",
        "--no-first-run",
        "--new-window",
        "about:blank",
    ]
    if extension_path is not None:
        command.insert(-2, f"--load-extension={extension_path}")

    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    if not wait_for_debugger(address):
        raise BrowserStartError(
            "专用 Chrome 已启动，但 CDP 调试端口未在 90 秒内就绪。"
        )
    verify_profile(address, user_data_dir, profile_directory, page_timeout)
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
        print(json.dumps(diagnostics(), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.config:
        parser.error("--config 是必需参数。")
    config_path = resolve_config_path(args.config)
    try:
        config = load_config(config_path)
        if args.if_needed and not should_auto_start(config):
            return 0
        start_browser(config)
    except BrowserStartError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

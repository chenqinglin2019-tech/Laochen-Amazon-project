from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _auth_binary() -> Path:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        os_name = "darwin"
        arch = "arm64" if machine in {"arm64", "aarch64"} else "amd64"
        suffix = ""
    elif system == "linux":
        os_name = "linux"
        arch = "amd64"
        suffix = ""
    elif system == "windows":
        os_name = "windows"
        arch = "amd64"
        suffix = ".exe"
    else:
        raise RuntimeError(f"unsupported platform for auth gate: {system}/{machine}")
    return _skill_root() / "tools" / "bin" / f"lc-auth-check-{os_name}-{arch}{suffix}"


def require_laochen_auth() -> None:
    if os.environ.get("LAOCHEN_AUTH_PASSED") == "1":
        return
    root = _skill_root()
    binary = _auth_binary()
    if not binary.exists():
        raise SystemExit("云端鉴权工具缺失，本轮不继续执行。")
    if platform.system().lower() == "darwin":
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(root / "tools" / "bin")], check=False)
    try:
        binary.chmod(binary.stat().st_mode | 0o111)
    except OSError:
        pass
    result = subprocess.run(
        [str(binary), "--config", str(root / "config.json")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("云端鉴权未通过，本轮不继续执行。")
    os.environ["LAOCHEN_AUTH_PASSED"] = "1"

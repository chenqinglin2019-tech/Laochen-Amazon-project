"""Short-lived record that the cloud authentication gate passed on this machine.

auth_gate.py writes it after a real pass; plan and deliver check it. It stores
no token or configuration content: only times, a host fingerprint and a salted
fingerprint of config.json, so changing the token or machine requires a new pass.
Standard library only.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import socket
import tempfile
import time
from pathlib import Path

from lc_paths import cache_home

SCHEMA = "LC-AUTH-PASS/1"
TTL_SECONDS = 12 * 3600
TEST_BYPASS_ENV = "LC_SKIP_AUTH_PASS_FOR_TESTS"
MISSING_MESSAGE = ("AUTH_PASS_REQUIRED: 请先从 skill 根目录运行云端鉴权 `python scripts/auth_gate.py`"
                   "（Windows 可用 `py -3 scripts\\auth_gate.py`），通过后 12 小时内有效。")


def pass_path() -> Path:
    return cache_home() / "auth-pass.json"


def _host_fingerprint() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - some sandboxes have no user database
        user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    raw = "\0".join([socket.gethostname(), user, platform.system(), platform.machine()])
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:24]


def _config_fingerprint(skill_root: Path) -> str | None:
    path = Path(skill_root) / "config.json"
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(b"lc-auth-pass\0" + payload).hexdigest()[:32]


def write_pass(skill_root: Path, now: float | None = None) -> Path:
    now = time.time() if now is None else now
    record = {"schema": SCHEMA, "passed_at": now, "expires_at": now + TTL_SECONDS,
              "host": _host_fingerprint(), "config": _config_fingerprint(skill_root),
              "skill_root": hashlib.sha256(str(Path(skill_root).resolve()).encode("utf-8")).hexdigest()[:24]}
    path = pass_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".auth-pass.", delete=False)
    try:
        with handle:
            json.dump(record, handle)
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)
    return path


def check_pass(skill_root: Path, now: float | None = None) -> tuple[bool, str]:
    """Return (ok, reason). Never raises for missing/corrupt records."""
    if os.environ.get(TEST_BYPASS_ENV) == "1":
        return True, "test bypass"
    now = time.time() if now is None else now
    try:
        record = json.loads(pass_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, MISSING_MESSAGE
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return False, MISSING_MESSAGE
    expires = record.get("expires_at")
    if not isinstance(expires, (int, float)) or now >= expires or now + 60 < record.get("passed_at", now):
        return False, "AUTH_PASS_EXPIRED: 鉴权记录已过期，请重新运行 scripts/auth_gate.py。"
    if record.get("host") != _host_fingerprint():
        return False, "AUTH_PASS_OTHER_MACHINE: 鉴权记录不属于当前机器/用户，请重新运行 scripts/auth_gate.py。"
    if record.get("config") != _config_fingerprint(skill_root):
        return False, "AUTH_PASS_CONFIG_CHANGED: config.json 已变化，请重新运行 scripts/auth_gate.py。"
    return True, "ok"

"""Short-lived record that the cloud authentication gate passed on this machine.

auth_gate.py writes it after a real pass; plan and deliver check it. It stores
no token or configuration content: only times, host fingerprints and a salted
fingerprint of config.json, so changing the token or machine requires a new pass.
Standard library only.

V7.1 robustness (approved; the gate, binaries, endpoint, texts and 12 h TTL are unchanged):
- the host fingerprint uses a stable machine id (macOS IOPlatformUUID, Windows
  MachineGuid, Linux machine-id) instead of the hostname, which macOS changes when
  switching networks; the previous fingerprint is kept as `host_alt`, so existing
  passes stay valid until they expire;
- when the cache directory is not writable (host sandbox), the record goes to a
  private per-user temp directory, and plan/deliver look in both places and say
  where they looked.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from lc_paths import cache_home

SCHEMA = "LC-AUTH-PASS/1"
TTL_SECONDS = 12 * 3600
TEST_BYPASS_ENV = "LC_SKIP_AUTH_PASS_FOR_TESTS"
MISSING_MESSAGE = ("AUTH_PASS_REQUIRED: 请先从 skill 根目录运行云端鉴权 `python scripts/auth_gate.py`"
                   "（Windows 可用 `py -3 scripts\\auth_gate.py`），通过后 12 小时内有效。")
EXPIRED_MESSAGE = "AUTH_PASS_EXPIRED: 鉴权记录已过期，请重新运行 scripts/auth_gate.py。"
OTHER_MACHINE_MESSAGE = "AUTH_PASS_OTHER_MACHINE: 鉴权记录不属于当前机器/用户，请重新运行 scripts/auth_gate.py。"
CONFIG_MESSAGE = "AUTH_PASS_CONFIG_CHANGED: config.json 已变化，请重新运行 scripts/auth_gate.py。"


def pass_path() -> Path:
    return cache_home() / "auth-pass.json"


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - some sandboxes have no user database
        return os.environ.get("USER") or os.environ.get("USERNAME") or ""


def fallback_pass_path() -> Path:
    """Private per-user temp location, keyed to the cache home it stands in for."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", _user() or "user")
    scope = hashlib.sha256(str(cache_home()).encode("utf-8", "replace")).hexdigest()[:8]
    return Path(tempfile.gettempdir()).resolve() / f"lc-amazon-image-studio-{safe}-{scope}" / "auth-pass.json"


def _machine_id() -> str | None:
    """A stable per-machine identifier, or None when the platform hides it."""
    system = platform.system().lower()
    try:
        if system == "darwin":
            output = subprocess.run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5).stdout
            match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', output)
            return match.group(1) if match else None
        if system == "windows":
            import winreg
            access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                return str(value) or None
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                value = Path(path).read_text(encoding="utf-8").strip()
                if value:
                    return value
            except OSError:
                continue
    except Exception:  # noqa: BLE001 - fall back to the legacy fingerprint
        return None
    return None


def _digest(parts) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8", "replace")).hexdigest()[:24]


def _legacy_fingerprint() -> str:
    return _digest([socket.gethostname(), _user(), platform.system(), platform.machine()])


def _host_fingerprints() -> list[str]:
    """[primary, legacy]; primary is machine-id based when available."""
    legacy = _legacy_fingerprint()
    machine = _machine_id()
    primary = _digest(["machine-id:" + machine, _user(), platform.system(), platform.machine()]) if machine else legacy
    return [primary, legacy] if primary != legacy else [primary]


def _host_fingerprint() -> str:
    return _host_fingerprints()[0]


def _config_fingerprint(skill_root: Path) -> str | None:
    path = Path(skill_root) / "config.json"
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(b"lc-auth-pass\0" + payload).hexdigest()[:32]


def _write_record(path: Path, record: dict, private: bool) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, **({"mode": 0o700} if private else {}))
    if private and os.name == "posix":
        info = path.parent.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise PermissionError(f"Refusing a shared temp directory for the auth pass: {path.parent}")
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".auth-pass.", delete=False)
    try:
        with handle:
            json.dump(record, handle)
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)
    return path


def write_pass(skill_root: Path, now: float | None = None) -> Path:
    now = time.time() if now is None else now
    fingerprints = _host_fingerprints()
    record = {"schema": SCHEMA, "passed_at": now, "expires_at": now + TTL_SECONDS,
              "host": fingerprints[0], "host_alt": fingerprints[-1], "config": _config_fingerprint(skill_root),
              "skill_root": hashlib.sha256(str(Path(skill_root).resolve()).encode("utf-8")).hexdigest()[:24]}
    try:
        return _write_record(pass_path(), record, private=False)
    except OSError:
        # Cache not writable (e.g. a host sandbox): keep the pass in a private temp dir.
        return _write_record(fallback_pass_path(), record, private=True)


def _evaluate(path: Path, skill_root: Path, now: float, fingerprints: list[str]):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "不存在"
    except (OSError, ValueError) as exc:
        return None, f"无法读取:{type(exc).__name__}"
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return None, "格式无效"
    expires = record.get("expires_at")
    if not isinstance(expires, (int, float)) or now >= expires or now + 60 < record.get("passed_at", now):
        return EXPIRED_MESSAGE, "已过期"
    if not {record.get("host"), record.get("host_alt")} & set(fingerprints):
        return OTHER_MACHINE_MESSAGE, "其他机器"
    if record.get("config") != _config_fingerprint(skill_root):
        return CONFIG_MESSAGE, "config 已变化"
    return True, "有效"


def _cache_writable() -> bool:
    directory = cache_home()
    probe = directory if directory.exists() else next((p for p in directory.parents if p.exists()), directory)
    return os.access(probe, os.W_OK)


def check_pass(skill_root: Path, now: float | None = None) -> tuple[bool, str]:
    """Return (ok, reason). Never raises for missing/corrupt records."""
    if os.environ.get(TEST_BYPASS_ENV) == "1":
        return True, "test bypass"
    now = time.time() if now is None else now
    fingerprints = _host_fingerprints()
    findings, first_problem = [], None
    for path in (pass_path(), fallback_pass_path()):
        outcome, why = _evaluate(path, skill_root, now, fingerprints)
        if outcome is True:
            return True, "ok"
        findings.append(f"{path}（{why}）")
        if isinstance(outcome, str) and first_problem is None:
            first_problem = outcome
    line2 = "查找位置：" + "；".join(findings)
    if not _cache_writable():
        line2 += "；缓存目录不可写，已改用临时目录"
    return False, (first_problem or MISSING_MESSAGE) + "\n" + line2

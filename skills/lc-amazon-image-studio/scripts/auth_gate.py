#!/usr/bin/env python3
"""Prepare and run this Skill's existing account checker using only the stdlib."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import sys


SAFE_FAILURE = "云端鉴权未通过，本轮不继续执行。"
SAFE_REASONS = {
    "unsupported_platform": "当前系统或处理器架构没有可用的鉴权组件。",
    "auth_component_invalid": "鉴权组件缺失或校验失败。",
    "auth_component_permission_failed": "鉴权组件缺少执行权限且无法修复，请将 Skill 安装到当前用户可写的目录。",
    "auth_component_attributes_failed": "无法检查 macOS 隔离标记，请检查宿主对 Skill 目录和 /usr/bin/xattr 的访问权限。",
    "auth_component_quarantine_failed": "无法移除已校验鉴权组件的 macOS 隔离标记，请检查目录权限及宿主限制。",
    "auth_component_launch_failed": "鉴权组件无法启动，请检查系统兼容性或文件权限。",
    "configuration_error": "鉴权配置无效，请检查本 Skill 根目录的 config.json。",
    "missing_token": "未读取到可用 Token，请检查 config.json 中的 backend_token。",
    "auth_rejected": "账户鉴权未通过，请检查 Token、账号状态及可用余额。",
    "user_not_enabled": "账户未启用或账户状态不可用。",
    "rate_limited": "鉴权服务请求过于频繁，请稍后重试。",
    "service_unavailable": "鉴权连接或服务不可用，请检查宿主网络权限、DNS/TLS、代理及服务状态。",
    "service_timeout": "鉴权请求超时，请检查宿主网络权限和服务状态。",
    "service_endpoint_invalid": "鉴权服务地址或接口不可用。",
    "invalid_response": "鉴权服务返回异常。",
    "auth_failed": "账户校验未通过。",
}


def stop(reason: str) -> None:
    raise SystemExit(f"{SAFE_FAILURE}\n原因：{SAFE_REASONS.get(reason, SAFE_REASONS['auth_failed'])}")


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def auth_binary() -> Path:
    system, machine = platform.system().lower(), platform.machine().lower()
    if system == "darwin" and machine in {"arm64", "aarch64", "x86_64", "amd64"}:
        name = "lc-auth-check-darwin-" + ("arm64" if machine in {"arm64", "aarch64"} else "amd64")
    elif system == "linux" and machine in {"x86_64", "amd64"}:
        name = "lc-auth-check-linux-amd64"
    elif system == "windows" and machine in {"x86_64", "amd64"}:
        name = "lc-auth-check-windows-amd64.exe"
    else:
        stop("unsupported_platform")
    return skill_root() / "tools" / "bin" / name


def verify_binary(binary: Path) -> None:
    try:
        manifest = json.loads((skill_root() / "references/auth-binaries.json").read_text(encoding="utf-8"))
        if manifest["schema"] != "LC-AUTH-BINARIES/1.0":
            stop("auth_component_invalid")
        expected = manifest["sha256"][binary.name]
        if binary.is_symlink() or not binary.is_file():
            stop("auth_component_invalid")
        digest = hashlib.sha256()
        with binary.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            stop("auth_component_invalid")
    except (OSError, ValueError, KeyError, TypeError):
        stop("auth_component_invalid")


def prepare_binary(binary: Path) -> None:
    system = platform.system().lower()
    # Already executable files may live in a read-only host sandbox. A chmod,
    # even to the same mode, can be denied there and must not block execution.
    # Windows executable permission is determined by ACLs, not POSIX mode bits.
    if system != "windows" and not os.access(binary, os.X_OK):
        try:
            binary.chmod(binary.stat().st_mode | 0o111)
            if not os.access(binary, os.X_OK):
                stop("auth_component_permission_failed")
        except OSError:
            stop("auth_component_permission_failed")
    if system == "darwin":
        try:
            attributes = subprocess.run(
                ["/usr/bin/xattr", str(binary)], text=True, capture_output=True,
                encoding="utf-8", check=True, timeout=10,
            )
        except (OSError, UnicodeError, subprocess.SubprocessError):
            stop("auth_component_attributes_failed")
        if "com.apple.quarantine" in attributes.stdout.splitlines():
            try:
                subprocess.run(
                    ["/usr/bin/xattr", "-d", "com.apple.quarantine", str(binary)],
                    text=True, capture_output=True, encoding="utf-8", check=True, timeout=10,
                )
            except (OSError, UnicodeError, subprocess.SubprocessError):
                stop("auth_component_quarantine_failed")


def result_payload(*streams: str) -> dict:
    for stream in streams:
        for line in reversed(stream.splitlines()):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and isinstance(value.get("ok"), bool):
                return value
    return {}


def failure_reason(payload: dict) -> str:
    reason = payload.get("reason")
    if not isinstance(reason, str):
        return "invalid_response"
    known = {
        "missing_api_key": "missing_token",
        "bad_auth_request": "configuration_error",
        "auth_service_unavailable": "service_unavailable",
        "auth_response_unreadable": "invalid_response",
        "auth_response_malformed": "invalid_response",
        "auth_rejected": "auth_rejected",
        "user_not_enabled": "user_not_enabled",
        "auth_rate_limited": "rate_limited",
    }
    if reason in known:
        return known[reason]
    if reason == "auth_http_status_404":
        return "service_endpoint_invalid"
    if reason.startswith("auth_http_status_5"):
        return "service_unavailable"
    return "auth_failed" if payload else "invalid_response"


def require_auth() -> None:
    binary = auth_binary()
    verify_binary(binary)
    prepare_binary(binary)
    try:
        # Keep the existing checker's account protocol and credential precedence.
        result = subprocess.run(
            [str(binary), "--config", str(skill_root() / "config.json")],
            cwd=skill_root(), text=True, capture_output=True, encoding="utf-8", check=False, timeout=20,
        )
    except subprocess.TimeoutExpired:
        stop("service_timeout")
    except UnicodeError:
        stop("invalid_response")
    except OSError:
        stop("auth_component_launch_failed")
    payload = result_payload(result.stdout, result.stderr)
    if result.returncode != 0:
        stop(failure_reason(payload))
    if payload.get("ok") is not True or payload.get("message") != "auth_passed":
        stop("invalid_response")
    try:
        # Short-lived local pass (no token) checked by plan/deliver; see lc_auth_pass.
        from lc_auth_pass import write_pass
        write_pass(skill_root())
    except Exception as exc:  # noqa: BLE001 - the account check itself passed
        print(f"auth pass record not written: {type(exc).__name__}", file=sys.stderr)


def main() -> None:
    # Chinese failure text must survive non-Chinese Windows code pages.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    require_auth()
    print('{"ok":true,"message":"auth_passed"}')


if __name__ == "__main__":
    main()

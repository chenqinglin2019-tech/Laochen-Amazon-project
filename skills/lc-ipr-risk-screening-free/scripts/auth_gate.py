#!/usr/bin/env python3
"""Run the independent Laochen cloud authorization gate."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path

from common import atomic_write_json, credential, load_skill_config, sha256_file


SAFE_FAILURE = "云端鉴权未通过，本轮不继续执行。"
SAFE_REASONS = {
    "missing_token": "未配置访问 Token。",
    "invalid_token": "访问 Token 无效或无权访问。",
    "user_disabled": "账户已停用。",
    "insufficient_balance": "账户余额不足。",
    "rate_limited": "鉴权服务请求过于频繁，请稍后重试。",
    "service_unavailable": "鉴权服务暂时不可用。",
    "invalid_response": "鉴权服务返回异常。",
    "configuration_error": "鉴权配置无效。",
    "auth_component_invalid": "鉴权组件缺失或校验失败。",
    "auth_failed": "鉴权失败。",
}


def stop(reason: str) -> None:
    detail = SAFE_REASONS.get(reason, SAFE_REASONS["auth_failed"])
    raise SystemExit(f"{SAFE_FAILURE}\n原因：{detail}")


def result_reason(*streams: str) -> str:
    for stream in streams:
        for line in reversed(stream.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("reason") in SAFE_REASONS:
                return payload["reason"]
    return "auth_failed"


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def auth_binary() -> Path:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        return skill_root() / "tools" / "bin" / f"lc-ipr-auth-check-darwin-{'arm64' if machine in {'arm64', 'aarch64'} else 'amd64'}"
    if system == "linux":
        return skill_root() / "tools" / "bin" / "lc-ipr-auth-check-linux-amd64"
    if system == "windows":
        return skill_root() / "tools" / "bin" / "lc-ipr-auth-check-windows-amd64.exe"
    stop("auth_component_invalid")


def require_auth() -> None:
    if os.environ.get("LAOCHEN_AUTH_PASSED") == "1" and os.environ.get("LC_IPR_TEST_MODE") == "1":
        return
    binary = auth_binary()
    try:
        config = load_skill_config()
        expected = str(config.get("auth", {}).get("binary_sha256", {}).get(binary.name, ""))
        timeout = int(config.get("auth", {}).get("timeout_seconds", 20))
    except (AttributeError, OSError, TypeError, ValueError):
        stop("configuration_error")
    if timeout <= 0:
        stop("configuration_error")
    if not binary.is_file() or not expected or sha256_file(binary) != expected:
        stop("auth_component_invalid")
    backend_token = credential(config, "backend_token")
    backend_url = str(config.get("backend_url") or "").strip()
    if not backend_token:
        stop("missing_token")
    if not backend_url:
        stop("configuration_error")
    try:
        binary.chmod(binary.stat().st_mode | 0o111)
        with tempfile.TemporaryDirectory(prefix="lc-ipr-auth-") as temp_dir:
            auth_config = Path(temp_dir) / "auth.json"
            atomic_write_json(auth_config, {"backend_url": backend_url, "backend_token": backend_token})
            auth_config.chmod(0o600)
            result = subprocess.run(
                [str(binary), "--config", str(auth_config)],
                text=True, capture_output=True, check=False,
                timeout=timeout,
            )
    except subprocess.TimeoutExpired:
        stop("service_unavailable")
    except OSError:
        stop("auth_component_invalid")
    if result.returncode != 0:
        stop(result_reason(result.stderr, result.stdout))
    os.environ["LAOCHEN_AUTH_PASSED"] = "1"


def main() -> None:
    require_auth()
    print('{"ok":true,"message":"auth_passed"}')


if __name__ == "__main__":
    main()

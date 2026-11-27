"""云端鉴权。协议、凭据位置和失败时的说法都照老版，不改：
- 凭据在 Skill 目录的 config.json（backend_url、backend_token）；token 也可以放在环境变量 LAOCHEN_BACKEND_TOKEN；
- 用 tools/bin/ 里对应系统的鉴权组件去问后台，组件先核对哈希；
- 没通过就停，只显示固定的那几句原因。
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path

from . import config
from .outcome import StopSignal

SAFE_FAILURE = "云端鉴权未通过，本轮不继续执行。"
SAFE_REASONS = {
    "missing_token": "未配置访问 Token。",
    "invalid_token": "访问 Token 无效或无权访问。",
    "user_disabled": "账户已停用。",
    "insufficient_balance": "账户余额不足。",
    "unknown_skill": "后台尚未登记本 Skill。",
    "skill_disabled": "本 Skill 已停用。",
    "permission_disabled": "当前账户未开通本 Skill 权限。",
    "permission_missing": "当前账户缺少本 Skill 权限。",
    "rate_limited": "鉴权服务请求过于频繁，请稍后重试。",
    "service_unavailable": "鉴权服务暂时不可用。",
    "invalid_response": "鉴权服务返回异常。",
    "configuration_error": "鉴权配置无效。",
    "auth_component_invalid": "鉴权组件缺失或校验失败。",
    "auth_component_prepare_failed": "鉴权组件启动准备失败，请检查文件权限或 macOS 隔离标记。",
    "auth_failed": "鉴权失败。",
}
BINARY_SHA256 = {
    "lc-ipr-auth-check-darwin-amd64": "b0a0bf7e7aa0b681bbcaeecc7651790e4e12773c65fbdd20b1bd95739bb4695a",
    "lc-ipr-auth-check-darwin-arm64": "c048ab1c9740843a8b343231e712fffaaa810141d8674bf7c4b03519281bce01",
    "lc-ipr-auth-check-linux-amd64": "6aeda1ed58fefe918f36c1dea6c067e7914d5dab4b6ef315bfb6365506b14f0c",
    "lc-ipr-auth-check-windows-amd64.exe": "d3003ec2264be6e2a62698912afb0587ac7f9b7ce24c5ca348f622087eaf71e7",
}
TIMEOUT_SECONDS = 20
TOKEN_ENV = "LAOCHEN_BACKEND_TOKEN"
CONFIG_FILE = "config.json"
LOCAL_CONFIG_FILE = "config.local.json"


class AuthFailed(StopSignal):
    """鉴权没通过：停下，不采集、不出报告。"""

    def __init__(self, reason: str):
        self.reason = reason if reason in SAFE_REASONS else "auth_failed"
        super().__init__("%s原因：%s" % (SAFE_FAILURE, SAFE_REASONS[self.reason]))


def binary_path(skill_dir: Path = None) -> Path:
    skill_dir = skill_dir or config.SKILL_DIR
    system, machine = platform.system().lower(), platform.machine().lower()
    if system == "darwin":
        name = "lc-ipr-auth-check-darwin-%s" % ("arm64" if machine in ("arm64", "aarch64") else "amd64")
    elif system == "linux":
        name = "lc-ipr-auth-check-linux-amd64"
    elif system == "windows":
        name = "lc-ipr-auth-check-windows-amd64.exe"
    else:
        raise AuthFailed("auth_component_invalid")
    return skill_dir / "tools" / "bin" / name


def _reason_from(*streams: str) -> str:
    for stream in streams:
        for line in reversed((stream or "").splitlines()):
            try:
                payload = json.loads(line)
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get("reason") in SAFE_REASONS:
                return payload["reason"]
    return "auth_failed"


def load_backend(skill_dir: Path = None) -> tuple:
    """返回 (后台地址, token)。读不了就是配置无效。"""
    skill_dir = skill_dir or config.SKILL_DIR
    data = {}
    for name in (CONFIG_FILE, LOCAL_CONFIG_FILE):  # 和老版一样：config.json 必须有，config.local.json 有就合并进来
        path = skill_dir / name
        if name == LOCAL_CONFIG_FILE and not path.exists():
            continue
        try:
            value = json.loads(config.read_text(path))  # 记事本存出来带 BOM 的也认
        except (OSError, ValueError):
            raise AuthFailed("configuration_error")
        if not isinstance(value, dict):
            raise AuthFailed("configuration_error")
        data.update(value)
    url = str(data.get("backend_url") or "").strip()
    token = os.environ.get(TOKEN_ENV) or str(data.get("backend_token") or "")
    return url, token


def require(skill_dir: Path = None, runner=subprocess.run) -> None:
    """通过就安静返回；没通过抛 AuthFailed。runner 可替换，测试时不真的联网。"""
    skill_dir = skill_dir or config.SKILL_DIR
    binary = binary_path(skill_dir)
    expected = BINARY_SHA256.get(binary.name, "")
    if binary.is_symlink() or not binary.is_file() or not expected:
        raise AuthFailed("auth_component_invalid")
    if hashlib.sha256(binary.read_bytes()).hexdigest() != expected:
        raise AuthFailed("auth_component_invalid")
    url, token = load_backend(skill_dir)
    if not token:
        raise AuthFailed("missing_token")
    if not url:
        raise AuthFailed("configuration_error")
    config.add_secret(token)
    child_env = config.child_env()
    try:
        binary.chmod(binary.stat().st_mode | 0o111)
        if platform.system().lower() == "darwin":  # 只处理这一个核对过哈希的组件的隔离标记
            attributes = runner(["/usr/bin/xattr", str(binary)], text=True, encoding="utf-8", capture_output=True,
                                check=True, timeout=10, env=child_env)
            if "com.apple.quarantine" in (attributes.stdout or "").splitlines():
                runner(["/usr/bin/xattr", "-d", "com.apple.quarantine", str(binary)], text=True, encoding="utf-8",
                       capture_output=True, check=True, timeout=10, env=child_env)
    except (OSError, subprocess.SubprocessError):
        raise AuthFailed("auth_component_prepare_failed")
    try:
        with tempfile.TemporaryDirectory(prefix="lc-ipr-auth-") as temp_dir:
            auth_config = Path(temp_dir) / "auth.json"
            auth_config.write_text(json.dumps({"backend_url": url, "backend_token": token}), encoding="utf-8")
            auth_config.chmod(0o600)
            result = runner([str(binary), "--config", str(auth_config)], text=True, encoding="utf-8", capture_output=True,
                            check=False, timeout=TIMEOUT_SECONDS, env=child_env)
    except subprocess.TimeoutExpired:
        raise AuthFailed("service_unavailable")
    except OSError:
        raise AuthFailed("auth_component_invalid")
    if result.returncode != 0:
        raise AuthFailed(_reason_from(result.stderr, result.stdout))

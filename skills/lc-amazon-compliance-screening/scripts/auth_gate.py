"""Cloud authorization for the distributed CLI; no business data or success cache."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

import csc_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]
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
    "auth_failed": "鉴权失败。",
}


class AuthError(Exception):
    def __init__(self, reason):
        self.reason = reason if reason in SAFE_REASONS else "auth_failed"
        super().__init__(SAFE_FAILURE + "\n原因：" + SAFE_REASONS[self.reason])


def auth_binary():
    system, machine = platform.system().lower(), platform.machine().lower()
    arch = {"arm64": "arm64", "aarch64": "arm64", "amd64": "amd64", "x86_64": "amd64"}.get(machine)
    if (system, arch) not in {("darwin", "arm64"), ("darwin", "amd64"),
                              ("linux", "amd64"), ("windows", "amd64")}:
        raise AuthError("auth_component_invalid")
    suffix = ".exe" if system == "windows" else ""
    return ROOT / "tools" / "bin" / f"lc-compliance-auth-check-{system}-{arch}{suffix}"


def load_config():
    try:
        cfg = runtime.read_json(ROOT / "config.json")
        if not isinstance(cfg, dict):
            raise ValueError()
        local = ROOT / "config.local.json"
        if local.exists():
            overrides = runtime.read_json(local)
            if not isinstance(overrides, dict) or set(overrides) - {"backend_url", "backend_token"}:
                raise ValueError()
            cfg.update(overrides)
        url = cfg.get("backend_url")
        token = os.environ.get("LAOCHEN_BACKEND_TOKEN", "").strip() or cfg.get("backend_token", "")
        timeout, hashes = runtime.read_auth_settings(ROOT)
        if not isinstance(url, str) or not url.strip() or not isinstance(token, str):
            raise ValueError()
        return url.strip(), token.strip(), timeout, hashes
    except (OSError, ValueError, TypeError):
        raise AuthError("configuration_error") from None


def require_auth():
    url, token, timeout, hashes = load_config()
    if not token:
        raise AuthError("missing_token")
    binary = auth_binary()
    try:
        expected = hashes.get(binary.name)
        if not isinstance(expected, str) or hashlib.sha256(binary.read_bytes()).hexdigest() != expected:
            raise AuthError("auth_component_invalid")
        # Installed executables may be owned by an administrator or on a
        # read-only volume. Repair stripped ZIP permissions only when needed.
        if os.name != "nt" and not os.access(binary, os.X_OK):
            binary.chmod(binary.stat().st_mode | 0o111)
        # Keep credentials out of argv and task files. The directory is private.
        with tempfile.TemporaryDirectory(prefix="lc-compliance-auth-") as directory:
            config_path = Path(directory) / "auth.json"
            with config_path.open("x", encoding="utf-8") as handle:
                config_path.chmod(0o600)
                json.dump({"backend_url": url, "backend_token": token}, handle)
            result = subprocess.run(
                [str(binary), "--config", str(config_path), "--timeout", f"{timeout}s"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout + 2, check=False,
            )
    except subprocess.TimeoutExpired:
        raise AuthError("service_unavailable") from None
    except OSError:
        raise AuthError("auth_component_invalid") from None
    try:
        payload = json.loads(result.stdout if result.returncode == 0 else result.stderr)
        if not isinstance(payload, dict):
            raise ValueError()
    except ValueError:
        raise AuthError("invalid_response") from None
    if result.returncode != 0:
        reason = payload.get("reason")
        raise AuthError(reason if isinstance(reason, str) else "auth_failed")
    if payload.get("ok") is not True or payload.get("message") != "auth_passed":
        raise AuthError("invalid_response")


def main():
    runtime.configure_stdio()
    try:
        require_auth()
    except AuthError as exc:
        print(json.dumps({"ok": False, "reason": exc.reason, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "message": "auth_passed"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

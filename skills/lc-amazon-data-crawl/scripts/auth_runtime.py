"""Credential selection and safe diagnostics; the native account protocol is unchanged.

Standard library only (Python 3.8+). Never print configurations, raw responses,
exception text or credential values. Native checker files are not modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

SAFE_FAILURE = "云端鉴权未通过，本轮不继续执行。"
REASONS = {
    "configuration_error": "鉴权配置无法读取或格式无效，请检查 config.json / config.local.json。",
    "configuration_conflict": "config.json 与 config.local.json 的非空 token 冲突；请用 configure_credentials.py 或安装器的替换 token 选项统一更新。",
    "missing_token": "未读取到可用 token；请通过安装器或 configure_credentials.py 填写本 Skill 的云端 token。",
    "credential_write_failed": "无法安全写入云端凭据，请检查当前用户对 Skill / runner 目录的写入权限。",
    "auth_rejected": "账户鉴权被拒绝，请检查 token 和账户权限；未自动尝试其他凭据。",
    "user_not_enabled": "账户未启用或账户状态不可用。",
    "rate_limited": "鉴权服务请求过于频繁，请稍后重试。",
    "service_unavailable": "鉴权连接或服务不可用；请检查宿主网络权限、DNS/TLS、代理及服务状态，不能据此判定 token 无效。",
    "service_timeout": "鉴权请求超时；请检查宿主网络权限和服务状态，不能据此判定 token 无效。",
    "service_endpoint_invalid": "鉴权服务地址或接口不可用，请检查 backend_url。",
    "invalid_response": "鉴权服务返回异常，无法确认账户鉴权结果。",
    "auth_failed": "鉴权组件未通过校验且没有可识别的安全原因，请检查安装和连接；未公开原始响应。",
}


class AuthError(Exception):
    def __init__(self, reason, status=4):
        self.reason, self.status = reason, status


def read_config(path, optional=False):
    try:
        if path.is_symlink():
            raise AuthError("configuration_error")
        if optional and not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise AuthError("configuration_error")
        return payload
    except (OSError, ValueError, UnicodeError):
        raise AuthError("configuration_error") from None


def token_value(config):
    value = config.get("backend_token", "")
    if value is None:
        return ""
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise AuthError("configuration_error")
    return value.strip()


def valid_url(value):
    try:
        if not isinstance(value, str) or value != value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError()
        url = urlsplit(value)
        url.port
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
            raise ValueError()
    except ValueError:
        raise AuthError("configuration_error") from None
    return value


def resolve_config(root):
    public_path, local_path = root / "config.json", root / "config.local.json"
    public, local = read_config(public_path), read_config(local_path, optional=True)
    public_token, local_token = token_value(public), token_value(local)
    if public_token and local_token and public_token != local_token:
        raise AuthError("configuration_conflict")
    token = local_token or public_token
    if not token:
        raise AuthError("missing_token")
    # A tokenless local file cannot replace the public token OR its endpoint.
    effective = dict(public, **local) if local_token else dict(public)
    effective.update(backend_token=token, backend_url=valid_url(effective.get("backend_url")))
    path = local_path if local_token else public_path
    # Preserve the original config path when it already carries the effective
    # values. Partial overrides / BOM / whitespace are materialized privately.
    selected = local if local_token else public
    direct = (selected.get("backend_url") == effective["backend_url"] and
              selected.get("backend_token") == token and not path.read_bytes().startswith(b'\xef\xbb\xbf'))
    return effective, path if direct else None


def atomic_write(path, data):
    if path.is_symlink():
        raise AuthError("credential_write_failed")
    fd, temporary = tempfile.mkstemp(prefix=".config.local.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def encode(config):
    return (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_credentials(root, token, backend_url=None):
    token = token_value({"backend_token": token})
    if not token:
        raise AuthError("missing_token")
    public_path, local_path = root / "config.json", root / "config.local.json"
    public = read_config(public_path)
    if local_path.is_symlink():
        raise AuthError("credential_write_failed")
    try:
        local = read_config(local_path, optional=True)
    except AuthError:
        # Explicit replacement can repair a corrupt local credential file.
        local = {}
    url = valid_url(backend_url or local.get("backend_url") or public.get("backend_url"))
    local.update(backend_url=url, backend_token=token)
    public["backend_token"] = ""
    old_local = local_path.read_bytes() if local_path.exists() else None
    try:
        atomic_write(local_path, encode(local))
        atomic_write(public_path, encode(public))
    except (OSError, AuthError):
        # Do not leave a new local token masking the previous public token if
        # the second write fails. No secret-bearing backup is left behind.
        try:
            if old_local is None:
                local_path.unlink(missing_ok=True)
            else:
                atomic_write(local_path, old_local)
        except (OSError, AuthError):
            pass
        raise AuthError("credential_write_failed") from None


def sync_runner(source, target):
    config, _ = resolve_config(source)
    if source.resolve() == target.resolve():
        return
    # Called only after the setup entry's successful gate. No model keys or
    # task configuration is read/copied here; only cloud-auth fields change.
    write_credentials(target, config["backend_token"], config["backend_url"])


def credential_fingerprint(root):
    config, _ = resolve_config(root)
    fields = {k: config[k] for k in ("backend_url", "backend_token")}
    return hashlib.sha256(b"lc-install-auth\0" + encode(fields)).hexdigest()


def recent_auth(root):
    try:
        age = time.time() - int(os.environ.get("LC_AUTH_VERIFIED_AT", ""))
        return (0 <= age <= 600 and
                os.environ.get("LC_AUTH_VERIFIED_CONFIG", "") == credential_fingerprint(root))
    except (ValueError, AuthError, OSError):
        return False


def failure_reason(stdout, stderr):
    payload = None
    for stream in (stdout, stderr):
        for line in reversed(stream.splitlines()):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and isinstance(value.get("ok"), bool):
                payload = value
                break
        if payload is not None:
            break
    if payload is None:
        return "auth_failed"
    reason = payload.get("reason")
    if not isinstance(reason, str):
        return "invalid_response"
    known = {"missing_api_key": "missing_token", "bad_auth_request": "configuration_error",
             "auth_service_unavailable": "service_unavailable", "auth_response_unreadable": "invalid_response",
             "auth_response_malformed": "invalid_response", "auth_rejected": "auth_rejected",
             "user_not_enabled": "user_not_enabled", "auth_rate_limited": "rate_limited",
             "auth_http_status_401": "auth_rejected", "auth_http_status_403": "auth_rejected",
             "auth_http_status_429": "rate_limited", "auth_http_status_404": "service_endpoint_invalid"}
    if reason in known:
        return known[reason]
    if reason.startswith("auth_http_status_5"):
        return "service_unavailable"
    return "auth_failed"


def check(root, binary):
    config, path = resolve_config(root)
    temporary = None
    try:
        if path is None:
            fd, temporary = tempfile.mkstemp(prefix="lc-auth-", suffix=".json")
            with os.fdopen(fd, "wb") as stream:
                stream.write(encode(config))
            os.chmod(temporary, 0o600)
            path = Path(temporary)
        result = subprocess.run([str(binary), "--config", str(path)], cwd=str(root),
                                capture_output=True, text=True, encoding="utf-8", timeout=20, check=False)
    except subprocess.TimeoutExpired:
        raise AuthError("service_timeout") from None
    except UnicodeError:
        raise AuthError("invalid_response") from None
    except OSError:
        raise AuthError("auth_component_launch_failed", 3) from None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    if result.returncode == 0:
        return
    if result.returncode < 0 or result.returncode in (126, 127) or result.returncode >= 128:
        raise AuthError("auth_component_launch_failed", 3)
    raise AuthError(failure_reason(result.stdout, result.stderr))


def report_error(exc):
    if exc.status == 3:
        print("鉴权程序启动准备失败：鉴权组件无法执行或被系统终止。本轮不继续执行。", file=sys.stderr)
    else:
        print(SAFE_FAILURE, file=sys.stderr)
        print("原因：" + REASONS.get(exc.reason, REASONS["auth_failed"]), file=sys.stderr)
    return exc.status


def configure_console():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "configured", "configure", "sync-runner", "fingerprint"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--token-stdin", action="store_true")
    parser.add_argument("--allow-recent", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "configured":
            try:
                resolve_config(args.root)
                return 0
            except AuthError as exc:
                if exc.reason == "missing_token":
                    return 1
                raise
        if args.action == "check":
            if args.binary is None:
                raise AuthError("configuration_error")
            if not args.allow_recent or not recent_auth(args.root):
                check(args.root, args.binary)
        elif args.action == "fingerprint":
            print(credential_fingerprint(args.root))
        elif args.action == "configure":
            payload = {"backend_token": sys.stdin.read()} if args.token_stdin else json.load(sys.stdin)
            if not isinstance(payload, dict) or set(payload) - {"backend_token", "backend_url"} or "backend_token" not in payload:
                raise AuthError("configuration_error")
            write_credentials(args.root, payload["backend_token"], payload.get("backend_url"))
            print('{"ok":true,"updated_fields":["backend_token"],"credential_file":"config.local.json"}')
        elif args.action == "sync-runner":
            if args.target is None:
                raise AuthError("configuration_error")
            sync_runner(args.root, args.target)
        return 0
    except AuthError as exc:
        return report_error(exc)
    except (OSError, ValueError, UnicodeError):
        return report_error(AuthError("configuration_error"))


if __name__ == "__main__":
    configure_console()
    raise SystemExit(main())

"""Validate the local backend configuration without exposing its token."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = SKILL_ROOT / "config.json"
REQUIRED_FIELDS = ("backend_url", "backend_token")


class BackendConfigError(ValueError):
    """The user-owned local backend config cannot be used safely."""


def validate(path: Path = DEFAULT_CONFIG_PATH) -> Mapping[str, Any]:
    """Return a redacted audit summary after strict local validation."""
    target = Path(path).expanduser()
    if not target.exists():
        raise BackendConfigError("后端配置不存在：%s" % target)
    if target.is_symlink() or not target.is_file():
        raise BackendConfigError("后端配置必须是普通文件：%s" % target)
    if os.name != "nt" and stat.S_IMODE(target.stat().st_mode) != 0o600:
        raise BackendConfigError("后端配置权限必须为 0600：%s" % target)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackendConfigError("后端配置不是有效 JSON：%s" % type(exc).__name__) from None
    if not isinstance(payload, Mapping):
        raise BackendConfigError("后端配置顶层必须是对象")
    for field in REQUIRED_FIELDS:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise BackendConfigError("后端配置缺少非空字段：%s" % field)
    endpoint = str(payload["backend_url"]).strip()
    token = str(payload["backend_token"]).strip()
    if not endpoint.startswith("https://"):
        raise BackendConfigError("backend_url 必须使用 HTTPS")
    if not token.startswith("sk-"):
        raise BackendConfigError("backend_token 格式无效")
    return {
        "status": "configured",
        "config_path": str(target),
        "backend_url": endpoint,
        "backend_token_present": True,
        "backend_token_redacted": "<configured>",
    }

#!/usr/bin/env bash
set -euo pipefail
set +x

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-$(dirname "$SKILL_DIR")/lc-amazon-data-crawl-runner}"
PUBLIC_CONFIG="$SKILL_DIR/config.json"
LOCAL_CONFIG="$SKILL_DIR/config.local.json"

if [[ ! -f "$PUBLIC_CONFIG" ]]; then
  echo "缺少 config.json；请使用完整的 Skill 发布包。" >&2
  exit 2
fi

configured_token() {
  python3 - "$1" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
    raise SystemExit(0 if isinstance(data, dict) and str(data.get("backend_token") or "").strip() else 1)
except (OSError, ValueError, TypeError):
    raise SystemExit(1)
PY
}

if ! configured_token "$LOCAL_CONFIG" && ! configured_token "$PUBLIC_CONFIG"; then
  if [[ -t 0 ]]; then
    printf '请输入你自己的云端授权令牌（输入不会显示）：' >&2
  fi
  IFS= read -r -s token || {
    echo "未读到授权令牌；安装已停止。" >&2
    exit 2
  }
  if [[ -t 0 ]]; then
    printf '\n' >&2
  fi
  if [[ -z "${token//[[:space:]]/}" ]]; then
    echo "授权令牌不能为空；安装已停止。" >&2
    exit 2
  fi
  printf '%s' "$token" | python3 -c '
import json, os, pathlib, sys, tempfile
public = pathlib.Path(sys.argv[1])
local = pathlib.Path(sys.argv[2])
with public.open(encoding="utf-8") as handle:
    config = json.load(handle)
if not isinstance(config, dict) or not str(config.get("backend_url") or "").strip():
    raise SystemExit("公开配置缺少 backend_url。")
config["backend_token"] = sys.stdin.read().strip()
fd, temporary = tempfile.mkstemp(prefix=".config.local.", dir=str(local.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, local)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
' "$PUBLIC_CONFIG" "$LOCAL_CONFIG"
  unset token
fi

bash "$SKILL_DIR/scripts/setup_runner.sh" "$TARGET_DIR"
if [[ "${LC_AMAZON_INSTALL_SETUP_ONLY:-}" != "1" ]]; then
  bash "$TARGET_DIR/lc-amazon-data-crawl.sh" install
  bash "$TARGET_DIR/lc-amazon-data-crawl.sh" doctor
fi
printf '安装完成。Runner：%s\n' "$TARGET_DIR"

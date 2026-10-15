#!/usr/bin/env bash
set -euo pipefail
set +x

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$(dirname "$SKILL_DIR")/lc-amazon-data-crawl-runner"
replace_token=0
for argument in "$@"; do
  if [[ "$argument" == "--replace-token" ]]; then replace_token=1; else TARGET_DIR="$argument"; fi
done
PUBLIC_CONFIG="$SKILL_DIR/config.json"

if [[ ! -f "$PUBLIC_CONFIG" ]]; then
  echo "缺少 config.json；请使用完整的 Skill 发布包。" >&2
  exit 2
fi

configured=0
if [[ "$replace_token" -eq 0 ]]; then
  if python3 "$SKILL_DIR/scripts/auth_runtime.py" configured --root "$SKILL_DIR"; then
    configured=1
  else
    config_status=$?
    if [[ "$config_status" -ne 1 ]]; then exit "$config_status"; fi
  fi
fi
if [[ "$configured" -eq 0 ]]; then
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
  printf '%s' "$token" | python3 "$SKILL_DIR/scripts/auth_runtime.py" configure --root "$SKILL_DIR" --token-stdin
  unset token
fi

# One cloud-auth call per installation: setup, install and doctor below honor
# this marker for up to 10 minutes (crawl commands never do).
bash "$SKILL_DIR/scripts/check_auth.sh"
LC_AUTH_VERIFIED_AT="$(date +%s)"
LC_AUTH_VERIFIED_CONFIG="$(python3 "$SKILL_DIR/scripts/auth_runtime.py" fingerprint --root "$SKILL_DIR")"
export LC_AUTH_VERIFIED_AT LC_AUTH_VERIFIED_CONFIG

bash "$SKILL_DIR/scripts/setup_runner.sh" "$TARGET_DIR"
if [[ "${LC_AMAZON_INSTALL_SETUP_ONLY:-}" != "1" ]]; then
  bash "$TARGET_DIR/lc-amazon-data-crawl.sh" install
  bash "$TARGET_DIR/lc-amazon-data-crawl.sh" doctor
fi
printf '安装完成。Runner：%s\n' "$TARGET_DIR"

#!/usr/bin/env bash
set -euo pipefail

# Invoke with bash so a downloaded script does not need execute permission.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --allow-recent is passed ONLY by setup_runner.sh and the launcher's
# install/doctor commands: inside one installation (install_for_user.sh), a
# successful check exported as LC_AUTH_VERIFIED_AT (epoch seconds) is reused
# for at most 10 minutes and only for the same credential fingerprint.
# Crawl commands never pass it and always re-check.
os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m | tr '[:upper:]' '[:lower:]')"
ext=""
case "$os" in
  linux*) os="linux" ;;
  darwin*) os="darwin" ;;
  mingw*|msys*|cygwin*) os="windows"; ext=".exe" ;;
  *) echo "鉴权程序不支持当前系统：$os" >&2; exit 2 ;;
esac
case "$arch" in
  x86_64|amd64) arch="amd64" ;;
  arm64|aarch64) arch="arm64" ;;
  *) echo "鉴权程序不支持当前架构：$arch" >&2; exit 2 ;;
esac
if [[ "$os" == "windows" ]]; then
  arch="amd64"
fi
auth_bin="$ROOT_DIR/tools/bin/lc-auth-check-$os-$arch$ext"

startup_failed() {
  echo "鉴权程序启动准备失败：$1。本轮不继续执行。" >&2
  printf '文件：%s\n' "$auth_bin" >&2
  exit 3
}

if [[ ! -f "$auth_bin" ]]; then
  echo "云端鉴权工具缺失，本轮不继续执行。" >&2
  exit 2
fi

if [[ "$os" == "darwin" ]]; then
  # Check names, not values: a missing quarantine attribute is already ready.
  if ! attributes="$(xattr "$auth_bin" 2>/dev/null)"; then
    startup_failed "无法读取 macOS 隔离标记"
  fi
  if [[ $'\n'"$attributes"$'\n' == *$'\ncom.apple.quarantine\n'* ]]; then
    if ! xattr -d com.apple.quarantine "$auth_bin" >/dev/null 2>&1; then
      startup_failed "无法清除 macOS 隔离标记，请将 Skill 安装在当前用户可写的目录"
    fi
    if ! attributes="$(xattr "$auth_bin" 2>/dev/null)"; then
      startup_failed "无法复查 macOS 隔离标记"
    fi
    if [[ $'\n'"$attributes"$'\n' == *$'\ncom.apple.quarantine\n'* ]]; then
      startup_failed "macOS 隔离标记仍然存在"
    fi
  fi
fi

if [[ ! -x "$auth_bin" ]]; then
  if ! chmod u+x "$auth_bin" 2>/dev/null; then
    startup_failed "无法恢复执行权限，请将 Skill 安装在当前用户可写的目录"
  fi
  if [[ ! -x "$auth_bin" ]]; then
    startup_failed "执行权限未生效"
  fi
fi

# Credential selection, conflict detection and safe backend diagnostics are
# shared by both platforms. Python is already required by the runner installer.
auth_python=""
for candidate in python3 python "$ROOT_DIR/.venv-scrapling/bin/python" "$ROOT_DIR/.venv/bin/python"; do
  if command -v "$candidate" >/dev/null 2>&1 && \
     "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    auth_python="$candidate"
    break
  fi
done
if [[ -z "$auth_python" ]]; then
  startup_failed "没有找到 Python 3.8+；请安装 Python 后重试"
fi
if [[ ! -f "$ROOT_DIR/scripts/auth_runtime.py" ]]; then
  startup_failed "共享鉴权入口缺失，请更新完整 Skill 或 runner"
fi
# config.local.json is selected per value, never merely because it exists.
# Raw output and credentials are captured inside auth_runtime.py, not echoed.
if [[ "${1:-}" == "--allow-recent" ]]; then
  "$auth_python" "$ROOT_DIR/scripts/auth_runtime.py" check --root "$ROOT_DIR" --binary "$auth_bin" --allow-recent
else
  "$auth_python" "$ROOT_DIR/scripts/auth_runtime.py" check --root "$ROOT_DIR" --binary "$auth_bin"
fi

#!/usr/bin/env bash
set -euo pipefail

# Invoke with bash so a downloaded script does not need execute permission.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

# A published Skill keeps config.json empty. Each installation stores its own
# token in the ignored local override, while existing installs still work.
auth_config="$ROOT_DIR/config.json"
if [[ -f "$ROOT_DIR/config.local.json" ]]; then
  auth_config="$ROOT_DIR/config.local.json"
fi

# Keep credentials and backend responses out of terminal output.
if "$auth_bin" --config "$auth_config" >/dev/null 2>&1; then
  exit 0
else
  auth_status=$?
  if [[ "$auth_status" -eq 126 || "$auth_status" -eq 127 || "$auth_status" -ge 128 ]]; then
    startup_failed "鉴权程序无法执行或被系统终止（退出码 $auth_status）"
  fi
  echo "云端鉴权未通过，本轮不继续执行。" >&2
  exit 4
fi

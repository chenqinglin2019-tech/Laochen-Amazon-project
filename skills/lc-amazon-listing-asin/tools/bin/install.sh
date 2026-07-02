#!/bin/bash
# Mac 用户首次使用前运行一次，去除系统隔离标记
DIR="$(cd "$(dirname "$0")" && pwd)"
xattr -dr com.apple.quarantine "$DIR"
chmod +x "$DIR"/laochen-cli-*
echo "✅ 安装完成，CLI 可正常使用"

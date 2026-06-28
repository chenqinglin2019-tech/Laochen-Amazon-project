#!/bin/bash
# Mac 用户首次使用前运行一次，去除系统隔离标记（解决"已损坏/无法验证开发者"弹窗）
# 用法：cd 到此目录后运行 bash install.sh
# 只需运行一次，之后 CLI 可正常使用

DIR="$(cd "$(dirname "$0")" && pwd)"
xattr -dr com.apple.quarantine "$DIR"
chmod +x "$DIR"/amazon-niche-choice-v2-*
echo "✅ 安装完成，CLI 可正常使用"

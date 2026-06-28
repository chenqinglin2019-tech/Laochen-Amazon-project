#!/bin/bash
# Mac 用户首次使用前运行一次，去除系统隔离标记。
# Public release packages may omit CLI binaries. Put authorized binaries in this
# folder before running this script.
DIR="$(cd "$(dirname "$0")" && pwd)"
if ! compgen -G "$DIR/laochen-cli-*" > /dev/null; then
  echo "No laochen-cli binaries found in $DIR"
  echo "Place authorized CLI binaries here before running install.sh."
  exit 0
fi

xattr -dr com.apple.quarantine "$DIR"
chmod +x "$DIR"/laochen-cli-*
echo "Install complete. CLI binaries are executable."

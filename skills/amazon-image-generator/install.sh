#!/usr/bin/env bash
set -euo pipefail

SKILL_NAME="amazon-image-generator"
CODEX_HOME_DIR="${CODEX_HOME:-"$HOME/.codex"}"
SKILLS_DIR="$CODEX_HOME_DIR/skills"
DEST_DIR="$SKILLS_DIR/$SKILL_NAME"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UI_UX_SKILL_NAME="ui-ux-pro-max"
UI_UX_SKILL_DIR="$SKILLS_DIR/$UI_UX_SKILL_NAME"
UI_UX_REPO="nextlevelbuilder/ui-ux-pro-max-skill"
UI_UX_REPO_PATH=".claude/skills/ui-ux-pro-max"
SKILL_INSTALLER="$SKILLS_DIR/.system/skill-installer/scripts/install-skill-from-github.py"

OVERWRITE=0

usage() {
  cat <<'USAGE'
Install 飞鱼神图 (amazon-image-generator) into Codex.

Usage:
  ./install.sh [--overwrite]

Options:
  --overwrite      Replace an existing installed skill after backing it up.
  -h, --help       Show this help.

Run this script from inside the amazon-image-generator skill folder.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --overwrite)
      OVERWRITE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$(basename "$SOURCE_DIR")" != "$SKILL_NAME" || ! -f "$SOURCE_DIR/SKILL.md" ]]; then
  echo "This installer must be run from inside the $SKILL_NAME skill folder." >&2
  exit 1
fi

mkdir -p "$SKILLS_DIR"

if [[ -f "$UI_UX_SKILL_DIR/SKILL.md" ]]; then
  echo "UI dependency already installed: $UI_UX_SKILL_DIR"
elif [[ -e "$UI_UX_SKILL_DIR" ]]; then
  echo "UI dependency directory exists but is incomplete: $UI_UX_SKILL_DIR" >&2
  echo "Repair or remove that directory, then run the installer again." >&2
  exit 1
elif [[ ! -f "$SKILL_INSTALLER" ]]; then
  echo "Codex skill-installer is unavailable: $SKILL_INSTALLER" >&2
  echo "Install ui-ux-pro-max from https://github.com/$UI_UX_REPO/tree/main/$UI_UX_REPO_PATH, then run this installer again." >&2
  exit 1
else
  echo "Installing UI dependency: $UI_UX_SKILL_NAME"
  python3 "$SKILL_INSTALLER" \
    --repo "$UI_UX_REPO" \
    --path "$UI_UX_REPO_PATH"
  if [[ ! -f "$UI_UX_SKILL_DIR/SKILL.md" ]]; then
    echo "UI dependency installation did not create: $UI_UX_SKILL_DIR/SKILL.md" >&2
    exit 1
  fi
fi

if [[ "$SOURCE_DIR" == "$DEST_DIR" ]]; then
  echo "Skill is already installed at: $DEST_DIR"
else
  if [[ -e "$DEST_DIR" ]]; then
    if [[ "$OVERWRITE" != "1" ]]; then
      echo "Skill already exists: $DEST_DIR" >&2
      echo "Run with --overwrite to replace it after creating a backup." >&2
      exit 1
    fi
    BACKUP_DIR="$DEST_DIR.backup.$(date +%Y%m%d%H%M%S)"
    mv "$DEST_DIR" "$BACKUP_DIR"
    echo "Backed up existing skill to: $BACKUP_DIR"
  fi

  cp -R "$SOURCE_DIR" "$DEST_DIR"
  echo "Installed skill to: $DEST_DIR"
fi

chmod +x "$DEST_DIR/scripts/feiyushentu_amazon.py" 2>/dev/null || true
chmod +x "$DEST_DIR/scripts/install_harness_app.py" 2>/dev/null || true
chmod +x "$DEST_DIR/scripts/remove_harness_app.py" 2>/dev/null || true
chmod +x "$DEST_DIR/scripts/configure_harness_proxy.py" 2>/dev/null || true
chmod +x "$DEST_DIR/install.sh" 2>/dev/null || true

cat <<'NEXT'

Next step: configure your FeiyuShentu token:

  python3 ~/.codex/skills/amazon-image-generator/scripts/feiyushentu_amazon.py set-token

Then use the skill in Codex:

  使用 飞鱼神图 生成亚马逊图片

Explicit skill invocation is also supported:

  使用 $amazon-image-generator 生成亚马逊图片

To install the tested Codex Harness website module later, ask Codex:

  使用 $amazon-image-generator 在当前 Codex Harness 网站安装飞鱼神图

To safely remove the website module while preserving a recoverable archive:

  使用 $amazon-image-generator 删除当前网站的飞鱼神图模块
NEXT

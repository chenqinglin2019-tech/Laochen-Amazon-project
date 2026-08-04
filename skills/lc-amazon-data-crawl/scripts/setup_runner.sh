#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-$PWD/lc-amazon-data-crawl-runner}"

select_setup_auth_bin() {
  local os arch ext
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m | tr '[:upper:]' '[:lower:]')"
  ext=""
  case "$os" in
    linux*) os="linux" ;;
    darwin*) os="darwin" ;;
    mingw*|msys*|cygwin*) os="windows"; ext=".exe" ;;
    *) echo "unsupported os for auth gate: $os" >&2; return 2 ;;
  esac
  case "$arch" in
    x86_64|amd64) arch="amd64" ;;
    arm64|aarch64) arch="arm64" ;;
    *) echo "unsupported arch for auth gate: $arch" >&2; return 2 ;;
  esac
  if [[ "$os" == "windows" ]]; then
    arch="amd64"
  fi
  echo "$SKILL_DIR/tools/bin/lc-auth-check-$os-$arch$ext"
}

require_setup_auth() {
  local auth_bin
  auth_bin="$(select_setup_auth_bin)"
  if [[ ! -f "$auth_bin" ]]; then
    echo "云端鉴权工具缺失，本轮不继续执行。" >&2
    exit 2
  fi
  case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
    darwin*)
      xattr -dr com.apple.quarantine "$SKILL_DIR/tools/bin" 2>/dev/null || true
      chmod +x "$SKILL_DIR"/tools/bin/lc-auth-check-darwin-* 2>/dev/null || true
      ;;
  esac
  chmod +x "$auth_bin" 2>/dev/null || true
  if ! "$auth_bin" --config "$SKILL_DIR/config.json" >/dev/null; then
    echo "云端鉴权未通过，本轮不继续执行。" >&2
    exit 4
  fi
}

require_setup_auth

mkdir -p "$TARGET_DIR/scripts" "$TARGET_DIR/config" "$TARGET_DIR/inputs" "$TARGET_DIR/outputs" "$TARGET_DIR/chrome_profiles" "$TARGET_DIR/tools/bin"

cp "$SKILL_DIR"/scripts/*.py "$TARGET_DIR/scripts/"
cp "$SKILL_DIR/assets/requirements.txt" "$TARGET_DIR/requirements.txt"
for config_file in "$SKILL_DIR"/assets/config/*.json; do
  config_name="$(basename "$config_file")"
  if [[ "$config_name" == "doubao_embedding_vision.example.json" ]]; then
    continue
  fi
  target_config="$TARGET_DIR/config/$config_name"
  if [[ ! -f "$target_config" ]]; then
    cp "$config_file" "$target_config"
  fi
done

DOUBAO_CONFIG="$TARGET_DIR/config/doubao_embedding_vision.json"
if [[ ! -f "$DOUBAO_CONFIG" ]]; then
  cp "$SKILL_DIR/assets/config/doubao_embedding_vision.example.json" "$DOUBAO_CONFIG"
fi
chmod 600 "$DOUBAO_CONFIG" 2>/dev/null || true

RUNNER_GITIGNORE="$TARGET_DIR/.gitignore"
touch "$RUNNER_GITIGNORE"
if ! grep -Fqx 'config/doubao_embedding_vision.json' "$RUNNER_GITIGNORE"; then
  printf '\n# Local API credentials\nconfig/doubao_embedding_vision.json\n' >> "$RUNNER_GITIGNORE"
fi
if [[ ! -f "$TARGET_DIR/config.json" ]]; then
  cp "$SKILL_DIR/config.json" "$TARGET_DIR/config.json"
fi
if [[ -d "$SKILL_DIR/tools/bin" ]]; then
  cp "$SKILL_DIR"/tools/bin/* "$TARGET_DIR/tools/bin/"
  chmod +x "$TARGET_DIR"/tools/bin/* 2>/dev/null || true
fi

for input_file in "$SKILL_DIR"/assets/inputs/*; do
  target_file="$TARGET_DIR/inputs/$(basename "$input_file")"
  if [[ ! -f "$target_file" ]]; then
    cp "$input_file" "$target_file"
  fi
done

if [[ ! -f "$TARGET_DIR/config/amazon_front_crawler.json" ]]; then
  cp "$TARGET_DIR/config/amazon_front_keyword_search.json" "$TARGET_DIR/config/amazon_front_crawler.json"
fi

cat > "$TARGET_DIR/lc-amazon-data-crawl.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

usage() {
  cat <<'USAGE'
Usage:
  ./lc-amazon-data-crawl.sh install
  ./lc-amazon-data-crawl.sh doctor
  ./lc-amazon-data-crawl.sh amazon-front-dry-run [--config config/amazon_front_keyword_search.json]
  ./lc-amazon-data-crawl.sh amazon-front-run [--config config/amazon_front_storefront.json]
  ./lc-amazon-data-crawl.sh category-rank-dry-run [--config config/category_rank_crawler.json]
  ./lc-amazon-data-crawl.sh category-rank-run [--config config/category_rank_crawler.json]
  ./lc-amazon-data-crawl.sh image-competitor-dry-run [--config config/amazon_image_competitors.json]
  ./lc-amazon-data-crawl.sh image-competitor-run [--config config/amazon_image_competitors.json]
  ./lc-amazon-data-crawl.sh cdp-browser-start --config <config-file>
  ./lc-amazon-data-crawl.sh sellersprite-check --config <config-file>
USAGE
}

select_auth_bin() {
  local os arch ext
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m | tr '[:upper:]' '[:lower:]')"
  ext=""
  case "$os" in
    linux*) os="linux" ;;
    darwin*) os="darwin" ;;
    mingw*|msys*|cygwin*) os="windows"; ext=".exe" ;;
    *) echo "unsupported os for auth gate: $os" >&2; return 2 ;;
  esac
  case "$arch" in
    x86_64|amd64) arch="amd64" ;;
    arm64|aarch64) arch="arm64" ;;
    *) echo "unsupported arch for auth gate: $arch" >&2; return 2 ;;
  esac
  if [[ "$os" == "windows" ]]; then
    arch="amd64"
  fi
  echo "$ROOT_DIR/tools/bin/lc-auth-check-$os-$arch$ext"
}

require_cloud_auth() {
  local auth_bin
  auth_bin="$(select_auth_bin)"
  if [[ ! -f "$auth_bin" ]]; then
    echo "云端鉴权工具缺失，本轮不继续执行。" >&2
    exit 2
  fi
  case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
    darwin*)
      xattr -dr com.apple.quarantine "$ROOT_DIR/tools/bin" 2>/dev/null || true
      chmod +x "$ROOT_DIR"/tools/bin/lc-auth-check-darwin-* 2>/dev/null || true
      ;;
  esac
  chmod +x "$auth_bin" 2>/dev/null || true
  if ! "$auth_bin" --config "$ROOT_DIR/config.json" >/dev/null; then
    echo "云端鉴权未通过，本轮不继续执行。" >&2
    exit 4
  fi
}

ensure_installed() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Missing .venv. Run: ./lc-amazon-data-crawl.sh install" >&2
    exit 2
  fi
}

install_runner() {
  local python3_bin
  python3_bin="$(command -v python3 || true)"
  if [[ -z "$python3_bin" ]]; then
    echo "python3 is required." >&2
    exit 2
  fi
  if [[ ! -d "$ROOT_DIR/.venv" ]]; then
    "$python3_bin" -m venv "$ROOT_DIR/.venv"
  fi
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements.txt"
  "$PYTHON_BIN" -m playwright install chromium
}

doctor() {
  echo "runner: $ROOT_DIR"
  if [[ -x "$PYTHON_BIN" ]]; then
    echo "python: ok ($PYTHON_BIN)"
    "$PYTHON_BIN" -c "import playwright; print('playwright: ok')"
    "$PYTHON_BIN" -c "import selenium; print('selenium: ok')"
    "$PYTHON_BIN" "$ROOT_DIR/scripts/start_cdp_browser.py" --diagnose
  else
    echo "python: missing .venv"
  fi
  for file in \
    config/amazon_delivery_locations.json \
    config/amazon_front_keyword_search.json \
    config/amazon_front_storefront.json \
    config/amazon_front_bsr_category.json \
    config/category_rank_crawler.json \
    config/amazon_image_competitors.json \
    inputs/keywords.example.csv \
    inputs/storefronts.example.csv \
    inputs/image_competitors.example.csv; do
    if [[ -f "$ROOT_DIR/$file" ]]; then
      echo "$file: ok"
    else
      echo "$file: missing"
    fi
  done
  doubao_config_status
}

doubao_config_status() {
  local config_file="$ROOT_DIR/config/doubao_embedding_vision.json"
  local inspect_python status
  if [[ ! -f "$config_file" ]]; then
    echo "doubao_embedding_vision: missing"
    return
  fi
  if [[ -x "$PYTHON_BIN" ]]; then
    inspect_python="$PYTHON_BIN"
  else
    inspect_python="$(command -v python3 || true)"
  fi
  if [[ -z "$inspect_python" ]]; then
    echo "doubao_embedding_vision: unconfigured"
    return
  fi
  status="$($inspect_python - "$config_file" <<'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
    required = ("api_key", "model", "base_url", "api_path", "encoding_format")
    ready = isinstance(payload, dict) and all(
        isinstance(payload.get(field), str) and payload[field].strip()
        for field in required
    )
    print("ready" if ready else "unconfigured")
except (OSError, ValueError, TypeError):
    print("unconfigured")
PY
)"
  case "$status" in
    ready) echo "doubao_embedding_vision: ready" ;;
    *) echo "doubao_embedding_vision: unconfigured" ;;
  esac
}

auto_start_reuse_browser() {
  local default_config="$1"
  shift
  local config_path="$default_config"
  local previous=""
  local argument
  for argument in "$@"; do
    if [[ "$previous" == "--config" ]]; then
      config_path="$argument"
      previous=""
      continue
    fi
    case "$argument" in
      --config)
        previous="--config"
        ;;
      --config=*)
        config_path="${argument#--config=}"
        ;;
    esac
  done
  "$PYTHON_BIN" "$ROOT_DIR/scripts/start_cdp_browser.py" \
    --if-needed \
    --config "$config_path"
}

COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
  install)
    require_cloud_auth
    install_runner "$@"
    ;;
  doctor)
    require_cloud_auth
    doctor
    ;;
  amazon-front-dry-run)
    require_cloud_auth
    ensure_installed
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/run_amazon_front_crawl.py" --dry-run "$@"
    ;;
  amazon-front-run)
    require_cloud_auth
    ensure_installed
    auto_start_reuse_browser "config/amazon_front_crawler.json" "$@"
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/run_amazon_front_crawl.py" "$@"
    ;;
  category-rank-dry-run)
    require_cloud_auth
    ensure_installed
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/run_category_rank_crawl.py" --dry-run "$@"
    ;;
  category-rank-run)
    require_cloud_auth
    ensure_installed
    auto_start_reuse_browser "config/category_rank_crawler.json" "$@"
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/run_category_rank_crawl.py" "$@"
    ;;
  image-competitor-dry-run)
    require_cloud_auth
    ensure_installed
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/run_amazon_image_competitor_crawl.py" --dry-run "$@"
    ;;
  image-competitor-run)
    require_cloud_auth
    ensure_installed
    auto_start_reuse_browser "config/amazon_image_competitors.json" "$@"
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/run_amazon_image_competitor_crawl.py" "$@"
    ;;
  cdp-browser-start)
    require_cloud_auth
    ensure_installed
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/start_cdp_browser.py" "$@"
    ;;
  sellersprite-check)
    require_cloud_auth
    ensure_installed
    auto_start_reuse_browser "config/amazon_front_keyword_search.json" "$@"
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/run_sellersprite_check.py" "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: $COMMAND" >&2
    usage >&2
    exit 2
    ;;
esac
EOF

chmod +x "$TARGET_DIR/lc-amazon-data-crawl.sh"

echo "Created runner at: $TARGET_DIR"
echo "Next:"
echo "  cd \"$TARGET_DIR\""
echo "  ./lc-amazon-data-crawl.sh install"
echo "  ./lc-amazon-data-crawl.sh doctor"

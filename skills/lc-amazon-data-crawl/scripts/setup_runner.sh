#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-$PWD/lc-amazon-data-crawl-runner}"

# --allow-recent: inside install_for_user.sh the installer already verified
# auth (LC_AUTH_VERIFIED_AT, <=10 min); run standalone this always checks.
bash "$SKILL_DIR/scripts/check_auth.sh" --allow-recent

mkdir -p "$TARGET_DIR/scripts" "$TARGET_DIR/config" "$TARGET_DIR/inputs" "$TARGET_DIR/outputs" "$TARGET_DIR/chrome_profiles" "$TARGET_DIR/tools/bin"

for script_file in "$SKILL_DIR"/scripts/*.py; do
  case "$(basename "$script_file")" in
    # Skill-maintenance tools: nothing in a runner imports or calls them.
    migrate_unique_runner.py|package_skill.py) continue ;;
  esac
  cp "$script_file" "$TARGET_DIR/scripts/"
done
cp "$SKILL_DIR/scripts/check_auth.sh" "$TARGET_DIR/scripts/check_auth.sh"
# Windows entry points travel with every runner so it works on either OS.
if [[ -f "$SKILL_DIR/scripts/check_auth.ps1" ]]; then
  cp "$SKILL_DIR/scripts/check_auth.ps1" "$TARGET_DIR/scripts/check_auth.ps1"
fi
for launcher_file in lc-amazon-data-crawl.ps1 lc-amazon-data-crawl.cmd; do
  if [[ -f "$SKILL_DIR/scripts/runner/$launcher_file" ]]; then
    cp "$SKILL_DIR/scripts/runner/$launcher_file" "$TARGET_DIR/$launcher_file"
  fi
done
cp "$SKILL_DIR/assets/requirements.txt" "$TARGET_DIR/requirements.txt"
for config_file in "$SKILL_DIR"/assets/config/*.json; do
  config_name="$(basename "$config_file")"
  case "$config_name" in
    doubao_embedding_vision.example.json|doubao_same_product_mini.example.json)
      continue
      ;;
  esac
  target_config="$TARGET_DIR/config/$config_name"
  if [[ ! -f "$target_config" ]]; then
    cp "$config_file" "$target_config"
  fi
done

DOUBAO_CONFIG="$TARGET_DIR/config/doubao_embedding_vision.json"
if [[ ! -f "$DOUBAO_CONFIG" ]]; then
  (umask 077; cp "$SKILL_DIR/assets/config/doubao_embedding_vision.example.json" "$DOUBAO_CONFIG")
fi
chmod 600 "$DOUBAO_CONFIG" 2>/dev/null || true

DOUBAO_MINI_CONFIG="$TARGET_DIR/config/doubao_same_product_mini.json"
if [[ ! -f "$DOUBAO_MINI_CONFIG" ]]; then
  (umask 077; cp "$SKILL_DIR/assets/config/doubao_same_product_mini.example.json" "$DOUBAO_MINI_CONFIG")
fi
chmod 600 "$DOUBAO_MINI_CONFIG" 2>/dev/null || true

RUNNER_GITIGNORE="$TARGET_DIR/.gitignore"
touch "$RUNNER_GITIGNORE"
if ! grep -Fqx 'config/doubao_embedding_vision.json' "$RUNNER_GITIGNORE"; then
  printf '\n# Local API credentials\nconfig/doubao_embedding_vision.json\n' >> "$RUNNER_GITIGNORE"
fi
if ! grep -Fqx 'config/doubao_same_product_mini.json' "$RUNNER_GITIGNORE"; then
  printf 'config/doubao_same_product_mini.json\n' >> "$RUNNER_GITIGNORE"
fi
for ignored_path in 'outputs/' 'chrome_profiles/' '_archive/'; do
  if ! grep -Fqx "$ignored_path" "$RUNNER_GITIGNORE"; then
    printf '%s\n' "$ignored_path" >> "$RUNNER_GITIGNORE"
  fi
done
for ignored_path in '.venv/' '.venv-scrapling/' 'inputs/' 'config.local.json'; do
  if ! grep -Fqx "$ignored_path" "$RUNNER_GITIGNORE"; then
    printf '%s\n' "$ignored_path" >> "$RUNNER_GITIGNORE"
  fi
done
if [[ ! -f "$TARGET_DIR/config.json" ]]; then
  cp "$SKILL_DIR/config.json" "$TARGET_DIR/config.json"
fi
chmod 600 "$TARGET_DIR/config.json" 2>/dev/null || true
if [[ -f "$SKILL_DIR/config.local.json" && ! -f "$TARGET_DIR/config.local.json" ]]; then
  (umask 077; cp "$SKILL_DIR/config.local.json" "$TARGET_DIR/config.local.json")
fi
if [[ -f "$TARGET_DIR/config.local.json" ]]; then
  chmod 600 "$TARGET_DIR/config.local.json" 2>/dev/null || true
fi
if ! grep -Fqx 'config.json' "$RUNNER_GITIGNORE"; then
  printf 'config.json\n' >> "$RUNNER_GITIGNORE"
fi
if [[ -d "$SKILL_DIR/tools/bin" ]]; then
  cp "$SKILL_DIR"/tools/bin/* "$TARGET_DIR/tools/bin/"
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
python3 "$SKILL_DIR/scripts/migrate_operation_config.py" "$TARGET_DIR/config"

cat > "$TARGET_DIR/lc-amazon-data-crawl.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# POSIX venvs use bin/python; a venv created by Windows Python uses Scripts/python.exe.
venv_python() {
  if [[ ! -x "$1/bin/python" && -f "$1/Scripts/python.exe" ]]; then
    printf '%s\n' "$1/Scripts/python.exe"
  else
    printf '%s\n' "$1/bin/python"
  fi
}

VENV_DIR="$ROOT_DIR/.venv"
if [[ -x "$(venv_python "$ROOT_DIR/.venv-scrapling")" ]]; then
  VENV_DIR="$ROOT_DIR/.venv-scrapling"
fi
PYTHON_BIN="$(venv_python "$VENV_DIR")"

usage() {
  cat <<'USAGE'
Usage:
  ./lc-amazon-data-crawl.sh install
  ./lc-amazon-data-crawl.sh install-browser
  ./lc-amazon-data-crawl.sh doctor
  ./lc-amazon-data-crawl.sh amazon-front-dry-run [--config config/amazon_front_keyword_search.json] [--operation-mode supervised|unattended]
  ./lc-amazon-data-crawl.sh amazon-front-run [--config config/amazon_front_storefront.json] [--operation-mode supervised|unattended]
  ./lc-amazon-data-crawl.sh amazon-front-supervise --config config/<job>.json
  ./lc-amazon-data-crawl.sh verify-output --job outputs/<job> [--live]
  ./lc-amazon-data-crawl.sh category-rank-dry-run [--config config/category_rank_crawler.json]
  ./lc-amazon-data-crawl.sh category-rank-run [--config config/category_rank_crawler.json] [--operation-mode supervised|unattended]
  ./lc-amazon-data-crawl.sh image-competitor-dry-run [--config config/amazon_image_competitors.json]
  ./lc-amazon-data-crawl.sh image-competitor-run [--config config/amazon_image_competitors.json] [--operation-mode supervised|unattended]
  ./lc-amazon-data-crawl.sh cdp-browser-start --config <config-file>
  ./lc-amazon-data-crawl.sh sellersprite-check --config <config-file>
  ./lc-amazon-data-crawl.sh safety-status
  ./lc-amazon-data-crawl.sh safety-clear --confirm-reviewed
USAGE
}

require_cloud_auth() {
  bash "$ROOT_DIR/scripts/check_auth.sh" "$@"
}

ensure_installed() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "Missing .venv. Run: ./lc-amazon-data-crawl.sh install" >&2
    exit 2
  fi
}

install_runner() {
  local python3_bin candidate version
  python3_bin=""
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    candidate="$(command -v "$candidate" || true)"
    [[ -n "$candidate" ]] || continue
    version="$($candidate -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    case "$version" in 3.1[0-9]|3.[2-9][0-9]) python3_bin="$candidate"; break ;; esac
  done
  if [[ -z "$python3_bin" ]]; then
    echo "Scrapling requires Python 3.10 or newer." >&2
    exit 2
  fi
  if [[ -x "$PYTHON_BIN" ]] && ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    VENV_DIR="$ROOT_DIR/.venv-scrapling"
    PYTHON_BIN="$(venv_python "$VENV_DIR")"
  fi
  if [[ ! -x "$PYTHON_BIN" ]]; then
    "$python3_bin" -m venv "$VENV_DIR"
    PYTHON_BIN="$(venv_python "$VENV_DIR")"
  fi
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements.txt"
  # Deliberately no browser download here (it can fail on restricted or slow
  # CDN connections and is not needed when Chrome for Testing is already
  # installed): run install-browser once when doctor reports
  # chrome_for_testing: missing.
  "$PYTHON_BIN" -c "from playwright.sync_api import sync_playwright; print('playwright CDP runtime: ok')"
}

install_browser() {
  # Playwright's Chromium honors --load-extension (branded Chrome 137+ does
  # not) and start_cdp_browser.py's chrome_binary:auto finds it in the
  # ms-playwright cache on macOS, Linux and Windows.
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
  doubao_config_status \
    "doubao_embedding_vision" \
    "$ROOT_DIR/config/doubao_embedding_vision.json" \
    api_key model base_url api_path encoding_format
  doubao_config_status \
    "doubao_same_product_mini" \
    "$ROOT_DIR/config/doubao_same_product_mini.json" \
    api_key model base_url api_path
}

doubao_config_status() {
  local status_name="$1"
  local config_file="$2"
  local inspect_python status
  shift 2
  if [[ ! -f "$config_file" ]]; then
    echo "$status_name: missing"
    return
  fi
  if [[ -x "$PYTHON_BIN" ]]; then
    inspect_python="$PYTHON_BIN"
  else
    inspect_python="$(command -v python3 || true)"
  fi
  if [[ -z "$inspect_python" ]]; then
    echo "$status_name: unconfigured"
    return
  fi
  status="$($inspect_python - "$config_file" "$@" <<'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
    required = tuple(sys.argv[2:])
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
    ready) echo "$status_name: ready" ;;
    *) echo "$status_name: unconfigured" ;;
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
  # Never touch the browser while another crawl owns this machine.
  "$PYTHON_BIN" "$ROOT_DIR/scripts/safety_cli.py" guard
  "$PYTHON_BIN" "$ROOT_DIR/scripts/start_cdp_browser.py" \
    --if-needed \
    --config "$config_path"
}

COMMAND="${1:-help}"
shift || true

case "$COMMAND" in
  install)
    require_cloud_auth --allow-recent
    install_runner "$@"
    ;;
  install-browser)
    require_cloud_auth
    ensure_installed
    install_browser
    ;;
  doctor)
    require_cloud_auth --allow-recent
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
  amazon-front-supervise)
    require_cloud_auth
    ensure_installed
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/supervise_amazon_front.py" "$@"
    ;;
  verify-output)
    require_cloud_auth
    ensure_installed
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/verify_front_output.py" "$@"
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
  safety-status)
    ensure_installed
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/safety_cli.py" status
    ;;
  safety-clear)
    ensure_installed
    exec "$PYTHON_BIN" "$ROOT_DIR/scripts/safety_cli.py" clear "$@"
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

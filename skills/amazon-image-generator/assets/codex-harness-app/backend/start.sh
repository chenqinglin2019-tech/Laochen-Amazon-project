#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$APP_DIR/data/backend.pid"
LOG_FILE="$APP_DIR/data/backend.log"
APP_PORT="${FEIYUSHENTU_APP_PORT:-39081}"
HARNESS_ORIGIN_VALUE="${HARNESS_ORIGIN:-http://127.0.0.1:38080}"

if [[ "$(id -u)" == "0" ]]; then
  exec runuser -u skilldeck -- "$0" "$@"
fi

umask 027
if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(tr -cd '0-9' < "$PID_FILE")"
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "Backend already running with PID $existing_pid"
    exit 0
  fi
fi

nohup setsid env HARNESS_ORIGIN="$HARNESS_ORIGIN_VALUE" python3 "$APP_DIR/backend/server.py" --host 127.0.0.1 --port "$APP_PORT" </dev/null >> "$LOG_FILE" 2>&1 &
backend_pid=$!
printf '%s\n' "$backend_pid" > "$PID_FILE"
sleep 1
if ! kill -0 "$backend_pid" 2>/dev/null; then
  echo "Backend failed to start; check $LOG_FILE" >&2
  exit 1
fi
echo "Backend started with PID $backend_pid"

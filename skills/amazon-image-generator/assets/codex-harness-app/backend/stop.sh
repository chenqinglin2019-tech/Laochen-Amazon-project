#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$APP_DIR/data/backend.pid"

if [[ "$(id -u)" == "0" ]]; then
  exec runuser -u skilldeck -- "$0" "$@"
fi

if [[ ! -f "$PID_FILE" ]]; then
  echo "Backend is not running"
  exit 0
fi

backend_pid="$(tr -cd '0-9' < "$PID_FILE")"
if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
  kill "$backend_pid"
  for _attempt in {1..20}; do
    if ! kill -0 "$backend_pid" 2>/dev/null; then
      break
    fi
    sleep 0.1
  done
fi
: > "$PID_FILE"
echo "Backend stopped"

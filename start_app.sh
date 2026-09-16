#!/usr/bin/env bash
# Bambu AI Studio — one-click Linux/macOS launcher (same app as start_app.bat).
# Starts API + UI, then opens the browser when Vite is ready.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
UI_URL="http://127.0.0.1:5173"

open_browser() {
  for _ in $(seq 1 50); do
    if command -v curl >/dev/null 2>&1 && curl -sf -o /dev/null --max-time 1 "$UI_URL"; then
      if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$UI_URL" >/dev/null 2>&1 || true
      elif command -v open >/dev/null 2>&1; then
        open "$UI_URL" >/dev/null 2>&1 || true
      fi
      return 0
    fi
    sleep 0.4
  done
}

open_browser &
exec "$ROOT/run.sh" both

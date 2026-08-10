#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

start_api() {
  cd "$ROOT/backend"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export PYTHONPATH="$ROOT/backend"
  exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
}

start_ui() {
  cd "$ROOT/frontend"
  exec npm run dev
}

case "${1:-}" in
  api) start_api ;;
  ui) start_ui ;;
  *)
    echo "Usage: $0 {api|ui}"
    echo "  api  → FastAPI http://127.0.0.1:8000"
    echo "  ui   → Vite   http://127.0.0.1:5173"
    exit 1
    ;;
esac

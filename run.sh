#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

start_api() {
  cd "$ROOT/backend"
  if [[ ! -x .venv/bin/python ]]; then
    echo "[HATA] Backend sanal ortami bulunamadi!"
    echo "Lutfen backend klasorunde 'python3 -m venv .venv' calistirin."
    exit 1
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export PYTHONPATH="$ROOT:$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
  exec python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
}

start_ui() {
  cd "$ROOT/frontend"
  if [[ ! -d node_modules ]]; then
    echo "[HATA] Frontend bagimliliklari eksik!"
    echo "Lutfen frontend klasorunde 'npm install' calistirin."
    exit 1
  fi
  exec npm run dev
}

case "${1:-}" in
  api) start_api ;;
  ui) start_ui ;;
  *)
    echo "Usage: $0 {api|ui}"
    echo "  api  → FastAPI http://127.0.0.1:8000  (uvicorn main:app)"
    echo "  ui   → Vite   http://127.0.0.1:5173  (proxies /api → :8000)"
    exit 1
    ;;
esac

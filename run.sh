#!/usr/bin/env bash
# Local stack launcher for bambu_studio_ai (Vite + FastAPI).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="${ROOT}/.run"
API_PID_FILE="${PID_DIR}/api.pid"
UI_PID_FILE="${PID_DIR}/ui.pid"
API_LOG="${PID_DIR}/api.log"
UI_LOG="${PID_DIR}/ui.log"
API_PORT=8000
UI_PORT=5173

mkdir -p "$PID_DIR"

usage() {
  cat <<EOF
Usage: $0 {api|ui|both|status|stop|free-ports}

  api         Start FastAPI only  → http://127.0.0.1:${API_PORT}
  ui          Start Vite only     → http://127.0.0.1:${UI_PORT}
  both        Start API + UI in parallel (foreground, Ctrl+C stops both)
  status      Show who listens on ${UI_PORT} / ${API_PORT}
  stop        Stop processes started by this script (and free ports)
  free-ports  Kill anything listening on ${UI_PORT} / ${API_PORT}
EOF
}

# --- diagnostics / port hygiene ------------------------------------------------

pids_on_port() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  elif command -v fuser >/dev/null 2>&1; then
    fuser "${port}/tcp" 2>/dev/null || true
  elif command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :${port}" 2>/dev/null \
      | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true
  fi
}

show_status() {
  echo "=== Port status ==="
  for port in "$UI_PORT" "$API_PORT"; do
    echo "--- :${port} ---"
    if command -v ss >/dev/null 2>&1; then
      ss -ltnp "sport = :${port}" 2>/dev/null || echo "(nothing listening)"
    else
      lsof -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || echo "(nothing listening)"
    fi
    local pids
    pids="$(pids_on_port "$port" | tr '\n' ' ')"
    echo "PIDs: ${pids:-none}"
  done
  echo "=== Script PID files ==="
  for f in "$API_PID_FILE" "$UI_PID_FILE"; do
    if [[ -f "$f" ]]; then
      local p
      p="$(cat "$f")"
      if kill -0 "$p" 2>/dev/null; then
        echo "$(basename "$f"): $p (alive)"
      else
        echo "$(basename "$f"): $p (stale)"
      fi
    else
      echo "$(basename "$f"): (missing)"
    fi
  done
}

kill_pids() {
  local pids=("$@")
  [[ ${#pids[@]} -eq 0 ]] && return 0
  for p in "${pids[@]}"; do
    [[ -z "$p" ]] && continue
    if kill -0 "$p" 2>/dev/null; then
      echo "Stopping PID $p ..."
      kill "$p" 2>/dev/null || true
    fi
  done
  sleep 0.4
  for p in "${pids[@]}"; do
    [[ -z "$p" ]] && continue
    if kill -0 "$p" 2>/dev/null; then
      echo "Force-killing PID $p ..."
      kill -9 "$p" 2>/dev/null || true
    fi
  done
}

free_ports() {
  echo "Freeing ports ${UI_PORT} and ${API_PORT} ..."
  local collected=()
  local p
  for port in "$UI_PORT" "$API_PORT"; do
    while IFS= read -r p; do
      [[ -n "$p" ]] && collected+=("$p")
    done < <(pids_on_port "$port")
  done
  if [[ ${#collected[@]} -eq 0 ]]; then
    echo "No listeners on ${UI_PORT}/${API_PORT}."
    return 0
  fi
  # unique
  mapfile -t collected < <(printf '%s\n' "${collected[@]}" | sort -u)
  kill_pids "${collected[@]}"
  show_status
}

stop_managed() {
  local pids=()
  for f in "$API_PID_FILE" "$UI_PID_FILE"; do
    if [[ -f "$f" ]]; then
      pids+=("$(cat "$f")")
      rm -f "$f"
    fi
  done
  kill_pids "${pids[@]}"
  free_ports
}

# --- process starters ----------------------------------------------------------

start_api_fg() {
  cd "$ROOT/backend"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export PYTHONPATH="$ROOT:$ROOT/backend"
  exec uvicorn app.main:app --reload --host 127.0.0.1 --port "$API_PORT"
}

start_ui_fg() {
  cd "$ROOT/frontend"
  exec npm run dev -- --host 127.0.0.1 --port "$UI_PORT" --strictPort
}

start_both() {
  free_ports

  if [[ ! -d "$ROOT/backend/.venv" ]]; then
    echo "ERROR: backend/.venv missing. Create it first:"
    echo "  cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
  fi
  if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    echo "ERROR: frontend/node_modules missing. Run: cd frontend && npm install"
    exit 1
  fi

  cleanup() {
    echo ""
    echo "Shutting down both servers ..."
    stop_managed
  }
  trap cleanup EXIT INT TERM

  (
    cd "$ROOT/backend"
    # shellcheck disable=SC1091
    source .venv/bin/activate
    export PYTHONPATH="$ROOT:$ROOT/backend"
    exec uvicorn app.main:app --reload --host 127.0.0.1 --port "$API_PORT"
  ) >"$API_LOG" 2>&1 &
  echo $! >"$API_PID_FILE"
  echo "API  PID $(cat "$API_PID_FILE")  → http://127.0.0.1:${API_PORT}  (log: $API_LOG)"

  (
    cd "$ROOT/frontend"
    exec npm run dev -- --host 127.0.0.1 --port "$UI_PORT" --strictPort
  ) >"$UI_LOG" 2>&1 &
  echo $! >"$UI_PID_FILE"
  echo "UI   PID $(cat "$UI_PID_FILE")  → http://127.0.0.1:${UI_PORT}  (log: $UI_LOG)"

  # Ready when logs show listen banners (avoids false negatives from curl/sandbox).
  api_ready=0
  ui_ready=0
  for _ in $(seq 1 60); do
    if [[ "$api_ready" -eq 0 ]] && grep -q "Application startup complete\|Uvicorn running" "$API_LOG" 2>/dev/null; then
      api_ready=1
      echo "API ready."
    fi
    if [[ "$ui_ready" -eq 0 ]] && grep -q "Local:.*127.0.0.1:${UI_PORT}" "$UI_LOG" 2>/dev/null; then
      ui_ready=1
      echo "UI ready."
    fi
    if [[ "$api_ready" -eq 1 && "$ui_ready" -eq 1 ]]; then
      break
    fi
    sleep 0.25
  done

  if [[ "$api_ready" -ne 1 || "$ui_ready" -ne 1 ]]; then
    echo "Timed out waiting for servers."
    echo "--- API log ---"; tail -n 40 "$API_LOG" || true
    echo "--- UI log ---"; tail -n 40 "$UI_LOG" || true
    exit 1
  fi

  show_status
  echo "Both servers are up. Press Ctrl+C to stop both."
  wait
}

case "${1:-}" in
  api) start_api_fg ;;
  ui) start_ui_fg ;;
  both|up|dev) start_both ;;
  status) show_status ;;
  stop) stop_managed ;;
  free-ports|kill-ports) free_ports ;;
  *) usage; exit 1 ;;
esac

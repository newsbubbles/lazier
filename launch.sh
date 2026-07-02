#!/usr/bin/env bash
# lazier launcher (bash: Git Bash on Windows, or Linux/macOS)
# Frees the target ports (killing any listener by PID) then launches the
# service(s) in the background and streams their logs. Ctrl+C stops them.
#
#   ./launch.sh            # both (default)
#   ./launch.sh backend    # backend only
#   ./launch.sh frontend   # frontend only

set -uo pipefail

TARGET="${1:-both}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=5181
FRONTEND_PORT=5180

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) IS_WIN=1 ;;
  *) IS_WIN=0 ;;
esac

free_port() {
  local port="$1" pids procid
  if [ "$IS_WIN" = "1" ]; then
    # netstat -ano: last column is the PID; keep only LISTENING rows for this port
    pids=$(netstat -ano 2>/dev/null | grep -i 'LISTENING' | grep -E ":${port}\b" | awk '{print $NF}' | sort -u || true)
    for procid in $pids; do
      [ -n "$procid" ] && [ "$procid" != "0" ] || continue
      echo "killing PID $procid holding :$port"
      taskkill //F //PID "$procid" >/dev/null 2>&1 || true
    done
  else
    pids=$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)
    for procid in $pids; do
      echo "killing PID $procid holding :$port"
      kill -9 "$procid" 2>/dev/null || true
    done
  fi
  sleep 0.4
}

PIDS=()
cleanup() {
  echo
  echo "shutting down…"
  for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
  exit 0
}
trap cleanup INT TERM

start_backend() {
  free_port "$BACKEND_PORT"
  echo "starting backend on :$BACKEND_PORT"
  ( cd "$ROOT/backend" && exec uv run uvicorn lazier.main:app --port "$BACKEND_PORT" --host 127.0.0.1 ) &
  PIDS+=("$!")
}

start_frontend() {
  free_port "$FRONTEND_PORT"
  echo "starting frontend on :$FRONTEND_PORT"
  ( cd "$ROOT/frontend" && exec npm run dev ) &
  PIDS+=("$!")
}

case "$TARGET" in
  backend)  start_backend ;;
  frontend) start_frontend ;;
  both)     start_backend; start_frontend ;;
  -h|--help|help) echo "usage: $0 [both|backend|frontend]"; exit 0 ;;
  *) echo "usage: $0 [both|backend|frontend]"; exit 1 ;;
esac

echo "running: $TARGET (backend :$BACKEND_PORT, frontend :$FRONTEND_PORT) — Ctrl+C to stop"
wait

#!/usr/bin/env bash
# Start the MiroFish Flask backend headless (no web UI) and wait until /health answers.
# Usage: backend/claude_cli/start_server.sh [--sync]   (--sync runs `uv sync` first)
# Env: MIROFISH_PORT (default 5001), MIROFISH_LOG (default backend/logs/server.out),
#      MIROFISH_HEALTH_TIMEOUT seconds (default 90)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/.." && pwd)"
PORT="${MIROFISH_PORT:-5001}"
LOG="${MIROFISH_LOG:-$BACKEND/logs/server.out}"
PIDFILE="$BACKEND/logs/server.pid"
TIMEOUT="${MIROFISH_HEALTH_TIMEOUT:-90}"
mkdir -p "$(dirname "$LOG")" "$BACKEND/logs"

health() { curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; }

if health; then
  echo "{\"status\":\"already_running\",\"url\":\"http://localhost:${PORT}\",\"pid\":\"$(cat "$PIDFILE" 2>/dev/null || echo unknown)\"}"
  exit 0
fi
if [ ! -f "$BACKEND/../.env" ]; then
  echo "warning: $BACKEND/../.env not found; copy .env.example and set LLM_API_KEY" >&2
fi

cd "$BACKEND"
UV_ARGS=(run --no-sync)
if [ "${1:-}" = "--sync" ] || [ ! -d "$BACKEND/.venv" ]; then UV_ARGS=(run); fi
FLASK_PORT="$PORT" FLASK_DEBUG=False PYTHONUNBUFFERED=1 \
  nohup uv "${UV_ARGS[@]}" python run.py >"$LOG" 2>&1 &
echo $! >"$PIDFILE"

for _ in $(seq 1 "$TIMEOUT"); do
  if health; then
    echo "{\"status\":\"started\",\"url\":\"http://localhost:${PORT}\",\"pid\":$(cat "$PIDFILE"),\"log\":\"$LOG\"}"
    exit 0
  fi
  if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "backend exited during startup; last log lines:" >&2
    tail -n 40 "$LOG" >&2
    exit 1
  fi
  sleep 1
done
echo "backend did not become healthy within ${TIMEOUT}s; see $LOG" >&2
tail -n 40 "$LOG" >&2
exit 1

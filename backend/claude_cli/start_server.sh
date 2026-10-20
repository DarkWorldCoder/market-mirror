#!/usr/bin/env bash
# Start the MiroFish Flask backend headless (no web UI) and wait until /health answers.
# Usage: backend/claude_cli/start_server.sh [--sync] [--port N] [--env-file F] [--upload-dir D]
#   --sync        run `uv sync` first
#   --port N      listen on N (default MIROFISH_PORT or 5001)
#   --env-file F  settings for this instance (MIROFISH_ENV_FILE; default the repository .env)
#   --upload-dir D  this instance's data: projects, simulations, local_graph.db, tasks (MIROFISH_UPLOAD_DIR;
#                 default backend/uploads on 5001, backend/uploads-<port> on any other port)
# Several instances run side by side, one per port, each with its own pid/log file and data directory:
#   start_server.sh --port 5011 --env-file .env.claude
#   start_server.sh --port 5012 --env-file .env.codex
#   start_server.sh --port 5013 --env-file .env.antigravity
# Env: MIROFISH_PORT, MIROFISH_LOG (default backend/logs/server.out, server-<port>.out on other ports),
#      MIROFISH_HEALTH_TIMEOUT seconds (default 90)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/.." && pwd)"
SYNC=0
PORT="${MIROFISH_PORT:-5001}"
ENV_FILE="${MIROFISH_ENV_FILE:-}"
UPLOAD_DIR="${MIROFISH_UPLOAD_DIR:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --sync) SYNC=1 ;;
    --port) PORT="$2"; shift ;;
    --port=*) PORT="${1#*=}" ;;
    --env-file) ENV_FILE="$2"; shift ;;
    --env-file=*) ENV_FILE="${1#*=}" ;;
    --upload-dir) UPLOAD_DIR="$2"; shift ;;
    --upload-dir=*) UPLOAD_DIR="${1#*=}" ;;
    *) echo "unknown argument: $1 (usage: start_server.sh [--sync] [--port N] [--env-file F] [--upload-dir D])" >&2; exit 2 ;;
  esac
  shift
done
case "$PORT" in ''|*[!0-9]*) echo "--port must be a number" >&2; exit 2 ;; esac
if [ "$PORT" = 5001 ]; then SUFFIX=""; else SUFFIX="-$PORT"; fi
LOG="${MIROFISH_LOG:-$BACKEND/logs/server$SUFFIX.out}"
PIDFILE="$BACKEND/logs/server$SUFFIX.pid"
TIMEOUT="${MIROFISH_HEALTH_TIMEOUT:-90}"
if [ -z "$UPLOAD_DIR" ] && [ "$PORT" != 5001 ]; then UPLOAD_DIR="$BACKEND/uploads$SUFFIX"; fi
if [ -n "$ENV_FILE" ]; then
  case "$ENV_FILE" in /*) ;; *) ENV_FILE="$(cd "$(dirname "$ENV_FILE")" && pwd)/$(basename "$ENV_FILE")" ;; esac
  [ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }
fi
if [ -n "$UPLOAD_DIR" ]; then
  mkdir -p "$UPLOAD_DIR"; UPLOAD_DIR="$(cd "$UPLOAD_DIR" && pwd)"
fi
mkdir -p "$(dirname "$LOG")" "$BACKEND/logs"

health() { curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; }

if health; then
  echo "{\"status\":\"already_running\",\"url\":\"http://localhost:${PORT}\",\"pid\":\"$(cat "$PIDFILE" 2>/dev/null || echo unknown)\"}"
  exit 0
fi
if [ -z "$ENV_FILE" ] && [ ! -f "$BACKEND/../.env" ]; then
  echo "warning: $BACKEND/../.env not found; copy .env.example and set LLM_API_KEY" >&2
fi

cd "$BACKEND"
UV_ARGS=(run --no-sync)
if [ "$SYNC" = 1 ] || [ ! -d "$BACKEND/.venv" ]; then UV_ARGS=(run); fi
if command -v uv >/dev/null 2>&1; then
  RUN=(uv "${UV_ARGS[@]}" python)
elif [ -x "$BACKEND/.venv/bin/python" ] && [ "$SYNC" != 1 ]; then
  RUN=("$BACKEND/.venv/bin/python")          # uv not on PATH: the environment is already installed, use it
else
  echo "uv is not installed and backend/.venv is missing; run bash install.sh first" >&2
  exit 1
fi
EXTRA_ENV=()
[ -n "$ENV_FILE" ] && EXTRA_ENV+=("MIROFISH_ENV_FILE=$ENV_FILE")
[ -n "$UPLOAD_DIR" ] && EXTRA_ENV+=("MIROFISH_UPLOAD_DIR=$UPLOAD_DIR")
env ${EXTRA_ENV[@]+"${EXTRA_ENV[@]}"} FLASK_PORT="$PORT" FLASK_DEBUG=False PYTHONUNBUFFERED=1 \
  nohup "${RUN[@]}" run.py >"$LOG" 2>&1 &
echo $! >"$PIDFILE"

for _ in $(seq 1 "$TIMEOUT"); do
  if health; then
    echo "{\"status\":\"started\",\"url\":\"http://localhost:${PORT}\",\"pid\":$(cat "$PIDFILE"),\"log\":\"$LOG\",\"env_file\":\"${ENV_FILE:-$BACKEND/../.env}\",\"upload_dir\":\"${UPLOAD_DIR:-$BACKEND/uploads}\"}"
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

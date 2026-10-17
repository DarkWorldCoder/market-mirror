#!/usr/bin/env bash
# Manage the optional Cognee memory sidecar (MEMORY_BACKEND=cognee).
#   setup   create backend/memory_sidecar/.venv and install cognee (separate from backend/.venv)
#   start   run the sidecar in the background (log: backend/logs/cognee_sidecar.out)
#   stop    stop it
#   status  print /health
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(dirname "$HERE")"
VENV="$HERE/.venv"
PY="$VENV/bin/python"
PIDFILE="$BACKEND/logs/cognee_sidecar.pid"
LOG="$BACKEND/logs/cognee_sidecar.out"
HOST="${COGNEE_SIDECAR_HOST:-127.0.0.1}"
PORT="${COGNEE_SIDECAR_PORT:-8765}"
URL="http://$HOST:$PORT"

case "${1:-}" in
  setup)
    if command -v uv >/dev/null 2>&1; then
      uv venv --python 3.12 "$VENV"
      VIRTUAL_ENV="$VENV" uv pip install --python "$PY" -r "$HERE/requirements.txt"
    else
      python3 -m venv "$VENV"
      "$PY" -m pip install --upgrade pip
      "$PY" -m pip install -r "$HERE/requirements.txt"
    fi
    "$PY" -c "import cognee; print('cognee', cognee.__version__, 'installed in', '$VENV')"
    ;;
  start)
    [ -x "$PY" ] || { echo "run: $0 setup" >&2; exit 1; }
    mkdir -p "$BACKEND/logs"
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "{\"ok\": true, \"already_running\": true, \"url\": \"$URL\"}"; exit 0
    fi
    COGNEE_SIDECAR_HOST="$HOST" COGNEE_SIDECAR_PORT="$PORT" \
      nohup "$PY" "$HERE/cognee_server.py" >"$LOG" 2>&1 &
    echo $! >"$PIDFILE"
    for _ in $(seq 1 90); do
      if curl -fsS "$URL/health" >/dev/null 2>&1; then
        echo "{\"ok\": true, \"url\": \"$URL\", \"pid\": $(cat "$PIDFILE"), \"log\": \"$LOG\"}"; exit 0
      fi
      kill -0 "$(cat "$PIDFILE")" 2>/dev/null || break
      sleep 1
    done
    echo "{\"ok\": false, \"log\": \"$LOG\"}"; tail -20 "$LOG" >&2; exit 1
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then kill "$(cat "$PIDFILE")" 2>/dev/null || true; rm -f "$PIDFILE"; fi
    echo '{"ok": true, "stopped": true}'
    ;;
  status)
    curl -fsS "$URL/health" || { echo "{\"ok\": false, \"url\": \"$URL\"}"; exit 1; }
    echo
    ;;
  *)
    echo "usage: $0 {setup|start|stop|status}" >&2; exit 2
    ;;
esac

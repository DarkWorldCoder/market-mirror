#!/usr/bin/env bash
# Stop the backend started by start_server.sh on one port (and any run.py still bound to that port).
# Usage: backend/claude_cli/stop_server.sh [--port N]   (default MIROFISH_PORT or 5001)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/.." && pwd)"
PORT="${MIROFISH_PORT:-5001}"
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift ;;
    --port=*) PORT="${1#*=}" ;;
    *) echo "unknown argument: $1 (usage: stop_server.sh [--port N])" >&2; exit 2 ;;
  esac
  shift
done
case "$PORT" in ''|*[!0-9]*) echo "--port must be a number" >&2; exit 2 ;; esac
if [ "$PORT" = 5001 ]; then SUFFIX=""; else SUFFIX="-$PORT"; fi
PIDFILE="$BACKEND/logs/server$SUFFIX.pid"
stopped=0
kill_tree() {  # kill a pid and its descendants (uv -> python run.py -> simulation subprocesses)
  local pid=$1
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null && stopped=1
}
if [ -f "$PIDFILE" ]; then
  kill_tree "$(cat "$PIDFILE")"
  rm -f "$PIDFILE"
fi
# Fallback: our run.py whose FLASK_PORT is this port (other instances on other ports are left alone)
for pid in $(pgrep -f "python run.py" 2>/dev/null); do
  [ "$(readlink -f /proc/$pid/cwd 2>/dev/null)" = "$BACKEND" ] || continue
  pport=$(tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | sed -n 's/^FLASK_PORT=//p' | head -n1)
  if [ "${pport:-5001}" = "$PORT" ]; then kill_tree "$pid"; fi
done
for _ in $(seq 1 10); do
  curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 || break
  sleep 1
done
if curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "{\"status\":\"still_running\",\"port\":${PORT}}"; exit 1
fi
echo "{\"status\":\"$([ $stopped = 1 ] && echo stopped || echo not_running)\",\"port\":${PORT}}"

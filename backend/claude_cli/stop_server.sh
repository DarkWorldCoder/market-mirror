#!/usr/bin/env bash
# Stop the backend started by start_server.sh (and any run.py still bound to the port).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/.." && pwd)"
PORT="${MIROFISH_PORT:-5001}"
PIDFILE="$BACKEND/logs/server.pid"
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
# Fallback: anything still listening on the port that is our run.py
for pid in $(pgrep -f "python run.py" 2>/dev/null); do
  if [ "$(readlink -f /proc/$pid/cwd 2>/dev/null)" = "$BACKEND" ]; then kill_tree "$pid"; fi
done
for _ in $(seq 1 10); do
  curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 || break
  sleep 1
done
if curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "{\"status\":\"still_running\",\"port\":${PORT}}"; exit 1
fi
echo "{\"status\":\"$([ $stopped = 1 ] && echo stopped || echo not_running)\"}"

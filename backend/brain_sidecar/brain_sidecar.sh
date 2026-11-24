#!/usr/bin/env bash
# Manage the optional TRIBE v2 brain-response sidecar (MM_BRAIN_RESPONSE_URL).
#   setup   create backend/brain_sidecar/.venv and install tribev2 (needs MM_TRIBE_ACCEPT_NONCOMMERCIAL=1)
#   start   run the server in the background on 127.0.0.1:7860 (log: backend/logs/brain_sidecar.out)
#   stop    stop it
#   status  print /health
# A GPU is needed in practice. Most owners run the Colab notebook instead (colab/MarketMirror_TRIBE_v2.ipynb).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(dirname "$HERE")"
VENV="$HERE/.venv"
PY="$VENV/bin/python"
PIDFILE="$BACKEND/logs/brain_sidecar.pid"
LOG="$BACKEND/logs/brain_sidecar.out"
HOST="${MM_TRIBE_HOST:-127.0.0.1}"
PORT="${MM_TRIBE_PORT:-7860}"
URL="http://$HOST:$PORT"

license_text() {
  cat <<EOF
TRIBE v2 (Meta, facebook/tribev2) is licensed CC BY-NC 4.0: noncommercial use only, for the code and the weights.
Its text encoder is meta-llama/Llama-3.2-3B, which is gated. Before setup, the owner must:
  1. Accept the Llama 3.2 license at https://huggingface.co/meta-llama/Llama-3.2-3B (with their own account).
  2. Create a read token at https://huggingface.co/settings/tokens and run:  huggingface-cli login
     (type the token yourself; MarketMirror never stores or prints it).
  3. Have a CUDA GPU (or use the Colab notebook: backend/brain_sidecar/colab/MarketMirror_TRIBE_v2.ipynb).
It predicts average-viewer brain activity only: not attention, feelings, memory or buying. Not validated for ads.
To accept the noncommercial license and continue:  MM_TRIBE_ACCEPT_NONCOMMERCIAL=1 $0 setup
EOF
}

case "${1:-}" in
  setup)
    if [ "${MM_TRIBE_ACCEPT_NONCOMMERCIAL:-}" != "1" ]; then
      license_text >&2
      exit 3
    fi
    license_text
    if command -v uv >/dev/null 2>&1; then
      uv venv --python 3.11 "$VENV"
      VIRTUAL_ENV="$VENV" uv pip install --python "$PY" -r "$HERE/requirements.txt"
    else
      python3 -m venv "$VENV"
      "$PY" -m pip install --upgrade pip
      "$PY" -m pip install -r "$HERE/requirements.txt"
    fi
    "$PY" -c "import tribev2, nilearn; print('tribev2 and nilearn installed in', '$VENV')"
    echo "Weights (~1 GB) download on the first prediction into \${MM_TRIBE_CACHE:-./cache}."
    ;;
  start)
    [ -x "$PY" ] || { echo "run: MM_TRIBE_ACCEPT_NONCOMMERCIAL=1 $0 setup" >&2; exit 1; }
    mkdir -p "$BACKEND/logs"
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "{\"ok\": true, \"already_running\": true, \"url\": \"$URL\"}"; exit 0
    fi
    MM_TRIBE_HOST="$HOST" MM_TRIBE_PORT="$PORT" MM_TRIBE_CACHE="${MM_TRIBE_CACHE:-$HERE/cache}" \
      nohup "$PY" "$HERE/tribe_server.py" >"$LOG" 2>&1 &
    echo $! >"$PIDFILE"
    for _ in $(seq 1 60); do
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
  license)
    license_text
    ;;
  *)
    echo "usage: $0 {setup|start|stop|status|license}" >&2; exit 2
    ;;
esac

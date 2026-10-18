#!/usr/bin/env bash
# mm.sh - MarketMirror helper for agents: simulated buyers, ad/message/price tests (MiroFish engine).
#
#   mm.sh setup                 clone or update the engine, install Python deps, create .env
#   mm.sh doctor                check repo, deps, API key (never printed) and backend
#   mm.sh start | stop          start or stop the backend (port 5001)
#   mm.sh scenario NAME FILE... copy documents into <home>/scenarios/NAME/ and print that folder
#   mm.sh cli ARGS...           run the MiroFish CLI from the engine folder (see its --help)
#   mm.sh live [ARGS...]        serve the live dashboard on http://127.0.0.1:5050/ (foreground)
#   mm.sh gateway start|stop|status [claude|codex]   run without an API key on your Claude Code or ChatGPT login
#   mm.sh home                  print the engine folder
#   mm.sh mcp                   run the MCP server (stdio) exposing all of this as agent tools
#
# Environment: MARKET_MIRROR_HOME (default ~/.market-mirror/engine; MIROFISH_HOME also accepted),
#              MARKET_MIRROR_REPO (default https://github.com/DarkWorldCoder/market-mirror.git)
set -euo pipefail

REPO_URL="${MARKET_MIRROR_REPO:-${MIROFISH_REPO:-https://github.com/DarkWorldCoder/market-mirror.git}}"
HOME_DIR="${MARKET_MIRROR_HOME:-${MIROFISH_HOME:-$HOME/.market-mirror/engine}}"
PY="$HOME_DIR/backend/.venv/bin/python"
CLI="$HOME_DIR/backend/claude_cli/mirofish.py"

say() { printf '%s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }

key_status() {
  # Reports whether a key is configured without ever reading it into a variable or printing it.
  local env="$HOME_DIR/.env"
  if [ -n "${ANTHROPIC_API_KEY:-}" ] || [ -n "${LLM_API_KEY:-}" ]; then echo "set (environment)"; return; fi
  [ -f "$env" ] || { echo "missing (.env not created)"; return; }
  if grep -Eq '^LLM_API_KEY=[[:space:]]*("|'"'"')?(your_api_key_here)?("|'"'"')?[[:space:]]*$' "$env" \
     || ! grep -Eq '^LLM_API_KEY=' "$env"; then
    echo "missing (edit LLM_API_KEY in $env)"
  else
    echo "set (.env)"
  fi
}

backend_up() { curl -fsS -m 3 "${MIROFISH_URL:-http://localhost:5001}/health" >/dev/null 2>&1; }

doctor() {
  local ok=1
  [ -d "$HOME_DIR/.git" ] && say "engine:  $HOME_DIR" || { say "engine:  missing (run: mm.sh setup)"; ok=0; }
  [ -x "$PY" ] && say "python:  $("$PY" --version 2>&1)" || { say "python:  deps not installed (run: mm.sh setup)"; ok=0; }
  local k; k=$(key_status); say "api key: $k"
  case $k in set*) ;; *)
    if grep -Eq '^LLM_BASE_URL=http://127\.0\.0\.1:5055' "$HOME_DIR/.env" 2>/dev/null; then
      say "gateway: configured (LLM_GATEWAY=$(grep -E '^LLM_GATEWAY=' "$HOME_DIR/.env" | cut -d= -f2-)); $(curl -fsS -m 2 http://127.0.0.1:5055/health >/dev/null 2>&1 && echo running || echo 'stopped (run: mm.sh gateway start)')"
    else
      ok=0
      command -v claude >/dev/null && say "no key, but 'claude' is installed: 'mm.sh gateway start claude' runs on your Claude Code login (personal use)"
      command -v codex  >/dev/null && say "no key, but 'codex' is installed: 'mm.sh gateway start codex' runs on your ChatGPT login (personal use)"
    fi ;;
  esac
  if [ -f "$HOME_DIR/.env" ]; then
    say "model:   $(grep -E '^LLM_MODEL_NAME=' "$HOME_DIR/.env" | cut -d= -f2- || true)"
    say "memory:  $(grep -E '^MEMORY_BACKEND=' "$HOME_DIR/.env" | cut -d= -f2- || true)"
  fi
  backend_up && say "backend: running" || say "backend: stopped (run: mm.sh start)"
  [ $ok -eq 1 ] && say "ready" || { say "not ready"; return 1; }
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  home) echo "$HOME_DIR" ;;
  setup)
    command -v git >/dev/null || die "git is required"
    if [ -d "$HOME_DIR/.git" ]; then
      say "updating $HOME_DIR"; git -C "$HOME_DIR" pull --ff-only -q || say "warning: could not fast-forward; keeping the current version"
    else
      say "cloning $REPO_URL -> $HOME_DIR"; mkdir -p "$(dirname "$HOME_DIR")"; git clone -q --depth 1 "$REPO_URL" "$HOME_DIR"
    fi
    command -v uv >/dev/null || die "uv is required. Install it with one of: 'brew install uv', 'pipx install uv', 'pip install uv' (see https://docs.astral.sh/uv/), then run setup again"
    say "installing Python deps (first time takes a few minutes)"
    (cd "$HOME_DIR/backend" && uv sync -q --python 3.12)
    [ -f "$HOME_DIR/.env" ] || { cp "$HOME_DIR/.env.example" "$HOME_DIR/.env"; say "created $HOME_DIR/.env"; }
    doctor || true
    ;;
  doctor) doctor ;;
  start)
    [ -x "$PY" ] || die "not set up yet (run: mm.sh setup)"
    case $(key_status) in set*) ;; *) die "no API key: $(key_status)" ;; esac
    cd "$HOME_DIR" && bash backend/claude_cli/start_server.sh
    ;;
  stop) cd "$HOME_DIR" && bash backend/claude_cli/stop_server.sh ;;
  scenario)
    name="${1:-}"; [ -n "$name" ] || die "usage: mm.sh scenario NAME FILE..."; shift
    case "$name" in .*|*[!A-Za-z0-9._-]*) die "scenario name must start with a letter or digit and use only letters, digits, . _ -" ;; esac
    dir="$HOME_DIR/scenarios/$name"; mkdir -p "$dir"
    for f in "$@"; do [ -f "$f" ] || die "not a file: $f"; cp "$f" "$dir/"; done
    echo "$dir"
    ;;
  cli)
    [ -x "$PY" ] || die "not set up yet (run: mm.sh setup)"
    cd "$HOME_DIR" && exec "$PY" "$CLI" "$@"
    ;;
  live)
    [ -x "$PY" ] || die "not set up yet (run: mm.sh setup)"
    cd "$HOME_DIR" && exec "$PY" "$CLI" live "$@"
    ;;
  gateway)
    [ -x "$PY" ] || die "not set up yet (run: mm.sh setup)"
    sub="${1:-status}"; be="${2:-$(grep -E '^LLM_GATEWAY=' "$HOME_DIR/.env" 2>/dev/null | cut -d= -f2-)}"; be="${be:-claude}"
    pidf="$HOME_DIR/backend/logs/gateway.pid"; mkdir -p "$HOME_DIR/backend/logs"
    case "$sub" in
      start)
        command -v "$be" >/dev/null || die "'$be' CLI not found on PATH (install it and log in first)"
        if curl -fsS -m 2 http://127.0.0.1:5055/health >/dev/null 2>&1; then say "gateway already running"; else
          (cd "$HOME_DIR" && nohup "$PY" backend/gateway/local_gateway.py --backend "$be" > backend/logs/gateway.out 2>&1 & echo $! > "$pidf")
          for i in 1 2 3 4 5 6 7 8 9 10; do curl -fsS -m 1 http://127.0.0.1:5055/health >/dev/null 2>&1 && break; sleep 0.5; done
          say "gateway started ($be) on http://127.0.0.1:5055/v1"
        fi
        # point the engine at it (keeps a real key if one is set)
        if ! grep -Eq '^LLM_BASE_URL=http://127\.0\.0\.1:5055' "$HOME_DIR/.env" 2>/dev/null; then
          { grep -Ev '^(LLM_PROVIDER|LLM_BASE_URL|LLM_API_KEY|LLM_GATEWAY|LLM_MODEL_NAME)=' "$HOME_DIR/.env" 2>/dev/null
            printf 'LLM_PROVIDER=openai\nLLM_BASE_URL=http://127.0.0.1:5055/v1\nLLM_API_KEY=gateway\nLLM_GATEWAY=%s\nLLM_MODEL_NAME=%s\n' "$be" "$be"; } > "$HOME_DIR/.env.tmp"
          mv "$HOME_DIR/.env.tmp" "$HOME_DIR/.env"; say "wrote gateway settings to $HOME_DIR/.env (restart the backend: mm.sh stop && mm.sh start)"
        fi ;;
      stop) [ -f "$pidf" ] && kill "$(cat "$pidf")" 2>/dev/null && rm -f "$pidf" && say "gateway stopped" || say "gateway not running" ;;
      status) curl -fsS -m 2 http://127.0.0.1:5055/health 2>/dev/null || say "gateway stopped" ;;
      *) die "usage: mm.sh gateway start|stop|status [claude|codex]" ;;
    esac ;;
  mcp) exec python3 "$(dirname "$0")/mcp_server.py" ;;
  help|-h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command '$cmd' (try: mm.sh help)" ;;
esac

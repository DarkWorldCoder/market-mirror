#!/usr/bin/env bash
# mf.sh - helper for agents running MiroFish (swarm simulation) on any machine.
#
#   mf.sh setup                 clone or update the engine, install Python deps, create .env
#   mf.sh doctor                check repo, deps, API key (never printed) and backend
#   mf.sh start | stop          start or stop the backend (port 5001)
#   mf.sh scenario NAME FILE... copy documents into <home>/scenarios/NAME/ and print that folder
#   mf.sh cli ARGS...           run the MiroFish CLI from the engine folder (see its --help)
#   mf.sh live [ARGS...]        serve the live dashboard on http://127.0.0.1:5050/ (foreground)
#   mf.sh home                  print the engine folder
#
# Environment: MIROFISH_HOME (default ~/.mirofish/mirofish-claude),
#              MIROFISH_REPO (default https://github.com/DarkWorldCoder/mirofish-claude.git)
set -euo pipefail

REPO_URL="${MIROFISH_REPO:-https://github.com/DarkWorldCoder/mirofish-claude.git}"
HOME_DIR="${MIROFISH_HOME:-$HOME/.mirofish/mirofish-claude}"
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
  [ -d "$HOME_DIR/.git" ] && say "engine:  $HOME_DIR" || { say "engine:  missing (run: mf.sh setup)"; ok=0; }
  [ -x "$PY" ] && say "python:  $("$PY" --version 2>&1)" || { say "python:  deps not installed (run: mf.sh setup)"; ok=0; }
  local k; k=$(key_status); say "api key: $k"; case $k in set*) ;; *) ok=0 ;; esac
  if [ -f "$HOME_DIR/.env" ]; then
    say "model:   $(grep -E '^LLM_MODEL_NAME=' "$HOME_DIR/.env" | cut -d= -f2- || true)"
    say "memory:  $(grep -E '^MEMORY_BACKEND=' "$HOME_DIR/.env" | cut -d= -f2- || true)"
  fi
  backend_up && say "backend: running" || say "backend: stopped (run: mf.sh start)"
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
    [ -x "$PY" ] || die "not set up yet (run: mf.sh setup)"
    case $(key_status) in set*) ;; *) die "no API key: $(key_status)" ;; esac
    cd "$HOME_DIR" && bash backend/claude_cli/start_server.sh
    ;;
  stop) cd "$HOME_DIR" && bash backend/claude_cli/stop_server.sh ;;
  scenario)
    name="${1:-}"; [ -n "$name" ] || die "usage: mf.sh scenario NAME FILE..."; shift
    case "$name" in .*|*[!A-Za-z0-9._-]*) die "scenario name must start with a letter or digit and use only letters, digits, . _ -" ;; esac
    dir="$HOME_DIR/scenarios/$name"; mkdir -p "$dir"
    for f in "$@"; do [ -f "$f" ] || die "not a file: $f"; cp "$f" "$dir/"; done
    echo "$dir"
    ;;
  cli)
    [ -x "$PY" ] || die "not set up yet (run: mf.sh setup)"
    cd "$HOME_DIR" && exec "$PY" "$CLI" "$@"
    ;;
  live)
    [ -x "$PY" ] || die "not set up yet (run: mf.sh setup)"
    cd "$HOME_DIR" && exec "$PY" "$CLI" live "$@"
    ;;
  help|-h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command '$cmd' (try: mf.sh help)" ;;
esac

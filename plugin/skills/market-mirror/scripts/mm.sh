#!/usr/bin/env bash
# mm.sh - MarketMirror helper for agents: simulated buyers, ad/message/price tests (MiroFish engine).
#
#   mm.sh setup                 clone or update the engine, install Python deps, create .env
#   mm.sh doctor                check repo, deps, API key (never printed) and backend
#   mm.sh configure             choose local models, hosted API, or a login gateway (hidden key input)
#   mm.sh provider ACTION       list/status/check/configure provider settings; use --key-env for agent setup
#   mm.sh agent-config          print portable MCP config (--client codex|claude|cursor|gemini|generic)
#   mm.sh start | stop [--port N] [--env-file F]   start or stop a backend (default port 5001; other ports keep
#                               their data in backend/uploads-<port>, so several backends run side by side)
#   mm.sh scenario NAME FILE... copy documents into <home>/scenarios/NAME/ and print that folder
#   mm.sh cli ARGS...           run the MiroFish CLI from the engine folder (see its --help)
#   mm.sh live [ARGS...]        serve the live dashboard on http://127.0.0.1:5050/ (foreground)
#   mm.sh gateway login|start|stop|status [claude|codex|gemini|antigravity|chatgpt|siwc|multi] [--port N] [--model M]
#                               local login gateway (default port 5055, writes .env); --port N runs another one
#                               side by side and writes .env.<backend> for a backend started with --env-file
#   mm.sh home                  print the engine folder
#   mm.sh mcp                   run the MCP server (stdio) exposing all of this as agent tools
#
# Environment: MARKET_MIRROR_HOME (default ~/.market-mirror/engine; MIROFISH_HOME also accepted),
#              MARKET_MIRROR_REPO (default https://github.com/DarkWorldCoder/market-mirror.git)
set -euo pipefail

REPO_URL="${MARKET_MIRROR_REPO:-${MIROFISH_REPO:-https://github.com/DarkWorldCoder/market-mirror.git}}"
HOME_DIR="${MARKET_MIRROR_HOME:-${MIROFISH_HOME:-}}"
if [ -z "$HOME_DIR" ]; then
  registry="${MARKET_MIRROR_CONFIG_DIR:-$HOME/.market-mirror}/engine.json"
  HOME_DIR=$(python3 - "$registry" <<'PY'
import json,sys
from pathlib import Path
try:
    candidate = Path(json.loads(Path(sys.argv[1]).read_text())["path"])
    if candidate.is_absolute() and (candidate / "backend/claude_cli/mirofish.py").is_file():
        print(candidate)
except (OSError, ValueError, KeyError, TypeError):
    pass
PY
  )
  HOME_DIR="${HOME_DIR:-$HOME/.market-mirror/engine}"
fi
PY="$HOME_DIR/backend/.venv/bin/python"
CLI="$HOME_DIR/backend/claude_cli/mirofish.py"

say() { printf '%s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }

key_status() {
  # Reports whether a key is configured without ever reading it into a variable or printing it.
  local env="$HOME_DIR/.env"
  # hosted OpenAI-compatible providers (API_PROVIDERS in backend/app/utils/model_pool.py)
  local hosted="DEEPSEEK MOONSHOT KIMI MISTRAL XAI GROK GROQ TOGETHER FIREWORKS OPENROUTER DASHSCOPE QWEN ZAI ZHIPU CEREBRAS MINIMAX"
  if [ -n "${ANTHROPIC_API_KEY:-}" ] || [ -n "${GEMINI_API_KEY:-}" ] || [ -n "${GOOGLE_API_KEY:-}" ] || [ -n "${OPENAI_API_KEY:-}" ] || [ -n "${LLM_API_KEY:-}" ]; then echo "set (environment)"; return; fi
  local name; for name in $hosted; do
    name="${name}_API_KEY"
    if [ -n "${!name:-}" ]; then echo "set (environment)"; return; fi
  done
  [ -f "$env" ] || { echo "missing (.env not created)"; return; }
  if grep -Eq "^(${hosted// /|})_API_KEY=[[:space:]]*[\"']?[^\"'[:space:]]" "$env"; then echo "set (.env)"; return; fi
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
  local k; k=$(key_status); say "model credential: $k"
  case $k in set*) ;; *)
    if grep -Eq '^LLM_BASE_URL=http://127\.0\.0\.1:5055' "$HOME_DIR/.env" 2>/dev/null; then
      say "gateway: configured (LLM_GATEWAY=$(grep -E '^LLM_GATEWAY=' "$HOME_DIR/.env" | cut -d= -f2-)); $(curl -fsS -m 2 http://127.0.0.1:5055/health >/dev/null 2>&1 && echo running || echo 'stopped (run: mm.sh gateway start)')"
    else
      ok=0
      for cli in claude codex antigravity gemini; do
        if [ -x "$PY" ] && "$PY" "$HOME_DIR/backend/gateway/local_gateway.py" --backend "$cli" --check >/dev/null 2>&1; then
          say "no key, but the $cli CLI is installed: 'mm.sh gateway start $cli' runs on its login (personal use; add --port N to run several side by side)"
        fi
      done
      say "multi-agent pool: 'mm.sh gateway start multi' pools all installed local CLIs together"
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
      say "using existing checkout $HOME_DIR (update separately with git pull --ff-only)"
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
  agent-config)
    exec python3 "$HOME_DIR/backend/claude_cli/agent_install.py" --root "$HOME_DIR" "$@"
    ;;
  configure|provider)
    action="configure"
    if [ "$cmd" = provider ]; then action="${1:-list}"; [ $# -eq 0 ] || shift; fi
    provider_py="$PY"; [ -x "$provider_py" ] || provider_py="$(command -v python3)"
    exec "$provider_py" "$HOME_DIR/backend/claude_cli/providers.py" "$action" --root "$HOME_DIR" "$@"
    ;;
  start)
    [ -x "$PY" ] || die "not set up yet (run: mm.sh setup)"
    case " $* " in
      *" --env-file"*) ;;           # a per-instance settings file (written by: mm.sh gateway start BACKEND --port N)
      *) case $(key_status) in set*) ;; *) die "provider not configured; run mm.sh configure (local models and login gateways are available)" ;; esac ;;
    esac
    cd "$HOME_DIR" && bash backend/claude_cli/start_server.sh "$@"
    ;;
  stop) cd "$HOME_DIR" && bash backend/claude_cli/stop_server.sh "$@" ;;
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
    gw_usage="usage: mm.sh gateway login|start|stop|status [claude|codex|gemini|antigravity|chatgpt|siwc|multi] [--port N] [--model M] [--env-file F]"
    sub="${1:-status}"; [ $# -eq 0 ] || shift
    be=""; port="5055"; gw_model=""; envf=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --port) port="${2:-}"; shift ;;
        --port=*) port="${1#*=}" ;;
        --model) gw_model="${2:-}"; shift ;;
        --model=*) gw_model="${1#*=}" ;;
        --env-file) envf="${2:-}"; shift ;;
        --env-file=*) envf="${1#*=}" ;;
        -*) die "$gw_usage" ;;
        *) [ -z "$be" ] || die "$gw_usage"; be="$1" ;;
      esac
      shift
    done
    case "$port" in ''|*[!0-9]*) die "--port must be a number" ;; esac
    if [ -z "$be" ] && [ "$sub" = start ]; then
      be="$(grep -E '^LLM_GATEWAY=' "$HOME_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '"')"; be="${be:-claude}"
    fi
    case "${be:-claude}" in claude|codex|gemini|antigravity|chatgpt|siwc|multi) ;; *) die "unknown gateway backend '$be'; $gw_usage" ;; esac
    # one pid/token/log file per port, so several gateways (one per provider) run side by side
    if [ "$port" = 5055 ]; then sfx=""; else sfx="-$port"; fi
    mkdir -p "$HOME_DIR/backend/logs"
    pidf="$HOME_DIR/backend/logs/gateway$sfx.pid"
    tokenf="$HOME_DIR/backend/logs/gateway$sfx.token"
    logf="$HOME_DIR/backend/logs/gateway$sfx.out"
    url="http://127.0.0.1:$port"
    case "$sub" in
      login) cd "$HOME_DIR" && exec "$PY" backend/gateway/siwc_auth.py login ;;
      start)
        if [ "$be" = siwc ]; then
          "$PY" "$HOME_DIR/backend/gateway/siwc_auth.py" status | "$PY" -c 'import json,sys; s=json.load(sys.stdin); sys.exit(0 if s.get("eligible_scope") and not s.get("needs_login") else 1)' || die "Continue with ChatGPT is not ready (run: mm.sh gateway login)"
        else
          # the gateway finds each CLI on PATH or in its known install locations (codex in the ChatGPT app, agy in ~/.local/bin)
          "$PY" "$HOME_DIR/backend/gateway/local_gateway.py" --backend "$be" --check >/dev/null 2>&1 \
            || die "'$be' is not available (install its CLI and log in first; for multi, at least one of claude, codex, antigravity, gemini)"
        fi
        if [ ! -s "$tokenf" ]; then (umask 077; "$PY" -c 'import secrets,sys; open(sys.argv[1],"w").write(secrets.token_urlsafe(48))' "$tokenf"); fi
        if curl -fsS -m 2 "$url/health" >/dev/null 2>&1; then
          curl -fsS -m 2 "$url/health" | "$PY" -c 'import json,sys; s=json.load(sys.stdin); sys.exit(0 if s.get("auth_required") and s.get("backend")==sys.argv[1] else 1)' "$be" || die "a different or unauthenticated gateway is on port $port; stop it or pick another --port"
          say "gateway already running ($be on $url)"
        else
          margs=(); [ -n "$gw_model" ] && margs=(--model "$gw_model")
          # exec, so the recorded pid is the gateway itself (stop kills it) and nothing keeps the caller's output open
          (cd "$HOME_DIR" && exec nohup "$PY" backend/gateway/local_gateway.py --backend "$be" --port "$port" --auth-token-file "$tokenf" ${margs[@]+"${margs[@]}"} > "$logf" 2>&1 < /dev/null) &
          echo $! > "$pidf"
          for _ in $(seq 1 20); do curl -fsS -m 1 "$url/health" >/dev/null 2>&1 && break; sleep 0.5; done
          curl -fsS -m 1 "$url/health" >/dev/null 2>&1 || { tail -n 20 "$logf" >&2; die "gateway did not start; see $logf"; }
          say "gateway started ($be) on $url/v1 (log $logf)"
        fi
        model="${gw_model:-$be}"
        if [ "$be" = siwc ] && [ -z "$gw_model" ]; then model=$("$PY" "$HOME_DIR/backend/gateway/siwc_auth.py" status | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("model") or "")'); fi
        # settings: the default port writes .env (as before); other ports write a settings file for that provider,
        # used by a backend instance started with: mm.sh start --port P --env-file F
        if [ -z "$envf" ]; then
          if [ "$port" = 5055 ]; then envf="$HOME_DIR/.env"; else envf="$HOME_DIR/.env.$be"; fi
        fi
        case "$envf" in /*) ;; *) envf="$PWD/$envf" ;; esac
        base_env="$envf"; [ -f "$base_env" ] || base_env="$HOME_DIR/.env"
        (umask 077
         { grep -Ev '^(LLM_PROVIDER|LLM_BASE_URL|LLM_API_KEY|LLM_GATEWAY|LLM_MODEL_NAME|LLM_POOL|MARKET_MIRROR_PROVIDER)=' "$base_env" 2>/dev/null || true
           printf 'LLM_PROVIDER=openai\nLLM_BASE_URL=%s/v1\nLLM_API_KEY=%s\nLLM_GATEWAY=%s\nLLM_MODEL_NAME=%s\n' "$url" "$(cat "$tokenf")" "$be" "$model"; } > "$envf.tmp")
        mv "$envf.tmp" "$envf"
        if [ "$envf" = "$HOME_DIR/.env" ]; then
          say "wrote gateway settings to $envf (restart the backend: mm.sh stop && mm.sh start)"
        else
          say "wrote gateway settings to $envf; start a backend on it with:"
          say "  mm.sh start --port <backend port, e.g. 5011> --env-file $envf"
          say "  (its data goes to backend/uploads-<port>; point the CLI at it with MIROFISH_URL=http://localhost:<port>)"
        fi ;;
      stop)
        if [ -f "$pidf" ] && kill "$(cat "$pidf")" 2>/dev/null; then rm -f "$pidf"; say "gateway on port $port stopped"; else rm -f "$pidf"; say "no gateway running on port $port"; fi ;;
      status) curl -fsS -m 2 "$url/health" 2>/dev/null || say "no gateway on port $port" ;;
      *) die "$gw_usage" ;;
    esac ;;
  mcp) exec python3 "$(dirname "$0")/mcp_server.py" "$@" ;;
  help|-h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command '$cmd' (try: mm.sh help)" ;;
esac

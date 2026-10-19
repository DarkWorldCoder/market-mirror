#!/usr/bin/env bash
# Install the checked-out open-source engine without changing agent configuration or credentials.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "${1:-}" = --help ]; then
  printf '%s\n' 'Usage: bash install.sh [--configure]' 'Requires git, uv and Python 3.12. Installs this checkout, then prints agent registration instructions.'
  exit 0
fi
export MARKET_MIRROR_HOME="$ROOT"
HELPER="$ROOT/plugin/skills/market-mirror/scripts/mm.sh"
bash "$HELPER" setup
"$ROOT/backend/.venv/bin/python" "$ROOT/backend/claude_cli/agent_install.py" --root "$ROOT" --register-engine
if [ "${1:-}" = --configure ]; then bash "$HELPER" configure; fi
printf '\n%s\n' 'Choose your model provider: bash plugin/skills/market-mirror/scripts/mm.sh configure' 'Check connection and available models: bash plugin/skills/market-mirror/scripts/mm.sh provider check' 'Get a config for your daily agent: bash plugin/skills/market-mirror/scripts/mm.sh agent-config --client codex' 'Other clients: claude, cursor, gemini, generic. No agent settings are overwritten.'

#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MARKET_MIRROR_HOME="${MARKET_MIRROR_HOME:-$ROOT}"
exec bash "$ROOT/plugin/skills/market-mirror/scripts/mm.sh" "$@"

#!/usr/bin/env bash
# Copy the MCP server files from the plugin into the package before building (they are not kept twice in git).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/../../plugin/skills/market-mirror/scripts"
dst="$here/src/marketmirror/_server"
rm -rf "$dst"; mkdir -p "$dst"
cp "$src/mcp_server.py" "$src/job_worker.py" "$src/mm.sh" "$dst/"

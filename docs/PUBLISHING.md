# Distributing MarketMirror to local agents

The canonical Agent Plugin is `plugin/` (`plugin.json`, `mcp.json`, `skills/`). `.agents/plugins/marketplace.json` advertises it to repo-local Codex clients. `.claude-plugin/marketplace.json` and `plugin/.claude-plugin/plugin.json` are compatibility manifests for Claude Code. `codex/skills/market-mirror` uses symlinks to canonical files; do not edit those targets separately.

For a release, keep the version in all three plugin/marketplace manifests aligned. Validate with `claude plugin validate plugin`, a temporary Codex marketplace install, and a generic MCP `initialize` + `tools/list` exchange. Test `campaign_plan`, `actuals_import`, `study`, and `job_status` with local fixtures. The plugin only packages a local stdio MCP server and skills; public plugin-directory submission and a remote hosted MCP service are separate work.

Local install smoke tests:

```bash
CODEX_HOME=/tmp/mm-codex-plugin-test codex plugin marketplace add /absolute/path/to/market-mirror
CODEX_HOME=/tmp/mm-codex-plugin-test codex plugin add market-mirror@market-mirror-local
CLAUDE_CONFIG_DIR=/tmp/mm-claude-plugin-test claude plugin marketplace add /absolute/path/to/market-mirror
CLAUDE_CONFIG_DIR=/tmp/mm-claude-plugin-test claude plugin install market-mirror@market-mirror
```

For a generic client, launch `python3 plugin/skills/market-mirror/scripts/mcp_server.py` over stdio. A local HTTP client can use `--http --token-file /private/path/token` and a bearer header. Do not package credentials in manifests.

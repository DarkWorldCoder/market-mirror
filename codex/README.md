# MarketMirror for Codex

The canonical portable plugin is [`../plugin/`](../plugin/). `codex/skills/market-mirror/` contains symlinks to its skill and scripts so the old manual path continues to work without a second copy to maintain.

```bash
codex plugin marketplace add /absolute/path/to/market-mirror
codex plugin add market-mirror@market-mirror-local
```

The plugin installs Agent Skills and the stdio MCP server. For a generic MCP client, run `python3 plugin/skills/market-mirror/scripts/mcp_server.py`. See the repository README for setup and the campaign workflow.

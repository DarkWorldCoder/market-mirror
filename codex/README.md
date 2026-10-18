# MarketMirror for OpenAI Codex

A packaged copy of the skill (`skills/market-mirror/`, Agent Skills format: `SKILL.md` + `scripts/`) and an `AGENTS.md` snippet.

```bash
mkdir -p ~/.codex/skills && cp -r codex/skills/market-mirror ~/.codex/skills/
cat codex/AGENTS.md >> AGENTS.md          # in the project Codex works in
```

MCP server for Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.market-mirror]
command = "bash"
args = ["/absolute/path/to/market-mirror/codex/skills/market-mirror/scripts/mm.sh", "mcp"]
```

No API key? `bash codex/skills/market-mirror/scripts/mm.sh gateway start codex` runs the engine on your ChatGPT login (personal use). The copy is refreshed from `plugin/` at release time (`docs/PUBLISHING.md`).

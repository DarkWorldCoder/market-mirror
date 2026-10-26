# MarketMirror MCP server

<!-- mcp-name: io.github.DarkWorldCoder/market-mirror -->

MarketMirror tests marketing and sales decisions on simulated buyers before you spend money on real ones. It builds
interviewed buyer personas, shows them your ads in simulated social feeds, runs a buyer survey and a sales-pitch
rehearsal, and writes a go / iterate / no-go report with an offline HTML dashboard. Results are simulated and labelled
as such; `backtest` and `calibrate` compare them with your real ad and survey results.

This package is the MCP server (Python standard library only). Add it to any MCP client:

```json
{
  "mcpServers": {
    "market-mirror": { "command": "uvx", "args": ["marketmirror"] }
  }
}
```

Then ask your agent to run `doctor`, and `setup` to install the MarketMirror engine (Git, Bash and
[uv](https://docs.astral.sh/uv/) required; Linux, macOS or WSL). Choose a model provider in your own terminal with the
engine's `./mm configure`; never paste API keys into a chat.

- Repository, docs and full install guide: https://github.com/DarkWorldCoder/market-mirror
- Live demo (a 2,999-person simulated run, no install): https://darkworldcoder.github.io/market-mirror/demo/
- License: AGPL-3.0

# MarketMirror Agent Plugin

Give your agent a marketing research and simulation lab: analyze real ad data it can access, research customer feedback, survey simulated buyers, plan campaigns, compare ads and offers, rehearse sales conversations, and test real product URLs with synthetic visitors. Review campaign evidence, scenario comparisons, and the next real experiment in a saved report.

Connected advertising, analytics, and CRM access belongs to the calling agent. It fetches authorized records and passes ad rows or CSV/JSON exports to MarketMirror. Supplied exports work too. Surveys and browser visitors are simulated; real survey and campaign results remain separately identified evidence.

The portable Agent Plugin at `plugin.json` bundles four focused Agent Skills plus the canonical `market-mirror` workflow and a stdio MCP server. The repo marketplace is `.agents/plugins/marketplace.json`; Claude Code can also use the compatibility marketplace at the repository root.

```bash
codex plugin marketplace add /absolute/path/to/market-mirror
codex plugin add market-mirror@market-mirror-local
# Claude Code:
claude plugin marketplace add /absolute/path/to/market-mirror
claude plugin install market-mirror@market-mirror
```

MCP tools include `understand`, `website_test`, `research`, `actuals_import`, `campaign_plan`, `run_test`, `study`, `holdout_backtest`, `predict`, `results`, and all earlier tools. `website_test` uses optional browser support to test a real product URL with prepared synthetic visitors and supplied outcome checks; see [website testing](../docs/WEBSITE_TESTING.md). Use `job_status` for persistent long-running jobs. `scripts/mm.sh` is the local helper; `MARKET_MIRROR_HOME` selects an existing checkout. A generic MCP client can launch `python3 /absolute/path/to/plugin/skills/market-mirror/scripts/mcp_server.py` over stdio. Authenticated loopback MCP is available with `--http --token-file /private/path/token`.

MarketMirror prepares and simulates decisions. It does not send campaigns or change ad accounts. See the repository README for the full workflow and provider setup.

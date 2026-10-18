# MarketMirror plugin for Claude Code

Test ads, messages, prices, emails, launches and sales pitches on simulated buyers before you spend; get a plain-language report, a go / iterate / no-go decision and predictions that say what they rest on.

```
/plugin marketplace add DarkWorldCoder/market-mirror
/plugin install market-mirror@market-mirror
```

What you get:

- **Skill** `market-mirror`: the recipes (understand the product, research real voices, quickstart, campaign tests, email tests, studies, calibration, reports) and the house rules (show the people before spending, say "simulated", give margins).
- **MCP tools**: `doctor`, `setup`, `start_backend`, `understand`, `research`, `quickstart`, `market_test`, `run_test`, `email_test`, `pitch`, `study`, `predict`, `calibrate`, `ideas`, `push_context`, `ads_import`, `backtest`, `results`, `list_runs`, `start_live`, `cli`.
- **Helper** `scripts/mm.sh`: `setup | doctor | start | stop | gateway | scenario | cli | live | mcp`.

First run: `setup` (clones the engine into `~/.market-mirror/engine`, installs deps with `uv`), put your Anthropic key in `<engine>/.env` or run `mm.sh gateway start claude` to use your Claude Code login, then `start_backend` and `quickstart`.

Screenshots and the full guide: the repository README.

# MarketMirror for Gemini CLI

MarketMirror tests marketing and sales decisions on simulated buyers: it builds interviewed personas, shows them ads in
simulated social feeds, runs a buyer survey and a sales-pitch rehearsal, and writes a go / iterate / no-go report with an
offline HTML dashboard. Use the `market-mirror` MCP tools from this extension.

- Start with `doctor`. If the engine is missing, run `setup` (it installs the engine with `uv`).
- Use `market_test` for a full test from one config, or `run_test` for a single experiment spec; poll `job_status`.
- Show the user the simulated people before approving model spend, and keep runs small at first. Suggest
  `max_spend_usd` in the `market_test` config: a hard cap on estimated spend that keeps partial results.
- After a run, give the user `real_check.md` / `real_check.csv` from the run folder to check the result with real
  people, then `calibrate` their answers.
- Report simulated numbers as directions with their ranges, never as measured results. Simulated comments are not
  real customer quotes.
- Never ask for API keys in chat; point the user to `mm.sh configure` in their own terminal or an existing environment
  variable through `provider_setup` with `key_env`.

The full agent guide is `plugin/skills/market-mirror/SKILL.md` in this extension (its `scripts/` paths are relative to
that folder). Privacy: `PRIVACY.md`. Repo: https://github.com/DarkWorldCoder/market-mirror

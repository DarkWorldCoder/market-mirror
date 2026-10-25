# MarketMirror for Gemini CLI

MarketMirror tests marketing and sales decisions on simulated buyers: it builds interviewed personas, shows them ads in
simulated social feeds, runs a buyer survey and a sales-pitch rehearsal, and writes a go / iterate / no-go report with an
offline HTML dashboard. Use the `market-mirror` MCP tools from this extension.

- Start with `doctor`. If the engine is missing, run `setup` (it installs the engine with `uv`).
- Use `market_test` for a full test from one config, or `run_test` for a single experiment spec; poll `job_status`.
- Show the user the simulated people before approving model spend, and keep runs small at first.
- Report simulated numbers as directions with their ranges, never as measured results. Simulated comments are not
  real customer quotes.
- Never ask for API keys in chat; point the user to `mm.sh configure` in their own terminal or an existing environment
  variable through `provider_setup` with `key_env`.

The full agent guide is `plugin/skills/market-mirror/SKILL.md` in this extension (its `scripts/` paths are relative to
that folder). Privacy: `PRIVACY.md`. Repo: https://github.com/DarkWorldCoder/market-mirror

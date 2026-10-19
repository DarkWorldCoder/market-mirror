---
name: market-mirror
description: Analyze real ad data, research markets, survey simulated buyers, and test campaigns, pricing, sales pitches, and product journeys through MarketMirror MCP tools or the local CLI.
---

# MarketMirror

MarketMirror is your agent's marketing research and simulation lab. Analyze observed campaign performance, research customer feedback, survey and interview simulated buyers, compare campaigns and pricing, rehearse sales conversations, and test actual product URLs with synthetic visitors. Use the bundled MCP tools in any compatible agent, or `scripts/mm.sh cli ...` when MCP is unavailable. `doctor` checks the local engine; `setup` installs it if needed. `mm.sh home` shows the engine path. A checkout can be used directly with `MARKET_MIRROR_HOME` set to its absolute path.

## Bring your agent's data

When the calling agent has authorized advertising, analytics, CRM, or survey tools, use those tools to fetch relevant records. Pass exported CSV/JSON to `actuals_import` or `ads_import`; `ideas` also accepts ad rows directly from a connected ads tool. Retain the source, reporting period, market, metric definitions, and currency. Report missing access or fields and use supplied exports where available. MarketMirror does not automatically connect accounts or expand the agent's permissions. Its surveys interview simulated personas; imported human survey responses remain separate real evidence.

For a real product URL, use `website_test` on prepared personas. The optional browser extra drives isolated Chromium sessions; agents can inspect the product, use the cart, reach signup or checkout, or leave. Supply named DOM checks and `goal_check` to verify outcomes independently. Account submission needs explicit opt-in and owned test identities; never submit payments or orders. Start with 1–3 visitors and review screenshots, traces, deliberate departures and execution failures separately. See `docs/WEBSITE_TESTING.md` in the engine checkout. Observed actions are synthetic visitor behavior, not measured human conversion.

## Workflow

1. `understand` product documents or an existing project. Read the resulting `product_profile.json`, including unknowns. `research` public feedback; retain cited URL, date, market and quality, and state blocked sources.
2. `actuals_import` existing ads, email, website, CRM and survey CSV/JSON exports. Map columns explicitly and resolve validation errors. The old `ads_import` tool remains available for ad-specific seed files and benchmarks.
3. `campaign_plan` takes a profile or project, goal, budget and optional channels. Review audiences, positioning, funnel metrics, allocations, proof gaps and the runnable `test_specs`. The plan is a draft; supplied claims need verification.
4. `run_test` evaluates a relevant spec on prepared simulated buyers. For a controlled scenario comparison, use `study` with one simulation and the same seed list across variants. Poll `job_status`; finished cells resume on rerun. Search and organic content and referrals use a concept survey, lifecycle messages use the inbox engine, and sales outreach uses pitch rehearsal. Their simulated outcomes are not actual channel performance.
5. `backtest` past ads and `holdout_backtest` independent real experiments. The latter compares the persona estimate against a no-persona training-mean baseline. An uncalibrated `predict` result is directional. A predictive claim needs held-out evidence that beats the baseline; otherwise label the conclusion exploratory.
6. Open `results` and the saved dashboard, check the evidence and report paths, then recommend the next small real randomized test. Record audience, exposure, assignment, outcome, date, market and source. MarketMirror does not send campaigns or change ad accounts.

## Setup and access

`bash scripts/mm.sh setup` installs the engine with `uv`; `bash scripts/mm.sh doctor` checks it. Choose an API-key or local-model provider, the documented eligible-user Sign in with ChatGPT option when configured, or a local `codex exec` / Claude CLI gateway. Run the backend with `bash scripts/mm.sh start`. The MCP server defaults to stdio: `bash scripts/mm.sh mcp`. To serve authenticated loopback MCP, provide a private bearer-token file: `bash scripts/mm.sh mcp --http --port 5061 --token-file /private/path/token`. Never commit or print tokens or API keys.

Use `provider_setup` with `action:list` for official provider guides, `action:status` for masked configuration, and `action:check` for model discovery without an inference call. For hosted keys, direct the user to `mm.sh configure` in their own terminal (hidden input), or use a pre-existing environment variable through `key_env`. API keys must never be supplied in chat or tool arguments. Ollama and LM Studio support local use without a hosted API key; confirm the selected local model supports tools and structured output on a small fixture.

Large simulations can consume substantial model calls. Review the intended audience and estimated work before running. Report measured calls, time and costs separately from estimates. Do not call simulated buyer comments real customer quotes. For focused workflows, use the bundled `research`, `planning`, `testing`, and `evidence-review` skills.

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/marketmirror-logo-dark.png" />
  <img src="docs/brand/marketmirror-logo-light.png" alt="MarketMirror" width="480" />
</picture>

# MarketMirror

**Your agent's marketing research and simulation lab.**

Analyze real ad performance your agent can access, research customer feedback, survey simulated buyers, and test campaigns, pricing, sales pitches, and real product journeys. Turn the findings into your next experiment.

Self-hosted · Open source · Local agents and MCP · Offline HTML reports

[Quick start](#quick-start) · [Connect your agent](#connect-your-agent) · [Example workflow](#example-workflow) · [Documentation](#documentation)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/dashboard-dark.png" />
  <img src="docs/images/dashboard-results.png" alt="MarketMirror dashboard for 1,008 simulated buyers: sidebar navigation, decision bar, headline figures and the at-a-glance cards" width="92%" />
</picture>

</div>

MarketMirror gives Codex, Claude Code, and compatible MCP agents a shared toolkit for marketing, sales, and product analysis. Bring a product brief or website, campaign results, and customer evidence. Build an audience, run simulated surveys and interviews, compare ads and offers, rehearse sales conversations, and watch synthetic visitors explore your actual website. Review the findings together in an offline report.

If your agent already has authorized access to advertising, analytics, or CRM tools, it can fetch the relevant records and bring ad rows or CSV/JSON exports into MarketMirror. Analyze spend, clicks, conversions, and campaign comparisons alongside simulated responses. Access comes from your agent's connected tools; MarketMirror also works with exports you supply.

**Simulation results are exploratory.** Generated people are not customer observations. Validate a specific prediction against independent real outcomes before using it to forecast performance. MarketMirror prepares and simulates campaigns; this release does not send messages or change ad accounts.

## What you can do

| Work | What you get |
|---|---|
| **Understand the product** | A reusable profile of the audience, offer, positioning, proof, competitors, and missing information |
| **Analyze real ads** | Performance summaries and benchmarks from ad rows or exports your agent supplies; compare observed results with simulation and generate the next test ideas |
| **Research the market** | Source-linked feedback from Hacker News, country-specific App Store reviews, accessible Reddit results, and supplied pages |
| **Survey simulated buyers** | Synthetic survey responses and interviews to explore preferences, objections, purchase intent, and message reactions; import real survey exports as separate evidence |
| **Plan a campaign** | Audience hypotheses, positioning, draft channel budgets, funnel goals, measurement requirements, and runnable test specs |
| **Test acquisition** | Ad and landing-page reactions, offer and message comparisons, search and organic content concepts, creator posts, and channel mixes |
| **Test the actual website** | Browser journeys on a real product URL: product exploration, cart actions, signup and checkout reachability, screenshots, outcome assertions, and reasons for leaving |
| **Explore lifecycle and referrals** | Inbox simulations for email, nurture, and retention messages; referral concept tests |
| **Rehearse sales** | Outreach, follow-ups, pitches, objections, rebuttals, a battlecard built from real objections with tested answers, a sales roleplay, and an audience playbook |
| **Run the marketing lab** | Buying committee (who blocks and who signs), a creative optimizer that rewrites an ad and re-tests it on the same people, a four-touch journey with memory, pricing choice between tiers, competitor choice with counter-moves, landing-page teardown, what-if choice experiments, per-audience ads, how buyers would search, real versus simulated concerns, and word-of-mouth forwards |
| **Mix model providers** | One market played by several providers at once: Claude, Codex and Gemini each write, play and answer for their own share of the people, and the dashboard shows where they agree |
| **Explore pricing** | Price sensitivity, offer comparisons, and conjoint choices |
| **Compare scenarios** | Studies using the same prepared people and seed list, saved progress, and scenario deltas |
| **Review evidence** | Normalized ads, email, website, CRM, and survey exports; calibration diagnostics and held-out backtests |
| **Share the findings** | One offline HTML dashboard, a readable report, action plans, CSV/JSON exports, and a printable report |

## Use cases

Each recipe starts from a prepared simulation (`./mm cli quickstart`, then `market-test` with `"approve_spend": true`). Ask your agent in plain words, or run the command yourself. Results land in the run folder and in the dashboard section named in the last column.

| You want to know | Ask your agent | Or run | Look at |
|---|---|---|---|
| **Which ad to run** | "Test these 3 ads on our buyers in realistic feeds, 3 seeds." | `./mm cli feedtest --simulation $SIM --creatives @creatives.json --seeds 3` | Feed test, At a glance |
| **Which message or name lands** | "Split-test these headlines; which one makes people want to try it?" | `./mm cli survey --simulation $SIM --messages @messages.txt --split` | Messages, Results |
| **What to charge, and which offer** | "Would people start a trial with a card required? What price feels fair?" | `./mm cli survey --simulation $SIM --offer "7-day trial, no card" --pricing USD` | Pricing, Objections |
| **Whether a change really wins** | "Compare no-card vs card-required vs a lower price on the same people, 3 seeds each." | `./mm cli study --spec study.json` | Study, Scenarios |
| **Which country and audience to start with** | "Where does this land best: India, the Philippines or Kenya?" | personas spec with segments and countries, then `market-test` | Where they are (map), Audiences |
| **How a launch plays out socially** | "Run our launch posts and day-3 announcement through a few social rounds." | `market_test.json` keys `posts`, `events`, `rounds` | Social feed, Activity |
| **How news changes the conversation** | "A competitor just cut its price; push that into the running simulation." | `./mm cli context --simulation $SIM --text "..."` | Social feed (next round) |
| **Whether the email gets opened** | "Test these subject lines and a 3-step sequence in their inboxes." | `./mm cli emailtest --simulation $SIM --emails @emails.json` | Email |
| **How a sales pitch is received** | "Pitch every buyer, answer their objections, and tell me who to call first." | `./mm cli pitch --simulation $SIM --script @pitch.md --rebuttals @rebuttals.md` | Sales rehearsal, lead scores |
| **Whether the website converts** | "Send 3 buyers to our product page and see if they add to cart." | `./mm cli website-test --simulation $SIM --url https://... --goal add_to_cart` | Website test report |
| **What real people already say** | "Find what people say about home workout apps in India, with links." | `./mm cli research --query "home workout app" --country in` | Voices, Report |
| **What to test next, from real ads** | "Read our ad export and suggest the next three tests." | `./mm cli ideas --ads export.csv --run-dir mirofish_runs/x --brand Acme` | Test ideas |
| **What results to expect** | "Forecast sign-ups for USD 500 of spend, calibrated on our past campaigns." | `./mm cli predict --run-dir mirofish_runs/x --brand Acme --spend 500` | Predictions |
| **Whether the simulation matches reality** | "Compare the simulated survey with our real answers." | `./mm cli calibrate --run-dir mirofish_runs/x --real answers.csv` | Evidence, calibration verdict |
| **Why someone said no** | "Ask person 12 why they would not start the trial." | `./mm cli interview --simulation $SIM --agent 12 --prompt "..."` | (answer printed) |
| **Who blocks the deal and who signs** | "Run a buying committee on 12 households or companies." | `./mm cli gtm committee --simulation $SIM` | Marketing lab |
| **How to make an ad better** | "Rewrite this ad three times and re-test each version on the same people." | `./mm cli gtm creative --simulation $SIM --creative @ad.json --generations 3` | Marketing lab |
| **How to answer objections** | "Build a battlecard from their real objections and test the answers." | `./mm cli gtm battlecard --simulation $SIM` | Marketing lab |
| **Which tier people pick** | "Basic, Plus or Family at these prices: what share picks each?" | `./mm cli gtm pricing --simulation $SIM --tiers @tiers.json` | Marketing lab |
| **What happens if a competitor moves** | "Would they switch if X cuts its price by 30%?" | `./mm cli gtm competitors --simulation $SIM --competitors X Y --move "X cuts its price by 30%"` | Competitors |
| **Whether the landing page holds attention** | "Tear down our landing page with 20 buyers." | `./mm cli gtm teardown --simulation $SIM --url https://...` | Landing and sales lab |
| **Whether different models agree** | "Run the same market on Claude, Codex and Gemini people together." | `LLM_POOL` in the backend's settings (see [Several providers in one market](#several-providers-in-one-market)) | Do the models agree? |
| **What someone thought but did not say** | "Show me what people thought while they scrolled." | `./mm cli gtm thoughts --simulation $SIM` | Agent thoughts |
| **Where a theme shows up in the run** | "Find everything people said about price in Kenya." | `./mm cli search --run-dir mirofish_runs/x -q "price Kenya"` | (results printed) |
| **What is happening right now** | "Show me the run live." | `./mm live --run-dir mirofish_runs/x`, then open `/live` | Live control room |

Simulated people remember what happened to them across tests in the same run: someone who hid your ad or unsubscribed from the email carries that into the survey and the pitch. Each study cell keeps its own memory, so scenarios never leak into each other. Set `"memory_scope": "off"` in a config to test every step on fresh people.

Feed-test previews cover Facebook, Instagram, Reddit, TikTok, LinkedIn, and X. Optional social rounds use the MiroFish/OASIS Twitter and Reddit environments. Search, organic, referral, and sales test families adapt the existing survey, inbox, and pitch engines; they do not reproduce those channels' production systems.

## Quick start

Requires Git, Bash, Python 3, and [uv](https://docs.astral.sh/uv/). The installer provisions the Python 3.12 environment. Use Linux, macOS, or WSL; native Windows has not been validated.

```bash
git clone https://github.com/DarkWorldCoder/market-mirror.git
cd market-mirror
bash install.sh
./mm configure
```

Choose your model provider, then start the backend and create your first scenario:

```bash
./mm provider check
./mm start
./mm cli quickstart --out scenarios/acme
```

The wizard asks about your product, buyers, channels, budget, and test size. It writes editable inputs, prepares the simulated people, and stops for review before running the remaining tests. **Preparation itself uses model calls.** Start with a small cohort. `provider check` discovers models without running inference; it does not test model quality or tool support.

Inspect the generated files and profiles. To continue, retain the returned `simulation_id`, set `"approve_spend": true` in `scenarios/acme/market_test.json`, and run:

```bash
./mm cli market-test scenarios/acme/market_test.json
./mm live --run-dir mirofish_runs/acme
```

The live viewer runs at [127.0.0.1:5050](http://127.0.0.1:5050), and its control room at [127.0.0.1:5050/live](http://127.0.0.1:5050/live) shows every stage, every simulated person lighting up as they act, what they post, and the progress log, updated every two seconds. Use the actual run directory printed by the pipeline if its name differs. The saved `dashboard.html` also opens directly without a server. To generate templates without preparing people, use `./mm cli quickstart --no-run`.

If a `market-test` run stops (a crash, a restart, a closed terminal), first make sure the earlier `market-test` process has exited and `./mm cli status --simulation <sid>` shows no rounds running (wait for them, or stop them with `./mm cli stop`), then run the same command again, with the same `MIROFISH_URL` for a backend on another port. It resumes from the run folder's `run_manifest.json`, and a simulation that stopped before its people were ready is prepared again; people already written come from the cache. With `"resume_steps": true` in the config it also reuses a usable saved feed test and survey and a live social environment. The wait for preparation grows with the market (at least an hour, or about 6 s per person), and backend tasks are followed for up to six hours.

`./mm start` starts the backend; `./mm cli start --simulation …` starts social simulation rounds. All examples below use the repository's `./mm` helper—no global command or alias is required.

### Test your product URL

Install the optional browser support, then use a prepared simulation's ID:

```bash
uv sync --project backend --extra browser --python 3.12
backend/.venv/bin/python -m playwright install chromium
./mm cli website-test --simulation "$SIMULATION_ID" \
  --url https://your-product.example/products/shoes --goal add_to_cart \
  --task "Evaluate these shoes and decide whether to add a suitable pair to your cart." \
  --limit 3 --steps 12
```

Restart the backend after installing the browser extra. Replace the URL with your site. Browser control supports search and keyboard actions, product options, hover menus, same-site tabs and frames, open shadow DOM, and bounded recovery when the page changes. Add `--record-video` for a recording or `--headed` to watch on a desktop with a graphical session. Agents may interact with the actual cart; signup submission requires explicitly supplied test data and opt-in. No orders or payments are supported. Named DOM checks verify outcomes independently of what an agent claims. Without them, completion stays unverified. See [real website testing](docs/WEBSITE_TESTING.md) for outcome checks, signup setup, browser limits, and the evidence report.

Browser runs use compact model observations while retaining full local evidence. Set call, input-token, and elapsed-time limits; repeated actions on unchanged pages are detected separately from buyer departures. Reports show available cache usage, model time, and cost basis. See [browser context and run limits](docs/WEBSITE_TESTING.md#control-context-usage-and-run-limits).

### Choose your model

| Provider | Setup | Authorization |
|---|---|---|
| **Local Codex** | `./mm gateway start codex` | Existing local Codex login |
| **Local Claude Code** | `./mm gateway start claude` | Existing local Claude Code login |
| **ChatGPT sign-in** | `./mm gateway login`, then `./mm gateway start siwc` | Eligible account; scope and model access checked during setup |
| **Local Antigravity (Gemini models)** | `./mm gateway start antigravity --model gemini-3.8-flash-medium` | Existing local Antigravity login; `agy models` lists the models it offers |
| **Local Gemini CLI** | `./mm gateway start gemini` | Existing local Gemini CLI login |
| **Every installed login behind one gateway** | `./mm gateway start multi` | The login CLIs that are installed and signed in (`LLM_GATEWAY_POOL` lists which); calls are spread across them, so use `LLM_POOL` (below) to keep one provider per person |
| **Ollama / LM Studio** | Choose the provider in `./mm configure` | A locally installed, tool-capable model |
| **Claude / OpenAI / Google Gemini API** | Choose the provider in `./mm configure` | Provider API key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`) and available model access |
| **Other API providers**: DeepSeek, Kimi (Moonshot AI), Mistral, xAI (Grok), Groq, Together AI, Fireworks AI, OpenRouter, Qwen (Alibaba Model Studio), Z.ai (GLM), Cerebras, MiniMax | `./mm configure`, the settings page (`./mm cli setup`), or `.env`: `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY` (base URL and a default model are filled in; `<NAME>_BASE_URL` and `<NAME>_MODEL_NAME` override them; Qwen also needs `QWEN_BASE_URL`, which contains your workspace id) | That provider's API key (`MOONSHOT_API_KEY`, `XAI_API_KEY`, `ZAI_API_KEY`, `DASHSCOPE_API_KEY`, otherwise `<NAME>_API_KEY`) |
| **Other compatible servers** | Configure the endpoint and model, or the pool slot `custom` (`CUSTOM_BASE_URL`, `CUSTOM_API_KEY`, `CUSTOM_MODEL_NAME`) | Provider-dependent |

The gateway commands above use the default port 5055 and write their settings into `.env`. On another port (for example `--port 5057`) a gateway writes `.env.<backend>` instead, such as `.env.antigravity`; start a backend on that file with `./mm start --port <P> --env-file .env.antigravity`.

Several providers in one market: `LLM_POOL=deepseek,kimi,claude` with each provider's key set (`<name>:<model>` picks a model, for example `deepseek:deepseek-v4-pro`). `LLM_POOL=auto` pools every provider that has a key, and a JSON list of `{"provider": ..., "model": ...}` objects also works. Pool names accept common aliases, such as `zai` or `glm` for `zhipu` and `moonshot` for `kimi`. See [Several providers in one market](#several-providers-in-one-market).

**Usage limits pause the run instead of breaking it.** When a Claude Code, Codex or Antigravity login hits a limit, its gateway reads the reset time, stops sending calls and answers `429` with `Retry-After`. `market-test` and `study` check every gateway in the pool and wait up to 12 hours (the CLI finds the pool's gateways in `MIROFISH_ENV_FILE`, else `.env`, so run it with the backend's settings file). Then they redo only the test step that was hit (feed test, email test, rounds, survey, pitch, panel or report), so a half-answered survey never becomes a result. A provider paused for longer than that is skipped, and its calls are counted as failed. Preparation does not wait: people a paused provider could not write are left out and counted. `curl 127.0.0.1:5055/health` shows `paused`, `paused_until` and `limit_hits`.

**Pick the gateway's model.** Through the Claude Code gateway most steps make one Claude Code call per simulated person (persona writing and interviews batch 4 people per call), and the model decides how fast your subscription's limit runs out. The gateway uses Sonnet unless you set `LLM_GATEWAY_MODEL` (`haiku`, `sonnet`, `opus`, a full model id, or `default` for Claude Code's own default) or pass `--model` (for example `./mm gateway start claude --model haiku`); an `LLM_MODEL_NAME` set in `.env` is replaced each time a gateway starts on 5055. A 1,000-person run makes several thousand calls (the measured 1,000-person run below: 434 feed-test calls, 1,159 round actions, 1,038 survey interviews). With an API key there is no session limit. Social rounds run up to 50 calls per platform (`OASIS_SEMAPHORE`). Persona writing and interviews default to at most 16 calls in flight, split across providers. Set `MM_LANE_<PROVIDER>` (for example `MM_LANE_DEEPSEEK=50`) to run more.

**Prompt caching with a Claude API key.** With `ANTHROPIC_API_KEY` (provider `claude`), Claude is called through Anthropic's native Messages API (the official `anthropic` SDK) instead of its OpenAI-compatible endpoint, which does not cache. Prompts that many calls share put their shared part first (the brief, context, rules and JSON schema for writing people, interviewing them and showing them a feed) with a cache breakpoint after it, so later calls read it at about a tenth of the input price; each person's own details come after the breakpoint. Cache reads and writes are counted in the usage figures. `MM_CACHE_TTL=1h` keeps entries for an hour instead of five minutes (writes cost 2x instead of 1.25x), `MM_CLAUDE_EFFORT` sets the effort for these calls (default `low`; empty uses the model's own), and `MM_CLAUDE_NATIVE=off` goes back to the OpenAI-compatible endpoint. Measured on 12 full-depth people with `claude-opus-5-5`: 9 calls in 163 s, 5,002 input tokens read from the cache; output was most of that test's cost, so caching pays most on input-heavy stages. The social rounds, survey and pitch run inside the OASIS engine and do not use this yet.

**Choose a provider in the browser.** After `./mm start`, `./mm cli setup` opens a settings page (this computer only). There you pick a Claude Code, Codex or Antigravity login (ports 5055/5056/5057) or any supported API key, store the Jev key, start and stop gateways (stopping one here stops it for every backend that uses it), test the connection and apply the change to the running backend. For Antigravity, choose a Gemini Flash model rather than the default Argon (see below). Keys are stored owner-only in `.env` and shown masked; the page needs the one-time token in its link.

Start a login gateway **before** `./mm provider check` and `./mm start`. Several gateways can run side by side on different ports (`--port`); see [Several providers in one market](#several-providers-in-one-market). If changing providers while the backend is running, restart it with `./mm stop` followed by `./mm start`.

### Several providers in one market

One simulated market can be played by several model providers at once. Each provider writes an equal share of the people, interviews them, plays them in the social rounds and answers for them in every test, so with `LLM_POOL_STRICT=true` one model speaks for a person from start to finish (without it, rounds and tests may fail over to another provider). The dashboard then splits the results by provider ("Do the models agree?") with 95% ranges.

Start one login gateway per provider, each on its own port:

```bash
LLM_GATEWAY_WORKERS=12 LLM_GATEWAY_EFFORT=low ./mm gateway start claude                          # 5055
LLM_GATEWAY_WORKERS=7 LLM_GATEWAY_EFFORT=low ./mm gateway start codex --port 5056 --model gpt-6-luna
LLM_GATEWAY_WORKERS=10 ./mm gateway start antigravity --port 5057 --model gemini-3.8-flash-low
```

`LLM_GATEWAY_WORKERS` is how many CLI calls a gateway runs at once. The default is 2, so raise it to match the lane limits below. `LLM_GATEWAY_EFFORT` (`low`, `medium`, `high`, `xhigh` or `max`) sets Codex's reasoning effort and Claude Code's effort level. Antigravity takes its effort from the end of the model id (`-low`, `-medium`). `LLM_GATEWAY_TIMEOUT` is the limit per call (default 180 s).

Then give a backend these settings in its own file, for example `.env.mixed` copied from `.env`. Take each gateway's token from `backend/logs/gateway.token` (port 5055) or `backend/logs/gateway-<port>.token` (other ports). The same token is also written into the `.env.<backend>` file that `gateway start --port` creates. Keep the pool out of `.env` itself: starting a gateway on 5055 rewrites `.env` and removes `LLM_POOL` from it.

```bash
LLM_POOL=claude_code:sonnet,codex:gpt-6-luna,antigravity:gemini-3.8-flash-low
LLM_POOL_STRICT=true                       # rounds and tests also stay on each person's provider
MM_LANE_CLAUDE_CODE=12                     # calls in flight per provider (see "Writing people fast" below)
MM_LANE_CODEX=7
MM_LANE_ANTIGRAVITY=10
CLAUDE_CODE_GATEWAY_URL=http://127.0.0.1:5055/v1
CLAUDE_CODE_GATEWAY_KEY=...
CODEX_GATEWAY_URL=http://127.0.0.1:5056/v1
CODEX_GATEWAY_KEY=...
ANTIGRAVITY_GATEWAY_URL=http://127.0.0.1:5057/v1
ANTIGRAVITY_GATEWAY_KEY=...
```

```bash
./mm start --port 5011 --env-file .env.mixed
MIROFISH_ENV_FILE=.env.mixed MIROFISH_URL=http://localhost:5011 ./mm cli market-test scenarios/acme/market_test.json
MIROFISH_URL=http://localhost:5011 ./mm live --run-dir mirofish_runs/acme --port 5060   # watch it
```

Use ports nothing else is using. If a gateway already runs on a port, `start` leaves it as it is; to change its workers or effort, stop it first.

A backend on any port other than 5001 keeps its data (projects, tasks, local graph and population cache) in `backend/uploads-<port>/` and its log in `backend/logs/server-<port>.out`, so it runs beside the default one. `./mm start --port` is the same as `backend/claude_cli/start_server.sh --port`.

Writing and interviewing the people is always strict: one provider per person, with failures counted. `LLM_POOL_STRICT=true` makes the social rounds and tests strict as well. Without it those later calls fail over to the next provider, which is faster but mixes models. Cost and usage lines count calls by the provider that actually answered. A difference between providers mixes the model and the people it wrote, so agreement is a robustness check, not evidence about real buyers. To compare separate runs instead (each provider with its own people in its own run), use `./mm cli compare --run Claude=mirofish_runs/a --run Codex=mirofish_runs/b --out mirofish_runs/compare`, which writes `comparison.json` and `comparison.html` in the `--out` folder.

What the check looks like: in a 12-person mixed market (4 simulated people per provider), 1 of 3 checks agreed. The would-convert ranges overlapped, because every provider's people said 0% yes (95% range 0-49%, n = 4 each). The top objection differed (Codex and Gemini: price; Claude: trust), and so did the best message (Codex #1, Gemini #3, Claude #2). With 4 people per provider the ranges are too wide to read more into it.

Login subscriptions have their own limits. Antigravity's Gemini 4 Argon quota ran out after a few dozen calls in our test (the reset was about 160 hours away), while Gemini 3.8 Flash kept answering. The gateway reads the reset time and pauses that provider. A reset more than 12 hours away is longer than `market-test` waits, so that provider's calls fail and are counted; pick a Flash model for Antigravity.

### Writing people fast without losing depth

At the default depth (`"depth": "full"` in the persona spec) every simulated person gets the full treatment: a persona with a 150-250 word description, a 12-question life interview with a first-person summary, follow-up questions chosen from their answers, product questions and a decision card. Each call covers 4 people (`MM_DEEP_BATCH`). The calls are run like this:

- **No waiting between stages.** Each batch of 4 people goes straight from persona to interview to follow-ups; it does not wait for the rest of its audience.
- **One lane per provider.** Writing and interviews share a per-provider limit on calls in flight, so a slow provider never holds up a fast one. Without a setting, each lane starts at the run's `parallel` divided by the number of providers. `parallel` is the `market_test.json` key or `--parallel`, capped at 16 here; its default is the CPU count, kept between 4 and 16. `MM_LANE=N` sets every lane, and `MM_LANE_<PROVIDER>` one of them: `<PROVIDER>` is the pool name in `LLM_POOL` (`MM_LANE_CLAUDE_CODE`, `MM_LANE_CODEX`, `MM_LANE_ANTIGRAVITY`, `MM_LANE_DEEPSEEK`, ...); with a single login gateway it is the gateway's name (`MM_LANE_CLAUDE`, `MM_LANE_GEMINI`). Keep a gateway's lane at or below its `LLM_GATEWAY_WORKERS`. A rate limit halves the limit. A timeout or server error lowers it by one, never below half the starting value. It grows back by one after twice the limit in successes, up to the starting value. After 8 failures in a row the lane pauses 60 s (`MM_LANE_BREAK_AFTER`, `MM_LANE_BREAK_PAUSE_S`), and after 40 it stops (`MM_LANE_DEAD_AFTER`). The people still waiting on that lane are counted as missing.
- **Nothing written twice.** Answers come back as compact JSON: numbered rows instead of echoed names, the 12 answers as a list instead of repeating every question, no fixed demographics written back, short keys for the decision card. That is about a quarter fewer output tokens for the same information.
- **Only the missing are asked again.** Rows still missing or broken are re-asked together in one call; the rest of the batch is kept. Answers from another provider are not used. A person whose persona row is still missing after three tries is left out and counted, never filled in by code. A person whose interview or follow-ups still fail is kept, marked as depth `profile` (or interviewed without follow-ups), and counted. Unreadable answers are saved under `debug/unreadable_answers` in the upload folder.
- **A cache.** Every usable answer is stored under a hash of the prompt, provider and model, so a rerun or a restart after a crash costs nothing for the people already written. The file is `population_cache.sqlite` in the backend's upload folder: `backend/uploads/` on 5001, `backend/uploads-<port>/` on other ports. Override it with `MM_POPULATION_CACHE=<path>`, or set `MM_POPULATION_CACHE=off` to disable it. Each login gateway also caches identical low-temperature prompts in its own file (`gateway_cache.sqlite` on 5055, `gateway_cache_<port>.sqlite` on other ports, under `backend/uploads/`); `LLM_GATEWAY_CACHE` sets the path, and `''` turns it off.

Measured on the login gateways on 2026-10-20 (single-batch spot checks of one 4-person batch, all fields complete; the raw files were not kept):

| Provider | Setting | Persona batch | Interview batch | Calls in flight |
|---|---|---:|---:|---|
| Codex | `--model gpt-6-luna` + `LLM_GATEWAY_EFFORT=low` (default model: 82 s and 151 s) | 28 s | 35 s | about 7 per login; more are held back |
| Gemini via Antigravity | `--model gemini-3.8-flash-low` (medium: 62 s and 66 s, with hidden thinking) | 50 s | 56 s | 10; 16 at once still raised throughput |
| Claude Code | Sonnet + `LLM_GATEWAY_EFFORT=low` | 39 s | 53 s | 12-16 |

With these models and lane limits, 60 full-depth people (20 per provider) were written and interviewed, and 57 of them followed up, in 6 minutes 7 seconds; see [Measured runs and costs](#measured-runs-and-costs). The Codex and Antigravity CLIs add about 20,000 tokens of their own instructions to every call (21-23k input tokens per call in the 12-person feed test; Claude Code reported about 2,400) and need a few seconds to start, which an API key avoids.

**Depth for large audiences.** `"depth": "fast"` writes compact cards for everyone in batches of 20 (`MM_CARD_BATCH`) and gives the full life interview to `interview_share` (default 10%) of every audience and provider pair, at least 2 per pair. `"depth": "auto"` uses full depth up to 300 people and fast depth above that (`MM_FAST_ABOVE`). Each person records their depth: `interviewed`, `profile` (the interview failed) or `card`. A persona spec may ask for up to 5,000 people; raise the limit with `MM_MAX_PERSONAS` in the backend's settings.

**Social rounds at scale.** Set `OASIS_MAX_ITERATION=1` (default 3) so each active person makes one model call per turn. Other settings: `OASIS_SEMAPHORE` (model calls in flight per platform, default 50), `OASIS_ACTIVE_AGENT_CAP` (most people acting per round), `OASIS_MEMORY_WINDOW` (messages each person keeps, default 10) and `OASIS_TOKEN_LIMIT` (default 32000). `MODEL_TIMEOUT` is 60 s, or 420 s through a login gateway. `OASIS_ACTION_TIMEOUT` is 120 s, or 480 s through a gateway, and unless you set it, it stays at least 60 s above `MODEL_TIMEOUT`.

**Surveys, pitches and analysts at scale.** Survey and pitch send up to 120 people per interview call (`MM_INTERVIEW_BATCH` for the survey and the CLI pitch; `--batch` on each command; the pitch inside `market-test` and `study` always uses 120; `./mm cli test` defaults to 40). Each survey call waits up to `MM_INTERVIEW_WAIT_S` (720 s; the pitch always waits 720 s). Each interview has its own deadline, `MM_INTERVIEW_DEADLINE_S` (540 s). Set `MM_INTERVIEW_BATCH` and `MM_INTERVIEW_WAIT_S` in the shell that runs `./mm cli`; `MM_INTERVIEW_DEADLINE_S` is a backend setting. An interview that misses it gets no answer instead of an older one. The survey saves `survey_partial.json` after every batch, waits before a batch while any gateway is paused, and logs and skips a batch that fails. At the end it asks everyone without a usable answer once more, and it fails only when nobody answered. The pitch mixes providers in every batch; a failed batch is reported in `pitch.json` (`failed_batches`, `failed_batch_errors`, and `unanswered` per turn) instead of stopping the pitch. Analysts read at most about 80,000 characters of material. Longer material is thinned evenly, and the analysts are told what was cut.

**Stopping a survey early.** Add `"survey": {"settle": {"margin": 5, "min_n": 60, "cells": "provider"}}` to `market_test.json`, or run `survey --settle [--settle-margin 5 --settle-min 60 --settle-cells provider|segment|segment,provider|all]`. People are asked in waves of one batch, shuffled and dealt across cells. A cell stops once it has at least `min_n` answers and every yes/maybe/no share is within ±margin (checked with z = 2.5, because the results are looked at after every wave). The default cell is the provider, so use `segment` to settle per audience. In settle mode nobody is asked a second time. The survey file and the dashboard say how many were asked and why it stopped. Fast depth and settle are off unless you ask for them.

What we borrowed from other large-scale simulators, and what we chose not to, is in [speed research notes](docs/SPEED_RESEARCH.md).

### API keys: cost and speed

Prices checked on 2026-10-20 against the providers' pages; they change often. Token volumes for 3,000 people: preparing them in full depth is about 7M input and 10.5M output tokens; the whole market test afterwards (survey, sales pitch, feed test, four social rounds) is roughly 84M input and 8.4M output tokens (an estimate from the prompt sizes), most of it the same persona prefix again, which prompt caching discounts where the provider offers it. The prices below leave each model's hidden reasoning on (its default), which roughly doubles the output tokens for the DeepSeek models; with thinking off they are about half. They are estimates from these volumes, not measured bills.

| Model and route | Price per 1M tokens (in / out) | Prepare 3,000 full-depth people | Market test for 3,000 | Speed per call |
|---|---|---:|---:|---|
| DeepSeek V4.1 Flash via OpenRouter (cheapest endpoint, pinned) | $0.09 / $0.18 | about $4.65 | about $9.60 | 80-200 tokens/s depending on the endpoint |
| DeepSeek V4.1 Flash via OpenRouter (inference.net) | $0.08 / $0.50 | about $11.70 | about $11.50 | about 133 tokens/s |
| DeepSeek V4.1 Flash, DeepSeek's own API (off-peak; peak is double) | $0.15 / $0.60, cache hits $0.003 | about $13.70 | about $17.60 | about 60 tokens/s, 2,500 calls in flight allowed |
| DeepSeek V4 Pro via OpenRouter | $0.66 / $1.98 | about $49 | about $76 | about 30-50 tokens/s |
| gpt-oss-120b on Cerebras | $0.35 / $0.75 | about $14 | about $37 | about 760 tokens/s; capped at 1M tokens per minute (about 23 minutes for the 3,000) |
| Claude Haiku 5.5 (Anthropic API) | $0.10 / $0.50 | about $7.50 | about $12.60 | about 136 tokens/s |
| Claude Sonnet 5.5 (Anthropic API) | $2 / $10 | about $170 | about $252 | about 90 tokens/s |

OpenRouter adds 5.5% when you buy credits (bring-your-own-key is free up to $25,000 a month) and sets no rate limit of its own on paid models; its default routing balances across endpoints, so pin the provider to get one endpoint's price. Persona writing and interviews run at most 16 calls in flight by default. With 50 in flight (`MM_LANE_DEEPSEEK=50`, `MM_LANE_OPENROUTER=50` through OpenRouter, or `MM_LANE=50`), preparing 3,000 full-depth people would take roughly 20-55 minutes on DeepSeek Flash; that is an estimate, not a measured run. These are list prices for the stated token volumes, not measured bills; measure a small run first.

API keys are entered privately in your terminal. `./mm configure --open-guide` can open the provider's key console; `./mm provider status` shows masked configuration. Agents can configure an existing secret with `--key-env` instead of placing it in tool arguments. See [provider setup and troubleshooting](docs/LOCAL_AGENTS.md).

### Scoring with Jev (optional)

[Jev](https://docs.typesafe.ai/introduction/quickstart) is TypeSafe's decision model. It does not write text: it reads a piece of text and answers typed questions (pick one label, place it on a scale, yes or no) with a probability for every option. MarketMirror can use it in three places:

- **Rating distributions.** Each free-text survey answer is scored against the same five anchor statements the embedding method uses (level 0 = rating 1 ... level 4 = rating 5), and Jev's probabilities become the 1-5 distribution. The embeddings stay the default. `auto` uses Jev and falls back to the embeddings for the answers Jev did not rate, and records which engine rated each one. In `jev` mode an answer Jev fails on gets no rating and is counted as failed.
- **Concern classification.** `gtm voc --classifier jev` labels the real text and the simulated objections with the same Jev question (concern types plus "none").
- **Objection check.** `survey --objection-check` has Jev label each person's main objection with the survey's objection types and reports how often that matches the person's own tag, as a percentage with a 95% range (one line in the dashboard's Objections section).

Jev cannot write or play the simulated people; the chat model you chose above still does that. Its accuracy for these tasks has not been validated in this project, so treat a Jev distribution as a different measurement, not a better one; the dashboard's go / iterate cut-offs were set on the embedding method.

To enable it, set `TYPESAFE_API_KEY` in `.env` (direct to `api.typesafe.ai`), or use OpenRouter with `OPENROUTER_API_KEY` and `JEV_VIA=openrouter`. `JEV_MODEL` overrides the model (`jev-latest` direct, `~typesafe/jev-latest` on OpenRouter), `JEV_BASE_URL` the endpoint, `JEV_PARALLEL` the number of parallel requests (default 4), `JEV_TIMEOUT` the seconds per request (default 60) and `JEV_RETRIES` the retries (default 3). Then choose where to use it: `SSR_ENGINE=jev` (or `auto`) for every survey, `survey --ssr-engine jev`, or `"survey": {"ssr_engine": "jev", "objection_check": true}` in `market_test.json`. `./mm cli jev check` shows whether a key is configured and which route and model would be used without calling the API; `--ping` sends one request. Each result records the requests, failures and tokens used (and the cost when OpenRouter reports it).

The default knowledge graph uses local SQLite and local embeddings; no Zep account is required. Model downloads and public-source research require network access. Hosted providers and CLI gateways receive model prompts through the selected provider. Model usage remains subject to that account's limits and charges.

## Connect your agent

Use MarketMirror from Codex, Claude Code, Cursor, Gemini, or another client supporting its MCP transport. Install and configure the engine first using the quick start above.

### Codex plugin

From the repository root:

```bash
codex plugin marketplace add "$PWD"
codex plugin add market-mirror@market-mirror-local
```

### Claude Code plugin

```bash
claude plugin marketplace add "$PWD"
claude plugin install market-mirror@market-mirror
```

The plugin bundles the main workflow plus focused research, planning, testing, and evidence-review Agent Skills. They share one canonical source. Client plugin support and configuration locations vary; see the [plugin guide](plugin/README.md).

### Any compatible MCP client

Print configuration for your client without overwriting its settings:

```bash
./mm agent-config --client generic
# Also supports: codex, claude, cursor, gemini
```

The output contains an absolute server path and engine location. Copy the entry into your client's MCP configuration and restart the client. The stdio server can also be launched with `./mm mcp`.

For authenticated loopback HTTP MCP:

```bash
python3 plugin/skills/market-mirror/scripts/mcp_server.py \
  --http --port 5061 --token-file /absolute/path/to/private-token
```

Create a private token file containing a random bearer token of at least 24 characters. Connect to `http://127.0.0.1:5061/mcp` using that token. This transport is intended for local agents, not a hosted remote service.

Try this in your agent:

> Use MarketMirror to analyze our product and campaign performance. Bring in ad and analytics data from tools you have authorized access to, or use the exports I provide. Research cited customer feedback, survey a small simulated audience, and compare two ads or offers. Test our product URL with synthetic visitors, show the evidence and missing inputs, and recommend the next real experiment.

Core tools: `doctor`, `provider_setup`, `understand`, `ads_import`, `ideas`, `website_test`, `research`, `actuals_import`, `campaign_plan`, `run_test`, `study`, `job_status`, `holdout_backtest`, `predict`, and `results`. Long jobs return status, logs, and result paths. Poll `job_status` before treating a job as complete.

## Example workflow

```mermaid
flowchart LR
    A[Product brief] --> B[Product profile]
    C[Cited public feedback] --> D[Campaign plan]
    J[Connected ad data or exports] --> D
    B --> D
    D --> E[Surveys, campaign tests and website journeys]
    E --> F[Compare scenarios]
    F --> G[Next real experiment]
    G --> H[Import observed results]
    H --> I[Backtest and calibration]
    I --> D
```

After quickstart creates `scenarios/acme/`, replace its example content with your product material:

```bash
./mm cli understand --docs scenarios/acme/brief.md --name Acme \
  --out scenarios/acme/product_profile.json

./mm cli research --query "home workout app" --country in \
  --out scenarios/acme/research

./mm cli campaign-plan --profile scenarios/acme/product_profile.json \
  --research scenarios/acme/research/voices.json \
  --goal "trial signup" --budget 500 --currency USD \
  --channels search organic paid_social email sales referral \
  --out scenarios/acme/campaign_plan.json
```

The plan contains `test_specs`, cited evidence, assumptions, and unknowns. Channel budgets start as equal draft allocations. Review the claims and allocations, save a selected spec as `experiment.json`, and test it on a prepared simulation:

```bash
# Set this to the ID returned by your preparation step.
SIMULATION_ID=sim_replace_me
./mm cli test --simulation "$SIMULATION_ID" --spec @experiment.json
./mm cli study --spec study.json
```

`experiment.json` and `study.json` are your reviewed input files; [input examples](docs/INPUT_FORMATS.md) and `./mm cli study --help` describe their contracts. Study cells reuse completed work; rerun the same specification to resume. Each independent comparison should begin from the same initial state and matched scenario seeds.

Import actual outcomes when available. This example expects an export with `Day`, `Country`, `Views`, and `Clicks` columns:

```bash
./mm cli actuals-import exports/campaign.csv --source-type ads \
  --map date=Day market=Country impressions=Views clicks=Clicks \
  --out scenarios/acme/actuals.json

./mm cli holdout-backtest --pairs experiments_with_train_and_holdout.json \
  --out scenarios/acme/holdout_backtest.json
```

The importer retains source, date, market, and quality labels and returns row-level validation errors. Backtests require explicitly paired simulated and real outcomes with declared training/holdout splits; the imported export alone is not a ready-made holdout dataset.

<details>
<summary>Useful commands after preparing a simulation</summary>

```bash
./mm cli profiles --simulation "$SIMULATION_ID" --brief
./mm cli feedtest --simulation "$SIMULATION_ID" --creatives @creatives.json --seeds 3
./mm cli survey --simulation "$SIMULATION_ID" --offer "Acme trial" \
  --goal "start a trial" --messages @messages.txt --split --pricing USD
./mm cli emailtest --simulation "$SIMULATION_ID" --emails @emails.json
./mm cli pitch --simulation "$SIMULATION_ID" --script @pitch.md --rebuttals @rebuttals.md
./mm cli report --simulation "$SIMULATION_ID" --run-dir mirofish_runs/acme
```

If preparation saved a complete profile set but stopped before its configuration was ready, use `./mm cli prepare --simulation "$SIMULATION_ID" --resume-only`. It reuses saved profiles and refuses to regenerate incomplete sets.

Keep inputs under `scenarios/` and outputs under `mirofish_runs/`; both are gitignored. Use `./mm cli --help` for the full command list.

</details>

## Reports and visualization

Each run produces one self-contained HTML dashboard: no server, no external requests, light and dark themes, and phone layouts. A sidebar groups its sections into overview, buyers, tests, evidence and the simulation itself; every chart has a table behind it, and the report exports to Markdown, JSON, CSV and PDF. In runs with more than 500 agents, the agents table lists the 500 most active and says so; everyone is still in the people cards and the CSV downloads. The screenshots below come from the 1,000-person Fitloop run and the offer study.

<table>
<tr><td colspan="2"><b>Overview</b></td></tr>
<tr>
<td width="50%" valign="top"><img src="docs/images/glance.png" alt="At a glance KPI cards, the decision card and the one-page brief" /><br /><b>At a glance and the decision.</b> Headline numbers, the go / iterate / no-go call with the signals behind it, and a one-page brief with three actions, a budget plan and the next 30 days.</td>
<td width="50%" valign="top"><img src="docs/images/map.png" alt="World map of the simulated people with a metric switcher and a per-country table" /><br /><b>Where they are.</b> A world map of the simulated people. Switch between people, would-convert, ad CTR, pitch yes and lead score per country; the table lists top cities and where people live.</td>
</tr>
<tr><td colspan="2"><b>Buyers</b></td></tr>
<tr>
<td width="50%" valign="top"><img src="docs/images/results.png" alt="Survey results: what the simulation says, rating bars and purchase intent by audience" /><br /><b>What buyers said.</b> Purchase intent, interest, trust and word of mouth from free-text answers, mapped to 1–5 distributions and broken down by audience.</td>
<td width="50%" valign="top"><img src="docs/images/audiences.png" alt="Audience comparison with intent bars and a sortable table" /><br /><b>Which audience to target.</b> Every segment, country, community, age band and gender side by side, with intent, trust, would-convert and the top objection.</td>
</tr>
<tr>
<td width="50%" valign="top"><img src="docs/images/objections.png" alt="Objections chart and quotes grouped by objection" /><br /><b>What stops people.</b> Objections ranked by share, each with real-sounding quotes and what would change that person's mind.</td>
<td width="50%" valign="top"><img src="docs/images/messages.png" alt="Split-test results and best message per audience" /><br /><b>Which message wins.</b> A randomized split test of your messages, plus the best message for each audience.</td>
</tr>
<tr><td colspan="2"><b>Tests</b></td></tr>
<tr>
<td width="50%" valign="top"><img src="docs/images/feed-test.png" alt="Platform-style ad preview with feed reactions, click funnel and spend projection" /><br /><b>Ads in realistic feeds.</b> Each ad shown in its platform's feed among organic posts: thumb-stop, CTR, what happened after the click, comments, and a spend projection.</td>
<td width="50%" valign="top"><img src="docs/images/social-feed.png" alt="Brand posts with replies and activity per round from the social simulation" /><br /><b>Social feed.</b> Every post of the simulated social rounds, with likes, replies and their sentiment, filters by round, audience and country, and activity per round.</td>
</tr>
<tr>
<td width="50%" valign="top"><img src="docs/images/pricing.png" alt="Van Westendorp price sensitivity with acceptable range and sweet spot" /><br /><b>What people would pay.</b> Acceptable price range, sweet spot and the price-sensitivity curves, by segment.</td>
<td width="50%" valign="top"><img src="docs/images/playbook.png" alt="Sales and marketing playbook cards per audience" /><br /><b>The playbook.</b> One card per audience: what to lead with, the objection to pre-empt, how to answer it, where to seed it, and a quote as proof.</td>
</tr>
<tr><td colspan="2" valign="top"><b>Marketing lab and model agreement.</b> The marketing lab (buying committee, creative optimizer, battlecard, journey, pricing choice, competitor choice, landing teardown, roleplay, what-if, per-audience ads, search behaviour, real versus simulated concerns, word of mouth) shows every result with how many people were asked, answered and failed, and a 95% range. In a market with several providers, "Do the models agree?" splits the survey by provider and checks whether the would-convert ranges overlap and whether the top objection and best message match.</td></tr>
<tr><td colspan="2"><b>Evidence</b></td></tr>
<tr>
<td width="50%" valign="top"><img src="docs/images/analysts.png" alt="Independent analyst panel with consensus, themes and five analyst cards" /><br /><b>Analyst panel.</b> Five analysts read the run independently; their consensus, the themes they agree on, and each one's recommendation.</td>
<td width="50%" valign="top"><img src="docs/images/people.png" alt="Cards for each simulated person with interview summary, phone, groups and lead score" /><br /><b>The simulated people.</b> Every person's life story from a short interview, phone and data plan, groups, what they did in the run, and a lead score. Filter by segment, country, verdict and lead score.</td>
</tr>
<tr>
<td width="50%" valign="top"><img src="docs/images/report.png" alt="The plain-language report with contents, decision lead and tables" /><br /><b>The report.</b> A plain-language report with contents, the decision up front, who was simulated, results, objections, pricing, sales notes, an action plan and its limits. Exports to Markdown, JSON, CSV and PDF.</td>
<td width="50%" valign="top"><img src="docs/images/study.png" alt="Study page comparing three offers across three seeds" /><br /><b>Studies.</b> Several scenarios on the same people, each with several seeds: the winner, the side-by-side table, what changed and whether it is outside the seed spread.</td>
</tr>
<tr><td colspan="2"><b>Live</b></td></tr>
<tr>
<td colspan="2" valign="top"><img src="docs/images/live.png" alt="Live control room with run stages, counters, every simulated person and the activity stream" /><br /><b>Live control room.</b> Watch a run as it happens at <code>/live</code>: each stage, every simulated person lighting up as they act and taking their answer's colour, what they post and comment, and the progress log.</td>
</tr>
</table>

Fitloop, its audiences and its pilot figures are invented; every number in these screenshots is simulated, not observed campaign performance. Report generation checks numbers against the run's fact sheet and falls back to a data-only report if the model fails. Those checks establish consistency with saved outputs, not real-world accuracy.

## Evidence and simulation limits

- **Generated interviews remain synthetic.** Detailed biographies and BDE profiles do not turn invented people into customer evidence.
- **Behavior controls are assumptions.** Attention, fatigue, social proof, and landing friction include hand-set priors that need validation for the intended market.
- **Seed variation measures simulation variation.** It is not a predictive confidence interval. Repeated agreement and synthetic test–retest consistency do not establish agreement with humans.
- **Backtests answer specific questions.** The existing no-persona comparator is the mean real outcome in the training set. Beating it alone does not establish general predictive reliability or replace a matched generic-reader LLM comparison.
- **Calibration depends on coverage and assumptions.** Uncalibrated predictions omit intervals and success probabilities. Validate absolute rates, rankings, and subgroup findings separately on untouched real experiments.

Read the [human-behavior research guide](docs/HUMAN_BEHAVIOR_RESEARCH.md) for the papers, inspected code gaps, and proposed memory/state architecture. It distinguishes implemented controls from future work and experimentally supported results.

## Example: which offer should Fitloop launch with?

A study ran three offers on the same 150 simulated buyers, three seeds each (9 cells, about 10 minutes per cell through the local Claude Code gateway). Each number is the mean across seeds, with the lowest and highest seed in brackets; the brackets show simulation variation only.

| Measure | No card, USD 4.99 | Card required, USD 4.99 | No card, USD 2.99 |
|---|---:|---:|---:|
| Purchase intent (1–5) | 3.51 (3.46–3.60) | 3.01 (2.99–3.04) | 3.60 (3.59–3.60) |
| Would start the trial (%) | 4.1 (2.7–5.4) | 0.2 (0.0–0.7) | 6.7 (5.3–8.0) |
| Would click (%) | 7.7 (3.3–16.5) | 10.9 (8.0–12.7) | 23.5 (21.3–25.3) |
| Trust (0–10) | 3.6 (3.4–4.0) | 3.4 (3.3–3.4) | 4.1 (4.1–4.1) |
| "Looks like a scam" as top objection (%) | 54.6 (47.5–59.7) | 88.2 (86.7–90.7) | 60.5 (58.0–62.7) |
| Decision across seeds | iterate in 2 of 3 | no-go in 3 of 3 | iterate in 2 of 3 |

**What the study concluded.** Requiring a card was a clear loss in every seed: intent fell by 0.5, would-start fell by 3.9 points, "maybe" answers fell by 44.8 points, and scam worry rose by 33.6 points, all outside the seed spread. Dropping the price to USD 2.99 lifted would-click (+15.8 points) and trust (+0.47) beyond the spread, but its intent gain (+0.09) stayed inside it, so the price cut is not a clear winner even in simulation. It came out best in 2 of 3 seeds, and the study's summary marks its result as not supporting a predictive claim. The recommendation: keep the trial card-free, work on trust (proof, a named company, a clear "no card needed" line), and run a small randomized real test of USD 2.99 against USD 4.99. The full write-up is generated as `study_report.md` next to `study.html` in the study folder.

<img src="docs/images/study.png" alt="The Fitloop offer study page: conclusion, a card per offer and the side-by-side table" width="100%" />

## Measured runs and costs

These are local Fitloop measurements, not speed guarantees. Model, hardware, activity settings, concurrency, and provider limits affect runtime. Every rate in this section is simulated.

| Run | Simulated buyers | Scope | Measured wall time | Feed-test calls | Invoiced cost |
|---|---:|---|---:|---:|---|
| Fitloop launch | 28 | Marketing pipeline | 28m 12s | 75 | Unavailable |
| Fitloop | 150 | Marketing pipeline | 54m 50s | 262 | Unavailable |
| Fitloop mixed market check | 12 (4 each from Claude, Codex and Gemini) | Feed test, 2 social rounds (37 actions), survey, pitch, through the three login gateways | 17m 50s | 23 (Claude 8, Gemini 8, Codex 7) | Subscriptions (no invoice) |
| Fitloop large (social only) | 1,008 | Six Reddit social rounds only | 3m 42s | Not measured | Unavailable |
| Fitloop 1,000 | 1,008 | Full pipeline on Sonnet via the Claude Code gateway: feed test, 4 Reddit rounds, survey of 1,008 + retest of 30, 5 analysts, report | about 52m of active work | 434 | Subscription (no invoice) |

The 1,000-person run's active time breaks down as feed test 10m 17s (434 calls, 1,296,106 input and 375,768 output tokens), four social rounds 18m 28s (1,159 actions), survey and retest 20m 29s, report 1m 26s; the analyst panel failed during that run (all five analysts; fixed afterwards) and was run again later. Its wall-clock time was much longer: the Claude Code session limit paused it for 4h 12m mid-survey, it was resumed by hand the next morning, and the four social rounds were run again, so the active times above count only the final pass. With an API key there is no session limit.

Preparing the people is measured separately, through the three login gateways. "Writing the people" is the persona planner alone (personas, interviews and follow-ups); "upload to ready" adds the knowledge graph, agent profiles and simulation config. At full depth the decision card comes from the follow-up call, so that column is also the number followed up.

| Run | Depth | People (Claude / Codex / Gemini) | Interviewed | Decision card | Not written | Writing the people | Upload to ready |
|---|---|---|---:|---:|---:|---:|---:|
| Full-depth speed check | full | 60 (20 / 20 / 20) | 60 | 57 | 0 | 6m 7s | 7m 16s |
| Fast population check | fast | 150 (45 / 55 / 50) | 24 | 150 | 0 | 7m 29s | 8m 51s |
| Fitloop 3,000 mixed market | full | 2,999 (1,000 / 999 / 1,000) | 2,987 | 2,905 | 1 | 2h 40m 11s, with a restart | 2h 57m 31s, with a restart |

The 60- and 3,000-person runs used Sonnet, gpt-6-luna and gemini-3.8-flash-low. The 150-person run used Sonnet, Codex's default model and gemini-3.8-flash-medium; its 24 interviews are 4 per audience. It predates the even per-audience split (each audience was split 20 + 5 between two providers, hence 45 / 55 / 50); current runs split every audience evenly across all providers.

The 3,000-person times are not a clean single pass. At 14:34, after 1,865 of 3,000 people, the backend was restarted to apply a lane fix (hung calls had cut the Gemini lane from 10 to 2; now only a rate limit halves a lane). The new prepare task replayed 1,043 finished answers from the population cache and wrote the rest; that second part alone took 1h 54m 39s. After the people were written, the 3,011 agent profiles took about 7.5 minutes and the simulation config about 9.5 minutes.

### The 3,000-person mixed market

One Fitloop market of 3,000 requested people, a third each written, interviewed and played by Claude Sonnet, Codex (gpt-6-luna) and Gemini 3.8 Flash (`gemini-3.8-flash-low`). The persona spec asks for full depth with interviews and follow-ups, six audiences in India, the Philippines and Kenya, and five communities: Bengaluru Fitness Buddies (WhatsApp), Working Moms & Dads India (Facebook), Fit Pinoy Community (Facebook), Nairobi Runners & Gym Rats (WhatsApp) and r/budgetfitness. Each person joins at most 2 communities.

What is final now is the simulated population:

| | Claude | Codex | Gemini | All |
|---|---:|---:|---:|---:|
| People written | 1,000 | 999 | 1,000 | 2,999 |
| Interviewed | 1,000 | 987 | 1,000 | 2,987 |
| With a decision card | 980 | 933 | 992 | 2,905 |

- One requested person was not written because their calls failed. They are counted, not filled in.
- The 12 Codex people whose interview failed are kept at depth `profile`. 82 interviewed people have no decision card.
- Audiences: Students 642, Philippines young professionals 536, India young professionals 534, India parents 429, Philippines parents 429 and Kenya young professionals 429, each split evenly across the three providers. By country: India 1,284, the Philippines 1,125 and Kenya 590.
- The stereotype guard changed 20 people and found no audience with too little variety.
- With 7 actors from the knowledge graph and the 5 community accounts, the simulation has 3,011 agents, each with a profile.
- After the restart, the lanes made 471 Claude, 832 Codex and 688 Gemini calls (1,991 in all); the other 1,043 answers came from the cache written before the restart, whose calls are not counted here. The Gemini lane recorded 8 overloads and ended at 9 calls in flight; Claude ended at 12 and Codex at 7, with none.

The feed test has finished: all 5,140 person-platform sessions, 1,289 model calls (Gemini 442, Codex 440, Claude 407) and 19.9M input / 0.94M output tokens in 62 minutes, with no session lost. Its results, and those of the social rounds, survey and pitch, will be added here when the run finishes.

### The 1,000-person run: what 1,008 simulated buyers said

<img src="docs/images/live.png" alt="Live control room at the end of the 1,000-person run: every person coloured by their answer" width="100%" />

Offer: 7-day free trial without a card, then USD 4.99 a month, shown to young professionals, parents and students in India, the Philippines and Kenya.

| Measure | Result |
|---|---|
| Answered the survey | 1,001 of 1,008 |
| Would start the trial | 1.1% yes, 74.8% maybe, 24.1% no |
| Purchase intent from free-text answers (1–5) | 3.07 ± 1.12 |
| Top objection | "Looks like a scam / trust": 70.3% |
| Most willing audience | Kenya young professionals: 2.8% yes, 8.3% would click |
| Least willing audience | Students: 0% yes (their answers were too similar to trust; flagged in the report) |
| By country, would start | Kenya 2.0%, India 0.9%, the Philippines 0.8% |
| Best survey message | "A month of Fitloop costs less than one gym visit": 1.5% yes vs 0.9% for the others |
| Acceptable price range | USD 1.80–7.99, sweet spot around USD 2.49 |
| Test–retest agreement (30 people, a simulated week later) | 86.7% gave the same verdict |
| Analyst panel | 5 of 5 analysts: iterate |

**What it concluded: iterate** (medium confidence). The signals differ: the survey alone points to no-go (n = 1,001), the feed test to iterate (best creative fb_parents, expected CTR 1.58%), and all five simulated analysts to iterate. The decision written at the end of the run, before the analyst panel was added, was no-go. The idea interests people (three in four said maybe), but trust blocks them. The report also caught a concrete flaw: the ad promises "no card", while the landing page form asks for a card number, expiry and CVV, and simulated people dropped off at that step. The next step it recommends is to remove the card step, add proof from real users in each country, and retest. These are simulated people; treat every rate as a direction until a real experiment confirms it.

Preparation, active simulation turns, surveys, email/feed reactions, pitches, and reports can all use model calls. Repeated seeds multiply work. Local gateways report upstream usage when available and label estimates; subscription use does not imply a measured monetary cost. Measure a small run before choosing a large cohort. First-time embedding setup may download model assets even when inference runs locally.

## Other integrations

| Interface | Entry point |
|---|---|
| **REST API** | Backend at `http://127.0.0.1:5001`; [endpoint guide](docs/API.md) and [OpenAPI schema](docs/openapi.json) |
| **Python SDK** | `pip install -e sdk`, then `from marketmirror import MarketMirror`; [SDK examples](sdk/README.md) |
| **Docker** | Configure `.env`, then `docker compose up --build`; backend on 5001, viewer on 5050, both published on loopback |
| **Webhooks** | Set `MIROFISH_WEBHOOK_URL` to receive completion summaries from CLI pipelines, studies, and tests |

The Docker services mount uploads, scenarios, and run outputs from the host. The host's loopback login gateway is not directly reachable from those containers; use a provider reachable from the container or run the CLI gateway workflow on the host.

## Development

```bash
cd backend
uv sync --python 3.12
uv run --no-sync python -m pytest tests claude_cli/tests -q
```

Tests mock model calls and do not need a live model key. CI also checks generated API documentation. Backend services live in `backend/app/`, the CLI and report renderer in `backend/claude_cli/`, agent tools in `plugin/`, and the Python SDK in `sdk/`.

## Documentation

- [Local installation, providers, and agent setup](docs/LOCAL_AGENTS.md)
- [Persona, creative, and experiment input formats](docs/INPUT_FORMATS.md)
- [Real product URL testing: carts, signup, and browser evidence](docs/WEBSITE_TESTING.md)
- [Agent plugin](plugin/README.md) · [Codex setup](codex/README.md)
- [REST API](docs/API.md) · [OpenAPI schema](docs/openapi.json) · [Python SDK](sdk/README.md)
- [Human-behavior research and proposed improvements](docs/HUMAN_BEHAVIOR_RESEARCH.md)
- [Speed research: what large simulators do and what we borrowed](docs/SPEED_RESEARCH.md)
- [Publishing](docs/PUBLISHING.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md)

## Credits and license

MarketMirror is released under [AGPL-3.0](LICENSE). It builds on [MiroFish](https://github.com/666ghj/MiroFish) and [OASIS](https://github.com/camel-ai/oasis). The dashboard embeds [Apache ECharts](https://echarts.apache.org); third-party notices are in [the vendor directory](backend/claude_cli/vendor/README.md). The [original MiroFish README](docs/MIROFISH-UPSTREAM.md) is preserved.

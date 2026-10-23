# Providers, mixed markets and large runs

The [README](../README.md) explains what MarketMirror does and how a market test works. This guide holds the settings for running it at scale: which gateway or API key plays the people, how several providers share one market, how 3,000 people get written fast without losing depth, what usage limits do, and what API runs cost.

## Gateways, ports and usage limits

The gateway commands in the [technical guide's model table](TECHNICAL_GUIDE.md#choose-your-model) use the default port 5055 and write their settings into `.env`. On another port (for example `--port 5057`) a gateway writes `.env.<backend>` instead, such as `.env.antigravity`; start a backend on that file with `./mm start --port <P> --env-file .env.antigravity`.

Several providers in one market: `LLM_POOL=deepseek,kimi,claude` with each provider's key set (`<name>:<model>` picks a model, for example `deepseek:deepseek-v4-pro`). `LLM_POOL=auto` pools every provider that has a key, and a JSON list of `{"provider": ..., "model": ...}` objects also works. Pool names accept common aliases, such as `zai` or `glm` for `zhipu` and `moonshot` for `kimi`. See [Several providers in one market](#several-providers-in-one-market).

**Usage limits pause the run instead of breaking it.** When a Claude Code, Codex or Antigravity login hits a limit, its gateway reads the reset time, stops sending calls and answers `429` with `Retry-After`. `market-test` and `study` check every gateway in the pool and wait up to 12 hours (the CLI finds the pool's gateways in `MIROFISH_ENV_FILE`, else `.env`, so run it with the backend's settings file). Then they redo only the test step that was hit (feed test, email test, rounds, survey, pitch, panel or report), so a half-answered survey never becomes a result. A provider paused for longer than that is skipped, and its calls are counted as failed. Only gateways of providers listed in `LLM_POOL` are checked, so a provider moved to an API key no longer pauses the run. Preparation does not wait: people a paused provider could not write are left out and counted. `curl 127.0.0.1:5055/health` shows `paused`, `paused_until` and `limit_hits`.

**Pick the gateway's model.** Through the Claude Code gateway most steps make one Claude Code call per simulated person (persona writing and interviews batch 4 people per call), and the model decides how fast your subscription's limit runs out. The gateway uses Sonnet unless you set `LLM_GATEWAY_MODEL` (`haiku`, `sonnet`, `opus`, a full model id, or `default` for Claude Code's own default) or pass `--model` (for example `./mm gateway start claude --model haiku`); an `LLM_MODEL_NAME` set in `.env` is replaced each time a gateway starts on 5055. A 1,000-person run makes several thousand calls (the measured 1,000-person run below: 434 feed-test calls, 1,159 round actions, 1,038 survey interviews). With an API key there is no session limit. Social rounds run up to 50 calls per platform (`OASIS_SEMAPHORE`). Persona writing and interviews default to at most 16 calls in flight, split across providers. Set `MM_LANE_<PROVIDER>` (for example `MM_LANE_DEEPSEEK=50`) to run more.

**Prompt caching with a Claude API key.** With `ANTHROPIC_API_KEY` (provider `claude`), Claude is called through Anthropic's native Messages API (the official `anthropic` SDK) instead of its OpenAI-compatible endpoint, which does not cache. Prompts that many calls share put their shared part first (the brief, context, rules and JSON schema for writing people, interviewing them and showing them a feed) with a cache breakpoint after it, so later calls read it at about a tenth of the input price; each person's own details come after the breakpoint. Cache reads and writes are counted in the usage figures. `MM_CACHE_TTL=1h` keeps entries for an hour instead of five minutes (writes cost 2x instead of 1.25x), `MM_CLAUDE_EFFORT` sets the effort for these calls (default `low`; empty uses the model's own), and `MM_CLAUDE_NATIVE=off` goes back to the OpenAI-compatible endpoint. Measured on 12 full-depth people with `claude-opus-5-5`: 9 calls in 163 s, 5,002 input tokens read from the cache; output was most of that test's cost, so caching pays most on input-heavy stages. The social rounds, survey and pitch run inside the OASIS engine and do not use this yet.

**Choose a provider in the browser.** After `./mm start`, `./mm cli setup` opens a settings page (this computer only). There you pick a Claude Code, Codex or Antigravity login (ports 5055/5056/5057) or any supported API key, store the Jev key, start and stop gateways (stopping one here stops it for every backend that uses it), test the connection and apply the change to the running backend. For Antigravity, choose a Gemini Flash model rather than the default Argon (see below). Keys are stored owner-only in `.env` and shown masked; the page needs the one-time token in its link.

Start a login gateway **before** `./mm provider check` and `./mm start`. Several gateways can run side by side on different ports (`--port`); see [Several providers in one market](#several-providers-in-one-market). If changing providers while the backend is running, restart it with `./mm stop` followed by `./mm start`.

## Several providers in one market

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

### When a provider runs out mid-run

Two settings keep a long run going when one provider's account runs dry. Both go in the backend's settings file (for example `.env.mixed`) and take effect after a backend restart and a `market-test` rerun, which resumes from the run folder.

- **Move a provider to an API key.** Replace its pool entry, for example `claude_code:sonnet` with `claude:claude-sonnet-5-5` and `ANTHROPIC_API_KEY` set. `claude_code` and `claude` are the same family, so every person Claude wrote stays on Claude. Only the gateways of providers still in `LLM_POOL` can pause the run, so the old login's usage limit no longer stops it.
- **Let another provider stand in.** `MM_PROVIDER_STANDIN=antigravity=claude` (comma-separated pairs) sends every person a writer wrote to another provider in the rounds, survey and pitch, after you remove the writer from `LLM_POOL`. Without it those people would be spread over the remaining providers. Results label them `antigravity (played by claude)`, so "Do the models agree?" never presents the stand-in's answers as the writer's own.

The 3,000-person run used both: its Claude login kept hitting the session limit during the social rounds, and its Gemini login ran out of quota for about four days. See the [technical guide](TECHNICAL_GUIDE.md#the-3000-person-mixed-market).

## Writing people fast without losing depth

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

With these models and lane limits, 60 full-depth people (20 per provider) were written and interviewed, and 57 of them followed up, in 6 minutes 7 seconds; see [Measured runs and costs](TECHNICAL_GUIDE.md#measured-runs). The Codex and Antigravity CLIs add about 20,000 tokens of their own instructions to every call (21-23k input tokens per call in the 12-person feed test; Claude Code reported about 2,400) and need a few seconds to start, which an API key avoids.

**Depth for large audiences.** `"depth": "fast"` writes compact cards for everyone in batches of 20 (`MM_CARD_BATCH`) and gives the full life interview to `interview_share` (default 10%) of every audience and provider pair, at least 2 per pair. `"depth": "auto"` uses full depth up to 300 people and fast depth above that (`MM_FAST_ABOVE`). Each person records their depth: `interviewed`, `profile` (the interview failed) or `card`. A persona spec may ask for up to 5,000 people; raise the limit with `MM_MAX_PERSONAS` in the backend's settings.

**Social rounds at scale.** Set `OASIS_MAX_ITERATION=1` (default 3) so each active person makes one model call per turn. Other settings: `OASIS_SEMAPHORE` (model calls in flight per platform, default 50), `OASIS_ACTIVE_AGENT_CAP` (most people acting per round), `OASIS_MEMORY_WINDOW` (messages each person keeps, default 10) and `OASIS_TOKEN_LIMIT` (default 32000). `MODEL_TIMEOUT` is 60 s, or 420 s through a login gateway. `OASIS_ACTION_TIMEOUT` is 120 s, or 480 s through a gateway, and unless you set it, it stays at least 60 s above `MODEL_TIMEOUT`.

**Surveys, pitches and analysts at scale.** Survey and pitch send up to 120 people per interview call (`MM_INTERVIEW_BATCH` for the survey and the CLI pitch; `--batch` on each command; the pitch inside `market-test` and `study` always uses 120; `./mm cli test` defaults to 40). Each survey call waits up to `MM_INTERVIEW_WAIT_S` (720 s; the pitch always waits 720 s). Each interview has its own deadline, `MM_INTERVIEW_DEADLINE_S` (540 s). Set `MM_INTERVIEW_BATCH` and `MM_INTERVIEW_WAIT_S` in the shell that runs `./mm cli`; `MM_INTERVIEW_DEADLINE_S` is a backend setting. An interview that misses it gets no answer instead of an older one. The survey saves `survey_partial.json` after every batch, waits before a batch while any gateway is paused, and logs and skips a batch that fails. At the end it asks everyone without a usable answer once more, and it fails only when nobody answered. The pitch mixes providers in every batch; a failed batch is reported in `pitch.json` (`failed_batches`, `failed_batch_errors`, and `unanswered` per turn) instead of stopping the pitch. Analysts read at most about 80,000 characters of material. Longer material is thinned evenly, and the analysts are told what was cut.

**Stopping a survey early.** Add `"survey": {"settle": {"margin": 5, "min_n": 60, "cells": "provider"}}` to `market_test.json`, or run `survey --settle [--settle-margin 5 --settle-min 60 --settle-cells provider|segment|segment,provider|all]`. People are asked in waves of one batch, shuffled and dealt across cells. A cell stops once it has at least `min_n` answers and every yes/maybe/no share is within ±margin (checked with z = 2.5, because the results are looked at after every wave). The default cell is the provider, so use `segment` to settle per audience. In settle mode nobody is asked a second time. The survey file and the dashboard say how many were asked and why it stopped. Fast depth and settle are off unless you ask for them.

What we borrowed from other large-scale simulators, and what we chose not to, is in [speed research notes](SPEED_RESEARCH.md).

## API keys: cost and speed

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

API keys are entered privately in your terminal. `./mm configure --open-guide` can open the provider's key console; `./mm provider status` shows masked configuration. Agents can configure an existing secret with `--key-env` instead of placing it in tool arguments. See [provider setup and troubleshooting](LOCAL_AGENTS.md).

## Scoring with Jev (optional)

[Jev](https://docs.typesafe.ai/introduction/quickstart) is TypeSafe's decision model. It does not write text: it reads a piece of text and answers typed questions (pick one label, place it on a scale, yes or no) with a probability for every option. MarketMirror can use it in three places:

- **Rating distributions.** Each free-text survey answer is scored against the same five anchor statements the embedding method uses (level 0 = rating 1 ... level 4 = rating 5), and Jev's probabilities become the 1-5 distribution. The embeddings stay the default. `auto` uses Jev and falls back to the embeddings for the answers Jev did not rate, and records which engine rated each one. In `jev` mode an answer Jev fails on gets no rating and is counted as failed.
- **Concern classification.** `gtm voc --classifier jev` labels the real text and the simulated objections with the same Jev question (concern types plus "none").
- **Objection check.** `survey --objection-check` has Jev label each person's main objection with the survey's objection types and reports how often that matches the person's own tag, as a percentage with a 95% range (one line in the dashboard's Objections section).

Jev cannot write or play the simulated people; the chat model you chose above still does that. Its accuracy for these tasks has not been validated in this project, so treat a Jev distribution as a different measurement, not a better one; the dashboard's go / iterate cut-offs were set on the embedding method.

To enable it, set `TYPESAFE_API_KEY` in `.env` (direct to `api.typesafe.ai`), or use OpenRouter with `OPENROUTER_API_KEY` and `JEV_VIA=openrouter`. `JEV_MODEL` overrides the model (`jev-latest` direct, `~typesafe/jev-latest` on OpenRouter), `JEV_BASE_URL` the endpoint, `JEV_PARALLEL` the number of parallel requests (default 4), `JEV_TIMEOUT` the seconds per request (default 60) and `JEV_RETRIES` the retries (default 3). Then choose where to use it: `SSR_ENGINE=jev` (or `auto`) for every survey, `survey --ssr-engine jev`, or `"survey": {"ssr_engine": "jev", "objection_check": true}` in `market_test.json`. `./mm cli jev check` shows whether a key is configured and which route and model would be used without calling the API; `--ping` sends one request. Each result records the requests, failures and tokens used (and the cost when OpenRouter reports it).

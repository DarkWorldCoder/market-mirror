---
name: market-mirror
description: MarketMirror - test marketing and sales decisions on simulated buyers before spending. Builds diverse personas (country, age, upbringing, education, income, thinking style, communities) from any documents, then runs ad and creative tests in realistic Facebook/Instagram/Reddit/TikTok/LinkedIn/X feeds, split tests of messages, buyer surveys (free-text intent mapped to rating distributions, objections, word of mouth), multi-seed ranges, price testing (Van Westendorp), landing-page drop-off, spend/ROI/cost-per-lead projections calibrated to real ad data, past-ad analysis and backtests, an independent analyst panel, and a sales playbook per audience, all in a live dashboard with downloadable reports. Use when the user wants to test ads, messages, offers, prices, launches, positioning or sales pitches on an audience; predict how customers, students, parents, voters or the public will react; analyse past ad performance; estimate cost per lead or ROI; or mentions MarketMirror or MiroFish. Needs a shell and an Anthropic API key.
---

# MarketMirror

MarketMirror simulates buyers. Concrete personas react to your material in realistic social feeds and answer a buyer survey, and you get a marketing and sales dashboard: who converts, what message wins, what stops people, what they would pay, and what spend would return. It runs locally on the user's own Anthropic key (engine: MiroFish, AGPL-3.0).

All commands go through the helper next to this file:

```bash
MM="<this skill's folder>/scripts/mm.sh"     # e.g. ~/.claude/skills/market-mirror/scripts/mm.sh
bash "$MM" help
```

The engine lives in `~/.market-mirror/engine` unless `MARKET_MIRROR_HOME` says otherwise.

## 0. Ground rules

- Simulated people are not real people. Always say so when reporting, show the sample size, and prefer directions ("parents in Manila look strongest") over precise claims. The dashboard shows 95% margins and flags small samples; repeat them.
- Ground everything you can in real data (section 2). Ungrounded runs are brainstorming, not evidence.
- Never print, echo or grep the API key. Ask the user to put it in `<engine>/.env`, or write it there with a file edit if they paste it.
- Spend control: always stop after `prepare` and show the personas first. Say roughly how many Claude calls the next step makes before running rounds, surveys or feed tests.

## 1. Set up (first time, then just `doctor`)

1. `bash "$MM" setup` clones the engine, installs Python 3.12 deps with `uv`, creates `.env`. If `uv` is missing, relay the install options it prints.
2. `bash "$MM" doctor`. If the key is missing, ask the user to set `LLM_API_KEY` in `<engine>/.env` (a new key with a spending limit is best).
3. `bash "$MM" start` starts the backend on port 5001.
4. `bash "$MM" live` (in the background) serves the live dashboard at `http://127.0.0.1:5050/`. In the Claude desktop app open it in the browser pane; elsewhere give the user the link.

**Fastest route for anyone (no files to write):** ask the user the nine quickstart questions in chat (brand; what they sell, for whom, at what price; who buys and where; platforms; what to test: ads, messages, price, launch, pitch; monthly budget; size small/medium/large; past ad export; extra documents), then `bash "$MM" cli quickstart --answers @answers.json` (or the `quickstart` MCP tool). It writes the scenario folder with template ads, messages, launch calendar, pitch and rebuttals, builds the simulated people and stops. Show the people and the `edit_first` list, improve the templates with real material (section 2) or `cli captions`, then run the printed `market-test` command with `"approve_spend": true`.

## 2. Gather real data first (use whatever tools this session has)

| Source | How | Becomes |
|---|---|---|
| Ad accounts (Meta Ads, Google Ads connectors) | pull ads, ad sets, spend, impressions, clicks, landing page views, results, by country/age/placement | a CSV/JSON export, then `cli ads-import` |
| Ads Manager export the user has | `cli ads-import export.csv --out <scenario>/past_ads.md` | seed file + `past_ads.json` benchmarks |
| SEO/market tools (Semrush etc.), web search | competitors, keywords, prices, reviews, audience size | a Markdown seed file |
| CRM, survey results, interviews, support tickets, reviews | export or paste | seed files; quote real objections |
| Landing page | fetch it; time how long it loads on mobile; list form fields | the feed test `landing` block |

Put everything in a scenario folder: `bash "$MM" scenario <name> file1 file2 ...` (gitignored inside the engine).

## 3. Define the audience (persona spec)

Write `<scenario>/personas.json`. Each segment gets real people with ages spread over the range, balanced genders, rotating cities, and balanced upbringing, education, income, thinking style, tech comfort and media diet; each person also gets one deliberate contradiction and realistic local names (never real people).

```json
{"segments": [
  {"label": "Kenya young professionals", "count": 8, "country": "Kenya", "cities": ["Nairobi", "Mombasa"], "age_min": 22, "age_max": 35,
   "role": "young professional or freelancer", "entity_type": "Customer", "languages": ["English", "Swahili"], "platforms": ["Instagram", "TikTok"],
   "notes": "Pilot: highest cost per trial; questions about data use"}],
 "communities": [
  {"name": "Nairobi Runners & Gym Rats", "kind": "whatsapp_group", "segments": ["Kenya young professionals"], "norms": "data-cost conscious; compare by price"}],
 "keep_entities": ["Your brand name"]}
```

Every person is then interviewed (12 life questions, 2 adaptive follow-ups, 3 questions about the product) and distilled into a BDE card (how they decide, what they pay for); add `"probes": false` to skip the second call, `"population": {country: {age/gender shares}}` to weight people to a real population mix. No spec? `--auto-personas 30` lets Claude plan segments and communities from the question. Up to 500 per segment and 2,000 in total are allowed; start with 20-40 and scale once the setup is right. `diversity` (top level or per segment) overrides the trait lists.

## 4. All in one (fastest)

Write `<scenario>/market_test.json` (keys: name, title, brand, seeds, requirement, personas or auto_personas, creatives, seeds_n (repeat the feed test with N seeds; 3 for anything you will report), posts and events (brand posts and a launch calendar inside the rounds), rounds, survey {offer, goal, messages, split, pricing}, pitch {script, rebuttals, channel}, panel {analysts, brief}, report, approve_spend) and run `bash "$MM" cli market-test <scenario>/market_test.json`. The first run stops after creating the people and prints them: show them to the user. Then add the printed `simulation_id` and `"approve_spend": true` and run again. If the MCP tools are available (`market_test`, `job_status`, `results`), use those instead of the shell.

The dashboard opens with a **go / iterate / no-go decision** combining every signal. Report it with its confidence and the "fix first" list.

## 5. Pick a recipe

Run stage one for every recipe, then show the personas (`cli profiles --simulation <id> --brief`) before spending more:

```bash
bash "$MM" cli run --seed <abs paths...> --requirement @<scenario>/requirement.txt \
  --personas <scenario>/personas.json --platform parallel --max-rounds 5 --stop-after prepare --out mirofish_runs/<name>
```

`simulation_id` is in `<engine>/mirofish_runs/<name>/run_manifest.json`.

**A. Ad and creative test (feed test).** Write `<scenario>/creatives.json`:
```json
{"creatives": [{"id": "fb1", "platform": "facebook", "format": "image", "page": "Brand", "text": "...", "headline": "...",
                "cta": "Sign up", "media": "what the image shows", "image": "optional local image path",
                "segments": ["optional targeting"], "real_ad": "optional real ad name for backtests"}],
 "landing": {"load_seconds": 3.5, "language": "English", "shows": "...", "form_fields": ["name", "email", "phone"], "price": "free"},
 "benchmarks": {"facebook": {"cpm": 2.1, "ctr": 1.4, "budget": 500, "currency": "USD",
                             "lead_value": 12, "close_rate": 0.1, "deal_value": 300, "gross_margin": 0.8}}}
```
Then `bash "$MM" cli feedtest --simulation <id> --creatives @<scenario>/creatives.json --exposures 2 --seeds 3`. `--seeds N` repeats the test with N random seeds (N times the cost; the log prints Claude calls and tokens per seed) and reports each creative's mean and min-max range for expected CTR, thumb-stop and engagement, plus how often it ranked first. Use `--seeds 1` only for a quick check, and then report the result as a direction. Several creatives on one platform are split-tested automatically (each person sees one). Output: thumb-stop, CTR (realised and expected), engagement, hides, comments in the persona's voice, landing-page funnel with drop reasons, and spend projections: clicks, CPC, conversions, cost per lead, CAC, ROAS, ROI, break-even CPL, payback. Benchmarks from `ads-import` calibrate CTR to reality.

**B. Message or offer test (buyer survey).** Needs the simulation running: `cli start --simulation <id> --max-rounds 3`, then
`cli survey --simulation <id> --offer "..." --goal "sign up for X" --messages @<scenario>/messages.txt --split`.
`--split` gives each person one message (a real A/B test); without it people pick their favourite.
People answer interest, trust, purchase intent and recommendation in their own words first; the backend maps each answer to a 1-5 distribution by similarity to anchor statements with the local embedding model (semantic similarity rating, arXiv 2510.08338; free, no Claude calls). The dashboard's Ratings section shows the distributions and mean ± spread per audience, and "would convert" is the share who said yes (the SSR purchase mean drives go ≥ 3.75 / iterate ≥ 3.1). Quote intent as "3.4/5 ± 1.1", not the stated 0-10 numbers, which run high. If the log says SSR is unavailable, the stated numbers are used: say so when reporting.

**C. Price test.** Add `--pricing USD` (any currency) to the survey: acceptable range, sweet spot, and "never pay" price by segment. Treat it as low confidence unless calibrated with real price data.

**D. Past-ads analysis.** `cli ads-import <export.csv or .json> --out <scenario>/past_ads.md`. Read the seed it writes (best and worst ad sets, cost per conversion, landing-page loss), use it as a seed file, and pass `past_ads.json` as `--benchmarks` to the feed test.

**E. Backtest (is the simulation any good here?).** Recreate 3+ past ads as creatives with `"real_ad": "<ad name in the export>"`, run the feed test, then `cli backtest --run-dir mirofish_runs/<name> --actuals <scenario>/past_ads.json`. Report the rank correlation, whether the winner matched, and the calibration factor. If it does not match, say the simulation is not predictive for this market yet.

**F. Product or feature launch.** Seed: the launch announcement, pricing page and competitor notes. Write the brand's own captions (`cli captions --brief @brief.md --platform instagram --n 6`, or the user's real ones) as `posts.json` (day 0) and `events.json` (`[{"round": 1, "agent": "<brand name>", "platform": "both", "content": "teaser"}, {"round": 2, ...launch}, {"round": 4, ...offer}]`), run 6+ rounds with `--posts @posts.json --events @events.json` (or the `posts`/`events` keys in `market_test.json`). The dashboard's **Social feed** then shows every post by platform, round, audience and country, and a brand-posts strip with reach, reply sentiment, best and worst reply. Then the survey with the positioning lines as `--messages --split`.

**G. Sales pitch rehearsal.** Seed: the pitch deck or call script and real objections from the CRM. Write `pitch.md` and `rebuttals.md` (`## price`, `## trust`, `## effort`, `## relevance`, `## privacy`, `## any`), then `cli pitch --simulation <id> --script @pitch.md --rebuttals @rebuttals.md --channel call` (or the `pitch` MCP tool; needs a live environment, so run rounds first). Every simulated buyer answers in their own voice, objects, asks a question back; objectors hear the matching rebuttal and say whether it moved them. Report the pitch score, the objections the rebuttals cannot handle ("fix first"), the hot leads with the best time to reach them, and the by-audience table. Lead scores also appear on the People cards and in `leads.csv`.

**I. What to test next (from real data).** If the session has an ads connector (Meta, Google, TikTok), pull the ads with spend, impressions, clicks, conversions, country and age, and call the `ideas` MCP tool with those rows (or `cli ideas --rows @rows.json`), plus `--run-dir` of the last run and `--brand`. Without a connector use the user's export: `cli ideas --ads export.csv --run-dir mirofish_runs/<name>`. Each idea cites its evidence and carries the MarketMirror config to simulate it first; present them as a prioritised list and offer to run the top one.

**K. Email campaigns.** Write `<scenario>/emails.json` (`{"emails": [{"id": "a", "from_name": "Brand", "subject": "...", "preheader": "...", "body": "...", "cta": "...", "send_time": "morning|midday|evening|night", "sequence": [{"delay_days": 2, "subject": "...", "body": "..."}]}], "list_size": 10000, "benchmarks": {"cost_per_send": 0.002, "lead_value": 12}}`) and run the `email_test` MCP tool or `cli emailtest --simulation <id> --emails @<scenario>/emails.json --list-size 10000`. Report open, click and unsubscribe rates per subject line and audience, the sequence funnel, the projection to leads, and every spam-word warning.

**L. Anything else, one spec.** The `run_test` MCP tool (or `cli test --simulation <id> --spec @test.json`) takes `{"type": ..., "variants": [...], "audience": {...}}` for ad, message, price, offer, positioning, naming, landing, launch, pitch, email, creator_post and channel_mix tests and returns one result shape: each variant's metric with a 95% margin, the winner, the lift, and whether it is clear or a tie. Use it when the user asks "can we test X" and X is not one of the recipes above.

**J. Is the panel trustworthy here?** Two checks, both cheap. `cli survey ... --retest 20` reports how many of twenty people give the same verdict a simulated week later (quote it as the reliability figure). When the user has 50-300 real answers (a real survey, Ads Manager results, email stats) export them as a CSV with segment, country, gender, age and y (yes/maybe/no or 0-1) and run the `calibrate` MCP tool (or `cli calibrate --run-dir ... --real answers.csv`): it returns trust / correct / walk-away per audience, the overlap between the real customers and the simulated panel, and a corrected rate with its standard error. Report the verdict before any number from that run, and use the corrected rate when the verdict is "correct".

**H. Second opinion.** `cli panel --simulation <id> --analysts 5 --brief "what we need to decide"`: independent analysts (performance marketer, brand strategist, sales lead, psychologist, sceptical data analyst, ...) each read the anonymized posts, comments, feed reactions and survey answers alone. Report the consensus and where they disagree.

## 6. Show the results

- Live: the browser pane at `http://127.0.0.1:5050/` updates as steps finish.
- Final: `<engine>/mirofish_runs/<name>/dashboard.html` (one offline file). Publish it as an Artifact if available, otherwise send the file. The **Report** section (right under the decision) is written in plain language for non-technical readers and its header holds every download: this page, print/PDF, report (Markdown), action plan (JSON), survey answers and feed sessions (CSV), lead scores (CSV), pitch and social feed (JSON), test ideas, all numbers (JSON); the same files sit next to it (`market_report.md`, `leads.csv`, `pitch.json`, `ideas.md`...). The `results` MCP tool returns the report path, the action plan, pitch and ideas summaries.
- In chat: lead with the decision (which audience, which message, what to fix first, expected cost per lead), then the evidence and its limits. Give ranges, not points: the feed-test range across seeds and the survey mean ± spread. If seeds disagree on the winning creative, call it a tie. Quote real comments from personas, labelled as simulated.

## 7. Costs and cleanup

Feed tests call Claude only for exposures that catch someone's eye (most do not), plus one call per click for the landing page; `--seeds N` multiplies that by N. Rounds cost one call per active agent per round; surveys one per person; the panel one per analyst. `claude-haiku-4-5` is the cheap default; use a Sonnet model for final reports. `bash "$MM" stop` stops everything.

## Troubleshooting

`bash "$MM" doctor` first. Backend log: `<engine>/backend/logs/server.out`. A failed `run` still exports what it has. More detail: `<engine>/CLAUDE.md`.

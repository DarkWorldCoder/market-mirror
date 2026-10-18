---
name: market-mirror
description: MarketMirror - test marketing and sales decisions on simulated buyers before spending. Builds diverse personas (country, age, upbringing, education, income, thinking style, communities) from any documents, then runs ad and creative tests in realistic Facebook/Instagram/Reddit/TikTok/LinkedIn/X feeds, split tests of messages, buyer surveys (intent, objections, NPS), price testing (Van Westendorp), landing-page drop-off, spend/ROI/cost-per-lead projections calibrated to real ad data, past-ad analysis and backtests, an independent analyst panel, and a sales playbook per audience, all in a live dashboard with downloadable reports. Use when the user wants to test ads, messages, offers, prices, launches, positioning or sales pitches on an audience; predict how customers, students, parents, voters or the public will react; analyse past ad performance; estimate cost per lead or ROI; or mentions MarketMirror or MiroFish. Needs a shell and an Anthropic API key.
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

- Simulated people are not real people. Always say so when reporting, show the sample size, and prefer directions ("Bangladesh students look strongest") over precise claims. The dashboard shows 95% margins and flags small samples; repeat them.
- Ground everything you can in real data (section 2). Ungrounded runs are brainstorming, not evidence.
- Never print, echo or grep the API key. Ask the user to put it in `<engine>/.env`, or write it there with a file edit if they paste it.
- Spend control: always stop after `prepare` and show the personas first. Say roughly how many Claude calls the next step makes before running rounds, surveys or feed tests.

## 1. Set up (first time, then just `doctor`)

1. `bash "$MM" setup` clones the engine, installs Python 3.12 deps with `uv`, creates `.env`. If `uv` is missing, relay the install options it prints.
2. `bash "$MM" doctor`. If the key is missing, ask the user to set `LLM_API_KEY` in `<engine>/.env` (a new key with a spending limit is best).
3. `bash "$MM" start` starts the backend on port 5001.
4. `bash "$MM" live` (in the background) serves the live dashboard at `http://127.0.0.1:5050/`. In the Claude desktop app open it in the browser pane; elsewhere give the user the link.

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
  {"label": "Nepal parents", "count": 8, "country": "Nepal", "cities": ["Kathmandu", "Pokhara"], "age_min": 40, "age_max": 55,
   "role": "parent paying for study abroad", "entity_type": "Parent", "languages": ["Nepali"], "platforms": ["Facebook", "Viber"],
   "notes": "Real ads: 603 clicks, 0 sign-ups"}],
 "communities": [
  {"name": "Nepali Abhibhawak Samuha", "kind": "viber_group", "segments": ["Nepal parents"], "norms": "forward warnings; trust people they know"}],
 "keep_entities": ["Your brand name"]}
```

No spec? `--auto-personas 30` lets Claude plan segments and communities from the question. Up to 500 per segment and 2,000 in total are allowed; start with 20-40 and scale once the setup is right. `diversity` (top level or per segment) overrides the trait lists.

## 4. Pick a recipe

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
Then `bash "$MM" cli feedtest --simulation <id> --creatives @<scenario>/creatives.json --exposures 2`. Several creatives on one platform are split-tested automatically (each person sees one). Output: thumb-stop, CTR (realised and expected), engagement, hides, comments in the persona's voice, landing-page funnel with drop reasons, and spend projections: clicks, CPC, conversions, cost per lead, CAC, ROAS, ROI, break-even CPL, payback. Benchmarks from `ads-import` calibrate CTR to reality.

**B. Message or offer test (buyer survey).** Needs the simulation running: `cli start --simulation <id> --max-rounds 3`, then
`cli survey --simulation <id> --offer "..." --goal "sign up for X" --messages @<scenario>/messages.txt --split`.
`--split` gives each person one message (a real A/B test); without it people pick their favourite.

**C. Price test.** Add `--pricing USD` (any currency) to the survey: acceptable range, sweet spot, and "never pay" price by segment. Treat it as low confidence unless calibrated with real price data.

**D. Past-ads analysis.** `cli ads-import <export.csv or .json> --out <scenario>/past_ads.md`. Read the seed it writes (best and worst ad sets, cost per conversion, landing-page loss), use it as a seed file, and pass `past_ads.json` as `--benchmarks` to the feed test.

**E. Backtest (is the simulation any good here?).** Recreate 3+ past ads as creatives with `"real_ad": "<ad name in the export>"`, run the feed test, then `cli backtest --run-dir mirofish_runs/<name> --actuals <scenario>/past_ads.json`. Report the rank correlation, whether the winner matched, and the calibration factor. If it does not match, say the simulation is not predictive for this market yet.

**F. Product or feature launch.** Seed: the launch announcement, pricing page and competitor notes. Requirement: who reacts how, what they misunderstand, which feature matters, what would make them switch. Run rounds (C as well if pricing matters), then the survey with the positioning lines as `--messages --split`.

**G. Sales objections and pitch.** Seed: the pitch deck or call script and real objections from the CRM. Run the survey with candidate pitches as messages, then `cli interview --simulation <id> --agent <id> --prompt "<your pitch>. What would you say back?"` for the strongest objectors. The playbook section turns this into "lead with / pre-empt / answer with / seed it in" per audience.

**H. Second opinion.** `cli panel --simulation <id> --analysts 5 --brief "what we need to decide"`: independent analysts (performance marketer, brand strategist, sales lead, psychologist, sceptical data analyst, ...) each read the anonymized posts, comments, feed reactions and survey answers alone. Report the consensus and where they disagree.

## 5. Show the results

- Live: the browser pane at `http://127.0.0.1:5050/` updates as steps finish.
- Final: `<engine>/mirofish_runs/<name>/dashboard.html` (one offline file). Publish it as an Artifact if available, otherwise send the file. Its Downloads section exports the report (Markdown), every survey answer and feed session (CSV), metrics (JSON) and print-to-PDF; the same files sit next to it.
- In chat: lead with the decision (which audience, which message, what to fix first, expected cost per lead), then the evidence and its limits. Quote real comments from personas, labelled as simulated.

## 6. Costs and cleanup

Feed tests call Claude only for exposures that catch someone's eye (most do not), plus one call per click for the landing page. Rounds cost one call per active agent per round; surveys one per person; the panel one per analyst. `claude-haiku-4-5` is the cheap default; use a Sonnet model for final reports. `bash "$MM" stop` stops everything.

## Troubleshooting

`bash "$MM" doctor` first. Backend log: `<engine>/backend/logs/server.out`. A failed `run` still exports what it has. More detail: `<engine>/CLAUDE.md`.

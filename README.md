<div align="center">

# MarketMirror

**Test ads, messages, prices and launches on simulated buyers before you spend.**

Diverse AI personas scroll realistic Facebook, Instagram, Reddit, TikTok, LinkedIn and X feeds, react to your ads, answer a buyer survey and argue in their own communities. You get a marketing and sales dashboard: who converts, which message wins, what stops people, what they would pay, and what your budget would return.

Runs on Claude · works as a Claude Code skill · one offline HTML dashboard · built on the [MiroFish](https://github.com/666ghj/MiroFish) swarm-simulation engine

<img src="docs/images/dashboard-results.png" alt="MarketMirror dashboard: verdicts, conversion, click and trust numbers" width="92%"/>

</div>

## What you can do with it

| Question | MarketMirror answer | How |
|---|---|---|
| Which ad or creative should get the budget? | Thumb-stop rate, CTR, engagement, hides and comments per creative, split-tested per platform | **Feed test** in platform-styled feeds |
| Which message or offer converts, for whom? | Would-convert by segment, country, community, age and gender; winning message per audience | **Buyer survey** with true split tests |
| What should we charge? | Acceptable price range, sweet spot and "never pay" price by segment | **Van Westendorp** price questions |
| Where do we lose people after the click? | Page load on each person's network vs their patience, form drop-off with reasons | **Landing-page step** |
| What will this cost per lead, and does it pay back? | Impressions, clicks, CPC, conversions, cost per lead, CAC, ROAS, ROI, break-even CPL, payback | **Projections** calibrated to your real CPM and CTR |
| What did our past ads actually do? | Best and worst ad sets, cost per conversion, landing-page loss, benchmarks | **`ads-import`** for Meta / Google Ads exports |
| Can we trust the simulation for this market? | Rank correlation and winner match against real ad results | **`backtest`** |
| What do the objections sound like, and how do we answer them? | Objections by audience in the buyers' own words, "what would change my mind", a sales playbook per audience | **Survey + playbook + interviews** |
| Does a second opinion agree? | Independent analysts (performance, brand, sales, psychology, data, local market) each read the anonymized evidence alone | **Analyst panel** |
| So, launch it or not? | **Go / iterate / no-go**, with confidence, the signal behind each vote and what to fix first | **Decision card** combining every test |

## See it

<table>
<tr>
<td width="50%"><img src="docs/images/feed-test.png" alt="Feed test: a TikTok ad mock with simulated reactions and comments, plus metrics"/><br><b>Feed test.</b> Each ad looks the way it does on the platform, with the reactions and comments simulated people left. Press <i>Replay the scroll</i> to watch them scroll past, stop, react or click, one by one.</td>
<td width="50%"><img src="docs/images/playbook.png" alt="Sales and marketing playbook cards per audience"/><br><b>Playbook.</b> For each audience: priority, what to lead with, the objection to pre-empt, how to answer it, the community to seed it in, and a proof line.</td>
</tr>
<tr>
<td><img src="docs/images/audiences.png" alt="Would-convert chart by segment with margins of error"/><br><b>Audiences.</b> Would convert, maybe and no by segment, country, community, age and gender, with 95% margins and small-sample flags.</td>
<td><img src="docs/images/analysts.png" alt="Independent analyst panel with themes and evidence"/><br><b>Analyst panel.</b> Five analysts each work alone on the anonymized evidence. Every theme is backed by quotes from the simulated people.</td>
</tr>
<tr>
<td><img src="docs/images/pricing.png" alt="Price sensitivity curves with acceptable range"/><br><b>Pricing.</b> Van Westendorp curves: the acceptable range, the sweet spot and the "never pay" price by segment.</td>
<td><img src="docs/images/objections.png" alt="Objections chart and quotes"/><br><b>Objections.</b> What stops people, how often, in their own words, and what would change their mind.</td>
</tr>
</table>

**Demo run.** These screenshots come from a real run on **Fitloop**, a made-up home-workout app with a 7-day card-required trial at $4.99 a month. It was tested on 28 simulated young professionals, parents and students in India, the Philippines and Kenya, across Facebook, Instagram, TikTok and Reddit ads. The brand, the audiences and the pilot numbers in its brief are all invented.
- **Decision:** iterate, low confidence. The survey and the analysts said iterate; the best Instagram ad said go.
- **Survey:** nobody committed and 61% said maybe. Trust was the biggest blocker, mostly about entering card details for a "free" trial.
- **Analysts:** all five said iterate, with an average success chance of 25%. Their themes: free YouTube workouts set the bar, old phones and prepaid data plans worry people, and the adaptive-coaching claim needs proof.
- **Price:** the acceptable range was $3 to $15, with a sweet spot around $5.

These numbers come from simulated people. Two runs in a row produced no firm "yes", so treat absolute rates as pessimistic until a backtest calibrates them, and use the run to rank options and find objections.

## How it works

```mermaid
flowchart LR
    A["Your material<br/>briefs, ads, landing page,<br/>past ad exports, CRM notes"] --> B["Knowledge graph<br/>who and what matters"]
    A --> C["Persona planner<br/>segments, ages, upbringing,<br/>education, income, thinking style,<br/>communities"]
    B --> C
    C --> D["Feed test<br/>FB / IG / Reddit / TikTok /<br/>LinkedIn / X feeds"]
    C --> E["Social simulation<br/>posts, comments, follows<br/>inside communities"]
    D --> F["Landing page<br/>load time vs patience,<br/>form drop-off"]
    E --> G["Buyer survey<br/>intent, objections, split test,<br/>price"]
    D & F & G --> H["Analyst panel<br/>independent reviewers"]
    D & F & G & H --> I["Dashboard + reports<br/>funnel, ROI, playbook,<br/>CSV / MD / JSON / PDF"]
```

1. **Personas.** You describe audience segments (country, age range, role, count, languages, platforms, what you know about them). Every segment gets concrete people: ages spread across the range, balanced genders, rotating cities, and balanced upbringing (city, small town, village, migrant family), education, income, thinking style (analytical, sceptical, price-hunter, early adopter, traditional, busy...), tech comfort and media diet. Each person has one deliberate contradiction so nobody reads like a stereotype, and a realistic local name that is invented, never a real person. Or let Claude plan the segments from your question.
2. **Communities.** People join the groups where they actually talk (a parents' WhatsApp group, a subreddit, a Facebook group) and pick up each group's norms. Members follow each other before the simulation starts, so feeds are mostly in-group, with a small cross-group bridge.
3. **Feed test.** Each person scrolls a feed of local organic posts with one test ad, the way each platform shows ads. See [How realistic is it?](#how-realistic-is-it) for what keeps this honest.
4. **Social simulation (optional).** Personas post, comment and follow on simulated Twitter and Reddit for a few rounds (the MiroFish / OASIS engine), so word of mouth and group dynamics play out.
5. **Buyer survey.** Everyone answers the same questionnaire: interest, trust, purchase intent and whether they would recommend it, first in their own words and then as quick numbers; would click, the message that works (or a single assigned message in a split test), main objection, what would change their mind, a quote, and optional price questions. The free-text answers become rating distributions (see [How realistic is it?](#how-realistic-is-it)).
6. **Analyst panel.** Several analysts with different lenses each read the anonymized evidence alone, then the panel reports where they agree.
7. **Dashboard.** One self-contained HTML file (Apache ECharts inlined, works offline), live while the run happens, with downloads for every report.

## Quick start

### As a Claude skill (recommended)

In Claude Code:

```
/plugin marketplace add DarkWorldCoder/market-mirror
/plugin install market-mirror@market-mirror
```

Then just ask, for example: *"Test these three Facebook ads on parents in Jakarta and Surabaya; here is our landing page and last month's Ads Manager export."* The skill downloads the engine, sets it up, asks for your Anthropic key, plans personas, stops to show them to you before spending, runs the tests and opens the live dashboard. It also pulls real data from tools you have connected (Meta Ads, Google Ads, Semrush, web search, your CRM exports).

You can also copy `plugin/skills/market-mirror/` into `~/.claude/skills/`. The skill needs a shell, `git` and [`uv`](https://docs.astral.sh/uv/).

### As agent tools (MCP)

The plugin also starts an MCP server, so Claude Desktop, Claude Code or any MCP client gets these tools: `doctor`, `setup`, `start_backend`, `market_test` (everything in one call), `job_status`, `results`, `list_runs`, `start_live`, `ads_import`, `backtest` and `cli`. To add it by hand:

```bash
claude mcp add market-mirror -- python3 /path/to/market-mirror/plugin/skills/market-mirror/scripts/mcp_server.py
```

### One command for everything

```json
{
  "name": "acme_launch", "title": "Acme Pro launch test",
  "seeds": ["brief.md", "past_ads.md", "landing_page.md"],
  "requirement": "question.txt",
  "personas": "personas.json",
  "creatives": "creatives.json",
  "seeds_n": 3,
  "rounds": 3,
  "survey": {"offer": "Acme Pro trial", "goal": "start a free trial", "messages": "messages.txt", "split": true, "pricing": "USD"},
  "panel": {"analysts": 5, "brief": "Which audience and message get the budget, and should we launch?"},
  "approve_spend": false
}
```

```bash
mm market-test scenarios/acme/market_test.json   # 1st run: builds the people, then stops so you can check them
# add "simulation_id" from the output and "approve_spend": true, run again: feed test, rounds, survey, panel, dashboard
```

### By hand

```bash
git clone https://github.com/DarkWorldCoder/market-mirror && cd market-mirror
cp .env.example .env                 # set LLM_API_KEY=<your Anthropic key>
cd backend && uv sync --python 3.12 && cd ..
bash backend/claude_cli/start_server.sh
alias mm="backend/.venv/bin/python backend/claude_cli/mirofish.py"

# 1. personas (stop before paid rounds and look at them)
mm run --seed scenarios/acme/brief.md scenarios/acme/past_ads.md \
       --requirement @scenarios/acme/question.txt --personas scenarios/acme/personas.json \
       --stop-after prepare --out mirofish_runs/acme
mm profiles --simulation <sim_id> --brief

# 2. ads in real-looking feeds, with landing page, projections and ROI
mm feedtest --simulation <sim_id> --creatives @scenarios/acme/creatives.json --exposures 2 --seeds 3

# 3. a few rounds of social simulation, then the buyer survey (split test + price)
mm start  --simulation <sim_id> --max-rounds 3
mm survey --simulation <sim_id> --offer "Acme Pro trial" --goal "start a free trial" \
          --messages @scenarios/acme/messages.txt --split --pricing USD

# 4. second opinion, then watch everything live
mm panel --simulation <sim_id> --analysts 5 --brief "Which audience and message get the budget?"
mm live                              # http://127.0.0.1:5050/
```

Keep your own inputs in `scenarios/<name>/`. That folder is gitignored, and so is `mirofish_runs/`.

## Recipes

| Recipe | You provide | Run |
|---|---|---|
| **Ad / creative test** | ads (text, headline, CTA, image or description, platform, targeting) | `feedtest --creatives @creatives.json --seeds 3` |
| **Message / offer split test** | 2+ messages, the conversion goal | `survey --messages @messages.txt --split` |
| **Price test** | offer description, currency | `survey --pricing USD` |
| **Landing page check** | load time, language, form fields, price | `landing` block in `creatives.json` |
| **Spend, CPL and ROI** | CPM and budget (or an ads export); optional lead value, close rate, deal value, margin | `benchmarks` block, or `--benchmarks @past_ads.json` |
| **Past-ads analysis** | Meta Ads Manager / Google Ads CSV or JSON export | `ads-import export.csv --out scenarios/x/past_ads.md` |
| **Backtest** | 3+ past ads recreated as creatives with `"real_ad"` names | `backtest --run-dir ... --actuals past_ads.json` |
| **Product or feature launch** | announcement, pricing page, competitor notes | `run` + `survey --messages` with positioning lines |
| **Sales objections and pitch** | pitch or call script, real CRM objections | `survey`, then `interview --agent <id> --prompt "<pitch>"` |
| **Second opinion** | anything above | `panel --analysts 5` |

<details>
<summary><b>Input formats</b> (personas.json, creatives.json)</summary>

**personas.json**

```json
{
  "segments": [
    {"label": "Philippines parents", "count": 8, "country": "Philippines", "cities": ["Manila", "Cebu City"],
     "age_min": 35, "age_max": 50, "role": "parent who wants to get fit at home", "entity_type": "Parent",
     "languages": ["Tagalog", "English"], "platforms": ["Facebook"],
     "notes": "Pilot: cheapest cost per trial; many drop at the card step", "gender_mix": "balanced",
     "diversity": {"income": ["lower-middle", "middle", "upper-middle"]}}
  ],
  "communities": [
    {"name": "Fit Pinoy Community", "kind": "facebook_group", "segments": ["Philippines parents"],
     "norms": "encouraging, Taglish posts, before/after photos", "join_share": 0.9, "account": true}
  ],
  "keep_entities": ["Your brand"], "graph_agents": "auto", "in_group_follows": 6, "bridge_rate": 0.05
}
```

Up to 500 people per segment and 2,000 in total. `--auto-personas N` plans segments and communities for you.

**creatives.json**

```json
{
  "creatives": [
    {"id": "fb1", "platform": "facebook", "format": "image", "page": "Acme", "link": "https://acme.com",
     "text": "Primary text...", "headline": "Headline", "cta": "Sign up",
     "media": "what the image or video shows", "image": "optional/local/image.png",
     "segments": ["optional targeting"], "countries": ["optional"], "real_ad": "optional name in your ads export"}
  ],
  "landing": {"load_seconds": 3.5, "language": "English", "shows": "what the page shows",
              "form_fields": ["full name", "email", "phone number"], "price": "free", "steps": 1},
  "benchmarks": {"facebook": {"cpm": 2.1, "ctr": 1.4, "budget": 500, "currency": "USD",
                              "lead_value": 12, "close_rate": 0.1, "deal_value": 300, "gross_margin": 0.8, "monthly_value": 25}}
}
```

Platforms: `facebook`, `instagram`, `reddit`, `tiktok`, `linkedin`, `x`. Several creatives on one platform are split-tested automatically.

In the `market-test` config, `seeds` lists your documents and `seeds_n` is how many times to repeat the feed test with different random seeds (same as `feedtest --seeds N`).
</details>

## The dashboard

Sections, in order: **Decision** (go / iterate / no-go), **Results** (plain-language verdicts and headline numbers), **Ratings** (free-text answers as 1-5 distributions, mean ± spread per audience), **Playbook**, **Feed test** (range across seeds, post mocks with scroll replay, metrics, landing funnel, projections and ROI), **Funnel**, **Audiences**, **Objections**, **Messages** (split-test ranking and an audience × message heatmap), **Pricing** (Van Westendorp curves), **Voices** (quotes from would-buy and would-not-buy people), **Analysts**, **Backtest**, **Downloads**, then the analyst report, what people posted, the people themselves, activity over time, the knowledge graph (documents, people, segments, communities and countries, all connected) and run details.

**Downloads:** the dashboard (HTML), print or save as PDF, the analyst report (Markdown), every survey answer and every feed session (CSV), results by audience and creative metrics with ROI (CSV), and all key numbers (JSON). The same files are written next to `dashboard.html`.

## How realistic is it?

LLM personas are known to be too positive, too uniform and too eager to engage. MarketMirror builds in the fixes published research supports:

- **Attention is decided in code, not by the model.** Whether an ad catches someone's eye at all comes from a per-platform prior and that person's ad avoidance. Most exposures are a quick scroll past and never reach the model ([attention research](https://www.amplified.co/insight/blog-attention-science-paid-social-strategy); [simulated users over-engage](https://arxiv.org/html/2508.21740v2)).
- **Leaving is the default.** Scrolling past is listed first, and each person's habits are stated as facts ("you comment about once a month"; "you rarely click ads"), drawn from skewed distributions ([non-buyers are over-simulated](https://arxiv.org/abs/2606.20708)).
- **Probabilities as well as single choices.** For each ad, people also state how likely they are to click, react, comment, share or hide. Expected rates are reported next to the realised counts.
- **Ratings from free text, not from numbers.** Asked for a 0-10 score or a yes/no, simulated people bunch up in the middle-positive range. In the buyer survey each person first answers interest, trust, purchase intent and recommendation in their own words, in English or in their language's own script (romanized Hinglish or Taglish flips negations in the embedding model), opening with a verdict ("No" … "Yes, definitely") and one reason. The verdict clause of each answer (cut at its first colon or dash) is embedded with the local multilingual model and compared with anchor statements for every point of a 1-5 scale ("I definitely would not do this" … "I would definitely do it", three anchor sets per scale); the similarities become a probability distribution over the five points. This is semantic similarity rating, which reproduced real purchase-intent distributions far better than direct ratings across 57 personal-care product surveys ([Maier et al. 2025](https://arxiv.org/abs/2510.08338)). The dashboard shows the distributions and mean ± spread per audience. The decision card and playbook judge the purchase mean (go ≥ 3.75, iterate ≥ 3.1); "would convert" is always the share who said yes, because the top-2 share of a distribution counts a 50-50 answer as half a yes. The stated numbers are kept and used only when the embedding model is unavailable (`survey --no-ssr` turns the mapping off). It costs no extra Claude calls.
- **Spread, not a single run.** One run is one draw: who sees which ad, feed order, whose attention is caught and each person's habits all come from a random seed. `feedtest --seeds 3` (or `"seeds_n": 3` in `market-test`) repeats the test with different seeds and reports each creative's mean and min-max range for expected CTR, thumb-stop and engagement, and how often each creative ranked first. The decision card only says go (or no-go) when every seed agrees. Each seed's Claude calls and tokens are logged.
- **Diversity by construction.** Upbringing, education, income, thinking style, tech comfort and media diet are spread evenly across each segment, with one contradiction per person ([twins are less varied than humans](https://arxiv.org/html/2509.19088v4)).
- **Social proof is damped.** Everyone sees reaction counts, but only about a third open the comments ([LLM agents over-follow the crowd](https://arxiv.org/html/2411.11581v3)).
- **Frequency and wear-out.** People can see an ad several times, are told so, and notice it less each time.
- **The click is not the conversion.** Page load on the person's likely network, their patience, the page language and the form fields all decide whether a click becomes a lead.
- **Calibration and validation.** Projections can be calibrated to your real platform CTR and CPM, `backtest` scores the simulation against your real ads, every rate shows a 95% margin, and small samples are flagged.

Report a single-seed result as a direction only; with `--seeds 3` or more, quote the range.

**Limits.** Simulated people are not real people. Persona panels can still misjudge real click-through rates ([study](https://arxiv.org/abs/2609.25010)), and price answers from models are unreliable without real price data ([MSI](https://www.msi.org/working-paper/using-llms-for-market-research-2/)). Use MarketMirror to rank options, find objections and plan tests, then confirm with a small real budget. When a backtest disagrees with reality, trust reality.

## Costs

Everything runs on your own Anthropic key. Defaults use `claude-haiku-4-5`.

- **Personas:** about one call per 8 people.
- **Feed test:** one call per exposure that catches someone's eye (typically 15-35%), plus one per click for the landing page. `--seeds N` multiplies this by N; the log shows calls and tokens per seed.
- **Rounds:** one call per active agent per round.
- **Survey:** one call per person. Mapping the free-text answers to ratings runs on the local embedding model and is free.
- **Panel:** one call per analyst.

Always stop after `prepare` and look at the people before spending on the rest.

## Under the hood

| Part | Where |
|---|---|
| Persona planner, communities, follow graph | `backend/app/services/persona_planner.py` |
| Feed test, landing page, projections and ROI | `backend/app/services/feed_test.py` |
| Analyst panel | `backend/app/services/analyst_panel.py` |
| API | `backend/app/api/market.py` (+ upstream `simulation.py`) |
| CLI | `backend/claude_cli/mirofish.py`, `market_cli.py` |
| Survey analysis, playbook, pricing | `backend/claude_cli/marketing.py` |
| Free-text ratings (SSR) | `backend/app/services/ssr.py` |
| Dashboard | `backend/claude_cli/exporter.py`, `feed_view.py`, `vendor/echarts.min.js` |
| All-in-one command | `mirofish.py market-test` |
| MCP server (agent tools) | `plugin/skills/market-mirror/scripts/mcp_server.py` |
| Claude skill | `plugin/skills/market-mirror/` |

Claude runs through Anthropic's OpenAI-compatible endpoint. Memory is a free local knowledge graph (SQLite with BM25 and local multilingual embeddings), so no Zep account is needed. `CLAUDE.md` is the full operating guide for agents, and `HANDOFF.md` lists known gaps. Run the tests with `cd backend && uv run --no-sync python -m pytest tests claude_cli/tests -q`.

## Credits and license

MarketMirror is built on [MiroFish](https://github.com/666ghj/MiroFish) (swarm-intelligence engine, AGPL-3.0) and [OASIS](https://github.com/camel-ai/oasis) (social simulation). The original MiroFish README is kept at [docs/MIROFISH-UPSTREAM.md](docs/MIROFISH-UPSTREAM.md). The dashboard embeds [Apache ECharts](https://echarts.apache.org) 5.5.1 (Apache-2.0, see `backend/claude_cli/vendor/`). MarketMirror is released under AGPL-3.0.

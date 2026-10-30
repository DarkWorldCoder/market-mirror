# What would make MarketMirror much more powerful: feature research, October 2026

Reviewed 30 October 2026. This document compares MarketMirror with commercial synthetic-research and ad pre-testing tools, open-source social simulators and the survey-simulation literature, then ranks the features worth building. It complements [HUMAN_BEHAVIOR_RESEARCH.md](../HUMAN_BEHAVIOR_RESEARCH.md), which covers the behavior model, and does not repeat it.

Read the numbers with care:

- Almost every accuracy figure a vendor publishes is self-reported, and none of them has been independently audited.
- Papers from 2026 are mostly preprints. Their effect sizes describe their own tasks, models and populations.
- Star counts were read from the GitHub API on 30 October 2026.
- Nothing here has been validated in MarketMirror against real buyers.

## 1. What MarketMirror already has (so it is not proposed again)

The full inventory came from a read of the code (`backend/app/services`, `backend/app/api/market.py`, `backend/claude_cli`, the MCP server and the skills). These already exist:

- **Personas.** Interview-grounded personas with BDE cards, communities and raking weights; a stereotype guard and a diversity report; stable identity seeds; a persistent behavior state with episodic memory across tests.
- **Tests.** Feed test (six platforms; seeds, wear-out, a competitor ad, a landing step and a generic-reader baseline); survey (SSR, verbalized chances, a collapsed-segment check, `--split`, Van Westendorp, `--retest`, sequential settling); sales pitch with rebuttals; email test; real-browser website test; analyst panel; buying committee; creative evolution; battlecards; customer journey; tier choice; a paired-offer what-if with attribute effects; persona-tailored ads; landing teardown; two-wave word of mouth; search/GEO.
- **Real data.** Ad, email, CRM and survey imports; backtest and holdout backtest against a training-mean baseline; `calibrate` (overlap, conditional calibration, AIPW with cross-fitting); a calibration store with ratio-based prediction intervals; 30/90-day forecasts; ad-pattern labelling of real ad libraries; `research` voices.
- **Delivery.** Dashboard, live view, study (scenarios × seeds), MCP server (28 tools, `tools` capability only), plugin skills, SDK, Codex and Gemini packages, a local login gateway, mixed-provider markets and a GitHub Pages demo.

Confirmed gaps, which the shortlist below draws on:

- **Creatives are text only.** Images and video are described in words (`feed_test.py:172`, `render_item` at `feed_test.py:573`; `docs/ad-patterns.md:109` lists vision as "not in this version"). The native Claude client also drops non-text message parts (`utils/anthropic_native.py:_to_native`).
- **Pricing and choice methods are incomplete.** `conjoint` raises "not available yet" (`claude_cli/experiments.py:343`), and there is no MaxDiff or Gabor-Granger.
- **No PPI, conformal intervals or effective sample size.** Intervals in `predict.py` are ratio spreads.
- **No population-level distribution estimator.** There is no option-order or paraphrase perturbation, and no shrinkage of simulated lifts.
- **No intake from raw customer material.** Structured real records already become grounded personas (`PersonaSpec.real_profiles`, `persona_planner.py:1572`, with a Grounded badge in the dashboard), but nothing turns transcripts, reviews or CRM exports into those records, and the input was undocumented. Research voices are only prompt grounding (`persona_planner.py:658`).
- **Personas can't be talked to after a run.** Interviews need a live OASIS environment, and there is no moderated focus group.
- **No public accuracy record.** There is no human-accuracy benchmark anywhere in the repo (`benchmarks/` holds speed and website fixtures only).
- **The MCP server is tools-only.** It has no UI resources, tasks, elicitation, prompts or resources, and no recipes for the ad, analytics or CRM MCP servers marketers already connect.
- **No branching from a mid-run snapshot.** There is also no archetype or hybrid crowd scaling (`docs/SPEED_RESEARCH.md` lists archetypes as not built).

## 2. Landscape

### Commercial synthetic research

| Tool | What it sells that MarketMirror lacks | Evidence (self-reported unless noted) |
|---|---|---|
| [Simile](https://www.simile.com/) (Joon Park; $100M A, then $200M B) | Confidence tag on every result; bring-your-own-data models; drift detection | ~7,000 weekly evaluations against humans; fine-tuning on 2.9M responses improved unseen studies by 26% |
| [Aaru](https://aaru.com) ($1B headline A, [TechCrunch](https://techcrunch.com/2025/12/05/ai-synthetic-research-startup-aaru-raised-a-series-a-at-a-1b-headline-valuation)) | Scenario injection at population scale | 2,993-question benchmark, mean TVD 7.62% |
| [Electric Twin](https://www.electrictwin.com) | Audiences built from the client's own surveys and interviews; per-client holdout | 96% (1-MAE) vs 94% human test-retest |
| [Ask Rally](https://askrally.com) | Image and video analysis by personas; clone personas from transcripts; API; a Claude Code plugin | No accuracy number published |
| [Artificial Societies](https://societies.ai/) | Interactive focus groups; conjoint; opinion-spread networks; crisis cascades | 86% distribution accuracy across 1,000 panels |
| [Ipsos PersonaBot](https://www.ipsos.com/en-in/ipsos-announces-launch-ipsos-personabot-groundbreaking-ai-powered-solution-enhance-segmentation), [Native AI](https://www.getapp.com/all-software/a/native-ai/), [Delve AI](https://www.delve.ai/pricing) | Persistent chat with segment personas or customer twins (Delve: HubSpot app) | n/a |
| [Qualtrics Edge Audiences](https://siliconangle.com/2026/03/18/qualtrics-adds-ai-powered-synthetic-data-research-tools-speed-customer-insights/), [Toluna HarmonAIze](https://tolunacorporate.com/lp/harmonaize/) | Panels from models trained on real panel data; blended human and synthetic samples | "12x more accurate than general LLMs" (Qualtrics) |
| [Brox.ai](https://venturebeat.com/data/market-research-is-too-slow-for-the-ai-era-so-brox-built-60-000-identical-digital-twins-of-real-people-you-can-survey-instantly-repeatedly) | 60,000 twins of real, recontactable people ($100k–1.5M a year) | None published |
| [Yabble Vision](https://bestmediainfo.com/mediainfo/mediainfo-digital/yabble-rolls-out-ai-image-based-testing-for-rapid-concept-feedback-10533361) | Image concept tests (colour, mood, style, message) | Unverified |

### Ad pre-testing and creative analytics

| Tool | Feature | Evidence |
|---|---|---|
| [Kantar LINK AI](https://www.kantar.com/inspiration/agile-market-research/can-ai-really-decode-creative-effectiveness) | Up to 20k features per video (frames, OCR, audio); 15 predicted metrics; a norm base of ~250k tests | >80% hit rate on top-30% ads (vendor) |
| [System1 Test Your Ad](https://ppc.land/system1-adds-ai-layer-to-test-your-ad-as-creative-measurement-race-heats-up/) | Star (brand) / Spike (sales) / Fluency (brand linkage); second-by-second emotion | Human panel; the AI layer is unvalidated |
| [Neurons](https://knowledge.neuronsinc.com/how-neurons-ai-works), [Dragonfly AI](https://dragonflyai.co/faqs) | Attention heatmaps; Figma and Chrome plugins | >95% / 89% vs eye tracking (vendor; Dragonfly on MIT300/CAT2000) |
| [DAIVID](https://www.exchangewire.com/blog/2024/10/29/daivid-launches-ai-powered-solution-that-predicts-attention-emotions-memory-brand-impact-of-ads/) | 39 emotions second by second; attention; memory | 3,000-video analysis (vendor) |
| [VidMob](https://help.vidmob.com/en/articles/12676204-vidmob-api-overview-unlock-your-creative-data), [CreativeX](https://www.creativex.com/reports/data-from-1m-ads-1b-media-spend-1-trillion-impressions) | Pre-flight rule checks (logo early, captions, safe zones, aspect ratio) | CreativeX: +10% quality score associated with −2% CPM (correlational) |
| [Motion](https://motionapp.com/faq), Marpipe | In-flight hook and thumb-stop rates; multivariate modular creative | n/a |

### Open-source simulators

| Project | Stars | Relevant idea |
|---|---|---|
| [MiroFish](https://github.com/666ghj/MiroFish) | 82,732 | The upstream engine. Its hosted demo and "predict anything" pitch drove growth. Critics note it publishes no backtests |
| [MiroShark](https://github.com/MiroShark/MiroShark) | 1,487 | Closest derivative: counterfactual branch at round N, director mode, Nemotron-Personas grounding, a public "verified predictions" ledger |
| [OASIS](https://github.com/camel-ai/oasis) | 5,363 | 1M agents; TwHIN-BERT and hot-score recommenders. Validated on 198 Twitter15/16 cascades: scale and breadth track, depth diverges ([arXiv 2411.11581](https://arxiv.org/abs/2411.11581)) |
| [TinyTroupe](https://github.com/microsoft/TinyTroupe) | 7,627 | Empirical validator (t-test and KS against real survey data); in-place A/B runner; ad and focus-group notebooks |
| [AgentTorch](https://github.com/AgentTorch/AgentTorch) | 657 | LLM archetypes: 8.4M agents at ~300 LLM queries per step ([AAMAS 2025](https://aamas.csc.liv.ac.uk/Proceedings/aamas2025/pdfs/p500.pdf)) |
| [HiSim](https://github.com/xymou/HiSim) | 62 | LLM core users plus rule-based periphery; beats pure ABM on real events ([arXiv 2402.16333](https://arxiv.org/abs/2402.16333)) |
| [Expected Parrot EDSL](https://github.com/expectedparrot/edsl) | 510 | Survey DSL across many models, with human validation |
| [genagents](https://github.com/joonspk-research/genagents) | 623 | Code for the 1,000-person interview agents |
| GOD, WorldSeed | 1,253 / 822 | Zero-install browser replay and live intervention: replayable demos without a key |

### MCP and marketer integrations (2026)

- **Official ad and analytics servers.** Meta Ads MCP: read and write, open to any app since 21 July 2026, with Ad Library search, industry benchmarks, paused ad creation and A/B and lift tests ([ppc.land](https://ppc.land/meta-opens-ads-mcp-to-any-app-cutting-integration-code-to-zero/)). Google Ads MCP (read-only, 1,098★). GA4 MCP (read-only, 3,592★). TikTok Agentic Hub (read and write).
- **CRM, email and creative servers.** Hosted servers for HubSpot, Klaviyo, Salesforce, Shopify, Semrush, Ahrefs, Notion and Slack; Apify (13,840★) covers Ad Library, Reddit and TikTok scraping.
- **The 2026-07-28 MCP spec** makes **Tasks** an official extension, which fits 10–60-minute runs. **MCP Apps** (January 2026) renders server UI inside Claude, ChatGPT and VS Code, and elicitation suits spend approval ([RC post](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)).
- **Marketers star skill packs.** [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) reached 57k★ in nine months, and anthropics/skills has 185k★. No open-source repo yet owns "marketing simulation"; the synthetic focus-group repos sit under 60★.

### What the literature says improves accuracy

| Finding | Source | Implication |
|---|---|---|
| Interviews with *real* people beat demographic-only agents by 14–15 normalized points (0.85 of test-retest on GSS) | Park et al. 2024, [arXiv 2411.10109](https://arxiv.org/abs/2411.10109) | MarketMirror's interviews are synthetic. Real customer material is the biggest grounding lever |
| Twins sit under-dispersed on 154/164 outcomes; correlation with humans ~0.2 but positive on 157/164; a concise summary matches the full profile; temperature 0 is best per person | Peng, Gui, Toubia et al. 2025, [arXiv 2509.19088](https://arxiv.org/abs/2509.19088) | Lead with direction and rank; report and correct dispersion |
| One call that *describes* a distribution: TV 0.22. Sampling personas one by one: TV 0.46. Randomizing option order, phrasing and field order per call cuts TV by 21% at no extra cost; temperature captures <20% of that gain (replicated on Claude Sonnet 4.5) | Jang, Kim, Lee 2026, [arXiv 2607.25292](https://arxiv.org/abs/2607.25292) (preprint) | Add a segment-level distribution estimator and prompt perturbation |
| Strong option-position bias; answers drift to uniform once order is randomized | Dominguez-Olmedo et al., NeurIPS 2024, [arXiv 2306.07951](https://arxiv.org/abs/2306.07951) | Randomize option order; test against a uniform null |
| Means match, variance too small, coefficients often wrong; drift over time | Bisbee et al. 2024, [Political Analysis](https://doi.org/10.1017/pan.2024.5) | Pin model versions; never use simulated spread for power analysis |
| Simulated treatment effects correlate r = 0.85 with 476 real effects but are too large | Hewitt et al. 2024, [Stanford](https://ai4pb.stanford.edu/projects/predicting-results-of-social-science-experiments-using-large-language-models) | Shrink simulated lifts toward zero |
| LLM WTP is often off and sometimes wrong-signed; changing only the price makes the model infer other changes | Brand, Israeli, Ngwe ([SSRN 4395751](https://papers.ssrn.com/abstract=4395751)); Gui & Toubia ([arXiv 2312.15524](https://arxiv.org/abs/2312.15524)) | State the attributes held fixed in every price arm; treat WTP as direction |
| Valid confidence intervals from a few human labels plus many predictions; λ falls back to human-only when predictions are poor | PPI, Angelopoulos et al., Science 2023 ([arXiv 2301.09633](https://arxiv.org/abs/2301.09633)); PPI++ ([arXiv 2311.01453](https://arxiv.org/abs/2311.01453)) | Upgrade `calibrate` from point AIPW to PPI++ intervals |
| Effective sample size and a power analysis to choose how many humans to recruit | Broska, Howes, van Loon 2025, *Sociological Methods & Research* 54(3) | "This run is worth ≈N real respondents; collect M more for ±x" |
| Coverage-calibrated simulation size; "an LLM is worth ≤ ~60 respondents" on opinion data | Huang, Wu, Wang, ICML 2025, [arXiv 2502.17773](https://arxiv.org/abs/2502.17773) | Honest margins from the calibration store |
| A 12-model ensemble matched 925 human forecasters; models agree with each other more than with humans | Schoenegger et al. 2024, [arXiv 2402.19379](https://arxiv.org/abs/2402.19379) | Cross-model pooling cuts model noise, not shared bias |
| A generic-reader model beat a ten-persona panel on Upworthy headline winners (49.2% vs 34.6%) | Maiorano 2026, [arXiv 2609.25010](https://arxiv.org/html/2609.25010v1) (preprint) | A public benchmark must include the generic-reader comparator, and MarketMirror may lose on it |

## 3. Ranked shortlist

Scores run 1–5:

- **Impact:** value to a marketer or founder.
- **Stars:** demo appeal and shareability.
- **Evidence:** strength of support that the feature works or is wanted.
- **Effort:** higher means harder.

**Rank score = (Impact + Stars) / 2 × Evidence / Effort.** Ties are broken by how many competitors already sell the feature.

| # | Feature | Impact | Stars | Evidence | Effort | Score |
|---|---|---|---|---|---|---|
| 1 | Customer intake into grounded twins (the persona side exists) | 5 | 4 | 4 | 2 | 9.0 |
| 2 | Buyers see the real ad: image and video creatives | 5 | 5 | 3 | 2 | 7.5 |
| 3 | Valid intervals from a small real sample (PPI++, effective sample size, sample planner) | 4 | 2 | 5 | 2 | 7.5 |
| 4 | MarketMirror-Bench: a public accuracy record on open human data | 5 | 5 | 4 | 3 | 6.7 |
| 5 | Distribution-accurate survey (describe estimator, perturbation, dispersion, shrinkage) | 4 | 2 | 4 | 2 | 6.0 |
| 6 | Talk to the buyers after the run: persona chat and moderated focus group | 4 | 5 | 2 | 2 | 4.5 |
| 7 | MCP upgrade: dashboard as MCP App, Tasks, spend elicitation, connector recipes | 4 | 4 | 3 | 3 | 4.0 |
| 8 | MaxDiff, choice-based conjoint and Gabor-Granger | 3 | 2 | 3 | 2 | 3.75 |
| 9 | Archetype or hybrid scaling to 10k–100k weighted buyers | 3 | 3 | 3 | 4 | 2.25 |
| 10 | Counterfactual branch from round N | 4 | 4 | 2 | 4 | 2.0 |

### 1. Customer intake into grounded twins

- **Who has it:** Electric Twin, Ask Rally ("clone from transcripts"), Simile (bring your own data), Native AI, Delve AI (HubSpot), Brox (real recontactable twins).
- **Why it matters:** a founder's best evidence is their own calls, reviews, support tickets, NPS verbatims and CRM notes. This is also the largest accuracy lever in the literature: Park et al.'s gain comes from real interviews, and MarketMirror's interviews are currently synthetic.
- **Evidence:** strong. The 1,000-person study gives +14–15 normalized points. Deng et al. 2026 found real interviews beat demographic profiles on held-out marketing responses. Twin mega-study caveat: richer data improves correlation, but levels stay off.
- **Fit:** the grounded-persona side already exists (`real_profiles`). Missing is the intake:
  - A new `intake` step reads transcripts, review exports, NPS CSVs or CRM notes and scrubs PII locally (emails, phone numbers, names → initials) before any model call.
  - It clusters people into *source records* and writes `personas.json` entries whose interview answers are **quoted from the source** with `provenance: "real"`; unknown fields stay unknown.
  - The planner fills the remaining slots synthetically, labelled `provenance: "synthetic"`.
  - The dashboard's people cards show the provenance badge. `calibrate` can then compare real-grounded and synthetic personas on the same outcomes.
  - This implements "First: grounding" in HUMAN_BEHAVIOR_RESEARCH.md.

### 2. Buyers see the real ad: image and video creatives

- **Who has it:** Kantar LINK AI, Yabble Vision, Ask Rally, DAIVID, Neurons; TinyTroupe 0.7 added vision.
- **Why it matters:** the visual decides the scroll on Instagram, TikTok and Facebook. Today a persona reacts to "(image: a woman running at sunrise)", which tests the copywriter's description rather than the creative. This is the most visible gap a marketer would notice.
- **Evidence:** the vendors' predictions rest on visual features. Pre-flight checks correlate with lower CPM (CreativeX, correlational). Whether vision improves simulated *ranking* accuracy is unknown, so measure it with feature 4.
- **Fit:**
  - `normalize_creatives` accepts `image` (path or URL) and `video` (path; keyframes via ffmpeg when present).
  - A one-time **describe pass** per creative (one vision call, cached by file hash) writes `media`, on-image text, brand visibility and a pre-flight checklist (text density, logo in the first seconds, captions, aspect ratio and safe zones per platform). Text-only providers and gateways still work.
  - With `vision: "direct"`, each persona's scroll prompt also carries the image as an OpenAI `image_url` part. `anthropic_native._to_native` translates that part into a native image block. The image sits in the cached shared prefix, so the crowd pays for it about once.
  - A brand-recall question ("which brand was the ad about?") in the follow-up survey uses behavior-state memories, giving a simple brand-linkage score in the spirit of System1 Fluency.
  - Ad patterns get a vision labelling option (`docs/ad-patterns.md:109`).

### 3. Valid intervals from a small real sample

- **Who has it:** standard in the PPI and DSL literature; no commercial tool exposes it openly. Simile's confidence tags are the commercial analogue.
- **Why it matters:** it answers "how much should I trust this?" with a number: "this simulated panel is worth about 40 real respondents for this question; recruit 60 more to get ±5 points". It also turns the existing `calibrate` into something a researcher can cite.
- **Evidence:** strong and peer-reviewed. The papers are PPI (Science 2023), PPI++, DSL (NeurIPS 2023) and Broska et al. 2025. Krsteski et al. 2026 found that, for a fixed human budget, rectification beats fine-tuning.
- **Fit:**
  - Pure arithmetic in `services/calibration.py`, stdlib only: `ppi_mean()` with power-tuned λ, stratified by segment, plus `effective_n()` and `plan_humans(target_halfwidth)`.
  - Exposed as new fields in `calibration.json`, a dashboard line and an MCP `calibrate` output. AIPW stays as is.

### 4. MarketMirror-Bench: a public accuracy record on open human data

- **Who has it:** vendors publish one-line claims (Aaru, Electric Twin, Artificial Societies). MiroShark has a "verified" ledger, and OASIS validates cascades. MiroFish is criticised for publishing no backtests.
- **Why it matters:**
  - Trust is the main barrier to buying synthetic research.
  - An open tool can publish *reproducible* numbers, including the misses, which no vendor does.
  - It is also the strongest star driver available: a quantified headline, a leaderboard page and a paper-style write-up.
- **Evidence:** it uses two public human datasets:
  - The [Upworthy Research Archive](https://upworthy.natematias.com/): 32k headline A/B tests with real click results, the task Maiorano 2026 used.
  - [Twin-2K-500](https://arxiv.org/abs/2505.17479): 2,058 people × 500 questions, with persona data.
- **Fit:**
  - `benchmarks/bench/`: loaders, a fixed sampled split checked into the repo (hashes only for licensed data), and runners that score the feed test against the generic-reader and training-mean baselines.
  - Metrics: top-choice accuracy, rank correlation, Brier, ranked probability score, the KS distance and SD ratio of distributions, and the test-retest-normalized score.
  - The results page goes to `docs/bench/` on GitHub Pages. Runs cost money, so code and fixtures ship first, and the first paid run waits for the owner's go-ahead and budget.

### 5. Distribution-accurate survey

- **Who has it:** research methods rather than products. Qualtrics, Simile and Electric Twin instead train on real panels, which this repo cannot do with Claude.
- **Why it matters:** better shares and spreads per segment, honest margins, and fewer "everyone says maybe" results.
- **Evidence:**
  - Describe vs sample: TV 0.22 vs 0.46, and perturbation cuts TV by 21% (preprint).
  - Under-dispersion on 154 of 164 outcomes.
  - Position bias (NeurIPS 2024).
  - Inflated effects (Hewitt).
- **Fit:**
  - **(a)** A segment-level *describe* estimator: one direct call per segment × question returns a JSON distribution over the five SSR levels. It is blended with the pooled SSR distribution, and disagreement between the two is reported as a margin. It runs through the backend client, outside OASIS.
  - **(b)** Option-order, paraphrase and persona-field perturbation in `survey_prompt` and the retest.
  - **(c)** SD ratio and a uniform-null check in the survey section.
  - **(d)** Lift shrinkage, learned from backtest pairs in the calibration store with a 0.5–0.6 prior, applied to split-test and price deltas, and a ranking-first verdict.
  - **(e)** A "held fixed" attribute sheet in every price arm (Gui & Toubia).

### 6. Talk to the buyers after the run

- **Who has it:** Ipsos PersonaBot, Native AI, Delve AI, Electric Twin, Ask Rally, Artificial Societies, and TinyTroupe focus-group notebooks.
- **Why it matters:**
  - Founders and sales teams want to "ask the buyer" after the run, and MarketMirror's interviews die with the OASIS environment.
  - A moderated group discussion is also the most shareable demo there is.
- **Evidence:** weak on accuracy, since this is qualitative exploration, and LLM groups converge (Ashery et al.). The design therefore records each person's **private answer before the discussion** and reports how far the group moved them.
- **Fit:**
  - `services/focus_group.py` rebuilds each persona from `persona_index`, its BDE card and behavior-state memories, so it needs no live environment.
  - `chat(person, message, history)` handles one-to-one chat. `run_group(people, guide, rounds)` runs a moderator plus 4–8 people, takes turns, anonymises output and writes `focus_group.json` and a transcript section in the dashboard.
  - Surfaces: CLI `ask` / `focus-group` and the MCP tool `ask_buyers`.

### 7. MCP upgrade

- **Who has it:** MCP Apps (ext-apps 3k★, mcp-ui 5.2k★), the Tasks extension in the 2026-07-28 spec, and AgentSociety 2's MCP support.
- **Why it matters:** the dashboard renders inside Claude, ChatGPT and VS Code. Long runs survive disconnects. Persona sign-off and spend approval happen through elicitation instead of free text.
- **Connector recipes:** skills that pull real results from the ad, analytics and CRM servers marketers already connect (Meta Ads insights and Ad Library, Google Ads and GA4 read-only, HubSpot, Klaviyo) into `actuals_import`, `ad_patterns` and `calibrate`. They push winners back only as paused drafts after approval. The platform APIs are not re-implemented.
- **Evidence:** spec adoption and registry listings; marketers star skill packs.
- **Fit:** in `mcp_server.py`, advertise `resources` (run files), `prompts` (recipes) and UI resources (the existing self-contained dashboard HTML), and wrap the existing job mechanism as tasks. Elicitation is gated on client capability, with a fallback to today's behavior.

### 8. MaxDiff, choice-based conjoint and Gabor-Granger

- **Who has it:** standard research methods; Artificial Societies lists conjoint.
- **Why it matters:** ranking 10–20 claims or features, and pricing beyond Van Westendorp.
- **Evidence:** LLM conjoint gives realistic *direction* but unreliable WTP levels, which must be stated in the output.
- **Fit:** `services/choice_methods.py`:
  - balanced MaxDiff designs and best-worst counting scores, with bootstrap intervals;
  - CBC designs and a stdlib multinomial-logit fit;
  - a Gabor-Granger demand curve.
  - It fills `conjoint` in `test --spec` and adds `maxdiff` and `gabor_granger` types.

### 9. Archetype or hybrid scaling (later)

- AgentTorch archetypes and HiSim's hybrid design are both evidenced at scale.
- Fit: reuse the BDE cards and raking weights as archetypes, and let a rule-based crowd inherit their decisions. Results must be labelled modelled.
- It touches the OASIS runners, so it should wait for prompt caching (`f58d14d`) to merge.

### 10. Counterfactual branch from round N (later)

- MiroShark and GOD make this their headline feature. The marketing question is "what if a competitor cuts price in round 3?".
- It needs OASIS database and agent-memory snapshots and runner changes on top of `f58d14d`.
- `study` and `context` already cover most of the question without the fork.

### Considered and not shortlisted

| Idea | Why it was left out |
|---|---|
| Attention heatmaps and saliency | Needs a vision model outside the LLM stack; licences unclear; Neurons and Dragonfly already do it well |
| Second-by-second video emotion | High effort; the keyframe reactions from feature 1 cover the first step |
| Normative benchmark database | Needs many runs; the calibration store and the bench (feature 4) are its seed |
| Fine-tuned response model | Claude cannot be fine-tuned through the public API; few-shot real answers belong under feature 2 |
| Cross-model linear pool | Partly present as mixed-provider markets plus `provider_agreement`. The evidence says it removes model noise but not shared bias. A small follow-up to feature 5 |
| Recommender variants as a test axis | `OASIS_RECSYS` exists for Twitter only; a small follow-up exposing it in `study` overrides |
| Live ad-account connectors in code | Covered by feature 7's recipes over official MCP servers instead |

## 4. Validity rules for everything above

- Simulated numbers stay directions with margins: seed ranges, SSR spread, PPI intervals only when real answers exist.
- Real-grounded and synthetic material are labelled separately everywhere.
- Every new accuracy feature is judged on held-out real data, including the generic-reader comparator. It counts as an improvement only if it wins there.
- Model, version, prompt hash and dataset hash are recorded in `run_manifest.json`.
- Backtests count only on data after the model's training cutoff.

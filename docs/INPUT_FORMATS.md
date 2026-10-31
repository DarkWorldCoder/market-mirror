# Simulation input formats

Use these files with the CLI or a `market_test.json` configuration. Run commands from the repository root.

All brands, audiences, pilot notes, and benchmark values below are illustrative. Replace them with your own sourced inputs; sample numbers are not recommended market benchmarks.

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

Up to 500 people per segment and 2,000 in total. `run --auto-personas N` plans segments and communities for you. Optional keys: `"probes": false` skips the second interview call (adaptive follow-ups, product questions, BDE card); `"population": {"India": {"age": {"18-24": 0.32, "25-34": 0.28, ...}, "gender": {"female": 0.49, "male": 0.51}}}` rakes each person's `weight` to the census-like shares you give, so weighted rates reflect the supplied marginal shares; this does not establish joint representativeness or predictive accuracy (bring the shares from your census or ad-platform reach data; none are shipped).

**Grounded personas from your own customers (`real_profiles`)**

Add real customers next to the planned segments. Each record becomes one persona marked *Grounded* in the dashboard; the planner never invents what a record leaves out.

```json
{
  "segments": [{"label": "Teams", "count": 20, "country": "United States"}],
  "real_profiles": [
    {"name": "Customer 1", "segment": "Pro", "country": "India",
     "excerpts": ["The app kept charging me after I cancelled", "I only pay for tools my manager approves."],
     "past_purchases": ["Pro plan"],
     "bde": {"decision_procedure": {"who_they_ask": "my manager", "stoppers": ["charges after cancelling"]}}}
  ]
}
```

You rarely write these by hand. `intake` builds them from the material you already have: call or interview transcripts (`.txt`, `.md`, `.vtt`, `.srt`, one person per file), review exports, NPS or survey verbatims and CRM notes (`.csv`, `.tsv`, `.json`, `.jsonl`):

```bash
python backend/claude_cli/mirofish.py intake --files reviews.csv calls/*.txt --segment-field plan \
       --base scenarios/x/personas.json --out scenarios/x/personas.json          # model-written records (backend)
python backend/claude_cli/mirofish.py intake --files reviews.csv --engine supplied --out scenarios/x/personas.json   # offline
```

- **Contact details are removed first, on your machine:** emails, phone and card-like numbers, links, @handles, and the names found in name or author columns (replaced by initials). Names that appear only inside free text are not detected, so read `intake.md` before sharing anything.
- **Quotes are verbatim.** A quote the model returns that is not in that person's own material is dropped.
- **Nothing is invented.** Age, country, city and gender are kept only when a column or the text states them. Decision-card fields stay empty unless the person said so.
- **The output** is the persona spec (`real_profiles` added, or replacing earlier intake records with `--replace`), plus `intake.json` and `intake.md` next to it. In `market_test.json`, use `"intake": {"files": ["reviews.csv"], "segment_field": "plan"}`.

Grounded people are a small, self-selected sample: the customers who wrote a review or took a call. Synthetic people fill the rest of the audience. Use `calibrate` to check coverage before treating results as representative.

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

**Pictures.** `image` (a local path up to 4 MB, or an https URL) or `video` (a local file: keyframes at 0 s, 1 s, 3 s and the middle are taken with ffmpeg) let the simulated buyers react to the real creative.

- **`"vision": "describe"`** (the default). One vision call per creative writes what it shows, the words on it, brand and CTA visibility and a pre-flight checklist into `media`; the brief's own `media` is kept as `media_brief`. Every provider, including the local login gateway, then works from that.
- **`"vision": "direct"`.** Every scroll call also carries the picture. It sits in the cached shared part of the prompt, so a crowd pays for it about once on Claude's API.
- **`"off"`** keeps the run text-only.

The dashboard card shows "What the buyers saw". `creative-check --creatives @creatives.json` runs the same check without a simulation.

In the `market-test` config, `seeds` lists your documents and `seeds_n` is how many times to repeat the feed test with different random seeds (same as `feedtest --seeds N`).

## One experiment

Save this as `experiment.json`, then run `./mm cli test --simulation "$SIMULATION_ID" --spec @experiment.json`. Replace `$SIMULATION_ID` with a prepared simulation's ID.

```json
{
  "type": "offer",
  "name": "Trial signup message",
  "variants": [
    {"id": "control", "text": "Start a 7-day trial for $4.99 a month."},
    {"id": "treatment", "text": "Start a 7-day trial. No card required. Then $4.99 a month."}
  ],
  "audience": {"segments": ["Philippines parents"]},
  "metric": "convert_yes",
  "exposure_context": "Trial offer on the landing page",
  "next_real_world_test": "Randomize eligible visitors between the two offers and measure completed signups."
}
```

The example is invented. Use only offers your product actually supports. Search/organic/referral tests measure simulated concept responses, nurture/retention tests use the inbox engine, and sales outreach/follow-up tests use pitch rehearsal. Those outcomes are not observed search, retention, referral or sales performance.

## A scenario study

Save this as `scenarios/acme/study.json`, beside the `market_test.json` created by quickstart. Set `simulation_id` to the prepared audience's actual ID and ensure the base configuration includes a survey. The base path is relative to the study file; its referenced inputs resolve from the base configuration's directory.

```json
{
  "name": "acme_trial_offer",
  "base": "market_test.json",
  "simulation_id": "sim_replace_me",
  "scenarios": [
    {"name": "control", "overrides": {
      "survey": {"offer": "7-day trial, card required, then $4.99 a month"}
    }},
    {"name": "no_card", "overrides": {
      "survey": {"offer": "7-day trial, no card required, then $4.99 a month"}
    }}
  ],
  "seeds": [1, 2, 3],
  "steps": ["survey"]
}
```

```bash
./mm cli study --spec scenarios/acme/study.json
```

This schedules six survey cells on the same prepared audience and uses model calls. Review the inherited survey messages so they do not contradict either offer. Rerunning the same unchanged study specification reuses completed work. Seed variation describes the simulation, not uncertainty about real conversion. Inspect `study_summary.json`, `study_report.md`, and `study.html` in the returned output folder.

For an all-in-one configuration, run `./mm cli quickstart --no-run --out scenarios/acme` and edit its generated `market_test.json`. Use `./mm cli study --help` for study options.

[Back to README](../README.md) · [Local-agent setup](LOCAL_AGENTS.md) · [REST API](API.md)

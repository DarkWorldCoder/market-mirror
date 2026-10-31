# Ad patterns

Label a library of real ads (your own, or competitors' from the Meta Ad Library) on seven creative dimensions, then
see which patterns stay in market longest, which earn the best real results when the rows carry metrics, and where
your simulated creatives sit on the same map.

```bash
# no key, no backend: 77 fictional, pre-labelled ads
python backend/claude_cli/mirofish.py ad-patterns --ads docs/examples/ad_patterns_sample.json --engine supplied --out /tmp/ap/ad_patterns.json

# your library, labelled by the chat model (or Jev when configured), next to a run's feed test
python backend/claude_cli/mirofish.py ad-patterns --ads library.json --run-dir mirofish_runs/x
```

## Where the idea comes from

[ad-pattern-lab](https://github.com/artemnovitckii/ad-pattern-lab) by Artem Novitckii (MIT) is a local Node app.
It collects ads (pasted copy, uploads, JSON or an Apify Meta Ad Library scrape), prepares images and video frames with
FFmpeg, and asks TypeSafe Jev seven typed questions per ad. It then ranks labels by the share of dated active ads
that started at least 60 days before collection. MarketMirror reuses these ideas: the seven dimensions, keeping
dates and metrics out of the labelling request, exact copy fingerprints for ad families, the 60-day longevity proxy,
the minimum group size and the "this is not performance" framing. No code was copied. This is a Python
re-implementation.

## How it fits with what already exists

| Existing | What it does | Overlap |
|---|---|---|
| `ads-import`, `backtest` | own ad-account metrics -> seed + benchmarks; simulated vs real CTR per creative | `ad-patterns` also reads metric columns, but groups them by creative label instead of by ad name |
| `ideas` | next tests from own metrics + a run | `ad-patterns` findings carry a next-test line and a `feedtest` stub; not yet fed into `ideas` |
| `feedtest` | simulated people react to your creatives (a competitor ad can share the feed) | `ad-patterns` labels those creatives and shows them beside the real patterns |
| `research` | what real people say (reviews, threads) | different evidence: what advertisers keep running |
| `services/jev.py` | Jev client | reused as the optional `jev` engine |

What is new: a taxonomy of the creative itself across many advertisers, and a market-level longevity signal. MarketMirror
had nothing that reads a library of ads by hook, offer or format.

## Pieces

| Piece | Where |
|---|---|
| service (stdlib only, so the CLI can load it without the backend) | `backend/app/services/ad_patterns.py` |
| API | `POST /api/simulation/ad-patterns` in `backend/app/api/market.py` (synchronous) |
| CLI | `mirofish.py ad-patterns` -> `market_cli.ad_patterns` |
| MCP tool | `ad_patterns` (background job); `results` adds an `ad_patterns` summary |
| dashboard | `report_view.ad_patterns_section`, section id `adpatterns`, between Sales rehearsal and Test ideas; `ad_patterns.md` download |
| sample | `docs/examples/ad_patterns_sample.json` (fictional) |

### Input rows

Any list of objects. The column names that are recognised:

- Meta Ad Library and scraper JSON: `ad_archive_id`, `page_name`, `is_active`, `start_date`, and `snapshot.body`, `title`, `cards[0]`, `cta_text`. Dynamic `{{...}}` templates fall back to the card.
- Ad-account exports: `Ad name`, `Primary text`, `Headline`, `Impressions`, `Link clicks`, `Results`, `Amount spent`.
- A sheet: `text`, `headline`, `cta`, `visual_notes`, `transcript`, `brand`, `start_date`, `collected_at`, `active`, `url`.
- Optional `labels: {format, hook, ...}`, already decided. With `--engine supplied` nothing calls a model.

Rows without words are dropped. Duplicate ids get a suffix. At most 300 rows by default (`--max-ads`, hard cap 500).
Images are not read in this version: describe an image or video in `visual_notes`.

### Engines

- `llm`: the configured chat model, 10 ads per call. The prompt says the ads are untrusted material, not instructions.
- `jev`: one Jev request per ad with seven `choice` questions, which also return confidence.
- `supplied`: the labels already in the rows.
- `auto` (the default): Jev when a key is configured, otherwise `llm`. When every row already has labels, it uses `supplied`.

The labelling request sees only the copy, headline, CTA button, visual notes and transcript. It never sees dates,
status or metrics. A label outside the taxonomy becomes `unknown`. An ad the model leaves out, or a failed call,
is marked `failed` and gets no invented label.

### Output (`ad_patterns.json`)

```json
{"kind": "ad_patterns", "version": 1, "engine": "llm", "brand": "...",
 "counts": {"ads": 120, "labelled": 118, "simulated_creatives": 3, "failed": 2, "unlabelled": 0},
 "longevity": {"kind": "real_longevity", "min_age_days": 60, "dated_active": 96, "aged": 21, "baseline_share": 0.2188,
               "min_group": 5, "by_dimension": {"hook": [{"value": "mistake", "ads": 9, "families": 8, "advertisers": 4,
               "dated_active": 7, "aged": 4, "share": 0.5714, "ratio_to_baseline": 2.61, "median_age_days": 88, "enough": true}]}},
 "results": {"kind": "real_results", "min_impressions": 1000, "by_dimension": {"hook": [{"value": "...", "ctr": 1.9, "cvr": 4.1, "cpa": 12.5, "enough": true}]}},
 "simulated": {"kind": "simulated", "by_dimension": {"hook": [{"value": "mistake", "creatives": ["warmup"], "expected_ctr": 1.8}]}},
 "findings": [{"kind": "real_longevity", "dimension": "hook", "value": "mistake", "heading": "...", "observation": "...",
               "example_ids": ["..."], "next_test": "...", "simulated_note": "...", "how_to_test": {"tool": "feedtest", "config": {}}}],
 "caveats": ["..."], "credit": "...", "ads": [{"id": "...", "labels": {"hook": {"value": "mistake", "confidence": 0.8}}}],
 "markdown": "..."}
```

`ad_patterns.md` and `ad_patterns.csv` (one row per ad with its seven labels) are written next to it.

## Keeping the three kinds of numbers apart

| `kind` | Means | Never means |
|---|---|---|
| `real_longevity` | The share of dated, still-active real ads that started 60+ days before collection, compared with the library as a whole | profit, spend, CTR, or the chance that a new ad will work |
| `real_results` | The rows' own impressions, clicks, conversions and spend, summed per label (your account) | the market as a whole |
| `simulated` | Your feed-test creatives on the same labels, with their simulated CTR | a measurement |

Rules in the code:

- Simulated creatives are never counted in `longevity` or `results`, even when they have dates.
- A label counts only with at least max(5, 2% of dated ads) dated ads.
- A longevity finding appears only when its share beats the library baseline.
- The markdown, the dashboard section (pills "Real ads · longevity" and "Simulated") and the MCP `results` summary all
  say that longevity is observational.
- `caveats` and `credit` travel with every file.

## Pictures (`--vision`)

With `--vision`, rows that carry `image`, `image_url`, `thumbnail_url` (a local path, data URI or https URL) or `video` (a local file; keyframes need ffmpeg) are described first by the backend's `creative-check` endpoint. The description and the words on the picture become the row's `visual_notes`, so the labels read the picture as well as the copy.

## Not in this version


- Collecting from the Ad Library through an API or a scraper.
- Feeding the findings into `ideas`, and a market-test config key.
- Perceptual (image) families.
- Real competitor ad data, which needs the owner's permission.

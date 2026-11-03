# MarketMirror-Bench results

Every paid run is recorded here, misses included. Raw files are in `results/<date>/`.

## 1 November 2026: first run

Model: Claude Sonnet through the local login gateway (`backend/gateway/local_gateway.py --backend claude`).
Panel: 10 people from a 1,000-person Fitloop run (a fitness app; these are not news readers).
Data: 50 Upworthy confirmatory-archive tests with a clear winner, and 20 Twin-2K-500 people x 20 of the
buy-at-this-price questions (both CC BY 4.0). Sample fixed by the bench's salted hash.

### Upworthy: pick the headline that got the most clicks

| Method | Picked the real winner | 95% range | Spearman with real CTR | Calls |
|---|---|---|---|---|
| chance | 34% | | | 0 |
| generic reader (no persona) | **64%** | 50-78% | 0.47 | 50 |
| persona panel | 44% | 30-58% | 0.20 | 500 |
| persona panel with a mild mood | 50% | 36-64% | 0.21 | 500 |
| persona panel asked for feelings | 36% | 22-50% | 0.18 | 500 |

The plain prompt with no persona beat the persona panel, as Maiorano et al. (2026, arXiv 2609.25010) found.
The panel also herded: in 66-75% of tests at least 80% of the panel picked the same headline.

### Twin-2K-500: predict each person's buy / don't-buy answer

| Method | Accuracy | 95% range | Normalised by test-retest (0.838) | Brier | Predicted "buy" | Real "buy" |
|---|---|---|---|---|---|---|
| majority (leave-one-out) | 49.0% | 44-53% | 0.585 | 0.51 | 32% | 43% |
| no persona | **61.3%** | 55-67% | 0.731 | **0.388** | 66% | 43% |
| twin (summary of waves 1-3) | 59.8% | 52-67% | 0.713 | 0.403 | 70% | 43% |
| twin, feelings first | 61.0% | 54-68% | 0.728 | 0.390 | 64% | 43% |

Every model method predicted far more buying than real people reported.

### Emotion layer gate: not passed

`on` stays off by default. Feelings panel vs persona panel -8 points (-22 to +6), vs generic reader -28 points
(-44 to -10); twin with feelings first vs twin +1.2 points (-2.5 to +4.7); feelings looked human (69% "nothing
much", no caricature flag); pleasantness vs real clicks Spearman 0.003 (-0.19 to +0.21), so the negativity sign
does not match. Details: `results/2026-11-01/bench_emotion_gate.md`.

### Caveats

- 50 tests and 20 people give wide ranges.
- The model may remember which Upworthy headlines won; both datasets predate it.
- The panel's personas were built for another product.
- A good score on these tasks is not evidence for a particular market.

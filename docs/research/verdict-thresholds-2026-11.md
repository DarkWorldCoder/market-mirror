# Small shifts, big verdict swings: what 4,501 simulated survey answers show

Written 23 Nov 2026 from saved MarketMirror runs. No new model calls. Every number is from simulated people, not
real buyers, and from one invented brand (Fitloop, a home-workout app).

## The data

- 13 saved runs with a buyer survey: 4,501 answers to "would you start the free trial?" (yes / maybe / no), each with
  a free-text explanation.
- One of them, the 3,000-person market run of 21-23 Oct 2026, has three panels of 1,000 people. Each panel was
  written, interviewed and played by a different model: Claude Sonnet, Codex (gpt-6-luna) and Gemini 3.8 Flash.
  The panels share the brief, the questions and the country mix (428 India, 375 Philippines, 197 Kenya each). They
  are different people, so the writer and the answering model cannot be separated.
- The free-text answers are scored on a 1-5 purchase-intent scale by semantic similarity to anchor sentences (SSR,
  local embeddings, no model call).

## What we found

**1. Simulated buyers hedge.** Across all 4,501 answers, 1.6% said yes, 57.9% maybe and 40.5% no. In the 3,000-person
run, each person's own stated chance of converting averaged 14.6% (Claude panel), 14.4% (Gemini) and 6.5% (Codex).

**2. The verdict swings far more than the reasons do.** In the 3,000-person run:

| Panel written and played by | Said "no" | Said "maybe" | Free-text intent, 1-5 (mean, SD) |
|---|---|---|---|
| Claude Sonnet | 23% | 76% | 3.05 (0.45) |
| Gemini 3.8 Flash | 29% | 70% | 3.04 (0.49) |
| Codex (gpt-6-luna) | 94% | 6% | 2.56 (0.31) |

The same split holds inside every country (Codex panel 93-96% "no"; the others 19-37%).

**3. The labels mean the same thing in every panel.** Free-text intent behind a "no" is 2.52-2.62 for all three
panels, and behind a "maybe" 3.17-3.24. The Codex panel is not using the words differently; its people are about half
a point less keen.

**4. Why half a point flips most of a panel.** Each panel's answers are packed tightly: a standard deviation of
0.31-0.49 on a 1-5 scale. When almost everyone sits near the line between "maybe" and "no", moving the whole panel by
half a point moves most people across it. A three-option verdict turns a modest difference into a 70-point swing.

**5. It can change which ad wins.** In the same run's feed test, the Claude and Gemini panels ranked the 7-day
challenge ad first; the Codex panel ranked the price ad first, with an expected click-through of 0.42% against
1.27-1.59%.

## What it means

- Compare panels, ads or models on continuous scores (free-text intent, stated chances), not on yes / maybe / no
  shares. The closed verdict exaggerates small shifts when answers are this alike.
- Treat the spread as a warning sign. Real survey answers vary much more (154 of 164 outcomes in arXiv 2509.19088
  found simulated answers less spread out); a tight panel will swing on small prompt or model changes.
- Run more than one model when the decision matters, and read agreement as robustness, not accuracy: models can agree
  with each other and still disagree with people.

## Limits

One invented brand and one market test; three different panels rather than the same people answered by three models;
SSR intent is a model of the text, not a measured behaviour; no real answers were collected for this brand. These are
patterns in simulated data that suggest how to read it, not facts about real buyers.

## How to reproduce

The analysis reads `survey.json` and `config.json` (`persona_index[].model_provider`) in each run folder and the
per-answer `answer.ssr.purchase` scores; the feed numbers come from `feed_test.json` `summary.by_provider`.

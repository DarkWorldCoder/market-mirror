# Realism and trust: what the 2024-2026 evidence says, and what MarketMirror does about it

Written 23 Nov 2026 from two literature reviews (realism of simulated people; trust in synthetic research). Most 2026
items are arXiv preprints, not yet peer reviewed. Numbers are quoted from the papers; where only an abstract was
available, that is said.

For a consolidated list of cited academic papers, see [Research References](REFERENCES.md).


## What goes wrong with simulated people

- **Gaps between segments are too big.** Models inflate differences between segments 2-4x and pick the wrong top
  segment in about half of US cases; bigger models do not fix it (Chen, Zhu & Zheng 2026,
  [arXiv 2607.26348](https://arxiv.org/abs/2607.26348)). Predicted treatment effects correlate with real ones
  (r = 0.85 over 70 experiments) but are larger than real (Hewitt et al. 2024).
- **Answers are too alike.** Across 19 studies, simulated answers were less spread out than real ones in 154 of 164
  outcomes; twins built from 500+ real answers reach r = 0.20 with the person ([arXiv 2509.19088](https://arxiv.org/abs/2509.19088)).
  Pew (Sep 2026) calls synthetic polls "one-note", and found the model choice changes the picture of the public.
- **Demographic labels carry too much weight.** One demographic feature explains a two-feature persona better than
  both in 75-82% of subgroups (Rennard 2026, [arXiv 2608.23005](https://arxiv.org/abs/2608.23005)).
- **Model-written persona detail adds bias.** The more LLM-generated text in a persona, the more skewed the results
  (Li et al., NeurIPS 2025, [arXiv 2503.16527](https://arxiv.org/abs/2503.16527)).
- **Simulated buyers rarely walk away.** On 2,790 real sales chats, simulated non-buyers kept engaging and their
  stated resistance fell from 25.1% to 13.5% (Chen 2026, [arXiv 2606.20708](https://arxiv.org/abs/2606.20708)).
- **Position bias in choices.** After removing answer-position effects, synthetic group differences correlate with
  real ones about twice as well (Kim, Baek & Lee 2026, [arXiv 2611.09977](https://arxiv.org/abs/2611.09977)).
- **More reasoning does not help.** On SimBench (ICLR 2026) the best model scores 40.8/100; fidelity grows with model
  size but not with inference-time compute, and instruction tuning hurts on questions where people disagree.

## What earns trust

- **Disclosure.** AAPOR's 2026 task-force report asks every AI-respondent study to state that the AI answered, how
  many real people took part, the model and access method, the dates, whether the agents had memory, what a human
  checked and the known biases, and not to call the result a poll or survey
  ([AAPOR 2026](https://aapor.org/wp-content/uploads/2026/05/Responsible-AI-Integration-In-Survey-Research.pdf)).
- **Answers to ESOMAR's 20 questions** for buyers of AI-based services; Ipsos, Toluna and Voxco publish theirs.
- **Scored forecasts.** Locking a prediction before the outcome is known, then scoring it, is how vendors now answer
  "why should we trust you" (Aaru's blind reruns, Fortune, Jun 2026).
- **Reproducibility.** Models change silently; the exact model, date and prompt version have to be recorded.
- **Honest accuracy numbers.** Critics found vendor figures measured against a "human ceiling" rather than raw
  accuracy (Simile 85%, Artificial Societies 95% vs 86% raw on its own page). Keeping the misses visible matters.

## What MarketMirror does now

| Finding | In MarketMirror |
|---|---|
| Segment gaps inflated 2-4x | Each segment's would-convert share is shrunk toward the overall rate by 0.4 when no real data exists; a "Close call" note appears when the shrunk lead is under 3 points or a top segment has fewer than 10 people |
| Test-arm effects inflated | Split-test lift shrunk toward the average (prior 0.55), already in place |
| Too alike | `too_alike` flags in surveys and the questionnaire; the spread check in `calibrate` |
| Position bias | Option order shuffled per person (questionnaire, monadic recipes); verdict order randomised in the survey |
| Disclosure | Every dashboard has "How this was made" and `disclosure.md` with the AAPOR items |
| Reproducibility | `run_manifest.json.provenance`: models, engine commit and local changes, a hash of the prompt code, seeds, spend approval |

## Next, in order of value

1. Pre-registered forecast ledger: hash and timestamp a run's prediction, score it when actuals arrive, publish hits and misses.
2. Persona datasheet per run (grounded vs derived, sources, target vs actual demographics, coverage gaps).
3. A "when not to use" gate before spend (new categories, small subgroups, absolute rates, identity-sensitive topics).
4. Weight personas by how well they match real anchor answers (P2P, NeurIPS 2026: MSE 0.014 across 14 ATP waves).
5. Real example answers from the matching segment in the prompt at answer time (mixture of personas, ACL Findings 2025).
6. Walk-away rates fitted to real sales conversations instead of fixed rules.
7. Turn off extended reasoning for persona calls and offer a model mix for spread (never as validation).
8. Published answers to ESOMAR's 20 questions, and a public, versioned accuracy leaderboard that keeps the misses.

Evidence that looked weak: fine-tuned "human behaviour" models such as Centaur (overfitting critiques), richer
digital twins (r = 0.20), prompted cognitive biases (no study shows human-sized effects in consumer choice), and
agreement between models as validation (models agree with each other while disagreeing with people).

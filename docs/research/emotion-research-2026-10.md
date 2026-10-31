# Giving simulated buyers feelings: research and what MarketMirror built, October 2026

Reviewed 31 October 2026. This note covers what the research says about emotion in LLM agents and simulated consumers, what MarketMirror now does, and what is still unproven. It complements [HUMAN_BEHAVIOR_RESEARCH.md](../HUMAN_BEHAVIOR_RESEARCH.md) (the behaviour model) and [feature-research-2026-10.md](feature-research-2026-10.md) (feature ranking).

Read with care:

- Papers from 2026 are mostly preprints. Their effect sizes describe their own tasks, models and populations.
- An LLM does not have feelings. "Emotion" here means a simulated state: an appraisal the model writes down, mapped by fixed rules, with a mood that fades over simulated time.
- Nothing in this note has been validated in MarketMirror against real buyers. The bench that would test it is built, but no results have been published yet.

## 1. The problem

Simulated panels are known to go wrong in ways that real emotion often explains:

| Failure | What was reported | Why it matters for marketing tests |
|---|---|---|
| Too positive | Simulated respondents lean favourable (Kaiser et al. 2026) | Every ad looks better than it is |
| Too uniform | Answers bunch into a narrower range than human answers (Ogg et al. 2025; Peng et al. 2025) | Real differences between ads and audiences shrink |
| Rarely walk away | In sales-style conversations, simulated customers resisted far less than real ones; resistance fell from about 25% to 13.5% (Chen et al. 2026) | Pitches look easier to close than they are |
| Groups converge | Simulated group discussions converge on one opinion too quickly (DEBATE, 2025) | Focus groups hide disagreement |
| Personas can lose to no persona | On Upworthy headline tests, a plain no-persona ranker beat a 10-persona panel (Maiorano et al. 2026, arXiv 2609.25010) | Adding detail is not the same as adding accuracy |

Emotional state also changes what LLMs choose as consumers. In one study, an anxiety prime shifted simulated shopping baskets by large effect sizes (Cohen's d of about −1 to −2; arXiv 2510.06222). So feelings matter, and they can be steered, which makes them both useful and risky.

## 2. The model we chose

The best-supported template is **layered affect** (ALMA; Gebhard 2005), with three layers:

1. **Traits** are stable. Each person has a home mood, a level of reactivity, a fading speed and a weight on negatives.
2. **Emotions** come from appraisal, one per stimulus: how pleasant, new, relevant, controllable, fair and urgent something is. This follows the OCC model (Ortony, Clore & Collins 1988) and Scherer's appraisal checks.
3. **Mood** is a pleasure / arousal / dominance (PAD) state that each emotion pulls on. It decays back to the person's own baseline over time, as in DynAffect (Kuppens et al. 2010).

Reporting uses scales people answer in human studies. Pleasantness goes on the 1-9 Self-Assessment Manikin (Bradley & Lang 1994). Free-text feelings are rated by semantic similarity to anchor statements, the same SSR method MarketMirror uses for survey intent (Maier et al. 2025, arXiv 2510.08338).

## 3. What MarketMirror now does

| Part | What it does | Mode |
|---|---|---|
| Appraisal on existing calls | The feed ad, the landing page, email reads, the survey (plus a sentence on how the offer feels) and both pitch turns ask for a short `feel` object. No extra model calls; about 3-6% more output tokens | `observe` (default) and `on` |
| Fixed rules | The appraisal maps to one of 12 feelings. A relevance gate keeps "nothing much" common, intensity is capped at 0.85, and when the model's own label disagrees with the rules, the rules win and the mismatch is reported | both |
| Mood that fades | Mood is kept per person in `behavior_state.json` v2 and decays toward that person's baseline over simulated hours. Dislike of the brand fades more slowly | both |
| Walk-away | The pitch allows "not now". Resistance is reported, and a rate below 20% is flagged as low for real buyers | both; in `on`, walk-aways get no rebuttal |
| Couplings | Small bounded multipliers on what the code already decides: ad notice and wear-out, landing patience, the wallet threshold, the polite back-out at payment, email opens and actions per social round. Directions follow Lerner & Keltner (2001), Zeelenberg & Pieters (2007) and Berger & Milkman (2012). No new random draws, so modes stay comparable | `on` only |
| Words check | The stated pleasantness is compared with what the person's own words say (local embeddings, no model call). It is flagged when they mostly disagree | both |
| Focus group check | Private feelings before and after are compared with how people sounded in the room. Flags: masking (warmer in public) and over-convergence (the room flattened them) | both |
| Quality flags | Too uniform, positive skew, caricature (too few "nothing much" answers, or feelings too intense) | both |
| Say vs do | Survey and pitch yeses are shown next to what is left after fixed say-do rules from each person's decision card | always, labelled as an assumption |
| Evidence grade | A-D per run, from people, seeds, retest, real-data check, providers and feelings flags. The report never states a C or D as firm | always |

`off` leaves every prompt byte-identical to the version before the emotion layer.

## 4. How it will be validated

`bench` now runs an ablation on open human data:

- **Upworthy** (real headline A/B tests): `persona_panel` against `persona_panel_feel` (feelings asked with the vote) and `persona_panel_mood` (a mild seeded mood line), next to `generic_reader`. Bootstrap 95% intervals with paired differences per test.
- **Negativity check:** on Upworthy, negative words raised click-through (Robertson et al. 2023). If the simulated feelings mean anything, pleasantness should run against real clicks.
- **Caricature proxy:** how often at least 80% of the panel picks the same headline (real readers split; caricatured personas do not; CoMPosT, Cheng et al. 2023).
- **Twin-2K-500** (real people's buy-at-this-price answers): `twin` against `twin_affect` (feelings first), on accuracy and Brier score.

The **default-flip gate** in `bench.flip_gate` keeps `observe` as the default unless all four checks pass:

1. The feelings panel is at least as accurate as both `persona_panel` and `generic_reader`.
2. `twin_affect` is no worse than `twin` on accuracy and Brier score.
3. At least 30% of feelings are "nothing much" and none are flagged as caricature.
4. The negativity sign matches.

The results go into the findings and the article whichever way they come out.

## 5. What is not proven

- Coupling sizes are assumptions. Their directions come from human studies, but the sizes have not been fitted to MarketMirror's people.
- A self-reported model appraisal is not an emotion. The words check and the quality flags catch some failures, not all.
- Mood decay times (12-48 simulated hours, brand dislike about a week) are chosen, not measured.
- None of this replaces a small real test. The evidence grade keeps that visible.

## References

- Berger, J. & Milkman, K. (2012). What makes online content viral? *Journal of Marketing Research*.
- Bradley, M. & Lang, P. (1994). Measuring emotion: the Self-Assessment Manikin. *Journal of Behavior Therapy and Experimental Psychiatry*.
- Chen et al. (2026). Simulated customers in sales conversations (preprint).
- Cheng, M. et al. (2023). CoMPosT: characterizing and evaluating caricature in LLM simulations. *EMNLP*.
- DEBATE (2025). Convergence in simulated group discussions (preprint).
- Gebhard, P. (2005). ALMA: a layered model of affect. *AAMAS*.
- Kaiser et al. (2026). Positivity bias in LLM survey respondents (preprint).
- Kuppens, P., Oravecz, Z. & Tuerlinckx, F. (2010). Feelings change: the DynAffect model. *Journal of Personality and Social Psychology*.
- Lerner, J. & Keltner, D. (2001). Fear, anger and risk. *Journal of Personality and Social Psychology*.
- Maier et al. (2025). LLMs reproduce human purchase intent via semantic similarity elicitation (arXiv 2510.08338).
- Maiorano et al. (2026). Persona panels against a generic reader on Upworthy (arXiv 2609.25010).
- Ogg et al. (2025); Peng et al. (2025). Variance compression in LLM survey answers (preprints).
- Ortony, A., Clore, G. & Collins, A. (1988). *The Cognitive Structure of Emotions*.
- Robertson, C. et al. (2023). Negativity drives online news consumption. *Nature Human Behaviour*.
- Zeelenberg, M. & Pieters, R. (2007). A theory of regret regulation. *Journal of Consumer Psychology*.
- arXiv 2510.06222 (2025). Emotional priming changes LLM consumer choices.

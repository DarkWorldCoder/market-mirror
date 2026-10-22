# What makes large simulated markets fast: research notes

October 2026. We looked at 40 open-source projects, datasets and papers that simulate large LLM populations or speed up many small LLM calls. We read the code of the ten most promising, and an independent reviewer tried to refute each speed claim for MarketMirror's setup. That setup is login CLIs (7-12 calls at once per provider, with about 20,000 tokens of CLI instructions per call) or API keys (50+ calls at once). It has no GPU and mixes providers, with one provider per person. Its rules are that nobody is invented and that failures are counted, never filled in.

The short version: most of the large speedups reported elsewhere come from running your own GPU servers, or from sharing one answer across many people. Neither fits here. What does fit has been built in: see the first table below.

## Borrowed

| Idea | Source | What we built | Gain for us |
|---|---|---|---|
| Keep every provider's slots busy instead of waiting for the slowest call in a batch | AI Metropolis (out-of-order execution, MLSys 2025); OpenCity's request scheduler | Each batch of 4 people goes straight through persona → interview → follow-ups on its provider's own lane. Survey and pitch batches mix providers and hold up to 120 people per call (`MM_INTERVIEW_BATCH`) | Persona writing: 3,000 full-depth people in about 2.5 h instead of 10+ h (measured). Survey and pitch: estimated 1.3-2x |
| One model call per activated agent per turn | OASIS time engine (camel-ai/oasis, Apache-2.0) | `OASIS_MAX_ITERATION=1` for large runs | Estimated 2-3x fewer calls in the social rounds |
| Small batches, numbered items, parse answers by index | Batch Prompting (Cheng et al., EMNLP 2023): accuracy holds at 3-4 items and drops from about 6 | 4 people per persona/interview call, numbered rows, re-ask only the missing ones | Kept at 4 deliberately |
| Cache by exact prompt | Bespoke Curator's run cache (Apache-2.0) | `population_cache.sqlite`: a rerun or a restart replays every person already written | Measured: 540 people replayed in 16 s after a restart |

## Looked at and not used (yet)

| Idea | Source | Why not |
|---|---|---|
| Archetypes: one answer per cluster of similar agents | AgentTorch "LLM archetypes" (AGPL-3.0); APS prototype simulation | People in a cluster would share one answer, which breaks "every person's answer comes from a call about that person". It would have to be a separate, clearly labelled mode |
| Many people in one call (group-and-distill) | OpenCity (no license: idea only); BatchPrompt | Estimated 1.2-1.4x on the survey, but answers in one call become correlated. Counted honestly (cluster-adjusted ranges), the gain can disappear. Possible later as an opt-in mode with an A/B check |
| Folding pitch turn 1 and turn 2 into one call | "Fast silicon sampling" (arXiv 2608.14079) | About 1.6x on the pitch, but people would see the rebuttals before they object, which changes the experiment |
| Batch APIs (Anthropic, OpenAI) | Provider docs; Bespoke Curator | Half price, but they need an API key and return results in minutes to hours, not faster. Useful for cost on API runs, not for speed |
| Prompt caching (Anthropic, DeepSeek) | Provider docs | The login CLIs already cache their own instructions. On APIs our calls are output-bound, so the wall-clock gain is 0-3%; it lowers cost |
| Ready-made persona pools | NVIDIA Nemotron-Personas (CC BY 4.0) | About 1.05-1.4x on persona writing. The profiles would come from NVIDIA's pipeline rather than the provider that plays the person, so they would need a label. A good option for census-grounded demographics later |
| Hybrid agents: an LLM for core users, rules for the rest | HiSim (Apache-2.0); Affordable Generative Agents | Changes what the social rounds measure. OASIS's own activity sampling already limits who calls the model each round |

## What limits speed now

Output tokens and calls in flight per provider. A full-depth person is about 3,000 output tokens across three calls. Through the login gateways, Codex manages about 7 calls at once and Gemini about 10 (roughly 73 s each). With an API key (see the README section on costs) the same work runs 50 or more calls at once, and preparing 3,000 people takes about 20-55 minutes.

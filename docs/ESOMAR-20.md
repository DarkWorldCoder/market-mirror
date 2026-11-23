# MarketMirror and ESOMAR's 20 questions for buyers of AI-based services

ESOMAR publishes 20 questions that research buyers use to evaluate AI-based services. Ipsos, Toluna and others publish their
answers. These are ours. The questions are paraphrased and grouped by ESOMAR's themes. Answers describe the open-source
software in this repository as of November 2026; where something is not done, we say so.

## The company and its experience

**What experience do you have with AI-based research, and where does AI help?**
MarketMirror is an open-source tool built on the MiroFish engine. It tests ads, prices, surveys and sales pitches on
language-model personas inside a social simulation. It helps with fast, cheap screening: comparing wordings, finding
objections, pretesting questionnaires and ranking options before real research.

**What problems have you run into, and what has worked less well?**
Our own benchmark (1 Nov 2026, [results](../benchmarks/bench/RESULTS.md)) found:
- A plain prompt with no persona picked winning headlines more often than a persona panel did.
- Every method we tried predicted more buying than real people reported: 66% predicted against 43% real on Twin-2K-500.
- An emotion layer did not improve accuracy, so it stays off for decisions.

We publish these misses.

## Explainability and fitness for purpose

**What does the AI do, in plain terms?**
It writes invented people from your brief and any real customer data you supply. Each person answers your test in a
separate model call: they scroll a feed with your ad, answer a survey, react to a pitch, or fill in your own
questionnaire. Each run ends in a report and a dashboard. Every exported run has a "How this was made" disclosure
(`disclosure.md`).

**Which models do you use? Did you build them?**
We train no models. Runs call the third-party model you configure, such as Anthropic Claude, OpenAI, Google Gemini or
others through an OpenAI-compatible endpoint, or a local model. The run manifest records the model, the engine's git
commit and a hash of the prompt code, so a run can be repeated.

**How is the service trained, and what data shapes it?**
There is no training step. Personas come from the brief, a demographic sampler with raking weights, and optional real
inputs: customer records (`intake`), web-analytics aggregates and public research voices. A persona built from real
records is marked Grounded.

**How do you validate output, and handle unreliable or biased results?**
- `calibrate` compares simulated answers with real answers to the same questions. It reports PPI++ intervals, a spread
  check for answers that are too alike, and the effective number of real answers the panel is worth.
- `backtest` compares with past ad results.
- `forecast lock` and `forecast score` hash a run's prediction before the real result exists and score it afterwards.
- Every run gets an A-D evidence grade. It drops for thin samples, flagged answer spread and markets the models cover
  less well.
- Segment gaps are shrunk by default, because models exaggerate them 2-4x.
- Before any spend, a fit check warns when a test is a poor fit: small segments, sensitive topics, new categories,
  absolute forecasts, or less-covered markets.

**What are the limits, and how do you mitigate them?**
- Simulated answers vary less than real ones.
- Gaps between groups are inflated.
- Simulated people overstate buying.
- Fit is weaker outside the US, UK, Canada, Australia, New Zealand and Ireland.
- Identity groups get flattened.
- New categories fail most often.

The mitigations are the ones listed above, plus the real-people check kit (`real_check.md/.csv`) that every run writes.
We say the results are directions, never measurements, and recommend a small real test before spending. See
[realism and trust research](research/realism-and-trust-2026-11.md).

## Trust, ethics and transparency

**How did you design for a duty of care to people?**
- The simulated people are invented and are never presented as real.
- Real customer data stays on the user's machine. Contact details are removed locally during intake.
- A seed-document check warns about personal data before upload.
- Website tests mask inputs in screenshots and keep recordings opt-in.

**How do you make clear when AI is used?**
Every dashboard and `disclosure.md` states that AI models answered and no real person did, and how many real answers
were compared. Following AAPOR's 2026 guidance, we do not call a simulation a poll or a survey.

**How do you provide human oversight and accountability?**
- Paid steps need explicit approval (`approve_spend`). The people are shown before approval.
- A hard dollar cap can stop new model calls.
- Every run keeps its inputs, prompts' code version and outputs locally, for review.
- The code is open, and changes go through public pull requests with tests.

## Data, privacy and security

**What data do you use, and where does it go?**
Inputs and outputs are saved in the user's installation. Model calls send prompts to the provider the user configures,
under that provider's terms. See [PRIVACY.md](../PRIVACY.md) and the
[provider data handling table](PROVIDERS_AND_SCALE.md#provider-data-handling). There is no MarketMirror account and no
hosted MarketMirror service receiving the data.

**How do you comply with privacy law and protect participants?**
Simulated runs involve no research participants. When users import real customer data, they are the controller and
need their own legal basis. MarketMirror processes that data locally, removes contact details during intake, and hashes
ids in `real-split`.

**What security frameworks do you use?**
MarketMirror is self-hosted software, not a certified service. It binds to localhost by default, uses a local setup
token for the app, and never prints provider keys. Report vulnerabilities as described in [SECURITY.md](../SECURITY.md).
Users who need certified controls should run it inside their own controlled environment.

**Who owns the output, and what happens to the data?**
Users own their inputs and outputs. The software is AGPL-3.0, and runs are stored where the user chooses until the user
deletes them. Copies held by a model provider follow that provider's retention terms.

## Not yet done

- No third-party audit or certification of the method.
- No published real-versus-simulated case study with a named brand.
- The forecast ledger is new, and no scored forecasts are published yet.

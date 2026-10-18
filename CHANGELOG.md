# Changelog

## 0.3.0 (2026-10-18)

- Product understanding (`understand`): one profile every step reads; market map seeded before the graph build.
- No-key gateway over Claude Code / Codex logins (`backend/gateway/local_gateway.py`, `mm.sh gateway`).
- Research-backed persona engine: adaptive interview probes, product questions, BDE card, stereotype guard, population weights, verbalized chances with a dispersion check, test-retest, `calibrate` (overlap, per-audience verdicts, AIPW correction), SSR on pitch replies.
- Speed: agent memory window, concurrent batch interviews, config generator pool, speed knobs; 150 people in 11 minutes instead of 40.
- Email campaign testing; one `test` spec for ad, message, price, offer, positioning, naming, landing, launch, pitch, email, creator post and channel-mix tests.
- Studies (scenarios x seeds, one conclusion), `predict` with a calibration store and a 90-day forecast.
- Research from public keyless sources (Hacker News, App Store reviews, Reddit when reachable, pages) and a voice store that grounds personas, feeds, the report and the ideas; live context into running rounds.
- Report v2: so-what per section, sales rehearsal, email results, real-world check, budget plan, 30-day plan, decision changers, risks, reliability note.
- Dashboard design system (tokens, theme switch, scrollspy, sortable tables, filters).
- API docs and OpenAPI, Python SDK, Dockerfile and compose, CI, contributor files, marketplace packaging.

## 0.2.0 (2026-10-18)

- Interview-grounded personas, brand posts inside the rounds, social feed, plain-language report, sales rehearsal, test ideas, quickstart, MCP server, measured costs.

## 0.1.0

- MarketMirror on the MiroFish engine: persona planner, feed test, buyer survey, pricing, analyst panel, decision card, dashboard, Claude skill.

---
name: market-mirror-testing
description: Run controlled marketing and sales simulation tests and studies on the same audience with repeatable seeds.
---

# Testing

Use `run_test` for one experiment spec from a campaign plan. Supported families include ads, offers, price, landing, search and organic content concepts, nurture and retention messages, referrals, and sales outreach and follow-ups. Search/organic/referral concept tests use survey responses; nurture/retention use the inbox engine; sales tests use pitch rehearsal. Do not present their simulated metrics as observed channel performance.

Use `study` for scenario comparisons on the same simulation and seed list. Poll `job_status` until complete, then read result paths and compare paired seed deltas. Rerun the same study spec to resume finished cells. Recommend a small real randomized test with the outcome metric and audience recorded.

For a real product URL use `website_test` with an existing `simulation_id`, a URL, a concrete visitor task, and optional named DOM checks plus `goal_check`. Browser support is an optional install; see `docs/WEBSITE_TESTING.md` in the engine checkout. Start with 1–3 visitors. Cart/checkout goals enable cart writes; account submission needs explicit `allow_signup_submit`, supplied test identities, and a goal check. Never submit orders or payments. A model saying it finished is `completed_unverified` unless the supplied outcome assertion passes. Report screenshots, action traces, model/browser failures, and deliberate departures separately. These are actual browser actions by synthetic visitors, not measured human conversion rates.

The browser controller supports keyboard/search, options and checkboxes, hover menus, navigation, same-site tabs/frames, and open shadow DOM. Reference IDs expire after each attempted action. Recovery requires inspecting the new state and checking outcomes before another action; never blindly replay a cart or signup write after a timeout. `record_video`, `record_trace`, `headless`, and `max_recoveries` are optional spec fields. Video and traces can contain raw test data; enable them only when needed and keep them private.

Browser model context defaults to `observation_mode: compact`, with up to 4,000 page-text characters and all observed controls. Full evidence stays local; use `full` or raise `observation_text_chars` when more context is needed. Keep the mode fixed across comparisons. Set whole-run `max_model_calls`, `max_input_tokens`, and `max_elapsed_s` as appropriate; these stop between actions and cannot cap an in-flight call or invoice spend. Missing usage halts further calls when a token limit is configured. Default `loop_limit: 3` catches repeated actions on equivalent state. Report `budget_exhausted`, unstarted visitors, and `loop_detected` separately from departures. Review `efficiency.usage` for cache breakdowns, model time, and reported-cost basis; unknown costs stay null and CLI list cost is not an invoice. Character reduction is not proven token savings.

Keep synthetic interviews separate from real customer evidence. Hand-set attention rates, seed variation and repeated synthetic answers do not establish human predictive accuracy. Use held-out real experiments to assess rankings and rates separately; group related variants within one split. A training-mean baseline and a generic-reader LLM baseline answer different questions. See `docs/HUMAN_BEHAVIOR_RESEARCH.md` in the engine checkout for the paper review and proposed behavior architecture.

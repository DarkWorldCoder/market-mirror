# Test a real product website

Give MarketMirror a real product URL and a prepared synthetic audience. Each visitor gets an isolated Chromium session and decides what to do from the site's rendered DOM: inspect the product, search, choose an option, add to cart, find signup, continue to checkout, or leave. Screenshots and action traces show what happened on the site. These are synthetic visitors using an actual interface, not real customer observations or a conversion forecast.

## Install browser support

From the repository root:

```bash
cd backend
uv sync --extra browser --python 3.12
uv run python -m playwright install chromium
```

On Linux hosts missing browser libraries, use Playwright's documented dependency setup for your OS. See [Playwright installation](https://playwright.dev/python/docs/library). Restart the backend after installing or changing environments. Browser support is optional; other MarketMirror tests do not require it.

## Start with a URL

Prepare an audience through quickstart or an existing project, configure your model provider, and start the backend. From the repository root:

```bash
./mm cli website-test --simulation "$SIMULATION_ID" \
  --url https://your-product.example/products/running-shoes \
  --goal add_to_cart --task "Find shoes for everyday running. Decide whether to add a suitable pair to your cart." \
  --limit 3 --steps 12 --out mirofish_runs/shoe_journey
```

The placeholder URL must be replaced with your actual site. Cart goals permit actual cart changes. Use a site you operate or are authorized to test, preferably a staging storefront or test tenant where generated analytics and cart activity can be isolated. Test traffic can reach your site's analytics and backend.

The default is three mobile visitors with up to twelve actions each; limits are 20 visitors and 30 actions. `--device desktop` changes the viewport. Goals: `explore_product`, `add_to_cart`, `reach_signup`, `complete_signup`, `reach_checkout`, `custom`. A goal describes the task; it is not itself proof of completion.

## Control context, usage, and run limits

The model receives a compact observation by default: labeled controls and their state, page text up to 4,000 characters, tabs, frame scopes, and recent browser errors. Empty fields, geometry, and controller-only metadata are omitted from model input. Full observations, controls, and screenshots remain in the local evidence. Truncated text is explicitly marked; use `--observation-mode full` or increase `--observation-text-chars` when the task needs more detail. Compact context changes the information available to the model, so keep the same setting across comparison scenarios and validate it on representative journeys.

```bash
./mm cli website-test --simulation "$SIMULATION_ID" --spec @website_test.json \
  --max-model-calls 12 --max-input-tokens 100000 --max-elapsed-s 180 \
  --observation-mode compact --observation-text-chars 4000 --loop-limit 3
```

REST, Python SDK, and MCP accept the same fields in `spec`:

| Field | Default | Meaning |
|---|---|---|
| `observation_mode` | `compact` | `compact` or `full`; full retains the previous model observation format |
| `observation_text_chars` | `4000` | Compact text cap, 1,000–10,000 characters; all observed controls remain available |
| `max_model_calls` | unset | Whole-run call cap, including failed calls; 1–600 |
| `max_input_tokens` | unset | Whole-run input-token threshold, including cached input; 1–100,000,000 |
| `max_elapsed_s` | unset | Whole-run elapsed-time threshold, up to 86,400 seconds |
| `loop_limit` | `3` | Stop before the Nth equivalent action on unchanged observed state; 2–10 |

Limits apply across visitors and are checked between actions. They cannot interrupt an in-flight call or browser operation; one call can cross a token or time threshold. Missing token usage stops further calls when an input-token limit is configured. Estimated gateway usage remains labeled as estimated. These are operational limits, not an invoice spending cap. Calls are counted once per runner request; provider SDK retries can perform additional upstream requests.

Repeated actions are compared without volatile reference IDs or decision explanations. Changed page text or control state counts as progress; scrolling is excluded because position is not in the observation. A detected loop ends that visitor with `loop_detected`. Budget stops use `budget_exhausted`; visitors never started because of the shared budget have `started: false`. Either stop makes the result `status: stopped`. Neither is counted as a buyer choosing to leave.

Each model step records usage, response model, model latency, and full/compact payload character counts when available. `efficiency.usage` aggregates fresh input, cache reads, cache writes, and reported cost. Missing breakdowns or costs stay null rather than becoming zero. `reported_cost_usd` can contain a partial total; `cost_usd` is populated only when every call has a cost. Claude CLI list cost is labeled `cli_reported_list_cost`, not treated as an invoice. A gateway response-cache hit reports zero upstream tokens and `no_upstream_call`; browser decisions at temperature 0.5 do not use that response cache. Prompt caching by the provider is separate.

Payload character reduction is diagnostic evidence, not measured token savings. No throughput or monetary savings are claimed without a provider-backed comparison.

The [owned context fixture comparison](../benchmarks/browser_context_fixture.json) completed the same seven-action search/options/cart journey in both modes. Compact payloads contained 19,218 characters versus 27,230 in full mode, a 29.42% reduction. Responses came from a deterministic acceptance policy, not an external model; this verifies preserved fixture controls and outcome, not model quality or token savings. Reproduce it with `backend/.venv/bin/python backend/scripts/benchmark_website_context.py` after installing Chromium and pytest. It writes new local journey evidence and replaces the benchmark JSON with the measured run.

## Browser control

The controller exposes observed controls rather than asking the model to invent selectors or execute JavaScript. Each observation includes labeled controls, available options, tab IDs, frame scopes, and recent browser errors. References expire after one attempted action. Replaced or hidden elements require a fresh observation.

| Control | Supported behavior |
|---|---|
| Navigation | Back, forward, reload, and navigation to previously observed same-origin URLs |
| Tabs | Keep same-site popups, switch tabs, and close a tab while retaining another eligible tab; up to four open tabs |
| Forms | Fill supplied test identity fields, search, select an observed dropdown option, set checkboxes/radios/switches, and submit searches with Enter |
| Menus and keyboard | Hover, focus, click, Tab, Escape, arrow keys, Home, End, and Space on observed controls |
| Scrolling | Up/down/left/right, 100–1,000 pixels per action; short bounded waits for changing pages |
| Embedded UI | Visible same-origin frames and open shadow DOM controls, including custom options and menu items |
| Recovery | Fresh observations after stale targets or interaction timeouts; two recoveries by default, configurable from zero to five |

Numeric quantity input is restricted to whole values from 1–10 within the control's supplied bounds. Other arbitrary free text is limited to search. Custom dropdowns are operated by clicking their observed combobox and option controls; native selects support direct option selection. Cross-origin and closed-shadow-root controls remain unsupported.

Recovery never blindly replays an action. A click may have completed before its navigation timed out; the runner checks the updated page and outcome assertions before asking the model what to do next. Each step records its target label, document scope, elapsed time, before/after URLs, and before/after screenshots. A permission-blocked action is separate from a technical failure or a deliberate departure.

To watch a local browser window or record a journey:

```bash
./mm cli website-test --simulation "$SIMULATION_ID" --spec @website_test.json \
  --record-video --recoveries 2
# On a machine with a graphical session:
./mm cli website-test --simulation "$SIMULATION_ID" --spec @website_test.json --headed
```

The SDK, REST API, and MCP spec accept the same options: `headless` (default true), `record_video` (default false), `record_trace` (default false), and `max_recoveries` (default 2). Visible-window mode requires a working graphical session and is not exercised by the headless CI fixtures.

`--record-trace` optionally saves a Playwright `trace.zip` for detailed inspection. **Raw traces and videos can contain unredacted test identities, page contents, and network payloads.** They are opt-in; use disposable test data and keep the artifacts private. JSON diagnostics redact supplied identity strings and screenshots mask input controls, including in frames; this does not sanitize video or raw trace files. Open a trace locally with `backend/.venv/bin/python -m playwright show-trace /path/to/trace.zip`. See [Playwright tracing](https://playwright.dev/python/docs/api/class-tracing) and [video recording](https://playwright.dev/python/docs/videos).

## Verify outcomes independently

For a verified outcome, supply a visible DOM assertion for the actual confirmation state. Inspect your site to choose selectors; do not copy example selectors blindly. Save as `website_test.json`:

```json
{
  "url": "https://your-product.example/products/running-shoes",
  "goal": "add_to_cart",
  "task": "Evaluate these shoes for everyday running. Add a suitable pair only if the price and product fit your needs.",
  "max_personas": 3,
  "max_steps": 12,
  "device": "mobile",
  "checks": [
    {"name": "product_visible", "selector": "[data-testid=product-title]"},
    {"name": "cart_added", "selector": "[data-testid=cart-count]", "text": "1"}
  ],
  "goal_check": "cart_added"
}
```

```bash
./mm cli website-test --simulation "$SIMULATION_ID" --spec @website_test.json
```

Checks inspect visible matches in the active tab and its eligible same-origin frames and, when specified, require a case-insensitive text substring. An optional `frame_url` restricts a check to an exact document URL. Open shadow DOM is traversed by CSS checks. Make checks specific enough to distinguish an empty cart, existing state, and newly completed work. A pre-satisfied goal is recorded separately as `already_satisfied`. Milestones record the first passing step and screenshot; they are counts, not a guaranteed sequential conversion funnel. A UI confirmation does not independently verify durable server-side state—reconcile with test-tenant logs or exports when needed.

Without a `goal_check`, agents can explore and report that they finished, but completion stays **unverified**. The runner does not turn a model's claim into an observed conversion. An agent choosing to leave, a step limit, a CAPTCHA, a blocked request, and a model/browser error have distinct statuses.

## Signup and checkout

`reach_signup` can inspect a signup screen without submitting an account. To submit a test signup, explicitly enable submission and supply a test identity you control:

```json
{
  "url": "https://your-product.example/signup",
  "goal": "complete_signup",
  "task": "Try creating a free test account if the product meets your needs. Use the supplied test identity.",
  "max_personas": 1,
  "allow_signup_submit": true,
  "test_data": {"email": "owned-test@example.com", "password": "REPLACE_WITH_TEST_ONLY_PASSWORD"},
  "checks": [{"name": "account_screen", "selector": "[data-testid=welcome]", "text": "Welcome"}],
  "goal_check": "account_screen"
}
```

Replace the example email with your own test inbox and keep the spec private. For multiple visitors use an owned email template such as `testing+{visitor}@your-domain.example`; each isolated session receives a different number. Identity input values are withheld from the model, masked in screenshots of inputs, and redacted from persisted text diagnostics. Test identities can still appear in site-rendered confirmation text and screenshots; use disposable test data, not customer credentials. Retained screenshots should be handled accordingly.

Supported supplied fields are `email`, `password`, `name`, `first_name`, `last_name`, and `search`. Free text entry is limited to search; other fields require a supplied data key. CAPTCHA solving, email/phone verification, external identity providers, payments, orders, and paid subscriptions are not supported. `reach_checkout` can prepare a cart and inspect checkout, but cannot complete a purchase.

## Agent tools, REST, and SDK

The MCP tool is `website_test` with `simulation_id`, `spec`, and optional `out`. Poll `job_status`; `results` can read the exported website run. The existing Codex/Claude/local-model gateway works through MarketMirror's model interface; no separate browser-model credential is required. The engine still needs a working provider and the browser extra.

REST: `POST /api/simulation/website-test` starts a task and returns `task_id` and `run_id`. Poll the normal market-task status route, then `GET /api/simulation/{simulation_id}/website-test?run_id=...` to retrieve that exact run. Omitting `run_id` retrieves the latest successful task result for that simulation.

```python
from marketmirror import MarketMirror

mm = MarketMirror("http://127.0.0.1:5001")
result = mm.website_test("sim_replace_me", {
    "url": "https://your-product.example",
    "goal": "reach_signup",
    "max_personas": 2,
    "checks": [{"name": "signup_form", "selector": "form[data-testid=signup]"}],
    "goal_check": "signup_form"
})
print(result["summary"], result["files"])
```

## Reports and interpretation

The result contains each visitor's screenshots, chosen actions, concise decision explanations, passing outcome checks, blocked requests, browser events, recoveries, timings, calls, and available token counts. The standalone HTML report includes milestone counts, expandable before/after evidence, and optional video recordings under 10 MB embedded for offline viewing. Larger videos remain separate artifacts listed in the JSON. Monetary invoice cost is unavailable unless separately measured. Explanations are model-generated rationales, not access to human thought processes.

An owned-fixture live gateway check used two synthetic visitors: one added the $50 shoes to the actual fixture cart and one declined because of a $10 budget. It used two model calls in 11.848 seconds. The [measured fixture record](../benchmarks/website_fixture_live.json) documents scope and limits; this is integration evidence, not human-behavior validation or an external storefront benchmark.

A separate [live browser-control check](../benchmarks/browser_control_fixture.json) completed catalog search, a product popup, tab switching, size selection, a checkbox, and an iframe cart. The server confirmed one cart write with Medium and blue laces. That run used seven model calls in 43.028 seconds and recorded the tabs; it is a controlled acceptance example, not a performance guarantee.

Every visitor starts with fresh cookies and storage. Navigation stays on the tested origin, service workers and WebSockets are blocked, and external subresources are read-only. Same-origin POST requests containing an explicit GraphQL query without a mutation are allowed for product discovery. Other writes are restricted to recognized cart endpoints or explicitly enabled signup endpoints. Persisted GraphQL operations, custom APIs, cross-origin checkout/auth or frames, bot defenses, and consent systems may require an adapter. A blocked journey is not evidence that humans would abandon. These controls cannot guarantee the semantics of arbitrary website endpoints; staging/test environments remain the appropriate place for write-enabled tests.

Private and reserved network URLs are rejected. For an owned localhost fixture, set `MARKET_MIRROR_ALLOW_LOCAL_WEBSITE_TESTS=1` **in the backend process**. This enables loopback only, not private LAN addresses; it is not a URL-level option available to model actions. Do not expose the self-hosted backend as a public website-testing service.

[Back to README](../README.md) · [Input formats](INPUT_FORMATS.md) · [API reference](API.md)

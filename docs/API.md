# MarketMirror API

The backend is a Flask app on `http://localhost:5001` (start it with `backend/claude_cli/start_server.sh`). Every response is
`{"success": true, "data": ...}` or `{"success": false, "error": "..."}`. Long jobs return a `task_id`; poll
`POST /api/simulation/market-task/status` until `status` is `completed` or `failed`, then `GET` the result. The upstream
engine routes (projects, ontology, graph build, simulations, start/stop, interviews, reports) are documented in
`docs/MIROFISH-UPSTREAM.md`; the `mirofish.py` CLI and the MCP server wrap all of them.

Authentication: none by default (the backend binds to localhost). Put it behind your own auth or network rules before exposing it.
Webhooks: set `MIROFISH_WEBHOOK_URL` (or `"webhook"` in `market_test.json`) and the CLI posts a JSON summary when a run, study
or test finishes. SDK: `pip install -e sdk` then `from marketmirror import MarketMirror`. Machine-readable: `docs/openapi.json`.


## Product understanding

### `POST /api/graph/profile`

Product profile from text/url/ads (no project).

Request body:

```json
{
  "text": "...",
  "url": "https://...",
  "ads_summary": {},
  "name": "Brand"
}
```

Returns: product profile + quickstart_answers

### `POST /api/graph/project/{project_id}/profile`

Create or reuse the project's product profile (seeds the market map before the graph build).

Request body:

```json
{
  "url": "https://...",
  "ads_summary": {},
  "refresh": false,
  "name": "Brand"
}
```

Returns: product profile

### `GET /api/graph/project/{project_id}/profile`

The project's product profile.

Returns: product profile

## Real voices

### `PUT /api/graph/project/{project_id}/voices`

Attach real voices (from research) to a project.

Request body:

```json
{
  "voices": [
    {
      "text": "...",
      "source": "appstore",
      "sentiment": "neg",
      "country": "in"
    }
  ]
}
```

Returns: {stored}

### `GET /api/graph/project/{project_id}/voices`

The project's voices.

Returns: {voices}

## Campaign planning

### `POST /api/graph/campaign-plan`

Save a draft evidence-led campaign plan and runnable test specs.

Request body:

```json
{
  "profile": {
    "name": "Brand"
  },
  "project_id": "",
  "goal": "trial signup",
  "budget": {
    "amount": 500,
    "currency": "USD"
  },
  "channels": [
    "search",
    "email"
  ],
  "research": {}
}
```

Returns: {plan, file}

## Tests on simulated people

### `POST /api/simulation/website-test`

Real-browser journeys by synthetic visitors with screenshots and supplied DOM outcome checks; background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "spec": {
    "url": "https://your-product.example",
    "goal": "add_to_cart",
    "max_personas": 3,
    "checks": [
      {
        "name": "cart_added",
        "selector": "[data-testid=cart-count]",
        "text": "1"
      }
    ],
    "goal_check": "cart_added",
    "observation_mode": "compact",
    "max_model_calls": 12,
    "max_input_tokens": 100000,
    "max_elapsed_s": 180
  }
}
```

Returns: {task_id, simulation_id, run_id}

### `GET /api/simulation/{simulation_id}/website-test`

Browser journey evidence; optional ?run_id=website_x selects the exact run.

Returns: website_test.json with sessions, summary, milestones and artifact paths

### `POST /api/simulation/feed-test`

Ads in realistic feeds (attention gate, split test, landing page, projections); background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "creatives": [
    {
      "id": "fb1",
      "platform": "facebook",
      "text": "..."
    }
  ],
  "landing": {},
  "benchmarks": {},
  "seeds": 3,
  "exposures": 2
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/feed-test`

Feed-test result.

Returns: feed_test.json

### `POST /api/simulation/email-test`

Email campaign test in simulated inboxes; background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "emails": [
    {
      "id": "a",
      "from_name": "Brand",
      "subject": "...",
      "body": "...",
      "send_time": "morning"
    }
  ],
  "list_size": 10000
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/email-test`

Email-test result.

Returns: email_test.json

### `POST /api/simulation/pitch`

Sales rehearsal: pitch every simulated buyer, then rebuttals; background task (needs a live environment).

Request body:

```json
{
  "simulation_id": "sim_x",
  "script": "...",
  "rebuttals": {
    "price": "...",
    "*": "..."
  },
  "channel": "dm"
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/pitch`

Pitch result.

Returns: pitch.json

### `POST /api/simulation/interview/batch`

Ask simulated people anything (the survey uses it); needs a live environment.

Request body:

```json
{
  "simulation_id": "sim_x",
  "interviews": [
    {
      "agent_id": 1,
      "prompt": "..."
    }
  ],
  "platform": "reddit"
}
```

Returns: {results:[{agent_id, response}]}

### `POST /api/simulation/ssr`

Free-text answers to 1-5 rating distributions (semantic similarity rating; engine embeddings, jev or auto).

Request body:

```json
{
  "items": [
    {
      "id": "1",
      "scale": "purchase",
      "text": "Maybe: if it is really free"
    }
  ],
  "engine": "embeddings"
}
```

Returns: {engine, method, model, counts, results:[{pmf, mean, sd}]}

### `POST /api/simulation/objection-check`

Jev labels survey objections; agreement with each person's own tag (Wilson 95% range). Needs a Jev key.

Request body:

```json
{
  "items": [
    {
      "id": "1",
      "text": "Not sure it is really free",
      "self_tag": "price"
    }
  ]
}
```

Returns: {agreement:{pct, lo, hi, k, n}, labelled, failed, model, usage}

## Inside the rounds

### `PUT /api/simulation/{simulation_id}/events`

Brand posts and scheduled launch events for the rounds.

Request body:

```json
{
  "posts": [
    {
      "agent": "Brand",
      "platform": "both",
      "content": "..."
    }
  ],
  "events": [
    {
      "round": 2,
      "agent": "Brand",
      "content": "..."
    }
  ]
}
```

Returns: {initial_posts, scheduled_events}

### `GET /api/simulation/{simulation_id}/events`

The configured posts and events.

Returns: {initial_posts, scheduled_events}

### `PUT /api/simulation/{simulation_id}/context`

Push live context into a running simulation (from the next round on).

Request body:

```json
{
  "text": "A competitor dropped its price",
  "source": "news",
  "round": 3
}
```

Returns: {context_updates, running}

### `GET /api/simulation/{simulation_id}/context`

Context updates on file.

Returns: {context_updates}

### `GET /api/simulation/{simulation_id}/feed-story`

Every post of the simulation with authors, rounds, likes, quotes, comments; brand posts strip.

Returns: feed_story.json

### `GET /api/simulation/{simulation_id}/memory`

Behaviour state across tests (?scope=, ?agent= for one person's memories).

Returns: {people, avg_trust, avg_familiarity, avg_fatigue, events}

### `POST /api/simulation/{simulation_id}/memory`

Record behaviour events (or survey answers) into a memory scope.

Request body:

```json
{
  "scope": "default",
  "events": [
    {
      "agent_id": 1,
      "test": "manual",
      "kind": "saw_brand_post",
      "text": "You saw the launch post."
    }
  ],
  "survey": {
    "responses": [],
    "offer": "..."
  }
}
```

Returns: {events_recorded, summary}

## Analysis and reports

### `POST /api/simulation/analyst-panel`

Independent anonymized analysts over the run's material; background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "material": {},
  "analysts": 5,
  "brief": "..."
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/analyst-panel`

Panel result.

Returns: analyst_panel.json

### `POST /api/simulation/market-report`

Plain-language report (one call, number-guarded); background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "material": {
    "summary": {}
  },
  "brand": "Brand"
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/market-report`

Report result (sections, action_plan, markdown).

Returns: market_report.json

### `POST /api/simulation/ideas`

Next test ideas from real ad rows and a run (synchronous).

Request body:

```json
{
  "brand": "Brand",
  "ads": [
    {
      "Ad name": "A",
      "Spend": 100,
      "Impressions": 10000,
      "Clicks": 120
    }
  ],
  "run_summary": {},
  "profile": {}
}
```

Returns: {ideas, evidence, markdown}

### `POST /api/simulation/captions`

Platform-native captions from a brief (synchronous).

Request body:

```json
{
  "brief": "...",
  "platform": "instagram",
  "n": 6,
  "objections": []
}
```

Returns: {captions}

### `POST /api/simulation/study-report`

One-call report over a study summary (number-guarded).

Request body:

```json
{
  "summary": {},
  "brand": "Brand"
}
```

Returns: {markdown, method}

## Reliability and prediction

### `POST /api/simulation/actuals-import`

Normalize a local ads/email/website/CRM/survey CSV or JSON export with provenance.

Request body:

```json
{
  "file": "/path/to/export.csv",
  "source_type": "ads",
  "mapping": {
    "clicks": "Link clicks"
  },
  "market": "PH"
}
```

Returns: {file, observations, validation_errors, summary}

### `POST /api/simulation/holdout-backtest`

Compare calibrated persona predictions with no-persona baseline on held-out real experiments.

Request body:

```json
{
  "pairs": [
    {
      "sim": 2.0,
      "real": 1.0,
      "split": "train"
    }
  ]
}
```

Returns: {status, persona_mae, no_persona_baseline_mae}

### `POST /api/simulation/calibrate`

Synthetic panel vs real answers: overlap, per-audience verdicts, AIPW-corrected rate (synchronous).

Request body:

```json
{
  "synthetic": [
    {
      "segment": "..",
      "country": "..",
      "gender": "..",
      "age": 30,
      "y": 1
    }
  ],
  "real": [],
  "key": "segment",
  "field": "would_convert"
}
```

Returns: {verdict, overlap, calibration, corrected}

### `POST /api/simulation/predict`

Predictions with intervals, scaled by the calibration store (synchronous).

Request body:

```json
{
  "brand": "Brand",
  "summary": {},
  "feed_test": {},
  "email_test": {},
  "targets": {
    "ctr": 2
  }
}
```

Returns: {predictions, calibrated}

### `POST /api/simulation/forecast`

30/60/90-day adoption forecast from the best ad and the rounds' word of mouth.

Request body:

```json
{
  "feed_test": {},
  "feed_story": {},
  "spend": 500,
  "days": 90
}
```

Returns: {curve, customers_total, cac, k_factor}

### `POST /api/simulation/calibration-pairs`

Store real-vs-simulated pairs (backtest, calibrate, your own stats).

Request body:

```json
{
  "brand": "Brand",
  "metric": "ctr",
  "pairs": [
    {
      "sim": 4.0,
      "real": 2.1,
      "label": "ad A"
    }
  ],
  "source": "backtest"
}
```

Returns: {stored}

### `GET /api/simulation/calibration-pairs`

Fits per metric (?brand=).

Returns: {pairs, brands, fits}

## Background tasks

### `POST /api/simulation/market-task/status`

Status of a background task.

Request body:

```json
{
  "task_id": "..."
}
```

Returns: {status, progress, message, result}

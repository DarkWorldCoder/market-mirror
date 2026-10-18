# Contributing to MarketMirror

Thanks for helping. MarketMirror is a marketing and sales simulation tool built on the MiroFish engine (AGPL-3.0).

## Set up

```bash
git clone https://github.com/DarkWorldCoder/market-mirror && cd market-mirror
cp .env.example .env                 # LLM_API_KEY=... (or the no-key gateway, see README)
cd backend && uv sync --python 3.12 && cd ..
bash backend/claude_cli/start_server.sh
cd backend && uv run --no-sync python -m pytest tests claude_cli/tests -q
```

Tests mock the model and the embedder; they need no key. A real run (`mirofish.py quickstart`) does.

## Where things live

| Area | Path |
|---|---|
| Services (personas, feed test, email test, pitch, report, ideas, research, calibration, predict) | `backend/app/services/` |
| REST API | `backend/app/api/market.py`, `product.py`, `feed.py`; registry in `registry.py` (run `backend/scripts/gen_api_docs.py` after changing routes) |
| Inside the rounds (persona cards, events, context) | `backend/scripts/agent_context.py`, `event_schedule.py` |
| CLI and dashboard | `backend/claude_cli/` (`mirofish.py`, `market_cli.py`, `experiments.py`, `study.py`, `quickstart.py`, `exporter.py`, `marketing.py`, `feed_view.py`, `social_feed.py`, `report_view.py`, `tokens.py`, `ui.py`) |
| Claude skill, MCP server, helper | `plugin/skills/market-mirror/` |
| Python SDK | `sdk/` |
| Docs and screenshots | `docs/`, `docs/make_shots.py` |

## Rules of the road

- Keep the dashboard one offline HTML file (stdlib Python, inline CSS/JS, vendored ECharts only).
- Every number the model writes in a report must come from the fact sheet (the number guard enforces it); never invent benchmarks.
- Simulated people are not real people: labels, margins and "direction, not measurement" wording stay.
- New endpoints go into `backend/app/api/registry.py`; new CLI commands get a parser entry, a `COMMANDS` entry, an MCP tool when agents should use them, a README row and a test.
- Commit messages: plain English, present tense. No secrets, no `backend/uploads/`, no `mirofish_runs/`, no `scenarios/` (all gitignored).

## Pull requests

Open an issue first for anything larger than a fix. A PR needs green tests, updated docs for user-visible changes, and screenshots for dashboard changes (regenerate with `docs/make_shots.py`).

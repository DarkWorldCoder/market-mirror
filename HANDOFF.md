# HANDOFF: MarketMirror (read this first)

This handoff is for the next Claude Code session. Read this file, then `CLAUDE.md` (operating guide) and `plugin/skills/market-mirror/SKILL.md` (recipes).

## What this repo is
MarketMirror tests marketing and sales decisions on simulated buyers. It is a fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish) (AGPL-3.0) with:

1. **Claude as the LLM** through Anthropic's OpenAI-compatible endpoint (`backend/app/config.py`, `backend/app/utils/openai_chat_compat.py`).
2. **Free local memory** instead of Zep Cloud (`backend/app/utils/local_graph.py`, `embeddings.py`; optional Cognee sidecar).
3. **Persona planner** (`backend/app/services/persona_planner.py`): segments, balanced diversity traits, contradictions, communities, follow graph, and a filter that drops non-actor graph entities.
4. **Feed test** (`backend/app/services/feed_test.py`): platform feeds with attention gating, habits, stated probabilities, damped social proof, wear-out, landing page, projections, ROI economics.
5. **Analyst panel** (`backend/app/services/analyst_panel.py`) and **API** (`backend/app/api/market.py`).
6. **CLI** (`backend/claude_cli/mirofish.py`, `market_cli.py`): run, survey, feedtest, panel, ads-import, backtest, live, export.
7. **Dashboard** (`backend/claude_cli/exporter.py`, `marketing.py`, `feed_view.py`, vendored ECharts): one offline HTML file plus CSV/JSON/MD downloads.
8. **Claude skill / plugin** (`plugin/`, `.claude-plugin/marketplace.json`).

Your own inputs go in `scenarios/<name>/` (gitignored). Runs go to `mirofish_runs/` (gitignored).

## Verified with real Claude (claude-haiku-4-5)
- [x] Ontology, graph build (local memory), persona planning with communities, agent preparation.
- [x] Feed test end to end, including landing page drop-off.
- [x] OASIS rounds start and run; community follows are seeded on both platforms.
- [ ] Survey and analyst panel on a real run: check the latest run folder; if `survey.json` exists they worked.
- [ ] Report generation (ReportAgent) on real Claude.

## Known gaps / next steps
- Survey ratings are asked directly. Research (arXiv 2510.08338) shows free text mapped to anchor statements by embedding similarity matches humans far better; implement with the local fastembed model.
- No multi-seed runs yet: run the same test with several seeds and report the spread.
- Pricing (Van Westendorp) answers from LLMs are low-confidence without real price data.
- The upstream Vue frontend is not updated for MarketMirror (the dashboard replaces it). Upstream bug: `frontend/src/api/report.js` calls `getReportStatus` with GET, the route is POST-only.
- Local memory: no temporal invalidation of old facts; multilingual embedding truncates at 128 tokens.

## First run
```bash
cp .env.example .env    # LLM_API_KEY=<Anthropic key>
cd backend && uv sync --python 3.12 && cd ..
bash backend/claude_cli/start_server.sh
alias mm="backend/.venv/bin/python backend/claude_cli/mirofish.py"
mm run --seed scenarios/x/brief.md --requirement @scenarios/x/question.txt --personas scenarios/x/personas.json \
       --stop-after prepare --out mirofish_runs/x --title "X market test"
mm feedtest --simulation <id> --creatives @scenarios/x/creatives.json --run-dir mirofish_runs/x
mm live      # http://127.0.0.1:5050/
```

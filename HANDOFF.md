# HANDOFF: MiroFish Claude Edition (read this first)

This handoff is for the next Claude Code session. Read this file, then `CLAUDE.md`, which has the full operating guide.

## What this repo is
This is a fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish) (AGPL-3.0), a swarm-intelligence simulation engine: AI personas react to seed documents on a simulated Twitter/Reddit, and the run ends in a prediction report. It is a generic base: no client or campaign data lives in the repo. Branch `main` adds:

1. **Claude as the LLM.** `LLM_PROVIDER=claude` is the default and uses Anthropic's OpenAI-compatible endpoint `https://api.anthropic.com/v1/`.
   - Files: `backend/app/config.py` and `backend/app/utils/openai_chat_compat.py`. These drop `response_format` (JSON is requested in the prompt instead) and set a default `max_tokens`.
   - OASIS agents use camel `OPENAI_COMPATIBLE_MODEL`, set up in `backend/scripts/run_*_simulation.py`.
2. **Free memory instead of Zep Cloud.** `MEMORY_BACKEND=local` is the default.
   - `backend/app/utils/local_graph.py`: an SQLite drop-in for the Zep SDK. It does entity/relation extraction with Claude, plus hybrid search: BM25 combined with multilingual fastembed embeddings, computed locally for free (`backend/app/utils/embeddings.py`).
   - `MEMORY_BACKEND=cognee`: Cognee runs as a separate service (`backend/memory_sidecar/`) because its dependencies conflict with camel-ai's.
   - `MEMORY_BACKEND=zep`: the original Zep Cloud behaviour.
3. **Claude-controllable CLI.** `backend/claude_cli/mirofish.py` runs the full pipeline headless.
   - `export` writes a self-contained `dashboard.html` (knowledge graph, personas, per-round charts, report) that can be published as a claude.ai Artifact.
   - `live` serves that dashboard on `http://127.0.0.1:5050/` and refreshes it while a run progresses, so the Claude desktop app's browser pane can show it (`.claude/launch.json` entry `mirofish-live`).
4. **Tests.** Run `cd backend && uv run --no-sync python -m pytest tests claude_cli/tests -q`. They use a mocked LLM.

## Where your own inputs go
Put private scenario inputs (seed documents, the prediction question, ad copy, earlier results) in `scenarios/<name>/`. That folder is gitignored, so client data stays on your machine. Run outputs go to `mirofish_runs/`, which is also gitignored.

## Status / what is NOT done yet
- [x] **Runs against a real Claude key.** The ontology step works with `claude-haiku-4-5` through the OpenAI-compatible endpoint.
- [ ] **Full run not yet verified end to end.** Graph build, agent preparation, simulation rounds and the report still need a complete real run. Expect fixes in `openai_chat_compat.py` or the camel model setup (tool-calling parameters, unsupported request fields).
- [ ] The first graph build downloads the ~220 MB embedding model into `backend/uploads/models`; it can take several minutes.
- [ ] Simulation activity written back into the graph by the local backend (`start` default) is untested with a real LLM; the CLI flag `--no-graph-memory` turns it off.
- [ ] Known upstream frontend bug: `frontend/src/api/report.js` calls `getReportStatus` with GET, but the backend route is POST-only.
- [ ] Local memory limits:
  - no temporal invalidation of old facts
  - the multilingual embedding model truncates at 128 tokens
  - the Cognee path doesn't extract ontology attributes

## First run
```bash
cp .env.example .env    # set LLM_API_KEY=<Anthropic key>; keep LLM_PROVIDER=claude, MEMORY_BACKEND=local
cd backend && uv sync --python 3.12 && cd ..
bash backend/claude_cli/start_server.sh
backend/.venv/bin/python backend/claude_cli/mirofish.py run \
  --seed scenarios/<name>/seed.md \
  --requirement @scenarios/<name>/requirement.txt \
  --platform parallel --max-rounds 10 --stop-after prepare --out mirofish_runs/<name>
backend/.venv/bin/python backend/claude_cli/mirofish.py live   # watch it at http://127.0.0.1:5050/
```
Check the agents after `--stop-after prepare`, then run the rounds with `start --simulation <id> --max-rounds 10`.

## Repo map (new or changed)
- `CLAUDE.md`: operating guide (setup, CLI, live view, export and publish, memory backends, costs)
- `HANDOFF.md`: this file
- `.claude/launch.json`: browser-pane launch entry for the live dashboard
- `backend/claude_cli/`: `mirofish.py` (CLI), `exporter.py` (dashboard), `start_server.sh`, `stop_server.sh`, `tests/`
- `backend/app/utils/local_graph.py`, `embeddings.py`, `cognee_graph.py`: memory backends
- `backend/memory_sidecar/`: Cognee sidecar (`cognee_sidecar.sh setup|start|stop|status`)
- `.env.example`: all settings, with English comments

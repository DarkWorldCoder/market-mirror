# MarketMirror (MiroFish engine) — operating guide for Claude

MarketMirror adds marketing and sales testing on top of the MiroFish engine: persona planning, feed tests, buyer surveys, pricing, ROI projections, past-ads import, backtests and an analyst panel (section 3b). The installable skill is `plugin/skills/market-mirror/SKILL.md` and holds the recipes.

MiroFish is a swarm-simulation engine. You give it seed documents plus a prediction question. It builds a knowledge graph, turns entities into LLM agents, simulates them on a Twitter-like and a Reddit-like platform, and then writes a prediction report. This edition runs headless, so you never need the Vue UI: drive the Flask backend (port 5001) with `backend/claude_cli/mirofish.py` and show the user the self-contained HTML dashboard it exports.

## 1. Setup (once)

```bash
cp .env.example .env        # if .env does not exist yet
```

Set these in `MiroFish/.env` (it is loaded by `backend/app/config.py`):

```
LLM_PROVIDER=claude          # Anthropic OpenAI-compatible endpoint (default)
LLM_API_KEY=<Anthropic API key>   # or export ANTHROPIC_API_KEY
LLM_MODEL_NAME=claude-haiku-4-5   # cheap and fast; use a Sonnet model for better reports
MEMORY_BACKEND=local         # local SQLite graph + local embeddings, so no Zep key is needed
```

Install the Python deps with `cd backend && uv sync` (this includes `fastembed`; the ~220 MB multilingual embedding model is downloaded on first use into `backend/uploads/models`). See section 6 for the memory backends. The CLI itself needs only the stdlib and `requests`. Offline `export --run-dir` needs only the stdlib.

## 2. Start / stop the backend

```bash
backend/claude_cli/start_server.sh     # background start, waits for /health, prints JSON
backend/claude_cli/stop_server.sh      # stops it, including simulation subprocesses
```

The log is written to `backend/logs/server.out`. The CLI reads `MIROFISH_URL` (default `http://localhost:5001`) or takes `--base-url`.

## 3. Run a simulation end to end

```bash
C="python backend/claude_cli/mirofish.py"   # from the repo root; or: cd backend && uv run --no-sync python claude_cli/mirofish.py
$C health
$C run --seed brief.md data.pdf \
       --requirement "If X happens, how will the public react over the next 3 days?" \
       --platform parallel --max-rounds 5 --out mirofish_runs/x_test
```

`run` performs these steps: upload, ontology, graph build, create simulation, prepare (profiles and config), start (polls until the run is `completed`), report, collect, and export. Progress lines go to **stderr**, and the final JSON (ids and paths) goes to **stdout**. Every intermediate file is saved in `--out`: `ontology.json`, `project.json`, `graph.json`, `simulation.json`, `config.json`, `profiles_*.json`, `run_status.json`, `timeline.json`, `actions.json`, `posts_*.json`, `comments_*.json`, `report.json`, `run_manifest.json`, `dashboard.html`, `report.md` and `summary.json`. If a step fails, the CLI exports whatever exists, records `run_manifest.json.error` and exits 1.

`--requirement @file.txt` reads the question from a file. Use `--stop-after prepare` to check the agents before spending money on rounds.

### Individual steps (all print JSON)

| Step | Command |
|---|---|
| upload + ontology | `$C upload --seed a.md --requirement "..." [--name N]` gives `project_id` |
| graph build | `$C build-graph --project proj_x` (waits), gives `graph_id` |
| simulation | `$C create-sim --project proj_x --platform parallel` gives `simulation_id` |
| agents/config | `$C prepare --simulation sim_x [--entity-types Student Media]` |
| run | `$C start --simulation sim_x --max-rounds 5` (waits; `--no-wait` + `$C wait`) |
| status | `$C status --simulation sim_x` / `--project proj_x` / `--task task_x` |
| report | `$C report --simulation sim_x [--force] [--out report.md]` |
| ask ReportAgent | `$C chat --simulation sim_x --message "Why did sentiment flip?" [--history chat.json]` |
| interview agents | `$C profiles --simulation sim_x --brief`, then `$C interview --simulation sim_x --agent 3 --prompt "..."` (or `--agent 1 2 5`, or `--all`) |
| housekeeping | `$C list [projects|simulations|reports]`, `$C stop`, `$C close-env --simulation sim_x` |

Interviews work only while the simulation environment is still alive (`status` shows `env.env_alive`). It stays alive after a run finishes until `close-env`, `stop` or a server restart.

## 3b. MarketMirror commands

| Goal | Command |
|---|---|
| concrete personas + communities | `$C run ... --personas scenarios/x/personas.json` (or `--auto-personas 30`), `--stop-after prepare` first |
| ads in realistic feeds | `$C feedtest --simulation sim_x --creatives @scenarios/x/creatives.json [--exposures 2] [--seeds 3] [--landing @..] [--benchmarks @past_ads.json]` |
| buyer survey / split test / price | `$C survey --simulation sim_x --offer ".." --goal ".." --messages @msgs.txt --split --pricing USD` (needs a started simulation; free-text answers are mapped to 1-5 distributions by `POST /api/simulation/ssr`, `--no-ssr` to skip) |
| analyst panel | `$C panel --simulation sim_x --analysts 5 --brief ".."` |
| past ads to seed + benchmarks | `$C ads-import export.csv --out scenarios/x/past_ads.md` |
| backtest vs real ads | `$C backtest --run-dir mirofish_runs/x --actuals scenarios/x/past_ads.json` |

Results land in the run folder (`feed_test.json`, `survey.json`, `analyst_panel.json`, `backtest.json`) and in the dashboard, which also writes CSV/JSON/Markdown downloads next to `dashboard.html`. API: `backend/app/api/market.py`. Persona spec, creatives and benchmark formats are documented in `README.md` and the skill. Report simulated numbers as directions with their margins, never as measurements: the feed-test range across `--seeds` and the survey's SSR mean ± spread.

## 4. Export and show the dashboard

```bash
$C export --simulation sim_x --out mirofish_runs/x/dashboard.html   # fetches everything from the API
$C export --run-dir mirofish_runs/x                                  # offline re-render from saved JSON
```

The output is one HTML file with inline CSS, inline SVG and no external requests. It contains the knowledge graph (layout computed in Python, colored by entity type, relation labels toggleable), the persona table (stance, sentiment, activity), the actions-per-round chart, the action mix and most active agents, top posts and comments, and the rendered report. It adapts to light and dark mode and to phone width. **Publish `dashboard.html` with the Artifact tool**, or send it as a file, so the user can view it. `report.md` and `summary.json` (key numbers) are written next to it. Use `summary.json` for your own written summary.

### Live view (watch a run while it happens)

```bash
$C live                                   # follows the newest run under mirofish_runs/
$C live --run-dir mirofish_runs/x         # or a specific run; --simulation sim_x also works
```

`live` serves the same dashboard at `http://127.0.0.1:5050/` (`--port` or `MIROFISH_LIVE_PORT` to change it). Every `--interval` seconds (default 10) it re-collects the run from the backend and re-renders the page; the open page reloads itself only when something changed, keeps its scroll position, and shows the current stage in a corner badge (graph build, preparing agents, round N/M, report, done). In the Claude desktop app, open it in the browser pane with `preview_start` and the `.claude/launch.json` entry `market-mirror-live`. `--offline` re-renders saved JSON without calling the backend.

### Scenario inputs

Keep private inputs (seed documents, questions, campaign data) in `scenarios/<name>/`, which is gitignored. The repo itself stays a generic base.

## 5. Cost tips

- Start small: `--max-rounds 3-5`, one platform (`--platform reddit`), and a short seed document.
- Agent count equals the number of graph entities. Use `--entity-types` (on `run` or `prepare`) to limit which types become agents.
- `claude-haiku-4-5` is fine for exploration. Switch `LLM_MODEL_NAME` only for the final run.
- Reports are cached per simulation, so `report` reuses the existing one unless you pass `--force`.
- `--no-graph-memory` skips writing agent activity back into the graph. With `MEMORY_BACKEND=local` or `cognee` that write is cheap anyway, because activity is stored and searchable without LLM extraction unless `MEMORY_EXTRACT_ACTIVITY=true`.
- The local backend makes one Claude call per unique chunk. Re-building a graph from the same document with the same ontology and model reuses the cached extractions for free.

## 6. Memory backends (knowledge graph)

All three backends expose the same `zep_cloud`-shaped client (`get_zep_client()` in `backend/app/utils/zep.py`), so graph building, entity reading, ReportAgent tools and simulation memory work the same on each.

- **`local` (default)**: `backend/app/utils/local_graph.py`, a SQLite file at `backend/uploads/local_graph.db`. The configured LLM (Claude) extracts entities and relationships per chunk with a compact prompt, 4 workers in parallel. Identical chunks reuse a cached extraction, and chunks are capped at `LOCAL_GRAPH_MAX_EPISODE_CHARS`. Search is **hybrid**: BM25 fused with cosine similarity over local `fastembed` embeddings (reciprocal rank fusion). The default model is `paraphrase-multilingual-MiniLM-L12-v2` (multilingual, 384 dims, CPU only), and vectors are cached in the same SQLite file. Entity resolution merges exact names, declared aliases, safe variants (`Acme Inc.` = `Acme`, `WHO` = `World Health Organization`, an unambiguous `Alice` = `Alice Smith`) and same-type names with embedding cosine >= `MEMORY_ENTITY_SIMILARITY` (0.9). If fastembed or the model is unavailable, search falls back to BM25 with no error. Set `MEMORY_EMBEDDINGS=false` to skip embeddings entirely.
- **`cognee` (optional)**: `backend/app/utils/cognee_graph.py` plus a sidecar. Cognee cannot share `backend/.venv`: every Cognee release needs `tiktoken>=0.8` and `openai>=2`, while `camel-ai==0.2.78` (required by `camel-oasis`) pins `tiktoken<0.8` and `openai<2`. So Cognee runs in `backend/memory_sidecar/.venv` (about 1.3 GB) behind a small localhost JSON API:
  ```bash
  backend/memory_sidecar/cognee_sidecar.sh setup    # once
  backend/memory_sidecar/cognee_sidecar.sh start    # before start_server.sh; also: status | stop
  # .env: MEMORY_BACKEND=cognee
  ```
  Cognee uses the same Claude key and model (its `anthropic` provider), fastembed embeddings and local stores (SQLite, LanceDB, Ladybug/Kuzu) under `backend/uploads/cognee`. The ontology is passed as Cognee's `custom_prompt`. After each `cognify` run, the Cognee graph is read back and mirrored as `EntityNode`/`EntityEdge` rows. Search fuses Cognee's vector hits with the local hybrid ranking, and falls back to the local ranking if the sidecar is down.
- **`zep` (legacy)**: hosted Zep Cloud, requires `ZEP_API_KEY`.

| Option | License / cost | Runs where | Fit for MiroFish | Decision |
|---|---|---|---|---|
| **local hybrid** (this repo) | AGPL (repo), free | in-process SQLite + ONNX | Typed ontology, episodes/batches and the Zep shapes the services expect; one Claude call per unique chunk | **Default** |
| **Cognee** | Apache-2.0, free | sidecar venv, local stores | Mature extraction/cognify pipeline and vector retrieval; dependency conflict with camel-ai | **Optional** (`cognee`) |
| **Zep Cloud** | hosted, paid tiers | SaaS | Original upstream backend | **Legacy** (`zep`) |
| Graphiti (Zep OSS) | Apache-2.0 | needs a graph DB (Neo4j/FalkorDB/Kuzu) + embedding provider | Strong temporal graph, but several LLM calls per episode and extra infrastructure | Not used |
| Mem0 | Apache-2.0 | vector store (+ optional graph) | Built for user/agent conversational memory, not ontology-typed document graphs | Not used |
| LightRAG | MIT | file/DB storage + embedding function | Good graph-RAG question answering, but no episode/batch model or typed ontology contract | Not used |

Choice: the local backend keeps the "no extra service, no extra key" path and the exact Zep data model, so it is the default. Cognee is the drop-in upgrade for richer extraction when you can run a second process. Every backend uses Claude for extraction, and embeddings are always local and free (Anthropic has no embeddings API).

## 7. Code map / rules

- `backend/app/api/{graph,simulation,report}.py` contains the REST endpoints, and `backend/app/services/` the logic (graph builder, OASIS runner, ReportAgent). Runtime data is under `backend/uploads/` (projects, simulations, reports).
- Memory: `backend/app/utils/{local_graph,embeddings,cognee_graph,zep}.py` and `backend/memory_sidecar/` (Cognee sidecar). Backend tests: `cd backend && uv run --no-sync python -m pytest tests claude_cli/tests -q`.
- `backend/claude_cli/` holds the CLI (`mirofish.py`), the dashboard exporter (`exporter.py`, stdlib only), the server scripts and the tests (`python -m unittest discover -s backend/claude_cli/tests`).
- Never commit `.env` or anything under `backend/uploads/` or `mirofish_runs/`.

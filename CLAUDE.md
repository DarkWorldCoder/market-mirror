# MiroFish — operating guide for Claude

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
MEMORY_BACKEND=local         # local SQLite graph, so no Zep key is needed
```

Install the Python deps with `cd backend && uv sync`. The CLI itself needs only the stdlib and `requests`. Offline `export --run-dir` needs only the stdlib.

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

## 4. Export and show the dashboard

```bash
$C export --simulation sim_x --out mirofish_runs/x/dashboard.html   # fetches everything from the API
$C export --run-dir mirofish_runs/x                                  # offline re-render from saved JSON
```

The output is one HTML file with inline CSS, inline SVG and no external requests. It contains the knowledge graph (layout computed in Python, colored by entity type, relation labels toggleable), the persona table (stance, sentiment, activity), the actions-per-round chart, the action mix and most active agents, top posts and comments, and the rendered report. It adapts to light and dark mode and to phone width. **Publish `dashboard.html` with the Artifact tool**, or send it as a file, so the user can view it. `report.md` and `summary.json` (key numbers) are written next to it. Use `summary.json` for your own written summary.

## 5. Cost tips

- Start small: `--max-rounds 3-5`, one platform (`--platform reddit`), and a short seed document.
- Agent count equals the number of graph entities. Use `--entity-types` (on `run` or `prepare`) to limit which types become agents.
- `claude-haiku-4-5` is fine for exploration. Switch `LLM_MODEL_NAME` only for the final run.
- Reports are cached per simulation, so `report` reuses the existing one unless you pass `--force`.
- `--no-graph-memory` skips writing agent activity back into the graph. With `MEMORY_BACKEND=local` that write is cheap anyway.

## 6. Code map / rules

- `backend/app/api/{graph,simulation,report}.py` contains the REST endpoints, and `backend/app/services/` the logic (graph builder, OASIS runner, ReportAgent). Runtime data is under `backend/uploads/` (projects, simulations, reports).
- `backend/claude_cli/` holds the CLI (`mirofish.py`), the dashboard exporter (`exporter.py`, stdlib only), the server scripts and the tests (`python -m unittest discover -s backend/claude_cli/tests`).
- Never commit `.env` or anything under `backend/uploads/` or `mirofish_runs/`.

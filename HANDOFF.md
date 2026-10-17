# HANDOFF: MiroFish Claude Edition (read this first)

This handoff is for the next Claude Code session. Read this file, then `CLAUDE.md`, which has the full operating guide.

## What this repo is
This is a fork of [666ghj/MiroFish](https://github.com/666ghj/MiroFish) (AGPL-3.0), a swarm-intelligence simulation engine: AI personas react to seed documents on a simulated Twitter/Reddit, and the run ends in a prediction report. Branch `claude-edition` adds:

1. **Claude as the LLM.** `LLM_PROVIDER=claude` is the default and uses Anthropic's OpenAI-compatible endpoint `https://api.anthropic.com/v1/`.
   - Files: `backend/app/config.py` and `backend/app/utils/openai_chat_compat.py`. These drop `response_format` (JSON is requested in the prompt instead) and set a default `max_tokens`.
   - OASIS agents use camel `OPENAI_COMPATIBLE_MODEL`, set up in `backend/scripts/run_*_simulation.py`.
2. **Free memory instead of Zep Cloud.** `MEMORY_BACKEND=local` is the default.
   - `backend/app/utils/local_graph.py`: an SQLite drop-in for the Zep SDK. It does entity/relation extraction with Claude, plus hybrid search: BM25 combined with multilingual fastembed embeddings, computed locally for free (`backend/app/utils/embeddings.py`).
   - `MEMORY_BACKEND=cognee`: Cognee runs as a separate service (`backend/memory_sidecar/`) because its dependencies conflict with camel-ai's.
   - `MEMORY_BACKEND=zep`: the original Zep Cloud behaviour.
3. **Claude-controllable CLI.** `backend/claude_cli/mirofish.py` runs the full pipeline headless. `export` writes a self-contained `dashboard.html` (knowledge graph, personas, per-round charts, report) that can be published as a claude.ai Artifact.
4. **Tests.** 178 pass (`cd backend && uv run python -m pytest tests claude_cli/tests -q`). They run with a mocked LLM.

## Status / what is NOT done yet
- [ ] **Never run end to end with a real Claude key.** The first real run will probably surface issues in Anthropic's OpenAI-compatible layer, such as tool-calling parameters sent by camel/OASIS or unsupported request fields. Fix them in `openai_chat_compat.py` or the camel model setup.
- [ ] **Verify the default model name.** Use `curl https://api.anthropic.com/v1/models -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01"`, then set `LLM_MODEL_NAME`. Prefer a cheap Haiku-class model for agents.
- [x] **Pushed to `DarkWorldCoder/mirofish-claude`** (`main`, full upstream history included).
- [ ] Simulation activity written back into the graph by the local backend (`start` default) is untested with a real LLM; the CLI flag `--no-graph-memory` turns it off.
- [ ] Known upstream frontend bug: `frontend/src/api/report.js` calls `getReportStatus` with GET, but the backend route is POST-only.
- [ ] Local memory limits:
  - no temporal invalidation of old facts
  - the multilingual embedding model truncates at 128 tokens
  - the Cognee path doesn't extract ontology attributes

## First thing to do (the user's actual goal)
Run the **CSCA.ai ad simulation** with real MiroFish and show the dashboard.

```bash
cp .env.example .env    # set LLM_API_KEY=<Anthropic key>; keep LLM_PROVIDER=claude, MEMORY_BACKEND=local
cd backend && uv sync && cd ..
bash backend/claude_cli/start_server.sh
python backend/claude_cli/mirofish.py run \
  --seed examples/csca/csca_mirofish_seed.md examples/csca/csca_new_ads.md \
  --requirement @examples/csca/requirement.txt \
  --platform parallel --max-rounds 10 --out mirofish_runs/csca
# then publish mirofish_runs/csca/dashboard.html as an Artifact and summarise the findings
```
Start small: around 10 rounds. Compare the results with `examples/csca/csca_ad_simulation_report.md`, an earlier panel run by Claude without the MiroFish engine, and report where the two agree and disagree.

## Business context (CSCA.ai)
- **Product:** csca.ai is WiseAdmit's exam-prep platform for the CSCA (China Scholastic Competency Assessment).
  - 2,400+ Maths/Physics/Chemistry questions
  - 30 timed mock tests
  - free practice
  - Not affiliated with the official exam.
- **Owner:** Ayush Niroula (ayush@wiseadmit.io), Full Stack Engineer at WiseAdmit, Asia/Kathmandu.
- **Meta ad account "CSCA AI New"** (id 826794296689424), lifetime: $56 spent, 3,791 link clicks, 1,500 landing page views, 16 registrations (about $3.50 per registration). All ads are paused.
  - The campaign optimised for landing page views, not registrations.
  - Only 40% of clicks loaded the page.
  - Instagram CTR was 2.6% vs Facebook 1.4%.
  - Nepal and Bangladesh were the cheapest markets; Indonesia had the highest CTR.
- **Ad copy:** the new ads are in `examples/csca/csca_new_ads.md` (10 concepts).
- **Earlier panel's winners:**
  - Nepal: #8 (Reel)
  - Bangladesh: #1 (score check)
  - Indonesia: #10 (Bahasa headline)
  - Overall: retargeting (#7) got the most sign-ups.
- **Earlier panel's main blockers:**
  - scam/fee fears
  - the phone-number field
  - a slow, English-only landing page
  - unanswered comments

## Repo map (new or changed)
- `CLAUDE.md`: operating guide (setup, CLI, export and publish, memory backends, costs)
- `HANDOFF.md`: this file
- `backend/claude_cli/`: `mirofish.py` (CLI), `exporter.py` (dashboard), `start_server.sh`, `stop_server.sh`, `tests/`
- `backend/app/utils/local_graph.py`, `embeddings.py`, `cognee_graph.py`: memory backends
- `backend/memory_sidecar/`: Cognee sidecar (`cognee_sidecar.sh setup|start|stop|status`)
- `examples/csca/`: seed document, ad copy, requirement, earlier panel report
- `.env.example`: all settings, with English comments

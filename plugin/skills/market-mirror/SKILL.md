---
name: mirofish
description: Run MiroFish swarm simulations. Turn any documents (briefs, ad copy, product pages, news, policies, PDFs) plus a question into a crowd of AI personas who react on a simulated Twitter and Reddit, then get a prediction report and a live dashboard. Use when the user wants to simulate how an audience, market, customers, voters or the public would react; test ads, messages, launches or announcements on personas; run a focus group or swarm prediction; or mentions MiroFish. Downloads and sets up the engine on first use. Needs a shell and an Anthropic API key.
---

# MiroFish swarm simulation

MiroFish reads seed documents, builds a knowledge graph, turns the people and groups in it into LLM agents, lets them post, comment and react over several rounds, and writes a prediction report. Everything runs locally against the user's own Anthropic key.

All commands go through the helper script next to this file:

```bash
MF="<this skill's folder>/scripts/mf.sh"   # e.g. ~/.claude/skills/mirofish/scripts/mf.sh
bash "$MF" help
```

The engine lives in `~/.mirofish/mirofish-gtm` unless `MIROFISH_HOME` says otherwise. `bash "$MF" home` prints it.

## 1. Set up (first time, then just `doctor`)

1. Run `bash "$MF" setup`. It clones the engine, installs Python 3.12 dependencies with `uv`, and creates `.env`. If `uv` is missing, tell the user the install options it prints and wait.
2. Run `bash "$MF" doctor`. If it says the key is missing, ask the user to open `<home>/.env` and replace `your_api_key_here` on the `LLM_API_KEY` line, or to export `ANTHROPIC_API_KEY`. Recommend a new key with a spending limit.
   - Never print, echo, cat or grep the key, and never put it in a command line. If the user pastes a key in chat, write it into `.env` with a file edit and do not repeat it.
3. Run `bash "$MF" start` to start the backend. It must say `started`.

The default model is `claude-haiku-4-5` (cheap). For a final, higher-quality report the user can set `LLM_MODEL_NAME` to a Sonnet model in `.env`, then restart with `stop` and `start`.

## 2. Prepare the scenario

1. Collect the user's material: files they name, documents in the conversation, or pages they ask you to fetch. Supported seed formats are `.md`, `.txt` and `.pdf`. Save anything that only exists in chat as a Markdown file first.
2. Copy it into a scenario folder: `bash "$MF" scenario <name> file1.md file2.pdf`. It prints the folder.
3. Write the prediction question to `<folder>/requirement.txt`. A good question names:
   - who should be simulated, with concrete personas (country, age, role, what they care about)
   - what they see or experience
   - what to predict, as a short numbered list
   - "Keep the simulation under N rounds."
   Ground personas in any real data the user has (results, survey answers, past campaigns) and put that data in a seed file too.

Scenario folders are gitignored inside the engine, so client data never ends up in the repo.

## 3. Run in two stages (protects the user's money)

Use absolute paths for seeds. Run long commands in the background.

```bash
bash "$MF" cli run --seed <folder>/a.md <folder>/b.pdf \
  --requirement @<folder>/requirement.txt \
  --platform parallel --max-rounds 10 --stop-after prepare --out mirofish_runs/<name>
```

This builds the graph and creates the agents, then stops before the paid rounds. The first graph build also downloads a ~220 MB embedding model, which can take several minutes.

Then show the user the agents and ask before spending more:

```bash
bash "$MF" cli profiles --simulation <simulation_id> --brief
```

`simulation_id` is in `<home>/mirofish_runs/<name>/run_manifest.json`. If the personas are wrong, fix the seed or question and rerun stage one. Use `--entity-types` to keep only useful agent types and lower the cost.

Once the user agrees:

```bash
bash "$MF" cli start --simulation <simulation_id> --max-rounds 10
bash "$MF" cli report --simulation <simulation_id>
bash "$MF" cli export --simulation <simulation_id> --out mirofish_runs/<name>/dashboard.html
```

## 4. Show the results

- **Live while it runs:** start `bash "$MF" live` in the background. It follows the newest run and serves a self-refreshing dashboard at `http://127.0.0.1:5050/`. In the Claude desktop app, open that URL in the browser pane. Elsewhere, give the user the link.
- **Final dashboard:** `<home>/mirofish_runs/<name>/dashboard.html` is one self-contained file. Publish it as an Artifact if that tool exists, otherwise send the file.
- **Summary:** read `summary.json` and `report.md` next to the dashboard and answer the user's numbered questions directly. Say where the simulation agrees or disagrees with any real data they gave you, and remind them it is a simulation of personas, not real users.
- **Follow-ups:** `cli chat --simulation <id> --message "..."` asks the report agent. `cli interview --simulation <id> --agent 3 --prompt "..."` questions one persona while the environment is still alive.

## 5. Costs and cleanup

- Start with `--max-rounds 3-10` and a short seed. Agent count equals graph entities, so long seeds mean many agents.
- Every graph build, agent profile, round and report calls Claude on the user's key. Say roughly what a step will do before running rounds.
- `bash "$MF" stop` stops the backend and any running simulation. Stop the `live` server when done.

## Troubleshooting

- `doctor` is the first check for anything.
- Backend log: `<home>/backend/logs/server.out` (some lines are in Chinese; they are upstream log messages).
- A failed `run` still exports what it has and records the error in `run_manifest.json`.
- More detail: `<home>/CLAUDE.md` (full operating guide) and `<home>/HANDOFF.md` (known gaps).

# Installing the MarketMirror MCP server (for AI agents)

These steps are for an agent (Cline, Codex, Claude Code, Cursor, Gemini CLI or another MCP client) setting up
MarketMirror for its user. MarketMirror runs locally. Linux, macOS or WSL; native Windows has not been validated.

## 1. Requirements

Check that `git`, `bash`, `python3` and `uv` are installed (`uv --version`). If `uv` is missing, ask the user to install
it (https://docs.astral.sh/uv/); do not install system packages without asking.

## 2. Get the engine

```bash
git clone https://github.com/DarkWorldCoder/market-mirror.git ~/.market-mirror/engine
cd ~/.market-mirror/engine
bash install.sh
```

`install.sh` creates the Python 3.12 environment for the backend. It does not ask for or store any key.

## 3. Add the MCP server

Print the configuration for the client and merge it into the client's MCP settings (do not overwrite other servers):

```bash
./mm agent-config --client generic   # also: codex, claude, cursor, gemini
```

The result is a stdio server, for example:

```json
{
  "mcpServers": {
    "market-mirror": {
      "command": "python3",
      "args": ["/home/USER/.market-mirror/engine/plugin/skills/market-mirror/scripts/mcp_server.py"],
      "env": { "MARKET_MIRROR_HOME": "/home/USER/.market-mirror/engine" }
    }
  }
}
```

Use the absolute paths that `agent-config` prints. No API key goes in this file.

## 4. Choose a model provider (the user does this)

Never ask the user to paste an API key into the chat. Ask them to run this in their own terminal, where the key is
entered hidden:

```bash
cd ~/.market-mirror/engine && ./mm configure
```

They can pick a hosted API (Anthropic, OpenAI, Google Gemini and others), a local model (Ollama, LM Studio), or a local
login gateway (`./mm gateway start claude|codex|gemini`) that uses a CLI they are already signed in to.

## 5. Check it works

Restart the client, then call the `doctor` tool. It reports the engine, Python dependencies, whether a provider is
configured (never the key itself) and whether the backend is running. Start the backend with the `start_backend` tool or
`./mm start`. A first small test: the `quickstart` tool, which writes editable inputs and stops before any paid step.

Results are simulated buyers, not real customers. Report them as directions with their ranges.

# Publishing MarketMirror for agents

## Claude Code plugin marketplace (done: this repo is a marketplace)

The repository root carries `.claude-plugin/marketplace.json`, and `plugin/` is the plugin (manifest at `plugin/.claude-plugin/plugin.json`, skill at `plugin/skills/market-mirror/SKILL.md`, MCP server registered through `mm.sh mcp`). Anyone can install it today:

```
/plugin marketplace add DarkWorldCoder/market-mirror
/plugin install market-mirror@market-mirror
```

Before a release:

1. Bump `version` in `plugin/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, add the entry to `CHANGELOG.md`.
2. Validate: `python3 -c "import json;json.load(open('plugin/.claude-plugin/plugin.json'));json.load(open('.claude-plugin/marketplace.json'))"` and, inside Claude Code, `claude plugin validate .` if your version offers it.
3. Tag the release (`git tag v0.3.0 && git push --tags`); the Docker image workflow builds on tags.

### Listing in Anthropic's official plugin directory

Submissions go through Anthropic's own process (a pull request or form against their official marketplace repository; the current instructions are in the Claude Code documentation under "Plugins > Marketplaces"). Prepare: the plugin name and one-line description, the repository URL, the `plugin.json` above, a short demo (the README's screenshots), the license (AGPL-3.0) and a contact. The submission itself is made from the maintainer's GitHub account.

## OpenAI Codex

Codex reads **skills** in the open Agent Skills format and project instructions from `AGENTS.md`; MCP servers are configured in `~/.codex/config.toml`.

1. Install the skill for Codex: copy `plugin/skills/market-mirror/` to `~/.codex/skills/market-mirror/` (or the `skills` folder Codex shows in `codex --help`). The `SKILL.md` front matter (name, description) is what Codex indexes.
2. Register the MCP server in `~/.codex/config.toml`:

```toml
[mcp_servers.market-mirror]
command = "bash"
args = ["/absolute/path/to/market-mirror/plugin/skills/market-mirror/scripts/mm.sh", "mcp"]
```

3. Add the snippet from `codex/AGENTS.md` to the project's `AGENTS.md` so Codex knows when to use MarketMirror.
4. No API key? `mm.sh gateway start codex` runs the engine on the ChatGPT login (personal use).

A Codex marketplace listing, when OpenAI opens submissions for third-party skills, needs the same material as the Claude listing; keep `codex/` as the packaged copy.

## Python package

`sdk/` is a plain `pyproject.toml` package (`pip install -e sdk`). To publish: `cd sdk && python -m build && twine upload dist/*` from the maintainer's PyPI account.

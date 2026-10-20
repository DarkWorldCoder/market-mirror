# Use MarketMirror in your daily agent

MarketMirror is self-hosted open-source software under the repository's AGPL-3.0 license. The default knowledge graph and embeddings run locally. Hosted model accounts are optional: an OpenAI-compatible local model can power the same workflow. Public-source research needs internet access; imported documents and customer exports remain usable offline with a local model.

## Install a checkout

Install Git and [uv](https://docs.astral.sh/uv/), then:

```bash
git clone https://github.com/DarkWorldCoder/market-mirror.git
cd market-mirror
bash install.sh
./mm configure
./mm provider check
./mm start
```

The installer installs the Python 3.12 environment and dependencies. It preserves existing credentials and does not edit your agent settings. It records the checkout location in `~/.market-mirror/engine.json` so installed plugin copies can find it; an explicit `MARKET_MIRROR_HOME` takes priority. Bash is required by the helper; use Linux, macOS, or a suitable WSL environment on Windows. Native Windows installation has not been validated.

## Choose how models run

To use your existing local CLI login directly:

```bash
./mm gateway start codex   # existing Codex / ChatGPT login
# Or:
./mm gateway start claude  # existing Claude Code login
./mm start
```

Choose one gateway at a time. `./mm gateway status` reports availability and usage. Claude Code runs with tools, MCP, skills and hooks disabled for relay requests while keeping its normal saved login. The gateway reports provider token usage when supplied; otherwise token counts are explicitly estimates. CLI-reported list costs are not an invoice.

For Claude Code the relay forwards each request's output budget through the documented [`CLAUDE_CODE_MAX_OUTPUT_TOKENS` setting](https://code.claude.com/docs/en/env-vars). `LLM_GATEWAY_MODEL`, `LLM_GATEWAY_WORKERS`, and `LLM_GATEWAY_EFFORT` control the configured model, concurrency and optional effort level. Start with a small cohort to measure local CLI throughput before a large study; every upstream request launches a separate CLI process.

| Choice | Setup | Hosted API key |
|---|---|---|
| Ollama | Install a tool-capable model locally; choose `ollama` in `./mm configure` | No |
| LM Studio | Load a model and enable its local OpenAI-compatible server; choose `lmstudio` | No for the default local endpoint |
| Claude API | Choose `anthropic`; the wizard links to the official key console | Yes |
| OpenAI API | Choose `openai`; the wizard links to the official key console | Yes |
| Other API providers | Choose `deepseek`, `kimi`, `mistral`, `xai`, `groq`, `together`, `fireworks`, `openrouter`, `qwen`, `zhipu`, `cerebras` or `minimax`; the base URL and a default model are filled in (Qwen asks for its workspace URL). The key comes from that provider's variable, for example `DEEPSEEK_API_KEY` or `MOONSHOT_API_KEY` | Yes |
| Another compatible server | Choose `compatible`; provide its HTTPS endpoint and model | Provider-dependent |
| ChatGPT sign-in | Choose `siwc`, follow the returned login command, then start its gateway | Eligible account authorization |
| Existing CLI login | Choose `codex` or `claude`, then run the returned gateway command | Uses that CLI's local authorization |

The wizard discovers available model identifiers when the provider supports model listing. Choose a model that can use tools and produce structured JSON; discovery alone does not validate simulation quality. Run a small fixture before scaling the cohort. Local-model speed and quality depend on the selected model and hardware.

For hosted credentials, use the official [Claude key console](https://platform.claude.com/settings/keys) or [OpenAI API key console](https://platform.openai.com/api-keys). `./mm configure --open-guide` can open the console while prompting for hidden input in your own terminal. The wizard saves `.env` atomically with private file permissions and never returns the key to the agent. API access, billing, and a consumer chat subscription can have different eligibility requirements; follow the provider's setup instructions.

For unattended agents, use an existing environment variable rather than a key in command arguments:

```bash
./mm provider configure --provider anthropic --model YOUR_MODEL_ID --key-env ANTHROPIC_API_KEY
# Another API provider; without --model its default model is used:
./mm provider configure --provider deepseek --key-env DEEPSEEK_API_KEY
# Or a local model, with no hosted key:
./mm provider configure --provider ollama --model YOUR_INSTALLED_MODEL_ID
./mm provider status
./mm provider check
```

`provider status` is masked. `provider check` requests the model catalog without running inference, rejects insecure hosted HTTP endpoints and credential-bearing URLs, and does not forward credentials through redirects. Restart the backend after changing providers. Agent conversations and MCP arguments must never contain the API key itself.

## Connect an agent

The portable plugin supports Codex and Claude Code installation from this repo; see [plugin setup](../plugin/README.md). For direct MCP registration:

```bash
./mm agent-config --client codex
./mm agent-config --client claude
./mm agent-config --client cursor
./mm agent-config --client gemini
./mm agent-config --client generic
```

Codex and Claude outputs include a registration command. The generic output includes a `mcpServers` entry with the absolute server path and engine directory. Copy that server entry into the location your client expects; configuration formats and restart controls differ by client. These commands print configuration without overwriting existing servers. Any MCP client supporting stdio and the negotiated protocol can use the server. Local authenticated Streamable HTTP is also available; see the root README.

## First daily workflow

Ask your agent: “Use MarketMirror to understand this product brief, import our campaign export, research cited feedback, and prepare a campaign plan. Test the alternatives with a small simulated cohort, show missing evidence, and recommend the next real experiment.”

The agent can call `doctor`, `provider_setup`, `understand`, `research`, `actuals_import`, `campaign_plan`, `run_test`, `study`, `job_status`, `holdout_backtest`, and `results`. Each long job has status, a log path, and a result path. Reuse a prepared simulation to avoid regenerating personas. Study cells reuse completed steps and identical feed exposures for the same seed. Reports distinguish simulated evidence, actual exports, calibration, and held-out validation.

The tool prepares campaigns and rehearses sales conversations. Publishing, sending, and ad-account changes are outside this release.

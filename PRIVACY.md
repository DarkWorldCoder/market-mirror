# Privacy

Last updated: 25 October 2026.

MarketMirror is open-source software that runs on your own machine. There is no MarketMirror service, account or server, so we
(the maintainers) never receive, see or store your data.

## What stays on your machine

Everything you give MarketMirror and everything it produces: briefs, documents, ad exports, survey answers you import, simulated
people, simulation runs, reports and dashboards. These are saved as files under the engine folder (by default
`~/.market-mirror/engine`: `backend/uploads/`, `scenarios/` and `mirofish_runs/`). Your API key is kept in your local `.env` file
and is never printed or sent anywhere except to the provider it belongs to. Delete those folders to delete the data.

MarketMirror has no analytics, tracking or telemetry.

## What leaves your machine, and where it goes

- **Prompts to the language model you configure.** To build simulated buyers, run simulations and write reports, MarketMirror
  sends prompts (which include parts of your brief, documents and data) to the LLM provider you chose: for example Anthropic,
  OpenAI, Google Gemini or OpenRouter with your own key, a local model (Ollama, LM Studio) that never leaves your machine, or the
  optional local login gateway, which passes prompts to the Claude Code or Codex CLI you are signed in to. That provider's own
  privacy policy and data-retention terms apply to those prompts.
- **Public pages for research.** The `research` step fetches public web pages (for example Reddit, Hacker News search, app-store
  reviews or URLs you give it) to collect what real people say. It sends only the search query or URL, not your files.
- **Downloads during setup.** Setup clones this repository from GitHub and installs Python packages; the first run downloads
  an embedding model. These requests send no data of yours.

## Personal data

If you import files that contain personal data (for example survey answers or customer lists), that data is stored locally and
may be included in prompts to your chosen LLM provider. Remove personal details you do not want sent before importing.
Simulated people are synthetic and are not real individuals.

## Contact

Questions: open an issue at https://github.com/DarkWorldCoder/market-mirror/issues, or report a security problem privately as
described in [SECURITY.md](SECURITY.md).

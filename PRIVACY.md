# Privacy

Last updated: 31 October 2026.

This notice describes the self-hosted MarketMirror software and agent plugin. MarketMirror does not require a hosted
MarketMirror account. Where your data is processed depends on your installation, the model and memory providers you configure,
the websites you test, and the agent or MCP client you use. Running the software locally does not make every operation offline.

## Local files and credentials

MarketMirror saves briefs, imported documents and exports, research records, generated personas, simulation state, reports
and dashboards in your installation and configured output locations. The managed engine normally lives at
`~/.market-mirror/engine`; common data locations include `backend/uploads/`, `scenarios/` and `mirofish_runs/`.
Paths can be overridden. Backend logs are stored separately in `backend/logs/`, and MCP job metadata and output logs can
also be written under `~/.market-mirror/jobs/`.

Provider credentials can come from local configuration such as `.env` or environment variables. An agent, CLI provider,
browser or hosting service can keep additional credentials and records under its own settings. Keep configuration, imported
customer data and run artifacts private; do not attach credentials to public support issues.

## What can leave your machine

- **Models and gateways.** Model-powered operations send prompts containing relevant inputs, retrieved context and simulated
  responses to the configured provider or gateway. This can include parts of briefs, documents, imported customer data and
  observed website text. Multiple configured providers can be used in a run. A local gateway that calls Claude Code or Codex
  still uses that CLI's configured service. A model endpoint is local only when you actually run and configure it locally.
- **Memory and knowledge graphs.** The default `MEMORY_BACKEND=local` stores a SQLite graph locally, but graph extraction can
  still call your configured language model. Optional `MEMORY_BACKEND=zep` sends document chunks and simulation activity
  to Zep Cloud for graph processing. Optional `MEMORY_BACKEND=cognee` sends texts and search queries to the configured Cognee
  sidecar, which has its own storage and model configuration. A local graph or sidecar is not a promise of offline processing.
- **Research and product pages.** Research and product-inspection operations request the search queries and URLs you supply.
  The destination services receive those requests and ordinary connection information such as your IP address. Avoid putting
  private data in a query or URL.
- **Website tests.** Synthetic visitors connect to the actual target site and its allowed resources. The site can record the
  visits in its logs or analytics. Enabled cart or signup actions can send supplied test data and change site state. Use a site
  and test identity you are authorized to test, preferably a staging environment.
- **Setup and dependencies.** Installation, package downloads and model downloads contact their respective hosts. Those hosts,
  your AI client, provider CLIs and dependencies have their own privacy, logging and telemetry settings.

The receiving provider's or service's privacy and retention terms apply. Self-hosting does not override those terms.

## Website-test recordings

Website tests save local observations, action records, screenshots and reports. Supplied identity strings are redacted from
JSON diagnostics, and screenshot capture masks input controls. This is not complete anonymization: a site can echo a test
identity elsewhere on the page, including in a screenshot.

Video and raw Playwright traces are opt-in. They can contain unredacted page contents, test identities and network payloads.
Keep these recordings private and use disposable test data. See [website testing](docs/WEBSITE_TESTING.md) for the controls
and their limits.

## Retention and deletion

Saved reports and working files remain in the locations used by your installation until you remove them or another configured
process does. Review custom output paths, backend logs, MCP job records, recordings, caches and backups as well as the engine
data folders when cleaning up an installation. Stop relevant jobs before removing their working data.

Deleting local files does not delete copies held by a model provider, Zep Cloud, a configured sidecar, a tested website,
your AI client, a hosting service or a recipient of an exported report. Manage those copies through the applicable service
or operator. Maintainers can receive information you choose to send in an issue or support report; public issues are public.

## Personal data and deployment

Use only data you are authorized to process. Remove unnecessary personal details before importing files or sending them to
a configured provider, and use test identities rather than customer credentials for website tests. Generated buyer reactions
are simulated and do not establish what real customers think or will do.

If you host MarketMirror for other people, you control that deployment's access, storage, provider choices and retention.
This notice does not describe an independently operated hosted service, GitHub's hosting, or third-party clients and providers.

## Contact

For a non-sensitive question, open an issue at https://github.com/DarkWorldCoder/market-mirror/issues.
Report security problems privately as described in [SECURITY.md](SECURITY.md); do not publish customer data or credentials.


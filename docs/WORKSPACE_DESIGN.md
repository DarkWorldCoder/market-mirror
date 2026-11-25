# MarketMirror workspace design

The local app opens directly into conversation. It uses Vue 3, the actual 21st.dev Agent Elements InputBar mounted through a small React boundary, shadcn-vue controls, ECharts reports, and a lazy-loaded Three.js persona scene. The public landing page remains in `docs/index.html`; its message and visual restraint inform the local home page.

## Reference choices

- [shadcn-vue](https://www.shadcn-vue.com/blocks): composable controls, sidebar structure, compact tables and semantic theme tokens. Button and Badge sources are installed under `frontend/src/components/ui` through the official CLI.
- [Kokonut UI on 21st.dev](https://21st.dev/@kokonutd/library/kokonut-ui): search, compact AI composer and quiet activity layouts. Kokonut informs layout; the official Agent Elements InputBar and its dependencies are installed as React source with provenance in `frontend/src/components/agent-elements/PROVENANCE.md`.
- [Agent Elements on 21st.dev](https://21st.dev/@21st/library/agent-elements): separate message, tool and agent activity surfaces. Saved report data and provider replies have distinct labels.
- [Nuxt UI](https://ui.nuxt.com/) and [PrimeVue](https://primevue.org/datatable/): considered as alternative Vue systems. The app retains ownership of its component sources through shadcn-vue.
- [Three.js](https://threejs.org/docs/): persona selection, orbit controls and segment grouping. Positions are an arrangement, not measured similarity.

## Tokens and structure

`frontend/src/assets/design-system.css` maps semantic component tokens to the workspace palette. `workspace.css` owns shell geometry and light/dark colors. The main surfaces are a quiet navigation rail, experiment overview, report conversation, and audience/activity inspector. Data tables retain every row through pagination or scrolling.

## Data behavior

- Run index refreshes every 15 seconds while visible. Run data refreshes every 8 seconds while visible.
- Saved statuses are recorded states. A polling timestamp does not prove that a simulation is running.
- Counts come from saved files. Missing values remain absent or explicitly unrecorded.
- The artifact explorer reads JSON, Markdown, CSV and HTML exports. Numeric columns in structured tables can be charted.
- Read-only report chat uses saved data. Persona and report-agent model calls retain their provider usage notices.
- The 3D scene renders every available persona with instanced geometry, resizes with its container, and releases graphics resources on unmount. The person selector and profile remain usable if WebGL fails.

## Local review

Open `/` or `/workspace/chat` for direct conversation, `/start` for the guided entry page, `/workspace` for the run library, and `/workspace/runs/<name>` for reports and personas. The local setup session is required for private run data. `fitloop_launch` is a rich saved example; its results describe a fictional product and simulated buyers.

## Chat interaction references and implemented behavior

[assistant-ui tool UI](https://github.com/assistant-ui/assistant-ui/blob/main/apps/docs/content/docs/tools/tool-ui.mdx) informed the grouped activity and inline tool-result pattern. [LibreChat](https://github.com/danny-avila/LibreChat) was reviewed for agents, MCP, skills, artifacts, search, and multiuser chat organization. These projects are research references, not additional installed application runtimes.

The workspace currently provides inline report charts, audience globe/profile exploration, structured connector results, currency-safe advertising export cards, project context, selectable reviewers with per-reviewer models, skills, and shared cloud notes/presence. A single activity panel groups actual server events and replaces repeated working labels. Chat names can be changed directly in the top bar or sidebar.

The composer’s View a website action accepts a public URL. Show preview captures the page without a model call and stores its actual screenshot, extracted text, links, and capture metadata in chat. Analyze page sends a request through the selected model and enabled browser tool. Screenshot and Parsed text tabs share the selected-tab styling used by Settings and Connections. Screenshot expansion stays inside the conversation. This is a guarded, read-only capture with JavaScript disabled, not an interactive remote browser or a continuous live stream.

Actual Google Analytics and Meta data require an authorized connector or a supplied export. Their presence in the catalog does not mean an external account is connected. Public hosting and live billing remain separate deployment checks.

## Added on top of this design

- **Compare** (`/workspace/compare?a=&b=`): two saved runs side by side: decision, people, would-buy, maybe, strongest audience, top objection and best ad, with a "higher" marker, purchase-intent charts and a too-close-to-call note. Simulated gaps tend to be larger than real ones, and the page says so.
- **Pinned runs**: pin any saved run to the top of the sidebar. Pins are kept in this browser.
- **World map** in the audience explorer: next to the 3D globe, every simulated person on a flat world map in their own country. Lines show replies, likes, quotes and shares between people; you can play it round by round or see all of it at once. What people wrote at each step sits beside the map, with interactions per round and the most discussed posts under it. Cities are not geocoded.
- **Plain-language person card**: the verdict in big type (yes, maybe, no), the person's own words, what's holding them back, what would change their mind, what they did in plain sentences, who they talked to, facts about them and their thinking step by step. "Ask … a question" opens the run's Person chat with them selected; nothing is sent until you press send. Community and brand accounts are labelled as accounts, not buyers.
- **Run page**: key numbers (people, segments, would buy, maybe) and a fourth mode, **Focus group**: each line is a discussion question. You get the before and after verdicts, themes and the transcript. It reads the shared result file only after its own task completes. `Alt 1–4` switch modes.
- **Chat**: copy and "edit and send again" on your own messages, and download the chat as Markdown.
- **Shortcuts**: `?` lists them.
- **Thin scrollbars** everywhere. The sidebar rows line up with the search box.
- **Thinking** loads from `GET /api/runs/<name>/thoughts`, which harvests the run folder and the simulation folder. Saved runs have no `thought_stream.json`, so the old source came up empty. `GET /api/runs/<name>/status` reports stages and round status.
- **Local mode** skips the hosted account probe, so loopback pages no longer log a 404 on every load.

## Design pass: runs in the chat

- **Run card in the thread** (`RunChatCard.vue`, helpers in `workspace/runCard.js`): a saved run opened from the sidebar, the home page, a `?run=&show=` link or the agent's `open_view` shows up as a card in the conversation. It has the simulated verdict, key numbers (people, segments, would buy, maybe), each marked simulated, and the run page's five tabs (Results, Audience & world, Buyer responses, Activity, Social feed). Tabs load the first time you open them and follow the WAI-ARIA tabs pattern: arrow keys, Home and End. The action row holds Ask a person, Run a focus group, Compare with…, Open full page and Download report. Asking a person and focus groups go to the chat agent, which shows the cost on its approval card before anything runs.
- **Next steps** under the latest answer about a run: chips that fit what the run saved. "Why did people say no?" and "Which audience should we target?" are answered from `summary.json` without a model call. Chips that would spend ("Test a cheaper price", "Ask the buyers a follow-up") send a message to the agent and say "asks first".
- **Everywhere**: one focus ring, skeleton loaders instead of "Loading…", answers with copy, retry and download, your messages with copy and edit, one chip style, lined tables with numbers in columns, messages that rise in (still under reduced motion), and 40 to 44 px tap targets with sideways-scrolling tabs at phone width.

## Legacy views

The legacy MiroFish pages (`/legacy`, `/process/:id`, `/simulation/:id`, `/report/:id`, `/interaction/:id`) are kept for old bookmarks and links. They are not part of the workspace and are not linked from it. Every legacy page carries a MarketMirror bar with a link back to the workspace, and its brand reads MarketMirror; the repository link points at this project. A future release may redirect these routes to the matching workspace page instead.

## Connections and settings

- **Connections page** (`/workspace/connectors`, `ConnectionsPage.vue`): the sidebar link used to point at the chat home with `?connectors=1`, which only opened a dialog when that flag changed, so closing the dialog left you on the chat. It is now a page with three tabs. **MCP servers** (`McpServers.vue`) lists saved servers as cards: status (Connected, Sign-in failed, Error, Not checked), transport, last check, tool count, a "Use in chat" switch, Test, Edit and Remove. Expanding a card lists its tools with a switch each and a hint from the server's annotations (Read-only, May change data, Can change or delete data); only read-only tools can be switched on. "Add MCP server" checks the address in the browser first, then `POST /api/workspace/connectors/test` connects and lists tools without saving. A blank token on an edit reuses the saved token only for the saved address. Only public https Streamable HTTP servers with an optional bearer token are supported; there is no stdio, custom header or OAuth support. **Data imports** keeps the analytics and ads sources as cards with a status (Import a file, or the matching MCP server's state). **Use in your AI apps** (`McpClientSetup.vue`) shows copy-ready setup for Claude Desktop, Claude Code, Cursor, VS Code, Codex and other apps from `GET /api/workspace/mcp-setup`, built from this checkout's real paths, plus the `--http --token-file` option with the token left as a placeholder.
- **Chat and connector tools**: the older direct chat (`/api/workspace/chat`) calls enabled read-only connector tools picked under Tools in the chat box. The chat agent (`app/services/chat_agent/`, on by default in the standard answer mode) does not call them yet. The page says so.
- If the chat agent loses its connection, it explains the interruption in the conversation. Use Retry to ask again.
- **Settings > Models** (`ModelCards.vue`, helpers in `workspace/connections.js`): one card per way to reach models: logins on this computer, then API providers, each with a status (Connected, Key saved, Connects on first use, Key rejected, Not set up) and "Use this". The key field is a password field with show and hide. **Test** calls `POST /api/workspace/settings/test`, which only asks the provider for its model list (free). When a server has no model list, the page asks before one one-token call. A saved key is only sent to its own provider's address. The API address sits under Advanced. Production (`MM_ENV=production`) shows the cards read-only.
- **Settings > Spending, Memory, Decision engine** use the same cards with a one-line help each; rarely used fields sit under Advanced. **Settings > Connections** is a summary (servers connected, tools on in chat, models ready) with a link to the page. On phones the settings sections are a select.

## Everything from the chat

Anything you can see or do elsewhere in the app also works in the conversation, shown inline. The page only changes when you press **Open full page**. There are three ways in, and they open the same views:

- **The chat agent** calls `open_view` (free, read-only, offered in every phase). Run views take `run` and optional `filters`. `compare` takes `runs`. `insights` takes a `panel`. Workspace views take no run. Bad arguments come back to the agent as a tool error, so nothing renders. The tool result holds only the view spec. The browser reads the data with the user's own session, so a view never shows more than its full page would.
- **Typed requests without a model.** `workspace/chatViews.js` (`localViewIntent`) answers near-exact phrases from saved files, with no model connected and nothing spent. Examples: "show the people in Kenya", "show buyer responses that said no", "who said no", "show the dashboard map", "what's my spend", "which connectors are on", "open the landing analysis", "show objections across all runs". Run views use the selected run, then the newest. "for <run>" names another one. Anything else still goes to the agent.
- **Slash commands.** Type `/` for the menu. Each row shows a label, a description and a badge: **Free** means no model call. **Asks first** means it goes to the chat agent, and anything that runs simulated buyers shows its cost on the approval card first. Arrow keys, Page Up/Down, Ctrl+Home/End, Enter and Esc work, and the best match comes first. Words after a view command filter it: `/people Kenya`, `/responses no`, `/responses price`, `/insights objections`, `/people for <run>`.

| Feature or view | Where it lives | How the chat reaches it | Cost |
|---|---|---|---|
| Results (verdict, key numbers, report) | Run page, Results | run card tab; `open_view results`; `/results`; "show the results" | Free |
| Audience & world (world map, 3D audience) | Run page tab | run card tab; `open_view world_map` / `audience`; `/map`; "show the world map" | Free |
| People explorer (filters, compare, CSV) | Run page tab | run card tab; `open_view people` with `segment`, `country`, `verdict`, `gender`, `query`; `/people Kenya`; "show the people in Kenya" | Free |
| Buyer responses (verdict, segment, objection, search) | Run page tab | run card tab (same `BuyerResponses` component); `open_view buyer_responses` with `verdict`, `segment`, `objection`, `source`, `query`; `/responses no`; "show buyer responses that said no" | Free |
| Activity (rounds, analyst panel, most active) | Run page tab | run card tab (`RunActivity`); `open_view activity`; `/activity` | Free |
| Social feed | Run page tab | run card tab; `open_view social_feed`; `/feed`; "show the social feed" | Free |
| Landing page analysis | Run page, inside Results | own run card tab (`LandingAnalysis`); `open_view landing`; `/landing`; "open the landing analysis". Testing a fix goes to the agent and asks first | Free to view |
| Predicted brain response (research) | Run page, inside Results | run card tab, shown when the run saved one (`BrainResponseSection`); `open_view brain_response`; `/brain` | Free to view |
| Dashboard world map (audiences across runs) | Dashboard | `ChatViewCard` with `overview/AudienceWorldMap`; `open_view dashboard_map`; `/dashboard-map`; "show the dashboard map" | Free |
| Dashboard insights: activity calendar, intent across runs, objections, audiences, trust and forecasts, spend, live runs | Dashboard | `ChatViewCard` with the overview panels; `open_view insights` (all) or with `panel`; `/dashboard`, `/insights objections`; "show the activity calendar", "what is running now" | Free |
| Reports browser | Run page, Results | "Browse all saved reports" in the run card's Results tab (`ReportBrowser`) | Free |
| Compare two runs | `/workspace/compare` | embedded `CompareRuns`; `open_view compare`; `/compare`; "compare my last two experiments"; run card "Compare with…" | Free |
| Projects | `/workspace/projects` | `ChatViewCard` list linking to each project's chat; `open_view projects`; `/projects`; "show my projects" | Free |
| Skills | `/workspace/skills` | `ChatViewCard` list by group, each one usable in place; `open_view skills`; `/skills`; the `/` menu | Free to browse |
| Connectors status | Connections panel | `ChatViewCard` summary (model keys set, connected tools on or off) with **Manage connections**; `open_view connectors`; `/connectors`; "which connectors are on" | Free |
| Model settings | Settings panel | `ChatViewCard` summary (provider, model, key set, memory, Jev, spending limit) with **Open settings**; `open_view settings_summary`; `/settings`; "which model am I using" | Free |
| Spending cap and spend so far | Settings, Spending; dashboard Spend panel | `ChatViewCard` with the process spend, the limit, a running test's cap and the per-run Spend panel, plus **Change the limit in Settings**; `open_view spend`; `/spend`; "what's my spend" | Free |
| Start an experiment | Guided setup | `/new-experiment` opens it inside the chat; the agent's `market_test` | Asks first |
| Focus group | Run page Ask mode | `/focus-group`; run card **Run a focus group**; agent `ask_buyers` | Asks first |
| Ask one person | Run page Ask mode, person cards | `/ask`; **Ask** on a person in People or Buyer responses (draft only, nothing sent); agent `ask_buyers` | Asks first |
| Calibrate with real answers | CLI `calibrate` | agent `calibrate` (form for the run and CSV); `/calibrate` | Free (no model calls) |
| Analytics audience (GA4, PostHog) | CLI `analytics-audience` | agent `analytics_audience`; `/analytics` | Free (offline) |
| Ads import, real results import | CLI `ads-import`, `actuals_import` | agent `ads_import`, `actuals_import`; `/ads-import`, `/actuals` | Free (offline) |
| Questionnaire, choice tests (MaxDiff, conjoint, Gabor-Granger) | CLI | agent `run_test` (types `maxdiff`, `conjoint`, `gabor_granger`) or `cli questionnaire`; `/questionnaire`, `/choice-test` | Asks first |
| Research (what real people say) | CLI `research` | agent `research`, after a one-line notice that it contacts public sites; `/research` | Outside notice |
| Predict, forecast lock and score, backtest, holdout backtest, real split | CLI | agent `predict`, `cli forecast …`, `backtest`, `holdout_backtest`, `real_split`; `/predict`, `/forecast`, `/backtest`, `/holdout`, `/split` | Free |
| Feed, email, pitch, website tests, ad patterns, creative check, ideas, campaign plan, study | CLI and MCP tools | agent tools with their own cost class; matching slash commands | Asks first (website test and creative check also give an outside notice) |

The run card's tabs now cover every run page tab plus the two sections the run page keeps inside Results, so nothing is page-only: Results, Audience & world, People, Buyer responses, Activity, Social feed, Landing page and Brain response (shown when saved). **Open full page** for Landing page or Brain response lands on the run page's Results. Views of simulated buyers carry "Simulated". Settings, connectors, spend, projects and skills are this computer's own data and do not.

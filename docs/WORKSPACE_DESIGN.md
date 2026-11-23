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

# MarketMirror local decision workspace

The app helps a founder or marketer compare two ads/headlines, review fictional
buyer reactions, and write a test to run with real people. It reuses the existing
persona, creative, landing-page, email and buying-committee engines. It does not
send emails, buy ads, publish content or establish demand.

## First visit and return visits

Install the engine using the README instructions, then run:

```bash
./mm app
```

The launcher builds the Vue interface once, starts the local backend and opens a
private browser session. The initial build needs Node.js 20.19+ or 22.12+ and npm;
Python dependencies must already be installed. A provider is **not** required to
open the app, save drafts or explore the saved demo. Use the same command to return.
After changing frontend sources, run `./mm app --build`. A separate instance can
use `./mm app --port 5011`; stop it with `./mm stop --port 5011`.

The token in the initial URL fragment stays in tab session storage and is removed
from the address bar. Do not share it or publish the app through a tunnel. All
workflow API operations require that token and a loopback connection. Production
API authentication, when configured, still applies; this launcher is intended for
the local development configuration, not an Internet-hosted service.

1. Choose **Compare two ideas** (or a task recipe).
2. Paste the actual product details. Optionally read a public URL or a PDF,
   Markdown or text document up to 5 MB. Extraction makes no model calls; fetching
   a URL contacts the website. Review and correct all imported text.
3. Add two variants, an audience, country and language. Defaults are 20 simulated
   buyers, compact profiles, one seed, and no social rounds or analyst panel.
4. Open **Model settings**, select a provider and use its existing connection
   check. A connection check itself can make a small provider call, as labelled
   in that page. Return and refresh connection status.
5. Review and approve preparation. This stage creates the fictional profiles and
   stops. Review them, then separately approve the comparison.
6. Read the comparison, objections and evidence. Edit/download the real-test
   worksheet. The existing [worked example](guides/first-real-test/) explains how
   to move from a simulated objection to real customer research.

The beginner workflow uses the first configured model provider, without pool
failover or SDK retries. Advanced multi-provider studies remain in the existing
CLI/MCP toolkit. Each attempt is reserved against the approved stage call limit
before dispatch. Cost is labelled unavailable rather than assuming a per-call
dollar rate. A call limit is **not** a dollar cap; upstream gateways/providers may
have internal processing or billing. Advertising budget is planning context only.

## Recovery and evidence

- Drafts and immutable executed comparisons live under the instance's upload
  folder in `workflows/`. Credentials are not copied into workflow records.
- Closing the browser does not stop an approved backend job. Reopening only reads
  its status. A backend restart marks unfinished work interrupted; it never
  automatically makes more calls.
- A retry requires an updated total call limit and explicit approval. Completed
  profiles and exposures are preserved. Failed exposures are excluded from scores.
- Changed inputs after execution create a new revision. Changed provider settings
  invalidate approval and require a new comparison/audience.
- Both variants see the same saved people in independent exposures. No behaviour
  history is passed between versions. These are simulated responses, not measured
  clicks or testimonials. The descriptive five-point highlight is not a test of
  statistical significance or real-world prediction accuracy.
- **Explore the evidence** opens escaped offline HTML with inputs, stage/task
  references, usage, profiles and raw saved results. The worksheet's observed-results
  field is user-entered real-test documentation, separate from simulated scores.
- Local events record connection confirmations, starts/completions, failures,
  retries and visible editing time (idle cutoff: 60 seconds, excluding running
  jobs). No external analytics service receives these events. Inspect aggregate
  counts through authenticated `GET /api/workflows/metrics`.

## CLI and API

Existing `./mm cli ...` commands and MCP contracts are preserved. The optional
workflow client uses the same API and execution service as the browser:

```bash
./mm workflow create --inputs my-product.json
./mm workflow estimate wf_ID --phase prepare
# Review the estimate, then supply its exact digest and chosen total call limit:
./mm workflow approve wf_ID --phase prepare --digest DIGEST --call-limit 12 --approve-calls
./mm workflow status wf_ID
# After reviewing the audience, repeat estimate/approve for --phase test.
./mm workflow results wf_ID
```

Use the complete `wf_...` ID returned by `create`, not the illustrative `wf_ID`.
Failed/interrupted stages additionally require `--retry` on approval. Inputs use
the request example in [API.md](API.md); `parent_id` creates a new revision. The
API and OpenAPI document the token header, digest approval, upload and HTML routes.

## Usability validation protocol (not yet conducted)

Recruit five founders or marketers unfamiliar with the implementation. Do not
replace them with simulated buyers. Run sessions with fictional product inputs
and a deterministic provider, or separately obtain permission for any model spend.

Ask each participant to: start a comparison, enter two headlines, explain the
model cost versus advertising budget, approve preparation, inspect the audience,
approve the test, explain what its result can/cannot establish, and save a real-test
worksheet. Include one interrupted run and a provider-setting problem across the
sessions. Avoid coaching unless the participant is blocked; record any assistance.

Target: at least four of five complete the comparison without developer help,
excluding engine installation and provider sign-in. Record task completion,
hands-on time, errors, retries, and whether the participant correctly distinguishes
simulation from real customer evidence. Compare against a measured baseline before
claiming an improvement. Five sessions alone do not establish a conversion effect.

Human sessions and a real paid-provider smoke test are outstanding until performed;
automated fixture/browser checks are engineering evidence only.

## Workspace (chat with your runs)

Open **Workspace** in the header, or `/workspace`, in the same app session. It opens dark (the sidebar toggles
light) and lists the runs saved under `mirofish_runs/` (or `MIROFISH_RUNS_DIR`), plus simulations on this backend
that have no run folder:

- **Home.** A chat box with attach (a text, Markdown or CSV file up to 60 KB, sent with your message), `@` to pick
  the run, Skills and the model in use; quick actions under it; **Previous chats** (chats saved in this browser,
  then runs and simulations, with "report ready" when the backend has a finished report) and **Suggested**.
- **Agents.** The tabs at the top pick who answers: **Results** (common questions answered from the saved files
  with a chart, no model call), **Report agent** (`POST /api/report/chat`), **Person** (one simulated person,
  `POST /api/simulation/ask`) and **Focus group** (`POST /api/simulation/focus-group`; each line is a question,
  then the transcript and the before/after verdicts). The three marked `$` send model calls to your provider; the
  box says so before you send, and they need the run's simulation on this backend. Every answer is labelled
  simulated. Chats are kept per run in this browser (`localStorage`) and listed under **Inbox**.
- **Steps with charts.** People created, the feed test, purchase intent, which audience to target (with the
  shrunk-gap marker), objections, and the files. Steps fold away once a chat starts.
- **Visuals** beside the chat: **Thinking** (what the people thought, said and posted, by source, from
  `GET /api/runs/<name>/thoughts`), **3D market** (3d-force-graph: people coloured by segment, linked to their
  segment and communities, with the market map's entities and links; a 2D map where the browser has no WebGL),
  **Live status** (stages, rounds and actions per round; refreshes every 5 s while a run is going, from
  `GET /api/runs/<name>/status`) and **Social feed** (posts and replies by platform from `feed_story.json`).
- **Skills and Connectors.** The test types and the data you can bring in, each with its command to copy.
- **Inbox.** Chats saved in this browser and finished reports, grouped by day, with filters (all, chats, reports,
  pinned) and search. The reading pane shows the whole conversation; pin the run, download the chat as Markdown
  (answers marked simulated), delete it, or open the run.
- **World map.** The World tab beside a chat puts every simulated person on a real world map (Natural Earth country
  shapes from `world-atlas`, pinned), in their own country; cities are not geocoded, so dots inside a country are spread
  out. Lines show who replied to, liked, quoted or shared whom in the social rounds; play it round by round, or see all
  of it at once. Beside the map is what people wrote at that step, and under it interactions per round and the most
  discussed posts. While a run is going on this backend it follows the newest round. Open it full screen from the tab.
- **Person card.** Click a dot, a name in Thinking, or a person in the 3D market: their verdict in big type (yes, maybe,
  no), their own words, what is holding them back, what would change their mind, what they did in the simulation in
  plain sentences, who they talked to, facts about them and their thinking step by step. "Ask" opens the Person agent
  with them selected. Community and brand accounts are marked as accounts, not buyers.
- **Getting around.** `Ctrl K` (or `⌘K`, or `/`) opens a palette that jumps to any run, page, agent or action;
  `Alt 1` to `Alt 4` switch agents; `?` lists every shortcut. Pin runs to the top of the sidebar; the dot beside each
  run is its decision. A run page shows its key numbers (people, segments, intent, best click-through) and lets you
  copy a link, download or clear the chat, and copy any message. Icons are Lucide (`lucide-vue-next`, pinned).

The workspace reads runs through `GET /api/runs`, `/api/runs/<name>`, `/api/runs/<name>/thoughts`,
`/api/runs/<name>/status` and `/api/runs/<name>/files/<file>`. They need the same local setup token and loopback
connection as the rest of the app, and only read plain result files directly inside a run folder (and the run's
simulation folder for thoughts and live status).

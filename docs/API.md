# MarketMirror API

The backend is a Flask app on `http://localhost:5001` (start it with `backend/claude_cli/start_server.sh`). Every response is
`{"success": true, "data": ...}` or `{"success": false, "error": "..."}`. Long jobs return a `task_id`; poll
`POST /api/simulation/market-task/status` until `status` is `completed` or `failed`, then `GET` the result. The upstream
engine routes (projects, ontology, graph build, simulations, start/stop, interviews, reports) are documented in
`docs/MIROFISH-UPSTREAM.md`; the `mirofish.py` CLI and the MCP server wrap all of them.

Authentication: `/api/workflows`, `/api/runs`, `/api/workspace/*` (except session bootstrap) and `/api/setup` are loopback-only and require the local `X-Setup-Token`, including reads.
Use `./mm app` for a browser session; the local browser also establishes its session automatically. Never share its token. Workflow approvals are tied to an input/provider digest and a model-call limit.
Other endpoints use the configured production authentication policy. Put the backend behind your own auth/network rules before exposing it.
Webhooks: set `MIROFISH_WEBHOOK_URL` (or `"webhook"` in `market_test.json`) and the CLI posts a JSON summary when a run, study
or test finishes. SDK: `pip install -e sdk` then `from marketmirror import MarketMirror`. Machine-readable: `docs/openapi.json`.


## Product understanding

### `POST /api/graph/profile`

Product profile from text/url/ads (no project).

Request body:

```json
{
  "text": "...",
  "url": "https://...",
  "ads_summary": {},
  "name": "Brand"
}
```

Returns: product profile + quickstart_answers

### `POST /api/graph/project/{project_id}/profile`

Create or reuse the project's product profile (seeds the market map before the graph build).

Request body:

```json
{
  "url": "https://...",
  "ads_summary": {},
  "refresh": false,
  "name": "Brand"
}
```

Returns: product profile

### `GET /api/graph/project/{project_id}/profile`

The project's product profile.

Returns: product profile

## Real voices

### `PUT /api/graph/project/{project_id}/voices`

Attach real voices (from research) to a project.

Request body:

```json
{
  "voices": [
    {
      "text": "...",
      "source": "appstore",
      "sentiment": "neg",
      "country": "in"
    }
  ]
}
```

Returns: {stored}

### `GET /api/graph/project/{project_id}/voices`

The project's voices.

Returns: {voices}

## Campaign planning

### `POST /api/graph/campaign-plan`

Save a draft evidence-led campaign plan and runnable test specs.

Request body:

```json
{
  "profile": {
    "name": "Brand"
  },
  "project_id": "",
  "goal": "trial signup",
  "budget": {
    "amount": 500,
    "currency": "USD"
  },
  "channels": [
    "search",
    "email"
  ],
  "research": {}
}
```

Returns: {plan, file}

## Local guided workflows (X-Setup-Token required)

### `POST /api/workspace/agent/stream`

One chat-agent turn over the MCP server's own tools, called in-process (up to 12 model steps). Free tools run at once; tools that contact outside websites ask Go/Skip once per chat; tools that make model calls pause on an approval card with people, calls per step and an estimated cost. Resume a paused turn with `resume`.

Request body:

```json
{
  "session_id": "chat id",
  "messages": [
    {
      "role": "user",
      "content": "Test these two headlines for busy parents in India"
    }
  ],
  "model": "server catalog ID",
  "fallback_models": [
    "server catalog ID"
  ],
  "run": "saved run",
  "files": [
    {
      "name": "ga4.csv",
      "text": "Country,Active users\n..."
    }
  ],
  "resume": {
    "id": "ap_...",
    "answer": {
      "decision": "run",
      "max_spend_usd": 5
    }
  }
}
```

Returns: text/event-stream: plan, tool_start, tool_progress, approval_request {id,kind: spend|outside|form|audience|limit,...}, tool_result, artifact {kind: view|compare|results}, error {message,status,code,actions}, done {status: complete|waiting|stopped, message, suggestions, trace, artifacts, pending}

### `POST /api/workspace/agent/audience/estimate`

Live numbers for the chat's audience table: people, model calls by step and a rough cost from the MCP server's spend_plan, plus fit-check flags (segments under 10 people, half or more in less-covered markets). No model call.

Request body:

```json
{
  "segments": [
    {
      "label": "Young parents",
      "count": 12,
      "country": "India",
      "platforms": [
        "instagram"
      ]
    }
  ]
}
```

Returns: {segments, people, estimate, fit_check}

### `GET /api/workspace/agent/jobs/{job_id}`

Status and log tail of a background job the chat agent started.

Returns: {job_id, label, status, elapsed_s, log_tail, result}

### `GET /api/workspace/agent/tools`

The tools the chat agent may call, with their cost class (free, outside, spend), phases and whether results are simulated.

Returns: {tools: [{name, label, cost, phases, simulated, source}], max_steps}

### `POST /api/workspace/chat/stream`

Stream actual public model/tool/reviewer progress then result or error; same validated chat inputs; no private reasoning or implicit execution.

Request body:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Explore my saved results"
    }
  ],
  "mode": "team",
  "model": "server catalog ID",
  "project": "proj_abcdef123456",
  "team_agents": [
    "market-analyst",
    "critical-reviewer"
  ],
  "team_models": {
    "market-analyst": "server catalog ID"
  },
  "connector_tools": [
    "mcp_abcdef123456/reports"
  ]
}
```

Returns: text/event-stream: progress {type,status,label,tool?,role?,model?,summary?,data?}, result {message,artifacts,trace,suggestions,agent_activity?,tool_results?,browser_observations?,workflow_id?}, error {message,status}; project source text is read in bounded authorized pages

### `POST /api/workspace/projects/{project_id}/sources`

Append a persistent plain-text project source; 10 sources,24k chars each,120k total,30KB request cap; no downloads or model calls.

Request body:

```json
{
  "name": "Product brief",
  "text": "Source facts and references"
}
```

Returns: updated project with sources and preferred_model

### `DELETE /api/workspace/projects/{project_id}/sources/{source_id}`

Remove one saved project source by opaque ID.

Returns: updated project

### `GET /api/workspace/skills`

List private workspace prompt templates; no executable imports.

Returns: custom skill array

### `POST /api/workspace/skills`

Save a reusable instruction template without fetching or running code.

Request body:

```json
{
  "name": "Ad review",
  "description": "Review supplied ads",
  "instructions": "Use supplied evidence",
  "group": "Custom skills",
  "source_url": "https://github.com/example/repository"
}
```

Returns: custom skill

### `GET /api/workspace/skills/{skill_id}`

Read one saved prompt template.

Returns: custom skill

### `PATCH /api/workspace/skills/{skill_id}`

Edit a saved prompt template; built-in engine skills cannot be changed.

Request body:

```json
{
  "name": "Weekly ad review"
}
```

Returns: custom skill

### `DELETE /api/workspace/skills/{skill_id}`

Delete a saved custom prompt template.

Returns: {id,deleted:true}

### `POST /api/workspace/browser/observe`

Capture a real bounded read-only public browser page snapshot with JavaScript off and public-IP-pinned GET resources; optional sandboxed Playwright required.

Request body:

```json
{
  "url": "https://example.com"
}
```

Returns: {session_id,url,title,text,text_truncated,screenshot,screenshots,events,links,mode,javascript,status_code}

### `GET /api/workspace/browser/{session_id}/image`

Guarded PNG screenshot for an opaque observation session; frame=0 or1, expires after24h.

Returns: image/png

### `GET /api/workspace/local-models`

Explicit bounded loopback-only installed-model discovery; refresh=1 refreshes cache, hosted workers skip unconfigured defaults.

Returns: {models:[{id,provider,base_url,source}],sources,checked_at,truncated}

### `GET /api/workspace/connectors`

Safe saved remote MCP configuration and actual discovery status; tokens omitted.

Returns: connector array

### `POST /api/workspace/connectors`

Save a public HTTPS Streamable HTTP MCP server with write-only bearer credential; no connection or tool call.

Request body:

```json
{
  "name": "Meta Ads",
  "url": "https://mcp.facebook.com/ads",
  "token": "write-only",
  "enabled": false,
  "allowed_tools": [],
  "protocol_version": "2025-11-25"
}
```

Returns: safe connector

### `PATCH /api/workspace/connectors/{connector_id}`

Update connector settings, enabled state and explicit read-only tool allowlist.

Request body:

```json
{
  "enabled": true,
  "allowed_tools": [
    "ads_read"
  ]
}
```

Returns: safe connector

### `DELETE /api/workspace/connectors/{connector_id}`

Remove connector configuration and its stored credential.

Returns: {id,deleted:true}

### `POST /api/workspace/connectors/{connector_id}/discover`

Actually initialize a saved MCP server and list tools with bounded JSON/SSE parsing; no business tool execution.

Returns: safe connector with status, tools, checked_at, error

### `GET /api/workspace/session`

Bootstrap a same-origin browser session on a literal loopback host; Sec-Fetch-Site same-origin required.

Returns: {token}

### `GET /api/workspace/projects`

List persistent projects and chat/run associations.

Returns: project array

### `POST /api/workspace/projects`

Create a real engine project and workspace metadata without model calls.

Request body:

```json
{
  "name": "Launch",
  "description": "Launch research",
  "instructions": "Project preferences",
  "chat_ids": [],
  "run_names": []
}
```

Returns: project

### `GET /api/workspace/projects/{project_id}`

Read one project.

Returns: project

### `PATCH /api/workspace/projects/{project_id}`

Update project preferences and associations.

Request body:

```json
{
  "name": "Launch"
}
```

Returns: project

### `DELETE /api/workspace/projects/{project_id}`

Archive project metadata while preserving evidence.

Returns: {archived:true}

### `GET /api/workspace/settings`

Read safe model, memory, decision engine and spending configuration without secrets.

Returns: {llm,memory,jev,spending}

### `PUT /api/workspace/settings`

Save validated configuration and write-only credentials; no paid connection test.

Request body:

```json
{
  "memory": {
    "backend": "local"
  }
}
```

Returns: safe settings with restart and connection status

### `GET /api/workspace/models`

Safe configured and connected local chat model choices; no credentials or configuration writes.

Returns: {models:[{id,name,provider,model,available,description,connection_required,connection_backend?}],default_id}

### `POST /api/workspace/chat`

Validated conversational assistant with saved evidence, selected-project source index/paged reads, enabled read-only connector tools and explicitly requested public page snapshots; optional2–4 no-tool team reviewers; never executes experiments.

Request body:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "What did the pricing test show?"
    }
  ],
  "run": "saved_run",
  "project": "proj_abcdef123456",
  "model": "server catalog ID",
  "mode": "team",
  "team_agents": [
    "market-analyst",
    "critical-reviewer"
  ],
  "team_models": {
    "market-analyst": "server catalog ID"
  },
  "connector_tools": [
    "mcp_abcdef123456/reports"
  ],
  "context": {
    "name": "Product brief",
    "text": "User-supplied source text"
  }
}
```

Returns: {message,artifacts:[{run,file}],trace,suggestions,workflow_id?,agent_activity:[{id,role,status,summary,model?}]?,tool_results?,browser_observations?}; model IDs are server catalog pointers and never modify global provider settings

### `GET /api/workflows/meta`

Recipe catalog and public provider status; no model calls.

Returns: {recipes, provider, demo_url}

### `GET /api/workflows`

Recent local workflow revisions.

Returns: workflow summaries

### `POST /api/workflows`

Save a draft or a new comparison revision; no model calls.

Request body:

```json
{
  "inputs": {
    "recipe": "ads",
    "name": "Brand",
    "product": "Actual product details",
    "audience": "Intended buyers",
    "country": "Nepal",
    "variants": [
      {
        "text": "A"
      },
      {
        "text": "B"
      }
    ]
  },
  "parent_id": null
}
```

Returns: workflow

### `GET /api/workflows/{wid}`

Saved draft, stage progress, people and artifact checkpoints.

Returns: workflow

### `PUT /api/workflows/{wid}`

Update an unexecuted draft; changed executed comparisons require a new revision.

Request body:

```json
{
  "inputs": {}
}
```

Returns: workflow

### `POST /api/workflows/{wid}/estimate`

Review remaining work and configuration digest; no model calls.

Request body:

```json
{
  "phase": "prepare"
}
```

Returns: {digest, provider, estimated_calls, calls_used, suggested_call_limit, cost_usd:null}

### `POST /api/workflows/{wid}/approve`

Explicitly approve a phase and start or reuse its task; retries require retry true.

Request body:

```json
{
  "phase": "prepare",
  "approved": true,
  "digest": "from estimate",
  "call_limit": 12,
  "retry": false
}
```

Returns: workflow with stage task_id

### `GET /api/workflows/{wid}/results`

Simulation-labelled comparison and editable next-real-test worksheet.

Returns: {complete, verdict, variants, metric_label, limits, worksheet}

### `PUT /api/workflows/{wid}/worksheet`

Save the user's real-world experiment worksheet.

Request body:

```json
{
  "text": "Markdown"
}
```

Returns: {saved}

### `GET /api/workflows/{wid}/evidence`

Escaped offline HTML evidence, no provider credentials.

Returns: HTML evidence document

### `POST /api/workflows/source`

Extract editable public page text or an uploaded PDF/Markdown/text file up to 5MB; no model calls.

Request body:

```json
{
  "url": "https://your-product.example"
}
```

Returns: {text, method, url?}

### `POST /api/workflows/events`

Record an allowlisted local usage event; no external telemetry.

Request body:

```json
{
  "name": "active_seconds",
  "workflow_id": null,
  "seconds": 20
}
```

Returns: {saved}

### `GET /api/workflows/metrics`

Local setup confirmations, completions, failures, retries and editing time; no product text.

Returns: local aggregate counts

### `GET /api/runs`

Saved run folders (mirofish_runs or MIROFISH_RUNS_DIR), newest first; no model calls.

Returns: {root, runs: [{name, title, decision, people, simulation_id, updated_at, has_dashboard}]}

### `GET /api/runs/insights`

One aggregate across all saved runs for the workspace overview, from saved files only (no model calls); cached per run by file mtimes.

Returns: {root, generated_at, total_runs, runs, activity: [{date, count, runs}], decisions: {go, iterate, no_go, unrecorded}, intent: [{run, rate, n, low, high, small_sample}], objections: [{label, runs, people}], segments: [{segment, runs, people, rate}], geography: {countries: [{country, people, runs, segments}], cities: [{country, city, people, runs}]}, trust: {runs, graded, calibrated, grades}, spend: {runs, total_usd, estimate}, forecasts: {locked, scored, hits, checks, entries}, running}

### `GET /api/runs/{name}`

One run: manifest, summary and the result files it has.

Returns: {name, title, decision, files, manifest, summary, simulation_on_backend}

### `GET /api/runs/{name}/thoughts`

What the simulated people wrote in this run (feed and landing thoughts, survey and pitch replies, posts), harvested from the run folder and the simulation folder; no model calls.

Returns: {total, people, by_source, by_kind, entries: [{agent_id, name, segment, source, kind, text, did, context}]}

### `GET /api/runs/{name}/status`

The run's stages, round status (live when the simulation is on this backend, else saved) and actions per round.

Returns: {simulation_id, live, run, stages: [{id, label, done}], rounds: [{round, actions, twitter, reddit, active}], started_at, finished_at}

### `GET /api/runs/{name}/files/{filename}`

A result file directly inside the run folder (.json parsed; .md, .csv, .html as files; ?download=1).

Returns: file contents

## Accounts, workspaces and team data (setup token locally; session cookie, CSRF token and X-MM-Workspace in team mode)

### `GET /api/auth/session`

Which mode the server is in (local or accounts) and, in team mode, the signed-in person, CSRF token, chosen workspace and all their workspaces.

Returns: {mode,account,csrf,workspace,workspaces,signups,first_account?}

### `POST /api/auth/signup`

Team mode only. Create an account (argon2id); the first account is always allowed, later ones follow MM_SIGNUPS (open, invite, closed); exact Origin; rate limited.

Request body:

```json
{
  "email": "person@example.com",
  "password": "12 to 256 characters",
  "name": "Sam",
  "workspace_name": "Acme marketing",
  "invitation": "token from an invitation link"
}
```

Returns: session state; sets the HttpOnly mm_session cookie

### `POST /api/auth/login`

Team mode only. Sign in; 10 failures per email and 30 attempts per client in 15 minutes, then 429.

Request body:

```json
{
  "email": "person@example.com",
  "password": "..."
}
```

Returns: session state; sets the mm_session cookie

### `POST /api/auth/logout`

Delete this browser's session (CSRF token required).

Returns: {signed_out:true}

### `POST /api/auth/password`

Change your password; signs out every other browser.

Request body:

```json
{
  "current_password": "...",
  "new_password": "..."
}
```

Returns: session state

### `POST /api/auth/workspaces`

Create a workspace you own and switch to it.

Request body:

```json
{
  "name": "Second team"
}
```

Returns: session state

### `POST /api/auth/workspaces/select`

Switch this session to a workspace you belong to.

Request body:

```json
{
  "id": "ws_..."
}
```

Returns: session state

### `GET /api/auth/invitations/{token}`

Preview an open invitation: workspace name, role, bound email, expiry.

Returns: {workspace,role,email,expires_at}

### `POST /api/auth/invitations/accept`

Accept an invitation as the signed-in person (one use; email must match when bound).

Request body:

```json
{
  "token": "..."
}
```

Returns: session state

### `GET /api/team`

Workspace, members with roles and (for owners) open invitations.

Returns: {workspace,members,invitations,you,mode}

### `PATCH /api/team/workspace`

Owner: rename the workspace.

Request body:

```json
{
  "name": "Acme marketing"
}
```

Returns: {id,name}

### `PATCH /api/team/members/{user_id}`

Owner: change a member's role (owner, editor, viewer); the last owner stays.

Request body:

```json
{
  "role": "viewer"
}
```

Returns: member array

### `DELETE /api/team/members/{user_id}`

Owner: remove a member; anyone: leave (yourself). Their open tabs lose access at once.

Returns: member array

### `POST /api/team/invitations`

Owner, team mode: one-use invitation link (token after #, stored hashed), optional email, 5 minutes to 30 days; no email is sent.

Request body:

```json
{
  "email": "optional",
  "role": "editor",
  "expires_in_days": 7
}
```

Returns: {id,email,role,expires_at,url}

### `DELETE /api/team/invitations/{invite_id}`

Owner: revoke an open invitation.

Returns: {id,revoked:true}

### `GET /api/workspace/chats`

Chats of the workspace from the database (viewer); since=ms for changes only, summary=1 without messages.

Returns: {chats,imported_sources,role}

### `GET /api/workspace/chats/{chat_id}`

One chat with messages and authors.

Returns: chat

### `PUT /api/workspace/chats/{chat_id}`

Editor: create or replace a chat; a stale base_revision returns 409 with the stored chat to merge.

Request body:

```json
{
  "chat": {
    "id": "chat-1",
    "title": "Pricing",
    "messages": [
      {
        "role": "user",
        "content": "..."
      }
    ]
  },
  "base_revision": 3
}
```

Returns: chat with new revision

### `DELETE /api/workspace/chats/{chat_id}`

Delete a chat: its creator or an owner.

Returns: {id,deleted:true}

### `POST /api/workspace/chats/import`

Editor: one-time upload of a browser's localStorage chats; existing ids are skipped; once per browser id.

Request body:

```json
{
  "source": "browser id",
  "chats": []
}
```

Returns: {imported,skipped,already_imported}

### `GET /api/workspace/pins`

Your pinned runs in this workspace.

Returns: {pins}

### `PUT /api/workspace/pins`

Replace your pinned runs (only runs this workspace can see are kept).

Request body:

```json
{
  "pins": [
    "run_name"
  ]
}
```

Returns: {pins}

### `GET /api/workspace/preferences`

Workspace preferences (default_model) and yours (theme).

Returns: {workspace,user}

### `PUT /api/workspace/preferences`

Set preferences; workspace keys need an owner.

Request body:

```json
{
  "user": {
    "theme": "dark"
  }
}
```

Returns: {workspace,user}

### `GET /api/workspace/onboarding`

First-run steps done, whether a model is connected and who can connect one or invite.

Returns: {steps,workspace,model_connected,can_connect_model,can_invite,members,runs_in_workspace,mode,demo_url}

### `PUT /api/workspace/onboarding`

Editor: mark onboarding steps (workspace, model, invite, demo, dismissed).

Request body:

```json
{
  "steps": {
    "demo": true
  }
}
```

Returns: onboarding state

### `GET /api/workspace/runs-index`

Saved runs this workspace can see.

Returns: {runs}

### `POST /api/workspace/runs-index`

Editor: add a saved run (local caller: any run folder; team member: a run they already edit in another workspace).

Request body:

```json
{
  "name": "run_name"
}
```

Returns: {runs}

### `DELETE /api/workspace/runs-index/{name}`

Editor: remove a run from this workspace's list (the folder stays).

Returns: {runs}

## Tests on simulated people

### `POST /api/simulation/website-test`

Real-browser journeys by synthetic visitors with screenshots and supplied DOM outcome checks; background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "spec": {
    "url": "https://your-product.example",
    "goal": "add_to_cart",
    "max_personas": 3,
    "checks": [
      {
        "name": "cart_added",
        "selector": "[data-testid=cart-count]",
        "text": "1"
      }
    ],
    "goal_check": "cart_added",
    "observation_mode": "compact",
    "max_model_calls": 12,
    "max_input_tokens": 100000,
    "max_elapsed_s": 180
  }
}
```

Returns: {task_id, simulation_id, run_id}

### `GET /api/simulation/{simulation_id}/website-test`

Browser journey evidence; optional ?run_id=website_x selects the exact run.

Returns: website_test.json with sessions, summary, milestones and artifact paths

### `POST /api/simulation/feed-test`

Ads in realistic feeds (attention gate, split test, landing page, projections); background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "creatives": [
    {
      "id": "fb1",
      "platform": "facebook",
      "text": "..."
    }
  ],
  "landing": {},
  "benchmarks": {},
  "seeds": 3,
  "exposures": 2
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/feed-test`

Feed-test result.

Returns: feed_test.json

### `GET /api/simulation/provenance`

Models and engine commit a run records in run_manifest.json (no keys or endpoints).

Returns: {models: [{provider, model}], engine: {commit, local_changes}, at}

### `POST /api/simulation/questionnaire`

Your own questionnaire (scale, nps, choice, multi, open) answered by the saved personas, option order shuffled per person; background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "questions": [
    {
      "id": "trust",
      "text": "How much do you trust us?",
      "type": "scale",
      "low": 1,
      "high": 5
    }
  ],
  "people": 0,
  "segment": "",
  "seed": 7
}
```

Returns: {task_id, people, questions}

### `GET /api/simulation/{simulation_id}/questionnaire`

Questionnaire result: per-question distributions by segment, too-alike and position checks.

Returns: questionnaire.json

### `POST /api/simulation/email-test`

Email campaign test in simulated inboxes; background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "emails": [
    {
      "id": "a",
      "from_name": "Brand",
      "subject": "...",
      "body": "...",
      "send_time": "morning"
    }
  ],
  "list_size": 10000
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/email-test`

Email-test result.

Returns: email_test.json

### `POST /api/simulation/pitch`

Sales rehearsal: pitch every simulated buyer, then rebuttals; background task (needs a live environment).

Request body:

```json
{
  "simulation_id": "sim_x",
  "script": "...",
  "rebuttals": {
    "price": "...",
    "*": "..."
  },
  "channel": "dm"
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/pitch`

Pitch result.

Returns: pitch.json

### `POST /api/simulation/interview/batch`

Ask simulated people anything (the survey uses it); needs a live environment.

Request body:

```json
{
  "simulation_id": "sim_x",
  "interviews": [
    {
      "agent_id": 1,
      "prompt": "..."
    }
  ],
  "platform": "reddit"
}
```

Returns: {results:[{agent_id, response}]}

### `POST /api/simulation/ssr`

Free-text answers to 1-5 rating distributions (semantic similarity rating; engine embeddings, jev or auto).

Request body:

```json
{
  "items": [
    {
      "id": "1",
      "scale": "purchase",
      "text": "Maybe: if it is really free"
    }
  ],
  "engine": "embeddings"
}
```

Returns: {engine, method, model, counts, results:[{pmf, mean, sd}]}

### `POST /api/simulation/objection-check`

Jev labels survey objections; agreement with each person's own tag (Wilson 95% range). Needs a Jev key.

Request body:

```json
{
  "items": [
    {
      "id": "1",
      "text": "Not sure it is really free",
      "self_tag": "price"
    }
  ]
}
```

Returns: {agreement:{pct, lo, hi, k, n}, labelled, failed, model, usage}

## Inside the rounds

### `PUT /api/simulation/{simulation_id}/events`

Brand posts and scheduled launch events for the rounds.

Request body:

```json
{
  "posts": [
    {
      "agent": "Brand",
      "platform": "both",
      "content": "..."
    }
  ],
  "events": [
    {
      "round": 2,
      "agent": "Brand",
      "content": "..."
    }
  ]
}
```

Returns: {initial_posts, scheduled_events}

### `GET /api/simulation/{simulation_id}/events`

The configured posts and events.

Returns: {initial_posts, scheduled_events}

### `PUT /api/simulation/{simulation_id}/context`

Push live context into a running simulation (from the next round on).

Request body:

```json
{
  "text": "A competitor dropped its price",
  "source": "news",
  "round": 3
}
```

Returns: {context_updates, running}

### `GET /api/simulation/{simulation_id}/context`

Context updates on file.

Returns: {context_updates}

### `GET /api/simulation/{simulation_id}/feed-story`

Every post of the simulation with authors, rounds, likes, quotes, comments; brand posts strip.

Returns: feed_story.json

### `GET /api/simulation/{simulation_id}/memory`

Behaviour state across tests (?scope=, ?agent= for one person's memories).

Returns: {people, avg_trust, avg_familiarity, avg_fatigue, events}

### `POST /api/simulation/{simulation_id}/memory`

Record behaviour events (or survey answers) into a memory scope.

Request body:

```json
{
  "scope": "default",
  "events": [
    {
      "agent_id": 1,
      "test": "manual",
      "kind": "saw_brand_post",
      "text": "You saw the launch post."
    }
  ],
  "survey": {
    "responses": [],
    "offer": "..."
  }
}
```

Returns: {events_recorded, summary}

## Analysis and reports

### `POST /api/simulation/analyst-panel`

Independent anonymized analysts over the run's material; background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "material": {},
  "analysts": 5,
  "brief": "..."
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/analyst-panel`

Panel result.

Returns: analyst_panel.json

### `POST /api/simulation/market-report`

Plain-language report (one call, number-guarded); background task.

Request body:

```json
{
  "simulation_id": "sim_x",
  "material": {
    "summary": {}
  },
  "brand": "Brand"
}
```

Returns: {task_id}

### `GET /api/simulation/{simulation_id}/market-report`

Report result (sections, action_plan, markdown).

Returns: market_report.json

### `POST /api/simulation/ideas`

Next test ideas from real ad rows and a run (synchronous).

Request body:

```json
{
  "brand": "Brand",
  "ads": [
    {
      "Ad name": "A",
      "Spend": 100,
      "Impressions": 10000,
      "Clicks": 120
    }
  ],
  "run_summary": {},
  "profile": {}
}
```

Returns: {ideas, evidence, markdown}

### `POST /api/simulation/captions`

Platform-native captions from a brief (synchronous).

Request body:

```json
{
  "brief": "...",
  "platform": "instagram",
  "n": 6,
  "objections": []
}
```

Returns: {captions}

### `POST /api/simulation/study-report`

One-call report over a study summary (number-guarded).

Request body:

```json
{
  "summary": {},
  "brand": "Brand"
}
```

Returns: {markdown, method}

## Reliability and prediction

### `POST /api/simulation/actuals-import`

Normalize a local ads/email/website/CRM/survey CSV or JSON export with provenance.

Request body:

```json
{
  "file": "/path/to/export.csv",
  "source_type": "ads",
  "mapping": {
    "clicks": "Link clicks"
  },
  "market": "PH"
}
```

Returns: {file, observations, validation_errors, summary}

### `POST /api/simulation/holdout-backtest`

Compare calibrated persona predictions with no-persona baseline on held-out real experiments.

Request body:

```json
{
  "pairs": [
    {
      "sim": 2.0,
      "real": 1.0,
      "split": "train"
    }
  ]
}
```

Returns: {status, persona_mae, no_persona_baseline_mae}

### `POST /api/simulation/calibrate`

Synthetic panel vs real answers: overlap, per-audience verdicts, AIPW-corrected rate, PPI++ interval, answer spread (synchronous).

Request body:

```json
{
  "synthetic": [
    {
      "segment": "..",
      "country": "..",
      "gender": "..",
      "age": 30,
      "y": 1
    }
  ],
  "real": [],
  "key": "segment",
  "field": "would_convert",
  "halfwidth": 0.05,
  "budget": 100
}
```

Returns: {verdict, overlap, calibration, corrected, ppi (incl. allocation), spread}

### `POST /api/simulation/predict`

Predictions with intervals, scaled by the calibration store (synchronous).

Request body:

```json
{
  "brand": "Brand",
  "summary": {},
  "feed_test": {},
  "email_test": {},
  "targets": {
    "ctr": 2
  }
}
```

Returns: {predictions, calibrated}

### `POST /api/simulation/forecast`

30/60/90-day adoption forecast from the best ad and the rounds' word of mouth.

Request body:

```json
{
  "feed_test": {},
  "feed_story": {},
  "spend": 500,
  "days": 90
}
```

Returns: {curve, customers_total, cac, k_factor}

### `POST /api/simulation/calibration-pairs`

Store real-vs-simulated pairs (backtest, calibrate, your own stats).

Request body:

```json
{
  "brand": "Brand",
  "metric": "ctr",
  "pairs": [
    {
      "sim": 4.0,
      "real": 2.1,
      "label": "ad A"
    }
  ],
  "source": "backtest"
}
```

Returns: {stored}

### `GET /api/simulation/calibration-pairs`

Fits per metric (?brand=).

Returns: {pairs, brands, fits}

## Background tasks

### `POST /api/simulation/market-task/status`

Status of a background task.

Request body:

```json
{
  "task_id": "..."
}
```

Returns: {status, progress, message, result}

### `POST /api/simulation/spend-cap`

Arm a spend cap for a run (estimated US dollars; 409 while another run's cap is armed).

Request body:

```json
{
  "max_spend_usd": 5,
  "label": "mirofish_runs/acme",
  "replace": false
}
```

Returns: {cap_id, limit_usd, spent_usd, calls, reached, label}

### `GET /api/simulation/spend-cap`

The armed spend cap and what was spent (null when none).

Returns: {limit_usd, spent_usd, calls, input_tokens, output_tokens, reached}

### `DELETE /api/simulation/spend-cap`

Lift the spend cap (?cap_id= lifts only that cap); returns its final state.

Returns: {limit_usd, spent_usd, calls, reached}

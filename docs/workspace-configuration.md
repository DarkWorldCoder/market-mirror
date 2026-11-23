# Workspace projects and settings

The local chat workspace uses the same session token as `./mm app` and the setup wizard. Its project and settings routes accept requests from loopback addresses with `X-Setup-Token`. Settings writes also reject an `Origin` from another site. This is a single-computer workspace, not a hosted account or multi-user permission system.

## Projects

- `GET /api/workspace/projects` lists existing engine projects and their workspace metadata.
- `POST /api/workspace/projects` creates an engine project. Send `name` and optionally `description`, `instructions`, `chat_ids` and `run_names`.
- `GET /api/workspace/projects/<id>` returns one project.
- `PATCH /api/workspace/projects/<id>` replaces the supplied fields.
- `DELETE /api/workspace/projects/<id>` archives the workspace entry. Existing engine files, graph data and saved run evidence remain on disk.

Each response uses `{success: true, data: ...}`. Creation returns HTTP 201. Invalid fields return 400; missing or archived projects return 404. A project contains `id`, `engine_project_id`, `name`, `description`, `instructions`, `chat_ids`, `run_names`, `created_at` and `updated_at`.

Project names are required and limited to 120 characters. Descriptions allow 2,000 characters, and instructions allow 12,000. Chat and run associations allow 200 identifiers each. A run must already exist in the configured local runs directory. Associations do not copy chat messages or run files.

Workspace metadata is saved atomically in an owner-only `workspace.json` beside the engine's `project.json`. Existing engine projects appear with empty workspace fields until edited.

## Memory and Jev

`GET /api/workspace/settings` returns safe configuration and provider availability. `PUT` accepts partial `memory` and `jev` objects. Keys are write-only, and blank key inputs leave stored keys intact.

Supported memory fields:

| Field | Values |
| --- | --- |
| `backend` | `local`, `cognee`, `zep` |
| `embeddings` | Boolean |
| `extract_activity` | Boolean |
| `cognee_url` | HTTP or HTTPS URL without embedded credentials, query or fragment |
| `zep_api_key` | Write-only Zep Cloud key |

Local memory uses SQLite. Cognee requires a separately running sidecar. Zep requires a key before it can be selected. The engine has no native Supermemory adapter; the status response marks it unsupported.

Supported Jev fields:

| Field | Values |
| --- | --- |
| `route` | `typesafe`, `openrouter` |
| `model` | Native Jev model identifier; empty selects the route default |
| `parallel` | Integer 1–32 |
| `timeout` | Integer 5–600 seconds |
| `retries` | Integer 0–8 |
| `labels` | `auto`, `on`, `off` |
| `ssr_engine` | `embeddings`, `jev` |
| `api_key` | Write-only key for the selected route |

Jev is the existing decision and classification engine. It is separate from the conversational chat model. Selecting OpenRouter uses `OPENROUTER_API_KEY`, which is also used by other OpenRouter features in this workspace.

Saves use the setup wizard's atomic, owner-only `.env` writer. These settings and credentials belong to this computer and must not be committed. `connection_tested: false` means saving configuration has made no provider call. A configured key does not prove the account, entitlement or endpoint works.

Memory saves set `restart_required: true`. Restart `./mm app` before relying on changed memory behavior; active graph clients may retain their previous settings. Existing memory is not migrated or deleted. Jev reads saved settings for subsequent decisions. A manually configured `JEV_BASE_URL` remains in effect and is represented by `custom_endpoint` in the status response.

## Models and spending

The settings dialog also exposes API model configuration through `llm`: `provider`, `model`, `base_url`, write-only `api_key` and `pool`. Provider defaults come from the engine's installed model-pool catalog. Saving a provider replaces the default API target, removes the default login-gateway selection, and updates its named provider key, URL and model for pool use. Blank keys retain the selected provider's existing key; an unrelated gateway token is never reused. Ollama can use a local placeholder key. API URLs accept HTTP or HTTPS without embedded credentials, query parameters or fragments.

A pool accepts a comma-separated list such as `openai:model-id,claude`, `auto`, or JSON entries containing `provider`, `model` and `base_url`. Save API keys through their provider fields, not inline in pool JSON. Existing inline pool keys are omitted from responses. Changing only the pool preserves the default chat model; stages using the model pool may distribute work among its configured providers.

The `spending` object accepts `process_limit_usd`, `input_price_usd_per_mtok` and `output_price_usd_per_mtok`. The process limit sets the existing `MM_MAX_SPEND_USD` enforcement. Zero disables it. Input and output estimate prices set `MM_USD_PER_MTOK`; send both as `null` to restore the engine price table. Responses include the process's recorded usage and any currently armed shared run cap. Saving settings never resets recorded usage or arms, replaces or clears a run cap.

The process cap covers chat through `LLMClient` and other instrumented model calls. It checks before a request and charges estimated token usage after a response. Requests already in flight can exceed the limit, and a response without usage cannot be priced. Each server or subprocess keeps its own process counter, reset on restart. Direct Jev calls and external service/provider charges are outside this process cap. Set a per-run workflow budget when a shared cap across subprocesses is needed. These controls do not set a provider account billing limit.

## Discovering installed local models

`GET /api/workspace/local-models?refresh=1` explicitly reads installed model catalogs. The settings model panel can select an actual discovered identifier. It never invents model IDs or downloads a model.

Only HTTP loopback endpoints with ports from 1024 to 65535 and base paths `/` or `/v1` are eligible. The service uses fixed `/api/tags` (Ollama) and `/v1/models` requests, refuses redirects, limits catalog size, and returns no keys. Local desktop instances can check the known Ollama and LM Studio ports plus their configured local endpoint. When `MM_WORKER_SECRET` is present, default port probes are disabled and only explicitly configured worker-local endpoints are considered. A hosted worker cannot discover models on a visitor's computer.

The chat catalog can read `cached_local_models()` after explicit discovery; that helper never starts network discovery. Discovery metadata expires after five minutes. `key_for_local_model(base_url)` resolves a server-held credential only for a previously discovered endpoint. Custom OpenAI-compatible servers that do not require authentication use the client's local placeholder; it is not reported as a saved API credential.

## Project knowledge

Projects also contain `sources` and `preferred_model`. A source has an opaque ID, a name, plain text and its creation time. `POST /api/workspace/projects/<id>/sources` accepts `{name,text}`; `DELETE /api/workspace/projects/<id>/sources/<source_id>` removes one. Both return the updated project and preserve its other metadata.

Each project allows ten sources, at most 24,000 characters per source and 120,000 total. Requests have a separate 30 KB JSON body cap, so non-ASCII or escaped text may need smaller excerpts. Source text is stored in the same atomic owner-only workspace metadata file. No URL downloading, executable content processing or automatic model request happens when a source is saved.

The Project knowledge dialog can read local Markdown, TXT, CSV and JSON files as text, or save a typed note. It does not extract PDFs. Saving and removing a source updates the project immediately. Instruction and model preferences have a separate Save preferences action.

`preferred_model` accepts an empty value or an opaque `m_<24 hex characters>` server-catalog ID. It never accepts an API key or endpoint. Availability and actual model selection are checked against the server catalog when used. Saved source capacity is larger than the model context allowance; conversations include a bounded excerpt, not a guarantee that all saved material was read.

# Background jobs: the durable queue

Every long step (graph build, persona preparation, OASIS starts, feed test, survey, pitch, focus group,
questionnaire, choice tests, email test, analyst panel, market report, GTM suite, workflows) runs as a job in a durable
queue (`backend/app/jobs/`). Endpoints and their replies are unchanged: the job's id is the `task_id` the endpoint
already returned, and `POST /api/simulation/market-task/status`, `/prepare/status`, the graph and report task
endpoints and `run-status` work as before. The CLI and the MCP server need no change.

## What it gives you

| | |
|---|---|
| Durable | Jobs live in SQLite (WAL) next to the task store (`MM_TASK_DB_PATH`, or `MM_JOB_DB_PATH`). A restart does not lose queued work. |
| Status | queued, running, succeeded, failed, cancelled, needs_approval; attempts, model calls, queue place and wait, attempt history (`GET /api/jobs/<id>`). |
| Limits | Running jobs per model provider (`MM_JOB_LIMIT_PROVIDER`, default 4) and per workspace (`MM_JOB_LIMIT_WORKSPACE`, default 2; none for the local app's own workspace), counted across every process on the database. A job waits; it is never refused. |
| Spend cap | A job that spends fails before it starts when the spend cap (`app/utils/spend_cap.py`) is reached, with zero model calls. A job with an `estimate_usd` waits while it would not fit beside the jobs already spending. |
| Cancellation | `POST /api/jobs/<id>/cancel`: a queued job at once; a running one at its next model call or progress update. A cancelled market test writes no result and records no memory. |
| Retries | Only when the attempt made **no** model call and the error is transient (connection, timeout, 429/5xx), with backoff, up to `MM_JOB_MAX_ATTEMPTS` (3). |
| No silent re-spend | A job interrupted or failed after model calls goes to `needs_approval`. It runs again only after `POST /api/jobs/<id>/retry {"approve_spend": true}`. The sales rehearsal (pitch) pays for interviews inside the OASIS subprocess, where calls cannot be counted, so an interrupted pitch always waits for approval. Jev labelling calls are counted like model calls. |
| Recovery | A worker is dead when its pid is gone (same host, seen at once) or, on another host, its heartbeat is older than two leases (`MM_JOB_LEASE_S`, 60 s). A live process on the same host keeps its jobs even after a long pause such as laptop sleep. Any live process then requeues a dead worker's job (no model call yet), holds it for approval (calls made), cancels it (cancel was requested), or fails it (its work lived only in the dead process). A worker whose job was taken over this way drops its own outcome. |
| Workers | The server runs `MM_JOB_WORKERS` threads (default 4). More processes: `python -m app.jobs.worker`. |

Workspaces come from the `X-MM-Workspace` header or a `workspace_id` in the body (default `local`), so a login and
teams layer only has to set that header.

## Why SQLite and not Redis/RQ, Celery or Postgres (for now)

- The local app stays one command. No broker to install or run.
- A claim is one `BEGIN IMMEDIATE` transaction. SQLite serialises those across processes, so worker processes on one
  host never take the same job. Jobs last seconds to hours and claims are a few per second at most. SQLite handles
  far more than that (the load test below claims about 5 jobs a second across 4 processes with no claim errors).
- Admission needs the full picture at claim time: running jobs per provider, per workspace and per lane, the spend
  cap, and the OASIS runner's live round count. Here that is one query. RQ or Celery would need a second store for
  the same check.
- RQ wants picklable callables. Our work is closures over request data that has already been validated. Instead a
  job keeps its request and any worker re-runs the endpoint (below).

The limit is one host (or one shared disk). For several hosts, the same claim works on Postgres with `SELECT ... FOR
UPDATE SKIP LOCKED`, and only `app/jobs/store.py` changes. That backend is **not built yet**.

## How a job runs

1. The endpoint validates the request, creates its task as before and calls `jobs.submit(task_id, closure, ...)`.
2. The job row stores kind, workspace, provider, lane and, for endpoint jobs, the request (method, path, JSON body,
   `Accept-Language`, `X-MM-Workspace`).
3. By default the server binds the closure to its own runner and runs it when the limits allow.
4. With `MM_JOB_EXTERNAL_WORKERS=1`, endpoint jobs are left unbound. A worker process (or the server after a
   restart) **replays** the request through Flask's test client with a job context on its thread.
   `TaskManager.create_task()` then returns the job's own id, `jobs.submit()` runs the closure inline, and auth and
   rate limits are skipped for that in-process call only. A contextvar marks it, and no client can set one. The
   endpoint validates again, so a job whose simulation was deleted fails cleanly.
5. Model calls are counted per job through `spend_cap.check()`, which every call runs first. The first call of an
   attempt is written at once, so a crash right after it can never look like a job that spent nothing. Thread pools
   inside a job inherit its context. A call from a bare thread counts against every job running in that process,
   which over-counts on purpose: the only effect is asking for approval instead of retrying.

Jobs that can only run where they started (prepare, graph build, report, workflows, website test) keep their closure
in the server. After a crash they fail with a clear message instead of re-running.

A job failed at admission (spend cap reached) has its task marked failed at once, so pollers stop.

## The OASIS runner: one process, queued runs

OASIS runs are subprocesses with monitor threads and live IPC owned by the server, so the runner stays in a single
process. Instead of more runners, starts are queued:

- At most `MM_OASIS_MAX_RUNS` runs (default 2) play rounds at a time. A finished run that is kept alive for interviews
  does not count.
- `POST /api/simulation/start` on a full runner returns `success: true` with `runner_status: "queued"`, `job_id` and
  `queue_position`. `run-status` shows `queued` until it starts. The CLI's `wait_run` keeps polling, as it already
  does for any non-final status.
- Starts are first come, first served, in the `oasis` lane. Only the server takes that lane. It re-runs the start
  request as soon as a slot frees.
- Repeating `start` returns the same queued job (`force: true` replaces it). `stop` on a queued run cancels it, also
  while the queue is beginning it: the re-run checks under the same lock that the run is still queued.
- A queued start that fails, is cancelled or is held for approval sets run-status to `failed` or `stopped`, never
  leaving it at `queued`.
- Direct and queued starts share one lock, so the slot check and the start are atomic in the server. A queued start
  whose slot was taken goes back in line without using an attempt.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `MM_JOB_WORKERS` | 4 | job threads in the server (at least 1) |
| `MM_JOB_EXTERNAL_WORKERS` | off | `1`: leave endpoint jobs to worker processes (the server keeps closure-only jobs and the oasis lane) |
| `MM_JOB_LIMIT_PROVIDER` | `*=4` | running jobs per provider, e.g. `claude=6,openai=8,*=4`; 0 = no limit |
| `MM_JOB_LIMIT_WORKSPACE` | `local=0` (others 2) | running jobs per workspace, e.g. `acme=6,*=2`; the local app's own workspace `local` has no cap unless set |
| `MM_JOB_LIMIT_LANE` | none | running jobs per lane |
| `MM_OASIS_MAX_RUNS` | 2 | OASIS runs playing rounds at a time |
| `MM_JOB_MAX_ATTEMPTS` | 3 | attempts per job (automatic retries only without model calls) |
| `MM_JOB_LEASE_S` | 60 | lease length; a dead worker's jobs are recovered after it (sooner on the same host) |
| `MM_JOB_DB_PATH` | `MM_TASK_DB_PATH` | queue database |
| `MM_JOB_STOP_GRACE` | 30 | seconds a worker waits for running jobs on SIGTERM |

Job limits cap how many jobs run at once. Inside a job, the provider pool still handles 429s and failover per call.

## Running more workers

```bash
MM_JOB_EXTERNAL_WORKERS=1 backend/claude_cli/start_server.sh
cd backend && uv run --no-sync python -m app.jobs.worker --threads 4     # as many as the host carries
```

Workers read the same `.env` and database as the server. `GET /api/jobs/stats` lists live workers, counts, running
jobs per provider, workspace and lane, and queue waits over the last hour.

## Load test (fake LLM, no spend)

`backend/scripts/load_test_jobs.py` starts a fake OpenAI-compatible server (0.25 s per call), writes small
simulations (8 personas each), starts the backend with `MM_JOB_EXTERNAL_WORKERS=1` plus worker processes, fires
questionnaire runs at once across three workspaces, then **SIGKILLs one worker and the server mid-run and restarts
them**. The child processes get a clean environment and a fake `.env`, so no real key can be used.

```bash
cd backend && uv run --no-sync python scripts/load_test_jobs.py --runs 60 --sims 10 --workers 3
```

Results on a laptop (2026-11-23, 12 threads, provider limit 4, workspace limit 2):

| | 24 runs, 2 workers | 60 runs, 3 workers |
|---|---|---|
| Lost jobs | 0 | 0 |
| Interrupted by the kill after model calls | 1, held for approval, then succeeded once approved | 3, same |
| Requeued or retried without approval | 0 | 0 |
| Final | 24 succeeded | 60 succeeded |
| Task status matches job status | yes | yes |
| Wall time (including the crash and restart) | 7.8 s | 12.8 s |
| Throughput | 186 runs/min | 281 runs/min |
| Queue wait p50 / p95 / max | 2.1 / 4.2 / 4.4 s | 5.5 / 9.1 / 9.6 s |
| Peak running per provider (limit 4) | 4 | 4 |
| Peak running per workspace (limit 2) | 2 | 2 |
| Fake model requests / recorded model calls | 196 / 193 | 498 / 495 |

The recorded model calls run a little below the fake server's count only for attempts killed mid-run. Their first
call is recorded at once (that is what blocks an automatic retry); the rest would have been written at the next lease
renewal. These are queue numbers on a fake model, not model speed: real runs are bound by the provider's latency and
rate limits.

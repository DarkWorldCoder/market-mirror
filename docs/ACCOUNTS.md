# Accounts, workspaces and teams

MarketMirror runs in one of two modes.

| | Local mode (default) | Team mode (`MM_ACCOUNTS=on`) |
|---|---|---|
| Who signs in | Nobody. The browser on this computer uses the setup token from `./mm app` | People with an email and password |
| Who can reach it | Loopback only (`127.0.0.1`, `::1`) | Anyone who can reach the server, through HTTPS |
| Workspaces | One built-in workspace (`ws_local`) | As many as people create; each has members with roles |
| Where chats, projects, pins and the run index live | The database (`backend/uploads/marketmirror.db`) | The database (SQLite, or Postgres with `MM_DATABASE_URL`) |
| Model and provider keys | `.env`, changed through Settings on this computer | `.env` on the server, changed only on that computer with `./mm setup` |

Local mode works exactly as before: no account, no password, loopback plus the setup token. Team mode is opt-in, and nothing in it relaxes the local checks: the setup page, gateways, connectors, browser tools and workflows still answer only to the setup token on loopback.

## Design note: finish `cloud/` or build accounts into the Flask app

`cloud/` (in the owner's checkout, not on any branch) is a separate account gateway. It keeps accounts, sessions and invitations in its own SQLite file, starts one engine container per workspace through the Docker socket, proxies every request to that container and stores each workspace's chats as one JSON blob with a revision number.

**Option A: publish and finish `cloud/`.**
Strong points: real per-workspace isolation (each workspace has its own engine process, `.env`, uploads and spending limit), a reviewed set of security checks (exact-Origin writes, CSRF header, 20-per-15-minute login throttle, stale-tab binding, provider URL allowlist), a fixed-model broker with durable spending reservations, and Stripe credit packs.
Weak points: it only exists as a hosted deployment. The local app gets nothing from it: chats stay in `localStorage`, projects stay in loose files. It needs Docker, a privileged control plane and a domain to run at all. Roles are owner/member only. Chats are a single 4 MB JSON document per workspace, so every save rewrites everything and two teammates conflict on any change. Passwords use PBKDF2 rather than a memory-hard hash. There is no migration framework and no Postgres path.

**Option B: a fresh auth layer inside the Flask app.**
Strong points: one data model for both modes, so the local app gets a real database the same day; per-chat rows and revisions, so teammates only conflict when they edit the same chat; three roles enforced on the server; versioned migrations that run on SQLite and Postgres; tests run with the existing backend suite.
Weak points: one Flask process shares one engine configuration (one provider key, one spending limit) across all its workspaces. That is fine for one organisation running its own server, but it is not tenant isolation for strangers paying for a public service.

**Recommendation: B now, and keep `cloud/` unpublished as the isolation layer for a later public service.**
This branch builds B and ports the parts of `cloud/` that were already right: exact-Origin and CSRF checks on writes, hashed opaque session and invitation tokens, the login throttle, one-use invitations bound to an optional email, and the `{chats, revision}` style of conflict detection (now per chat). If you later sell hosted accounts to the public, put `cloud/`'s per-workspace workers in front of B: the gateway keeps routing and isolation, the workers keep their engine settings, and account data moves to this schema instead of `cloud/`'s own tables. Whether `cloud/` gets published at all is your call; this branch does not include or change it.

## Turning on team mode

```bash
# .env on the server
MM_ACCOUNTS=on
MM_PUBLIC_ORIGIN=https://mm.example.com     # the exact origin people open; required in production
MM_DATABASE_URL=postgresql://mm:...@db/mm   # optional; SQLite in backend/uploads is the default
MM_SIGNUPS=invite                           # open | invite (default) | closed
```

The first account on a fresh database may always be created; it owns the first workspace. After that, `MM_SIGNUPS=invite` lets only people with a valid invitation link sign up. Put the server behind HTTPS: session cookies are marked `Secure` whenever the request or `MM_PUBLIC_ORIGIN` uses HTTPS, or always with `MM_ENV=production`.

Postgres needs `psycopg` (`uv pip install "psycopg[binary]"`). Migrations run on start and can also be run by hand:

```bash
cd backend && uv run --no-sync python -m app.db.cli migrate
uv run --no-sync python -m app.db.cli status
uv run --no-sync python -m app.db.cli reset-password person@example.com   # prompts for the new password
```

## Roles

| Action | Viewer | Editor | Owner |
|---|---|---|---|
| Read chats, projects, saved runs in the workspace | yes | yes | yes |
| Ask the model, create and edit chats and projects | | yes | yes |
| Delete a chat or archive a project | own | own | any |
| Pin runs (pins are per person) | yes | yes | yes |
| Add or remove runs in the workspace's run list | | yes | yes |
| Invite people, change roles, remove members, rename the workspace | | | yes |

A workspace always keeps at least one owner. Members can leave a workspace; the last owner cannot.

Engine settings (model, provider keys, memory backend, spending limits, gateways, connectors) are not workspace settings. They belong to the server and stay in `.env`, changed only on that computer with `./mm setup`. Onboarding shows whether a model is connected and says who can connect one.

## Security

- **Passwords**: argon2id (`argon2-cffi`, library defaults), 12 to 256 characters. Unknown emails still run a hash check so timing does not reveal which emails exist.
- **Sessions**: a random 256-bit token in an `HttpOnly`, `SameSite=Lax` cookie (`mm_session`); only its SHA-256 is stored. Sessions last 14 days, are replaced on every sign-in and are deleted on sign-out, on password reset and when a member is removed.
- **CSRF**: every write from a signed-in browser needs the `X-CSRF-Token` header that `/api/auth/session` returns (stored per session) and an `Origin` equal to `MM_PUBLIC_ORIGIN` (or the request host). Reads never change data.
- **Workspace binding**: every workspace request carries `X-MM-Workspace`; the server checks the signed-in person is a member with the needed role. A tab left open after switching workspaces gets 409 instead of writing to the wrong one.
- **Rate limits**: at most 10 failed sign-ins per email and 30 sign-in or sign-up attempts per client address in 15 minutes (429 after that), counted in the database so restarts and several processes share the count.
- **Invitations**: 256-bit random tokens, stored hashed, one use, 7 days by default (5 minutes to 30 days), revocable, optionally bound to one email. Links put the token after `#`, so it does not reach server logs. No email is sent; the owner copies the link.
- **Local mode**: session cookies are ignored when `MM_ACCOUNTS` is off. The setup token is still required on loopback for every workspace route.

Not done yet, and needed before public sign-ups: email verification, password reset by email, account deletion and export, and per-workspace engine isolation (see the design note).

## Data and migrations

Tables: `users`, `sessions`, `workspaces`, `memberships`, `invitations`, `projects`, `project_sources`, `project_runs`, `chats`, `chat_messages`, `run_index`, `pins`, `preferences`, `auth_attempts`, `data_imports`, `schema_migrations`. Migrations live in `backend/app/db/migrations/` as numbered SQL files written to run unchanged on SQLite and Postgres; `schema_migrations` records each one with a checksum, and a changed file stops the start-up instead of running twice.

What moves where:

- **Chats** (`localStorage` key `mm-conversations-v1`): the first time the app opens a workspace it uploads the browser's chats once (`POST /api/workspace/chats/import`, existing IDs are skipped). After that the database is the source and the browser keeps a cache. Each chat has its own revision; a stale save gets 409 and the app merges messages by ID before saving again.
- **Pins** (`mm-pinned-runs`): imported once, then stored per person and workspace.
- **Projects** (`uploads/projects/<id>/workspace.json`): imported into the local workspace on first use. The engine's own `project.json` files are left alone.
- **Saved runs**: run folders stay on disk. `run_index` records which runs each workspace can see. In local mode every run folder is visible. In team mode a workspace sees only the runs in its index; runs are added from this computer (`python -m app.db.cli share-run`) or by an editor who already sees the run in another workspace.
- **Preferences**: per-workspace default model and per-person appearance.
- **Onboarding**: which steps each workspace has finished.

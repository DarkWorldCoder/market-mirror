-- Accounts, workspaces, roles and the workspace data that used to live in the browser or loose files.
-- Written to run unchanged on SQLite and Postgres: TEXT ids, BIGINT millisecond timestamps, JSON kept as TEXT.

CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  password_hash TEXT,
  is_local INTEGER NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  last_login_at BIGINT,
  password_changed_at BIGINT
);

CREATE TABLE workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  onboarding TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE memberships (
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
  created_at BIGINT NOT NULL,
  PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX memberships_user ON memberships (user_id);

CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
  csrf_token TEXT NOT NULL,
  created_at BIGINT NOT NULL,
  expires_at BIGINT NOT NULL,
  last_seen_at BIGINT NOT NULL
);
CREATE INDEX sessions_user ON sessions (user_id);
CREATE INDEX sessions_expiry ON sessions (expires_at);

CREATE TABLE invitations (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  email TEXT,
  role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
  created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at BIGINT NOT NULL,
  expires_at BIGINT NOT NULL,
  accepted_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  accepted_at BIGINT,
  revoked_at BIGINT
);
CREATE INDEX invitations_workspace ON invitations (workspace_id);

CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  instructions TEXT NOT NULL DEFAULT '',
  preferred_model TEXT NOT NULL DEFAULT '',
  created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  archived_at BIGINT
);
CREATE INDEX projects_workspace ON projects (workspace_id, updated_at);

CREATE TABLE project_sources (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  body TEXT NOT NULL,
  position INTEGER NOT NULL,
  created_at BIGINT NOT NULL
);
CREATE INDEX project_sources_project ON project_sources (project_id, position);

CREATE TABLE project_links (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('chat', 'run')),
  ref TEXT NOT NULL,
  position INTEGER NOT NULL,
  PRIMARY KEY (project_id, kind, ref)
);

CREATE TABLE chats (
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  custom_title TEXT,
  project_id TEXT,
  run_name TEXT,
  model TEXT,
  options TEXT NOT NULL DEFAULT '{}',
  created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (workspace_id, id)
);
CREATE INDEX chats_recent ON chats (workspace_id, updated_at);

CREATE TABLE chat_messages (
  workspace_id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  author_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  extra TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (workspace_id, chat_id, position),
  FOREIGN KEY (workspace_id, chat_id) REFERENCES chats(workspace_id, id) ON DELETE CASCADE
);

CREATE TABLE run_index (
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  run_name TEXT NOT NULL,
  added_by TEXT REFERENCES users(id) ON DELETE SET NULL,
  added_at BIGINT NOT NULL,
  PRIMARY KEY (workspace_id, run_name)
);

CREATE TABLE pins (
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  run_name TEXT NOT NULL,
  position INTEGER NOT NULL,
  PRIMARY KEY (workspace_id, user_id, run_name)
);

CREATE TABLE preferences (
  scope TEXT NOT NULL CHECK (scope IN ('workspace', 'user')),
  owner_id TEXT NOT NULL,
  pref_key TEXT NOT NULL,
  value TEXT NOT NULL,
  updated_at BIGINT NOT NULL,
  PRIMARY KEY (scope, owner_id, pref_key)
);

CREATE TABLE auth_attempts (
  id TEXT PRIMARY KEY,
  key_hash TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at BIGINT NOT NULL
);
CREATE INDEX auth_attempts_lookup ON auth_attempts (key_hash, kind, created_at);

CREATE TABLE data_imports (
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  item_count INTEGER NOT NULL,
  created_at BIGINT NOT NULL,
  PRIMARY KEY (workspace_id, user_id, source)
);

"""Data access for accounts, workspaces and workspace data. Every function takes an open transaction.

Nothing here checks who is asking: the API layer resolves the person and their role first (app/auth.py) and
only then calls these functions with the workspace id it has verified.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import Connection, Database, now_ms

LOCAL_USER = "usr_local"
LOCAL_WORKSPACE = "ws_local"
LOCAL_EMAIL = "local@marketmirror.invalid"
ROLES = ("viewer", "editor", "owner")
RANK = {role: index for index, role in enumerate(ROLES, start=1)}
SESSION_TTL_MS = 14 * 24 * 3600 * 1000
INVITE_TTL_S = 7 * 24 * 3600
MAX_ACTIVE_INVITES = 50
MAX_CHATS = 5000
MAX_MESSAGES = 1000
MAX_MESSAGE_CHARS = 200_000
MAX_EXTRA_BYTES = 400_000
MAX_CHAT_BYTES = 4 * 1024 * 1024

CHAT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
MESSAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
ROLE_NAME = re.compile(r"^[a-z][a-z_]{0,19}$")
EMAIL = re.compile(r"^[^\s@]{1,128}@[^\s@]{1,128}\.[^\s@]{1,64}$")
_CHAT_FIELDS = {"id", "title", "customTitle", "project", "run", "model", "updated", "messages", "revision",
                "created", "createdBy", "updatedBy"}
_MESSAGE_FIELDS = {"id", "role", "content", "author"}


class Conflict(Exception):
    def __init__(self, message: str, current: Any = None):
        super().__init__(message)
        self.current = current


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_id(prefix: str) -> str:
    return prefix + "_" + secrets.token_hex(12)


def iso(ms: Optional[int]) -> Optional[str]:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat() if ms is not None else None


def from_iso(value: Any, default: int) -> int:
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return default


def normalize_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if not EMAIL.fullmatch(email):
        raise ValueError("Enter a valid email address")
    return email


def clean_name(value: Any, field: str, maximum: int = 80, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError(f"{field} must be one line of at most {maximum} characters")
    value = value.strip()
    if required and not value:
        raise ValueError(f"Enter a {field.lower()}")
    return value


# ---------------------------------------------------------------------------------------------- local workspace

def ensure_local_workspace(db: Database) -> None:
    """The built-in owner and workspace used by the single-user local app (setup token on loopback)."""
    with db.transaction() as conn:
        stamp = now_ms()
        conn.execute("INSERT INTO users (id, email, name, password_hash, is_local, created_at) VALUES (?, ?, ?, NULL, 1, ?) "
                     "ON CONFLICT (id) DO NOTHING", (LOCAL_USER, LOCAL_EMAIL, "This computer", stamp))
        conn.execute("INSERT INTO workspaces (id, name, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?) "
                     "ON CONFLICT (id) DO NOTHING", (LOCAL_WORKSPACE, "This computer", LOCAL_USER, stamp, stamp))
        conn.execute("INSERT INTO memberships (workspace_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?) "
                     "ON CONFLICT (workspace_id, user_id) DO NOTHING", (LOCAL_WORKSPACE, LOCAL_USER, stamp))


# ---------------------------------------------------------------------------------------------- users

def public_user(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {"id": row["id"], "email": row["email"], "name": row.get("name") or ""}


def count_people(conn: Connection) -> int:
    return int(conn.scalar("SELECT count(*) AS n FROM users WHERE is_local=0") or 0)


def create_user(conn: Connection, email: str, name: str, password_hash: str) -> Dict[str, Any]:
    if conn.one("SELECT id FROM users WHERE email=?", (email,)):
        raise Conflict("An account already uses this email. Sign in instead.")
    user_id = new_id("usr")
    stamp = now_ms()
    conn.execute("INSERT INTO users (id, email, name, password_hash, is_local, created_at, password_changed_at) "
                 "VALUES (?, ?, ?, ?, 0, ?, ?)", (user_id, email, name, password_hash, stamp, stamp))
    return conn.one("SELECT * FROM users WHERE id=?", (user_id,))


def user_by_email(conn: Connection, email: str) -> Optional[Dict[str, Any]]:
    return conn.one("SELECT * FROM users WHERE email=? AND is_local=0", (email,))


def user_by_id(conn: Connection, user_id: str) -> Optional[Dict[str, Any]]:
    return conn.one("SELECT * FROM users WHERE id=?", (user_id,))


def set_password(conn: Connection, user_id: str, password_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash=?, password_changed_at=? WHERE id=? AND is_local=0",
                 (password_hash, now_ms(), user_id))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def touch_login(conn: Connection, user_id: str) -> None:
    conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now_ms(), user_id))


# ---------------------------------------------------------------------------------------------- workspaces

def create_workspace(conn: Connection, name: str, owner_id: str) -> Dict[str, Any]:
    workspace_id = new_id("ws")
    stamp = now_ms()
    conn.execute("INSERT INTO workspaces (id, name, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                 (workspace_id, name, owner_id, stamp, stamp))
    conn.execute("INSERT INTO memberships (workspace_id, user_id, role, created_at) VALUES (?, ?, 'owner', ?)",
                 (workspace_id, owner_id, stamp))
    return {"id": workspace_id, "name": name, "role": "owner"}


def workspace(conn: Connection, workspace_id: str) -> Optional[Dict[str, Any]]:
    row = conn.one("SELECT * FROM workspaces WHERE id=?", (workspace_id,))
    if row:
        row["onboarding"] = _json(row.get("onboarding"), {})
    return row


def workspaces_for(conn: Connection, user_id: str) -> List[Dict[str, Any]]:
    return conn.all("SELECT w.id, w.name, m.role FROM memberships m JOIN workspaces w ON w.id=m.workspace_id "
                    "WHERE m.user_id=? ORDER BY w.created_at, w.id", (user_id,))


def role_in(conn: Connection, workspace_id: str, user_id: str) -> Optional[str]:
    row = conn.one("SELECT role FROM memberships WHERE workspace_id=? AND user_id=?", (workspace_id, user_id))
    return row["role"] if row else None


def rename_workspace(conn: Connection, workspace_id: str, name: str) -> None:
    conn.execute("UPDATE workspaces SET name=?, updated_at=? WHERE id=?", (name, now_ms(), workspace_id))


def set_onboarding(conn: Connection, workspace_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
    current = workspace(conn, workspace_id)["onboarding"]
    current.update(values)
    conn.execute("UPDATE workspaces SET onboarding=?, updated_at=? WHERE id=?",
                 (json.dumps(current), now_ms(), workspace_id))
    return current


def members(conn: Connection, workspace_id: str) -> List[Dict[str, Any]]:
    rows = conn.all("SELECT u.id, u.email, u.name, u.is_local, m.role, m.created_at FROM memberships m "
                    "JOIN users u ON u.id=m.user_id WHERE m.workspace_id=? ORDER BY m.created_at, u.email",
                    (workspace_id,))
    return [{"id": r["id"], "email": "" if r["is_local"] else r["email"], "name": r["name"], "role": r["role"],
             "joined_at": iso(r["created_at"])} for r in rows]


def _owners(conn: Connection, workspace_id: str) -> int:
    return int(conn.scalar("SELECT count(*) AS n FROM memberships WHERE workspace_id=? AND role='owner'",
                           (workspace_id,)) or 0)


def set_role(conn: Connection, workspace_id: str, user_id: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError("Role must be owner, editor or viewer")
    current = role_in(conn, workspace_id, user_id)
    if not current:
        raise LookupError("Member not found")
    if current == "owner" and role != "owner" and _owners(conn, workspace_id) <= 1:
        raise Conflict("A workspace needs at least one owner. Make someone else an owner first.")
    conn.execute("UPDATE memberships SET role=? WHERE workspace_id=? AND user_id=?", (role, workspace_id, user_id))


def remove_member(conn: Connection, workspace_id: str, user_id: str) -> None:
    current = role_in(conn, workspace_id, user_id)
    if not current:
        raise LookupError("Member not found")
    if current == "owner" and _owners(conn, workspace_id) <= 1:
        raise Conflict("A workspace needs at least one owner. Make someone else an owner first.")
    conn.execute("DELETE FROM memberships WHERE workspace_id=? AND user_id=?", (workspace_id, user_id))
    conn.execute("DELETE FROM pins WHERE workspace_id=? AND user_id=?", (workspace_id, user_id))
    # Their open tabs lose this workspace at once instead of at the next sign-in.
    conn.execute("UPDATE sessions SET workspace_id=NULL WHERE user_id=? AND workspace_id=?", (user_id, workspace_id))


# ---------------------------------------------------------------------------------------------- sessions

def create_session(conn: Connection, user_id: str, workspace_id: Optional[str]) -> Tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    stamp = now_ms()
    conn.execute("DELETE FROM sessions WHERE expires_at<?", (stamp,))
    conn.execute("INSERT INTO sessions (token_hash, user_id, workspace_id, csrf_token, created_at, expires_at, last_seen_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?)", (token_hash(token), user_id, workspace_id, csrf, stamp,
                                                  stamp + SESSION_TTL_MS, stamp))
    return token, csrf


def session(conn: Connection, token: str) -> Optional[Dict[str, Any]]:
    if not token or len(token) > 200:
        return None
    row = conn.one("SELECT s.token_hash, s.user_id, s.workspace_id, s.csrf_token, s.expires_at, s.last_seen_at, "
                   "u.email, u.name FROM sessions s JOIN users u ON u.id=s.user_id "
                   "WHERE s.token_hash=? AND s.expires_at>? AND u.is_local=0", (token_hash(token), now_ms()))
    if row and now_ms() - row["last_seen_at"] > 60_000:
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (now_ms(), row["token_hash"]))
    return row


def select_session_workspace(conn: Connection, hashed: str, workspace_id: Optional[str]) -> None:
    conn.execute("UPDATE sessions SET workspace_id=? WHERE token_hash=?", (workspace_id, hashed))


def delete_session(conn: Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))


# ---------------------------------------------------------------------------------------------- invitations

def create_invitation(conn: Connection, workspace_id: str, email: Optional[str], role: str, created_by: str,
                      ttl_s: int = INVITE_TTL_S) -> Tuple[str, Dict[str, Any]]:
    if role not in ROLES:
        raise ValueError("Role must be owner, editor or viewer")
    stamp = now_ms()
    active = conn.scalar("SELECT count(*) AS n FROM invitations WHERE workspace_id=? AND accepted_at IS NULL "
                         "AND revoked_at IS NULL AND expires_at>?", (workspace_id, stamp))
    if int(active or 0) >= MAX_ACTIVE_INVITES:
        raise Conflict(f"{MAX_ACTIVE_INVITES} invitations are already open. Revoke one first.")
    token = secrets.token_urlsafe(32)
    invite_id = new_id("inv")
    conn.execute("INSERT INTO invitations (id, workspace_id, token_hash, email, role, created_by, created_at, expires_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (invite_id, workspace_id, token_hash(token), email or None, role,
                                                     created_by, stamp, stamp + ttl_s * 1000))
    return token, _invite(conn.one("SELECT * FROM invitations WHERE id=?", (invite_id,)))


def _invite(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": row["id"], "email": row["email"], "role": row["role"], "created_at": iso(row["created_at"]),
            "expires_at": iso(row["expires_at"])}


def invitations(conn: Connection, workspace_id: str) -> List[Dict[str, Any]]:
    rows = conn.all("SELECT * FROM invitations WHERE workspace_id=? AND accepted_at IS NULL AND revoked_at IS NULL "
                    "AND expires_at>? ORDER BY created_at DESC", (workspace_id, now_ms()))
    return [_invite(row) for row in rows]


def revoke_invitation(conn: Connection, workspace_id: str, invite_id: str) -> None:
    changed = conn.execute("UPDATE invitations SET revoked_at=? WHERE id=? AND workspace_id=? AND accepted_at IS NULL "
                           "AND revoked_at IS NULL", (now_ms(), invite_id, workspace_id)).rowcount
    if not changed:
        raise LookupError("Invitation not found")


def invitation(conn: Connection, token: str) -> Optional[Dict[str, Any]]:
    """The open invitation for this token, or None when it is unknown, used, revoked or expired."""
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        return None
    row = conn.one("SELECT i.*, w.name AS workspace_name FROM invitations i JOIN workspaces w ON w.id=i.workspace_id "
                   "WHERE i.token_hash=?", (token_hash(token),))
    if not row or row["accepted_at"] or row["revoked_at"] or row["expires_at"] <= now_ms():
        return None
    return row


def accept_invitation(conn: Connection, token: str, user: Dict[str, Any]) -> Dict[str, Any]:
    row = invitation(conn, token)
    if not row:
        raise LookupError("This invitation has expired, was revoked or was already used.")
    if row["email"] and row["email"] != user["email"]:
        raise PermissionError("This invitation is for another email address. Sign in with that address.")
    current = role_in(conn, row["workspace_id"], user["id"])
    if current is None:
        conn.execute("INSERT INTO memberships (workspace_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
                     (row["workspace_id"], user["id"], row["role"], now_ms()))
    elif RANK[row["role"]] > RANK[current]:
        conn.execute("UPDATE memberships SET role=? WHERE workspace_id=? AND user_id=?",
                     (row["role"], row["workspace_id"], user["id"]))
    changed = conn.execute("UPDATE invitations SET accepted_by=?, accepted_at=? WHERE id=? AND accepted_at IS NULL",
                           (user["id"], now_ms(), row["id"])).rowcount
    if not changed:
        raise LookupError("This invitation was already used.")
    return {"id": row["workspace_id"], "name": row["workspace_name"],
            "role": role_in(conn, row["workspace_id"], user["id"])}


# ---------------------------------------------------------------------------------------------- rate limiting

def record_attempt(conn: Connection, key: str, kind: str) -> None:
    stamp = now_ms()
    conn.execute("DELETE FROM auth_attempts WHERE created_at<?", (stamp - 24 * 3600 * 1000,))
    conn.execute("INSERT INTO auth_attempts (id, key_hash, kind, created_at) VALUES (?, ?, ?, ?)",
                 (secrets.token_hex(12), token_hash(key), kind, stamp))


def attempts(conn: Connection, key: str, kind: str, window_s: int) -> int:
    return int(conn.scalar("SELECT count(*) AS n FROM auth_attempts WHERE key_hash=? AND kind=? AND created_at>?",
                           (token_hash(key), kind, now_ms() - window_s * 1000)) or 0)


def clear_attempts(conn: Connection, key: str, kind: str) -> None:
    conn.execute("DELETE FROM auth_attempts WHERE key_hash=? AND kind=?", (token_hash(key), kind))


# ---------------------------------------------------------------------------------------------- projects

def _project(conn: Connection, row: Dict[str, Any]) -> Dict[str, Any]:
    links = conn.all("SELECT kind, ref FROM project_links WHERE project_id=? ORDER BY position", (row["id"],))
    sources = conn.all("SELECT id, name, body, created_at FROM project_sources WHERE project_id=? ORDER BY position",
                       (row["id"],))
    return {"id": row["id"], "engine_project_id": row["id"], "name": row["name"], "description": row["description"],
            "instructions": row["instructions"], "preferred_model": row["preferred_model"],
            "chat_ids": [link["ref"] for link in links if link["kind"] == "chat"],
            "run_names": [link["ref"] for link in links if link["kind"] == "run"],
            "sources": [{"id": s["id"], "name": s["name"], "text": s["body"], "created_at": iso(s["created_at"])}
                        for s in sources],
            "created_by": row["created_by"], "created_at": iso(row["created_at"]), "updated_at": iso(row["updated_at"])}


def project_row(conn: Connection, workspace_id: str, project_id: str, archived: bool = False) -> Optional[Dict[str, Any]]:
    row = conn.one("SELECT * FROM projects WHERE id=? AND workspace_id=?", (project_id, workspace_id))
    if not row or (row["archived_at"] and not archived):
        return None
    return row


def project_known(conn: Connection, project_id: str) -> bool:
    return conn.one("SELECT id FROM projects WHERE id=?", (project_id,)) is not None


def get_project(conn: Connection, workspace_id: str, project_id: str) -> Dict[str, Any]:
    row = project_row(conn, workspace_id, project_id)
    if not row:
        raise LookupError("Project not found")
    return _project(conn, row)


def list_projects(conn: Connection, workspace_id: str) -> List[Dict[str, Any]]:
    rows = conn.all("SELECT * FROM projects WHERE workspace_id=? AND archived_at IS NULL ORDER BY updated_at DESC",
                    (workspace_id,))
    return [_project(conn, row) for row in rows]


def insert_project(conn: Connection, workspace_id: str, project_id: str, values: Dict[str, Any], user_id: Optional[str],
                   created_at: Optional[int] = None, updated_at: Optional[int] = None,
                   archived_at: Optional[int] = None) -> None:
    stamp = now_ms()
    conn.execute("INSERT INTO projects (id, workspace_id, name, description, instructions, preferred_model, created_by, "
                 "created_at, updated_at, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (project_id, workspace_id, values.get("name") or project_id, values.get("description", ""),
                  values.get("instructions", ""), values.get("preferred_model", ""), user_id,
                  created_at or stamp, updated_at or created_at or stamp, archived_at))
    _set_links(conn, project_id, "chat", values.get("chat_ids", []))
    _set_links(conn, project_id, "run", values.get("run_names", []))
    for source in values.get("sources", []) or []:
        _insert_source(conn, project_id, source.get("name", "Source"), source.get("text", ""),
                       source.get("id"), from_iso(source.get("created_at"), stamp))


def _set_links(conn: Connection, project_id: str, kind: str, refs: Iterable[str]) -> None:
    conn.execute("DELETE FROM project_links WHERE project_id=? AND kind=?", (project_id, kind))
    for position, ref in enumerate(dict.fromkeys(refs)):
        conn.execute("INSERT INTO project_links (project_id, kind, ref, position) VALUES (?, ?, ?, ?)",
                     (project_id, kind, ref, position))


def _insert_source(conn: Connection, project_id: str, name: str, text: str, source_id: Optional[str] = None,
                   created_at: Optional[int] = None) -> str:
    position = int(conn.scalar("SELECT coalesce(max(position), -1) + 1 AS n FROM project_sources WHERE project_id=?",
                               (project_id,)) or 0)
    source_id = source_id if isinstance(source_id, str) and re.fullmatch(r"src_[a-f0-9]{12}", source_id) else \
        "src_" + secrets.token_hex(6)
    conn.execute("INSERT INTO project_sources (id, project_id, name, body, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (source_id, project_id, name, text, position, created_at or now_ms()))
    return source_id


def update_project(conn: Connection, workspace_id: str, project_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
    if not project_row(conn, workspace_id, project_id):
        raise LookupError("Project not found")
    columns = [key for key in ("name", "description", "instructions", "preferred_model") if key in values]
    if columns:
        conn.execute("UPDATE projects SET " + ", ".join(f"{c}=?" for c in columns) + " WHERE id=?",
                     [values[c] for c in columns] + [project_id])
    if "chat_ids" in values:
        _set_links(conn, project_id, "chat", values["chat_ids"])
    if "run_names" in values:
        _set_links(conn, project_id, "run", values["run_names"])
    touch_project(conn, project_id)
    return get_project(conn, workspace_id, project_id)


def touch_project(conn: Connection, project_id: str) -> None:
    conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now_ms(), project_id))


def archive_project(conn: Connection, workspace_id: str, project_id: str) -> None:
    if not project_row(conn, workspace_id, project_id):
        raise LookupError("Project not found")
    conn.execute("UPDATE projects SET archived_at=?, updated_at=? WHERE id=?", (now_ms(), now_ms(), project_id))


def add_source(conn: Connection, workspace_id: str, project_id: str, name: str, text: str,
               max_sources: int, max_chars: int) -> Dict[str, Any]:
    project = get_project(conn, workspace_id, project_id)
    if len(project["sources"]) >= max_sources:
        raise ValueError(f"A project can contain up to {max_sources} sources")
    if sum(len(s["text"]) for s in project["sources"]) + len(text) > max_chars:
        raise ValueError(f"Project source text is limited to {max_chars} characters in total")
    _insert_source(conn, project_id, name, text)
    touch_project(conn, project_id)
    return get_project(conn, workspace_id, project_id)


def remove_source(conn: Connection, workspace_id: str, project_id: str, source_id: str) -> Dict[str, Any]:
    get_project(conn, workspace_id, project_id)
    if not conn.execute("DELETE FROM project_sources WHERE id=? AND project_id=?", (source_id, project_id)).rowcount:
        raise LookupError("Project source not found")
    touch_project(conn, project_id)
    return get_project(conn, workspace_id, project_id)


# ---------------------------------------------------------------------------------------------- chats

def _json(value: Any, default: Any) -> Any:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return default
    return parsed if isinstance(parsed, type(default)) else default


def validate_chat(chat: Any) -> Dict[str, Any]:
    if not isinstance(chat, dict):
        raise ValueError("Each chat must be an object")
    chat_id = chat.get("id")
    if not isinstance(chat_id, str) or not CHAT_ID.fullmatch(chat_id):
        raise ValueError("Chat ids use letters, numbers, - and _ (at most 120)")
    messages = chat.get("messages", [])
    if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
        raise ValueError(f"A chat can hold at most {MAX_MESSAGES} messages")
    for key in ("title", "customTitle", "project", "run", "model"):
        value = chat.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 300):
            raise ValueError(f"Chat {key} must be text of at most 300 characters")
    seen = set()
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each message must be an object")
        role = message.get("role")
        if not isinstance(role, str) or not ROLE_NAME.fullmatch(role):
            raise ValueError("Message roles are short lowercase words such as user or assistant")
        content = message.get("content", "")
        if content is None:
            content = ""
        if not isinstance(content, str) or len(content) > MAX_MESSAGE_CHARS:
            raise ValueError(f"Message text is limited to {MAX_MESSAGE_CHARS} characters")
        message_id = message.get("id")
        if message_id is not None:
            if not isinstance(message_id, str) or not MESSAGE_ID.fullmatch(message_id) or message_id in seen:
                raise ValueError("Message ids must be unique short identifiers")
            seen.add(message_id)
    if len(json.dumps(chat, ensure_ascii=False).encode("utf-8")) > MAX_CHAT_BYTES:
        raise ValueError("This chat is larger than 4 MB. Start a new chat.")
    return chat


def _chat_row_values(chat: Dict[str, Any]) -> Dict[str, Any]:
    options = {key: value for key, value in chat.items() if key not in _CHAT_FIELDS}
    encoded = json.dumps(options, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_EXTRA_BYTES:
        raise ValueError("Chat settings are too large")
    title = chat.get("customTitle") or chat.get("title") or ""
    return {"title": str(title)[:300], "custom_title": chat.get("customTitle"), "project_id": chat.get("project"),
            "run_name": chat.get("run"), "model": chat.get("model"), "options": encoded}


def _write_messages(conn: Connection, workspace_id: str, chat_id: str, messages: List[Dict[str, Any]],
                    user_id: Optional[str], previous: Dict[str, Dict[str, Any]]) -> None:
    conn.execute("DELETE FROM chat_messages WHERE workspace_id=? AND chat_id=?", (workspace_id, chat_id))
    for position, message in enumerate(messages):
        message_id = message.get("id") or "msg_" + secrets.token_hex(10)
        extra = {key: value for key, value in message.items() if key not in _MESSAGE_FIELDS}
        encoded = json.dumps(extra, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_EXTRA_BYTES:
            raise ValueError("A message carries too much attached data")
        old = previous.get(message_id)
        # Authorship is the server's record: kept from the stored copy, set to the writer for new user messages.
        author = old["author_id"] if old else (user_id if message["role"] == "user" else None)
        conn.execute("INSERT INTO chat_messages (workspace_id, chat_id, position, id, role, content, author_id, extra) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (workspace_id, chat_id, position, message_id, message["role"],
                                                         message.get("content") or "", author, encoded))


def _people(conn: Connection, ids: Iterable[Optional[str]]) -> Dict[str, Dict[str, Any]]:
    wanted = sorted({i for i in ids if i and i != LOCAL_USER})
    if not wanted:
        return {}
    rows = conn.all("SELECT id, email, name FROM users WHERE id IN (" + ",".join("?" * len(wanted)) + ")", wanted)
    return {row["id"]: public_user(row) for row in rows}


def _chat(conn: Connection, row: Dict[str, Any], with_messages: bool = True) -> Dict[str, Any]:
    chat = dict(_json(row["options"], {}))
    chat.update({"id": row["id"], "title": row["title"], "updated": row["updated_at"], "created": row["created_at"],
                 "revision": row["revision"]})
    for key, column in (("customTitle", "custom_title"), ("project", "project_id"), ("run", "run_name"),
                        ("model", "model")):
        chat[key] = row[column]
    messages = conn.all("SELECT id, role, content, author_id, extra FROM chat_messages WHERE workspace_id=? AND chat_id=? "
                        "ORDER BY position", (row["workspace_id"], row["id"])) if with_messages else []
    people = _people(conn, [row["created_by"], row["updated_by"], *(m["author_id"] for m in messages)])
    chat["createdBy"], chat["updatedBy"] = people.get(row["created_by"]), people.get(row["updated_by"])
    if with_messages:
        chat["messages"] = []
        for message in messages:
            value = dict(_json(message["extra"], {}))
            value.update({"id": message["id"], "role": message["role"], "content": message["content"]})
            if message["author_id"] in people:
                value["author"] = people[message["author_id"]]
            chat["messages"].append(value)
    else:
        chat["message_count"] = int(conn.scalar("SELECT count(*) AS n FROM chat_messages WHERE workspace_id=? AND chat_id=?",
                                                (row["workspace_id"], row["id"])) or 0)
    return chat


def chat_row(conn: Connection, workspace_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
    return conn.one("SELECT * FROM chats WHERE workspace_id=? AND id=?", (workspace_id, chat_id))


def get_chat(conn: Connection, workspace_id: str, chat_id: str) -> Dict[str, Any]:
    row = chat_row(conn, workspace_id, chat_id)
    if not row:
        raise LookupError("Chat not found")
    return _chat(conn, row)


def list_chats(conn: Connection, workspace_id: str, since: Optional[int] = None,
               with_messages: bool = True) -> List[Dict[str, Any]]:
    sql, params = "SELECT * FROM chats WHERE workspace_id=?", [workspace_id]
    if since is not None:
        sql, params = sql + " AND updated_at>?", params + [since]
    rows = conn.all(sql + " ORDER BY updated_at DESC LIMIT ?", params + [MAX_CHATS])
    return [_chat(conn, row, with_messages) for row in rows]


def save_chat(conn: Connection, workspace_id: str, chat: Dict[str, Any], base_revision: Optional[int],
              user_id: str) -> Dict[str, Any]:
    """Create or replace one chat. A stale base revision raises Conflict carrying the stored chat."""
    validate_chat(chat)
    values = _chat_row_values(chat)
    stamp = now_ms()
    updated = chat.get("updated") if isinstance(chat.get("updated"), int) and 0 < chat["updated"] < 2 ** 53 else stamp
    row = chat_row(conn, workspace_id, chat["id"])
    if row is None:
        if base_revision not in (None, 0):
            raise Conflict("This chat was deleted by a teammate.", None)
        if int(conn.scalar("SELECT count(*) AS n FROM chats WHERE workspace_id=?", (workspace_id,)) or 0) >= MAX_CHATS:
            raise ValueError(f"A workspace can hold {MAX_CHATS} chats. Delete old chats first.")
        conn.execute("INSERT INTO chats (workspace_id, id, title, custom_title, project_id, run_name, model, options, "
                     "created_by, updated_by, created_at, updated_at, revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                     (workspace_id, chat["id"], values["title"], values["custom_title"], values["project_id"],
                      values["run_name"], values["model"], values["options"], user_id, user_id,
                      from_iso(chat.get("created"), updated), updated))
        previous: Dict[str, Dict[str, Any]] = {}
    else:
        if base_revision is not None and base_revision != row["revision"]:
            raise Conflict("A teammate changed this chat. Merge and save again.", _chat(conn, row))
        conn.execute("UPDATE chats SET title=?, custom_title=?, project_id=?, run_name=?, model=?, options=?, updated_by=?, "
                     "updated_at=?, revision=revision+1 WHERE workspace_id=? AND id=?",
                     (values["title"], values["custom_title"], values["project_id"], values["run_name"], values["model"],
                      values["options"], user_id, max(updated, row["updated_at"]), workspace_id, chat["id"]))
        previous = {m["id"]: m for m in conn.all("SELECT id, author_id FROM chat_messages WHERE workspace_id=? AND chat_id=?",
                                                  (workspace_id, chat["id"]))}
    _write_messages(conn, workspace_id, chat["id"], chat.get("messages", []), user_id, previous)
    return get_chat(conn, workspace_id, chat["id"])


def delete_chat(conn: Connection, workspace_id: str, chat_id: str) -> None:
    if not conn.execute("DELETE FROM chats WHERE workspace_id=? AND id=?", (workspace_id, chat_id)).rowcount:
        raise LookupError("Chat not found")


def import_chats(conn: Connection, workspace_id: str, user_id: str, chats: List[Any]) -> Dict[str, int]:
    """Add browser-stored chats once. Chats whose id already exists here are left as they are."""
    imported = skipped = 0
    for chat in chats:
        validate_chat(chat)
        if chat_row(conn, workspace_id, chat["id"]):
            skipped += 1
            continue
        save_chat(conn, workspace_id, chat, None, user_id)
        imported += 1
    return {"imported": imported, "skipped": skipped}


# ---------------------------------------------------------------------------------------------- runs, pins, preferences

def run_index(conn: Connection, workspace_id: str) -> List[str]:
    return [row["run_name"] for row in conn.all("SELECT run_name FROM run_index WHERE workspace_id=? ORDER BY added_at DESC",
                                                (workspace_id,))]


def run_in_workspace(conn: Connection, workspace_id: str, run_name: str) -> bool:
    return conn.one("SELECT 1 AS ok FROM run_index WHERE workspace_id=? AND run_name=?", (workspace_id, run_name)) is not None


def runs_visible_to(conn: Connection, user_id: str, run_name: str, minimum_role: str = "editor") -> bool:
    rows = conn.all("SELECT m.role FROM run_index r JOIN memberships m ON m.workspace_id=r.workspace_id "
                    "WHERE r.run_name=? AND m.user_id=?", (run_name, user_id))
    return any(RANK[row["role"]] >= RANK[minimum_role] for row in rows)


def add_run(conn: Connection, workspace_id: str, run_name: str, user_id: Optional[str]) -> None:
    conn.execute("INSERT INTO run_index (workspace_id, run_name, added_by, added_at) VALUES (?, ?, ?, ?) "
                 "ON CONFLICT (workspace_id, run_name) DO NOTHING", (workspace_id, run_name, user_id, now_ms()))


def remove_run(conn: Connection, workspace_id: str, run_name: str) -> None:
    if not conn.execute("DELETE FROM run_index WHERE workspace_id=? AND run_name=?", (workspace_id, run_name)).rowcount:
        raise LookupError("Run not found in this workspace")
    conn.execute("DELETE FROM pins WHERE workspace_id=? AND run_name=?", (workspace_id, run_name))


def pins(conn: Connection, workspace_id: str, user_id: str) -> List[str]:
    return [row["run_name"] for row in conn.all("SELECT run_name FROM pins WHERE workspace_id=? AND user_id=? ORDER BY position",
                                                (workspace_id, user_id))]


def set_pins(conn: Connection, workspace_id: str, user_id: str, names: List[str]) -> List[str]:
    conn.execute("DELETE FROM pins WHERE workspace_id=? AND user_id=?", (workspace_id, user_id))
    for position, name in enumerate(dict.fromkeys(names)):
        conn.execute("INSERT INTO pins (workspace_id, user_id, run_name, position) VALUES (?, ?, ?, ?)",
                     (workspace_id, user_id, name, position))
    return pins(conn, workspace_id, user_id)


def preferences(conn: Connection, scope: str, owner_id: str) -> Dict[str, Any]:
    rows = conn.all("SELECT pref_key, value FROM preferences WHERE scope=? AND owner_id=?", (scope, owner_id))
    return {row["pref_key"]: json.loads(row["value"]) for row in rows}


def set_preference(conn: Connection, scope: str, owner_id: str, key: str, value: Any) -> None:
    if value is None:
        conn.execute("DELETE FROM preferences WHERE scope=? AND owner_id=? AND pref_key=?", (scope, owner_id, key))
        return
    conn.execute("INSERT INTO preferences (scope, owner_id, pref_key, value, updated_at) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT (scope, owner_id, pref_key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                 (scope, owner_id, key, json.dumps(value), now_ms()))


def record_import(conn: Connection, workspace_id: str, user_id: str, source: str, count: int) -> bool:
    if conn.one("SELECT 1 AS ok FROM data_imports WHERE workspace_id=? AND user_id=? AND source=?",
                (workspace_id, user_id, source)):
        return False
    conn.execute("INSERT INTO data_imports (workspace_id, user_id, source, item_count, created_at) VALUES (?, ?, ?, ?, ?)",
                 (workspace_id, user_id, source, count, now_ms()))
    return True


def imported(conn: Connection, workspace_id: str, user_id: str) -> List[str]:
    return [row["source"] for row in conn.all("SELECT source FROM data_imports WHERE workspace_id=? AND user_id=?",
                                              (workspace_id, user_id))]

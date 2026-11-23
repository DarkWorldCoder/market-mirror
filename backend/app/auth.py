"""Who is asking, and what they may touch.

Two kinds of callers reach the workspace API:

* **local** - the single-user app on this computer: loopback plus the setup token, checked by
  `api.setup._guard` exactly as before. It owns the built-in workspace `ws_local` and sees every saved run.
* **session** - a signed-in person in team mode (`MM_ACCOUNTS=on`): an opaque cookie, a per-session CSRF
  token on writes, an Origin that matches the public origin, and a role in the workspace named by
  `X-MM-Workspace`. They see only the runs in that workspace's run index.

When team mode is off, session cookies are ignored completely, so the local checks are the only way in.

The resolved `Scope` is kept on `flask.g` for the request and copied into worker threads with `run_in_scope`,
so `runs._run_dir` (the one place every run read goes through) can refuse runs outside the workspace.
"""
from __future__ import annotations

import contextvars
import hmac
import os
from dataclasses import dataclass
from typing import Any, Callable, FrozenSet, Optional, Tuple

from flask import g, has_request_context, jsonify, request

from .db import get_db, repo

COOKIE = "mm_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOGIN_FAILURES_PER_EMAIL = 10
AUTH_ATTEMPTS_PER_CLIENT = 30
WINDOW_S = 15 * 60
_SCOPE: contextvars.ContextVar[Optional["Scope"]] = contextvars.ContextVar("mm_scope", default=None)


def accounts_enabled() -> bool:
    return os.environ.get("MM_ACCOUNTS", "off").strip().lower() in {"on", "1", "true", "yes"}


def signup_policy() -> str:
    value = os.environ.get("MM_SIGNUPS", "invite").strip().lower()
    return value if value in {"open", "invite", "closed"} else "invite"


def public_origin() -> str:
    configured = os.environ.get("MM_PUBLIC_ORIGIN", "").strip().rstrip("/")
    return configured or request.host_url.rstrip("/")


def secure_cookies() -> bool:
    return (request.is_secure or public_origin().startswith("https://")
            or os.environ.get("MM_ENV", "").lower() == "production")


@dataclass(frozen=True)
class Scope:
    user_id: str
    workspace_id: str
    role: str
    via: str                       # "local" or "session"
    email: str = ""
    name: str = ""
    session_hash: str = ""
    csrf: str = ""
    runs: Optional[FrozenSet[str]] = None   # None: every saved run (local); otherwise the workspace's run index

    def can(self, role: str) -> bool:
        return repo.RANK[self.role] >= repo.RANK[role]

    @property
    def is_local(self) -> bool:
        return self.via == "local"


def current_scope() -> Optional[Scope]:
    if has_request_context():
        return g.get("mm_scope")
    return _SCOPE.get()


def run_in_scope(function: Callable[[], Any]) -> Callable[[], Any]:
    """Wrap a function for a worker thread so it keeps the request's workspace limits."""
    scope = current_scope()

    def wrapped():
        token = _SCOPE.set(scope)
        try:
            return function()
        finally:
            _SCOPE.reset(token)
    return wrapped


def run_allowed(name: str) -> bool:
    scope = current_scope()
    return scope is None or scope.runs is None or name in scope.runs


def workspace_id() -> str:
    scope = current_scope()
    return scope.workspace_id if scope else repo.LOCAL_WORKSPACE


def user_id() -> str:
    scope = current_scope()
    return scope.user_id if scope else repo.LOCAL_USER


# ---------------------------------------------------------------------------------------------- passwords

_HASHER = None
_DUMMY = None


def _hasher():
    global _HASHER, _DUMMY
    if _HASHER is None:
        try:
            from argon2 import PasswordHasher
        except ImportError as exc:  # pragma: no cover - argon2-cffi is a declared dependency
            raise RuntimeError("Team accounts need argon2-cffi: uv pip install argon2-cffi") from exc
        _HASHER = PasswordHasher()
        _DUMMY = _HASHER.hash("marketmirror-timing-placeholder")
    return _HASHER


def check_password_rules(password: Any) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Use a password of 12 to 256 characters.")
    return password


def hash_password(password: str) -> str:
    return _hasher().hash(check_password_rules(password))


def verify_password(saved: Optional[str], password: Any) -> Tuple[bool, bool]:
    """(matches, needs_rehash). Unknown accounts still pay for one hash check."""
    from argon2.exceptions import InvalidHashError, VerificationError
    hasher = _hasher()
    if not isinstance(password, str) or len(password) > 256:
        password = ""
    try:
        hasher.verify(saved or _DUMMY, password)
    except (VerificationError, InvalidHashError):
        return False, False
    if not saved:
        return False, False
    return True, hasher.check_needs_rehash(saved)


# ---------------------------------------------------------------------------------------------- resolving callers

def _local_scope() -> Optional[Scope]:
    from .api import setup as setup_api
    if not setup_api._loopback():
        return None
    if not hmac.compare_digest(request.headers.get("X-Setup-Token", ""), setup_api.SETUP_TOKEN):
        return None
    return Scope(user_id=repo.LOCAL_USER, workspace_id=repo.LOCAL_WORKSPACE, role="owner", via="local")


def signed_in() -> Optional[dict]:
    """The session row for this browser in team mode, or None."""
    if not accounts_enabled():
        return None
    token = request.cookies.get(COOKIE, "")
    if not token:
        return None
    with get_db().transaction() as conn:
        return repo.session(conn, token)


def _session_scope(row: dict) -> Tuple[Optional[Scope], Optional[Tuple[Any, int]]]:
    asked = request.headers.get("X-MM-Workspace", "").strip()
    chosen = asked or row["workspace_id"]
    if not chosen:
        return None, (jsonify(success=False, error="Create or join a workspace first.", code="no_workspace"), 409)
    with get_db().transaction() as conn:
        role = repo.role_in(conn, chosen, row["user_id"])
        runs = frozenset(repo.run_index(conn, chosen)) if role else frozenset()
    if not role:
        return None, (jsonify(success=False, error="You are no longer a member of this workspace. Reload the page.",
                              code="workspace_changed"), 409)
    return Scope(user_id=row["user_id"], workspace_id=chosen, role=role, via="session", email=row["email"],
                 name=row.get("name") or "", session_hash=row["token_hash"], csrf=row["csrf_token"], runs=runs), None


def check_write_origin(csrf: Optional[str]) -> Optional[Tuple[Any, int]]:
    """Writes from a signed-in browser: exact Origin and, once signed in, the session's CSRF token."""
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin != public_origin():
        return jsonify(success=False, error="Cross-site request refused."), 403
    if csrf is not None and not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), csrf):
        return jsonify(success=False, error="Your session changed. Reload the page and try again.", code="csrf"), 403
    return None


def require(role: str = "viewer", write: Optional[bool] = None, local_only: bool = False):
    """Resolve the caller for a workspace route and keep the scope on g. Returns an error response or None."""
    from .api.setup import _guard
    write = request.method not in SAFE_METHODS if write is None else write
    row = None if local_only else signed_in()
    if row:
        scope, error = _session_scope(row)
        if error:
            return error
        if write:
            error = check_write_origin(scope.csrf)
            if error:
                return error
        if not scope.can(role):
            names = {"viewer": "a member", "editor": "an editor or owner", "owner": "an owner"}
            return jsonify(success=False, error=f"Only {names[role]} of this workspace can do this.", code="role"), 403
        g.mm_scope = scope
        return None
    denied = _guard(write=write)
    if denied:
        if accounts_enabled() and not local_only and not request.headers.get("X-Setup-Token"):
            return jsonify(success=False, error="Sign in to continue.", code="signed_out"), 401
        return denied
    g.mm_scope = _local_scope()
    return None


# ---------------------------------------------------------------------------------------------- rate limits

def client_key() -> str:
    return "client:" + (request.remote_addr or "unknown")


def too_many(conn, email: Optional[str] = None) -> bool:
    if repo.attempts(conn, client_key(), "auth", WINDOW_S) >= AUTH_ATTEMPTS_PER_CLIENT:
        return True
    return bool(email) and repo.attempts(conn, "email:" + email, "login_failure", WINDOW_S) >= LOGIN_FAILURES_PER_EMAIL

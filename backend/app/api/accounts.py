"""Sign-up, sign-in, workspaces, members and invitations.

`/api/auth/session` answers in both modes so the app knows which one it is in. Everything else under
`/api/auth/` exists only in team mode (`MM_ACCOUNTS=on`). `/api/team/` works in both: in local mode the
caller is the owner of the built-in workspace and there is nobody to invite.
"""
from __future__ import annotations

import re

from flask import Blueprint, g, jsonify, make_response, request

from .. import auth
from ..db import get_db, repo

accounts_bp = Blueprint("accounts", __name__)
_INVITE_ID = re.compile(r"^inv_[a-f0-9]{24}$")
_USER_ID = re.compile(r"^usr_([a-f0-9]{24}|local)$")


@accounts_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@accounts_bp.errorhandler(ValueError)
def invalid(error):
    return jsonify(success=False, error=str(error)), 400


@accounts_bp.errorhandler(LookupError)
def missing(error):
    return jsonify(success=False, error=str(error) or "Not found"), 404


@accounts_bp.errorhandler(PermissionError)
def forbidden(error):
    return jsonify(success=False, error=str(error)), 403


@accounts_bp.errorhandler(repo.Conflict)
def conflict(error):
    return jsonify(success=False, error=str(error)), 409


def _body() -> dict:
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def _teams_only():
    if not auth.accounts_enabled():
        return jsonify(success=False, error="Team accounts are off on this server. Set MM_ACCOUNTS=on to use them.",
                       code="accounts_off"), 404
    return None


def _payload(conn, row) -> dict:
    """The signed-in state the app needs: person, chosen workspace, all workspaces, CSRF token."""
    spaces = repo.workspaces_for(conn, row["user_id"])
    chosen = next((w for w in spaces if w["id"] == row["workspace_id"]), None) or (spaces[0] if spaces else None)
    if chosen and chosen["id"] != row["workspace_id"]:
        repo.select_session_workspace(conn, row["token_hash"], chosen["id"])
    return {"mode": "accounts", "signups": auth.signup_policy(),
            "account": {"id": row["user_id"], "email": row["email"], "name": row.get("name") or ""},
            "csrf": row["csrf_token"], "workspace": chosen, "workspaces": spaces}


def _signed_in_response(conn, user: dict, workspace_id, status: int = 200):
    old = request.cookies.get(auth.COOKIE)
    if old:
        repo.delete_session(conn, old)
    token, _ = repo.create_session(conn, user["id"], workspace_id)
    payload = _payload(conn, repo.session(conn, token))
    response = make_response(jsonify(success=True, data=payload), status)
    response.set_cookie(auth.COOKIE, token, max_age=repo.SESSION_TTL_MS // 1000, httponly=True, samesite="Lax",
                        secure=auth.secure_cookies(), path="/")
    return response


def _session_write():
    """A signed-in write: returns (session row, error)."""
    row = auth.signed_in()
    if not row:
        return None, (jsonify(success=False, error="Sign in to continue.", code="signed_out"), 401)
    error = auth.check_write_origin(row["csrf_token"])
    return (None, error) if error else (row, None)


# ---------------------------------------------------------------------------------------------- session

@accounts_bp.get("/api/auth/session")
def session_state():
    if not auth.accounts_enabled():
        return jsonify(success=True, data={"mode": "local", "account": None, "signups": "closed"})
    row = auth.signed_in()
    with get_db().transaction() as conn:
        if row:
            return jsonify(success=True, data=_payload(conn, row))
        first = repo.count_people(conn) == 0
    return jsonify(success=True, data={"mode": "accounts", "account": None, "signups": auth.signup_policy(),
                                       "first_account": first})


@accounts_bp.post("/api/auth/signup")
def signup():
    denied = _teams_only() or auth.check_write_origin(None)
    if denied:
        return denied
    value = _body()
    email = repo.normalize_email(value.get("email"))
    name = repo.clean_name(value.get("name", ""), "Name", required=False)
    password = auth.check_password_rules(value.get("password"))
    invite_token = value.get("invitation") or ""
    with get_db().transaction() as conn:
        if auth.too_many(conn):
            return jsonify(success=False, error="Too many attempts. Try again in 15 minutes."), 429
        repo.record_attempt(conn, auth.client_key(), "auth")
    password_hash = auth.hash_password(password)   # slow; outside the write lock
    with get_db().transaction() as conn:
        first = repo.count_people(conn) == 0
        invite = repo.invitation(conn, invite_token) if invite_token else None
        if invite_token and not invite:
            return jsonify(success=False, error="This invitation has expired, was revoked or was already used."), 410
        policy = auth.signup_policy()
        if not first and not (policy == "open" or (policy == "invite" and invite)):
            return jsonify(success=False, error="Sign-up needs an invitation from a workspace owner.",
                           code="invite_required"), 403
        if invite and invite["email"] and invite["email"] != email:
            return jsonify(success=False, error="This invitation is for another email address."), 403
        user = repo.create_user(conn, email, name, password_hash)
        if invite:
            chosen = repo.accept_invitation(conn, invite_token, user)["id"]
        else:
            label = repo.clean_name(value.get("workspace_name") or (name or email.split("@")[0]) + "'s workspace",
                                    "Workspace name")
            chosen = repo.create_workspace(conn, label, user["id"])["id"]
        repo.touch_login(conn, user["id"])
        return _signed_in_response(conn, user, chosen, 201)


@accounts_bp.post("/api/auth/login")
def login():
    denied = _teams_only() or auth.check_write_origin(None)
    if denied:
        return denied
    value = _body()
    email = str(value.get("email") or "").strip().lower()[:320]
    with get_db().transaction() as conn:
        if auth.too_many(conn, email):
            return jsonify(success=False, error="Too many attempts. Try again in 15 minutes."), 429
        repo.record_attempt(conn, auth.client_key(), "auth")
        user = repo.user_by_email(conn, email) if email else None
    matches, rehash = auth.verify_password(user["password_hash"] if user else None, value.get("password"))
    with get_db().transaction() as conn:
        if not (user and matches):
            if email:
                repo.record_attempt(conn, "email:" + email, "login_failure")
            return jsonify(success=False, error="Wrong email or password."), 401
        repo.clear_attempts(conn, "email:" + email, "login_failure")
        if rehash:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (auth.hash_password(value["password"]), user["id"]))
        repo.touch_login(conn, user["id"])
        spaces = repo.workspaces_for(conn, user["id"])
        return _signed_in_response(conn, user, spaces[0]["id"] if spaces else None)


@accounts_bp.post("/api/auth/logout")
def logout():
    denied = _teams_only()
    if denied:
        return denied
    row, error = _session_write()
    if error:
        return error
    with get_db().transaction() as conn:
        repo.delete_session(conn, request.cookies.get(auth.COOKIE, ""))
    response = jsonify(success=True, data={"signed_out": True})
    response.delete_cookie(auth.COOKIE, path="/", samesite="Lax", secure=auth.secure_cookies(), httponly=True)
    return response


@accounts_bp.post("/api/auth/password")
def change_password():
    denied = _teams_only()
    if denied:
        return denied
    row, error = _session_write()
    if error:
        return error
    value = _body()
    with get_db().transaction() as conn:
        user = repo.user_by_id(conn, row["user_id"])
    if not auth.verify_password(user["password_hash"], value.get("current_password"))[0]:
        return jsonify(success=False, error="Your current password is wrong."), 403
    new_hash = auth.hash_password(value.get("new_password"))
    with get_db().transaction() as conn:
        repo.set_password(conn, user["id"], new_hash)     # signs out every other browser too
        return _signed_in_response(conn, user, row["workspace_id"])


# ---------------------------------------------------------------------------------------------- workspaces

@accounts_bp.post("/api/auth/workspaces")
def create_workspace():
    denied = _teams_only()
    if denied:
        return denied
    row, error = _session_write()
    if error:
        return error
    name = repo.clean_name(_body().get("name"), "Workspace name")
    with get_db().transaction() as conn:
        if len(repo.workspaces_for(conn, row["user_id"])) >= 50:
            return jsonify(success=False, error="You can belong to at most 50 workspaces."), 409
        created = repo.create_workspace(conn, name, row["user_id"])
        repo.select_session_workspace(conn, row["token_hash"], created["id"])
        return jsonify(success=True, data=_payload(conn, repo.session(conn, request.cookies[auth.COOKIE]))), 201


@accounts_bp.post("/api/auth/workspaces/select")
def select_workspace():
    denied = _teams_only()
    if denied:
        return denied
    row, error = _session_write()
    if error:
        return error
    chosen = _body().get("id")
    with get_db().transaction() as conn:
        if not isinstance(chosen, str) or not repo.role_in(conn, chosen, row["user_id"]):
            raise LookupError("Workspace not found")
        repo.select_session_workspace(conn, row["token_hash"], chosen)
        return jsonify(success=True, data=_payload(conn, repo.session(conn, request.cookies[auth.COOKIE])))


# ---------------------------------------------------------------------------------------------- invitations

@accounts_bp.get("/api/auth/invitations/<token>")
def invitation_preview(token):
    denied = _teams_only()
    if denied:
        return denied
    with get_db().transaction() as conn:
        row = repo.invitation(conn, token)
        if not row:
            raise LookupError("This invitation has expired, was revoked or was already used.")
        return jsonify(success=True, data={"workspace": row["workspace_name"], "role": row["role"], "email": row["email"],
                                           "expires_at": repo.iso(row["expires_at"])})


@accounts_bp.post("/api/auth/invitations/accept")
def accept_invitation():
    denied = _teams_only()
    if denied:
        return denied
    row, error = _session_write()
    if error:
        return error
    with get_db().transaction() as conn:
        user = repo.user_by_id(conn, row["user_id"])
        joined = repo.accept_invitation(conn, _body().get("token") or "", user)
        repo.select_session_workspace(conn, row["token_hash"], joined["id"])
        return jsonify(success=True, data=_payload(conn, repo.session(conn, request.cookies[auth.COOKIE])))


# ---------------------------------------------------------------------------------------------- team

@accounts_bp.get("/api/team")
def team():
    denied = auth.require("viewer")
    if denied:
        return denied
    scope = g.mm_scope
    with get_db().transaction() as conn:
        space = repo.workspace(conn, scope.workspace_id)
        data = {"workspace": {"id": space["id"], "name": space["name"], "role": scope.role},
                "members": repo.members(conn, scope.workspace_id), "you": scope.user_id,
                "mode": "local" if scope.is_local else "accounts",
                "invitations": repo.invitations(conn, scope.workspace_id) if scope.can("owner") else []}
    return jsonify(success=True, data=data)


@accounts_bp.patch("/api/team/workspace")
def rename_workspace():
    denied = auth.require("owner")
    if denied:
        return denied
    name = repo.clean_name(_body().get("name"), "Workspace name")
    with get_db().transaction() as conn:
        repo.rename_workspace(conn, g.mm_scope.workspace_id, name)
    return jsonify(success=True, data={"id": g.mm_scope.workspace_id, "name": name})


@accounts_bp.patch("/api/team/members/<user_id>")
def change_role(user_id):
    denied = auth.require("owner")
    if denied:
        return denied
    if not _USER_ID.fullmatch(user_id):
        raise LookupError("Member not found")
    with get_db().transaction() as conn:
        repo.set_role(conn, g.mm_scope.workspace_id, user_id, _body().get("role"))
        return jsonify(success=True, data=repo.members(conn, g.mm_scope.workspace_id))


@accounts_bp.delete("/api/team/members/<user_id>")
def remove_member(user_id):
    """Owners remove anyone; everyone else may only leave (remove themselves)."""
    denied = auth.require("viewer", write=True)
    if denied:
        return denied
    scope = g.mm_scope
    if user_id != scope.user_id and not scope.can("owner"):
        return jsonify(success=False, error="Only an owner of this workspace can remove members.", code="role"), 403
    if scope.is_local:
        return jsonify(success=False, error="The local workspace always keeps this computer as its owner."), 409
    if not _USER_ID.fullmatch(user_id):
        raise LookupError("Member not found")
    with get_db().transaction() as conn:
        repo.remove_member(conn, scope.workspace_id, user_id)
        return jsonify(success=True, data=repo.members(conn, scope.workspace_id))


@accounts_bp.post("/api/team/invitations")
def invite():
    denied = _teams_only() or auth.require("owner")
    if denied:
        return denied
    value = _body()
    email = repo.normalize_email(value["email"]) if value.get("email") else None
    role = value.get("role", "editor")
    days = value.get("expires_in_days", 7)
    if isinstance(days, bool) or not isinstance(days, (int, float)) or not 0.0035 <= days <= 30:
        raise ValueError("Invitations expire after 5 minutes to 30 days.")
    with get_db().transaction() as conn:
        token, row = repo.create_invitation(conn, g.mm_scope.workspace_id, email, role, g.mm_scope.user_id,
                                            int(days * 86400))
    # The token sits after '#', so it never reaches server or proxy logs when the link is opened.
    return jsonify(success=True, data={**row, "url": auth.public_origin() + "/join#invite=" + token}), 201


@accounts_bp.delete("/api/team/invitations/<invite_id>")
def revoke(invite_id):
    denied = _teams_only() or auth.require("owner")
    if denied:
        return denied
    if not _INVITE_ID.fullmatch(invite_id):
        raise LookupError("Invitation not found")
    with get_db().transaction() as conn:
        repo.revoke_invitation(conn, g.mm_scope.workspace_id, invite_id)
    return jsonify(success=True, data={"id": invite_id, "revoked": True})

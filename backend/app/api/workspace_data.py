"""Chats, pins, preferences, onboarding and the run index, stored in the workspace database.

Roles: viewers read; editors write chats, import and change the run index; owners change workspace
preferences and may delete anyone's chat. Pins and appearance are per person, so every member may set them.
"""
from __future__ import annotations

import re

from flask import Blueprint, g, jsonify, request

from .. import auth
from ..db import get_db, repo

workspace_data_bp = Blueprint("workspace_data", __name__)
_SOURCE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_WORKSPACE_PREFS = {"default_model": lambda v: isinstance(v, str) and len(v) <= 64}
_USER_PREFS = {"theme": lambda v: v in ("light", "dark")}
_STEPS = {"workspace", "model", "invite", "demo", "dismissed"}


@workspace_data_bp.after_request
def private(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@workspace_data_bp.errorhandler(ValueError)
def invalid(error):
    return jsonify(success=False, error=str(error)), 400


@workspace_data_bp.errorhandler(LookupError)
def missing(error):
    return jsonify(success=False, error=str(error) or "Not found"), 404


def _body():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


def ok(value, status=200):
    return jsonify(success=True, data=value), status


# ---------------------------------------------------------------------------------------------- chats

@workspace_data_bp.get("/api/workspace/chats")
def list_chats():
    denied = auth.require("viewer")
    if denied:
        return denied
    since = request.args.get("since")
    try:
        since = int(since) if since not in (None, "") else None
    except ValueError:
        raise ValueError("since must be a millisecond timestamp") from None
    with get_db().transaction() as conn:
        chats = repo.list_chats(conn, g.mm_scope.workspace_id, since, request.args.get("summary") != "1")
        imports = repo.imported(conn, g.mm_scope.workspace_id, g.mm_scope.user_id)
    return ok({"chats": chats, "imported_sources": imports, "role": g.mm_scope.role})


@workspace_data_bp.get("/api/workspace/chats/<chat_id>")
def get_chat(chat_id):
    denied = auth.require("viewer")
    if denied:
        return denied
    with get_db().transaction() as conn:
        return ok(repo.get_chat(conn, g.mm_scope.workspace_id, chat_id))


@workspace_data_bp.put("/api/workspace/chats/<chat_id>")
def save_chat(chat_id):
    denied = auth.require("editor")
    if denied:
        return denied
    if request.content_length and request.content_length > repo.MAX_CHAT_BYTES + 100_000:
        return jsonify(success=False, error="This chat is larger than 4 MB. Start a new chat."), 413
    value = _body()
    chat = value.get("chat")
    if not isinstance(chat, dict) or chat.get("id") != chat_id:
        raise ValueError("Send the chat with the same id as the address")
    base = value.get("base_revision")
    if base is not None and (isinstance(base, bool) or not isinstance(base, int) or base < 0):
        raise ValueError("base_revision must be a whole number")
    try:
        with get_db().transaction() as conn:
            return ok(repo.save_chat(conn, g.mm_scope.workspace_id, chat, base, g.mm_scope.user_id))
    except repo.Conflict as error:
        return jsonify(success=False, error=str(error), code="conflict", data={"current": error.current}), 409


@workspace_data_bp.delete("/api/workspace/chats/<chat_id>")
def delete_chat(chat_id):
    denied = auth.require("editor")
    if denied:
        return denied
    scope = g.mm_scope
    with get_db().transaction() as conn:
        row = repo.chat_row(conn, scope.workspace_id, chat_id)
        if not row:
            raise LookupError("Chat not found")
        if not scope.can("owner") and row["created_by"] != scope.user_id:
            return jsonify(success=False, error="Only the person who started this chat or an owner can delete it.",
                           code="role"), 403
        repo.delete_chat(conn, scope.workspace_id, chat_id)
    return ok({"id": chat_id, "deleted": True})


@workspace_data_bp.post("/api/workspace/chats/import")
def import_chats():
    """One-time upload of the chats a browser kept in localStorage. Existing chat ids are skipped."""
    denied = auth.require("editor")
    if denied:
        return denied
    if request.content_length and request.content_length > 40 * 1024 * 1024:
        return jsonify(success=False, error="Too much to import at once. Import in smaller parts."), 413
    value = _body()
    source = value.get("source")
    chats = value.get("chats")
    if not isinstance(source, str) or not _SOURCE.fullmatch(source):
        raise ValueError("Name the browser this import comes from")
    if not isinstance(chats, list) or len(chats) > repo.MAX_CHATS:
        raise ValueError(f"Import at most {repo.MAX_CHATS} chats")
    label = "browser-chats:" + source
    with get_db().transaction() as conn:
        if label in repo.imported(conn, g.mm_scope.workspace_id, g.mm_scope.user_id):
            return ok({"imported": 0, "skipped": len(chats), "already_imported": True})
        counts = repo.import_chats(conn, g.mm_scope.workspace_id, g.mm_scope.user_id, chats)
        repo.record_import(conn, g.mm_scope.workspace_id, g.mm_scope.user_id, label, counts["imported"])
    return ok({**counts, "already_imported": False}, 201)


# ---------------------------------------------------------------------------------------------- pins and preferences

@workspace_data_bp.route("/api/workspace/pins", methods=["GET", "PUT"])
def pins():
    denied = auth.require("viewer")
    if denied:
        return denied
    scope = g.mm_scope
    with get_db().transaction() as conn:
        if request.method == "GET":
            return ok({"pins": repo.pins(conn, scope.workspace_id, scope.user_id)})
        names = _body().get("pins")
        if not isinstance(names, list) or len(names) > 200 or any(not isinstance(n, str) or len(n) > 200 for n in names):
            raise ValueError("Pins must be a list of at most 200 run names")
        if scope.runs is not None:
            names = [n for n in names if n in scope.runs]
        return ok({"pins": repo.set_pins(conn, scope.workspace_id, scope.user_id, names)})


@workspace_data_bp.route("/api/workspace/preferences", methods=["GET", "PUT"])
def preferences():
    denied = auth.require("viewer")
    if denied:
        return denied
    scope = g.mm_scope
    with get_db().transaction() as conn:
        if request.method == "PUT":
            value = _body()
            workspace_values, user_values = value.get("workspace") or {}, value.get("user") or {}
            if not isinstance(workspace_values, dict) or not isinstance(user_values, dict):
                raise ValueError("Send workspace and user preferences as objects")
            if workspace_values and not scope.can("owner"):
                return jsonify(success=False, error="Only an owner can change workspace preferences.", code="role"), 403
            for values, rules, kind, owner in ((workspace_values, _WORKSPACE_PREFS, "workspace", scope.workspace_id),
                                               (user_values, _USER_PREFS, "user", scope.user_id)):
                for key, item in values.items():
                    if key not in rules or (item is not None and not rules[key](item)):
                        raise ValueError(f"Unknown or invalid {kind} preference: {str(key)[:40]}")
                    repo.set_preference(conn, kind, owner, key, item)
        return ok({"workspace": repo.preferences(conn, "workspace", scope.workspace_id),
                   "user": repo.preferences(conn, "user", scope.user_id)})


# ---------------------------------------------------------------------------------------------- onboarding

def _model_connected() -> bool:
    try:
        from ..services import workspace_chat
        return any(m.get("available") is not False for m in (workspace_chat.models().get("models") or []))
    except Exception:  # the status is a hint; never fail onboarding on it
        return False


@workspace_data_bp.route("/api/workspace/onboarding", methods=["GET", "PUT"])
def onboarding():
    denied = auth.require("viewer")
    if denied:
        return denied
    scope = g.mm_scope
    with get_db().transaction() as conn:
        if request.method == "PUT":
            steps = _body().get("steps")
            if not isinstance(steps, dict) or set(steps) - _STEPS or any(not isinstance(v, bool) for v in steps.values()):
                raise ValueError("Steps are workspace, model, invite, demo and dismissed, each true or false")
            # A viewer cannot change the checklist, but must be able to dismiss it for
            # themselves; the other steps stay editor-only.
            if not scope.can("editor") and (set(steps) != {"dismissed"} or steps.get("dismissed") is not True):
                return jsonify(success=False, error="A viewer can only dismiss the setup checklist.", code="role"), 403
            repo.set_onboarding(conn, scope.workspace_id, steps)
        space = repo.workspace(conn, scope.workspace_id)
        people = len(repo.members(conn, scope.workspace_id))
        runs = len(repo.run_index(conn, scope.workspace_id))
    return ok({"steps": space["onboarding"], "workspace": {"id": space["id"], "name": space["name"]},
               "model_connected": _model_connected(), "can_connect_model": scope.is_local,
               "can_invite": auth.accounts_enabled() and scope.can("owner"), "members": people,
               "runs_in_workspace": runs, "mode": "local" if scope.is_local else "accounts",
               "demo_url": "https://darkworldcoder.github.io/market-mirror/demo/"})


# ---------------------------------------------------------------------------------------------- run index

@workspace_data_bp.get("/api/workspace/runs-index")
def list_run_index():
    denied = auth.require("viewer")
    if denied:
        return denied
    with get_db().transaction() as conn:
        return ok({"runs": repo.run_index(conn, g.mm_scope.workspace_id)})


@workspace_data_bp.post("/api/workspace/runs-index")
def add_run():
    """Local callers may add any saved run; editors may bring in a run they already edit in another workspace."""
    denied = auth.require("editor")
    if denied:
        return denied
    from .runs import _run_dir
    scope = g.mm_scope
    name = _body().get("name")
    with get_db().transaction() as conn:
        if not scope.is_local and not (isinstance(name, str) and repo.runs_visible_to(conn, scope.user_id, name)):
            raise LookupError("Run not found")
    g.mm_scope = None   # the folder check below must not apply this workspace's own run list
    try:
        _run_dir(name)
    finally:
        g.mm_scope = scope
    with get_db().transaction() as conn:
        repo.add_run(conn, scope.workspace_id, name, scope.user_id)
        return ok({"runs": repo.run_index(conn, scope.workspace_id)}, 201)


@workspace_data_bp.delete("/api/workspace/runs-index/<name>")
def remove_run(name):
    denied = auth.require("editor")
    if denied:
        return denied
    with get_db().transaction() as conn:
        repo.remove_run(conn, g.mm_scope.workspace_id, name)
        return ok({"runs": repo.run_index(conn, g.mm_scope.workspace_id)})

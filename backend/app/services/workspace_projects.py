"""Workspace projects, stored in the workspace database and tied to real engine projects.

Each workspace project shares its id with an engine (graph) project under uploads/projects/. Older installs kept
the workspace part in uploads/projects/<id>/workspace.json; the local workspace imports those files the first
time it sees them and leaves them in place. Engine projects made outside the app (the CLI, MCP) appear in the
local workspace too, as before. The workspace comes from the caller's scope (app/auth.py).
"""
import json
import re
import threading
from pathlib import Path

from .. import auth
from ..db import get_db, repo
from ..models.project import ProjectManager

_LOCK = threading.RLock()
_ID = re.compile(r"^proj_[a-f0-9]{12}$")
_CHAT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_FIELDS = {"name", "description", "instructions", "chat_ids", "run_names", "preferred_model"}
_SOURCE_ID = re.compile(r"^src_[a-f0-9]{12}$")
MAX_SOURCES = 10
MAX_SOURCE_CHARS = 120000


def _validate(data, creating=False):
    if not isinstance(data, dict) or set(data) - _FIELDS:
        raise ValueError("Use name, description, instructions, chat_ids, run_names or preferred_model")
    if creating and "name" not in data:
        raise ValueError("Give the project a name")
    result = {}
    for key, value in data.items():
        if key == "preferred_model":
            if value is not None and (not isinstance(value, str) or (value and not re.fullmatch(r"m_[a-f0-9]{24}", value))):
                raise ValueError("Choose a model from the server catalog or leave it empty")
            result[key] = value or ""
        elif key in {"name", "description", "instructions"}:
            maximum = {"name": 120, "description": 2000, "instructions": 12000}[key]
            if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
                raise ValueError(f"{key} must be text of at most {maximum} characters")
            result[key] = value.strip()
            if key == "name" and not result[key]:
                raise ValueError("Give the project a name")
        else:
            if not isinstance(value, list) or len(value) > 200 or any(not isinstance(v, str) for v in value):
                raise ValueError(f"{key} must contain at most 200 identifiers")
            if key == "chat_ids" and any(not _CHAT.fullmatch(v) for v in value):
                raise ValueError("Invalid chat identifier")
            if key == "run_names":
                from ..api.runs import _run_dir
                for name in value:
                    try:
                        _run_dir(name)
                    except LookupError as exc:
                        raise ValueError(f"Run not found: {name[:120]}") from exc
            result[key] = list(dict.fromkeys(value))
    return result


# ---------------------------------------------------------------------------------------------- legacy files

def _legacy_values(project_id):
    """The workspace.json written by earlier versions, or the engine project's own name and dates."""
    root = Path(ProjectManager.PROJECTS_DIR).resolve()
    directory = root / project_id
    if directory.is_symlink() or directory.resolve().parent != root or not directory.is_dir():
        return None
    try:
        value = json.loads((directory / "workspace.json").read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    engine = ProjectManager.get_project(project_id)
    if not engine:
        return None
    return {"name": engine.name, "created_at": engine.created_at, "updated_at": engine.updated_at}


def _import_one(conn, project_id):
    value = _legacy_values(project_id)
    if value is None:
        return False
    stamp = repo.now_ms()
    clean = {"name": str(value.get("name") or project_id)[:120], "description": str(value.get("description") or "")[:2000],
             "instructions": str(value.get("instructions") or "")[:12000],
             "preferred_model": value.get("preferred_model") if isinstance(value.get("preferred_model"), str) else "",
             "chat_ids": [c for c in value.get("chat_ids") or [] if isinstance(c, str) and _CHAT.fullmatch(c)][:200],
             "run_names": [r for r in value.get("run_names") or [] if isinstance(r, str)][:200],
             "sources": [s for s in value.get("sources") or [] if isinstance(s, dict)][:MAX_SOURCES]}
    created = repo.from_iso(value.get("created_at"), stamp)
    repo.insert_project(conn, repo.LOCAL_WORKSPACE, project_id, clean, repo.LOCAL_USER, created,
                        repo.from_iso(value.get("updated_at"), created), stamp if value.get("archived") else None)
    return True


def _import_local(conn, only=None):
    """Bring engine projects this database has not seen into the local workspace (once each)."""
    root = Path(ProjectManager.PROJECTS_DIR)
    if not root.exists():
        return
    names = [only] if only else [d.name for d in root.iterdir() if _ID.fullmatch(d.name)]
    for name in names:
        if not repo.project_known(conn, name):
            _import_one(conn, name)


def _local():
    scope = auth.current_scope()
    return scope is None or scope.is_local


# ---------------------------------------------------------------------------------------------- service

def get_project(project_id):
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise LookupError("Project not found")
    with _LOCK, get_db().transaction() as conn:
        if _local():
            _import_local(conn, project_id)
        return repo.get_project(conn, auth.workspace_id(), project_id)


def list_projects():
    with _LOCK, get_db().transaction() as conn:
        if _local():
            _import_local(conn)
        return repo.list_projects(conn, auth.workspace_id())


def create_project(data):
    values = _validate(data, creating=True)
    with _LOCK:
        engine = ProjectManager.create_project(values["name"])
        with get_db().transaction() as conn:
            repo.insert_project(conn, auth.workspace_id(), engine.project_id, values, auth.user_id())
            return repo.get_project(conn, auth.workspace_id(), engine.project_id)


def update_project(project_id, data):
    values = _validate(data)
    get_project(project_id)
    with _LOCK:
        with get_db().transaction() as conn:
            project = repo.update_project(conn, auth.workspace_id(), project_id, values)
        if "name" in values:
            engine = ProjectManager.get_project(project_id)
            if engine:
                engine.name = values["name"]
                ProjectManager.save_project(engine)
        return project


def project_creator(project_id):
    get_project(project_id)
    with get_db().transaction() as conn:
        return repo.project_row(conn, auth.workspace_id(), project_id)["created_by"]


def archive_project(project_id):
    get_project(project_id)
    with _LOCK, get_db().transaction() as conn:
        repo.archive_project(conn, auth.workspace_id(), project_id)


def add_source(project_id, data):
    if not isinstance(data, dict) or set(data) != {"name", "text"}:
        raise ValueError("Provide a source name and plain text")
    name, text = data["name"], data["text"]
    if not isinstance(name, str) or not name.strip() or len(name) > 160 or any(ord(c) < 32 for c in name):
        raise ValueError("Source name must be a single line of at most 160 characters")
    if not isinstance(text, str) or not text.strip() or len(text) > 24000 or "\x00" in text:
        raise ValueError("Source text must contain 1 to 24000 characters without null bytes")
    get_project(project_id)
    with _LOCK, get_db().transaction() as conn:
        return repo.add_source(conn, auth.workspace_id(), project_id, name.strip(), text, MAX_SOURCES, MAX_SOURCE_CHARS)


def remove_source(project_id, source_id):
    if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
        raise LookupError("Project source not found")
    get_project(project_id)
    with _LOCK, get_db().transaction() as conn:
        return repo.remove_source(conn, auth.workspace_id(), project_id, source_id)

"""Workspace metadata attached to real engine projects, without deleting run evidence."""
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..models.project import ProjectManager

_LOCK = threading.RLock()
_ID = re.compile(r"^proj_[a-f0-9]{12}$")
_CHAT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_FIELDS = {"name", "description", "instructions", "chat_ids", "run_names", "preferred_model"}
_SOURCE_ID = re.compile(r"^src_[a-f0-9]{12}$")


def _path(project_id):
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise LookupError("Project not found")
    root = Path(ProjectManager.PROJECTS_DIR).resolve()
    directory = root / project_id
    if directory.is_symlink() or directory.resolve().parent != root:
        raise LookupError("Project not found")
    return directory / "workspace.json"


def _write(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".workspace.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


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


def get_project(project_id):
    path = _path(project_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        engine = ProjectManager.get_project(project_id)
        if not engine:
            raise LookupError("Project not found") from exc
        # Existing graph projects remain visible before workspace metadata is added.
        value = {"id": engine.project_id, "engine_project_id": engine.project_id,
                 "name": engine.name, "description": "", "instructions": "", "chat_ids": [],
                 "run_names": [], "created_at": engine.created_at, "updated_at": engine.updated_at}
    if value.get("archived"):
        raise LookupError("Project not found")
    value.setdefault("sources", [])
    value.setdefault("preferred_model", "")
    return value


def list_projects():
    root = Path(ProjectManager.PROJECTS_DIR)
    if not root.exists():
        return []
    projects = []
    for directory in root.iterdir():
        if _ID.fullmatch(directory.name):
            try:
                projects.append(get_project(directory.name))
            except (LookupError, ValueError, OSError):
                continue
    return sorted(projects, key=lambda p: p["updated_at"], reverse=True)


def create_project(data):
    values = _validate(data, creating=True)
    with _LOCK:
        engine = ProjectManager.create_project(values["name"])
        value = {"id": engine.project_id, "engine_project_id": engine.project_id,
                 "name": engine.name, "description": "", "instructions": "", "chat_ids": [],
                 "run_names": [], "sources": [], "preferred_model": "", "created_at": engine.created_at, "updated_at": engine.updated_at, **values}
        _write(_path(engine.project_id), value)
        return value


def update_project(project_id, data):
    values = _validate(data)
    with _LOCK:
        value = get_project(project_id)
        value.update(values)
        value["updated_at"] = datetime.now(timezone.utc).isoformat()
        if "name" in values:
            engine = ProjectManager.get_project(project_id)
            if engine:
                engine.name = values["name"]
                ProjectManager.save_project(engine)
        _write(_path(project_id), value)
        return value


def archive_project(project_id):
    with _LOCK:
        value = get_project(project_id)
        value["archived"] = True
        value["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write(_path(project_id), value)



def add_source(project_id, data):
    if not isinstance(data, dict) or set(data) != {"name", "text"}:
        raise ValueError("Provide a source name and plain text")
    name, text = data["name"], data["text"]
    if not isinstance(name, str) or not name.strip() or len(name) > 160 or any(ord(c) < 32 for c in name):
        raise ValueError("Source name must be a single line of at most 160 characters")
    if not isinstance(text, str) or not text.strip() or len(text) > 24000 or "\x00" in text:
        raise ValueError("Source text must contain 1 to 24000 characters without null bytes")
    with _LOCK:
        project = get_project(project_id)
        if len(project["sources"]) >= 10:
            raise ValueError("A project can contain up to 10 sources")
        if sum(len(source.get("text", "")) for source in project["sources"]) + len(text) > 120000:
            raise ValueError("Project source text is limited to 120000 characters in total")
        project["sources"].append({"id": "src_" + uuid.uuid4().hex[:12], "name": name.strip(), "text": text,
                                   "created_at": datetime.now(timezone.utc).isoformat()})
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write(_path(project_id), project)
        return project


def remove_source(project_id, source_id):
    if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
        raise LookupError("Project source not found")
    with _LOCK:
        project = get_project(project_id)
        remaining = [source for source in project["sources"] if source["id"] != source_id]
        if len(remaining) == len(project["sources"]):
            raise LookupError("Project source not found")
        project["sources"] = remaining
        project["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write(_path(project_id), project)
        return project

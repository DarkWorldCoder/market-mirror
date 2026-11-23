"""Private local prompt-template storage. Skills are text, never executable imports."""
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from ..config import Config

GROUPS = ("Workspace", "Buyer research", "Advertising", "Strategy", "Go to market", "Validation", "Custom skills")
_FIELDS = {"name", "description", "instructions", "group", "source_url"}
_ID = re.compile(r"^skill_[a-f0-9]{32}$")
_LOCK = threading.RLock()


def _root(create=False):
    root = Path(Config.UPLOAD_FOLDER).resolve() / "workspace_skills"
    if root.is_symlink():
        raise ValueError("Skill storage must be a local directory")
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _path(skill_id):
    if not isinstance(skill_id, str) or not _ID.fullmatch(skill_id):
        raise LookupError("Skill not found")
    root = _root()
    path = root / f"{skill_id}.json"
    if path.is_symlink() or path.resolve().parent != root:
        raise LookupError("Skill not found")
    return path


def _validate(data, creating=False):
    if not isinstance(data, dict) or set(data) - _FIELDS:
        raise ValueError("Use name, description, instructions, group and source_url only")
    if creating and not {"name", "instructions"} <= set(data):
        raise ValueError("Give the skill a name and instructions")
    values = {}
    for field, value in data.items():
        maximum = {"name": 120, "description": 300, "instructions": 12000, "group": 40, "source_url": 2000}[field]
        if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
            raise ValueError(f"{field} must be text of at most {maximum} characters")
        value = value.strip()
        if field in {"name", "instructions"} and not value:
            raise ValueError(f"Give the skill a non-empty {field}")
        if field == "group" and value not in GROUPS:
            raise ValueError("Choose an available skill category")
        if field == "source_url" and value:
            try:
                url = urlsplit(value)
                valid = url.scheme in {"https", "http"} and bool(url.hostname) and not url.username and not url.password
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("Source must be an HTTP(S) link without credentials")
        values[field] = value
    return values


def _write(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".skill.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def get_skill(skill_id):
    try:
        value = json.loads(_path(skill_id).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LookupError("Skill not found") from error
    if not isinstance(value, dict) or value.get("id") != skill_id or not isinstance(value.get("updated_at"), str):
        raise ValueError("The saved skill record is invalid")
    _validate({key: value[key] for key in _FIELDS if key in value}, creating=True)
    return value


def list_skills():
    root = _root()
    if not root.exists():
        return []
    items = []
    for path in root.iterdir():
        if path.suffix == ".json" and _ID.fullmatch(path.stem) and not path.is_symlink():
            try:
                items.append(get_skill(path.stem))
            except (LookupError, ValueError, OSError):
                continue
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


def create_skill(data):
    values = _validate(data, creating=True)
    with _LOCK:
        root = _root(create=True)
        if len(list_skills()) >= 200:
            raise ValueError("This workspace already has 200 custom skills")
        timestamp = datetime.now(timezone.utc).isoformat()
        skill = {"id": f"skill_{uuid4().hex}", "name": values["name"], "description": "", "instructions": values["instructions"], "group": "Custom skills", "source_url": "", "created_at": timestamp, "updated_at": timestamp, **values}
        _write(root / f"{skill['id']}.json", skill)
        return skill


def update_skill(skill_id, data):
    values = _validate(data)
    with _LOCK:
        skill = get_skill(skill_id)
        skill.update(values)
        skill["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write(_path(skill_id), skill)
        return skill


def delete_skill(skill_id):
    with _LOCK:
        get_skill(skill_id)
        _path(skill_id).unlink()

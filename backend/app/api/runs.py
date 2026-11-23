"""Loopback-only read access to saved run folders for the workspace dashboard.

The CLI writes each run to `mirofish_runs/<name>/` (summary.json, survey.json, feed_test.json, graph.json,
disclosure.md, dashboard.html...). The workspace lists those folders and reads their result files through this
blueprint. Every route needs the local setup token, like the workflow API. Only plain files directly inside a run
folder, with a known extension, can be read; names are checked before any path is built.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, send_from_directory

from .setup import _guard

runs_bp = Blueprint("runs", __name__)
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(json|md|csv|html)$")
MAX_JSON = 25 * 1024 * 1024


def runs_root() -> Path:
    """MIROFISH_RUNS_DIR, else `mirofish_runs` at the repository root (where the CLI writes runs by default)."""
    env = os.environ.get("MIROFISH_RUNS_DIR")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[3] / "mirofish_runs"


def _run_dir(name: str) -> Path:
    if not isinstance(name, str) or not NAME.match(name) or ".." in name:
        raise LookupError("unknown run")
    root = runs_root()
    path = (root / name).resolve()
    if path.parent != root or not path.is_dir():
        raise LookupError("unknown run")
    return path


def _read(path: Path) -> Optional[Any]:
    try:
        if path.stat().st_size > MAX_JSON:
            return None
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and "success" in data and "data" in data:
        data = data["data"]
    return data


def _card(path: Path) -> Dict[str, Any]:
    manifest = _read(path / "run_manifest.json") or {}
    summary = _read(path / "summary.json") or {}
    mk = summary.get("marketing") if isinstance(summary, dict) else None
    decision = (summary.get("decision") or {}) if isinstance(summary, dict) else {}
    when = manifest.get("finished_at") or manifest.get("started_at")
    return {"name": path.name, "title": manifest.get("title") or summary.get("project_name") or path.name,
            "decision": decision.get("decision"), "summary": decision.get("summary"),
            "people": (mk or {}).get("people") or summary.get("agents"),
            "simulation_id": manifest.get("simulation_id") or summary.get("simulation_id"),
            "updated_at": when, "mtime": path.stat().st_mtime,
            "has_dashboard": (path / "dashboard.html").is_file()}


@runs_bp.before_request
def protect():
    if request.path.startswith("/api/runs"):
        return _guard(write=request.method != "GET")


@runs_bp.errorhandler(LookupError)
def missing(error):
    return jsonify(success=False, error=str(error) or "not found"), 404


def ok(value):
    response = jsonify(success=True, data=value)
    response.headers["Cache-Control"] = "no-store"
    return response


@runs_bp.get("/api/runs")
def list_runs():
    root = runs_root()
    if not root.is_dir():
        return ok({"root": str(root), "runs": []})
    dirs = [d for d in root.iterdir() if d.is_dir() and NAME.match(d.name) and not d.name.startswith("_")
            and ((d / "summary.json").is_file() or (d / "run_manifest.json").is_file())]
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return ok({"root": str(root), "runs": [_card(d) for d in dirs[:200]]})


@runs_bp.get("/api/runs/<name>")
def run_detail(name):
    path = _run_dir(name)
    files = sorted(f.name for f in path.iterdir() if f.is_file() and FILE.match(f.name))
    return ok({**_card(path), "files": files, "manifest": _read(path / "run_manifest.json") or {},
               "summary": _read(path / "summary.json") or {}})


@runs_bp.get("/api/runs/<name>/files/<filename>")
def run_file(name, filename):
    path = _run_dir(name)
    if not FILE.match(filename) or not (path / filename).is_file():
        raise LookupError("unknown file")
    if filename.endswith(".json"):
        data = _read(path / filename)
        if data is None:
            raise LookupError("file too large or not valid JSON")
        return ok(data)
    response = send_from_directory(path, filename, as_attachment=request.args.get("download") == "1")
    response.headers["Cache-Control"] = "no-store"
    if filename.endswith(".html"):          # the exported dashboard: a self-contained page, shown sandboxed
        response.headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups allow-downloads"
    return response

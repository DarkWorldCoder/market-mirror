"""Loopback-only read access to saved run folders for the workspace dashboard.

The CLI writes each run to `mirofish_runs/<name>/` (summary.json, survey.json, feed_test.json, graph.json,
disclosure.md, dashboard.html...). The workspace lists those folders and reads their result files through this
blueprint. Every route needs the local setup token, like the workflow API, or (in team mode) a signed-in member
of a workspace, who sees only the runs in that workspace's run index. Only plain files directly inside a run
folder, with a known extension, can be read; names are checked before any path is built.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, send_from_directory

from .. import auth

runs_bp = Blueprint("runs", __name__)
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(json|md|csv|html)$")
MAX_JSON = 25 * 1024 * 1024


def runs_root() -> Path:
    """MIROFISH_RUNS_DIR, else `mirofish_runs` at the repository root (where the CLI writes runs by default)."""
    env = os.environ.get("MIROFISH_RUNS_DIR")
    return Path(env).resolve() if env else Path(__file__).resolve().parents[3] / "mirofish_runs"


def _run_dir(name: str) -> Path:
    if not isinstance(name, str) or not NAME.fullmatch(name) or ".." in name or not auth.run_allowed(name):
        raise LookupError("unknown run")
    root = runs_root()
    candidate = root / name
    path = candidate.resolve()
    if candidate.is_symlink() or path.parent != root or not path.is_dir():
        raise LookupError("unknown run")
    return path


def _read(path: Path) -> Optional[Any]:
    try:
        if not _plain_file(path) or path.stat().st_size > MAX_JSON:
            return None
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and "success" in data and "data" in data:
        data = data["data"]
    return data


def _plain_file(path: Path) -> bool:
    return not path.is_symlink() and path.is_file()


def _object(value: Any) -> Dict[str, Any]:
    """Metadata files and nested metadata must be objects; result files may contain arrays."""
    return value if isinstance(value, dict) else {}


def _files(path: Path):
    return sorted(f.name for f in path.iterdir() if FILE.fullmatch(f.name) and _plain_file(f))


def _card(path: Path) -> Dict[str, Any]:
    manifest = _object(_read(path / "run_manifest.json"))
    summary = _object(_read(path / "summary.json"))
    mk = _object(summary.get("marketing"))
    decision = _object(summary.get("decision"))
    status = _object(_read(path / "run_status.json"))
    when = manifest.get("finished_at") or manifest.get("started_at")
    return {"name": path.name, "title": manifest.get("title") or summary.get("project_name") or path.name,
            "decision": decision.get("decision"), "summary": decision.get("summary"),
            "people": mk.get("people", summary.get("agents")),
            "simulation_id": manifest.get("simulation_id") or summary.get("simulation_id"),
            "updated_at": when, "mtime": path.stat().st_mtime,
            "has_dashboard": _plain_file(path / "dashboard.html"),
            "file_count": len(_files(path)),
            "status": status.get("runner_status") or summary.get("runner_status") or summary.get("simulation_status"),
            "progress_percent": status.get("progress_percent"),
            "current_round": status.get("current_round", summary.get("current_round")),
            "total_rounds": status.get("total_rounds", summary.get("total_rounds"))}


@runs_bp.before_request
def protect():
    if request.path.startswith("/api/runs"):
        return auth.require("viewer")


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
    dirs = [d for d in root.iterdir() if not d.is_symlink() and d.is_dir() and NAME.fullmatch(d.name) and ".." not in d.name
            and (_plain_file(d / "summary.json") or _plain_file(d / "run_manifest.json"))]
    dirs = [d for d in dirs if auth.run_allowed(d.name)]
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    scope = auth.current_scope()
    if scope is not None and scope.is_local:
        _index_local(d.name for d in dirs)
    return ok({"root": "" if scope is not None and not scope.is_local else str(root), "runs": [_card(d) for d in dirs]})


def _index_local(names) -> None:
    """Keep the local workspace's run index in step with the run folders on this computer."""
    from ..db import get_db, repo
    try:
        with get_db().transaction() as conn:
            for name in names:
                repo.add_run(conn, repo.LOCAL_WORKSPACE, name, repo.LOCAL_USER)
    except Exception:  # the folder listing is the answer; the index is bookkeeping
        pass


@runs_bp.get("/api/runs/insights")
def run_insights():
    """One aggregate across every saved run for the workspace overview, from saved files only (no model calls):
    activity per day, decision mix, buying intent, objections, segments, geography, evidence and real-sample checks,
    recorded spend, the forecast ledger and runs still running. Cached per run by file mtimes."""
    from ..services import run_insights as insights
    root = runs_root()
    return ok({**insights.collect(root), "root": str(root)})   # a missing root gives empty lists


def _sim_folder(sid: Any) -> Optional[Path]:
    """The simulation's folder on this backend, when it is there (chat with people and the report agent needs it)."""
    from ..config import Config
    if not isinstance(sid, str) or not NAME.fullmatch(sid) or ".." in sid:
        return None
    root = Path(Config.OASIS_SIMULATION_DATA_DIR).resolve()
    candidate = root / sid
    path = candidate.resolve()
    return path if not candidate.is_symlink() and path.parent == root and path.is_dir() else None


@runs_bp.get("/api/runs/<name>")
def run_detail(name):
    path = _run_dir(name)
    card = _card(path)
    return ok({**card, "files": _files(path), "manifest": _object(_read(path / "run_manifest.json")),
               "summary": _object(_read(path / "summary.json")),
               "simulation_on_backend": _sim_folder(card.get("simulation_id")) is not None})


@runs_bp.get("/api/runs/<name>/thoughts")
def run_thoughts(name):
    """What the simulated people wrote (private thoughts in feeds and landing pages, survey and pitch replies, posts),
    harvested from the run folder and, when it is on this backend, the simulation folder. No model call."""
    from ..services import agent_thoughts
    path = _run_dir(name)
    sim = _sim_folder(_card(path).get("simulation_id"))
    return ok(agent_thoughts.harvest_thoughts(str(sim) if sim else None, str(path)))


STAGES = [("graph", "Market map built", "graph_id"), ("people", "Simulated people created", "simulation_id"),
          ("rounds", "Social rounds", "runner_status"), ("feed", "Ads scrolled in feeds", "feed_test"),
          ("survey", "Buyer survey", "survey"), ("pitch", "Sales pitch", "pitch"), ("panel", "Analyst panel", "panel"),
          ("report", "Report written", "report"), ("export", "Dashboard exported", "export")]


@runs_bp.get("/api/runs/<name>/status")
def run_status(name):
    """The run's stages, its round status (live from the runner when the simulation is on this backend, else the
    saved run_status.json) and actions per round from timeline.json."""
    path = _run_dir(name)
    manifest = _object(_read(path / "run_manifest.json"))
    sid = _card(path).get("simulation_id")  # manifest first, then summary.json, as in run detail
    live = None
    if _sim_folder(sid):
        try:
            from ..services.simulation_runner import SimulationRunner
            state = SimulationRunner.get_run_state(sid)
            live = state.to_dict() if state else None
        except Exception:  # noqa: BLE001 - the saved status is shown instead
            live = None
    timeline = _read(path / "timeline.json")
    rounds = [{"round": r.get("round_num"), "actions": r.get("total_actions") or 0,
               "twitter": r.get("twitter_actions") or 0, "reddit": r.get("reddit_actions") or 0,
               "active": r.get("active_agents_count") or 0}
              for r in (timeline if isinstance(timeline, list) else []) if isinstance(r, dict)]
    stages = [{"id": i, "label": label, "done": bool(manifest.get(key))} for i, label, key in STAGES
              if manifest.get(key) or i in ("graph", "people", "report")]
    return ok({"simulation_id": sid, "live": live is not None, "run": live or _object(_read(path / "run_status.json")),
               "stages": stages, "rounds": rounds, "error": manifest.get("error"),
               "started_at": manifest.get("started_at"), "finished_at": manifest.get("finished_at")})


@runs_bp.get("/api/runs/<name>/files/<filename>")
def run_file(name, filename):
    path = _run_dir(name)
    if not FILE.fullmatch(filename) or not _plain_file(path / filename):
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

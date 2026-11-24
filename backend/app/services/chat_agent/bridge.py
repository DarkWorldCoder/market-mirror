"""One shared tool layer: the chat agent calls the MCP server's own tool functions in-process.

The MCP server (`plugin/skills/market-mirror/scripts/mcp_server.py`) is loaded once under a private module name, so
there is no second copy of any tool logic. Its spend approval runs through elicitation: the chat context's
``elicit()`` raises the server's ``NeedInput`` carrying the elicitation, the agent saves it as a pending approval,
and the same call is made again with the user's answer.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import tools as T

REPO = Path(__file__).resolve().parents[4]
MCP_PATH = REPO / "plugin" / "skills" / "market-mirror" / "scripts" / "mcp_server.py"
_LOCK = threading.Lock()
_MODULE = None


class ApprovalNeeded(Exception):
    """A tool needs the user before it can run (the MCP server's NeedInput, translated)."""

    def __init__(self, key: str, elicitation: Dict[str, Any]):
        super().__init__("approval needed")
        self.key, self.elicitation = key, elicitation


def engine_home() -> str:
    """The engine the app runs on: MARKET_MIRROR_HOME when set, else this checkout."""
    return os.environ.get("MARKET_MIRROR_HOME") or str(REPO)


def mcp():
    """The MCP server module, loaded once. Its home() is the app's engine, and mm.sh subprocesses use the same."""
    global _MODULE
    with _LOCK:
        if _MODULE is None:
            spec = importlib.util.spec_from_file_location("marketmirror_mcp_inprocess", MCP_PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.home = engine_home
            os.environ.setdefault("MARKET_MIRROR_HOME", engine_home())
            _MODULE = module
        return _MODULE


def chat_ctx(answers: Optional[Dict[str, Any]] = None):
    """A request context for in-process calls: it can always elicit, and an unanswered elicitation raises NeedInput."""
    m = mcp()

    class ChatCtx(m.Ctx):
        def __init__(self):
            super().__init__(m.Session("workspace-chat"))
            self.answers = dict(answers or {})

        def can_elicit(self) -> bool:
            return True

        def tasks(self):
            return None

        def elicit(self, key, params):
            if key in self.answers:
                return self.answers[key]
            raise m.NeedInput({key: {"method": "elicitation/create", "params": params}})

    return ChatCtx()


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(name: str, fallback: str) -> str:
    base = SAFE_NAME.sub("_", os.path.basename(str(name or "")))[:100].strip("._")
    return base or fallback


class Executor:
    """Runs tools for the agent loop. Tests replace it with a fake that records calls."""

    def __init__(self):
        self._mcp = None

    @property
    def m(self):
        if self._mcp is None:
            self._mcp = mcp()
        return self._mcp

    @property
    def usd_per_call(self) -> float:
        return float(self.m.USD_PER_CALL)

    # ---- tools ----------------------------------------------------------------
    def call(self, name: str, args: Dict[str, Any], *, answers: Optional[Dict[str, Any]] = None,
             allowed_urls: Optional[List[str]] = None, approval: Optional[str] = None) -> Any:
        """Run one tool. `approval` is the user's recorded decision for a spend tool (the loop only calls spend tools
        once it is set); market_test's own approval travels in `answers` to the MCP server's elicitation."""
        if name == "open_view":
            from ...api import runs
            path = runs._run_dir(args.get("run"))
            card = runs._card(path)
            return {"view": args.get("view"), "run": path.name, "title": card.get("title"), "files": runs._files(path)}
        if name == "read_run_file":
            from .. import workspace_chat
            data, _ = workspace_chat._tool("read_run_file", {k: args[k] for k in ("run", "file", "offset", "limit") if k in args})
            return data
        if name == "browse_page":
            if args.get("url") not in (allowed_urls or []):
                raise ValueError("Choose a page address you gave in this chat.")
            from ..workspace_browser import observe
            return observe({"url": args["url"]})
        if name not in T.MCP_TOOLS:
            raise ValueError(f"unknown tool {name}")
        try:
            return self.m.call(name, args, chat_ctx(answers))
        except self.m.NeedInput as need:
            key, request = next(iter(need.requests.items()))
            raise ApprovalNeeded(key, (request or {}).get("params") or {}) from None

    def tool_schemas(self) -> Dict[str, Dict[str, Any]]:
        """The MCP server's own descriptions and input schemas for the tools the chat may call."""
        out = {}
        for tool in self.m.TOOLS:
            if tool["name"] not in T.MCP_TOOLS:
                continue
            description = tool["description"]
            if tool["name"] == "market_test":
                description += " In this app the user approves spend on a card; never set approve_spend."
            out[tool["name"]] = {"description": description[:1800], "parameters": tool["inputSchema"]}
        return out

    def job_status(self, job_id: str) -> Dict[str, Any]:
        return self.m.job_status(job_id, tail=15)

    # ---- estimates ------------------------------------------------------------
    def runs(self) -> List[Dict[str, Any]]:
        from ...api import runs
        root = runs.runs_root()
        if not root.is_dir():
            return []
        paths = [p for p in root.iterdir() if not p.is_symlink() and p.is_dir() and runs.NAME.fullmatch(p.name)
                 and (runs._plain_file(p / "summary.json") or runs._plain_file(p / "run_manifest.json"))]
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [runs._card(p) for p in paths[:40]]

    def simulation_people(self, simulation_id: str) -> Optional[int]:
        for card in self.runs():
            if card.get("simulation_id") == simulation_id:
                return self.m._planned_people({"simulation_id": simulation_id, "name": card["name"]})
        return None

    def spend_plan(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "market_test":
            return self.m.spend_plan(dict(args.get("config") or {}))
        people = self.simulation_people(args["simulation_id"]) if isinstance(args.get("simulation_id"), str) else None
        return T.plan_from(T.estimate_calls(name, args, people), people, self.usd_per_call)

    def fit_check(self, cfg: Dict[str, Any], people: List[Dict[str, Any]], brief: str = "") -> Dict[str, Any]:
        try:
            from claude_cli import fit_check
        except ImportError:
            spec = importlib.util.spec_from_file_location("mm_fit_check", REPO / "backend" / "claude_cli" / "fit_check.py")
            fit_check = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fit_check)
        return fit_check.check(cfg, people, brief)

    def personas_of(self, cfg: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Planned people of a market_test config from its persona spec (segments), for the fit check before spend."""
        spec = cfg.get("personas")
        if isinstance(spec, str):
            path = spec if os.path.isabs(spec) else os.path.join(engine_home(), spec)
            try:
                with open(path, encoding="utf-8") as f:
                    spec = json.load(f)
            except (OSError, ValueError):
                return None
        if isinstance(spec, dict) and isinstance(spec.get("segments"), list):
            try:
                return T.pseudo_people(T.normalize_segments(spec["segments"]))
            except ValueError:
                return None
        return None

    # ---- files ------------------------------------------------------------------
    def _chat_dir(self, session_id: str, kind: str) -> str:
        path = os.path.join(engine_home(), "scenarios", "_chat", _safe(session_id, "session"), kind)
        os.makedirs(path, mode=0o700, exist_ok=True)
        return path

    def save_upload(self, session_id: str, name: str, text: str) -> str:
        path = os.path.join(self._chat_dir(session_id, "uploads"), _safe(name, "upload_" + uuid.uuid4().hex[:6]))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def save_audience(self, session_id: str, name: str, spec: Dict[str, Any]) -> str:
        path = os.path.join(self._chat_dir(session_id, "audiences"), _safe(name, "audience") + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(spec, f, ensure_ascii=False, indent=2)
        return path

    def product_profile(self) -> Optional[Dict[str, Any]]:
        folder = Path(engine_home()) / "scenarios" / "_profiles"
        try:
            files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            return json.loads(files[0].read_text(encoding="utf-8")) if files else None
        except (OSError, ValueError):
            return None

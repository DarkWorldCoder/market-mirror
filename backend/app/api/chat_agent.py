"""Token-protected chat agent endpoints: a streamed agent turn, live audience estimates, job polling, the tool list."""
import json
import logging
import os
import queue
import re
import threading

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from .setup import _guard
from ..services.chat_agent import loop, tools as T
from ..services.chat_agent.bridge import Executor

chat_agent_bp = Blueprint("chat_agent", __name__)
EVENTS = {"plan", "tool_start", "tool_progress", "approval_request", "tool_result", "artifact", "error", "done"}
MAX_EVENT = 256000
_log = logging.getLogger(__name__)


def _turn_limit() -> int:
    """Concurrent agent turns (each one is a model loop on its own thread). MM_AGENT_MAX_TURNS, default 2.
    A value that is not a whole number falls back to the default instead of stopping the app at import."""
    raw = (os.environ.get("MM_AGENT_MAX_TURNS") or "").strip()
    if not raw:
        return 2
    try:
        return max(1, int(raw))
    except ValueError:
        _log.warning("MM_AGENT_MAX_TURNS=%r is not a whole number; using 2", raw)
        return 2


TURN_SLOTS = threading.BoundedSemaphore(_turn_limit())
_ACTIVE_TURNS = 0
_ACTIVE_LOCK = threading.Lock()


def _take_slot() -> bool:
    global _ACTIVE_TURNS
    if not TURN_SLOTS.acquire(blocking=False):
        return False
    with _ACTIVE_LOCK:
        _ACTIVE_TURNS += 1
    return True


def _free_slot() -> None:
    global _ACTIVE_TURNS
    with _ACTIVE_LOCK:
        _ACTIVE_TURNS -= 1
    TURN_SLOTS.release()


def active_turns() -> int:
    """Agent turns running in this process right now (for /metrics)."""
    with _ACTIVE_LOCK:
        return _ACTIVE_TURNS


@chat_agent_bp.before_request
def protect():
    return _guard(write=request.method != "GET")


def ok(value):
    response = jsonify(success=True, data=value)
    response.headers["Cache-Control"] = "no-store"
    return response


@chat_agent_bp.post("/api/workspace/agent/stream")
def stream():
    """Stream one agent turn (or its resumption after an approval) as server-sent events."""
    if request.content_length is not None and request.content_length > 1_200_000:
        return jsonify(success=False, error="This request is too large. Attach fewer or smaller files."), 413
    value = request.get_json(silent=True)
    try:
        loop.validate(value)
    except (ValueError, TypeError) as error:
        return jsonify(success=False, error=str(error)), 400
    if not _take_slot():
        response = jsonify(success=False, error="Too many agent turns are running. Wait for one to finish, then try again.")
        response.headers["Retry-After"] = "5"
        return response, 429
    app = current_app._get_current_object()
    messages = queue.Queue(maxsize=256)
    disconnected = threading.Event()

    def emit(event, data):
        if disconnected.is_set() or event not in EVENTS:
            return
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_EVENT:
            slim = {k: v for k, v in data.items() if k not in ("result", "files", "preview")}
            slim["truncated"] = True
            encoded = json.dumps(slim, ensure_ascii=False, separators=(",", ":"), default=str)
        while not disconnected.is_set():
            try:
                messages.put((event, encoded), timeout=0.1)
                return
            except queue.Full:
                continue

    def work():
        try:
            with app.app_context():
                try:
                    loop.run_turn(value, emit, disconnected=disconnected.is_set)
                except ValueError as error:
                    emit("error", {"message": str(error), "status": 400, "code": "request", "actions": []})
                except loop.AgentError as error:
                    emit("error", error.body())
                except Exception:  # noqa: BLE001 - private details never reach the browser
                    current_app.logger.exception("chat agent turn failed")
                    emit("error", {"message": "Could not complete this response. Try again.", "status": 500,
                                   "code": "server", "actions": []})
        finally:
            _free_slot()

    @stream_with_context
    def events():
        try:
            while not disconnected.is_set():
                try:
                    event, encoded = messages.get(timeout=15)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {event}\ndata: {encoded}\n\n"
                if event in {"done", "error"}:
                    return
        finally:
            disconnected.set()

    try:
        threading.Thread(target=work, name="workspace-agent-turn", daemon=True).start()
    except Exception:
        _free_slot()
        raise
    response = Response(events(), content_type="text/event-stream; charset=utf-8")
    response.headers["Cache-Control"] = "no-store, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.call_on_close(disconnected.set)
    return response


@chat_agent_bp.post("/api/workspace/agent/audience/estimate")
def audience_estimate():
    """Live numbers for the audience table: people, model calls, rough dollars and fit-check flags. No model call."""
    value = request.get_json(silent=True) or {}
    try:
        segments = T.normalize_segments(value.get("segments"))
    except ValueError as error:
        return jsonify(success=False, error=str(error)), 400
    ex = Executor()
    cfg = {"personas": T.persona_spec(segments)}
    return ok({"segments": segments, "people": sum(s["count"] for s in segments),
               "estimate": ex.spend_plan("market_test", {"config": cfg}),
               "fit_check": ex.fit_check(cfg, T.pseudo_people(segments), "")})


@chat_agent_bp.get("/api/workspace/agent/jobs/<job_id>")
def job(job_id):
    if not re.fullmatch(r"[a-f0-9]{10}", job_id or ""):
        return jsonify(success=False, error="unknown job"), 404
    status = Executor().job_status(job_id)
    if status.get("error"):
        return jsonify(success=False, error="unknown job"), 404
    return ok({k: status.get(k) for k in ("job_id", "label", "status", "elapsed_s", "log_tail", "result")})


@chat_agent_bp.get("/api/workspace/agent/tools")
def tool_list():
    rows = [{"name": name, "label": T.LABELS.get(name, name), "cost": T.classify(name, {})["cost"],
             "phases": [p for p in T.PHASES if name in T.phase_tools(p)], "simulated": name in T.SIMULATED,
             "source": "app" if name in T.APP_TOOLS else "mcp"} for name in T.all_tools()]
    return ok({"tools": rows, "max_steps": loop.MAX_STEPS})

"""Token-protected local conversational workspace endpoint."""
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
import json
import queue
import threading
from urllib.parse import urlsplit

from .setup import _loopback
from . import setup as setup_api
from .. import auth
from ..services import workspace_chat as service

workspace_chat_bp = Blueprint("workspace_chat", __name__)


@workspace_chat_bp.before_request
def protect():
    if request.endpoint == "workspace_chat.session":
        return None
    # Asking the model is an editor's action; listing the models is open to every member.
    return auth.require("editor" if request.method != "GET" else "viewer")


@workspace_chat_bp.post("/api/workspace/chat")
def chat():
    if request.content_length is not None and request.content_length > 200000:
        return jsonify(success=False, error="This conversation is too large. Start a new chat."), 413
    try:
        result = service.chat(request.get_json(silent=True))
    except ValueError as error:
        return jsonify(success=False, error=str(error)), 400
    except service.ChatError as error:
        return jsonify(success=False, error=str(error)), error.status
    response = jsonify(success=True, data=result)
    response.headers["Cache-Control"] = "no-store"
    return response


@workspace_chat_bp.post("/api/workspace/chat/stream")
def chat_stream():
    """Stream public stage events and the final answer, never private model reasoning."""
    if request.content_length is not None and request.content_length > 200000:
        return jsonify(success=False, error="This conversation is too large. Start a new chat."), 413
    value = request.get_json(silent=True)
    try:
        service.validate_request(value)
    except (ValueError, TypeError) as error:
        return jsonify(success=False, error=str(error)), 400

    app = current_app._get_current_object()
    messages = queue.Queue(maxsize=64)
    disconnected = threading.Event()

    def enqueue(event, data):
        if disconnected.is_set():
            return
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str, allow_nan=False)
        while not disconnected.is_set():
            try:
                messages.put((event, encoded), timeout=0.1)
                return
            except queue.Full:
                continue

    def observe(event):
        if not isinstance(event, dict) or event.get("type") not in {"model", "tool", "agent"}:
            return
        # Service-owned public summaries/results only. Unknown model internals are not forwarded.
        allowed = {"type", "status", "label", "tool", "turn", "run", "file", "id", "role", "provider", "model", "summary", "data"}
        progress = {key: item for key, item in event.items() if key in allowed}
        if len(json.dumps(progress, ensure_ascii=False, default=str).encode("utf-8")) > 256000:
            progress.pop("data", None)
            progress["data_truncated"] = True
        enqueue("progress", progress)

    def work():
        with app.app_context():
            try:
                result = service.chat(value, on_event=observe)
                enqueue("result", result)
            except ValueError as error:
                enqueue("error", {"message": str(error), "status": 400})
            except service.ChatError as error:
                enqueue("error", {"message": str(error), "status": error.status})
            except Exception:
                enqueue("error", {"message": "Could not complete this response. Try again.", "status": 500})

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
                if event in {"result", "error"}:
                    return
        finally:
            # A closed browser stops delivery, not an upstream provider call already in progress.
            disconnected.set()

    threading.Thread(target=auth.run_in_scope(work), name="workspace-chat-stream", daemon=True).start()
    response = Response(events(), content_type="text/event-stream; charset=utf-8")
    response.headers["Cache-Control"] = "no-store, no-transform"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.call_on_close(disconnected.set)
    return response


@workspace_chat_bp.get("/api/workspace/models")
def models():
    response = jsonify(success=True, data=service.models())
    response.headers["Cache-Control"] = "no-store"
    return response


@workspace_chat_bp.get("/api/workspace/session")
def session():
    """Bootstrap only a same-origin browser on a literal local app host."""
    host = urlsplit(request.host_url).hostname
    origin = request.headers.get("Origin")
    same_origin = request.headers.get("Sec-Fetch-Site") == "same-origin"
    if (not _loopback() or host not in {"127.0.0.1", "localhost", "::1"} or not same_origin
            or (origin and origin.rstrip("/") != request.host_url.rstrip("/"))):
        return jsonify(success=False, error="Open MarketMirror on this computer to connect."), 403
    response = jsonify(success=True, data={"token": setup_api.SETUP_TOKEN})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

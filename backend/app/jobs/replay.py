"""Run a queued endpoint job in any process by calling the endpoint again.

Endpoints that start background work validate the request, then hand a closure to `jobs.submit`. The closure itself
cannot be stored, so the job keeps the request (method, path, JSON body and the few headers that change behaviour:
language and workspace). A worker that has no closure (another process, or the server after a restart) re-runs the
endpoint through Flask's test client with a job context set on its thread:

* `TaskManager().create_task(...)` returns the job's own id (the task the client is already polling);
* `jobs.submit(...)` runs the closure inline on the worker thread instead of queueing it again;
* production auth and rate limits are skipped for that in-process call only (a contextvar no client can set).

The endpoint validates again, so a job whose simulation was deleted in the meantime fails cleanly.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from . import context as jctx

REPLAY_HEADERS = ("Accept-Language", "X-MM-Workspace")

_APP = None
_APP_LOCK = threading.Lock()


def set_app(app) -> None:
    global _APP
    _APP = app


def _app():
    global _APP
    with _APP_LOCK:
        if _APP is None:
            from .. import create_app
            _APP = create_app()
        return _APP


def request_payload() -> Optional[Dict[str, Any]]:
    """What a replay needs from the current request (None outside a request)."""
    try:
        from flask import has_request_context, request
    except ImportError:
        return None
    if not has_request_context():
        return None
    headers = {h: request.headers[h] for h in REPLAY_HEADERS if request.headers.get(h)}
    return {"method": request.method, "path": request.path, "query": request.query_string.decode("utf-8", "replace"),
            "json": request.get_json(silent=True), "headers": headers}


def run_replay(job: Dict[str, Any], ctx: jctx.JobContext) -> Any:
    from .runner import ReplayRejected
    payload = job.get("payload") or {}
    if not payload.get("path"):
        raise ReplayRejected("this job has no request to re-run")
    ctx.replay = True
    path = payload["path"] + (("?" + payload["query"]) if payload.get("query") else "")
    client = _app().test_client()
    resp = client.open(path, method=payload.get("method") or "POST", json=payload.get("json"),
                       headers=payload.get("headers") or {})
    if ctx.replay_error is not None:
        raise ctx.replay_error
    data = resp.get_json(silent=True) or {}
    if resp.status_code >= 400 or data.get("success") is False:
        raise ReplayRejected(str(data.get("error") or f"HTTP {resp.status_code}"))
    return data.get("data", data)

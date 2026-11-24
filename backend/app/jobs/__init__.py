"""Durable job queue for long work (graph build, persona preparation, OASIS starts, feed test, survey, pitch, focus
group, report and the other market tests).

Why SQLite (WAL) and not Redis/RQ or Celery
-------------------------------------------
* The local app must stay one command with no extra service. The queue lives in the same SQLite file as the task
  store (`MM_TASK_DB_PATH`, or `MM_JOB_DB_PATH`), so there is nothing to install or run.
* Claims are single `BEGIN IMMEDIATE` transactions, which SQLite serialises across processes, so several worker
  processes on one host (`python -m app.jobs.worker`) share the queue safely. Jobs take minutes and claims are a few
  per second at most, far below what SQLite handles.
* Admission needs the whole picture at claim time (running jobs per provider, per workspace and per lane, the spend
  cap, the single OASIS runner). That is one SQL query here; RQ/Celery would need a second coordination store.
* RQ also wants picklable callables and forks per job; the work here is closures over validated request data, which
  is why jobs carry the request and re-run their endpoint (see replay.py).
For several hosts, point every host at one Postgres instead: the claim is the same shape (`SELECT ... FOR UPDATE
SKIP LOCKED`), and only `store.py` changes. That is not built yet (see docs/JOBS.md).

How a job runs
--------------
`submit(task_id, fn, ...)` writes the job (id = the task id the client polls) and, in the server, binds `fn` to this
process's runner. With `MM_JOB_EXTERNAL_WORKERS=1` endpoint jobs are left unbound for worker processes, which re-run
the endpoint (replay). Jobs whose closure exists only here (prepare, graph build, report) always run in the server.
The OASIS runner is single-process by design: OASIS starts queue in the `oasis` lane, which only the server takes,
gated by its live round count (`MM_OASIS_MAX_RUNS`, default 2).
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, Optional

from . import context
from .context import JobCancelled, checkpoint, replaying
from .limits import from_env as limits_from_env
from .runner import JobRunner
from .store import (ACTIVE, CANCELLED, FAILED, NEEDS_APPROVAL, QUEUED, RUNNING, SUCCEEDED, TERMINAL, JobStore)

logger = logging.getLogger("mirofish.jobs")

__all__ = ["submit", "cancel", "approve", "get", "summary", "checkpoint", "replaying", "JobCancelled",
           "register_handler", "register_gate", "start_runner", "runner", "stop_runner", "store", "init_app",
           "start_for_app"]

_STORE = JobStore()
_RUNNER: Optional[JobRunner] = None
_RUNNER_LOCK = threading.Lock()
HANDLERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {}
GATES: Dict[str, Callable[[Dict[str, Dict[str, int]]], bool]] = {}   # lane -> gate(running counts)


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def store() -> JobStore:
    return _STORE


def external_workers() -> bool:
    return os.environ.get("MM_JOB_EXTERNAL_WORKERS", "").strip().lower() in ("1", "true", "yes")


def lease_s() -> float:
    return _env_float("MM_JOB_LEASE_S", 60.0, 2.0)


def max_attempts() -> int:
    return _env_int("MM_JOB_MAX_ATTEMPTS", 3, 1)


def oasis_limit() -> int:
    return _env_int("MM_OASIS_MAX_RUNS", 2, 1)


def register_handler(name: str, fn: Callable[[Dict[str, Any]], Any]) -> None:
    HANDLERS[name] = fn


def register_gate(lane: str, fn: Callable[[Dict[str, Dict[str, int]]], bool]) -> None:
    GATES[lane] = fn


def _oasis_active() -> int:
    try:
        from ..services.simulation_runner import SimulationRunner
        return SimulationRunner.active_run_count()
    except Exception:  # noqa: BLE001
        logger.exception("jobs: cannot count running simulations")
        return 0


def oasis_full_now() -> bool:
    """For a queued start about to begin (under the start lock): is the runner full without counting this start?"""
    try:
        in_flight = _STORE.running_in_lane("oasis") - 1
    except Exception:  # noqa: BLE001
        in_flight = 0
    return _oasis_active() + max(0, in_flight) >= oasis_limit()


def _oasis_gate(running: Dict[str, Dict[str, int]]) -> bool:
    # starts in flight count too, so two workers cannot both take the last slot (a run that is already STARTING
    # is counted twice for a moment, which only delays the next start)
    return _oasis_active() + running.get("lane", {}).get("oasis", 0) < oasis_limit()


register_gate("oasis", _oasis_gate)


class SlotTaken(RuntimeError):
    """The OASIS slot a queued start was admitted to was taken by a direct start: back in line, attempt kept."""
    requeue = True


def oasis_should_queue() -> bool:
    """A new OASIS start waits when the runner is full (runs playing rounds plus queued starts being started) or
    earlier starts are still queued (first come, first served). Call it under the start lock."""
    try:
        in_flight = _STORE.running_in_lane("oasis")
    except Exception:  # noqa: BLE001
        in_flight = 0
    if _oasis_active() + in_flight >= oasis_limit():
        return True
    try:
        return any(j["lane"] == "oasis" for j in _STORE.list(status=QUEUED, limit=50))
    except Exception:  # noqa: BLE001
        return False


def _admit(job: Dict[str, Any], running_rows) -> Optional[str]:
    """Spend-cap admission for a job that spends: fail it at once when a cap is reached (it made no call yet), and
    keep it waiting while its estimate does not fit next to the estimates of spending jobs already running."""
    from ..utils import spend_cap
    msg = spend_cap.reached_message()
    if msg:
        return f"fail: {msg} (this job made no model calls)"
    est = float(job.get("estimate_usd") or 0)
    if est > 0:
        st = spend_cap.status()
        if st:
            left = float(st["limit_usd"]) - float(st.get("spent_usd") or 0)
            spending = [r for r in running_rows if r.get("spends")]
            reserved = sum(float(r.get("estimate_usd") or 0) for r in spending)
            if est + reserved > left:
                if spending:
                    return "waiting for spend-cap budget"
                return f"fail: estimated ${est:.2f} is more than the ${left:.2f} left under the spend cap"
    return None


def start_runner(*, role: str = "server", threads: Optional[int] = None, **kw) -> JobRunner:
    """Start this process's runner (once). Server: MM_JOB_WORKERS threads (default 4, at least 1), takes every lane;
    with MM_JOB_EXTERNAL_WORKERS=1 it leaves unbound endpoint jobs to worker processes but keeps the oasis lane."""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is not None:
            return _RUNNER
        n = threads if threads is not None else _env_int("MM_JOB_WORKERS", 4, 1)
        if role == "server" and "accept_unbound" not in kw:
            kw["accept_unbound"] = (lambda lane: lane == "oasis") if external_workers() else (lambda lane: True)
        _RUNNER = JobRunner(_STORE, threads=n, lease_s=lease_s(), limits=limits_from_env(), handlers=HANDLERS,
                            gates=GATES, admit=_admit, max_attempts=max_attempts(), role=role, on_end=_on_end,
                            **kw).start()
        logger.info("jobs: %s runner %s started with %d thread(s)", role, _RUNNER.worker, n)
        return _RUNNER


def runner() -> JobRunner:
    return _RUNNER if _RUNNER is not None else start_runner()


def stop_runner(timeout: float = 5.0) -> None:
    global _RUNNER
    with _RUNNER_LOCK:
        r, _RUNNER = _RUNNER, None
    if r is not None:
        r.stop(timeout)


def init_app(app) -> None:
    """Called early in create_app(): the app replayed jobs run against."""
    from .replay import set_app
    set_app(app)


def start_for_app(app) -> None:
    """Called at the end of create_app(), after every blueprint is registered (a replay claimed at once must find its
    route): settle jobs a dead process left behind and start the server runner."""
    if os.environ.get("MM_JOB_ROLE") == "worker":
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return            # the reloader's watcher process: only the serving child runs jobs (it starts on first use)
    start_runner()


def _on_end(job: Dict[str, Any], outcome: str, error: Optional[str]) -> None:
    """A queued OASIS start that ends without starting (failed, held for approval, cancelled) must not leave
    run-status at "queued" for clients that poll it."""
    if job.get("kind") == "simulation_start" and job.get("subject"):
        from ..services.simulation_runner import SimulationRunner
        SimulationRunner.mark_unqueued(job["subject"], error=None if outcome == CANCELLED else (error or outcome))


def _workspace() -> str:
    try:
        from flask import has_request_context, request
        if has_request_context():
            ws = request.headers.get("X-MM-Workspace") or (request.get_json(silent=True) or {}).get("workspace_id")
            if isinstance(ws, str) and ws.strip():
                return ws.strip()[:64]
    except Exception:  # noqa: BLE001
        pass
    return "local"


def _provider() -> str:
    try:
        from ..config import Config
        return (Config.LLM_PROVIDER or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def submit(task_id: str, fn: Optional[Callable[[], Any]], *, kind: str, subject: str = "", replay: bool = False,
           handler: str = "", payload: Any = None, lane: str = "default", spends: Any = True,
           estimate_usd: Optional[float] = None, workspace: Optional[str] = None, provider: Optional[str] = None,
           max_attempts_: Optional[int] = None, priority: int = 0,
           on_discard: Optional[Callable[[], None]] = None) -> str:
    """Queue `fn` as the job behind task `task_id` and return the id.

    replay=True keeps the current request so any worker can re-run the endpoint (handler "replay"). Inside such a
    re-run this runs `fn` inline instead (errors are handed back to the worker).
    spends="out_of_process": the work pays for model calls this process cannot count (OASIS interviews in the
    simulation subprocess): an interrupted attempt always waits for approval.
    on_discard runs if the closure is dropped without running (cancelled while queued, failed at admission)."""
    ctx = context.current()
    if ctx is not None and ctx.replay and ctx.job_id == task_id:
        if fn is not None:
            try:
                fn()
            except BaseException as e:  # noqa: BLE001 - re-raised by the worker after the request returns
                ctx.replay_error = e
        return task_id
    if replay and not handler:
        from .replay import request_payload
        payload = request_payload()
        handler = "replay" if payload else ""
    run = runner()
    bind = fn is not None and (not handler or not external_workers() or lane == "oasis")
    _STORE.enqueue(task_id, kind, handler=handler, payload=payload, subject=subject or "",
                   workspace=workspace or _workspace(), provider=provider if provider is not None else _provider(),
                   lane=lane, priority=priority, max_attempts=max_attempts_ or max_attempts(), spends=spends,
                   estimate_usd=estimate_usd, owner=run.worker if bind else None, bound=bind)
    if bind:
        run.bind(task_id, fn, on_discard=on_discard)
    else:
        from ..models.task import TaskManager
        TaskManager().release(task_id)       # whichever process runs it owns its task row from then on
        run.wake()
    return task_id


def get(job_id: str) -> Optional[Dict[str, Any]]:
    return _STORE.get(job_id) if job_id else None


def summary(job_id: str) -> Optional[Dict[str, Any]]:
    """The queue view of a task (added to task status replies)."""
    try:
        job = _STORE.get(job_id) if job_id else None
    except Exception:  # noqa: BLE001
        return None
    if not job:
        return None
    return {"status": job["status"], "lane": job["lane"], "workspace": job["workspace"], "provider": job["provider"],
            "attempts": job["attempts"], "max_attempts": job["max_attempts"], "model_calls": job["model_calls"],
            "queue_position": _STORE.position(job_id), "queue_wait_s": job["queue_wait_s"],
            "cancel_requested": job["cancel_requested"], "message": job["message"],
            "needs_approval": job["status"] == NEEDS_APPROVAL}


def cancel(job_id: str) -> Optional[Dict[str, Any]]:
    job = _STORE.cancel(job_id)
    if job is None:
        return None
    r = _RUNNER
    if r is not None and job["status"] == RUNNING:
        ctx = context.active().get(job_id)
        if ctx is not None:
            ctx.cancel.set()
    if job["status"] == CANCELLED:
        if r is not None:
            r.unbind(job_id)
        from ..models.task import TaskManager, TaskStatus
        TaskManager().mirror(job_id, status=TaskStatus.FAILED, message="cancelled", error="cancelled")
        if job["kind"] == "simulation_start" and job.get("subject"):
            _unqueue_simulation(job["subject"])
    return job


def _unqueue_simulation(simulation_id: str) -> None:
    try:
        from ..services.simulation_runner import SimulationRunner
        SimulationRunner.mark_unqueued(simulation_id)
    except Exception:  # noqa: BLE001
        logger.exception("jobs: cannot reset queued simulation %s", simulation_id)


def approve(job_id: str) -> Optional[Dict[str, Any]]:
    """Queue one more attempt. The task is reset to pending *before* the job becomes claimable, so a worker that
    takes the retry at once can never be overwritten by a late reset; a refused approval puts the task back."""
    from ..models.task import TaskManager, TaskStatus
    tm = TaskManager()
    before = tm.get_task(job_id)
    previous = (before.status, before.message, before.error) if before is not None else None
    tm.mirror(job_id, status=TaskStatus.PENDING, message="queued (retry approved)", error="")
    try:
        job = _STORE.approve(job_id)
    except Exception:
        if previous:
            tm.mirror(job_id, status=previous[0], message=previous[1], error=previous[2] or "")
        raise
    if job is None:
        if previous:
            tm.mirror(job_id, status=previous[0], message=previous[1], error=previous[2] or "")
        return None
    runner().wake()
    return job

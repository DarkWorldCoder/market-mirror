"""Worker threads that claim jobs from the store and run them.

One `JobRunner` per process. It runs `threads` jobs at a time, renews their leases, passes cancellations on to the
running work, writes model-call counts, and sweeps jobs left behind by dead workers. The server process starts one
(MM_JOB_WORKERS threads, default 4); `python -m app.jobs.worker` starts one in a separate process.

Retry policy (no silent re-spend):
* an attempt that raised a retryable error (connection, timeout, 5xx/429 from a provider) and made **no** model call
  goes back to the queue with backoff while attempts are left (MM_JOB_MAX_ATTEMPTS, default 3);
* an attempt that made model calls is never retried on its own: the job goes to `needs_approval`
  (POST /api/jobs/<id>/retry {"approve_spend": true} queues one more attempt);
* other errors fail the job.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Any, Callable, Dict, Optional, Set

from . import context as jctx
from .limits import Limits, from_env
from .store import CANCELLED, FAILED, NEEDS_APPROVAL, QUEUED, SUCCEEDED, JobStore, new_worker_token

logger = logging.getLogger("mirofish.jobs")

RETRYABLE_NAMES = {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
                   "ServiceUnavailableError", "OverloadedError", "ConnectError", "ReadTimeout", "ConnectTimeout"}


def retryable(exc: BaseException) -> bool:
    if getattr(exc, "no_retry", False):
        return False
    if getattr(exc, "retryable", False):
        return True
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    return any(cls.__name__ in RETRYABLE_NAMES for cls in type(exc).__mro__)


class ReplayRejected(RuntimeError):
    """The re-run endpoint refused the request (validation, missing simulation...)."""
    no_retry = True


class JobRunner:
    def __init__(self, store: JobStore, *, threads: int = 4, worker: Optional[str] = None,
                 accept_unbound: Callable[[str], bool] = lambda lane: True,
                 lanes: Optional[Set[str]] = None, exclude_lanes: Optional[Set[str]] = None,
                 lease_s: float = 60.0, poll_s: float = 1.0, limits: Optional[Limits] = None,
                 handlers: Optional[Dict[str, Callable[[Dict[str, Any]], Any]]] = None,
                 gates: Optional[Dict[str, Callable[[Dict[str, Dict[str, int]]], bool]]] = None,
                 admit: Optional[Callable] = None, max_attempts: int = 3, role: str = "server",
                 on_end: Optional[Callable[[Dict[str, Any], str, Optional[str]], None]] = None):
        self.store = store
        self.threads = max(1, int(threads))
        self.worker = worker or new_worker_token()
        self.accept_unbound = accept_unbound
        self.lanes, self.exclude_lanes = lanes, exclude_lanes or set()
        self.lease_s, self.poll_s = float(lease_s), float(poll_s)
        self.limits = limits or from_env()
        self.handlers = handlers if handlers is not None else {}
        self.gates = gates if gates is not None else {}
        self.admit = admit
        self.max_attempts = max_attempts
        self.role = role
        self.on_end = on_end
        self._bound: Dict[str, Callable[[], Any]] = {}
        self._running: Dict[str, jctx.JobContext] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: list = []
        self._last_sweep = 0.0
        self.completed = 0

    # ------------------------------------------------------------- control

    def bind(self, job_id: str, fn: Callable[[], Any]) -> None:
        with self._lock:
            self._bound[job_id] = fn
        self._wake.set()

    def unbind(self, job_id: str) -> None:
        with self._lock:
            self._bound.pop(job_id, None)

    def wake(self) -> None:
        self._wake.set()

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._running

    def start(self) -> "JobRunner":
        jctx.install(on_first_call=lambda jid: self.store.note_first_call(jid, self.worker))
        self.store.register_worker(self.worker, {"role": self.role, "threads": self.threads,
                                                 "lanes": sorted(self.lanes) if self.lanes else "all",
                                                 "exclude_lanes": sorted(self.exclude_lanes)})
        self.sweep(force=True)
        for i in range(self.threads):
            t = threading.Thread(target=self._loop, name=f"mm-job-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        m = threading.Thread(target=self._maintain, name="mm-job-lease", daemon=True)
        m.start()
        self._threads.append(m)
        return self

    def stop(self, timeout: float = 5.0) -> None:
        """Stop claiming and wait up to `timeout` for running jobs. Jobs still running afterwards are not cancelled:
        once this process is gone the sweep of a live process requeues them (no model call yet) or holds them for
        approval."""
        self._stop.set()
        self._wake.set()
        deadline = time.monotonic() + timeout
        for t in self._threads:
            t.join(max(0.0, deadline - time.monotonic()))
        try:
            self.store.unregister_worker(self.worker)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------- loops

    def _lane_ok(self, lane: str) -> bool:
        if lane in self.exclude_lanes:
            return False
        return self.lanes is None or lane in self.lanes

    def _claim(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            bound = set(self._bound) - set(self._running)
        failed: list = []
        job = self.store.claim(self.worker, limits=self.limits, bound_ids=bound,
                               accept_unbound=self.accept_unbound, handlers=set(self.handlers) | {"replay"},
                               lanes=self._lane_ok, gates=self.gates, admit=self.admit, lease_s=self.lease_s,
                               failed_out=failed, exclude_lanes=self.exclude_lanes)
        for f in failed:                     # failed at admission (spend cap): settle the task and the closure
            from ..models.task import TaskManager, TaskStatus
            self.unbind(f["job_id"])
            TaskManager().mirror(f["job_id"], status=TaskStatus.FAILED, message="failed before it started",
                                 error=f["error"])
            self._ended(f, FAILED, f["error"])
        return job

    def _ended(self, job: Dict[str, Any], outcome: str, error: Optional[str]) -> None:
        if self.on_end is None:
            return
        try:
            self.on_end(job, outcome, error)
        except Exception:  # noqa: BLE001
            logger.exception("jobs: end hook failed for %s", job.get("job_id"))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._claim()
            except Exception:  # noqa: BLE001 - a busy or broken database must not kill the worker thread
                logger.exception("jobs: claim failed")
                job = None
            if job is None:
                self._wake.wait(self.poll_s)
                self._wake.clear()
                continue
            self._execute(job)

    def _maintain(self) -> None:
        every = max(0.2, self.lease_s / 3)
        while not self._stop.wait(every):
            try:
                with self._lock:
                    running = dict(self._running)
                cancelled = self.store.renew(self.worker, running.keys(), self.lease_s)   # cancelled or lease lost
                for jid in cancelled:
                    ctx = running.get(jid)
                    if ctx is not None:
                        ctx.cancel.set()
                for jid, ctx in running.items():
                    with ctx.lock:
                        calls, usd = ctx.calls, ctx.spent_usd
                    if calls:
                        self.store.flush_usage(jid, self.worker, calls, 0.0)
                self.sweep()
            except Exception:  # noqa: BLE001
                logger.exception("jobs: lease renewal failed")

    def sweep(self, force: bool = False) -> list:
        """Settle jobs of dead workers (at most every lease period unless forced)."""
        now = time.monotonic()
        if not force and now - self._last_sweep < self.lease_s:
            return []
        self._last_sweep = now
        alive_fn = self.store.worker_alive_fn(stale_after_s=self.lease_s * 2)
        me = self.worker
        changed = self.store.recover(lambda token: token == me or alive_fn(token))
        for c in changed:
            _mirror_recovery(c)
            if c["action"] in (FAILED, NEEDS_APPROVAL, CANCELLED):
                self._ended(c, c["action"], c.get("message"))
            logger.warning("jobs: %s -> %s %s", c["job_id"], c["action"], c.get("message", ""))
        self.store.prune_workers(self.lease_s * 2)
        if changed:
            self._wake.set()
        return changed

    # ------------------------------------------------------------- one job

    def _execute(self, job: Dict[str, Any]) -> None:
        from ..models.task import TaskManager, TaskStatus
        jid = job["job_id"]
        ctx = jctx.JobContext(job_id=jid)
        with self._lock:
            self._running[jid] = ctx
            fn = self._bound.get(jid)
        tm = TaskManager()
        adopted = tm.adopt(jid)
        token = jctx.activate(ctx)
        outcome, error, result, retry_in, message, refund = SUCCEEDED, None, None, None, "", False
        try:
            tm.update_task(jid, status=TaskStatus.PROCESSING,
                           message=f"started (attempt {job['attempts']})" if job["attempts"] > 1 else None)
            if fn is not None:
                out = fn()
            elif job["handler"] == "replay":
                from .replay import run_replay
                out = run_replay(job, ctx)
            elif job["handler"] in self.handlers:
                out = self.handlers[job["handler"]](job.get("payload") or {})
            else:
                raise ReplayRejected(f"no handler {job['handler']!r} in this worker")
            jctx.checkpoint()
            result = out if isinstance(out, (dict, list, str, int, float)) or out is None else str(out)
            task = tm.get_task(jid)
            if task is not None and task.status == TaskStatus.FAILED:
                outcome, error = FAILED, task.error or "failed"
        except jctx.JobCancelled:
            outcome, error = CANCELLED, "cancelled"
        except Exception as e:  # noqa: BLE001 - the job's outcome
            if getattr(e, "requeue", False):
                # not this job's fault (e.g. the OASIS slot it was admitted to was taken): back in line, attempt kept
                outcome, retry_in, refund, message = QUEUED, 1.0, True, f"waiting: {e}"
            elif ctx.cancel.is_set():
                outcome, error = CANCELLED, "cancelled"
            else:
                error = f"{type(e).__name__}: {e}"
                logger.error("job %s (%s) failed: %s\n%s", jid, job["kind"], error, traceback.format_exc())
                with ctx.lock:
                    calls = ctx.calls
                if retryable(e) and job["attempts"] < job["max_attempts"]:
                    if calls == 0 and not job.get("spends_out_of_process"):
                        outcome, retry_in = QUEUED, min(60.0, 2.0 ** job["attempts"])
                        message = f"retrying in {retry_in:.0f}s after: {error}"
                    else:
                        outcome = NEEDS_APPROVAL
                        message = (f"failed after {calls} model call(s); approve a retry to run it again "
                                   "(it will spend again)")
                else:
                    outcome = FAILED
        finally:
            jctx.deactivate(ctx, token)
            with ctx.lock:
                calls, usd = ctx.calls, ctx.spent_usd
            try:
                if calls or usd:
                    self.store.flush_usage(jid, self.worker, calls, usd)
            except Exception:  # noqa: BLE001
                logger.exception("jobs: cannot write usage for %s", jid)
        if ctx.cancel.is_set() and outcome == SUCCEEDED:
            outcome, error = CANCELLED, "cancelled"
        if outcome in (SUCCEEDED, FAILED, CANCELLED, NEEDS_APPROVAL):
            with self._lock:
                self._bound.pop(jid, None)
        try:
            ok = self.store.finish(jid, self.worker, outcome, error=error, result=result if outcome == SUCCEEDED else None,
                                   message=message or outcome, retry_in=retry_in, refund_attempt=refund)
        except Exception:  # noqa: BLE001
            logger.exception("jobs: cannot finish %s", jid)
            ok = False
        if ok:
            _mirror_outcome(tm, jid, outcome, error, result, message)
            if outcome in (FAILED, NEEDS_APPROVAL, CANCELLED):
                self._ended(job, outcome, error)
        else:
            # another process recovered this job while we looked dead: its record wins, ours is dropped
            logger.warning("jobs: lease on %s was lost; its outcome %s is not recorded", jid, outcome)
        if adopted:
            tm.release(jid)
        with self._lock:
            self._running.pop(jid, None)
        self.completed += 1
        self._wake.set()


def _mirror_outcome(tm, jid: str, outcome: str, error: Optional[str], result: Any, message: str) -> None:
    """Keep the TaskManager row (what /market-task/status and friends read) in step with the job."""
    from ..models.task import TaskStatus
    task = tm.get_task(jid)
    if task is None:
        return
    try:
        if outcome == SUCCEEDED:
            if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                tm.complete_task(jid, result if isinstance(result, dict) else {"result": result})
        elif outcome == QUEUED:
            tm.update_task(jid, status=TaskStatus.PENDING, message=message)
        elif outcome == CANCELLED:
            tm.update_task(jid, status=TaskStatus.FAILED, message="cancelled", error="cancelled")
        elif outcome == NEEDS_APPROVAL:
            tm.update_task(jid, status=TaskStatus.FAILED, message=message, error=f"needs approval: {error}")
        elif task.status != TaskStatus.FAILED:
            tm.fail_task(jid, error or "failed")
    except Exception:  # noqa: BLE001
        logger.exception("jobs: cannot mirror %s into its task", jid)


def _mirror_recovery(change: Dict[str, Any]) -> None:
    from ..models.task import TaskManager, TaskStatus
    status = {QUEUED: TaskStatus.PENDING, FAILED: TaskStatus.FAILED, NEEDS_APPROVAL: TaskStatus.FAILED}.get(change["action"])
    if status is None:
        return
    msg = change.get("message", "")
    TaskManager().mirror(change["job_id"], status=status, message=msg,
                         error=None if status == TaskStatus.PENDING else f"server restarted: {msg}")

"""Which job is running on this thread, and the hooks that tie model calls to it.

* `current()` is the job a thread is working for (a contextvar). Thread pools started inside a job inherit it:
  `install()` makes `ThreadPoolExecutor.submit` copy the caller's context while a job is active, so the per-person
  workers of a feed test count against (and can be cancelled through) their job.
* `spend_cap.check()` runs before every model call. The check hook counts the call against the current job (the
  first call of an attempt is written to the database at once, so a crash right after it can never look like a
  job that spent nothing; when that write fails the call is refused) and raises `JobCancelled` when the job was
  cancelled.
* A model call made on a thread that carries no job (a raw `threading.Thread`) is counted against every job running
  in this process. That over-counts on purpose: the only effect of an extra count is that an interrupted job asks
  for approval before it runs again instead of retrying on its own.
"""

from __future__ import annotations

import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


class JobCancelled(RuntimeError):
    """The job was cancelled; raised at the next model call or progress update."""
    no_retry = True


@dataclass
class JobContext:
    job_id: str
    replay: bool = False                  # the endpoint is being re-run by a worker: run the work inline
    cancel: threading.Event = field(default_factory=threading.Event)
    calls: int = 0                        # model calls started in this attempt
    spent_usd: float = 0.0
    first_call_flushed: bool = False
    task_claimed: bool = False            # replay: the endpoint's create_task() already returned this job's id
    replay_error: Optional[BaseException] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_CURRENT: contextvars.ContextVar[Optional[JobContext]] = contextvars.ContextVar("mm_job", default=None)
_ACTIVE: Dict[str, JobContext] = {}       # jobs running in this process
_ACTIVE_LOCK = threading.Lock()
_ON_FIRST_CALL: Optional[Callable[[str], None]] = None
_INSTALLED = False


def current() -> Optional[JobContext]:
    return _CURRENT.get()


def replaying() -> bool:
    ctx = _CURRENT.get()
    return bool(ctx and ctx.replay)


def activate(ctx: JobContext) -> contextvars.Token:
    with _ACTIVE_LOCK:
        _ACTIVE[ctx.job_id] = ctx
    return _CURRENT.set(ctx)


def deactivate(ctx: JobContext, token: contextvars.Token) -> None:
    _CURRENT.reset(token)
    with _ACTIVE_LOCK:
        _ACTIVE.pop(ctx.job_id, None)


def active() -> Dict[str, JobContext]:
    with _ACTIVE_LOCK:
        return dict(_ACTIVE)


def checkpoint() -> None:
    """Raise JobCancelled when the current job was cancelled (no-op outside a job)."""
    ctx = _CURRENT.get()
    if ctx is not None and ctx.cancel.is_set():
        raise JobCancelled("cancelled")


def _targets() -> list:
    ctx = _CURRENT.get()
    if ctx is not None:
        return [ctx]
    with _ACTIVE_LOCK:
        return list(_ACTIVE.values())


def _on_check() -> None:
    checkpoint()
    for ctx in _targets():
        with ctx.lock:
            first = not ctx.first_call_flushed
        if first and _ON_FIRST_CALL is not None:
            try:
                _ON_FIRST_CALL(ctx.job_id)
            except Exception as e:  # noqa: BLE001
                # an unrecorded spend could be retried after a crash without approval: refuse the job's call instead
                # (a call on a thread with no job is only counted conservatively and goes ahead)
                if _CURRENT.get() is ctx:
                    raise RuntimeError(f"cannot record the first model call of job {ctx.job_id}: {e}") from e
                continue
        with ctx.lock:
            ctx.first_call_flushed = True
            ctx.calls += 1


def _on_charge(usd: float) -> None:
    for ctx in _targets():
        with ctx.lock:
            ctx.spent_usd += float(usd or 0)


_orig_submit = ThreadPoolExecutor.submit


def _submit(self, fn, /, *args, **kwargs):
    if _CURRENT.get() is not None:
        return _orig_submit(self, contextvars.copy_context().run, fn, *args, **kwargs)
    return _orig_submit(self, fn, *args, **kwargs)


def install(on_first_call: Optional[Callable[[str], None]] = None) -> None:
    """Hook spend_cap and thread pools once per process."""
    global _INSTALLED, _ON_FIRST_CALL
    if on_first_call is not None:
        _ON_FIRST_CALL = on_first_call
    if _INSTALLED:
        return
    from ..utils import spend_cap
    spend_cap.add_hook("check", _on_check)
    spend_cap.add_hook("charge", _on_charge)
    ThreadPoolExecutor.submit = _submit
    _INSTALLED = True

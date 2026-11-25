"""The durable job table (SQLite, WAL) shared by every process that points at the same file.

A claim is one `BEGIN IMMEDIATE` transaction: read the queued jobs and the running counts, pick the first job every
limit allows, flip it to `running` with a lease. SQLite serialises those transactions across processes, so two
workers never take the same job. A worker renews its leases while it runs; a lease that runs out (the worker died)
is picked up by the recovery sweep of any live process.

Status flow:

    queued -> running -> succeeded | failed | cancelled
                      -> queued            (retry: no model call made in that attempt, attempts left)
                      -> needs_approval    (interrupted or failed after model calls: never retried on its own)
    needs_approval -> queued (approve) | cancelled
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Set

from .limits import Limits

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED, NEEDS_APPROVAL = (
    "queued", "running", "succeeded", "failed", "cancelled", "needs_approval")
ACTIVE = (QUEUED, RUNNING, NEEDS_APPROVAL)
TERMINAL = (SUCCEEDED, FAILED, CANCELLED)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    handler TEXT NOT NULL DEFAULT '',
    payload_json TEXT,
    subject TEXT DEFAULT '',
    workspace TEXT NOT NULL DEFAULT 'local',
    provider TEXT NOT NULL DEFAULT '',
    lane TEXT NOT NULL DEFAULT 'default',
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    spends INTEGER NOT NULL DEFAULT 1,
    model_calls INTEGER NOT NULL DEFAULT 0,
    attempt_calls INTEGER NOT NULL DEFAULT 0,
    spent_usd REAL NOT NULL DEFAULT 0,
    estimate_usd REAL,
    spend_approved INTEGER NOT NULL DEFAULT 0,
    owner TEXT,
    bound INTEGER NOT NULL DEFAULT 0,
    worker TEXT,
    lease_until REAL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    run_after REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    first_started_at REAL,
    started_at REAL,
    finished_at REAL,
    queue_wait_s REAL,
    message TEXT DEFAULT '',
    error TEXT,
    result_json TEXT,
    history_json TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status, lane, priority, created_at);
CREATE INDEX IF NOT EXISTS jobs_subject_idx ON jobs (kind, subject);
CREATE TABLE IF NOT EXISTS job_workers (
    worker TEXT PRIMARY KEY,
    host TEXT,
    pid INTEGER,
    started_at REAL,
    heartbeat_at REAL,
    info_json TEXT
);
"""

_JSON_COLS = ("payload_json", "result_json", "history_json")


def default_path() -> str:
    custom = os.environ.get("MM_JOB_DB_PATH") or os.environ.get("MM_TASK_DB_PATH")
    if custom:
        path = os.path.abspath(custom)
    else:
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../uploads/tasks.sqlite"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def new_worker_token() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError, ValueError, TypeError):
        return True


class JobStore:
    def __init__(self, path: Optional[str] = None):
        self._fixed_path = path
        self._ready: Set[str] = set()

    @property
    def path(self) -> str:
        return self._fixed_path or default_path()

    @contextmanager
    def _db(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        path = self.path
        conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            if path not in self._ready:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                self._ready.add(path)
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    # ---------------------------------------------------------------- rows

    @staticmethod
    def _row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        d = dict(row)
        for col in _JSON_COLS:
            raw = d.pop(col, None)
            d[col[:-5]] = json.loads(raw) if raw else None
        d["spends_out_of_process"] = int(d["spends"] or 0) == 2
        d["bound"], d["spends"] = bool(d["bound"]), bool(d["spends"])
        d["cancel_requested"], d["spend_approved"] = bool(d["cancel_requested"]), bool(d["spend_approved"])
        return d

    @staticmethod
    def _history(conn: sqlite3.Connection, job_id: str, entry: Dict[str, Any]) -> str:
        raw = conn.execute("SELECT history_json FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        hist = json.loads(raw[0]) if raw and raw[0] else []
        hist.append({"at": round(time.time(), 3), **entry})
        return json.dumps(hist[-50:], ensure_ascii=False, default=str)

    # ---------------------------------------------------------------- writes

    def enqueue(self, job_id: str, kind: str, *, handler: str = "", payload: Any = None, subject: str = "",
                workspace: str = "local", provider: str = "", lane: str = "default", priority: int = 0,
                max_attempts: int = 3, spends: Any = True, estimate_usd: Optional[float] = None,
                owner: Optional[str] = None, bound: bool = False, message: str = "queued") -> Dict[str, Any]:
        now = time.time()
        with self._db(immediate=True) as conn:
            conn.execute(
                "INSERT INTO jobs (job_id, kind, handler, payload_json, subject, workspace, provider, lane, priority, "
                "status, max_attempts, spends, estimate_usd, owner, bound, created_at, updated_at, message, history_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, kind, handler or "", json.dumps(payload, ensure_ascii=False, default=str) if payload is not None else None,
                 subject or "", workspace or "local", (provider or "").lower(), lane or "default", int(priority),
                 QUEUED, max(1, int(max_attempts)), 2 if spends == "out_of_process" else int(bool(spends)), estimate_usd,
                 owner, int(bool(bound)),
                 now, now, message, json.dumps([{"at": round(now, 3), "event": "queued"}])))
        return self.get(job_id)

    def claim(self, worker: str, *, limits: Limits, bound_ids: Iterable[str] = (), accept_unbound: Any = True,
              handlers: Optional[Set[str]] = None, lanes: Any = None,
              gates: Optional[Dict[str, Callable[[Dict[str, Dict[str, int]]], bool]]] = None,
              admit: Optional[Callable[[Dict[str, Any], List[Dict[str, Any]]], Optional[str]]] = None,
              lease_s: float = 60.0, failed_out: Optional[List[Dict[str, Any]]] = None,
              exclude_lanes: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
        """Take the first queued job this worker can run and every limit allows, or None.

        bound_ids: jobs whose closure lives in this process. accept_unbound (bool or lane -> bool): also take jobs
        any process can run (a handler name in `handlers`). admit(job, running) may return "fail: ..." to fail the job at once or any
        other string to leave it waiting; jobs failed that way are appended to `failed_out` so the caller can settle
        their tasks after this transaction."""
        bound_ids = set(bound_ids)
        with self._db(immediate=True) as conn:
            now = time.time()                          # after the write lock: never older than a row it reads
            mine = sorted(bound_ids)
            excl = sorted(set(exclude_lanes))
            sql = ("SELECT * FROM jobs WHERE status = ? AND run_after <= ? AND cancel_requested = 0 "
                   f"AND (bound = 0 OR job_id IN ({','.join('?' * len(mine)) or 'NULL'})) "
                   + (f"AND lane NOT IN ({','.join('?' * len(excl))}) " if excl else "")
                   + "ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?")

            def pages():
                # page through every queued candidate in priority order, so blocked jobs never hide an eligible one
                offset = 0
                while True:
                    page = conn.execute(sql, (QUEUED, now, *mine, *excl, 500, offset)).fetchall()
                    yield from page
                    if len(page) < 500:
                        return
                    offset += 500
            running_rows = [dict(r) for r in conn.execute(
                "SELECT job_id, provider, workspace, lane, spends, estimate_usd, attempt_calls FROM jobs "
                "WHERE status = ?", (RUNNING,))]   # a dead worker's jobs count until the sweep settles them
            running: Dict[str, Dict[str, int]] = {"provider": {}, "workspace": {}, "lane": {}}
            for r in running_rows:
                for k in ("provider", "workspace", "lane"):
                    running[k][r[k]] = running[k].get(r[k], 0) + 1
            for row in pages():
                job = dict(row)
                if lanes is not None and not (lanes(job["lane"]) if callable(lanes) else job["lane"] in lanes):
                    continue
                is_mine = job["job_id"] in bound_ids
                if job["bound"] and not is_mine:
                    continue                                   # its closure lives in another (live) process
                unbound_ok = accept_unbound(job["lane"]) if callable(accept_unbound) else bool(accept_unbound)
                if not is_mine and not (unbound_ok and job["handler"] and (handlers is None or job["handler"] in handlers)):
                    continue
                if job["cancel_requested"]:
                    continue
                if limits.allows(job, running):
                    continue
                gate = (gates or {}).get(job["lane"])
                if gate is not None and not gate(running):
                    continue
                if admit is not None and job["spends"]:
                    verdict = admit(job, running_rows)
                    if verdict and verdict.startswith("fail:"):
                        hist = self._history(conn, job["job_id"], {"event": "failed", "error": verdict[5:].strip()})
                        conn.execute("UPDATE jobs SET status = ?, error = ?, message = ?, finished_at = ?, updated_at = ?, "
                                     "history_json = ?, bound = 0 WHERE job_id = ?",   # its closure is discarded
                                     (FAILED, verdict[5:].strip(), "failed before it started", now, now, hist, job["job_id"]))
                        if failed_out is not None:
                            failed_out.append({"job_id": job["job_id"], "kind": job["kind"], "subject": job["subject"],
                                               "error": verdict[5:].strip()})
                        continue
                    if verdict:
                        continue
                hist = self._history(conn, job["job_id"], {"event": "started", "worker": worker,
                                                            "attempt": job["attempts"] + 1})
                conn.execute(
                    "UPDATE jobs SET status = ?, worker = ?, lease_until = ?, attempts = attempts + 1, attempt_calls = 0, "
                    "started_at = ?, first_started_at = COALESCE(first_started_at, ?), "
                    "queue_wait_s = COALESCE(queue_wait_s, ? - created_at), message = ?, updated_at = ?, history_json = ? "
                    "WHERE job_id = ? AND status = ?",
                    (RUNNING, worker, now + lease_s, now, now, now, "running", now, hist, job["job_id"], QUEUED))
                return self._row(conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job["job_id"],)).fetchone())
        return None

    def note_first_call(self, job_id: str, worker: str) -> bool:
        """Written at once on the first model call of an attempt: from here on a retry needs approval. False when
        this attempt no longer owns the job (recovered by another process): the call must not be made."""
        with self._db(immediate=True) as conn:
            cur = conn.execute("UPDATE jobs SET attempt_calls = MAX(attempt_calls, 1), "
                         "model_calls = model_calls + (CASE WHEN attempt_calls = 0 THEN 1 ELSE 0 END), "
                         "updated_at = ? WHERE job_id = ? AND worker = ? AND status = ?",
                         (time.time(), job_id, worker, RUNNING))
            return (cur.rowcount or 0) > 0

    def flush_usage(self, job_id: str, worker: str, calls: int, usd: float) -> None:
        """Bring the attempt's counts up to `calls` (model_calls grows by the difference)."""
        with self._db(immediate=True) as conn:
            row = conn.execute("SELECT attempt_calls FROM jobs WHERE job_id = ? AND worker = ?", (job_id, worker)).fetchone()
            if not row:
                return
            delta = max(0, int(calls) - int(row[0] or 0))
            conn.execute("UPDATE jobs SET attempt_calls = attempt_calls + ?, model_calls = model_calls + ?, "
                         "spent_usd = spent_usd + ?, updated_at = ? WHERE job_id = ? AND worker = ?",
                         (delta, delta, max(0.0, float(usd)), time.time(), job_id, worker))

    def progress(self, job_id: str, message: str) -> None:
        with self._db(immediate=True) as conn:
            conn.execute("UPDATE jobs SET message = ?, updated_at = ? WHERE job_id = ?",
                         (str(message or "")[:500], time.time(), job_id))

    def renew(self, worker: str, job_ids: Iterable[str], lease_s: float) -> Set[str]:
        """Extend this worker's leases; returns the ids that must stop: cancellation requested, or the lease was
        lost (another process recovered the job after this one looked dead)."""
        ids = list(job_ids)
        now = time.time()
        cancelled: Set[str] = set()
        with self._db(immediate=True) as conn:
            conn.execute("INSERT INTO job_workers (worker, host, pid, started_at, heartbeat_at, info_json) "
                         "VALUES (?, ?, ?, ?, ?, '{}') ON CONFLICT(worker) DO UPDATE SET heartbeat_at = excluded.heartbeat_at",
                         (worker, socket.gethostname(), os.getpid(), now, now))
            for jid in ids:
                conn.execute("UPDATE jobs SET lease_until = ? WHERE job_id = ? AND worker = ? AND status = ?",
                             (now + lease_s, jid, worker, RUNNING))
                row = conn.execute("SELECT cancel_requested, worker, status FROM jobs WHERE job_id = ?", (jid,)).fetchone()
                if not row or row[0] or row[1] != worker or row[2] != RUNNING:
                    cancelled.add(jid)
        return cancelled

    def register_worker(self, worker: str, info: Dict[str, Any]) -> None:
        now = time.time()
        with self._db(immediate=True) as conn:
            conn.execute("INSERT OR REPLACE INTO job_workers (worker, host, pid, started_at, heartbeat_at, info_json) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (worker, socket.gethostname(), os.getpid(), now, now, json.dumps(info, default=str)))

    def unregister_worker(self, worker: str) -> None:
        with self._db(immediate=True) as conn:
            conn.execute("DELETE FROM job_workers WHERE worker = ?", (worker,))

    def finish(self, job_id: str, worker: str, status: str, *, error: Optional[str] = None, result: Any = None,
               message: str = "", retry_in: Optional[float] = None, refund_attempt: bool = False) -> Any:
        """End this worker's attempt. status QUEUED = retry after `retry_in` seconds. Returns the status committed (a
        cancellation recorded meanwhile turns a retry or an approval hold into "cancelled"), or False when the
        attempt no longer owns the job."""
        now = time.time()
        with self._db(immediate=True) as conn:
            row = conn.execute("SELECT worker, status, cancel_requested FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row or row["worker"] != worker or row["status"] != RUNNING:
                return False
            if row["cancel_requested"] and status in (QUEUED, NEEDS_APPROVAL):
                status, error, message, retry_in = CANCELLED, "cancelled", "cancelled", None
            hist = self._history(conn, job_id, {"event": status, **({"error": error} if error else {})})
            if status == QUEUED:
                conn.execute("UPDATE jobs SET status = ?, worker = NULL, lease_until = NULL, run_after = ?, error = ?, "
                             "message = ?, updated_at = ?, history_json = ?, spend_approved = 0, "
                             "attempts = attempts - ? WHERE job_id = ?",
                             (QUEUED, now + float(retry_in or 0), error, message or "queued for retry", now, hist,
                              1 if refund_attempt else 0, job_id))
            else:
                conn.execute("UPDATE jobs SET status = ?, worker = NULL, lease_until = NULL, error = ?, result_json = ?, "
                             "message = ?, finished_at = ?, updated_at = ?, history_json = ?, bound = 0, "
                             "spend_approved = 0 WHERE job_id = ?",
                             (status, error, json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                              message or status, now if status in TERMINAL else None, now, hist, job_id))
        return status

    def cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self._db(immediate=True) as conn:
            row = conn.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            if row[0] in (QUEUED, NEEDS_APPROVAL):
                hist = self._history(conn, job_id, {"event": "cancelled"})
                conn.execute("UPDATE jobs SET status = ?, cancel_requested = 1, message = ?, finished_at = ?, "
                             "updated_at = ?, bound = 0, history_json = ? WHERE job_id = ?",
                             (CANCELLED, "cancelled before it ran", now, now, hist, job_id))
            elif row[0] == RUNNING:
                conn.execute("UPDATE jobs SET cancel_requested = 1, message = ?, updated_at = ? WHERE job_id = ?",
                             ("cancelling", now, job_id))
        return self.get(job_id)

    def approve(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Approve one more attempt that may spend again (needs_approval or failed -> queued)."""
        now = time.time()
        with self._db(immediate=True) as conn:
            row = conn.execute("SELECT status, attempts, max_attempts, handler, bound FROM jobs WHERE job_id = ?",
                               (job_id,)).fetchone()
            if not row or row["status"] not in (NEEDS_APPROVAL, FAILED):
                return None
            if not row["handler"] and not row["bound"]:
                raise ValueError("this job cannot be re-run from the queue (its work lived in a process that stopped); "
                                 "start the step again")
            hist = self._history(conn, job_id, {"event": "retry approved"})
            conn.execute("UPDATE jobs SET status = ?, spend_approved = 1, cancel_requested = 0, "
                         "max_attempts = MAX(max_attempts, attempts + 1), run_after = 0, error = NULL, finished_at = NULL, "
                         "message = ?, updated_at = ?, history_json = ? WHERE job_id = ?",
                         (QUEUED, "queued (retry approved)", now, hist, job_id))
        return self.get(job_id)

    def recover(self, alive_worker: Optional[Callable[[str], bool]] = None, *, stale_after_s: float = 120.0,
                also_alive: Iterable[str] = ()) -> List[Dict[str, Any]]:
        """Settle jobs whose worker is gone. Returns [{job_id, action, ...}] for each job it changed.

        * running, worker dead (pid gone on this host, or no heartbeat for a while elsewhere): back to queued when the attempt made no model call, attempts are
          left and some process can run it (a handler, or the bound closure's owner is alive); needs_approval when it
          made model calls; failed otherwise.
        * queued and bound to a dead owner: unbound (any worker may run it through its handler) or failed when it has
          no handler (its closure died with the process; nothing was spent).

        Without `alive_worker`, liveness is read from the heartbeat table inside this same transaction, so a worker
        that registers and claims in between is never mistaken for a dead one.
        """
        now = time.time()
        changed: List[Dict[str, Any]] = []
        with self._db(immediate=True) as conn:
            if alive_worker is None:
                keep = set(also_alive)
                beats_alive = self.worker_alive_fn(stale_after_s, conn)
                alive_worker = lambda token: token in keep or beats_alive(token)  # noqa: E731
            for row in conn.execute("SELECT * FROM jobs WHERE status = ?", (RUNNING,)).fetchall():
                job = dict(row)
                if alive_worker(job["worker"] or ""):
                    continue      # a live worker (its pid runs on this host, or a fresh heartbeat elsewhere) keeps it
                runnable = bool(job["handler"])
                if job["cancel_requested"]:
                    status, msg = CANCELLED, "cancelled (its worker stopped)"
                elif job["attempt_calls"] > 0 or int(job["spends"] or 0) == 2:
                    status, msg = NEEDS_APPROVAL, ("interrupted after model calls (or work that spends outside this "
                                                   "process); approve a retry to run it again (it will spend again)")
                elif runnable and job["attempts"] < job["max_attempts"]:
                    status, msg = QUEUED, "interrupted before any model call; queued again"
                else:
                    status, msg = FAILED, ("interrupted before any model call; start it again"
                                           if not runnable else "interrupted; no attempts left")
                hist = self._history(conn, job["job_id"], {"event": "recovered", "to": status, "worker": job["worker"]})
                conn.execute("UPDATE jobs SET status = ?, worker = NULL, lease_until = NULL, bound = 0, message = ?, "
                             "error = ?, run_after = ?, finished_at = ?, updated_at = ?, history_json = ? WHERE job_id = ?",
                             (status, msg, None if status == QUEUED else "server restarted: " + msg, now,
                              now if status in TERMINAL else None, now, hist, job["job_id"]))
                changed.append({"job_id": job["job_id"], "action": status, "message": msg, "kind": job["kind"],
                                "subject": job["subject"]})
            for row in conn.execute("SELECT job_id, owner, handler, kind, subject FROM jobs WHERE status = ? AND bound = 1",
                                    (QUEUED,)).fetchall():
                if alive_worker(row["owner"] or ""):
                    continue
                if row["handler"]:
                    conn.execute("UPDATE jobs SET bound = 0, updated_at = ? WHERE job_id = ?", (now, row["job_id"]))
                    changed.append({"job_id": row["job_id"], "action": "unbound"})
                else:
                    msg = "server restarted before this job started (no model calls were made); start it again"
                    hist = self._history(conn, row["job_id"], {"event": "recovered", "to": FAILED})
                    conn.execute("UPDATE jobs SET status = ?, bound = 0, message = ?, error = ?, finished_at = ?, "
                                 "updated_at = ?, history_json = ? WHERE job_id = ?",
                                 (FAILED, msg, "server restarted: " + msg, now, now, hist, row["job_id"]))
                    changed.append({"job_id": row["job_id"], "action": FAILED, "message": msg, "kind": row["kind"],
                                    "subject": row["subject"]})
        return changed

    def worker_alive_fn(self, stale_after_s: float, conn: Optional[sqlite3.Connection] = None) -> Callable[[str], bool]:
        """A predicate for recover(): a worker is alive when its heartbeat is recent and, on this host, its pid runs.
        With `conn`, the heartbeats are read in that connection's transaction."""
        now = time.time()
        if conn is not None:
            beats = {r["worker"]: dict(r) for r in conn.execute("SELECT * FROM job_workers")}
        else:
            with self._db() as own:
                beats = {r["worker"]: dict(r) for r in own.execute("SELECT * FROM job_workers")}
        host = socket.gethostname()

        def alive(token: str) -> bool:
            if not token:
                return False
            parts = token.split(":")
            if len(parts) >= 3 and parts[0] == host:
                try:
                    # on this host the pid decides: a live process is alive even after a long pause (laptop sleep);
                    # a day without a heartbeat means the pid was reused by something else
                    beat = beats.get(token)
                    return bool(beat and now - float(beat["heartbeat_at"] or 0) < 86400 and _pid_alive(int(parts[1])))
                except ValueError:
                    pass
            beat = beats.get(token)
            return bool(beat and now - float(beat["heartbeat_at"] or 0) <= stale_after_s)
        return alive

    def prune_workers(self, stale_after_s: float) -> None:
        """Forget workers whose heartbeat is long gone and that hold no running job."""
        with self._db(immediate=True) as conn:
            conn.execute("DELETE FROM job_workers WHERE heartbeat_at < ? AND worker NOT IN "
                         "(SELECT worker FROM jobs WHERE status = ? AND worker IS NOT NULL)",
                         (time.time() - max(stale_after_s * 10, 86400), RUNNING))

    # ---------------------------------------------------------------- reads

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as conn:
            return self._row(conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone())

    def list(self, status: Optional[str] = None, kind: Optional[str] = None, workspace: Optional[str] = None,
             subject: Optional[str] = None, limit: int = 100,
             exclude_kind_prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        where, args = [], []
        for col, val in (("status", status), ("kind", kind), ("workspace", workspace), ("subject", subject)):
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        if exclude_kind_prefix:
            where.append("substr(kind, 1, ?) != ?")
            args.extend((len(exclude_kind_prefix), exclude_kind_prefix))
        sql = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(where) if where else "") + \
              " ORDER BY created_at DESC LIMIT ?"
        with self._db() as conn:
            return [self._row(r) for r in conn.execute(sql, (*args, max(1, min(int(limit), 1000))))]

    def active_ids(self) -> Set[str]:
        with self._db() as conn:
            return {r[0] for r in conn.execute(
                f"SELECT job_id FROM jobs WHERE status IN ({','.join('?' * len(ACTIVE))})", ACTIVE)}

    def running_in_lane(self, lane: str) -> int:
        with self._db() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM jobs WHERE status = ? AND lane = ?",
                                    (RUNNING, lane)).fetchone()[0])

    def position(self, job_id: str) -> Optional[int]:
        """1-based place in the queue (same lane), or None when the job is not queued."""
        with self._db() as conn:
            row = conn.execute("SELECT status, lane, priority, created_at FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row or row["status"] != QUEUED:
                return None
            n = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = ? AND lane = ? AND "
                             "(priority > ? OR (priority = ? AND created_at < ?))",
                             (QUEUED, row["lane"], row["priority"], row["priority"], row["created_at"])).fetchone()[0]
        return int(n) + 1

    def stats(self, window_s: float = 3600.0, stale_after_s: float = 120.0) -> Dict[str, Any]:
        """Queue health. `workers` lists live workers only (recent heartbeat, and on this host a running pid)."""
        alive = self.worker_alive_fn(stale_after_s)
        now = time.time()
        with self._db() as conn:
            counts = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")}
            running = {}
            for col in ("provider", "workspace", "lane"):
                running[col] = {r[0]: r[1] for r in conn.execute(
                    f"SELECT {col}, COUNT(*) FROM jobs WHERE status = ? GROUP BY {col}", (RUNNING,))}
            queued = {r[0]: r[1] for r in conn.execute(
                "SELECT lane, COUNT(*) FROM jobs WHERE status = ? GROUP BY lane", (QUEUED,))}
            waits = sorted(r[0] for r in conn.execute(
                "SELECT queue_wait_s FROM jobs WHERE queue_wait_s IS NOT NULL AND first_started_at >= ?",
                (now - window_s,)))
            finished = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = ? AND finished_at >= ?",
                                    (SUCCEEDED, now - window_s)).fetchone()[0]
            oldest = conn.execute("SELECT MIN(created_at) FROM jobs WHERE status = ?", (QUEUED,)).fetchone()[0]
            workers = [dict(r) for r in conn.execute("SELECT worker, host, pid, heartbeat_at, info_json FROM job_workers")]

        def pct(p: float) -> Optional[float]:
            if not waits:
                return None
            return round(waits[min(len(waits) - 1, int(round(p / 100 * (len(waits) - 1))))], 3)
        workers = [w for w in workers if alive(w["worker"])]
        for w in workers:
            w["info"] = json.loads(w.pop("info_json") or "{}")
            w["seconds_since_heartbeat"] = round(now - float(w["heartbeat_at"] or 0), 1)
        return {"counts": {s: int(counts.get(s, 0)) for s in (QUEUED, RUNNING, NEEDS_APPROVAL, SUCCEEDED, FAILED, CANCELLED)},
                "running": running, "queued_by_lane": queued,
                "queue_wait_s": {"p50": pct(50), "p95": pct(95), "max": round(waits[-1], 3) if waits else None,
                                 "n": len(waits), "window_s": window_s},
                "succeeded_in_window": int(finished),
                "oldest_queued_age_s": round(now - oldest, 1) if oldest else None,
                "workers": workers}

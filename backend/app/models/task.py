"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
"""

import json
import logging
import os
import sqlite3
import uuid
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, Iterator, List, Optional
from dataclasses import dataclass, field

from ..utils.locale import t

logger = logging.getLogger("mirofish.tasks")

SERVER_RESTARTED_ERROR = "server restarted"

_COLUMNS = (
    "task_id, task_type, status, created_at, updated_at, progress, message, "
    "result_json, error, metadata_json, progress_detail_json"
)


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待中
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0              # 总进度百分比 0-100
    message: str = ""              # 状态消息
    result: Optional[Dict] = None  # 任务结果
    error: Optional[str] = None    # 错误信息
    metadata: Dict = field(default_factory=dict)  # 额外元数据
    progress_detail: Dict = field(default_factory=dict)  # 详细进度信息

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "message": self.message,
            "progress_detail": self.progress_detail,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


class TaskManager:
    """
    Thread-safe task registry backed by SQLite.

    * Tasks created by this process ("owned" tasks) live in ``_tasks`` and are
      updated in place; every change is also written to SQLite.
    * Rows this process did not create are read from SQLite on every lookup and
      never cached, so a reader always sees the owner's latest write instead of
      a frozen snapshot.
    * SQLite I/O never happens while ``_task_lock`` (the registry lock) is held.
      ``_write_lock`` orders writes so an older snapshot cannot overwrite a newer one.
    * The schema is created lazily, once per database path (``MM_TASK_DB_PATH``).
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._tasks: Dict[str, Task] = {}
                    inst._task_lock = threading.Lock()
                    inst._write_lock = threading.Lock()
                    inst._schema_lock = threading.Lock()
                    inst._schema_ready: set = set()
                    cls._instance = inst
        return cls._instance

    # ------------------------------------------------------------------ storage

    def _db_path(self) -> str:
        custom = os.environ.get("MM_TASK_DB_PATH")
        if custom:
            os.makedirs(os.path.dirname(os.path.abspath(custom)), exist_ok=True)
            return custom
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../uploads"))
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "tasks.sqlite")

    def _ensure_schema(self, conn: sqlite3.Connection, path: str) -> None:
        if path in self._schema_ready:
            return
        with self._schema_lock:
            if path in self._schema_ready:
                return
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    progress INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    result_json TEXT,
                    error TEXT,
                    metadata_json TEXT,
                    progress_detail_json TEXT
                )
                """
            )
            conn.commit()
            self._schema_ready.add(path)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """Open a connection (schema ensured), commit on success, always close it."""
        path = self._db_path()
        conn = sqlite3.connect(path, timeout=10)
        try:
            self._ensure_schema(conn, path)
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create the table for the current path now (it is otherwise created on first use)."""
        try:
            with self._db():
                pass
        except Exception:
            logger.exception("task store: cannot initialise the task database")

    @staticmethod
    def _row_values(task: Task) -> tuple:
        return (
            task.task_id,
            task.task_type,
            task.status.value,
            task.created_at.isoformat(),
            task.updated_at.isoformat(),
            int(task.progress or 0),
            str(task.message or ""),
            json.dumps(task.result, ensure_ascii=False, default=str) if task.result is not None else None,
            task.error,
            json.dumps(task.metadata or {}, ensure_ascii=False, default=str),
            json.dumps(task.progress_detail or {}, ensure_ascii=False, default=str),
        )

    def _write_row(self, values: tuple) -> None:
        try:
            with self._db() as conn:
                conn.execute(
                    f"INSERT OR REPLACE INTO tasks ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
        except Exception:
            logger.exception("task store: cannot save task %s", values[0])

    def _save_to_db(self, task: Task) -> None:
        """Persist one task: snapshot under the registry lock, I/O outside it, writes ordered."""
        with self._write_lock:
            with self._task_lock:
                values = self._row_values(task)
            self._write_row(values)

    def _row_to_task(self, row: tuple) -> Task:
        (tid, ttype, st, c_at, u_at, prog, msg, res_j, err, meta_j, det_j) = row
        return Task(
            task_id=tid,
            task_type=ttype,
            status=TaskStatus(st) if st in TaskStatus._value2member_map_ else TaskStatus.PENDING,
            created_at=datetime.fromisoformat(c_at),
            updated_at=datetime.fromisoformat(u_at),
            progress=int(prog or 0),
            message=msg or "",
            result=json.loads(res_j) if res_j else None,
            error=err,
            metadata=json.loads(meta_j) if meta_j else {},
            progress_detail=json.loads(det_j) if det_j else {},
        )

    def _load_row(self, task_id: str) -> Optional[Task]:
        try:
            with self._db() as conn:
                row = conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        except Exception:
            logger.exception("task store: cannot read task %s", task_id)
            return None
        if not row:
            return None
        try:
            return self._row_to_task(row)
        except Exception:
            logger.exception("task store: corrupt row for task %s", task_id)
            return None

    def _load_rows(self, task_type: Optional[str] = None) -> List[Task]:
        try:
            with self._db() as conn:
                if task_type:
                    rows = conn.execute(f"SELECT {_COLUMNS} FROM tasks WHERE task_type = ?", (task_type,)).fetchall()
                else:
                    rows = conn.execute(f"SELECT {_COLUMNS} FROM tasks").fetchall()
        except Exception:
            logger.exception("task store: cannot list tasks")
            return []
        tasks: List[Task] = []
        for row in rows:
            try:
                tasks.append(self._row_to_task(row))
            except Exception:
                logger.exception("task store: skipping corrupt row %s", row[0] if row else "?")
        return tasks

    # ------------------------------------------------------------------ lifecycle

    def recover_interrupted_tasks(self) -> int:
        """
        Mark pending/processing rows that this process does not own as failed
        ("server restarted"). Called once at server start-up: the backend runs as
        a single process, so such a row was left behind by a process that died
        or was stopped, and nothing will ever finish it.
        """
        with self._task_lock:
            owned = set(self._tasks)
        now = datetime.now().isoformat()
        active = (TaskStatus.PENDING.value, TaskStatus.PROCESSING.value)
        try:
            with self._write_lock, self._db() as conn:
                rows = conn.execute("SELECT task_id FROM tasks WHERE status IN (?, ?)", active).fetchall()
                stale = [r[0] for r in rows if r[0] not in owned]
                conn.executemany(
                    "UPDATE tasks SET status = ?, error = ?, message = ?, updated_at = ? "
                    "WHERE task_id = ? AND status IN (?, ?)",
                    [
                        (TaskStatus.FAILED.value, SERVER_RESTARTED_ERROR, t('progress.taskFailed'), now, tid, *active)
                        for tid in stale
                    ],
                )
        except Exception:
            logger.exception("task store: cannot recover interrupted tasks")
            return 0
        if stale:
            logger.warning("task store: marked %d interrupted task(s) as failed (server restarted)", len(stale))
        return len(stale)

    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        """
        创建新任务（由本进程持有）

        Args:
            task_type: 任务类型
            metadata: 额外元数据

        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        now = datetime.now()
        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        with self._task_lock:
            self._tasks[task_id] = task
        self._save_to_db(task)
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """Owned tasks come from memory; any other task is read fresh from SQLite and not cached."""
        with self._task_lock:
            task = self._tasks.get(task_id)
        if task is not None:
            return task
        return self._load_row(task_id)

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        progress_detail: Optional[Dict] = None
    ):
        """
        更新任务状态（仅限本进程持有的任务；其他任务的更新会被忽略并记录日志）

        Args:
            task_id: 任务ID
            status: 新状态
            progress: 进度
            message: 消息
            result: 结果
            error: 错误信息
            progress_detail: 详细进度信息
        """
        with self._write_lock:
            with self._task_lock:
                task = self._tasks.get(task_id)
                if task is None:
                    logger.warning("task store: update for unknown or foreign task %s ignored", task_id)
                    return
                task.updated_at = datetime.now()
                if status is not None:
                    task.status = status
                if progress is not None:
                    task.progress = progress
                if message is not None:
                    task.message = message
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                if progress_detail is not None:
                    task.progress_detail = progress_detail
                values = self._row_values(task)
            self._write_row(values)

    def complete_task(self, task_id: str, result: Dict):
        """标记任务完成"""
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message=t('progress.taskComplete'),
            result=result
        )

    def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message=t('progress.taskFailed'),
            error=error
        )

    def list_tasks(self, task_type: Optional[str] = None) -> list:
        """List tasks, newest first: persisted rows overlaid with the live owned tasks (the get_task view)."""
        merged: Dict[str, Task] = {task.task_id: task for task in self._load_rows(task_type)}
        with self._task_lock:
            for task in self._tasks.values():
                if not task_type or task.task_type == task_type:
                    merged[task.task_id] = task
            ordered = sorted(merged.values(), key=lambda x: x.created_at, reverse=True)
            return [task.to_dict() for task in ordered]

    def count_by_status(self) -> Dict[str, int]:
        """Task counts per status, from SQLite (falls back to the owned tasks if it cannot be read)."""
        counts = {status.value: 0 for status in TaskStatus}
        try:
            with self._db() as conn:
                for status, n in conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status"):
                    counts[status] = counts.get(status, 0) + int(n)
            return counts
        except Exception:
            logger.exception("task store: cannot count tasks")
        with self._task_lock:
            for task in self._tasks.values():
                counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return counts

    def store_healthy(self) -> bool:
        """True when the task database can be opened and queried."""
        try:
            with self._db() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            logger.exception("task store: health check failed")
            return False

    def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        """Delete finished (completed/failed) tasks older than max_age_hours from memory and SQLite."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        finished = (TaskStatus.COMPLETED, TaskStatus.FAILED)
        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in finished
            ]
            for tid in old_ids:
                del self._tasks[tid]
        deleted = 0
        try:
            with self._write_lock, self._db() as conn:
                cur = conn.execute(
                    "DELETE FROM tasks WHERE created_at < ? AND status IN (?, ?)",
                    (cutoff.isoformat(), TaskStatus.COMPLETED.value, TaskStatus.FAILED.value),
                )
                deleted = max(0, cur.rowcount or 0)
        except Exception:
            logger.exception("task store: cannot delete old tasks")
        return max(deleted, len(old_ids))

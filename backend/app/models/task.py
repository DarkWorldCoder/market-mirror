"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
"""

import json
import os
import sqlite3
import uuid
import threading
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from ..utils.locale import t


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
    任务管理器
    线程安全的任务状态管理
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, Task] = {}
                    cls._instance._task_lock = threading.Lock()
                    cls._instance._init_db()
        return cls._instance

    def _db_path(self) -> str:
        custom = os.environ.get("MM_TASK_DB_PATH")
        if custom:
            return custom
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../uploads"))
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, "tasks.sqlite")

    def _init_db(self) -> None:
        try:
            path = self._db_path()
            with sqlite3.connect(path, timeout=10) as conn:
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
        except Exception:
            pass

    def _save_to_db(self, task: Task) -> None:
        try:
            with sqlite3.connect(self._db_path(), timeout=10) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO tasks
                    (task_id, task_type, status, created_at, updated_at, progress, message,
                     result_json, error, metadata_json, progress_detail_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
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
                    ),
                )
        except Exception:
            pass

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
    
    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        """
        创建新任务
        
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
            metadata=metadata or {}
        )
        
        with self._task_lock:
            self._tasks[task_id] = task
            self._save_to_db(task)
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task is not None:
                return task
            try:
                with sqlite3.connect(self._db_path(), timeout=10) as conn:
                    row = conn.execute(
                        "SELECT task_id, task_type, status, created_at, updated_at, progress, message, "
                        "result_json, error, metadata_json, progress_detail_json FROM tasks WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()
                if row:
                    task = self._row_to_task(row)
                    self._tasks[task_id] = task
                    return task
            except Exception:
                pass
            return None
    
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
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            progress: 进度
            message: 消息
            result: 结果
            error: 错误信息
            progress_detail: 详细进度信息
        """
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
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
                self._save_to_db(task)
    
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
        """列出任务"""
        with self._task_lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [t for t in tasks if t.task_type == task_type]
            return [t.to_dict() for t in sorted(tasks, key=lambda x: x.created_at, reverse=True)]
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        with self._task_lock:
            old_ids = [
                tid for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                del self._tasks[tid]


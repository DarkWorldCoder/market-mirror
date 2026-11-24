"""The workspace database: SQLite by default, Postgres with MM_DATABASE_URL=postgresql://...

One small DB-API wrapper serves both. SQL is written with `?` placeholders and portable types (see
migrations/); for Postgres the placeholders are rewritten to `%s`. Every unit of work runs in `transaction()`,
which takes a write lock up front on SQLite (BEGIN IMMEDIATE) so read-check-write sequences cannot interleave.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlsplit

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_MIGRATION_FILE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_LOCK = threading.Lock()
_READY: Dict[str, "Database"] = {}


class MigrationError(RuntimeError):
    pass


def now_ms() -> int:
    return int(time.time() * 1000)


def database_url() -> str:
    configured = os.environ.get("MM_DATABASE_URL", "").strip()
    if configured:
        return configured
    from .. import config  # read at call time: tests point UPLOAD_ROOT at a temporary folder
    return "sqlite:///" + os.path.join(config.UPLOAD_ROOT, "marketmirror.db")


class Connection:
    """Rows come back as dicts on both engines."""

    def __init__(self, raw, dialect: str):
        self.raw, self.dialect = raw, dialect

    def execute(self, sql: str, params=()):
        if self.dialect == "postgres":
            sql = sql.replace("?", "%s")
        return self.raw.execute(sql, tuple(params))

    def one(self, sql: str, params=()) -> Optional[Dict[str, Any]]:
        row = self.execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def all(self, sql: str, params=()) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.execute(sql, params).fetchall()]

    def scalar(self, sql: str, params=()):
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None


class Database:
    def __init__(self, url: str):
        self.url = url
        parsed = urlsplit(url)
        if parsed.scheme == "sqlite":
            self.dialect = "sqlite"
            self.path = url[len("sqlite:///"):] if url.startswith("sqlite:///") else parsed.path
            if not self.path:
                raise ValueError("MM_DATABASE_URL needs a file path, for example sqlite:////srv/mm/marketmirror.db")
        elif parsed.scheme in ("postgres", "postgresql"):
            self.dialect = "postgres"
            self.path = None
        else:
            raise ValueError("MM_DATABASE_URL must start with sqlite:/// or postgresql://")

    def _open(self):
        if self.dialect == "sqlite":
            path = Path(self.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            fresh = not path.exists()
            raw = sqlite3.connect(str(path), timeout=15, isolation_level=None, check_same_thread=False)
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys=ON")
            raw.execute("PRAGMA busy_timeout=15000")
            if fresh:
                raw.execute("PRAGMA journal_mode=WAL")
                os.chmod(path, 0o600)
            return raw
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on the optional driver
            raise RuntimeError('Postgres needs the psycopg driver: uv pip install "psycopg[binary]"') from exc
        return psycopg.connect(self.url, row_factory=dict_row, autocommit=True)

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        raw = self._open()
        conn = Connection(raw, self.dialect)
        try:
            raw.execute("BEGIN IMMEDIATE" if self.dialect == "sqlite" else "BEGIN")
            try:
                yield conn
            except BaseException:
                raw.execute("ROLLBACK")
                raise
            raw.execute("COMMIT")
        finally:
            raw.close()

    # ------------------------------------------------------------------ migrations

    def migrations(self) -> List[Dict[str, str]]:
        found = []
        for path in sorted(MIGRATIONS.glob("*.sql")):
            match = _MIGRATION_FILE.match(path.name)
            if not match:
                continue
            sql = path.read_text(encoding="utf-8")
            found.append({"version": match.group(1), "name": match.group(2), "sql": sql,
                          "checksum": hashlib.sha256(sql.encode("utf-8")).hexdigest()})
        return found

    def applied(self) -> Dict[str, Dict[str, Any]]:
        with self.transaction() as conn:
            self._ensure_table(conn)
            return {row["version"]: row for row in conn.all("SELECT * FROM schema_migrations ORDER BY version")}

    @staticmethod
    def _ensure_table(conn: Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, name TEXT NOT NULL, "
                     "checksum TEXT NOT NULL, applied_at BIGINT NOT NULL)")

    def migrate(self) -> List[str]:
        """Apply pending migrations in order, each in its own transaction. Returns the versions applied."""
        done: List[str] = []
        for migration in self.migrations():
            with self.transaction() as conn:
                if self.dialect == "postgres":
                    conn.execute("SELECT pg_advisory_xact_lock(727274001)")
                self._ensure_table(conn)
                row = conn.one("SELECT checksum FROM schema_migrations WHERE version=?", (migration["version"],))
                if row:
                    if row["checksum"] != migration["checksum"]:
                        raise MigrationError(
                            f"Migration {migration['version']}_{migration['name']} changed after it was applied. "
                            "Add a new migration instead of editing an applied one.")
                    continue
                for statement in _statements(migration["sql"]):
                    conn.execute(statement)
                conn.execute("INSERT INTO schema_migrations (version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                             (migration["version"], migration["name"], migration["checksum"], now_ms()))
                done.append(migration["version"])
        return done


def _statements(sql: str) -> List[str]:
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


def get_db() -> Database:
    """The migrated database for the current MM_DATABASE_URL (or the upload folder's SQLite file)."""
    url = database_url()
    db = _READY.get(url)
    if db is not None and (db.dialect != "sqlite" or os.path.exists(db.path)):
        return db
    with _LOCK:
        db = _READY.get(url)
        if db is None or (db.dialect == "sqlite" and not os.path.exists(db.path)):
            db = Database(url)
            db.migrate()
            from . import repo
            repo.ensure_local_workspace(db)
            _READY[url] = db
    return db


def reset_cache() -> None:
    with _LOCK:
        _READY.clear()

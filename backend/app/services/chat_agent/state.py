"""Pending approvals and per-chat session memory, kept in this process.

A pending approval holds everything needed to resume the turn exactly: the paused call, calls queued after it and
the model conversation so far. A server restart drops them; the user then sends the message again.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Dict, Optional

PENDING_TTL = 2 * 3600
SESSION_TTL = 24 * 3600
MAX_PENDING = 200
MAX_SESSIONS = 500

_LOCK = threading.Lock()
_PENDING: Dict[str, Dict[str, Any]] = {}
_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _prune(now: float) -> None:
    for key in [k for k, v in _PENDING.items() if now - v["created"] > PENDING_TTL]:
        _PENDING.pop(key, None)
    while len(_PENDING) > MAX_PENDING:
        _PENDING.pop(min(_PENDING, key=lambda k: _PENDING[k]["created"]))
    for key in [k for k, v in _SESSIONS.items() if now - v["updated"] > SESSION_TTL]:
        _SESSIONS.pop(key, None)
    while len(_SESSIONS) > MAX_SESSIONS:
        _SESSIONS.pop(min(_SESSIONS, key=lambda k: _SESSIONS[k]["updated"]))


def session(session_id: str) -> Dict[str, Any]:
    now = time.time()
    with _LOCK:
        _prune(now)
        s = _SESSIONS.setdefault(session_id, {"outside_ok": set(), "audience": None, "product": None,
                                              "understood": False, "updated": now})
        s["updated"] = now
        return s


def save_pending(session_id: str, record: Dict[str, Any]) -> str:
    pid = "ap_" + secrets.token_hex(8)
    with _LOCK:
        _prune(time.time())
        _PENDING[pid] = {**record, "session_id": session_id, "created": time.time()}
    return pid


def take_pending(pid: Any, session_id: str) -> Dict[str, Any]:
    """Remove and return a pending approval of this chat; each approval is answered once."""
    with _LOCK:
        _prune(time.time())
        record = _PENDING.get(pid) if isinstance(pid, str) else None
        if not record or record["session_id"] != session_id:
            raise ValueError("This approval has expired or was already answered. Send your message again.")
        return _PENDING.pop(pid)


def peek_pending(pid: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        return _PENDING.get(pid)


def reset() -> None:
    with _LOCK:
        _PENDING.clear()
        _SESSIONS.clear()

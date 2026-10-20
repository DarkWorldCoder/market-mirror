"""
production.py - Production Deployment Middleware, Security, Rate Limiting & Observability.

Features:
1. API Authentication (`MM_API_AUTH_TOKEN` / `API_AUTH_TOKEN`):
   - Optional Bearer / `X-API-Key` authentication on `/api/*` and `/metrics` using constant-time comparison.
   - Zero-friction in local development when unset.
2. Sliding-Window Rate Limiter (`MM_RATE_LIMIT_RPM`):
   - Per-IP rate limiting on `/api/*` with `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After` headers.
3. Request Correlation IDs (`X-Request-ID`), Latency Timing (`X-Response-Time-Ms`), and Security Headers.
4. Reverse Proxy Support (`TRUST_PROXY_HEADERS=1` via Werkzeug `ProxyFix`).
5. Production Readiness (`/ready`), Liveness (`/health`), System Diagnostics (`/api/system/status`),
   and Prometheus Metrics (`/metrics`) endpoints.
"""

from __future__ import annotations

import collections
import hmac
import math
import os
import platform
import shutil
import threading
import time
import uuid
from typing import Any, Deque, Dict, List, Optional

from flask import Flask, g, jsonify, request, Response

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from .logger import get_logger

logger = get_logger("mirofish.production")

VERSION = "2.0.0"
_BOOT_TIME = time.time()
_METRICS_LOCK = threading.Lock()
_REQUEST_COUNTS: Dict[str, int] = collections.Counter()
_STATUS_COUNTS: Dict[int, int] = collections.Counter()
_LATENCIES_MS: Deque[float] = collections.deque(maxlen=2000)

_RATE_LOCK = threading.Lock()
_RATE_WINDOWS: Dict[str, Deque[float]] = {}


def _auth_token(app: Flask) -> str:
    return str(
        app.config.get("MM_API_AUTH_TOKEN")
        or os.environ.get("MM_API_AUTH_TOKEN")
        or os.environ.get("API_AUTH_TOKEN")
        or ""
    ).strip()


def _rate_limit_rpm(app: Flask) -> int:
    raw = app.config.get("MM_RATE_LIMIT_RPM")
    if raw is None:
        raw = os.environ.get("MM_RATE_LIMIT_RPM", "0")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def _check_auth(expected_token: str) -> bool:
    auth_header = request.headers.get("Authorization", "").strip()
    candidate = ""
    if auth_header.lower().startswith("bearer "):
        candidate = auth_header[7:].strip()
    if not candidate:
        candidate = request.headers.get("X-API-Key", "").strip()
    if not candidate:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected_token.encode("utf-8"))


def _check_rate_limit(ip: str, rpm: int) -> tuple[bool, int, int]:
    """Return (allowed, remaining, retry_after_s)."""
    now = time.monotonic()
    window_start = now - 60.0
    with _RATE_LOCK:
        dq = _RATE_WINDOWS.get(ip)
        if dq is None:
            dq = collections.deque()
            _RATE_WINDOWS[ip] = dq
        while dq and dq[0] < window_start:
            dq.popleft()
        if len(dq) >= rpm:
            retry_after = max(1, int(math.ceil(60.0 - (now - dq[0]))))
            return False, 0, retry_after
        dq.append(now)
        return True, max(0, rpm - len(dq)), 0


def _percentile(vals: List[float], pct: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = min(len(s) - 1, max(0, int(round((pct / 100.0) * (len(s) - 1)))))
    return round(s[idx], 2)


def readiness_report() -> Dict[str, Any]:
    """Run deep readiness checks on storage directories, task SQLite store, and LLM provider configuration."""
    checks: Dict[str, Any] = {}
    ok = True

    # 1. Storage writeability
    for label, folder in (("upload_folder", Config.UPLOAD_FOLDER), ("simulation_data_dir", Config.OASIS_SIMULATION_DATA_DIR)):
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, f".ready_probe_{uuid.uuid4().hex[:8]}")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            usage = shutil.disk_usage(folder)
            checks[label] = {"ok": True, "free_mb": round(usage.free / (1024 * 1024), 1)}
        except Exception as e:
            checks[label] = {"ok": False, "error": str(e)}
            ok = False

    # 2. Task store SQLite health
    try:
        tm = TaskManager()
        db_path = tm._db_path()
        checks["task_store"] = {"ok": os.path.exists(db_path), "db_path": db_path, "cached_tasks": len(tm.list_tasks())}
    except Exception as e:
        checks["task_store"] = {"ok": False, "error": str(e)}

    # 3. LLM Provider / MultiProviderPool readiness
    try:
        pool = Config.get_model_pool()
        has_key = bool(Config.LLM_API_KEY or Config.LLM_POOL or len(pool.slots) > 0)
        checks["llm"] = {
            "configured": has_key,
            "provider": Config.LLM_PROVIDER,
            "model": Config.LLM_MODEL_NAME,
            "pool_size": len(pool.slots),
            "pool": pool.summary() if pool.slots else None,
        }
    except Exception as e:
        checks["llm"] = {"configured": False, "error": str(e)}

    return {
        "status": "ready" if ok else "degraded",
        "ready": ok,
        "version": VERSION,
        "uptime_seconds": round(time.time() - _BOOT_TIME, 1),
        "checks": checks,
    }


def system_status_report() -> Dict[str, Any]:
    """Detailed production telemetry for `/api/system/status`."""
    ready = readiness_report()
    tm = TaskManager()
    all_tasks = tm.list_tasks()
    by_status = collections.Counter(t.get("status") for t in all_tasks)
    with _METRICS_LOCK:
        lats = list(_LATENCIES_MS)
        total_reqs = sum(_REQUEST_COUNTS.values())
        err_reqs = sum(c for code, c in _STATUS_COUNTS.items() if code >= 500)
        status_map = {str(k): v for k, v in sorted(_STATUS_COUNTS.items())}
    return {
        **ready,
        "environment": os.environ.get("MM_ENV", "development"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "http": {
            "requests_total": total_reqs,
            "errors_5xx": err_reqs,
            "status_codes": status_map,
            "latency_p50_ms": _percentile(lats, 50),
            "latency_p95_ms": _percentile(lats, 95),
        },
        "tasks": {
            "total": len(all_tasks),
            "pending": by_status.get(TaskStatus.PENDING.value, 0),
            "processing": by_status.get(TaskStatus.PROCESSING.value, 0),
            "completed": by_status.get(TaskStatus.COMPLETED.value, 0),
            "failed": by_status.get(TaskStatus.FAILED.value, 0),
        },
    }


def prometheus_metrics_text() -> str:
    """Prometheus text exposition format for `/metrics`."""
    rep = system_status_report()
    lines = [
        "# HELP marketmirror_uptime_seconds Process uptime in seconds",
        "# TYPE marketmirror_uptime_seconds gauge",
        f'marketmirror_uptime_seconds {rep["uptime_seconds"]}',
        "# HELP marketmirror_ready Readiness state (1 = ready, 0 = degraded)",
        "# TYPE marketmirror_ready gauge",
        f'marketmirror_ready {1 if rep["ready"] else 0}',
        "# HELP marketmirror_http_requests_total Total HTTP requests handled",
        "# TYPE marketmirror_http_requests_total counter",
        f'marketmirror_http_requests_total {rep["http"]["requests_total"]}',
        "# HELP marketmirror_http_errors_total Total HTTP 5xx responses",
        "# TYPE marketmirror_http_errors_total counter",
        f'marketmirror_http_errors_total {rep["http"]["errors_5xx"]}',
        "# HELP marketmirror_http_latency_p95_ms 95th percentile HTTP latency in ms",
        "# TYPE marketmirror_http_latency_p95_ms gauge",
        f'marketmirror_http_latency_p95_ms {rep["http"]["latency_p95_ms"]}',
        "# HELP marketmirror_tasks_count Tasks by status",
        "# TYPE marketmirror_tasks_count gauge",
    ]
    for st in ("pending", "processing", "completed", "failed"):
        lines.append(f'marketmirror_tasks_count{{status="{st}"}} {rep["tasks"].get(st, 0)}')
    pool_info = (rep.get("checks", {}).get("llm") or {}).get("pool") or {}
    slots = pool_info.get("slots") or []
    if slots:
        lines.append("# HELP marketmirror_llm_pool_calls_total Total calls per LLM pool slot")
        lines.append("# TYPE marketmirror_llm_pool_calls_total counter")
        for s in slots:
            prov = s.get("provider", "unknown")
            mod = s.get("model", "unknown")
            lines.append(f'marketmirror_llm_pool_calls_total{{provider="{prov}",model="{mod}"}} {int(s.get("calls") or 0)}')
    return "\n".join(lines) + "\n"


def install_production_middleware(app: Flask) -> None:
    """Attach production auth, rate-limiting, request IDs, security headers, error handlers, and probes."""
    if os.environ.get("TRUST_PROXY_HEADERS", "").lower() in ("1", "true", "yes"):
        try:
            from werkzeug.middleware.proxy_fix import ProxyFix
            app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)  # type: ignore[assignment]
        except ImportError:
            pass

    @app.before_request
    def _prod_before_request():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        g.request_start_time = time.monotonic()

        # Public probes bypass auth & rate limits
        if request.path in ("/health", "/ready") or request.method == "OPTIONS":
            return None

        # 1. Optional API Key / Bearer Token Authentication
        expected = _auth_token(app)
        if expected and (request.path.startswith("/api/") or request.path == "/metrics"):
            if not _check_auth(expected):
                return jsonify({
                    "success": False,
                    "error": "Unauthorized: valid API key or Bearer token required",
                    "request_id": g.request_id,
                }), 401

        # 2. Optional Per-IP Rate Limiting
        rpm = _rate_limit_rpm(app)
        if rpm > 0 and request.path.startswith("/api/"):
            allowed, remaining, retry_after = _check_rate_limit(_client_ip(), rpm)
            g.rate_limit_rpm = rpm
            g.rate_limit_remaining = remaining
            if not allowed:
                resp = jsonify({
                    "success": False,
                    "error": f"Rate limit exceeded ({rpm} requests/minute)",
                    "retry_after_seconds": retry_after,
                    "request_id": g.request_id,
                })
                resp.status_code = 429
                resp.headers["Retry-After"] = str(retry_after)
                resp.headers["X-RateLimit-Limit"] = str(rpm)
                resp.headers["X-RateLimit-Remaining"] = "0"
                return resp
        return None

    @app.after_request
    def _prod_after_request(response: Response) -> Response:
        req_id = getattr(g, "request_id", None)
        if req_id:
            response.headers["X-Request-ID"] = str(req_id)
        started = getattr(g, "request_start_time", None)
        if started is not None:
            elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
            response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
            with _METRICS_LOCK:
                _LATENCIES_MS.append(elapsed_ms)
                _REQUEST_COUNTS[f"{request.method} {request.path}"] += 1
                _STATUS_COUNTS[response.status_code] += 1
        if hasattr(g, "rate_limit_rpm"):
            response.headers.setdefault("X-RateLimit-Limit", str(g.rate_limit_rpm))
            response.headers.setdefault("X-RateLimit-Remaining", str(getattr(g, "rate_limit_remaining", 0)))

        # Production security headers
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.errorhandler(413)
    def _handle_413(_err):
        return jsonify({"success": False, "error": "Payload too large (exceeds MAX_CONTENT_LENGTH)", "request_id": getattr(g, "request_id", None)}), 413

    @app.errorhandler(500)
    def _handle_500(err):
        logger.error(f"Unhandled 500 error [req={getattr(g, 'request_id', '?')}]: {err}")
        return jsonify({"success": False, "error": "Internal server error", "request_id": getattr(g, "request_id", None)}), 500

    @app.route("/ready", methods=["GET"])
    def ready_probe():
        rep = readiness_report()
        return jsonify(rep), (200 if rep["ready"] else 503)

    @app.route("/api/system/status", methods=["GET"])
    def api_system_status():
        return jsonify({"success": True, "data": system_status_report()})

    @app.route("/metrics", methods=["GET"])
    def prometheus_metrics():
        return Response(prometheus_metrics_text(), mimetype="text/plain; version=0.0.4; charset=utf-8")
